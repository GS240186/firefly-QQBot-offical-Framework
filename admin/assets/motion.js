/* 小流萤控制台 · anime.js 动效增强层 (motion.js)
 * 非侵入式：不修改 charts.js 任何逻辑，仅通过观察 DOM class 变化 + 入场动画提升体验。
 * 依赖：window.anime（anime.js v4 命名空间，含 animate / stagger / set / remove）。
 */
(function () {
  'use strict';

  var anime = window.anime;
  if (!anime || typeof anime.animate !== 'function') {
    if (window.console) console.warn('[motion] anime.js 未就绪，跳过动效增强');
    return;
  }

  var prefersReduced = !!(window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches);

  function $(sel, root) { return (root || document).querySelectorAll(sel); }
  function isVisible(el) {
    return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  }
  function fmtInt(n) {
    n = Math.round(n);
    var s = String(Math.abs(n));
    s = s.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    return (n < 0 ? '-' : '') + s;
  }

  /* ---------- 通用 stagger 入场 ---------- */
  function staggerIn(els, opts) {
    opts = opts || {};
    var list = [];
    for (var i = 0; i < els.length; i++) {
      if (els[i] && els[i].nodeType === 1) list.push(els[i]);
    }
    if (!list.length) return;
    if (prefersReduced) {
      anime.set(list, { opacity: 1, translateY: 0, scale: 1 });
      return;
    }
    anime.remove(list);
    anime.set(list, {
      opacity: opts.fromOpacity != null ? opts.fromOpacity : 0,
      translateY: opts.fromY != null ? opts.fromY : 14,
      scale: opts.fromScale != null ? opts.fromScale : 1
    });
    anime.animate(list, {
      opacity: [opts.fromOpacity != null ? opts.fromOpacity : 0, 1],
      translateY: [opts.fromY != null ? opts.fromY : 14, 0],
      scale: [opts.fromScale != null ? opts.fromScale : 1, 1],
      duration: opts.duration || 520,
      delay: anime.stagger(opts.stagger || 45, { start: opts.start || 60 }),
      ease: opts.ease || 'outCubic'
    });
  }

  /* ---------- KPI 数字滚动（仅 dashboard 首次） ---------- */
  function countUpDashboard(page) {
    if (prefersReduced) return;
    var nums = page.querySelectorAll('.kpi .num');
    for (var i = 0; i < nums.length; i++) {
      var el = nums[i];
      var txt = (el.textContent || '').trim();
      if (!/^-?\d+(\.\d+)?$/.test(txt)) continue;   // 仅纯数字（跳过 "0 / 0"、"--" 等）
      var target = parseFloat(txt);
      if (isNaN(target)) continue;
      var obj = { v: 0 };
      anime.animate(obj, {
        v: target,
        duration: 900,
        ease: 'outCubic',
        update: (function (node) {
          return function () { node.textContent = fmtInt(obj.v); };
        })(el)
      });
    }
  }

  /* ---------- 页面切换入场 ---------- */
  var BLOCK_SEL = '.card, .panel, .kpi, .section-block, .sys-status-bar, .ann-box, .tool-card, .feature-card, .data-block';
  var lastActivePage = null;

  function animatePage(page) {
    if (!page) return;
    var blocks = [];
    var nodes = page.querySelectorAll(BLOCK_SEL);
    for (var i = 0; i < nodes.length; i++) {
      if (isVisible(nodes[i])) blocks.push(nodes[i]);
    }
    if (!blocks.length) {
      for (var j = 0; j < page.children.length; j++) blocks.push(page.children[j]);
    }
    if (!prefersReduced) {
      anime.remove(page);
      anime.set(page, { opacity: 0.35 });
      anime.animate(page, { opacity: [0.35, 1], duration: 280, ease: 'linear' });
    }
    staggerIn(blocks, { fromY: 16, stagger: 42, start: 70, duration: 520 });
    if (page.id === 'page-dashboard') countUpDashboard(page);
  }

  /* ---------- 模态框缩放淡入 ---------- */
  function animateModal(modal) {
    var content = modal.querySelector('.modal-content') || modal;
    if (prefersReduced) { anime.set(content, { opacity: 1, scale: 1, translateY: 0 }); return; }
    anime.remove(content);
    anime.set(content, { opacity: 0, scale: 0.94, translateY: 12 });
    anime.animate(content, {
      opacity: [0, 1],
      scale: [0.94, 1],
      translateY: [12, 0],
      duration: 360,
      ease: 'outBack'
    });
  }

  /* ---------- 下拉 / 弹层展开 ---------- */
  var POPOVERS = [
    { sel: '#dash-bot-selector', on: 'open', child: '#dash-bot-selector-menu li, #dash-bot-selector-menu button, #dash-bot-selector-menu .bot-selector-item' },
    { sel: '#ws-bot-selector', on: 'open', child: '#ws-bot-selector-menu li, #ws-bot-selector-menu button, #ws-bot-selector-menu .bot-selector-item' },
    { sel: '#cmd-overlay', on: 'active', child: '.cmd-result-item, li, button' }
  ];

  function animateOpen(el, childSel) {
    var items = childSel ? el.querySelectorAll(childSel) : el.children;
    var arr = [];
    for (var i = 0; i < items.length; i++) arr.push(items[i]);
    if (!arr.length) return;
    if (prefersReduced) { anime.set(arr, { opacity: 1, translateY: 0 }); return; }
    anime.remove(arr);
    anime.set(arr, { opacity: 0, translateY: -8 });
    anime.animate(arr, {
      opacity: [0, 1],
      translateY: [-8, 0],
      duration: 280,
      delay: anime.stagger(28),
      ease: 'outCubic'
    });
  }

  /* ---------- 观察器 ---------- */
  var pageMO = new MutationObserver(function (muts) {
    muts.forEach(function (m) {
      var el = m.target;
      if (el.classList && el.classList.contains('page') && el.classList.contains('active')) {
        if (el.id !== lastActivePage) {
          lastActivePage = el.id;
          requestAnimationFrame(function () { animatePage(el); });
        }
      }
    });
  });

  var modalMO = new MutationObserver(function (muts) {
    muts.forEach(function (m) {
      var el = m.target;
      if (el.classList && el.classList.contains('modal') && el.classList.contains('show')) {
        requestAnimationFrame(function () { animateModal(el); });
      }
    });
  });

  var popMO = new MutationObserver(function (muts) {
    muts.forEach(function (m) {
      var el = m.target;
      if (!el.classList) return;
      for (var k = 0; k < POPOVERS.length; k++) {
        var cfg = POPOVERS[k];
        if (el.matches && el.matches(cfg.sel) && el.classList.contains(cfg.on)) {
          (function (node, child) {
            requestAnimationFrame(function () { animateOpen(node, child); });
          })(el, cfg.child);
        }
      }
    });
  });

  /* ---------- 初始化 ---------- */
  function setup() {
    var pages = $('.page');
    if (!pages.length) return false;
    pages.forEach(function (p) {
      if (p.classList.contains('active')) lastActivePage = p.id;
      pageMO.observe(p, { attributes: true, attributeFilter: ['class'] });
    });
    if (lastActivePage) {
      var initPage = document.getElementById(lastActivePage);
      setTimeout(function () { animatePage(initPage); }, 120);
    }
    // 侧边栏初始入场
    staggerIn($('.nav-group'), { fromY: 10, stagger: 60, start: 80, duration: 480 });
    $('.modal').forEach(function (m) {
      modalMO.observe(m, { attributes: true, attributeFilter: ['class'] });
    });
    POPOVERS.forEach(function (cfg) {
      $(cfg.sel).forEach(function (el) {
        popMO.observe(el, { attributes: true, attributeFilter: ['class'] });
      });
    });
    return true;
  }

  function boot() {
    try {
      if (!setup()) { setTimeout(boot, 60); return; }
    } catch (e) {
      if (window.console) console.warn('[motion] init error', e);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
