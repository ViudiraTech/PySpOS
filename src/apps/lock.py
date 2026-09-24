import api


def main():
    print("Bootloader 锁定不能由应用或 ROOT 直接修改。")
    print("请使用设备外部的签名 policy 工具完成锁定。")


if __name__ == "__exec__":
    main()
else:
    raise SystemError("请不要直接运行本程序")
