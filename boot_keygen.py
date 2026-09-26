'''
 *
 *      boot_keygen.py
 *      Generate the PySpOS bootloader Ed25519 signing key
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import argparse
import base64
import hashlib
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


# Generate a private key, write it with restrictive permissions, and print the public metadata.
def main(argv=None):
    parser = argparse.ArgumentParser(description="生成 PySpOS Bootloader Ed25519 签名密钥")
    parser.add_argument("--private-key", default="boot_signing_key.pem")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    if os.path.exists(args.private_key) and not args.force:
        parser.error(f"文件已存在: {args.private_key}")
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM,
                            serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    path = os.path.abspath(args.private_key)
    with open(path, "wb") as stream:
        stream.write(pem)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.chmod(path, 0o600)
    except OSError as e:
        # A private key left group or world readable is worse than no key at all,
        # so the failure is fatal rather than a shrug: the key never goes on to be
        # printed and used while it is exposed.
        raise SystemExit(f"无法将私钥权限收紧为 0600: {e}")
    public = key.public_key().public_bytes(serialization.Encoding.Raw,
                                             serialization.PublicFormat.Raw)
    encoded = base64.b64encode(public).decode("ascii")
    key_id = hashlib.sha256(public).hexdigest()[:32]
    print(f"私钥已写入: {path}")
    print(f"key_id: {key_id}")
    print(f"公钥 base64: {encoded}")
    print("将公钥加入 secure_boot.py 的 TRUSTED_PUBLIC_KEYS 后再构建签名镜像。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
