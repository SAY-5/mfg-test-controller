"""Unit tests for built-in device profiles and the simulated device."""

from __future__ import annotations

import pytest

from mfg_test_controller.config import DeviceProfile, RegisterSpec
from mfg_test_controller.device.profiles import (
    builtin_profile,
    builtin_profile_names,
)
from mfg_test_controller.device.simulated import SimulatedDevice
from mfg_test_controller.modbus.codec import (
    decode_read_response,
    encode_read_holding,
    encode_read_input,
    encode_write_single,
)
from mfg_test_controller.modbus.exceptions import (
    ExceptionCode,
    decode_exception,
    is_exception_frame,
)
from mfg_test_controller.modbus.frame import Frame


def test_all_four_profiles_exist() -> None:
    assert builtin_profile_names() == ["actuator", "dmm", "power_supply", "thermocouple"]


@pytest.mark.parametrize("name", builtin_profile_names())
def test_profile_loads_into_device(name: str) -> None:
    device = SimulatedDevice(builtin_profile(name))
    assert device.unit_id == builtin_profile(name).unit_id


def test_power_supply_write_then_read_holding() -> None:
    device = SimulatedDevice(builtin_profile("power_supply"))
    write = encode_write_single(1, 0, 1200)
    echo = device.handle_frame(write)
    assert echo is not None and not is_exception_frame(echo)

    read = encode_read_holding(1, 0, 1)
    response = device.handle_frame(read)
    assert response is not None
    assert decode_read_response(response).registers == [1200]


def test_dmm_read_input_register() -> None:
    device = SimulatedDevice(builtin_profile("dmm"))
    response = device.handle_frame(encode_read_input(2, 0, 1))
    assert response is not None
    assert decode_read_response(response).registers == [4980]


def test_thermocouple_has_three_input_channels() -> None:
    device = SimulatedDevice(builtin_profile("thermocouple"))
    response = device.handle_frame(encode_read_input(4, 0, 3))
    assert response is not None
    assert len(decode_read_response(response).registers) == 3


def test_actuator_write_multiple_then_read() -> None:
    device = SimulatedDevice(builtin_profile("actuator"))
    from mfg_test_controller.modbus.codec import (
        encode_register_block,
        encode_write_multiple,
    )

    request = encode_write_multiple(3, 0, 2)
    payload = encode_register_block([700, 1])
    echo = device.handle_frame(request, payload)
    assert echo is not None and not is_exception_frame(echo)

    response = device.handle_frame(encode_read_holding(3, 0, 2))
    assert response is not None
    assert decode_read_response(response).registers == [700, 1]


def test_unknown_address_returns_exception() -> None:
    device = SimulatedDevice(builtin_profile("dmm"))
    response = device.handle_frame(encode_read_input(2, 99, 1))
    assert response is not None and is_exception_frame(response)
    assert decode_exception(response).code == ExceptionCode.ILLEGAL_DATA_ADDRESS


def test_wrong_unit_id_returns_exception() -> None:
    device = SimulatedDevice(builtin_profile("dmm"))
    response = device.handle_frame(encode_read_input(99, 0, 1))
    assert response is not None and is_exception_frame(response)


def test_unknown_function_code_returns_exception() -> None:
    device = SimulatedDevice(builtin_profile("dmm"))
    bogus = Frame(2, 0x07, 0, 1).encode()
    response = device.handle_frame(bogus)
    assert response is not None and is_exception_frame(response)
    assert decode_exception(response).code == ExceptionCode.ILLEGAL_FUNCTION


def test_bad_crc_request_returns_crc_exception() -> None:
    device = SimulatedDevice(builtin_profile("dmm"))
    corrupt = bytearray(encode_read_input(2, 0, 1))
    corrupt[-1] ^= 0xFF
    response = device.handle_frame(bytes(corrupt))
    assert response is not None and is_exception_frame(response)
    assert decode_exception(response).code == ExceptionCode.CRC_ERROR


def test_duplicate_register_address_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        DeviceProfile(
            name="bad",
            unit_id=1,
            kind="dmm",
            registers=[
                RegisterSpec(name="a", address=0, kind="input"),
                RegisterSpec(name="b", address=0, kind="input"),
            ],
        )
