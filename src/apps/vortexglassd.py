'''
 *
 *      vortexglassd.py
 *      System compositor service entry point, launched as a real PID 1 child.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os
import shlex

from vortexglass.daemon import run


def main():
    run(shlex.split(os.environ.get("PYSPOS_APP_ARGS", "")))


if __name__ == "__exec__":
    main()
