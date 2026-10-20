# P015 — Configuration Migration

P015 keeps the existing server-mode path and reads v1 without changing it. The read-only preview is:

```sh
ic server policy migrate --dry-run
```

For valid v1 `disabled` or `observe_only`, the command prints a v2 proposal with the same policy and conservative session fields. It never writes, renames, repairs, or deletes a file. A missing file proposes no source migration; invalid, unsafe, or unsupported input produces no migration proposal. Existing v2 reports `already_version_2`.

```text
migration.mode=DRY_RUN
migration.write_performed=no
migration.writer_supported=no
migration.source_status=VALID
migration.proposed_config={"version":2,"policy":"observe_only","session":{"max_duration_seconds":300,"require_operator_confirmation":true,"allow_automatic_start":false,"allow_restart_resume":false}}
migration.original_preserved=yes
migration.session_activation=no
```

The v2 writer is intentionally gated. `ic server policy apply` is not implemented. There is no automated migration, config replacement, backup, rollback, or activation path in P015. A future writer must first provide root-only enforcement, trusted parent traversal, exact schema validation, ownership/mode checks, single-link checks, exclusive same-directory temporary creation, atomic replacement, file and directory synchronization, concurrent-change detection, and fault-injection coverage. Until then, do not use migration preview output as an instruction to overwrite persistent state.

Migration does not read or modify P004 schedules, P014 recovery state, logs, hardware evidence, launchd, networking, package state, or runtime assertions. Package upgrade does not migrate configuration.
