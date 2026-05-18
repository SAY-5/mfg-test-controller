"""Unit tests for the YAML config loaders."""

from __future__ import annotations

from pathlib import Path

from mfg_test_controller.config import load_device_profile, load_test_plan

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_load_all_shipped_profiles() -> None:
    for name in ("power_supply", "dmm", "actuator", "thermocouple"):
        profile = load_device_profile(REPO_ROOT / "profiles" / f"{name}.yaml")
        assert profile.name == name


def test_load_station_bringup_plan() -> None:
    plan = load_test_plan(REPO_ROOT / "plans" / "station_bringup.yaml")
    assert plan.name == "station_bringup"
    assert len(plan.steps) == 11


def test_plan_references_only_shipped_devices() -> None:
    plan = load_test_plan(REPO_ROOT / "plans" / "station_bringup.yaml")
    referenced = {step.device for step in plan.steps}
    assert referenced <= {"power_supply", "dmm", "actuator", "thermocouple"}


def test_plan_step_registers_resolve_against_profiles() -> None:
    plan = load_test_plan(REPO_ROOT / "plans" / "station_bringup.yaml")
    profiles = {
        name: load_device_profile(REPO_ROOT / "profiles" / f"{name}.yaml")
        for name in {step.device for step in plan.steps}
    }
    for step in plan.steps:
        # Should not raise: every plan register exists on its device.
        profiles[step.device].register_by_name(step.register)
