# P016 — Health and Resource Observation Architecture

P016 adds an on-demand, read-only observation model for device uptime, battery and charging availability, thermal availability, and existing daemon health. It does not add a second daemon, polling loop, persistent telemetry file, or privileged endpoint.

## Data path

```text
Platform provider → normalization and validation → freshness → CLI presentation
                                               ↘ P015 diagnostic adapter
Existing server-status IPC ────────────────────↗
```

- `src/health_ios.c` isolates platform acquisition. It exposes iOS device uptime through `mach_continuous_time`; battery and thermal values remain unavailable where the public API cannot distinguish missing data from a valid reading.
- `src/health.c` owns the version 1 snapshot types, strict range checks, source metadata, freshness evaluation, and conservative state normalization. It has no policy or filesystem access.
- `src/health_policy.c` copies valid readings into the existing P015 diagnostic fields. It never creates a P009 `PASS`. Only an already verified, current `CRITICAL` device-reported thermal result can add a P015 `UNSAFE` blocker.
- `ic health status` may issue the existing bounded `SERVER STATUS` Unix-socket query. It reports daemon uptime, state, assertion ownership and remaining hold, acquisition/release timestamps, release failure, recent errors, schedule state, P014 recovery and supervisor fields. It does not infer iOS awake state, SSH reachability, assertion cleanup by a dead process, or launchd persistence.

For an explicit P012 association, `ic health status --trial-id ID --condition-id A|B|C|D --outside-quiet-interval` includes the validated trial and condition identifiers in the output. It requires an operator assertion that the measurement is outside a quiet interval, records the device observation timestamps, and writes no P012 record. Independent host-observer time remains separate and must come from the P012 host procedure.

The model separates API discovery, acquisition, value validity, freshness, physical-source verification, safety review, and P009 acceptance. CI and host fixtures are labeled `MOCK`; none is described as an iPad reading. Unknown and unavailable values remain explicit.

## iOS 12 source decisions

`UIDevice` battery properties are unavailable while battery monitoring is disabled. Enabling monitoring changes process state, so the CLI does not enable it. `NSProcessInfo.thermalState` is public on iOS 11+, but the iOS 12 SDK says unknown or unsupported thermal state returns `NOMINAL`; that behavior cannot be distinguished from an actual nominal observation, so P016 rejects the API. No battery temperature or health metric is fabricated.

`mach_continuous_time()` is public from iOS 10 and advances during sleep. P016 uses it for a monotonic boot-scoped clock and device uptime. `sysctl(KERN_BOOTTIME)` supplies the boot time identity when the kernel permits the read. Both paths are included in the configured iPhoneOS cross-build; compile compatibility will be established by exact-head CI, while device behavior remains `RUNTIME_UNVERIFIED` until run on the reference iPad.

See the [capability matrix](P016-IOS12-CAPABILITY-MATRIX.md), [schema](P016-TELEMETRY-SCHEMA.md), [freshness rules](P016-FRESHNESS.md), and [policy adapter](P016-POLICY-INTEGRATION.md).
