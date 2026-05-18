"""Hypothesis property tests for threshold evaluation.

Each generated step is checked against an independent, hand-computed
reference verdict so the property test does not just re-derive the
implementation. Both the value/tolerance branch and the range branch are
covered.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from mfg_test_controller.config import PlanStep
from mfg_test_controller.controller.thresholds import evaluate_step

MEASUREMENTS = st.floats(min_value=-1.0e6, max_value=1.0e6, allow_nan=False, allow_infinity=False)
TARGETS = st.integers(min_value=0, max_value=0xFFFF)
TOLERANCES = st.floats(min_value=0.0, max_value=1.0e5, allow_nan=False, allow_infinity=False)
LIMITS = st.floats(min_value=-1.0e6, max_value=1.0e6, allow_nan=False, allow_infinity=False)


def _reference_value_verdict(measured: float, target: float, tolerance: float) -> bool:
    """Independent reference: pass iff |measured - target| <= tolerance."""
    return abs(measured - target) <= tolerance


def _reference_range_verdict(measured: float, low: float, high: float) -> bool:
    """Independent reference: pass iff low <= measured <= high."""
    return low <= measured <= high


@given(measured=MEASUREMENTS, target=TARGETS, tolerance=TOLERANCES)
def test_value_tolerance_matches_reference(measured: float, target: int, tolerance: float) -> None:
    """The value/tolerance verdict matches the hand-computed reference."""
    step = PlanStep(
        name="probe",
        device="dmm",
        action="read",
        register="dc_voltage",
        expected_value=target,
        tolerance=tolerance,
    )
    result = evaluate_step(step, measured)
    assert result.measured == measured
    assert result.passed == _reference_value_verdict(measured, float(target), tolerance)


@given(measured=MEASUREMENTS, a=LIMITS, b=LIMITS)
def test_range_matches_reference(measured: float, a: float, b: float) -> None:
    """The range verdict matches the hand-computed reference."""
    low, high = sorted((a, b))
    step = PlanStep(
        name="probe",
        device="dmm",
        action="read",
        register="dc_voltage",
        expected_range=(low, high),
    )
    result = evaluate_step(step, measured)
    assert result.measured == measured
    assert result.passed == _reference_range_verdict(measured, low, high)


@given(target=TARGETS, tolerance=TOLERANCES)
def test_measurement_exactly_on_target_passes(target: int, tolerance: float) -> None:
    """A measurement equal to the target always passes."""
    step = PlanStep(
        name="probe",
        device="dmm",
        action="read",
        register="dc_voltage",
        expected_value=target,
        tolerance=tolerance,
    )
    assert evaluate_step(step, float(target)).passed


@given(target=TARGETS, tolerance=TOLERANCES, overshoot=st.floats(min_value=1.0, max_value=1.0e4))
def test_measurement_beyond_tolerance_fails(
    target: int, tolerance: float, overshoot: float
) -> None:
    """A measurement past target + tolerance + overshoot always fails."""
    step = PlanStep(
        name="probe",
        device="dmm",
        action="read",
        register="dc_voltage",
        expected_value=target,
        tolerance=tolerance,
    )
    measured = float(target) + tolerance + overshoot
    assert not evaluate_step(step, measured).passed


@given(a=LIMITS, b=LIMITS)
def test_range_boundaries_are_inclusive(a: float, b: float) -> None:
    """Both range endpoints are inclusive."""
    low, high = sorted((a, b))
    step = PlanStep(
        name="probe",
        device="dmm",
        action="read",
        register="dc_voltage",
        expected_range=(low, high),
    )
    assert evaluate_step(step, low).passed
    assert evaluate_step(step, high).passed
