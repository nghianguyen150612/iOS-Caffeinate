# H005 — Bounded dpkg audit exception review

## Warning type and metadata-package hypothesis

The reported warning category is **missing the `md5sums` control file in the dpkg database**. Under `LC_ALL=C`, the dpkg warning header is:

```text
The following packages are missing the md5sums control file in the
database, they need to be reinstalled:
```

The dpkg audit implementation checks the info-file's presence for installed package records; it does not exempt an empty package file list. See [`audit_infofile` and the `HASHFILE` audit category](https://salsa.debian.org/dpkg-team/dpkg/-/blob/main/src/main/audit.c). Thus `install ok installed` plus a `/.` file-list marker does not by itself clear the audit warning.

The device-reported count is 173 entries:

| Prefix/category | Reported count |
|---|---:|
| `gsc.*` | 166 |
| `cy+cpu.*` | 2 |
| `cy+kernel.*` | 1 |
| `cy+lib.*` | 1 |
| `cy+model.*` | 1 |
| `cy+os.*` | 1 |
| `firmware` | 1 |

There is a source-backed metadata-package hypothesis. The Cydia `firmware.sh` generator creates pseudo-package records for firmware, `gsc.*` GraphicsServices capabilities, and `cy+` OS/CPU/model/kernel/CoreFoundation dependencies. It writes `/.` into each `.list` file and writes `Status: install ok installed`, `Essential: yes`, and `Installed-Size: 0` into the status database. It does not create `.md5sums` files. See [the generator at Cydia commit `bb0ace74560c5c96c8dbefec00c8e3881c504558`](https://github.com/autopear/Cydia/blob/bb0ace74560c5c96c8dbefec00c8e3881c504558/Library/firmware.sh).

This source explains how such records can produce this warning without an ordinary payload, but it does not prove that the target device generated these records with that script. It must be verified against the actual complete warning list, exact status records, descriptions, architectures, versions, file lists, and info-file paths. The two `cy+cpu.*` entries deserve specific review: this target's reported ARM64 generator input implies `cy+cpu.arm64`; the extra entry must be identified and independently explained. The tool does not accept an unexplained second CPU pseudo-package.

## Capture procedure

Perform this only during the attended H004 read-only inspection with the operator physically present, independent local recovery ready, and secure private evidence capture active. Do not repair, edit, reconfigure, reinstall, remove, or normalize any package. Do not write capture files on the iPad. Preserve every raw stdout/stderr stream and each command or wrapper exit code in the private evidence destination; record the exact command, executable path/hash, dpkg version, timebase, UTC and uncertainty. Hash the preserved capture files after collection. Do not commit them or upload them to CI.

1. Capture the whole audit once with an English diagnostic locale:

   ```sh
   LC_ALL=C dpkg --audit
   ```

   Preserve the exact output, stderr, and exit code. The expected warning header is the dpkg missing-`md5sums` category (it may be wrapped over two lines by the installed dpkg version). Record every listed package name. Any other warning section, unknown database-directory entry, nonzero exit, or unreadable output blocks the proposed exception.

2. Using **all package names from the captured warning**, query their database records in one read-only command. The argument list must come from the captured output, not from the expected prefixes. First copy only the 173 validated package-name tokens into the local shell variable; the placeholder below is not an executable package name:

   ```sh
   set -f
   packages='<space-separated names copied from the captured warning>'
   LC_ALL=C dpkg-query -W -f='${Package}\t${Status}\t${Version}\t${Architecture}\t${Essential}\t${Installed-Size}\t${Description}\n' $packages
   ```

   Preserve output, stderr, and exit code. Review one unique row per warning name, exact `install ok installed` state, nonempty version, `iphoneos-arm` architecture, `Essential: yes`, `Installed-Size: 0`, and the pseudo-package descriptions from the generator. Check the target-specific identities and versions against the separately captured device `hw.machine`, iOS version, CPU, kernel, and CoreFoundation version. A missing, extra, duplicated, malformed, or mismatched record blocks acceptance.

3. Query file lists for the same complete name set. The following wrapper frames each actual `dpkg-query -L` output and exit code without writing a file on the device; capture its stdout and stderr externally. Replace the placeholder list with the exact names from step 1:

   ```sh
   set +e
   set -f
   packages='<space-separated names copied from the captured warning>'
   for p in $packages; do
     printf 'PACKAGE\t%s\n' "$p"
     LC_ALL=C dpkg-query -L "$p"
     query_rc=$?
     printf 'EXIT\t%s\t%s\n' "$p" "$query_rc"
   done
   ```

   Require one `/.` result and exit `0` for every package. Any ordinary path, missing marker, query failure, or package-name mismatch is a database inconsistency, not a metadata exception.

4. For those same names, inspect `/var/lib/dpkg/info/<package>.list` and `.md5sums` path types without changing them. Capture a framed TSV record for every package with the following read-only checks; `.list` must be a regular non-symlink file and `.md5sums` must be absent:

   ```sh
   set -f
   packages='<space-separated names copied from the captured warning>'
   for p in $packages; do
     base="/var/lib/dpkg/info/$p"
     if [ -L "$base.list" ]; then list_state=SYMLINK
     elif [ -f "$base.list" ]; then list_state=REGULAR
     elif [ -e "$base.list" ]; then list_state=OTHER
     else list_state=ABSENT; fi
     if [ -L "$base.md5sums" ] || [ -e "$base.md5sums" ]; then md5sums_state=PRESENT
     else md5sums_state=ABSENT; fi
     printf '%s\t%s\t%s\n' "$p" "$list_state" "$md5sums_state"
   done
   ```

   Capture BSD `stat -f '%N|%HT|%u:%g|%Sp|%z|%l'` output for each present `.list` file and preserve each command result. Review that the file contents are only the `/.` marker and that owner/type/size/link metadata is consistent with the package database. A present `.md5sums`, symlinked, nonregular, unreadable, or mismatched info file blocks the hypothesis.

5. The offline checker can validate the captured shape. Its input files are references to private captures and a derived tab-separated capture of the read-only queries; keep raw stdout/stderr untouched beside them. `--file-lists` uses the exact framed output from step 3. `--info-files` has one reviewed row per package: `<package>\tREGULAR\tABSENT`.

   ```sh
   python3 scripts/h005_validate_dpkg_exception.py \
     --audit-stdout /private/H004/dpkg-audit.stdout \
     --audit-stderr /private/H004/dpkg-audit.stderr \
     --audit-exit-code 0 \
     --records /private/H004/dpkg-query-records.tsv \
     --records-stderr /private/H004/dpkg-query-records.stderr \
     --records-exit-code 0 \
     --file-lists /private/H004/dpkg-query-file-lists.stdout \
     --file-lists-stderr /private/H004/dpkg-query-file-lists.stderr \
     --file-lists-exit-code 0 \
     --info-files /private/H004/dpkg-info-files.tsv \
     --info-files-stderr /private/H004/dpkg-info-files.stderr \
     --info-files-exit-code 0
   ```

   Replace the sample paths and exit values with the actual private capture references and recorded results. The script rejects empty audit output, unexpected warning categories, any count or set mismatch, incomplete query coverage, unexpected status/metadata, non-lone `/.` file lists, and present `.md5sums` files. Its success string is `H005_DPKG_AUDIT_TECHNICAL_SHAPE_MATCH_REVIEW_REQUIRED`; **it never accepts the exception**.

## Human review and disposition

An independent human reviewer must compare the complete raw output, command identities, exit codes, hashes, package-name set and records against the derived checker inputs. The reviewer must inspect all 173 names (including the second `cy+cpu.*` record), verify target-specific versions and generated descriptions, and confirm there are no other audit warnings or database anomalies. Record reviewer identity, UTC/timebase, capture hashes reviewed, decision, rationale, and unresolved items in the private H004 record.

Only that reviewer may mark the missing-checksum exception accepted in a completed H004 review record, and only if every check passes. A checker pass alone remains `REVIEW_REQUIRED`. Empty `dpkg --audit` output, status `install ok installed`, the `/.` sentinel, or matching package prefixes alone never clear the audit gate. Any inconsistency stays blocked and is escalated for a separately authorized plan; H004 performs no repair.
