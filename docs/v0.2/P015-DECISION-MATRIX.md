# P015 — Decision Matrix

The evaluator collects every applicable blocker in stable gate order. Its primary decision follows this precedence: invalid configuration; duration error; P014 recovery block; unsafe daemon state; active assertion conflict; explicit resource denial; missing or stale evidence; eligibility.

| Inputs | Result | Reason |
|---|---|---|
| No config | `DISABLED` | `CONFIG_MISSING_DISABLED` |
| Valid v1 disabled / observe-only | `DISABLED` / `OBSERVE_ONLY` | v1 meaning is retained |
| Unsupported or unsafe config | `BLOCK_UNSAFE_CONFIGURATION` | Version, schema, or file-safety failure |
| Valid v2 bounded session, missing P014 journal | `BLOCK_RECOVERY` | Journal is not evidence of cleanup |
| P014 `RELEASE_FAILED`, unclean process, unknown prior assertion ownership, or unverified cleanup | `BLOCK_RECOVERY` | P014 remains authoritative |
| Daemon `BLOCKED` | `BLOCK_UNSAFE_RUNTIME` | Resolve through P014 recovery handling |
| Existing active assertion | `BLOCK_ASSERTION_CONFLICT` | Do not overlap independent assertion ownership |
| Missing, stale, mock, simulated, CI, or unreviewed hardware evidence | `DEFER_INSUFFICIENT_EVIDENCE` | Collect current reviewed physical evidence |
| Explicit battery/thermal or hardware denial | `BLOCK_RESOURCE_SAFETY` | Resolve the reported safety condition |
| Zero, negative, overflowed, or excessive duration | `BLOCK_DURATION` | Duration must be 1..configured maximum and at most 300 seconds |
| All P011–P014, resource, network, runtime, and attendance gates valid | `ELIGIBLE_FOR_MANUAL_BOUNDED_SESSION` | A later separate operator authorization is still required |
| Unattended or automatic-recovery operation | `BLOCK_UNSAFE_CONFIGURATION` or `BLOCK_UNVERIFIED_SUPERVISOR` | P015 has no unattended executor |

The session gates are P011 signed-package acceptance, installed CLI execution, installed daemon execution, P012 idle/power review, assertion acquire, assertion release, P013 lifecycle compatibility, physical recovery, battery safety, thermal safety, LAN reachability, Tailscale reachability, and operator attendance. LAN and Tailscale are independent gates; evidence for one cannot replace the other. A successful CI run cannot pass a physical gate. SSH reachability is a network observation and does not prove that iPadOS is awake.

P014 journal cleanup and physical recovery evidence are separate. An operator-reviewed P014 reset may satisfy the P014 journal's own policy; it is not automatically device-verified physical recovery evidence.
