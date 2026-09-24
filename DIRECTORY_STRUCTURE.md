# PySpOS 目录结构说明

## 新的目录结构

```
PySpOS/
├── src/                      # 源代码目录（所有系统文件）
│   ├── apps/                # 应用程序目录
│   ├── docs/                # 文档目录
│   ├── spfapps/             # SPF应用程序目录
│   ├── btcfg.py             # 启动配置模块
│   ├── current_slot          # 当前槽位记录文件
│   ├── fs.py                # 文件系统模块
│   ├── kernel.py            # 内核模块
│   ├── logk.py              # 日志模块
│   ├── main.py              # 主程序入口
│   ├── ota.py               # OTA更新模块
│   ├── parse_spf.py         # SPF解析模块
│   ├── printk.py            # 打印模块
│   ├── pyspos.py            # PySpOS核心模块
│   ├── recovery.py          # 恢复模块
│   ├── sync.py              # 同步模块
│   ├── version.txt          # 版本信息文件
│   └── launcher.py          # 启动器
├── slot_a/                  # 槽位A（运行版本）
│   ├── apps/
│   ├── docs/
│   ├── spfapps/
│   ├── btcfg.py
│   ├── current_slot
│   ├── fs.py
│   ├── kernel.py
│   ├── logk.py
│   ├── main.py
│   ├── ota.py
│   ├── parse_spf.py
│   ├── printk.py
│   ├── pyspos.py
│   ├── recovery.py
│   ├── sync.py
│   ├── version.txt
│   └── update_log.json
├── slot_b/                  # 槽位B（运行版本）
│   └── (同slot_a结构)
├── etc/                     # 配置目录（保留在根目录）
│   └── bootcfg.json
├── ota/                     # OTA更新包目录
│   └── update.zip
├── launcher.py              # 启动器（根目录副本）
├── start.bat                # Windows启动脚本
├── start.sh                 # Linux/Mac启动脚本
├── calculate_zip_info.py    # 更新包创建工具
├── README.md                # 项目说明文档
├── STARTUP.md               # 启动说明文档
└── .git/                    # Git仓库
```

## 目录说明

### 根目录（PySpOS/）
**保留的文件**：
- `launcher.py` - 启动器（根目录副本）
- `start.bat` - Windows启动脚本
- `start.sh` - Linux/Mac启动脚本
- `calculate_zip_info.py` - 更新包创建工具
- `README.md` - 项目说明文档
- `STARTUP.md` - 启动说明文档
- `.git/` - Git仓库

**保留的目录**：
- `etc/` - 配置目录（用户数据）
- `ota/` - OTA更新包目录
- `slot_a/` - 槽位A
- `slot_b/` - 槽位B

### src目录（PySpOS/src/）
**作用**：源代码目录，包含所有系统文件

**包含内容**：
- 所有Python系统文件（main.py, kernel.py, ota.py等）
- 应用程序目录（apps/）
- SPF应用程序目录（spfapps/）
- 文档目录（docs/）
- 配置文件（btcfg.py, current_slot, version.txt）
- 启动器（launcher.py）

**使用场景**：
- 开发和测试
- 创建更新包（calculate_zip_info.py从这里打包）
- 系统恢复的基础版本

### 槽位目录（slot_a/, slot_b/）
**作用**：运行版本，支持OTA更新和回滚

**包含内容**：
- 完整的系统文件副本
- 应用程序目录
- SPF应用程序目录
- 文档目录
- 配置文件
- 更新日志（update_log.json）

**使用场景**：
- 正常系统运行
- OTA更新后的新版本
- 回滚后的旧版本

## 路径逻辑

### 启动器（launcher.py）
```python
# 根目录 = launcher.py所在目录
root_dir = os.path.dirname(os.path.abspath(__file__))

# 读取current_slot文件
current_slot_file = os.path.join(root_dir, "current_slot")

# 确定系统文件加载路径
if 槽位有效:
    system_path = slot_path  # 从槽位加载
else:
    system_path = os.path.join(root_dir, "src")  # 从src加载
```

### 主程序（main.py）
```python
# 获取main.py所在目录
script_dir = os.path.dirname(os.path.abspath(__file__))

# 检查是否在src目录或槽位目录中
if os.path.basename(script_dir) == 'src':
    # 在src目录中，根目录是src的父目录
    root_dir = os.path.dirname(script_dir)
elif os.path.basename(script_dir) in ['slot_a', 'slot_b']:
    # 在槽位目录中，根目录是槽位的父目录
    root_dir = os.path.dirname(script_dir)
else:
    # 其他情况，使用当前目录作为根目录
    root_dir = script_dir
```

