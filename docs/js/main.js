/* 站点交互：主题切换、导航菜单、代码块复制。
   三项都是渐进增强，脚本失效时页面内容与导航仍然可用。 */
(function () {
  "use strict";

  var KEY = "pg-theme";

  function readTheme() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }
  function saveTheme(theme) {
    try { localStorage.setItem(KEY, theme); } catch (e) { /* 隐私模式下忽略 */ }
  }
  function preferredTheme() {
    if (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) return "light";
    return "dark";
  }

  function initTheme() {
    var btn = document.getElementById("theme-toggle");
    function apply(theme, persist) {
      var dark = theme !== "light";
      document.body.classList.toggle("theme-dark", dark);
      document.documentElement.dataset.theme = dark ? "dark" : "light";
      if (btn) {
        btn.textContent = dark ? "主题：深色" : "主题：浅色";
        btn.setAttribute("aria-label", dark ? "当前为深色主题，点击切换到浅色" : "当前为浅色主题，点击切换到深色");
      }
      if (persist) saveTheme(dark ? "dark" : "light");
    }
    apply(readTheme() || preferredTheme(), false);
    if (!btn) return;
    btn.addEventListener("click", function () {
      apply(document.body.classList.contains("theme-dark") ? "light" : "dark", true);
    });
    window.addEventListener("storage", function (e) {
      if (e.key === KEY) apply(e.newValue || preferredTheme(), false);
    });
  }

  function initMenu() {
    var toggle = document.getElementById("nav-toggle");
    var menu = document.getElementById("site-nav");
    var drops = Array.prototype.slice.call(document.querySelectorAll(".site-nav details.menu"));

    function closeDrops(except) {
      drops.forEach(function (d) { if (d !== except) d.removeAttribute("open"); });
    }
    // 下拉菜单一次只开一个；点到别处或按 Esc 收起。
    drops.forEach(function (d) {
      d.addEventListener("toggle", function () { if (d.open) closeDrops(d); });
    });
    document.addEventListener("click", function (e) {
      drops.forEach(function (d) { if (d.open && !d.contains(e.target)) d.removeAttribute("open"); });
    });

    function setOpen(open) {
      if (!toggle || !menu) return;
      menu.classList.toggle("open", open);
      toggle.setAttribute("aria-expanded", String(open));
    }
    if (toggle && menu) {
      toggle.addEventListener("click", function () {
        setOpen(!menu.classList.contains("open"));
      });
      document.addEventListener("click", function (e) {
        if (menu.classList.contains("open") && !menu.contains(e.target) && !toggle.contains(e.target)) setOpen(false);
      });
    }
    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      closeDrops(null);
      if (menu && menu.classList.contains("open")) {
        setOpen(false);
        if (toggle) toggle.focus();
      }
    });
  }

  function initCopy() {
    var status = document.createElement("span");
    status.className = "sr-only";
    status.setAttribute("role", "status");
    document.body.appendChild(status);

    // 只给可以直接粘贴执行的命令块加复制按钮；输出示例标成 class="output"，不加。
    document.querySelectorAll("main pre:not(.output)").forEach(function (pre) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "copy-btn";
      btn.textContent = "复制";
      pre.appendChild(btn);
    });

    document.addEventListener("click", function (e) {
      var btn = e.target.closest(".copy-btn");
      if (!btn) return;
      var copy = btn.parentElement.cloneNode(true);
      var own = copy.querySelector(".copy-btn");
      if (own) own.remove();
      var text = copy.textContent.replace(/\n$/, "");
      function done(ok) {
        btn.textContent = ok ? "已复制" : "复制失败";
        status.textContent = ok ? "已复制到剪贴板" : "复制失败，请手动选择文本";
        window.setTimeout(function () { btn.textContent = "复制"; }, 1600);
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () { done(true); }, function () { done(false); });
      } else {
        done(false);
      }
    });
  }

  function init() {
    initTheme();
    initMenu();
    initCopy();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
