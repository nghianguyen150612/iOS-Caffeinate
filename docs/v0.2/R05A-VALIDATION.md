# R05A Validation Record

**Source under review:** R05 baseline `b2fdea8764ba08a8f60fe4d5acae2705dce7bd37`; the corrected branch and final workflow run IDs will be recorded after the exact-source GitHub checks complete.

## Completed local checks

- The authentic failed R05 receipt, package hash, source commit, binary hashes, H003 signer identity, and profile identity were checked against the downloaded evidence.
- Independent parsing of both failed Mach-O signatures verified all 53/35 code-slot hashes, special slots 2/5/7, CodeDirectory v2.4 metadata, entitlement identities, and the signature's `__LINKEDIT` placement. Both CodeDirectories had flags `0`.
- The pinned H003 signer was run on copies of both exact unsigned inputs using `-Cadhoc -S` and the unchanged approved profile. Both outputs had flags `0x2`; independent hashes and exact entitlements passed.
- Regression tests cover the required ad hoc flag, valid code and special-slot hashes, missing CodeDirectory, malformed SuperBlob offsets, changed executable bytes, changed special-slot hashes, altered entitlement content, truncation, wrong architecture, receipt run binding, and source/package digest mismatch.

## GitHub-hosted validation

| Check | Run / result |
|---|---|
| R05A exact-head PR CI | Pending first pushed R05A source |
| Authentic macOS comparison workflow | Pending first pushed R05A source; it captures the genuine unsigned, failed H003, Apple-native ad hoc diagnostic, and v0.1.0 historical cases |
| Corrected signed-candidate workflow | Pending exact-source R05A CI and Apple macOS verification |
| Final candidate inventory and fresh-extraction validation | Not available until all prior gates pass |

## Qualification boundary

No device transfer or operation was performed. Physical H004, P011, P012, P013, P014, P016, and P019 evidence remains pending. A completed macOS host check will not establish iOS runtime behavior or target-device acceptance.
