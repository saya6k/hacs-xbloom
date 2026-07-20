# Troubleshooting

The official XBloom troubleshooting guidance, mapped to this integration's
error event types. The `event.error` entity fires one of the types below
when the machine reports an alarm over BLE (cmd `0xFFFE` — see
[protocol.md](protocol.md)'s command table); each event carries the raw
alarm `code` as an attribute, so automations can notify with the matching
quick fix.

## Machine alarms (event types)

| Event type | Official issue | Quick fix |
| --- | --- | --- |
| `mismatched_power` | Mismatched power / Power-Voltage alert | Ensure the machine's voltage matches your country's and connect the right power adapter. If the voltage matches, try a different outlet. |
| `brewing_error` | Brewing error / Water Intake alert¹ | Ensure the water tank and lines have sufficient water, and that the selected water source is available/turned on. Consider running a descaling cycle or checking the water inlet for blockage. |
| `dock_moving_error` | Dock moving error | Make sure there are no obstacles around the dock and keep the surrounding area clean. If it persists, unplug the machine for 30 seconds and retry. |
| `grinding_error` | Grinding error / Grinder Overload¹ | Check the grinder for foreign objects or jammed beans. Quick-press the right knob three times to restart, then calibrate the grinder and try again. If the grinder overheats, limit sessions to ≤30 s with ≥60 s between them. Very hard beans (Agtron 100+) are not recommended for espresso grinding. |
| `scale_overload` | Scale overload | Do not exceed the 2 kg limit. If readings stay wrong, recalibrate the scale (triple-press the center knob on the scale page). |
| `upgrade_failed` | Upgrade failed | During a firmware upgrade, keep Bluetooth on and stay next to the machine. The process takes 2–10 minutes. |

¹ "Water Intake Alert", "Grinder Overload", and "Overflow Trigger /
Waiting During Pouring" have no distinct BLE alarm id — the machine's
display distinguishes them, but over BLE they arrive inside the broader
category shown here (decompile-confirmed 2026-07-20).

## Errors with their own dedicated signals

| Event type | Official issue | Quick fix |
| --- | --- | --- |
| `water_shortage` | Water Shortage alert (cmd 40522) | Check whether the water source is depleted and refill. The machine reports refills too — `water_shortage_cleared` fires when resolved. |
| `no_beans` | Bean Shortage alert (cmd 40517) | Check for foreign objects or stuck beans (tap the grinder), then add beans. |
| `abnormal_dose_or_water` | Overflow / abnormal dose (cmd 8204) | Ensure a cup is under the dispenser before starting and don't remove it mid-brew. Espresso-fine grinds are not recommended for pour-over. |
| `abnormal_gear_position` | Grinder gear position (cmd 8203) | Run the grinder calibration (button or `calibrate_xbloom_grinder`). |

## Other official guidance (no BLE signal)

- **Bluetooth connection issues** — check the host's Bluetooth is on;
  quick-press the machine's **right knob three times** to restart it. The
  integration reconnects automatically once the machine is reachable.
- **Weighing value fluctuates while unloaded** — remove any factory
  protective tape, plug the machine directly into a wall outlet (power
  strips with ungrounded appliances destabilize the scale), and run the
  scale calibration (triple-press the center knob on the scale page).
