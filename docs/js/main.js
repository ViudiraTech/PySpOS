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
      var rows = table.querySelectorAll("tbody tr");
      // 文字最长的那一列就是说明本身，不需要再标列名，免得每张卡片都多一行「说明」「作用」
      var totals = [];
      rows.forEach(function (tr) {
        Array.prototype.forEach.call(tr.children, function (cell, i) {
          totals[i] = (totals[i] || 0) + cell.textContent.trim().length;
        });
      });
      var main = totals.indexOf(Math.max.apply(null, totals));
      rows.forEach(function (tr) {
        Array.prototype.forEach.call(tr.children, function (cell, i) {
          var label = heads[i] && heads[i].textContent.trim();
          if (cell.tagName === "TD" && label && i !== main) cell.setAttribute("data-label", label);
        });
      });
    });
  }


  /* ---------- 长内容：折叠、横滑、本页目录 ----------
     三项都只在有脚本时生效；没有脚本时内容全部平铺，一个字都不会被藏起来。 */

  var FOLD_ROWS = 4;   // 表格超过 FOLD_ROWS + 1 行时，先显示 FOLD_ROWS 行
  var FOLD_CARDS = 4;  // 特性卡片超过 FOLD_CARDS 张时，电脑上先显示 FOLD_CARDS 张
  var uid = 0;

  function makeFold(list, items, keep, extraClass) {
    if (items.length <= keep + 1) return;
    if (!list.id) list.id = "fold-" + (++uid);
    var rest = items.length - keep;
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "fold-btn" + (extraClass ? " " + extraClass : "");
    btn.setAttribute("aria-controls", list.id);
    function set(open) {
      list.classList.toggle("is-collapsed", !open);
      btn.setAttribute("aria-expanded", String(open));
      btn.innerHTML = (open ? "收起" : "展开其余 " + rest + " 项") +
        '<svg class="icon" aria-hidden="true"><use href="#i-chevron"/></svg>';
    }
    set(false);
    btn.addEventListener("click", function () {
      var open = list.classList.contains("is-collapsed");
      set(open);
      if (open) {
        if (window.pgMotion) window.pgMotion.show(items.slice(keep));
      } else {
        // 收起时把按钮带回视野，免得停在一大片空白里
        var top = list.getBoundingClientRect().top;
        if (top < 0) list.scrollIntoView({ block: "start" });
      }
      if (window.ScrollTrigger) window.ScrollTrigger.refresh();
    });
    var anchor = list.closest(".table-wrap") || list;
    anchor.insertAdjacentElement("afterend", btn);
  }

  function initFold() {
    document.querySelectorAll("main .table-wrap:not([data-nofold]) table").forEach(function (table) {
      var rows = Array.prototype.slice.call(table.querySelectorAll("tbody > tr"));
      makeFold(table, rows, FOLD_ROWS);
    });
    document.querySelectorAll("main .rows-wide:not([data-nofold])").forEach(function (list) {
      var items = Array.prototype.slice.call(list.children);
      // 手机上这类列表改为横滑卡片，不需要折叠按钮（CSS 在窄屏隐藏 .fold-cards）
      makeFold(list, items, FOLD_CARDS, "fold-cards");
    });
  }

  // 手机上特性卡片横向滑动：下方一条进度条和「当前 / 总数」
  function initCarousel() {
    document.querySelectorAll("main .rows-wide").forEach(function (list) {
      var total = list.children.length;
      if (total < 2) return;
      var meta = document.createElement("div");
      meta.className = "swipe-meta";
      meta.setAttribute("aria-hidden", "true");
      meta.innerHTML = '<span class="swipe-track"><i></i></span><span class="swipe-count"></span>';
      list.insertAdjacentElement("afterend", meta);
      var thumb = meta.querySelector("i");
      var count = meta.querySelector(".swipe-count");
      function update() {
        var max = list.scrollWidth - list.clientWidth;
        if (max <= 1) { meta.hidden = true; return; }
        meta.hidden = false;
        var ratio = list.clientWidth / list.scrollWidth;
        var p = list.scrollLeft / max;
        thumb.style.width = (ratio * 100) + "%";
        thumb.style.transform = "translateX(" + (p * (1 / ratio - 1) * 100) + "%)";
        var card = list.children[0].getBoundingClientRect().width || 1;
        var idx = Math.min(total, Math.round(list.scrollLeft / card) + 1);
        count.textContent = "左右滑动 · " + idx + " / " + total;
      }
      list.addEventListener("scroll", update, { passive: true });
      window.addEventListener("resize", update);
      update();
    });
  }

  // 本页目录：小节多的页面，在首屏下方放一条吸顶的目录，滚动时高亮当前小节
  function initToc() {
    var main = document.querySelector("main");
    if (!main) return;
    var sections = Array.prototype.slice.call(main.querySelectorAll(":scope > section.section[id]")).filter(function (s) {
      return s.querySelector("h2");
    });
    if (sections.length < 4) return;
    var nav = document.createElement("nav");
    nav.className = "page-toc";
    nav.setAttribute("aria-label", "本页目录");
    var ul = document.createElement("ul");
    var links = sections.map(function (s) {
      var li = document.createElement("li");
      var a = document.createElement("a");
      a.href = "#" + s.id;
      a.textContent = s.querySelector("h2").textContent.trim();
      li.appendChild(a);
      ul.appendChild(li);
      return a;
    });
    nav.appendChild(ul);
    var hero = main.querySelector(":scope > .hero");
    if (hero) hero.insertAdjacentElement("afterend", nav);
    else main.prepend(nav);
    document.documentElement.classList.add("has-toc");

    if (!("IntersectionObserver" in window)) return;
    var current = null;
    function activate(a) {
      if (current === a) return;
      if (current) current.removeAttribute("aria-current");
      current = a;
      if (!a) return;
      a.setAttribute("aria-current", "true");
      // 只横向滚动目录本身，不带动页面
      var left = a.offsetLeft - (ul.clientWidth - a.offsetWidth) / 2;
      ul.scrollTo({ left: Math.max(0, left), behavior: "smooth" });
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) activate(links[sections.indexOf(e.target)]);
      });
    }, { rootMargin: "-40% 0px -55% 0px" });
    sections.forEach(function (s) { io.observe(s); });
  }

  function init() {
    initTheme();
    initMenu();
    initCopy();
    initTableLabels();
    initToc();
    initFold();
    initCarousel();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
