'''
 *
 *      terminal_shell.py
 *      PySpOS shell session attached to the desktop's real pseudoterminal.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os
import sys


# Enter only the command loop: the verified parent has already booted the system.
def run():
    sys._launcher_detected = True
    os.environ["PYSPOS_GUI_SESSION"] = "1"
    import main
    import kernel
    import syslocale
    syslocale.init_from_bootcfg(main.bootcfg)
    print("PySpOS PTY shell — guicalc / guiclock / guicanvas; Ctrl-D 关闭终端", flush=True)
    kernel.start_shell_session()
    kernel._command_loop()


if __name__ == "__main__":
    run()
