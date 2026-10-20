# P013 — Package Integration

The package remains `com.ioscaffeinate.cli`, architecture `iphoneos-arm`, with the existing `ios-caffeinate`, `ios-caffeinated`, and `ic` identities. The P013 C module is linked into the CLI for iOS and the Linux mock build.

The package builder continues to stage only the immutable template at `/usr/share/ioscaffeinate/launchd/com.ioscaffeinate.daemon.plist`. It does not include a plist under `/Library/LaunchDaemons`, does not seed enablement state, and does not run a launchctl command. `preinst` remains a collision and layout check; it does not enable or start the daemon.

The staged plist remains `Disabled=true`, `RunAtLoad=false`, and `KeepAlive=true` for compatibility with the existing package contract. P013's separately generated managed live profile is `Disabled=false`, `RunAtLoad=false`, and `KeepAlive=false`. That conservative profile avoids an uncontrolled restart loop; its actual iOS 12 load/start semantics remain unverified.

`prerm` still rejects an existing default daemon endpoint. It additionally rejects a live plist and uses `ic service status` as a read-only check that registration, runtime, and IPC are positively clear. Unknown status blocks removal or upgrade. It never deletes service files, schedules, server policy, evidence, or logs. A package with an active or uncertain launchd job must be explicitly disabled and verified before removal.

Package installation, upgrade, removal, package verification, and P013 CI do not activate launchd. The stable `v0.1.0` release tag and assets are unchanged. See the [device acceptance gate](P013-DEVICE-ACCEPTANCE.md) and [rollback procedure](P013-ROLLBACK.md).
