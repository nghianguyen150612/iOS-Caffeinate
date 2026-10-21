# P019 Validation

P019 CI is named `p019-supervised-reliability-validation`. It checks the preregistered protocol and schemas; runs the offline P019 session, analysis, fault, and side-effect-boundary cases; checks P009/P012/P018 compatibility; verifies the checked-out source SHA; and uploads deterministic `SIMULATED`/`MOCK` artifacts only.

The P019 job depends on the existing Linux protocol, iOS ARM64 cross-build, Mach-O inspection, rootful packaging, and P009–P018 validation jobs. Existing release/signing gates remain enabled. P008 attestation retains its existing branch guard and may be skipped only under that documented guard.

Cloud validation commands:

```sh
python3 scripts/p019_session.py plan
python3 -m unittest discover -s tests -p 'test_p019_session.py' -v
python3 scripts/p019_session.py validate --session /path/to/session.json
python3 scripts/p019_session.py analyze --session /path/to/session.json
python3 scripts/p019_session.py report --session /path/to/session.json --format markdown
```

`init` and `record-confirmation` explicitly write a new local host file. All other P019 commands are offline and read-only. No CI step runs SSH, starts a daemon, changes launchd, acquires IOKit assertions, installs/removes/rolls back packages, or touches a physical device.

Passing the job proves cloud code and deterministic fixtures only. Generated records remain synthetic and hardware acceptance remains pending.
