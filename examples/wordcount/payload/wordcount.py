'''
 *
 *      wordcount.py
 *      Count words from package arguments with a built-in example fallback.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os


# Count package-provided words, or use the example default words.
def main():
    text = os.environ.get("PYSPOS_PACKAGE_ARGS", "").strip()
    words = text.split() if text else ["PySpOS", "package", "manager"]
    print(f"词数: {len(words)}")


if __name__ == "__main__":
    main()
