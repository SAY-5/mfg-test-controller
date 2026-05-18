"""Measurement-versus-specification evaluation.

A test step declares either an ``expected_value`` (with a ``tolerance``) or an
``expected_range`` (a low/high pair). The measured register value is compared
against that specification and a pass/fail verdict plus a human-readable
detail string are produced.
"""

from __future__ import annotations

from dataclasses import dataclass

from mfg_test_controller.config import PlanStep


@dataclass(frozen=True)
class ThresholdResult:
    """The verdict of evaluating one measurement against its specification."""

    passed: bool
    measured: float
    detail: str


def evaluate_step(step: PlanStep, measured: float) -> ThresholdResult:
    """Evaluate ``measured`` against the threshold declared by ``step``.

    Raises ValueError when the step declares neither an expected value nor an
    expected range; the config layer normally prevents this.
    """
    if step.expected_range is not None:
        low, high = step.expected_range
        passed = low <= measured <= high
        detail = f"measured {measured:g}, expected within [{low:g}, {high:g}]"
        return ThresholdResult(passed=passed, measured=measured, detail=detail)

    if step.expected_value is not None:
        target = float(step.expected_value)
        delta = abs(measured - target)
        passed = delta <= step.tolerance
        detail = (
            f"measured {measured:g}, expected {target:g} "
            f"+/- {step.tolerance:g} (delta {delta:g})"
        )
        return ThresholdResult(passed=passed, measured=measured, detail=detail)

    raise ValueError(f"step {step.name!r} declares no expected_value or expected_range")
