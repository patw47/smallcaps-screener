"""
model.py — Modèle de score v3 : régression logistique L2 + calibration isotonic (Epic 3 S3).

Volontairement MINIMAL et interprétable (protocole v3 §4) : numpy seul, aucune dépendance
sklearn/scipy ajoutée à un projet à 5 deps. La CLASSE DE MODÈLE est gelée au protocole —
ne pas substituer un modèle plus flexible sans révision (c'est ainsi qu'on pêche l'overfit).

- `LogisticL2` : IRLS (Newton-Raphson) avec pénalité ridge sur les poids (pas l'intercept).
  Converge en < 10 itérations sur des features standardisées ; peu de features → système
  linéaire minuscule résolu par `numpy.linalg.solve`.
- `Isotonic` : recalibration monotone (pool-adjacent-violators) des probabilités prédites.
- `ScoreModel` : logistique + calibrateur + noms de features, sérialisable en JSON. La PROD
  charge un modèle entraîné UNE FOIS par l'étude (S5) ; aucune ré-estimation en ligne.

Auto-vérification exécutable : `python3 backend/model.py`.
"""
from __future__ import annotations

import json
import numpy as np


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30.0, 30.0)))


class LogisticL2:
    """Régression logistique à pénalité L2, ajustée par IRLS (Newton pondéré)."""

    def __init__(self, lam: float = 1.0, max_iter: int = 50, tol: float = 1e-9):
        self.lam = float(lam)
        self.max_iter = int(max_iter)
        self.tol = float(tol)
        self.coef_: np.ndarray | None = None  # [intercept, w1..wd]

    def fit(self, X, y) -> "LogisticL2":
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float).ravel()
        n, d = X.shape
        Xb = np.hstack([np.ones((n, 1)), X])
        w = np.zeros(d + 1)
        ridge = self.lam * np.eye(d + 1)
        ridge[0, 0] = 0.0  # jamais de pénalité sur l'intercept
        for _ in range(self.max_iter):
            p = _sigmoid(Xb @ w)
            grad = Xb.T @ (p - y) + ridge @ w
            S = p * (1.0 - p)
            H = (Xb.T * S) @ Xb + ridge
            try:
                step = np.linalg.solve(H, grad)
            except np.linalg.LinAlgError:
                step = np.linalg.lstsq(H, grad, rcond=None)[0]
            w = w - step
            if np.max(np.abs(step)) < self.tol:
                break
        self.coef_ = w
        return self

    def decision(self, X) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        Xb = np.hstack([np.ones((X.shape[0], 1)), X])
        return Xb @ self.coef_

    def predict_proba(self, X) -> np.ndarray:
        return _sigmoid(self.decision(X))


class Isotonic:
    """Calibration isotonic croissante (pool-adjacent-violators)."""

    def __init__(self):
        self.x_: np.ndarray | None = None  # bornes droites des blocs (prédictions triées)
        self.y_: np.ndarray | None = None  # valeur calibrée du bloc (moyenne des labels)

    def fit(self, p, y) -> "Isotonic":
        p = np.asarray(p, dtype=float).ravel()
        y = np.asarray(y, dtype=float).ravel()
        order = np.argsort(p, kind="mergesort")
        xs, ys = p[order], y[order]
        val: list[float] = []
        wt: list[float] = []
        xr: list[float] = []
        for xi, yi in zip(xs, ys):
            val.append(float(yi))
            wt.append(1.0)
            xr.append(float(xi))
            while len(val) > 1 and val[-2] > val[-1]:  # violation → fusionne les 2 derniers blocs
                w2 = wt[-1] + wt[-2]
                val[-2] = (val[-1] * wt[-1] + val[-2] * wt[-2]) / w2
                wt[-2] = w2
                xr[-2] = xr[-1]
                val.pop()
                wt.pop()
                xr.pop()
        self.x_ = np.array(xr) if xr else np.array([0.0, 1.0])
        self.y_ = np.array(val) if val else np.array([0.0, 1.0])
        return self

    def predict(self, p) -> np.ndarray:
        p = np.asarray(p, dtype=float).ravel()
        if self.x_ is None or len(self.x_) == 1:  # bloc unique → constante
            return np.full_like(p, self.y_[0] if self.y_ is not None else 0.0)
        return np.interp(p, self.x_, self.y_)  # monotone, clampé aux bornes hors domaine


