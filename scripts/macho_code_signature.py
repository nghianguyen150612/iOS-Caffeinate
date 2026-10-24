#!/usr/bin/env python3
"""Bounded independent validation for the pinned ldid Mach-O signature format."""

from __future__ import annotations

import hashlib
import plistlib
import struct
from typing import Any


ARM64_CPU_TYPE = 0x0100000C
MH_EXECUTE = 2
LC_SEGMENT_64 = 0x19
LC_CODE_SIGNATURE = 0x1D
LC_BUILD_VERSION = 0x32
PLATFORM_IOS = 2
CS_ADHOC = 0x2
EXPECTED_ENTITLEMENTS = {"com.apple.private.security.no-container": True}
MAX_SIGNATURE_BYTES = 16 * 1024 * 1024


class CodeSignatureError(ValueError):
    """Mach-O signature data is malformed or fails independent integrity checks."""


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise CodeSignatureError(message)


def _hash_function(hash_type: int, hash_size: int):
    algorithms = {1: "sha1", 2: "sha256", 3: "sha256", 4: "sha384"}
    _need(hash_type in algorithms, f"unsupported CodeDirectory hash type: {hash_type}")
    expected_size = 20 if hash_type in (1, 3) else 32 if hash_type == 2 else 48
    _need(hash_size == expected_size, "CodeDirectory hash type and size disagree")
    return lambda data: hashlib.new(algorithms[hash_type], data).digest()[:hash_size]


def _subblob(data: bytes, offset: int, expected_magic: int, limit: int) -> bytes:
    _need(offset >= 0 and offset + 8 <= limit, "signature blob header is out of bounds")
    magic, length = struct.unpack_from(">II", data, offset)
    _need(magic == expected_magic, f"unexpected signature blob magic 0x{magic:08x}")
    _need(length >= 8 and offset + length <= limit, "signature blob length is out of bounds")
    return data[offset:offset + length]


def _validate_requirements(blob: bytes) -> dict[str, Any]:
    _need(len(blob) >= 12, "Requirements SuperBlob is truncated")
    magic, length, count = struct.unpack_from(">III", blob, 0)
    _need(magic == 0xFADE0C01 and length == len(blob), "Requirements SuperBlob header is invalid")
    _need(count <= 256 and 12 + count * 8 <= len(blob), "Requirements index table is out of bounds")
    regions: list[tuple[int, int]] = []
    seen: set[int] = set()
    for index in range(count):
        kind, offset = struct.unpack_from(">II", blob, 12 + index * 8)
        _need(kind not in seen, "Requirements SuperBlob has duplicate requirement types")
        seen.add(kind)
        requirement = _subblob(blob, offset, 0xFADE0C00, len(blob))
        regions.append((offset, offset + len(requirement)))
    cursor = 12 + count * 8
    for start, end in sorted(regions):
        _need(start == cursor, "Requirements SuperBlob contains overlap, a gap, or unindexed data")
        cursor = end
    _need(cursor == len(blob), "Requirements SuperBlob has unexpected trailing data")
    return {"count": count, "types": sorted(seen)}


def _validate_der_entitlements(blob: bytes, *, allow_canonical_boolean: bool = False) -> None:
    _need(8 <= len(blob) <= 4096, "DER entitlement blob size is outside the supported bound")
    magic, length = struct.unpack_from(">II", blob, 0)
    _need(magic == 0xFADE7172 and length == len(blob), "DER entitlement blob header is invalid")
    der = blob[8:]
    key = b"com.apple.private.security.no-container"
    expected = (
        b"\x31" + bytes((len(key) + 7,))
        + b"\x30" + bytes((len(key) + 5,))
        + b"\x0c" + bytes((len(key),)) + key + b"\x01\x01\x01"
    )
    apple_inner = (
        b"\x30" + bytes((len(key) + 5,))
        + b"\x0c" + bytes((len(key),)) + key + b"\x01\x01\xff"
    )
    apple_canonical_true = (
        b"\x70" + bytes((len(apple_inner) + 5,))
        + b"\x02\x01\x01\xb0" + bytes((len(apple_inner),)) + apple_inner
    )
    _need(der == expected or (allow_canonical_boolean and der == apple_canonical_true),
          "DER entitlement payload is not the exact approved entitlement set")


