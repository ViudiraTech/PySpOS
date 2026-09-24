import api
import hmac

# 上锁主逻辑
def lock():
    print("现在我们将上锁 Bootloader。")
    if api.api_confirm("现在上锁 Bootloader 吗？"):
        if api.get_rootstate() or api.get_rootstate_bcfg(): # 是否 ROOT？
            print("检测到Root权限已开启，关闭Root权限...")
            api.set_rootstate(False)
        else:
            pass # 忽略

        print("Start lock flow...")
        api.set_lockstate(True)  # 设置lockstate为True（上锁）
        print("Lock Pass!")
    else:
        print("用户取消了操作")

# 主函数
def main():
    print("上锁 Bootloader 实用程序")
    print("版本 1.0.1\n")

    print("在开始前，我们需要验证您的 Unlock Token。请输入你得到的 Token。")
    while 1:
        # 2026-09-24：stdin 关闭（EOF/Ctrl-D）时必须退出，
        # 否则 apps 变成真子进程后会无限空转吃满 CPU。
        try:
            key = input("> ")
        except (EOFError, KeyboardInterrupt):
            print("\n输入已结束，退出 lock。")
            return

        # 改用常时比较，避免时序侧信道（行为不变）。
        if hmac.compare_digest(key.strip(), api.return_token()):
            lock()
        elif key == "exit":
            break
        else:
            print("输入无效")

if __name__ == "__exec__":
    main()
else:
    print("请在main.py中使用open 此文件命令打开本程序")