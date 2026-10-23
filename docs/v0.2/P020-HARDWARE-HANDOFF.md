# P020 Hardware Handoff

**Current target:** iPad mini 2 A1489 (`iPad4,4`), Apple A7 ARM64, iOS 12.5.7, Amethyst/Procursus rootful. Cloud work must not connect to the target, install a package, run device tests, reboot, or respring.

The separately authorized H004 Phase 0 read-only baseline may precede this sequence. It records existing state only and does not satisfy P011 acceptance or waive any prerequisite below.

## Required sequence

1. Resolve and independently verify the pinned P010 `ldid` executable identity and origin, then verify the approved entitlement profile bytes.
2. Complete P011 acceptance of the existing v0.1 stable package, including installed paths, runtime, cleanup, preservation, and rollback readiness.
3. Prepare a separately reviewed v0.2 development candidate after signer provenance is verified.
4. Verify exact source, package, CLI, daemon and signing hashes against the candidate provenance manifest.
5. Under attended authorization, perform supervised P013/P014 runtime, graceful stop, assertion cleanup, recovery, and state-preservation acceptance.
6. Review P016 battery/charging/thermal source availability and safe operating conditions; unavailable remains unavailable.
7. Conduct the registered 24 P012 controlled trials with separate LAN/Tailscale reporting and valid P009 evidence.
8. Conduct the P019 12 supervised bounded cycles across three attended dates; confirm acquire/release for every accepted cycle, rest intervals, cleanup, and no unexpected exit/restart.
9. Independently review unchanged P009 original evidence and the separately hashed P018 sanitized derivative. A derivative hash does not prove the observation occurred.
10. Independently evaluate the exact P020 source and complete release manifest, including security findings, limitations, and rollback review.
11. Obtain explicit human authorization before any stable publication.

A failed safety, cleanup, provenance, or critical security gate stops progression. Do not convert a missing observation to success, infer continuous awake time from SSH responses, or use mock/simulated data as device acceptance.

## H002/P011 compatibility result

The official v0.1.0 release API and all eight asset digests were checked. The exact package archive SHA, seven historical checksum records, complete historical layout, Debian metadata, original build/signing metadata, profile bytes, Mach-O properties, and maintainer-script safety passed host inspection. The release never contained a complete payload checksum manifest; H002 uses a post-publication derived inventory only to verify the byte-pinned archive's layout and expose its 52 historically uncovered regular members. P020's strict full-file coverage rule remains required for v0.2 candidates.

P011 remains blocked because the exact H001 `ldid` executable and receipt files were not present in the engineering workspace. Its published version/SHA metadata matches the pinned H001 identity, but independent signer executable verification and embedded entitlement extraction are pending. Signature integrity remains `PENDING`; P011 device package acceptance remains `PENDING`. No iPad inspection or package installation was performed.

## H003 current host result

H003 subsequently rebuilt the exact Procursus source commit in a newly pinned Ubuntu environment. Two independent builds produced the P010 signer SHA-256 `15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c`; both embedded entitlement sets in the published v0.1.0 package were independently extracted and matched the approved profile. The H002 P011 command exited `0` with `P011_HOST_PREFLIGHT_PASS_DEVICE_ACCEPTANCE_PENDING`. The full result and reproducible build receipt are in [H003-P011-HOST-PREFLIGHT.json](H003-P011-HOST-PREFLIGHT.json) and [H003-SIGNER-PROVENANCE.json](H003-SIGNER-PROVENANCE.json).

This H003 observation updates the present host-side signer/provenance state only. The historical H002 result above is preserved. The H001 historical image digest and snapshot receipt were not recovered, so H003 documents its new environment without presenting it as H001's former environment. Signature integrity and P011 device package acceptance remain `PENDING`; release authorization remains `BLOCKED`. No iPad was accessed, no package was installed, no service or assertion was activated, and no release was changed.

The H004 Phase 0 baseline is a separate, earlier read-only inspection and may precede P011 physical acceptance under its own checklist. Any later P019 session still requires separate P011 physical acceptance and the P019 prerequisites; use the existing [P019 operator runbook](P019-OPERATOR-RUNBOOK.md). Neither host receipts nor H004 authorizes those later actions.

## Current hardware state

- H003 host signer provenance: verified for the exact P010 executable hash using the newly documented environment; historical H001 environment receipt remains unavailable.
- P011 stable package acceptance: pending.
- P012 physical 24-trial observations: none accepted.
- P013 launchd lifecycle acceptance: pending; mutations remain disabled.
- P014 physical recovery acceptance: pending; no production restart executor exists.
- P016 resource review: pending; battery/thermal sources may remain unavailable.
- P019 physical session: none accepted; no accepted P019 trial observations.
- P009 independent provenance review: pending; raw evidence remains private and unchanged.

Do not perform scheduled assertion execution, unattended Server Mode, automatic restart, reboot persistence checks, or deep-sleep wake claims under this handoff.
