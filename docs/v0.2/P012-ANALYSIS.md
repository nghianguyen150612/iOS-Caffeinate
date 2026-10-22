# P012 — Offline analysis

Run the standard-library analyzer on stored JSON records without network access:

```sh
python3 scripts/p012_analyze.py /secure/private/p012-records --format markdown
python3 scripts/p012_analyze.py /secure/private/p012-records --format json
```

The report groups every evidence origin by condition and route, counts trials and attempted probes, computes success percentages, summarizes successful SSH elapsed time by median/IQR/range, separates failure classes, and lists interrupted, invalid, incomplete, duplicate, and missing observations. LAN and Tailscale are never combined.

Primary comparison pairs use valid route-specific repetitions only: A/C, B/C, and C/D. A separate LAN-versus-Tailscale summary for each condition uses only matching `pair_id` and repetition records. Unmatched pairs are exposed and reduce the matched sample; route samples are never combined into a single success rate. The analyzer flags quiet-window or timeout differences, clock discontinuities, timebase changes, high uncertainty, battery/charging/thermal/Wi-Fi changes, reboot/respring reports, missing repetitions, and invalid/incomplete trials. It never converts a higher percentage into PASS or a causal claim. Identical windows are necessary for an interpretable matched comparison; an unequal window can make the result `NOT_IDENTIFIABLE`.

## Outcome labels

| Label | Meaning |
|---|---|
| `NO_OBSERVABLE_DIFFERENCE` | Both conditions show the same observed outcome; if both are 100%, the report says the tested conditions did not demonstrate an observable difference. This is not equivalence or proof of sleep prevention. |
| `OBSERVED_ASSOCIATION` | One condition shows a higher/lower observed percentage with sufficient exploratory pairs; alternative explanations remain. |
| `INCONCLUSIVE` | Mixed, confounded, or unstable observations do not support a clear comparison. |
| `INSUFFICIENT_DATA` | Fewer than three valid matched repetitions are available. |
| `NOT_IDENTIFIABLE` | No matched valid data exist, or observation-window/timebase problems prevent comparison. |

Invalid and incomplete records remain visible in the report but are excluded from the primary valid success percentage. Raw attempted-probe totals and valid-only totals are both shown. Duplicate trial IDs and duplicate condition/route/repetition cells are flagged and excluded from valid comparisons.

## Statistical limits

P012 is a small exploratory study on one iPad. Trials can share a day, operator, Wi-Fi environment, battery/thermal state, daemon state, and carryover. The analyzer does not calculate confidence intervals or significance because a simple independent-probe assumption is not justified. Three repetitions do not establish strong evidence. A strong-evidence classification is never emitted by this milestone.

Authenticated SSH is a sampled result, not an observation of OS suspend. A successful IOKit call does not show that iOS stayed awake; a screen lock is not deep sleep; and Tailscale peer status does not substitute for SSH authentication. The report keeps assertions, daemon availability, screen state, route, transport, authentication, battery/thermal observations, release cleanup, and long-duration reliability separate.

## Simulated example

The CI fixture contains 24 `SIMULATED` records (three repetitions in each condition/route cell). It gives every route 3/3 authenticated successes in A, B, C, and D. Its route-separated comparison includes:

| Origin | Route | Condition A | Condition C | Comparison |
|---|---|---:|---:|---|
| SIMULATED | LAN | 3/3 (100%) | 3/3 (100%) | `NO_OBSERVABLE_DIFFERENCE` |
| SIMULATED | TAILSCALE | 3/3 (100%) | 3/3 (100%) | `NO_OBSERVABLE_DIFFERENCE` |

The RQ4 example uses the same 3-repetition `pair_id` across routes within each condition. LAN and Tailscale remain separate route observations; the matched route comparison is descriptive only.

| Origin | Condition | Matched pairs | LAN success | Tailscale success | Route comparison |
|---|---|---:|---:|---:|---|
| SIMULATED | A | 3 | 100% | 100% | `NO_OBSERVABLE_DIFFERENCE` |
| SIMULATED | B | 3 | 100% | 100% | `NO_OBSERVABLE_DIFFERENCE` |
| SIMULATED | C | 3 | 100% | 100% | `NO_OBSERVABLE_DIFFERENCE` |
| SIMULATED | D | 3 | 100% | 100% | `NO_OBSERVABLE_DIFFERENCE` |

Example JSON excerpt (synthetic only):

```json
{
  "evidence_origins": ["SIMULATED"],
  "comparisons": [
    {
      "comparison": "A_vs_C",
      "route": "LAN",
      "matched_pair_count": 3,
      "left_success_percent": 100.0,
      "right_success_percent": 100.0,
      "outcome": "NO_OBSERVABLE_DIFFERENCE",
      "statistical_significance_claimed": false
    },
    {
      "comparison": "A_vs_C",
      "route": "TAILSCALE",
      "matched_pair_count": 3,
      "left_success_percent": 100.0,
      "right_success_percent": 100.0,
      "outcome": "NO_OBSERVABLE_DIFFERENCE",
      "statistical_significance_claimed": false
    }
  ],
  "evidence_strength": {
    "classification": "EXPLORATORY_ONLY",
    "strong_evidence_established": false
  },
  "route_comparisons": [
    {
      "condition_id": "A",
      "route_comparison": "LAN_vs_TAILSCALE",
      "matched_pair_count": 3,
      "lan_success_percent": 100.0,
      "tailscale_success_percent": 100.0,
      "outcome": "NO_OBSERVABLE_DIFFERENCE"
    }
  }
}
```

This fixture demonstrates report behavior only and is not device evidence. The report also exposes battery, thermal, route, assertion, quiet-period, result, and cleanup fields for future P015 policy review, without implementing a policy recommendation.
