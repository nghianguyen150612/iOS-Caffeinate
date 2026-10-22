# P016 — Thermal Observations

P016 reports thermal state as `UNKNOWN` / `UNAVAILABLE` on iOS 12.5.7. The public `NSProcessInfo.thermalState` property exists from iOS 11, but the iOS 12 SDK header explicitly states that unknown or unsupported thermal state returns `NSProcessInfoThermalStateNominal`. A caller cannot tell that fallback from a real nominal state. P016 therefore does not use the property as safety evidence.

No private registry key, undocumented sensor utility, processor-frequency estimate, or numeric temperature is used. Thermal state categories are not degrees Celsius. A thermal read failure never becomes `NOMINAL`.

The core normalization tests preserve `NOMINAL`, `FAIR`, `SERIOUS`, and `CRITICAL` as mock platform categories; `FAIR` and `SERIOUS` normalize to `ELEVATED` while their raw category remains available. These tests validate mapping logic only. They do not indicate that iOS 12 currently supplies those observations through this CLI.

Use `ic health thermal` or `ic health doctor` to see availability. `CRITICAL` can add a P015 resource blocker only when a current device-reported source has separately verified physical provenance. It cannot pass the P015 gate or authorize a session.
