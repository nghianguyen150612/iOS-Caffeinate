# H004 — Supervised Device Phase 0 Read-only Checklist

**Status: preparation only.** This procedure has not accessed the iPad. It authorizes no device connection or action. A physically present operator must separately approve this narrow inspection scope before carrying it out. Do not transfer files to the iPad, use SSH or Tailscale, or execute any device command as part of preparing this package.

Phase 0 records the device's existing state. It is not P011 installation or acceptance, P018 export, P019 reliability testing, or a release decision. Keep all host-side H003 evidence separate from actual device observations.

## Host prerequisites checked

- Requested repository head: `fb39559766144ab0cf4327273ff3188c58200b6b` (H003).
- Exact-head pull request run [39798613948](https://github.com/nghianguyen150612/iOS-Caffeinate/actions/runs/39798613948) (`iOS-Caffeinate CI`) concluded `success` on that SHA. The run's 18 jobs include the P011–P020 validation jobs; `p008-release-attestation` was skipped. The P020 readiness job succeeded while confirming `RELEASE_BLOCKED`. The separate H003 host-preflight run [39798613926](https://github.com/nghianguyen150612/iOS-Caffeinate/actions/runs/39798613926) concluded `success` on the same SHA. These runs validate host/source work only.
- H003 P011 host receipt: `P011_HOST_PREFLIGHT_PASS_DEVICE_ACCEPTANCE_PENDING`, command exit `0`.
- H003 signer receipt: `VERIFIED`; Procursus `ldid` version `2.1.5-procursus7`, SHA-256 `15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c`; approved `amethyst-ios12-rootful` profile SHA-256 `cd1358e7c8c3b01da98b5544e3c2ffcdc9d92cf9a3191e45038e8691ef2021ca`.
- The H003 P011 receipt's canonical stable package SHA-256 is `439d2543adbe1472f82cfd6c9e6bb9dd747da6c31c79f3da1f3da86b8ca9421c`. The package digest printed in the task brief is 59 hexadecimal characters and is not a SHA-256 value. Use the 64-character receipt value for host-side comparison. If the later artifact does not match the receipt, stop; do not guess or repair the digest.
- Physical P011 acceptance and signature integrity remain pending. The current release decision remains `RELEASE_BLOCKED`. A successful host check, CI job, or H003 receipt is not device acceptance.

Receipts: [H003 P011 host preflight](H003-P011-HOST-PREFLIGHT.json), [H003 signer provenance](H003-SIGNER-PROVENANCE.json), and [H003 validation record](H003-VALIDATION.md).

## Operator prerequisites

Complete every item before beginning. Any unchecked or unknown item blocks inspection.

- [ ] Target is physically confirmed as iPad mini 2 A1489 (`iPad4,4`), iOS 12.5.7, Amethyst/Procursus rootful. Stop if identity differs.
- [ ] Operator is physically beside the iPad for the entire inspection and can see its physical condition.
- [ ] A working local terminal or equivalent direct read-only inspection method is available at the device. It is not a remote SSH/Tailscale session.
- [ ] An independent physical recovery method is available and understood. It does not depend on SSH, Tailscale, an active project daemon, or a network path. Confirm the method is accessible and has already been safely validated; record it without testing a state-changing recovery action during Phase 0. If no such method exists, stop before running commands.
- [ ] Current power and charging state are known from direct observation. Record them without changing charge, battery, or thermal controls.
- [ ] Operator and device UTC clock sources, timebase identifiers, and known uncertainty can be recorded. Do not set or correct either clock during inspection.
- [ ] A secure evidence destination is ready. Raw output stays private, access-restricted, and outside CI, the repository, and shared artifacts.
- [ ] The operator has explicitly approved the Phase 0 read-only scope and stop rules. This approval does not include any P011 installation or acceptance action.
- [ ] P012 safety findings and the applicable P011/P018/P019 procedures have been reviewed. The later P011 physical acceptance gate remains pending.

If the local inspection method or independent recovery is unavailable, record the blocker and stop. Do not try remote SSH or Tailscale as a substitute.

## Inspection sequence

Follow [the read-only command plan](H004-READONLY-COMMANDS.md) in order. Begin with operator/time/device and filesystem metadata. Only invoke installed project executables after their paths and hashes are recorded and the initial process, socket, launchd, and recovery observations show no stop condition. Run only commands that the installed CLI advertises as supported and read-only.

If any required project command is absent or not supported, record `UNAVAILABLE`. Record values that cannot safely be observed as `UNKNOWN`; do not infer a clean or absent state. If execution is denied, unexpectedly terminated, or reports an unplanned error, preserve the exact command, exit/signal result, and observed error, then stop. Do not retry through another shell, privilege, executable, or transport.

If assertion ownership/state or P014 recovery state remains `UNKNOWN`, stop the inspection and preserve that uncertainty. It blocks progression beyond Phase 0, including P011 installation or acceptance; a missing journal alone, an absent diagnostic, or an empty process/socket observation does not prove a safe state.

### Fresh-install journal classification

When the package database reports `com.ioscaffeinate.cli` not installed and all standard project executables, project process, socket, lock, registered launchd label, and live plist are absent, a missing P014 journal may be recorded as `MISSING_FIRST_INSTALL_REVIEW_REQUIRED`. It is still not a clean recovery record and does not itself authorize installation. Record whether prior manual/staged project binaries or assertion activity are known, and record direct assertion-owner/cleanup observations. If prior history, assertion ownership, or cleanup remains unknown, stop. Only an independent review of the complete observations and a separate P011 authorization can decide whether a first-install package action is eligible.

The P014 root-only `service recovery reset --reviewed-cleanup --reviewed-supervisor-state` command is not part of H004. If a later, separately authorized v0.2 installation reaches P014 review, follow [P014 device acceptance](P014-DEVICE-ACCEPTANCE.md) and run the command before daemon startup only after its required direct observations are recorded.

## Immediate disposition

Stop and preserve observations if a stop condition in [H004 stop conditions](H004-STOP-CONDITIONS.md) occurs. Do not repair the condition during inspection. Complete the [H004 result template](H004-RESULT-TEMPLATE.md) with actual observations only.

A complete Phase 0 record can only be marked `OBSERVATIONS_RECORDED_REVIEW_PENDING`. It cannot assign `PASS`, `DEVICE_VERIFIED`, P011 acceptance, P019 acceptance, or release readiness. If no independent recovery exists, the outcome is `BLOCKED` and no device commands are run.

## After Phase 0

Preserve raw records and review their provenance before proposing any next action. Only a successful, independently reviewed inspection may make the later P011 steps eligible for a separate scope review: artifact/package confirmation and device preflight, including any separately approved package transfer; then, under their own explicit operator authorization, P011 manual installation, installed-binary checks, bounded assertion acceptance, separate connectivity observations, state-preservation review, and removal/rollback. Phase 0 itself authorizes none of them. Follow [P011 device acceptance](P011-DEVICE-ACCEPTANCE.md) and P020's handoff order.

Run the deterministic host-only document check with:

```sh
python3 scripts/validate_h004_operator_package.py
```

That validator reads the H003 receipts and H004 documents only. It does not contact or control a device and does not create physical evidence.
