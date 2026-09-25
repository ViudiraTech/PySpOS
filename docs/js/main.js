/* 站点交互：主题切换 + 移动端导航。无其他 JS 依赖。 */
(function () {
  "use strict";

  var KEY = "pg-theme";
  var ICON_MOON =
    '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">' +
    '<path d="M13.5 9.5A5.5 5.5 0 0 1 6.5 2.5a.5.5 0 0 0-.6-.6A6.5 6.5 0 1 0 14 10a.5.5 0 0 0-.5-.5Z" fill="currentColor"/></svg>';
  var ICON_SUN =
    '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">' +
    '<circle cx="8" cy="8" r="3" fill="currentColor"/>' +
    '<path d="M8 1v1.5M8 13.5V15M1 8h1.5M13.5 8H15M3 3l1 1M12 12l1 1M13 3l-1 1M4 12l-1 1" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>';

  function readTheme() {
    try {
      return localStorage.getItem(KEY);
    } catch (e) {
      return null;
    }
  }

  function saveTheme(theme) {
    try {
      localStorage.setItem(KEY, theme);
    } catch (e) {
      /* 隐私模式下直接忽略 */
    }
  }

  function preferredTheme() {
    if (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) {
      return "light";
    }
    return "dark";
  }

  function paintToggle(btn, theme) {
    var dark = theme !== "light";
    btn.innerHTML = dark ? ICON_MOON : ICON_SUN;
    btn.setAttribute("aria-pressed", String(dark));
    btn.setAttribute("aria-label", dark ? "切换到亮色主题" : "切换到暗色主题");
  }

  function applyTheme(theme, persist) {
    var normalized = theme === "light" ? "light" : "dark";
    document.body.classList.toggle("theme-dark", normalized === "dark");
    document.documentElement.dataset.theme = normalized;
    var btn = document.getElementById("theme-toggle");
    if (btn) paintToggle(btn, normalized);
    if (persist) saveTheme(normalized);
  }

  function initTheme() {
    applyTheme(readTheme() || preferredTheme(), !readTheme());
    var btn = document.getElementById("theme-toggle");
    if (!btn) return;
    btn.addEventListener("click", function () {
      applyTheme(document.body.classList.contains("theme-dark") ? "light" : "dark", true);
    });
    window.addEventListener("storage", function (e) {
      if (e.key === KEY || e.key === null) applyTheme(e.newValue || preferredTheme(), false);
    });
  }

  function initCopy() {
    document.addEventListener("click", function (e) {
      var btn = e.target.closest(".copy-btn");
      if (!btn) return;
      var box = btn.dataset.copy && document.getElementById(btn.dataset.copy);
      if (!box) return;
      var cmds = Array.prototype.map.call(
        box.querySelectorAll(".t-cmd"),
        function (el) { return el.textContent; }
      ).join("\n");
      var done = function (ok) {
        btn.textContent = ok ? "已复制" : "复制失败";
        window.setTimeout(function () { btn.textContent = "复制命令"; }, 1600);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(cmds).then(function () { done(true); }, function () { done(false); });
      } else {
        done(false);
      }
    });
  }

  function initNav() {
    var toggle = document.getElementById("nav-toggle");
    var menu = document.getElementById("site-nav");
    if (!toggle || !menu) return;

    function setOpen(open) {
      menu.classList.toggle("open", open);
      toggle.setAttribute("aria-expanded", String(open));
      toggle.textContent = open ? "✕" : "☰";
    }

    toggle.addEventListener("click", function () {
      setOpen(!menu.classList.contains("open"));
    });
    menu.addEventListener("click", function (e) {
      if (e.target.closest("a")) setOpen(false);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") setOpen(false);
    });
    document.addEventListener("click", function (e) {
      if (
        menu.classList.contains("open") &&
        !menu.contains(e.target) &&
        !toggle.contains(e.target)
      ) {
        setOpen(false);
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      initTheme();
      initNav();
      initCopy();
    });
  } else {
    initTheme();
    initNav();
    initCopy();
  }
})();
