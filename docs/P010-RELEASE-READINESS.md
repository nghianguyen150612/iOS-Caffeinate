# P010 — Release Readiness

P010 cloud readiness separates source/CI evidence, operator-reported physical observations, P009-reviewed hardware gates, and target-device package acceptance. The detailed observations are in [P010 hardware findings](P010-HARDWARE-FINDINGS.md); the exact-source CI manifest is generated as an Actions artifact.

## Gate matrix

| Gate | Status | Evidence class / next requirement |
|---|---|---|
| CLI native execution | Observed PASS | Operator report; P009 review still required |
| Daemon foreground execution | Observed PASS | Operator report; P009 review still required |
| IOKit acquire/release | Observed PASS | Operator report; P009 review still required |
| Timed expiry | Observed PASS | Operator report; P009 review still required |
| Explicit STOP | Observed PASS | Operator report; P009 review still required |
| SIGTERM cleanup | Observed PASS | Operator report; P009 review still required |
| Locked-screen LAN SSH | Observed PASS, 24/24 | Operator report; independent evidence review required |
| Locked-screen Tailscale SSH | Observed PASS, 24/24 | Operator report; independent evidence review required |
| No-assertion comparison | PENDING | Controlled A/B/C/D procedure in [device acceptance](P010-DEVICE-ACCEPTANCE.md) |
| Signed rootful package candidate | Separate local gate | Build only from the exact-source CI artifacts with the opt-in profile; inspect that candidate's generated manifest |
| Host signature integrity | PENDING | Requires host verifier; signature presence is a separate state |
| Signed package installation | PENDING | Requires separate authorization and supervised target install |
| Rollback acceptance | PENDING | Requires eligible prior package, backup, and supervised verification |
| Battery/thermal characterization | PENDING | Requires physical observations |
| Scheduled wake | UNVERIFIED | No supported capability established |
| 24/7 reliability | NOT VALIDATED | No long-duration unattended test |
| RC1 release authorization | BLOCKED | Signed package/device acceptance and evidence review remain open |
| Device-accepted stable v0.1.0 certification | BLOCKED | Package installation and operational gates remain unverified; publishing a public stable-channel tag does not satisfy them |

## Release artifacts and authorization

Public-facing intended prerelease: `v0.1.0-rc1`. Debian version: `0.1.0~rc1-1`, which sorts before `0.1.0-1`. Hosted CI remains unsigned and clearly labeled. Its manifest records the exact source SHA and unsigned artifact hashes. A local signed candidate is a separate artifact; its generated package manifest is the authoritative source for signed binary/package hashes and signer identity.

No package is installed on the iPad, and no GitHub Release or tag is created. Release authorization remains blocked. Passing CI or producing a signed candidate does not establish device trust, package acceptance, network causality, scheduled wake, or long-duration reliability.

## Maintainer-directed public stable channel

The repository maintainer explicitly requested an official public `v0.1.0` GitHub stable release while the device package acceptance gates remain pending. The release pipeline retains the exact signing, source, CI and package verification safeguards and publishes unambiguous `SIGNED-DEVICE-UNVERIFIED` payloads; publication **does not** change these P010 engineering gate results. The release notes disclose missing package installation, upgrade/removal, rollback, long-term reliability and scheduled-wake proof. Distinguish the public GitHub release channel from a device-accepted/stability-certified build.
