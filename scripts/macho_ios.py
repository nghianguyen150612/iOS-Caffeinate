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


@dataclass(frozen=True)
class MachOInfo:
    architecture: str
    subtype: int
    filetype: int
    platform: str
    minimum_os: tuple[int, int, int]
    has_code_signature: bool

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
            has_signature = True
        offset += command_size

    if offset != commands_end:
        raise ValueError("Mach-O load commands do not fill their declared area")
    if len(platform_versions) != 1:
        raise ValueError("missing or ambiguous minimum OS load command")
    platform, minimum = platform_versions[0]
    return MachOInfo("arm64", subtype, filetype, platform, minimum, has_signature)


def validate_ios12_arm64(path: str | Path, *, allow_signature: bool = False) -> MachOInfo:
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
    return info
