#!/usr/bin/env python3
"""Small, dependency-free inspector for thin 64-bit iOS Mach-O executables."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path


ARM64_CPU_TYPE = 0x0100000C
ARM64E_CPU_SUBTYPE = 2
MH_EXECUTE = 2
LC_VERSION_MIN_IPHONEOS = 0x25
LC_CODE_SIGNATURE = 0x1D
LC_BUILD_VERSION = 0x32
PLATFORM_IOS = 2
LC_LOAD_DYLIB = 0x0C
LC_LOAD_WEAK_DYLIB = 0x18 | 0x80000000
LC_REEXPORT_DYLIB = 0x1F | 0x80000000
LC_LOAD_UPWARD_DYLIB = 0x23 | 0x80000000
LC_LAZY_LOAD_DYLIB = 0x20


@dataclass(frozen=True)
class MachOInfo:
    architecture: str
    subtype: int
    filetype: int
    platform: str
    minimum_os: tuple[int, int, int]
    has_code_signature: bool
    dependencies: tuple[str, ...]
    code_signature_command_offset: int | None
    code_signature_data_offset: int | None
    code_signature_data_size: int | None

    @property
    def minimum_os_text(self) -> str:
        return ".".join(str(part) for part in self.minimum_os)


def _version(value: int) -> tuple[int, int, int]:
    return ((value >> 16) & 0xFFFF, (value >> 8) & 0xFF, value & 0xFF)


def inspect_macho(path: str | Path) -> MachOInfo:
    """Parse enough load-command metadata to gate the P007 package inputs."""
    data = Path(path).read_bytes()
    if len(data) < 32 or data[:4] != b"\xcf\xfa\xed\xfe":
        raise ValueError("not a thin little-endian 64-bit Mach-O executable")

    magic, cpu_type, cpu_subtype, filetype, ncmds, sizeofcmds, _flags, _reserved = struct.unpack_from(
        "<IiiIIIII", data, 0
    )
    if magic != 0xFEEDFACF:
        raise ValueError("unsupported Mach-O byte order or class")
    if cpu_type != ARM64_CPU_TYPE:
        raise ValueError(f"wrong Mach-O CPU type: 0x{cpu_type & 0xFFFFFFFF:08x}")
    subtype = cpu_subtype & 0x00FFFFFF
    if subtype == ARM64E_CPU_SUBTYPE:
        raise ValueError("arm64e-only executable is not accepted")
    if filetype != MH_EXECUTE:
        raise ValueError("Mach-O input is not an executable")
    commands_end = 32 + sizeofcmds
    if commands_end > len(data):
        raise ValueError("Mach-O load-command area is truncated")

    offset = 32
    platform_versions: list[tuple[str, tuple[int, int, int]]] = []
    has_signature = False
    signature_command_offset: int | None = None
    signature_data_offset: int | None = None
    signature_data_size: int | None = None
    dependencies: list[str] = []
    for _ in range(ncmds):
        if offset + 8 > commands_end:
            raise ValueError("Mach-O load command is truncated")
        command, command_size = struct.unpack_from("<II", data, offset)
        if command_size < 8 or offset + command_size > commands_end:
            raise ValueError("Mach-O load command has an invalid size")
        if command == LC_BUILD_VERSION:
            if command_size < 24:
                raise ValueError("LC_BUILD_VERSION is truncated")
            _cmd, _size, platform, minos, _sdk, _ntools = struct.unpack_from("<IIIIII", data, offset)
            name = "iOS" if platform == PLATFORM_IOS else f"platform-{platform}"
            platform_versions.append((name, _version(minos)))
        elif command == LC_VERSION_MIN_IPHONEOS:
            if command_size < 16:
                raise ValueError("LC_VERSION_MIN_IPHONEOS is truncated")
            _cmd, _size, minos, _sdk = struct.unpack_from("<IIII", data, offset)
            platform_versions.append(("iOS", _version(minos)))
        elif command == LC_CODE_SIGNATURE:
            if command_size != 16 or has_signature:
                raise ValueError("LC_CODE_SIGNATURE is malformed or duplicated")
            has_signature = True
            signature_command_offset = offset
            _cmd, _size, signature_data_offset, signature_data_size = struct.unpack_from("<IIII", data, offset)
            if signature_data_offset > len(data) or signature_data_size > len(data) - signature_data_offset:
                raise ValueError("code-signature blob is outside the Mach-O file")
        elif command in (LC_LOAD_DYLIB, LC_LOAD_WEAK_DYLIB, LC_REEXPORT_DYLIB, LC_LOAD_UPWARD_DYLIB, LC_LAZY_LOAD_DYLIB):
            if command_size < 24:
                raise ValueError("dylib load command is truncated")
            name_offset = struct.unpack_from("<I", data, offset + 8)[0]
            if name_offset < 24 or name_offset >= command_size:
                raise ValueError("dylib load command has an invalid name offset")
            name_end = data.find(b"\x00", offset + name_offset, offset + command_size)
            if name_end < 0:
                raise ValueError("dylib load command name is not terminated")
            try:
                dependencies.append(data[offset + name_offset:name_end].decode("utf-8"))
            except UnicodeDecodeError:
                raise ValueError("dylib load command name is not UTF-8") from None
        offset += command_size

    if offset != commands_end:
        raise ValueError("Mach-O load commands do not fill their declared area")
    if len(platform_versions) != 1:
        raise ValueError("missing or ambiguous minimum OS load command")
    platform, minimum = platform_versions[0]
    return MachOInfo(
        "arm64", subtype, filetype, platform, minimum, has_signature,
        tuple(dependencies), signature_command_offset, signature_data_offset, signature_data_size,
    )


def validate_ios12_arm64(
    path: str | Path,
    *,
    allow_signature: bool = False,
    expected_dependencies: set[str] | None = None,
) -> MachOInfo:
    info = inspect_macho(path)
    if info.platform != "iOS":
        raise ValueError(f"wrong Apple platform: {info.platform}")
    if info.minimum_os > (12, 0, 0):
        raise ValueError(f"minimum iOS target is {info.minimum_os_text}, above 12.0")
    if info.minimum_os != (12, 0, 0):
        raise ValueError(f"minimum iOS target must be exactly 12.0, found {info.minimum_os_text}")
    if info.has_code_signature != allow_signature:
        expected = "present" if allow_signature else "absent"
        raise ValueError(f"Mach-O code signature must be {expected}")
    if expected_dependencies is not None and set(info.dependencies) != expected_dependencies:
        raise ValueError(f"unexpected dynamic dependencies: {set(info.dependencies)}")
    return info


def validate_signed_source_identity(source: str | Path, signed: str | Path) -> None:
    """Prove the signer changed only the Mach-O signature command and blob."""
    source_bytes = Path(source).read_bytes()
    signed_bytes = bytearray(Path(signed).read_bytes())
    info = inspect_macho(signed)
    if not info.has_code_signature or info.code_signature_command_offset is None:
        raise ValueError("signed output has no code-signature load command")
    header_size = 32
    ncmds = struct.unpack_from("<I", signed_bytes, 16)[0]
    sizeofcmds = struct.unpack_from("<I", signed_bytes, 20)[0]
    command_offset = info.code_signature_command_offset
    if ncmds < 1 or sizeofcmds < 16 or command_offset != header_size + sizeofcmds - 16:
        raise ValueError("code-signature command is not the final 16-byte load command")
    if info.code_signature_data_offset is None or info.code_signature_data_size is None or info.code_signature_data_size == 0:
        raise ValueError("signed output has no inspectable signature blob")
    data_offset = info.code_signature_data_offset
    data_size = info.code_signature_data_size
    if data_offset < command_offset + 16:
        raise ValueError("code-signature blob overlaps Mach-O load commands")

    def linkedit_segments(data: bytes | bytearray) -> list[tuple[int, int, int, int]]:
        count, command_bytes = struct.unpack_from("<II", data, 16)
        offset = 32
        found: list[tuple[int, int, int, int]] = []
        for _ in range(count):
            command, size = struct.unpack_from("<II", data, offset)
            if command == 0x19:
                if size < 72:
                    raise ValueError("LC_SEGMENT_64 is truncated")
                segment_name = bytes(data[offset + 8:offset + 24]).split(b"\x00", 1)[0]
                if segment_name == b"__LINKEDIT":
                    vmsize, fileoff, filesize = struct.unpack_from("<QQQ", data, offset + 32)
                    found.append((offset, vmsize, fileoff, filesize))
            offset += size
        if offset != 32 + command_bytes:
            raise ValueError("Mach-O load commands changed while checking source identity")
        return found

    original_linkedit = linkedit_segments(source_bytes)
    signed_linkedit = linkedit_segments(signed_bytes)
    if len(original_linkedit) != len(signed_linkedit):
        raise ValueError("signer changed the __LINKEDIT segment count")
    adjusted_signature_offset = data_offset - 16
    if adjusted_signature_offset < len(source_bytes):
        raise ValueError("code-signature blob overlaps unsigned source bytes")
    if any(signed_bytes[len(source_bytes):adjusted_signature_offset]):
        raise ValueError("unexpected non-zero data precedes the code-signature blob")
    if adjusted_signature_offset + data_size > len(signed_bytes):
        raise ValueError("code-signature blob is truncated after removing its load command")
    for original, changed in zip(original_linkedit, signed_linkedit):
        original_offset, original_vmsize, original_fileoff, original_filesize = original
        changed_offset, changed_vmsize, changed_fileoff, changed_filesize = changed
        if changed_offset != original_offset or changed_fileoff != original_fileoff:
            raise ValueError("signer changed the __LINKEDIT segment identity")
        if changed_filesize < original_filesize or changed_vmsize < changed_filesize:
            raise ValueError("signed __LINKEDIT segment has invalid bounds")
        if changed_fileoff + changed_filesize < data_offset + data_size:
            raise ValueError("signed __LINKEDIT segment does not contain its code-signature blob")
        struct.pack_into("<Q", signed_bytes, changed_offset + 32, original_vmsize)
        struct.pack_into("<Q", signed_bytes, changed_offset + 48, original_filesize)
    del signed_bytes[command_offset:command_offset + 16]
    del signed_bytes[len(source_bytes):adjusted_signature_offset + data_size]
    struct.pack_into("<I", signed_bytes, 16, ncmds - 1)
    struct.pack_into("<I", signed_bytes, 20, sizeofcmds - 16)
    if bytes(signed_bytes) != source_bytes:
        raise ValueError("signed executable is not a signature-only transformation of the exact source artifact")