class ScoreModel:
    """Logistique L2 + calibrateur isotonic + noms de features. Sérialisable JSON."""

    def __init__(self, feature_names: list[str], lam: float = 1.0):
        self.feature_names = list(feature_names)
        self.logit = LogisticL2(lam=lam)
        self.iso = Isotonic()
        self.fitted = False

    def fit(self, X, y) -> "ScoreModel":
        X = np.asarray(X, dtype=float)
        self.logit.fit(X, y)
        self.iso.fit(self.logit.predict_proba(X), y)
        self.fitted = True
        return self

    def predict_proba(self, X) -> np.ndarray:
        return self.iso.predict(self.logit.predict_proba(X))

    def to_json(self) -> str:
        return json.dumps({
            "feature_names": self.feature_names,
            "coef": self.logit.coef_.tolist(),
            "iso_x": self.iso.x_.tolist(),
            "iso_y": self.iso.y_.tolist(),
            "lam": self.logit.lam,
        })

    @classmethod
    def from_json(cls, text: str) -> "ScoreModel":
        d = json.loads(text)
        m = cls(d["feature_names"], lam=d.get("lam", 1.0))
        m.logit.coef_ = np.array(d["coef"], dtype=float)
        m.iso.x_ = np.array(d["iso_x"], dtype=float)
        m.iso.y_ = np.array(d["iso_y"], dtype=float)
        m.fitted = True
        return m


def _demo() -> None:
    """Auto-vérification : correction du logistique, de l'isotonic et du round-trip JSON."""
    rng = np.random.default_rng(0)
    n, d = 4000, 3
    X = rng.normal(size=(n, d))
    w_true = np.array([1.5, -2.0, 0.5])
    p = _sigmoid(X @ w_true - 0.3)
    y = (rng.uniform(size=n) < p).astype(float)

    # 1) le logistique récupère le signe et l'ordre de grandeur des poids vrais
    m = LogisticL2(lam=1.0).fit(X, y)
    est = m.coef_[1:]
    assert np.sign(est[0]) == 1 and np.sign(est[1]) == -1, est
    assert abs(est[0]) > abs(est[2]) and abs(est[1]) > abs(est[2]), est

    # 2) L2 rétrécit : lam énorme → poids ~0
    m_big = LogisticL2(lam=1e6).fit(X, y)
    assert np.max(np.abs(m_big.coef_[1:])) < 0.05, m_big.coef_

    # 3) isotonic monotone + baisse le Brier sur des probas mal calibrées (sur-confiantes)
    p_raw = np.clip(p * 1.8, 0, 1)
    iso = Isotonic().fit(p_raw, y)
    cal = iso.predict(p_raw)
    assert np.all(np.diff(iso.y_) >= -1e-9), "isotonic doit être croissante"
    brier_raw = np.mean((p_raw - y) ** 2)
    brier_cal = np.mean((cal - y) ** 2)
    assert brier_cal <= brier_raw + 1e-9, (brier_raw, brier_cal)

    # 4) round-trip JSON identique
    sm = ScoreModel([f"f{i}" for i in range(d)], lam=1.0).fit(X, y)
    pred = sm.predict_proba(X)
    sm2 = ScoreModel.from_json(sm.to_json())
    assert np.allclose(pred, sm2.predict_proba(X))

    print("model.py demo OK — logistic sign/shrinkage, isotonic monotone+calibrating, JSON round-trip")


if __name__ == "__main__":
    _demo()
