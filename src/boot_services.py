'''
 *
 *      boot_services.py
 *      Bind the verified runtime's unit graph to boot and service callbacks.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os
from pathlib import Path

from service_manager import ServiceManager, set_manager


# Load the selected runtime's unit definitions and publish its service manager.
def create_manager():
    import main
    import kernel
    import oobe
    import ota
    import process
    import syslocale
    from vortexglass.service import manager as graphics

    context = {"oobe_ok": False}

    # Register reserved PIDs without storing PCB objects in JSON status output.
    def processes():
        process.boot_system()

    # Apply the persisted locale before the first-boot wizard runs.
    def locale():
        syslocale.init_from_bootcfg(main.bootcfg)

    # Preserve the wizard result for the verified boot commit.
    def wizard():
        context["oobe_ok"] = oobe.maybe_run_oobe(main.root_dir)

    # Commit a signed slot only after successful first-boot setup.
    def commit():
        if context["oobe_ok"] and os.environ.get("PYSPOS_BOOT_VERIFIED") == "1":
            import secure_boot
            slot = os.environ.get("PYSPOS_BOOT_SLOT")
            manifest = secure_boot.verify_slot(main.root_dir, slot, locked=True)
            secure_boot.mark_boot_success(main.root_dir, slot, manifest)

    actions = {"process-table": processes, "locale": locale,
               "oobe": wizard, "boot-commit": commit, "ota": ota.ota_init,
               "vortexglass-start": graphics.start, "vortexglass-stop": graphics.stop,
               "shell-start": kernel.start_shell_session, "shell-stop": kernel.stop_shell_session}
    manager = ServiceManager()
    manager.load(Path(__file__).with_name("units"), actions)
    manager.units["vortexglass.service"].probe = graphics.status
    manager.units["vortexglass.service"].read_logs = graphics.read_logs
    set_manager(manager)
    return manager
