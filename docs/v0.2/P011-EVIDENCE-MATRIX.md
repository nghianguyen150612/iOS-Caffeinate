# P011 — Evidence matrix

The labels `CLOUD_VERIFIED`, `OPERATOR_REPORTED`, `DEVICE_VERIFIED`, `REVIEW_REQUIRED`, `PENDING`, and `BLOCKED` are summary concepts. Machine evidence continues to use the P009 source classes and gate states in `docs/schemas/device-acceptance-v1.schema.json` and `docs/schemas/device-acceptance-gates-v1.json`. No P009 validator or schema has been changed to permit hardware PASS results.

- `CLOUD_VERIFIED` describes release metadata, hashes, source, and CI only; it never maps to a hardware PASS.
- `OPERATOR_REPORTED` maps to P009 source class `OPERATOR_RECORDED` and normally leaves the affected gate `REVIEW_REQUIRED` until human review.
- `DEVICE_VERIFIED` is reserved for a physical observation with valid P009 provenance that has been reviewed. No P011 device gate currently has this status.
- `REVIEW_REQUIRED`, `PENDING`, `BLOCKED`, `INSUFFICIENT_EVIDENCE`, and `PASS` use the corresponding existing P009 states; `NOT_VALIDATED` and `UNVERIFIED` remain readiness labels already used by P009 reports.

| Claim or gate | Evidence currently available | P009-compatible state | P011 interpretation |
|---|---|---|---|
| Public release identity and package digest | v0.1.0 release asset metadata; package SHA-256 `439d2543adbe1472f82cfd6c9e6bb9dd747da6c31c79f3da1f3da86b8ca9421c` | Not a physical gate result | `CLOUD_VERIFIED` for release identity and digest only |
| Debian identity/version/architecture | Published release metadata and package control fields | Not a physical gate result | `CLOUD_VERIFIED` for `com.ioscaffeinate.cli`, `0.1.0-1`, `iphoneos-arm` |
| Package structure, Mach-O, maintainer scripts, sidecars, exact profile | The historical H002 run stopped before independent entitlement extraction. H003 rebuilt the exact signer, reran the H002 P011 command, and verified both embedded entitlement sets. | P009 `package_integrity_verified` remains `PENDING` until a physical package integrity event is collected | Host P011 is `PASS_DEVICE_ACCEPTANCE_PENDING`; signature integrity and device acceptance remain pending. The H003 receipt records the result. |
| Signature presence and profile | P010 says signature present, exact profile `amethyst-ios12-rootful`, exact profile SHA `cd1358e7c8c3b01da98b5544e3c2ffcdc9d92cf9a3191e45038e8691ef2021ca`, entitlement set exactly `com.apple.private.security.no-container=true` | `signature_acceptance_verified=PENDING` | Profile is specific to Amethyst/Procursus rootful; signature integrity remains `PENDING`; signature presence is not cryptographic trust |
| Installed-package signature acceptance | No P011 installation observation | Existing P010 operator record uses `INSUFFICIENT_EVIDENCE`; a new unevaluated P009 session stays `PENDING` | `PENDING` |
| Installed CLI/daemon execution and IPC | No installed-package run | `installation_verified=PENDING` | `PENDING` |
| IOKit create/release, 30-second expiry, STOP, SIGTERM cleanup | Operator-reported results from separately staged binaries on 2026-10-18 | Existing P010 record uses `DEVICE_REPORTED`/`OPERATOR_RECORDED`; P009 gates `REVIEW_REQUIRED` | `OPERATOR_REPORTED`; not P011 installed-package acceptance |
| Locked-screen LAN SSH | 24/24 operator-reported observations on 2026-10-18; some commands succeeded after assertion expiry | `REVIEW_REQUIRED`; no causal effect established | `OPERATOR_REPORTED`; keep separate from Tailscale and power claims |
| Locked-screen Tailscale SSH | 24/24 operator-reported observations on 2026-10-18; some commands succeeded after assertion expiry | `REVIEW_REQUIRED`; no causal effect established | `OPERATOR_REPORTED`; keep separate from LAN and power claims |
| No-assertion A/B/C/D comparison | Not performed | `independent_no_assertion_comparison=PENDING` in P009 readiness | `PENDING`; assigned to P012 |
| Battery/thermal impact | No measurements | P009 battery/thermal gates `PENDING` | `PENDING` |
| Long-duration reliability | Not measured | `unattended_24_7=NOT_VALIDATED` | `PENDING`; P019 owns supervised reliability validation |
| Scheduled wake | No device observation | `scheduled_wake=UNVERIFIED` | `PENDING` |
| Package removal and rollback | No package install/removal or rollback | `rollback_verified=PENDING` | `PENDING`; requires prior verified artifact and physical recovery |
| LaunchDaemon activation | No activation is authorized; package contains only staged disabled template | P009 `launchd_remains_disabled=PENDING` until device observation | Must remain inactive; P013 handles lifecycle management |

The existing operator record is `docs/evidence/P010-OPERATOR-REPORTED.json`. It has no raw device logs or independent provenance files, so human review remains required. Its reported observations must not be rewritten as package-installed or device-verified results.

## Collection and review

Use the P009 session template and run only the existing P009 utilities after replacing placeholders with genuine observations:

```sh
python3 scripts/p009_evidence.py manifest /path/to/p011-session
python3 scripts/p009_evidence.py validate /path/to/p011-session
python3 scripts/p009_evidence.py replay /path/to/p011-session --json
python3 scripts/p009_evidence.py report /path/to/p011-session --format json
```

P009 integrity hashes establish file consistency, not observer identity or truth. Human review must inspect provenance, timebases, original outputs, installed artifact identity, and cleanup results before any gate is upgraded.
