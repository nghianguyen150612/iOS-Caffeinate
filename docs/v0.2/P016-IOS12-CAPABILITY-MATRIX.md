# P016 — iOS 12 Capability Matrix

Target: iPad mini 2 A1489, Apple A7 ARM64, iOS 12.5.7, Amethyst/Procursus rootful. The iPhoneOS 12.4 public SDK headers were inspected for availability and fallback semantics. The exact-head workflow cross-build is configured; compile status remains pending until that job passes. No API below is device-runtime verified until observed on the iPad.

| Candidate | Availability and library | Units and permissions | Read-only decision | Runtime status |
|---|---|---|---|---|
| `mach_continuous_time()` / `mach_timebase_info()` | Public Mach headers; iOS 10+; `libSystem` | Hardware ticks converted to nanoseconds/seconds; no additional entitlement | Implemented for monotonic time and device uptime; advances during sleep | `RUNTIME_UNVERIFIED` |
| `sysctl(KERN_BOOTTIME)` | `sys/sysctl.h` exposes `CTL_KERN` and `KERN_BOOTTIME`; iOS SDK | `struct timeval`; no new entitlement documented | Read only; used to scope monotonic timebase identity | `RUNTIME_UNVERIFIED`; identity falls back to an explicit unknown string if denied |
| `UIDevice.batteryLevel` | UIKit; iOS 3+ | Float 0.0–1.0; `-1.0` when battery state is unknown | SDK says battery state is unknown when monitoring is disabled. Enabling `batteryMonitoringEnabled` mutates per-process state, so P016 does not enable it or report a percentage | `UNAVAILABLE` |
| `UIDevice.batteryState` | UIKit; iOS 3+ | Unknown, unplugged, charging, full | Same monitoring requirement; no source is read by the C CLI | `UNAVAILABLE` |
| `NSProcessInfo.thermalState` | Foundation declaration; iOS 11+ | Nominal, fair, serious, critical | SDK declaration inspected but no call is compiled or linked. Rejected: the iOS 12 SDK documents `NOMINAL` as the return value when the state is unknown or unsupported. It cannot distinguish a genuine nominal observation from missing support | `UNAVAILABLE` |
| `IOPSCopyPowerSourcesInfo` / IOPowerSources | Public macOS power-source API family; not established as a public iOS 12 source | Battery source properties vary by platform | Not called; macOS availability is not evidence of iOS availability | `UNSUPPORTED_FOR_TARGET` |
| IOKit registry battery properties | Registry keys are private/platform-specific and can require entitlements | Units and semantics vary | Not read; no private entitlement or registry probe is added | `UNSUPPORTED_FOR_TARGET` |
| `pmset`, `upower`, other Procursus utilities | Installation and iOS 12 semantics are not established | Utility-specific | Never invoked or searched automatically | `UNAVAILABLE` |
| Existing `SERVER STATUS` daemon IPC | Existing local Unix socket protocol | Daemon seconds, state counters and timestamps | Read-only bounded query; no sensor or OS-awake claim | Available only when the existing daemon answers; hardware semantics remain separately verified |

SDK header references inspected: [`NSProcessInfo.h`](https://raw.githubusercontent.com/xybp888/iOS-SDKs/master/iPhoneOS12.4.sdk/System/Library/Frameworks/Foundation.framework/Headers/NSProcessInfo.h), [`UIDevice.h`](https://raw.githubusercontent.com/xybp888/iOS-SDKs/master/iPhoneOS12.4.sdk/System/Library/Frameworks/UIKit.framework/Headers/UIDevice.h), [`mach_time.h`](https://raw.githubusercontent.com/xybp888/iOS-SDKs/master/iPhoneOS12.4.sdk/usr/include/mach/mach_time.h), and [`sysctl.h`](https://raw.githubusercontent.com/xybp888/iOS-SDKs/master/iPhoneOS12.4.sdk/usr/include/sys/sysctl.h). CI's iOS cross-build records compile compatibility only, not runtime verification.

Battery cycles, maximum capacity, wear, numeric battery temperature, CPU temperature, and charging-controller values are not available from P016. No API failure is normalized to `NOMINAL` or a fabricated number.
