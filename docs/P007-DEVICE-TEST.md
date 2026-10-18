# P007 Deferred Device Installation and Runtime Procedure

**P007 snapshot: package procedure not executed at that milestone.** The target iPad was unavailable then. P010 later records operator-reported binary execution and assertion results, but no `.deb` installation has been performed. Do not treat CI output as package acceptance. Do not run an unattended 24/7 test; follow [P010 device acceptance](P010-DEVICE-ACCEPTANCE.md).

## Pre-install checks

1. Confirm the physical device is an iPad mini 2 A1489 with Apple A7, iOS 12.5.7, and the intended Amethyst/Procursus **rootful** environment. Record the jailbreak and package-manager versions.
2. Run `dpkg --print-architecture`; require exactly `iphoneos-arm`. Stop if it reports another value, including `iphoneos-arm64`.
3. Check free space with the device's available filesystem tools. Confirm direct physical access, a working passcode/recovery path, and a way to recover if SSH or the jailbreak becomes unavailable.
4. Save a package inventory and identify existing files or packages owning `/usr/local/bin/ios-caffeinate`, `/usr/local/bin/ios-caffeinated`, `/usr/local/bin/ic`, `/usr/local/libexec/ioscaffeinate-manager`, and `/usr/share/ioscaffeinate`. The package `preinst` refuses unowned file collisions and unsafe package directories; do not override that refusal to force installation.
5. Record relevant original package versions and inspect those paths. Verify existing SSH and Tailscale separately before installation; do not use this package to modify either service.
6. Follow the current [P010 artifact and signing procedure](P010-DEVICE-ACCEPTANCE.md). The P010 RC uses package version `0.1.0~rc1-1`; CI artifacts remain unsigned. Verify the exact package hash and signature/profile evidence before inspection. Presence of `LC_CODE_SIGNATURE` alone is not acceptance evidence.
7. Check that the live launchd destination `/Library/LaunchDaemons/com.ioscaffeinate.daemon.plist` is absent or record its owner and state. P007 package installation must not place a file there.

## Install verification

Installation is a separate, explicitly authorized device action. Before it, read package control fields, payload, maintainer scripts, package/binary hashes, and the P010 validation report. A CI package is unsigned. Do not install it until the P010 signing and acceptance requirements have been met. `ldid -h` reports metadata only; it does not verify a signature or establish device acceptance.

After those gates pass, use the device's root shell and the verified artifact path:

```sh
dpkg -i /path/to/verified/ioscaffeinate_0.1.0~rc1-1_iphoneos-arm_SIGNED-DEVICE-UNVERIFIED.deb
```

The example filename applies only to an explicitly signed artifact. If the package is still unsigned, stop at the signing gate. Dpkg and `preinst` must both accept the `iphoneos-arm` architecture. Do not force an architecture mismatch. P010 cloud work does not run this command.

After installation, inspect package status and `dpkg --print-architecture`, then run:

```sh
/usr/local/libexec/ioscaffeinate-manager status
/usr/local/libexec/ioscaffeinate-manager verify
/usr/local/libexec/ioscaffeinate-manager doctor
ic wake status
ic server status
ic server doctor
```

Check root ownership and expected modes for both executables, manager, alias, data/log directories, and staged plist. Verify hashes against `/usr/share/ioscaffeinate/SHA256SUMS`. Confirm `ic` is a symlink to `ios-caffeinate`, no configuration files were created, the launchd template is staged and disabled, and the live LaunchDaemons path remains unchanged. Confirm SSH and Tailscale still work independently.

CLI diagnostics are a smoke test; they do not call IOKit or establish assertion behavior. Do not load launchd. A foreground daemon trial requires separate authorization and an attended recovery plan.

## Bounded runtime validation

Perform only after the install checks pass, with physical recovery available and a separately approved test window.

1. Start the daemon manually in the foreground. Do not use `launchctl` or enable a persistent service.
2. Use the CLI to request one 30–60 second bounded assertion. Record the start, status, expiry, and release observations.
3. Verify IOKit assertion creation and release. Test explicit STOP, natural expiry, and SIGTERM cleanup in separate runs. Confirm the daemon reports release failure as unresolved if the IOKit release fails; do not convert that into a successful package test.
4. Confirm no assertion remains after each trial using the best available device evidence. Do not record raw assertion IDs as recovery tokens.
5. With screen lock controlled and documented, measure authenticated LAN SSH reachability and Tailscale reachability in separate trials. Record timestamps, latency, lock state, and connection result independently. A successful CLI command or package install does not establish either network path.
6. Record battery level/charging and thermal observations before and after each bounded trial. Stop on unexpected heat, battery drain, loss of access, or uncertain release state.
7. If a release is uncertain, stop further trials, keep launchd disabled, preserve logs/state, and record the unresolved physical recovery issue.

## Rollback

Use [P007 rollback](P007-ROLLBACK.md). Stop the manually run daemon, verify the assertion was released, check that no default endpoint remains, and verify the previous `.deb` plus its matching SHA-256 sidecar before any downgrade. Keep the launchd template disabled, preserve user state, and report any unresolved assertion or access issue. Do not claim rollback succeeded based only on dpkg status.

## Required evidence and pending gates

Record device model, iOS, jailbreak/package-manager versions, dpkg architecture, artifact hash/signing state, package version, file ownership/modes, command outputs, timestamps, screen-lock state, independent LAN/Tailscale observations, battery/thermal observations, and physical recovery results. Redact credentials and do not include personal tokens.

P010 records operator-reported iOS execution, IOKit create/release, cleanup, and locked-screen LAN/Tailscale observations; they remain subject to P009 evidence review. Signed package installation, upgrade/removal, rollback, no-assertion comparison, battery/thermal behavior, and long-duration operation remain pending or unvalidated. Use [P010 release readiness](P010-RELEASE-READINESS.md) for the current gates.
