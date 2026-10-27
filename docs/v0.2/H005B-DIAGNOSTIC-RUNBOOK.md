# H005B — Separate supervised assertion diagnostic runbook

## Authorization boundary

H004 authorizes only its narrow attended read-only observations. It does **not** authorize retrieval, transfer, staging, or execution of the H005/H005B binary. This runbook describes a later session that may proceed only after a separate written authorization names the exact H005B artifact, source commit, binary SHA-256, target device, one foreground execution, evidence destination, operator, independent reviewer, local transfer method, and stop rules.

The H005B binary is standalone. It does not require or install the iOS-Caffeinate package or daemon. Its host signature check does not prove iOS runtime compatibility, device acceptance, H004 acceptance, or P011 readiness. Do not use it to install software, start/stop services, change launchd, acquire/release assertions, change power settings, or reboot. Deleting the transferred copy is a separate authorized action.

## Retained device observations

These remain operator-reported preliminary observations, not independently reviewed device evidence:

- Device: iPad mini 2 A1489 (`iPad4,4`), iOS 12.5.7, Amethyst/Procursus rootful.
- Boot time displayed by the device: `2026-10-25 20:41:49`. This does not prove all assertions are clear or that none were recreated after boot.
- No official iOS-Caffeinate installation was detected; project state and log directories were absent; project process/socket/launchd observations were previously absent.
- Reported `IOPMrootDomain` driver mask `0x100`, owner `en0`, ID `500`, level `255`. XNU `xnu-4903.221.2` defines `0x100` as magic-packet wake enabled. This driver-domain bit is not equivalent to a user-space `PreventUserIdleSystemSleep` assertion. The report has not been independently checked on the device.
- Process-level assertion ownership has not been verified. Historical October 18 trial logs are unavailable. Physical acceptance has not been performed.

## Before the separately authorized session

- [ ] Obtain the separate written H005B authorization described above. Confirm it does not authorize package installation or P011.
- [ ] Have the operator physically beside the iPad for the full session and an independent reviewer available to review the artifact before transfer and raw results afterward.
- [ ] Confirm independent local recovery is present, understood, and usable without SSH, Tailscale, a network route, or the project daemon. Do not test a state-changing recovery action.
- [ ] Directly confirm A1489 / `iPad4,4`, iOS 12.5.7, and Amethyst/Procursus rootful. Stop on mismatch or unknown bootstrap identity.
- [ ] Observe safe power, charge, temperature, and handling conditions. Stop if unsafe or uncertain; do not change thermal or battery controls.
- [ ] Prepare a unique non-identifying session ID and a secure private evidence destination outside the iPad, repository, CI, and shared artifacts. Capture raw stdout, stderr, exit code or signal, exact command, timebase, UTC/uncertainty, artifact hashes, and evidence-file hashes. Do not place capture files on the iPad.
- [ ] Confirm no other operator action is occurring that could change packages, assertions, processes, launchd, or power state during the diagnostic.

## Retrieve and independently review the exact artifact

Use a successful exact-head CI run for the reviewed H005B commit. Download only the Actions artifact named `H005B-SIGNED-DEVICE-UNVERIFIED`. Do not use the intermediate `H005B-SIGNED-PENDING-APPLE-VERIFICATION` artifact.

On the review host, unpack to a private directory and verify the recorded inventory:

```sh
ARTIFACT_DIR=/absolute/path/to/private/H005B-SIGNED-DEVICE-UNVERIFIED
cd "$ARTIFACT_DIR"
shasum -a 256 -c SHA256SUMS
```

An independent reviewer must compare the manifest and files before any transfer. Require all of the following:

- `artifact_name` is exactly `H005B-SIGNED-DEVICE-UNVERIFIED` and `artifact_file` is `ios-power-preflight-inspector`.
- `source.commit_sha` equals the reviewed H005B PR head; `source.tree_sha` matches that commit's tree; the signed binary hash matches `artifact_sha256` and `SHA256SUMS`.
- `build.target` is `arm64-apple-ios12.0`; the recorded iPhoneOS SDK, Xcode, and Clang identities are present; IOPM calls are runtime `dlsym` lookups; assertion-mutation imports are absent.
- `signing` records Procursus `ldid` 2.1.5-procursus7 SHA-256 `15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c`, profile `amethyst-ios12-rootful` SHA-256 `cd1358e7c8c3b01da98b5544e3c2ffcdc9d92cf9a3191e45038e8691ef2021ca`, exactly `com.apple.private.security.no-container=true`, and the empty requirements profile SHA-256 `987920904eab650e75788c054aa0b0524e6a80bfc71aa32df8d237a61743f986`.
- `verification.apple_codesign.status` is `VERIFIED`, exit code is `0`, and the recorded command is Apple `codesign --verify --strict --verbose=4` for this exact binary. The independent Mach-O audit must report exact entitlements, ad hoc signature, zero designated requirements, and verified code-directory hashes.
- `scope.device_transfer` and `scope.device_execution` are `NOT_PERFORMED`; `scope.device_acceptance` is `PENDING_SEPARATE_AUTHORIZATION`.

