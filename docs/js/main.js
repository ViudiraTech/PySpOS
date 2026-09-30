/* 站点交互：主题、导航和渐进增强的滚动动效。无 JS 依赖。 */
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

  function initMotion() {
    var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)");
    var header = document.querySelector(".site-header");
    var progress = document.createElement("div");
    progress.className = "reading-progress";
    progress.setAttribute("aria-hidden", "true");
    document.body.appendChild(progress);
    var pending = false;

    function updateProgress() {
      pending = false;
      var root = document.documentElement;
      var distance = root.scrollHeight - root.clientHeight;
      var position = Math.max(0, window.scrollY || root.scrollTop);
      progress.style.setProperty("--pg-scroll-progress", distance > 0 ? Math.min(1, position / distance) : 0);
      if (header) header.classList.toggle("is-scrolled", position > 16);
    }
    function queueProgress() {
      if (!pending) {
        pending = true;
        window.requestAnimationFrame(updateProgress);
      }
    }
    window.addEventListener("scroll", queueProgress, { passive: true });
    window.addEventListener("resize", queueProgress);
    window.addEventListener("load", queueProgress);
    if (window.ResizeObserver) new ResizeObserver(queueProgress).observe(document.body);
    updateProgress();

    if (!window.IntersectionObserver || (reduced && reduced.matches)) return;
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-revealed");
        observer.unobserve(entry.target);
      });
    }, { threshold: 0, rootMargin: "0px 0px -32px 0px" });
    var targets = document.querySelectorAll(
      ".page-head-grid > div, .section-head, .story-heading, .story-copy, .system-layer, " +
      ".desktop-evidence, .rows > .row, .timeline > li, .archive-index > div, .fact"
    );
    targets.forEach(function (el) {
      // 首屏和锚点目标即时可读；不通过透明度隐藏正文。
      var rect = el.getBoundingClientRect();
      el.classList.add("scroll-reveal");
      var siblings = Array.prototype.filter.call(el.parentElement.children, function (child) {
        return child.tagName === el.tagName;
      });
      el.style.setProperty("--pg-reveal-delay", (siblings.indexOf(el) % 4) * 60 + "ms");
      if (rect.top < window.innerHeight && rect.bottom > 0) el.classList.add("is-revealed");
      else observer.observe(el);
    });
    function revealFocus(event) {
      var el = event.target.closest(".scroll-reveal");
      if (el) { el.classList.add("is-revealed"); observer.unobserve(el); }
    }
    document.addEventListener("focusin", revealFocus);
    function revealHash() {
      var target = document.getElementById(window.location.hash.slice(1));
      if (!target) return;
      var el = target.closest(".scroll-reveal");
      if (el) { el.classList.add("is-revealed"); observer.unobserve(el); }
    }
    window.addEventListener("hashchange", revealHash);
    revealHash();
    if (reduced) reduced.addEventListener("change", function () {
      if (!reduced.matches) return;
      observer.disconnect();
      targets.forEach(function (el) { el.classList.add("is-revealed"); });
    });
  }

  function init() {
    initTheme();
    initNav();
    initCopy();
    initMotion();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
