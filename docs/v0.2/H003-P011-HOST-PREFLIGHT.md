# H003 P011 Host Preflight Result

**Observed:** 2026-10-22. **Command exit:** `0`. **Result:** `P011_HOST_PREFLIGHT_PASS_DEVICE_ACCEPTANCE_PENDING`.

H003 used the exact H001/P010 signer identity, rebuilt from the pinned Procursus commit twice in the newly recorded H003 environment, and compared both outputs with the required executable SHA-256. It retrieved the public GitHub v0.1.0 release and validated all eight published assets. The original release package was read and inspected; no package bytes, metadata, signature, tag, or release were changed.

## Observed report

| Check | Result |
|---|---|
| Public release identity and exact eight-asset set | `VERIFIED` |
| Package SHA-256 / size | `439d2543adbe1472f82cfd6c9e6bb9dd747da6c31c79f3da1f3da86b8ca9421c` / `95,572` bytes |
| Debian identity | `com.ioscaffeinate.cli`, `0.1.0-1`, `iphoneos-arm` |
| Historical archive | `VERIFIED` |
| Historical seven-record checksum contract | `VERIFIED` |
| Historical checksum coverage | `HISTORICALLY_PARTIAL` |
| Derived inventory and package structure | `VERIFIED` |
| Approved profile bytes | `amethyst-ios12-rootful`, SHA-256 `cd1358e7c8c3b01da98b5544e3c2ffcdc9d92cf9a3191e45038e8691ef2021ca` |
| CLI and daemon Mach-O | iOS ARM64, minimum iOS 12.0, code-signature blobs present |
| Embedded entitlements | Independently extracted; `EXACT_MATCH` for both executables |
| Signer source, build and executable provenance | `VERIFIED` |
| Signature integrity / cryptographic trust | `PENDING` / `NOT_ESTABLISHED_BY_SIGNATURE_PRESENCE_OR_THIS_PREFLIGHT` |
| Device acceptance | `PENDING` |
| Release authorization | `BLOCKED` |

The signed package contains seven published historical checksum records. The post-publication derived inventory checks archive layout but does not convert the old checksum list into a full original manifest. The verifier found 52 historically uncovered regular members, as recorded in the embedded report.

The complete machine-readable result is [H003-P011-HOST-PREFLIGHT.json](H003-P011-HOST-PREFLIGHT.json). It records the official release/tag identity, package checks, P010 legacy validation, entitlement inspection, and every hardware gate as pending. The H002 blocked run remains preserved as the contemporaneous H002 result in the earlier history; this H003 record supersedes only the current host-side signer availability state.

No device was accessed. No package was installed, daemon started, launchd state changed, assertion acquired, or release authorization granted. Physical P011 acceptance and signature integrity remain open.
