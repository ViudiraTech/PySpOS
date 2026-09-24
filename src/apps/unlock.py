import api


def main():
    print("Bootloader 信任域不能由 Token 或 ROOT 改变。")
    print("请在设备外部使用 boot_policy.py，并重新确认/签名 policy。")
    print("当前 ROOT 权限不会绕过镜像验签，也不会伪造 OEM 签名。")


if __name__ == "__exec__":
    main()
else:
    raise SystemError("请不要直接运行本程序")
