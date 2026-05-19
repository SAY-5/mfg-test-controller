"""Measurement trend analysis and drift detection.

Across historical test runs a register that is still passing its threshold
can be walking steadily toward a limit. This module reads the run history
from the SQLite store and, per measured register, computes:

* mean, standard deviation, min and max of the measured values
* a least-squares linear-fit slope, the per-run drift rate
* a Statistical Process Control (SPC) control-chart classification

The classification follows simplified Western Electric rules over a control
chart whose centre line is the series mean and whose control limits are at
+/- 3 sigma:

* ``in-control``     no rule fired
* ``trending``       a monotonic run of points, or a clear linear drift, that
                     has not yet breached a limit
* ``out-of-control`` a point outside the +/- 3 sigma control limits

When a register is ``trending`` toward a threshold limit, an estimated
``runs_to_failure`` is computed by extrapolating the linear fit to the limit.

See ``docs/trend-analysis.md`` for the full rule set.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from enum import Enum

# A monotonic run of at least this many points counts as a trend (Western
# Electric rule: six points steadily increasing or decreasing).
TREND_RUN_LENGTH = 6

# Sigma multiplier for the control limits.
CONTROL_SIGMA = 3.0


class ControlState(str, Enum):
    """SPC control-chart classification of a measurement series."""

    IN_CONTROL = "in-control"
    TRENDING = "trending"
    OUT_OF_CONTROL = "out-of-control"


@dataclass(frozen=True)
class RegisterTrend:
    """The trend analysis of one measured register's history."""

    register: str
    device: str
    samples: int
    mean: float
    stddev: float
    minimum: float
    maximum: float
    slope: float
    state: ControlState
    runs_to_failure: float | None
    limit: float | None

    def summary_line(self) -> str:
        """A compact one-line human summary."""
        rtf = (
            f", ~{self.runs_to_failure:.1f} runs to limit"
            if self.runs_to_failure is not None
            else ""
        )
        return (
            f"{self.register} ({self.device}): {self.state.value}, "
            f"mean {self.mean:g}, stddev {self.stddev:g}, "
            f"slope {self.slope:+g}/run{rtf}"
        )


def linear_slope(values: list[float]) -> float:
    """Least-squares slope of ``values`` against their 0-based index.

    Returns 0.0 for a series too short to fit (fewer than two points).
    """
    n = len(values)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mean_x = (n - 1) / 2.0
    mean_y = statistics.fmean(values)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values, strict=True))
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _longest_monotonic_run(values: list[float]) -> int:
    """Length of the longest strictly increasing or decreasing run."""
    if len(values) < 2:
        return len(values)
    best = 1
    up = 1
    down = 1
    for prev, cur in zip(values, values[1:], strict=False):
        if cur > prev:
            up += 1
            down = 1
        elif cur < prev:
            down += 1
            up = 1
        else:
            up = 1
            down = 1
        best = max(best, up, down)
    return best


def classify(values: list[float], slope: float, stddev: float) -> ControlState:
    """Classify a measurement series with simplified Western Electric rules."""
    if len(values) < 2:
        return ControlState.IN_CONTROL
    mean = statistics.fmean(values)
    if stddev > 0:
        upper = mean + CONTROL_SIGMA * stddev
        lower = mean - CONTROL_SIGMA * stddev
        if any(v > upper or v < lower for v in values):
            return ControlState.OUT_OF_CONTROL
    run = _longest_monotonic_run(values)
    if run >= TREND_RUN_LENGTH:
        return ControlState.TRENDING
    # A clear linear drift relative to the noise also counts as trending.
    span = (len(values) - 1) * abs(slope)
    if stddev > 0 and span > CONTROL_SIGMA * stddev:
        return ControlState.TRENDING
    if stddev == 0 and abs(slope) > 0:
        return ControlState.TRENDING
    return ControlState.IN_CONTROL


def estimate_runs_to_failure(values: list[float], slope: float, limit: float) -> float | None:
    """Estimate how many further runs until the series reaches ``limit``.

    Extrapolates the last value along the linear fit. Returns ``None`` when
    the series is not moving toward the limit (zero slope, or drifting away).
    """
    if not values or slope == 0:
        return None
    last = values[-1]
    distance = limit - last
    # The slope must point toward the limit.
    if distance == 0:
        return 0.0
    if (distance > 0) != (slope > 0):
        return None
    runs = distance / slope
    return runs if runs >= 0 else None


def analyse_register(
    register: str,
    device: str,
    values: list[float],
    limit: float | None = None,
) -> RegisterTrend:
    """Compute the full trend analysis for one register's measurement series."""
    samples = len(values)
    if samples == 0:
        return RegisterTrend(
            register=register,
            device=device,
            samples=0,
            mean=0.0,
            stddev=0.0,
            minimum=0.0,
            maximum=0.0,
            slope=0.0,
            state=ControlState.IN_CONTROL,
            runs_to_failure=None,
            limit=limit,
        )
    mean = statistics.fmean(values)
    stddev = statistics.pstdev(values) if samples > 1 else 0.0
    slope = linear_slope(values)
    state = classify(values, slope, stddev)
    runs_to_failure: float | None = None
    if state is ControlState.TRENDING and limit is not None:
        runs_to_failure = estimate_runs_to_failure(values, slope, limit)
    return RegisterTrend(
        register=register,
        device=device,
        samples=samples,
        mean=mean,
        stddev=stddev,
        minimum=min(values),
        maximum=max(values),
        slope=slope,
        state=state,
        runs_to_failure=runs_to_failure,
        limit=limit,
    )


def render_trends_markdown(trends: list[RegisterTrend]) -> str:
    """Render a per-register control-chart summary as a Markdown report."""
    lines = [
        "# Measurement trend analysis",
        "",
        f"Registers analysed: {len(trends)}",
        "",
        "| Register | Device | Samples | Mean | StdDev | Min | Max "
        "| Slope/run | State | Runs to limit |",
        "|----------|--------|---------|------|--------|-----|-----"
        "|-----------|-------|---------------|",
    ]
    for trend in trends:
        rtf = f"{trend.runs_to_failure:.1f}" if trend.runs_to_failure is not None else "-"
        lines.append(
            f"| {trend.register} | {trend.device} | {trend.samples} "
            f"| {trend.mean:g} | {trend.stddev:g} | {trend.minimum:g} "
            f"| {trend.maximum:g} | {trend.slope:+g} | {trend.state.value} "
            f"| {rtf} |"
        )
    lines.append("")
    trending = [t for t in trends if t.state is ControlState.TRENDING]
    out = [t for t in trends if t.state is ControlState.OUT_OF_CONTROL]
    if out:
        lines.append("## Out of control")
        lines.append("")
        for trend in out:
            lines.append(f"- {trend.summary_line()}")
        lines.append("")
    if trending:
        lines.append("## Trending toward a limit")
        lines.append("")
        for trend in trending:
            lines.append(f"- {trend.summary_line()}")
        lines.append("")
    return "\n".join(lines)


__all__ = [
    "ControlState",
    "RegisterTrend",
    "TREND_RUN_LENGTH",
    "CONTROL_SIGMA",
    "linear_slope",
    "classify",
    "estimate_runs_to_failure",
    "analyse_register",
    "render_trends_markdown",
]