def _validate_code_directory(blob: bytes, image: bytes, identifier: str,
                             special_blobs: dict[int, bytes]) -> dict[str, Any]:
    _need(len(blob) >= 44, "CodeDirectory is truncated")
    (magic, length, version, flags, hash_offset, ident_offset, special_count,
     code_count, code_limit) = struct.unpack_from(">IIIIIIIII", blob, 0)
    _need(magic == 0xFADE0C02 and length == len(blob), "CodeDirectory header is invalid")
    _need(0x20001 <= version <= 0x20400, f"unsupported CodeDirectory version 0x{version:08x}")
    header_size = 88 if version >= 0x20400 else 64 if version >= 0x20300 else 52 if version >= 0x20200 else 48 if version >= 0x20100 else 44
    _need(length >= header_size, "CodeDirectory versioned header is truncated")
    hash_size, hash_type, platform, page_exponent = struct.unpack_from(">4B", blob, 36)
    spare2 = struct.unpack_from(">I", blob, 40)[0]
    _need(spare2 == 0, "CodeDirectory reserved field is nonzero")
    if version >= 0x20100:
        _need(struct.unpack_from(">I", blob, 44)[0] == 0, "CodeDirectory scatter vectors are unsupported")
    if version >= 0x20200:
        team_offset = struct.unpack_from(">I", blob, 48)[0]
        _need(team_offset == 0, "unexpected CodeDirectory team identifier")
    if version >= 0x20300:
        _need(struct.unpack_from(">I", blob, 52)[0] == 0, "CodeDirectory reserved extension field is nonzero")
        code_limit_64 = struct.unpack_from(">Q", blob, 56)[0]
        _need(code_limit_64 == 0 or code_limit == 0xFFFFFFFF, "unexpected extended CodeDirectory code limit")
        if code_limit == 0xFFFFFFFF:
            code_limit = code_limit_64
    _need(platform == 0, "unexpected CodeDirectory platform marker")
    _need(code_limit > 0 and code_limit <= len(image), "CodeDirectory code limit is outside the executable")
    _need(code_limit == image_signature_offset(image), "CodeDirectory does not cover the exact signed executable prefix")
    _need(special_count == 7, "CodeDirectory special-slot count is not the approved ldid layout")
    _need(0 < page_exponent <= 16, "CodeDirectory page size is unsupported")
    page_size = 1 << page_exponent
    expected_code_count = (code_limit + page_size - 1) // page_size
    _need(code_count == expected_code_count, "CodeDirectory code-slot count does not cover codeLimit")
    digest = _hash_function(hash_type, hash_size)
    _need(hash_offset >= header_size and hash_offset <= length, "CodeDirectory hash array offset is invalid")
    _need(ident_offset >= header_size and ident_offset < hash_offset, "CodeDirectory identifier offset is invalid")
    ident_end = blob.find(b"\x00", ident_offset, hash_offset)
    _need(ident_end >= 0, "CodeDirectory identifier is not terminated")
    try:
        found_identifier = blob[ident_offset:ident_end].decode("utf-8")
    except UnicodeDecodeError:
        raise CodeSignatureError("CodeDirectory identifier is not UTF-8") from None
    _need(found_identifier == identifier, "CodeDirectory identifier differs from its package executable")
    special_start = hash_offset - special_count * hash_size
    _need(special_start >= ident_end + 1, "CodeDirectory special hashes overlap its identifier")
    _need(hash_offset + code_count * hash_size == length, "CodeDirectory hash array has an invalid length")

    checked_special = []
    for slot in range(1, special_count + 1):
        slot_start = hash_offset - slot * hash_size
        slot_hash = blob[slot_start:slot_start + hash_size]
        special_blob = special_blobs.get(slot)
        if special_blob is None:
            _need(slot_hash == bytes(hash_size), f"unexpected data in CodeDirectory special slot {slot}")
            continue
        _need(slot_hash == digest(special_blob), f"CodeDirectory special-slot {slot} hash mismatch")
        checked_special.append(slot)

    for slot in range(code_count):
        start = slot * page_size
        end = min(start + page_size, code_limit)
        expected = digest(image[start:end])
        actual_start = hash_offset + slot * hash_size
        _need(blob[actual_start:actual_start + hash_size] == expected,
              f"CodeDirectory executable hash mismatch at code slot {slot}")

    return {
        "version": f"0x{version:08x}",
        "flags": flags,
        "hash_type": hash_type,
        "hash_size": hash_size,
        "code_limit": code_limit,
        "page_size": page_size,
        "code_slots": code_count,
        "special_slots_verified": checked_special,
        "identifier": found_identifier,
    }


