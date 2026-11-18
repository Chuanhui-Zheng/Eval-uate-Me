"""Small, dependency-free statistics helpers for eval results."""
from __future__ import annotations

import math
import random
from typing import Sequence


def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def std(xs: Sequence[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased estimator of P(at least one of k samples passes), given c of n passed."""
    if k > n:
        raise ValueError("k cannot exceed n")
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def bootstrap_ci(values: Sequence[float], iters: int = 2000, alpha: float = 0.05, seed: int = 0) -> tuple[float, float]:
    """Percentile bootstrap CI for the mean. Resamples *cases*, so repeated attempts
    of one case are not treated as independent evidence."""
    n = len(values)
    if n == 0:
        return (0.0, 0.0)
    rng = random.Random(seed)
    means = sorted(mean([values[rng.randrange(n)] for _ in range(n)]) for _ in range(iters))
    return (means[int(alpha / 2 * iters)], means[min(iters - 1, int((1 - alpha / 2) * iters))])


def paired_delta_ci(a: Sequence[float], b: Sequence[float], iters: int = 2000, alpha: float = 0.05, seed: int = 0):
    """Bootstrap CI for mean(b - a) over paired cases. Returns (delta, lo, hi)."""
    if len(a) != len(b):
        raise ValueError("paired samples must have equal length")
    diffs = [y - x for x, y in zip(a, b)]
    lo, hi = bootstrap_ci(diffs, iters, alpha, seed)
    return mean(diffs), lo, hi


def cohen_kappa(a: Sequence[bool], b: Sequence[bool]) -> float:
    """Agreement between two yes/no raters beyond what chance would give. 1 = perfect, 0 = chance level."""
    n = len(a)
    if n == 0 or n != len(b):
        raise ValueError("need two non-empty, equal-length rating lists")
    agree = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return 1.0 if pe == 1 else (agree - pe) / (1 - pe)


# --- how many cases do you need, and how to compare many slices without fooling yourself ---

def _z(p: float) -> float:
    from statistics import NormalDist
    return NormalDist().inv_cdf(p)


def sample_size_unpaired(p1: float, delta: float, alpha: float = 0.05, power: float = 0.8) -> int:
    """Cases per system to detect a pass-rate difference `delta` from baseline `p1` (two independent samples,
    normal approximation)."""
    p2 = p1 + delta
    if not (0 < p1 < 1 and 0 < p2 < 1) or delta == 0:
        raise ValueError("baseline and baseline+delta must be strictly between 0 and 1, and delta must not be 0")
    pbar = (p1 + p2) / 2
    num = (_z(1 - alpha / 2) * math.sqrt(2 * pbar * (1 - pbar)) + _z(power) * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2
    return math.ceil(num / delta ** 2)


def sample_size_paired(delta: float, discordant: float, alpha: float = 0.05, power: float = 0.8) -> int:
    """Cases to detect `delta` when both systems run on the same cases. `discordant` is the fraction of cases
    where the two systems' outcomes differ; the variance of the per-case difference is discordant - delta^2."""
    if delta == 0 or not 0 < discordant <= 1 or discordant < abs(delta):
        raise ValueError("need delta != 0 and abs(delta) <= discordant <= 1")
    k = (_z(1 - alpha / 2) + _z(power)) ** 2
    return math.ceil(k * (discordant - delta ** 2) / delta ** 2)


def detectable_effect_unpaired(n: int, p1: float, alpha: float = 0.05, power: float = 0.8) -> float:
    """Smallest pass-rate increase over `p1` that n cases per system can reliably detect (bisection on the exact formula)."""
    lo, hi = 1e-6, 1 - p1 - 1e-6
    if hi <= lo or sample_size_unpaired(p1, hi, alpha, power) > n:
        return float("nan")  # even the largest possible difference needs more than n
    for _ in range(60):
        mid = (lo + hi) / 2
        if sample_size_unpaired(p1, mid, alpha, power) > n:
            lo = mid
        else:
            hi = mid
    return hi


def detectable_effect_paired(n: int, discordant: float, alpha: float = 0.05, power: float = 0.8) -> float:
    k = (_z(1 - alpha / 2) + _z(power)) ** 2
    return math.sqrt(k * discordant / (n + k))


def paired_permutation_p(diffs: Sequence[float], iters: int = 10000, seed: int = 0) -> float:
    """Two-sided sign-flip test: how often would random +/- signs on the per-case differences give a total at
    least as extreme as observed? Exact for up to 14 non-zero differences, otherwise Monte Carlo."""
    nz = [d for d in diffs if d != 0]
    if not nz:
        return 1.0
    obs = abs(sum(nz)) - 1e-12
    if len(nz) <= 14:
        hits = 0
        for mask in range(1 << len(nz)):
            s = sum(d if (mask >> i) & 1 else -d for i, d in enumerate(nz))
            hits += abs(s) >= obs
        return hits / (1 << len(nz))
    rng = random.Random(seed)
    hits = sum(abs(sum(d if rng.random() < 0.5 else -d for d in nz)) >= obs for _ in range(iters))
    return (hits + 1) / (iters + 1)


def holm_adjust(pvals: Sequence[float]) -> list[float]:
    """Holm step-down adjustment: controls the chance of any false positive across all the comparisons made."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    adjusted = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvals[i]))
        adjusted[i] = running
    return adjusted
