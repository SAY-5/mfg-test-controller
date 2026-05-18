# Test plans

This directory holds YAML test plans for the manufacturing test controller.

## station_bringup.yaml

The canonical example: an 11-step bring-up of a four-instrument test station
(power supply, multimeter, actuator, thermocouple). It configures the power
supply, verifies its readbacks, commands the actuator, and checks the
multimeter and thermocouple measurements against per-step thresholds.

Run it with:

```
mfg-ctl run plans/station_bringup.yaml
```

The 11 plan steps correspond one-to-one to the 11 manual bring-up actions
described in the project README. See `docs/test-plans.md` for the plan file
format and threshold semantics.
