# P006-HW — Deferred Device Validation Plan

The iPad is unavailable. This procedure is planning only; no device access, transfer, deployment, launchd activation, assertion, screen lock, reboot, or network change was performed for P006.

## Preconditions

- A physical operator is present with a known recovery path and can reach the iPad's buttons and power source.
- Record iPad model, iOS build, jailbreak/bootstrap, battery level if available, charging state, ambient conditions, and start time.
- Verify the exact unsigned `arm64-apple-ios12.0` artifacts and checksums from a passing P006 CI run. Do not activate launchd.
- Confirm the launchd plist remains disabled. Start the daemon manually in the foreground for the bounded test session.
- Run `ic server doctor` and `ic server status`. These reports must not start an assertion. Record all unknown and unavailable checks.
- Keep the display unlocked for the first short assertion lifecycle check. Use a 30–60 second trial, below the 300-second ceiling.

## Bounded trial sequence

1. Start one explicit trial: `ic server trial start --for 1m`.
2. Confirm the daemon reports one owned assertion and `trial_state=ACTIVE`. Record the time, backend output, and complete error output.
3. Stop promptly with `ic server trial stop`; confirm `trial_state=STOPPED`, no current daemon-owned assertion, and a successful release result. Repeat once with natural expiry, still within 300 seconds.
4. Send SIGTERM to the foreground daemon. Confirm the shutdown release result and that the daemon exits. A failed or unavailable result remains unresolved; do not continue to locked-screen tests.
5. Restart the daemon and confirm it does not restore a trial. A fresh daemon status cannot prove that a killed process's assertion was cleaned up by iOS; record this as unverified.

Do not extend this first session into a multi-hour or 24/7 hold.

## Locked-screen connectivity observations

Only after the short acquire/release/expiry checks pass and physical recovery remains available, conduct separate bounded trials of at most 300 seconds. The operator may lock the display locally. An independent observer on another machine records LAN and Tailscale results separately using [`schemas/connectivity-evidence-v1.schema.json`](schemas/connectivity-evidence-v1.schema.json):

- LAN: local address, TCP-22 result, authenticated SSH result, latency, timestamp, and operator-reported lock state.
- Tailscale: tailnet address, peer connectivity, direct/relay/unknown path, authenticated SSH result, latency, timestamp, and lock state.
- Do not treat one path as a substitute for the other. Do not infer successful SSH from a green app indicator or local daemon status.
- Record missing battery or thermal observations as unavailable. Use supported read-only sources and do not install sensor tools or invoke private APIs for this milestone.

Run a few short, repeatable trials at most. Record configuration, charging state, and environment for each trial so results can be compared. No multi-hour/24/7 operation is authorized by P006.

## Recovery and rollback

- Use `ic server trial stop`, then terminate the foreground daemon with SIGTERM.
- If the daemon reports release failure, retain the error and owned state as unresolved. Do not assume a process restart releases an assertion.
- If the device becomes unresponsive, use the operator's previously confirmed physical recovery procedure. Record whether it worked, recovery duration, and any data or network impact.
- Remove only the manually staged P006 binaries and temporary test configuration after recording evidence. Do not install or activate the launchd template.
- Keep SSH/Tailscale configuration and system daemons unchanged.

Record acquisition, release, expiry, screen-lock, LAN, Tailscale, battery/thermal, recovery, and rollback evidence with timestamps. Hardware gates pass only when backed by these real observations, not by Linux tests or CI.
