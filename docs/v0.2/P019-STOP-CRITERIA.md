# P019 Stop Criteria

Stop the current session immediately and do not begin another trial if any item occurs:

1. Assertion release fails or cannot be confirmed.
2. Prior assertion ownership becomes unknown.
3. P014 recovery state or journal becomes unsafe, corrupt, or inconsistent.
4. Daemon unexpectedly restarts or exits.
5. Unexplained reboot or respring occurs.
6. A schedule unexpectedly acquires an assertion.
7. SSH host-key verification fails.
8. Independent physical recovery becomes unavailable.
9. Battery or thermal concern occurs, or observations no longer support safe continuation.
10. The operator leaves or attendance cannot be confirmed.
11. Package, installed binary, signer, entitlement profile, or build identity mismatches.
12. Service, socket, lock, or assertion ownership state becomes inconsistent.
13. Persistent state is corrupted or a required observation is lost.
14. Approved test duration or the 300-second assertion ceiling is exceeded.
15. The previous trial leaves daemon, socket, assertion, or recovery state uncertain.

An SSH failure is recorded as an outcome. Continue only when the registered safety rule allows it and safety state remains known. Host-key failure is an immediate stop.

## After a stop

Preserve incomplete P012/P019/P009 records, original outputs, timestamps, clock uncertainty, and the exact package/build identity. Mark the result `FAILED_SAFETY`, `INCOMPLETE`, or `INCONCLUSIVE` as appropriate. Keep the operator present. Use only a separately authorized manual recovery plan.

Do not automatically restart services, reboot, respring, SIGKILL, repair state, delete sockets, reset the P014 journal, install/rollback a package, mutate launchd, or acquire/release another assertion. An SSH failure alone does not authorize service recovery.
