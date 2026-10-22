# P013 — iOS 12 launchd Compatibility

## Current result

No device-side `launchctl` command or iOS 12 launchd behavior was executed during cloud engineering. The compatibility result for `help`, `list`, `load`, `unload`, `start`, `stop`, `enable`, `disable`, `bootstrap`, and `bootout` is **UNVERIFIED on iOS 12.5.7**. P013 does not guess a launchd domain or apply modern macOS `system/<label>` syntax.

The CLI securely locates `/bin/launchctl`, then may execute only the read-only `help` and `list` subcommands. It reports advertised command names as `DETECTED_UNVERIFIED`; a nonzero result, missing executable, unsafe executable identity, or truncated output remains `UNSUPPORTED` or `UNVERIFIED`. A successful Linux fake is only a test of reporting logic.

| Interface | P013 use | iOS 12 result |
|---|---|---|
| `launchctl help` | Read-only capability observation | UNVERIFIED until run on target |
| `launchctl list` | Read-only registration/PID observation | UNVERIFIED until run on target |
| `load` / `unload` | No invocation | UNVERIFIED |
| `start` / `stop` | No launchctl invocation; graceful stop uses daemon IPC | UNVERIFIED |
| `enable` / `disable` | No invocation | UNVERIFIED |
| `bootstrap` / `bootout` | No invocation | UNSUPPORTED by P013 pending proof |

P013 lifecycle mutations that depend on registration or launchctl start semantics return exit code 3 with `changed=no`. Root access and command-name detection do not upgrade a capability to verified.

## Device-side read-only investigation

Run these observations only while physically present with independent recovery available. Do not run `load`, `unload`, `start`, `stop`, `enable`, `disable`, `bootstrap`, or `bootout` during this phase.

1. Record the iOS version, device identifier, jailbreak/rootful environment, local time, and operator. Do not include SSH keys, Tailscale credentials, or private network addresses in the report.
2. Inspect executable identity and permissions with read-only tools: `ls -l /bin/launchctl`, `stat /bin/launchctl`, and `file /bin/launchctl`. If `/bin/launchctl` is a symlink or its ownership/mode is unexpected, stop and record that fact.
3. Run `/bin/launchctl help` and capture its exit status and output. Do not infer domain syntax from macOS documentation or from a usage line that does not explicitly describe the iOS command.
4. Run `/bin/launchctl list` and capture its exit status and output. Check whether the exact label `com.ioscaffeinate.daemon` appears and record the PID/status fields. A plist on disk is not evidence that a job is loaded.
5. Inspect the staged plist with `plutil -lint` where available and `cat /usr/share/ioscaffeinate/launchd/com.ioscaffeinate.daemon.plist`. Confirm it remains disabled and no live plist has appeared.
6. If help documents a subcommand-specific help form, use that form only for read-only help. Otherwise do not probe it by issuing a mutation command.
7. Report each candidate syntax as `DETECTED`, `UNSUPPORTED`, or `UNVERIFIED`, with the exact command output, OS version, and provenance. Do not report operational compatibility until a separate supervised lifecycle test establishes the effect and rollback behavior.

The P013 device acceptance sequence is in [P013-DEVICE-ACCEPTANCE.md](P013-DEVICE-ACCEPTANCE.md). Package acceptance and direct recovery are prerequisites; the procedure is not an instruction to run automatically.
