'''
 *
 *      lock.py
 *      App that only explains how to lock the bootloader.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

# Report that locking needs the external signed policy tool; prints only.
def main():
    print("Bootloader 锁定不能由应用或 ROOT 直接修改。")
    print("请使用设备外部的签名 policy 工具完成锁定。")


if __name__ == "__exec__":
    main()
else:
    raise SystemError("请不要直接运行本程序")
