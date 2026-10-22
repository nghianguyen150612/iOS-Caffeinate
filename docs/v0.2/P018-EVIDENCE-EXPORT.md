# P018 Evidence Inventory and Export

## Inventory

```sh
ic evidence status
ic evidence inventory
ic evidence validate
```

The fixed inventory looks for P009 session/manifest records and validated P009 attachments; known P011, P012, P013, P014, P015, P016, and P017 records under `/var/lib/ioscaffeinate/evidence`; and the packaged P010 operator-reported record. A defined path does not make a record present. Missing, present, invalid, unknown provenance, unreviewed, and operator-reported states remain distinct. The P010 report is inventoried but excluded by default because it contains raw assertion IDs and device-specific observations.

P009 validation is authoritative for hardware acceptance. Parsing or a human `REVIEWED` claim is reported as a claim; P018 never changes a P009 v1 event definition or automatically accepts a gate.

## Explicit export

Preview without writes:

```sh
ic evidence export --dry-run
```

Create a new bundle only after privacy review, using a new absolute destination whose parent already exists and is root-controlled:

```sh
ic evidence export --output "/var/root/ioscaffeinate-p018-export"
```

The final directory must not already exist. Export requires root on the rootful device. The result contains a versioned manifest, sanitized inventory and doctor snapshots, selected allowlisted records, per-file SHA-256, content type, size, source ID, provenance/review labels, package/build identity when available, and a UTC timestamp. The manifest states `hardware_evidence_accepted=NOT_ESTABLISHED`.

The tool does not recursively archive `/var`. It excludes SSH keys/logs, Tailscale credentials, tokens, process environments, unrelated logs, and arbitrary application/user files. It rejects credential-like fields, key/token material, IPv4/IPv6 and MAC addresses, assertion ID fields, and private home/application-data paths. It follows only P009-manifest attachment paths after P009 validation. Unknown content is conservatively excluded.

An operator may explicitly add an extra record after reviewing it:

```sh
ic evidence export --output "/var/root/ioscaffeinate-p018-export" \
  --include-operator-file "/var/root/reviewed-observation.json"
```

Only singly linked, root-owned JSON, UTF-8 text, or CSV files are accepted. They are scanned separately, receive `UNKNOWN`/`UNREVIEWED` provenance labels, and their source paths and original filenames are not placed in the bundle. A file containing raw assertion IDs or other prohibited identifiers is rejected; prepare a separately reviewed, sanitized copy before opting it in. `--include-operator-file` is repeatable.

## Bounds and validation

Per-file size is capped at 2 MiB, aggregate content at 16 MiB, and the bundle at 129 files. Sources must be no-follow, regular, singly linked, root-owned files. The destination is created with mode `0700`; files and manifest use `0600`. Destination parents are checked without following symlinks. Existing destinations are never overwritten. Sources are revalidated immediately before copy. The final manifest is atomically published after content and checksums are complete; its validation field requires the standalone validator and does not self-attest. SIGINT/SIGTERM trigger cleanup. A process kill may leave an incomplete directory; it is not reported as a completed export.

Validate offline on Linux or macOS:

```sh
python3 scripts/p018_validate_export.py "/absolute/path/to/export"
```

The validator checks schema, unique paths and JSON keys, containment, allowed types, encoding, provenance labels, size bounds, hashes, and privacy filters. It never executes bundle contents. `EXPORT_CREATED` means only that a consistent bundle was created. It does not mean `HARDWARE_EVIDENCE_ACCEPTED`.
