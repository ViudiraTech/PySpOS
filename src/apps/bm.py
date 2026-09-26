'''
 *
 *      bm.py
 *      Interactive runtime permission manager app.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import api


# Run the interactive bm> prompt that toggles ROOT and shows the trust state.
def main():
    print("BM：运行时权限管理器")
    print("ROOT 只影响运行时操作，不会改变 Bootloader 信任域或 OEM 签名。")
    try:
        while True:
            command = input("bm> ").strip().lower()
            if command == "getroot":
                if not api.api_confirm("确认获取 ROOT 权限？"):
                    continue
                if api.authorize_root() and api.set_rootstate(True):
                    print("临时 ROOT 已启用。")
            elif command == "disableroot":
                api.set_rootstate(False)
                print("ROOT 已关闭。")
            elif command == "status":
                print(f"ROOT={api.get_rootstate()}，LOCKED={api.get_lockstate()}")
            elif command == "exit":
                break
            elif command == "help":
                print("getroot/disableroot/status/exit")
            elif command:
                print("找不到该命令")
    except (EOFError, KeyboardInterrupt):
        print()


if __name__ == "__exec__":
    main()
else:
    print("can't run!!!!!!!!")
