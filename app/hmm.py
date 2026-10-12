"""Gaussian Hidden Markov Model (from scratch, numpy only).

Used to detect latent market regimes from return/volatility features. Implements
Baum-Welch (EM) training with multiple restarts + Viterbi decoding, in log-space
for numerical stability.
"""
from __future__ import annotations

import numpy as np


def _logsumexp(a, axis=-1):
    m = np.max(a, axis=axis, keepdims=True)
    m = np.where(np.isfinite(m), m, 0.0)
    out = m + np.log(np.sum(np.exp(a - m), axis=axis, keepdims=True) + 1e-300)
    return np.squeeze(out, axis=axis)


class GaussianHMM:
    def __init__(self, n_states: int = 4, n_iter: int = 40, tol: float = 1e-4,
                 restarts: int = 3, seed: int = 7) -> None:
        self.k = n_states
        self.n_iter = n_iter
        self.tol = tol
        self.restarts = restarts
        self.seed = seed
        self.pi: np.ndarray | None = None
        self.A: np.ndarray | None = None
        self.mu: np.ndarray | None = None
        self.var: np.ndarray | None = None
        self.loglik: float = -np.inf

    # ------------------------------------------------------------------
    def _init_params(self, X: np.ndarray, rng: np.random.Generator):
        T, D = X.shape
        k = self.k
        pi = np.ones(k) / k
        A = np.full((k, k), 1.0 / k) + rng.uniform(0, 0.1, (k, k))
        A /= A.sum(axis=1, keepdims=True)
        order = np.argsort(X[:, 0])
        chunks = np.array_split(order, k)
        mu = np.array([X[c].mean(axis=0) for c in chunks])
        var = np.array([X[c].var(axis=0) + 1e-2 for c in chunks])
        return pi, A, mu, var

    def _log_emission(self, X: np.ndarray) -> np.ndarray:
        T = X.shape[0]
        logB = np.zeros((T, self.k))
        for j in range(self.k):
            v = self.var[j]
            d = X - self.mu[j]
            logB[:, j] = -0.5 * (np.sum(np.log(2 * np.pi * v)) + np.sum(d * d / v, axis=1))
        return np.clip(logB, -700.0, 0.0)

    def _forward_backward(self, logB: np.ndarray):
        T = logB.shape[0]
        k = self.k
        logpi = np.log(self.pi + 1e-300)
        logA = np.log(self.A + 1e-300)
        logalpha = np.zeros((T, k))
        logalpha[0] = logpi + logB[0]
        for t in range(1, T):
            logalpha[t] = _logsumexp(logalpha[t - 1][:, None] + logA, axis=0) + logB[t]
        logbeta = np.zeros((T, k))
        for t in range(T - 2, -1, -1):
            logbeta[t] = _logsumexp(logA + (logB[t + 1] + logbeta[t + 1])[None, :], axis=1)
        loglik = _logsumexp(logalpha[-1], axis=0)
        return logalpha, logbeta, loglik, logA

    def _em(self, X: np.ndarray) -> float:
        T = X.shape[0]
        k = self.k
        prev = -np.inf
        for it in range(self.n_iter):
            logB = self._log_emission(X)
            logalpha, logbeta, loglik, logA = self._forward_backward(logB)
            if it > 0 and (loglik - prev) < self.tol:
                prev = loglik
                break
            prev = loglik
            loggamma = logalpha + logbeta - loglik
            gamma = np.exp(loggamma)
            gsum = gamma.sum(axis=0) + 1e-12

            # vectorised xi accumulations: (T-1, k, k)
            lb_next = logB[1:] + logbeta[1:]
            tmp = logalpha[:-1][:, :, None] + logA[None, :, :] + lb_next[:, None, :]
            xi_sum = np.exp(tmp - loglik).sum(axis=0)

            self.pi = gamma[0] / gamma[0].sum()
            self.A = xi_sum / (xi_sum.sum(axis=1, keepdims=True) + 1e-12)
            self.mu = (gamma.T @ X) / gsum[:, None]
            for j in range(k):
                d = X - self.mu[j]
                self.var[j] = (gamma[:, j][:, None] * d * d).sum(axis=0) / gsum[j] + 1e-2
        return prev

    # ------------------------------------------------------------------
    def fit(self, X: np.ndarray) -> "GaussianHMM":
        X = np.asarray(X, dtype=float)
        best = None
        for r in range(self.restarts):
            rng = np.random.default_rng(self.seed + r)
            self.pi, self.A, self.mu, self.var = self._init_params(X, rng)
            ll = self._em(X)
            if best is None or ll > best[0]:
                best = (ll, self.pi.copy(), self.A.copy(), self.mu.copy(), self.var.copy())
        self.loglik, self.pi, self.A, self.mu, self.var = best
        return self

    def predict_proba_last(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        logB = self._log_emission(X)
        logalpha, logbeta, loglik, _ = self._forward_backward(logB)
        gamma = np.exp(logalpha + logbeta - loglik)
        return gamma[-1]

    def viterbi(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        logB = self._log_emission(X)
        logpi = np.log(self.pi + 1e-300)
        logA = np.log(self.A + 1e-300)
        T, k = logB.shape
        delta = np.zeros((T, k))
        psi = np.zeros((T, k), dtype=int)
        delta[0] = logpi + logB[0]
        for t in range(1, T):
            for j in range(k):
                vals = delta[t - 1] + logA[:, j]
                psi[t, j] = int(np.argmax(vals))
                delta[t, j] = vals[psi[t, j]] + logB[t, j]
        path = np.zeros(T, dtype=int)
        path[-1] = int(np.argmax(delta[-1]))
        for t in range(T - 2, -1, -1):
            path[t] = psi[t + 1, path[t + 1]]
        return path


def build_features(df, vol_window: int = 10) -> np.ndarray:
    """Two features: log-return and rolling volatility, standardized."""
    close = df["close"].to_numpy(dtype=float)
    ret = np.diff(np.log(close), prepend=np.log(close[0]))
    ret[0] = 0.0
    import pandas as pd

    vol = pd.Series(ret).rolling(vol_window, min_periods=1).std().to_numpy()
    vol = np.nan_to_num(vol, nan=0.0)
    X = np.column_stack([ret, vol])
    mu, sd = X.mean(axis=0), X.std(axis=0)
    sd[sd == 0] = 1.0
    return (X - mu) / sd
