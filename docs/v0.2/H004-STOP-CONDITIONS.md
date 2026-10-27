# H004 — Stop Conditions

Phase 0 is inspection only. Stop at the first applicable condition. Do not continue with later commands to get a cleaner result, and do not repair, clean up, or normalize the observed state.

## Before inspection begins

Do not start if any of these is true:

- The operator is not physically present for the full session.
- No working local read-only inspection method is available.
- No independent physical recovery method is available that does not depend on SSH, Tailscale, a network route, or the project daemon.
- The operator has not explicitly approved the narrow Phase 0 scope.
- Power/charging conditions or safe handling cannot be established.
- No secure private destination is ready for raw evidence.

Do not attempt SSH or Tailscale to fill a prerequisite gap.

## Stop during observation

Stop immediately and preserve observations if:

1. Device identity differs from iPad mini 2 A1489 (`iPad4,4`) or iOS 12.5.7.
2. A system or project command is denied, unexpectedly terminated, crashes, times out unexpectedly, or returns an unplanned execution error. Record its exact command, stdout/stderr, exit code or signal, and stop. Do not try another shell, privilege, executable, or transport.
3. The package database is partial, contradictory, or reports an unresolved package audit issue.
4. Process, socket, lock, or launchd registration/plist observations conflict, have an unexpected owner or type, or leave service ownership ambiguous. The default socket is expected to be a root-owned Unix socket with mode `0600`; its lock path is expected to be a root-owned regular single-link file with mode `0600`. File presence alone does not establish active lock ownership.
5. A project daemon is active and the installed read-only diagnostics cannot establish its state, or a project assertion, recognized active sleep-prevention assertion, active CPU Dark Wake driver assertion, or assertion ownership/release state is `UNKNOWN` or possibly active. Do not stop the daemon or release an assertion. A recognized unrelated assertion such as the reported `0x100` magic-packet wake driver bit is recorded by domain and reviewed; it is not automatically attributed to iOS-Caffeinate. Unknown owner/type/driver mask, conflicting sources, or incomplete critical enumeration blocks clearance.
6. The P014 journal is corrupt, unsafe, unsupported, unreadable, inconsistent, or indicates unverified cleanup, unresolved ownership, or a recovery blocker. A missing journal with prior project runtime history or unknown history is also a stop. For a confirmed first-install baseline, record the missing journal as `MISSING_FIRST_INSTALL_REVIEW_REQUIRED`; it remains unverified and cannot by itself clear the P011 install gate. Continue only the authorized read-only observations needed to document the baseline. Unknown assertion ownership or cleanup is always a stop. Do not reset or create a journal during Phase 0.
7. A launchd registration or live plist is present contrary to the known disabled state, or a loaded job cannot be safely reconciled with the observed plist and process.
8. A schedule unexpectedly appears to have acquired an assertion, or policy/schedule/recovery output reports critical state that conflicts with the filesystem or runtime observations.
9. The device becomes unusually hot, power/charging conditions change unexpectedly, battery is low enough to threaten safe completion, or a resource observation indicates an immediate safety issue.
10. Device files or state change during inspection without an explained, authorized cause.
11. Evidence capture would expose credentials, unrelated personal data, raw private addresses, or unreviewed user files to an unsecured destination.

An absent CLI, unsupported project command, missing optional health source, or unavailable telemetry is recorded as `UNAVAILABLE` and is not retried. A value that cannot safely be established is `UNKNOWN`. These states do not become `false`, `clear`, or `PASS`.

The reported IOPMrootDomain driver assertion (`0x100`, owner `en0`, ID `500`, level `255`) is a positive operator-reported driver-domain observation pending direct review. Apple XNU `xnu-4903.221.2` defines driver bit `0x100` as magic-packet wake enabled; that bit is not equivalent to a user-space `PreventUserIdleSystemSleep` assertion and does not by itself establish iOS-Caffeinate ownership. Do not infer current device state from this source interpretation. Record a complete current read-only observation and distinguish driver masks from process assertions. Stop if a relevant active sleep-prevention owner is present, an owner/type/driver bit is unknown, source results conflict, or a critical query is unavailable/incomplete. A known unrelated assertion may be recorded for independent review without automatically calling it a project assertion. The H005/H005B inspector cannot be transferred or executed under H004; an unavailable or incomplete existing query is `UNKNOWN` and stops progression.

## At a stop

- Stop issuing commands. Keep the operator physically present.
- Record the last command and exact observed error/output, timestamp, timebase, and stop reason.
- Leave processes, sockets, lock files, launchd, assertions, journals, schedules, policies, packages, logs, and power settings as found.
- Preserve raw observations privately and mark the inspection `STOPPED` or `INCOMPLETE`.
- Escalate for a separately authorized manual recovery plan. H004 provides no recovery action.

Do not install/remove/configure Debian packages; copy binaries; start/restart/stop/kill processes; acquire or release assertions; load/unload/change launchd; delete or create sockets/locks; reset/rewrite P014; change Server Mode or schedules; inspect reachability over SSH/Tailscale; change battery/thermal settings; export evidence; reboot; or respring. A safety blocker is preserved as an observation, not repaired during this session.
