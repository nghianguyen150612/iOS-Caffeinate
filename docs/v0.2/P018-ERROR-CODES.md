# P018 Error and Exit-Code Contract

New P018 frontends use stable `error.*` keys where the command can identify a failure:

```text
error.code=RECOVERY_BLOCKED
error.operation=package_upgrade_check
error.reason=P014_RECOVERY_NOT_CONFIRMED_HEALTHY
changed=no
cleanup=not_applicable
next_safe_step=inspect_service_recovery_status
```

`changed` is `no` for a confirmed read-only failure, `yes` only when an operation reports a completed change, and `unknown` when partial effects cannot be ruled out. `cleanup=not_applicable` is used when the failed operation could not create cleanup work; stateful operations report `confirmed` only when cleanup is observed and otherwise use `unknown`. Export errors conservatively report both `changed=unknown` and `cleanup=unknown` because interrupted filesystem cleanup cannot always be independently established. A success line is not inferred from a missing error.

The package manager reports each readiness blocker with a stable `blocker=` key. This preserves multiple independent reasons in one preflight; `readiness` and `operator_*_authorization` remain the decision fields. Text error output uses `error.operation`, `error.code`, `error.reason`, `changed`, `cleanup`, and `next_safe_step`; the opt-in JSON frontends use corresponding stable fields such as `operation`, `error_code`, `error_reason`, `changed`, `cleanup`, and `next_safe_step`. Older subsystem text remains compatible and may retain its historical field names.

## Vocabulary

| Code | Meaning | Safe next step |
| --- | --- | --- |
| `OK` | Requested diagnostic completed. Component states still need inspection. | Read each result field. |
| `INVALID_ARGUMENT` | The command shape or argument is invalid. | Use `ic help <topic>`. |
| `PERMISSION_DENIED` | The caller lacks a required privilege. | Review the operation; use the required operator context only when appropriate. |
| `NOT_INSTALLED` | A required packaged manager/tool is absent. | Verify package status; do not auto-start or reinstall. |
| `DAEMON_UNAVAILABLE` | IPC could not establish a usable daemon response. This does not distinguish process absence from every unsafe/unknown service state by itself. | Inspect `ic service status` and `ic service recovery status`. |
| `UNSUPPORTED` | The current platform or implementation does not provide the operation. | Read the stated platform limitation. |
| `UNVERIFIED` | A result lacks required signer, device, or runtime verification. | Obtain the relevant provenance/attended evidence. |
| `UNSAFE_STATE` | A path, ownership, link, socket, or current-state check is unsafe. | Inspect the named state without deleting or repairing it. |
| `RECOVERY_BLOCKED` | P014 has not established safe cleanup/recovery. | Inspect recovery status and complete physical cleanup review. Do not reset automatically. |
| `POLICY_BLOCKED` | Policy does not authorize the requested operation. | Follow policy diagnostics; do not bypass the gate. |
| `EVIDENCE_PENDING` | Evidence is absent, unreviewed, or incomplete. | Collect genuine evidence and use P009 review. |
| `INTEGRITY_FAILED` | A checksum, schema, or metadata consistency check failed. | Preserve artifacts and investigate the exact reported file. |
| `IO_ERROR` | A bounded read/write/query failed. | Inspect the named path/state and retry only after review. |
| `INTERNAL_ERROR` | An unexpected internal failure occurred. | Preserve output and report the incident. |

## Exit compatibility

- Existing service exit values remain unchanged: `0` success, `1` error, `2` usage, `3` unsupported, `4` privilege, `5` invalid state, `6` unsafe state (`src/service.h`).
- Legacy CLI runtime/usage codes are preserved: ordinary runtime failures commonly use `1`, invalid syntax `2`, and unavailable health sources may use `3`.
- The manager's legacy `rollback-check` keeps its artifact-check exit result for scripts. Read `rollback.readiness`; `0` does not mean a rollback was authorized.
- New doctor output can return `0` when the aggregation ran successfully even if individual components are `FAILED`, `UNAVAILABLE`, or `PENDING_VERIFICATION`. Inspect the component statuses.

Some historical subsystem diagnostics still use their existing text and exit conventions. P018 documents those rather than globally renumbering them.
