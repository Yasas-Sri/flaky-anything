import pytest

from flaky_anything.stats import wilson_interval

# Reference: statsmodels 0.14 proportion_confint(k, n, alpha, method="wilson"), run once offline.
WILSON = [
    # k, n, 95% interval, 99% interval
    (1, 10, (0.017876, 0.404150), (0.011852, 0.507232)),
    (0, 10, (0.0, 0.277533), (0.0, 0.398854)),
    (5, 10, (0.236593, 0.763407), (0.184226, 0.815774)),
    (10, 10, (0.722467, 1.0), (0.601146, 1.0)),
    (3, 100, (0.010255, 0.084519), (0.007612, 0.110875)),
    (2, 20, (0.027866, 0.301034), (0.019787, 0.379498)),
]


@pytest.mark.parametrize(("k", "n", "ci95", "ci99"), WILSON)
def test_wilson_matches_statsmodels(
    k: int, n: int, ci95: tuple[float, float], ci99: tuple[float, float]
) -> None:
    assert wilson_interval(k, n) == pytest.approx(ci95, abs=1e-6)
    assert wilson_interval(k, n, confidence=0.99) == pytest.approx(ci99, abs=1e-6)


def test_wilson_degenerate_and_invalid_input() -> None:
    assert wilson_interval(0, 0) == (0.0, 1.0)
    with pytest.raises(ValueError, match="failures <= n"):
        wilson_interval(3, 2)
