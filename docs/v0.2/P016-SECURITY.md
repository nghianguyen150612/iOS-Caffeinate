# P016 — Security and Privacy

Health commands are read-only. `health battery`, `health thermal`, `health doctor`, and `health sources` do not contact another process. `health status` uses only the existing local `SERVER STATUS` Unix-socket IPC with bounded read/write timeouts. It adds no IPC command or endpoint.

The platform layer reads `mach_continuous_time()` and `KERN_BOOTTIME`; it does not invoke IOKit sensor enumeration, shell utilities, network probes, launchctl, service lifecycle actions, or power assertion APIs. It never sets `UIDevice.batteryMonitoringEnabled`. No telemetry file is written. Measurements are held only in the process memory used for that diagnostic command.

Output contains source names, measurements where valid, timestamps, status, and bounded daemon diagnostics. It does not include credentials, keys, tokens, arbitrary environment values, memory contents, kernel addresses, or unnecessary hardware identifiers. The telemetry configuration has no executable paths or external commands.

Linux providers and tests use explicit `MOCK` or simulated data. They are not labeled device observations and cannot satisfy a P015 or P009 hardware gate.
