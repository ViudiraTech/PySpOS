/* 主题预初始化：放在 <body> 的第一行，正文绘制前就定好主题，避免闪一下。
   约定：body.theme-dark = 暗色，无类名 = 亮色。
   没有保存过选择时跟随系统；系统也没给出偏好时用暗色。
   同时给 <html> 打上 js 标记，窄屏侧栏据此才收成抽屉；没有脚本时导航照常显示。 */
(function () {
  var KEY = "pg-theme";
  var root = document.documentElement;
  var saved = null;
  try { saved = localStorage.getItem(KEY); } catch (e) { saved = null; }

  var theme;
  if (saved === "light" || saved === "dark") {
    theme = saved;
  } else if (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) {
    theme = "light";
  } else {
    theme = "dark";
  }

  root.classList.add("js");
  root.dataset.theme = theme;
  var apply = function () { document.body.classList.toggle("theme-dark", theme === "dark"); };
  if (document.body) apply();
  else document.addEventListener("DOMContentLoaded", apply);
})();