def image_signature_offset(image: bytes) -> int:
    """Read the bounded LC_CODE_SIGNATURE offset without trusting it elsewhere."""
    if len(image) < 32 or image[:4] != b"\xcf\xfa\xed\xfe":
        raise CodeSignatureError("not a thin little-endian 64-bit Mach-O executable")
    _magic, _cpu, _subtype, _filetype, count, command_bytes, _flags, _reserved = struct.unpack_from("<IiiIIIII", image, 0)
    if count > 65535 or 32 + command_bytes > len(image):
        raise CodeSignatureError("Mach-O load-command area is out of bounds")
    offset = 32
    signature_offsets = []
    for _ in range(count):
        if offset + 8 > 32 + command_bytes:
            raise CodeSignatureError("Mach-O load command is truncated")
        command, size = struct.unpack_from("<II", image, offset)
        if size < 8 or offset + size > 32 + command_bytes:
            raise CodeSignatureError("Mach-O load command size is invalid")
        if command == LC_CODE_SIGNATURE:
            if size != 16:
                raise CodeSignatureError("LC_CODE_SIGNATURE command has an invalid size")
            signature_offsets.append(struct.unpack_from("<I", image, offset + 8)[0])
        offset += size
    if offset != 32 + command_bytes or len(signature_offsets) != 1:
        raise CodeSignatureError("Mach-O has missing or ambiguous LC_CODE_SIGNATURE")
    return signature_offsets[0]


