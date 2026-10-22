# P012 — Cloud validation

P012 cloud engineering is offline and does not require the target iPad. The probe and trial controller are inert by default; tests mock subprocess execution. CI does not initiate SSH connections or change device power state.

## Local commands

```sh
python3 -m json.tool experiments/p012/protocol-v1.json >/dev/null
python3 -m json.tool experiments/p012/protocol-v1.schema.json >/dev/null
python3 -m json.tool experiments/p012/trial-record-v1.schema.json >/dev/null
python3 -m py_compile scripts/p012_common.py scripts/p012_host_probe.py scripts/p012_trial.py scripts/p012_analyze.py
python3 -m unittest discover -s tests -p 'test_p012_research.py' -v
```

Run existing regression suites separately:

```sh
./scripts/build-linux-test.sh
python3 tests/integration.py
python3 -m unittest discover -s tests -p 'test_p009_evidence.py' -v
python3 -m unittest discover -s tests/packaging -p 'test_p010_signing.py' -v
python3 -m unittest discover -s tests/packaging -p 'test_rootful_package.py' -v
python3 -m unittest discover -s tests -p 'test_p011_preflight.py' -v
```

## Current cloud regression results

The local Linux cloud run completed with the following deterministic suites:

| Suite | Tests | Result |
|---|---:|---|
| Linux integration (P001–P008 product regressions) | 45 | PASS |
| P009 evidence validator | 55 | PASS |
| P010 signing/release gate | 13 | PASS |
| Rootful package regression | 21 | PASS |
| P011 release preflight | 27 | PASS |
| P012 protocol, probe mocks, safety, privacy, analysis, and P009 mapping | 52 | PASS |

These local counts demonstrate cloud regressions only. GitHub Actions reruns them at the exact PR head and attaches the P012 source SHA and simulated report.

## Dedicated CI job

`p012-idle-research-validation` checks both JSON formats and runtime protocol invariants; compiles the P012 Python files; runs P012 subprocess-mock/safety/privacy/analysis tests; reruns the P009 compatibility regression; generates a 24-record simulated report; records `git rev-parse HEAD`; and uploads the deterministic JSON/Markdown analysis and test logs. CI records are labeled `SIMULATED`; they cannot pass physical gates.

The job does not modify P009 validators, P010 signing, P011 release preflight, Linux protocol jobs, iOS cross-builds, package validation, or other milestones. PR branch protection remains the repository's responsibility; no merge or release is performed by the job.

## Hardware status

P012 physical trials were not run during cloud engineering. P011 stable package installation, installed-path execution, and package-specific acceptance remain required. The known `ldid` provenance blocker is not bypassed. See [P011 validation](P011-VALIDATION.md) and the [P012 experiment protocol](P012-EXPERIMENT-PROTOCOL.md).
