# P014 — Manifest

- Milestone: P014, Daemon Crash Recovery and Restart-Loop Protection
- Branch: `ios/p014-crash-recovery`
- Repository: `https://github.com/nghianguyen150612/iOS-Caffeinate`
- Effective starting SHA: `3d7b5d4c700194ab71713c51577e7a7cf0acd48c`
- Effective merge-base: `3d7b5d4c700194ab71713c51577e7a7cf0acd48c`
- Stacked PR base: `ios/p013-launchd-lifecycle`
- Predecessor PRs: P011 #10, P012 #11, and P013 #12 were open at preflight
- Predecessor P013 exact-head CI: run `39399231884`, successful
- Target: iPad mini 2 A1489 / iPad4,4, iOS 12.5.7, Apple A7 ARM64, Amethyst/Procursus rootful
- Components: `ios-caffeinate` / `ic`, `ios-caffeinated`, package `com.ioscaffeinate.cli`
- Recovery journal: `/var/lib/ioscaffeinate/recovery-state.json`, schema 1, policy 1
- Limits: 3 attempts per 10 minutes; backoff 5/15/60 seconds; 30-minute healthy reset
- Automatic runtime restart: `NO`
- P013 launchd mutation gates: `PRESERVED; UNVERIFIED ON DEVICE`
- Managed profile: `KeepAlive=false`
- P009 schema: v1 retained; CI source classes are `SIMULATED` or `MOCK`
- Device recovery: `PENDING`
- Final source SHA, PR URL, and exact-head CI are recorded by the P014 workflow artifact and final submission report; they are not embedded as a self-referential commit value.
- Stable v0.1.0 release/tag/assets: unchanged
- v0.2.0 release/tag: not created

This manifest describes cloud engineering only. It does not certify iOS launchd compatibility, assertion cleanup after process death, boot persistence, SSH reachability, OS awake state, or long-duration reliability.
