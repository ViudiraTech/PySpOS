/* 主题预初始化：放在 <body> 的第一行，正文绘制前就定好主题，避免闪一下。
   约定：body.theme-dark = 暗色，无类名 = 亮色。
   站点默认暗色；只有访客手动切到浅色并保存过，才用浅色。
   同时给 <html> 打上 js 标记，窄屏侧栏据此才收成抽屉；没有脚本时导航照常显示。
   访客没有要求减少动态效果时再打上 motion 标记：首屏内容先藏起来，等 motion.js 接管后播放入场动画。
   motion.js 3 秒内没有接管（脚本加载失败、被拦截），就撤掉标记，内容照常显示。 */
(function () {
  var KEY = "pg-theme";
  var root = document.documentElement;
  var saved = null;
  try { saved = localStorage.getItem(KEY); } catch (e) { saved = null; }

  var theme = saved === "light" ? "light" : "dark";

  root.classList.add("js");
  root.dataset.theme = theme;

  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!reduce) {
    root.classList.add("motion");
    window.setTimeout(function () {
      if (!root.classList.contains("motion-ready")) root.classList.remove("motion");
    }, 3000);
  }

  var apply = function () { document.body.classList.toggle("theme-dark", theme === "dark"); };
  if (document.body) apply();
  else document.addEventListener("DOMContentLoaded", apply);
})();
