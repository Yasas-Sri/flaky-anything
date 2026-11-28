"""Statistics behind every number we print (hard rule 8). stdlib only: math + statistics."""

import math
from statistics import NormalDist


def wilson_interval(failures: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Wilson score interval for a failure rate of `failures` out of `n` trials."""
    if not 0 <= failures <= n:
        raise ValueError(f"need 0 <= failures <= n, got {failures}/{n}")
    if n == 0:
        return (0.0, 1.0)
    z = NormalDist().inv_cdf(1 - (1 - confidence) / 2)
    p = failures / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))
