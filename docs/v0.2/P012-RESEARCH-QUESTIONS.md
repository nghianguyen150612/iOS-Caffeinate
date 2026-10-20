# P012 — Research questions and interpretation boundaries

P012 asks whether a bounded iOS-Caffeinate assertion is associated with authenticated SSH reachability after a controlled idle period. It separates four questions and treats LAN and Tailscale as distinct routes.

## Questions

| ID | Comparison | Question | What the result can say |
|---|---|---|---|
| RQ1 | A versus C, separately for LAN and Tailscale | Does an active `PreventUserIdleSystemSleep` assertion change the observed probability of authenticated SSH success after quiet idle? | An observed route-specific association under the recorded conditions. It cannot prove that iOS stayed awake or that the assertion caused the result. |
| RQ2 | A versus B, separately for LAN and Tailscale | Does running the foreground daemon in IDLE without an assertion change SSH reachability? | An observed association with daemon-only availability. This does not measure assertion effectiveness. |
| RQ3 | C versus D, separately for LAN and Tailscale | What is observed after an assertion has expired or has been released and release is confirmed? | A post-release observation while the daemon remains running. D is not equivalent to A and may include carryover. |
| RQ4 | LAN versus Tailscale within each condition | Do authenticated SSH outcomes differ by route? | Separate route-specific observations. Tailscale peer status and authenticated SSH are distinct evidence. |

The comparison tool never pools LAN and Tailscale. Each trial has one route and one SSH command. Route order is counterbalanced over the three repetitions, and condition order is also preregistered. Paired route observations remain clustered by repetition and do not become independent samples merely because they are separate SSH processes.

## What each observation means

| Observation | It establishes | It does not establish |
|---|---|---|
| IOKit assertion acquisition succeeds | The API accepted an assertion request at that time. | That the OS prevented suspend, that the display stayed locked, or that SSH will remain reachable. |
| Daemon is running | A process is available to report or manage state while it executes. | That iOS will schedule it after suspension or that an assertion is active. |
| Display is locked | The operator observed a locked display at the recorded time. | OS suspend, deep sleep, or a quiet background state. |
| SSH transport connects | An SSH service was reachable on the selected route at one instant. | Successful authentication or continued availability. |
| SSH authenticates and runs `true` | The configured SSH client authenticated and completed one minimal remote command. | That a power assertion caused success or that the device avoided suspend. |
| Tailscale peer is shown connected | A separately observed Tailscale peer state at its observation time. | Authenticated SSH reachability. P012's host probe does not query peer status. |
| Several sparse probes succeed | The measured route was reachable at those sampled instants. | Long-duration server reliability, uninterrupted background execution, or scheduled wake. |

Repeated authenticated SSH can affect idle behavior. The operator performs a no-probe quiet interval before each trial, then makes at most one route-specific probe. There are no ping loops, port scans, status polling, or daemon polling during quiet time.

## Previously reported observations — October 18, 2026

The following are preserved as operator-reported observations and are not P012 measurements:

- Native CLI execution: PASS.
- Foreground daemon execution: PASS.
- IOKit assertion acquire/release: PASS.
- 30-second timed expiry: PASS.
- Explicit STOP: PASS.
- SIGTERM cleanup: PASS.
- LAN SSH: 24/24 successful.
- Tailscale SSH: 24/24 successful.
- The operator reported the iPad display remained locked throughout the SSH measurement window.
- In the 180-second assertion observation, acquisition was reported at approximately 20:15:01 and release at approximately 20:18:01. SSH observations ran approximately 20:16:09–20:18:25. The reported time zone and clock uncertainty were not captured.

These observations used manually staged binaries, not the installed signed stable Debian package. They have no controlled no-assertion baseline; the SSH commands may have influenced idle behavior; the SSH window extended beyond the reported assertion release; and P009 human evidence review remains required. Do not recast them as causal or controlled results, and do not copy their timestamps into trial records.

P012 can conclude “no observable difference,” “observed association,” “inconclusive,” “insufficient data,” or “not identifiable.” A higher success percentage is not an automatic PASS or a causal improvement claim. If A and C both show 100% success, the report explicitly states that the tested conditions did not demonstrate an observable difference.
