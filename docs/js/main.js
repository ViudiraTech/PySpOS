/* 站点交互：主题切换、导航菜单、代码块复制。
   三项都是渐进增强，脚本失效时页面内容与导航仍然可用。
   滚动与入场动画在 motion.js 里，和这里互不依赖。 */
(function () {
  "use strict";

  var KEY = "pg-theme";

  function readTheme() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }
  function saveTheme(theme) {
    try { localStorage.setItem(KEY, theme); } catch (e) { /* 隐私模式下忽略 */ }
  }
  // 站点默认暗色，访客手动切到浅色才用浅色（与 theme-init.js 一致）。
  function preferredTheme() { return "dark"; }
  function reducedMotion() {
    return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function initTheme() {
    var btn = document.getElementById("theme-toggle");
    function apply(theme, persist) {
      var dark = theme !== "light";
      document.body.classList.toggle("theme-dark", dark);
      document.documentElement.dataset.theme = dark ? "dark" : "light";
      if (btn) {
        var label = dark ? "当前为深色主题，点击切换到浅色" : "当前为浅色主题，点击切换到深色";
        btn.setAttribute("aria-label", label);
        btn.title = label;
      }
      if (persist) saveTheme(dark ? "dark" : "light");
    }
    apply(readTheme() || preferredTheme(), false);
    if (!btn) return;
    // 支持 View Transitions 的浏览器里，新主题从按钮位置以圆形展开；其余浏览器直接切换。
    btn.addEventListener("click", function () {
      var next = document.body.classList.contains("theme-dark") ? "light" : "dark";
      if (!document.startViewTransition || reducedMotion()) { apply(next, true); return; }
      var rect = btn.getBoundingClientRect();
      var x = rect.left + rect.width / 2;
      var y = rect.top + rect.height / 2;
      var r = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y));
      var root = document.documentElement;
      root.classList.add("vt-theme");
      var vt = document.startViewTransition(function () { apply(next, true); });
      vt.ready.then(function () {
        root.animate(
          { clipPath: ["circle(0 at " + x + "px " + y + "px)", "circle(" + r + "px at " + x + "px " + y + "px)"] },
          { duration: 560, easing: "cubic-bezier(0.65, 0, 0.35, 1)", pseudoElement: "::view-transition-new(root)" }
        );
      }).catch(function () { /* 被打断时主题已经切好，忽略 */ });
      vt.finished.then(function () { root.classList.remove("vt-theme"); }, function () { root.classList.remove("vt-theme"); });
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
        btn.classList.toggle("is-done", ok);
        status.textContent = ok ? "已复制到剪贴板" : "复制失败，请手动选择文本";
        window.setTimeout(function () { btn.textContent = "复制"; btn.classList.remove("is-done"); }, 1600);
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () { done(true); }, function () { done(false); });
      } else {
        done(false);
      }
    });
  }

  // 手机上表格会堆叠成卡片，每个单元格前要显示列名；这里把表头文字抄到 data-label。
  function initTableLabels() {
    document.querySelectorAll("main table").forEach(function (table) {
      var heads = table.querySelectorAll("thead th");
      if (!heads.length) return;
      table.querySelectorAll("tbody tr").forEach(function (tr) {
        Array.prototype.forEach.call(tr.children, function (cell, i) {
          var label = heads[i] && heads[i].textContent.trim();
          if (cell.tagName === "TD" && label) cell.setAttribute("data-label", label);
        });
      });
    });
  }

  function init() {
    initTheme();
    initMenu();
    initCopy();
    initTableLabels();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
