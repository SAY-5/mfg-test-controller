"""YAML loaders and Pydantic models for device profiles and test plans."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import AliasChoices, BaseModel, Field, model_validator

FaultKind = Literal["drift", "stuck", "delay", "crc_corrupt", "drop"]
RegisterKind = Literal["holding", "input"]


class FaultConfig(BaseModel):
    """Configuration for a single injected fault.

    The ``register`` field is exposed in YAML as ``register`` but bound to the
    Python attribute ``register_addr`` to avoid shadowing a base-class name.
    """

    kind: FaultKind
    register_addr: int | None = Field(
        default=None,
        validation_alias=AliasChoices("register", "register_addr"),
        serialization_alias="register",
    )
    amount: int = 0
    delay_seconds: float = 0.0
    after_requests: int = 0

    model_config = {"extra": "forbid", "populate_by_name": True}

    @property
    def register(self) -> int | None:
        """Backwards-compatible accessor for the targeted register address."""
        return self.register_addr


class RegisterSpec(BaseModel):
    """A named register with its address, kind, and initial value."""

    name: str
    address: int = Field(ge=0, le=0xFFFF)
    kind: RegisterKind = "holding"
    value: int = Field(default=0, ge=0, le=0xFFFF)

    model_config = {"extra": "forbid"}


class DeviceProfile(BaseModel):
    """A simulated device definition loaded from YAML."""

    name: str
    unit_id: int = Field(ge=0, le=0xFF)
    kind: Literal["power_supply", "dmm", "actuator", "thermocouple"]
    registers: list[RegisterSpec]
    faults: list[FaultConfig] = Field(default_factory=list)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _unique_addresses(self) -> DeviceProfile:
        seen: set[tuple[str, int]] = set()
        for reg in self.registers:
            key = (reg.kind, reg.address)
            if key in seen:
                raise ValueError(f"duplicate {reg.kind} register address {reg.address}")
            seen.add(key)
        return self

    def register_by_name(self, name: str) -> RegisterSpec:
        """Look up a register by its declared name."""
        for reg in self.registers:
            if reg.name == name:
                return reg
        raise KeyError(f"no register named {name!r} on device {self.name!r}")


class PlanStep(BaseModel):
    """A single ordered step in a test plan.

    The YAML key ``register`` is bound to the Python attribute
    ``register_name`` to avoid shadowing a base-class name.
    """

    name: str
    device: str
    action: Literal["read", "write"]
    register_name: str = Field(
        validation_alias=AliasChoices("register", "register_name"),
        serialization_alias="register",
    )
    expected_value: int | None = None
    expected_range: tuple[float, float] | None = None
    tolerance: float = 0.0
    write_value: int | None = None

    model_config = {"extra": "forbid", "populate_by_name": True}

    @property
    def register(self) -> str:
        """The name of the register this step reads or writes."""
        return self.register_name

    @model_validator(mode="after")
    def _check_action(self) -> PlanStep:
        if self.action == "write" and self.write_value is None:
            raise ValueError(f"step {self.name!r}: write action needs write_value")
        if self.action == "read" and (self.expected_value is None and self.expected_range is None):
            raise ValueError(
                f"step {self.name!r}: read action needs expected_value " "or expected_range"
            )
        return self


class TestPlan(BaseModel):
    """An ordered test plan referencing one or more devices."""

    name: str
    description: str = ""
    steps: list[PlanStep]

    model_config = {"extra": "forbid"}


def load_device_profile(path: str | Path) -> DeviceProfile:
    """Load and validate a device profile YAML file."""
    raw = yaml.safe_load(Path(path).read_text())
    return DeviceProfile.model_validate(raw)


def load_test_plan(path: str | Path) -> TestPlan:
    """Load and validate a test plan YAML file."""
    raw = yaml.safe_load(Path(path).read_text())
    return TestPlan.model_validate(raw)
