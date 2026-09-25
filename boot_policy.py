'''
 *
 *      boot_policy.py
 *      Command-line signer for PySpOS Bootloader policy files.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import argparse
import getpass
import os

import secure_boot


# Parse command-line options and issue a signed Bootloader policy.
def main(argv=None):
    parser = argparse.ArgumentParser(description="签发 PySpOS Bootloader policy")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--lock", action="store_true")
    mode.add_argument("--unlock", action="store_true")
    parser.add_argument("--rollback-index", type=int, required=True)
    parser.add_argument("--private-key", required=True)
    parser.add_argument("--root-dir", default=os.path.dirname(os.path.abspath(__file__)))
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    if args.rollback_index < 0:
        parser.error("rollback-index 不能为负数")
    if not args.yes:
        confirmation = getpass.getpass("确认签发 Bootloader policy? [y/N] ")
        if confirmation.strip().lower() not in ("y", "yes"):
            print("已取消")
            return 1
    policy = secure_boot.write_policy(
        args.root_dir, args.lock, args.rollback_index, args.private_key)
    print(f"policy 已签发: locked={policy['locked']} "
          f"rollback_index={policy['rollback_index']} key_id={policy['key_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
