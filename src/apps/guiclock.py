'''
 *
 *      guiclock.py
 *      Live clock GUI client communicating with VortexGlass through a socket.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

from vortexglass.demos import run_demo


def main():
    run_demo("clock")


if __name__ == "__exec__":
    main()
