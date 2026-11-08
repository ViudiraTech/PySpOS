/* 站点动画：GSAP + ScrollTrigger + SplitText + Lenis（都在 js/vendor，本地加载）。
   全部是渐进增强：
   - 访客要求减少动态效果，或者任何一个库没加载上，就什么都不做，页面保持静态完整；
   - 没有脚本时 theme-init.js 不会打上 motion 标记，内容不会被藏起来；
   - 动画只改 transform / opacity / clip-path，不改文字内容（数字滚动结束后与原文一致）。 */
(function () {
  "use strict";

  var root = document.documentElement;
  var gsap = window.gsap;
  var ScrollTrigger = window.ScrollTrigger;
  var SplitText = window.SplitText;
  var mm = window.matchMedia ? function (q) { return window.matchMedia(q).matches; } : function () { return false; };

  if (!gsap || !ScrollTrigger || mm("(prefers-reduced-motion: reduce)")) {
    root.classList.remove("motion");
    return;
  }
  gsap.registerPlugin(ScrollTrigger);
  if (SplitText) gsap.registerPlugin(SplitText);

  var finePointer = mm("(hover: hover) and (pointer: fine)");
  var $ = function (sel, ctx) { return (ctx || document).querySelector(sel); };
  var $$ = function (sel, ctx) { return Array.prototype.slice.call((ctx || document).querySelectorAll(sel)); };

  gsap.defaults({ ease: "power3.out", duration: 0.9 });

  /* ---------- 平滑滚动 ---------- */
  var lenis = null;
  function initLenis() {
    if (!window.Lenis) return;
    // 锚点跳转交给 Lenis，它会读取 html 的 scroll-padding-top，避开吸顶页眉。
    lenis = new window.Lenis({ lerp: 0.1, wheelMultiplier: 1, anchors: true });
    lenis.on("scroll", ScrollTrigger.update);
    gsap.ticker.add(function (time) { lenis.raf(time * 1000); });
    gsap.ticker.lagSmoothing(0);
  }

  /* ---------- 阅读进度条与页眉 ---------- */
  function initChrome() {
    var bar = document.createElement("div");
    bar.className = "scroll-progress";
    bar.setAttribute("aria-hidden", "true");
    document.body.appendChild(bar);
    gsap.to(bar, { scaleX: 1, ease: "none", scrollTrigger: { start: 0, end: "max", scrub: 0.3 } });

    var header = $(".site-header");
    var nav = $("#site-nav");
    if (!header) return;
    // 往下滚时收起页眉，往上滚立刻出现；菜单展开或焦点在页眉里时不收。
    ScrollTrigger.create({
      start: 0,
      end: "max",
      onUpdate: function (self) {
        var y = self.scroll();
        header.classList.toggle("is-scrolled", y > 8);
        var busy = (nav && nav.classList.contains("open")) || header.querySelector("details[open]") ||
          header.contains(document.activeElement);
        header.classList.toggle("is-hidden", self.direction === 1 && y > 320 && !busy);
      }
    });
  }

  /* ---------- 导航：跟随鼠标的高亮块、窄屏菜单展开 ---------- */
  function initNav() {
    var nav = $("#site-nav");
    if (!nav) return;
    var list = $(":scope > ul", nav);
    var items = $$(":scope > ul > li > a, :scope > ul > li > details > summary", nav);

    var media = gsap.matchMedia();
    media.add("(min-width: 56.01rem) and (hover: hover)", function () {
      var pill = document.createElement("span");
      pill.className = "nav-indicator";
      pill.setAttribute("aria-hidden", "true");
      list.prepend(pill);
      nav.classList.add("has-indicator");
      var shown = false;
      function moveTo(el) {
        var vars = { x: el.offsetLeft, y: el.offsetTop, width: el.offsetWidth, height: el.offsetHeight };
        if (!shown) { gsap.set(pill, vars); shown = true; }
        gsap.to(pill, Object.assign({ autoAlpha: 1, duration: 0.45, ease: "expo.out", overwrite: true }, vars));
      }
      function hide() { shown = false; gsap.to(pill, { autoAlpha: 0, duration: 0.25, overwrite: true }); }
      items.forEach(function (el) {
        el.addEventListener("mouseenter", function () { moveTo(el); });
        el.addEventListener("focus", function () { moveTo(el); });
      });
      list.addEventListener("mouseleave", hide);
      return function () { pill.remove(); nav.classList.remove("has-indicator"); };
    });

    // 窄屏：菜单打开时逐项落下
    new MutationObserver(function () {
      if (nav.classList.contains("open")) {
        gsap.from($$(":scope > ul > li", nav), { y: -10, autoAlpha: 0, duration: 0.45, stagger: 0.04, ease: "power2.out" });
      }
    }).observe(nav, { attributes: true, attributeFilter: ["class"] });
  }

  /* ---------- 文字拆分 ---------- */
  // 带 <br> 的标题按行包一层遮罩，逐行从下方升起；行内的 .grad 渐变不受影响。
  function splitLines(el) {
    var groups = [[]];
    Array.prototype.slice.call(el.childNodes).forEach(function (n) {
      if (n.nodeName === "BR") groups.push([]);
      else groups[groups.length - 1].push(n);
    });
    el.textContent = "";
    return groups.map(function (nodes) {
      var mask = document.createElement("span");
      var line = document.createElement("span");
      mask.className = "pg-line-mask";
      line.className = "pg-line";
      mask.style.display = "block";
      mask.style.overflow = "clip";
      line.style.display = "block";
      nodes.forEach(function (n) { line.appendChild(n); });
      mask.appendChild(line);
      el.appendChild(mask);
      return line;
    });
  }

  function splitChars(el) {
    if (!SplitText) return null;
    var split = SplitText.create(el, { type: "words,chars", wordsClass: "pg-word", charsClass: "pg-char" });
    return split.chars;
  }

  /* ---------- 插画：分层拼装、连线描边、虚线流动 ---------- */
  function prepStroke(path) {
    var len = 0;
    try { len = path.getTotalLength(); } catch (e) { len = 0; }
    if (!len) return 0;
    gsap.set(path, { strokeDasharray: len, strokeDashoffset: len });
    return len;
  }

  function artTimeline(svg) {
    var tl = gsap.timeline({ paused: true });
    var blocks = $$("rect", svg);
    var texts = $$("text", svg);
    var strokes = $$(".art-brand, .art-line", svg);
    var icons = $$(".art-ico", svg);
    tl.from(blocks, { y: -28, autoAlpha: 0, scale: 0.94, transformOrigin: "50% 50%", duration: 0.9, stagger: 0.14, ease: "back.out(1.4)" }, 0)
      .from(texts, { x: -12, autoAlpha: 0, duration: 0.6, stagger: 0.04 }, 0.25)
      .from(icons, { scale: 0, autoAlpha: 0, transformOrigin: "50% 50%", duration: 0.7, stagger: 0.12, ease: "back.out(2)" }, 0.45);
    strokes.forEach(function (p, i) {
      if (!prepStroke(p)) return;
      tl.to(p, { strokeDashoffset: 0, duration: 0.8, ease: "power2.inOut" }, 0.55 + i * 0.12);
    });
    // 描完之后变成流动的虚线，表示数据在层与层之间传递
    tl.call(function () {
      strokes.forEach(function (p) {
        gsap.set(p, { strokeDasharray: "6 7", strokeDashoffset: 0 });
        gsap.to(p, { strokeDashoffset: -26, duration: 1.4, ease: "none", repeat: -1 });
      });
      icons.forEach(function (g, i) {
        gsap.to(g, { y: -3, duration: 1.8 + i * 0.3, ease: "sine.inOut", yoyo: true, repeat: -1 });
      });
    });
    return tl;
  }

  /* ---------- 终端：逐行打出 ---------- */
  function typeTerminal(pre) {
    var code = $("code", pre) || pre;
    var lines = Math.max(1, code.textContent.replace(/\n$/, "").split("\n").length);
    var caret = document.createElement("span");
    caret.className = "term-caret";
    caret.setAttribute("aria-hidden", "true");
    gsap.set(code, { display: "block", clipPath: "inset(0% 0% 100% 0%)" });
    return gsap.to(code, {
      clipPath: "inset(0% 0% 0% 0%)",
      duration: Math.min(2.4, lines * 0.11),
      ease: "steps(" + lines + ")",
      paused: true,
      onComplete: function () { code.appendChild(caret); gsap.set(code, { clearProps: "clipPath" }); }
    });
  }

  /* ---------- 首屏入场 ---------- */
  function initHero() {
    var hero = $(".hero");
    if (!hero) return;
    var tl = gsap.timeline({ defaults: { ease: "expo.out", duration: 1.1 }, delay: 0.05 });

    var badge = $(".hero-badge", hero);
    if (badge) tl.from(badge, { y: 16, autoAlpha: 0, duration: 0.8 }, 0);

    var h1 = $("h1", hero);
    if (h1) {
      if (h1.querySelector("br")) {
        h1.classList.add("is-split");
        tl.from(splitLines(h1), { yPercent: 110, rotation: 2, duration: 1.2, stagger: 0.12 }, 0.08);
      } else {
        var chars = splitChars(h1);
        if (chars && chars.length) {
          h1.classList.add("is-split");
          tl.from(chars, {
            yPercent: 90, rotationX: -80, autoAlpha: 0, transformOrigin: "50% 100% -0.5em",
            duration: 1, stagger: { each: 0.03, from: "start" }
          }, 0.08);
        } else {
          tl.from(h1, { y: 30, autoAlpha: 0 }, 0.08);
        }
      }
    }

    var lede = $(".lede", hero);
    if (lede) tl.from(lede, { y: 24, autoAlpha: 0 }, 0.4);
    var acts = $$(".actions > *", hero);
    if (acts.length) tl.from(acts, { y: 20, autoAlpha: 0, stagger: 0.08 }, 0.55);
    var spec = $$(".spec > div", hero);
    if (spec.length) tl.from(spec, { y: 16, autoAlpha: 0, stagger: 0.06 }, 0.65);

    var fig = $("figure", hero);
    if (fig) {
      var svg = $("svg.art", fig);
      if (svg) {
        var art = artTimeline(svg);
        tl.from(fig, { autoAlpha: 0, duration: 0.4 }, 0.2);
        tl.add(function () { art.play(); }, 0.25);
        var cap = $("figcaption", fig);
        if (cap) tl.from(cap, { y: 10, autoAlpha: 0, duration: 0.8 }, 1.2);
      } else {
        tl.from(fig, { y: 50, scale: 0.95, rotationX: 10, transformPerspective: 1200, autoAlpha: 0, duration: 1.4 }, 0.25);
        var term = $("pre.terminal", fig);
        if (term) {
          var typing = typeTerminal(term);
          tl.add(function () { typing.play(); }, 0.8);
        }
        // 往下滚时截图比文字移得快一点，拉出前后景深
        var img = $("img", fig);
        if (img) {
          gsap.to(fig, {
            yPercent: -10, ease: "none",
            scrollTrigger: { trigger: hero, start: "top top", end: "bottom top", scrub: true }
          });
        }
      }
    }

    // 极光随鼠标轻微偏移
    if (finePointer) {
      var ax = gsap.quickTo(hero, "--ax", { duration: 1.6, ease: "power3" });
      var ay = gsap.quickTo(hero, "--ay", { duration: 1.6, ease: "power3" });
      hero.addEventListener("pointermove", function (e) {
        var r = hero.getBoundingClientRect();
        ax((e.clientX - r.left) / r.width - 0.5);
        ay((e.clientY - r.top) / r.height - 0.5);
      });
      hero.addEventListener("pointerleave", function () { ax(0); ay(0); });
    }
  }

  /* ---------- 滚动入场 ---------- */
  function reveal(targets, from, opts) {
    targets = targets.filter(Boolean);
    if (!targets.length) return;
    opts = opts || {};
    gsap.set(targets, Object.assign({ autoAlpha: 0 }, from));
    ScrollTrigger.batch(targets, {
      start: opts.start || "top 88%",
      once: true,
      onEnter: function (batch) {
        var to = { autoAlpha: 1, x: 0, y: 0, scale: 1, rotationX: 0, rotation: 0, stagger: opts.stagger || 0.09,
          duration: opts.duration || 1, ease: opts.ease || "expo.out", overwrite: true,
          clearProps: "transform,opacity,visibility" };
        gsap.to(batch, to);
        if (opts.onEnter) opts.onEnter(batch);
      }
    });
  }

  // 去掉祖先已经在列表里的元素，避免父子叠加两次动画
  function topmost(els) {
    return els.filter(function (el) {
      return !els.some(function (other) { return other !== el && other.contains(el); });
    });
  }

  function popIcons(batch) {
    var icons = batch.map(function (el) { return $(".icon-box", el); }).filter(Boolean);
    if (icons.length) {
      gsap.fromTo(icons, { scale: 0.5, rotation: -20 },
        { scale: 1, rotation: 0, duration: 0.9, stagger: 0.09, ease: "back.out(2.2)", delay: 0.15, clearProps: "transform" });
    }
  }

  function initReveals() {
    var main = $("main");
    if (!main) return;
    var heroEl = $(".hero", main);
    var notHero = function (el) { return !(heroEl && heroEl.contains(el)); };

    // 小节标题逐字浮现
    reveal($$(".archive-title", main), { x: -20 });
    $$(".section-head h2, .split > h2", main).filter(notHero).forEach(function (h) {
      var chars = splitChars(h);
      if (!chars || !chars.length) { reveal([h], { y: 30 }); return; }
      gsap.from(chars, {
        yPercent: 80, autoAlpha: 0, rotationX: -60, transformOrigin: "50% 100%", duration: 0.9,
        stagger: 0.025, ease: "expo.out",
        scrollTrigger: { trigger: h, start: "top 88%", once: true }
      });
    });
    reveal($$(".section-head .lede", main).filter(notHero), { y: 24 });

    reveal($$(".tile", main), { y: 70, rotationX: -14, transformOrigin: "50% 100%" },
      { stagger: 0.12, duration: 1.2, onEnter: popIcons });
    reveal($$(".points > li", main), { y: 40 }, { stagger: 0.1, onEnter: popIcons });
    reveal($$(".flow > li", main), { y: 40, scale: 0.96 }, { stagger: 0.12, onEnter: popIcons });
    reveal($$(".rows > li", main), { x: -30 }, { stagger: 0.07 });
    reveal($$(".layers > li", main), { x: 50 }, { stagger: 0.07 });

    var general = topmost($$([
      ".notice", ".table-wrap", "main pre", ".stack > p", ".stack > ul", ".stack > ol", ".stack > dl",
      ".stack > .actions", ".stack > h3", "figure", ".prose > *", ".release-tools"
    ].join(","), main).filter(notHero).filter(function (el) {
      return !el.closest(".tile, .points, .flow, .rows, .layers");
    }));
    reveal(general, { y: 36 }, { stagger: 0.08 });

    // 插画：进入视口后再拼装
    $$("svg.art", main).filter(notHero).forEach(function (svg) {
      var tl = artTimeline(svg);
      ScrollTrigger.create({ trigger: svg, start: "top 80%", once: true, onEnter: function () { tl.play(); } });
    });

    // 不在首屏的终端也逐行打出
    $$("pre.terminal", main).filter(notHero).forEach(function (pre) {
      var t = typeTerminal(pre);
      ScrollTrigger.create({ trigger: pre, start: "top 80%", once: true, onEnter: function () { t.play(); } });
    });

    // 首屏以外的大图：遮罩展开 + 轻微缩放
    $$("figure img", main).filter(notHero).forEach(function (img) {
      gsap.fromTo(img, { clipPath: "inset(8% 6% 8% 6% round 1.125rem)", scale: 1.06 }, {
        clipPath: "inset(0% 0% 0% 0% round 1.125rem)", scale: 1, duration: 1.6, ease: "expo.out",
        clearProps: "clipPath,transform",
        scrollTrigger: { trigger: img, start: "top 85%", once: true }
      });
    });
  }

  /* ---------- 数据：条形图生长、数字滚动 ---------- */
  function initData() {
    $$(".table-wrap").forEach(function (wrap) {
      var bars = $$(".bar > i", wrap);
      var nums = $$("td.num", wrap);
      if (!bars.length && !nums.length) return;
      gsap.set(bars, { scaleX: 0 });
      ScrollTrigger.create({
        trigger: wrap, start: "top 82%", once: true,
        onEnter: function () {
          gsap.to(bars, { scaleX: 1, duration: 1.6, stagger: 0.08, ease: "expo.out", delay: 0.2 });
          nums.forEach(function (td, i) {
            var node = td.lastChild;
            if (!node || node.nodeType !== 3) return;
            var text = node.nodeValue.trim();
            if (!/^\d{1,3}(,\d{3})*$|^\d+$/.test(text)) return;
            var end = parseInt(text.replace(/,/g, ""), 10);
            var grouped = text.indexOf(",") !== -1;
            var obj = { v: 0 };
            gsap.to(obj, {
              v: end, duration: 1.6, delay: 0.2 + i * 0.08, ease: "expo.out",
              onUpdate: function () {
                var n = Math.round(obj.v);
                node.nodeValue = grouped ? n.toLocaleString("en-US") : String(n);
              },
              onComplete: function () { node.nodeValue = text; }
            });
          });
        }
      });
    });
  }

  /* ---------- 卡片：鼠标跟随高光、3D 倾斜；按钮：磁吸 ---------- */
  function initPointer() {
    if (!finePointer) return;
    function track(el) {
      el.classList.add("spot");
      el.addEventListener("pointermove", function (e) {
        var r = el.getBoundingClientRect();
        el.style.setProperty("--mx", (e.clientX - r.left) + "px");
        el.style.setProperty("--my", (e.clientY - r.top) + "px");
      });
    }
    $$(".tile, .flow > li, .release, .table-wrap").forEach(track);
    window.pgTrackSpot = track;

    $$(".tile").forEach(function (tile) {
      var rx = gsap.quickTo(tile, "rotationX", { duration: 0.6, ease: "power3" });
      var ry = gsap.quickTo(tile, "rotationY", { duration: 0.6, ease: "power3" });
      gsap.set(tile, { transformPerspective: 900 });
      tile.addEventListener("pointermove", function (e) {
        var r = tile.getBoundingClientRect();
        ry(((e.clientX - r.left) / r.width - 0.5) * 8);
        rx(-((e.clientY - r.top) / r.height - 0.5) * 8);
      });
      tile.addEventListener("pointerleave", function () { rx(0); ry(0); });
    });

    $$(".button").forEach(function (btn) {
      var mx = gsap.quickTo(btn, "x", { duration: 0.5, ease: "power3" });
      var my = gsap.quickTo(btn, "y", { duration: 0.5, ease: "power3" });
      btn.addEventListener("pointermove", function (e) {
        var r = btn.getBoundingClientRect();
        mx((e.clientX - r.left - r.width / 2) * 0.22);
        my((e.clientY - r.top - r.height / 2) * 0.35);
      });
      btn.addEventListener("pointerleave", function () {
        gsap.to(btn, { x: 0, y: 0, duration: 0.9, ease: "elastic.out(1, 0.4)", overwrite: true });
      });
    });
  }

  /* ---------- 版本历史：脚本渲染出来的列表也有入场 ---------- */
  function initDynamicLists() {
    var host = $("#version-history");
    if (!host) return;
    new MutationObserver(function () {
      var items = $$(":scope > .release", host).slice(0, 12);
      if (!items.length) return;
      if (window.pgTrackSpot) items.forEach(window.pgTrackSpot);
      gsap.fromTo(items, { y: 28, autoAlpha: 0 }, {
        y: 0, autoAlpha: 1, duration: 0.7, stagger: 0.05, ease: "expo.out", overwrite: true,
        clearProps: "transform,opacity,visibility"
      });
    }).observe(host, { childList: true });
  }

  /* ---------- 页脚：超大字标随滚动升起 ---------- */
  function initFooter() {
    var footer = $(".site-footer");
    if (!footer) return;
    var mark = document.createElement("div");
    mark.className = "footer-mark";
    mark.setAttribute("aria-hidden", "true");
    mark.textContent = "GoutouStdio";
    footer.appendChild(mark);
    gsap.from(mark, {
      yPercent: 45, autoAlpha: 0, ease: "none",
      scrollTrigger: { trigger: footer, start: "top bottom", end: "bottom bottom", scrub: 0.6 }
    });
    reveal($$(".footer-grid > *", footer), { y: 24 }, { stagger: 0.07, start: "top 95%" });
  }

  function init() {
    initLenis();
    initChrome();
    initNav();
    initHero();
    root.classList.add("motion-ready");
    initReveals();
    initData();
    initPointer();
    initDynamicLists();
    initFooter();
    // 图片和字体到齐后重新量一次触发位置
    window.addEventListener("load", function () { ScrollTrigger.refresh(); });
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { ScrollTrigger.refresh(); });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
