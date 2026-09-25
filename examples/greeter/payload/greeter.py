import os


def main():
    target = os.environ.get("PYSPOS_PACKAGE_ARGS", "").strip()
    if target:
        print(f"你好，{target}！这是 PySpOS 用户包。")
    else:
        print("你好！这是 PySpOS 用户包。")


if __name__ == "__main__":
    main()
