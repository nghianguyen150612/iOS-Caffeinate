# R05A Apple Code-Signature Root Cause

**Finding:** two signature metadata defects were reproduced. The first caused R05's “code object is not signed at all” failure. The first correction exposed a second designated-requirement mismatch. The signing path now supplies an explicit empty Requirements SuperBlob to the same pinned signer; the exact-source candidate workflow remains the authority for Apple verification and finalization.

## R05 failure: missing ad hoc flag

R05 signed both v0.2.0-rc1 executables with the pinned H003 Procursus `ldid` 2.1.5-procursus7 executable, but used `ldid -S<profile>`. The authentic receipt is bound to source `b2fdea8764ba08a8f60fe4d5acae2705dce7bd37`, package SHA-256 `18631b8aff5c25607a88ba4fc28c945d1b8a552903950ec73dbae386d695807e`, and reports exit 1 for both binaries with `code object is not signed at all`.

Independent byte parsing found internally consistent Mach-O signatures and all CodeDirectory page and entitlement special-slot hashes verified, but both CodeDirectories had flags `0`. The pinned signer source at commit [`aaf8f23`](https://github.com/ProcursusTeam/ldid/tree/aaf8f23d7975ecdb8e77e3a8f22253e0a2352cef) defines `kSecCodeSignatureAdhoc=0x0002` and sets it for `-Cadhoc` ([`ldid.cpp`](https://github.com/ProcursusTeam/ldid/blob/aaf8f23d7975ecdb8e77e3a8f22253e0a2352cef/ldid.cpp#L3491-L3496)). The first correction therefore added `-Cadhoc` while retaining the approved profile.

## Second failure: default designated requirement conflicts with ad hoc signing

The exact-source candidate from `0c19552ddb74c78bffc5ba16d434054268c61b40` tested that first correction in [candidate run 40064205079](https://github.com/nghianguyen150612/iOS-Caffeinate/actions/runs/40064205079). The signed input package SHA-256 was `f920e8455773d0a5994856b88ac1f65c69f094c89fbcad2fcb08941738a90d7a`; the failed receipt SHA-256 is `f17459b43c55af8fe0475930121c5de5cdc2e5eee71fc04b7eb13e2e9e8cb4a0` (artifact ID `12549330339`). Both Apple commands returned exit 3 and reported `valid on disk` followed by `does not satisfy its designated Requirement`. The finalizer was skipped. This failed package and receipt remain diagnostic evidence only.

The candidate binaries had CodeDirectory flags `0x2`; all code slots, special slots 2/5/7, and exact XML/DER entitlements independently verified. Their Requirements SuperBlobs each contained one requirement (type 3). In the pinned source, when no `-Q` requirements input is supplied, `ldid` creates a designated requirement containing the executable identifier, `anchor apple generic`, a `subject.CN` certificate field, and an Apple extension test ([source lines 2268–2292](https://github.com/ProcursusTeam/ldid/blob/aaf8f23d7975ecdb8e77e3a8f22253e0a2352cef/ldid.cpp#L2268-L2292)). That certificate requirement cannot match an ad hoc signature, which has no signing certificate or CMS blob. The host's “valid on disk” output and the independently verified hashes show that this failure was a requirement mismatch, not a malformed CodeDirectory, hash inconsistency, or iOS-targeted Mach-O rejection.

The candidate's raw Requirements SuperBlobs were 132 bytes, each with count 1 and type 3. Their hashes were `988826a4d1629fbe2c8ba5b499b532a9e9d00c7b292c52ac0dc3e9a4bc96057a` (`ios-caffeinate`) and `831a2c150da128499b8bcf1373b992908fb057d44e825303cbd82818c81eaa4b` (`ios-caffeinated`). The independent parser now reports requirement count and types and the RC gate requires exactly zero requirements.

## Supported correction and security impact

The builder now invokes the same pinned H003 signer with the same approved entitlement profile and an explicit raw empty Requirements SuperBlob:

```text
ldid -Cadhoc -Q<empty-requirements.superblob> -S<amethyst-ios12-rootful.plist> <binary>
```

The input is exactly `fade0c010000000c00000000` (12 bytes), SHA-256 `987920904eab650e75788c054aa0b0524e6a80bfc71aa32df8d237a61743f986`. This is the empty Requirements SuperBlob emitted for Apple's native ad hoc diagnostic signatures. The pinned H003 executable accepted the raw blob through its supported `-Q` input. On copies of the exact-source unsigned binaries, the corrected command produced flags `0x2`, requirement count zero, verified code and special-slot hashes, and the exact approved entitlement set.

This changes only the embedded designated-requirement policy from an unsatisfiable certificate identity condition to no embedded identity condition. It does not change the signer, signing profile, entitlement set, executable bytes before signing, or host acceptance contract. The source/package hashes, pinned signer provenance, profile hash, binary hashes, independent CodeDirectory audit, and genuine Apple `codesign --verify --strict` checks remain enforced. The independent parser and finalizer both reject a nonempty requirement set. Both Apple checks must still pass before finalization. No Apple-native signature is used in the candidate.

**Confidence:** high for both observed root causes and for the local structural correction, based on authentic run-bound receipts, extracted candidate bytes, the pinned signer's source, and exact-source local copies. Apple verification and RC finalization are determined only from the corrected exact-source candidate workflow result; this document does not substitute a local parser result for that gate.

No corrected package is authorized for transfer or installation. Physical acceptance remains separate from host signature verification.
