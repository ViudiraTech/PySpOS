# bm.py -- bootloader manager
import api

# 获取root权限
def get_root():
    print("Start enable root flow...\n")
    api.set_rootstate(True)
    print("Enable Pass!")

# 关闭root权限
def disable_root():
    print("Start disable root flow...\n")
    api.set_rootstate(False)
    print("Disable Pass!")  

# 主程序
def main():
    print("BM：Bootloader CFG 管理工具")
    print("版本 2.0")

    # 2026-09-24：token 输入也要处理 EOF，否则后台/管道运行时会直接崩栈
    try:
        ut = input("请输入Unlock Token：")
    except (EOFError, KeyboardInterrupt):
        print("\n输入已结束，退出 bm。")
        return

    token = api.return_token()
    if ut.strip() != token:
        print("Unlock Token 不正确")
    else:
        try:
            while True:
                pm = input("bm> ").strip().lower()
                if pm == "help":
                    print("lock/unlock      解锁/上锁Bootloader")
                    print("getroot/disableroot  获取/关闭 root 权限")
                    print("exit             退出")
                elif pm == "lock":
                    if not api.get_lockstate():
                        print("Start lock flow...\n")
                        if api.get_rootstate() or api.get_rootstate_bcfg():
                            print("You have root permisson, disable root...")
                            api.set_rootstate(False)
                        api.set_lockstate(True)
                        print("Lock Pass!")
                    else:
                        print("bootloader is locked, pass...")
                elif pm == "unlock":
                    if api.get_lockstate():
                        print("Start unlock flow...")
                        print("warning: after unlocking, you can manage your system\n")
                        api.set_lockstate(False)
                        print("Unlock Pass!")
                    else:
                        print("bootloader is unlocked, pass...")
                elif pm == "getroot":
                    if not api.get_rootstate() or api.get_rootstate_bcfg():
                        get_root()
                    else:
                        print("You have root permisson, pass...")
                elif pm == "disableroot":
                    if api.get_rootstate() or api.get_rootstate_bcfg():
                        disable_root()
                    else:
                        print("You don't have root permisson, pass...")
                elif pm == "exit":
                    break
                elif pm == "":
                    continue
                else:
                    print(f"找不到 {pm} 命令")
        except KeyboardInterrupt:
            print("\nExiting...")
        except EOFError:
            # 2026-09-24：stdin 关闭时必须退出，否则真子进程会空转吃 CPU
            print("\n输入已结束，退出 bm。")
            return

if __name__ == "__exec__":
    main()
else:
    print("can't run!!!!!!!!")