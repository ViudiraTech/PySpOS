'''
 *
 *      pyspos.py
 *      PySpOS version numbers and build switches.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

NULL = 0

# OS Name.
OS_NAME = "PySpOS"

# OS Major Version. (0~99)
OS_MAJOR_VER = 3

# OS Develop stage. 
#   Possible values: "alpha", "beta", "stable"
#   "alpha": Early development stage, may contain many bugs and incomplete features.
#   "beta": Feature complete, but may still contain bugs. More stable than alpha.
#   "RC x(number 1-10   ``)": Release Candidate, final testing before official release.
#   "stable": Official release, thoroughly tested and stable for general use.
#   You can change this value to your custom format, but you need change parse_spf to truely use it.
OS_DEVELOP_STAGE = "RC 1"

# OS Minor Version. (0~99)
OS_MINOR_VER = 2

# OS Patch Version. (0~99)
OS_PATCH_VER = 0

# Full OS Version String.
OS_VERSION = f"{OS_MAJOR_VER}.{OS_MINOR_VER}.{OS_PATCH_VER}"

# OS Vendor. (your Company/Author Name)
OS_VENDOR = "GoutouStdio"

# OS Copyright.
OS_COPYRIGHT = "@2022~2026 GoutouStdio. Open all rights."

# Select whether to enable spf support.
SPF_ENABLED = True

# SPF parser version.
SPF_VERSION = "2.0" # 0.1 had only putchar and exit; 2.0 adds var, set, add, print, input, include and sleep

# Select whether to enable SpaceConfig.
SPC_ENABLED = True # SpaceConfig (.spc) v2 is available: a type system, schema validation and tool commands

# SpaceConfig Version.
SPC_VERSION = "2.0"

# Select whether to enable Space User Interface.
SPUI_ENABLED = False # SPUI2 is disabled for now, because it is not developed yet.

# SPUI Version.
SPUI_VERSION = NULL # SPUI is not developed yet, so we think its version is NULL

# Sunglass Settings.
if SPUI_ENABLED:
    # Select whether to enable SunGlass.
    SUNGLASS_ENABLED = True # SunGlass is true by default. (You can change this in spui settings later)

    # SunGlass Version.
    SUNGLASS_VERSION = NULL # SunGlass is not developed yet, so we think its version is NULL
else:
    # You don't need these values, because you have disabled SPUI.
    SUNGLASS_ENABLED = NULL
    SUNGLASS_VERSION = NULL

# Select whether to enable developer mode.
DEVELOPER_MODE = False # Developer mode is disabled by default. You can enable it for development and testing purposes.

# OTA master switch.
# temporarily disabled on 2026-09-24 after a server failure; the cloud host has moved to
# goutoustdio.rainyland.top, and it was set back to True once the service recovered.
# while disabled, check_cloud_update and download_and_install_update return a degraded notice straight away,
# without sending any network request; the local install_update, rollback and status queries are unaffected.
OTA_ENABLED = True
OTA_DISABLE_REASON = "OTA 服务器维护中，云端更新已临时禁用（本地安装/回滚不受影响）"

# OTA update channel: "stable" / "beta" / "nightly".
# check_cloud_update prefers changelog entries from the same channel.
OTA_CHANNEL = "beta"
