# P016 — Battery Observations

The current iOS adapter reports battery percentage and charging state as `UNAVAILABLE`. This is intentional. In the iOS 12.4 UIKit header, `batteryState` is `Unknown` when battery monitoring is disabled and `batteryLevel` is `-1.0` for an unknown battery state. Monitoring defaults to disabled; enabling it would change the process' monitoring state and violate P016's strictly read-only contract.

The CLI does not infer charging from a steady percentage. It does not write controller state, alter charging limits, or change power management. Battery cycles, capacity, health, wear, and temperature are not promised.

Use:

```sh
ic health battery
ic health sources
```

When a source is unavailable, the command prints a null-like `UNAVAILABLE` value, its source and reason, and exits with status `3`. A valid observed zero remains `0`; it is not treated as missing. Future battery support requires a public read-only interface that works without enabling monitoring, followed by iPad runtime verification and P009 review.
