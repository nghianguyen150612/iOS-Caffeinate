# R05A Apple Code-Signature Root Cause

**Status:** root cause confirmed by the authentic macOS comparison. Corrected-candidate verification and finalization are established separately for each exact PR source commit by the candidate workflow.

## Finding

R05 signed both v0.2.0-rc1 executables with the pinned H003 `ProcursusTeam/ldid` 2.1.5-procursus7 binary and the approved `amethyst-ios12-rootful` profile. The packaging command used `ldid -S<profile>`. In the pinned source, `-S` creates a fakesign and the CodeDirectory flags begin at zero. The `-Cadhoc` option sets `kSecCodeSignatureAdhoc` to `0x0002`. The documented mode for an ad hoc signature with entitlements is `-Cadhoc` together with `-S<profile>`.

The authentic failed receipt for package SHA-256 `18631b8aff5c25607a88ba4fc28c945d1b8a552903950ec73dbae386d695807e` records Apple `codesign` returning exit 1 for both binaries with `code object is not signed at all`. Independent parsing found internally consistent CodeDirectories and entitlement links, but `flags=0` and no CMS blob. Direct signing of copies with the exact pinned H003 executable and `-Cadhoc -S<profile>` produced `flags=2`; all executable-page and special-slot hashes verified and both entitlement sets matched.

Evidence for the mode distinction is in Procursus `ldid` source commit `aaf8f23d7975ecdb8e77e3a8f22253e0a2352cef`: `docs/ldid.1` lines 160–174 describe `-S` as fakesigning and `-Cadhoc` as marking an ad hoc signature; `ldid.cpp` lines 1080–1083 define `kSecCodeSignatureAdhoc = 0x0002`, line 3351 initializes flags to zero, and lines 3491–3496 set the flag for `-Cadhoc`. The local H003 executable hash was verified as `15329a4714608bcfd61717fd2e6dd4fd1aec48965fa90dd312a94ed9e6d7093c`.

## Correction and confidence

The production package builder now invokes the same pinned signer with `-Cadhoc -S<profile>`. It still requires the pinned signer, exact profile bytes, unchanged entitlement policy, signature-only binary transformation, and matching extracted entitlements. A bounded independent parser validates the Mach-O layout, CodeDirectory, every code-slot hash, requirements and entitlement special-slot hashes, and the ad hoc flag. Apple `codesign --verify --strict` remains a separate required finalization gate.

The macOS diagnostics workflow [run 40064018459](https://github.com/nghianguyen150612/iOS-Caffeinate/actions/runs/40064018459), on source `8f61de738d2fe9f402d3ea247071d6aa41bae82c`, compared the genuine unsigned binary, genuine R05 `ldid` output, separate Apple-native ad hoc copies, and byte-pinned v0.1.0 binaries on macOS 26.6.2 with Xcode 26.6. Both Apple-native copies had flags `0x2`, exact entitlements, and passed Apple `codesign --verify --strict --verbose=4`. The failed R05 inputs and v0.1 controls had flags `0` and failed with “code object is not signed at all.” This confirms the missing `CS_ADHOC` flag as the root cause. The corrected exact-source package still requires its own Apple verification and finalization run.

No Apple-signed diagnostic copy is a candidate input. No failed receipt is changed. If either corrected binary fails Apple verification, finalization remains blocked and the failure receipt is retained.
