# P018 Manifest

- Milestone: P018 — CLI & Package Manager User Experience.
- Branch: `ios/p018-cli-package-ux`.
- Intended integration base while P017 is open: `ios/p017-scheduling-v2`.
- Package identity and paths are unchanged: `com.ioscaffeinate.cli`, `iphoneos-arm`, `/usr/local/bin/ios-caffeinate`, `/usr/local/bin/ios-caffeinated`, `/usr/local/bin/ic`, `/usr/local/libexec/ioscaffeinate-manager`, `/var/lib/ioscaffeinate/`, `/var/log/ioscaffeinate/`.
- New package tools: `p018_evidence.py`, `p018_validate_export.py`, `p018_package_preflight.py`; P009 validator is also installed beside them. All are checksum-covered.
- Release version remains the existing package source version. No v0.2.0 tag or release is created.
- No iPad was accessed during P018 cloud engineering.
- Hardware status: `P018_CLOUD_COMPLETE_DEVICE_UX_PENDING`.

See [architecture](P018-ARCHITECTURE.md), [CLI contract](P018-CLI-CONTRACT.md), [errors](P018-ERROR-CODES.md), [package preflight](P018-PACKAGE-PREFLIGHT.md), [upgrade/rollback](P018-UPGRADE-ROLLBACK.md), [evidence export](P018-EVIDENCE-EXPORT.md), [security](P018-SECURITY.md), [device acceptance](P018-DEVICE-ACCEPTANCE.md), [validation](P018-VALIDATION.md), and [operator guide](OPERATOR-GUIDE.md).
