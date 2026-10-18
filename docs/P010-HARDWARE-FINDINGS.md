# P010 — Hardware Findings

## Evidence class and scope

This record transcribes operator-supplied observations from October 18, 2026. The repository does not contain the original device logs, observer log, binary hashes, signer hash/version, profile hash from the test, or independent provenance records. Therefore these are **operator-reported observations**, not independently reviewed P009 hardware evidence. The summary is preserved in [P010-OPERATOR-REPORTED.json](evidence/P010-OPERATOR-REPORTED.json); its digest identifies that summary file only, not raw device evidence.

Target: iPad mini 2 A1489, Apple A7 ARM64, iOS 12.5.7, Amethyst/Procursus rootful. The P010 source baseline is `67d2aa8d7009770822ea1bd8dc48a546fe63a64b`. The exact tested binary source commit and tested binary hashes were not supplied.

## Signing and execution observation

The original binaries were signed with `ldid -S` and exited with code 137. The kernel reported `process-exec denied while updating label`. The reported failure occurred both on a separate APFS volume and below `/private/var/tmp`.

Fresh binary copies were then signed using `ldid -S<entitlements.plist>`. The supplied profile contained exactly:

```xml
<dict>
    <key>com.apple.private.security.no-container</key>
    <true/>
</dict>
```

With that profile, CLI help and wake diagnostics returned 0, the daemon started in foreground, and SIGINT shutdown completed. This supports the entitlement's effectiveness in the tested bootstrap context. It does not establish a universal requirement across jailbreaks. No tested profile hash or signer identity was recorded.

## IOKit observation

Both `IOPMAssertionCreateWithName` and `IOPMAssertionRelease` resolved. Reported successful lifecycle results:

| Observation | Assertion | Reported result |
|---|---:|---|
| Probe acquire/release | 33628 | Acquired and released |
| Timed hold | 33700 | Released after 30 seconds |
| Explicit STOP | 33701 | Released |
| Timed hold | 33702 | Released after 60 seconds |
| SIGTERM cleanup | 33720 | Acquired at local 20:11:50, released at 20:11:52; socket/process cleanup succeeded |
| Locked-screen network trial | 33721 | Acquired at local 20:15:01, released at 20:18:01 after 180 seconds |

The time zone and raw event logs were not supplied. Successful native calls establish the reported assertion lifecycle; they do not prove prevention of deep sleep.

## Locked-screen networking observation

The operator confirmed that the display stayed locked during an SSH observation from an independent Arch Linux machine, approximately 20:16:09–20:18:25 local time. The report says 24/24 authenticated LAN SSH commands and 24/24 authenticated Tailscale SSH commands succeeded. Some commands succeeded after assertion expiry. Historical addresses are omitted from this record.

These results establish reported reachability during the observed interval. They do not establish that iOS-Caffeinate caused connectivity to remain available. The no-assertion baseline is still pending, and LAN and Tailscale remain separate measurements.

## P009 review disposition

The normalized findings bundle is generated with:

```sh
python3 scripts/p010_evidence.py prepare --output-dir dist/p010-operator-evidence
```

It creates a summary attachment and bundle metadata that labels the origin `OPERATOR_RECORDED`, sets review to `REVIEW_REQUIRED`, and lists raw evidence and provenance as absent. Its hash covers the normalized summary only. It is not a P009 acceptance session and cannot pass any hardware gate. To use P009, create a session from [the P009 template](templates/device-acceptance-v1.template.json), add genuine classified records and supporting files, then run the P009 validation, replay, report, and interactive review commands. A JSON review field never approves itself.

Execution, IOKit lifecycle, cleanup, and locked-screen SSH claims remain `REVIEW_REQUIRED`. Package integrity, signature acceptance, installation, and rollback remain `INSUFFICIENT_EVIDENCE`. The no-assertion comparison, battery/thermal behavior, scheduled wake, and long-duration reliability remain pending or unverified.
