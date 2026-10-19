# P005 — Deferred Device Test Procedure

## Status and gate

**P005 snapshot — not executed at that milestone.** The iPad was unavailable then. No SSH, deployment, reboot, respring, service loading, power assertion, or wake mechanism was attempted for P005. Later operator-reported execution and assertion observations are summarized in [P010 hardware findings](P010-HARDWARE-FINDINGS.md); scheduled wake remains unverified.

P005 found no public iOS 12 scheduled-wake API. Experiment C is therefore **not ready to run**. It may be reconsidered only if a viable, bounded, cancelable platform wake mechanism is identified and its target access and recovery behavior are reviewed first. Experiments A and B are still useful for distinguishing lock, process scheduling, and network behavior.

## Common preparation

Before any future hardware test:

1. Have the physical iPad and a person beside it throughout the test. Confirm the passcode and a physical recovery path before starting. Keep a known-good host/cable available; remote SSH must never be the only recovery path.
2. Keep each trial short and bounded. Start with at most five minutes, use a single trial at a time, and stop at the first unexpected heat, battery, boot, network, or assertion behavior.
3. Use an independently time-synchronized observer and record UTC timestamps from both the observer and device. A local test marker should record wall-clock and monotonic time when it actually runs. Preserve raw logs and note clock offset.
4. Record display state, lock action, power source, battery level, Wi-Fi association, and whether the device was touched. Do not call a dark screen “system sleep.”
5. Treat LAN and Tailscale as separate measurements from separate observer locations. Do not combine their success/failure into one reachability result. Network polling can itself change radio behavior, so record whether a trial had active probes.
6. Do not change SpringBoard, powerd, assertiond, Apple launchd services, Wi-Fi, Tailscale, SSH configuration, kernel code, or RTC state. Do not leave a persistent service or assertion behind.

## Experiment A — Screen lock

**Question:** Does the target remain reachable with its display locked?

1. With physical recovery available, record UTC time and the baseline display, lock, LAN, and Tailscale observations.
2. Lock the device locally and observe the display directly. Leave it untouched for a bounded five-minute window.
3. From one observer on the same LAN, record ping/TCP/SSH results and timestamps. In a separate trial, repeat from a Tailscale-connected observer. Do not use the SSH session as the only way to control or recover the iPad.
4. Unlock locally and record whether any queued output appears only after unlock.

**Interpretation:** This establishes only screen-lock reachability for those network paths and conditions. It does not establish process suspension, full system sleep, Wi-Fi wake behavior, or scheduled wake.

## Experiment B — Userspace suspension and launchd delivery

**Question:** Do a userspace timer and a temporary launchd calendar job execute during the locked interval, or only after later resumption?

1. Prepare a temporary, single-shot test marker that records its actual run time to a local file. Use a separately reviewed, target-version-validated temporary launchd job only if its creation and removal can be bounded without altering Apple service plists or enabling the project's persistent daemon. Do not use P005 `wake status` as a timer or wake mechanism.
2. First run a trial with no active network polling. Lock the display, schedule one marker within the five-minute window, and do not touch the device until the window ends. Record independent timestamps and whether the display stays dark.
3. Read the marker only after the planned observation window. Compare its recorded device time to the independent clock. A marker timestamp after manual unlock demonstrates delayed delivery/resumption only; it does not prove the device woke autonomously at the scheduled time.
4. Repeat separate bounded trials for LAN observation and Tailscale observation. Mark those as network-active trials because the probes may wake a radio or otherwise change power behavior.
5. Remove the temporary job and marker, verify no job remains loaded, and confirm there is no active assertion before ending.

**Interpretation:** A missing marker cannot distinguish process suspension, job rejection, termination, clock error, or device sleep. A `ps` sleeping state is not enough to prove process suspension. If there is no independent way to establish when execution occurred while the display remained locked, record the result as **unknown**.

## Experiment C — Scheduled wake (conditional; currently gated)

Run only after a viable mechanism is identified for iOS 12.5.7/A7 and separately reviewed as safe, cancelable, and nonpersistent. Do not use a guessed `IOPMSchedulePowerEvent` symbol or write RTC registers as discovery.

1. Confirm physical recovery and prepare to cancel the single test event. Keep the window to at most five minutes and do not use a repeating alarm.
2. Record the mechanism, target availability evidence, privilege/entitlement, exact request time, and cancellation path before scheduling it.
3. Observe the physical display locally, record independent UTC timestamps, and collect the test marker. Measure LAN and Tailscale in separate trials; active network probes are a separate wake source and must not be used as the sole evidence.
4. Record separately whether the screen turned on, a process ran while the display stayed off, LAN responded, and Tailscale responded. These are different outcomes.
5. Cancel the event immediately after the bounded trial and verify cancellation. Confirm no assertion, recurring job, or scheduled event remains.

**Pass evidence:** An independently timed event observed while the device remained physically locked, without a manual interaction or unaccounted network trigger, plus a marker showing userspace execution before unlock. A delayed event first observed after manual unlock is not a pass. Repeatability and recovery are required before any reliability claim; one trial never establishes 24/7 unattended behavior.
