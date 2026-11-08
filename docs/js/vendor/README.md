# 第三方动画库

官网动画用到的库，原样从 npm 包的 `dist/` 复制过来，只去掉了 sourceMappingURL 注释。
放在本地而不是 CDN，是为了国内访问稳定，也让页面不依赖外部服务。
加载顺序由 `tools/sync_docs_chrome.py` 的 `VENDOR_SCRIPTS` 决定。

| 文件 | 来源 | 版本 | 许可 |
|---|---|---|---|
| `gsap.min.js` | npm `gsap` | 3.15.1 | GSAP Standard "No Charge" License，<https://gsap.com/standard-license> |
| `ScrollTrigger.min.js` | npm `gsap` | 3.15.1 | 同上 |
| `SplitText.min.js` | npm `gsap` | 3.15.1 | 同上 |
| `lenis.min.js` | npm `lenis` | 1.3.27 | MIT，见 `LICENSE-lenis.txt` |

升级时：`npm pack gsap lenis`，解包后把同名文件覆盖进来，删掉末尾的 sourceMappingURL 注释，
更新上表，再运行 `python tools/sync_docs_chrome.py` 刷新各页面引用里的版本哈希。
