/* 主题预初始化：在正文渲染前确定主题，避免闪烁。
   约定：body.theme-dark = 暗色（默认），无类名 = 亮色。 */
(function () {
  var KEY = "pg-theme";
  var saved = null;
  try {
    saved = localStorage.getItem(KEY);
  } catch (e) {
    saved = null;
  }
  var theme;
  if (saved === "light" || saved === "dark") {
    theme = saved;
  } else if (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) {
    theme = "light";
  } else {
    theme = "dark";
  }
  document.documentElement.dataset.theme = theme;
  var apply = function () {
    document.body.classList.toggle("theme-dark", theme === "dark");
  };
  if (document.body) {
    apply();
  } else {
    document.addEventListener("DOMContentLoaded", apply);
  }
})();
