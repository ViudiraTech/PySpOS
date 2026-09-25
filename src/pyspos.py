#
#   pyspos.py
#   PySpOS Base information file
#
#   2026/1/31 By GoutouStdio
#   @2022~2026 GoutouStdio. Open all rights.

#   2026/1/31 update log: add this file to store base information of PySpOS!!!
#   2026/1/31 update 2 log: add null value definition, add spui,sunglass definitions

# Null value.
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
SPF_VERSION = "2.0" # 0.1: 仅 putchar/exit；2.0: 新增 var/set/add/print/input/include/sleep

# Select whether to enable SpaceConfig.
SPC_ENABLED = True # SpaceConfig（.spc）v2 已可用：类型系统+Schema 校验+工具命令

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
#   2026-09-24 曾因服务器故障临时禁用；云端已迁移到
#   goutoustdio.rainyland.top，服务恢复后改回 True。
#   禁用后：check_cloud_update / download_and_install_update 直接返回降级提示，
#   不发任何网络请求；本地安装 install_update / 回滚 rollback / 状态查询不受影响。
OTA_ENABLED = True
OTA_DISABLE_REASON = "OTA 服务器维护中，云端更新已临时禁用（本地安装/回滚不受影响）"

# OTA update channel: "stable" / "beta" / "nightly".
#   check_cloud_update 会优先匹配同 channel 的 changelog 条目。
OTA_CHANNEL = "beta"