The reviewer records the exact CI run URL, source SHA, manifest hash, binary hash, `SHA256SUMS` result, and decision in the private evidence record. Reject missing, mismatched, unsigned, failed, or ambiguous evidence. Do not transfer the intermediate signed artifact before Apple verification.

## Transfer and one foreground execution

Only after the reviewer has accepted the artifact and the operator has confirmed the separate scope:

1. Use only the local transfer method explicitly named in that authorization. Do not use SSH, Tailscale, or a network route unless the separate authorization explicitly names and reviews that method. Copy only `ios-power-preflight-inspector` to a temporary, operator-controlled path. Do not copy it into a package, daemon path, launchd path, or stable asset directory.
2. Before execution, inspect the temporary path and executable mode using already present read-only tools. Run an already present SHA-256 utility against the transferred file and compare it byte-for-byte with the independently reviewed manifest hash. If the utility is missing, the hash differs, the file is not regular, or execution permission is unexpected, stop; do not install a hashing utility or repair the file.
3. Reconfirm the operator, local recovery, safe power, target identity, private evidence capture, and unchanged device state. Capture only the diagnostic stdout/stderr and required command/exit metadata; do not collect credentials, process environments, unrelated logs, personal files, or unrelated process names.
4. Execute the binary exactly once in the foreground with no arguments:

   ```text
   /absolute/temporary/path/ios-power-preflight-inspector
   ```

   The program applies a 15-second process-local alarm around the three read-only queries and emits one bounded JSON object to stdout. Capture stdout, stderr, exit status or terminating signal at the operator's private evidence destination, without redirecting files onto the iPad. It does not create or release assertions. It must not be relaunched to get a cleaner result.
5. Record the exact executable path, file hash, command, start/end time, observer timebase, raw output hashes, exit result, and any signal. Preserve output as collected; do not rewrite the raw capture. If a separate redacted review copy is needed, retain both copies and bind the derived copy to the raw hash.
6. Perform only the pre-approved read-only post-execution observations needed to verify the device did not unexpectedly change and to correlate assertion owners with the independently recorded process/service state. Do not run the diagnostic a second time or infer cleanup from boot time, process absence, or an absent socket.

## Result interpretation and stop conditions

The global `classification` reports any observed assertion domain. `ASSERTIONS_PRESENT` by itself does not prove an iOS-Caffeinate assertion is present; review `assertion_domain`, `assertion_role`, source completeness, and `sleep_prevention_ownership` separately.

- `ACTIVE_SLEEP_PREVENTION_OWNER_IDENTIFIED` is a positive active sleep-prevention observation and blocks P011 clearance. Correlate the PID/driver label through separately authorized evidence; do not assume it names iOS-Caffeinate.
- `ACTIVE_SLEEP_PREVENTION_OWNER_UNKNOWN`, `UNESTABLISHED`, `UNAVAILABLE`, `UNKNOWN`, `enumeration_complete=false`, unknown types/bits/owners, malformed output, source conflicts, privilege denial, missing symbols, or a 15-second alarm signal block clearance and stop the session.
- A complete `NO_ACTIVE_SLEEP_PREVENTION_OBSERVED_COMPLETE` result is a bounded diagnostic observation, not a safety certificate and not automatic H004 acceptance. An unrelated recognized assertion such as `NetworkAccess` or driver mask `0x100` remains recorded and is reviewed by a human without automatically being called an iOS-Caffeinate sleep assertion.
- Any AMFI denial, loader error, crash, unexpected termination, timeout, unexpected output, device state change, unsafe power/temperature, or evidence-handling problem is an immediate stop. Preserve the exact evidence; do not retry with another privilege, shell, binary, transport, or tool.

The independent reviewer compares the manifest, binary hash, raw output, exit result, source completeness, assertion domains, and prior device observations. The reviewer records a decision and rationale in the private H004/H005B record; the tool cannot accept its own exception or certify H004/P011. P011 remains blocked until H004 is separately completed and accepted, the 173-entry dpkg audit exception is independently reviewed or otherwise resolved, current assertion ownership/state is reviewed, and the exact package/recovery gates have separate approval.

Do not remove the temporary diagnostic after execution unless a separate cleanup authorization names the file, path, reviewer, and method. Do not edit or repair system packages or other device state.
