'''
 *
 *      unlock.py
 *      App that only explains how to change the trust domain.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import api


# Report that the trust domain only changes offline; prints only.
def main():
    print("Bootloader 信任域不能由 Token 或 ROOT 改变。")
    print("请在设备外部使用 boot_policy.py，并重新确认/签名 policy。")
    print("当前 ROOT 权限不会绕过镜像验签，也不会伪造 OEM 签名。")


if __name__ == "__exec__":
    main()
else:
    raise SystemError("请不要直接运行本程序")