def _audit_code_signature(image: bytes, *, expected_identifier: str,
                         allow_apple_adhoc_layout: bool = False) -> dict[str, Any]:
    """Verify the exact ldid CodeDirectory, signature blobs, and approved entitlements."""
    _need(len(image) >= 32, "Mach-O header is truncated")
    magic, cpu_type, cpu_subtype, filetype, command_count, command_bytes, _flags, _reserved = struct.unpack_from(
        "<IiiIIIII", image, 0
    )
    _need(magic == 0xFEEDFACF and image[:4] == b"\xcf\xfa\xed\xfe", "unsupported Mach-O class or byte order")
    _need(cpu_type == ARM64_CPU_TYPE and (cpu_subtype & 0x00FFFFFF) == 0, "executable is not generic ARM64")
    _need(filetype == MH_EXECUTE, "Mach-O is not an executable")
    commands_end = 32 + command_bytes
    _need(command_count <= 65535 and commands_end <= len(image), "Mach-O load-command area is out of bounds")
    offset = 32
    build_versions: list[tuple[int, int]] = []
    signatures: list[tuple[int, int, int]] = []
    segments: list[tuple[bytes, int, int]] = []
    for _ in range(command_count):
        _need(offset + 8 <= commands_end, "Mach-O load command is truncated")
        command, size = struct.unpack_from("<II", image, offset)
        _need(size >= 8 and offset + size <= commands_end, "Mach-O load command size is invalid")
        if command == LC_BUILD_VERSION:
            _need(size >= 24, "LC_BUILD_VERSION is truncated")
            _cmd, _size, platform, minimum, _sdk, _tools = struct.unpack_from("<IIIIII", image, offset)
            build_versions.append((platform, minimum))
        elif command == LC_CODE_SIGNATURE:
            _need(size == 16, "LC_CODE_SIGNATURE command has an invalid size")
            data_offset, data_size = struct.unpack_from("<II", image, offset + 8)
            signatures.append((offset, data_offset, data_size))
        elif command == LC_SEGMENT_64:
            _need(size >= 72, "LC_SEGMENT_64 is truncated")
            segment_name = image[offset + 8:offset + 24].split(b"\x00", 1)[0]
            file_offset, file_size = struct.unpack_from("<QQ", image, offset + 40)
            _need(file_offset <= len(image) and file_size <= len(image) - file_offset,
                  "Mach-O segment file range is out of bounds")
            segments.append((segment_name, file_offset, file_size))
        offset += size
    _need(offset == commands_end, "Mach-O load commands do not fill their declared area")
    _need(len(build_versions) == 1 and build_versions[0][0] == PLATFORM_IOS,
          "Mach-O must have exactly one iOS LC_BUILD_VERSION")
    minimum = build_versions[0][1]
    _need(minimum == (12 << 16), "Mach-O deployment target is not iOS 12.0")
    _need(len(signatures) == 1, "Mach-O must have exactly one LC_CODE_SIGNATURE")
    command_offset, data_offset, data_size = signatures[0]
    _need(command_offset + 16 == commands_end, "LC_CODE_SIGNATURE must be the final Mach-O load command")
    _need(data_offset % 16 == 0, "code-signature data offset is not 16-byte aligned")
    _need(data_size > 0 and data_size <= MAX_SIGNATURE_BYTES, "code-signature data size is outside the supported bound")
    _need(data_offset + data_size == len(image), "code signature is truncated or followed by unexpected trailing data")
    linkedit = [item for item in segments if item[0] == b"__LINKEDIT"]
    _need(len(linkedit) == 1, "Mach-O must contain exactly one __LINKEDIT segment")
    _name, linkedit_offset, linkedit_size = linkedit[0]
    _need(data_offset >= linkedit_offset and data_offset + data_size <= linkedit_offset + linkedit_size,
          "code signature is outside __LINKEDIT bounds")
    for name, file_offset, file_size in segments:
        if name != b"__LINKEDIT" and file_size:
            _need(file_offset + file_size <= data_offset, "code signature overlaps a non-__LINKEDIT segment")

    superblob = image[data_offset:data_offset + data_size]
    _need(len(superblob) >= 12, "signature SuperBlob is truncated")
    sb_magic, sb_length, sb_count = struct.unpack_from(">III", superblob, 0)
    _need(sb_magic == 0xFADE0CC0 and 12 <= sb_length <= len(superblob), "signature SuperBlob header is invalid")
    _need(sb_count <= 32 and 12 + sb_count * 8 <= sb_length, "signature SuperBlob index table is out of bounds")
    entries: dict[int, tuple[int, int, bytes]] = {}
    regions: list[tuple[int, int]] = []
    for index in range(sb_count):
        kind, blob_offset = struct.unpack_from(">II", superblob, 12 + index * 8)
        _need(kind not in entries, "signature SuperBlob has duplicate index types")
        _need(blob_offset >= 12 + sb_count * 8, "signature blob overlaps the SuperBlob index")
        _need(blob_offset + 8 <= sb_length, "signature blob header is out of bounds")
        blob_header = _subblob(superblob[:sb_length], blob_offset, struct.unpack_from(">I", superblob, blob_offset)[0], sb_length)
        entries[kind] = (blob_offset, len(blob_header), blob_header)
        regions.append((blob_offset, blob_offset + len(blob_header)))
    cursor = 12 + sb_count * 8
    for start, end in sorted(regions):
        _need(start == cursor, "signature SuperBlob contains overlap, a gap, or unindexed data")
        cursor = end
    _need(cursor == sb_length, "signature SuperBlob has unexpected trailing data")
    expected_entries = {0, 2, 5, 7}
    has_empty_adhoc_slot = set(entries) == expected_entries | {0x10000}
    _need(set(entries) == expected_entries or
          (allow_apple_adhoc_layout and has_empty_adhoc_slot),
          "signature SuperBlob has missing or unexpected signature slots")
    if has_empty_adhoc_slot:
        empty_signature = entries[0x10000][2]
        _need(len(empty_signature) == 8 and struct.unpack_from(">II", empty_signature, 0) == (0xFADE0B01, 8),
              "ad hoc signature wrapper must be empty")
    _need(all(byte == 0 for byte in superblob[sb_length:]), "signature area has nonzero padding")

    cd_blob = entries[0][2]
    requirements = entries[2][2]
    xml_blob = entries[5][2]
    der_blob = entries[7][2]
    requirements_record = _validate_requirements(requirements)
    _need(struct.unpack_from(">I", xml_blob, 0)[0] == 0xFADE7171, "XML entitlement blob magic is invalid")
    _need(len(xml_blob) <= 1024 * 1024, "XML entitlement blob exceeds the supported size limit")
    _need(struct.unpack_from(">I", xml_blob, 4)[0] == len(xml_blob), "XML entitlement blob length is invalid")
    try:
        entitlements = plistlib.loads(xml_blob[8:])
    except (plistlib.InvalidFileException, ValueError):
        raise CodeSignatureError("XML entitlement payload is malformed") from None
    _need(isinstance(entitlements, dict) and entitlements == EXPECTED_ENTITLEMENTS and
          all(type(value) is bool for value in entitlements.values()),
          "XML entitlement set differs from the exact approved profile")
    _validate_der_entitlements(der_blob, allow_canonical_boolean=allow_apple_adhoc_layout)
    code_directory = _validate_code_directory(
        cd_blob, image, expected_identifier, {2: requirements, 5: xml_blob, 7: der_blob}
    )
    flags = code_directory["flags"]
    adhoc = bool(flags & CS_ADHOC)
    _need(not has_empty_adhoc_slot or adhoc,
          "empty signature wrapper is only supported for ad hoc CodeDirectories")
    _need(flags & ~CS_ADHOC == 0, "CodeDirectory has unexpected signing flags")
    return {
        "independent_code_directory_verified": True,
        "entitlements_exact_match": True,
        "adhoc_flag_present": adhoc,
        "signature_kind": "ADHOC" if adhoc else "UNMARKED_LDID_SIGNATURE",
        "device_signature_acceptance": "PENDING",
        "code_directory": code_directory,
        "superblob": {"length": sb_length, "index_types": sorted(entries)},
        "requirements": requirements_record,
        "signature_padding_bytes": len(superblob) - sb_length,
        "cms_blob_present": False,
        "empty_adhoc_signature_slot_present": has_empty_adhoc_slot,
    }


def audit_code_signature(image: bytes, *, expected_identifier: str,
                         allow_apple_adhoc_layout: bool = False) -> dict[str, Any]:
    """Translate malformed binary parsing errors into a stable fail-closed result."""
    try:
        return _audit_code_signature(
            image,
            expected_identifier=expected_identifier,
            allow_apple_adhoc_layout=allow_apple_adhoc_layout,
        )
    except CodeSignatureError:
        raise
    except (struct.error, IndexError, OverflowError, RecursionError):
        raise CodeSignatureError("Mach-O signature contains malformed or truncated binary structures") from None
