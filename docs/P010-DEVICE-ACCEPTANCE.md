# P010 — Supervised Package Acceptance and Idle Comparison

This is a manual procedure for the target iPad mini 2 A1489 on iOS 12.5.7 / Amethyst-Procursus rootful. Cloud implementation does not authorize installation. Do not install until the operator separately authorizes the supervised session and a direct physical recovery path is present. Keep launchd disabled and never conduct an unattended test.

## Artifact preflight

1. Retrieve the exact P010 `ios-cross-build` binaries and unsigned rootful package from the same successful workflow run. Confirm the workflow source SHA and `iphoneos-arm` package architecture.
2. On the build host, use the exact source commit and package version `0.1.0~rc1-1`. Confirm the input `SHA256SUMS`, signing profile ID/hash, ldid version/hash, source binary hashes, final signed binary hashes, `.deb` hash, and sidecars. Generate `P010-SIGNED-CANDIDATE-MANIFEST.json` as documented in [P010 signing](P010-SIGNING.md); it must link the signed output back to the unsigned CI hashes and exact workflow SHA.
3. Run the signed-package validation command in [P010 packaging validation](P010-PACKAGING-VALIDATION.md). Stop if entitlement extraction, source identity, package metadata, hashes, inactive launchd, or maintainer-script review fails. A host signature-integrity result is not device acceptance.
4. Before moving the package, verify on the device that `dpkg --print-architecture` returns exactly `iphoneos-arm`. Check file ownership/collisions, current daemon and socket state, SSH/Tailscale baseline, available space, and package scripts. Do not bypass a failed maintainer-script safety check.
5. Record an existing-state backup and confirm direct physical recovery that does not depend on SSH or Tailscale. Keep the operator beside the device.

## Manual installation boundary

Only after the separate human authorization and every preflight above, the operator may transfer the exact package and verify its SHA-256 again. Review package metadata and scripts on device before installation. The manual installation command is:

```sh
dpkg -i /path/to/verified/ioscaffeinate_0.1.0~rc1-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb
```

This command is documented for a later supervised session; P010 cloud work does not execute it. Record `dpkg` output, then confirm package name/version and run:

```sh
/usr/local/libexec/ioscaffeinate-manager verify
/usr/local/bin/ios-caffeinate --help
/usr/local/bin/ios-caffeinate wake status
/usr/local/bin/ios-caffeinate status
```

Check that `/usr/local/bin/ios-caffeinate` and `/usr/local/bin/ios-caffeinated` execute from their installed paths. Confirm no active LaunchDaemon and no change to SSH/Tailscale configuration.

Manually start `/usr/local/bin/ios-caffeinated --foreground` only after diagnostics pass. Run `ios-caffeinate probe`, then supervise one short `ios-caffeinate start --for 30s` assertion. Verify STOP and natural expiry in separate bounded trials. Verify SIGTERM release and process/socket cleanup. Do not continue if release or cleanup is unresolved. Record battery/thermal state and preserve user schedules, server policy, logs, and evidence. No package script starts the daemon.

## Controlled no-assertion comparison

The research question is whether a native assertion changes SSH reachability while the iPad is idle. Compare four attended conditions, with LAN and Tailscale analyzed separately:

| Condition | Device state |
|---|---|
| A | Display locked, daemon stopped, no assertion |
| B | Display locked, daemon available, no active assertion |
| C | Display locked, daemon available, one bounded active assertion (at most 300 seconds) |
| D | Display locked, after confirmed expiry or release |

Keep or record charging state, battery level, Wi-Fi network, Tailscale state, screen state, foreground/background context, observer machine, probe timing, idle duration, SSH authentication result, and unexpected user interaction. Use the same device setup and independent observer for each condition. A and B are separate baselines; daemon availability is not the same as an active assertion.

For each condition, first leave a quiet interval with **no incoming SSH probes** so polling does not itself disturb idle behavior. Then make separate, sparse LAN and Tailscale measurements and record each result. Do not run continuous polling, leave a persistent observer, or infer prevention of sleep from connectivity after release. If user interaction occurs or a trial is interrupted, record it and repeat only as a new attended trial with recovery present. Do not run this experiment automatically.

## Rollback and closeout

Rollback is a separate supervised operation. Before starting, verify the prior package artifact and matching checksum, supported version ordering, a data backup, dpkg architecture, physical recovery, and that the daemon has stopped and the assertion/socket cleanup is complete. Run `/usr/local/libexec/ioscaffeinate-manager rollback-check /path/to/previous.deb`, inspect the prior package and P007 rollback procedure, then proceed only if every prerequisite passes. Verify preserved user state and logs after removal or downgrade. Do not overwrite state, force package scripts, or treat an untested rollback as accepted.

After installation and any rollback, export sanitized P009 evidence. The session's observations must identify source classes and timebases; attach original supporting files where available. Run P009 validation, replay, report, and human review. The P010 operator summary alone cannot pass package acceptance.
