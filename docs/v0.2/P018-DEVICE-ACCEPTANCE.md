# P018 Supervised Device Acceptance

Cloud engineering does not access the iPad. Device acceptance remains pending until the package and signer provenance gates pass and an operator performs an attended session with recovery independent of SSH/Tailscale.

## Prerequisites

- P011 signed-package acceptance and exact P010 signer provenance are reviewed.
- P012 safety findings are reviewed.
- P013 launchd and P014 cleanup/recovery behavior are reviewed.
- Existing package, daemon, socket, assertion, recovery, schedule, policy, and persistent-data state are known.
- The operator is physically present and has a working recovery path independent of the network session.
- No reboot/respring, package mutation, or unattended power test is planned.

## Initial read-only session

Run only these commands first; save their genuine terminal output with timestamps and source/binary identity:

```sh
ic --version
ic --help
ic doctor
ic package status
ic package verify
ic schedule doctor
ic server policy explain
ic health status
ic evidence inventory
```

These are **read-only**. They do not start the daemon, acquire an assertion, or enable launchd. Do not interpret missing battery/thermal sources as zero, `READY_FOR_OPERATOR_REVIEW` as package authorization, or an export as hardware acceptance.

## Export review

After inspecting the inventory and privacy implications, an operator may explicitly choose a new root-owned destination:

```sh
ic evidence export --dry-run
ic evidence export --output "/var/root/ioscaffeinate-p018-export"
python3 /usr/share/doc/ioscaffeinate/tools/p018_validate_export.py "/var/root/ioscaffeinate-p018-export"
```

The first command is **read-only**. The second command is **explicit file creation**. The validator is read-only. Inspect every included record and manifest before sharing. Preserve original evidence and terminal output; never replace missing device evidence with fixtures or CI artifacts.

Package upgrade/removal and rollback testing need separate explicit authorization and their own supervised procedure. Do not run `dpkg -i`, `dpkg --remove`, reboot/respring, launchctl mutation, or unattended power-management tests as part of this initial P018 session. Do not depend on an SSH connection surviving daemon shutdown.

## Acceptance result

Until genuine P009 evidence is independently reviewed, report `P018_CLOUD_COMPLETE_DEVICE_UX_PENDING`. A valid export remains `EXPORT_CREATED`; P009 hardware acceptance is a separate gate.
