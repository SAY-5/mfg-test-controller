"""Runs a test plan step by step against connected simulated devices."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from mfg_test_controller.config import DeviceProfile, PlanStep, TestPlan
from mfg_test_controller.controller.client import (
    DeviceClient,
    DeviceError,
    ModbusException,
)
from mfg_test_controller.controller.thresholds import evaluate_step


@dataclass
class StepOutcome:
    """The result of executing one plan step."""

    name: str
    device: str
    action: str
    register: str
    passed: bool
    measured: float | None
    detail: str
    duration_s: float


@dataclass
class StationReport:
    """Aggregate result of running a whole test plan."""

    plan_name: str
    outcomes: list[StepOutcome] = field(default_factory=list)
    duration_s: float = 0.0

    @property
    def total(self) -> int:
        """Number of steps executed."""
        return len(self.outcomes)

    @property
    def passed(self) -> int:
        """Number of steps that passed."""
        return sum(1 for o in self.outcomes if o.passed)

    @property
    def failed(self) -> int:
        """Number of steps that failed."""
        return self.total - self.passed

    @property
    def all_passed(self) -> bool:
        """True if every executed step passed."""
        return self.failed == 0 and self.total > 0

    @property
    def first_failure(self) -> StepOutcome | None:
        """The first failing step, or None if all passed."""
        for outcome in self.outcomes:
            if not outcome.passed:
                return outcome
        return None


class Sequencer:
    """Executes a :class:`TestPlan` against a set of device clients."""

    def __init__(
        self,
        plan: TestPlan,
        profiles: dict[str, DeviceProfile],
        clients: dict[str, DeviceClient],
    ) -> None:
        self.plan = plan
        self.profiles = profiles
        self.clients = clients

    async def _run_step(self, step: PlanStep) -> StepOutcome:
        started = time.perf_counter()
        profile = self.profiles.get(step.device)
        client = self.clients.get(step.device)
        if profile is None or client is None:
            return StepOutcome(
                name=step.name,
                device=step.device,
                action=step.action,
                register=step.register,
                passed=False,
                measured=None,
                detail=f"no device configured named {step.device!r}",
                duration_s=time.perf_counter() - started,
            )

        try:
            reg = profile.register_by_name(step.register)
        except KeyError as exc:
            return StepOutcome(
                name=step.name,
                device=step.device,
                action=step.action,
                register=step.register,
                passed=False,
                measured=None,
                detail=str(exc),
                duration_s=time.perf_counter() - started,
            )

        try:
            measured = await self._execute(step, profile, client, reg.address, reg.kind)
        except (DeviceError, ModbusException) as exc:
            return StepOutcome(
                name=step.name,
                device=step.device,
                action=step.action,
                register=step.register,
                passed=False,
                measured=None,
                detail=f"device error: {exc}",
                duration_s=time.perf_counter() - started,
            )

        if step.action == "write":
            return StepOutcome(
                name=step.name,
                device=step.device,
                action=step.action,
                register=step.register,
                passed=True,
                measured=measured,
                detail=f"wrote {step.write_value} to {step.register}",
                duration_s=time.perf_counter() - started,
            )

        verdict = evaluate_step(step, measured)
        return StepOutcome(
            name=step.name,
            device=step.device,
            action=step.action,
            register=step.register,
            passed=verdict.passed,
            measured=verdict.measured,
            detail=verdict.detail,
            duration_s=time.perf_counter() - started,
        )

    async def _execute(
        self,
        step: PlanStep,
        profile: DeviceProfile,
        client: DeviceClient,
        address: int,
        kind: str,
    ) -> float:
        if step.action == "write":
            assert step.write_value is not None
            await client.write_single_register(profile.unit_id, address, step.write_value)
            return float(step.write_value)

        if kind == "input":
            values = await client.read_input_registers(profile.unit_id, address, 1)
        else:
            values = await client.read_holding_registers(profile.unit_id, address, 1)
        return float(values[0])

    async def run(self, only_failed: list[str] | None = None) -> StationReport:
        """Run the plan, optionally restricted to ``only_failed`` step names."""
        report = StationReport(plan_name=self.plan.name)
        started = time.perf_counter()
        for step in self.plan.steps:
            if only_failed is not None and step.name not in only_failed:
                continue
            report.outcomes.append(await self._run_step(step))
        report.duration_s = time.perf_counter() - started
        return report
