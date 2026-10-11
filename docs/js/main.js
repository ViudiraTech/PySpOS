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
    var status = document.createElement("span");
    status.className = "sr-only";
    status.setAttribute("role", "status");
    document.body.appendChild(status);
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
        status.textContent = ok ? "命令已复制到剪贴板" : "复制失败，请手动选择命令复制";
        window.setTimeout(function () { btn.textContent = "复制命令"; }, 1600);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(cmds).then(function () { done(true); }, function () { done(false); });
      } else {
        done(false);
      }
    });
  }

  function initMotionPreference() {
    var actions = document.querySelector(".header-actions");
    if (!actions) return;
    var preference = null;
    try { preference = localStorage.getItem("pg-motion"); } catch (e) { /* optional storage */ }
    var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    var button = document.createElement("button");
    button.className = "icon-btn motion-toggle";
    button.type = "button";
    actions.insertBefore(button, document.getElementById("nav-toggle"));
    function paint() {
      var paused = preference === "off" || reduced.matches;
      document.body.classList.toggle("motion-paused", paused);
      document.documentElement.dataset.motion = paused ? "off" : "on";
      button.textContent = paused ? "▷" : "Ⅱ";
      button.setAttribute("aria-pressed", String(paused));
      button.setAttribute("aria-label", reduced.matches ? "已按系统设置减少动效" : (paused ? "开启动效" : "减少动效"));
      button.title = reduced.matches ? "已遵循系统的减少动态效果设置" : (paused ? "开启动效" : "减少动效");
      button.disabled = reduced.matches;
    }
    button.addEventListener("click", function () {
      preference = document.body.classList.contains("motion-paused") ? "on" : "off";
      try { localStorage.setItem("pg-motion", preference); } catch (e) { /* optional storage */ }
      paint();
    });
    reduced.addEventListener("change", paint);
    paint();
  }

  function initLab() {
    var lab = document.querySelector(".architecture-lab");
    if (!lab) return;
    var controls = lab.querySelector(".layer-controls");
    var description = lab.querySelector(".lab-description");
    var layers = {
      app: ["shell / applications", "从一条命令开始。Shell 解析输入，独立应用拥有自己的界面与逻辑。"],
      kernel: ["process.py / EEVDF", "进程、调度、权限与系统调用。沿着 Python 源码，看到系统如何作出决定。"],
      runtime: ["Python 3.10+ / host OS", "以 Python 与宿主系统作为运行基础。应用通过真实子进程执行，ELF 指令由执行引擎处理。"]
    };
    controls.hidden = false;
    controls.addEventListener("click", function (event) {
      var button = event.target.closest("[data-layer]");
      if (!button) return;
      var key = button.dataset.layer;
      controls.querySelectorAll("button").forEach(function (item) {
        item.setAttribute("aria-pressed", String(item === button));
      });
      lab.querySelectorAll("[data-plane]").forEach(function (plane) {
        plane.dataset.selected = String(plane.dataset.plane === key);
      });
      description.querySelector("code").textContent = layers[key][0];
      description.querySelector("p").textContent = layers[key][1];
      if (!document.body.classList.contains("motion-paused") && description.animate) {
        description.animate([{ transform: "translateY(8px)" }, { transform: "translateY(0)" }], { duration: 450, easing: "cubic-bezier(0.16, 1, 0.3, 1)" });
      }
    });
    var view = lab.querySelector(".stack-view");
    var finePointer = window.matchMedia("(hover: hover) and (pointer: fine)");
    var pointerFrame = null;
    var pointerX = 0;
    var pointerY = 0;
    view.addEventListener("pointermove", function (event) {
      if (!finePointer.matches || document.body.classList.contains("motion-paused")) return;
      var rect = view.getBoundingClientRect();
      pointerX = ((event.clientX - rect.left) / rect.width - 0.5) * 8;
      pointerY = ((event.clientY - rect.top) / rect.height - 0.5) * -6;
      if (pointerFrame !== null) return;
      pointerFrame = window.requestAnimationFrame(function () {
        view.style.setProperty("--pg-stack-tilt-x", pointerY + "deg");
        view.style.setProperty("--pg-stack-tilt-y", pointerX + "deg");
        pointerFrame = null;
      });
    });
    view.addEventListener("pointerleave", function () {
      if (pointerFrame !== null) window.cancelAnimationFrame(pointerFrame);
      pointerFrame = null;
      view.style.setProperty("--pg-stack-tilt-x", "0deg");
      view.style.setProperty("--pg-stack-tilt-y", "0deg");
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
    var backTop = document.createElement("a");
    backTop.className = "back-top";
    backTop.href = "#main";
    backTop.textContent = "↑";
    backTop.setAttribute("aria-label", "回到页面顶部");
    document.body.appendChild(backTop);
    var story = document.querySelector(".command-story");
    var steps = story ? Array.prototype.slice.call(story.querySelectorAll(".command-step")) : [];
    var nodes = story ? story.querySelectorAll(".execution-node") : [];
    var activeStep = -1;
    var sectionLinks = Array.prototype.slice.call(document.querySelectorAll(".section-jump a[href^='#'], .page-toc a[href^='#']"));
    var sectionTargets = sectionLinks.map(function (link) { return document.getElementById(link.hash.slice(1)); });
    var pending = false;

    function updateProgress() {
      pending = false;
      var root = document.documentElement;
      var distance = root.scrollHeight - root.clientHeight;
      var position = Math.max(0, window.scrollY || root.scrollTop);
      progress.style.setProperty("--pg-scroll-progress", distance > 0 ? Math.min(1, position / distance) : 0);
      if (header) header.classList.toggle("is-scrolled", position > 16);
      backTop.classList.toggle("is-visible", position > root.clientHeight);
      var currentSection = -1;
      sectionTargets.forEach(function (target, i) {
        if (target && target.getBoundingClientRect().top <= root.clientHeight * 0.35) currentSection = i;
      });
      sectionLinks.forEach(function (link, i) {
        link.classList.toggle("is-current", i === currentSection);
        if (i === currentSection) link.setAttribute("aria-current", "location");
        else link.removeAttribute("aria-current");
      });
      if (story) {
        var middle = root.clientHeight * 0.52;
        var nearest = 0;
        var best = Infinity;
        var centers = steps.map(function (step, index) {
          var rect = step.getBoundingClientRect();
          var center = rect.top + rect.height / 2;
          if (Math.abs(center - middle) < best) { best = Math.abs(center - middle); nearest = index; }
          return center;
        });
        var span = centers[centers.length - 1] - centers[0];
        var completed = span > 0 ? Math.max(0, Math.min(1, (middle - centers[0]) / span)) : 0;
        story.style.setProperty("--pg-section-progress", completed);
        if (nearest !== activeStep) {
          activeStep = nearest;
          steps.forEach(function (step, i) { step.classList.toggle("is-active", i === nearest); });
          nodes.forEach(function (node, i) { node.classList.toggle("is-active", i === nearest); });
          story.querySelector(".execution-count").textContent = "0" + (nearest + 1) + " / 03";
        }
      }
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
      ".desktop-evidence, .feature-grid > .feature-card, .timeline > li, .archive-index > div, .fact, .command-step"
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
    initMotionPreference();
    initLab();
    initMotion();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
