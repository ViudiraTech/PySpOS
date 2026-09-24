import api
import hmac

def unlock():
    if api.get_lockstate():
        api.api_info("开始解锁 Bootloader...")
        api.set_lockstate(False)
        api.api_ok("解锁完成！（本次操作已审计）")
    else:
        print("\n您已经解锁了Bootloader，无需再次解锁")

def main():
    print("解锁 Bootloader 实用程序")
    print("版本 2.2.0\n")
    print("请输入您获取的解锁 Token 以继续下一步操作")

    while 1:
        # 2026-09-24：stdin 关闭时退出，避免真子进程空转吃 CPU
        try:
            token = input("> ")
        except (EOFError, KeyboardInterrupt):
            print("\n输入已结束，退出 unlock。")
            return
        # 改用常时比较，避免时序侧信道（行为不变）。
        if hmac.compare_digest(token.strip(), api.return_token()):
            print("验证成功，您可以进行下一步了\n")
            if api.api_confirm("是否现在解锁 Bootloader？"):
                unlock()
            else:
                pass
            break
        else:
            print("你输入的密钥有误，请重新输入。\n")

if __name__ == "__exec__":
    try:
        main()
    except Exception as e:
        print(f"程序运行出错：{str(e)}")
else:
    raise SystemError("请不要直接运行本程序")