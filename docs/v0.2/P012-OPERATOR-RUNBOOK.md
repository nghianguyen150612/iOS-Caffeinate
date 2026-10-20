# P012 — Operator runbook

This runbook prepares and records a supervised experiment. The scripts do not start/stop the daemon, install packages, change network settings, or acquire/release an assertion. P012 physical work is still blocked on P011 acceptance and separate operator authorization.

## Before considering a hardware trial

1. Review [P011 device acceptance](P011-DEVICE-ACCEPTANCE.md) and the [P011 validation record](P011-VALIDATION.md). Confirm that the exact installed stable package passed its preflight and that installed CLI/daemon execution and assertion cleanup have been verified. The P011 `ldid` provenance blocker must be resolved through its own gate, not bypassed here.
2. Obtain separate authorization for package installation and for each physical trial. Be physically present with direct recovery that does not depend on SSH or Tailscale.
3. Review battery and thermal conditions and choose the operator-approved battery threshold. Do not start if the device is unexpectedly hot or the previous state is uncertain.
4. Use the protocol's fixed trial order and counterbalanced route order. Give every route trial a new sanitized `trial_id`; use the same `pair_id` for its matched LAN/Tailscale trial in that condition and repetition. Do not run a batch of probes or leave a loop running.
5. From a trusted host, use the existing SSH client configuration and known-hosts file. Confirm host identity before the run. Never disable host-key checking or add passwords/tokens to a command.

## Preparation commands (offline)

```sh
python3 scripts/p012_trial.py plan
python3 scripts/p012_trial.py validate
python3 scripts/p012_trial.py dry-run --condition A --route LAN
python3 scripts/p012_host_probe.py --route LAN --condition-id A --trial-id feasibility-a-lan --repetition 1
```

These commands do not contact a host or device. The host-probe default is dry-run even though a route and trial are named.

## Manually place the device in the condition

Use the installed CLI and the reviewed P011 operating procedure. Perform all device state changes manually and separately authorize them. Do not automate these actions with the P012 controller.

- **A:** stop the foreground daemon by its reviewed manual procedure. Confirm it is stopped and no daemon-owned assertion is active. Lock the display.
- **B:** manually run the daemon in foreground. Confirm it reports IDLE and no active iOS-Caffeinate assertion. Lock the display.
- **C:** with the foreground daemon running, manually start one 180-second bounded assertion. Record actual acquisition success and time. Keep the operator present, confirm the display is locked, and finish the route-specific probe before expiry. Record the actual release/expiry result and time afterward.
- **D:** keep the daemon running. Manually confirm timed expiry or explicit release and no daemon-owned active assertion. Only then begin a fresh quiet interval with the display locked.

Do not infer that all OS assertions are inactive in A, B, or D. If the daemon, socket, assertion, or prior-trial state is uncertain, stop; do not force-kill, reboot, or try remote recovery.

## One attended host probe

Only after all P011 prerequisites and trial confirmations pass, the operator may run one command for one destination supplied separately at invocation. Replace the literal destination placeholder locally; never commit the real address:

```sh
python3 scripts/p012_host_probe.py \
  --route LAN \
  --condition-id A \
  --trial-id feasibility-a-lan \
  --repetition 1 \
  --target-id ipad-mini-lab \
  --destination operator@HOSTNAME-SUPPLIED-BY-OPERATOR \
  --timebase-id arch-host-ntp \
  --timing-uncertainty-ms 500 \
  --quiet-interval-seconds 120 \
  --quiet-interval-complete \
  --screen-lock-status LOCKED \
  --screen-lock-confirmed \
  --daemon-state STOPPED \
  --daemon-state-confirmed \
  --assertion-state INACTIVE \
  --assertion-state-confirmed \
  --operator-present \
  --p011-preflight-passed \
  --package-installation-authorized \
  --installed-runtime-verified \
  --assertion-cleanup-verified \
  --physical-recovery-confirmed \
  --battery-thermal-approved \
  --wifi-association-confirmed \
  --route-state-confirmed \
  --run-attended
```

For B/C/D, supply that condition's registered daemon/assertion state. Use `--route TAILSCALE` only in a separate Tailscale trial with its own quiet interval. The tool invokes SSH once with batch authentication, strict existing host-key verification, a bounded timeout, and remote command `true`. It records no destination or raw SSH log. A host-key failure stops that probe and requires operator review.

The probe command does not confirm a later assertion release. Capture actual C/D release results in the operator trial record. Never use the probe's process exit or interruption as evidence of device cleanup.

## Record, validate, and report

Prepare a JSON object conforming to [trial-record-v1.schema.json](../../experiments/p012/trial-record-v1.schema.json), with all operator confirmations and the host probe result. Use `UNKNOWN`, `null`, or `false` where appropriate; do not fill gaps from memory. Store measurements outside the repository:

```sh
python3 scripts/p012_trial.py record \
  --input /secure/private/path/trial.json \
  --operator-recorded
python3 scripts/p012_trial.py validate --record /secure/private/path/trial.json
python3 scripts/p012_trial.py map-p009 --record /secure/private/path/trial.json
python3 scripts/p012_trial.py report /secure/private/p012-records --format markdown
python3 scripts/p012_analyze.py /secure/private/p012-records --format json
```

`record` writes exclusively under `$XDG_DATA_HOME/ios-caffeinate/p012` by default, or under an explicit private `--data-root`; files are mode 0600 and are never overwritten. Invalid or incomplete trials are still stored with their original operator-reported fields. Keep raw trial files out of Git and review the JSON before sharing it.

Stop or mark the trial interrupted if a stop condition occurs. Preserve the outcome, interruption code, and any confirmed state. Do not write “release succeeded” unless the device actually reported it.