### OTA模块（ota.py）
```python
# 获取ota.py所在目录
script_dir = os.path.dirname(os.path.abspath(__file__))

# 检查是否在src目录或槽位目录中
if os.path.basename(script_dir) == 'src':
    # 在src目录中，根目录是src的父目录
    root_dir = os.path.dirname(script_dir)
elif os.path.basename(script_dir) in ['slot_a', 'slot_b']:
    # 在槽位目录中，根目录是槽位的父目录
    root_dir = os.path.dirname(script_dir)
else:
    # 其他情况，使用当前目录作为根目录
    root_dir = script_dir
```

### 更新包创建（calculate_zip_info.py）
```python
# 从src目录打包文件
src_dir = 'src'
include_items = ['apps', 'docs', 'spfapps', 'btcfg.py', ...]

# 使用相对于src的路径作为zip中的路径
arcname = os.path.relpath(file_path, src_dir)
```

## 启动流程

### 正常启动（有槽位）
1. 运行 `start.bat` 或 `start.sh`
2. launcher.py 读取 `current_slot` 文件
3. launcher.py 验证槽位有效性
4. launcher.py 从槽位加载系统文件
5. main.py 在槽位目录中运行
6. PySpOS 正常启动

### 开发启动（无槽位）
1. 运行 `start.bat` 或 `start.sh`
2. launcher.py 读取 `current_slot` 文件（不存在或无效）
3. launcher.py 从src目录加载系统文件
4. main.py 在src目录中运行
5. PySpOS 正常启动

### OTA更新流程
1. 在src目录开发和测试新功能
2. 运行 `calculate_zip_info.py` 创建更新包（从src打包）
3. 在PySpOS中执行 `ota_update` 命令
4. 更新包解压到相反槽位
5. 切换 `current_slot` 文件
6. 重启系统
7. launcher.py 从新槽位加载系统文件
8. PySpOS 运行新版本

## 开发工作流

### 1. 修改代码
在 `src/` 目录中修改系统文件

### 2. 测试代码
```bash
# Windows
start.bat

# Linux/Mac
./start.sh
```

### 3. 创建更新包
```bash
python calculate_zip_info.py
```

这将：
- 从 `src/` 目录打包所有文件
- 计算SHA256哈希值
- 更新 `docs/ota/version.json`

### 4. 测试更新
```bash
# 在PySpOS中执行
ota_update
```

### 5. 重启系统
```bash
# Windows
start.bat

# Linux/Mac
./start.sh
```

## 注意事项

1. **src目录是源代码**：所有开发和修改都在src目录进行
2. **槽位是运行版本**：槽位包含完整的系统文件副本
3. **根目录保留必要文件**：launcher.py, start.bat, start.sh等保留在根目录
4. **更新包从src打包**：calculate_zip_info.py从src目录打包文件
5. **路径自动适配**：系统会自动检测当前所在目录并调整路径

## 常见问题

**Q: 为什么需要src目录？**
A: src目录作为源代码目录，便于开发和维护，同时保持根目录简洁。

**Q: 根目录和src目录有什么区别？**
A: 根目录保留必要的启动文件和文档，src目录包含所有系统代码。

**Q: 更新包从哪里打包？**
A: calculate_zip_info.py从src目录打包文件，确保更新包包含最新代码。

**Q: 如何确保路径正确？**
A: 所有文件都使用相对路径和自动检测，系统会自动适配不同运行环境。

**Q: 开发时如何测试？**
A: 直接运行start.bat或start.sh，系统会自动从src目录加载文件。
## 2026-09-24 重构补充

- `src/main.py` 已由 1217 行单体拆分为 `src/shell/*` 包（`util/sys_cmds/elf_cmd/ota_cmds/proc_cmds/dispatch`），`main.py` 仅保留启动状态与 facade 重导出，历史 `import main` 调用方零改动。
- 进程管理实现位于 `src/process.py`（PCB + EEVDF 调度器，对标 Linux 6.6+），`src/proc.py` 为兼容垫片。
- ELF 默认执行引擎为 Unicorn（`src/elf_loader/unicorn_runner.py`，需 `pip install unicorn`），自研 CPU 模拟器保留为 `--engine native` 兜底。
- OTA 云端更新由 `src/pyspos.py: OTA_ENABLED` 总控（服务器维护期间置 False，仅禁云端，本地安装/回滚不受影响）。
- 测试：`pytest tests/`（25 项：EEVDF/SPC/OTA 降级/shell/双引擎/SPF/公共模块）。

## SPC v2（2026-09-24）
- 格式稳定承诺：已有 `.spc` 逐字兼容。新增：引号内转义、行尾注释（`#` 前须有空白）、`null/none/~/空值`、`[列表]`。
- `spc.validate(data, schema, meta)`：缺失/类型/choices/越界记 error（带行号），未知项记 warning；`apply_defaults` 回填默认值；预置 `BOOTCFG_SCHEMA`。
- Shell：`spc_validate/spc_get/spc_set/spc_migrate`（`spc_migrate` 支持 json↔spc 双向，spc→json 自动重算 checksum）。
