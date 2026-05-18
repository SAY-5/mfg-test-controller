"""Built-in device profiles for the four simulated instrument types.

Each profile is also written out to ``profiles/*.yaml`` so it can be loaded
and edited from disk. These in-code definitions are the source of truth used
by tests and by the profile-export tooling.
"""

from __future__ import annotations

from mfg_test_controller.config import DeviceProfile, RegisterSpec


def _power_supply() -> DeviceProfile:
    """A bench power supply: voltage and current setpoints and readbacks."""
    return DeviceProfile(
        name="power_supply",
        unit_id=1,
        kind="power_supply",
        registers=[
            RegisterSpec(name="voltage_setpoint", address=0, kind="holding", value=0),
            RegisterSpec(name="current_limit", address=1, kind="holding", value=0),
            RegisterSpec(name="output_enable", address=2, kind="holding", value=0),
            RegisterSpec(name="voltage_readback", address=0, kind="input", value=0),
            RegisterSpec(name="current_readback", address=1, kind="input", value=0),
        ],
    )


def _dmm() -> DeviceProfile:
    """A digital multimeter: measurement registers across ranges."""
    return DeviceProfile(
        name="dmm",
        unit_id=2,
        kind="dmm",
        registers=[
            RegisterSpec(name="range_select", address=0, kind="holding", value=1),
            RegisterSpec(name="dc_voltage", address=0, kind="input", value=4980),
            RegisterSpec(name="dc_current", address=1, kind="input", value=120),
            RegisterSpec(name="resistance", address=2, kind="input", value=1000),
        ],
    )


def _actuator() -> DeviceProfile:
    """A linear actuator: commanded position and a status word."""
    return DeviceProfile(
        name="actuator",
        unit_id=3,
        kind="actuator",
        registers=[
            RegisterSpec(name="target_position", address=0, kind="holding", value=0),
            RegisterSpec(name="move_enable", address=1, kind="holding", value=0),
            RegisterSpec(name="actual_position", address=0, kind="input", value=0),
            RegisterSpec(name="status_word", address=1, kind="input", value=1),
        ],
    )


def _thermocouple() -> DeviceProfile:
    """A thermocouple module: temperature input registers in centi-degrees."""
    return DeviceProfile(
        name="thermocouple",
        unit_id=4,
        kind="thermocouple",
        registers=[
            RegisterSpec(name="channel_0_temp", address=0, kind="input", value=2300),
            RegisterSpec(name="channel_1_temp", address=1, kind="input", value=2310),
            RegisterSpec(name="cold_junction", address=2, kind="input", value=2500),
        ],
    )


_BUILTIN = {
    "power_supply": _power_supply,
    "dmm": _dmm,
    "actuator": _actuator,
    "thermocouple": _thermocouple,
}


def builtin_profile_names() -> list[str]:
    """Return the names of all built-in profiles."""
    return sorted(_BUILTIN)


def builtin_profile(name: str) -> DeviceProfile:
    """Return a fresh copy of the named built-in profile."""
    if name not in _BUILTIN:
        raise KeyError(f"unknown built-in profile: {name}")
    return _BUILTIN[name]()
