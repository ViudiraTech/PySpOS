'''
 *
 *      greeter.py
 *      Example user-package greeter payload.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os


# Print a package greeting, addressing the target when one is provided.
def main():
    target = os.environ.get("PYSPOS_PACKAGE_ARGS", "").strip()
    if target:
        print(f"你好，{target}！这是 PySpOS 用户包。")
    else:
        print("你好！这是 PySpOS 用户包。")


if __name__ == "__main__":
    main()
