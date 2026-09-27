"""Portable theme artwork for UI tests, generated without external packages."""

import struct
import zlib

import pytest

import spaceglass_theme as theme


def _chunk(kind, payload):
    return (struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff))


def _theme_png(asset, index):
    # Distinct colours identify each asset. Caption buttons stay opaque so
    # compositing tests can check that their pixels survive unchanged.
    shade = 40 + index * 5
    alpha = 64 if asset.name == "reflection.png" else 255
    if asset.color == 6:
        pixel = bytes((shade, 100, 180, alpha))
    elif asset.color == 4:
        pixel = bytes((shade, alpha))
    elif asset.color == 3:
        pixel = b"\x00"
    else:
        raise ValueError(f"Unsupported fixture colour type: {asset.color}")
    header = struct.pack(">IIBBBBB", asset.width, asset.height,
                         8, asset.color, 0, 0, 0)
    data = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header)
    if asset.color == 3:
        data += _chunk(b"PLTE", bytes((shade, 100, 180)))
    row = b"\x00" + pixel * asset.width
    data += _chunk(b"IDAT", zlib.compress(row * asset.height))
    return data + _chunk(b"IEND", b"")


@pytest.fixture(scope="session")
def theme_dir(tmp_path_factory):
    """A complete decodable VortexGlass theme, independent of host files."""
    directory = tmp_path_factory.mktemp("vortexglass")
    for index, asset in enumerate(theme.REQUIRED_ASSETS):
        (directory / asset.name).write_bytes(_theme_png(asset, index))
    return str(directory)
