# P019 Operator Runbook

This runbook defines future supervised work. P019 cloud preparation does not connect to or control the iPad. Each physical operation requires separate operator authorization. The cloud agent has not performed any device action.

## Before scheduling hardware work

1. Resolve the exact P010 signer blocker. The `ldid` executable must be version `2.1.5-procursus7` with SHA-256 `15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c`. A different same-version binary is rejected.
2. Complete P011 stable-package preflight and supervised acceptance for the exact v0.1.0 artifact. Keep signature integrity and device acceptance separate from package hash verification.
3. Prepare a separately signed, hash-verified development candidate from the exact P019 source. Record source SHA, build ID, package/version/hash, CLI and daemon hashes, P010 profile and entitlement result, signer version/hash, installed paths, and a previously accepted rollback package. P019 does not build, sign, transfer, or install it.
4. Confirm a physically present operator, direct recovery independent of SSH and Tailscale, a known safe P014 journal/assertion state, safe resource review, and separately authorized scope. If a prerequisite is unknown, stop.

## First safe attended session

Once the signer/provenance blocker is resolved and the operator separately authorizes an inspection, begin with Phase 0 only. Prefer local physical-console inspection. Confirm device model/iOS/bootstrap, installed package and executable identities, daemon/socket/launchd state, assertion ownership, P014 recovery journal, P015 policy, P017 schedules, P016 data availability, logs, and evidence inventory. Save original output privately with UTC time, source class, timebase, uncertainty, and exact binary identity. Do not install, start the daemon, acquire an assertion, mutate launchd, reset state, or probe SSH in this first session.

If the installed CLI is missing or lacks a suggested command, record `UNAVAILABLE`/`UNKNOWN`; do not download a binary to the device or infer a pass. Stop if process/socket/assertion/recovery state is inconsistent. Resolve the blocker before moving to Phase 1.

## Trial execution after all gates

- Follow P011 for every package install, upgrade, removal, and rollback; each action needs separate authorization.
- Use the stable release only for P011. Use the development candidate for P018/P019-only commands and behavior.
- Manually execute the P012 order and P019 bounded cycles. Never start a 24-trial runner. Preserve rest periods and missing trials.
- Keep one SSH probe per P012 trial and retain host-key checking. Do not collect passwords, private keys, tokens, raw debug logs, or secret-bearing command lines.
- On a stop condition, stop further tests, preserve records, keep the operator present, and follow only a separately authorized manual recovery procedure. Do not auto-restart, reboot, respring, delete sockets, repair state, or reset the P014 journal.

## Evidence handling

Create original P009 v1 packages with the existing P009 utility. Store raw packages securely. Run P009 validation and replay offline. Keep a separate P019 session and P012 trial records. Generate an P018 export only as an explicit operator action to a safe directory after privacy review; validate it with the standalone P018 validator. If privacy filtering blocks a derivative, record `EXPORT_BLOCKED_BY_PRIVACY` and preserve raw evidence unchanged.

Use `scripts/p019_session.py plan`, `validate`, `analyze`, and `report` on the host. `init` and `record-confirmation` write a new host file only. None of these commands connects to or controls a device.
