import os


def main():
    text = os.environ.get("PYSPOS_PACKAGE_ARGS", "").strip()
    words = text.split() if text else ["PySpOS", "package", "manager"]
    print(f"词数: {len(words)}")


if __name__ == "__main__":
    main()
