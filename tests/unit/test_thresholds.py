"""Unit tests for measurement-versus-specification evaluation."""

from __future__ import annotations

import pytest

from mfg_test_controller.config import PlanStep
from mfg_test_controller.controller.thresholds import evaluate_step


def _read_step(**kwargs: object) -> PlanStep:
    base: dict[str, object] = {
        "name": "s",
        "device": "dmm",
        "action": "read",
        "register": "meas",
    }
    base.update(kwargs)
    return PlanStep.model_validate(base)


def test_expected_value_within_tolerance_passes() -> None:
    step = _read_step(expected_value=100, tolerance=5)
    assert evaluate_step(step, 103).passed


def test_expected_value_outside_tolerance_fails() -> None:
    step = _read_step(expected_value=100, tolerance=5)
    result = evaluate_step(step, 120)
    assert not result.passed
    assert "delta 20" in result.detail


def test_expected_value_exact_boundary_passes() -> None:
    step = _read_step(expected_value=100, tolerance=5)
    assert evaluate_step(step, 105).passed
    assert evaluate_step(step, 95).passed


def test_expected_range_inside_passes() -> None:
    step = _read_step(expected_range=(10, 20))
    assert evaluate_step(step, 15).passed


def test_expected_range_boundaries_pass() -> None:
    step = _read_step(expected_range=(10, 20))
    assert evaluate_step(step, 10).passed
    assert evaluate_step(step, 20).passed


def test_expected_range_outside_fails() -> None:
    step = _read_step(expected_range=(10, 20))
    assert not evaluate_step(step, 21).passed
    assert not evaluate_step(step, 9).passed


def test_zero_tolerance_requires_exact_match() -> None:
    step = _read_step(expected_value=42, tolerance=0)
    assert evaluate_step(step, 42).passed
    assert not evaluate_step(step, 43).passed


def test_read_step_without_threshold_is_rejected_by_config() -> None:
    with pytest.raises(ValueError, match="expected_value or expected_range"):
        _read_step()


def test_write_step_requires_write_value() -> None:
    with pytest.raises(ValueError, match="write_value"):
        PlanStep.model_validate(
            {
                "name": "w",
                "device": "ps",
                "action": "write",
                "register": "voltage_setpoint",
            }
        )
