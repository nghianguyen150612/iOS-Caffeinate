# P013 — Manifest

- Milestone: P013, Opt-in LaunchDaemon Lifecycle Management
- Branch: `ios/p013-launchd-lifecycle`
- Effective base: exact P012 head `f459e332deefb134b6725c1455c5721830d0bb3a`
- PR base: `ios/p012-controlled-idle-power-research`
- CLI identity: `ios-caffeinate` / `ic`
- Daemon identity: `ios-caffeinated`
- Package identity: `com.ioscaffeinate.cli`
- Package architecture: `iphoneos-arm`
- Managed label: `com.ioscaffeinate.daemon`
- Staged template: disabled; retained under `/usr/share/ioscaffeinate/launchd`
- Managed profile: `Disabled=false`, `RunAtLoad=false`, `KeepAlive=false`
- Launchctl mutation compatibility: `UNVERIFIED` on iOS 12.5.7
- Device lifecycle: `PENDING`
- Boot persistence: `UNVERIFIED`
- Power assertion during enable/start: `NOT_REQUESTED`
- Automatic package activation: `NO`
- Stable v0.1.0 tag/assets: unchanged
- P014 crash recovery: deferred; no watchdog or indefinite relaunch policy added
- Source SHA and exact CI run: recorded by the `p013-launchd-lifecycle-validation` workflow artifact for each run

The manifest is cloud engineering evidence only. It does not certify physical service operation or a 24/7 server mode.
