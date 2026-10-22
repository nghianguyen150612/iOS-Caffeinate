# P014 — Durable Recovery Record

The daemon stores a bounded, versioned record at `/var/lib/ioscaffeinate/recovery-state.json`. This ledger is needed because P014 must distinguish a clean prior run from an unobserved process death before it evaluates P004 schedules. It does not replace or modify P004 schedule storage or P006 server policy.

## Record contents

Schema and policy versions, a recovery generation, process and cleanup state, last exit classification and observed signal, up to three attempt records, event counters, failure timing, and healthy-interval timing are stored. Attempt timestamps include monotonic nanoseconds, diagnostic wall UTC seconds, and a caller-provided clock identity. No assertion ID, credential, command argument, environment value, or device log is stored.

The JSON parser accepts the exact version 1 field order emitted by the writer. It rejects duplicate or unknown fields by rejecting unexpected structure, malformed or partial objects, unsupported versions, invalid enum values, oversized content, and inconsistent counters. The record is capped at 4096 bytes.

## Filesystem and crash consistency

The record must be a root-owned regular file with mode `0600` and exactly one hard link. The reader walks parent directories with `openat` and `O_NOFOLLOW`, checks ownership and permissions, verifies the opened inode against the inspected inode, and rechecks the file after reading. The atomic writer creates a private exclusive temporary file, writes and `fsync`s it, renames it over the trusted target, then `fsync`s the parent directory. The writer never replaces a corrupt, unsupported, symlinked, hardlinked, or otherwise unsafe target.

The existing daemon socket lock is the single-writer invariant. `recovery_store_begin_run` is called only while that lock is held and writes a durable `RUNNING` marker before schedule evaluation. The future supervisor-facing `recovery_store_consume_attempt` helper updates a private copy, writes it atomically, and returns success only after file and directory sync; a caller must not attempt the operation if persistence fails. A failed or interrupted write blocks assertions; a missing first-run record is initialized as unverified and also blocks assertions. A prior `RUNNING` marker remains evidence only that a previous run did not record a clean finish; it does not identify SIGKILL or prove assertion fate.

An absent, corrupt, unsupported, or unsafe record is not silently repaired. The operator-reviewed reset is allowed only after service registration is confirmed absent, daemon/socket absence is established while the daemon socket lock is held, and an operator separately reviews cleanup. The reset records an explicit operator decision and does not produce physical evidence.

## Timebase limits

Wall UTC is diagnostic. Policy elapsed-time calculations use monotonic nanoseconds only when the caller supplies the same nonempty clock identity. A boot or clock identity change, rollback, missing clock information, or nonreconcilable persisted timestamp leaves the policy unverified. P014 does not assume monotonic counters survive reboot. This avoids resetting an exhausted budget through a clock jump, at the cost of a conservative attended recovery after reboot or missing identity.

The test harness injects interrupted writes before rename and verifies that the previous record remains readable. A real iOS filesystem/power-loss durability guarantee remains unverified until device acceptance.
