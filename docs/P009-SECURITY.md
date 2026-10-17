# P009 — Security and Trust Boundaries

## Offline boundary

`validate`, `replay`, `report`, and `review` operate on an explicit local path using Python's standard library. They do not open sockets, scan a network, SSH to a device, invoke target commands, or persist a monitor. The tests patch socket creation to fail if an accidental network call is added.

The future observer contract is a data format for an operator-controlled second computer. P009 does not ship or start a live observer. Any future live observer must require explicit host/IP and transport, bounded attempts and timeouts, no discovery/scanning, no stored prompt secrets, and no automatic login unless separately configured and authorized.

## Untrusted inputs

Evidence packages are untrusted. The validator checks JSON duplicate keys, schema versions, required fields, safe relative paths, manifest/file agreement, file-count/size limits, exact package contents, and SHA-256 hashes before interpreting the session. It rejects symlinks and special files, including links outside the evidence root. It does not execute scripts or load arbitrary code from evidence.

Manifest hashes catch accidental changes and mismatches. They do not prove who collected evidence, whether a device is genuine, or whether an operator statement is truthful. P009 creates no signing keys and claims no cryptographic authenticity.

## Hardware claims and review

`SIMULATED`, `MOCK`, and `CI` data are blocked from all physical gates. A session's `review_status` is only an input claim. A structurally complete physical-source session is `REVIEW_REQUIRED` until an operator invokes `review` and approves gates individually after examining provenance and attached evidence. The review output is not a signature and is not authenticated by this program.

No evidence report authorizes unattended operation. No failed release, incomplete cleanup, or unresolved assertion can be treated as a successful trial. A connectivity result requires independently recorded authenticated SSH; a local daemon or connected Tailscale indicator alone is insufficient.

## Data minimization

Do not include passwords, keys, tokens, credentials, private files, or unrelated user data. Common secret field names, private-key markers, and recognizable token forms are rejected. The report omits arbitrary event detail values and does not print attachment contents. Operators must still inspect screenshots and binary attachments for private material that automated text checks cannot identify.

Evidence input is size-limited to bound memory use. Individual files are capped at 2 MiB, sessions at 2 MiB, manifests at 256 KiB, and total package data at 16 MiB. If future observations need larger media, revise the limits and review tests before adopting the new format.
