# Station report: station_bringup

Result: PASS

- Total steps: 11
- Passed: 11
- Failed: 0
- Wall-clock duration: 0.002 s

| # | Step | Device | Action | Register | Result | Detail |
|---|------|--------|--------|----------|--------|--------|
| 1 | set_supply_voltage | power_supply | write | voltage_setpoint | pass | wrote 1200 to voltage_setpoint |
| 2 | set_supply_current_limit | power_supply | write | current_limit | pass | wrote 500 to current_limit |
| 3 | enable_supply_output | power_supply | write | output_enable | pass | wrote 1 to output_enable |
| 4 | check_supply_voltage_readback | power_supply | read | voltage_readback | pass | measured 1200, expected 1200 +/- 25 (delta 0) |
| 5 | check_supply_current_readback | power_supply | read | current_readback | pass | measured 480, expected within [400, 520] |
| 6 | command_actuator_position | actuator | write | target_position | pass | wrote 500 to target_position |
| 7 | check_actuator_position | actuator | read | actual_position | pass | measured 500, expected 500 +/- 10 (delta 0) |
| 8 | check_actuator_status | actuator | read | status_word | pass | measured 1, expected 1 +/- 0 (delta 0) |
| 9 | check_dmm_dc_voltage | dmm | read | dc_voltage | pass | measured 4980, expected 5000 +/- 50 (delta 20) |
| 10 | check_thermocouple_channel_0 | thermocouple | read | channel_0_temp | pass | measured 2300, expected within [2200, 2400] |
| 11 | check_thermocouple_cold_junction | thermocouple | read | cold_junction | pass | measured 2500, expected within [2300, 2700] |
