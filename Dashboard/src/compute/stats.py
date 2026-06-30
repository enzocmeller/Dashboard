"""Trend, detrending and correlation helpers built on the ``statistics`` stdlib.

``statistics.linear_regression`` and ``statistics.correlation`` exist in
Python 3.10+, so no numpy/pandas is required.
"""
import statistics


def linear_trend(xs, ys):
    """Fit y = slope*x + intercept. Returns (slope, intercept) or None."""
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 2:
        return None
    fx = [p[0] for p in pairs]
    fy = [p[1] for p in pairs]
    try:
        res = statistics.linear_regression(fx, fy)
        return (res.slope, res.intercept)
    except statistics.StatisticsError:
        return None


def trend_line(xs, slope, intercept):
    """Evaluate the fitted line at each x (None where x is None)."""
    return [
        round(slope * x + intercept, 3) if x is not None else None for x in xs
    ]


def detrend(xs, ys, slope, intercept):
    """Residuals: actual - fitted. Captures the real year-to-year change."""
    out = []
    for x, y in zip(xs, ys):
        if x is None or y is None:
            out.append(None)
        else:
            out.append(round(y - (slope * x + intercept), 3))
    return out


def pearson(xs, ys):
    """Pearson r over paired finite values, or None if not computable."""
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 3:
        return None
    fx = [p[0] for p in pairs]
    fy = [p[1] for p in pairs]
    # correlation needs variation in both variables
    if len(set(fx)) < 2 or len(set(fy)) < 2:
        return None
    try:
        return round(statistics.correlation(fx, fy), 4)
    except statistics.StatisticsError:
        return None


def regression_endpoints(xs, ys):
    """Return [[x_min, y_at_min], [x_max, y_at_max]] for a fitted line, or None."""
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 2:
        return None
    fx = [p[0] for p in pairs]
    fy = [p[1] for p in pairs]
    fit = linear_trend(fx, fy)
    if not fit:
        return None
    slope, intercept = fit
    x0, x1 = min(fx), max(fx)
    return [[round(x0, 3), round(slope * x0 + intercept, 3)],
            [round(x1, 3), round(slope * x1 + intercept, 3)]]


def safe_stats(values):
    """min/median/max of a list ignoring None; returns (min, median, max) or Nones."""
    vals = [v for v in values if v is not None]
    if not vals:
        return (None, None, None)
    return (round(min(vals), 2), round(statistics.median(vals), 2), round(max(vals), 2))
