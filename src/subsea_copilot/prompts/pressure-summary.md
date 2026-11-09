---
prompt_id: subsea.pressure-summary
version: 1.0.0
---
recent_pressure_drop_bar and recent_5s_pressure_drop_bar equal baseline_median minus typical usable pressure in their named periods. Both use the same supplied normal-baseline reference, not a completed field verification: positive means below that reference, negative means above normal. Use recent_5s_pressure_drop_bar for current normal-relative pressure statements and label the final five seconds. recent_pressure_drop_bar covers twenty seconds, not five. The five-second value is not another within-recording comparison. median_pressure_drop_bar is a screening aggregate of qualifying drops when persistent, otherwise all usable readings; it is not necessarily the current pressure.
