'''
 *
 *      protocol.py
 *      Bounded, newline-delimited JSON messages over a private local socket.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import getpass
import hashlib
import json
import os
from pathlib import Path
import tempfile

from . import PROTOCOL_VERSION

ENDPOINT_ENV = "PYSPOS_VORTEXGLASS_ENDPOINT"
MAX_MESSAGE = 256 * 1024
MAX_PENDING = 1024 * 1024


class ProtocolError(ValueError):
    pass


def endpoint_path():
    override = os.environ.get(ENDPOINT_ENV)
    if override:
        return Path(override)
    identity = f"{getpass.getuser()}:{Path(__file__).resolve().parents[1]}"
    key = hashlib.sha256(identity.encode()).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"pyspos-vg-{key}" / "endpoint.json"


def encode(message):
    payload = json.dumps(message, ensure_ascii=False, allow_nan=False,
                         separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_MESSAGE:
        raise ProtocolError("message exceeds 256 KiB")
    return payload + b"\n"


def decode(line):
    if len(line) > MAX_MESSAGE:
        raise ProtocolError("message exceeds 256 KiB")
    try:
        message = json.loads(line, parse_constant=lambda value: _bad_constant(value))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ProtocolError("invalid JSON message") from exc
    if not isinstance(message, dict):
        raise ProtocolError("message must be an object")
    return message


def _bad_constant(value):
    raise ValueError(f"non-finite JSON value: {value}")


def read_endpoint(path=None):
    with open(path or endpoint_path(), "rb") as stream:
        data = stream.read(4097)
    if len(data) > 4096:
        raise ProtocolError("invalid endpoint descriptor")
    descriptor = decode(data)
    if descriptor.get("version") != PROTOCOL_VERSION:
        raise ProtocolError("unsupported compositor protocol")
    return descriptor
