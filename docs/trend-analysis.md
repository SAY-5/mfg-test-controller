# Trend analysis and drift detection

`mfg-ctl trends` reads the SQLite run history and, for each measured register,
computes a Statistical Process Control (SPC) summary. The goal is to catch a
register that is still passing its threshold but drifting steadily toward a
limit, before it causes a hard test failure.

## Inputs

The analysis operates on the time series of `measured` values for a register,
taken from `step_result` rows where `action = "read"` and `measured` is not
null. Rows are ordered by their parent run's `started_at`, so the series is
oldest-first. `--station` filters by plan name and `--device` filters by
device name.

## Per-register statistics

For each register the following are computed over the value series:

| Metric | Definition |
|--------|------------|
| `mean` | Arithmetic mean of the measured values |
| `stddev` | Population standard deviation (`statistics.pstdev`) |
| `min` / `max` | Smallest and largest measured value |
| `slope` | Least-squares linear-fit slope, the per-run drift rate |

## Linear-fit method

The drift rate is the slope of an ordinary least-squares fit of the measured
values against their 0-based run index `x = 0, 1, ..., n-1`:

```
slope = sum((x - mean_x) * (y - mean_y)) / sum((x - mean_x) ** 2)
```

A series of fewer than two points, or one whose x-values have zero variance,
has a slope of `0.0`. The slope carries the same units as the register per
run: a slope of `+25` means the register climbs 25 units on each successive
test run.

## Control-chart classification

The series is placed on a control chart whose centre line is the series mean
and whose upper and lower control limits sit at `mean +/- 3 * stddev`. The
classification follows a simplified subset of the Western Electric rules:

* **out-of-control** — Western Electric rule 1: any single point falls outside
  the 3-sigma control limits. This fires first and takes precedence.
* **trending** — Western Electric rule 3 (the trend rule): a run of at least
  six consecutive points all strictly increasing or all strictly decreasing.
  As an additional drift test, a series whose total linear span
  `(n - 1) * |slope|` exceeds `3 * stddev` is also classified `trending`, which
  catches a steady ramp that has not yet produced a six-point monotonic run
  because of measurement noise. When the series has zero variance, any nonzero
  slope is `trending`.
* **in-control** — no rule fired.

The standard Western Electric rule set has four rules (rule 1: one point beyond
3 sigma; rule 2: two of three beyond 2 sigma; rule 3: four of five beyond 1
sigma; the trend and run rules). This module implements the 3-sigma limit rule
and the six-point trend rule, which together cover the hard-failure and the
slow-drift cases this controller cares about.

## Runs-to-failure extrapolation

When a register is classified `trending` and a threshold `--limit` is
supplied, the linear fit is extrapolated forward to estimate how many further
test runs will pass before the measurement reaches the limit:

```
runs_to_failure = (limit - last_value) / slope
```

where `last_value` is the most recent measured value. The estimate is only
produced when the slope points toward the limit. If the slope is zero, or the
series is drifting away from the limit, `runs_to_failure` is `None`. A series
already at the limit yields `0.0`.

### Worked example

A register seeded with `start = 4000`, `step = +25` per run over 12 runs has
its last value at `4000 + 25 * 11 = 4275`. Against a limit of `5000`:

```
slope            = 25.0 per run
runs_to_failure  = (5000 - 4275) / 25 = 29.0 runs
```

## CLI usage

```
mfg-ctl trends --station station_bringup
mfg-ctl trends --register dc_voltage --station station_bringup --limit 5000
mfg-ctl trends --station station_bringup --export trend-report.md
```

`--export` renders a Markdown control-chart report listing every analysed
register plus dedicated sections for the trending and out-of-control
registers. With no value, `--export` prints the report to stdout.
