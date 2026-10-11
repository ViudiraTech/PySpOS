# 网站重构与验收 · 2026-10-11

整体方向：精密系统实验室。九个 HTML 依照内容重新组织，移除原有功能横线列表，以卡片、摘要面板、真实运行画面和文档侧栏建立层次。

## 成熟实现参考

- [Linear UI redesign](https://linear.app/now/how-we-redesigned-the-linear-ui)：导航层次、对齐、减少视觉噪声。
- [Vercel Geist](https://vercel.com/geist/introduction)：一致的色彩、字体和交互组件。
- [GSAP ScrollTrigger](https://gsap.com/docs/v3/Plugins/ScrollTrigger/)：滚动进度、固定展示和阶段联动；本站以原生 CSS、IntersectionObserver 和 requestAnimationFrame 实现。
- [Apple macOS](https://www.apple.com/os/macos/)：产品画面与分段展示的节奏。
- [Fedora Workstation download](https://fedoraproject.org/workstation/download/)：下载文件、版本信息与校验操作的分组。
- [shadcn Card](https://ui.shadcn.com/docs/components/card)：标题、内容和操作区域的卡片结构。

## 各页结构

| 页面 | 重构结果 |
| --- | --- |
| 首页 | 可交互立体架构、执行路径滚动叙事、项目展示面板、历史项目卡片与发展历程 |
| PySpOS | 终端会话首屏、介绍与概要双栏、不同尺寸的功能网格、模块代码卡片 |
| SpaceOS 8 | 真实运行画面首屏、项目规模展板、运行验证卡片与系统模块网格 |
| 配置要求 | 产品入口、文档侧栏、软件与硬件分组卡片 |
| SpaceOS 6 / 7 | 存档封面、历史导航、成果与技术卡片；保留停止开发提示 |
| SpaceOS 8 下载 | 镜像展示卡、文件元数据与校验命令双栏、版本与使用声明卡片 |
| OTA 下载 | 最新版本与真实下载操作合为更新包卡，安装要求与恢复步骤分组 |
| 版本历史 | 发布记录卡片、版本类型筛选、关键词搜索和空结果提示 |

## 验证

- `python3 -m pytest tests/web -q`：4 passed。包含 HTML/链接、产品状态、设计 token、对比度和 OTA manifest 检查。
- 外部与内联 JavaScript 均通过 `node --check`。
- 九页在 1280px 桌面及 768 / 390 / 320px 断点检查；390px 下额外检查卡片内容与页眉溢出。
- 深色和亮色主题均查看真实截图。实测剪贴板得到 `help\nps`；手机菜单打开及 Escape 关闭；版本筛选、搜索空结果和架构切换正常。
- 检查了动效开关与保存偏好，CSS 同时遵循系统 `prefers-reduced-motion`。系统设置本身未通过浏览器模拟切换。
- 修复窄屏更新包卡片的日期换行，以及默认开启的截图透视动效造成的页面横向溢出。
- 预览期间长时间运行的工具会话被终止，已改为独立本地预览进程；源文件与测试不依赖该进程。

截图及 `browser-qa.json` 保存于本目录。截图用于网站界面验证，不代表操作系统运行状态在本次任务中重新验证。
