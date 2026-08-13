/* 小流萤 bot 管理后台 · 数据 + 图表 */

(function () {

  // 每次 tick 开头调一次 _refreshTheme()，刷新深浅主题切换后的所有 CSS 变量值。

  // 这样 setOption 用到的 accent/ink/muted/rule 等永远跟随当前主题。

  var accent = '', accent2 = '', ink = '', muted = '', rule = '', green = '', warn = '', orange = '', bg2 = '';

  function _refreshTheme() {

    // CSS 变量在 body.dark-mode 上定义（不在 :root），所以读 body 才能取到深色模式值

    var s = getComputedStyle(document.body || document.documentElement);

    accent = s.getPropertyValue('--accent').trim() || '#3b6ef5';

    accent2 = s.getPropertyValue('--accent-2').trim() || '#00b894';

    ink = s.getPropertyValue('--ink').trim() || '#1f2240';

    muted = s.getPropertyValue('--muted').trim() || '#8b91b5';

    rule = s.getPropertyValue('--rule').trim() || '#ececf4';

    green = s.getPropertyValue('--green').trim() || '#26c281';

    warn = s.getPropertyValue('--warn').trim() || '#ff6b6b';

    orange = s.getPropertyValue('--orange').trim() || '#ff9f43';

    bg2 = s.getPropertyValue('--bg2').trim() || '#ffffff';

  }

  _refreshTheme();

  // 由 membersCenter / profilesCenter / groupsCenter 赋值，供 switchPage 调用

  var loadMembersRef = null;

  var loadProfilesRef = null;

  var loadGroupsRef = null;

  var loadJoinRequestsRef = null;
  var loadJoinApprovalRef = null;

  var loadBannedWordsListRef = null;

  var loadBannedWordsSetRef = null;

  var loadGroupMuteDurationRef = null;

  var loadUsersRef = null;

  var loadFeatureConfigRef = null;

  var loadPluginConfigRef = null;

  var loadPluginMarketRef = null;

  var loadQaRulesRef = null;

  var loadAiChatRef = null;

  var loadAiModelsRef = null;

  var loadAiSensitiveRef = null;

  var loadAiPersonaRef = null;

  var loadAiKnowledgeRef = null;

  var loadScheduledRef = null;

  var loadPersonalizeRef = null;

  var loadFeatureDataRef = null;

  var loadAdminSettingsRef = null;

  var loadAdminCommandsRef = null;

  var clearAdminStatusTimer = null;

  // ============================================================

  // 数据源：后端 127.0.0.1:9988

  // ============================================================

  var API_BASE = 'http://127.0.0.1:9988';

  var lastStats = null;

  var lastStatsFetchTime = 0;

  var isOnline = false;

  // ============================================================

  // localStorage 累积（趋势图历史）

  // ============================================================

  var LS_KEY = 'xiaoliu_daily_stats_v1';

  // 仪表盘所选机器人（空=全部）；用于 KPI / 图表按 bot 切换查看，刷新保持选择

  var dashBotFilter = (function () {

    try { var v = sessionStorage.getItem('dashBotFilter'); return v == null ? '' : v; }

    catch (e) { return ''; }

  })();

  // 仪表盘消息趋势「多机器人对比」开关 + 每条 bot 线配色

  var trendCompareMode = false;

  var BOT_PALETTE = ['#3b6ef5', '#26c281', '#ff9f43', '#a55eea', '#ff6b6b', '#00b894', '#6c8eff', '#fd79a8', '#fdcb6e', '#0984e3'];

  function todayKey() {

    var d = new Date();

    return d.getFullYear() + '-' +

      String(d.getMonth() + 1).padStart(2, '0') + '-' +

      String(d.getDate()).padStart(2, '0');

  }

  function loadHistory(key) {

    var k = key || LS_KEY;

    try {

      var raw = localStorage.getItem(k);

      return raw ? JSON.parse(raw) : {};

    } catch (e) { return {}; }

  }

  function saveHistory(h, key) {

    var k = key || LS_KEY;

    try { localStorage.setItem(k, JSON.stringify(h)); } catch (e) {}

  }

  // 仪表盘所选机器人的历史命名空间（空=全局）；用于按 bot 切换查看时图表各自累积

  function dashHistoryKey() { return dashBotFilter ? (LS_KEY + '#' + dashBotFilter) : LS_KEY; }

  function recordToday(snapshot) {

    if (!snapshot || !snapshot.online) return;

    // 全局历史始终累积（保证「全部机器人」视图准确）；选中某 bot 时额外累积该 bot 的历史（向前累积）

    _writeHistoryRow(LS_KEY, snapshot);

    if (dashBotFilter) _writeHistoryRow(dashHistoryKey(), snapshot);

  }

  function _writeHistoryRow(storageKey, snapshot) {

    var key = todayKey();

    var h = loadHistory(storageKey);

    h[key] = {

      ts: Date.now(),

      total: Math.max(snapshot.messages_today || 0, (h[key] && h[key].total) || 0),

      private: Math.max(snapshot.private_messages || 0, (h[key] && h[key].private) || 0),

      group: Math.max(snapshot.group_messages || 0, (h[key] && h[key].group) || 0),

      active_users: Math.max(snapshot.active_users_today || 0, (h[key] && h[key].active_users) || 0),

      active_groups: Math.max(snapshot.active_groups_today || 0, (h[key] && h[key].active_groups) || 0)

    };

    // 清理 60 天以前的数据

    var cutoff = Date.now() - 60 * 86400000;

    Object.keys(h).forEach(function (k) {

      var t = Date.parse(k + 'T00:00:00');

      if (!isNaN(t) && t < cutoff) delete h[k];

    });

    saveHistory(h, storageKey);

  }

  // 每次全局 tick：把每个机器人今日汇总写进各自的 per-bot 历史桶（LS_KEY#bot），

  // 使「多机器人对比」折线能获得所有 bot 的历史（而非仅被单独查看过的 bot）。

  function recordAllBotHistories(snapshot) {

    if (!snapshot || !snapshot.online) return;

    var pb = snapshot.per_bot || {};

    var key = todayKey();

    Object.keys(pb).forEach(function (bk) {

      try {

        var sk = LS_KEY + '#' + bk;

        var h = loadHistory(sk);

        var v = pb[bk] || {};

        h[key] = {

          ts: Date.now(),

          total: Math.max(v.messages_today || 0, (h[key] && h[key].total) || 0),

          private: Math.max(v.private_messages || 0, (h[key] && h[key].private) || 0),

          group: Math.max(v.group_messages || 0, (h[key] && h[key].group) || 0),

          active_users: Math.max(v.active_users_today || 0, (h[key] && h[key].active_users) || 0),

          active_groups: Math.max(v.active_groups_today || 0, (h[key] && h[key].active_groups) || 0)

        };

        saveHistory(h, sk);

      } catch (e) {}

    });

  }

  function fetchStats(cb, bot) {

    var url = API_BASE + '/api/stats';

    if (bot) url += '?bot=' + encodeURIComponent(bot);

    fetch(url, { method: 'GET' })

      .then(function (r) { return r.json(); })

      .then(function (j) {

        if (!bot) { lastStats = j; lastStatsFetchTime = Date.now(); }

        isOnline = true; cb(j);

      })

      .catch(function () {

        isOnline = false;

        cb(bot ? null : lastStats);

      });

  }

  function setText(id, value) {

    var el = document.getElementById(id);

    if (el) el.textContent = value;

  }

  // 将字节/秒格式化为易读网速（自动 B / KB / MB / GB）

  function fmtSpeed(bps) {

    if (bps == null || isNaN(bps)) return '--';

    var KB = 1024, MB = KB * 1024, GB = MB * 1024;

    if (bps >= GB) return (bps / GB).toFixed(2) + ' GB/s';

    if (bps >= MB) return (bps / MB).toFixed(2) + ' MB/s';

    if (bps >= KB) return (bps / KB).toFixed(1) + ' KB/s';

    return Math.round(bps) + ' B/s';

  }

  function setStatus(value) {

    var el = document.getElementById('kpi-status');

    var dot = document.getElementById('kpi-status-dot');

    if (el) {

      el.textContent = value ? '在线' : '离线';

      el.style.color = value ? accent : warn;

    }

    if (dot) {

      dot.style.background = value ? accent : warn;

      dot.style.boxShadow = value

        ? '0 0 0 3px ' + accent + '22'

        : '0 0 0 3px ' + warn + '22';

    }

  }

  // ====== 机器人 KPI 卡片: 渲染每个 bot 的状态 chip ======

  function botDotClass(bot) {

    if (!bot) return 'unknown';

    if (bot.connected) return 'on';

    if (bot.enabled === false) return 'disabled';

    return 'off';

  }

  function escapeHtml(s) {

    if (s == null) return '';

    return String(s)

      .replace(/&/g, '&amp;')

      .replace(/</g, '&lt;')

      .replace(/>/g, '&gt;')

      .replace(/"/g, '&quot;')

      .replace(/'/g, '&#39;');

  }

  function renderBotChips(bots) {

    var wrap = document.getElementById('kpi-robots-list');

    if (!wrap) return;

    if (!Array.isArray(bots) || bots.length === 0) {

      wrap.innerHTML = '';

      return;

    }

    var html = '';

    var shown = 0;

    bots.forEach(function (b) {

      var nm = b.name_rt || _sanitizeName(b.name, b.appid) || b.appid_masked || b.appid || '机器人';

      nm = String(nm).slice(0, 12);

      var dot = botDotClass(b);

      var env = b.environment || '?';

      var titleRaw =

        (b.name_rt || b.name || '') +

        ' | appid: ' + (b.appid || '?') +

        ' | env: ' + env +

        ' | enabled: ' + (b.enabled ? 'true' : 'false') +

        ' | connected: ' + (b.connected ? 'true' : 'false') +

        ' | event: ' + (b.event_mode || '?');

      html +=

        '<span class="bot-chip" title="' + escapeHtml(titleRaw) + '">' +

        '<span class="bot-dot ' + dot + '"></span>' +

        '<span class="bot-nm">' + escapeHtml(nm) + '</span>' +

        '</span>';

      shown++;

    });

    if (shown === 0) {

      wrap.innerHTML = '';

      return;

    }

    wrap.innerHTML = html;

    wrap.setAttribute('data-bots-count', String(shown));

  }

  function formatUptime(sec) {

    if (!sec) return '--';

    var h = Math.floor(sec / 3600);

    var m = Math.floor((sec % 3600) / 60);

    var s = sec % 60;

    if (h > 0) return h + 'h ' + m + 'm';

    if (m > 0) return m + 'm ' + s + 's';

    return s + 's';

  }

  function fmtUptimeKpi(sec) {

    if (!sec && sec !== 0) return { main: '--', sub: '--' };

    var d = Math.floor(sec / 86400);

    var h = Math.floor((sec % 86400) / 3600);

    var m = Math.floor((sec % 3600) / 60);

    var s = Math.floor(sec % 60);

    if (d > 0) {

      return { main: d + '天', sub: h + '小时 ' + (m < 10 ? '0' : '') + m + '分' };

    }

    if (h > 0) {

      return { main: h + '小时', sub: (m < 10 ? '0' : '') + m + '分 ' + (s < 10 ? '0' : '') + s + '秒' };

    }

    if (m > 0) {

      return { main: m + '分', sub: (s < 10 ? '0' : '') + s + '秒' };

    }

    return { main: s + '秒', sub: '运行中' };

  }

  function updateUptime() {

    if (!lastStats || !lastStatsFetchTime) return;

    var elapsed = Math.floor((Date.now() - lastStatsFetchTime) / 1000);

    var sec = (lastStats.uptime_seconds || 0) + elapsed;

    var fmt = fmtUptimeKpi(sec);

    setText('kpi-uptime', fmt.main);

    setText('kpi-uptime-sub', fmt.sub);

  }

  function isDark() { return document.body.classList.contains('dark-mode'); }

  function tooltipTheme() {

    return isDark()

      ? { backgroundColor: '#1e2035', borderColor: '#2f324d', textStyle: { color: '#f0f1f7' } }

      : { backgroundColor: '#ffffff', borderColor: rule, textStyle: { color: ink } };

  }

  // ============================================================

  // KPI 指标渲染

  // ============================================================

  function periodDays(period) {

    switch (period) {

      case 'today': return 1;

      case 'week': return 7;

      case 'month': return 30;

      case 'quarter': return 90;

      case 'year': return 365;

      case 'all': return 0;

      default: return 30;

    }

  }

  // 实时按 bot 缓存（兜底用：bot 专属切换后 todayKey 还没写进历史时，

  // 不依赖 lastStats 全局值，避免被全局累加串扰）

  var _statsByBot = {};

  function rememberBotSnapshot(s, key) {

    if (!s) return;

    var k = key || '';

    _statsByBot[k] = s;

  }

  function sumHistory(days, key, todayFallback) {

    var k = key || LS_KEY;

    var h = loadHistory(k);

    var sum = 0;

    if (days <= 0) {

      Object.keys(h).forEach(function (ky) { sum += (h[ky] && h[ky].total) || 0; });

    } else {

      var now = new Date();

      for (var i = 0; i < days; i++) {

        var d = new Date(now.getTime() - i * 86400000);

        var dk = d.getFullYear() + '-' +

          String(d.getMonth() + 1).padStart(2, '0') + '-' +

          String(d.getDate()).padStart(2, '0');

        sum += (h[dk] && h[dk].total) || 0;

      }

    }

    // 兜底：今天的历史还没写入时，用调用方传入的 todayFallback（来自 s.messages_today，

    // 已经按 bot 过滤），保证"切到该 bot"也能立刻看到今天的累加。

    if (!h[todayKey()]) {

      sum += todayFallback || 0;

    }

    return sum;

  }

  function avgHistory(days, key, todayFallback) {

    var k = key || LS_KEY;

    var h = loadHistory(k);

    if (days <= 0) days = Object.keys(h).length || 1;

    var total = sumHistory(days <= 0 ? 0 : days, k, todayFallback);

    return Math.round(total / Math.max(1, days));

  }

  function weekMessageTotal(key, todayFallback) { return sumHistory(7, key, todayFallback); }

  function monthMessageTotal(key, todayFallback) { return sumHistory(30, key, todayFallback); }

  // 旧版首页仪表盘 KPI

  function applyKpi(s) {

    if (!s) {

      setStatus(false);

      return;

    }

    setStatus(!!s.online);

    setText('kpi-robots', (s.robots_online || 0) + ' / ' + (s.robots_total || 0));

    setText('kpi-msg-today', s.messages_today || 0);

    setText('kpi-msg-yest', s.messages_yesterday_delta || 0);

    setText('kpi-checkin', s.checkins_today || 0);

    setText('kpi-checkin-d', s.checkins_yesterday_delta || 0);

    setText('kpi-groups', s.groups_total || 0);

    setText('kpi-groups-d', s.groups_yesterday_delta || 0);

    setText('kpi-members', s.members_total || 0);

    setText('kpi-members-d', s.members_yesterday_delta || 0);

    setText('kpi-priv', s.private_messages || 0);

    setText('kpi-grp', s.group_messages || 0);

    setText('kpi-active-user', s.active_users_today || 0);

    setText('kpi-active-grp', s.active_groups_today || 0);

    setText('kpi-leave-grp', s.groups_left_today || 0);

    setText('kpi-join-grp', s.groups_joined_today || 0);

    setText('kpi-add-friend', s.friends_added_today || 0);

    setText('kpi-del-friend', s.friends_removed_today || 0);

    setText('kpi-network', s.network_latency != null ? s.network_latency : '--');

    setText('kpi-network-speed', (function () {

      var sp = s.network_speed || {};

      return '↓ ' + fmtSpeed(sp.recv_bps) + '  ↑ ' + fmtSpeed(sp.send_bps);

    })());

    updateUptime();

    // 数据概览（按 dashBotFilter 联动；本周/总/签到/插件 — 插件是全局共享的，不切但弱化标注）

    rememberBotSnapshot(s, dashBotFilter);

    setText('overview-week-msg', weekMessageTotal(dashHistoryKey(), s.messages_today || 0) + ' 条');

    setText('overview-total-msg', (s.messages_total || s.messages_today || 0) + ' 条');

    setText('overview-checkin', (s.checkins_today || 0) + ' 次');

    var _plug = s.active_plugins || 0;

    var _ovPlugins = document.getElementById('overview-plugins');

    if (_ovPlugins) _ovPlugins.innerHTML = _plug + ' 个<small class="overview-shared-tag">共享</small>';

    renderOverviewBotTag(s);

    // 顶栏：机器人名 + 在线指示

    setText('top-bot-name', s.bot_name || '小流萤');

    setText('top-bot-pid', 'PID ' + (s.bot_pid || '--'));

    setText('top-bot-uptime', formatUptime(s.uptime_seconds || 0));

    // ====== 渲染每个 bot 的状态 chip (基于 /api/stats.bots) ======

    renderBotChips(s.bots || []);

  }

  // 新版数据中心 · 数据总览 KPI

  function setDataText(id, value) {

    var el = document.getElementById(id);

    if (el) el.textContent = value;

  }

  function setDataStatus(value) {

    var el = document.getElementById('data-kpi-status');

    if (el) {

      el.textContent = value ? '在线' : '离线';

      el.style.color = value ? accent : warn;

    }

  }

  function applyDataOverviewKpi(s) {

    if (!s) {

      setDataStatus(false);

      return;

    }

    setDataStatus(!!s.online);

    setDataText('data-kpi-robots', (s.robots_online || 0) + ' / ' + (s.robots_total || 0));

    setDataText('data-kpi-msg-today', s.messages_today || 0);

    setDataText('data-kpi-checkin', s.checkins_today || 0);

    setDataText('data-kpi-groups', s.groups_total || 0);

    setDataText('data-kpi-members', s.members_total || 0);

    setDataText('data-kpi-msg-week', weekMessageTotal(dashHistoryKey(), s.messages_today || 0));

    setDataText('data-kpi-msg-month', monthMessageTotal(dashHistoryKey(), s.messages_today || 0));

    setDataText('data-kpi-msg-avg', avgHistory(0, dashHistoryKey(), s.messages_today || 0));

  }

  // 实时系统状态条：日期时间 + CPU / 内存 / GPU

  var WEEK_CN = ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六'];

  function pad2(n) { return String(n).padStart(2, '0'); }

  function updateClock() {

    var d = new Date();

    setText('ssb-date', d.getFullYear() + '年' + pad2(d.getMonth() + 1) + '月' + pad2(d.getDate()) + '日');

    setText('ssb-time', pad2(d.getHours()) + ':' + pad2(d.getMinutes()) + ':' + pad2(d.getSeconds()));

    setText('ssb-week', WEEK_CN[d.getDay()]);

    updateUptime();

  }

  function metricColor(pct, base) {

    if (pct == null) return base;

    if (pct >= 85) return '#e74c3c';

    if (pct >= 70) return '#f39c12';

    return base;

  }

  function setSysMetric(fillId, valId, pct, base) {

    var fill = document.getElementById(fillId);

    var val = document.getElementById(valId);

    if (!fill || !val) return;

    if (pct == null) {

      fill.style.width = '0%';

      val.textContent = '-- %';

      val.style.color = '';

      return;

    }

    var safe = Math.max(0, Math.min(100, pct));

    var c = metricColor(pct, base);

    fill.style.width = safe + '%';

    fill.style.background = c;

    val.textContent = (Math.round(pct * 10) / 10) + ' %';

    val.style.color = c;

  }

  function applySysStatus(s) {

    if (!s) return;

    // CPU

    var cpu = s.cpu || {};

    setSysMetric('ssb-cpu-fill', 'ssb-cpu-val', cpu.percent, '#3b6ef5');

    // 内存

    var mem = s.mem;

    setSysMetric('ssb-mem-fill', 'ssb-mem-val', mem && mem.percent != null ? mem.percent : null, '#00b894');

    // GPU（取第一张卡）

    var gpu = s.gpu || {};

    var g0 = (gpu.available && gpu.devices && gpu.devices[0]) ? gpu.devices[0] : null;

    setSysMetric('ssb-gpu-fill', 'ssb-gpu-val', g0 && g0.percent != null ? g0.percent : null, '#8b5cf6');

  }

  // ============================================================

  // 图表

  // ============================================================

  function initChart(elId) {

    var el = document.getElementById(elId);

    if (!el) return null;

    return echarts.init(el, null, { renderer: 'svg' });

  }

  // 旧版首页仪表盘

  var chart = initChart('chart-trend');

  var activeChart = initChart('chart-active');

  // 新版数据中心 · 数据总览（延迟初始化，避免在 display:none 时取到 0 尺寸）

  var dataChartTrend = null;

  var dataChartDir = null;

  var dataChartType = null;

  var dataChartRank = null;

  var dataChartPeak = null;

  function ensureDataCharts() {

    var page = document.getElementById('page-data-overview');

    if (!page || !page.classList.contains('active')) return;

    if (!dataChartTrend) dataChartTrend = initChart('data-chart-trend');

    if (!dataChartDir) dataChartDir = initChart('data-chart-dir');

    if (!dataChartType) dataChartType = initChart('data-chart-type');

    if (!dataChartRank) dataChartRank = initChart('data-chart-rank');

    if (!dataChartPeak) dataChartPeak = initChart('data-chart-peak');

  }

  function baseOption() {

    var t = tooltipTheme();

    return {

      textStyle: { fontFamily: 'Outfit, "Noto Sans CJK SC", "Microsoft YaHei", sans-serif' },

      tooltip: {

        backgroundColor: t.backgroundColor,

        borderColor: t.borderColor,

        textStyle: { color: t.textStyle.color, fontSize: 12 }

      }

    };

  }

  function liveSnapshot() {

    return lastStats || {};

  }

  function todayRecFromSnapshot() {

    var s = liveSnapshot();

    return {

      total: s.messages_today || 0,

      private: s.private_messages || 0,

      group: s.group_messages || 0

    };

  }

  function getSeries(days, key) {

    var h = loadHistory(key);

    var dates = [], total = [], priv = [], grp = [];

    var now = new Date();

    for (var i = days - 1; i >= 0; i--) {

      var d = new Date(now.getTime() - i * 86400000);

      var k = d.getFullYear() + '-' +

        String(d.getMonth() + 1).padStart(2, '0') + '-' +

        String(d.getDate()).padStart(2, '0');

      var label = String(d.getMonth() + 1).padStart(2, '0') + '-' +

        String(d.getDate()).padStart(2, '0');

      dates.push(label);

      var rec = h[k] || { total: 0, private: 0, group: 0 };

      // 今天的数据若尚未写入历史，用实时快照兜底，保证切到页面至少能看到当前数据

      if (i === 0 && !h[k]) {

        rec = todayRecFromSnapshot();

      }

      total.push(rec.total); priv.push(rec.private); grp.push(rec.group);

    }

    return { dates: dates, total: total, priv: priv, grp: grp };

  }

  // ---------- 旧版首页：消息趋势 ----------

  function renderChart(days) {

    if (!chart) return;

    if (trendCompareMode) { renderTrendCompare(days); return; }

    var d = getSeries(days, dashHistoryKey());

    var max = Math.max(1, d.total.concat(d.priv).concat(d.grp));

    var yMax = Math.max(1, Math.ceil(max * 1.2));

    var opt = baseOption();

    opt.animation = false;

    opt.tooltip.trigger = 'axis';

    opt.tooltip.appendToBody = true;

    opt.tooltip.axisPointer = { type: 'line', lineStyle: { color: rule } };

    opt.grid = { left: 40, right: 18, top: 18, bottom: 28 };

    opt.xAxis = {

      type: 'category',

      data: d.dates,

      boundaryGap: false,

      axisLine: { lineStyle: { color: rule } },

      axisTick: { show: false },

      axisLabel: { color: muted, fontSize: 11 }

    };

    opt.yAxis = {

      type: 'value',

      min: 0,

      max: yMax,

      splitLine: { lineStyle: { color: rule, type: 'dashed' } },

      axisLabel: { color: muted, fontSize: 11 }

    };

    opt.series = [

      {

        name: '总消息', type: 'line', smooth: true, symbol: 'circle', symbolSize: 6,

        data: d.total, itemStyle: { color: accent }, lineStyle: { color: accent, width: 2 },

        areaStyle: { color: accent + '22' }

      },

      {

        name: '单聊', type: 'line', smooth: true, symbol: 'circle', symbolSize: 6,

        data: d.priv, itemStyle: { color: '#6c8eff' }, lineStyle: { color: '#6c8eff', width: 2 }

      },

      {

        name: '群聊', type: 'line', smooth: true, symbol: 'circle', symbolSize: 6,

        data: d.grp, itemStyle: { color: green }, lineStyle: { color: green, width: 2 }

      }

    ];

    chart.setOption(opt, true);

  }

  // ---------- 旧版首页：消息趋势 · 多机器人对比 ----------

  function renderTrendCompare(days) {

    if (!chart) return;

    var now = new Date();

    var dateKeys = [], dates = [];

    for (var i = days - 1; i >= 0; i--) {

      var d = new Date(now.getTime() - i * 86400000);

      var y = d.getFullYear();

      var mo = String(d.getMonth() + 1).padStart(2, '0');

      var da = String(d.getDate()).padStart(2, '0');

      dateKeys.push(y + '-' + mo + '-' + da);

      dates.push(mo + '-' + da);

    }

    // bot 列表以全局快照 per_bot 为准（与历史写入键一致），并用 allBoundBots 排序/取展示名

    var pb = (lastStats && lastStats.per_bot) || {};

    var keys = Object.keys(pb);

    var order = {};

    (allBoundBots || []).forEach(function (b, idx) {

      var k = (b.name_rt || b.name || b.appid || '').trim();

      if (k) order[k] = idx;

    });

    keys.sort(function (a, b) {

      var ia = order.hasOwnProperty(a) ? order[a] : 999;

      var ib = order.hasOwnProperty(b) ? order[b] : 999;

      if (ia !== ib) return ia - ib;

      return a.localeCompare(b, 'zh-CN');

    });

    var labelOf = {};

    (allBoundBots || []).forEach(function (b) {

      var k = (b.name_rt || b.name || b.appid || '').trim();

      if (k) labelOf[k] = k;

    });

    Object.keys(botRegistry || {}).forEach(function (n) { if (n && !labelOf[n]) labelOf[n] = n; });

    var series = keys.map(function (bk, idx) {

      var h = loadHistory(LS_KEY + '#' + bk);

      var data = dateKeys.map(function (dk) {

        var rec = h[dk];

        return rec ? (rec.total || 0) : 0;

      });

      var color = BOT_PALETTE[idx % BOT_PALETTE.length];

      return {

        name: labelOf[bk] || bk, type: 'line', smooth: true, symbol: 'circle', symbolSize: 5,

        data: data, itemStyle: { color: color }, lineStyle: { color: color, width: 2 },

        areaStyle: { color: color + '14' }

      };

    });

    var maxV = 1;

    series.forEach(function (s) { s.data.forEach(function (v) { if (v > maxV) maxV = v; }); });

    var opt = baseOption();

    opt.animation = false;

    opt.tooltip = { trigger: 'axis', appendToBody: true, axisPointer: { type: 'line', lineStyle: { color: rule } } };

    opt.legend = {

      data: keys.map(function (bk) { return labelOf[bk] || bk; }),

      top: 2, type: 'scroll', textStyle: { color: muted, fontSize: 11 }, icon: 'roundRect'

    };

    opt.grid = { left: 40, right: 18, top: 36, bottom: 28 };

    opt.xAxis = {

      type: 'category', data: dates, boundaryGap: false,

      axisLine: { lineStyle: { color: rule } }, axisTick: { show: false },

      axisLabel: { color: muted, fontSize: 11 }

    };

    opt.yAxis = {

      type: 'value', min: 0, max: Math.max(1, Math.ceil(maxV * 1.2)),

      splitLine: { lineStyle: { color: rule, type: 'dashed' } },

      axisLabel: { color: muted, fontSize: 11 }

    };

    opt.series = series;

    chart.setOption(opt, true);

  }

  // ---------- 旧版首页：活跃数据 ----------

  function getActiveSeries(days, key) {

    var h = loadHistory(key);

    var dates = [], users = [], groups = [];

    var now = new Date();

    for (var i = days - 1; i >= 0; i--) {

      var d = new Date(now.getTime() - i * 86400000);

      var k = d.getFullYear() + '-' +

        String(d.getMonth() + 1).padStart(2, '0') + '-' +

        String(d.getDate()).padStart(2, '0');

      var label = String(d.getMonth() + 1).padStart(2, '0') + '-' +

        String(d.getDate()).padStart(2, '0');

      dates.push(label);

      var rec = h[k] || { active_users: 0, active_groups: 0 };

      if (i === 0 && !h[k]) {

        var s = liveSnapshot();

        rec = { active_users: s.active_users_today || 0, active_groups: s.active_groups_today || 0 };

      }

      users.push(rec.active_users || 0);

      groups.push(rec.active_groups || 0);

    }

    return { dates: dates, users: users, groups: groups };

  }

  function renderActiveChart(days) {

    if (!activeChart) return;

    var d = getActiveSeries(days, dashHistoryKey());

    var max = Math.max(1, d.users.concat(d.groups));

    var yMax = Math.max(1, Math.ceil(max * 1.2));

    var opt = baseOption();

    opt.animation = false;

    opt.tooltip.trigger = 'axis';

    opt.tooltip.appendToBody = true;

    opt.tooltip.formatter = function (params) {

      var html = '<div style="font-weight:600;margin-bottom:4px;">' + escapeHtml(params[0].axisValue) + '</div>';

      params.forEach(function (p) {

        html += '<div style="display:flex;align-items:center;gap:6px;margin:2px 0;">' +

          '<span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:' + p.color + ';"></span>' +

          '<span style="flex:1;">' + escapeHtml(p.seriesName) + '</span>' +

          '<span style="font-weight:600;">' + p.value + '</span>' +

          '</div>';

      });

      return html;

    };

    opt.tooltip.axisPointer = { type: 'line', lineStyle: { color: rule } };

    opt.grid = { left: 40, right: 18, top: 18, bottom: 28 };

    opt.xAxis = {

      type: 'category',

      data: d.dates,

      boundaryGap: false,

      axisLine: { lineStyle: { color: rule } },

      axisTick: { show: false },

      axisLabel: { color: muted, fontSize: 11 }

    };

    opt.yAxis = {

      type: 'value',

      min: 0,

      max: yMax,

      splitLine: { lineStyle: { color: rule, type: 'dashed' } },

      axisLabel: { color: muted, fontSize: 11 }

    };

    opt.series = [

      {

        name: '活跃成员', type: 'line', smooth: true, symbol: 'circle', symbolSize: 6,

        data: d.users, itemStyle: { color: accent }, lineStyle: { color: accent, width: 2 }

      },

      {

        name: '活跃群聊', type: 'line', smooth: true, symbol: 'circle', symbolSize: 6,

        data: d.groups, itemStyle: { color: green }, lineStyle: { color: green, width: 2 }

      }

    ];

    activeChart.setOption(opt, true);

  }

  function renderDashboardCharts() {

    renderChart(trendRange());

    renderActiveChart(activeRange());

  }

  // ---------- 新版数据中心 · 数据总览 ----------

  function periodAgg(period) {

    var days = periodDays(period);

    var h = loadHistory();

    var total = 0, priv = 0, grp = 0;

    var keys = Object.keys(h).sort();

    var cutoff = days > 0 ? Date.now() - days * 86400000 : 0;

    keys.forEach(function (k) {

      var t = Date.parse(k + 'T00:00:00');

      if (days > 0 && (!isFinite(t) || t < cutoff)) return;

      var rec = h[k] || {};

      total += rec.total || 0;

      priv += rec.private || 0;

      grp += rec.group || 0;

    });

    // 若历史里还没有今天的数据，用实时快照兜底，避免页面初次打开时所有环形图都是 0

    if (!h[todayKey()]) {

      var snap = todayRecFromSnapshot();

      total += snap.total;

      priv += snap.private;

      grp += snap.group;

    }

    return { total: total, private: priv, group: grp };

  }

  function dataRenderTrend(days) {

    if (!dataChartTrend) return;

    var d = getSeries(days);

    var max = Math.max(1, d.total.concat(d.priv).concat(d.grp));

    var yMax = Math.max(1, Math.ceil(max * 1.2));

    var opt = baseOption();

    opt.animation = false;

    opt.tooltip.trigger = 'axis';

    opt.tooltip.appendToBody = true;

    opt.tooltip.axisPointer = { type: 'line', lineStyle: { color: rule } };

    opt.grid = { left: 40, right: 18, top: 18, bottom: 28 };

    opt.xAxis = {

      type: 'category',

      data: d.dates,

      boundaryGap: false,

      axisLine: { lineStyle: { color: rule } },

      axisTick: { show: false },

      axisLabel: { color: muted, fontSize: 11 }

    };

    opt.yAxis = {

      type: 'value',

      min: 0,

      max: yMax,

      splitLine: { lineStyle: { color: rule, type: 'dashed' } },

      axisLabel: { color: muted, fontSize: 11 }

    };

    opt.series = [

      {

        name: '总消息', type: 'line', smooth: true, symbol: 'circle', symbolSize: 6,

        data: d.total, itemStyle: { color: accent }, lineStyle: { color: accent, width: 2 },

        areaStyle: { color: accent + '22' }

      },

      {

        name: '单聊', type: 'line', smooth: true, symbol: 'circle', symbolSize: 6,

        data: d.priv, itemStyle: { color: '#6c8eff' }, lineStyle: { color: '#6c8eff', width: 2 }

      },

      {

        name: '群聊', type: 'line', smooth: true, symbol: 'circle', symbolSize: 6,

        data: d.grp, itemStyle: { color: green }, lineStyle: { color: green, width: 2 }

      }

    ];

    dataChartTrend.setOption(opt, true);

  }

  function dataRenderDir(period) {

    if (!dataChartDir) return;

    var agg = periodAgg(period);

    var hasData = (agg.total || 0) > 0;

    var data = hasData

      ? [{ value: agg.group || 0, name: '收到' }, { value: agg.private || 0, name: '发出' }]

      : [{ value: 0, name: '收到' }, { value: 0, name: '发出' }];

    var opt = baseOption();

    opt.animation = false;

    opt.tooltip.trigger = 'item';

    opt.legend = { bottom: 0, itemWidth: 10, itemHeight: 10, textStyle: { color: muted, fontSize: 11 } };

    opt.title = {

      text: hasData ? '' : '暂无数据',

      left: 'center', top: 'center',

      textStyle: { color: muted, fontSize: 13, fontWeight: 500 }

    };

    opt.series = [{

      name: '消息方向', type: 'pie', radius: ['45%', '70%'], center: ['50%', '45%'],

      avoidLabelOverlap: false,

      label: { show: false },

      emphasis: { label: { show: true, fontSize: 13, fontWeight: 600, color: ink } },

      labelLine: { show: false },

      data: data,

      color: [green, accent]

    }];

    dataChartDir.setOption(opt, true);

  }

  function dataRenderType(period) {

    if (!dataChartType) return;

    var agg = periodAgg(period);

    var hasData = (agg.total || 0) > 0;

    var textVal = agg.private || 0;

    var imgVal = Math.max(0, (agg.total || 0) - textVal);

    var data = hasData

      ? [{ value: textVal, name: '文本' }, { value: imgVal, name: '图片/表情' }]

      : [{ value: 0, name: '文本' }, { value: 0, name: '图片/表情' }];

    var opt = baseOption();

    opt.animation = false;

    opt.tooltip.trigger = 'item';

    opt.legend = { bottom: 0, itemWidth: 10, itemHeight: 10, textStyle: { color: muted, fontSize: 11 } };

    opt.title = {

      text: hasData ? '' : '暂无数据',

      left: 'center', top: 'center',

      textStyle: { color: muted, fontSize: 13, fontWeight: 500 }

    };

    opt.series = [{

      name: '消息类型', type: 'pie', radius: ['45%', '70%'], center: ['50%', '45%'],

      avoidLabelOverlap: false,

      label: { show: false },

      emphasis: { label: { show: true, fontSize: 13, fontWeight: 600, color: ink } },

      labelLine: { show: false },

      data: data,

      color: [accent, orange]

    }];

    dataChartType.setOption(opt, true);

  }

  function dataRenderRank(s) {

    if (!dataChartRank) return;

    var bots = (s && s.bots) || [];

    // 多实例：按今日消息数降序排列，每条机器人一根横向柱

    var rows = bots.slice().sort(function (a, b) {

      return (b.messages_today || 0) - (a.messages_today || 0);

    });

    var maxVal = Math.max(1, rows.reduce(function (m, b) { return Math.max(m, b.messages_today || 0); }, 0));

    var yMax = Math.max(1, Math.ceil(maxVal * 1.15));

    var names = rows.map(function (b, i) {

      return (b.name_rt || _sanitizeName(b.name, b.appid) || b.appid_masked || b.appid || ('机器人' + (i + 1)));

    });

    var opt = baseOption();

    opt.animation = false;

    opt.tooltip.trigger = 'axis';

    opt.tooltip.axisPointer = { type: 'shadow' };

    opt.grid = { left: 14, right: 64, top: 10, bottom: 10, containLabel: true };

    opt.xAxis = { type: 'value', min: 0, max: yMax, splitLine: { show: false }, axisLabel: { show: false } };

    opt.yAxis = {

      type: 'category', data: names, axisLine: { show: false }, axisTick: { show: false },

      axisLabel: { color: ink, fontSize: 12 }

    };

    opt.title = {

      text: rows.length ? '' : '暂无数据',

      left: 'center', top: 'center',

      textStyle: { color: muted, fontSize: 13, fontWeight: 500 }

    };

    opt.series = [

      {

        name: '今日消息', type: 'bar', barMaxWidth: 22,

        data: rows.map(function (b, i) {

          return {

            value: b.messages_today || 0,

            itemStyle: { borderRadius: [0, 6, 6, 0], color: BOT_PALETTE[i % BOT_PALETTE.length] }

          };

        }),

        label: {

          show: true, position: 'right', offset: [6, 0],

          color: muted, fontSize: 12, formatter: '{c} 条'

        }

      }

    ];

    dataChartRank.setOption(opt, true);

  }

  function dataRenderPeak(period) {

    if (!dataChartPeak) return;

    // 今日小时级聚合：数据源 /api/stats.hourly_messages.total（_snapshot_today_hourly 输出）

    var hours = ['00','01','02','03','04','05','06','07','08','09','10','11','12','13','14','15','16','17','18','19','20','21','22','23'];

    var opt = baseOption();

    opt.animation = false;

    opt.tooltip = { trigger: 'axis', axisPointer: { type: 'shadow' }, appendToBody: true };

    opt.grid = { left: 40, right: 14, top: 26, bottom: 28 };

    var hourly = (lastStats && lastStats.hourly_messages && Array.isArray(lastStats.hourly_messages.total))

      ? lastStats.hourly_messages.total : null;

    var hasData = !!hourly && hourly.some(function (v) { return (v | 0) > 0; });

    if (!hasData) {

      opt.title = {

        text: '暂无小时级聚合数据',

        left: 'center', top: 'center',

        textStyle: { color: '#cbd5f5', fontSize: 14, fontWeight: 600 }

      };

    } else {

      opt.title = { text: '', show: false };

      opt.tooltip.formatter = function (params) {

        var p = params && params[0];

        if (!p) return '';

        var hr = p.name;

        var hh = parseInt(hr, 10) || 0;

        var next = (hh + 1) % 24;

        var suffix = (next < 10 ? '0' : '') + next;

        return (hh < 10 ? '0' : '') + hh + ':00 — ' + suffix + ':00' +

          '<br/>总消息 <b style="color:#ff9f43">' + p.value + '</b> 条';

      };

    }

    var maxV = hasData ? Math.max.apply(null, hourly) : 0;

    var yMax = Math.max(1, Math.ceil(maxV * 1.15));

    opt.xAxis = {

      type: 'category', data: hours,

      axisLine: { lineStyle: { color: rule } }, axisTick: { show: false },

      axisLabel: { color: muted, fontSize: 10, interval: 1 }

    };

    opt.yAxis = {

      type: 'value', min: 0, max: yMax,

      splitLine: { lineStyle: { color: rule, type: 'dashed' } },

      axisLabel: { color: muted, fontSize: 10 }

    };

    opt.series = [{

      name: '消息数', type: 'bar', barWidth: '60%',

      data: hasData ? hours.map(function (_, i) {

        var v = hourly[i] | 0;

        var isPeak = (v > 0 && v === maxV);

        return {

          value: v,

          itemStyle: {

            borderRadius: [4, 4, 0, 0],

            color: isPeak ? '#ff9f43' : accent

          }

        };

      }) : hours.map(function () { return 0; }),

      label: {

        show: hasData, position: 'top',

        color: muted, fontSize: 10,

        formatter: function (p) { return p.value > 0 ? p.value : ''; }

      }

    }];

    dataChartPeak.setOption(opt, true);

  }

  function renderBotMatrix(bots) {

    var body = document.getElementById('data-bot-matrix-body');

    if (!body) return;

    if (!Array.isArray(bots) || bots.length === 0) {

      body.innerHTML = '<tr class="empty-row"><td colspan="9">暂无机器人实例，先在「机器人管理」绑定并启用。</td></tr>';

      return;

    }

    var html = '';

    bots.forEach(function (b, i) {

      var nm = b.name_rt || _sanitizeName(b.name, b.appid) || b.appid_masked || b.appid || '机器人';

      var key = (b.name_rt || b.name || b.appid || '').trim();

      var avatar = b.avatar

        ? '<img class="matrix-avatar" src="' + escapeHtml(b.avatar) + '" alt="" onerror="this.style.display=\'none\'">' 

        : '<span class="matrix-avatar matrix-avatar-empty">🤖</span>';

      var dotCls = botDotClass(b);

      var statusTxt = b.connected ? '在线' : (b.enabled === false ? '已停用' : '离线');

      html +=

        '<tr data-bot-name="' + escapeHtml(key) + '">' +

          '<td class="matrix-bot">' + avatar +

            '<span class="matrix-bot-name">' + escapeHtml(nm) + '</span>' +

            '<span class="matrix-bot-appid">' + escapeHtml(b.appid_masked || b.appid || '') + '</span>' +

          '</td>' +

          '<td><span class="bot-dot ' + dotCls + '"></span>' + statusTxt + '</td>' +

          '<td class="num-col">' + (b.messages_today || 0) + '</td>' +

          '<td class="num-col">' + (b.private_messages_today || 0) + '</td>' +

          '<td class="num-col">' + (b.group_messages_today || 0) + '</td>' +

          '<td class="num-col">' + (b.groups_total || 0) + '</td>' +

          '<td class="num-col">' + (b.members_total || 0) + '</td>' +

          '<td class="num-col">' + (b.checkins_today || 0) + '</td>' +

          '<td class="matrix-last">' + escapeHtml(b.last_active_at || '—') + '</td>' +

        '</tr>';

    });

    body.innerHTML = html;

  }

  function renderDataOverviewCharts(period) {

    ensureDataCharts();

    dataRenderTrend(dataTrendRange());

    dataRenderDir(period);

    dataRenderType(period);

    dataRenderPeak(period);

  }

  // ============================================================

  // 通用工具

  // ============================================================

  function escapeHtml(s) {

    return String(s).replace(/[&<>"']/g, function (c) {

      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];

    });

  }

  function truncate(s, n) {

    s = String(s || '');

    if (s.length <= n) return s;

    return s.slice(0, n) + '…';

  }

  function nowStamp() {

    var d = new Date();

    return d.getFullYear() + '/' +

      String(d.getMonth() + 1).padStart(2, '0') + '/' +

      String(d.getDate()).padStart(2, '0') + ' ' +

      String(d.getHours()).padStart(2, '0') + ':' +

      String(d.getMinutes()).padStart(2, '0') + ':' +

      String(d.getSeconds()).padStart(2, '0');

  }

  // ============================================================

  // 公告（支持按群聊 / 个人 批量定向发布）

  // ============================================================

  // Chrome 自动填充时若页面有 @keyframes onAutoFillStart / onAutoFillCancel 会触发动画

  // 借此 animationstart 事件可靠识别自动填充并清空（避免 ai provider URL 历史污染公告内容）

  (function injectAutoFillKeyframes() {

    if (document.getElementById('__af_keyframes__')) return;

    var s = document.createElement('style');

    s.id = '__af_keyframes__';

    s.textContent =

      '@keyframes onAutoFillStart{from{}to{}}' +

      '@-webkit-keyframes onAutoFillStart{from{}to{}}' +

      '@keyframes onAutoFillCancel{from{}to{}}' +

      '@-webkit-keyframes onAutoFillCancel{from{}to{}}';

    document.head.appendChild(s);

  })();

  function renderAnnouncements(items, listId, timeId) {

    var box = document.getElementById(listId || 'ann-list');

    var timeEl = document.getElementById(timeId || 'ann-time');

    if (!box) return;

    if (!items || !items.length) {

      box.innerHTML = '<div class="announce"><span class="tag">通知</span>' +

        '<span class="body">欢迎使用小流萤 bot 管理后台</span>' +

        '<span class="time" id="' + (timeId || 'ann-time') + '">' + nowStamp() + '</span></div>';

      return;

    }

    box.innerHTML = items.map(function (it) {

      var scope = '';

      if (it.scope === 'groups') scope = ' · 群聊';

      else if (it.scope === 'persons') scope = ' · 好友';

      else if (it.scope === 'custom') scope = ' · 自定义(' + (it.target_count || 0) + ')';

      else if (it.scope === 'all') scope = ' · 全部';

      return '<div class="announce">' +

        '<span class="tag">' + escapeHtml(it.tag || '通知') + '</span>' +

        '<span class="body">' + escapeHtml(it.body || '') + '</span>' +

        '<span class="time">' + escapeHtml(it.ts || '') + (scope ? escapeHtml(scope) : '') + '</span>' +

        '</div>';

    }).join('');

  }

  function loadAnnouncements(listId, timeId) {

    fetch(API_BASE + '/api/announcement')

      .then(function (r) { return r.json(); })

      .then(function (j) { renderAnnouncements(j && j.items, listId, timeId); })

      .catch(function () { renderAnnouncements([], listId, timeId); });

  }

  // 已知群聊/个人缓存（全局，两处公告面板共享，避免重复请求）

  var knownContacts = { groups: [], persons: [] };

  var knownContactsLoaded = false;

  function loadKnownContacts() {

    return fetch(API_BASE + '/api/known-contacts', { cache: 'no-store' })

      .then(function (r) { return r.json(); })

      .then(function (j) {

        knownContacts = {

          groups: (j && j.groups) || [],

          persons: (j && j.persons) || [],

        };

        knownContactsLoaded = true;

        return knownContacts;

      })

      .catch(function () { return knownContacts; });

  }

  // 单个公告面板控制器

  function AnnounceBoard(prefix) {

    this.prefix = prefix;

    this.scope = 'all';          // all | groups | persons（全部 / 群聊 / 好友）

    this.selectedGroups = {};    // 群聊模式下的勾选（chat_id -> true）

    this.selectedPersons = {};   // 好友模式下的勾选

    this.contactsRendered = false;

  }

  AnnounceBoard.prototype.el = function (id) {

    return document.getElementById(this.prefix + '-' + id);

  };

  // 当前 scope 对应的受众列表 / 勾选桶

  AnnounceBoard.prototype.currentBucket = function () {

    if (this.scope === 'groups') return { list: knownContacts.groups || [], bucket: this.selectedGroups, kind: '群聊' };

    if (this.scope === 'persons') return { list: knownContacts.persons || [], bucket: this.selectedPersons, kind: '好友' };

    return { list: [], bucket: {}, kind: '' };

  };

  AnnounceBoard.prototype.renderContacts = function () {

    var listEl = this.el('target-list');

    var emptyEl = this.el('target-empty');

    var opsEl = this.el('select-ops');

    if (!listEl) return;

    var cur = this.currentBucket();

    var showList = cur.list.length > 0;

    if (opsEl) opsEl.classList.toggle('visible', this.scope !== 'all');

    if (!showList) {

      listEl.classList.remove('visible');

      if (emptyEl) {

        if (this.scope === 'all') {

          emptyEl.style.display = 'none';

        } else {

          emptyEl.textContent = '暂无已知' + cur.kind + '，先在监控中接收过消息才会显示';

          emptyEl.style.display = 'block';

        }

      }

      return;

    }

    if (emptyEl) emptyEl.style.display = 'none';

    listEl.classList.add('visible');

    var bucket = cur.bucket;

    listEl.innerHTML = cur.list.map(function (c) {

      var isGrp = c.chat_id.indexOf('g:') === 0;

      var label = c.name || c.openid;

      var cls = label && label === c.openid ? ' nm empty' : ' nm';

      return '<label class="ann-chk">' +

        '<input type="checkbox" data-chat="' + escapeHtml(c.chat_id) + '"' +

        (bucket[c.chat_id] ? ' checked' : '') + ' />' +

        '<span class="' + cls + '">' + escapeHtml(label) + '</span>' +

        '<span class="badge">' + (isGrp ? '群' : '人') + '</span>' +

        '</label>';

    }).join('');

    var self = this;

    Array.prototype.forEach.call(listEl.querySelectorAll('input[type=checkbox]'), function (cb) {

      cb.addEventListener('change', function () {

        var cid = cb.getAttribute('data-chat');

        if (cb.checked) bucket[cid] = true;

        else delete bucket[cid];

      });

    });

    this.contactsRendered = true;

  };

  AnnounceBoard.prototype.setScope = function (scope) {

    this.scope = scope;

    var sel = this.el('scope');

    if (sel && sel.value !== scope) sel.value = scope;

    // 切换到群聊/好友时，若该桶为空则默认全选，方便「单选/全选」直接可用

    if (scope === 'groups' && !Object.keys(this.selectedGroups).length) {

      (knownContacts.groups || []).forEach(function (c) {

        this.selectedGroups[c.chat_id] = true;

      }.bind(this));

    }

    if (scope === 'persons' && !Object.keys(this.selectedPersons).length) {

      (knownContacts.persons || []).forEach(function (c) {

        this.selectedPersons[c.chat_id] = true;

      }.bind(this));

    }

    this.renderContacts();

  };

  // 根据当前 scope 计算要推送的受众 chat_id 列表

  AnnounceBoard.prototype.getTargets = function () {

    if (this.scope === 'groups') {

      return Object.keys(this.selectedGroups).filter(function (k) { return this.selectedGroups[k]; }.bind(this));

    }

    if (this.scope === 'persons') {

      return Object.keys(this.selectedPersons).filter(function (k) { return this.selectedPersons[k]; }.bind(this));

    }

    // all：全部已知群聊 + 好友

    return (knownContacts.groups || []).concat(knownContacts.persons || []).map(function (c) { return c.chat_id; });

  };

  AnnounceBoard.prototype.selectAll = function () {

    if (this.scope === 'groups') {

      this.selectedGroups = {};

      (knownContacts.groups || []).forEach(function (c) { this.selectedGroups[c.chat_id] = true; }.bind(this));

    } else if (this.scope === 'persons') {

      this.selectedPersons = {};

      (knownContacts.persons || []).forEach(function (c) { this.selectedPersons[c.chat_id] = true; }.bind(this));

    }

    this.renderContacts();

  };

  AnnounceBoard.prototype.clearSelection = function () {

    if (this.scope === 'groups') {

      this.selectedGroups = {};

    } else if (this.scope === 'persons') {

      this.selectedPersons = {};

    }

    this.renderContacts();

  };

  AnnounceBoard.prototype.showWarn = function (msg) {

    var wEl = this.el('warn');

    if (!wEl) return;

    wEl.textContent = msg || '';

    wEl.style.display = 'block';

  };

  AnnounceBoard.prototype.hideWarn = function () {

    var wEl = this.el('warn');

    if (wEl) wEl.style.display = 'none';

  };

  AnnounceBoard.prototype.showResult = function (push) {

    var rEl = this.el('result');

    if (!rEl) return;

    if (!push) { rEl.style.display = 'none'; return; }

    var html = '已发布到 ' + push.total + ' 个对象：<span class="ok">成功 ' + push.ok + '</span>';

    if (push.failed > 0) {

      html += '，<span class="bad">失败 ' + push.failed + '</span>';

    }

    rEl.innerHTML = html;

    rEl.style.display = 'block';

  };

  AnnounceBoard.prototype.post = function (body) {

    var self = this;

    var targets = this.getTargets();

    var scope = this.scope;

    var payload = { tag: '通知', body: body, scope: scope, target_count: targets.length };

    if (targets.length) payload.targets = targets;

    return fetch(API_BASE + '/api/announcement', {

      method: 'POST',

      headers: { 'Content-Type': 'application/json' },

      body: JSON.stringify(payload)

    }).then(function (r) { return r.json(); }).then(function (j) {

      loadAnnouncements('ann-list', 'ann-time');

      loadAnnouncements('data-ann-list', 'data-ann-time');

      self.showResult(j && j.push);

      return j;

    });

  };

  var announceBoards = {};

  function setupAnnounceBoard(prefix) {

    var board = new AnnounceBoard(prefix);

    announceBoards[prefix] = board;

    // scope 下拉列表

    var scopeSel = board.el('scope');

    if (scopeSel) {

      scopeSel.addEventListener('change', function () {

        board.setScope(scopeSel.value);

      });

    }

    // 全选 / 清空

    var selAll = board.el('select-all');

    var selClear = board.el('select-clear');

    if (selAll) selAll.addEventListener('click', function () { board.selectAll(); });

    if (selClear) selClear.addEventListener('click', function () { board.clearSelection(); });

    // 发布

    var btn = board.el('submit');

    var input = board.el('input');

    if (btn && input) {

      // ===== 防止浏览器自动填充历史 URL（如 ai provider 的 moonshot URL）污染公告内容 =====

      try {

        input.setAttribute('autocomplete', 'off');

        input.setAttribute('type', 'text');

        input.setAttribute('name', 'announcement-body-' + prefix);

        input.setAttribute('data-form-type', 'other');

        input.setAttribute('data-lpignore', 'true');

        input.setAttribute('data-1p-ignore', 'true');

        input.setAttribute('data-bwignore', 'true');   // Bitwarden

        input.setAttribute('data-b24ignore', 'true');  // Bitwarden legacy

        input.setAttribute('data-1password-ignore', 'true'); // 1Password

        // 绑定到自动填充关键帧动画，便于 animationstart 事件捕获

        input.style.setProperty('animation-name', 'onAutoFillStart, onAutoFillCancel', 'important');

        input.style.setProperty('-webkit-animation-name', 'onAutoFillStart, onAutoFillCancel', 'important');

        input.style.setProperty('animation-duration', '0.001s', 'important');

        input.style.setProperty('-webkit-animation-duration', '0.001s', 'important');

      } catch (e) {}

      function isAutoFillVal(v) {

        if (!v) return false;

        var t = String(v).trim();

        return /^https?:\/\/[^\s]+/i.test(t);

      }

      function clearAutoFill() {

        try { if (isAutoFillVal(input.value)) input.value = ''; } catch (e) {}

      }

      // 1) Chrome 自动填充触发动画时清空（部分场景有效）

      input.addEventListener('animationstart', function (e) {

        if (e && (e.animationName === 'onAutoFillStart' || e.animationName === 'onAutoFillCancel' ||

                  e.animationName === '-webkit-onAutoFillStart' || e.animationName === '-webkit-onAutoFillCancel')) {

          clearAutoFill();

        }

      }, true);

      // 2) input 事件兜底（用户正常输入不会以 http:// 开头）

      input.addEventListener('input', clearAutoFill);

      // 3) 焦点进入时清空

      input.addEventListener('focus', clearAutoFill);

      // 4) 真正的兜底：requestAnimationFrame 高频轮询，10 秒内只要发现 value 被自动填入 URL 立即清空

      //    这能可靠捕获所有基于"异步修改 DOM property"的自动填充（Chrome 的某些 autofill 路径不触发任何事件）

      //    注意：不要把 'input' 加进 markTouched——Chrome 自动填充也会触发 input 事件，会让 userTouched 被误设为 true 而立刻停掉 RAF

      var userTouched = false;

      function markTouched() { userTouched = true; }

      input.addEventListener('keydown', markTouched, true);

      input.addEventListener('beforeinput', markTouched, true);

      input.addEventListener('compositionstart', markTouched, true);

      input.addEventListener('paste', markTouched, true);

      input.addEventListener('drop', markTouched, true);

      // 启动时立即清空（如果初始就是 URL 形态）

      clearAutoFill();

      var rafStart = Date.now();

      function rafLoop() {

        if (userTouched) return; // 用户开始主动输入，停止干扰

        var now = Date.now();

        // 每帧直接检测当前值，userTouched=false（用户没在输入）且值是 URL → 立即清空

        if (isAutoFillVal(input.value)) {

          try { input.value = ''; } catch (e) {}

        }

        if (now - rafStart < 10000) {

          requestAnimationFrame(rafLoop);

        }

      }

      requestAnimationFrame(rafLoop);

      btn.addEventListener('click', function () {

        var v = (input.value || '').trim();

        if (!v) return;

        var targets = board.getTargets();

        if (!targets.length) {

          if (board.scope === 'groups') board.showWarn('请至少选择一个群聊');

          else if (board.scope === 'persons') board.showWarn('请至少选择一个好友');

          else board.showWarn('暂无可发送的群聊或好友');

          return;

        }

        board.hideWarn();

        btn.disabled = true; input.disabled = true;

        board.post(v).finally(function () {

          input.value = ''; btn.disabled = false; input.disabled = false; input.focus();

        });

      });

      input.addEventListener('keydown', function (e) {

        if (e.key === 'Enter') btn.click();

      });

    }

    // 首次渲染（确保 knownContacts 已加载），默认「全部」直接推送

    loadKnownContacts().then(function () { board.setScope('all'); });

    return board;

  }

  setupAnnounceBoard('ann');

  setupAnnounceBoard('data-ann');

  // 后台定时刷新已知受众（新群/新人出现后约 15s 同步），并重渲染两个面板

  setInterval(function () {

    loadKnownContacts().then(function () {

      Object.keys(announceBoards).forEach(function (p) {

        announceBoards[p].renderContacts();

      });

    });

  }, 15000);

  // ============================================================

  // 主循环

  // ============================================================

  var currentPeriod = 'month';

  function tick() {

    // 主题感知：每轮先刷新 CSS 变量，确保 dark/light 切换后图表文字颜色立刻跟随

    try { _refreshTheme(); } catch (e) {}

    // 数据总览页：KPI 卡片按 dashBotFilter 过滤（空=全局聚合），矩阵始终显示全部实例对比

    refetchDataOverview();

    // 仪表盘 KPI + 图表：按仪表盘所选机器人（空=全局聚合）

    fetchStats(function (d) {

      applyKpi(d);

      if (d) recordToday(d);

      renderDashboardCharts();

    }, dashBotFilter);

  }

  function bindRange(containerId, renderFn, defaultRange) {

    var currentRange = function () { return defaultRange; };

    var container = document.getElementById(containerId);

    if (!container) return function () { return defaultRange; };

    container.querySelectorAll('button').forEach(function (b) {

      b.addEventListener('click', function () {

        container.querySelectorAll('button').forEach(function (x) { x.classList.remove('active'); });

        b.classList.add('active');

        currentRange = function () { return parseInt(b.getAttribute('data-range'), 10) || defaultRange; };

        renderFn(currentRange());

      });

    });

    return function () { return currentRange(); };

  }

  var trendRange = bindRange('trend-range', renderChart, 7);

  var activeRange = bindRange('active-range', renderActiveChart, 7);

  var dataTrendRange = bindRange('data-trend-range', dataRenderTrend, 7);

  var dataCurrentPeriod = 'month';

  function bindPeriodTabs() {

    var container = document.getElementById('data-period-tabs');

    if (!container) return;

    container.querySelectorAll('button').forEach(function (b) {

      b.addEventListener('click', function () {

        container.querySelectorAll('button').forEach(function (x) { x.classList.remove('active'); });

        b.classList.add('active');

        dataCurrentPeriod = b.getAttribute('data-period') || 'month';

        renderDataOverviewCharts(dataCurrentPeriod);

      });

    });

  }

  bindPeriodTabs();

  function bindRefresh() {

    var btn = document.getElementById('data-refresh');

    if (!btn) return;

    btn.addEventListener('click', function () {

      btn.classList.add('spin');

      btn.disabled = true;

      tick();

      setTimeout(function () { btn.classList.remove('spin'); btn.disabled = false; }, 500);

    });

  }

  bindRefresh();

  window.addEventListener('resize', function () {

    [chart, activeChart, dataChartTrend, dataChartDir, dataChartType, dataChartRank, dataChartPeak].forEach(function (c) {

      try { if (c) c.resize(); } catch (e) {}

    });

  });

  // 深色模式切换时重绘所有图表

  var dashObserver = new MutationObserver(function (mutations) {

    mutations.forEach(function (m) {

      if (m.type === 'attributes' && m.attributeName === 'class') {

        style = getComputedStyle(document.documentElement);

        accent = style.getPropertyValue('--accent').trim() || '#3b6ef5';

        accent2 = style.getPropertyValue('--accent-2').trim() || '#00b894';

        ink = style.getPropertyValue('--ink').trim() || '#1f2240';

        muted = style.getPropertyValue('--muted').trim() || '#8b91b5';

        rule = style.getPropertyValue('--rule').trim() || '#ececf4';

        green = style.getPropertyValue('--green').trim() || '#26c281';

        warn = style.getPropertyValue('--warn').trim() || '#ff6b6b';

        bg2 = style.getPropertyValue('--bg2').trim() || '#ffffff';

        renderDashboardCharts();

        renderDataOverviewCharts(dataCurrentPeriod);

      }

    });

  });

  dashObserver.observe(document.body, { attributes: true });

  // ============================================================

  // 页面切换（侧边栏导航）

  // ============================================================

  var PAGE_TITLES = {

    dashboard: '仪表盘',

    robots: '机器人',

    'c2c-logs': '单聊消息记录',

    'c2c-monitor': '单聊实时监控',

    'c2c-list': '用户列表',

    'group-logs': '群聊消息记录',

    'group-monitor': '群聊实时监控',

    'members-list': '成员列表',

    profiles: '用户分析',

    'groups-list': '群列表',

    'group-join-approval': '入群审批策略',

    'feature-config': '功能配置',

    'qa-rules': '问答规则',

    'personalize': '个性设置',

    'ai-chat': 'AI 对话',

    'ai-models': '模型管理',

    'ai-sensitive': '敏感词',

    'ai-persona': '人格设置',

    'ai-knowledge': '知识库',

    'data-overview': '数据总览',

    'feature-data': '功能数据',

    'admin-settings': '管理员设置',

    'admin-commands': '系统指令',

    logs: '日志中心',

    scheduled: '定时任务',

    profile: '个人中心',

    'docs-overview': '机器人概览',

    'docs-install': '安装部署',

    'docs-modules': '功能模块',

    'docs-admin': '后台管理',

    'docs-trouble': '常见问题',

    'docs-changelog': '更新日志',

    feedback: '问题反馈',

    health: '运行健康',

    'runtime-settings': '运行设置',

    'plugin-config': '插件配置',

    'plugin-market': '插件市场',

  };

  var PAGE_PARENTS = {

    'c2c-logs': '单聊管理',

    'c2c-monitor': '单聊管理',

    'c2c-list': '单聊管理',

    'group-logs': '群聊管理',

    'group-monitor': '群聊管理',

    'members-list': '成员管理',

    profiles: '成员管理',

    'groups-list': '群管理',

    'group-join-approval': '群管理',

    'feature-config': '功能中心',

    'qa-rules': '功能中心',

    'plugin-config': '插件中心',

    'plugin-market': '插件中心',

    'ai-chat': 'AI 智能',

    'ai-models': 'AI 智能',

    'ai-sensitive': 'AI 智能',

    'ai-persona': 'AI 智能',

    'ai-knowledge': 'AI 智能',

    'data-overview': '数据中心',

    'feature-data': '数据中心',

    'admin-settings': '管理员',

    'admin-commands': '管理员',

    'docs-overview': '说明文档',

    'docs-install': '说明文档',

    'docs-modules': '说明文档',

    'docs-admin': '说明文档',

    'docs-trouble': '说明文档',

      'docs-changelog': '说明文档',

    };



  // ============================================================

  // 数据总览 · 机器人筛选下拉（修复：列表填充 + 切换联动 KPI）

  // 复用 dashBotFilter（仪表盘 .bot-selector 共享同一状态 + sessionStorage 持久化）

  // ============================================================

  var _dataBotSelectorInited = false;

  // 注入矩阵行高亮样式（主题感知：深色模式用更亮的蓝）

  (function injectMatrixRowHighlight() {

    if (document.getElementById('__matrix_row_highlight__')) return;

    var s = document.createElement('style');

    s.id = '__matrix_row_highlight__';

    s.textContent =

      '#data-bot-matrix-body tr.matrix-row-highlight {' +

      '  background: rgba(59, 110, 245, 0.10);' +

      '}' +

      'body.dark-mode #data-bot-matrix-body tr.matrix-row-highlight {' +

      '  background: rgba(91, 142, 255, 0.22);' +

      '}' +

      '#data-bot-matrix-body tr.matrix-row-highlight .matrix-bot-name {' +

      '  color: #2a55d6;' +

      '}' +

      'body.dark-mode #data-bot-matrix-body tr.matrix-row-highlight .matrix-bot-name {' +

      '  color: #adc6ff;' +

      '}';

    document.head.appendChild(s);

  })();

  function ensureDataOverviewBotSelector() {

    var sel = document.getElementById('data-bot-select');

    if (!sel) return;

    // 数据总览页可能先于机器人管理页打开 → allBoundBots 空时主动拉一次

    if (!allBoundBots || !allBoundBots.length) {

      fetch(API_BASE + '/api/bots', { cache: 'no-store' })

        .then(function (r) { return r.json(); })

        .then(function (j) {

          allBoundBots = (j && j.bots) || [];

          (allBoundBots || []).forEach(function (b) {

            var k = (b.name_rt || b.name || b.appid || '').trim();

            if (k && !botRegistry[k]) {

              botRegistry[k] = {

                appid: b.appid, name_rt: b.name_rt || b.name || k,

                name: b.name || '', avatar: b.avatar || '',

                connected: !!b.connected, enabled: b.enabled !== false,

                environment: b.environment || ''

              };

            }

          });

          fillDataOverviewBotSelector();

        })

        .catch(function () { fillDataOverviewBotSelector(); });

    } else {

      fillDataOverviewBotSelector();

    }

  }

  function fillDataOverviewBotSelector() {

    var sel = document.getElementById('data-bot-select');

    if (!sel) return;

    var cur = dashBotFilter || sel.value || '';

    fillBotSelect(sel, '全部机器人');

    // 校验 cur 仍在选项中（机器人解绑时回退到「全部机器人」）

    if (cur) {

      var ok = false;

      for (var i = 0; i < sel.options.length; i++) {

        if (sel.options[i].value === cur) { ok = true; break; }

      }

      if (!ok) {

        dashBotFilter = '';

        try { sessionStorage.setItem('dashBotFilter', ''); } catch (err) {}

        cur = '';

      }

    }

    if (cur) sel.value = cur;

    if (!_dataBotSelectorInited) {

      _dataBotSelectorInited = true;

      sel.addEventListener('change', function () {

        var val = sel.value || '';

        dashBotFilter = val;

        try { sessionStorage.setItem('dashBotFilter', val); } catch (err) {}

        // 同步：仪表盘 .bot-selector 视觉 + 老 dashboard KPI + 数据总览 KPI

        if (typeof updateDashBotSelectorTrigger === 'function') updateDashBotSelectorTrigger();

        syncDashSelectorMenuActive();

        if (typeof refreshDashboardForBot === 'function') refreshDashboardForBot();

        refetchDataOverview();

      });

    }

  }

  function syncDashSelectorMenuActive() {

    if (!dashBotSelectorMenu) return;

    Array.prototype.forEach.call(

      dashBotSelectorMenu.querySelectorAll('.bot-selector-item'),

      function (li) {

        li.classList.toggle('active', (li.getAttribute('data-value') || '') === dashBotFilter);

      }

    );

  }

  // 请求序号守卫：短时间内多次切换机器人时，过滤掉「旧请求」的迟回响应（避免慢响

  // 应覆盖新选择的状态）。无需 cancel token，旧 cb 直接 return 即可。

  var _dataOverviewReqId = 0;

  function refetchDataOverview() {

    var reqId = ++_dataOverviewReqId;

    fetchStats(function (g) {

      if (reqId !== _dataOverviewReqId) return;

      renderBotMatrix(g.bots || []);

      applySysStatus(g);

      try { dataRenderRank(g); } catch (e) {}

      var applyKpiAndHint = function (d) {

        if (reqId !== _dataOverviewReqId) return;

        if (d) applyDataOverviewKpi(d);

        try {

          var hint = document.getElementById('data-matrix-hint');

          if (hint) {

            hint.textContent = dashBotFilter

              ? '已按「' + dashBotFilter + '」筛选 KPI（下方为全部实例对比）'

              : '聚合全部实例（共 ' + ((g.bots || []).length) + ' 个）';

          }

          highlightMatrixRow();

        } catch (e) {}

      };

      if (dashBotFilter) {

        fetchStats(applyKpiAndHint, dashBotFilter);

      } else {

        applyKpiAndHint(g);

      }

      try { renderBots(); } catch (e) {}

      try { recordAllBotHistories(g); } catch (e) {}

    });

  }

  function highlightMatrixRow() {

    try {

      var body = document.getElementById('data-bot-matrix-body');

      if (!body) return;

      var rows = body.querySelectorAll('tr');

      rows.forEach(function (r) {

        var nm = r.getAttribute('data-bot-name') || '';

        if (dashBotFilter && nm === dashBotFilter) r.classList.add('matrix-row-highlight');

        else r.classList.remove('matrix-row-highlight');

      });

    } catch (e) {}

  }

  function switchPage(name) {

    if (clearAdminStatusTimer) { try { clearAdminStatusTimer(); } catch (e) {} }

    document.querySelectorAll('.page').forEach(function (p) {

      p.classList.toggle('active', p.id === 'page-' + name);

    });

    // 侧边栏主项高亮

    document.querySelectorAll('#side-nav .item').forEach(function (it) {

      it.classList.toggle('active', it.getAttribute('data-page') === name);

    });

    // 子菜单高亮 + 父菜单展开

    document.querySelectorAll('#side-nav .subitem').forEach(function (it) {

      var p = it.getAttribute('data-page');

      it.classList.toggle('active', p === name);

    });

    document.querySelectorAll('#side-nav .nav-group').forEach(function (g) {

      var hasActive = !!g.querySelector('.subitem.active');

      g.classList.toggle('open', hasActive);

    });

    // 面包屑

    var title = PAGE_TITLES[name] || name;

    var parent = PAGE_PARENTS[name];

    var bc = document.getElementById('breadcrumbs');

    if (bc) {

      if (parent) {

        bc.innerHTML = '<span>首页</span><span class="sep">/</span><span>' + parent + '</span><span class="sep">/</span><span class="current">' + title + '</span>';

      } else {

        bc.innerHTML = '<span>首页</span><span class="sep">/</span><span class="current">' + title + '</span>';

      }

    }

    // 切换到机器人页时立刻刷一次

    if (name === 'robots') {

      loadWsLogs();

      renderBots();

    }

    // 切换到日志中心页时加载运行日志

    if (name === 'logs') {

      loadRuntimeLogs();

    }

    // 切换到备份中心页时刷新备份列表

    if (name === 'backup-center') {

      if (window.__backupCenter) window.__backupCenter.load();

    }

    // 消息记录/监控已拆分为单聊·群聊 4 页，加载由各 createChatCenter 轮询负责

    // 切换到成员列表页时加载成员

    if (name === 'members-list') {

      if (loadMembersRef) loadMembersRef();

    }

    // 切换到用户分析页时由 profilesCenter 控制显示提示

    if (name === 'profiles') {

      if (loadProfilesRef) loadProfilesRef();

    }

    // 切换到群列表页时加载群数据

    if (name === 'groups-list') {

      if (loadGroupsRef) loadGroupsRef();

    }

    // 切换到入群申请列表页时加载审批数据
    if (name === 'group-join-requests') {

      if (loadJoinRequestsRef) loadJoinRequestsRef();

    }

    // 切换到入群审批策略页时加载策略
    if (name === 'group-join-approval') {

      if (loadJoinApprovalRef) loadJoinApprovalRef();

    }

    // 切换到用户列表页时加载 C2C 用户

    if (name === 'c2c-list') {

      if (loadUsersRef) loadUsersRef();

    }

    // 切换到功能配置页时加载配置

    if (name === 'feature-config') {

      if (loadFeatureConfigRef) loadFeatureConfigRef();

    }

    // 切换到问答规则页时加载规则

    if (name === 'qa-rules') {

      if (loadQaRulesRef) loadQaRulesRef();

    }

    if (name === 'plugin-config') {

      if (loadPluginConfigRef) loadPluginConfigRef();

    }

    if (name === 'plugin-market') {

      if (loadPluginMarketRef) loadPluginMarketRef();

    }

    // 切换到个性设置页时刷新控件

    if (name === 'personalize') {

      if (loadPersonalizeRef) loadPersonalizeRef();

    }

    // 切换到 AI 智能子页时加载对应数据

    if (name === 'ai-chat') {

      if (loadAiChatRef) loadAiChatRef();

    }

    if (name === 'ai-models') {

      if (loadAiModelsRef) loadAiModelsRef();

    }

    if (name === 'ai-sensitive') {

      if (loadAiSensitiveRef) loadAiSensitiveRef();

    }

    if (name === 'ai-persona') {

      if (loadAiPersonaRef) loadAiPersonaRef();

    }

    if (name === 'ai-knowledge') {

      if (loadAiKnowledgeRef) loadAiKnowledgeRef();

    }

    // 切换到定时任务页时加载任务

    if (name === 'scheduled') {

      if (loadScheduledRef) loadScheduledRef();

    }



    // 切换到数据中心 · 数据总览时重绘图表并加载公告

    if (name === 'data-overview') {

      // 延迟到下一帧，确保 .page.active 已应用、容器有真实尺寸后再 init

      requestAnimationFrame(function () {

        ensureDataCharts();

        ensureDataOverviewBotSelector();

        renderDataOverviewCharts(dataCurrentPeriod);

        try { dataRenderRank(lastStats); } catch (e) {}

        setTimeout(function () {

          if (dataChartTrend) dataChartTrend.resize();

          if (dataChartDir) dataChartDir.resize();

          if (dataChartType) dataChartType.resize();

          if (dataChartRank) dataChartRank.resize();

          if (dataChartPeak) dataChartPeak.resize();

        }, 0);

      });

      loadAnnouncements('data-ann-list', 'data-ann-time');

    }

    // 切换到功能数据看板时加载签到数据

    if (name === 'feature-data') {

      if (loadFeatureDataRef) loadFeatureDataRef();

    }

    // 切换到管理员设置页时加载名单

    if (name === 'admin-settings') {

      if (loadAdminSettingsRef) loadAdminSettingsRef();

    }

    // 切换到系统指令页时加载状态与按钮

    if (name === 'admin-commands') {

      if (loadAdminCommandsRef) loadAdminCommandsRef();

    }

    // 切换到运行健康页时立即拉取一次并恢复轮询

    if (name === 'health') {

      if (window.healthCenter) healthCenter.start();

    }

  }

    // 切换到运行设置页时加载

    if (name === 'runtime-settings') {

      if (window.runtimeSettingsCenter) runtimeSettingsCenter.start();

    }

  // 主菜单点击

  document.querySelectorAll('#side-nav .item[data-page]').forEach(function (it) {

    it.addEventListener('click', function () {

      var p = it.getAttribute('data-page');

      switchPage(p);

      try { history.replaceState(null, '', '#' + p); } catch (e) {}

    });

  });

  // 可展开父菜单点击

  document.querySelectorAll('#side-nav .item[data-group]').forEach(function (it) {

    it.addEventListener('click', function () {

      var group = it.getAttribute('data-group');

      var groupEl = document.getElementById('nav-group-' + group);

      if (groupEl) groupEl.classList.toggle('open');

    });

  });

  // 子菜单点击

  document.querySelectorAll('#side-nav .subitem[data-page]').forEach(function (it) {

    it.addEventListener('click', function () {

      var p = it.getAttribute('data-page');

      switchPage(p);

      try { history.replaceState(null, '', '#' + p); } catch (e) {}

    });

  });

  // 支持 URL hash 直接进入指定页

  function _applyHash() {

    var h = (location.hash || '').replace(/^#/, '');

    if (h && PAGE_TITLES[h]) switchPage(h);

  }

  window.addEventListener('hashchange', _applyHash);

  _applyHash();

  // ============================================================

  // 命令面板 / 全局搜索

  // ============================================================

  (function commandPalette() {

    var overlay = document.getElementById('cmd-overlay');

    var input = document.getElementById('cmd-input');

    var results = document.getElementById('cmd-results');

    var hint = document.getElementById('cmd-hint');

    var closeBtn = document.getElementById('cmd-close');

    var topSearch = document.getElementById('top-search');

    var items = [];

    var activeIdx = -1;

    Object.keys(PAGE_TITLES).forEach(function (key) {

      items.push({

        page: key,

        title: PAGE_TITLES[key],

        parent: PAGE_PARENTS[key] || '',

        keywords: ((PAGE_TITLES[key] || '') + ' ' + (PAGE_PARENTS[key] || '')).toLowerCase(),

      });

    });

    function open() {

      if (!overlay || !input) return;

      overlay.classList.add('active');

      input.value = '';

      render('');

      input.focus();

    }

    function close() {

      if (!overlay) return;

      overlay.classList.remove('active');

      if (input) input.blur();

      activeIdx = -1;

    }

    function render(q) {

      if (!results || !hint) return;

      q = (q || '').trim().toLowerCase();

      var filtered = items.filter(function (it) { return it.keywords.indexOf(q) !== -1; });

      activeIdx = filtered.length ? 0 : -1;

      if (!q) {

        results.innerHTML = '';

        hint.style.display = 'block';

        hint.textContent = '输入关键词搜索页面和功能';

        return;

      }

      hint.style.display = 'none';

      if (!filtered.length) {

        results.innerHTML = '<div class="cmd-result-item" style="cursor:default;color:var(--muted);justify-content:center;">未找到相关页面或功能</div>';

        return;

      }

      results.innerHTML = filtered.map(function (it, idx) {

        return '<div class="cmd-result-item' + (idx === activeIdx ? ' active' : '') + '" data-page="' + it.page + '" data-idx="' + idx + '">' +

          '<span class="cmd-result-title">' + escapeHtml(it.title) + '</span>' +

          (it.parent ? '<span class="cmd-result-parent">' + escapeHtml(it.parent) + '</span>' : '') +

          '</div>';

      }).join('');

    }

    function moveActive(delta) {

      var nodes = results ? results.querySelectorAll('.cmd-result-item[data-page]') : [];

      if (!nodes.length) return;

      activeIdx = (activeIdx + delta + nodes.length) % nodes.length;

      nodes.forEach(function (n, i) { n.classList.toggle('active', i === activeIdx); });

      if (nodes[activeIdx]) nodes[activeIdx].scrollIntoView({ block: 'nearest' });

    }

    function activate() {

      var node = results ? results.querySelector('.cmd-result-item.active[data-page]') : null;

      if (!node) return;

      var p = node.getAttribute('data-page');

      close();

      switchPage(p);

      try { history.replaceState(null, '', '#' + p); } catch (e) {}

    }

    if (topSearch) {

      topSearch.addEventListener('click', open);

      topSearch.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } });

    }

    if (closeBtn) closeBtn.addEventListener('click', close);

    if (overlay) overlay.addEventListener('click', function (e) { if (e.target === overlay) close(); });

    if (input) {

      input.addEventListener('input', function () { render(input.value); });

      input.addEventListener('keydown', function (e) {

        if (e.key === 'ArrowDown') { e.preventDefault(); moveActive(1); }

        else if (e.key === 'ArrowUp') { e.preventDefault(); moveActive(-1); }

        else if (e.key === 'Enter') { e.preventDefault(); activate(); }

        else if (e.key === 'Escape') { e.preventDefault(); close(); }

      });

    }

    if (results) {

      results.addEventListener('click', function (e) {

        var node = e.target.closest('.cmd-result-item[data-page]');

        if (!node) return;

        activeIdx = parseInt(node.getAttribute('data-idx') || '0', 10) || 0;

        activate();

      });

      results.addEventListener('mouseover', function (e) {

        var node = e.target.closest('.cmd-result-item[data-page]');

        if (!node || !results) return;

        var idx = parseInt(node.getAttribute('data-idx') || '0', 10);

        activeIdx = idx;

        results.querySelectorAll('.cmd-result-item').forEach(function (n, i) { n.classList.toggle('active', i === idx); });

      });

    }

    document.addEventListener('keydown', function (e) {

      if (e.key === 'k' && (e.ctrlKey || e.metaKey)) {

        e.preventDefault();

        open();

      }

      if (e.key === '/' && overlay && !overlay.classList.contains('active') && document.activeElement && ['INPUT', 'TEXTAREA'].indexOf(document.activeElement.tagName) === -1) {

        e.preventDefault();

        open();

      }

      if (e.key === 'Escape' && overlay && overlay.classList.contains('active')) {

        e.preventDefault();

        close();

      }

    });

  })();

  // ============================================================

  // 绑定机器人弹窗

  // ============================================================

  (function bindBotModal() {

    var modal = document.getElementById('bind-modal');

    var closeBtn = document.getElementById('bind-modal-close');

    var bindBtn = document.getElementById('bind-bot-btn');

    var bindEmpty = document.getElementById('bind-bot-btn-empty');

    var nextBtn = document.getElementById('bind-next');

    var prevBtn = document.getElementById('bind-prev');

    var doneBtn = document.getElementById('bind-done');

    var appidInput = document.getElementById('bind-appid');

    var secretInput = document.getElementById('bind-secret');

    var nameInput = document.getElementById('bind-name');

    var enabledInput = document.getElementById('bind-enabled');

    var titleEl = document.getElementById('bind-modal-title');

    var eyeBtn = document.getElementById('bind-secret-eye');

    var step = 1;

    var maxStep = 3;

    var editAppid = null;

    function openModal(mode, bot) {

      if (!modal) return;

      editAppid = (mode === 'edit' && bot) ? (bot.appid || null) : null;

      resetForm(bot || {});

      goStep(1);

      if (titleEl) titleEl.textContent = editAppid ? '编辑机器人' : '绑定机器人';

      modal.classList.add('active');

      // 触发重绘以启动过渡动画

      requestAnimationFrame(function () { modal.classList.add('show'); });

      if (appidInput) { appidInput.readOnly = !!editAppid; appidInput.focus(); }

    }

    window.openBotModal = openModal;

    function closeModal() {

      if (!modal) return;

      modal.classList.remove('show');

      setTimeout(function () { modal.classList.remove('active'); }, 200);

    }

    function resetForm(bot) {

      bot = bot || {};

      if (appidInput) { appidInput.value = bot.appid || ''; appidInput.classList.remove('error'); appidInput.readOnly = false; }

      if (secretInput) { secretInput.value = bot.secret || ''; secretInput.classList.remove('error'); secretInput.type = 'password'; }

      if (nameInput) nameInput.value = bot.name_rt || bot.name || '';

      if (enabledInput) enabledInput.checked = (bot.enabled !== false);

      var eventRadios = document.querySelectorAll('input[name="bind-event"]');

      eventRadios.forEach(function (r) { r.checked = (r.value === (bot.event_mode || 'websocket')); });

      var envRadios = document.querySelectorAll('input[name="bind-env"]');

      envRadios.forEach(function (r) { r.checked = (r.value === (bot.environment || 'sandbox')); });

      setVerify('loading', '正在保存…', '正在写入多机器人配置，请稍候');

      setResult(true, '已保存', '机器人配置已保存，已自动即时生效。');

    }

    function goStep(n) {

      step = Math.max(1, Math.min(maxStep, n));

      // 步骤条

      document.querySelectorAll('.step-item').forEach(function (el) {

        var s = parseInt(el.getAttribute('data-step'), 10);

        el.classList.toggle('active', s === step);

        el.classList.toggle('done', s < step);

      });

      document.querySelectorAll('.step-line').forEach(function (el) {

        var s = parseInt(el.getAttribute('data-line'), 10);

        el.classList.toggle('done', s < step);

      });

      // 面板

      document.querySelectorAll('.step-panel').forEach(function (el) {

        var p = parseInt(el.getAttribute('data-panel'), 10);

        el.classList.toggle('active', p === step);

      });

      // 按钮

      if (prevBtn) prevBtn.style.display = step === 1 ? 'none' : 'inline-flex';

      if (nextBtn) nextBtn.style.display = step === 3 ? 'none' : 'inline-flex';

      if (doneBtn) doneBtn.style.display = step === 3 ? 'inline-flex' : 'none';

      if (nextBtn) nextBtn.textContent = step === 2 ? '验证中…' : '下一步';

      if (nextBtn) nextBtn.disabled = (step === 2);

    }

    function validateStep1() {

      var ok = true;

      var appid = (appidInput ? appidInput.value : '').trim();

      var secret = (secretInput ? secretInput.value : '').trim();

      if (!appid) { appidInput.classList.add('error'); ok = false; } else { appidInput.classList.remove('error'); }

      if (!secret) { secretInput.classList.add('error'); ok = false; } else { secretInput.classList.remove('error'); }

      return ok ? { appid: appid, secret: secret } : null;

    }

    function getRadioValue(name) {

      var el = document.querySelector('input[name="' + name + '"]:checked');

      return el ? el.value : '';

    }

    function setVerify(state, title, desc) {

      var icon = document.getElementById('verify-icon');

      var titleEl = document.getElementById('verify-title');

      var descEl = document.getElementById('verify-desc');

      if (titleEl) titleEl.textContent = title || '';

      if (descEl) descEl.textContent = desc || '';

      if (icon) {

        icon.className = 'status-icon';

        if (state === 'loading') icon.classList.add('spin');

        else if (state === 'ok') icon.classList.add('ok');

        else if (state === 'err') icon.classList.add('err');

        if (state === 'ok') icon.innerHTML = '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>';

        else if (state === 'err') icon.innerHTML = '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';

        else icon.innerHTML = '';

      }

    }

    function setResult(ok, title, desc) {

      var icon = document.getElementById('result-icon');

      var titleEl = document.getElementById('result-title');

      var descEl = document.getElementById('result-desc');

      if (titleEl) titleEl.textContent = title || '';

      if (descEl) descEl.textContent = desc || '';

      if (icon) {

        icon.className = 'status-icon' + (ok ? ' ok' : ' err');

        if (ok) icon.innerHTML = '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>';

        else icon.innerHTML = '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';

      }

    }

    function doSave() {

      var data = validateStep1();

      if (!data) return;

      goStep(2);

      setVerify('loading', '正在保存…', '正在写入多机器人配置，请稍候');

      var payload = {

        appid: data.appid,

        secret: data.secret,

        event_mode: getRadioValue('bind-event'),

        environment: getRadioValue('bind-env'),

        name: (nameInput ? nameInput.value : '').trim(),

        enabled: !!(enabledInput ? enabledInput.checked : true)

      };

      if (editAppid && editAppid !== data.appid) payload.appid = editAppid;

      fetch(API_BASE + '/api/bots/add', {

        method: 'POST',

        headers: { 'Content-Type': 'application/json' },

        body: JSON.stringify(payload)

      })

        .then(function (r) { return r.json(); })

        .then(function (j) {

          if (j && j.ok) {

            setVerify('ok', '保存成功', j.message || '凭证已保存。');

            setResult(true, '已保存', j.message || '机器人配置已保存，已自动即时生效。');

            if (typeof renderBots === 'function') renderBots();

            setTimeout(function () { goStep(3); }, 500);

          } else {

            var msg = j && j.error ? j.error : '保存失败，请检查后重试。';

            setVerify('err', '保存失败', msg);

            setResult(false, '保存失败', msg);

            setTimeout(function () { goStep(3); }, 500);

          }

        })

        .catch(function () {

          var msg = '无法连接到后端服务，请检查 bot 是否在运行。';

          setVerify('err', '保存失败', msg);

          setResult(false, '保存失败', msg);

          setTimeout(function () { goStep(3); }, 500);

        });

    }

    if (bindBtn) bindBtn.addEventListener('click', function () { openModal('add'); });

    if (bindEmpty) bindEmpty.addEventListener('click', function () { openModal('add'); });

    if (closeBtn) closeBtn.addEventListener('click', closeModal);

    if (modal) modal.addEventListener('click', function (e) {

      if (e.target === modal) closeModal();

    });

    if (nextBtn) nextBtn.addEventListener('click', function () {

      if (step === 1) doSave();

    });

    if (prevBtn) prevBtn.addEventListener('click', function () { goStep(step - 1); });

    if (doneBtn) doneBtn.addEventListener('click', closeModal);

    if (eyeBtn) {

      eyeBtn.addEventListener('click', function () {

        if (!secretInput) return;

        secretInput.type = (secretInput.type === 'password') ? 'text' : 'password';

      });

    }

    // 输入时移除错误样式

    [appidInput, secretInput].forEach(function (input) {

      if (input) input.addEventListener('input', function () { input.classList.remove('error'); });

    });

    // Esc 关闭

    document.addEventListener('keydown', function (e) {

      if (e.key === 'Escape' && modal && modal.classList.contains('active')) closeModal();

    });

  })();

  // ============================================================

  // 机器人管理页 · 机器人列表

  // ============================================================

  function renderBots() {

    var empty = document.getElementById('bot-empty');

    var list = document.getElementById('bot-list');

    var count = document.getElementById('robots-count');

    if (!list) return;

    fetch(API_BASE + '/api/bots')

      .then(function (r) { return r.json(); })

      .then(function (j) {

        var bots = (j && j.bots) || [];

        allBoundBots = bots;  // 缓存权威绑定列表，供 WS 筛选下拉完整渲染所有 bot

        // 若当前筛选项已不在绑定列表中（如被解绑），自动回退到「全部机器人」，避免 trigger 残留旧名

        if (wsBotFilter && !bots.some(function (b) {

              return ((b.name_rt || b.name || b.appid || '').trim()) === wsBotFilter;

            })) {

          wsBotFilter = '';

          _saveWsBotFilter();

        }

        if (count) count.textContent = bots.length > 0 ? (bots.length + ' 个机器人') : '未绑定机器人';

        // 卡片头 tip：运行中 X / 全部 Y（运行中 = 已启用且已连接）

        var onlineCount = 0;

        // 以 /api/bots 权威 key 集合为准：先记录本次新 key，再删 botRegistry 里消失的旧 key

        // 避免 disable/reload 后 stale 旧名字（如 enable 时注册的真名→disable 后 name 变备注）残留在 dropdown

        var newKeys = {};

        bots.forEach(function (_b) {

          var _k = (_b.name_rt || _b.name || _b.appid || '').trim();

          if (_k) newKeys[_k] = true;

        });

        Object.keys(botRegistry).forEach(function (k) { if (!newKeys[k]) delete botRegistry[k]; });

        bots.forEach(function (b) {

          if (b.enabled !== false && b.connected) onlineCount += 1;

          // 写入 botRegistry（key 用真名 name_rt），供 WS 日志筛选下拉展示头像/状态

          var key = (b.name_rt || b.name || b.appid || '').trim();

          if (key) {

            botRegistry[key] = {

              appid: b.appid,

              name_rt: b.name_rt || b.name || key,

              name: b.name || '',

              avatar: b.avatar || '',

              connected: !!b.connected,

              enabled: b.enabled !== false,

              environment: b.environment || ''

            };

          }

        });

        var tipOnline = document.getElementById('bots-online-count');

        var tipTotal = document.getElementById('bots-total-count');

        if (tipOnline) tipOnline.textContent = String(onlineCount);

        if (tipTotal) tipTotal.textContent = String(bots.length);

        // 重新渲染 WS 日志筛选下拉（首次/更新时同步头像）

        if (typeof renderBotSelector === 'function') renderBotSelector();

        // 同步刷新仪表盘「按机器人切换查看」下拉

        if (typeof renderDashBotSelector === 'function') renderDashBotSelector();

        // 同步刷新数据总览页「机器人」筛选下拉（修复：原本只硬编码「全部机器人」）

        if (typeof fillDataOverviewBotSelector === 'function') fillDataOverviewBotSelector();

        // 同步刷新 chat 页机器人筛选下拉（单聊/群聊 × 消息记录/实时监控）

        syncChatBotOptions();

        if (!bots.length) {

          if (empty) empty.style.display = 'block';

          list.style.display = 'none';

          list.innerHTML = '';

          return;

        }

        if (empty) empty.style.display = 'none';

        list.style.display = 'block';

        var html = '';

        bots.forEach(function (b) {

          var masked = b.appid_masked || b.appid;

          var enabled = b.enabled !== false;

          var connected = !!b.connected;

          // 优先使用从 QQ WS HELLO 拿到的真实昵称；没有再退回配置备注 / 脱敏 AppID

          var realName = (b.name_rt || b.name || masked || '').trim();

          var displayName = realName || masked;

          var initial = (displayName || '?').slice(0, 1).toUpperCase();

          var envTag = b.environment === 'production'

            ? '<span class="tag prod">正式</span>'

            : '<span class="tag sand">沙箱</span>';

          var evtTag = b.event_mode === 'webhook'

            ? '<span class="tag">Webhook</span>'

            : '<span class="tag">WebSocket</span>';

          var statusHtml;

          if (!enabled) statusHtml = '<span class="bot-status disabled">● 已停用</span>';

          else if (connected) statusHtml = '<span class="bot-status on">● 运行中</span>';

          else statusHtml = '<span class="bot-status off">● 未连接</span>';

          var verifyTag = b.name_rt

            ? '<span class="verified">✓ 已认证</span>'

            : '<span class="unverified">未取到昵称</span>';

          // 头像：真实 URL 不为空时显示，破图时 fallback 到首字母占位

          var avatarHTML;

          if (b.avatar) {

            avatarHTML = '<div class="bot-row-avatar">' +

              '<img src="' + escapeHtml(b.avatar) + '" alt="' + escapeHtml(displayName) + '" ' +

                   'onerror="this.style.display=\'none\'; this.nextElementSibling.style.display=\'flex\';">' +

              '<div class="bot-row-avatar-fallback" style="display:none;">' + escapeHtml(initial) + '</div>' +

            '</div>';

          } else {

            avatarHTML = '<div class="bot-row-avatar">' +

              '<div class="bot-row-avatar-fallback" style="display:flex;">' + escapeHtml(initial) + '</div>' +

            '</div>';

          }

          html +=

            '<div class="bot-row" data-appid="' + escapeHtml(b.appid) + '">' +

              avatarHTML +

              '<div class="bot-row-main">' +

                '<div class="bot-row-realname"><span class="name-text">' + escapeHtml(displayName) + '</span> ' + verifyTag + '</div>' +

                '<div class="bot-row-sub">' + escapeHtml(masked) + ' ' + envTag + ' ' + evtTag + '</div>' +

              '</div>' +

              '<div class="bot-row-status">' + statusHtml + '</div>' +

              '<div class="bot-row-actions">' +

                '<label class="bot-switch" title="启用/停用"><input type="checkbox" class="bot-toggle" ' + (enabled ? 'checked' : '') + ' data-appid="' + escapeHtml(b.appid) + '"><span class="slider"></span></label>' +

                '<button class="btn ghost btn-sm bot-edit" data-appid="' + escapeHtml(b.appid) + '">编辑</button>' +

                '<button class="btn ghost btn-sm bot-del" data-appid="' + escapeHtml(b.appid) + '" data-name="' + escapeHtml(displayName) + '">删除</button>' +

              '</div>' +

            '</div>';

        });

        html += '<div class="bot-list-foot"><span class="hint">凭证 / 启用修改后自动即时生效；下方按钮可手动全量刷新兜底</span>' +

                '<button class="btn primary" id="bots-apply-restart">全量刷新</button></div>';

        list.innerHTML = html;

      })

      .catch(function () {

        if (list) list.innerHTML = '<div class="table-empty">加载机器人列表失败，请检查后端是否在运行。</div>';

      });

  }

  // 机器人列表：编辑 / 删除 / 应用并重启（事件委托，兼容列表重渲染）

  var botListEl = document.getElementById('bot-list');

  if (botListEl) {

    botListEl.addEventListener('click', function (e) {

      var editBtn = e.target.closest && e.target.closest('.bot-edit');

      if (editBtn) {

        var appid = editBtn.getAttribute('data-appid');

        fetch(API_BASE + '/api/bots')

          .then(function (r) { return r.json(); })

          .then(function (j) {

            var bots = (j && j.bots) || [];

            var b = null;

            bots.forEach(function (x) { if (x.appid === appid) b = x; });

            if (b && typeof window.openBotModal === 'function') window.openBotModal('edit', b);

          });

        return;

      }

      var delBtn = e.target.closest && e.target.closest('.bot-del');

      if (delBtn) {

        var appid2 = delBtn.getAttribute('data-appid');

        var nm = delBtn.getAttribute('data-name') || appid2;

        if (!confirm('确定删除机器人「' + nm + '」？删除后将立即停止该 bot 线程。')) return;

        fetch(API_BASE + '/api/bots/delete', {

          method: 'POST', headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify({ appid: appid2 })

        })

          .then(function (r) { return r.json(); })

          .then(function (j) {

            if (j && j.ok) { renderBots(); }

            else { alert((j && j.error) || '删除失败'); }

          })

          .catch(function () { alert('删除失败：无法连接到后端'); });

        return;

      }

      var applyBtn = e.target.closest && e.target.closest('#bots-apply-restart');

      if (applyBtn) {

        applyBtn.disabled = true;

        var oldText = applyBtn.textContent;

        applyBtn.textContent = '刷新中…';

        fetch(API_BASE + '/api/bots/reload', { method: 'POST' })

          .then(function () {

            setTimeout(function () {

              renderBots();

              applyBtn.disabled = false;

              applyBtn.textContent = oldText;

            }, 9000);

          })

          .catch(function () {

            applyBtn.disabled = false;

            applyBtn.textContent = oldText;

            alert('刷新指令发送失败，请检查后端。');

          });

        return;

      }

    });

    botListEl.addEventListener('change', function (e) {

      var tog = e.target.closest && e.target.closest('.bot-toggle');

      if (!tog) return;

      var appid = tog.getAttribute('data-appid');

      var enabled = !!tog.checked;

      // 专用启停端点：只更新 enabled，绝不触碰 secret，避免把已存凭证清空

      fetch(API_BASE + '/api/bots/set-enabled', {

        method: 'POST', headers: { 'Content-Type': 'application/json' },

        body: JSON.stringify({ appid: appid, enabled: enabled })

      })

        .then(function (r) { return r.json(); })

        .then(function (j) {

          if (j && j.ok) {

            // 后端已自动按 appid 粒度热重载，无需 restart。给用户一个即时反馈。

            try { showToast(j.message || ('已' + (enabled ? '启用' : '禁用') + '，即时生效')); } catch (e) {}

            renderBots();

          } else {

            alert((j && j.error) || '更新启用状态失败');

            renderBots();

          }

        })

        .catch(function () { alert('更新失败：无法连接到后端'); renderBots(); });

    });

  }

  // ============================================================

  // 机器人管理页 · WebSocket 日志

  // ============================================================

  var wsFilter = 'all';

  // 从 sessionStorage 恢复上次选择的 WS 机器人筛选（刷新页面后保持选择）

  var wsBotFilter = (function () {

    try { var v = sessionStorage.getItem('wsBotFilter'); return v == null ? '' : v; }

    catch (e) { return ''; }

  })();

  function _saveWsBotFilter() {

    try { sessionStorage.setItem('wsBotFilter', wsBotFilter || ''); } catch (e) {}

  }

  var wsFilterEl = document.getElementById('ws-filter');

  // 自定义下拉（带头像+昵称+状态点），替代原来的 <select id="ws-bot-filter">

  var wsBotSelector = document.getElementById('ws-bot-selector');

  var wsBotSelectorTrigger = document.getElementById('ws-bot-selector-trigger');

  var wsBotSelectorMenu = document.getElementById('ws-bot-selector-menu');

  var wsBotSelectorName = document.getElementById('ws-bot-selector-name');

  // botRegistry：缓存所有 bot 详情（按 name_rt 索引，用于匹配 + 渲染头像）

  var botRegistry = {};  // name_rt -> {appid, name_rt, name, avatar, connected, enabled, environment}

  // allBoundBots：/api/bots 返回的全部绑定 bot（权威列表，驱动 WS 筛选下拉，杜绝漏项/时序问题）

  // botDisplayName：显示用机器人名称，与「机器人」管理卡片（红色圈）保持一致。

  // 优先 name_rt（QQ 平台真实昵称，如「小流萤」「恶龙遐蝶」）；其次 name（本地配置备注）；再 fallback key。

  // 后端筛选 key 仍是 name_rt（保持 /api/stats?bot= / /api/ws-logs?bot= 兼容），这里只决定显示文本。

  // E2E 测试残留防御：把"机器人 1905365716"这种「中文 + 空格 + 纯数字」占位名视为空，显示走 fallback

  // 另把"name"字段与 appid 一致（数字）的情况也算无效——说明该字段被错误地填成了 appid

  function _sanitizeName(n, appid) {

    if (!n) return '';

    var s = String(n).trim();

    if (!s) return '';

    // 形如"机器人 1905365716"/"机器人1905365716"

    if (/^机器人\s*\d{5,}$/.test(s)) return '';

    // 纯数字且等于 appid —— 被错误地填成 appid

    if (appid && s === String(appid).trim()) return '';

    return s;

  }

  function botDisplayName(key) {

    if (!key) return '';

    var info = botRegistry[key];

    if (info) {

      if (info.name_rt) return info.name_rt;

      var sane = _sanitizeName(info.name, info.appid);

      if (sane) return sane;

    }

    return key;

  }

  // 用真实昵称（name_rt）填充任意「按机器人筛选 / 选择」的 <select>。

  // value 用 name_rt（与后端 /api/...?bot= 筛选键一致），text 用 botDisplayName（真实昵称）。

  function fillBotSelect(sel, allLabel) {

    if (!sel) return;

    var cur = sel.value || '';

    var html = '<option value="">' + escapeHtml(allLabel || '全部机器人') + '</option>';

    var seen = {};

    function add(key) {

      if (!key || seen[key]) return;

      seen[key] = true;

      html += '<option value="' + escapeHtml(key) + '">' + escapeHtml(botDisplayName(key)) + '</option>';

    }

    (allBoundBots || []).forEach(function (b) {

      add((b.name_rt || b.name || b.appid || '').trim());

    });

    Object.keys(botRegistry || {}).forEach(function (n) { add(n); });

    sel.innerHTML = html;

    if (cur && seen[cur]) sel.value = cur;

  }

  var allBoundBots = [];

  // chat 页（单聊/群聊的消息记录与实时监控）机器人下拉：renderBots 更新后统一刷新

  var _chatBotOptionSync = [];

  function syncChatBotOptions() {

    for (var i = 0; i < _chatBotOptionSync.length; i++) {

      try { _chatBotOptionSync[i](); } catch (e) {}

    }

  }

  // 同步机器人 select 旁的状态点：value 为 '' 时灰点；否则按 connected 决定绿/灰（2026-08-08）

  function updateBotStatusDot(selId, dotId) {

    var sel = document.getElementById(selId);

    var dot = document.getElementById(dotId);

    if (!sel || !dot) return;

    var v = sel.value;

    if (!v) { dot.classList.remove('online'); return; }

    var connected = false;

    var info = botRegistry && botRegistry[v];

    if (info && info.connected) connected = true;

    if (!connected && Array.isArray(allBoundBots)) {

      for (var i = 0; i < allBoundBots.length; i++) {

        var b = allBoundBots[i];

        var k = (b.name_rt || b.name || b.appid || '').trim();

        if (k === v && b.connected) { connected = true; break; }

      }

    }

    dot.classList.toggle('online', connected);

  }

  // 渲染下拉菜单（从 botRegistry 提取，按 enabled/connected 排序）

  function renderBotSelector() {

    if (!wsBotSelectorMenu) return;

    var prev = wsBotFilter || '';

    // 以 /api/bots 权威列表为主，确保「所有绑定 bot 必出现」；botRegistry 作为首屏兜底

    var seen = {};

    var list = [];

    (allBoundBots || []).forEach(function (b) {

      var key = (b.name_rt || b.name || b.appid || '').trim();

      if (!key || seen[key]) return;

      seen[key] = true;

      list.push({

        key: key,

        name: botDisplayName(key),

        avatar: b.avatar || '',

        connected: !!b.connected,

        enabled: b.enabled !== false

      });

    });

    // 兜底：renderBots 尚未返回时，用 botRegistry 已收录的 bot（含 WS 日志占位）

    Object.keys(botRegistry).forEach(function (n) {

      if (!n || seen[n] || !botRegistry[n]) return;

      seen[n] = true;

      var info = botRegistry[n];

      list.push({

        key: n,

        name: botDisplayName(n),

        avatar: info.avatar || '',

        connected: !!info.connected,

        enabled: info.enabled !== false

      });

    });

    list.sort(function (a, b) {

      // connected 优先，再按 enabled，再按名称

      var ca = a.connected ? 1 : 0;

      var cb = b.connected ? 1 : 0;

      if (ca !== cb) return cb - ca;

      var ea = a.enabled ? 1 : 0;

      var eb = b.enabled ? 1 : 0;

      if (ea !== eb) return eb - ea;

      return a.name.localeCompare(b.name, 'zh-CN');

    });

    var html = '';

    html += '<li class="bot-selector-item' + (prev === '' ? ' active' : '') + '" data-value="">' +

            '<span class="bot-selector-avatar all">⊕</span>' +

            '<span class="bot-selector-name">全部机器人</span>' +

            '</li>';

    if (list.length === 0) {

      html += '<li class="bot-selector-empty">尚未绑定任何机器人</li>';

    } else {

      list.forEach(function (it) {

        var isActive = (prev === it.key) ? ' active' : '';

        var initial = (it.name || '?').slice(0, 1).toUpperCase();

        var avatar = it.avatar

          ? '<img src="' + escapeHtml(it.avatar) + '" alt="" onerror="this.outerHTML=\'<span>' + escapeHtml(initial) + '</span>\'">'

          : escapeHtml(initial);

        // 三态：enabled===false 优先 disabled（灰），否则看 connected

        var statusCls = (it.enabled === false) ? 'disabled'

          : (it.connected ? 'online' : 'offline');

        var statusTitle = (it.enabled === false) ? '已停用'

          : (it.connected ? '已连接' : '未连接');

        var labelName = (it.enabled === false) ? (escapeHtml(it.name) + ' <span class="bot-selector-tag-disabled">(已停用)</span>') : escapeHtml(it.name);

        html += '<li class="bot-selector-item' + isActive + '" data-value="' + escapeHtml(it.key) + '">' +

                '<span class="bot-selector-avatar">' + avatar + '</span>' +

                '<span class="bot-selector-name">' + labelName + '</span>' +

                '<span class="bot-selector-status ' + statusCls + '" title="' + statusTitle + '"></span>' +

                '</li>';

      });

    }

    wsBotSelectorMenu.innerHTML = html;

    positionBotSelectorMenu();

    updateBotSelectorTrigger();

  }

  // 更新触发按钮显示（当前选中）

  function updateBotSelectorTrigger() {

    if (!wsBotSelectorTrigger || !wsBotSelectorName) return;

    var cur = wsBotFilter || '';

    if (cur === '' || !botRegistry[cur]) {

      // 全部机器人 / 未匹配

      var av = wsBotSelectorTrigger.querySelector('.bot-selector-avatar');

      if (av) {

        av.className = 'bot-selector-avatar all';

        av.innerHTML = '⊕';

      }

      wsBotSelectorName.textContent = '全部机器人';

      return;

    }

    var info = botRegistry[cur] || {};

    var displayName = botDisplayName(cur);

    var initial = (displayName || '?').slice(0, 1).toUpperCase();

    var av = wsBotSelectorTrigger.querySelector('.bot-selector-avatar');

    if (av) {

      av.className = 'bot-selector-avatar';

      av.innerHTML = info.avatar

        ? '<img src="' + escapeHtml(info.avatar) + '" alt="" onerror="this.outerHTML=\'<span>' + escapeHtml(initial) + '</span>\'">'

        : escapeHtml(initial);

    }

    wsBotSelectorName.textContent = displayName;

  }

  // 计算下拉菜单位置（position:fixed，按 trigger 视口坐标定位，绕开祖先 overflow:hidden 裁剪）

  function positionBotSelectorMenu() {

    if (!wsBotSelectorMenu || !wsBotSelectorTrigger) return;

    if (!wsBotSelector.classList.contains('open')) return;

    var tr = wsBotSelectorTrigger.getBoundingClientRect();

    var mw = wsBotSelectorMenu.offsetWidth || 200;

    wsBotSelectorMenu.style.top = (tr.bottom + 4) + 'px';

    wsBotSelectorMenu.style.left = (tr.right - mw) + 'px';

  }

  window.addEventListener('resize', positionBotSelectorMenu);

  window.addEventListener('scroll', positionBotSelectorMenu, true);

  // 打开/关闭

  if (wsBotSelector) {

    if (wsBotSelectorTrigger) {

      wsBotSelectorTrigger.addEventListener('click', function (e) {

        e.stopPropagation();

        wsBotSelector.classList.toggle('open');

        positionBotSelectorMenu();

      });

    }

    if (wsBotSelectorMenu) {

      wsBotSelectorMenu.addEventListener('click', function (e) {

        var item = e.target.closest('.bot-selector-item');

        if (!item) return;

        e.stopPropagation();

        var val = item.getAttribute('data-value') || '';

        wsBotFilter = val;

        _saveWsBotFilter();

        // 重新渲染高亮

        Array.prototype.forEach.call(wsBotSelectorMenu.querySelectorAll('.bot-selector-item'), function (li) {

          li.classList.toggle('active', (li.getAttribute('data-value') || '') === val);

        });

        updateBotSelectorTrigger();

        wsBotSelector.classList.remove('open');

        loadWsLogs();

      });

    }

    // 点击外部关闭

    document.addEventListener('click', function () {

      wsBotSelector.classList.remove('open');

    });

    // ESC 关闭

    document.addEventListener('keydown', function (e) {

      if (e.key === 'Escape') wsBotSelector.classList.remove('open');

    });

  }

  if (wsFilterEl) {

    wsFilterEl.addEventListener('change', function () {

      wsFilter = wsFilterEl.value || 'all';

      loadWsLogs();

    });

  }

  // WebSocket 日志卡片：仅保留 WebSocket 日志

  var wsFiltersBox = document.getElementById('ws-filters');

  if (wsFiltersBox) wsFiltersBox.classList.remove('hidden');

  var wsClearBtn = document.getElementById('ws-clear');

  if (wsClearBtn) {

    wsClearBtn.addEventListener('click', function () {

      if (!confirm('确定清空 WebSocket 日志吗？')) return;

      fetch(API_BASE + '/api/ws-logs/clear', { method: 'POST' })

        .then(function (r) { return r.json(); })

        .then(function (j) {

          if (j && j.ok) {

            var tb = document.getElementById('ws-tbody');

            if (tb) tb.innerHTML = '<tr><td colspan="8" class="table-empty">已清空</td></tr>';

            setText('ws-msg-count', '0');

            setText('ws-bot-count', '1');

          } else {

            alert('清空失败：' + (j && j.error ? j.error : '未知错误'));

          }

        })

        .catch(function () { alert('清空失败：无法连接到后端'); });

    });

  }

  // ============================================================

  // 仪表盘 · 按机器人切换查看（与 WS 日志同款 .bot-selector 组件）

  // ============================================================

  var dashBotSelector = document.getElementById('dash-bot-selector');

  var dashBotSelectorTrigger = document.getElementById('dash-bot-selector-trigger');

  var dashBotSelectorMenu = document.getElementById('dash-bot-selector-menu');

  var dashBotSelectorName = document.getElementById('dash-bot-selector-name');

  function renderDashBotSelector() {

    if (!dashBotSelectorMenu) return;

    var prev = dashBotFilter || '';

    var seen = {};

    var list = [];

    (allBoundBots || []).forEach(function (b) {

      var key = (b.name_rt || b.name || b.appid || '').trim();

      if (!key || seen[key]) return;

      seen[key] = true;

      list.push({ key: key, name: botDisplayName(key), avatar: b.avatar || '', connected: !!b.connected, enabled: b.enabled !== false });

    });

    Object.keys(botRegistry).forEach(function (n) {

      if (!n || seen[n] || !botRegistry[n]) return;

      seen[n] = true;

      var info = botRegistry[n];

      list.push({ key: n, name: botDisplayName(n), avatar: info.avatar || '', connected: !!info.connected, enabled: info.enabled !== false });

    });

    list.sort(function (a, b) {

      var ca = a.connected ? 1 : 0, cb = b.connected ? 1 : 0;

      if (ca !== cb) return cb - ca;

      var ea = a.enabled ? 1 : 0, eb = b.enabled ? 1 : 0;

      if (ea !== eb) return eb - ea;

      return a.name.localeCompare(b.name, 'zh-CN');

    });

    var html = '';

    html += '<li class="bot-selector-item' + (prev === '' ? ' active' : '') + '" data-value="">' +

            '<span class="bot-selector-avatar all">⊕</span>' +

            '<span class="bot-selector-name">全部机器人</span></li>';

    if (list.length === 0) {

      html += '<li class="bot-selector-empty">尚未绑定任何机器人</li>';

    } else {

      list.forEach(function (it) {

        var isActive = (prev === it.key) ? ' active' : '';

        var initial = (it.name || '?').slice(0, 1).toUpperCase();

        var avatar = it.avatar

          ? '<img src="' + escapeHtml(it.avatar) + '" alt="" onerror="this.outerHTML=\'<span>' + escapeHtml(initial) + '</span>\'">'

          : escapeHtml(initial);

        // 三态：enabled===false 优先 disabled（灰），否则看 connected

        var statusCls = (it.enabled === false) ? 'disabled'

          : (it.connected ? 'online' : 'offline');

        var statusTitle = (it.enabled === false) ? '已停用'

          : (it.connected ? '已连接' : '未连接');

        var labelName = (it.enabled === false) ? (escapeHtml(it.name) + ' <span class="bot-selector-tag-disabled">(已停用)</span>') : escapeHtml(it.name);

        html += '<li class="bot-selector-item' + isActive + '" data-value="' + escapeHtml(it.key) + '">' +

                '<span class="bot-selector-avatar">' + avatar + '</span>' +

                '<span class="bot-selector-name">' + labelName + '</span>' +

                '<span class="bot-selector-status ' + statusCls + '" title="' + statusTitle + '"></span></li>';

      });

    }

    dashBotSelectorMenu.innerHTML = html;

    positionDashBotMenu();

    updateDashBotSelectorTrigger();

  }

  function updateDashBotSelectorTrigger() {

    if (!dashBotSelectorTrigger || !dashBotSelectorName) return;

    var cur = dashBotFilter || '';

    if (cur === '' || !botRegistry[cur]) {

      var av = dashBotSelectorTrigger.querySelector('.bot-selector-avatar');

      if (av) { av.className = 'bot-selector-avatar all'; av.innerHTML = '⊕'; }

      dashBotSelectorName.textContent = '全部机器人';

      return;

    }

    var info = botRegistry[cur] || {};

    var displayName = botDisplayName(cur);

    var initial = (displayName || '?').slice(0, 1).toUpperCase();

      var av = dashBotSelectorTrigger.querySelector('.bot-selector-avatar');

      if (av) {

        av.className = 'bot-selector-avatar';

        av.innerHTML = info.avatar

          ? '<img src="' + escapeHtml(info.avatar) + '" alt="" onerror="this.outerHTML=\'<span>' + escapeHtml(initial) + '</span>\'">'

          : escapeHtml(initial);

      }

      dashBotSelectorName.textContent = displayName;

  }

  function positionDashBotMenu() {

    if (!dashBotSelectorMenu || !dashBotSelectorTrigger) return;

    if (!dashBotSelector.classList.contains('open')) return;

    var tr = dashBotSelectorTrigger.getBoundingClientRect();

    var mw = dashBotSelectorMenu.offsetWidth || 200;

    dashBotSelectorMenu.style.top = (tr.bottom + 4) + 'px';

    dashBotSelectorMenu.style.left = (tr.right - mw) + 'px';

  }

  function refreshDashboardForBot() {

    fetchStats(function (d) {

      applyKpi(d);

      if (d) recordToday(d);

      renderDashboardCharts();

      renderOverviewBotTag(d);

    }, dashBotFilter);

  }

  // 在数据概览标题旁渲染当前所选机器人角标（空=全部）

  function renderOverviewBotTag(s) {

    var el = document.getElementById('overview-bot-tag');

    if (!el) return;

    if (!dashBotFilter) {

      el.textContent = '（全部机器人）';

      el.removeAttribute('data-active');

      return;

    }

    var label = (s && (s.bot_name || s.bot_appid)) || botDisplayName(dashBotFilter);

    el.textContent = '· ' + label;

    el.setAttribute('data-active', '1');

  }

  window.addEventListener('resize', positionDashBotMenu);

  window.addEventListener('scroll', positionDashBotMenu, true);

  if (dashBotSelector) {

    if (dashBotSelectorTrigger) {

      dashBotSelectorTrigger.addEventListener('click', function (e) {

        e.stopPropagation();

        dashBotSelector.classList.toggle('open');

        positionDashBotMenu();

      });

    }

    if (dashBotSelectorMenu) {

      dashBotSelectorMenu.addEventListener('click', function (e) {

        var item = e.target.closest('.bot-selector-item');

        if (!item) return;

        e.stopPropagation();

        var val = item.getAttribute('data-value') || '';

        dashBotFilter = val;

        try { sessionStorage.setItem('dashBotFilter', val || ''); } catch (err) {}

        Array.prototype.forEach.call(dashBotSelectorMenu.querySelectorAll('.bot-selector-item'), function (li) {

          li.classList.toggle('active', (li.getAttribute('data-value') || '') === val);

        });

        updateDashBotSelectorTrigger();

        dashBotSelector.classList.remove('open');

        // 反向同步：数据总览页的 data-bot-select 下拉 + 数据总览 KPI

        if (typeof fillDataOverviewBotSelector === 'function') fillDataOverviewBotSelector();

        refetchDataOverview();

        refreshDashboardForBot();

      });

    }

    document.addEventListener('click', function () { dashBotSelector.classList.remove('open'); });

    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') dashBotSelector.classList.remove('open'); });

  }

  // 仪表盘消息趋势：「单机器人 / 多机器人对比」切换

  (function () {

    var toggle = document.getElementById('trend-compare-toggle');

    if (!toggle) return;

    toggle.addEventListener('click', function () {

      trendCompareMode = !trendCompareMode;

      toggle.classList.toggle('active', trendCompareMode);

      var card = chart ? chart.getDom().closest('.chart-card') : null;

      if (card) card.classList.toggle('compare-mode', trendCompareMode);

      renderChart(trendRange());

    });

  })();

  // 运行日志（日志中心页）

  var runtimeTbody = document.getElementById('runtime-tbody');

  var runtimeTableWrap = document.getElementById('runtime-table-wrap');

  var runtimeScrollPausedTip = document.getElementById('runtime-scroll-paused');

  var runtimeHTrack = document.getElementById('runtime-hscroll-track');

  var runtimeHThumb = document.getElementById('runtime-hscroll-thumb');

  var runtimeStatusEl = document.getElementById('runtime-status');

  var runtimeAutoScroll = true;

  var runtimeAllItems = [];      // 后端返回的全部日志，前端据此做级别过滤

  var runtimeFilterLevel = 'ALL'; // ALL | INFO | WARN | ERROR

  function runtimeIsNearBottom() {

    if (!runtimeTableWrap) return true;

    var gap = runtimeTableWrap.scrollHeight - runtimeTableWrap.clientHeight - runtimeTableWrap.scrollTop;

    return gap <= 24;

  }

  function runtimeUpdatePausedTip() {

    if (runtimeScrollPausedTip) runtimeScrollPausedTip.classList.toggle('show', !runtimeAutoScroll);

  }

  function runtimeUpdateHScroll() {

    if (!runtimeTableWrap || !runtimeHTrack || !runtimeHThumb) return;

    var sw = runtimeTableWrap.scrollWidth;

    var cw = runtimeTableWrap.clientWidth;

    if (sw <= cw) {

      runtimeHTrack.classList.add('hidden');

      return;

    }

    runtimeHTrack.classList.remove('hidden');

    var trackW = runtimeHTrack.clientWidth;

    var ratio = cw / sw;

    var thumbW = Math.max(48, trackW * ratio);

    runtimeHThumb.style.width = thumbW + 'px';

    var maxScroll = sw - cw;

    var maxThumb = trackW - thumbW;

    var left = maxScroll > 0 ? (runtimeTableWrap.scrollLeft / maxScroll) * maxThumb : 0;

    runtimeHThumb.style.left = left + 'px';

  }

  var runtimeHDragging = false;

  var runtimeHDragStartX = 0;

  var runtimeHDragStartLeft = 0;

  function runtimeHGetClientX(e) { return e.touches && e.touches.length ? e.touches[0].clientX : e.clientX; }

  if (runtimeHThumb) {

    runtimeHThumb.addEventListener('mousedown', function (e) {

      runtimeHDragging = true;

      runtimeHDragStartX = runtimeHGetClientX(e);

      runtimeHDragStartLeft = parseFloat(runtimeHThumb.style.left) || 0;

      e.preventDefault();

    });

    runtimeHThumb.addEventListener('touchstart', function (e) {

      runtimeHDragging = true;

      runtimeHDragStartX = runtimeHGetClientX(e);

      runtimeHDragStartLeft = parseFloat(runtimeHThumb.style.left) || 0;

      e.preventDefault();

    }, { passive: false });

  }

  function runtimeHDragMove(e) {

    if (!runtimeHDragging || !runtimeTableWrap || !runtimeHThumb || !runtimeHTrack) return;

    var clientX = runtimeHGetClientX(e);

    var dx = clientX - runtimeHDragStartX;

    var trackW = runtimeHTrack.clientWidth;

    var thumbW = runtimeHThumb.clientWidth;

    var maxThumb = trackW - thumbW;

    var left = Math.max(0, Math.min(maxThumb, runtimeHDragStartLeft + dx));

    runtimeHThumb.style.left = left + 'px';

    var maxScroll = runtimeTableWrap.scrollWidth - runtimeTableWrap.clientWidth;

    runtimeTableWrap.scrollLeft = maxThumb > 0 ? (left / maxThumb) * maxScroll : 0;

  }

  function runtimeHDragEnd() { runtimeHDragging = false; }

  document.addEventListener('mousemove', runtimeHDragMove);

  document.addEventListener('mouseup', runtimeHDragEnd);

  document.addEventListener('touchmove', runtimeHDragMove, { passive: false });

  document.addEventListener('touchend', runtimeHDragEnd);

  if (runtimeHTrack) {

    runtimeHTrack.addEventListener('click', function (e) {

      if (e.target === runtimeHThumb) return;

      if (!runtimeTableWrap || !runtimeHTrack || !runtimeHThumb) return;

      var rect = runtimeHTrack.getBoundingClientRect();

      var clickX = e.clientX - rect.left;

      var trackW = runtimeHTrack.clientWidth;

      var thumbW = runtimeHThumb.clientWidth;

      var maxScroll = runtimeTableWrap.scrollWidth - runtimeTableWrap.clientWidth;

      var ratio = (clickX - thumbW / 2) / (trackW - thumbW);

      runtimeTableWrap.scrollLeft = Math.max(0, Math.min(maxScroll, ratio * maxScroll));

    });

  }

  window.addEventListener('resize', runtimeUpdateHScroll);

  if (runtimeTableWrap) {

    runtimeTableWrap.addEventListener('scroll', function () {

      runtimeAutoScroll = runtimeIsNearBottom();

      runtimeUpdatePausedTip();

      runtimeUpdateHScroll();

    }, { passive: true });

  }

  var runtimeScrollTopBtn = document.getElementById('runtime-scroll-top');

  var runtimeScrollBottomBtn = document.getElementById('runtime-scroll-bottom');

  if (runtimeScrollTopBtn) {

    runtimeScrollTopBtn.addEventListener('click', function () {

      if (!runtimeTableWrap) return;

      runtimeTableWrap.scrollTo({ top: 0, behavior: 'smooth' });

      runtimeAutoScroll = false;

      runtimeUpdatePausedTip();

    });

  }

  if (runtimeScrollBottomBtn) {

    runtimeScrollBottomBtn.addEventListener('click', function () {

      if (!runtimeTableWrap) return;

      runtimeTableWrap.scrollTo({ top: runtimeTableWrap.scrollHeight, behavior: 'smooth' });

      runtimeAutoScroll = true;

      runtimeUpdatePausedTip();

    });

  }

  var runtimeFullscreenBtn = document.getElementById('runtime-fullscreen');

  var runtimeLogCard = runtimeTableWrap && runtimeTableWrap.closest('.card');

  function toggleRuntimeFullscreen() {

    if (!runtimeLogCard) return;

    var d = document;

    if (d.fullscreenElement || d.webkitFullscreenElement || d.mozFullScreenElement || d.msFullscreenElement) {

      var exit = d.exitFullscreen || d.webkitExitFullscreen || d.mozCancelFullScreen || d.msExitFullscreen;

      if (exit) exit.call(d);

    } else {

      var req = runtimeLogCard.requestFullscreen || runtimeLogCard.webkitRequestFullscreen || runtimeLogCard.mozRequestFullScreen || runtimeLogCard.msRequestFullscreen;

      if (req) req.call(runtimeLogCard);

    }

  }

  if (runtimeFullscreenBtn) {

    runtimeFullscreenBtn.addEventListener('click', toggleRuntimeFullscreen);

  }

  // 进入全屏后默认定位到最新一条日志（当前顺序：最新在底部）

  function runtimeScrollToBottom() {

    if (!runtimeTableWrap) return;

    runtimeTableWrap.scrollTop = runtimeTableWrap.scrollHeight;

    runtimeAutoScroll = true;

    runtimeUpdatePausedTip();

    runtimeUpdateHScroll();

  }

  function onRuntimeFullscreenChange() {

    var d = document;

    var entered = !!(d.fullscreenElement || d.webkitFullscreenElement || d.mozFullScreenElement || d.msFullscreenElement);

    if (entered) {

      // 等全屏布局稳定后再滚到底部，确保看到最新日志

      setTimeout(runtimeScrollToBottom, 80);

    }

  }

  document.addEventListener('fullscreenchange', onRuntimeFullscreenChange);

  document.addEventListener('webkitfullscreenchange', onRuntimeFullscreenChange);

  document.addEventListener('mozfullscreenchange', onRuntimeFullscreenChange);

  document.addEventListener('MSFullscreenChange', onRuntimeFullscreenChange);

  // 运行日志级别过滤器（全部 / INFO / WARN / ERROR）

  var runtimeFiltersBox = document.getElementById('runtime-filters');

  if (runtimeFiltersBox) {

    runtimeFiltersBox.addEventListener('click', function (e) {

      var btn = e.target.closest('button[data-level]');

      if (!btn) return;

      var lv = btn.getAttribute('data-level');

      if (lv === runtimeFilterLevel) return;

      runtimeFilterLevel = lv;

      Array.prototype.forEach.call(runtimeFiltersBox.querySelectorAll('button'), function (b) {

        b.classList.toggle('active', b.getAttribute('data-level') === lv);

      });

      renderRuntimeLogs(); // 复用已加载的全部日志，无需重新请求

    });

  }

  var runtimeClearBtn = document.getElementById('runtime-clear');

  if (runtimeClearBtn) {

    runtimeClearBtn.addEventListener('click', function () {

      if (!confirm('确定清空机器人运行日志吗？')) return;

      fetch(API_BASE + '/api/bot-console/clear', { method: 'POST' })

        .then(function (r) { return r.json(); })

        .then(function (j) {

          if (j && j.ok) {

            if (runtimeTbody) runtimeTbody.innerHTML = '<tr><td colspan="2" class="table-empty">已清空</td></tr>';

            setText('runtime-msg-count', '0');

          } else {

            alert('清空失败：' + (j && j.error ? j.error : '未知错误'));

          }

        })

        .catch(function () { alert('清空失败：无法连接到后端'); });

    });

  }

  function renderRuntimeLogs(payload) {

    if (!runtimeTbody) return;

    if (payload && payload.items) runtimeAllItems = payload.items;

    // 后端 /api/bot-console 按"最新在前"返回（reversed），前端展示为"最新在底部"

    // 这里取一份副本反转成时间正序（旧→新），再按级别过滤

    var items = runtimeAllItems.slice().reverse();

    // 按级别过滤

    if (runtimeFilterLevel !== 'ALL') {

      items = items.filter(function (it) { return (it.level || 'INFO') === runtimeFilterLevel; });

    }

    // 消息计数显示过滤后的条数

    setText('runtime-msg-count', String(items.length));

    if (!items.length) {

      runtimeTbody.innerHTML = '<tr><td colspan="3" class="table-empty">暂无运行日志</td></tr>';

      runtimeUpdateHScroll();

      return;

    }

    var shouldStickBottom = runtimeAutoScroll;

    var prevTop = runtimeTableWrap ? runtimeTableWrap.scrollTop : 0;

    runtimeTbody.innerHTML = items.map(function (it) {

      var lv = it.level || 'INFO';

      return '<tr class="log-' + lv + '">' +

        '<td class="col-level"><span class="lv-tag ' + lv + '">' + lv + '</span></td>' +

        '<td class="col-time">' + escapeHtml(it.ts || '') + '</td>' +

        '<td class="col-content ws-console-line">' + escapeHtml(it.text || '') + '</td>' +

        '</tr>';

    }).join('');

    if (shouldStickBottom && runtimeTableWrap) {

      runtimeTableWrap.scrollTop = runtimeTableWrap.scrollHeight;

    } else if (runtimeTableWrap) {

      runtimeTableWrap.scrollTop = prevTop;

    }

    runtimeUpdateHScroll();

    runtimeUpdatePausedTip();

  }

  function loadRuntimeLogs() {

    fetch(API_BASE + '/api/bot-console?limit=1500')

      .then(function (r) { return r.json(); })

      .then(function (j) { updateRuntimeStatus(true); renderRuntimeLogs(j); })

      .catch(function () {

        updateRuntimeStatus(false);

        renderRuntimeLogs({ items: [{ ts: '--', text: '无法连接 127.0.0.1:9988，请检查 bot 是否在运行' }] });

      });

  }

  function updateRuntimeStatus(ok) {

    if (!runtimeStatusEl) return;

    runtimeStatusEl.classList.toggle('online', ok);

    runtimeStatusEl.classList.toggle('offline', !ok);

    var txt = runtimeStatusEl.querySelector('.text');

    if (txt) txt.textContent = ok ? '已连接' : '未连接';

  }

  var wsScrollTopBtn = document.getElementById('ws-scroll-top');

  var wsScrollBottomBtn = document.getElementById('ws-scroll-bottom');

  var wsTableWrap = document.getElementById('ws-table-wrap');

  var wsScrollPausedTip = document.getElementById('ws-scroll-paused');

  var wsHTrack = document.getElementById('ws-hscroll-track');

  var wsHThumb = document.getElementById('ws-hscroll-thumb');

  var wsAutoScroll = true;

  function wsIsNearTop() {

    if (!wsTableWrap) return true;

    return wsTableWrap.scrollTop < 8;

  }

  function wsUpdatePausedTip() {

    if (wsScrollPausedTip) wsScrollPausedTip.classList.toggle('show', !wsAutoScroll);

  }

  function wsUpdateHScroll() {

    if (!wsTableWrap || !wsHTrack || !wsHThumb) return;

    var sw = wsTableWrap.scrollWidth;

    var cw = wsTableWrap.clientWidth;

    if (sw <= cw) {

      wsHTrack.classList.add('hidden');

      return;

    }

    wsHTrack.classList.remove('hidden');

    var trackW = wsHTrack.clientWidth;

    var ratio = cw / sw;

    var thumbW = Math.max(48, trackW * ratio);

    wsHThumb.style.width = thumbW + 'px';

    var maxScroll = sw - cw;

    var maxThumb = trackW - thumbW;

    var left = maxScroll > 0 ? (wsTableWrap.scrollLeft / maxScroll) * maxThumb : 0;

    wsHThumb.style.left = left + 'px';

  }

  var wsHDragging = false;

  var wsHDragStartX = 0;

  var wsHDragStartLeft = 0;

  function wsHGetClientX(e) { return e.touches && e.touches.length ? e.touches[0].clientX : e.clientX; }

  if (wsHThumb) {

    wsHThumb.addEventListener('mousedown', function (e) {

      wsHDragging = true;

      wsHDragStartX = wsHGetClientX(e);

      wsHDragStartLeft = parseFloat(wsHThumb.style.left) || 0;

      e.preventDefault();

    });

    wsHThumb.addEventListener('touchstart', function (e) {

      wsHDragging = true;

      wsHDragStartX = wsHGetClientX(e);

      wsHDragStartLeft = parseFloat(wsHThumb.style.left) || 0;

      e.preventDefault();

    }, { passive: false });

  }

  function wsHDragMove(e) {

    if (!wsHDragging || !wsTableWrap || !wsHThumb || !wsHTrack) return;

    var clientX = wsHGetClientX(e);

    var dx = clientX - wsHDragStartX;

    var trackW = wsHTrack.clientWidth;

    var thumbW = wsHThumb.clientWidth;

    var maxThumb = trackW - thumbW;

    var left = Math.max(0, Math.min(maxThumb, wsHDragStartLeft + dx));

    wsHThumb.style.left = left + 'px';

    var maxScroll = wsTableWrap.scrollWidth - wsTableWrap.clientWidth;

    wsTableWrap.scrollLeft = maxThumb > 0 ? (left / maxThumb) * maxScroll : 0;

  }

  function wsHDragEnd() { wsHDragging = false; }

  document.addEventListener('mousemove', wsHDragMove);

  document.addEventListener('mouseup', wsHDragEnd);

  document.addEventListener('touchmove', wsHDragMove, { passive: false });

  document.addEventListener('touchend', wsHDragEnd);

  if (wsHTrack) {

    wsHTrack.addEventListener('click', function (e) {

      if (e.target === wsHThumb) return;

      if (!wsTableWrap || !wsHTrack || !wsHThumb) return;

      var rect = wsHTrack.getBoundingClientRect();

      var clickX = e.clientX - rect.left;

      var trackW = wsHTrack.clientWidth;

      var thumbW = wsHThumb.clientWidth;

      var maxScroll = wsTableWrap.scrollWidth - wsTableWrap.clientWidth;

      var ratio = (clickX - thumbW / 2) / (trackW - thumbW);

      wsTableWrap.scrollLeft = Math.max(0, Math.min(maxScroll, ratio * maxScroll));

    });

  }

  window.addEventListener('resize', wsUpdateHScroll);

  if (wsTableWrap) {

    wsTableWrap.addEventListener('scroll', function () {

      wsAutoScroll = wsIsNearTop();

      wsUpdatePausedTip();

      wsUpdateHScroll();

    }, { passive: true });

  }

  if (wsScrollTopBtn) {

    wsScrollTopBtn.addEventListener('click', function () {

      if (!wsTableWrap) return;

      wsTableWrap.scrollTo({ top: 0, behavior: 'smooth' });

      wsAutoScroll = true;

      wsUpdatePausedTip();

    });

  }

  if (wsScrollBottomBtn) {

    wsScrollBottomBtn.addEventListener('click', function () {

      if (!wsTableWrap) return;

      wsTableWrap.scrollTo({ top: wsTableWrap.scrollHeight, behavior: 'smooth' });

      wsAutoScroll = false;

      wsUpdatePausedTip();

    });

  }

  // ===== WebSocket 日志全屏（镜像 runtime log 全屏范式） =====

  var wsFullscreenBtn = document.getElementById('ws-fullscreen');

  var wsLogCard = wsTableWrap && wsTableWrap.closest('\.card');

  function toggleWsFullscreen() {

    if (!wsLogCard) return;

    var d = document;

    if (d.fullscreenElement || d.webkitFullscreenElement || d.mozFullScreenElement || d.msFullscreenElement) {

      var exit = d.exitFullscreen || d.webkitExitFullscreen || d.mozCancelFullScreen || d.msExitFullscreen;

      if (exit) exit.call(d);

    } else {

      var req = wsLogCard.requestFullscreen || wsLogCard.webkitRequestFullscreen || wsLogCard.mozRequestFullScreen || wsLogCard.msRequestFullscreen;

      if (req) req.call(wsLogCard);

    }

  }

  if (wsFullscreenBtn) {

    wsFullscreenBtn.addEventListener('click', toggleWsFullscreen);

  }

  // 进入全屏后默认定位到最新一条（最新在表格顶部，scrollTop=0）

  function wsScrollToTop() {

    if (!wsTableWrap) return;

    wsTableWrap.scrollTop = 0;

    wsAutoScroll = true;

    wsUpdatePausedTip();

    wsUpdateHScroll();

  }

  function onWsFullscreenChange() {

    var d = document;

    var entered = !!(d.fullscreenElement || d.webkitFullscreenElement || d.mozFullScreenElement || d.msFullscreenElement);

    if (entered) {

      // 等全屏布局稳定后再滚到顶，确保看到最新日志

      setTimeout(wsScrollToTop, 80);

    }

  }

  document.addEventListener('fullscreenchange', onWsFullscreenChange);

  document.addEventListener('webkitfullscreenchange', onWsFullscreenChange);

  document.addEventListener('mozfullscreenchange', onWsFullscreenChange);

  document.addEventListener('MSFullscreenChange', onWsFullscreenChange);

  function renderWsLogs(payload) {

    var tb = document.getElementById('ws-tbody');

    if (!tb) return;

    var statusEl = document.getElementById('ws-status');

    if (statusEl) {

      var on = !!(payload && payload.connected);

      statusEl.classList.toggle('online', on);

      statusEl.classList.toggle('offline', !on);

      var txt = statusEl.querySelector('.text');

      if (txt) txt.textContent = on ? '已连接' : '未连接';

    }

    setText('ws-bot-count', String(((payload && payload.bots) || []).length));

    // 把 WS 日志里出现过的机器人名合并到 botRegistry（用 /api/bots 数据补 avatar/connected）

    // 如果不在 botRegistry 里（极端情况：刚启动还没拉到 /api/bots），先用名称占位

    var wsBots = (payload && payload.bots) || [];

    wsBots.forEach(function (n) {

      if (!n) return;

      if (!botRegistry[n]) {

        botRegistry[n] = { name_rt: n, avatar: '', connected: false, enabled: true, environment: '' };

      }

    });

    // 重新渲染自定义下拉（保留当前 wsBotFilter 选择）

    renderBotSelector();

    // 若当前选中的机器人已下线，保留选择但允许用户主动改

    var items = (payload && payload.items) || [];

    var filtered = items.filter(function (it) {

      if (wsBotFilter && (it.bot || '') !== wsBotFilter) return false;

      if (wsFilter === 'up') return it.direction === '上行' || it.direction === 'up';

      if (wsFilter === 'down') return it.direction === '下行' || it.direction === 'down';

      if (wsFilter === 'system') return it.direction === 'system' || it.type === '系统';

      return true;

    });

    setText('ws-msg-count', String(filtered.length));

    if (!filtered.length) {

      tb.innerHTML = '<tr><td colspan="8" class="table-empty">暂无日志</td></tr>';

      wsUpdateHScroll();

      return;

    }

    // 记录本次渲染前是否处于顶部（最新一条），渲染后决定是否滚顶；用户上滑查看历史时用补偿保持视觉锚定

    var shouldStickTop = wsAutoScroll;

    var prevTop = wsTableWrap ? wsTableWrap.scrollTop : 0;

    var prevScrollHeight = wsTableWrap ? wsTableWrap.scrollHeight : 0;

    // 倒序后渲染（最新在上），但视觉显示顺位与接口顺序一致

    tb.innerHTML = filtered.map(function (it) {

      var typeCls = it.type === '群聊' ? 'group'

                  : it.type === '单聊' ? 'private'

                  : 'system';

      var dirCls = it.direction === '上行' ? 'up'

                : it.direction === '下行' ? 'down'

                : 'system';

      return '<tr>' +

        '<td class="col-idx">' + it.idx + '</td>' +

        '<td class="col-time">' + escapeHtml(it.ts) + '</td>' +

        '<td>' + escapeHtml(botDisplayName(it.bot)) + '</td>' +

        '<td><span class="tag-type ' + typeCls + '">' + escapeHtml(it.type) + '</span></td>' +

        '<td><span class="tag-dir ' + dirCls + '">' + escapeHtml(it.direction) + '</span></td>' +

        '<td>' + escapeHtml(it.scene) + '</td>' +

        '<td class="col-sender">' + escapeHtml(it.sender) + '</td>' +

        '<td class="col-content">' + escapeHtml(it.content) + '</td>' +

        '</tr>';

    }).join('');

    // 仅当用户处于顶部（最新）时才自动滚顶，否则用补偿保持当前阅读位置

    if (shouldStickTop && wsTableWrap) {

      wsTableWrap.scrollTop = 0;

    } else if (wsTableWrap) {

      var delta = wsTableWrap.scrollHeight - prevScrollHeight;

      wsTableWrap.scrollTop = prevTop + delta;

    }

    wsUpdateHScroll();

    wsUpdatePausedTip();

  }

  function loadWsLogs() {

    fetch(API_BASE + '/api/ws-logs?limit=200&bot=' + encodeURIComponent(wsBotFilter || ''))

      .then(function (r) { return r.json(); })

      .then(function (j) { renderWsLogs(j); })

      .catch(function () {

        // 离线占位

        renderWsLogs({ connected: false, items: [{

          idx: '-', ts: '--', bot: '-', type: '系统', direction: 'system',

          scene: '-', sender: '-', content: '无法连接 127.0.0.1:9988，请检查 bot 是否在运行'

        }] });

      });

  }

  // 根据当前所在页面分别轮询对应日志

  function loadActiveLog() {

    var robotsActive = document.getElementById('page-robots') && document.getElementById('page-robots').classList.contains('active');

    var logsActive = document.getElementById('page-logs') && document.getElementById('page-logs').classList.contains('active');

    if (robotsActive) { loadWsLogs(); renderBots(); }

    if (logsActive) loadRuntimeLogs();

  }

  // 首次 + 每 3 秒轮询

  tick();

  loadAnnouncements('ann-list', 'ann-time');

  loadAnnouncements('data-ann-list', 'data-ann-time');

  setInterval(tick, 3000);

  // 实时日期时间：每秒刷新

  updateClock();

  setInterval(updateClock, 1000);

  setInterval(function () {

    loadAnnouncements('ann-list', 'ann-time');

    loadAnnouncements('data-ann-list', 'data-ann-time');

  }, 15000);

  setInterval(loadActiveLog, 3000);

  // 页面初始时预拉一次 WebSocket 日志，以便切到机器人页即时显示

  loadWsLogs();

  // 仪表盘快捷操作：点击跳转页面

  document.addEventListener('click', function (e) {

    var btn = e.target.closest('.quick-btn');

    if (!btn) return;

    var page = btn.getAttribute('data-page');

    if (page && typeof switchPage === 'function') switchPage(page);

  });

  // ============================================================

  // 消息中心

  // ============================================================

    function createChatCenter(cfg) {

    cfg = cfg || {};

    var P = cfg.prefix || '';

    var fixedType = cfg.type || null;

    var fixedMode = cfg.mode || 'logs';

    var currentTab = 'c2c';

    if (fixedType) currentTab = fixedType;

    var messageItems = [];

    var monitorSessions = [];

    // 单聊/群聊「消息记录」表格（logs mode）专用：保存当前渲染时按 idx 排序后的过滤列表

    // 供「查看」按钮按 data-idx 回查对应条目展示详情。

    var logsLastItems = [];

    var activeSession = null;

    var activeChatId = '';

    var activeChatItems = [];

    var userProfiles = {}; // openid -> {nickname, avatar, qq}（已绑定 QQ 的真实资料）

    var groupProfiles = {}; // group_openid -> {name, avatar, qq}（已绑定 QQ 群号的群资料）

    // 机器人筛选下拉：用真实昵称填充选项（与「全部」标签区分 logs/monitor）

    var botSelId = P + (fixedMode === 'monitor' ? 'monitor-bot-select' : 'msg-bot-select');

    var botDotId = P + (fixedMode === 'monitor' ? 'monitor-bot-dot' : 'msg-bot-dot');

    function refreshChatBotOptions() {

      var botSel = document.getElementById(botSelId);

      if (!botSel) return;

      fetch(API_BASE + '/api/bots')

        .then(function (r) { return r.json(); })

        .then(function (j) {

          var bots = (j && j.bots) || [];

          var cur = botSel.value;

          var html = '<option value="">' + escapeHtml(fixedMode === 'monitor' ? '全部' : '全部机器人') + '</option>';

          var seen = {};

          bots.forEach(function (b) {

            var k = (b.name_rt || b.name || b.appid || '').trim();

            if (!k || seen[k]) return;

            seen[k] = true;

            html += '<option value="' + escapeHtml(k) + '">' + escapeHtml(k) + '</option>';

          });

          botSel.innerHTML = html;

          if (cur && seen[cur]) botSel.value = cur;

          updateBotStatusDot(botSelId, botDotId);

        })

        .catch(function () {});

    }

    refreshChatBotOptions();

    _chatBotOptionSync.push(refreshChatBotOptions);

    // 头像组件：优先显示远程头像，失败/无头像时 fallback 首字母

    function avatarHtml(avatar, name, sizeClass) {

      sizeClass = sizeClass || '';

      var initial = escapeHtml((name || '?').slice(0, 1));

      var img = avatar ? '<img class="avatar-img" src="' + escapeHtml(avatar) + '" alt="" onerror="this.style.visibility=\'hidden\';">' : '';

      return '<div class="avatar-wrap ' + sizeClass + '">' + img + '<span class="avatar-fallback">' + initial + '</span></div>';

    }

    function groupDisplayName(it) {
      // 优先用后端解析的官方/自定义群名；否则退化为原始 openid（带完整 openid 作 title 兜底）
      if (it && it.group_name) return it.group_name;
      var g = (it && (it.group_openid || it.scene)) || '';
      return g || '-';
    }

    function senderName(it) {

      // 优先从 userProfiles 取真实昵称（覆盖未绑 QQ + OIAPI 反查场景）

      var prof = it && it.sender ? profileOf(it.sender) : null;

      if (prof && prof.nickname) return prof.nickname;

      return it.nickname || (it.sender && it.sender !== '-' ? it.sender.slice(0, 8) : '-');

    }

    // 标签切换

    document.querySelectorAll('.msg-tab').forEach(function (tab) {

      tab.addEventListener('click', function () {

        document.querySelectorAll('.msg-tab').forEach(function (t) { t.classList.remove('active'); });

        tab.classList.add('active');

        currentTab = tab.getAttribute('data-tab') || 'c2c';

        updateTabUI();

        applyFilters();

      });

    });

    function updateTabUI() {

      // 切换表格显示

      ['c2c', 'group', 'event'].forEach(function (t) {

        var table = document.getElementById(P + 'msg-table-' + t);

        if (!table) return;

        // 单类型页面：只显示对应表格；多类型（原 messages-logs）：按 currentTab 切

        var showThis = fixedType ? (t === fixedType) : (t === currentTab);

        table.style.display = showThis ? 'table' : 'none';

      });

      // 切换筛选下拉

      var groupSel = document.getElementById(P + 'msg-group-select');

      var eventSel = document.getElementById(P + 'msg-event-select');

      var dirSel = document.getElementById(P + 'msg-direction');

      if (groupSel) groupSel.style.display = currentTab === 'group' ? 'inline-block' : 'none';

      if (eventSel) eventSel.style.display = currentTab === 'event' ? 'inline-block' : 'none';

      if (dirSel) dirSel.style.display = currentTab === 'event' ? 'none' : 'inline-block';

    }

    function statusText(direction) {

      if (direction === '上行') return '已接收';

      if (direction === '下行') return '已发送';

      return '系统';

    }

    function dirText(direction) {

      if (direction === '上行') return '收到';

      if (direction === '下行') return '发出';

      return direction || '-';

    }

    function renderMessages() {

      var tbody = document.getElementById(P + 'msg-tbody-' + currentTab);

      var empty = document.getElementById(P + 'msg-empty');

      var table = document.getElementById(P + 'msg-table-' + currentTab);

      if (!tbody || !table) return;

      var filtered = messageItems.filter(function (it) {

        // 单类型页面：按 fixedType 过滤；多类型页面：按 currentTab 过滤

        var t = fixedType || currentTab;

        if (t === 'c2c') return it.type === '单聊';

        if (t === 'group') return it.type === '群聊';

        return it.type === '系统';

      });

      // 应用筛选

      var bot = document.getElementById(P + 'msg-bot-select');

      var direction = document.getElementById(P + 'msg-direction');

      var group = document.getElementById(P + 'msg-group-select');

      var eventType = document.getElementById(P + 'msg-event-select');

      var search = document.getElementById(P + 'msg-search');

      var botVal = bot ? bot.value : '';

      var dirVal = direction ? direction.value : '';

      var groupVal = group ? group.value : '';

      var eventVal = eventType ? eventType.value : '';

      var searchVal = search ? search.value.trim().toLowerCase() : '';

      if (botVal) filtered = filtered.filter(function (it) { return it.bot === botVal; });

      var effectiveTab = fixedType || currentTab;

      if (dirVal && effectiveTab !== 'event') filtered = filtered.filter(function (it) { return it.direction === dirVal; });

      if (groupVal && effectiveTab === 'group') filtered = filtered.filter(function (it) { return it.scene === groupVal; });

      if (eventVal && effectiveTab === 'event') filtered = filtered.filter(function (it) { return it.type === eventVal; });

      if (searchVal) filtered = filtered.filter(function (it) { return (it.content || '').toLowerCase().indexOf(searchVal) !== -1 || (it.sender || '').toLowerCase().indexOf(searchVal) !== -1 || (it.nickname || '').toLowerCase().indexOf(searchVal) !== -1; });

      // 空状态

      if (!filtered.length) {

        tbody.innerHTML = '';

        table.style.display = 'none';

        if (empty) { empty.style.display = 'flex'; }

        return;

      }

      table.style.display = 'table';

      if (empty) empty.style.display = 'none';

      // 按时间倒序

      filtered.sort(function (a, b) { return String(b.ts).localeCompare(String(a.ts)); });

      tbody.innerHTML = filtered.map(function (it) {

        var op = '<span class="op-link" data-act="view" data-idx="' + it.idx + '">查看</span>';

        var name = senderName(it);

        var senderCell = '<div class="sender-cell">' + avatarHtml(it.avatar, name) + '<span>' + escapeHtml(name) + '</span></div>';

        var renderTab = fixedType || currentTab;

        if (renderTab === 'c2c') {

          return '<tr>' +

            '<td class="col-idx">' + it.idx + '</td>' +

            '<td>' + escapeHtml(botDisplayName(it.bot)) + '</td>' +

            '<td class="col-time">' + escapeHtml(it.ts) + '</td>' +

            '<td>' + escapeHtml(dirText(it.direction)) + '</td>' +

            '<td>' + statusText(it.direction) + '</td>' +

            '<td>' + senderCell + '</td>' +

            '<td><span class="tag-type private">' + escapeHtml(it.type) + '</span></td>' +

            '<td class="col-content">' + escapeHtml(it.content) + '</td>' +

            '<td class="col-op">' + op + '</td>' +

            '</tr>';

        }

        if (renderTab === 'group') {

          return '<tr>' +

            '<td class="col-idx">' + it.idx + '</td>' +

            '<td>' + escapeHtml(botDisplayName(it.bot)) + '</td>' +

            '<td class="col-time">' + escapeHtml(it.ts) + '</td>' +

            '<td>' + escapeHtml(dirText(it.direction)) + '</td>' +

            '<td>' + statusText(it.direction) + '</td>' +

            '<td>' + senderCell + '</td>' +

            '<td title="' + escapeHtml(it.group_openid || it.scene || '') + '">' + escapeHtml(groupDisplayName(it)) + '</td>' +

            '<td><span class="tag-type group">' + escapeHtml(it.type) + '</span></td>' +

            '<td class="col-content">' + escapeHtml(it.content) + '</td>' +

            '<td class="col-op">' + op + '</td>' +

            '</tr>';

        }

        return '<tr>' +

          '<td class="col-idx">' + it.idx + '</td>' +

          '<td>' + escapeHtml(botDisplayName(it.bot)) + '</td>' +

          '<td class="col-time">' + escapeHtml(it.ts) + '</td>' +

          '<td><span class="tag-type system">' + escapeHtml(it.type) + '</span></td>' +

          '<td class="col-content">' + escapeHtml(it.content) + '</td>' +

          '<td>' + escapeHtml(it.scene || '-') + '</td>' +

          '<td class="col-op">' + op + '</td>' +

          '</tr>';

      }).join('');

      // 缓存当前已渲染的过滤列表（已排序+赋 idx），供「查看」按钮回查

      if (fixedMode === 'logs') logsLastItems = filtered.slice();

    }

    function loadMessageLogs() {

      fetch(API_BASE + '/api/message-logs?limit=500')

        .then(function (r) { return r.json(); })

        .then(function (j) {

          messageItems = (j && j.items) || [];

          // 更新群下拉选项

          var groupSel = document.getElementById(P + 'msg-group-select');

          if (groupSel) {

            var groups = {};

            messageItems.forEach(function (it) { if (it.type === '群聊' && it.scene && it.scene !== '-') groups[it.scene] = groupDisplayName(it); });

            var opts = '<option value="">全部群</option>';

            Object.keys(groups).sort().forEach(function (g) { opts += '<option value="' + escapeHtml(g) + '" title="' + escapeHtml(g) + '">' + escapeHtml(groups[g]) + '</option>'; });

            groupSel.innerHTML = opts;

          }

          applyFilters();

        })

        .catch(function () {

          messageItems = [];

          applyFilters();

        });

    }

    function applyFilters() {

      updateTabUI();

      renderMessages();

    }

    function resetFilters() {

      var bot = document.getElementById(P + 'msg-bot-select');

      var direction = document.getElementById(P + 'msg-direction');

      var group = document.getElementById(P + 'msg-group-select');

      var eventType = document.getElementById(P + 'msg-event-select');

      var search = document.getElementById(P + 'msg-search');

      if (bot) bot.value = '';

      if (direction) direction.value = '';

      if (group) group.value = '';

      if (eventType) eventType.value = '';

      if (search) search.value = '';

      applyFilters();

    }

    if (fixedMode === 'logs') {

      document.getElementById(P + 'msg-search').addEventListener('input', applyFilters);

      document.getElementById(P + 'msg-search').addEventListener('keydown', function (e) { if (e.key === 'Enter') applyFilters(); });

      [P + 'msg-bot-select', P + 'msg-direction', P + 'msg-group-select', P + 'msg-event-select'].forEach(function (id) {

        var el = document.getElementById(id);

        if (el) el.addEventListener('change', applyFilters);

      });

    }

    if (fixedMode === 'logs') document.getElementById(P + 'msg-bot-select').addEventListener('change', function () { updateBotStatusDot(P + 'msg-bot-select', P + 'msg-bot-dot'); });

    // 实时监控

    function loadUserProfiles() {

      return fetch(API_BASE + '/api/user-profiles', { cache: 'no-store' })

        .then(function (r) { return r.json(); })

        .then(function (j) {

          if (j && j.profiles) {

            var next = j.profiles || {};

            // 简单 diff：检查是否有任何 openid 的昵称/头像发生变化

            var changed = false;

            var prevKeys = Object.keys(userProfiles || {});

            var nextKeys = Object.keys(next);

            if (prevKeys.length !== nextKeys.length) changed = true;

            if (!changed) {

              for (var i = 0; i < nextKeys.length; i++) {

                var k = nextKeys[i];

                var a = userProfiles[k], b = next[k];

                if (!a || a.nickname !== b.nickname || a.avatar !== b.avatar || a.qq !== b.qq || a.source !== b.source) {

                  changed = true; break;

                }

              }

            }

            userProfiles = next;

            // 同步更新已有会话列表中的用户名/头像，避免等下一轮 loadMonitorSessions

            if (changed && monitorSessions && monitorSessions.length) {

              var sessionChanged = false;

              monitorSessions.forEach(function (s) {

                if (s.type !== '单聊') return;

                var prof = userProfiles[s.name];

                if (!prof) return;

                if (prof.nickname && s.displayName !== prof.nickname) {

                  s.displayName = prof.nickname;

                  sessionChanged = true;

                }

                if (prof.avatar && s.avatar !== prof.avatar) {

                  s.avatar = prof.avatar;

                  sessionChanged = true;

                }

              });

              if (sessionChanged) renderMonitorSessions();

              refreshActiveSession();

              if (activeSession) {

                var active = monitorSessions.find(function (s) { return s.key === activeSession; });

                if (active && active.type === '单聊') selectSession(active.key);

              }

            }

          }

          return userProfiles;

        })

        .catch(function (e) {

          console.error('[user-profiles] 加载失败:', e);

          return userProfiles;

        });

    }

    function profileOf(openid) {

      return openid && openid !== '-' ? (userProfiles[openid] || null) : null;

    }

    function groupProfileOf(groupOpenid) {

      return groupOpenid && groupOpenid !== '-' ? (groupProfiles[groupOpenid] || null) : null;

    }

    function loadGroupProfiles() {

      return fetch(API_BASE + '/api/group-profiles', { cache: 'no-store' })

        .then(function (r) { return r.json(); })

        .then(function (j) {

          if (j && j.profiles) {

            groupProfiles = j.profiles || {};

            // 同步更新已有会话列表中的群名/头像，避免等下一轮 loadMonitorSessions

            var changed = false;

            monitorSessions.forEach(function (s) {

              if (s.type !== '群聊') return;

              var gprof = groupProfileOf(s.name);

              if (!gprof) return;

              if (gprof.name && s.displayName !== gprof.name) {

                s.displayName = gprof.name;

                changed = true;

              }

              if (gprof.avatar && s.avatar !== gprof.avatar) {

                s.avatar = gprof.avatar;

                changed = true;

              }

            });

            if (changed) renderMonitorSessions();

            refreshActiveSession();

            // 如果当前正在查看群聊，刷新聊天头部以应用新的群名/头像

            if (activeSession) {

              var active = monitorSessions.find(function (s) { return s.key === activeSession; });

              if (active && active.type === '群聊') selectSession(active.key);

            }

          }

          return groupProfiles;

        })

        .catch(function (e) {

          console.error('[group-profiles] 加载失败:', e);

          return groupProfiles;

        });

    }

    function loadMonitorSessions() {

      fetch(API_BASE + '/api/message-logs?limit=500')

        .then(function (r) { return r.json(); })

        .then(function (j) {

          messageItems = (j && j.items) || [];

          // 按会话分组：单聊按 sender(openid)，群聊按 scene

          var sessionsMap = {};

          // 单类型监控页只保留对应会话（单聊/群聊）；综合页(P 为空)保留全部

          var monitorItems = fixedType

            ? messageItems.filter(function (it) { return fixedType === 'c2c' ? it.type === '单聊' : it.type === '群聊'; })

            : messageItems;

          monitorItems.forEach(function (it) {

            if (it.type === '系统') return;

            var isGroup = it.type === '群聊';

            // 群聊使用 group_openid（完整群 openid）作为唯一标识；单聊用 sender openid

            var groupOpenid = isGroup ? (it.group_openid || it.scene || '-') : '';

            var key = isGroup ? ('grp:' + groupOpenid) : ('usr:' + it.sender);

            var prof = profileOf(it.sender);

            if (isGroup) {

              // 群聊会话：优先使用已绑定 QQ 群号后的真实群名/头像；

              // 如果已有该会话记录，保留用户手动修改过的群名/头像，避免被空 groupProfiles 覆盖

              var gprof = groupProfileOf(groupOpenid);

              var existing = sessionsMap[key];

              var displayName = existing ? (existing.displayName || groupDisplayName(it)) : groupDisplayName(it);

              var avatar = existing ? (existing.avatar || '') : '';

              if (gprof && gprof.name) displayName = gprof.name;

              if (gprof && gprof.avatar) avatar = gprof.avatar;

              if (!existing) {

                sessionsMap[key] = { key: key, name: groupOpenid, displayName: displayName, type: it.type, avatar: avatar, lastTs: it.ts, lastContent: it.content, unread: 0 };

              }

              sessionsMap[key].lastTs = it.ts;

              sessionsMap[key].lastContent = it.content;

              // 仅在拿到真实资料时才覆盖，防止 groupProfiles 尚未加载时清空已有名称/头像

              if (gprof && gprof.name) sessionsMap[key].displayName = gprof.name;

              if (gprof && gprof.avatar) sessionsMap[key].avatar = gprof.avatar;

            } else {

              var name = senderName(it);

              var avatar = it.avatar || '';

              if (prof) {

                if (prof.nickname) name = prof.nickname;

                if (prof.avatar) avatar = prof.avatar;

              }

              if (!sessionsMap[key]) {

                sessionsMap[key] = { key: key, name: name, displayName: name, type: it.type, avatar: avatar, lastTs: it.ts, lastContent: it.content, unread: 0 };

              }

              sessionsMap[key].lastTs = it.ts;

              sessionsMap[key].lastContent = it.content;

              if (it.avatar) sessionsMap[key].avatar = it.avatar;

              if (it.nickname) sessionsMap[key].name = it.nickname;

              if (prof && prof.avatar) sessionsMap[key].avatar = prof.avatar;

              if (prof && prof.nickname) sessionsMap[key].name = prof.nickname;

              sessionsMap[key].displayName = sessionsMap[key].name;

            }

          });

          monitorSessions = Object.values(sessionsMap).sort(function (a, b) { return String(b.lastTs).localeCompare(String(a.lastTs)); });

          renderMonitorSessions();

          refreshActiveSession();

        })

        .catch(function () {

          monitorSessions = [];

          renderMonitorSessions();

        });

    }

    function refreshActiveSession() {

      if (!activeSession) return;

      var session = monitorSessions.find(function (s) { return s.key === activeSession; });

      if (!session) return;

      var openid = session.type === '群聊' ? '' : session.key.replace('usr:', '');

      var chatItems = messageItems.filter(function (it) {

        if (it.type === '系统') return false;

        if (session.type === '群聊') return (it.group_openid || it.scene) === session.name;

        return it.sender === openid;

      }).sort(function (a, b) {

        var t = String(a.ts).localeCompare(String(b.ts));

        if (t !== 0) return t;

        return (a.idx || 0) - (b.idx || 0);

      });

      activeChatItems = chatItems;

      var box = document.getElementById(P + 'monitor-messages');

      if (!box) return;

      var bubbles = chatItems.map(function (it) { return renderBubble(it); }).join('');

      if (box.innerHTML === bubbles) return;

      var atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 24;

      var prevTop = box.scrollTop;

      var prevHeight = box.scrollHeight;

      box.innerHTML = bubbles;

      if (atBottom) {

        box.scrollTop = box.scrollHeight;

      } else {

        // 正在翻阅历史时，保持阅读位置不被新消息打断

        box.scrollTop = prevTop + (box.scrollHeight - prevHeight);

      }

      updateScrollNav();

    }

    function updateScrollNav() {

      var box = document.getElementById(P + 'monitor-messages');

      var bottom = document.getElementById(P + 'monitor-scroll-bottom');

      if (!box || !bottom) return;

      var atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 24;

      bottom.classList.toggle('active', !atBottom);

    }

    function wireScrollNav() {

      var box = document.getElementById(P + 'monitor-messages');

      var topBtn = document.getElementById(P + 'monitor-scroll-top');

      var bottomBtn = document.getElementById(P + 'monitor-scroll-bottom');

      if (!box) return;

      if (topBtn) topBtn.addEventListener('click', function () { box.scrollTo({ top: 0, behavior: 'smooth' }); });

      if (bottomBtn) bottomBtn.addEventListener('click', function () { box.scrollTo({ top: box.scrollHeight, behavior: 'smooth' }); });

      box.addEventListener('scroll', updateScrollNav);

      updateScrollNav();

    }

    function renderMonitorSessions() {

      var list = document.getElementById(P + 'monitor-list');

      if (!list) return;

      var searchVal = (document.getElementById(P + 'monitor-search') || { value: '' }).value.trim().toLowerCase();

      var filtered = monitorSessions.filter(function (s) {

        if (!searchVal) return true;

        var hay = ((s.name || '') + ' ' + (s.displayName || '')).toLowerCase();

        return hay.indexOf(searchVal) !== -1;

      });

      if (!filtered.length) {

        list.innerHTML = '<div class="' + P + 'msg-empty" style="padding:40px 0;"><div class="icon-box" style="width:48px;height:48px;"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg></div><div class="text">暂无可监控会话</div></div>';

        return;

      }

      list.innerHTML = filtered.map(function (s) {

        var disp = s.displayName || s.name;

        return '<div class="monitor-item' + (s.key === activeSession ? ' active' : '') + '" data-key="' + escapeHtml(s.key) + '">' +

          avatarHtml(s.avatar, disp, 'medium') +

          '<div class="meta">' +

            '<div class="name">' + escapeHtml(disp) + '</div>' +

            '<div class="preview">' + escapeHtml(s.lastContent || '') + '</div>' +

          '</div>' +

          '<div class="time">' + escapeHtml((s.lastTs || '').split(' ')[1] || s.lastTs || '') + '</div>' +

          '</div>';

      }).join('');

      // 绑定点击

      list.querySelectorAll('.monitor-item').forEach(function (el) {

        el.addEventListener('click', function () {

          selectSession(el.getAttribute('data-key'));

        });

      });

    }

    function mediaSrc(url) {

      if (!url) return '';

      if (url.indexOf('data:') === 0 || url.indexOf('blob:') === 0) return url;

      return API_BASE + url;

    }

    function renderBubble(it) {

      var isOut = it.direction === '下行';

      var inner;

      if (it.media_type === 'image' && it.media_url) {

        inner = '<img class="bubble-media" src="' + escapeHtml(mediaSrc(it.media_url)) + '" alt="图片">';

      } else if (it.media_type === 'voice' && it.media_url) {

        inner = '<audio class="bubble-media" controls preload="none" src="' + escapeHtml(mediaSrc(it.media_url)) + '"></audio>';

      } else if (it.media_type === 'video' && it.media_url) {

        inner = '<video class="bubble-media" controls preload="none" src="' + escapeHtml(mediaSrc(it.media_url)) + '"></video>';

      } else {

        inner = '<div class="bubble-text">' + escapeHtml(it.content || '') + '</div>';

      }

      // 收到的消息：展示发送者真实头像/昵称（已绑定 QQ 时使用真实资料）

      var sender = '';

      if (!isOut) {

        var prof = profileOf(it.sender);

        var sName = (prof && prof.nickname) ? prof.nickname : (it.nickname || senderName(it));

        var sAvatar = (prof && prof.avatar) ? prof.avatar : (it.avatar || '');

        sender = '<div class="bubble-sender">' + avatarHtml(sAvatar, sName, 'xs') +

          '<span class="bubble-name">' + escapeHtml(sName) + '</span></div>';

      }

      return '<div class="chat-bubble ' + (isOut ? 'out' : 'in') + '">' + sender + inner +

        '<div class="time">' + escapeHtml(it.ts) + '</div></div>';

    }

    function scrollMessagesToBottom() {

      var box = document.getElementById(P + 'monitor-messages');

      if (box) box.scrollTop = box.scrollHeight;

    }

    function nowTs() {

      var d = new Date();

      function p(n) { return (n < 10 ? '0' : '') + n; }

      return d.getFullYear() + '/' + p(d.getMonth() + 1) + '/' + p(d.getDate()) + ' ' +

        p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());

    }

    function labelOf(t) {

      return ({ image: '图片', voice: '语音', video: '视频' })[t] || '媒体';

    }

    function appendLocalBubble(it) {

      var box = document.getElementById(P + 'monitor-messages');

      if (!box) return;

      box.insertAdjacentHTML('beforeend', renderBubble(it));

      scrollMessagesToBottom();

    }

    function doSendText(chatId, text) {

      text = (text || '').trim();

      if (!text) return;

      appendLocalBubble({ direction: '下行', ts: nowTs(), content: text, media_type: '', media_url: '' });

      fetch(API_BASE + '/api/send-message', {

        method: 'POST',

        headers: { 'Content-Type': 'application/json' },

        body: JSON.stringify({ chat_id: chatId, msg_type: 'text', content: text })

      })

        .then(function (r) { return r.json(); })

        .then(function (j) {

          if (!j || !j.ok) {

            appendLocalBubble({ direction: '下行', ts: nowTs(), content: '⚠️ 发送失败：' + ((j && j.error) || '未知错误'), media_type: '', media_url: '' });

          }

        })

        .catch(function (err) {

          appendLocalBubble({ direction: '下行', ts: nowTs(), content: '⚠️ 发送失败：' + err, media_type: '', media_url: '' });

        });

    }

    function sendMedia(chatId, msgType, file) {

      if (!file) return;

      var reader = new FileReader();

      reader.onload = function () {

        var dataUrl = reader.result;

        appendLocalBubble({ direction: '下行', ts: nowTs(), content: '[' + labelOf(msgType) + '] ' + (file.name || ''), media_type: msgType, media_url: dataUrl });

        fetch(API_BASE + '/api/send-message', {

          method: 'POST',

          headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify({ chat_id: chatId, msg_type: msgType, content: '', file_data: dataUrl, file_name: file.name || ('file.' + msgType) })

        })

          .then(function (r) { return r.json(); })

          .then(function (j) {

            if (!j || !j.ok) {

              appendLocalBubble({ direction: '下行', ts: nowTs(), content: '⚠️ 发送失败：' + ((j && j.error) || '未知错误'), media_type: '', media_url: '' });

            }

          })

          .catch(function (err) {

            appendLocalBubble({ direction: '下行', ts: nowTs(), content: '⚠️ 发送失败：' + err, media_type: '', media_url: '' });

          });

      };

      reader.readAsDataURL(file);

    }

    function bindChatInput(chatId) {

      var text = document.getElementById(P + 'monitor-text');

      var sendBtn = document.getElementById(P + 'monitor-send-btn');

      var emojiBtn = document.getElementById(P + 'monitor-emoji-btn');

      var emojiPanel = document.getElementById(P + 'monitor-emoji-panel');

      var imgBtn = document.getElementById(P + 'monitor-img-btn');

      var imgInput = document.getElementById(P + 'monitor-img-input');

      if (text) {

        text.addEventListener('keydown', function (e) {

          if (e.key === 'Enter' && !e.shiftKey) {

            e.preventDefault();

            doSendText(chatId, text.value);

            text.value = '';

            text.style.height = 'auto';

          }

        });

        text.addEventListener('input', function () {

          text.style.height = 'auto';

          text.style.height = Math.min(text.scrollHeight, 120) + 'px';

        });

      }

      if (sendBtn) {

        sendBtn.addEventListener('click', function () {

          if (text) { doSendText(chatId, text.value); text.value = ''; text.style.height = 'auto'; }

        });

      }

      if (emojiBtn && emojiPanel) {

        var emojis = ['😀','😁','😂','🤣','😊','😍','😘','😎','🤔','😴','😭','😡','👍','👎','👏','🙏','💪','🎉','❤️','🔥','✨','🌹','💡','✅','❌','⚠️','🚀','💰','🍺','🍎','🐱','🌟'];

        emojiPanel.innerHTML = emojis.map(function (e) {

          return '<span class="emoji-item">' + e + '</span>';

        }).join('');

        emojiBtn.addEventListener('click', function (e) {

          e.stopPropagation();

          emojiPanel.style.display = emojiPanel.style.display === 'grid' ? 'none' : 'grid';

        });

        emojiPanel.querySelectorAll('.emoji-item').forEach(function (el) {

          el.addEventListener('click', function () {

            if (text) { text.value += el.textContent; text.focus(); }

          });

        });

      }

      function wireFile(btn, input, type) {

        if (!btn || !input) return;

        btn.addEventListener('click', function () { input.click(); });

        input.addEventListener('change', function () {

          if (input.files && input.files[0]) sendMedia(chatId, type, input.files[0]);

          input.value = '';

        });

      }

      wireFile(imgBtn, imgInput, 'image');

    }

    function selectSession(key) {

      activeSession = key;

      document.querySelectorAll('.monitor-item').forEach(function (el) {

        el.classList.toggle('active', el.getAttribute('data-key') === key);

      });

      var session = monitorSessions.find(function (s) { return s.key === key; });

      var main = document.getElementById(P + 'monitor-main');

      if (!main) return;

      if (!session) { main.innerHTML = '<div class="empty"><div class="title">会话不存在</div></div>'; return; }

      var openid = session.type === '群聊' ? '' : session.key.replace('usr:', '');

      var chatId = session.type === '群聊' ? ('g:' + session.name) : ('u:' + openid);

      activeChatId = chatId;

      var chatItems = messageItems.filter(function (it) {

        if (it.type === '系统') return false;

        if (session.type === '群聊') return (it.group_openid || it.scene) === session.name;

        return it.sender === openid;

      }).sort(function (a, b) {

        var t = String(a.ts).localeCompare(String(b.ts));

        if (t !== 0) return t;

        return (a.idx || 0) - (b.idx || 0);

      });

      activeChatItems = chatItems;

      var bubbles = chatItems.map(function (it) { return renderBubble(it); }).join('');

      var sessionDisplayName = session.displayName || session.name;

      var isGroupSession = session.type === '群聊';

      var editBtn = isGroupSession

        ? '<button type="button" class="ci-btn group-edit-name-btn" title="修改群名">✏️</button>'

        : '';

      main.innerHTML =

        '<div class="monitor-chat">' +

          '<div class="chat-head">' +

            avatarHtml(session.avatar, sessionDisplayName, 'large') +

            '<div style="flex:1;min-width:0;"><div class="name">' + escapeHtml(sessionDisplayName) + '</div>' +

            '<div class="id">' + (isGroupSession ? '群聊会话' : '单聊会话') + '</div></div>' +

            editBtn +

          '</div>' +

          '<div class="messages-wrap">' +

            '<div class="messages" id="' + P + 'monitor-messages">' + bubbles + '</div>' +

            '<div class="msg-scroll-nav">' +

              '<button type="button" id="' + P + 'monitor-scroll-top" class="msn-btn" title="回到顶部">↑</button>' +

              '<button type="button" id="' + P + 'monitor-scroll-bottom" class="msn-btn active" title="跳到最新消息">↓</button>' +

            '</div>' +

          '</div>' +

          '<div class="chat-input-bar">' +

            '<div class="emoji-wrap">' +

              '<button class="ci-btn" id="' + P + 'monitor-emoji-btn" type="button" title="表情">😊</button>' +

              '<div class="emoji-panel" id="' + P + 'monitor-emoji-panel"></div>' +

            '</div>' +

            '<button class="ci-btn" id="' + P + 'monitor-img-btn" type="button" title="图片">🖼️</button>' +

            '<input type="file" id="' + P + 'monitor-img-input" accept="image/*" hidden>' +

            '<textarea id="' + P + 'monitor-text" class="ci-text" rows="1" placeholder="输入消息，Enter 发送，Shift+Enter 换行"></textarea>' +

            '<button class="ci-send" id="' + P + 'monitor-send-btn" type="button">发送</button>' +

          '</div>' +

        '</div>';

      bindChatInput(chatId);

      wireScrollNav();

      scrollMessagesToBottom();

      // 群聊会话：绑定「修改群名」按钮

      if (isGroupSession) {

        var editBtnEl = main.querySelector('.group-edit-name-btn');

        if (editBtnEl) {

          editBtnEl.addEventListener('click', function () {

            var currentName = session.displayName || session.name || '';

            var newName = window.prompt('修改控制台显示的群名（仅本地显示，不影响QQ群）:', currentName);

            if (newName === null) return; // 用户取消

            newName = newName.trim();

            fetch(API_BASE + '/api/group-profile', {

              method: 'POST',

              headers: { 'Content-Type': 'application/json' },

              body: JSON.stringify({ openid: session.name, name: newName })

            })

              .then(function (r) {

                if (!r.ok) throw new Error('HTTP ' + r.status);

                return r.json();

              })

              .then(function (data) {

                if (data && data.ok) {

                  showToast('群名已保存 ✓');

                  // 立即更新当前会话显示

                  if (data.profile && data.profile.name) {

                    session.displayName = data.profile.name;

                    session.avatar = data.profile.avatar || session.avatar;

                  } else if (newName) {

                    session.displayName = newName;

                  }

                  // 重新加载群资料并刷新两侧列表与当前聊天头部

                  loadGroupProfiles().then(function () {

                    selectSession(session.key);

                    loadMonitorSessions();

                  });

                } else {

                  showToast('保存失败：' + (data && data.error ? data.error : '未知错误'));

                }

              })

              .catch(function () { showToast('保存失败：请确认机器人(bot)正在运行'); });

          });

        }

      }

    }

    if (fixedMode === 'monitor') document.getElementById(P + 'monitor-search').addEventListener('input', renderMonitorSessions);

    if (fixedMode === 'monitor') document.getElementById(P + 'monitor-bot-select').addEventListener('change', function () { updateBotStatusDot(P + 'monitor-bot-select', P + 'monitor-bot-dot'); loadMonitorSessions(); });

    // 同步一次机器人 select 状态点（首屏）

    try { updateBotStatusDot(botSelId, botDotId); } catch (e) {}

    // 加载已绑定 QQ 用户的真实资料（昵称/头像），并定时刷新

    // 间隔 10s：未绑 QQ 的用户走 OIAPI 反查，缓存命中后开销极低；

    // 太慢则单聊新会话需等很久才能拿到昵称（原 60s 太长）。

    // 首次先加载用户资料（OIAPI 反查）+ 群资料，再加载消息会话，

    // 确保会话列表第一次渲染时单聊用户就能拿到真实昵称，而非 C28490EC 这种 openid 截断

    // 单类型 monitor 页面才加载 monitor 会话；多类型（综合版）也加载；logs 页面不需加载 monitorSessions

    if (fixedMode === 'monitor') {

      Promise.all([loadUserProfiles(), loadGroupProfiles()]).then(function () {

        loadMonitorSessions();

      });

      setInterval(function () { loadUserProfiles(); }, 10000);

      setInterval(function () { loadGroupProfiles(); }, 60000);

    }

    // 定时刷新（仅在当前页可见时有效，但轮询本身轻量）

    var pageId = fixedMode === 'monitor'

      ? (P ? 'page-' + P.replace(/-$/, '') + '-monitor' : 'page-messages-monitor')

      : (P ? 'page-' + P.replace(/-$/, '') + '-logs' : 'page-messages-logs');

    setInterval(function () {

      var pageEl = document.getElementById(pageId);

      if (!pageEl || !pageEl.classList.contains('active')) return;

      if (fixedMode === 'logs') loadMessageLogs();

      else loadMonitorSessions();

    }, 3000);

    // 点击空白处收起表情面板

    document.addEventListener('click', function (e) {

      var panel = document.getElementById(P + 'monitor-emoji-panel');

      if (!panel || panel.style.display !== 'grid') return;

      var btn = document.getElementById(P + 'monitor-emoji-btn');

      if (e.target !== btn && !panel.contains(e.target)) panel.style.display = 'none';

    });

    // 初始化 tab UI

    updateTabUI();

    if (fixedMode === 'logs') {

      // 「查看」按钮 → 弹出消息详情 modal（修复：原先 data-idx 链接没有任何 click handler，点了什么也不会发生）

      var msgModal = document.getElementById('message-detail-modal');

      var msgBody = document.getElementById('message-detail-body');

      var msgHeader = msgModal ? msgModal.querySelector('.modal-header h2') : null;

      function mediaSrc(u) {

        if (!u) return '';

        if (typeof u === 'string' && (u.indexOf('data:') === 0 || u.indexOf('blob:') === 0)) return u;

        return API_BASE + u;

      }

      function renderMediaPreview(it) {

        var mt = it.media_type || '';

        var url = it.media_url || '';

        if (!mt || !url) {

          return '<div class="msg-content-text">' + escapeHtml(it.content || '(空)') + '</div>';

        }

        if (mt === 'image') {

          return '<img class="bubble-media" src="' + escapeHtml(mediaSrc(url)) +

            '" alt="图片" style="max-width:100%;border-radius:8px;display:block;">';

        }

        if (mt === 'voice') {

          return '<audio class="bubble-media" controls preload="metadata" src="' + escapeHtml(mediaSrc(url)) + '"></audio>';

        }

        if (mt === 'video') {

          return '<video class="bubble-media" controls preload="metadata" src="' + escapeHtml(mediaSrc(url)) +

            '" style="max-width:100%;border-radius:8px;display:block;"></video>';

        }

        return '<div class="msg-content-text">' + escapeHtml('[媒体] ' + (it.content || '')) + '</div>';

      }

      function rowKV(k, v, mono) {

        return '<div class="row"><div class="k">' + escapeHtml(k) +

          '</div><div class="v' + (mono ? ' mono' : '') + '">' + (v == null ? '-' : v) + '</div></div>';

      }

      function openMessageDetail(item) {

        if (!msgModal || !msgBody) return;

        var typeTxt = item.type === '群聊' ? '群聊消息' : (item.type === '单聊' ? '单聊消息' : '系统消息');

        if (msgHeader) msgHeader.textContent = typeTxt + ' #' + item.idx;

        var prof = item.sender ? profileOf(item.sender) : null;

        var dispName = (prof && prof.nickname) ? prof.nickname : (item.nickname || senderName(item));

        var gprof = item.group_openid ? groupProfileOf(item.group_openid) : null;

        var grpDispName = (gprof && gprof.name) ? gprof.name : (item.scene || item.group_openid || '-');

        var dirBadge = (item.direction === '上行')

          ? '<span class="tag-dir up">上行</span>'

          : (item.direction === '下行' ? '<span class="tag-dir down">下行</span>' : '<span class="tag-dir system">系统</span>');

        var rows = '';

        rows += rowKV('机器人', escapeHtml(botDisplayName(item.bot) || '-'));

        rows += rowKV('时间', escapeHtml(item.ts || '-'));

        if (item.type === '群聊') {

          rows += rowKV('群', escapeHtml(grpDispName));

          if (item.group_openid) rows += rowKV('群 OpenID', escapeHtml(item.group_openid), true);

        }

        if (item.type !== '系统') {

          rows += rowKV('发送者', '<div class="sender-cell">' +

            avatarHtml(item.avatar, dispName, '') +

            '<span>' + escapeHtml(dispName) + '</span></div>');

          rows += rowKV('方向', dirBadge);

          rows += rowKV('状态', escapeHtml(statusText(item.direction)));

        }

        if (item.scene && item.type !== '群聊') rows += rowKV('场景', escapeHtml(item.scene));

        if (item.sender && item.sender !== '-') rows += rowKV('OpenID', escapeHtml(item.sender), true);

        rows += rowKV('类型', escapeHtml(item.type || '-'));

        rows += '<div class="row" style="display:block;">' +

                  '<div class="k" style="margin:8px 0 6px 0;">消息内容</div>' +

                  '<div class="v msg-detail-content" style="padding:12px 14px;background:var(--bg-2);border-radius:8px;line-height:1.6;word-break:break-word;max-height:60vh;overflow:auto;">' +

                    renderMediaPreview(item) +

                  '</div>' +

                '</div>';

        msgBody.innerHTML = rows;

        msgModal.classList.add('active');

        requestAnimationFrame(function () { msgModal.classList.add('show'); });

      }

      function closeMessageDetail() {

        if (!msgModal) return;

        msgModal.classList.remove('show');

        setTimeout(function () { msgModal.classList.remove('active'); }, 200);

      }

      // 操作列事件委托：给 logs 模式的 3 个 tbody 全部绑定（虽然页面只显示一个）

      ['c2c', 'group', 'event'].forEach(function (tab) {

        var tb = document.getElementById(P + 'msg-tbody-' + tab);

        if (!tb) return;

        tb.addEventListener('click', function (e) {

          var el = e.target.closest ? e.target.closest('.op-link') : null;

          if (!el) return;

          var act = el.getAttribute('data-act');

          if (act !== 'view') return;

          var idx = parseInt(el.getAttribute('data-idx'), 10);

          var item = null;

          for (var i = 0; i < logsLastItems.length; i++) {

            if (logsLastItems[i].idx === idx) { item = logsLastItems[i]; break; }

          }

          if (item) openMessageDetail(item);

        });

      });

      var closeX = document.getElementById('message-detail-close');

      var closeBtn = document.getElementById('message-detail-close-btn');

      if (closeX) closeX.addEventListener('click', closeMessageDetail);

      if (closeBtn) closeBtn.addEventListener('click', closeMessageDetail);

      if (msgModal) msgModal.addEventListener('click', function (e) {

        if (e.target === msgModal) closeMessageDetail();

      });

      // Esc 关闭：全局只绑一次（多个 createChatCenter 实例共享），后续实例直接复用

      if (msgModal && !window.__msgDetailEscBound) {

        window.__msgDetailEscBound = true;

        document.addEventListener('keydown', function (e) {

          if (e.key !== 'Escape' && e.key !== 'Esc') return;

          var m = document.getElementById('message-detail-modal');

          if (m && m.classList.contains('active')) {

            m.classList.remove('show');

            setTimeout(function () { m.classList.remove('active'); }, 200);

          }

        });

      }

    }

  }

  // 实例化：4 个新页面（单聊/群聊 × 消息记录/实时监控）

  createChatCenter({ prefix: 'c2c-', mode: 'logs', type: 'c2c' });

  createChatCenter({ prefix: 'group-', mode: 'logs', type: 'group' });

  createChatCenter({ prefix: 'c2c-', mode: 'monitor', type: 'c2c' });

  createChatCenter({ prefix: 'group-', mode: 'monitor', type: 'group' });

  // ============================================================

  // 成员管理

  // ============================================================

  (function membersCenter() {

    var botSel = document.getElementById('mem-bot-select');

    var grpSel = document.getElementById('mem-group-select');

    var roleSel = document.getElementById('mem-role-select');

    var searchInput = document.getElementById('mem-search');

    var searchBtn = document.getElementById('mem-search-btn');

    var resetBtn = document.getElementById('mem-reset-btn');

    var tbody = document.getElementById('mem-tbody');

    var emptyEl = document.getElementById('mem-empty');

    var countLabel = document.getElementById('members-count-label');

    var lastItems = [];

    function avatarHtml(avatar, name, sizeClass) {

      var initial = (name && name !== '(未命名)') ? name.charAt(0) : '?';

      var inner = avatar

        ? '<img src="' + escapeHtml(avatar) + '" onerror="this.style.display=\'none\'" alt=""/>'

        : '<span class="avatar-fallback">' + escapeHtml(initial) + '</span>';

      return '<span class="avatar-wrap ' + (sizeClass || '') + '">' + inner + '</span>';

    }

    function truncate(s, n) {

      s = String(s == null ? '' : s);

      return s.length > n ? s.slice(0, n) + '…' : s;

    }

    function buildQuery() {

      var p = [];

      if (botSel && botSel.value) p.push('bot=' + encodeURIComponent(botSel.value));

      if (grpSel.value) p.push('group=' + encodeURIComponent(grpSel.value));

      if (roleSel.value) p.push('group_role=' + encodeURIComponent(roleSel.value));

      var kw = (searchInput.value || '').trim();

      if (kw) p.push('keyword=' + encodeURIComponent(kw));

      return p.join('&');

    }

    function loadMembers() {

      var url = API_BASE + '/api/members' + (buildQuery() ? ('?' + buildQuery()) : '');

      fetch(url, { cache: 'no-store' })

        .then(function (r) { return r.json(); })

        .then(function (data) { renderMembers(data || {}); })

        .catch(function () {

          tbody.innerHTML = '<tr><td colspan="11" class="table-empty">加载失败，请检查服务</td></tr>';

        });

    }

    function syncOptions(sel, values, defaultLabel) {

      var cur = sel.value;

      sel.innerHTML = '<option value="">' + defaultLabel + '</option>';

      values.forEach(function (v) {

        var o = document.createElement('option');

        o.value = v; o.textContent = v;

        sel.appendChild(o);

      });

      if (cur) {

        var found = false;

        for (var i = 0; i < sel.options.length; i++) {

          if (sel.options[i].value === cur) { found = true; break; }

        }

        if (found) sel.value = cur;

      }

    }

    function renderMembers(data) {

      var items = data.items || [];

      lastItems = items;

      var total = (data.total != null) ? data.total : items.length;

      var curBot = (botSel && botSel.value) ? botSel.value : '全部机器人';

      if (countLabel) countLabel.textContent = curBot + ' · ' + total + ' 人';

      if (botSel) syncOptions(botSel, data.bots || [], '全部机器人');

      syncOptions(grpSel, data.groups || [], '全部群');

      if (!items.length) {

        tbody.innerHTML = '';

        emptyEl.style.display = 'flex';

        return;

      }

      emptyEl.style.display = 'none';

      var rows = items.map(function (m) {

        var nick = m.nickname || '(未命名)';

        var sender = '<div class="sender-cell">' + avatarHtml(m.avatar, nick, '') +

          '<span>' + escapeHtml(nick) + '</span></div>';

        return '<tr>' +

          '<td class="col-check"><input type="checkbox" class="mem-check" value="' + escapeHtml(m.openid) + '"></td>' +

          '<td class="col-idx">' + m.idx + '</td>' +

          '<td>' + escapeHtml(m.bot || '-') + '</td>' +

          '<td>' + sender + '</td>' +

          '<td>' + escapeHtml(m.code || '-') + '</td>' +

          '<td title="' + escapeHtml(m.openid || '') + '">' + escapeHtml(truncate(m.openid, 16)) + '</td>' +

          '<td>' + escapeHtml(m.real_qq || '-') + '</td>' +

          '<td>' + escapeHtml(m.role || '-') + '</td>' +

          '<td>' + escapeHtml(m.group_role || '-') + '</td>' +

          '<td>' + escapeHtml(m.source || '-') + '</td>' +

          '<td>' + escapeHtml(m.level || '-') + '</td>' +

          '<td class="col-op">' +

            '<span class="op-link" data-act="view" data-idx="' + m.idx + '">查看</span> ' +

            '<span class="op-link" data-act="unbind" data-openid="' + escapeHtml(m.openid) + '">解绑</span> ' +

            '<span class="op-link op-danger" data-act="delete" data-openid="' + escapeHtml(m.openid) + '" data-name="' + escapeHtml(nick) + '">删除</span>' +

          '</td>' +

        '</tr>';

      }).join('');

      tbody.innerHTML = rows;

      // ===== 成员批量删除选择模式 =====
      var _memTableEl = document.getElementById('mem-table');
      var _memBtnDel = document.getElementById('mem-batch-delete');
      var _memBtnCancel = document.getElementById('mem-batch-cancel');
      var _memBtnConfirm = document.getElementById('mem-batch-confirm');
      var _memBatchBound = false;
      function _memRefreshBatchCount() {
        if (!_memBtnConfirm) return;
        var n = document.querySelectorAll('.mem-check:checked').length;
        _memBtnConfirm.textContent = '确认删除 (' + n + ')';
        _memBtnConfirm.disabled = n === 0;
        var _all = document.getElementById('mem-check-all');
        if (_all) {
          var tot = document.querySelectorAll('.mem-check').length;
          _all.checked = tot > 0 && n === tot;
          _all.indeterminate = n > 0 && n < tot;
        }
      }
      function _memEnterSelect() {
        if (_memTableEl) _memTableEl.classList.add('in-select');
        if (_memBtnDel) _memBtnDel.style.display = 'none';
        if (_memBtnCancel) _memBtnCancel.style.display = '';
        if (_memBtnConfirm) _memBtnConfirm.style.display = '';
        _memRefreshBatchCount();
      }
      function _memExitSelect() {
        if (_memTableEl) _memTableEl.classList.remove('in-select');
        var ck = document.querySelectorAll('.mem-check');
        for (var _i = 0; _i < ck.length; _i++) ck[_i].checked = false;
        if (_memBtnDel) _memBtnDel.style.display = '';
        if (_memBtnCancel) _memBtnCancel.style.display = 'none';
        if (_memBtnConfirm) _memBtnConfirm.style.display = 'none';
      }
      if (!_memBatchBound) {
        _memBatchBound = true;
        var _memAll = document.getElementById('mem-check-all');
        if (_memAll) _memAll.addEventListener('change', function () {
          var ck = document.querySelectorAll('.mem-check');
          for (var _j = 0; _j < ck.length; _j++) ck[_j].checked = _memAll.checked;
          _memRefreshBatchCount();
        });
        if (_memBtnDel) _memBtnDel.addEventListener('click', _memEnterSelect);
        if (_memBtnCancel) _memBtnCancel.addEventListener('click', _memExitSelect);
        if (_memBtnConfirm) _memBtnConfirm.addEventListener('click', function () {
          var oids = [];
          var ck = document.querySelectorAll('.mem-check:checked');
          for (var _k = 0; _k < ck.length; _k++) if (ck[_k].value) oids.push(ck[_k].value);
          if (!oids.length) { alert('请先勾选至少 1 个成员'); return; }
          if (!window.confirm('确认批量删除 ' + oids.length + ' 个成员？该操作不可撤销。')) return;
          _memBtnConfirm.disabled = true;
          var _t = _memBtnConfirm.textContent;
          _memBtnConfirm.textContent = '删除中…';
          fetch(API_BASE + '/api/members/delete-batch', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ openids: oids })
          })
            .then(function (r) { return r.json(); })
            .then(function (res) {
              if (res && res.ok) {
                var failed = (res.failed_count || 0);
                alert('已删除 ' + res.deleted_count + ' 个成员' + (failed ? ('；' + failed + ' 个不存在') : ''));
                _memExitSelect();
                loadMembers();
              } else {
                alert('删除失败：' + ((res && res.error) || '未知错误'));
              }
              _memBtnConfirm.disabled = false;
              _memBtnConfirm.textContent = _t;
              _memRefreshBatchCount();
            })
            .catch(function (e) { alert('请求失败：' + e); _memBtnConfirm.textContent = _t; _memRefreshBatchCount(); });
        });
      }
      var _memCks = document.querySelectorAll('.mem-check');
      for (var _mci = 0; _mci < _memCks.length; _mci++) {
        _memCks[_mci].addEventListener('change', _memRefreshBatchCount);
      }
      _memRefreshBatchCount();

    }

    function openMemberModal(m) {

      var modal = document.getElementById('member-modal');

      if (!modal) return;

      var groups = (m.groups && m.groups.length) ? m.groups.join('<br/>') : '-';

      var body = document.getElementById('member-detail-body');

      body.innerHTML =

        '<div class="row"><div class="k">机器人</div><div class="v">' + escapeHtml(m.bot || '-') + '</div></div>' +

        '<div class="row"><div class="k">昵称</div><div class="v" id="member-detail-nick">' + escapeHtml(m.nickname || '(未命名)') + '</div></div>' +

        '<div class="row"><div class="k">编号</div><div class="v">' + escapeHtml(m.code || '-') + '</div></div>' +

        '<div class="row"><div class="k">成员OpenID</div><div class="v mono">' + escapeHtml(m.openid || '-') + '</div></div>' +

        '<div class="row"><div class="k">真实QQ号</div><div class="v">' + escapeHtml(m.real_qq || '-') + '</div></div>' +

        '<div class="row"><div class="k">角色</div><div class="v">' + escapeHtml(m.role || '-') + '</div></div>' +

        '<div class="row"><div class="k">群角色</div><div class="v">' + escapeHtml(m.group_role || '-') + '</div></div>' +

        '<div class="row"><div class="k">来源</div><div class="v">' + escapeHtml(m.source || '-') + '</div></div>' +

        '<div class="row"><div class="k">等级</div><div class="v">' + escapeHtml(m.level || '-') + '</div></div>' +

        '<div class="row"><div class="k">群列表</div><div class="v mono">' + groups + '</div></div>' +

        '<div class="row"><div class="k">消息数</div><div class="v">' + (m.msg_count || 0) + '</div></div>';

      // 把当前成员 openid 注入到「反查昵称」按钮的 data-openid 属性

      var _fetchBtn = document.getElementById('member-fetch-nickname-btn');

      if (_fetchBtn) _fetchBtn.setAttribute('data-openid', m.openid || '');

      modal.classList.add('active');

      requestAnimationFrame(function () { modal.classList.add('show'); });

    }

    function closeMemberModal() {

      var modal = document.getElementById('member-modal');

      if (!modal) return;

      modal.classList.remove('show');

      setTimeout(function () { modal.classList.remove('active'); }, 200);

    }

    function unbindMember(openid) {

      fetch(API_BASE + '/api/members/unbind', {

        method: 'POST',

        headers: { 'Content-Type': 'application/json' },

        body: JSON.stringify({ openid: openid })

      })

        .then(function (r) { return r.json(); })

        .then(function (res) {

          if (res && res.ok) { loadMembers(); }

          else { alert((res && res.error) || '解绑失败'); }

        })

        .catch(function () { alert('解绑请求失败'); });

    }

    function deleteMember(openid, name) {

      fetch(API_BASE + '/api/members/delete', {

        method: 'POST',

        headers: { 'Content-Type': 'application/json' },

        body: JSON.stringify({ openid: openid })

      })

        .then(function (r) { return r.json(); })

        .then(function (res) {

          if (res && res.ok) { loadMembers(); }

          else { alert((res && res.error) || '删除失败'); }

        })

        .catch(function () { alert('删除请求失败'); });

    }

    function fetchNickname(openid) {

      fetch(API_BASE + '/api/members/fetch_nickname', {

        method: 'POST',

        headers: { 'Content-Type': 'application/json' },

        body: JSON.stringify({ openid: openid })

      })

        .then(function (r) { return r.json(); })

        .then(function (res) {

          if (res && res.ok) {

            // 更新弹窗中昵称显示

            var nickEl = document.getElementById('member-detail-nick');

            if (nickEl) nickEl.textContent = res.nickname || '(未命名)';

            // 刷新成员列表

            if (typeof loadMembersRef === 'function') loadMembersRef();

            try { showToast && showToast('已反查昵称：' + res.nickname, 'success'); } catch (e) {}

          } else {

            alert((res && res.error) || '反查失败');

          }

        })

        .catch(function () { alert('反查请求失败'); });

    }

    // 操作列事件委托

    tbody.addEventListener('click', function (e) {

      var el = e.target.closest ? e.target.closest('.op-link') : null;

      if (!el) return;

      var act = el.getAttribute('data-act');

      if (act === 'view') {

        var idx = parseInt(el.getAttribute('data-idx'), 10);

        var m = null;

        for (var i = 0; i < lastItems.length; i++) {

          if (lastItems[i].idx === idx) { m = lastItems[i]; break; }

        }

        if (m) openMemberModal(m);

      } else if (act === 'unbind') {

        var openid = el.getAttribute('data-openid');

        if (openid && window.confirm('确定解绑该成员的真实QQ号？')) {

          unbindMember(openid);

        }

      } else if (act === 'delete') {

        var openid = el.getAttribute('data-openid');

        var name = el.getAttribute('data-name') || '该成员';

        if (openid && window.confirm('确定要删除成员「' + name + '」吗？\\n\\n该操作会从成员库中彻底移除该成员（含头像缓存、真实QQ号绑定），且不可恢复。')) {

          deleteMember(openid, name);

        }

      }

    });

    // 筛选交互

    if (roleSel) roleSel.addEventListener('change', loadMembers);

    if (grpSel) grpSel.addEventListener('change', loadMembers);

    if (botSel) botSel.addEventListener('change', loadMembers);

    if (searchBtn) searchBtn.addEventListener('click', loadMembers);

    if (searchInput) searchInput.addEventListener('keydown', function (e) {

      if (e.key === 'Enter') loadMembers();

    });

    if (resetBtn) resetBtn.addEventListener('click', function () {

      if (botSel) botSel.value = '';

      if (grpSel) grpSel.value = '';

      if (roleSel) roleSel.value = '';

      if (searchInput) searchInput.value = '';

      loadMembers();

    });

    // 弹窗关闭

    var mClose = document.getElementById('member-modal-close');

    var mCloseBtn = document.getElementById('member-close-btn');

    var fetchNickBtn = document.getElementById('member-fetch-nickname-btn');

    if (mClose) mClose.addEventListener('click', closeMemberModal);

    if (mCloseBtn) mCloseBtn.addEventListener('click', closeMemberModal);

    if (fetchNickBtn) fetchNickBtn.addEventListener('click', function () {

      var openid = (fetchNickBtn.getAttribute('data-openid') || '').trim();

      if (!openid) { alert('未找到成员 openid'); return; }

      if (!window.confirm('将通过 OIAPI 官方接口反查该成员的昵称，确定继续？')) return;

      fetchNickname(openid);

    });

    // 暴露给 switchPage

    loadMembersRef = loadMembers;

  })();

  // ============================================================

  // 用户分析

  // ============================================================

  (function profilesCenter() {

    var botSel = document.getElementById('profile-bot-select');

    var refreshBtn = document.getElementById('profile-refresh-btn');

    var emptyState = document.getElementById('profile-empty-state');

    var content = document.getElementById('profile-content');

    var kpiGrid = document.getElementById('profile-kpi-grid');

    function syncOptions(sel, values, defaultLabel) {

      var cur = sel.value;

      sel.innerHTML = '<option value="">' + defaultLabel + '</option>';

      values.forEach(function (v) {

        var o = document.createElement('option');

        o.value = v; o.textContent = v;

        sel.appendChild(o);

      });

      if (cur) {

        var found = false;

        for (var i = 0; i < sel.options.length; i++) {

          if (sel.options[i].value === cur) { found = true; break; }

        }

        if (found) sel.value = cur;

      }

    }

    function renderBarChart(containerId, dataMap, colorClassPrefix) {

      var container = document.getElementById(containerId);

      if (!container) return;

      var keys = Object.keys(dataMap || {});

      if (!keys.length) {

        container.innerHTML = '<div class="table-empty">暂无数据</div>';

        return;

      }

      var max = Math.max.apply(null, keys.map(function (k) { return dataMap[k]; }));

      max = max || 1;

      var html = '<div class="bar-chart">';

      keys.forEach(function (k) {

        var val = dataMap[k] || 0;

        var pct = Math.round((val / max) * 100);

        var extraCls = colorClassPrefix ? (colorClassPrefix + escapeHtml(k)) : '';

        html +=

          '<div class="bar-row">' +

            '<div class="bar-label" title="' + escapeHtml(k) + '">' + escapeHtml(k) + '</div>' +

            '<div class="bar-track"><div class="bar-fill ' + extraCls + '" style="width:' + pct + '%"></div></div>' +

            '<div class="bar-value">' + val + '</div>' +

          '</div>';

      });

      html += '</div>';

      container.innerHTML = html;

    }

    function showEmpty() {

      emptyState.style.display = 'block';

      content.style.display = 'none';

    }

    function showContent() {

      emptyState.style.display = 'none';

      content.style.display = 'block';

    }

    function renderProfile(data) {

      if (!data.ok) {

        showEmpty();

        return;

      }

      showContent();

      syncOptions(botSel, data.bots || [], '全部');

      var total = data.total || 0;

      var active = data.active_today || 0;

      var src = data.source_counts || {};

      var grp = data.group_role_counts || {};

      kpiGrid.innerHTML =

        '<div class="profile-kpi-card"><div class="label">用户总数</div><div class="value accent">' + total + '</div></div>' +

        '<div class="profile-kpi-card"><div class="label">今日活跃</div><div class="value">' + active + '</div></div>' +

        '<div class="profile-kpi-card"><div class="label">单聊用户</div><div class="value">' + (src['单聊'] || 0) + '</div></div>' +

        '<div class="profile-kpi-card"><div class="label">群聊用户</div><div class="value">' + (src['群聊'] || 0) + '</div></div>';

      renderBarChart('profile-source-chart', src, '');

      renderBarChart('profile-role-chart', grp, 'role-');

      renderBarChart('profile-level-chart', data.level_counts || {}, '');

    }

    function getBot() {

      if (botSel.value) return botSel.value;

      // 全部/未选时默认取第一个真实机器人（单 bot 模式）

      for (var i = 0; i < botSel.options.length; i++) {

        if (botSel.options[i].value) return botSel.options[i].value;

      }

      return '';

    }

    function loadProfiles() {

      var bot = getBot();

      if (!bot) {

        showEmpty();

        return;

      }

      fetch(API_BASE + '/api/profiles?bot=' + encodeURIComponent(bot), { cache: 'no-store' })

        .then(function (r) { return r.json(); })

        .then(function (data) { renderProfile(data || {}); })

        .catch(function () {

          kpiGrid.innerHTML = '<div class="table-empty">加载失败，请检查服务</div>';

        });

    }

    // 刷新按钮

    if (refreshBtn) refreshBtn.addEventListener('click', loadProfiles);

    // 切换机器人时自动刷新

    if (botSel) botSel.addEventListener('change', function () { updateBotStatusDot('profile-bot-select', 'profile-bot-dot'); loadProfiles(); });

    // 切到该页时：填充下拉并自动加载（全部=默认第一个机器人）

    function onShow() {

      fetch(API_BASE + '/api/profiles?bot=', { cache: 'no-store' })

        .then(function (r) { return r.json(); })

        .then(function (data) {

          syncOptions(botSel, (data && data.bots) || [], '全部');

          updateBotStatusDot('profile-bot-select', 'profile-bot-dot');

          loadProfiles();

        })

        .catch(function () {

          syncOptions(botSel, ['小流萤'], '全部');

          loadProfiles();

        });

    }

    // 暴露给 switchPage

    loadProfilesRef = onShow;

  })();

  // ============================================================

  // 群管理：群列表

  // ============================================================

  (function groupsCenter() {

    var botSel = document.getElementById('grp-bot-select');

    var keywordInput = document.getElementById('grp-keyword');

    var searchBtn = document.getElementById('grp-search-btn');

    var resetBtn = document.getElementById('grp-reset-btn');

    var tbody = document.getElementById('groups-tbody');

    var tableWrap = document.getElementById('groups-table-wrap');

    var emptyEl = document.getElementById('groups-empty');

    var summaryEl = document.getElementById('groups-summary');

    var lastItems = []; // 缓存当前列表，用于操作列按 idx 取详情

    function buildQuery() {

      var params = [];

      if (botSel && botSel.value) params.push('bot=' + encodeURIComponent(botSel.value));

      if (keywordInput && keywordInput.value.trim()) params.push('keyword=' + encodeURIComponent(keywordInput.value.trim()));

      return params.length ? ('?' + params.join('&')) : '';

    }

    // 同步下拉选项（保留当前选中值；与 profilesCenter 的同名函数实现一致，独立 IIFE 内重复声明以确保闭包可见）

    function syncOptions(sel, values, defaultLabel) {

      if (!sel) return;

      var cur = sel.value;

      sel.innerHTML = '<option value="">' + defaultLabel + '</option>';

      (values || []).forEach(function (v) {

        var o = document.createElement('option');

        o.value = v; o.textContent = v;

        sel.appendChild(o);

      });

      if (cur) {

        var found = false;

        for (var i = 0; i < sel.options.length; i++) {

          if (sel.options[i].value === cur) { found = true; break; }

        }

        if (found) sel.value = cur;

      }

    }

    var _prefetchRunning = false;
    var _grpBatchBound = false;

    // 后台预拉官方群信息：未缓存的优先 + 缓存超过 STALE_MS 的次之；
    // 单次非限流失败不中断继续下一个；真 QPM 限流则停；全部完成后才 loadGroups()
    var PREFETCH_STALE_MS = 30 * 60 * 1000; // 30 分钟
    function prefetchOfficial() {
      if (_prefetchRunning) return;
      var now = Date.now();
      var pending = (lastItems || [])
        .filter(function (g) { return !!g.openid; })
        .map(function (g) {
          var ts = (g.official_info && g.official_info.ts) || 0;
          var fresh = !!g.official_info && (now - ts) < PREFETCH_STALE_MS;
          return { openid: g.openid, fresh: fresh, ts: ts };
        })
        .filter(function (x) { return !x.fresh; })
        .sort(function (a, b) { return a.ts - b.ts; }); // 越旧的先刷新
      if (!pending.length) return;
      _prefetchRunning = true;
      var okCount = 0;
      var i = 0;
      function fire() {
        if (i >= pending.length) { _prefetchRunning = false; if (okCount > 0) loadGroups(); return; }
        var oid = pending[i++].openid;
        fetch(API_BASE + '/api/group/official-info?openid=' + encodeURIComponent(oid) + '&refresh=1', { cache: 'no-store' })
          .then(function (r) { return r.json(); })
          .then(function (res) {
            if (res && res.ok) { okCount++; setTimeout(fire, 500); }
            else if (res && res.err === 'qpm') { _prefetchRunning = false; if (okCount > 0) loadGroups(); }
            else { setTimeout(fire, 800); } // 普通失败：跳过继续
          })
          .catch(function () { setTimeout(fire, 800); });
      }
      setTimeout(fire, 300);
    }

    function renderGroups(data) {

      try {

      var items = data.items || [];

      var total = (data.total != null) ? data.total : items.length;

      var bots = data.bots || [];

      if (summaryEl) {

        summaryEl.innerHTML = '<span class="dot"></span><span>' +

          (botSel && botSel.value ? escapeHtml(botSel.value) : '全部机器人') +

          ' · ' + total + ' 个群</span>';

      }

      syncOptions(botSel, bots, '全部机器人');

      if (!items.length) {

        if (tableWrap) tableWrap.style.display = 'none';

        if (emptyEl) emptyEl.style.display = 'flex';

        lastItems = [];

        return;

      }

      if (tableWrap) tableWrap.style.display = 'block';

      if (emptyEl) emptyEl.style.display = 'none';

      var rows = items.map(function (g, idx) {

        g.idx = idx + 1; // 用于按 idx 回查

        return '<tr>' +

          '<td class="col-check"><input type="checkbox" class="grp-check" value="' + escapeHtml(g.openid || '') + '"></td>' +

          '<td class="col-idx">' + (idx + 1) + '</td>' +

          '<td>' + escapeHtml(g.bot || '-') + '</td>' +

          '<td>' + escapeHtml(g.name || '-') + '</td>' +

          '<td class="mono" title="' + escapeHtml(g.openid || '') + '">' + escapeHtml(truncate(g.openid, 18)) + '</td>' +

          '<td>' + escapeHtml(g.real_qq || '-') + '</td>' +

          '<td>' + (g.official_info
            ? '<span class="off-badge ok" title="已缓存官方群信息（24h 内有效，来源 QQ 官方 /v2/groups/info）">官方✓</span>'
            : '<span class="off-badge no" title="尚未缓存官方群信息，可在群详情中点击刷新">未缓存</span>') + '</td>' +

          '<td>' + (g.member_count || 0) + '</td>' +

          '<td>' + (g.message_count || 0) + '</td>' +

          '<td>' + escapeHtml(g.last_message || '-') + '</td>' +

          '<td class="col-op">' +

            '<span class="op-link" data-act="view" data-idx="' + (idx + 1) + '">查看</span> ' +

            '<span class="op-link op-danger" data-act="delete" data-openid="' + escapeHtml(g.openid || '') + '" data-name="' + escapeHtml(g.name || '') + '">删除</span>' +

          '</td>' +

        '</tr>';

      }).join('');

      if (tbody) tbody.innerHTML = rows;

      lastItems = items;

      if (!_prefetchRunning) prefetchOfficial();

      // ===== 群管理多选删除 UX =====
      var _grpTableEl = document.querySelector('#groups-table-wrap table');
      var _batchBtnDel = document.getElementById('grp-batch-delete');
      var _batchBtnCancel = document.getElementById('grp-batch-cancel');
      var _batchBtnConfirm = document.getElementById('grp-batch-confirm');
      function _grpRefreshBatchCount() {
        if (!_batchBtnConfirm) return;
        var n = document.querySelectorAll('.grp-check:checked').length;
        _batchBtnConfirm.textContent = '确认删除 (' + n + ')';
        _batchBtnConfirm.disabled = n === 0;
        var _all = document.getElementById('grp-check-all');
        if (_all) {
          var tot = document.querySelectorAll('.grp-check').length;
          _all.checked = tot > 0 && n === tot;
          _all.indeterminate = n > 0 && n < tot;
        }
      }
      function _grpEnterSelect() {
        if (_grpTableEl) _grpTableEl.classList.add('in-select');
        if (_batchBtnDel) _batchBtnDel.style.display = 'none';
        if (_batchBtnCancel) _batchBtnCancel.style.display = '';
        if (_batchBtnConfirm) _batchBtnConfirm.style.display = '';
        _grpRefreshBatchCount();
      }
      function _grpExitSelect() {
        if (_grpTableEl) _grpTableEl.classList.remove('in-select');
        var ck = document.querySelectorAll('.grp-check');
        for (var _i = 0; _i < ck.length; _i++) ck[_i].checked = false;
        if (_batchBtnDel) _batchBtnDel.style.display = '';
        if (_batchBtnCancel) _batchBtnCancel.style.display = 'none';
        if (_batchBtnConfirm) _batchBtnConfirm.style.display = 'none';
      }
      if (!_grpBatchBound) {
        _grpBatchBound = true;
        var _allx = document.getElementById('grp-check-all');
        if (_allx) _allx.addEventListener('change', function () {
          var ck = document.querySelectorAll('.grp-check');
          for (var _j = 0; _j < ck.length; _j++) ck[_j].checked = _allx.checked;
          _grpRefreshBatchCount();
        });
        if (_batchBtnDel) _batchBtnDel.addEventListener('click', _grpEnterSelect);
        if (_batchBtnCancel) _batchBtnCancel.addEventListener('click', _grpExitSelect);
        if (_batchBtnConfirm) _batchBtnConfirm.addEventListener('click', function () {
          var oids = [];
          var ck = document.querySelectorAll('.grp-check:checked');
          for (var _k = 0; _k < ck.length; _k++) if (ck[_k].value) oids.push(ck[_k].value);
          if (!oids.length) { alert('请先勾选至少 1 个群'); return; }
          if (!window.confirm('确认批量删除 ' + oids.length + ' 个群？该操作不可撤销。')) return;
          _batchBtnConfirm.disabled = true;
          var _t = _batchBtnConfirm.textContent;
          _batchBtnConfirm.textContent = '删除中…';
          fetch(API_BASE + '/api/group/delete-batch', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ openids: oids })
          })
            .then(function (r) { return r.json(); })
            .then(function (res) {
              if (res && res.ok) {
                var failed = (res.failed_count || 0);
                alert('已删除 ' + res.deleted_count + ' 个群' + (failed ? ('；' + failed + ' 个失败') : ''));
                _grpExitSelect();
                loadGroups();
              } else {
                alert('删除失败：' + ((res && res.error) || '未知错误'));
              }
              _batchBtnConfirm.disabled = false;
              _batchBtnConfirm.textContent = _t;
              _grpRefreshBatchCount();
            })
            .catch(function (e) { alert('请求失败：' + e); _batchBtnConfirm.textContent = _t; _grpRefreshBatchCount(); });
        });
      }
      // 每次渲染后：挂行 checkbox 监听 + 刷新计数
      var _cks = document.querySelectorAll('.grp-check');
      for (var _ci = 0; _ci < _cks.length; _ci++) {
        _cks[_ci].addEventListener('change', _grpRefreshBatchCount);
      }
      _grpRefreshBatchCount();

      } catch (e) {

        console.error('[groups] renderGroups 失败:', e, e && e.stack, data);

        if (tbody) tbody.innerHTML = '<tr><td colspan="11" class="table-empty">渲染失败：' +

          escapeHtml(e && e.message ? e.message : String(e)) + '</td></tr>';

      }

    }

    function loadGroups() {

      if (tbody) tbody.innerHTML = '<tr><td colspan="11" class="table-empty">加载中…</td></tr>';

      fetch(API_BASE + '/api/groups' + buildQuery(), { cache: 'no-store' })

        .then(function (r) {

          if (!r.ok) throw new Error('HTTP ' + r.status + ' ' + (r.statusText || ''));

          return r.text().then(function (txt) {

            if (!txt) throw new Error('响应为空');

            try { return JSON.parse(txt); }

            catch (je) { throw new Error('JSON 解析失败：' + je.message + '（body 前 80 字：' + txt.slice(0, 80) + '）'); }

          });

        })

        .then(function (data) { renderGroups(data || {}); })

        .catch(function (e) {

          console.error('[groups] loadGroups 失败:', e);

          if (tbody) tbody.innerHTML = '<tr><td colspan="11" class="table-empty">加载失败：' +

            escapeHtml(e && e.message ? e.message : String(e)) + '</td></tr>';

        });

    }

    // 群详情弹窗

    function openGroupModal(g) {

      var modal = document.getElementById('group-modal');

      var body = document.getElementById('group-detail-body');

      if (!modal || !body) return;

      body.innerHTML = '<div style="padding: 20px 0; text-align: center; color: var(--muted);">加载中…</div>';

      modal.classList.add('active');

      requestAnimationFrame(function () { modal.classList.add('show'); });

      // 如果该群已有官方信息但超过 30 分钟，后台无感刷新（不阻塞弹窗渲染）
      try {
        var _gi = g && g.official_info;
        if (_gi && _gi.ts && (Date.now() - _gi.ts) > 30 * 60 * 1000) {
          fetch(API_BASE + '/api/group/official-info?openid=' + encodeURIComponent(g.openid) + '&refresh=1', { cache: 'no-store' })
            .then(function(rr){ return rr.json(); })
            .then(function(res){ if (res && res.ok) loadGroups(); });
        }
      } catch (_) {}

      fetch(API_BASE + '/api/group/detail?openid=' + encodeURIComponent(g.openid), { cache: 'no-store' })

        .then(function (r) {

          if (!r.ok) throw new Error('HTTP ' + r.status + ' ' + (r.statusText || ''));

          return r.json();

        })

        .then(function (res) {

          if (!res || !res.ok) throw new Error((res && res.error) || '加载失败');

          var grp = res.group || {};

          var members = res.members || [];

          var initial = (grp.name || '群').slice(0, 1).toUpperCase();

          var avatarHtml = grp.avatar

            ? '<img src="' + escapeHtml(grp.avatar) + '" alt="" onerror="this.parentNode.textContent=\'' + escapeHtml(initial) + '\'"/>'

            : escapeHtml(initial);

          var memberItems = members.map(function (m) {

            return '<li>' +

              '<span class="nick" title="' + escapeHtml(m.openid || '') + '">' + escapeHtml(m.nickname || '(未命名)') + '</span>' +

              '<span class="msgs">' + (m.msg_count || 0) + ' 条</span>' +

              '<span class="oid">' + escapeHtml(truncate(m.openid, 10)) + '</span>' +

            '</li>';

          }).join('');

          body.innerHTML =

            '<div class="grp-head">' +

              '<div class="grp-avatar">' + avatarHtml + '</div>' +

              '<div>' +

                '<div class="grp-name">' + escapeHtml(grp.name || '-') + '</div>' +

                '<div class="grp-sub">OpenID ' + escapeHtml(truncate(grp.openid, 24)) + '</div>' +

              '</div>' +

            '</div>' +

            '<div class="row"><div class="k">机器人</div><div class="v">' + escapeHtml(grp.bot || '-') + '</div></div>' +

            '<div class="row"><div class="k">群 OpenID</div><div class="v mono">' + escapeHtml(grp.openid || '-') + '</div></div>' +

            '<div class="row"><div class="k">真实QQ群号</div><div class="v">' + escapeHtml(grp.real_qq || '-') + '</div></div>' +

            '<div class="row"><div class="k">成员数</div><div class="v">' + (grp.member_count || 0) + '</div></div>' +

            '<div class="row"><div class="k">消息总数</div><div class="v">' + (grp.message_count || 0) + '</div></div>' +

            '<div class="row"><div class="k">最后消息</div><div class="v">' + escapeHtml(grp.last_message || '-') + '</div></div>' +

            (function (oi) {
              function oiRow(k, v, mono) {
                return '<div class="oi-row"><span class="oi-k">' + k + '</span><span class="oi-v' + (mono ? ' mono' : '') + '">' + v + '</span></div>';
              }
              if (!oi) {
                return '<div class="row" style="display:block;">' +
                  '<div class="k" style="margin-bottom:8px;">官方群信息（QQ 接口）</div>' +
                  '<div class="official-empty">' +
                    '<div class="oe-text">正在从 QQ 官方接口获取群信息（24h 内缓存，遵守官方 30 QPM 限制）…</div>' +
                    '<button class="btn btn-ghost btn-sm" id="grp-official-refresh" type="button">手动刷新</button>' +
                  '</div>' +
                '</div>';
              }
              return '<div class="row" style="display:block;">' +
                '<div class="k" style="margin-bottom:8px; display:flex; align-items:center; justify-content:space-between;">' +
                  '<span>官方群信息（QQ 接口）</span>' +
                  '<button class="btn btn-ghost btn-sm" id="grp-official-refresh" type="button">刷新</button>' +
                '</div>' +
                '<div class="official-box">' +
                  oiRow('官方群名', escapeHtml(oi.name || '-')) +
                  oiRow('官方成员数', (oi.member_count || 0)) +
                  oiRow('群简介', escapeHtml(oi.description || '-')) +
                  oiRow('群分类', escapeHtml(oi.category || '-')) +
                  (oi.tags && oi.tags.length
                    ? '<div class="oi-row"><span class="oi-k">群标签</span><span class="oi-v oi-tags">' +
                        oi.tags.map(function (t) { return '<span class="oi-tag">' + escapeHtml(t) + '</span>'; }).join('') +
                      '</span></div>'
                    : oiRow('群标签', '-')) +
                  oiRow('群号 (group_id)', escapeHtml(oi.group_id || '-'), true) +
                  oiRow('成员上限', (oi.max_member_count || 0)) +
                  oiRow('群主 OpenID', escapeHtml(oi.owner_openid || '-'), true) +
                '</div>' +
              '</div>';
            })(grp.official_info) +

            '<div class="row" style="display:block;">' +

              '<div class="k" style="margin-bottom:8px;">群内成员</div>' +

              '<div class="member-list">' +

                '<div class="mh"><span>成员列表（' + members.length + '）</span><span>消息数</span></div>' +

                (members.length

                  ? '<ul>' + memberItems + '</ul>'

                  : '<div style="padding: 20px; text-align: center; color: var(--muted); font-size: 13px;">暂无成员记录</div>') +

              '</div>' +

            '</div>';


          // 官方群信息：刷新按钮 + 未缓存时默认自动拉取（无需手动）
          var refreshBtn = body.querySelector('#grp-official-refresh');
          function doRefreshOfficial() {
            if (!refreshBtn) return;
            refreshBtn.disabled = true;
            var prevText = refreshBtn.textContent;
            refreshBtn.textContent = '刷新中…';
            fetch(API_BASE + '/api/group/official-info?openid=' + encodeURIComponent(g.openid) + '&refresh=1', { cache: 'no-store' })
              .then(function (rr) { return rr.json(); })
              .then(function (res) {
                if (res && res.ok) {
                  openGroupModal(g); // 重新拉详情，现已带官方信息
                } else {
                  alert((res && res.error) || '刷新失败');
                  if (refreshBtn) { refreshBtn.disabled = false; refreshBtn.textContent = prevText; }
                }
              })
              .catch(function (e) {
                alert('刷新官方信息失败：' + (e && e.message ? e.message : e));
                if (refreshBtn) { refreshBtn.disabled = false; refreshBtn.textContent = prevText; }
              });
          }
          if (refreshBtn) {
            refreshBtn.addEventListener('click', doRefreshOfficial);
            if (!grp.official_info) {
              doRefreshOfficial(); // 未缓存：默认自动刷新，不再要求手动点击
            }
          }
        })

        .catch(function (e) {

          body.innerHTML = '<div style="padding: 20px 0; text-align: center; color: #ef4444;">加载失败：' +

            escapeHtml(e && e.message ? e.message : String(e)) + '</div>';

        });

    }

    function closeGroupModal() {

      var modal = document.getElementById('group-modal');

      if (!modal) return;

      modal.classList.remove('show');

      setTimeout(function () { modal.classList.remove('active'); }, 200);

    }

    function deleteGroup(openid, name) {

      fetch(API_BASE + '/api/group/delete', {

        method: 'POST',

        headers: { 'Content-Type': 'application/json' },

        body: JSON.stringify({ openid: openid })

      })

        .then(function (r) { return r.json(); })

        .then(function (res) {

          if (res && res.ok) {

            loadGroups();

          } else {

            alert((res && res.error) || '删除失败');

          }

        })

        .catch(function (e) { alert('删除请求失败：' + (e && e.message ? e.message : e)); });

    }

    if (searchBtn) searchBtn.addEventListener('click', loadGroups);

    if (resetBtn) resetBtn.addEventListener('click', function () {

      if (botSel) botSel.value = '';

      if (keywordInput) keywordInput.value = '';

      loadGroups();

    });

    if (keywordInput) keywordInput.addEventListener('keydown', function (e) {

      if (e.key === 'Enter') loadGroups();

    });

    if (botSel) botSel.addEventListener('change', loadGroups);

    // 操作列事件委托：查看 / 删除

    if (tbody) {

      tbody.addEventListener('click', function (e) {

        var el = e.target.closest ? e.target.closest('.op-link') : null;

        if (!el) return;

        var act = el.getAttribute('data-act');

        if (act === 'view') {

          var idx = parseInt(el.getAttribute('data-idx'), 10);

          var g = null;

          for (var i = 0; i < lastItems.length; i++) {

            if (lastItems[i].idx === idx) { g = lastItems[i]; break; }

          }

          if (g) openGroupModal(g);

        } else if (act === 'delete') {

          var openid = el.getAttribute('data-openid');

          var name = el.getAttribute('data-name') || '该群';

          if (!openid) return;

          if (window.confirm('确定要删除群「' + name + '」吗？\n\n该操作会：\n· 从所有成员记录中移除该群关联\n· 清理该群的真实QQ号绑定与群资料\n\n且不可恢复。')) {

            deleteGroup(openid, name);

          }

        }

      });

    }

    // 群详情弹窗关闭

    var grpModalClose = document.getElementById('group-modal-close');

    var grpCloseBtn = document.getElementById('group-close-btn');

    if (grpModalClose) grpModalClose.addEventListener('click', closeGroupModal);

    if (grpCloseBtn) grpCloseBtn.addEventListener('click', closeGroupModal);

    var grpModal = document.getElementById('group-modal');

    if (grpModal) grpModal.addEventListener('click', function (e) {

      if (e.target === grpModal) closeGroupModal();

    });

    function onShow() {

      loadGroups();

    }

    loadGroupsRef = onShow;

  })();

  (function joinRequestsCenter() {

    var botSel = document.getElementById('jr-bot-select');
    var refreshBtn = document.getElementById('jr-refresh-btn');
    var listEl = document.getElementById('jr-list');
    var emptyEl = document.getElementById('jr-empty');
    var bannerEl = document.getElementById('jr-banner');
    var statsEl = document.getElementById('jr-stats');

    var state = { appid: '', loading: false, lastData: null };

    function fmtTime(input) {
      if (!input) return '';
      // 官方字段 apply_at 是 RFC3339 / ISO-8601 字符串
      if (typeof input === 'string') {
        var s = input.trim();
        if (!s) return '';
        if (s.charAt(s.length - 1) === 'Z') s = s.slice(0, -1) + '+00:00';
        var d = new Date(s);
        if (!isNaN(d.getTime())) {
          var p2 = function (n) { return (n < 10 ? '0' : '') + n; };
          return d.getFullYear() + '-' + p2(d.getMonth() + 1) + '-' + p2(d.getDate()) +
            ' ' + p2(d.getHours()) + ':' + p2(d.getMinutes());
        }
        return s; // 无法解析时原样返回
      }
      var ms = (input < 1e12) ? input * 1000 : input;
      var dd = new Date(ms);
      if (isNaN(dd.getTime())) return '';
      var p = function (n) { return (n < 10 ? '0' : '') + n; };
      return dd.getFullYear() + '-' + p(dd.getMonth() + 1) + '-' + p(dd.getDate()) +
        ' ' + p(dd.getHours()) + ':' + p(dd.getMinutes());
    }

    function sourceLabel(src) {
      if (src === 'self_apply') return '主动申请';
      if (src === 'invited') return '被邀请';
      return src || '';
    }

    function statusLabel(s) {
      if (s === 'ok') return '有申请';
      if (s === 'empty') return '无申请';
      if (s === 'not_admin') return '非管理员';
      if (s === 'rate_limit') return 'QPM 限流';
      if (s === 'error') return '探测失败';
      return s || '';
    }

    function showBanner(msg, type) {
      if (!bannerEl) return;
      bannerEl.textContent = msg || '';
      bannerEl.className = 'jr-banner' + (type ? ' ' + type : '');
      bannerEl.style.display = msg ? 'block' : 'none';
    }

    function setEmpty(show, text) {
      if (!emptyEl) return;
      emptyEl.style.display = show ? 'flex' : 'none';
      if (text) {
        var t = emptyEl.querySelector('.text');
        if (t) t.textContent = text;
      }
    }

    function clearItems() {
      if (!listEl) return;
      // 清除旧的分组 / 旧的内嵌空态 / 旧的统计条
      var nodes = listEl.querySelectorAll('.jr-group-section, .jr-stats');
      Array.prototype.forEach.call(nodes, function (n) { if (n.parentNode) n.parentNode.removeChild(n); });
    }

    function renderItem(it) {
      var item = document.createElement('div');
      item.className = 'jr-item';

      // 官方字段：username / member_openid / join_request_id / apply_at / apply_source / bot /
      //          verify_info{method, verify_message, review_qa_list[]}
      var displayName = it.username || it.display_name || it.nickname || '(未知)';
      var firstChar = displayName.charAt(0) || '?';
      var ph = document.createElement('div');
      ph.className = 'jr-avatar ph';
      ph.textContent = firstChar;
      item.appendChild(ph);

      var main = document.createElement('div');
      main.className = 'jr-main';

      var nameRow = document.createElement('div');
      nameRow.className = 'jr-name-row';
      var name = document.createElement('span');
      name.className = 'jr-name';
      name.textContent = displayName;
      nameRow.appendChild(name);
      var src = sourceLabel(it.apply_source);
      if (src) {
        var srcTag = document.createElement('span');
        srcTag.className = 'jr-tag';
        srcTag.textContent = src;
        nameRow.appendChild(srcTag);
      }
      if (it.bot) {
        var botTag = document.createElement('span');
        botTag.className = 'jr-tag jr-tag-bot';
        botTag.textContent = '机器人';
        nameRow.appendChild(botTag);
      }
      main.appendChild(nameRow);

      var oid = document.createElement('div');
      oid.className = 'jr-openid';
      oid.textContent = it.member_openid || '';
      if (it.join_request_id) {
        oid.title = 'join_request_id: ' + it.join_request_id + '\nmember_openid: ' + (it.member_openid || '');
      } else {
        oid.title = it.member_openid || '';
      }
      main.appendChild(oid);

      var vi = it.verify_info || {};
      var msgText = vi.verify_message || it.message || it.risk_tips || '';
      if (msgText) {
        var m = document.createElement('div');
        m.className = 'jr-msg';
        var prefix = '';
        if (vi.method === 'admin_review_qa') {
          prefix = '[问答验证] ';
        } else if (vi.method === 'verify_message') {
          prefix = '[验证消息] ';
        }
        m.textContent = prefix + ('申请留言：' + msgText);
        main.appendChild(m);
      }
      if (vi.method === 'admin_review_qa' && Array.isArray(vi.review_qa_list) && vi.review_qa_list.length) {
        var qa = document.createElement('div');
        qa.className = 'jr-qa';
        vi.review_qa_list.forEach(function (q, idx) {
          var line = document.createElement('div');
          line.textContent = 'Q' + (idx + 1) + '：' + (q.question || '') + ' → A：' + (q.answer || '（未填）');
          qa.appendChild(line);
        });
        main.appendChild(qa);
      }

      var timeVal = it.apply_at || it.apply_time_ms || it.time || 0;
      if (timeVal) {
        var tm = document.createElement('div');
        tm.className = 'jr-time';
        tm.textContent = fmtTime(timeVal);
        main.appendChild(tm);
      }
      item.appendChild(main);

      var actions = document.createElement('div');
      actions.className = 'jr-actions';
      var approveBtn = document.createElement('button');
      approveBtn.type = 'button';
      approveBtn.className = 'btn-blue jr-approve';
      approveBtn.setAttribute('data-jrid', it.join_request_id || '');
      approveBtn.setAttribute('data-mid', it.member_openid || '');
      approveBtn.setAttribute('data-gid', it._group_openid || '');
      approveBtn.setAttribute('data-appid', it._appid || '');
      approveBtn.textContent = '通过';
      var declineBtn = document.createElement('button');
      declineBtn.type = 'button';
      declineBtn.className = 'btn-danger jr-decline';
      declineBtn.setAttribute('data-jrid', it.join_request_id || '');
      declineBtn.setAttribute('data-mid', it.member_openid || '');
      declineBtn.setAttribute('data-gid', it._group_openid || '');
      declineBtn.setAttribute('data-appid', it._appid || '');
      declineBtn.textContent = '拒绝';
      actions.appendChild(approveBtn);
      actions.appendChild(declineBtn);
      item.appendChild(actions);

      return item;
    }

    function renderStats(d) {
      if (!statsEl) return;
      statsEl.innerHTML = '';
      var parts = [];
      parts.push('<span class="pill">已探测 <b>' + (d.total_groups || 0) + '</b> 个群</span>');
      parts.push('<span class="pill">有申请 <b>' + (d.ok_groups || 0) + '</b></span>');
      parts.push('<span class="pill">无申请 <b>' + (d.empty_groups || 0) + '</b></span>');
      parts.push('<span class="pill">非管理员 <b>' + (d.not_admin_groups || 0) + '</b></span>');
      if (d.rate_limit_groups) parts.push('<span class="pill">QPM 限流 <b>' + (d.rate_limit_groups || 0) + '</b></span>');
      if (d.error_groups) parts.push('<span class="pill">探测失败 <b>' + d.error_groups + '</b></span>');
      statsEl.innerHTML = parts.join('');
      statsEl.style.display = 'flex';
    }

    function renderGroupSection(g) {
      var sec = document.createElement('div');
      sec.className = 'jr-group-section';

      var head = document.createElement('div');
      head.className = 'jr-group-head';
      var nameSpan = document.createElement('span');
      nameSpan.className = 'jr-group-name';
      var status = g.status || 'error';
      var displayName = g.name || g.openid || '未命名群';
      nameSpan.textContent = displayName;
      if (g.name && g.openid) nameSpan.title = g.openid;
      head.appendChild(nameSpan);
      var right = document.createElement('span');
      right.style.display = 'inline-flex';
      right.style.alignItems = 'center';
      right.style.gap = '8px';
      if (status === 'ok' && Array.isArray(g.items)) {
        var cnt = document.createElement('span');
        cnt.className = 'jr-group-count';
        cnt.textContent = g.items.length + ' 条';
        right.appendChild(cnt);
      }
      var badge = document.createElement('span');
      badge.className = 'jr-group-badge ' + status;
      badge.textContent = statusLabel(status);
      right.appendChild(badge);
      head.appendChild(right);
      sec.appendChild(head);

      var body = document.createElement('div');
      body.className = 'jr-group-body';

      if (status === 'ok' && Array.isArray(g.items) && g.items.length) {
        g.items.forEach(function (it) { body.appendChild(renderItem(it)); });
      } else if (status === 'empty') {
        var note = document.createElement('div');
        note.className = 'jr-group-note';
        note.textContent = '暂无待审批的入群申请';
        body.appendChild(note);
      } else if (status === 'not_admin') {
        var note2 = document.createElement('div');
        note2.className = 'jr-group-note';
        var nm = '机器人不是该群管理员，已自动跳过此群';
        if (g.error_code) nm += '（官方 code ' + escapeHtml(String(g.error_code)) + (g.error_message ? ' · ' + escapeHtml(g.error_message) : '') + '）';
        note2.textContent = nm;
        body.appendChild(note2);
      } else if (status === 'rate_limit') {
        var note3 = document.createElement('div');
        note3.className = 'jr-group-note';
        note3.textContent = '本轮 QPM 已用完（30 QPM / 单机器人），未探测此群。请约 60 秒后再次点击刷新继续推进。';
        body.appendChild(note3);
      } else if (status === 'error') {
        var note4 = document.createElement('div');
        note4.className = 'jr-group-note';
        note4.textContent = '探测失败：' + escapeHtml(g.error || '未知错误');
        body.appendChild(note4);
      }
      sec.appendChild(body);
      return sec;
    }

    function populateBots() {
      if (!botSel) return;
      var cur = botSel.value;
      var hint = document.getElementById('jr-hint');
      if (hint) hint.textContent = '正在加载机器人列表…';
      botSel.innerHTML = '<option value="">加载中…</option>';
      fetch(API_BASE + '/api/group/bots', { cache: 'no-store' })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          var bots = (data && data.bots) || [];
          botSel.innerHTML = '<option value="">请选择机器人</option>';
          bots.forEach(function (b) {
            var o = document.createElement('option');
            o.value = b.appid || '';
            var label = (b.name || b.appid) + (b.online ? '' : '（离线）') + (' · ' + (b.group_count || 0) + ' 个群');
            if (b.orphan) label += '（未配置）';
            o.textContent = label;
            o.title = (b.appid || '') + (b.online ? '\n在线' : '\n离线（无 bridge 桥接）');
            botSel.appendChild(o);
          });
          if (!bots.length) {
            if (hint) hint.textContent = '未发现任何机器人，请检查 data/bots.json';
          } else {
            if (hint) hint.textContent = '选择机器人后自动拉取其所有作为管理员的群的入群申请（已自动过滤掉非管理员的群）';
          }
          if (cur) botSel.value = cur;
        })
        .catch(function (e) {
          console.error('[join-requests] populateBots 失败:', e);
          botSel.innerHTML = '<option value="">请选择机器人</option>';
          if (hint) hint.textContent = '加载失败：' + (e && e.message ? e.message : String(e));
        });
    }

    function renderSections(groups, totalItems) {
      clearItems();
      if (!groups || !groups.length) {
        setEmpty(true, '该机器人当前没有被映射到任何群');
        return;
      }
      setEmpty(false);
      if (statsEl) renderStats({ total_groups: groups.length,
        ok_groups: groups.filter(function (g) { return g.status === 'ok'; }).length,
        empty_groups: groups.filter(function (g) { return g.status === 'empty'; }).length,
        not_admin_groups: groups.filter(function (g) { return g.status === 'not_admin'; }).length,
        rate_limit_groups: groups.filter(function (g) { return g.status === 'rate_limit'; }).length,
        error_groups: groups.filter(function (g) { return g.status === 'error'; }).length,
      });
      if (listEl) {
        if (statsEl) listEl.appendChild(statsEl);
        groups.forEach(function (g) {
          listEl.appendChild(renderGroupSection(g));
        });
      }
      if (totalItems === 0) {
        // 没有一个有申请的群，单独提示
        if (groups.every(function (g) { return g.status !== 'ok'; })) {
          var note = document.createElement('div');
          note.className = 'jr-group-note';
          note.style.padding = '12px 14px';
          note.textContent = '所有群当前都没有待审批的入群申请（非管理员群已自动跳过）。';
          if (listEl) listEl.appendChild(note);
        }
      }
    }

    function loadAllRequests() {
      if (!botSel) return;
      var appid = botSel.value;
      if (!appid) {
        showBanner('请先在下拉框选择一个机器人', 'error');
        return;
      }
      if (state.loading) return;
      state.loading = true;
      clearItems();
      setEmpty(false);
      if (statsEl) statsEl.style.display = 'none';
      showBanner('正在依次拉取所有群的入群申请…（每个群 1 次官方请求，单机器人 30 QPM，超出会自动标 QPM 限流）');
      var url = API_BASE + '/api/group/join-requests/aggregate?appid=' + encodeURIComponent(appid) + '&limit=20';
      fetch(url, { cache: 'no-store' })
        .then(function (r) {
          if (!r.ok) throw new Error('HTTP ' + r.status);
          return r.json();
        })
        .then(function (res) {
          state.loading = false;
          if (!res || res.ok === false) {
            showBanner((res && res.error) || '加载失败', 'error');
            setEmpty(true, (res && res.error) || '加载失败');
            return;
          }
          state.lastData = res;
          var groups = res.groups || [];
          var totalItems = 0;
          groups.forEach(function (g) { if (g.status === 'ok' && Array.isArray(g.items)) totalItems += g.items.length; });
          renderSections(groups, totalItems);
          if (res.note) {
            showBanner(res.note, res.rate_limit_groups ? 'error' : 'ok');
          } else {
            showBanner('已完成：共 ' + (res.total_groups || 0) + ' 个群，' + totalItems + ' 条待审批入群申请', 'ok');
          }
        })
        .catch(function (e) {
          state.loading = false;
          console.error('[join-requests] loadAllRequests 失败:', e);
          showBanner('加载失败：' + (e && e.message ? e.message : e), 'error');
        });
    }

    function cssEsc(s) {
      return String(s).replace(/["\\]/g, '\\$&');
    }

    function approve(jrid, mid, action, gid, appid) {
      if (!jrid || !mid || !gid) {
        showBanner('缺少 join_request_id / member_openid / 群 openid，无法审批', 'error');
        return;
      }
      var reason = '';
      if (action === 'decline') {
        try {
          reason = window.prompt('拒绝原因（可留空）：', '') || '';
        } catch (e) { reason = ''; }
      }
      var body = {
        openid: gid,
        member_openid: mid,
        join_request_id: jrid,
        action: action
      };
      if (reason) body.reason = reason;
      if (appid) body.appid = appid;
      fetch(API_BASE + '/api/group/join-requests/approval', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })
        .then(function (r) { return r.json(); })
        .then(function (res) {
          if (!res || res.ok === false) {
            showBanner((res && res.error) || '操作失败', 'error');
            return;
          }
          showBanner((action === 'approve' ? '已通过' : '已拒绝') + '该入群申请', 'ok');
          if (listEl) {
            var btn = listEl.querySelector('[data-jrid="' + cssEsc(jrid) + '"][data-gid="' + cssEsc(gid) + '"]');
            var card = btn ? btn.closest('.jr-item') : null;
            if (card && card.parentNode) card.parentNode.removeChild(card);
          }
        })
        .catch(function (e) {
          console.error('[join-requests] approve 失败:', e);
          showBanner('操作失败：' + (e && e.message ? e.message : e), 'error');
        });
    }

    function escapeHtml(s) {
      return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    if (botSel) botSel.addEventListener('change', function () { loadAllRequests(); });
    if (refreshBtn) refreshBtn.addEventListener('click', function () { loadAllRequests(); });
    if (listEl) {
      listEl.addEventListener('click', function (e) {
        var t = e.target;
        if (!t) return;
        if (t.classList && t.classList.contains('jr-approve')) {
          approve(t.getAttribute('data-jrid'), t.getAttribute('data-mid'), 'approve', t.getAttribute('data-gid'), t.getAttribute('data-appid'));
        } else if (t.classList && t.classList.contains('jr-decline')) {
          approve(t.getAttribute('data-jrid'), t.getAttribute('data-mid'), 'decline', t.getAttribute('data-gid'), t.getAttribute('data-appid'));
        }
      });
    }

    function onShow() {
      populateBots();
      if (botSel && botSel.options.length > 1) {
        loadAllRequests();
      } else {
        setEmpty(true, '请选择机器人后查看入群申请');
      }
    }

    loadJoinRequestsRef = onShow;

  })();
  (function joinApprovalCenter() {

    var listEl = document.getElementById('ja-list');
    var emptyEl = document.getElementById('ja-empty');
    var bannerEl = document.getElementById('ja-banner');
    var hintEl = document.getElementById('ja-hint');
    var refreshBtn = document.getElementById('ja-refresh-btn');
    var createBtn = document.getElementById('ja-create-btn');

    var modalMask = document.getElementById('ja-modal-mask');
    var modalTitle = document.getElementById('ja-modal-title');
    var remarkInput = document.getElementById('ja-remark');
    var enableSel = document.getElementById('ja-enable');
    var groupBox = document.getElementById('ja-group-box');
    var modalSave = document.getElementById('ja-modal-save');
    var modalCancel = document.getElementById('ja-modal-cancel');
    var modalClose = document.getElementById('ja-modal-close');

    var wlMask = document.getElementById('ja-wl-mask');
    var wlClose = document.getElementById('ja-wl-close');
    var wlInput = document.getElementById('ja-wl-input');
    var wlRemoveInput = document.getElementById('ja-wl-remove-input');
    var wlAddBtn = document.getElementById('ja-wl-add-btn');
    var wlRemoveBtn = document.getElementById('ja-wl-remove-btn');
    var wlCountEl = document.getElementById('ja-wl-count');
    var wlBannerEl = document.getElementById('ja-wl-banner');

    var state = { editing: null, currentSid: null, currentCount: 0 };

    function showBanner(msg, type) {
      if (!bannerEl) return;
      bannerEl.textContent = msg || '';
      bannerEl.className = 'ja-banner' + (type ? ' ' + type : '');
      bannerEl.style.display = msg ? 'block' : 'none';
    }
    function showWlBanner(msg, type) {
      if (!wlBannerEl) return;
      wlBannerEl.textContent = msg || '';
      wlBannerEl.className = 'ja-banner' + (type ? ' ' + type : '');
      wlBannerEl.style.display = msg ? 'block' : 'none';
    }
    function setEmpty(show) { if (emptyEl) emptyEl.style.display = show ? 'flex' : 'none'; }
    function esc(s) {
      return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
      });
    }
    function fmtTime(ts) {
      if (!ts) return '';
      var ms = (ts < 1e12) ? ts * 1000 : ts;
      var d = new Date(ms);
      if (isNaN(d.getTime())) return '';
      var p = function (n) { return (n < 10 ? '0' : '') + n; };
      return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
    }

    function loadStrategies() {
      if (hintEl) hintEl.textContent = '加载策略列表…';
      showBanner('');
      fetch(API_BASE + '/api/group/join-approval/strategies?limit=20', { cache: 'no-store' })
        .then(function (r) { return r.json(); })
        .then(function (res) {
          if (!res || res.ok === false) {
            if (hintEl) hintEl.textContent = '加载失败';
            showBanner((res && res.error) || '加载失败', 'error');
            return;
          }
          var items = res.items || [];
          if (listEl) listEl.innerHTML = '';
          if (!items.length) {
            setEmpty(true);
            if (hintEl) hintEl.textContent = '暂无策略，点击「新建策略」创建';
            return;
          }
          setEmpty(false);
          if (hintEl) hintEl.textContent = '共 ' + items.length + ' 个策略';
          items.forEach(function (it) { if (listEl) listEl.appendChild(renderCard(it)); });
        })
        .catch(function (e) {
          if (hintEl) hintEl.textContent = '加载失败';
          showBanner('加载失败：' + (e && e.message ? e.message : e), 'error');
        });
    }

    function renderCard(it) {
      var card = document.createElement('div');
      card.className = 'ja-card';
      var groups = (it.group_openids || []);
      var groupsHtml = groups.length
        ? groups.slice(0, 3).map(function (g) { return '<code>' + esc(g.slice(-8)) + '</code>'; }).join('') + (groups.length > 3 ? ' …' : '')
        : '<span class="ja-muted">未关联群</span>';
      var enabled = String(it.is_enable || '').toLowerCase() === 'on';
      card.innerHTML =
        '<div class="ja-card-head">' +
          '<div class="ja-title">' + esc(it.remark || '(未命名策略)') + '</div>' +
          '<span class="ja-badge ' + (enabled ? 'on' : 'off') + '">' + (enabled ? '已启用' : '已停用') + '</span>' +
        '</div>' +
        '<div class="ja-card-meta">' +
          '<div><span class="ja-muted">策略ID</span><code class="ja-sid">' + esc(it.strategy_id || '') + '</code></div>' +
          '<div><span class="ja-muted">关联群</span>' + groupsHtml + '</div>' +
          '<div><span class="ja-muted">白名单</span>' + (it.whitelist_user_count || 0) + ' 个</div>' +
          (it.created_at ? '<div><span class="ja-muted">创建</span>' + esc(fmtTime(it.created_at)) + '</div>' : '') +
        '</div>' +
        '<div class="ja-card-actions">' +
          '<button type="button" class="btn-ghost ja-toggle" data-sid="' + esc(it.strategy_id) + '" data-enable="' + (enabled ? 'off' : 'on') + '">' + (enabled ? '停用' : '启用') + '</button>' +
          '<button type="button" class="btn-ghost ja-edit" data-sid="' + esc(it.strategy_id) + '">编辑</button>' +
          '<button type="button" class="btn-blue ja-exec" data-sid="' + esc(it.strategy_id) + '">执行</button>' +
          '<button type="button" class="btn-ghost ja-wl" data-sid="' + esc(it.strategy_id) + '" data-whitelist-count="' + esc(String(it.whitelist_user_count || 0)) + '">白名单</button>' +
          '<button type="button" class="btn-danger ja-del" data-sid="' + esc(it.strategy_id) + '">删除</button>' +
        '</div>';
      return card;
    }

    function populateGroupBox(selected) {
      if (!groupBox) return;
      groupBox.innerHTML = '<div class="ja-group-hint">加载群列表中…</div>';
      fetch(API_BASE + '/api/group/admin-groups', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}'
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          var groups = (data && data.groups) || [];
          if (!groups.length) {
            groupBox.innerHTML = '<div class="ja-group-hint">未发现机器人是管理员的群</div>';
            return;
          }
          groupBox.innerHTML = '';
          var sel = (selected || []);
          groups.forEach(function (g) {
            var lbl = document.createElement('label');
            lbl.className = 'ja-group-item';
            var cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.value = g.openid || '';
            if (sel.indexOf(g.openid) >= 0) cb.checked = true;
            lbl.appendChild(cb);
            var span = document.createElement('span');
            span.textContent = (g.name || g.openid || '未命名群');
            lbl.appendChild(span);
            groupBox.appendChild(lbl);
          });
        })
        .catch(function (e) {
          groupBox.innerHTML = '<div class="ja-group-hint">加载群列表失败：' + esc(e && e.message ? e.message : e) + '</div>';
        });
    }

    function openModal(editing, item) {
      state.editing = editing ? item : null;
      if (modalTitle) modalTitle.textContent = editing ? '编辑策略' : '新建策略';
      if (remarkInput) remarkInput.value = editing && item ? (item.remark || '') : '';
      if (enableSel) enableSel.value = editing && item ? (String(item.is_enable).toLowerCase() === 'on' ? 'on' : 'off') : 'on';
      var selected = (editing && item && item.group_openids) ? item.group_openids : [];
      populateGroupBox(selected);
      if (modalMask) modalMask.style.display = 'flex';
    }
    function closeModal() { if (modalMask) modalMask.style.display = 'none'; }

    function saveModal() {
      var remark = (remarkInput && remarkInput.value || '').trim();
      var isEnable = enableSel ? enableSel.value : 'on';
      var gids = [];
      if (groupBox) {
        var cbs = groupBox.querySelectorAll('input[type=checkbox]:checked');
        Array.prototype.forEach.call(cbs, function (cb) { if (cb.value) gids.push(cb.value); });
      }
      if (!gids.length) { showBanner('请至少选择一个关联群', 'error'); return; }
      var url, body;
      if (state.editing) {
        url = API_BASE + '/api/group/join-approval/strategies/' + encodeURIComponent(state.editing.strategy_id) + '/update';
        body = { is_enable: isEnable, remark: remark, group_openids: gids };
      } else {
        url = API_BASE + '/api/group/join-approval/strategies';
        body = { is_enable: isEnable, remark: remark, group_openids: gids };
      }
      fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })
        .then(function (r) { return r.json(); })
        .then(function (res) {
          if (!res || res.ok === false) { showBanner((res && res.error) || '保存失败', 'error'); return; }
          showBanner(state.editing ? '已更新策略' : '已创建策略', 'ok');
          closeModal();
          loadStrategies();
        })
        .catch(function (e) { showBanner('保存失败：' + (e && e.message ? e.message : e), 'error'); });
    }

    function toggleStrategy(sid, enable) {
      fetch(API_BASE + '/api/group/join-approval/strategies/' + encodeURIComponent(sid) + '/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_enable: enable })
      })
        .then(function (r) { return r.json(); })
        .then(function (res) {
          if (!res || res.ok === false) { showBanner((res && res.error) || '操作失败', 'error'); return; }
          showBanner('已' + (enable === 'on' ? '启用' : '停用') + '该策略', 'ok');
          loadStrategies();
        })
        .catch(function (e) { showBanner('操作失败：' + (e && e.message ? e.message : e), 'error'); });
    }

    function executeStrategy(sid) {
      fetch(API_BASE + '/api/group/join-approval/strategies/' + encodeURIComponent(sid) + '/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}'
      })
        .then(function (r) { return r.json(); })
        .then(function (res) {
          if (!res || res.ok === false) { showBanner((res && res.error) || '执行失败', 'error'); return; }
          showBanner('已下发执行该策略', 'ok');
        })
        .catch(function (e) { showBanner('执行失败：' + (e && e.message ? e.message : e), 'error'); });
    }

    function deleteStrategy(sid) {
      if (!confirm('确定删除该入群审批策略？此操作不可撤销。')) return;
      fetch(API_BASE + '/api/group/join-approval/strategies/' + encodeURIComponent(sid) + '/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}'
      })
        .then(function (r) { return r.json(); })
        .then(function (res) {
          if (!res || res.ok === false) { showBanner((res && res.error) || '删除失败', 'error'); return; }
          showBanner('已删除策略', 'ok');
          loadStrategies();
        })
        .catch(function (e) { showBanner('删除失败：' + (e && e.message ? e.message : e), 'error'); });
    }

    function openWhitelist(sid, initialCount) {
      state.currentSid = sid;
      state.currentCount = initialCount || 0;
      if (wlCountEl) wlCountEl.textContent = String(state.currentCount);
      showWlBanner('');
      if (wlInput) wlInput.value = '';
      if (wlRemoveInput) wlRemoveInput.value = '';
      if (wlMask) wlMask.style.display = 'flex';
    }
    function closeWhitelist() { if (wlMask) wlMask.style.display = 'none'; }

    function _parseQqList(raw) {
      return (raw || '').split(/[\s,，]+/).map(function (x) { return x.trim(); }).filter(function (x) { return /^[0-9]+$/.test(x); });
    }
    function _refreshWlCountFromServer() {
      // 服务端策略列表里的 whitelist_user_count 是权威值；重新拉一遍更新抽屉顶部数字
      fetch(API_BASE + '/api/group/join-approval/strategies?limit=100', { cache: 'no-store' })
        .then(function (r) { return r.json(); })
        .then(function (res) {
          if (!res || res.ok === false) return;
          var items = (res && res.items) || [];
          for (var i = 0; i < items.length; i++) {
            if (items[i].strategy_id === state.currentSid) {
              state.currentCount = items[i].whitelist_user_count || 0;
              if (wlCountEl) wlCountEl.textContent = String(state.currentCount);
              break;
            }
          }
        })
        .catch(function () { /* 静默失败 */ });
    }
    function addWhitelist() {
      if (!state.currentSid) return;
      var users = _parseQqList(wlInput && wlInput.value);
      if (!users.length) { showWlBanner('请输入至少一个合法的 QQ 号（仅数字）', 'error'); return; }
      fetch(API_BASE + '/api/group/join-approval/strategies/' + encodeURIComponent(state.currentSid) + '/whitelist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ op: 'add', whitelist_users: users })
      })
        .then(function (r) { return r.json(); })
        .then(function (res) {
          if (!res || res.ok === false) { showWlBanner((res && res.error) || '添加失败', 'error'); return; }
          showWlBanner('已添加 ' + users.length + ' 个 QQ 号', 'ok');
          if (wlInput) wlInput.value = '';
          _refreshWlCountFromServer();
          loadStrategies();
        })
        .catch(function (e) { showWlBanner('添加失败：' + (e && e.message ? e.message : e), 'error'); });
    }

    function removeWhitelistBatch() {
      if (!state.currentSid) return;
      var users = _parseQqList(wlRemoveInput && wlRemoveInput.value);
      if (!users.length) { showWlBanner('请输入至少一个要删除的 QQ 号', 'error'); return; }
      fetch(API_BASE + '/api/group/join-approval/strategies/' + encodeURIComponent(state.currentSid) + '/whitelist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ op: 'delete', whitelist_users: users })
      })
        .then(function (r) { return r.json(); })
        .then(function (res) {
          if (!res || res.ok === false) { showWlBanner((res && res.error) || '删除失败', 'error'); return; }
          showWlBanner('已提交删除 ' + users.length + ' 个 QQ 号', 'ok');
          if (wlRemoveInput) wlRemoveInput.value = '';
          _refreshWlCountFromServer();
          loadStrategies();
        })
        .catch(function (e) { showWlBanner('删除失败：' + (e && e.message ? e.message : e), 'error'); });
    }

    if (refreshBtn) refreshBtn.addEventListener('click', loadStrategies);
    if (createBtn) createBtn.addEventListener('click', function () { openModal(false, null); });
    if (modalSave) modalSave.addEventListener('click', saveModal);
    if (modalCancel) modalCancel.addEventListener('click', closeModal);
    if (modalClose) modalClose.addEventListener('click', closeModal);
    if (wlClose) wlClose.addEventListener('click', closeWhitelist);
    if (wlAddBtn) wlAddBtn.addEventListener('click', addWhitelist);
    if (wlRemoveBtn) wlRemoveBtn.addEventListener('click', removeWhitelistBatch);

    if (listEl) {
      listEl.addEventListener('click', function (e) {
        var t = e.target;
        if (!t) return;
        if (t.classList.contains('ja-toggle')) toggleStrategy(t.getAttribute('data-sid'), t.getAttribute('data-enable'));
        else if (t.classList.contains('ja-edit')) {
          var sid = t.getAttribute('data-sid');
          var card = t.closest('.ja-card');
          openModal(true, {
            strategy_id: sid,
            remark: (card && card.querySelector('.ja-title') ? card.querySelector('.ja-title').textContent : ''),
            is_enable: (card && card.querySelector('.ja-badge') && card.querySelector('.ja-badge').classList.contains('on') ? 'on' : 'off')
          });
        }
        else if (t.classList.contains('ja-exec')) executeStrategy(t.getAttribute('data-sid'));
        else if (t.classList.contains('ja-wl')) {
          var _sid = t.getAttribute('data-sid');
          var _count = parseInt(t.getAttribute('data-whitelist-count') || '0', 10);
          if (!isFinite(_count) || _count < 0) _count = 0;
          openWhitelist(_sid, _count);
        }
        else if (t.classList.contains('ja-del')) deleteStrategy(t.getAttribute('data-sid'));
      });
    }
    function onShow() { loadStrategies(); }
    loadJoinApprovalRef = onShow;

  })();



  (function usersCenter() {

    var botSel = document.getElementById('usr-bot-select');

    var keywordInput = document.getElementById('usr-keyword');

    var searchBtn = document.getElementById('usr-search-btn');

    var resetBtn = document.getElementById('usr-reset-btn');

    var tbody = document.getElementById('usr-tbody');

    var tableWrap = document.getElementById('usr-table-wrap');

    var emptyEl = document.getElementById('usr-empty');

    var summaryEl = document.getElementById('usr-summary');

    var lastItems = [];

    function buildQuery() {

      var params = [];

      if (botSel && botSel.value) params.push('bot=' + encodeURIComponent(botSel.value));

      if (keywordInput && keywordInput.value.trim()) params.push('keyword=' + encodeURIComponent(keywordInput.value.trim()));

      return params.length ? ('?' + params.join('&')) : '';

    }

    function syncOptions(sel, values, defaultLabel) {

      if (!sel) return;

      var cur = sel.value;

      sel.innerHTML = '<option value="">' + defaultLabel + '</option>';

      (values || []).forEach(function (v) {

        var o = document.createElement('option');

        o.value = v; o.textContent = v;

        sel.appendChild(o);

      });

      if (cur) {

        var found = false;

        for (var i = 0; i < sel.options.length; i++) {

          if (sel.options[i].value === cur) { found = true; break; }

        }

        if (found) sel.value = cur;

      }

    }

    function renderUsers(data) {

      try {

        var items = data.items || [];

        var total = (data.total != null) ? data.total : items.length;

        var bots = data.bots || [];

        if (summaryEl) {

          summaryEl.innerHTML = '<span class="dot"></span><span>' +

            (botSel && botSel.value ? escapeHtml(botSel.value) : '全部机器人') +

            ' · ' + total + ' 个用户</span>';

        }

        syncOptions(botSel, bots, '全部机器人');

        if (!items.length) {

          if (tableWrap) tableWrap.style.display = 'none';

          if (emptyEl) emptyEl.style.display = 'flex';

          lastItems = [];

          return;

        }

        if (tableWrap) tableWrap.style.display = 'block';

        if (emptyEl) emptyEl.style.display = 'none';

        var rows = items.map(function (u, idx) {

          u.idx = idx + 1;

          return '<tr>' +

            '<td class="col-check"><input type="checkbox" class="usr-check" value="' + escapeHtml(u.openid || '') + '"></td>' +

            '<td class="col-idx">' + (idx + 1) + '</td>' +

            '<td>' + escapeHtml(u.bot || '-') + '</td>' +

            '<td>' + (function(){              var nick = u.nickname || '-';              var initial = nick.slice(0,1).toUpperCase();              var av = u.avatar ? '<img src="' + escapeHtml(u.avatar) + '" alt="" onerror="this.style.display=\'none\';this.parentNode.classList.add(\'missing\')"/>' : '';              var initialHtml = av ? '' : escapeHtml(initial);              return '<span class="usr-cell' + (u.nickname ? '' : ' missing') + '">' +                '<span class="usr-avatar"' + (av ? ' style="background:transparent"' : '') + '>' + av + initialHtml + '</span>' +                '<span class="usr-nick" title="' + escapeHtml(nick) + '">' + escapeHtml(nick) + '</span>' +              '</span>';            })() + '</td>' +

            '<td class="mono" title="' + escapeHtml(u.openid || '') + '">' + escapeHtml(truncate(u.openid, 18)) + '</td>' +

            '<td>' + escapeHtml(u.real_qq || '-') + '</td>' +

            '<td>' + (u.msg_count || 0) + '</td>' +

            '<td>' + escapeHtml(u.last_seen || '-') + '</td>' +

            '<td class="col-op">' +

              '<span class="op-link" data-act="view" data-idx="' + (idx + 1) + '">查看</span> ' +

              '<span class="op-link op-danger" data-act="delete" data-openid="' + escapeHtml(u.openid || '') + '" data-name="' + escapeHtml(u.nickname || u.openid || '') + '">删除</span>' +

            '</td>' +

          '</tr>';

        }).join('');

        if (tbody) tbody.innerHTML = rows;

        lastItems = items;

      // ===== 用户批量删除选择模式 =====
      var _usrTableEl = document.querySelector('#usr-table-wrap table');
      var _usrBtnDel = document.getElementById('usr-batch-delete');
      var _usrBtnCancel = document.getElementById('usr-batch-cancel');
      var _usrBtnConfirm = document.getElementById('usr-batch-confirm');
      var _usrBatchBound = false;
      function _usrRefreshBatchCount() {
        if (!_usrBtnConfirm) return;
        var n = document.querySelectorAll('.usr-check:checked').length;
        _usrBtnConfirm.textContent = '确认删除 (' + n + ')';
        _usrBtnConfirm.disabled = n === 0;
        var _all = document.getElementById('usr-check-all');
        if (_all) {
          var tot = document.querySelectorAll('.usr-check').length;
          _all.checked = tot > 0 && n === tot;
          _all.indeterminate = n > 0 && n < tot;
        }
      }
      function _usrEnterSelect() {
        if (_usrTableEl) _usrTableEl.classList.add('in-select');
        if (_usrBtnDel) _usrBtnDel.style.display = 'none';
        if (_usrBtnCancel) _usrBtnCancel.style.display = '';
        if (_usrBtnConfirm) _usrBtnConfirm.style.display = '';
        _usrRefreshBatchCount();
      }
      function _usrExitSelect() {
        if (_usrTableEl) _usrTableEl.classList.remove('in-select');
        var ck = document.querySelectorAll('.usr-check');
        for (var _i = 0; _i < ck.length; _i++) ck[_i].checked = false;
        if (_usrBtnDel) _usrBtnDel.style.display = '';
        if (_usrBtnCancel) _usrBtnCancel.style.display = 'none';
        if (_usrBtnConfirm) _usrBtnConfirm.style.display = 'none';
      }
      if (!_usrBatchBound) {
        _usrBatchBound = true;
        var _usrAll = document.getElementById('usr-check-all');
        if (_usrAll) _usrAll.addEventListener('change', function () {
          var ck = document.querySelectorAll('.usr-check');
          for (var _j = 0; _j < ck.length; _j++) ck[_j].checked = _usrAll.checked;
          _usrRefreshBatchCount();
        });
        if (_usrBtnDel) _usrBtnDel.addEventListener('click', _usrEnterSelect);
        if (_usrBtnCancel) _usrBtnCancel.addEventListener('click', _usrExitSelect);
        if (_usrBtnConfirm) _usrBtnConfirm.addEventListener('click', function () {
          var oids = [];
          var ck = document.querySelectorAll('.usr-check:checked');
          for (var _k = 0; _k < ck.length; _k++) if (ck[_k].value) oids.push(ck[_k].value);
          if (!oids.length) { alert('请先勾选至少 1 个用户'); return; }
          if (!window.confirm('确认批量删除 ' + oids.length + ' 个用户？该操作不可撤销。')) return;
          _usrBtnConfirm.disabled = true;
          var _t = _usrBtnConfirm.textContent;
          _usrBtnConfirm.textContent = '删除中…';
          fetch(API_BASE + '/api/c2c-user/delete-batch', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ openids: oids })
          })
            .then(function (r) { return r.json(); })
            .then(function (res) {
              if (res && res.ok) {
                var failed = (res.failed_count || 0);
                alert('已删除 ' + res.deleted_count + ' 个用户' + (failed ? ('；' + failed + ' 个不存在') : ''));
                _usrExitSelect();
                loadUsers();
              } else {
                alert('删除失败：' + ((res && res.error) || '未知错误'));
              }
              _usrBtnConfirm.disabled = false;
              _usrBtnConfirm.textContent = _t;
              _usrRefreshBatchCount();
            })
            .catch(function (e) { alert('请求失败：' + e); _usrBtnConfirm.textContent = _t; _usrRefreshBatchCount(); });
        });
      }
      var _usrCks = document.querySelectorAll('.usr-check');
      for (var _uci = 0; _uci < _usrCks.length; _uci++) {
        _usrCks[_uci].addEventListener('change', _usrRefreshBatchCount);
      }
      _usrRefreshBatchCount();

      } catch (e) {

        console.error('[users] renderUsers 失败:', e, e && e.stack, data);

        if (tbody) tbody.innerHTML = '<tr><td colspan="8" class="table-empty">渲染失败：' +

          escapeHtml(e && e.message ? e.message : String(e)) + '</td></tr>';

      }

    }

    function loadUsers() {

      if (tbody) tbody.innerHTML = '<tr><td colspan="8" class="table-empty">加载中…</td></tr>';

      fetch(API_BASE + '/api/c2c-users' + buildQuery(), { cache: 'no-store' })

        .then(function (r) {

          if (!r.ok) throw new Error('HTTP ' + r.status + ' ' + (r.statusText || ''));

          return r.text().then(function (txt) {

            if (!txt) throw new Error('响应为空');

            try { return JSON.parse(txt); }

            catch (je) { throw new Error('JSON 解析失败：' + je.message + '（body 前 80 字：' + txt.slice(0, 80) + '）'); }

          });

        })

        .then(function (data) { renderUsers(data || {}); })

        .catch(function (e) {

          console.error('[users] loadUsers 失败:', e);

          if (tbody) tbody.innerHTML = '<tr><td colspan="8" class="table-empty">加载失败：' +

            escapeHtml(e && e.message ? e.message : String(e)) + '</td></tr>';

        });

    }

    function openUserModal(u) {

      var modal = document.getElementById('user-modal');

      var body = document.getElementById('user-detail-body');

      if (!modal || !body) return;

      body.innerHTML = '<div style="padding: 20px 0; text-align: center; color: var(--muted);">加载中…</div>';

      modal.classList.add('active');

      requestAnimationFrame(function () { modal.classList.add('show'); });

      fetch(API_BASE + '/api/c2c-user/detail?openid=' + encodeURIComponent(u.openid), { cache: 'no-store' })

        .then(function (r) {

          if (!r.ok) throw new Error('HTTP ' + r.status + ' ' + (r.statusText || ''));

          return r.json();

        })

        .then(function (res) {

          if (!res || !res.ok) throw new Error((res && res.error) || '加载失败');

          var usr = res.user || {};

          var groups = res.groups || [];

          var initial = (usr.nickname || '用').slice(0, 1).toUpperCase();

          var avatarHtml = usr.avatar

            ? '<img src="' + escapeHtml(usr.avatar) + '" alt="" onerror="this.parentNode.textContent=\'' + escapeHtml(initial) + '\'"/>'

            : escapeHtml(initial);

          var groupItems = groups.map(function (g) {

            return '<li>' +

              '<span class="nick" title="' + escapeHtml(g.openid || '') + '">' + escapeHtml(g.name || '(未命名)') + '</span>' +

              '<span class="oid">' + escapeHtml(truncate(g.openid, 16)) + '</span>' +

            '</li>';

          }).join('');

          body.innerHTML =

            '<div class="grp-head">' +

              '<div class="grp-avatar">' + avatarHtml + '</div>' +

              '<div>' +

                '<div class="grp-name">' + escapeHtml(usr.nickname || '-') + '</div>' +

                '<div class="grp-sub">OpenID ' + escapeHtml(truncate(usr.openid, 24)) + '</div>' +

              '</div>' +

            '</div>' +

            '<div class="row"><div class="k">机器人</div><div class="v">' + escapeHtml(usr.bot || '-') + '</div></div>' +

            '<div class="row"><div class="k">用户 OpenID</div><div class="v mono">' + escapeHtml(usr.openid || '-') + '</div></div>' +

            '<div class="row"><div class="k">真实QQ</div><div class="v">' + escapeHtml(usr.real_qq || '-') + '</div></div>' +

            '<div class="row"><div class="k">消息数</div><div class="v">' + (usr.msg_count || 0) + '</div></div>' +

            '<div class="row"><div class="k">最后活跃</div><div class="v">' + escapeHtml(usr.last_seen || '-') + '</div></div>' +

            '<div class="row" style="display:block;">' +

              '<div class="k" style="margin-bottom:8px;">所属群聊（' + groups.length + '）</div>' +

              '<div class="member-list">' +

                '<div class="mh"><span>群列表</span><span>群 OpenID</span></div>' +

                (groups.length

                  ? '<ul>' + groupItems + '</ul>'

                  : '<div style="padding: 20px; text-align: center; color: var(--muted); font-size: 13px;">该用户未加入任何已记录群聊</div>') +

              '</div>' +

            '</div>';

        })

        .catch(function (e) {

          body.innerHTML = '<div style="padding: 20px 0; text-align: center; color: #ef4444;">加载失败：' +

            escapeHtml(e && e.message ? e.message : String(e)) + '</div>';

        });

    }

    function closeUserModal() {

      var modal = document.getElementById('user-modal');

      if (!modal) return;

      modal.classList.remove('show');

      setTimeout(function () { modal.classList.remove('active'); }, 200);

    }

    function deleteUser(openid, name) {

      fetch(API_BASE + '/api/c2c-user/delete', {

        method: 'POST',

        headers: { 'Content-Type': 'application/json' },

        body: JSON.stringify({ openid: openid })

      })

        .then(function (r) { return r.json(); })

        .then(function (res) {

          if (res && res.ok) {

            loadUsers();

          } else {

            alert((res && res.error) || '删除失败');

          }

        })

        .catch(function (e) { alert('删除请求失败：' + (e && e.message ? e.message : e)); });

    }

    if (searchBtn) searchBtn.addEventListener('click', loadUsers);

    if (resetBtn) resetBtn.addEventListener('click', function () {

      if (botSel) botSel.value = '';

      if (keywordInput) keywordInput.value = '';

      loadUsers();

    });

    if (keywordInput) keywordInput.addEventListener('keydown', function (e) {

      if (e.key === 'Enter') loadUsers();

    });

    if (botSel) botSel.addEventListener('change', loadUsers);

    if (tbody) {

      tbody.addEventListener('click', function (e) {

        var el = e.target.closest ? e.target.closest('.op-link') : null;

        if (!el) return;

        var act = el.getAttribute('data-act');

        if (act === 'view') {

          var idx = parseInt(el.getAttribute('data-idx'), 10);

          var u = null;

          for (var i = 0; i < lastItems.length; i++) {

            if (lastItems[i].idx === idx) { u = lastItems[i]; break; }

          }

          if (u) openUserModal(u);

        } else if (act === 'delete') {

          var openid = el.getAttribute('data-openid');

          var name = el.getAttribute('data-name') || '该用户';

          if (!openid) return;

          if (window.confirm('确定要删除用户「' + name + '」吗？\n\n该操作会：\n· 从成员记录中移除该用户\n· 清除其群聊关联\n\n且不可恢复。')) {

            deleteUser(openid, name);

          }

        }

      });

    }

    var usrModalClose = document.getElementById('user-modal-close');

    var usrCloseBtn = document.getElementById('user-close-btn');

    if (usrModalClose) usrModalClose.addEventListener('click', closeUserModal);

    if (usrCloseBtn) usrCloseBtn.addEventListener('click', closeUserModal);

    var usrModal = document.getElementById('user-modal');

    if (usrModal) usrModal.addEventListener('click', function (e) {

      if (e.target === usrModal) closeUserModal();

    });

    function onShow() {

      loadUsers();

    }

    loadUsersRef = onShow;

    // 初始即通过 #c2c-list 直达时，switchPage 早于本模块执行，loadUsersRef 尚未赋值；

    // 此时页面已被标记为 active 但未加载数据，故在此补一次加载。

    if (document.getElementById('page-c2c-list') &&

        document.getElementById('page-c2c-list').classList.contains('active')) {

      onShow();

    }

  })();

  // ============================================================

  // 功能配置中心

  // ============================================================

  (function featureConfigCenter() {

    var currentCat = 'checkin';

    var currentTab = 'config';

    var switches = {};

    var serverSwitches = {};

    var systemCategories = {

      checkin: {

        name: '签到系统', icon: '📝', sub: '每日签到领取积分与金币',

        items: [

          { k: 'checkin', name: '系统总开关', emoji: '📝', desc: '开启后整体启用签到系统', master: true },

          { k: 'checkin_sign', name: '每日签到', emoji: '✍️', desc: '发送「签到」领取积分与金币' },

          { k: 'checkin_rank', name: '签到排名', emoji: '🏆', desc: '发送「签到排名」查看群内排行' },

          { k: 'checkin_query', name: '签到查询', emoji: '🔎', desc: '发送「签到查询」查看个人状态' },

          { k: 'checkin_lottery', name: '积分抽奖', emoji: '🎰', desc: '发送「抽奖」消耗积分抽取随机奖励' }

        ]

      },

      video: {

        name: '视频系统', icon: '🎬', sub: 'B站视频搜索与推送',

        items: [

          { k: 'video', name: '系统总开关', emoji: '🎬', desc: '开启后整体启用视频系统', master: true },

          { k: 'video_shuaige', name: '帅哥视频', emoji: '🤵', desc: '发送「帅哥视频」推送' },

          { k: 'video_fengjing', name: '风景视频', emoji: '🏞️', desc: '发送「风景视频」推送' },

          { k: 'video_bianzhuang', name: '变装视频', emoji: '💃', desc: '发送「变装视频」推送' },

          { k: 'video_cos', name: 'cos视频', emoji: '🎭', desc: '发送「cos视频」推送' },

          { k: 'video_manjian', name: '漫剪视频', emoji: '🎞️', desc: '发送「漫剪视频」推送' },

          { k: 'video_youxi', name: '游戏视频', emoji: '🕹️', desc: '发送「游戏视频」推送' }

        ]

      },

      music: {

        name: '音乐系统', icon: '🎵', sub: '点歌与音乐相关功能',

        items: [

          { k: 'music', name: '系统总开关', emoji: '🎵', desc: '开启后整体启用音乐系统', master: true },

          { k: 'music_random', name: '随机音乐', emoji: '🎲', desc: '发送「随机音乐」随机推荐' },

          { k: 'music_source', name: '音源选择', emoji: '🔀', desc: '发送「音源 / 音源选择」切换音源' },

          { k: 'music_search', name: '点歌', emoji: '🎤', desc: '发送「点歌 歌名」搜索点播' },

          { k: 'music_select', name: '选歌', emoji: '✔️', desc: '发送「选歌」从结果中选择' }

        ]

      },

      game: {

        name: '娱乐系统', icon: '🎮', sub: '棋类与互动游戏',

        items: [

          { k: 'game', name: '系统总开关', emoji: '🎮', desc: '开启后整体启用娱乐系统', master: true },

          { k: 'game_gomoku', name: '五子棋', emoji: '⚫', desc: '发送「五子棋」AI / 双人対战' },

          { k: 'game_idiom', name: '看图猜成语', emoji: '🀄', desc: '发送「猜成语」开始游戏' },

          { k: 'game_xiangqi', name: '中国象棋', emoji: '♟️', desc: '发送「象棋」AI / 双人対战' },

          { k: 'game_qiuqian', name: '观音灵签', emoji: '🎲', desc: '发送「求签」随机抽取观音灵签' },

          { k: 'game_daanzi', name: '答案之书', emoji: '🔮', desc: '发送「答案之书 问题」抽取随机答案' },

          { k: 'game_tarot', name: '塔罗牌', emoji: '🃏', desc: '发送「塔罗牌」抽取 4 张牌面揭示过去/现在/未来' },

          { k: 'game_horoscope', name: '今日运势', emoji: '🔮', desc: '发送「运势 星座」查运势' },

        ]

      },

      tools: {

        name: '工具系统', icon: '🛠', sub: '实用工具类功能',

        items: [

          { k: 'tools', name: '系统总开关', emoji: '🛠', desc: '开启后整体启用工具系统', master: true },

          { k: 'tool_weather', name: '天气查询', emoji: '🌤️', desc: '发送「天气 城市」查询天气' },

          { k: 'tool_wangzhe', name: '王者信息查询', emoji: '👑', desc: '发送「王者 英雄」查战力' },

          { k: 'tool_word', name: '单词详解', emoji: '🔤', desc: '发送「单词 英文」查释义' },

          { k: 'tool_video_parse', name: '视频解析', emoji: '🔗', desc: '发送「视频解析」+ 链接，支持抖音/快手/B站/小红书/视频号/YouTube/TikTok 等 20+ 平台' },

          { k: 'tool_disease', name: '疾病信息', emoji: '🏥', desc: '发送「疾病信息 名称」查询常见疾病百科' },

          { k: 'tool_waste', name: '垃圾分类', emoji: '🗑️', desc: '发送「垃圾分类 名称」查询分类（可回收 / 有害 / 湿 / 干 / 大件）' },

        ]      },

      novel: {

        name: '小说系统', icon: '📖', sub: '古典名著本地库（公有领域，本地阅读）',

        items: [

          { k: 'novel', name: '系统总开关', emoji: '📖', desc: '开启后整体启用小说系统', master: true },

          { k: 'novel_menu', name: '书库浏览', emoji: '📚', desc: '发送「小说」查看古典名著书目与分类' },

          { k: 'novel_read', name: '在线阅读', emoji: '📕', desc: '发送「看 / 读 书名」开始阅读古典名著' }

        ]

      },

      study: {

        name: '学习系统', icon: '📚', sub: '学科题库与答题',

        items: [

          { k: 'study', name: '系统总开关', emoji: '📚', desc: '开启后整体启用学习系统', master: true },

          { k: 'study_menu', name: '学习菜单', emoji: '🗂️', desc: '发送「学习」打开科目菜单' },

          { k: 'study_query', name: '题库查询', emoji: '❓', desc: '发送「科目 文字/图片」搜题' },

          { k: 'study_answer', name: '答题判分', emoji: '✅', desc: '发送「作答 科目」进入作答' }

        ]

      },

      group_admin: {

        name: '群管系统', icon: '⚙️', sub: '群管相关功能（仅在群聊生效）',

        items: [

          { k: 'group_admin', name: '系统总开关', emoji: '⚙️', desc: '开启后整体启用群管系统', master: true },

          { k: 'admin_banlist', name: '违禁词列表', emoji: '📋', desc: '发送「违禁词列表」查看（所有人可用，无需权限）' },

          { k: 'admin_banset', name: '违禁词设置', emoji: '⚒️', desc: '发送「违禁词设置」管理菜单（所有人可用，无需权限）' },

          { k: 'admin_banadd', name: '违禁词添加', emoji: '➕', desc: '发送「违禁词添加 词」（所有人可用，无需权限）' },

          { k: 'admin_bandel', name: '违禁词删除', emoji: '➖', desc: '发送「违禁词删除 词」（所有人可用，无需权限）' },

          { k: 'admin_automod', name: '违禁词自动过滤', emoji: '🚫', desc: '自动检测并撤回含违禁词消息（对所有人生效，无需权限）' },

          { k: 'admin_mute', name: '禁言管理', emoji: '🔇', desc: '发送「禁言管理」打开菜单（设置时长/自动处理/手动禁言/解除禁言），仅群主/管理员/控制台管理员' },

          { k: 'admin_mute_automod', name: '违禁词自动禁言', emoji: '🎚', desc: '每群独立开关与时长：违禁词命中后自动禁言触发用户（默认 600 秒），需机器人是群管理员' },

          { k: 'admin_chime', name: '整点报时', emoji: '⏰', desc: '发送「整点报时」打开报时菜单（开关 / 设置 / 立即报时），仅群主/管理员/控制台管理员' }

        ]

      },

      image: {

        name: '图片系统', icon: '🖼️', sub: '通用随机美图（二次元 / 风景 / 随机壁纸 / 原神cos / 原神 / 小姐姐）+ 角色图库（流萤专属相册，按角色名检索）',

        items: [

          { k: 'image', name: '系统总开关', emoji: '🖼️', desc: '开启后整体启用图片系统', master: true },

          { k: 'image_acg', name: '二次元', emoji: '🎨', desc: '发送「二次元」随机4K二次元插画' },

          { k: 'image_wallpaper', name: '风景', emoji: '🌄', desc: '发送「风景」随机4K风景壁纸' },

          { k: 'image_bizhi', name: '随机壁纸', emoji: '🖼️', desc: '发送「随机壁纸」随机高清壁纸' },

          { k: 'image_yscos', name: '原神cos', emoji: '🎭', desc: '发送「原神cos」随机原神cosplay图片' },

          { k: 'image_ys', name: '原神', emoji: '🌟', desc: '发送「原神」随机原神图片' },

          { k: 'image_meinvpic', name: '小姐姐', emoji: '👧', desc: '发送「小姐姐」随机美图（小小API meinvpic）' },

          { k: 'image_random', name: '角色图库', emoji: '🎲', desc: '发送「角色图库」从 photo.likefirefly.com 流萤专属相册按角色名检索，随机返回一张图（与通用随机图不同）' }

        ]

      }

    };

    // 由 systemCategories 自动生成默认开关（含总开关与所有子功能，默认开启）

    var defaultSwitches = {};

    Object.keys(systemCategories).forEach(function (cat) {

      systemCategories[cat].items.forEach(function (it) { defaultSwitches[it.k] = true; });

    });

    var menu = document.getElementById('feature-menu');

    var titleEl = document.getElementById('feature-panel-title');

    var subEl = document.getElementById('feature-panel-sub');

    var formBody = document.getElementById('feature-form-body');

    var banner = document.getElementById('feature-info-banner');

    var saveBtn = document.getElementById('feature-save-btn');

    var resetBtn = document.getElementById('feature-reset-btn');

    var enableAllBtn = document.getElementById('feature-enable-all');

    var disableAllBtn = document.getElementById('feature-disable-all');

    var configPanel = document.getElementById('feature-config-panel');

    var flowPanel = document.getElementById('feature-flow-panel');

    var videoLimitsPanel = document.getElementById('feature-video-limits-panel');

    var chimePanel = document.getElementById('feature-chime-panel');

    var welcomePanel = document.getElementById('feature-welcome-panel');

    var checkinRulesPanel = document.getElementById('feature-checkin-rules-panel');
    var bannedMutePanel = document.getElementById('feature-banned-mute-panel');
    var banwordLogPanel = document.getElementById('feature-banword-log-panel');

    var flowSteps = document.getElementById('feature-flow-steps');

    // === 多机器人独立功能配置 ===

    var currentBot = '';              // 当前选中机器人 appid；空串 = 全局默认

    var botSwitches = {};             // 服务端整体 bot_switches dict: {appid: {key:bool}}

    var serverSwitchesGlobal = {};    // 服务端全局 switches（_system_switches）

    var availableBots = [];           // 服务端 _list_runtime_bots().bots 列表

    var botSelectEl = document.getElementById('feature-bot-select');

    var botDotEl = document.getElementById('feature-bot-dot');

    var resetBotBtn = document.getElementById('feature-reset-bot-btn');

    var scopeHintEl = document.getElementById('feature-scope-hint');

    if (!menu || !formBody) return;

    function mergeSwitches(saved) {

      var out = {};

      Object.keys(defaultSwitches).forEach(function (k) { out[k] = defaultSwitches[k]; });

      if (saved) { Object.keys(saved).forEach(function (k) { out[k] = !!saved[k]; }); }

      return normalizeSwitches(out);

    }

    // 总开关关闭时，强制把该系统下所有子功能开关置为 false，保持前后端一致

    function normalizeSwitches(state) {

      Object.keys(systemCategories).forEach(function (cat) {

        var items = systemCategories[cat].items;

        if (!items || !items.length) return;

        var masterKey = items[0].k;

        if (!state[masterKey]) {

          items.forEach(function (it) {

            if (!it.master) state[it.k] = false;

          });

        }

      });

      return state;

    }

    function renderMenu() {

      var html = '';

      Object.keys(systemCategories).forEach(function (cat) {

        var c = systemCategories[cat];

        var active = cat === currentCat ? ' active' : '';

        html += '<div class="feature-menu-item' + active + '" data-cat="' + cat + '"><span class="ico">' + c.icon + '</span>' + c.name + '</div>';

      });

      menu.innerHTML = html;

    }

    function switchHtml(item, on, disabled) {

      return '<label class="switch' + (disabled ? ' disabled' : '') + '">' +

        '<input type="checkbox" data-key="' + item.k + '"' + (on ? ' checked' : '') + (disabled ? ' disabled' : '') + '>' +

        '<span class="track"></span><span class="thumb"></span>' +

      '</label>';

    }

    function renderCategory() {

      var c = systemCategories[currentCat];

      if (!c) return;

      if (titleEl) titleEl.textContent = c.icon + ' ' + c.name;

      if (subEl) subEl.textContent = c.sub;

      if (c.pluginManager) { renderPluginManager(); return; }

      var masterKey = c.items[0].k;

      var masterOn = !!switches[masterKey];

      var html = '<div class="switch-list">';

      c.items.forEach(function (item) {

        var on = switches[item.k] !== undefined ? switches[item.k] : (defaultSwitches[item.k] || false);

        if (item.master) {

          html += '<div class="switch-row master-row">' +

            '<div class="meta">' +

              '<div class="name"><span class="emoji">' + item.emoji + '</span>' + escapeHtml(item.name) +

                ' <span class="master-badge">总开关</span></div>' +

              '<div class="desc">' + escapeHtml(item.desc) + '</div>' +

            '</div>' +

            switchHtml(item, on) +

          '</div>';

          html += '<div class="switch-divider">子功能</div>';

          return;

        }

        var botOverride = currentBot && botSwitches[currentBot] && (item.k in botSwitches[currentBot]);

        var effectiveGlobalVal = (serverSwitchesGlobal[item.k] !== undefined) ? !!serverSwitchesGlobal[item.k] : !!defaultSwitches[item.k];

        var badge = '';

        if (currentBot) {

          if (botOverride) {

            badge = ' <span class="override-badge" style="display:inline-block;padding:1px 6px;margin-left:6px;font-size:11px;border-radius:8px;background:#ede9fe;color:#6d28d9;">已覆盖</span>';

          } else {

            badge = ' <span class="inherit-badge" style="display:inline-block;padding:1px 6px;margin-left:6px;font-size:11px;border-radius:8px;background:#f3f4f6;color:#6b7280;">继承</span>';

          }

        }

        html += '<div class="switch-row' + (masterOn ? '' : ' disabled') + '">' +

          '<div class="meta">' +

            '<div class="name"><span class="emoji">' + item.emoji + '</span>' + escapeHtml(item.name) + badge + '</div>' +

            '<div class="desc">' + escapeHtml(item.desc) + (currentBot ? ' · 全局值: ' + (effectiveGlobalVal ? '开' : '关') : '') + '</div>' +

          '</div>' +

          switchHtml(item, on, !masterOn) +

        '</div>';

      });

      html += '</div>';

      formBody.innerHTML = html;

    }

    function renderPluginManager() {
      if (!formBody) return;
      formBody.innerHTML = '<div class="pm-loading">加载插件列表…</div>';
      fetch(API_BASE + '/api/plugins', { cache: 'no-store' })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          // 展示全部插件（内置 + 外置），按 is_external 正确打标（C3 修复：内置插件不再被隐藏）
          var plugs = (data && data.plugins || []);
          if (!plugs.length) {
            formBody.innerHTML = '<div class="pm-empty">当前没有已安装的插件。</div>';
            return;
          }
          plugs.sort(function (a, b) {
            return (a.priority || 0) - (b.priority || 0);
          });
          var rows = plugs.map(function (p) {
            var tag = p.is_external
              ? '<span class="pm-tag pm-tag-ext">外置</span>'
              : '<span class="pm-tag pm-tag-builtin">内置</span>';
            var desc = p.description ? escapeHtml(p.description) : '<span class="pm-muted">无描述</span>';
            // 内置插件由「功能开关」统一控制，无启停开关；仅外置插件显示开关
            var toggle = p.is_external
              ? '<label class="pm-switch" title="启用/停用">' +
                  '<input type="checkbox" class="pm-toggle" ' + (p.enabled ? 'checked' : '') + ' data-key="' + escapeHtml(p.key) + '">' +
                  '<span class="slider"></span></label>'
              : '<span class="pm-muted" title="内置插件由功能开关统一控制" style="font-size:12px;padding:4px 10px;border:1px solid var(--border);border-radius:999px;">功能开关</span>';
            return '<div class="pm-row">' +
              '<div class="pm-meta">' +
                '<div class="pm-name">' + escapeHtml(p.name) + ' ' + tag +
                  ' <span class="pm-key">' + escapeHtml(p.key) + '</span></div>' +
                '<div class="pm-desc">' + desc + '</div>' +
              '</div>' +
              '<div class="pm-prio">优先级 ' + (p.priority != null ? p.priority : '-') + '</div>' +
              '<div class="pm-action">' + toggle + '</div>' +
            '</div>';
          }).join('');
          formBody.innerHTML =
            '<div class="pm-toolbar">' +
              '<button id="pm-reload-btn" class="pm-reload-btn">❔️ 热加载外置插件</button>' +
              '<span class="pm-hint">修改 plugins/ 下文件后点此立即生效，无需重启 bot</span>' +
            '</div>' +
            '<div class="pm-list">' + rows + '</div>';
          var reloadBtn = document.getElementById('pm-reload-btn');
          if (reloadBtn) {
            reloadBtn.addEventListener('click', function () {
              reloadBtn.disabled = true;
              reloadBtn.textContent = '⏳ 热加载中…';
              fetch(API_BASE + '/api/plugins/reload', { method: 'POST' })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                  reloadBtn.disabled = false;
                  reloadBtn.textContent = '❔️ 热加载外置插件';
                  if (d && d.ok) {
                    var s = d.stats || {};
                    showToast('已热加载：新增 ' + (s.loaded||0) + ' / 重载 ' + (s.reloaded||0) + ' / 注销 ' + (s.unregistered||0) + (s.errors ? (' / 错误 ' + s.errors) : ''));
                    renderPluginManager();
                  } else {
                    showToast('热加载失败：' + (d && d.error));
                  }
                })
                .catch(function () {
                  reloadBtn.disabled = false;
                  reloadBtn.textContent = '❔️ 热加载外置插件';
                  showToast('⚠️ 热加载请求失败');
                });
            });
          }
        })
        .catch(function () {
          formBody.innerHTML = '<div class="pm-empty">⚠️ 无法加载插件列表，请确认 bot 正在运行。</div>';
        });
    }

    function setConnStatus(ok, msg) {

      var el = document.getElementById('bot-conn-status');

      if (!el) return;

      if (ok) {

        el.className = 'conn-status conn-ok';

        el.textContent = msg || '已连接到机器人，开关修改将实时保存到本地文件并生效';

      } else {

        el.className = 'conn-status conn-fail';

        el.textContent = '⚠️ 无法连接机器人：请先启动 bot.py，否则开关无法保存';

      }

    }

    // 计算「当前作用域」生效开关：defaults ⊇ global switches ⊇ bot switches（若有）

    function computeEffectiveSwitches() {

      var src = {};

      Object.keys(defaultSwitches).forEach(function (k) { src[k] = defaultSwitches[k]; });

      Object.keys(serverSwitchesGlobal).forEach(function (k) { src[k] = !!serverSwitchesGlobal[k]; });

      if (currentBot && botSwitches[currentBot]) {

        Object.keys(botSwitches[currentBot]).forEach(function (k) { src[k] = !!botSwitches[currentBot][k]; });

      }

      return normalizeSwitches(src);

    }



    function renderBotSelector() {

      if (!botSelectEl) return;

      var html = '<option value="">🌐 全局默认（所有机器人）</option>';

      availableBots.forEach(function (b) {

        var name = b.name_rt || _sanitizeName(b.name, b.appid) || b.appid;

        var on = b.connected ? ' ●' : '';

        var cfg = botSwitches[b.appid] ? ' ⌗' : '';

        html += '<option value="' + escapeHtml(b.appid) + '">' + escapeHtml(name) + ' · ' + escapeHtml(b.appid) + on + cfg + '</option>';

      });

      botSelectEl.innerHTML = html;

      botSelectEl.value = currentBot;

      // status dot

      if (botDotEl) {

        if (!currentBot) {

          botDotEl.className = 'bsw-dot bsw-dot-online';

        } else {

          var target = availableBots.filter(function (b) { return b.appid === currentBot; })[0];

          botDotEl.className = 'bsw-dot ' + (target && target.connected ? 'bsw-dot-online' : 'bsw-dot-offline');

        }

      }

      // scope hint text

      if (scopeHintEl) {

        if (!currentBot) {

          scopeHintEl.textContent = '🌐 当前编辑「全局默认」';

          scopeHintEl.style.color = '#2563eb';

        } else {

          var ovr = botSwitches[currentBot] || {};

          var ovrCount = Object.keys(ovr).length;

          var target2 = availableBots.filter(function (b) { return b.appid === currentBot; })[0];

          var disp = target2 ? (target2.name_rt || target2.name || target2.appid) : currentBot;

          scopeHintEl.textContent = '🤖 当前仅编辑：' + disp + '（' + ovrCount + ' 项覆盖，其他开关继承全局）';

          scopeHintEl.style.color = ovrCount > 0 ? '#7c3aed' : '#6b7280';

        }

      }

      if (resetBotBtn) {

        resetBotBtn.disabled = !currentBot || !(botSwitches[currentBot] && Object.keys(botSwitches[currentBot]).length);

        resetBotBtn.style.opacity = resetBotBtn.disabled ? '0.5' : '1';

      }

    }



    function loadConfig() {

      // 加载全局 + bot 列表 + bot_switches

      fetch(API_BASE + '/api/system-config', { cache: 'no-store' })

        .then(function (r) { return r.json(); })

        .then(function (data) {

          serverSwitchesGlobal = (data && data.switches) || {};

          botSwitches = (data && data.bot_switches) || {};

          availableBots = (data && data.bots) || [];

          switches = computeEffectiveSwitches();

          serverSwitches = switches; // for legacy compat

          renderBotSelector();

          renderCategory();

          setConnStatus(true);

        })

        .catch(function () {

          switches = mergeSwitches({});

          renderCategory();

          setConnStatus(false);

        });

    }



    // 切换机器人之前先把当前作用域的修改落盘

    function switchBotScope(newBot) {

      if (newBot === currentBot) return;

      if (pendingSave) {

        // 异步触发一次保存，保持当前作用域

        saveConfig();

      }

      currentBot = newBot || '';

      switches = computeEffectiveSwitches();

      renderBotSelector();

      renderCategory();

    }



    // 重置当前机器人的所有覆盖项

    function resetCurrentBotOverrides() {

      if (!currentBot) { showToast('全局默认无需重置'); return; }

      if (!confirm('确认清空「' + currentBot + '」的所有功能覆盖项？\n该机器人将完全恢复为继承全局默认。')) return;

      fetch(API_BASE + '/api/system-config', {

        method: 'POST',

        headers: { 'Content-Type': 'application/json' },

        body: JSON.stringify({ bot: currentBot, reset: true })

      })

        .then(function (r) { return r.json(); })

        .then(function (data) {

          if (data && data.ok) {

            showToast('已清空覆盖项');

            loadConfig();

          } else {

            showToast('重置失败：' + (data && data.error));

          }

        })

        .catch(function () { showToast('⚠️ 重置失败'); });

    }

    var pendingSave = false;

    var isSaving = false;

    function saveConfig() {

      pendingSave = false;

      if (isSaving) return; // 避免并发保存互相覆盖

      isSaving = true;

      console.log('[featureConfig] 保存开关 (bot=' + currentBot + ')', JSON.parse(JSON.stringify(switches)));

      setConnStatus(true, '保存中…');

      fetch(API_BASE + '/api/system-config', {

        method: 'POST',

        headers: { 'Content-Type': 'application/json' },

        body: JSON.stringify({ bot: currentBot, switches: switches })

      })

        .then(function (r) {

          if (!r.ok) throw new Error('HTTP ' + r.status);

          return r.json();

        })

        .then(function (data) {

          isSaving = false;

          console.log('[featureConfig] 保存响应', data);

          if (data && data.ok) {

            // 重新拉一次（写入侧也会更新 serverSwitchesGlobal / botSwitches）

            fetch(API_BASE + '/api/system-config', { cache: 'no-store' })

              .then(function (r2) { return r2.json(); })

              .then(function (d2) {

                serverSwitchesGlobal = (d2 && d2.switches) || {};

                botSwitches = (d2 && d2.bot_switches) || {};

                availableBots = (d2 && d2.bots) || availableBots;

                renderBotSelector();

                showToast(currentBot ? ('已保存到「' + currentBot + '」覆盖 ✓') : '全局配置已保存 ✓');

                setConnStatus(true, '已连接到机器人，开关已实时保存到本地文件');

              });

          } else {

            var msg = data && data.error ? data.error : '未知错误';

            console.error('[featureConfig] 保存失败:', msg);

            showToast('保存失败：' + msg);

            setConnStatus(false);

          }

        })

        .catch(function (err) {

          isSaving = false;

          console.error('[featureConfig] 保存异常:', err);

          showToast('⚠️ 保存失败：请确认机器人(bot)正在运行');

          setConnStatus(false);

        });

    }

    // 页面关闭/刷新前兜底保存，避免刚改完就离开导致改动丢失

    window.addEventListener('beforeunload', function () {

      if (pendingSave) {

        try {

          fetch(API_BASE + '/api/system-config', {

            method: 'POST',

            headers: { 'Content-Type': 'application/json' },

            body: JSON.stringify({ bot: currentBot, switches: switches }),

            keepalive: true

          });

        } catch (e) {}

      }

    });



    if (botSelectEl) {

      botSelectEl.addEventListener('change', function () {

        switchBotScope(botSelectEl.value);

      });

    }

    if (resetBotBtn) {

      resetBotBtn.addEventListener('click', resetCurrentBotOverrides);

    }

    function showToast(msg) {

      var old = document.getElementById('feature-toast');

      if (old) old.remove();

      var div = document.createElement('div');

      div.id = 'feature-toast';

      div.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#333;color:#fff;padding:10px 20px;border-radius:8px;z-index:9999;font-size:13px;';

      div.textContent = msg;

      document.body.appendChild(div);

      setTimeout(function () { div.remove(); }, 2000);

    }

    if (menu) {

      menu.addEventListener('click', function (e) {

        var item = e.target.closest('.feature-menu-item');

        if (!item) return;

        menu.querySelectorAll('.feature-menu-item').forEach(function (el) { el.classList.remove('active'); });

        item.classList.add('active');

        currentCat = item.getAttribute('data-cat');

        renderCategory();

      });

    }

    if (formBody) {

      formBody.addEventListener('change', function (e) {

        var inp = e.target.closest('.switch input');

        if (!inp) return;

        var key = inp.getAttribute('data-key');

        var c = systemCategories[currentCat];

        var masterKey = c.items[0].k;

        switches[key] = !!inp.checked;

        console.log('[featureConfig] 开关切换:', key, switches[key]);

        // 关闭总开关时，同步关闭该系统的所有子功能并保持 UI 一致

        if (key === masterKey && !inp.checked) {

          c.items.forEach(function (it) {

            if (!it.master) switches[it.k] = false;

          });

          renderCategory();

        }

        pendingSave = true; saveConfig();

      });

    }

    // 外置插件启用/停用开关（仅停止分发，状态持久化，无需重启 bot）
    if (formBody) {
      formBody.addEventListener('change', function (e) {
        var tog = e.target.closest && e.target.closest('.pm-toggle');
        if (!tog) return;
        var key = tog.getAttribute('data-key');
        var enabled = !!tog.checked;
        tog.disabled = true;
        fetch(API_BASE + '/api/plugins/set-enabled', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ key: key, enabled: enabled })
        })
          .then(function (r) { return r.json(); })
          .then(function (j) {
            tog.disabled = false;
            if (j && j.ok) {
              try { showToast(j.message || ('已' + (enabled ? '启用' : '禁用') + '，已保存')); } catch (e) {}
            } else {
              tog.checked = !enabled;
              alert((j && j.error) || '更新启用状态失败');
            }
          })
          .catch(function () {
            tog.disabled = false;
            tog.checked = !enabled;
            alert('更新失败：无法连接到后端');
          });
      });
    }

    if (enableAllBtn) enableAllBtn.addEventListener('click', function () {

      (systemCategories[currentCat].items || []).forEach(function (it) { switches[it.k] = true; });

      renderCategory();

      pendingSave = true; saveConfig();

    });

    if (disableAllBtn) disableAllBtn.addEventListener('click', function () {

      (systemCategories[currentCat].items || []).forEach(function (it) { switches[it.k] = false; });

      renderCategory();

      pendingSave = true; saveConfig();

    });

    document.querySelectorAll('.feature-tab').forEach(function (tab) {

      tab.addEventListener('click', function () {

        document.querySelectorAll('.feature-tab').forEach(function (t) { t.classList.remove('active'); });

        tab.classList.add('active');

        currentTab = tab.getAttribute('data-ftab');

        if (configPanel) configPanel.style.display = currentTab === 'config' ? 'block' : 'none';

        if (flowPanel) flowPanel.style.display = currentTab === 'flow' ? 'block' : 'none';

        if (videoLimitsPanel) videoLimitsPanel.style.display = currentTab === 'video-limits' ? 'block' : 'none';

        if (chimePanel) chimePanel.style.display = currentTab === 'chime' ? 'block' : 'none';

        if (welcomePanel) welcomePanel.style.display = currentTab === 'welcome' ? 'block' : 'none';

        if (checkinRulesPanel) checkinRulesPanel.style.display = currentTab === 'checkin-rules' ? 'block' : 'none';

        if (bannedMutePanel) bannedMutePanel.style.display = currentTab === 'banned-mute' ? 'block' : 'none';

        if (banwordLogPanel) banwordLogPanel.style.display = currentTab === 'banword-log' ? 'block' : 'none';

        if (currentTab === 'welcome') { var we = document.getElementById('welcome-conn-status'); if (we) { we.className = 'conn-status conn-ok'; we.textContent = '已连接到机器人，修改将实时保存到本地文件'; } }

        if (currentTab === 'checkin-rules') { var ce = document.getElementById('checkin-rules-conn-status'); if (ce) { ce.className = 'conn-status conn-ok'; ce.textContent = '已连接到机器人，修改将实时保存到本地文件'; } }

        if (currentTab === 'flow') {

          var active = document.querySelector('#flow-relations .active');

          renderFlowSteps(active ? active.getAttribute('data-flow') : 'checkin');

        }

      });

    });

    var flowStepMap = {

      checkin: [

        '用户发送签到类命令',

        '校验签到系统总开关',

        '识别签到子功能',

        '执行对应签到逻辑',

        '计算奖励与加成',

        '写入用户数据',

        '返回签到结果卡片'

      ],

      video: [

        '用户发送视频类命令',

        '校验视频系统总开关',

        '识别具体视频分类',

        '调用B站搜索接口',

        '筛选并获取视频',

        '构建视频卡片',

        '返回视频给用户'

      ],

      music: [

        '用户发送音乐类命令',

        '校验音乐系统总开关',

        '识别点歌 / 随机 / 音源',

        '调用音乐搜索接口',

        '获取播放链接与封面',

        '返回音乐卡片'

      ],

      game: [

        '用户发送娱乐类命令',

        '校验娱乐系统总开关',

        '识别棋类 / 猜成语 / 求签',

        '初始化对局或出题 / 求签',

        '处理落子 / 作答 / 解签',

        '判定胜负或积分',

        '返回游戏状态'

      ],

      tools: [

        '用户发送工具类命令',

        '校验工具系统总开关',

        '识别天气 / 王者 / 运势等',

        '调用第三方或本地服务',

        '格式化查询结果',

        '返回工具卡片'

      ],

      novel: [

        '用户发送小说类命令',

        '校验小说系统总开关',

        '识别书库浏览或阅读',

        '读取古典名著文本',

        '分页或菜单展示',

        '记录阅读进度',

        '返回小说内容'

      ],

      study: [

        '用户发送学习类命令',

        '校验学习系统总开关',

        '识别题库查询或作答',

        '搜索题目或进入作答',

        '判分并生成解析',

        '返回学习结果'

      ],

      group_admin: [

        '群内触发群管事件',

        '校验群管系统总开关',

        '校验管理员权限',

        '执行违禁词管理',

        '或自动过滤违规消息',

        '违禁词触发后按各群设置自动禁言触发用户',

        '记录操作日志',

        '返回执行结果'

      ],

      group_admin_mute: [

        '用户发送「禁言管理」指令',

        '校验群管系统总开关',

        '校验管理员权限（群主/管理员/控制台管理员）',

        '渲染禁言父菜单（时长 / 自动处理 / 返回）',

        '用户选时长档位或输入「禁言时长 N」',

        '写入 data/group_admin.json 中本群的 mute_duration',

        '返回最新配置',

      ],

      group_admin_banword_auto_mute: [

        '群成员发送消息',

        '校验群管系统总开关',

        'check_banned_word 检测命中违禁词',

        '撤回违规消息并发出通知',

        '读取本群 mute_on_banword 开关',

        '若开启：按 mute_duration（每群独立）调官方 POST /v2/groups/{openid}/restrict_chat_setting',

        '对该成员下禁言（op=add，RFC3339 到期时间）',

        '返回禁言结果（QPM 60/分钟）',

      ],

      group_admin_unmute: [

        '用户发送「解除禁言 <openid>」',

        '校验群管系统总开关',

        '校验管理员权限',

        '调官方 POST /v2/groups/{openid}/restrict_chat_setting',

        '对该成员 op=del 解除禁言（mute_expire_at 为空表示立即解除）',

        '返回解除结果',

      ],

      image: [

        '用户发送图片类命令',

        '校验图片系统总开关',

        '识别具体图片分类',

        '调用对应分类的小小API接口',

        '获取图片直链',

        '下载并上传图片',

        '返回图片与切换按钮'

      ]

    };

    // 签到子功能

    flowStepMap.checkin_sign = [

      '用户发送「签到」',

      '检查今日是否已签到',

      '生成随机积分与金币',

      '计算连续 / 等级加成',

      '写入签到记录',

      '返回签到结果卡片'

    ];

    flowStepMap.checkin_rank = [

      '用户发送「签到排名」',

      '聚合本群签到数据',

      '按积分与连续天数排序',

      '生成排行榜卡片',

      '返回群内排行'

    ];

    flowStepMap.checkin_query = [

      '用户发送「签到查询」',

      '读取个人签到记录',

      '统计连续天数与累计奖励',

      '返回个人签到状态'

    ];

    // 视频子功能

    var videoCatMap = { '帅哥视频': 'shuaige', '风景视频': 'fengjing', '变装视频': 'bianzhuang', 'cos视频': 'cos', '漫剪视频': 'manjian', '游戏视频': 'youxi' };

    Object.keys(videoCatMap).forEach(function (cat) {

      flowStepMap['video_' + videoCatMap[cat]] = [

        '用户发送「' + cat + '」',

        '解析分类关键词',

        '调用B站搜索接口',

        '筛选并获取视频',

        '构建并返回视频卡片'

      ];

    });

    // 音乐子功能

    flowStepMap.music_random = [

      '用户发送「随机音乐」',

      '随机选取一首歌曲',

      '获取播放链接与封面',

      '返回音乐卡片'

    ];

    flowStepMap.music_source = [

      '用户发送「音源 / 音源选择」',

      '展示 4 个可选音源平台：QQ音乐 / 网易云音乐 / 酷狗音乐 / 酷我音乐(OIAPI)',

      '点击按钮或回复「音源 平台名」',

      '写入群维度的音源偏好到 music_source.json（持久化）',

      '返回切换结果「✅ 音源已切换为 XXX」',

      '后续「点歌/选歌/随机音乐」按新音源搜索'

    ];

    flowStepMap.music_search = [

      '用户发送「点歌 歌名」或「点歌 歌名 歌手」',

      '校验音乐系统总开关 + 当前群音源',

      '按当前音源调用对应搜索 API：QQ=client_search_cp / 网易=autumnfish / 酷狗=mobilecdn v3 / 酷我=OIAPI /api/Kuwo?msg=xxx',

      '解析 10 条结果（酷我还为每条写入 _oiapi_kw/_oiapi_n 隐藏字段）',

      '展示编号列表（🆓 可试听 / 🔒 VIP 歌曲）',

      '等待用户「选歌 序号」进入播放阶段'

    ];

    flowStepMap.music_select = [

      '用户发送「选歌 序号」',

      '从群 _search_cache 读取候选列表',

      '按音源拉取播放直链：QQ=u.y.qq.com musicu.fcg / 网易=autumnfish /song/url / 酷狗=自建代理签名 / 酷我=OIAPI /api/Kuwo?msg=xxx&n=N&page=1',

      '酷我音频直链带 Referer 防盗链（kuwo.cn），send_audio_for_scene 按音源切换 headers',

      '下载音频转 MP3，以语音消息发送（file_type=3）',

      '附带封面图 + 「再来一首」按钮'

    ];

    // 图片子功能

    flowStepMap.image_acg = [

      '用户发送「二次元」',

      '校验图片系统与二次元子开关',

      '调用小小API random4kPic(type=acg)',

      '获取随机4K二次元图直链',

      '下载图片并上传QQ',

      '返回图片与「看其他类型」按钮'

    ];

    flowStepMap.image_wallpaper = [

      '用户发送「风景」',

      '校验图片系统与风景子开关',

      '调用小小API random4kPic(type=wallpaper)',

      '获取随机4K风景图直链',

      '下载图片并上传QQ',

      '返回图片与「看其他类型」按钮'

    ];

    flowStepMap.image_bizhi = [

      '用户发送「随机壁纸」',

      '校验图片系统与随机壁纸子开关',

      '调用小小API wallpaper（独立端点）',

      '获取随机高清壁纸直链',

      '下载图片并上传QQ',

      '返回图片与「看其他类型」按钮'

    ];

    flowStepMap.image_yscos = [

      '用户发送「原神cos」',

      '校验图片系统与原神cos子开关',

      '调用小小API yscos（独立端点）',

      '获取随机原神cosplay图直链',

      '下载图片并上传QQ',

      '返回图片与「看其他类型」按钮'

    ];

    flowStepMap.image_ys = [

      '用户发送「原神」',

      '校验图片系统与原神子开关',

      '调用小小API ys（独立端点）',

      '获取随机原神图直链',

      '下载图片并上传QQ',

      '返回图片与「看其他类型」按钮'

    ];

    flowStepMap.image_meinvpic = [

      '用户发送「小姐姐」',

      '校验图片系统与小姐姐子开关',

      '调用小小API meinvpic（独立端点）',

      '获取随机美图直链',

      '下载图片并上传QQ',

      '返回图片与「看其他类型」按钮'

    ];

    flowStepMap.image_random = [

      '用户发送「角色图库」或「角色图库 关键字」（旧别名 随机图片/随机图/看图 仍可用）',

      '校验图片系统与角色图库子开关',

      'on_ready 启动时预热分类缓存（photo.likefirefly.com /api?list）',

      '无关键字：展示 top-N 角色分类菜单（3/行 + 全部随机 + 返回）',

      '有关键字：子串模糊匹配角色分类名',

      '调用 /api?type=<name> 跟随 302 得到 QQ 群相册直链',

      'send_image_for_scene 下载并上传QQ',

      '返回图片与「再来一张 / 全部随机 / 返回」按钮'

    ];

    // 娱乐子功能

    flowStepMap.game_gomoku = [

      '用户发送「五子棋」',

      '选择对战模式（AI / 双人）',

      '初始化棋盘',

      '落子并校验合法性',

      '判定胜负或继续对局',

      '返回棋盘状态'

    ];

    flowStepMap.game_idiom = [

      '用户发送「猜成语」',

      '拉取看图猜成语题目',

      '展示图片与操作按钮',

      '接收用户答案',

      '判定正误并计分',

      '返回成绩与解析'

    ];

    flowStepMap.game_xiangqi = [

      '用户发送「象棋」',

      '选择对战模式（AI / 双人）',

      '初始化棋局',

      '走子并校验合法性',

      '判定将死或继续',

      '返回棋局状态'

    ];

    flowStepMap.game_qiuqian = [

      '用户发送「求签」',

      '校验娱乐系统与观音灵签子开关',

      '调用小小API guanyinrandom',

      '解析签文（签名/吉凶/宫位/签诗/卦象/解签）',

      '返回签文文本与签文配图',

      '附「再求一签」「返回主菜单」按钮'

    ];

    flowStepMap.game_daanzi = [

      '用户发送「答案之书 问题」（或点击「🔮 答案之书」按钮后输入问题）',

      '校验娱乐系统与答案之书子开关',

      '调用小小API answers（question 参数）',

      '解析答案文本',

      '返回「问题 + 答案」卡片',

      '附「再问一次」「返回主菜单」按钮'

    ];

    flowStepMap.game_tarot = [

      '用户发送「塔罗牌」',

      '校验娱乐系统与塔罗牌子开关',

      '调用 OIAPI Tarot（完全免鉴权 GET https://oiapi.net/api/Tarot）',

      '解析 4 张牌（过去/现在/未来/切牌）',

      '提取每张牌：position（牌位）/ meaning（牌位含义）/ name_cn / name_en / type（正/逆位）/ 牌意解释',

      '发送「4 张牌位 + 名称 + 状态 + 牌位含义 + 牌意」长文本',

      '依次发送 4 张牌图（pic URL → 上传，缺失自动跳过）',

      '附「再抽一次」「返回主菜单」按钮'

    ];

    // 工具子功能

    flowStepMap.tool_weather = [

      '用户发送「天气 城市」',

      '解析城市名',

      '调用天气查询接口',

      '格式化天气信息',

      '返回天气卡片'

    ];

    flowStepMap.tool_wangzhe = [

      '用户发送「王者 英雄」',

      '解析英雄名与平台',

      '查询英雄战力门槛',

      '返回英雄资料与战力'

    ];

    flowStepMap.game_horoscope = [

      '用户发送「运势 星座」',

      '解析星座参数',

      '调用运势接口',

      '返回今日运势'

    ];

    flowStepMap.tool_word = [

      '用户发送「单词 英文」',

      '解析目标单词',

      '查询释义与例句',

      '返回单词详解'

    ];

    flowStepMap.tool_video_parse = [

      '用户发送「视频解析」',

      '等待用户发送链接（抖音/快手/B站/小红书/视频号/YouTube/TikTok 等 20+ 平台）',

      '识别平台类型（30+ 域名）',

      '调用小渡聚合 API（openapi.dwo.cc/api/svparse）',

      '小渡失败 → 抖音/B站 触发专属解析兜底',

      '区分类型：video → 下载字节上传 / image → 图集逐张发送',

      '校验时长与大小限制（视频限制配置）',

      '发送视频文件或图集 → 回复成功'

    ];

    flowStepMap.tool_disease = [

      '用户发送「疾病信息 名称」（或点击「🏥 疾病信息」按钮后输入名称）',

      '校验工具系统与疾病信息子开关',

      '调用小小API disease（word 参数）',

      '解析疾病百科（简介/病因/症状/治疗/用药/预防等）',

      '返回疾病信息卡片',

      '附「再查一次」「返回主菜单」按钮'

    ];

    flowStepMap.tool_waste = [

      '用户发送「垃圾分类 名称」（或点击「🗑️ 垃圾分类」按钮后输入垃圾名）',

      '校验工具系统与垃圾分类子开关',

      '调用 OIAPI WasteSorting（word 参数）',

      '解析候选列表（list 字段）',

      '列表长度 = 1 → 直接返回「X 是 Y 垃圾」结果卡片',

      '列表长度 > 1 → 展示前 8 个候选 + 提示选序号，记入上下文',

      '用户回复序号（1-8）→ 再次调 OIAPI（word + n=N）拿最终结论',

      '返回「♻️ X 是 Y 垃圾」结果卡片（带 emoji + 数据来源）'

    ];

    // 小说子功能

    flowStepMap.novel_menu = [

      '用户发送「小说」',

      '读取书库书目',

      '展示书目与分类',

      '返回书库主菜单'

    ];

    flowStepMap.novel_read = [

      '用户发送「看 / 读 书名」',

      '在书库中查找书籍',

      '定位到目标章节',

      '分页推送内容',

      '记录阅读进度',

      '返回章节内容'

    ];

    // 学习子功能

    flowStepMap.study_menu = [

      '用户发送「学习」',

      '展示科目菜单',

      '返回可选题库列表'

    ];

    flowStepMap.study_query = [

      '用户发送「科目 文字 / 图片」',

      '解析科目与题型',

      '搜索匹配题目',

      '返回题目卡片'

    ];

    flowStepMap.study_answer = [

      '用户发送「作答 科目」',

      '进入作答模式',

      '按顺序展示题目',

      '接收答案并判分',

      '返回成绩与解析'

    ];

    // 群管子功能

    flowStepMap.admin_banlist = [

      '用户发送「违禁词列表」',

      '校验管理员权限',

      '读取群违禁词库',

      '返回词库列表'

    ];

    flowStepMap.admin_banset = [

      '用户发送「违禁词设置」',

      '校验管理员权限',

      '展示管理菜单',

      '返回操作指引'

    ];

    flowStepMap.admin_banadd = [

      '用户发送「违禁词添加 词」',

      '校验管理员权限',

      '写入新的违禁词',

      '返回添加结果'

    ];

    flowStepMap.admin_bandel = [

      '用户发送「违禁词删除 词」',

      '校验管理员权限',

      '移除指定违禁词',

      '返回删除结果'

    ];

    flowStepMap.admin_automod = [

      '群成员发送消息',

      '自动检测是否含违禁词',

      '命中则撤回违规消息',

      '记录违规日志',

      '可选提示管理员'

    ];

    function resolveFlowKey(flow) {
      if (flowStepMap[flow]) return flow;
      // 子功能未单独定义流程图时，回退到所属分类的主流程
      for (var cat in systemCategories) {
        var its = systemCategories[cat].items || [];
        for (var i = 0; i < its.length; i++) {
          if (its[i].k === flow) return cat;
        }
      }
      return flow;
    }

    function renderFlowSteps(flow) {

      if (!flowSteps) return;

      var key = resolveFlowKey(flow);
      var steps = flowStepMap[key] || [];

      flowSteps.innerHTML = steps.map(function (s, i) {

        return '<li><span class="idx">' + (i + 1) + '</span>' + escapeHtml(s) + '</li>';

      }).join('');

      renderFlowCanvas(key);

    }

    // 流程图平移 / 缩放状态与交互
    var _flowState = { tx: 0, ty: 0, scale: 1 };
    var _flowPanning = false, _flowPanSX = 0, _flowPanSY = 0, _flowPanTX = 0, _flowPanTY = 0;

    function _applyFlowTransform(svg) {
      if (!svg) return;
      svg.style.transformOrigin = '0 0';
      svg.style.transform = 'translate(' + _flowState.tx + 'px,' + _flowState.ty + 'px) scale(' + _flowState.scale + ')';
      var zl = document.getElementById('flow-zoom-label');
      if (zl) zl.textContent = Math.round(_flowState.scale * 100) + '%';
    }

    function _zoomFlowAt(canvas, cx, cy, factor) {
      var ns = Math.min(4, Math.max(0.3, _flowState.scale * factor));
      _flowState.tx = cx - (cx - _flowState.tx) * (ns / _flowState.scale);
      _flowState.ty = cy - (cy - _flowState.ty) * (ns / _flowState.scale);
      _flowState.scale = ns;
      _applyFlowTransform(canvas._flowSvg);
    }

    function _bindFlowCanvasOnce(canvas) {
      if (canvas._flowBound) return;
      canvas._flowBound = true;
      canvas.addEventListener('mousedown', function (e) {
        _flowPanning = true; _flowPanSX = e.clientX; _flowPanSY = e.clientY;
        _flowPanTX = _flowState.tx; _flowPanTY = _flowState.ty;
        e.preventDefault();
      });
      window.addEventListener('mousemove', function (e) {
        if (!_flowPanning) return;
        _flowState.tx = _flowPanTX + (e.clientX - _flowPanSX);
        _flowState.ty = _flowPanTY + (e.clientY - _flowPanSY);
        _applyFlowTransform(canvas._flowSvg);
      });
      window.addEventListener('mouseup', function () { _flowPanning = false; });
      canvas.addEventListener('wheel', function (e) {
        e.preventDefault();
        var rect = canvas.getBoundingClientRect();
        _zoomFlowAt(canvas, e.clientX - rect.left, e.clientY - rect.top, e.deltaY < 0 ? 1.12 : 0.89);
      }, { passive: false });
      var zin = document.getElementById('flow-zoom-in');
      var zout = document.getElementById('flow-zoom-out');
      var zreset = document.getElementById('flow-zoom-reset');
      if (zin) zin.addEventListener('click', function () {
        var r = canvas.getBoundingClientRect(); _zoomFlowAt(canvas, r.width / 2, r.height / 2, 1.2);
      });
      if (zout) zout.addEventListener('click', function () {
        var r = canvas.getBoundingClientRect(); _zoomFlowAt(canvas, r.width / 2, r.height / 2, 0.83);
      });
      if (zreset) zreset.addEventListener('click', function () {
        _flowState.tx = 0; _flowState.ty = 0; _flowState.scale = 1; _applyFlowTransform(canvas._flowSvg);
      });
    }

    function renderFlowCanvas(flow) {

      var canvas = document.getElementById('feature-flow-canvas');

      if (!canvas) return;

      var host = document.getElementById('feature-flow-svg-host');

      if (!host) return;

      var steps = flowStepMap[flow] || [];

      if (!steps.length) {

        host.innerHTML = '<div class="flow-empty">暂无流程数据</div>';

        return;

      }

      // 每次切换流程回到默认视图
      _flowState.tx = 0; _flowState.ty = 0; _flowState.scale = 1;

      var nodeW = 220;

      var lineH = 18;

      var maxChars = 13;

      var gapY = 32;

      var nodeRadius = 10;

      var startColor = '#7c5cff';

      var normalColor = '#2c2c4a';

      var endColor = '#2d5a3d';

      var strokeColor = '#7c5cff';

      var textColor = '#fff';

      var arrowColor = '#a5a5c5';

      function wrapLines(text) {

        var lines = [];

        var current = '';

        for (var i = 0; i < text.length; i++) {

          current += text[i];

          if (current.length >= maxChars) {

            lines.push(current);

            current = '';

          }

        }

        if (current) lines.push(current);

        if (!lines.length) lines.push('');

        return lines;

      }

      var nodes = steps.map(function (s) {

        var lines = wrapLines(s);

        return { lines: lines, h: Math.max(48, 22 + lines.length * lineH) };

      });

      var svgW = 420;

      var y = 20;

      nodes.forEach(function (n) {

        n.x = (svgW - nodeW) / 2;

        n.y = y;

        n.w = nodeW;

        y += n.h + gapY;

      });

      var svgH = Math.max(180, y - gapY + 30);

      var svgNS = 'http://www.w3.org/2000/svg';

      var svg = document.createElementNS(svgNS, 'svg');

      svg.setAttribute('width', '100%');

      svg.setAttribute('height', '100%');

      svg.setAttribute('viewBox', '0 0 ' + svgW + ' ' + svgH);

      svg.style.maxWidth = svgW + 'px';

      var defs = document.createElementNS(svgNS, 'defs');

      var marker = document.createElementNS(svgNS, 'marker');

      marker.setAttribute('id', 'flow-arrow');

      marker.setAttribute('markerWidth', '10');

      marker.setAttribute('markerHeight', '7');

      marker.setAttribute('refX', '9');

      marker.setAttribute('refY', '3.5');

      marker.setAttribute('orient', 'auto');

      var poly = document.createElementNS(svgNS, 'polygon');

      poly.setAttribute('points', '0 0, 10 3.5, 0 7');

      poly.setAttribute('fill', arrowColor);

      marker.appendChild(poly);

      defs.appendChild(marker);

      svg.appendChild(defs);

      nodes.forEach(function (n, i) {

        var fill = i === 0 ? startColor : (i === nodes.length - 1 ? endColor : normalColor);

        var rect = document.createElementNS(svgNS, 'rect');

        rect.setAttribute('x', n.x);

        rect.setAttribute('y', n.y);

        rect.setAttribute('width', n.w);

        rect.setAttribute('height', n.h);

        rect.setAttribute('rx', nodeRadius);

        rect.setAttribute('ry', nodeRadius);

        rect.setAttribute('fill', fill);

        rect.setAttribute('stroke', strokeColor);

        rect.setAttribute('stroke-width', (i === 0 || i === nodes.length - 1) ? '0' : '1.5');

        svg.appendChild(rect);

        var text = document.createElementNS(svgNS, 'text');

        text.setAttribute('x', n.x + n.w / 2);

        text.setAttribute('y', n.y + n.h / 2 - ((n.lines.length - 1) * lineH) / 2 + 5);

        text.setAttribute('text-anchor', 'middle');

        text.setAttribute('fill', textColor);

        text.setAttribute('font-size', '13');

        text.setAttribute('font-family', 'system-ui, -apple-system, "Microsoft YaHei", sans-serif');

        n.lines.forEach(function (line, li) {

          var tspan = document.createElementNS(svgNS, 'tspan');

          tspan.setAttribute('x', n.x + n.w / 2);

          tspan.setAttribute('dy', li === 0 ? '0' : lineH);

          tspan.textContent = line;

          text.appendChild(tspan);

        });

        svg.appendChild(text);

        if (i > 0) {

          var prev = nodes[i - 1];

          var line = document.createElementNS(svgNS, 'line');

          line.setAttribute('x1', prev.x + prev.w / 2);

          line.setAttribute('y1', prev.y + prev.h);

          line.setAttribute('x2', n.x + n.w / 2);

          line.setAttribute('y2', n.y);

          line.setAttribute('stroke', arrowColor);

          line.setAttribute('stroke-width', '2');

          line.setAttribute('marker-end', 'url(#flow-arrow)');

          svg.appendChild(line);

        }

      });

      host.innerHTML = '';

      host.appendChild(svg);

      canvas._flowSvg = svg;

      _applyFlowTransform(svg);

      // 默认水平居中
      if (_flowState.scale === 1) {
        var hw = host.clientWidth || 0;
        if (hw > 420) { _flowState.tx = (hw - 420) / 2; _applyFlowTransform(svg); }
      }

      _bindFlowCanvasOnce(canvas);

    }

    // 构建左侧「关联功能」分组列表（系统 + 子功能），支持展开 / 折叠

    function buildFlowRelations() {

      var box = document.getElementById('flow-relations');

      if (!box) return;

      var html = '';

      Object.keys(systemCategories).forEach(function (cat, idx) {

        var c = systemCategories[cat];

        var expanded = idx === 0;

        html += '<div class="flow-sys' + (expanded ? ' open' : '') + '" data-flow="' + cat + '">' +

          '<span class="fs-ico">' + c.icon + '</span>' +

          '<span class="fs-name">' + escapeHtml(c.name) + '</span>' +

          '<span class="fs-caret">▾</span></div>';

        html += '<div class="flow-subs" style="display:' + (expanded ? 'block' : 'none') + ';">';

        c.items.forEach(function (it) {

          if (it.master) return;

          html += '<div class="flow-sub" data-flow="' + it.k + '"><span class="fs-emoji">' + it.emoji + '</span>' + escapeHtml(it.name) + '</div>';

        });

        html += '</div>';

      });

      box.innerHTML = html;

      var firstSys = box.querySelector('.flow-sys');

      if (firstSys) firstSys.classList.add('active');

    }

    function bindFlowRelations() {

      var box = document.getElementById('flow-relations');

      if (!box) return;

      box.addEventListener('click', function (e) {

        var sub = e.target.closest('.flow-sub');

        var sys = e.target.closest('.flow-sys');

        if (sub) {

          box.querySelectorAll('.active').forEach(function (el) { el.classList.remove('active'); });

          sub.classList.add('active');

          renderFlowSteps(sub.getAttribute('data-flow'));

          return;

        }

        if (sys) {

          var subs = sys.nextElementSibling;

          var isOpen = subs && subs.style.display !== 'none';

          if (sys.classList.contains('active') && isOpen) {

            if (subs) subs.style.display = 'none';

            sys.classList.remove('open');

          } else {

            if (subs) subs.style.display = 'block';

            sys.classList.add('open');

            box.querySelectorAll('.active').forEach(function (el) { el.classList.remove('active'); });

            sys.classList.add('active');

            renderFlowSteps(sys.getAttribute('data-flow'));

          }

        }

      });

    }

    buildFlowRelations();

    bindFlowRelations();

    renderFlowSteps('checkin');

    if (saveBtn) saveBtn.addEventListener('click', saveConfig);

    if (resetBtn) resetBtn.addEventListener('click', function () { loadConfig(); showToast('已恢复服务器配置'); });

    function onShow() {

      renderMenu();

      loadConfig();

    }

    loadFeatureConfigRef = onShow;

  })();


  (function pluginCenter() {
    var configBody = document.getElementById('plugin-config-body');
    var marketBody = document.getElementById('plugin-market-body');

    function showToast(msg) {
      var old = document.getElementById('plugin-toast');
      if (old) old.remove();
      var div = document.createElement('div');
      div.id = 'plugin-toast';
      div.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#333;color:#fff;padding:10px 20px;border-radius:8px;z-index:9999;font-size:13px;';
      div.textContent = msg;
      document.body.appendChild(div);
      setTimeout(function () { div.remove(); }, 2200);
    }

    function renderPluginConfig() {
      if (!configBody) return;
      configBody.innerHTML = '<div class="pm-loading">加载插件列表…</div>';
      fetch(API_BASE + '/api/plugins', { cache: 'no-store' })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          // 展示全部插件（内置 + 外置），按 is_external 正确打标（C3 修复：内置插件不再被隐藏）
          var plugs = (data && data.plugins || []);
          if (!plugs.length) {
            configBody.innerHTML = '<div class="pm-empty">当前没有已安装的插件。</div>';
            return;
          }
          plugs.sort(function (a, b) {
            return (a.priority || 0) - (b.priority || 0);
          });
          var rows = plugs.map(function (p) {
            var tag = p.is_external
              ? '<span class="pm-tag pm-tag-ext">外置</span>'
              : '<span class="pm-tag pm-tag-builtin">内置</span>';
            var desc = p.description ? escapeHtml(p.description) : '<span class="pm-muted">无描述</span>';
            // 内置插件由「功能开关」统一控制，无启停开关；仅外置插件显示开关
            var toggle = p.is_external
              ? '<label class="pm-switch" title="启用/停用">' +
                  '<input type="checkbox" class="pm-toggle" ' + (p.enabled ? 'checked' : '') + ' data-key="' + escapeHtml(p.key) + '">' +
                  '<span class="slider"></span></label>'
              : '<span class="pm-muted" title="内置插件由功能开关统一控制" style="font-size:12px;padding:4px 10px;border:1px solid var(--border);border-radius:999px;">功能开关</span>';
            return '<div class="pm-row">' +
              '<div class="pm-meta">' +
                '<div class="pm-name">' + escapeHtml(p.name) + ' ' + tag +
                  ' <span class="pm-key">' + escapeHtml(p.key) + '</span></div>' +
                '<div class="pm-desc">' + desc + '</div>' +
              '</div>' +
              '<div class="pm-prio">优先级 ' + (p.priority != null ? p.priority : '-') + '</div>' +
              '<div class="pm-action">' + toggle + '</div>' +
            '</div>';
          }).join('');
          configBody.innerHTML =
            '<div class="pm-toolbar">' +
              '<button id="pm-reload-btn" class="pm-reload-btn">🔄 热加载外置插件</button>' +
              '<span class="pm-hint">修改 plugins/ 下文件后点此立即生效，无需重启 bot</span>' +
            '</div>' +
            '<div class="pm-list">' + rows + '</div>';
          var reloadBtn = document.getElementById('pm-reload-btn');
          if (reloadBtn) {
            reloadBtn.addEventListener('click', function () {
              reloadBtn.disabled = true;
              reloadBtn.textContent = '⏳ 热加载中…';
              fetch(API_BASE + '/api/plugins/reload', { method: 'POST' })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                  reloadBtn.disabled = false;
                  reloadBtn.textContent = '🔄 热加载外置插件';
                  if (d && d.ok) {
                    var s = d.stats || {};
                    showToast('已热加载：新增 ' + (s.loaded||0) + ' / 重载 ' + (s.reloaded||0) + ' / 注销 ' + (s.unregistered||0) + (s.errors ? (' / 错误 ' + s.errors) : ''));
                    renderPluginConfig();
                  } else {
                    showToast('热加载失败：' + (d && d.error));
                  }
                })
                .catch(function () {
                  reloadBtn.disabled = false;
                  reloadBtn.textContent = '🔄 热加载外置插件';
                  showToast('⚠️ 热加载请求失败');
                });
            });
          }
        })
        .catch(function () {
          configBody.innerHTML = '<div class="pm-empty">⚠️ 无法加载插件列表，请确认 bot 正在运行。</div>';
        });
    }

    function renderPluginMarket() {
      if (!marketBody) return;
      marketBody.innerHTML = '<div class="pm-loading">加载插件市场…</div>';
      // 同时拉取「已注册外置插件」与「市场模板目录」，解决「市场只显示模板、外置插件显示不完全」
      Promise.all([
        fetch(API_BASE + '/api/plugins', { cache: 'no-store' }).then(function (r) { return r.json(); }),
        fetch(API_BASE + '/api/plugins/market', { cache: 'no-store' }).then(function (r) { return r.json(); })
      ]).then(function (res) {
        var remoteCatalog = (res[1] && res[1].catalog) || [];
        var builtinTest = (res[1] && res[1].builtin_test) || [];
        var repoUrl = (res[1] && res[1].repo_url) || "";
        var remoteError = (res[1] && res[1].remote_error) || null;

        function cardHtml(c, isRemote) {
          var tag = isRemote
            ? '<span class="pm-tag pm-tag-ext">仓库</span>'
            : '<span class="pm-tag pm-tag-builtin">内置</span>';
          var action;
          if (c.installed) {
            action = '<button class="pm-install-btn pm-uninstall" data-key="' + escapeHtml(c.key) + '">卸载</button>';
          } else {
            action = '<button class="pm-install-btn pm-install" data-key="' + escapeHtml(c.key) +
              '" data-raw="' + escapeHtml(c.raw_url || '') + '">安装</button>';
          }
          var desc = c.description ? escapeHtml(c.description) : '<span class="pm-muted">无描述</span>';
          return '<div class="pm-row pm-market-row">' +
            '<div class="pm-meta">' +
              '<div class="pm-name">' + escapeHtml(c.name) + ' ' + tag +
                ' <span class="pm-key">' + escapeHtml(c.key) + '</span></div>' +
              '<div class="pm-desc">' + desc + '</div>' +
            '</div>' +
            '<div class="pm-action">' + action + '</div>' +
          '</div>';
        }

        var html = '';
        html += '<div class="pm-market-head">' +
                  '<div class="pm-market-title">插件市场（你的仓库）</div>' +
                  '<div class="pm-repo-box">' +
                    '<input id="pm-repo-url" class="pm-repo-input" placeholder="直接粘贴仓库地址，如 https://github.com/OWNER/REPO（留空用默认）" value="' + escapeHtml(repoUrl) + '">' +
                    '<button id="pm-repo-save" class="pm-repo-save">保存</button>' +
                  '</div>' +
                '</div>';
        if (remoteError) {
          html += '<div class="pm-empty">⚠️ 远程仓库加载失败：' + escapeHtml(remoteError) + '（下方为内置测试插件）</div>';
        }
        if (remoteCatalog.length) {
          html += '<div class="pm-section-title">可安装的仓库插件</div>';
          html += '<div class="pm-list">' + remoteCatalog.map(function (c) { return cardHtml(c, true); }).join('') + '</div>';
        } else if (!remoteError) {
          html += '<div class="pm-empty">仓库暂无插件，或在上方填入你的插件仓库地址。</div>';
        }
        if (builtinTest.length) {
          html += '<div class="pm-section-title">内置测试插件（随框架附带，不在仓库）</div>';
          html += '<div class="pm-list">' + builtinTest.map(function (c) { return cardHtml(c, false); }).join('') + '</div>';
        }
        marketBody.innerHTML = html;

        // 绑定安装/卸载按钮
        marketBody.querySelectorAll('.pm-install-btn').forEach(function (b) {
          b.addEventListener('click', function () {
            var key = b.getAttribute('data-key');
            var installing = b.classList.contains('pm-install');
            b.disabled = true;
            b.textContent = installing ? '⏳ 安装中…' : '⏳ 卸载中…';
            fetch(API_BASE + '/api/plugins/market/' + (installing ? 'install' : 'uninstall'), {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ key: key, raw_url: (b.getAttribute('data-raw') || '') })
            })
              .then(function (r) { return r.json(); })
              .then(function (d) {
                if (d && d.ok) {
                  showToast((installing ? '安装' : '卸载') + '成功：' + key);
                  renderPluginMarket();
                  if (loadPluginConfigRef) loadPluginConfigRef();
                } else {
                  b.disabled = false;
                  b.textContent = installing ? '安装' : '卸载';
                  showToast((installing ? '安装' : '卸载') + '失败：' + (d && d.error));
                }
              })
              .catch(function () {
                b.disabled = false;
                b.textContent = installing ? '安装' : '卸载';
                showToast('⚠️ 请求失败');
              });
          });
        });

        var repoSave = document.getElementById('pm-repo-save');
        var repoInput = document.getElementById('pm-repo-url');
        if (repoSave) {
          repoSave.addEventListener('click', function () {
            var v = ((repoInput && repoInput.value) || '').trim();
            repoSave.disabled = true;
            repoSave.textContent = '⏳ 保存中…';
            fetch(API_BASE + '/api/runtime-settings', {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ action: 'save', key: 'plugin.market.repo_url', value: v, scope: 'global' })
            })
              .then(function (r) { return r.json(); })
              .then(function (d) {
                repoSave.disabled = false;
                repoSave.textContent = '保存';
                if (d && d.ok) { showToast('仓库地址已保存，正在刷新…'); renderPluginMarket(); }
                else { showToast('保存失败：' + (d && d.error)); }
              })
              .catch(function () { repoSave.disabled = false; repoSave.textContent = '保存'; showToast('⚠️ 保存失败'); });
          });
        }

      })
      .catch(function () {
        marketBody.innerHTML = '<div class="pm-empty">⚠️ 无法加载插件市场，请确认 bot 正在运行。</div>';
      });
    }

    loadPluginConfigRef = renderPluginConfig;
    loadPluginMarketRef = renderPluginMarket;

    // 外置插件启用/停用开关（仅停止分发，状态持久化，无需重启 bot）
    if (configBody) {
      configBody.addEventListener('change', function (e) {
        var tog = e.target.closest && e.target.closest('.pm-toggle');
        if (!tog) return;
        var key = tog.getAttribute('data-key');
        var enabled = !!tog.checked;
        tog.disabled = true;
        fetch(API_BASE + '/api/plugins/set-enabled', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ key: key, enabled: enabled })
        })
          .then(function (r) { return r.json(); })
          .then(function (j) {
            tog.disabled = false;
            if (j && j.ok) {
              try { showToast(j.message || ('已' + (enabled ? '启用' : '禁用') + '，已保存')); } catch (e) {}
            } else {
              tog.checked = !enabled;
              alert((j && j.error) || '更新启用状态失败');
            }
          })
          .catch(function () {
            tog.disabled = false;
            tog.checked = !enabled;
            alert('更新失败：无法连接到后端');
          });
      });
    }

    // 插件市场：外置插件启用/停用开关（与 config 页共用同一后端端点）
    if (marketBody) {
      marketBody.addEventListener('change', function (e) {
        var tog = e.target.closest && e.target.closest('.pm-toggle');
        if (!tog) return;
        var key = tog.getAttribute('data-key');
        var enabled = !!tog.checked;
        tog.disabled = true;
        fetch(API_BASE + '/api/plugins/set-enabled', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ key: key, enabled: enabled })
        })
          .then(function (r) { return r.json(); })
          .then(function (j) {
            tog.disabled = false;
            if (j && j.ok) {
              try { showToast(j.message || ('已' + (enabled ? '启用' : '禁用') + '，已保存')); } catch (e) {}
            } else {
              tog.checked = !enabled;
              alert((j && j.error) || '更新启用状态失败');
            }
          })
          .catch(function () {
            tog.disabled = false;
            tog.checked = !enabled;
            alert('更新失败：无法连接到后端');
          });
      });
    }
  })();


  // ============================================================

  // 问答规则中心

  // ============================================================

  (function qaRulesCenter() {

    var items = [];

    var page = 1;

    var pageSize = 20;

    var editingId = null;

    var botSel = document.getElementById('qa-bot-select');

    var search = document.getElementById('qa-keyword-search');

    var addBtn = document.getElementById('qa-add-btn');

    var tbody = document.getElementById('qa-tbody');

    var empty = document.getElementById('qa-empty');

    var pagination = document.getElementById('qa-pagination');

    var modal = document.getElementById('qa-modal');

    var modalTitle = document.getElementById('qa-modal-title');

    var ruleId = document.getElementById('qa-rule-id');

    var editKeyword = document.getElementById('qa-edit-keyword');

    var editMatch = document.getElementById('qa-edit-match');

    var editCooldown = document.getElementById('qa-edit-cooldown');

    var editBot = document.getElementById('qa-edit-bot');

    var editAnswer = document.getElementById('qa-edit-answer');

    var editAnswerType = document.getElementById('qa-edit-answer-type');

    var editScope = document.getElementById('qa-edit-scope');

    var keywordCounter = document.getElementById('qa-keyword-counter');

    var answerCounter = document.getElementById('qa-answer-counter');

    var modalOk = document.getElementById('qa-modal-ok');

    var modalCancel = document.getElementById('qa-modal-cancel');

    var modalClose = document.getElementById('qa-modal-close');

    if (!tbody) return;

    function buildQuery() {

      var q = '?page=' + page + '&page_size=' + pageSize;

      if (botSel && botSel.value) q += '&bot=' + encodeURIComponent(botSel.value);

      if (search && search.value.trim()) q += '&keyword=' + encodeURIComponent(search.value.trim());

      return q;

    }

    function loadRules() {

      fetch(API_BASE + '/api/qa-rules' + buildQuery(), { cache: 'no-store' })

        .then(function (r) { return r.json(); })

        .then(function (data) {

          items = (data && data.items) || [];

          page = (data && data.page) || 1;

          pageSize = (data && data.page_size) || 20;

          render();

          if (botSel && data && data.bots) syncBots(data.bots);

        })

        .catch(function () {

          items = [];

          render();

        });

    }

    function syncBots(bots) {

      var val = botSel.value;

      var opts = '<option value="">全部机器人</option>';

      bots.forEach(function (b) { opts += '<option value="' + escapeHtml(b) + '">' + escapeHtml(b) + '</option>'; });

      botSel.innerHTML = opts;

      botSel.value = val;

      if (editBot) {

        var eVal = editBot.value;

        var eOpts = '<option value="">全部</option>';

        bots.forEach(function (b) { eOpts += '<option value="' + escapeHtml(b) + '">' + escapeHtml(b) + '</option>'; });

        editBot.innerHTML = eOpts;

        editBot.value = eVal || '';

      }

    }

    function render() {

      if (!items.length) {

        tbody.innerHTML = '';

        if (empty) empty.style.display = 'flex';

        if (pagination) pagination.innerHTML = '';

        return;

      }

      if (empty) empty.style.display = 'none';

      tbody.innerHTML = items.map(function (r) {

        return '<tr>' +

          '<td class="col-keyword">' + escapeHtml(r.keyword) + '</td>' +

          '<td><span class="col-match">' + escapeHtml(r.match_type) + '</span></td>' +

          '<td class="col-answer" title="' + escapeHtml(r.answer) + '">' + escapeHtml(r.answer) + '</td>' +

          '<td>' + (r.hits || 0) + '</td>' +

          '<td>' + (r.cooldown || 0) + 's</td>' +

          '<td><label class="switch"><input type="checkbox" class="qa-toggle" data-id="' + r.id + '"' + (r.enabled ? ' checked' : '') + '><span class="slider"></span></label></td>' +

          '<td>' +

            '<span class="op-link qa-edit" data-id="' + r.id + '">编辑</span>' +

            '<span class="op-link del qa-delete" data-id="' + r.id + '">删除</span>' +

          '</td>' +

        '</tr>';

      }).join('');

      renderPagination();

    }

    function renderPagination() {

      if (!pagination) return;

      var total = items.length === pageSize ? page * pageSize : (page - 1) * pageSize + items.length;

      if (items.length < pageSize) total = (page - 1) * pageSize + items.length;

      var html = '共 ' + total + ' 条';

      html += '<button ' + (page <= 1 ? 'disabled' : '') + ' data-page="' + (page - 1) + '">上一页</button>';

      html += '<button class="active">' + page + '</button>';

      html += '<button ' + (items.length < pageSize ? 'disabled' : '') + ' data-page="' + (page + 1) + '">下一页</button>';

      html += '<select id="qa-page-size"><option value="10">10条/页</option><option value="20">20条/页</option><option value="50">50条/页</option></select>';

      pagination.innerHTML = html;

      var sel = document.getElementById('qa-page-size');

      if (sel) sel.value = String(pageSize);

    }

    function openModal(isEdit, rule) {

      editingId = isEdit && rule ? rule.id : null;

      if (modalTitle) modalTitle.textContent = isEdit ? '编辑规则' : '添加规则';

      if (ruleId) ruleId.value = isEdit && rule ? rule.id : '';

      if (editKeyword) editKeyword.value = rule ? rule.keyword : '';

      if (editMatch) editMatch.value = rule ? rule.match_type : '精确';

      if (editCooldown) editCooldown.value = rule ? (rule.cooldown || 0) : 0;

      if (editBot) editBot.value = rule ? (rule.bot || '') : '';

      if (editAnswer) editAnswer.value = rule ? rule.answer : '';

      if (editAnswerType) editAnswerType.value = rule ? (rule.answer_type || '文本') : '文本';

      if (editScope) editScope.value = rule ? (rule.scope || '') : '';

      updateCounters();

      if (modal) { modal.style.display = 'flex'; modal.classList.add('show'); }

    }

    function updateCounters() {

      if (keywordCounter && editKeyword) keywordCounter.textContent = (editKeyword.value.length) + '/200';

      if (answerCounter && editAnswer) answerCounter.textContent = (editAnswer.value.length) + '/2000';

    }

    function loadScopes() {

      if (!editScope) return;

      fetch(API_BASE + '/api/groups?bot=&keyword=', { cache: 'no-store' })

        .then(function (r) { return r.json(); })

        .then(function (data) {

          var groups = (data && data.items) || [];

          var val = editScope.value;

          var opts = '<option value="">全局生效</option>';

          groups.forEach(function (g) {

            var name = (g.name || g.openid || '未命名群').slice(0, 24);

            opts += '<option value="' + escapeHtml(g.openid || '') + '">' + escapeHtml(name) + '</option>';

          });

          editScope.innerHTML = opts;

          editScope.value = val || '';

        })

        .catch(function () {});

    }

    function closeModal() {

      if (modal) { modal.style.display = 'none'; modal.classList.remove('show'); }

      editingId = null;

    }

    function saveRule() {

      var original = editingId ? items.find(function (r) { return r.id === editingId; }) : null;

      var payload = {

        id: editingId,

        keyword: (editKeyword && editKeyword.value) || '',

        match_type: (editMatch && editMatch.value) || '精确',

        answer: (editAnswer && editAnswer.value) || '',

        cooldown: parseInt((editCooldown && editCooldown.value) || 0, 10) || 0,

        bot: (editBot && editBot.value) || '',

        answer_type: (editAnswerType && editAnswerType.value) || '文本',

        scope: (editScope && editScope.value) || '',

        enabled: original ? !!original.enabled : true

      };

      if (!payload.keyword || !payload.answer) {

        alert('关键词和回复内容不能为空');

        return;

      }

      fetch(API_BASE + '/api/qa-rules/save', {

        method: 'POST',

        headers: { 'Content-Type': 'application/json' },

        body: JSON.stringify(payload)

      })

        .then(function (r) { return r.json(); })

        .then(function (data) {

          if (data && data.ok) {

            closeModal();

            loadRules();

          } else {

            alert('保存失败：' + (data && data.error ? data.error : '未知错误'));

          }

        })

        .catch(function () { alert('保存失败，请检查网络'); });

    }

    function deleteRule(id) {

      if (!confirm('确定删除该规则？')) return;

      fetch(API_BASE + '/api/qa-rules/delete', {

        method: 'POST',

        headers: { 'Content-Type': 'application/json' },

        body: JSON.stringify({ id: id })

      })

        .then(function (r) { return r.json(); })

        .then(function (data) {

          if (data && data.ok) loadRules();

        })

        .catch(function () {});

    }

    function toggleRule(id, enabled) {

      var rule = items.find(function (r) { return r.id == id; });

      if (!rule) return;

      rule.enabled = enabled;

      fetch(API_BASE + '/api/qa-rules/save', {

        method: 'POST',

        headers: { 'Content-Type': 'application/json' },

        body: JSON.stringify(rule)

      }).catch(function () {});

    }

    if (addBtn) addBtn.addEventListener('click', function () { openModal(false); });

    if (modalCancel) modalCancel.addEventListener('click', closeModal);

    if (modalClose) modalClose.addEventListener('click', closeModal);

    if (modalOk) modalOk.addEventListener('click', saveRule);

    if (editKeyword) editKeyword.addEventListener('input', updateCounters);

    if (editAnswer) editAnswer.addEventListener('input', updateCounters);

    // 点击遮罩空白处关闭

    if (modal) {

      modal.addEventListener('click', function (e) {

        if (e.target === modal) closeModal();

      });

    }

    // 按 Esc 关闭

    document.addEventListener('keydown', function (e) {

      if (e.key === 'Escape' && modal && modal.classList.contains('show')) closeModal();

    });

    if (botSel) botSel.addEventListener('change', function () { page = 1; loadRules(); });

    if (search) {

      search.addEventListener('input', debounce(function () { page = 1; loadRules(); }, 300));

    }

    if (pagination) {

      pagination.addEventListener('click', function (e) {

        var btn = e.target.closest('button');

        if (!btn || btn.disabled) return;

        var p = parseInt(btn.getAttribute('data-page'), 10);

        if (!isNaN(p) && p > 0) { page = p; loadRules(); }

        var sel = e.target.closest('select');

        if (sel && sel.id === 'qa-page-size') { pageSize = parseInt(sel.value, 10); page = 1; loadRules(); }

      });

      pagination.addEventListener('change', function (e) {

        var sel = e.target.closest('select');

        if (sel && sel.id === 'qa-page-size') { pageSize = parseInt(sel.value, 10); page = 1; loadRules(); }

      });

    }

    if (tbody) {

      tbody.addEventListener('click', function (e) {

        var edit = e.target.closest('.qa-edit');

        var del = e.target.closest('.qa-delete');

        var toggle = e.target.closest('.qa-toggle');

        if (edit) {

          var id = parseInt(edit.getAttribute('data-id'), 10);

          var rule = items.find(function (r) { return r.id === id; });

          if (rule) openModal(true, rule);

        } else if (del) {

          deleteRule(parseInt(del.getAttribute('data-id'), 10));

        } else if (toggle) {

          toggleRule(toggle.getAttribute('data-id'), toggle.checked);

        }

      });

    }

    // 同步 bot 状态点（2026-08-08 新增 bot-select-wrap 配套）

    if (botSel) botSel.addEventListener('change', function () { updateBotStatusDot('qa-bot-select', 'qa-bot-dot'); });

    if (editBot) editBot.addEventListener('change', function () { updateBotStatusDot('qa-edit-bot', 'qa-edit-bot-dot'); });

    try { updateBotStatusDot('qa-bot-select', 'qa-bot-dot'); } catch (e) {}

    try { updateBotStatusDot('qa-edit-bot', 'qa-edit-bot-dot'); } catch (e) {}

    function debounce(fn, wait) {

      var t;

      return function () {

        clearTimeout(t);

        t = setTimeout(fn, wait);

      };

    }

    function onShow() {

      page = 1;

      loadScopes();

      loadRules();

    }

    loadQaRulesRef = onShow;

  })();

  // ============================================================

  // AI 智能中心

  // ============================================================

  (function aiCenter() {

    // ---------- AI 对话 ----------

    (function aiChat() {

      var botSel = document.getElementById('ai-chat-bot-select');

      var modelSel = document.getElementById('ai-chat-model-select');

      var statusEl = document.getElementById('ai-chat-status');

      var box = document.getElementById('ai-chat-messages');

      var input = document.getElementById('ai-chat-input');

      var sendBtn = document.getElementById('ai-chat-send');

      var autoReplySw = document.getElementById('ai-auto-reply-switch');

      if (!box) return;

      // ---------- AI 自动回复开关 ----------

      // 与「功能配置」共用后端存储：/api/system-config 的 switches.ai

      function showAutoReplyToast(msg) {

        var old = document.getElementById('ai-auto-reply-toast');

        if (old) old.remove();

        var div = document.createElement('div');

        div.id = 'ai-auto-reply-toast';

        div.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#333;color:#fff;padding:10px 20px;border-radius:8px;z-index:9999;font-size:13px;';

        div.textContent = msg;

        document.body.appendChild(div);

        setTimeout(function () { div.remove(); }, 2000);

      }

      function loadAutoReplyState() {

        fetch(API_BASE + '/api/system-config', { method: 'GET' })

          .then(function (r) { return r.ok ? r.json() : null; })

          .then(function (data) {

            if (!data || !autoReplySw) return;

            var sw = (data && data.switches) || {};

            autoReplySw.checked = sw.ai !== false; // 默认开启

          })

          .catch(function () {});

      }

      function saveAutoReplyState(on) {

        // 先拉取最新 switches，合并 ai 字段后整体写回，避免覆盖其它开关

        fetch(API_BASE + '/api/system-config', { method: 'GET' })

          .then(function (r) { return r.ok ? r.json() : null; })

          .then(function (data) {

            var switches = (data && data.switches) || {};

            switches.ai = !!on;

            return fetch(API_BASE + '/api/system-config', {

              method: 'POST',

              headers: { 'Content-Type': 'application/json' },

              body: JSON.stringify({ switches: switches })

            });

          })

          .then(function (r) {

            if (!r || !r.ok) throw new Error('HTTP ' + (r ? r.status : '?'));

            return r.json();

          })

          .then(function (d) {

            if (d && d.ok) {

              showAutoReplyToast(on ? '✅ AI 自动回复已开启' : '⏸ AI 自动回复已关闭');

            } else {

              showAutoReplyToast('保存失败：' + ((d && d.error) || '未知错误'));

              if (autoReplySw) autoReplySw.checked = !on;

            }

          })

          .catch(function () {

            showAutoReplyToast('⚠️ 保存失败：请确认机器人正在运行');

            if (autoReplySw) autoReplySw.checked = !on;

          });

      }

      if (autoReplySw) {

        autoReplySw.addEventListener('change', function () { saveAutoReplyState(autoReplySw.checked); });

      }

      loadAutoReplyState();

      var history = [];

      var busy = false;

      function syncStatus(online) {

        if (!statusEl) return;

        statusEl.classList.toggle('offline', !online);

        statusEl.innerHTML = '<span class="dot"></span>' + (online ? '实时连接' : '未连接');

      }

      function loadProviders() {

        var _b = botSel ? botSel.value : '';

        fetch(API_BASE + '/api/ai/providers' + (_b ? '?bot=' + encodeURIComponent(_b) : ''))

          .then(function (r) { return r.json(); })

          .then(function (data) {

            var list = (data && data.providers) || [];

            var html = '<option value="">选择供应商</option>';

            list.forEach(function (p) {

              html += '<option value="' + p.id + '">' + escapeHtml(p.name) + '</option>';

            });

            if (modelSel) modelSel.innerHTML = html;

            syncStatus(list.length > 0);

          })

          .catch(function () { syncStatus(false); });

      }

      function appendBubble(role, text) {

        if (!box) return;

        var empty = box.querySelector('.ai-chat-empty');

        if (empty) empty.remove();

        var div = document.createElement('div');

        div.className = 'ai-message ' + role;

        var avatar = role === 'user' ? '我' : '🤖';

        div.innerHTML = '<div class="avatar">' + avatar + '</div><div class="bubble">' + escapeHtml(text) + '</div>';

        box.appendChild(div);

        box.scrollTop = box.scrollHeight;

        return div;

      }

      function resetConversation() {

        history = [];

        if (box) box.innerHTML = '<div class="ai-chat-empty">' +

          '<div class="ai-empty-icon">🤖</div>' +

          '<div class="text">开始与机器人对话</div>' +

          '<div class="sub">选择机器人和供应商后，输入消息并发送</div></div>';

      }

      function send() {

        if (!input || busy) return;

        var text = input.value.trim();

        if (!text) return;

        var bot = botSel ? botSel.value : '';

        var provider = modelSel ? modelSel.value : '';

        if (!bot) { showToast('请选择机器人'); return; }

        if (!provider) { showToast('请选择供应商'); return; }

        history.push({ role: 'user', content: text });

        appendBubble('user', text);

        input.value = '';

        var last = appendBubble('bot', '思考中...');

        busy = true;

        fetch(API_BASE + '/api/ai/chat', {

          method: 'POST',

          headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify({ bot: bot, provider_id: provider, messages: history })

        })

          .then(function (r) { return r.json(); })

          .then(function (data) {

            busy = false;

            if (last) {

              if (data && data.ok) {

                last.querySelector('.bubble').textContent = data.reply;

                history.push({ role: 'assistant', content: data.reply });

              } else {

                var msg = (data && data.error) ? data.error : '（无回复）';

                // 供应商失效时自动重新拉取下拉，并提示用户重选

                if (data && data.available_providers) {

                  msg += '。请在供应商下拉框重新选择后再发送。';

                  try { loadProviders(); } catch (e) {}

                }

                last.querySelector('.bubble').textContent = '⚠️ ' + msg;

              }

            }

          })

          .catch(function () {

            busy = false;

            if (last) last.querySelector('.bubble').textContent = '请求失败，请检查网络或后端服务';

          });

      }

      if (sendBtn) sendBtn.addEventListener('click', send);

      if (input) input.addEventListener('keydown', function (e) { if (e.key === 'Enter') send(); });

      // 切换机器人 / 供应商时重置对话上下文

      if (botSel) botSel.addEventListener('change', function () { resetConversation(); loadProviders(); });

      if (modelSel) modelSel.addEventListener('change', resetConversation);

      function onShow() {

        fillBotSelect(botSel, '选择机器人');

        loadProviders();

      }

      loadAiChatRef = onShow;

    })();

    // ---------- 模型管理 ----------

    (function aiModels() {

      var tbody = document.getElementById('ai-provider-tbody');

      var empty = document.getElementById('ai-provider-empty');

      var addBtn = document.getElementById('ai-provider-add');

      var modal = document.getElementById('ai-provider-modal');

      var modalTitle = document.getElementById('ai-provider-modal-title');

      var pId = document.getElementById('ai-provider-id');

      var pName = document.getElementById('ai-provider-name');

      var pType = document.getElementById('ai-provider-type');

      var pUrl = document.getElementById('ai-provider-url');

      var pKey = document.getElementById('ai-provider-key');

      var pModel = document.getElementById('ai-provider-model');

      var eyeBtn = document.getElementById('ai-provider-key-eye');

      var okBtn = document.getElementById('ai-provider-modal-ok');

      var cancelBtn = document.getElementById('ai-provider-modal-cancel');

      var closeBtn = document.getElementById('ai-provider-modal-close');

      var testBtn = document.getElementById('ai-provider-modal-test');

      var fetchBtn = document.getElementById('ai-provider-model-fetch');

      var testResult = document.getElementById('ai-provider-test-result');

      var botSel = document.getElementById('ai-models-bot-select');

      function aiBotVal() { return botSel && botSel.value ? botSel.value : ''; }

      if (!tbody) return;

      function showTestResult(text, cls) {

        if (!testResult) return;

        testResult.style.display = 'block';

        testResult.className = 'ai-provider-test-result ' + (cls || '');

        // text 既可能是纯字符串也可能是 HTML 片段（renderModelsError 会嵌入复制链接）

        testResult.innerHTML = text;

      }

      // 点击复制链接（错误提示里展示的实际请求地址）

      if (testResult) {

        testResult.addEventListener('click', function (e) {

          var el = e.target.closest('.ai-copy-link');

          if (!el) return;

          var text = el.getAttribute('data-copy') || '';

          if (!text) return;

          var ok = false;

          try {

            if (navigator.clipboard && navigator.clipboard.writeText) {

              navigator.clipboard.writeText(text).then(function () {

                el.classList.add('copied');

                el.textContent = '已复制 ✓';

                setTimeout(function () {

                  el.classList.remove('copied');

                  el.textContent = '复制 URL';

                }, 1500);

              });

              ok = true;

            } else {

              var ta = document.createElement('textarea');

              ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';

              document.body.appendChild(ta); ta.select();

              ok = document.execCommand('copy');

              document.body.removeChild(ta);

            }

          } catch (err) { ok = false; }

          if (ok) {

            el.classList.add('copied');

            el.textContent = '已复制 ✓';

            setTimeout(function () {

              el.classList.remove('copied');

              el.textContent = '复制 URL';

            }, 1500);

          }

        });

      }

      function testConnection() {

        var cfg = {

          bot: aiBotVal(),

          id: pId.value ? parseInt(pId.value, 10) : null,

          name: pName.value.trim(),

          type: pType.value,

          url: pUrl.value.trim(),

          key: pKey.value.trim(),

          model: pModel.value.trim()

        };

        if (!cfg.url || !cfg.model) { showToast('请先填写 API 地址和模型再测试'); return; }

        showTestResult('测试连接中...', 'loading');

        if (testBtn) { testBtn.disabled = true; testBtn.textContent = '测试中...'; }

        fetch(API_BASE + '/api/ai/providers/test', {

          method: 'POST',

          headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify(cfg)

        })

          .then(function (r) { return r.json(); })

          .then(function (data) {

            if (data.ok) showTestResult('✅ 连接成功（' + data.elapsed_ms + 'ms）：' + (data.reply || ''), 'ok');

            else showTestResult('❌ ' + data.error, 'err');

          })

          .catch(function () { showTestResult('❌ 请求发送失败，请检查后端服务', 'err'); })

          .then(function () {

            if (testBtn) { testBtn.disabled = false; testBtn.textContent = '测试连接'; }

          });

      }

      function fetchModels() {

        var cfg = {

          bot: aiBotVal(),

          name: pName.value.trim(),

          type: pType.value,

          url: pUrl.value.trim(),

          key: pKey.value.trim()

        };

        if (!cfg.url) { showToast('请先填写 API 地址'); return; }

        if (fetchBtn) { fetchBtn.disabled = true; fetchBtn.textContent = '获取中...'; }

        fetch(API_BASE + '/api/ai/providers/models', {

          method: 'POST',

          headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify(cfg)

        })

          .then(function (r) { return r.json(); })

          .then(function (data) {

            if (data.ok && data.models && data.models.length) {

              pModel.value = data.models[0];

              showTestResult('已获取 ' + data.models.length + ' 个模型，已填入：' + data.models.slice(0, 6).join('、'), 'ok');

            } else {

              showTestResult(renderModelsError(data), 'err');

            }

          })

          .catch(function () { showTestResult('❌ 获取模型失败，请检查后端服务', 'err'); })

          .then(function () {

            if (fetchBtn) { fetchBtn.disabled = false; fetchBtn.textContent = '获取模型'; }

          });

      }

      function renderModelsError(data) {

        if (!data) return '❌ 获取失败：未知错误';

        var msg = data.error || '未知错误';

        var lines = ['❌ ' + msg];

        if (data.endpoint) {

          lines.push('请求地址：' + data.endpoint);

          lines.push('<span class="ai-copy-link" data-copy="' + escapeHtml(data.endpoint) + '">复制 URL</span>');

        }

        return lines.join('<br>');

      }

      function maskKey(k) {

        if (!k) return '';

        if (k.length <= 4) return '****';

        return '****' + k.slice(-4);

      }

      function render(list) {

        if (!tbody) return;

        if (!list || !list.length) {

          tbody.innerHTML = '';

          if (empty) empty.style.display = 'block';

          return;

        }

        if (empty) empty.style.display = 'none';

        tbody.innerHTML = list.map(function (p) {

          return '<tr>' +

            '<td>' + escapeHtml(p.name) + '</td>' +

            '<td>' + (p.type === 'ollama' ? 'Ollama 本地' : 'OpenAI 兼容') + '</td>' +

            '<td>' + escapeHtml(p.url) + '</td>' +

            '<td class="col-key">' + maskKey(p.key) + '</td>' +

            '<td>' + escapeHtml(p.model) + '</td>' +

            '<td>' +

              '<span class="op-link" data-id="' + p.id + '">编辑</span>' +

              '<span class="op-link del" data-id="' + p.id + '">删除</span>' +

            '</td>' +

          '</tr>';

        }).join('');

      }

      function load() {

        fetch(API_BASE + '/api/ai/providers' + (aiBotVal() ? '?bot=' + encodeURIComponent(aiBotVal()) : ''))

          .then(function (r) { return r.json(); })

          .then(function (data) { render((data && data.providers) || []); })

          .catch(function () { showToast('加载供应商失败'); });

      }

      function openModal(isEdit, item) {

        if (!modal) return;

        modalTitle.textContent = isEdit ? '编辑供应商' : '新增供应商';

        pId.value = item ? item.id : '';

        pName.value = item ? item.name : '';

        pType.value = item ? item.type : 'openai';

        pUrl.value = item ? item.url : '';

        pKey.value = item ? item.key : '';

        pModel.value = item ? item.model : '';

        if (testResult) { testResult.style.display = 'none'; testResult.textContent = ''; }

        modal.style.display = 'flex';

        setTimeout(function () { modal.classList.add('show'); }, 10);

      }

      function closeModal() {

        if (!modal) return;

        modal.classList.remove('show');

        setTimeout(function () { modal.style.display = 'none'; }, 200);

      }

      function save() {

        var payload = {

          bot: aiBotVal(),

          id: pId.value ? parseInt(pId.value, 10) : null,

          name: pName.value.trim(),

          type: pType.value,

          url: pUrl.value.trim(),

          key: pKey.value.trim(),

          model: pModel.value.trim()

        };

        if (!payload.name || !payload.url || !payload.model) {

          // 校验失败：在弹窗内部高亮提示（避免只弹底部小 toast 被忽略）

          var miss = [];

          if (!payload.name) miss.push('名称');

          if (!payload.url) miss.push('API 地址');

          if (!payload.model) miss.push('模型');

          showTestResult('⚠️ 请先填写：' + miss.join('、') + '，才能保存', 'err');

          showToast('请填写' + miss.join('、'));

          // 缺失字段加红框提示

          [pName, pUrl, pModel].forEach(function (el) {

            if (el) el.style.borderColor = '';

          });

          if (!payload.name && pName) pName.style.borderColor = '#d9534f';

          if (!payload.url && pUrl) pUrl.style.borderColor = '#d9534f';

          if (!payload.model && pModel) pModel.style.borderColor = '#d9534f';

          return;

        }

        [pName, pUrl, pModel].forEach(function (el) {

          if (el) el.style.borderColor = '';

        });

        fetch(API_BASE + '/api/ai/providers', {

          method: 'POST',

          headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify(payload)

        })

          .then(function (r) { return r.json(); })

          .then(function (data) {

            if (data && data.ok) {

              closeModal();

              load();

              showToast('保存成功');

            } else {

              showToast('保存失败：' + (data && data.error ? data.error : '未知错误'));

            }

          })

          .catch(function () { showToast('保存失败'); });

      }

      function deleteProvider(id) {

        if (!confirm('确定删除该供应商？')) return;

        fetch(API_BASE + '/api/ai/providers?id=' + id + (aiBotVal() ? '&bot=' + encodeURIComponent(aiBotVal()) : ''), { method: 'DELETE' })

          .then(function (r) { return r.json(); })

          .then(function (data) {

            if (data && data.ok) { load(); showToast('删除成功'); }

            else { showToast('删除失败'); }

          })

          .catch(function () { showToast('删除失败'); });

      }

      if (addBtn) addBtn.addEventListener('click', function () { openModal(false); });

      if (okBtn) okBtn.addEventListener('click', save);

      if (cancelBtn) cancelBtn.addEventListener('click', closeModal);

      if (closeBtn) closeBtn.addEventListener('click', closeModal);

      if (testBtn) testBtn.addEventListener('click', testConnection);

      if (fetchBtn) fetchBtn.addEventListener('click', fetchModels);

      if (eyeBtn) eyeBtn.addEventListener('click', function () {

        pKey.type = pKey.type === 'password' ? 'text' : 'password';

      });

      if (tbody) tbody.addEventListener('click', function (e) {

        var edit = e.target.closest('.op-link:not(.del)');

        var del = e.target.closest('.op-link.del');

        if (edit) {

          fetch(API_BASE + '/api/ai/providers' + (aiBotVal() ? '?bot=' + encodeURIComponent(aiBotVal()) : ''))

            .then(function (r) { return r.json(); })

            .then(function (data) {

              var list = (data && data.providers) || [];

              var item = list.find(function (p) { return p.id === parseInt(edit.getAttribute('data-id'), 10); });

              if (item) openModal(true, item);

            });

        } else if (del) {

          deleteProvider(parseInt(del.getAttribute('data-id'), 10));

        }

      });

      if (botSel) botSel.addEventListener('change', function () { load(); });

      function onShow() { fillBotSelect(botSel, '默认（全局 _shared）'); load(); }

      loadAiModelsRef = onShow;

    })();

    // ---------- 敏感词 ----------

    (function aiSensitive() {

      var tbody = document.getElementById('ai-sensitive-tbody');

      var empty = document.getElementById('ai-sensitive-empty');

      var refreshBtn = document.getElementById('ai-sensitive-refresh');

      var syncBtn = document.getElementById('ai-sensitive-sync');

      var addBtn = document.getElementById('ai-sensitive-add');

      var tabs = document.querySelectorAll('.ai-sens-tab');

      var autoRevoke = document.getElementById('ai-sensitive-auto-revoke');

      var botSel = document.getElementById('ai-sensitive-bot-select');

      var modal = document.getElementById('ai-sensitive-modal');

      var modalTitle = document.getElementById('ai-sensitive-modal-title');

      var sId = document.getElementById('ai-sensitive-edit-id');

      var sWord = document.getElementById('ai-sensitive-word');

      var sWordCounter = document.getElementById('ai-sensitive-word-counter');

      var sScopeWrap = document.getElementById('ai-sensitive-scope-select');

      var sCatWrap = document.getElementById('ai-sensitive-category-select');

      var sEnabled = document.getElementById('ai-sensitive-enabled');

      var okBtn = document.getElementById('ai-sensitive-modal-ok');

      var cancelBtn = document.getElementById('ai-sensitive-modal-cancel');

      var closeBtn = document.getElementById('ai-sensitive-modal-close');

      if (!tbody) return;

      var currentScope = 'all';

      var items = [];

      var categoryMeta = {

        '通用': { color: '#4a90e2', dot: true },

        '政治': { color: '#e74c3c', dot: true },

        '广告': { color: '#f39c12', dot: true },

        '辱骂': { color: '#9b59b6', dot: true },

        '其他': { color: '#95a5a6', dot: true }

      };

      var scopeMeta = {

        global: { icon: '&#x1F310;', title: '全局', desc: '所有机器人群聊生效' },

        bot: { icon: '&#x1F916;', title: '机器人级', desc: '指定机器人的所有群生效' },

        group: { icon: '&#x1F465;', title: '群级', desc: '指定机器人的指定群生效' }

      };

      function scopeLabel(scope) {

        return { global: '全局', bot: '机器人级', group: '群级' }[scope] || scope;

      }

      function initCustomSelect(wrap) {

        if (!wrap) return null;

        var trigger = wrap.querySelector('.ai-custom-select-trigger');

        var opts = wrap.querySelectorAll('.ai-custom-option');

        function closeAll() {

          document.querySelectorAll('.ai-custom-select.open').forEach(function (el) {

            if (el !== wrap) el.classList.remove('open');

          });

        }

        trigger.addEventListener('click', function (e) {

          e.stopPropagation();

          closeAll();

          wrap.classList.toggle('open');

        });

        opts.forEach(function (opt) {

          opt.addEventListener('click', function (e) {

            e.stopPropagation();

            var val = opt.getAttribute('data-value');

            wrap.setAttribute('data-value', val);

            opts.forEach(function (o) { o.classList.remove('active'); });

            opt.classList.add('active');

            updateSelectDisplay(wrap);

            wrap.classList.remove('open');

          });

        });

        return wrap;

      }

      function updateSelectDisplay(wrap) {

        if (!wrap) return;

        var val = wrap.getAttribute('data-value');

        var text = wrap.querySelector('.ai-custom-select-text');

        var triggerDot = wrap.querySelector('.ai-custom-select-trigger .ai-dot');

        var triggerIcon = wrap.querySelector('.ai-custom-select-trigger .ai-scope-icon');

        if (wrap.id === 'ai-sensitive-category-select' && categoryMeta[val]) {

          if (text) text.textContent = val;

          if (triggerDot) triggerDot.style.background = categoryMeta[val].color;

        } else if (wrap.id === 'ai-sensitive-scope-select' && scopeMeta[val]) {

          var m = scopeMeta[val];

          if (text) text.innerHTML = m.title + ' — ' + m.desc;

          if (triggerIcon) triggerIcon.innerHTML = m.icon;

        }

      }

      function setCustomSelectValue(wrap, val) {

        if (!wrap) return;

        wrap.setAttribute('data-value', val);

        var opts = wrap.querySelectorAll('.ai-custom-option');

        opts.forEach(function (o) { o.classList.toggle('active', o.getAttribute('data-value') === val); });

        updateSelectDisplay(wrap);

      }

      function getCustomSelectValue(wrap) {

        return wrap ? wrap.getAttribute('data-value') : '';

      }

      function updateWordCounter() {

        if (!sWord || !sWordCounter) return;

        var len = (sWord.value || '').length;

        sWordCounter.textContent = len + '/100';

      }

      function render(list) {

        items = list || [];

        var filtered = currentScope === 'all' ? items : items.filter(function (x) { return x.scope === currentScope; });

        if (!filtered.length) {

          tbody.innerHTML = '';

          if (empty) empty.style.display = 'block';

          return;

        }

        if (empty) empty.style.display = 'none';

        tbody.innerHTML = filtered.map(function (s) {

          return '<tr>' +

            '<td>' + s.id + '</td>' +

            '<td>' + escapeHtml(s.word) + '</td>' +

            '<td><span class="scope-tag">' + scopeLabel(s.scope) + '</span></td>' +

            '<td><span class="cat-tag">' + escapeHtml(s.category || '通用') + '</span></td>' +

            '<td><label class="switch"><input type="checkbox" data-id="' + s.id + '"' + (s.enabled ? ' checked' : '') + '><span class="track"></span><span class="thumb"></span></label></td>' +

            '<td>' + (s.created_at || '-') + '</td>' +

            '<td><span class="op-link del" data-id="' + s.id + '">删除</span></td>' +

          '</tr>';

        }).join('');

      }

      function load() {

        fetch(API_BASE + '/api/ai/sensitive-words')

          .then(function (r) { return r.json(); })

          .then(function (data) {

            render((data && data.words) || []);

            if (autoRevoke) autoRevoke.checked = !!(data && data.auto_revoke);

          })

          .catch(function () { showToast('加载敏感词失败'); });

      }

      function openModal(isEdit, item) {

        if (!modal) return;

        modalTitle.textContent = isEdit ? '编辑敏感词' : '新增敏感词';

        sId.value = item ? item.id : '';

        sWord.value = item ? item.word : '';

        updateWordCounter();

        setCustomSelectValue(sScopeWrap, item ? item.scope : 'global');

        setCustomSelectValue(sCatWrap, item ? (item.category || '通用') : '通用');

        sEnabled.checked = item ? !!item.enabled : true;

        modal.style.display = 'flex';

        setTimeout(function () { modal.classList.add('show'); }, 10);

      }

      function closeModal() {

        if (!modal) return;

        modal.classList.remove('show');

        setTimeout(function () { modal.style.display = 'none'; }, 200);

      }

      function save() {

        var payload = {

          id: sId.value ? parseInt(sId.value, 10) : null,

          word: sWord.value.trim(),

          scope: getCustomSelectValue(sScopeWrap) || 'global',

          category: getCustomSelectValue(sCatWrap) || '通用',

          enabled: sEnabled.checked

        };

        if (!payload.word) { showToast('请输入敏感词'); return; }

        fetch(API_BASE + '/api/ai/sensitive-words', {

          method: 'POST',

          headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify(payload)

        })

          .then(function (r) { return r.json(); })

          .then(function (data) {

            if (data && data.ok) {

              closeModal();

              load();

              showToast('保存成功');

            } else {

              showToast('保存失败：' + (data && data.error ? data.error : '未知错误'));

            }

          })

          .catch(function () { showToast('保存失败'); });

      }

      function deleteWord(id) {

        if (!confirm('确定删除该敏感词？')) return;

        fetch(API_BASE + '/api/ai/sensitive-words?id=' + id, { method: 'DELETE' })

          .then(function (r) { return r.json(); })

          .then(function (data) {

            if (data && data.ok) { load(); showToast('删除成功'); }

            else { showToast('删除失败'); }

          })

          .catch(function () { showToast('删除失败'); });

      }

      function saveAutoRevoke() {

        fetch(API_BASE + '/api/ai/sensitive-words', {

          method: 'POST',

          headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify({ action: 'set_auto_revoke', enabled: autoRevoke.checked })

        }).catch(function () {});

      }

      if (tabs) tabs.forEach(function (tab) {

        tab.addEventListener('click', function () {

          tabs.forEach(function (t) { t.classList.remove('active'); });

          tab.classList.add('active');

          currentScope = tab.getAttribute('data-scope');

          render(items);

        });

      });

      if (addBtn) addBtn.addEventListener('click', function () { openModal(false); });

      if (okBtn) okBtn.addEventListener('click', save);

      if (cancelBtn) cancelBtn.addEventListener('click', closeModal);

      if (closeBtn) closeBtn.addEventListener('click', closeModal);

      if (sWord) sWord.addEventListener('input', updateWordCounter);

      if (modal) {

        document.addEventListener('click', function (e) {

          if (!modal.contains(e.target)) return;

          document.querySelectorAll('.ai-custom-select.open').forEach(function (el) {

            if (!el.contains(e.target)) el.classList.remove('open');

          });

        });

      }

      initCustomSelect(sScopeWrap);

      initCustomSelect(sCatWrap);

      updateSelectDisplay(sScopeWrap);

      updateSelectDisplay(sCatWrap);

      if (refreshBtn) refreshBtn.addEventListener('click', load);

      if (syncBtn) syncBtn.addEventListener('click', function () { showToast('缓存已同步'); });

      if (autoRevoke) autoRevoke.addEventListener('change', saveAutoRevoke);

      if (tbody) tbody.addEventListener('click', function (e) {

        var del = e.target.closest('.op-link.del');

        var toggle = e.target.closest('input[type="checkbox"]');

        if (del) deleteWord(parseInt(del.getAttribute('data-id'), 10));

        else if (toggle) {

          var id = parseInt(toggle.getAttribute('data-id'), 10);

          fetch(API_BASE + '/api/ai/sensitive-words', {

            method: 'POST',

            headers: { 'Content-Type': 'application/json' },

            body: JSON.stringify({ id: id, enabled: toggle.checked })

          }).catch(function () { showToast('状态更新失败'); });

        }

      });

      function onShow() { fillBotSelect(botSel, '选择机器人'); load(); }

      loadAiSensitiveRef = onShow;

    })();

    // ---------- 人格设置 ----------

    (function aiPersona() {

      var list = document.getElementById('ai-persona-list');

      var editName = document.getElementById('ai-persona-edit-name');

      var editTitle = document.getElementById('ai-persona-edit-title');

      var editText = document.getElementById('ai-persona-edit-text');

      var count = document.getElementById('ai-persona-count');

      var saveBtn = document.getElementById('ai-persona-save');

      var resetBtn = document.getElementById('ai-persona-reset');

      var refreshBtn = document.getElementById('ai-persona-refresh');

      var addBtn = document.getElementById('ai-persona-add');

      var botSel = document.getElementById('ai-persona-bot-select');

      function aiBotVal() { return botSel && botSel.value ? botSel.value : ''; }

      if (!list || !editText) return;

      var personas = [];

      var activeId = null;

      var currentId = null;

      function refreshCount() {

        if (count) count.textContent = (editText.value || '').length + ' 字 · 留空则使用模型默认人设';

      }

      function load() {

        fetch(API_BASE + '/api/ai/persona?bot=' + encodeURIComponent(aiBotVal()), { method: 'GET' })

          .then(function (r) { return r.json(); })

          .then(function (d) {

            personas = (d && d.personas) || [];

            activeId = (d && d.active_id) != null ? d.active_id : null;

            renderList();

            if (currentId == null) selectFirst();

            else renderEditor();

          })

          .catch(function () {});

      }

      function renderList() {

        if (!list) return;

        list.innerHTML = '';

        if (!personas.length) {

          list.innerHTML = '<div class="kb-sidebar-empty" style="color:var(--muted);font-size:13px;">暂无人格，点「+ 新建」创建</div>';

          return;

        }

        personas.forEach(function (p) {

          var div = document.createElement('div');

          div.className = 'kb-base-item' + (p.id === currentId ? ' active' : '') + (p.id === activeId ? ' using' : '');

          div.setAttribute('data-id', p.id);

          var badge = personas.filter(function (x) { return x.id === p.id; }).length ? p.id : p.id;

          div.innerHTML =

            '<div class="kb-base-row">' +

              '<span class="kb-base-name">' + escapeHtml(p.name || '未命名人格') + '</span>' +

              '<span class="kb-base-badge">#' + p.id + '</span>' +

            '</div>' +

            '<div class="kb-base-meta">' +

              '<span class="kb-base-state ' + (p.id === activeId ? 'on' : 'off') + '">' + (p.id === activeId ? '使用中' : '未使用') + '</span>' +

              '<span class="op-link rename" data-id="' + p.id + '">改名</span>' +

              '<span class="op-link del" data-id="' + p.id + '">删除</span>' +

            '</div>' +

            '<label class="switch kb-base-use-switch" title="设为使用中">' +

              '<input type="checkbox" ' + (p.id === activeId ? 'checked' : '') + ' data-id="' + p.id + '" />' +

              '<span class="track"></span><span class="thumb"></span>' +

            '</label>';

          list.appendChild(div);

        });

      }

      function selectFirst() {

        currentId = personas.length ? personas[0].id : null;

        renderEditor();

      }

      function renderEditor() {

        var p = personas.filter(function (x) { return x.id === currentId; })[0];

        if (!p) {

          if (editName) editName.textContent = '未选择人格';

          if (editTitle) editTitle.value = '';

          editText.value = '';

          refreshCount();

          return;

        }

        if (editName) editName.textContent = p.name || '未命名人格';

        if (editTitle) editTitle.value = p.name || '';

        editText.value = p.prompt || '';

        refreshCount();

      }

      function select(id) {

        currentId = id;

        renderList();

        renderEditor();

      }

      function save() {

        if (currentId == null) { showToast('请先选择或新建一个人格'); return; }

        var name = (editTitle.value || '').trim();

        var prompt = (editText.value || '');

        if (!name) { showToast('名称不能为空'); return; }

        var payload = { action: 'update', id: currentId, name: name, prompt: prompt, bot: aiBotVal(),

                        active: currentId === activeId };

        fetch(API_BASE + '/api/ai/persona', {

          method: 'POST',

          headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify(payload)

        })

          .then(function (r) { return r.json(); })

          .then(function (d) {

            if (d && d.ok) { showToast('✅ 已保存'); load(); }

            else showToast('保存失败：' + ((d && d.error) || '未知'));

          })

          .catch(function () { showToast('⚠️ 保存失败：请确认机器人正在运行'); });

      }

      function resetContent() {

        editText.value = '';

        refreshCount();

        save();

      }

      function addNew() {

        fetch(API_BASE + '/api/ai/persona', {

          method: 'POST',

          headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify({ action: 'add', name: '新人格', prompt: '', active: false, bot: aiBotVal() })

        })

          .then(function (r) { return r.json(); })

          .then(function (d) {

            if (d && d.ok && d.persona_id) {

              currentId = d.persona_id;

              load();

              if (editTitle) setTimeout(function () { editTitle.focus(); }, 50);

              showToast('已新建，填写后点保存');

            } else showToast('新建失败：' + ((d && d.error) || '未知'));

          })

          .catch(function () { showToast('⚠️ 新建失败：请确认机器人正在运行'); });

      }

      function del(id) {

        if (!confirm('确定删除该人格吗？此操作不可撤销。')) return;

        fetch(API_BASE + '/api/ai/persona', {

          method: 'POST',

          headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify({ action: 'delete', id: id, bot: aiBotVal() })

        })

          .then(function (r) { return r.json(); })

          .then(function (d) {

            if (d && d.ok) {

              if (currentId === id) currentId = null;

              showToast('✅ 已删除'); load();

            } else showToast('删除失败：' + ((d && d.error) || '未知'));

          })

          .catch(function () { showToast('⚠️ 删除失败'); });

      }

      function setActive(id) {

        fetch(API_BASE + '/api/ai/persona', {

          method: 'POST',

          headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify({ action: 'set_active', id: id, bot: aiBotVal() })

        })

          .then(function (r) { return r.json(); })

          .then(function (d) {

            if (d && d.ok) { showToast('✅ 已切换使用的人格'); load(); }

            else showToast('切换失败：' + ((d && d.error) || '未知'));

          })

          .catch(function () { showToast('⚠️ 切换失败'); });

      }

      if (list) list.addEventListener('click', function (e) {

        var rename = e.target.closest('.op-link.rename');

        var delLink = e.target.closest('.op-link.del');

        var toggle = e.target.closest('input[type="checkbox"]');

        var item = e.target.closest('.kb-base-item');

        if (rename) {

          select(parseInt(rename.getAttribute('data-id'), 10));

          if (editTitle) setTimeout(function () { editTitle.focus(); editTitle.select(); }, 50);

        } else if (delLink) {

          del(parseInt(delLink.getAttribute('data-id'), 10));

        } else if (toggle) {

          var id = parseInt(toggle.getAttribute('data-id'), 10);

          // 立即给出视觉反馈

          activeId = id; renderList();

          if (toggle.checked) setActive(id);

          else { /* 关闭 = 取消使用，回到默认人设 */ setActive(-1); }

        } else if (item && !toggle) {

          select(parseInt(item.getAttribute('data-id'), 10));

        }

      });

      if (editText) editText.addEventListener('input', refreshCount);

      if (saveBtn) saveBtn.addEventListener('click', save);

      if (resetBtn) resetBtn.addEventListener('click', resetContent);

      if (refreshBtn) refreshBtn.addEventListener('click', load);

      if (addBtn) addBtn.addEventListener('click', addNew);

      if (botSel) botSel.addEventListener('change', function () { load(); });

      function onShow() { fillBotSelect(botSel, '默认（全局 _shared）'); load(); }

      loadAiPersonaRef = onShow;

    })();

    // ---------- 知识库 ----------

    // ---------- 知识库（布局仿照人格设置：左列表 + 右编辑器，无弹窗） ----------

    (function aiKnowledge() {

      var botSel = document.getElementById('ai-knowledge-bot-select');

      function aiBotVal() { return botSel && botSel.value ? botSel.value : ''; }

      var baseListEl = document.getElementById('ai-kb-base-list');

      var baseEmptyEl = document.getElementById('ai-kb-base-empty');

      var currentNameEl = document.getElementById('ai-kb-current-name');

      var currentCountEl = document.getElementById('ai-kb-current-count');

      var editName = document.getElementById('ai-kb-edit-name');

      var entriesEl = document.getElementById('ai-kb-edit-entries');

      var entryCountEl = document.getElementById('ai-kb-edit-entry-count');

      var addEntryBtn = document.getElementById('ai-kb-edit-add-entry');

      var saveBtn = document.getElementById('ai-kb-save');

      var clearBtn = document.getElementById('ai-kb-clear');

      var refreshBtn = document.getElementById('ai-kb-refresh');

      var addBaseBtn = document.getElementById('ai-kb-add-base');

      if (!baseListEl || !entriesEl) return;

      var bases = [];

      var currentBaseId = null;

      var baseEditState = { entries: [], nextKey: 1, saving: false };

      function load() {

        fetch(API_BASE + '/api/ai/knowledge?bot=' + encodeURIComponent(aiBotVal()), { method: 'GET' })

          .then(function (r) { return r.json(); })

          .then(function (d) {

            bases = (d && d.bases) || [];

            renderBases();

            if (currentBaseId == null || !bases.some(function (b) { return b.id === currentBaseId; })) {

              var first = bases.filter(function (b) { return b.active; })[0] || bases[0];

              currentBaseId = first ? first.id : null;

            }

            renderEditor();

          })

          .catch(function () {});

      }

      function currentBase() {

        return bases.filter(function (b) { return b.id === currentBaseId; })[0] || null;

      }

      function renderBases() {

        if (!baseListEl) return;

        baseListEl.innerHTML = '';

        if (!bases.length) { if (baseEmptyEl) baseEmptyEl.style.display = 'block'; return; }

        if (baseEmptyEl) baseEmptyEl.style.display = 'none';

        bases.forEach(function (b) {

          var div = document.createElement('div');

          var cnt = (b.items || []).length;

          div.className = 'kb-base-item' + (b.id === currentBaseId ? ' active' : '') + (b.active ? ' using' : '');

          div.setAttribute('data-base', b.id);

          div.innerHTML =

            '<div class="kb-base-row">' +

              '<span class="kb-base-name">' + escapeHtml(b.name || '') + '</span>' +

              '<span class="kb-base-badge">' + cnt + '</span>' +

            '</div>' +

            '<div class="kb-base-meta">' +

              '<span class="kb-base-state ' + (b.active ? 'on' : 'off') + '">' + (b.active ? '使用中' : '未使用') + '</span>' +

              '<span class="op-link rename" data-base="' + b.id + '">改名</span>' +

              '<span class="op-link del" data-base="' + b.id + '">删除</span>' +

            '</div>' +

            '<label class="switch kb-base-use-switch" title="设为使用中">' +

              '<input type="checkbox" ' + (b.active ? 'checked' : '') + ' data-base="' + b.id + '" />' +

              '<span class="track"></span><span class="thumb"></span>' +

            '</label>';

          baseListEl.appendChild(div);

        });

      }

      function select(id) {

        currentBaseId = id;

        renderBases();

        renderEditor();

      }

      function renderEditor() {

        var b = currentBase();

        if (!b) {

          if (currentNameEl) currentNameEl.textContent = '未选择知识库';

          if (currentCountEl) currentCountEl.textContent = '';

          if (editName) editName.value = '';

          baseEditState.entries = [];

          baseEditState.nextKey = 1;

          renderEntries();

          return;

        }

        if (currentNameEl) currentNameEl.textContent = b.name || '';

        if (currentCountEl) currentCountEl.textContent = (b.items || []).length + ' 条';

        if (editName) editName.value = b.name || '';

        baseEditState.entries = [];

        baseEditState.nextKey = 1;

        (b.items || []).forEach(function (it) {

          baseEditState.entries.push({

            _key: baseEditState.nextKey++,

            id: it.id,

            title: it.title || '',

            content: it.content || '',

            enabled: it.enabled !== false,

            _deleted: false,

            _isNew: false

          });

        });

        renderEntries();

      }

      function renderEntries() {

        if (!entriesEl) return;

        entriesEl.innerHTML = '';

        var live = baseEditState.entries.filter(function (e) { return !e._deleted; });

        if (entryCountEl) entryCountEl.textContent = live.length + ' 条';

        if (!live.length) {

          var empty = document.createElement('div');

          empty.className = 'kb-empty-entries';

          empty.textContent = '暂无条目，点击下方「+ 添加条目」创建';

          entriesEl.appendChild(empty);

          return;

        }

        live.forEach(function (e, idx) {

          var row = document.createElement('div');

          row.className = 'kb-entry-row';

          row.dataset.key = e._key;

          row.innerHTML =

            '<div class="kb-entry-row-head">' +

              '<span class="kb-entry-no">#' + (idx + 1) + (e.id != null ? ' · ID ' + e.id : ' · 新建') + '</span>' +

              '<input class="input kb-entry-title" type="text" placeholder="标题" />' +

              '<button class="kb-entry-del" type="button" title="移除此条">×</button>' +

            '</div>' +

            '<textarea class="input kb-entry-content" placeholder="内容（AI 会优先参考）" rows="3"></textarea>';

          var ti = row.querySelector('.kb-entry-title');

          var ta = row.querySelector('.kb-entry-content');

          ti.value = e.title;

          ta.value = e.content;

          ti.addEventListener('input', function () { e.title = ti.value; });

          ta.addEventListener('input', function () { e.content = ta.value; });

          row.querySelector('.kb-entry-del').addEventListener('click', function () {

            e._deleted = true;

            renderEntries();

          });

          entriesEl.appendChild(row);

        });

      }

      function addEntryRow() {

        baseEditState.entries.push({

          _key: baseEditState.nextKey++,

          id: null,

          title: '',

          content: '',

          enabled: true,

          _deleted: false,

          _isNew: true

        });

        renderEntries();

        setTimeout(function () {

          if (entriesEl) entriesEl.scrollTop = entriesEl.scrollHeight;

          var inputs = entriesEl ? entriesEl.querySelectorAll('.kb-entry-title') : [];

          if (inputs.length) inputs[inputs.length - 1].focus();

        }, 0);

      }

      function clearEntries() {

        if (!baseEditState.entries.length) return;

        if (!confirm('确定清空当前知识库的所有条目吗？点击「保存」后才会生效。')) return;

        baseEditState.entries = [];

        renderEntries();

      }

      function save() {

        if (baseEditState.saving) return;

        if (currentBaseId == null) { showToast('请先选择或新建一个知识库'); return; }

        var name = (editName.value || '').trim();

        if (!name) { showToast('名称不能为空'); return; }

        var live = baseEditState.entries.filter(function (e) { return !e._deleted; });

        var bad = live.find(function (e) { return !e.title.trim() || !e.content.trim(); });

        if (bad) { showToast('所有条目的标题和内容均不能为空'); return; }

        live = live.filter(function (e) { return !(e.id == null && e._isNew && !e.title.trim() && !e.content.trim()); });

        baseEditState.saving = true;

        if (saveBtn) saveBtn.disabled = true;

        function postJSON(p) {

          if (aiBotVal()) p.bot = aiBotVal();

          return fetch(API_BASE + '/api/ai/knowledge', {

            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(p)

          }).then(function (r) { return r.json(); });

        }

        function delItem(baseId, itemId) {

          return fetch(API_BASE + '/api/ai/knowledge?kind=item&base_id=' + baseId + '&id=' + itemId + (aiBotVal() ? '&bot=' + encodeURIComponent(aiBotVal()) : ''), { method: 'DELETE' })

            .then(function (r) { return r.json(); });

        }

        var b = currentBase();

        var active = b ? !!b.active : false;

        postJSON({ action: 'update_base', id: currentBaseId, name: name, active: active })

          .then(function (d) {

            if (!d || !d.ok) throw new Error((d && d.error) || '保存失败');

            var chain = Promise.resolve();

            baseEditState.entries.filter(function (e) { return e.id != null && e._deleted; }).forEach(function (e) {

              chain = chain.then(function () { return delItem(currentBaseId, e.id); });

            });

            baseEditState.entries.filter(function (e) { return e.id != null && !e._deleted; }).forEach(function (e) {

              chain = chain.then(function () {

                return postJSON({ action: 'update_item', base_id: currentBaseId, id: e.id, title: e.title, content: e.content, enabled: e.enabled });

              });

            });

            live.filter(function (e) { return e.id == null && e._isNew; }).forEach(function (e) {

              chain = chain.then(function () {

                return postJSON({ action: 'add_item', base_id: currentBaseId, title: e.title.trim(), content: e.content.trim(), enabled: e.enabled });

              });

            });

            return chain;

          })

          .then(function () { showToast('✅ 已保存'); load(); })

          .catch(function (err) { showToast('保存失败：' + ((err && err.message) || err)); })

          .then(function () { baseEditState.saving = false; if (saveBtn) saveBtn.disabled = false; });

      }

      function addNew() {

        fetch(API_BASE + '/api/ai/knowledge', {

          method: 'POST', headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify({ action: 'add_base', name: '新知识库', active: false, bot: aiBotVal() })

        })

          .then(function (r) { return r.json(); })

          .then(function (d) {

            if (d && d.ok && d.base_id) {

              currentBaseId = d.base_id;

              load();

              if (editName) setTimeout(function () { editName.focus(); editName.select(); }, 50);

              showToast('已新建，填写后点保存');

            } else showToast('新建失败：' + ((d && d.error) || '未知'));

          })

          .catch(function () { showToast('⚠️ 新建失败：请确认机器人正在运行'); });

      }

      function delBase(id) {

        var b = bases.filter(function (x) { return x.id === id; })[0];

        var cnt = b ? (b.items || []).length : 0;

        if (!confirm('确定删除知识库「' + (b ? b.name : '') + '」吗？' + (cnt ? ('含 ' + cnt + ' 条知识') : '') + '，此操作不可恢复')) return;

        fetch(API_BASE + '/api/ai/knowledge?kind=base&id=' + id + (aiBotVal() ? '&bot=' + encodeURIComponent(aiBotVal()) : ''), { method: 'DELETE' })

          .then(function (r) { return r.json(); })

          .then(function (d) {

            if (d && d.ok) { showToast('✅ 已删除'); if (currentBaseId === id) currentBaseId = null; load(); }

            else showToast('删除失败：' + ((d && d.error) || '未知'));

          })

          .catch(function () { showToast('⚠️ 删除失败'); });

      }

      function toggleBaseActive(id, checked) {

        fetch(API_BASE + '/api/ai/knowledge', {

          method: 'POST', headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify({ action: 'update_base', id: id, active: checked, bot: aiBotVal() })

        }).catch(function () {});

      }

      if (baseListEl) baseListEl.addEventListener('click', function (e) {

        var rename = e.target.closest('.op-link.rename');

        var delLink = e.target.closest('.op-link.del');

        var switchLabel = e.target.closest('.kb-base-use-switch');

        var item = e.target.closest('.kb-base-item');

        if (rename) {

          select(parseInt(rename.getAttribute('data-base'), 10));

          if (editName) setTimeout(function () { editName.focus(); editName.select(); }, 50);

        } else if (delLink) {

          delBase(parseInt(delLink.getAttribute('data-base'), 10));

        } else if (switchLabel) {

          // 开关区域（label/track/thumb/input）由 change 事件统一处理。

          // 不能在这里 select()，否则 renderBases() 会重建 DOM，

          // 把 input 从树里 detach 掉，导致浏览器后续转发到 input 的

          // 第二次 click 事件 bubble 不到 baseListEl，toggle 永远不生效。

          return;

        } else if (item) {

          select(parseInt(item.getAttribute('data-base'), 10));

        }

      });

      // 开关 change 事件委托：监听所有 data-base checkbox 的状态变化。

      // 用 change 而非 click，是因为 input 是 display:none，点击 track/thumb

      // 时 e.target.closest('input') 拿不到 input（closest 只找祖先），依赖

      // label 转发 click 不可靠；change 事件由浏览器在 input.checked 翻转后触发，

      // 不受 DOM 中间是否被重建的影响。

      if (baseListEl) baseListEl.addEventListener('change', function (e) {

        var input = e.target;

        if (!input || input.tagName !== 'INPUT' || input.type !== 'checkbox' || !input.hasAttribute('data-base')) return;

        var id = parseInt(input.getAttribute('data-base'), 10);

        toggleBaseActive(id, input.checked);

        var b = bases.filter(function (x) { return x.id === id; })[0];

        if (b) b.active = input.checked;

        // 只更新该 base 自己的视觉状态（class + 状态文案），不要整体 renderBases()

        var parent = input.closest('.kb-base-item');

        if (parent) {

          parent.classList.toggle('using', input.checked);

          var state = parent.querySelector('.kb-base-state');

          if (state) {

            state.className = 'kb-base-state ' + (input.checked ? 'on' : 'off');

            state.textContent = input.checked ? '使用中' : '未使用';

          }

        }

      });

      if (addEntryBtn) addEntryBtn.addEventListener('click', addEntryRow);

      if (clearBtn) clearBtn.addEventListener('click', clearEntries);

      if (saveBtn) saveBtn.addEventListener('click', save);

      if (refreshBtn) refreshBtn.addEventListener('click', load);

      if (addBaseBtn) addBaseBtn.addEventListener('click', addNew);

      if (botSel) botSel.addEventListener('change', function () { load(); });

      function onShow() { fillBotSelect(botSel, '默认（全局 _shared）'); load(); }

      loadAiKnowledgeRef = onShow;

    })();

    // ---------- 定时任务 ----------

    (function scheduledCenter() {

      var tbody = document.getElementById('scheduled-tbody');

      var empty = document.getElementById('scheduled-empty');

      var addBtn = document.getElementById('scheduled-add');

      var botSel = document.getElementById('scheduled-bot-select');

      var showAll = document.getElementById('scheduled-show-all');

      var modal = document.getElementById('scheduled-modal');

      var modalTitle = document.getElementById('scheduled-modal-title');

      var sId = document.getElementById('scheduled-edit-id');

      var sBot = document.getElementById('scheduled-edit-bot');

      var sName = document.getElementById('scheduled-edit-name');

      var sCron = document.getElementById('scheduled-edit-cron');

      var sTargetTypeWrap = document.getElementById('scheduled-target-type-select');

      var sTargetGroupWrap = document.getElementById('scheduled-target-group-select');

      var sTargetGroupOptions = document.getElementById('scheduled-target-group-options');

      var sTargetGroupSearch = document.getElementById('scheduled-target-group-search');

      var sContent = document.getElementById('scheduled-edit-content');

      var sMsgTypeWrap = document.getElementById('scheduled-msg-type-select');

      var timingTabs = document.querySelectorAll('.scheduled-timing-tab');

      var cronRow = document.getElementById('scheduled-cron-row');

      var quickRow = document.getElementById('scheduled-quick-row');

      var quickHour = document.getElementById('scheduled-quick-hour');

      var quickMin = document.getElementById('scheduled-quick-min');

      var quickRepeat = document.getElementById('scheduled-quick-repeat');

      var generatedCron = document.getElementById('scheduled-generated-cron');

      var autoGenBtn = document.getElementById('scheduled-auto-gen');

      var okBtn = document.getElementById('scheduled-modal-ok');

      var cancelBtn = document.getElementById('scheduled-modal-cancel');

      var closeBtn = document.getElementById('scheduled-modal-close');

      var typeRadios = document.querySelectorAll('input[name="scheduled-type"]');

      var targetTypeRow = document.getElementById('scheduled-target-type-row');

      var sTargetGroupRow = document.getElementById('scheduled-target-group-row');

      // 整行 wrapper（系统任务模式下整体隐藏，修复 flex 不 collapse 的 bug）

      var sTargetTwoCol = targetTypeRow && targetTypeRow.closest('.ai-form-row-two-col');

      if (!tbody) return;

      var items = [];

      var currentBotFilter = '';

      var currentTiming = 'cron';

      var msgTypeMeta = {

        text: { icon: '📝', text: '文本消息' },

        markdown: { icon: '📄', text: 'Markdown消息' }

      };

      function typeLabel(type) { return type === 'system' ? '系统任务' : '群聊任务'; }

      function render(list) {

        items = list || [];

        if (!items.length) {

          tbody.innerHTML = '';

          if (empty) empty.style.display = 'block';

          return;

        }

        if (empty) empty.style.display = 'none';

        tbody.innerHTML = items.map(function (s) {

          var status = s.enabled ? '<span class="status-tag enabled">启用</span>' : '<span class="status-tag disabled">停用</span>';

          var cls = s.type === 'system' ? 'type-tag system' : 'type-tag';

          return '<tr>' +

            '<td>' + escapeHtml(botDisplayName(s.bot) || '-') + '</td>' +

            '<td>' + escapeHtml(s.name || '') + '</td>' +

            '<td><span class="' + cls + '">' + typeLabel(s.type) + '</span></td>' +

            '<td><code>' + escapeHtml(s.cron || '') + '</code></td>' +

            '<td>' + status + '</td>' +

            '<td>' + (s.exec_count || 0) + '</td>' +

            '<td>' + (s.last_exec || '-') + '</td>' +

            '<td>' +

              '<label class="switch"><input type="checkbox" data-id="' + s.id + '"' + (s.enabled ? ' checked' : '') + '><span class="track"></span><span class="thumb"></span></label>' +

              '<span class="op-link edit" data-id="' + s.id + '">编辑</span>' +

              '<span class="op-link del" data-id="' + s.id + '">删除</span>' +

            '</td>' +

          '</tr>';

        }).join('');

      }

      function load() {

        var url = API_BASE + '/api/scheduled-tasks';

        if (currentBotFilter) url += '?bot=' + encodeURIComponent(currentBotFilter);

        fetch(url)

          .then(function (r) { return r.json(); })

          .then(function (data) { render((data && data.tasks) || []); })

          .catch(function () { showToast('加载定时任务失败'); });

      }

      var targetGroupData = []; // 当前缓存的群列表（用于搜索过滤）

      function renderTargetGroupOptions(filter) {

        if (!sTargetGroupOptions) return;

        var kw = (filter || '').toLowerCase().trim();

        var list = targetGroupData.filter(function (g) {

          if (!kw) return true;

          var name = (g.name || '').toLowerCase();

          var oid = (g.openid || '').toLowerCase();

          return name.indexOf(kw) >= 0 || oid.indexOf(kw) >= 0;

        });

        if (!list.length) {

          sTargetGroupOptions.innerHTML = '<div class="ai-custom-empty">没有匹配的群</div>';

          return;

        }

        var current = sTargetGroupWrap ? (sTargetGroupWrap.getAttribute('data-value') || '') : '';

        var html = '';

        list.forEach(function (g) {

          var active = g.openid === current ? ' active' : '';

          html += '<div class="ai-custom-option' + active + '" data-value="' + escapeHtml(g.openid) + '">' +

            '<span class="ai-scope-icon">💬</span>' +

            '<div class="ai-scope-line"><span class="ai-scope-title">' + escapeHtml(g.name || g.openid) + '</span>' +

            '<span class="ai-scope-desc">' + escapeHtml(g.openid) + '</span></div></div>';

        });

        sTargetGroupOptions.innerHTML = html;

        bindTargetGroupOptionEvents();

      }

      function bindTargetGroupOptionEvents() {

        if (!sTargetGroupOptions) return;

        sTargetGroupOptions.querySelectorAll('.ai-custom-option').forEach(function (opt) {

          opt.addEventListener('click', function (e) {

            e.stopPropagation();

            var val = opt.getAttribute('data-value') || '';

            var name = opt.querySelector('.ai-scope-title');

            setTargetGroup(val, name ? name.textContent : '选择群');

            if (sTargetGroupWrap) sTargetGroupWrap.classList.remove('open');

          });

        });

      }

      // 统一入口：根据当前 targetType 调 /api/groups 或 /api/c2c-users

      // 后端两个端点都返回 {items: [...]}；前端按 bot 过滤。

      function loadTargetList() {

        var t = getTargetType();

        var url = (t === '指定用户（单聊）') ? (API_BASE + '/api/c2c-users') : (API_BASE + '/api/groups');

        var botVal = sBot ? sBot.value : '';

        if (botVal) url += (url.indexOf('?') >= 0 ? '&' : '?') + 'bot=' + encodeURIComponent(botVal);

        fetch(url)

          .then(function (r) { return r.json(); })

          .then(function (data) {

            targetGroupData = (data && data.items) || [];

            renderTargetGroupOptions(sTargetGroupSearch ? (sTargetGroupSearch.value || '') : '');

          })

          .catch(function () {

            targetGroupData = [];

            if (sTargetGroupOptions) sTargetGroupOptions.innerHTML = '<div class="ai-custom-empty">加载目标列表失败</div>';

          });

      }

      function initTargetTypeSelect() {

        if (!sTargetTypeWrap) return;

        var trigger = sTargetTypeWrap.querySelector('.ai-custom-select-trigger');

        var opts = sTargetTypeWrap.querySelectorAll('.ai-custom-option');

        function refresh() {

          var val = sTargetTypeWrap.getAttribute('data-value') || '指定群聊';

          var opt = sTargetTypeWrap.querySelector('.ai-custom-option[data-value="' + val + '"]');

          if (opt) {

            var title = opt.querySelector('.ai-scope-title');

            var icon = opt.querySelector('.ai-scope-icon');

            var triggerIcon = trigger.querySelector('.ai-scope-icon');

            var triggerText = trigger.querySelector('.ai-custom-select-text');

            if (triggerIcon && icon) triggerIcon.textContent = icon.textContent;

            if (triggerText && title) triggerText.textContent = title.textContent;

          }

        }

        trigger.addEventListener('click', function (e) {

          e.stopPropagation();

          sTargetTypeWrap.classList.toggle('open');

        });

        opts.forEach(function (opt) {

          opt.addEventListener('click', function (e) {

            e.stopPropagation();

            var val = opt.getAttribute('data-value') || '指定群聊';

            sTargetTypeWrap.setAttribute('data-value', val);

            opts.forEach(function (o) { o.classList.remove('active'); });

            opt.classList.add('active');

            refresh();

            sTargetTypeWrap.classList.remove('open');

            // 切换目标类型时：

            //   1) 全部模式 → 隐藏整行 wrapper（避免「消息目标」标题下出现大空白）

            //   2) 指定模式 → 显示 wrapper，同时切 label/trigger 文字/图标 + 清空旧选择 + 重载

            var isAll = (val === '该机器人全部群聊' || val === '该机器人全部单聊用户');

            if (sTargetTwoCol) sTargetTwoCol.style.display = isAll ? 'none' : '';

            if (sTargetGroupRow) sTargetGroupRow.style.display = (val === '指定群聊' || val === '指定用户（单聊）') ? '' : 'none';

            if (sTargetGroupRow && sTargetGroupWrap) {

              var labelEl = sTargetGroupRow.querySelector('.ai-label');

              var triggerText = sTargetGroupWrap.querySelector('.ai-custom-select-trigger .ai-custom-select-text');

              var triggerIcon = sTargetGroupWrap.querySelector('.ai-custom-select-trigger .ai-scope-icon');

              if (val === '指定用户（单聊）') {

                if (labelEl) labelEl.textContent = '选择用户';

                if (triggerText) triggerText.textContent = '选择用户';

                if (triggerIcon) triggerIcon.textContent = '👤';

              } else {

                if (labelEl) labelEl.textContent = '选择群';

                if (triggerText) triggerText.textContent = '选择群';

                if (triggerIcon) triggerIcon.textContent = '🏷️';

              }

              setTargetGroup('', (val === '指定用户（单聊）') ? '选择用户' : '选择群');

            }

            if (!isAll) {

              targetGroupData = [];

              if (sTargetGroupSearch) sTargetGroupSearch.value = '';

              loadTargetList();

            }

          });

        });

        refresh();

      }

      function initTargetGroupSelect() {

        if (!sTargetGroupWrap) return;

        var trigger = sTargetGroupWrap.querySelector('.ai-custom-select-trigger');

        trigger.addEventListener('click', function (e) {

          e.stopPropagation();

          // 若数据为空则主动加载

          if (!targetGroupData.length) loadTargetList();

          sTargetGroupWrap.classList.toggle('open');

        });

        if (sTargetGroupSearch) {

          sTargetGroupSearch.addEventListener('click', function (e) { e.stopPropagation(); });

          sTargetGroupSearch.addEventListener('input', function () {

            renderTargetGroupOptions(sTargetGroupSearch.value);

          });

        }

      }

      function setTargetType(val) {

        if (!sTargetTypeWrap) return;

        var v = val || '指定群聊';

        sTargetTypeWrap.setAttribute('data-value', v);

        sTargetTypeWrap.querySelectorAll('.ai-custom-option').forEach(function (o) {

          o.classList.toggle('active', o.getAttribute('data-value') === v);

        });

        var opt = sTargetTypeWrap.querySelector('.ai-custom-option[data-value="' + v + '"]');

        if (opt) {

          var title = opt.querySelector('.ai-scope-title');

          var icon = opt.querySelector('.ai-scope-icon');

          var triggerIcon = sTargetTypeWrap.querySelector('.ai-custom-select-trigger .ai-scope-icon');

          var triggerText = sTargetTypeWrap.querySelector('.ai-custom-select-trigger .ai-custom-select-text');

          if (triggerIcon && icon) triggerIcon.textContent = icon.textContent;

          if (triggerText && title) triggerText.textContent = title.textContent;

        }

        // 全部模式 → 隐藏整行 wrapper（系统任务下也由 toggleTypeRows 控制）

        var isAll = (v === '该机器人全部群聊' || v === '该机器人全部单聊用户');

        if (sTargetTwoCol) sTargetTwoCol.style.display = isAll ? 'none' : '';

        if (sTargetGroupRow) sTargetGroupRow.style.display = (v === '指定群聊' || v === '指定用户（单聊）') ? '' : 'none';

        // 同步右侧 label / trigger 文字/图标

        if (sTargetGroupRow && sTargetGroupWrap) {

          var labelEl2 = sTargetGroupRow.querySelector('.ai-label');

          var triggerText2 = sTargetGroupWrap.querySelector('.ai-custom-select-trigger .ai-custom-select-text');

          var triggerIcon2 = sTargetGroupWrap.querySelector('.ai-custom-select-trigger .ai-scope-icon');

          if (v === '指定用户（单聊）') {

            if (labelEl2) labelEl2.textContent = '选择用户';

            if (triggerText2) triggerText2.textContent = '选择用户';

            if (triggerIcon2) triggerIcon2.textContent = '👤';

          } else {

            if (labelEl2) labelEl2.textContent = '选择群';

            if (triggerText2) triggerText2.textContent = '选择群';

            if (triggerIcon2) triggerIcon2.textContent = '🏷️';

          }

        }

      }

      function getTargetType() {

        return sTargetTypeWrap ? (sTargetTypeWrap.getAttribute('data-value') || '指定群聊') : '指定群聊';

      }

      function setTargetGroup(openid, displayName) {

        if (!sTargetGroupWrap) return;

        sTargetGroupWrap.setAttribute('data-value', openid || '');

        var triggerText = sTargetGroupWrap.querySelector('.ai-custom-select-trigger .ai-custom-select-text');

        if (triggerText) triggerText.textContent = displayName || '选择群';

        if (sTargetGroupOptions) {

          sTargetGroupOptions.querySelectorAll('.ai-custom-option').forEach(function (o) {

            o.classList.toggle('active', (o.getAttribute('data-value') || '') === (openid || ''));

          });

        }

      }

      function getTargetGroup() {

        return sTargetGroupWrap ? (sTargetGroupWrap.getAttribute('data-value') || '') : '';

      }

      function initMsgTypeSelect() {

        if (!sMsgTypeWrap) return;

        var trigger = sMsgTypeWrap.querySelector('.ai-custom-select-trigger');

        var opts = sMsgTypeWrap.querySelectorAll('.ai-custom-option');

        function update() {

          var val = sMsgTypeWrap.getAttribute('data-value');

          var m = msgTypeMeta[val] || msgTypeMeta.text;

          var text = trigger.querySelector('.ai-custom-select-text');

          var icon = trigger.querySelector('.ai-msg-type-icon');

          if (text) text.textContent = m.text;

          if (icon) icon.textContent = m.icon;

        }

        trigger.addEventListener('click', function (e) {

          e.stopPropagation();

          sMsgTypeWrap.classList.toggle('open');

        });

        opts.forEach(function (opt) {

          opt.addEventListener('click', function (e) {

            e.stopPropagation();

            var val = opt.getAttribute('data-value');

            sMsgTypeWrap.setAttribute('data-value', val);

            opts.forEach(function (o) { o.classList.remove('active'); });

            opt.classList.add('active');

            update();

            sMsgTypeWrap.classList.remove('open');

          });

        });

        update();

      }

      function setMsgType(val) {

        if (!sMsgTypeWrap) return;

        sMsgTypeWrap.setAttribute('data-value', val || 'text');

        sMsgTypeWrap.querySelectorAll('.ai-custom-option').forEach(function (o) {

          o.classList.toggle('active', o.getAttribute('data-value') === (val || 'text'));

        });

        var m = msgTypeMeta[val || 'text'] || msgTypeMeta.text;

        var trigger = sMsgTypeWrap.querySelector('.ai-custom-select-trigger');

        if (trigger) {

          trigger.querySelector('.ai-custom-select-text').textContent = m.text;

          trigger.querySelector('.ai-msg-type-icon').textContent = m.icon;

        }

      }

      function getMsgType() {

        return sMsgTypeWrap ? sMsgTypeWrap.getAttribute('data-value') : 'text';

      }

      function initQuickSelects() {

        if (!quickHour || !quickMin) return;

        var h = '';

        for (var i = 0; i < 24; i++) h += '<option value="' + (i < 10 ? '0' : '') + i + '">' + (i < 10 ? '0' : '') + i + '</option>';

        quickHour.innerHTML = h;

        quickHour.value = '09';

        var m = '';

        for (var i = 0; i < 60; i++) m += '<option value="' + (i < 10 ? '0' : '') + i + '">' + (i < 10 ? '0' : '') + i + '</option>';

        quickMin.innerHTML = m;

        quickMin.value = '00';

      }

      function generateCronFromQuick() {

        var min = quickMin ? quickMin.value : '00';

        var hour = quickHour ? quickHour.value : '09';

        var repeat = quickRepeat ? quickRepeat.value : '* * *';

        return min + ' ' + hour + ' ' + repeat;

      }

      function updateGeneratedCron() {

        if (generatedCron) generatedCron.value = generateCronFromQuick();

      }

      function applyGeneratedCron() {

        if (currentTiming !== 'quick') return;

        if (sCron) sCron.value = generateCronFromQuick();

      }

      function openModal(isEdit, item) {

        if (!modal) return;

        try {

        modalTitle.textContent = isEdit ? '编辑定时任务' : '新建定时任务';

        sId.value = item ? item.id : '';

        fillBotSelect(sBot, '选择机器人');

        sBot.value = item ? (item.bot || '') : '';

        sName.value = item ? (item.name || '') : '';

        sCron.value = item ? (item.cron || '0 9 * * *') : '0 9 * * *';

        setTargetType(item ? (item.target_type || '指定群聊') : '指定群聊');

        // 编辑时：先确保群列表已加载，再设置选中的群

        if (item && item.target_group) {

          // 等群列表加载完后再回填（loadGroups 是异步的）

          var applyGroup = function () {

            if (!targetGroupData.length) { setTimeout(applyGroup, 80); return; }

            var found = targetGroupData.find(function (g) { return g.openid === item.target_group; });

            setTargetGroup(item.target_group, found ? (found.name || found.openid) : ('群 ' + (item.target_group || '').slice(-6)));

          };

          applyGroup();

        } else {

          setTargetGroup('', '选择群');

        }

        sContent.value = item ? (item.content || '') : '';

        setMsgType(item ? item.msg_type : 'text');

        var taskType = item ? (item.type || 'group') : 'group';

        typeRadios.forEach(function (r) {

          r.checked = r.value === taskType;

          r.closest('.scheduled-radio').classList.toggle('active', r.value === taskType);

        });

        toggleTypeRows(taskType);

        switchTimingTab('cron');

        loadTargetList();

        modal.classList.add('active');

        modal.style.display = 'flex';

        modal.removeAttribute('hidden');

        setTimeout(function () { modal.classList.add('show'); }, 20);

      } catch (err) {

        // 兜底：防御性编程，正常情况不会触发。出错时仍强制显示 modal（display+active+show），

        // 并把错误打到 console 方便排查，但不打扰最终用户。

        try {

          modal.classList.add('active');

          modal.classList.add('show');

          modal.style.display = 'flex';

        } catch (_) { /* ignore */ }

        if (typeof console !== 'undefined' && console.error) console.error('[scheduled] openModal 失败:', err);

      }

      }

      function closeModal() {

        if (!modal) return;

        modal.classList.remove('show');

        setTimeout(function () { modal.classList.remove('active'); modal.style.display = 'none'; }, 200);

      }

      function toggleTypeRows(type) {

        // 系统任务 → 整行 .ai-form-row-two-col 全部隐藏（修复 flex wrapper 仍占空间的 bug）

        if (sTargetTwoCol) sTargetTwoCol.style.display = (type === 'group') ? '' : 'none';

        if (targetTypeRow) targetTypeRow.style.display = type === 'group' ? 'block' : 'none';

        // 选择群/用户只在「群聊任务 + 指定（群聊/单聊）」时显示

        if (sTargetGroupRow) {

          var tt = getTargetType();

          var showPick = (type === 'group') && (tt === '指定群聊' || tt === '指定用户（单聊）');

          sTargetGroupRow.style.display = showPick ? 'block' : 'none';

        }

      }

      function switchTimingTab(mode) {

        currentTiming = mode;

        timingTabs.forEach(function (t) {

          t.classList.toggle('active', t.getAttribute('data-timing') === mode);

        });

        if (cronRow) cronRow.style.display = mode === 'cron' ? 'block' : 'none';

        if (quickRow) quickRow.style.display = mode === 'quick' ? 'block' : 'none';

      }

      function save() {

        var taskType = '';

        typeRadios.forEach(function (r) { if (r.checked) taskType = r.value; });

        var cron = currentTiming === 'quick' ? generateCronFromQuick() : (sCron.value || '').trim();

        var payload = {

          id: sId.value ? parseInt(sId.value, 10) : null,

          bot: sBot.value,

          name: sName.value.trim(),

          type: taskType,

          cron: cron,

          target_type: taskType === 'group' ? getTargetType() : '',

          target_group: taskType === 'group' ? getTargetGroup() : '',

          msg_type: getMsgType(),

          content: sContent.value.trim(),

          enabled: true

        };

        if (!payload.bot) { showToast('请选择机器人'); return; }

        if (!payload.name) { showToast('请输入任务名称'); return; }

        if (!payload.cron) { showToast('请输入 Cron 表达式'); return; }

        if (payload.type === 'group' && !payload.target_group) { showToast('请选择目标群'); return; }

        fetch(API_BASE + '/api/scheduled-tasks', {

          method: 'POST',

          headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify(payload)

        })

          .then(function (r) { return r.json(); })

          .then(function (data) {

            if (data && data.ok) {

              closeModal();

              load();

              showToast('保存成功');

            } else {

              showToast('保存失败：' + (data && data.error ? data.error : '未知错误'));

            }

          })

          .catch(function () { showToast('保存失败'); });

      }

      function deleteTask(id) {

        if (!confirm('确定删除该定时任务？')) return;

        fetch(API_BASE + '/api/scheduled-tasks?id=' + id, { method: 'DELETE' })

          .then(function (r) { return r.json(); })

          .then(function (data) {

            if (data && data.ok) { load(); showToast('删除成功'); }

            else { showToast('删除失败'); }

          })

          .catch(function () { showToast('删除失败'); });

      }

      function editTask(id) {

        var item = items.find(function (x) { return x.id === id; });

        if (item) openModal(true, item);

      }

      if (addBtn) addBtn.addEventListener('click', function () { openModal(false); });

      // 备份：document 委托捕获 #scheduled-add 的点击（防止直接绑定失效/被覆盖）

      document.addEventListener('click', function (e) {

        var btn = e.target && e.target.closest && e.target.closest('#scheduled-add');

        if (btn) {

          e.preventDefault();

          openModal(false);

        }

      });

      if (okBtn) okBtn.addEventListener('click', save);

      if (cancelBtn) cancelBtn.addEventListener('click', closeModal);

      if (closeBtn) closeBtn.addEventListener('click', closeModal);

      if (botSel) botSel.addEventListener('change', function () { currentBotFilter = botSel.value; load(); updateBotStatusDot('scheduled-bot-select', 'scheduled-bot-dot'); });

      if (showAll) showAll.addEventListener('click', function () { if (botSel) botSel.value = ''; currentBotFilter = ''; load(); updateBotStatusDot('scheduled-bot-select', 'scheduled-bot-dot'); });

      if (sBot) sBot.addEventListener('change', function () { updateBotStatusDot('scheduled-edit-bot', 'scheduled-edit-bot-dot'); });

      try { updateBotStatusDot('scheduled-bot-select', 'scheduled-bot-dot'); } catch (e) {}

      try { updateBotStatusDot('scheduled-edit-bot', 'scheduled-edit-bot-dot'); } catch (e) {}

      if (timingTabs) timingTabs.forEach(function (t) {

        t.addEventListener('click', function () {

          var mode = t.getAttribute('data-timing');

          if (mode === 'quick' && currentTiming !== 'quick') {

            // 从 cron 切到 quick 时，尝试用当前 cron 回填时/分/重复

            var parts = (sCron.value || '').split(' ');

            if (parts.length === 5) {

              if (quickHour) quickHour.value = parts[1];

              if (quickMin) quickMin.value = parts[0];

              if (quickRepeat) quickRepeat.value = parts[2] + ' ' + parts[3] + ' ' + parts[4];

              updateGeneratedCron();

            }

          }

          switchTimingTab(mode);

        });

      });

      if (quickHour) quickHour.addEventListener('change', updateGeneratedCron);

      if (quickMin) quickMin.addEventListener('change', updateGeneratedCron);

      if (quickRepeat) quickRepeat.addEventListener('change', updateGeneratedCron);

      if (autoGenBtn) autoGenBtn.addEventListener('click', applyGeneratedCron);

      typeRadios.forEach(function (r) {

        r.addEventListener('change', function () {

          typeRadios.forEach(function (x) { x.closest('.scheduled-radio').classList.toggle('active', x.checked); });

          toggleTypeRows(r.value);

        });

      });

      if (tbody) tbody.addEventListener('click', function (e) {

        var del = e.target.closest('.op-link.del');

        var edit = e.target.closest('.op-link.edit');

        var toggle = e.target.closest('input[type="checkbox"]');

        if (del) deleteTask(parseInt(del.getAttribute('data-id'), 10));

        else if (edit) editTask(parseInt(edit.getAttribute('data-id'), 10));

        else if (toggle) {

          var id = parseInt(toggle.getAttribute('data-id'), 10);

          fetch(API_BASE + '/api/scheduled-tasks', {

            method: 'POST',

            headers: { 'Content-Type': 'application/json' },

            body: JSON.stringify({ id: id, enabled: toggle.checked })

          }).catch(function () { showToast('状态更新失败'); });

        }

      });

      if (modal) {

        document.addEventListener('click', function (e) {

          if (!modal.contains(e.target)) return;

          if (sMsgTypeWrap && !sMsgTypeWrap.contains(e.target)) sMsgTypeWrap.classList.remove('open');

          document.querySelectorAll('.ai-custom-select.open').forEach(function (el) {

            if (!el.contains(e.target)) el.classList.remove('open');

          });

        });

      }

      initQuickSelects();

      initTargetTypeSelect();

      initTargetGroupSelect();

      initMsgTypeSelect();

      updateGeneratedCron();

      function onShow() { fillBotSelect(botSel, '全部机器人'); load(); }

      loadScheduledRef = onShow;

    })();

    // ---------- 功能数据看板 ----------

    (function featureDataCenter() {

      var botSel = document.getElementById('fd-bot-select');

      var groupSel = document.getElementById('fd-group-select');

      var refreshBtn = document.getElementById('fd-refresh');

      var todayEl = document.getElementById('fd-checkin-today');

      var membersEl = document.getElementById('fd-checkin-members');

      var maxEl = document.getElementById('fd-checkin-max');

      var avgEl = document.getElementById('fd-checkin-avg');

      var tbody = document.getElementById('fd-checkin-tbody');

      if (!todayEl || !membersEl || !tbody) return;

      var cachedBots = [];

      var cachedGroups = [];

      function setText(el, text) {

        if (el) el.textContent = text;

      }

      function renderBotOptions(bots) {

        if (!botSel) return;

        var val = botSel.value || '';

        var opts = '<option value="">全部机器人</option>';

        (bots || []).forEach(function (b) {

          opts += '<option value="' + escapeHtml(b) + '">' + escapeHtml(b) + '</option>';

        });

        botSel.innerHTML = opts;

        if (cachedBots.indexOf(val) !== -1) botSel.value = val;

      }

      function renderGroupOptions(groups) {

        if (!groupSel) return;

        var val = groupSel.value || '';

        var opts = '<option value="">全部群聊</option>';

        (groups || []).forEach(function (g) {

          var label = g.length >= 4 ? ('群 ' + g.slice(-4)) : g;

          opts += '<option value="' + escapeHtml(g) + '">' + escapeHtml(label) + '</option>';

        });

        groupSel.innerHTML = opts;

        if (cachedGroups.indexOf(val) !== -1) groupSel.value = val;

      }

      function renderTable(records) {

        if (!tbody) return;

        if (!records || records.length === 0) {

          tbody.innerHTML = '<tr class="empty-row"><td colspan="8"><div class="empty small"><div class="illu">📭</div><div class="text">暂无数据</div></div></td></tr>';

          return;

        }

        var html = '';

        records.forEach(function (r, idx) {

          html += '<tr>' +

            '<td>' + (idx + 1) + '</td>' +

            '<td>' + escapeHtml(botDisplayName(r.bot || '小流萤')) + '</td>' +

            '<td>' + escapeHtml(r.member_name || r.member_openid || '-') + '</td>' +

            '<td>' + (r.total || 0) + '</td>' +

            '<td>' + (r.continuous || 0) + '</td>' +

            '<td>' + escapeHtml(r.last_date || '-') + '</td>' +

            '<td>' + (r.gold || 0) + '</td>' +

            '<td>' + (r.points || 0) + '</td>' +

            '</tr>';

        });

        tbody.innerHTML = html;

      }

      function render(data) {

        data = data || {};

        setText(todayEl, data.today_checkins || 0);

        setText(membersEl, data.total_members || 0);

        setText(maxEl, data.max_continuous || 0);

        setText(avgEl, data.avg_continuous || 0);

        cachedBots = data.bots || [];

        cachedGroups = data.groups || [];

        renderBotOptions(cachedBots);

        renderGroupOptions(cachedGroups);

        renderTable(data.records || []);

      }

      function fetchCheckinStats() {

        var bot = botSel ? (botSel.value || '') : '';

        var group = groupSel ? (groupSel.value || '') : '';

        var url = API_BASE + '/api/checkin-stats';

        if (bot || group) {

          var params = [];

          if (bot) params.push('bot=' + encodeURIComponent(bot));

          if (group) params.push('group=' + encodeURIComponent(group));

          url += '?' + params.join('&');

        }

        fetch(url)

          .then(function (r) { return r.json(); })

          .then(function (j) {

            if (j && j.ok) render(j);

          })

          .catch(function (e) { console.error('checkin stats error', e); });

      }

      function refresh() {

        if (!refreshBtn) return;

        refreshBtn.classList.add('spin');

        refreshBtn.disabled = true;

        fetchCheckinStats();

        setTimeout(function () {

          refreshBtn.classList.remove('spin');

          refreshBtn.disabled = false;

        }, 500);

      }

      if (refreshBtn) {

        refreshBtn.addEventListener('click', refresh);

      }

      if (botSel) botSel.addEventListener('change', fetchCheckinStats);

      if (groupSel) groupSel.addEventListener('change', fetchCheckinStats);

      loadFeatureDataRef = function () {

        fetchCheckinStats();

      };

    })();

    // ---------- 个性设置 ----------

    (function personalizeCenter() {

      var LS_KEY = 'xiaoliu_admin_bg_v1';

      var DARK_KEY = 'xiaoliu_admin_dark_v1';

      var LAYOUT_SWAP_KEY = 'xiaoliu_admin_layout_swap_v1';

      var DEFAULT_BG = '#f4f6fa';

      var preview = document.getElementById('personalize-preview');

      var colorInput = document.getElementById('personalize-color-input');

      var hexInput = document.getElementById('personalize-hex-input');

      var currentDot = document.getElementById('personalize-current-dot');

      var currentValue = document.getElementById('personalize-current-value');

      var presetsBox = document.getElementById('personalize-presets');

      var applyBtn = document.getElementById('personalize-apply-btn');

      var saveBtn = document.getElementById('personalize-save-btn');

      var resetBtn = document.getElementById('personalize-reset-btn');

      var layoutSwapInput = document.getElementById('personalize-layout-swap');

      var layoutPreview = document.getElementById('personalize-layout-preview');

      var appEl = document.querySelector('.app');

      if (!colorInput) return;

      function isValidHex(v) {

        return /^#([0-9a-fA-F]{6})$/.test(v);

      }

      function normalizeHex(v) {

        v = String(v || '').trim();

        if (!v.startsWith('#')) v = '#' + v;

        v = v.toLowerCase();

        return isValidHex(v) ? v : null;

      }

      function setCssBg(color) {

        document.documentElement.style.setProperty('--bg', color);

      }

      function getCssBg() {

        return getComputedStyle(document.documentElement).getPropertyValue('--bg').trim() || DEFAULT_BG;

      }

      function hexToRgb(hex) {

        return {

          r: parseInt(hex.slice(1, 3), 16),

          g: parseInt(hex.slice(3, 5), 16),

          b: parseInt(hex.slice(5, 7), 16)

        };

      }

      function rgbToHex(r, g, b) {

        return '#' + [r, g, b].map(function (x) {

          var v = Math.max(0, Math.min(255, Math.round(x))).toString(16);

          return v.length === 1 ? '0' + v : v;

        }).join('');

      }

      function mixHex(a, b, weight) {

        // weight: 0 = b, 1 = a

        var ca = hexToRgb(a);

        var cb = hexToRgb(b);

        return rgbToHex(

          ca.r * weight + cb.r * (1 - weight),

          ca.g * weight + cb.g * (1 - weight),

          ca.b * weight + cb.b * (1 - weight)

        );

      }

      function setHarmonizedPalette(base) {

        var root = document.documentElement.style;

        // 深色表面

        root.setProperty('--custom-bg2', mixHex(base, '#252842', 0.25));

        root.setProperty('--custom-sidebar', mixHex(base, '#1e2035', 0.30));

        root.setProperty('--custom-rule', mixHex(base, '#2f324d', 0.22));

        root.setProperty('--custom-border', mixHex(base, '#2f324d', 0.25));

        root.setProperty('--custom-accent-soft', mixHex(base, '#2c3a6b', 0.28));

        root.setProperty('--custom-hover', mixHex(base, '#2c3056', 0.28));

        root.setProperty('--custom-hover-border', mixHex(base, '#3d4060', 0.22));

        root.setProperty('--custom-info-banner', mixHex(base, '#1c274a', 0.25));

        root.setProperty('--custom-table-head', mixHex(base, '#1e2035', 0.32));

        root.setProperty('--custom-flow-canvas', mixHex(base, '#12131f', 0.20));

        root.setProperty('--custom-switch-track', mixHex(base, '#4a4e6e', 0.18));

        // 浅色表面（权重更高，使浅色自定义背景也能明显统一各区域）

        root.setProperty('--custom-bg2-light', mixHex(base, '#ffffff', 0.35));

        root.setProperty('--custom-sidebar-light', mixHex(base, '#ffffff', 0.35));

        root.setProperty('--custom-rule-light', mixHex(base, '#ececf4', 0.45));

        root.setProperty('--custom-border-light', mixHex(base, '#e0e2f0', 0.45));

        root.setProperty('--custom-accent-soft-light', mixHex(base, '#eaf0ff', 0.40));

        root.setProperty('--custom-sidebar-active-light', mixHex(base, '#eaf0ff', 0.40));

        root.setProperty('--custom-hover-light', mixHex(base, '#f5f7fb', 0.45));

        root.setProperty('--custom-hover-border-light', mixHex(base, '#d8d8e6', 0.40));

        root.setProperty('--custom-ghost-border-light', mixHex(base, '#c9cde0', 0.40));

      }

      function clearHarmonizedPalette() {

        var root = document.documentElement.style;

        ['--custom-bg2', '--custom-sidebar', '--custom-rule', '--custom-border', '--custom-accent-soft', '--custom-hover', '--custom-hover-border', '--custom-info-banner', '--custom-table-head', '--custom-flow-canvas', '--custom-switch-track', '--custom-bg2-light', '--custom-sidebar-light', '--custom-rule-light', '--custom-border-light', '--custom-accent-soft-light', '--custom-sidebar-active-light', '--custom-hover-light', '--custom-hover-border-light', '--custom-ghost-border-light'].forEach(function (k) {

          root.removeProperty(k);

        });

      }

      function luminance(hex) {

        var r = parseInt(hex.slice(1, 3), 16) / 255;

        var g = parseInt(hex.slice(3, 5), 16) / 255;

        var b = parseInt(hex.slice(5, 7), 16) / 255;

        return 0.299 * r + 0.587 * g + 0.114 * b;

      }

      function setDarkMode(dark) {

        document.body.classList.toggle('dark-mode', dark);

      }

      function isDarkMode() {

        return document.body.classList.contains('dark-mode');

      }

      function syncDarkMode(color) {

        var dark = luminance(color) < 0.5;

        setDarkMode(dark);

        return dark;

      }

      function updateUi(color, saveToLs) {

        colorInput.value = color;

        hexInput.value = color;

        if (currentDot) currentDot.style.background = color;

        if (currentValue) currentValue.textContent = color;

        if (preview) preview.style.background = color;

        // 高亮对应预设

        if (presetsBox) {

          presetsBox.querySelectorAll('.preset').forEach(function (p) {

            p.classList.toggle('active', p.getAttribute('data-color').toLowerCase() === color.toLowerCase());

          });

        }

        if (saveToLs) {

          try { localStorage.setItem(LS_KEY, color); } catch (e) {}

        }

      }

      function applyPalette(color, dark) {

        if (color === DEFAULT_BG && !dark) clearHarmonizedPalette();

        else setHarmonizedPalette(color);

      }

      function apply(color) {

        var hex = normalizeHex(color);

        if (!hex) { showToast('请输入有效的十六进制颜色，例如 #f4f6fa'); return; }

        setCssBg(hex);

        var dark = syncDarkMode(hex);

        applyPalette(hex, dark);

        updateUi(hex, false);

      }

      function save(color) {

        var hex = normalizeHex(color);

        if (!hex) { showToast('请输入有效的十六进制颜色'); return; }

        setCssBg(hex);

        var dark = syncDarkMode(hex);

        applyPalette(hex, dark);

        updateUi(hex, true);

        try { localStorage.setItem(DARK_KEY, dark ? '1' : '0'); } catch (e) {}

        showToast('背景色已保存');

      }

      function reset() {

        setCssBg(DEFAULT_BG);

        syncDarkMode(DEFAULT_BG);

        clearHarmonizedPalette();

        updateUi(DEFAULT_BG, true);

        try { localStorage.removeItem(DARK_KEY); } catch (e) {}

        showToast('已恢复默认背景色');

      }

      function applyLayoutSwap(on) {

        if (appEl) appEl.classList.toggle('sidebar-right', !!on);

        if (layoutPreview) layoutPreview.classList.toggle('swap', !!on);

        if (layoutSwapInput) layoutSwapInput.checked = !!on;

      }

      function loadLayoutSwap() {

        var saved = false;

        try { saved = localStorage.getItem(LAYOUT_SWAP_KEY) === '1'; } catch (e) {}

        applyLayoutSwap(saved);

      }

      function loadSaved() {

        var saved = DEFAULT_BG;

        try { saved = localStorage.getItem(LS_KEY) || DEFAULT_BG; } catch (e) {}

        if (!isValidHex(saved)) saved = DEFAULT_BG;

        var savedDark = false;

        try { savedDark = localStorage.getItem(DARK_KEY) === '1'; } catch (e) {}

        // 若仅开启深色模式但未设置深色背景，使用默认深色背景

        if (savedDark && saved === DEFAULT_BG) saved = '#1e2035';

        setCssBg(saved);

        var dark = savedDark || (luminance(saved) < 0.5);

        setDarkMode(dark);

        applyPalette(saved, dark);

        updateUi(saved, false);

      }

      if (colorInput) colorInput.addEventListener('input', function () { apply(colorInput.value); });

      if (hexInput) {

        hexInput.addEventListener('input', function () { apply(hexInput.value); });

        hexInput.addEventListener('blur', function () {

          var hex = normalizeHex(hexInput.value);

          if (hex) updateUi(hex, false);

          else hexInput.value = colorInput.value;

        });

      }

      if (applyBtn) applyBtn.addEventListener('click', function () { apply(hexInput.value || colorInput.value); });

      if (saveBtn) saveBtn.addEventListener('click', function () { save(hexInput.value || colorInput.value); });

      if (resetBtn) resetBtn.addEventListener('click', reset);

      if (presetsBox) {

        presetsBox.addEventListener('click', function (e) {

          var p = e.target.closest('.preset');

          if (!p) return;

          var color = p.getAttribute('data-color');

          apply(color);

        });

      }

      // 页面加载时先恢复保存的背景色

      loadSaved();

      // 布局互换开关

      if (layoutSwapInput) {

        layoutSwapInput.addEventListener('change', function () {

          var on = layoutSwapInput.checked;

          applyLayoutSwap(on);

          try { localStorage.setItem(LAYOUT_SWAP_KEY, on ? '1' : '0'); } catch (e) {}

          showToast(on ? '已切换为右侧布局' : '已切换为左侧布局');

        });

      }

      loadLayoutSwap();

      loadPersonalizeRef = function () {

        var current = getCssBg();

        updateUi(current, false);

      };

    })();

    // ===== 管理员中心 =====

    (function () {

      function apiGet(path) {

        return fetch(API_BASE + path, { method: 'GET', cache: 'no-store' })

          .then(function (r) { return r.json(); });

      }

      function apiPost(path, body) {

        return fetch(API_BASE + path, {

          method: 'POST',

          headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify(body || {})

        }).then(function (r) { return r.json(); });

      }

      function toast(msg) {

        var old = document.getElementById('admin-toast');

        if (old) old.remove();

        var div = document.createElement('div');

        div.id = 'admin-toast';

        div.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#333;color:#fff;padding:10px 20px;border-radius:8px;z-index:9999;font-size:13px;';

        div.textContent = msg;

        document.body.appendChild(div);

        setTimeout(function () { div.remove(); }, 2200);

      }

      function esc(s) {

        return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {

          return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];

        });

      }

      // ---------- 管理员设置 ----------

      var adminInput = document.getElementById('admin-input');

      var adminAddBtn = document.getElementById('admin-add-btn');

      var adminTbody = document.getElementById('admin-tbody');

      var adminEmpty = document.getElementById('admin-empty');

      var adminCount = document.getElementById('admin-count');

      function adminType(id) {

        return /^\d+$/.test(String(id).trim()) ? 'QQ 号' : 'openid';

      }

      function renderAdminList(admins) {

        admins = admins || [];

        if (adminCount) adminCount.textContent = '共 ' + admins.length + ' 位';

        if (!adminTbody) return;

        adminTbody.innerHTML = '';

        if (!admins.length) {

          if (adminEmpty) adminEmpty.style.display = 'block';

          return;

        }

        if (adminEmpty) adminEmpty.style.display = 'none';

        admins.forEach(function (id, i) {

          var tr = document.createElement('tr');

          tr.innerHTML =

            '<td class="row-idx">' + (i + 1) + '</td>' +

            '<td class="id-cell">' + esc(id) + '</td>' +

            '<td><span class="type-tag">' + adminType(id) + '</span></td>' +

            '<td><button class="btn btn-danger admin-remove" data-id="' + esc(id) + '">移除</button></td>';

          adminTbody.appendChild(tr);

        });

        adminTbody.querySelectorAll('.admin-remove').forEach(function (btn) {

          btn.addEventListener('click', function () {

            var id = btn.getAttribute('data-id');

            if (!confirm('确定移除管理员「' + id + '」？')) return;

            apiPost('/api/admin/remove', { id: id }).then(function (res) {

              if (res && res.ok) {

                toast(res.message || ('已移除 ' + id));

                renderAdminList(res.admins || []);

              } else {

                toast((res && res.error) || '移除失败');

              }

            }).catch(function () { toast('请求失败'); });

          });

        });

      }

      function loadAdminList() {

        apiGet('/api/admin/list').then(function (res) {

          if (res && res.ok) renderAdminList(res.admins || []);

          else toast('加载管理员名单失败');

        }).catch(function () { toast('无法连接后端'); });

      }

      function doAdd() {

        if (!adminInput) return;

        var id = adminInput.value.trim();

        if (!id) { toast('请输入管理员 ID'); return; }

        apiPost('/api/admin/add', { id: id }).then(function (res) {

          if (res && res.ok) {

            toast(res.message || ('已添加 ' + id));

            renderAdminList(res.admins || []);

            adminInput.value = '';

          } else {

            toast((res && res.error) || '添加失败');

          }

        }).catch(function () { toast('请求失败'); });

      }

      if (adminAddBtn) adminAddBtn.addEventListener('click', doAdd);

      if (adminInput) adminInput.addEventListener('keydown', function (e) {

        if (e.key === 'Enter') doAdd();

      });

      loadAdminSettingsRef = function () { loadAdminList(); };

      // ---------- 系统指令 ----------

      var statusGrid = document.getElementById('admin-status-grid');

      var onlineDot = document.getElementById('admin-online-dot');

      var onlineText = document.getElementById('admin-online-text');

      var uptimeEl = document.getElementById('admin-uptime');

      var statusTimer = null;

      function fmtUptime(sec) {

        sec = Number(sec) || 0;

        if (sec < 0) sec = 0;

        var d = Math.floor(sec / 86400);

        var h = Math.floor((sec % 86400) / 3600);

        var m = Math.floor((sec % 3600) / 60);

        var s = sec % 60;

        function p(n) { return (n < 10 ? '0' : '') + n; }

        if (d > 0) return d + '天 ' + p(h) + ':' + p(m) + ':' + p(s);

        return p(h) + ':' + p(m) + ':' + p(s);

      }

      function row(label, value, hint) {
      var hintHtml = hint ? '<span class="hint">' + esc(hint) + '</span>' : '';
      return '<div class="status-row">' +
        '<span class="label">' + esc(label) + '</span>' +
        '<span class="value">' + esc(value) + hintHtml + '</span>' +
        '</div>';
    }
    function section(title, icon, body) {
      return '<div class="status-section">' +
        '<div class="status-section-head"><span class="status-section-icon">' + icon + '</span><span class="status-section-title">' + esc(title) + '</span></div>' +
        '<div class="status-section-body">' + body + '</div>' +
        '</div>';
    }
    function renderStatus(s) {
      if (!s || !statusGrid) return;
      var ag = s.active_games || {};
      var gameStr = '五子棋 ' + (ag.gomoku || 0) + ' / 成语 ' + (ag.idiom || 0);
      var cpu = s.cpu || {};
      var cpuStr = (cpu.percent != null) ? (cpu.percent + '%') : 'N/A';
      var mem = s.mem;
      var memStr = 'N/A';
      if (mem && mem.percent != null) {
        memStr = mem.percent + '% (' + (mem.used_gb != null ? mem.used_gb : '?') +
          '/' + (mem.total_gb != null ? mem.total_gb : '?') + 'GB)';
      }
      var gpu = s.gpu || {};
      var gpuStr = '无';
      var gpuHint = '';
      if (gpu.available && gpu.devices && gpu.devices.length) {
        gpuStr = gpu.devices.length + ' 块';
        gpuHint = gpu.devices.map(function (d) {
          var seg = [];
          if (d.util_percent != null) seg.push('负载' + d.util_percent + '%');
          if (d.mem_used_mb != null && d.mem_total_mb != null)
            seg.push('显存' + (d.mem_used_mb / 1024).toFixed(1) + '/' + (d.mem_total_mb / 1024).toFixed(1) + 'GB');
          return d.name + (seg.length ? ' ' + seg.join(' ') : '');
        }).join('  |  ');
      }
      // 基础信息
      var baseBody = row('机器人', s.bot_name || '小流萤') +
        row('在线状态', s.online ? '在线' : '离线', s.online ? '●' : '○');
      // 运行统计
      var statsBody = row('消息总数', s.message_count != null ? s.message_count : 0) +
        row('指令次数', s.command_count != null ? s.command_count : 0) +
        row('API 调用', s.api_call_count != null ? s.api_call_count : 0) +
        row('违禁词数', s.banned_word_count != null ? s.banned_word_count : 0);
      // 活跃度
      var activityBody = row('活跃游戏', gameStr) +
        row('活跃会话', s.active_groups != null ? s.active_groups : 0);
      // 系统资源
      var sysBody = row('CPU 占用', cpuStr) +
        row('内存占用', memStr) +
        row('GPU 占用', gpuStr, gpuHint);
      var html = '';
      html += section('基础信息', '🤖', baseBody);
      html += section('运行统计', '📊', statsBody);
      html += section('活跃度', '🎮', activityBody);
      html += section('系统资源', '⚙️', sysBody);
      // 缓冲期倒计时横幅
      var bannerHtml = '';
      if (s.pending_action) {
        var paLabel = s.pending_action === 'restart' ? '重启' : '关机';
        bannerHtml = '<div class="admin-pending-banner">' + paLabel +
          '指令已发送，<b>' + (s.pending_remaining != null ? s.pending_remaining : 0) +
          '</b> 秒后生效…</div>';
      }
      statusGrid.innerHTML = bannerHtml + html;
      if (onlineDot) onlineDot.className = 'admin-status-dot ' + (s.online ? 'online' : 'offline');
      if (onlineText) onlineText.textContent = s.online ? '在线' : '离线';
      if (uptimeEl) uptimeEl.textContent = fmtUptime(s.uptime_seconds);
      // 缓冲期内禁用指令按钮，避免重复触发
      if (cmdRestart) cmdRestart.disabled = !!s.pending_action;
      if (cmdShutdown) cmdShutdown.disabled = !!s.pending_action;
      // 缓冲期内 1 秒轮询显示倒计时，平时 5 秒
      if (statusTimer) {
        clearInterval(statusTimer);
        statusTimer = setInterval(loadStatus, s.pending_action ? 1000 : 5000);
      }
    }

      function loadStatus() {

        apiGet('/api/admin/status').then(function (res) {

          if (res && res.ok) renderStatus(res.status || {});

          else toast('获取状态失败');

        }).catch(function () {

          toast('无法连接后端');

          stopTimer(); // 后端已停止（重启/关机生效），停止轮询避免刷屏

        });

      }

      function stopTimer() {

        if (statusTimer) { clearInterval(statusTimer); statusTimer = null; }

      }

      clearAdminStatusTimer = stopTimer;

      var cmdStatus = document.getElementById('admin-cmd-status');

      var cmdRestart = document.getElementById('admin-cmd-restart');

      var cmdShutdown = document.getElementById('admin-cmd-shutdown');

      var statusRefresh = document.getElementById('admin-status-refresh');

      if (cmdStatus) cmdStatus.addEventListener('click', loadStatus);

      if (statusRefresh) statusRefresh.addEventListener('click', loadStatus);

      if (cmdRestart) cmdRestart.addEventListener('click', function () {

        if (!confirm('确定要重启机器人吗？重启期间服务会短暂中断。')) return;

        apiPost('/api/admin/restart', {}).then(function (res) {

          toast((res && res.message) || '已发送重启指令');

        }).catch(function () { toast('请求失败'); });

      });

      if (cmdShutdown) cmdShutdown.addEventListener('click', function () {

        if (!confirm('确定要关闭机器人吗？关闭后需手动重新启动。')) return;

        apiPost('/api/admin/shutdown', {}).then(function (res) {

          toast((res && res.message) || '已发送关机指令');

        }).catch(function () { toast('请求失败'); });

      });

      loadAdminCommandsRef = function () {

        loadStatus();

        stopTimer();

        statusTimer = setInterval(loadStatus, 5000);

      };

    })();

  })();

  // ============================================================

  // 视频限制配置（视频解析 / 视频系统）

  // ============================================================

  (function videoLimitsConfig() {

    var parseDur = document.getElementById('vl-parse-duration');

    var parseMb = document.getElementById('vl-parse-mb');

    var sysDur = document.getElementById('vl-system-duration');

    var sysMb = document.getElementById('vl-system-mb');

    var saveBtn = document.getElementById('vl-save-btn');

    var resetBtn = document.getElementById('vl-reset-btn');

    if (!parseDur || !saveBtn) return;

    var DEFAULTS = { parse: { max_duration: 1200, max_mb: 0 }, system: { max_duration: 1200, max_mb: 0 } };

    function setConn(bad, msg) {

      var el = document.getElementById('vl-conn-status');

      if (!el) el = document.getElementById('bot-conn-status');

      if (!el) return;

      if (bad) { el.className = 'conn-status conn-fail'; el.textContent = '⚠️ ' + (msg || '无法连接机器人'); }

      else { el.className = 'conn-status conn-ok'; el.textContent = '✅ ' + (msg || '已连接到机器人'); }

    }

    function toast(msg) {

      var old = document.getElementById('vl-toast');

      if (old) old.remove();

      var div = document.createElement('div');

      div.id = 'vl-toast';

      div.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#333;color:#fff;padding:10px 20px;border-radius:8px;z-index:9999;font-size:13px;';

      div.textContent = msg;

      document.body.appendChild(div);

      setTimeout(function () { div.remove(); }, 2000);

    }

    function loadLimits() {

      fetch(API_BASE + '/api/system-config', { cache: 'no-store' })

        .then(function (r) { return r.json(); })

        .then(function (data) {

          var vl = (data && data.video_limits) || {};

          var p = vl.parse || {};

          var s = vl.system || {};

          parseDur.value = Math.round((p.max_duration != null ? p.max_duration : DEFAULTS.parse.max_duration) / 60);

          parseMb.value = p.max_mb != null ? p.max_mb : DEFAULTS.parse.max_mb;

          sysDur.value = Math.round((s.max_duration != null ? s.max_duration : DEFAULTS.system.max_duration) / 60);

          sysMb.value = s.max_mb != null ? s.max_mb : DEFAULTS.system.max_mb;

          setConn(false);

        })

        .catch(function () { setConn(true, '请先启动 bot.py'); });

    }

    function saveLimits() {

      var pDur = parseInt(parseDur.value, 10); if (isNaN(pDur) || pDur < 0) pDur = 0;

      var pMb = parseInt(parseMb.value, 10); if (isNaN(pMb) || pMb < 0) pMb = 0;

      var sDur = parseInt(sysDur.value, 10); if (isNaN(sDur) || sDur < 0) sDur = 0;

      var sMb = parseInt(sysMb.value, 10); if (isNaN(sMb) || sMb < 0) sMb = 0;

      var payload = {

        video_limits: {

          parse: { max_duration: pDur * 60, max_mb: pMb },

          system: { max_duration: sDur * 60, max_mb: sMb }

        }

      };

      setConn(false, '保存中…');

      fetch(API_BASE + '/api/system-config', {

        method: 'POST', headers: { 'Content-Type': 'application/json' },

        body: JSON.stringify(payload)

      })

        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })

        .then(function (data) {

          if (data && data.ok) { toast('视频限制已保存 ✓'); setConn(false); }

          else { toast('保存失败：' + ((data && data.error) || '未知错误')); setConn(true); }

        })

        .catch(function () { toast('⚠️ 保存失败：请确认机器人(bot)正在运行'); setConn(true); });

    }

    function resetDefaults() {

      parseDur.value = DEFAULTS.parse.max_duration / 60;

      parseMb.value = DEFAULTS.parse.max_mb;

      sysDur.value = DEFAULTS.system.max_duration / 60;

      sysMb.value = DEFAULTS.system.max_mb;

    }

    // 进入「视频限制」标签页时加载最新值

    document.querySelectorAll('.feature-tab').forEach(function (tab) {

      tab.addEventListener('click', function () {

        if (tab.getAttribute('data-ftab') === 'video-limits') loadLimits();

      });

    });

    if (saveBtn) saveBtn.addEventListener('click', saveLimits);

    if (resetBtn) resetBtn.addEventListener('click', function () { resetDefaults(); toast('已恢复默认，记得点保存'); });

  })();

  // ============================================================

  // 整点报时（自动）配置

  // ============================================================

  (function chimeConfig() {

    var groupSel = document.getElementById('chime-group-select');

    var enabledEl = document.getElementById('chime-enabled');

    var intervalEl = document.getElementById('chime-interval');

    var periodStartEl = document.getElementById('chime-period-start');

    var periodEndEl = document.getElementById('chime-period-end');

    var lastRunEl = document.getElementById('chime-last-run');

    var saveBtn = document.getElementById('chime-save-btn');

    var resetBtn = document.getElementById('chime-reset-btn');

    var runNowBtn = document.getElementById('chime-run-now');

    if (!enabledEl || !saveBtn || !groupSel) return;

    var DEFAULTS = { enabled: false, interval_hours: 1, period_start: 0, period_end: 23 };

    function setConn(bad, msg) {

      var el = document.getElementById('chime-conn-status');

      if (!el) el = document.getElementById('bot-conn-status');

      if (!el) return;

      if (bad) { el.className = 'conn-status conn-fail'; el.textContent = '⚠️ ' + (msg || '无法连接机器人'); }

      else { el.className = 'conn-status conn-ok'; el.textContent = '✅ ' + (msg || '已连接到机器人'); }

    }

    function toast(msg) {

      var old = document.getElementById('chime-toast');

      if (old) old.remove();

      var div = document.createElement('div');

      div.id = 'chime-toast';

      div.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#333;color:#fff;padding:10px 20px;border-radius:8px;z-index:9999;font-size:13px;';

      div.textContent = msg;

      document.body.appendChild(div);

      setTimeout(function () { div.remove(); }, 2200);

    }

    function fillGroups(groups) {

      var cur = groupSel.value;

      groupSel.innerHTML = '<option value="">— 请选择群 —</option>';

      (groups || []).forEach(function (g) {

        var o = document.createElement('option');

        o.value = g.id;

        var tail = g.openid && g.openid.length >= 4 ? g.openid.slice(-4) : '';

        o.textContent = (g.name || g.id) + (tail ? ' (' + tail + ')' : '');

        groupSel.appendChild(o);

      });

      if (cur) groupSel.value = cur;

    }

    function loadGroups(cb) {

      fetch(API_BASE + '/api/groups?bot=', { cache: 'no-store' })

        .then(function (r) { return r.json(); })

        .then(function (data) {

          var arr = (data && data.items) || [];

          fillGroups(arr);

          if (cb) cb();

        })

        .catch(function () { setConn(true, '请先启动 bot.py'); });

    }

    function loadChime() {

      var gid = groupSel.value;

      if (!gid) {

        setConn(false, '请先选择群');

        lastRunEl.textContent = '—';

        enabledEl.checked = DEFAULTS.enabled;

        intervalEl.value = DEFAULTS.interval_hours;

        periodStartEl.value = DEFAULTS.period_start;

        periodEndEl.value = DEFAULTS.period_end;

        return;

      }

      fetch(API_BASE + '/api/chime-config?group=' + encodeURIComponent(gid), { cache: 'no-store' })

        .then(function (r) { return r.json(); })

        .then(function (data) {

          var c = (data && data.config) || {};

          enabledEl.checked = !!c.enabled;

          intervalEl.value = c.interval_hours != null ? c.interval_hours : DEFAULTS.interval_hours;

          periodStartEl.value = c.period_start != null ? c.period_start : DEFAULTS.period_start;

          periodEndEl.value = c.period_end != null ? c.period_end : DEFAULTS.period_end;

          lastRunEl.textContent = c.last_run ? c.last_run : '—';

          setConn(false);

        })

        .catch(function () { setConn(true, '请先启动 bot.py'); });

    }

    function saveChime() {

      var gid = groupSel.value;

      if (!gid) { toast('请先选择群'); return; }

      var enabled = !!enabledEl.checked;

      var interval = parseInt(intervalEl.value, 10);

      if (isNaN(interval) || interval < 1) interval = 1;

      if (interval > 24) interval = 24;

      intervalEl.value = interval;

      var ps = parseInt(periodStartEl.value, 10);

      if (isNaN(ps) || ps < 0) ps = 0; if (ps > 23) ps = 23;

      var pe = parseInt(periodEndEl.value, 10);

      if (isNaN(pe) || pe < 0) pe = 0; if (pe > 23) pe = 23;

      if (ps > pe) { var t = ps; ps = pe; pe = t; }

      periodStartEl.value = ps; periodEndEl.value = pe;

      var payload = { group_openid: gid, enabled: enabled, interval_hours: interval, period_start: ps, period_end: pe };

      setConn(false, '保存中…');

      fetch(API_BASE + '/api/chime-config', {

        method: 'POST', headers: { 'Content-Type': 'application/json' },

        body: JSON.stringify(payload)

      })

        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })

        .then(function (data) {

          if (data && data.ok) {

            var c = data.config || {};

            lastRunEl.textContent = c.last_run ? c.last_run : '—';

            toast('整点报时配置已保存 ✓'); setConn(false);

          } else { toast('保存失败：' + ((data && data.error) || '未知错误')); setConn(true); }

        })

        .catch(function () { toast('⚠️ 保存失败：请确认机器人(bot)正在运行'); setConn(true); });

    }

    function runNow() {

      var gid = groupSel.value;

      if (!gid) { toast('请先选择群'); return; }

      toast('正在向本群广播整点报时…');

      fetch(API_BASE + '/api/chime-trigger', {

        method: 'POST', headers: { 'Content-Type': 'application/json' },

        body: JSON.stringify({ group_openid: gid })

      })

        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })

        .then(function (data) {

          if (data && data.ok) {

            var res = data.result || {};

            toast('已提交：' + (res.message || '完成') + '（群数 ' + (res.groups || 0) + '）');

          } else { toast('立即报时失败：' + ((data && data.error) || '未知错误')); }

        })

        .catch(function () { toast('⚠️ 立即报时失败：请确认机器人(bot)正在运行'); });

    }

    function resetDefaults() {

      enabledEl.checked = DEFAULTS.enabled;

      intervalEl.value = DEFAULTS.interval_hours;

      periodStartEl.value = DEFAULTS.period_start;

      periodEndEl.value = DEFAULTS.period_end;

    }

    groupSel.addEventListener('change', loadChime);

    // 进入「整点报时」标签页时加载群列表与本群配置

    document.querySelectorAll('.feature-tab').forEach(function (tab) {

      tab.addEventListener('click', function () {

        if (tab.getAttribute('data-ftab') === 'chime') { loadGroups(loadChime); }

      });

    });

    if (saveBtn) saveBtn.addEventListener('click', saveChime);

    if (resetBtn) resetBtn.addEventListener('click', function () { resetDefaults(); toast('已恢复默认，记得点保存'); });

    if (runNowBtn) runNowBtn.addEventListener('click', runNow);

  })();

  // ============================================================

  // 入群通知配置

  // ============================================================

  (function welcomeConfig() {

    var groupSel = document.getElementById('welcome-group-select');

    var enabledEl = document.getElementById('welcome-enabled');

    var msgEl = document.getElementById('welcome-msg');

    var saveBtn = document.getElementById('welcome-save-btn');

    var resetBtn = document.getElementById('welcome-reset-btn');

    if (!enabledEl || !saveBtn || !groupSel) return;

    var DEFAULTS = { welcome_enabled: true, welcome_msg: '' };

    function setConn(bad, msg) {

      var el = document.getElementById('welcome-conn-status');

      if (!el) el = document.getElementById('bot-conn-status');

      if (!el) return;

      if (bad) { el.className = 'conn-status conn-fail'; el.textContent = '⚠️ ' + (msg || '无法连接机器人'); }

      else { el.className = 'conn-status conn-ok'; el.textContent = '✅ ' + (msg || '已连接到机器人'); }

    }

    function toast(msg) {

      var old = document.getElementById('welcome-toast');

      if (old) old.remove();

      var div = document.createElement('div');

      div.id = 'welcome-toast';

      div.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#333;color:#fff;padding:10px 20px;border-radius:8px;z-index:9999;font-size:13px;';

      div.textContent = msg;

      document.body.appendChild(div);

      setTimeout(function () { div.remove(); }, 2200);

    }

    function fillGroups(groups) {

      var cur = groupSel.value;

      groupSel.innerHTML = '<option value="">— 请选择群 —</option>';

      (groups || []).forEach(function (g) {

        var o = document.createElement('option');

        o.value = g.id;

        var tail = g.openid && g.openid.length >= 4 ? g.openid.slice(-4) : '';

        o.textContent = (g.name || g.id) + (tail ? ' (' + tail + ')' : '');

        groupSel.appendChild(o);

      });

      if (cur) groupSel.value = cur;

    }

    function loadGroups(cb) {

      fetch(API_BASE + '/api/groups?bot=', { cache: 'no-store' })

        .then(function (r) { return r.json(); })

        .then(function (data) {

          var arr = (data && data.items) || [];

          fillGroups(arr);

          if (cb) cb();

        })

        .catch(function () { setConn(true, '请先启动 bot.py'); });

    }

    function loadWelcome() {

      var gid = groupSel.value;

      if (!gid) {

        setConn(false, '请先选择群');

        enabledEl.checked = DEFAULTS.welcome_enabled;

        msgEl.value = DEFAULTS.welcome_msg;

        return;

      }

      fetch(API_BASE + '/api/welcome-config?group=' + encodeURIComponent(gid), { cache: 'no-store' })

        .then(function (r) { return r.json(); })

        .then(function (data) {

          var c = (data && data.config) || {};

          enabledEl.checked = !!c.welcome_enabled;

          msgEl.value = c.welcome_msg != null ? c.welcome_msg : DEFAULTS.welcome_msg;

          setConn(false);

        })

        .catch(function () { setConn(true, '请先启动 bot.py'); });

    }

    function saveWelcome() {

      var gid = groupSel.value;

      if (!gid) { toast('请先选择群'); return; }

      var payload = {

        group_openid: gid,

        welcome_enabled: !!enabledEl.checked,

        welcome_msg: (msgEl.value || '').slice(0, 500),

      };

      setConn(false, '保存中…');

      fetch(API_BASE + '/api/welcome-config', {

        method: 'POST', headers: { 'Content-Type': 'application/json' },

        body: JSON.stringify(payload)

      })

        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })

        .then(function (data) {

          if (data && data.ok) {

            var c = data.config || {};

            enabledEl.checked = !!c.welcome_enabled;

            msgEl.value = c.welcome_msg != null ? c.welcome_msg : '';

            toast('入群通知配置已保存 ✓'); setConn(false);

          } else { toast('保存失败：' + ((data && data.error) || '未知错误')); setConn(true); }

        })

        .catch(function () { toast('⚠️ 保存失败：请确认机器人(bot)正在运行'); setConn(true); });

    }

    function resetDefaults() {

      enabledEl.checked = DEFAULTS.welcome_enabled;

      msgEl.value = DEFAULTS.welcome_msg;

    }

    groupSel.addEventListener('change', loadWelcome);

    document.querySelectorAll('.feature-tab').forEach(function (tab) {

      tab.addEventListener('click', function () {

        if (tab.getAttribute('data-ftab') === 'welcome') { loadGroups(loadWelcome); }

      });

    });

    if (saveBtn) saveBtn.addEventListener('click', saveWelcome);

    if (resetBtn) resetBtn.addEventListener('click', function () { resetDefaults(); toast('已恢复默认，记得点保存'); });

  })();

  // ============================================================

  // 签到积分规则配置

  // ============================================================

  (function checkinRulesConfig() {

    var baseEl = document.getElementById('ck-base-points');

    var perEl = document.getElementById('ck-bonus-per-day');

    var capEl = document.getElementById('ck-bonus-cap');

    var costEl = document.getElementById('ck-lottery-cost');

    var saveBtn = document.getElementById('checkin-rules-save-btn');

    var resetBtn = document.getElementById('checkin-rules-reset-btn');

    if (!baseEl || !saveBtn) return;

    var DEFAULTS = { base_points: 10, bonus_per_day: 5, bonus_cap: 200, lottery_cost: 50 };

    function setConn(bad, msg) {

      var el = document.getElementById('checkin-rules-conn-status');

      if (!el) return;

      if (bad) { el.className = 'conn-status conn-fail'; el.textContent = '⚠️ ' + (msg || '无法连接机器人'); }

      else { el.className = 'conn-status conn-ok'; el.textContent = '✅ ' + (msg || '已连接到机器人'); }

    }

    function toast(msg) {

      var old = document.getElementById('checkin-rules-toast');

      if (old) old.remove();

      var div = document.createElement('div');

      div.id = 'checkin-rules-toast';

      div.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#333;color:#fff;padding:10px 20px;border-radius:8px;z-index:9999;font-size:13px;';

      div.textContent = msg;

      document.body.appendChild(div);

      setTimeout(function () { div.remove(); }, 2200);

    }

    function loadRules() {

      fetch(API_BASE + '/api/checkin-config', { cache: 'no-store' })

        .then(function (r) { return r.json(); })

        .then(function (data) {

          var c = (data && data.config) || {};

          baseEl.value = c.base_points != null ? c.base_points : DEFAULTS.base_points;

          perEl.value = c.bonus_per_day != null ? c.bonus_per_day : DEFAULTS.bonus_per_day;

          capEl.value = c.bonus_cap != null ? c.bonus_cap : DEFAULTS.bonus_cap;

          costEl.value = c.lottery_cost != null ? c.lottery_cost : DEFAULTS.lottery_cost;

          setConn(false);

        })

        .catch(function () { setConn(true, '请先启动 bot.py'); });

    }

    function saveRules() {

      var base = parseInt(baseEl.value, 10); if (isNaN(base) || base < 0) base = 0; baseEl.value = base;

      var per = parseInt(perEl.value, 10); if (isNaN(per) || per < 0) per = 0; perEl.value = per;

      var cap = parseInt(capEl.value, 10); if (isNaN(cap) || cap < 0) cap = 0; capEl.value = cap;

      var cost = parseInt(costEl.value, 10); if (isNaN(cost) || cost < 1) cost = 1; costEl.value = cost;

      var payload = { base_points: base, bonus_per_day: per, bonus_cap: cap, lottery_cost: cost };

      setConn(false, '保存中…');

      fetch(API_BASE + '/api/checkin-config', {

        method: 'POST', headers: { 'Content-Type': 'application/json' },

        body: JSON.stringify(payload)

      })

        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })

        .then(function (data) {

          if (data && data.ok) {

            var c = data.config || {};

            baseEl.value = c.base_points; perEl.value = c.bonus_per_day;

            capEl.value = c.bonus_cap; costEl.value = c.lottery_cost;

            toast('签到规则已保存 ✓'); setConn(false);

          } else { toast('保存失败：' + ((data && data.error) || '未知错误')); setConn(true); }

        })

        .catch(function () { toast('⚠️ 保存失败：请确认机器人(bot)正在运行'); setConn(true); });

    }

    function resetDefaults() {

      baseEl.value = DEFAULTS.base_points;

      perEl.value = DEFAULTS.bonus_per_day;

      capEl.value = DEFAULTS.bonus_cap;

      costEl.value = DEFAULTS.lottery_cost;

    }

    // 进入「签到规则」标签页时加载最新值

    document.querySelectorAll('.feature-tab').forEach(function (tab) {

      tab.addEventListener('click', function () {

        if (tab.getAttribute('data-ftab') === 'checkin-rules') { loadRules(); }

      });

    });

    if (saveBtn) saveBtn.addEventListener('click', saveRules);

    if (resetBtn) resetBtn.addEventListener('click', function () { resetDefaults(); toast('已恢复默认，记得点保存'); });

  })();

  // ============================================================
  // 违禁词和禁言管理
  // ============================================================
  (function bannedMuteMgr() {

    var groupSel = document.getElementById('bm-group-select');
    var connStatus = document.getElementById('bm-conn-status');
    var wordsEl = document.getElementById('bm-banned-words');
    var muteOnEl = document.getElementById('bm-mute-on');
    var durEl = document.getElementById('bm-mute-duration');
    var saveBtn = document.getElementById('bm-save-btn');

    if (!groupSel || !wordsEl || !saveBtn) return;

    var DEFAULTS = { banned_words: [], mute_on_banword: true, mute_duration: 600 };

    function setConn(bad, msg) {
      var el = connStatus;
      if (!el) return;
      if (bad) { el.className = 'conn-status conn-fail'; el.textContent = '⚠️ ' + (msg || '无法连接机器人'); }
      else { el.className = 'conn-status conn-ok'; el.textContent = '✅ ' + (msg || '已连接到机器人'); }
    }

    function toast(msg) {
      var old = document.getElementById('bm-toast');
      if (old) old.remove();
      var div = document.createElement('div');
      div.id = 'bm-toast';
      div.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#333;color:#fff;padding:10px 20px;border-radius:8px;z-index:9999;font-size:13px;';
      div.textContent = msg;
      document.body.appendChild(div);
      setTimeout(function () { div.remove(); }, 2200);
    }

    function fillGroups(groups) {
      var cur = groupSel.value;
      groupSel.innerHTML = '<option value="">— 请选择群 —</option>';
      (groups || []).forEach(function (g) {
        var o = document.createElement('option');
        o.value = g.id;
        var tail = g.openid && g.openid.length >= 4 ? g.openid.slice(-4) : '';
        o.textContent = (g.name || g.id) + (tail ? ' (' + tail + ')' : '');
        groupSel.appendChild(o);
      });
      if (cur) groupSel.value = cur;
    }

    function loadGroups(cb) {
      fetch(API_BASE + '/api/groups?bot=', { cache: 'no-store' })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          var arr = (data && data.items) || [];
          fillGroups(arr);
          if (cb) cb();
        })
        .catch(function () { setConn(true, '请先启动 bot.py'); });
    }

    function loadConfig() {
      var gid = groupSel.value;
      if (!gid) {
        setConn(false, '请先选择群');
        wordsEl.value = (DEFAULTS.banned_words || []).join('\n');
        muteOnEl.checked = DEFAULTS.mute_on_banword;
        durEl.value = DEFAULTS.mute_duration;
        return;
      }
      fetch(API_BASE + '/api/group/banned-mute?openid=' + encodeURIComponent(gid), { cache: 'no-store' })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          var c = (data && data.config) || {};
          var words = c.banned_words || [];
          wordsEl.value = words.join('\n');
          muteOnEl.checked = c.mute_on_banword != null ? !!c.mute_on_banword : DEFAULTS.mute_on_banword;
          var d = c.mute_duration != null ? c.mute_duration : DEFAULTS.mute_duration;
          durEl.value = d;
          setConn(false);
        })
        .catch(function () { setConn(true, '请先启动 bot.py'); });
    }

    function saveConfig() {
      var gid = groupSel.value;
      if (!gid) { toast('请先选择群'); return; }
      var words = (wordsEl.value || '').split('\n').map(function (s) { return s.trim(); }).filter(function (s) { return s.length > 0; });
      var dur = parseInt(durEl.value, 10); if (isNaN(dur) || dur < 0) dur = 0; durEl.value = dur;
      var payload = {
        openid: gid,
        banned_words: words,
        mute_duration: dur,
        mute_on_banword: !!muteOnEl.checked
      };
      setConn(false, '保存中…');
      fetch(API_BASE + '/api/group/banned-mute', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(function (data) {
          if (data && data.ok) {
            var c = data.config || {};
            wordsEl.value = (c.banned_words || []).join('\n');
            muteOnEl.checked = !!c.mute_on_banword;
            durEl.value = c.mute_duration != null ? c.mute_duration : dur;
            toast('违禁词和禁言配置已保存 ✓'); setConn(false);
          } else { toast('保存失败：' + ((data && data.error) || '未知错误')); setConn(true); }
        })
        .catch(function () { toast('⚠️ 保存失败：请确认机器人(bot)正在运行'); setConn(true); });
    }

    groupSel.addEventListener('change', loadConfig);

    document.querySelectorAll('.feature-tab').forEach(function (tab) {
      tab.addEventListener('click', function () {
        if (tab.getAttribute('data-ftab') === 'banned-mute') { loadGroups(loadConfig); }
      });
    });

    if (saveBtn) saveBtn.addEventListener('click', saveConfig);

  })();

  (function banwordLogMgr() {

    var groupSel = document.getElementById('bwl-group-select');
    var listEl = document.getElementById('bwl-list');
    var connStatus = document.getElementById('bwl-conn-status');
    var refreshBtn = document.getElementById('bwl-refresh-btn');
    var clearBtn = document.getElementById('bwl-clear-btn');

    if (!groupSel || !listEl) return;

    function setConn(bad, msg) {
      var el = connStatus;
      if (!el) return;
      if (bad) { el.className = 'conn-status conn-fail'; el.textContent = '⚠️ ' + (msg || '无法连接机器人'); }
      else { el.className = 'conn-status conn-ok'; el.textContent = '✅ ' + (msg || '已连接到机器人'); }
    }

    function toast(msg) {
      var old = document.getElementById('bwl-toast');
      if (old) old.remove();
      var div = document.createElement('div');
      div.id = 'bwl-toast';
      div.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#333;color:#fff;padding:10px 20px;border-radius:8px;z-index:9999;font-size:13px;';
      div.textContent = msg;
      document.body.appendChild(div);
      setTimeout(function () { div.remove(); }, 2200);
    }

    function fillGroups(groups) {
      var cur = groupSel.value;
      groupSel.innerHTML = '<option value="">全部群</option>';
      (groups || []).forEach(function (g) {
        var o = document.createElement('option');
        o.value = g.id;
        var tail = g.openid && g.openid.length >= 4 ? g.openid.slice(-4) : '';
        o.textContent = (g.name || g.id) + (tail ? ' (' + tail + ')' : '');
        groupSel.appendChild(o);
      });
      if (cur) groupSel.value = cur;
    }

    function loadGroups(cb) {
      fetch(API_BASE + '/api/groups?bot=', { cache: 'no-store' })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          var arr = (data && data.items) || [];
          fillGroups(arr);
          if (cb) cb();
        })
        .catch(function () { setConn(true, '请先启动 bot.py'); });
    }

    function esc(s) {
      return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
      });
    }

    function render(logs) {
      if (!logs || !logs.length) {
        listEl.innerHTML = '<div style="padding:18px;text-align:center;color:var(--muted);">暂无拦截记录</div>';
        return;
      }
      var html = '';
      logs.forEach(function (it) {
        var acts = [];
        if (it.recalled) acts.push('撤回');
        if (it.muted) acts.push('禁言' + (it.mute_duration ? ' ' + it.mute_duration + 's' : ''));
        var actStr = acts.length ? acts.join(' · ') : '命中';
        var m = it.member_openid || '';
        var mask = m.length > 6 ? m.slice(0, 6) + '…' : (m || '未知');
        html += '<div style="border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin-bottom:8px;font-size:13px;">'
          + '<div style="display:flex;justify-content:space-between;gap:12px;">'
          + '<span style="color:var(--muted);">' + esc(it.ts) + '</span>'
          + '<span style="color:#ef4444;font-weight:600;">' + esc(actStr) + '</span>'
          + '</div>'
          + '<div style="margin-top:4px;">群：' + esc(it.group_openid || '未知') + ' ｜ 用户：' + esc(mask) + '</div>'
          + (it.word ? '<div style="margin-top:2px;color:var(--muted);">命中词：' + esc(it.word) + '</div>' : '')
          + '</div>';
      });
      listEl.innerHTML = html;
    }

    function loadLog() {
      var gid = groupSel.value;
      var url = API_BASE + '/api/group/banword-log?limit=300' + (gid ? '&openid=' + encodeURIComponent(gid) : '');
      fetch(url, { cache: 'no-store' })
        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(function (data) {
          render(data.logs || []);
          setConn(false, '共 ' + (data.logs || []).length + ' 条拦截记录');
        })
        .catch(function () { setConn(true, '请先启动 bot.py'); });
    }

    function clearLog() {
      if (!confirm('确定要清空违禁词拦截日志吗？')) return;
      var gid = groupSel.value;
      var payload = { clear: true };
      if (gid) payload.openid = gid;
      fetch(API_BASE + '/api/group/banword-log', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(function (data) {
          if (data && data.ok) { toast('已清空日志 ✓'); loadLog(); }
          else { toast('清空失败：' + ((data && data.error) || '未知错误')); }
        })
        .catch(function () { toast('⚠️ 清空失败：请确认机器人(bot)正在运行'); });
    }

    groupSel.addEventListener('change', loadLog);

    if (refreshBtn) refreshBtn.addEventListener('click', loadLog);
    if (clearBtn) clearBtn.addEventListener('click', clearLog);

    document.querySelectorAll('.feature-tab').forEach(function (tab) {
      tab.addEventListener('click', function () {
        if (tab.getAttribute('data-ftab') === 'banword-log') { loadGroups(loadLog); if (window.experienceGroupLinkCenter) window.experienceGroupLinkCenter.load(); }
      });
    });

  })();

  // ============================================================

  // 体验群加入链接（违禁词拦截日志右侧卡片，保存后热加载生效）

  // ============================================================

  (function experienceGroupLinkCenter() {
    var input = document.getElementById('eg-url-input');
    var saveBtn = document.getElementById('eg-url-save-btn');
    var statusEl = document.getElementById('eg-url-status');
    var openLink = document.getElementById('eg-url-open');
    if (!input || !saveBtn) return;
    function setStatus(msg, ok) {
      if (!statusEl) return;
      statusEl.style.display = 'inline';
      statusEl.textContent = msg;
      statusEl.style.color = ok ? 'var(--ok, #3a9)' : 'var(--danger, #e55)';
    }
    function refreshLink(url) {
      if (!openLink) return;
      var u = (url || '').trim();
      if (!u) {
        openLink.style.display = 'none';
        openLink.removeAttribute('href');
      } else {
        openLink.style.display = 'inline-flex';
        openLink.setAttribute('href', u);
      }
    }
    function load() {
      fetch(API_BASE + '/api/runtime-settings?scope=global', { cache: 'no-store' })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          if (!j.ok) { setStatus('加载失败', false); return; }
          var found = null;
          (j.keys || []).forEach(function (k) { if (k.key === 'experience_group.url') found = k; });
          var v = found ? (found.value == null ? '' : found.value) : '';
          input.value = v;
          refreshLink(v);
        })
        .catch(function () { setStatus('加载失败：请确认机器人(bot)运行中', false); });
    }
    saveBtn.addEventListener('click', function () {
      var v = input.value.trim();
      saveBtn.disabled = true;
      fetch(API_BASE + '/api/runtime-settings', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'save', key: 'experience_group.url', value: v, scope: 'global' })
      })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          if (j && j.ok) {
            setStatus('已保存并热加载 ✓', true);
            refreshLink(v);
          }
          else { setStatus('保存失败：' + ((j && j.error) || '未知错误'), false); }
        })
        .catch(function () { setStatus('保存失败：请确认机器人(bot)运行中', false); })
        .then(function () { saveBtn.disabled = false; });
    });
    if (input) input.addEventListener('input', function () { refreshLink(input.value); });
    window.experienceGroupLinkCenter = { load: load, refreshLink: refreshLink };
  })();

  // ============================================================

  // 内存管理 / 缓存清理

  // ============================================================

  (function cacheCenter() {

    var refreshBtn = document.getElementById('cache-refresh-btn');

    var listEl = document.getElementById('cache-list');

    var totalSizeEl = document.getElementById('cache-total-size');

    var totalFilesEl = document.getElementById('cache-total-files');

    var selectedSizeEl = document.getElementById('cache-selected-size');

    var selectedCountEl = document.getElementById('cache-selected-count');

    var lastRunEl = document.getElementById('cache-last-run');

    var lastRunSubEl = document.getElementById('cache-last-run-sub');

    var schedStateEl = document.getElementById('cache-sched-state');

    var schedSubEl = document.getElementById('cache-sched-sub');

    var listSummaryEl = document.getElementById('cache-list-summary');

    var footSummaryEl = document.getElementById('cache-foot-summary');

    var cleanBtn = document.getElementById('cache-clean-btn');

    var selectAllBtn = document.getElementById('cache-select-all');

    var selectNoneBtn = document.getElementById('cache-select-none');

    var selectInvertBtn = document.getElementById('cache-select-invert');

    var selectEmptyBtn = document.getElementById('cache-select-empty');

    var schedEnabled = document.getElementById('cache-sched-enabled');

    var schedSchedule = document.getElementById('cache-sched-schedule');

    var schedHour = document.getElementById('cache-sched-hour');

    var schedItems = document.getElementById('cache-sched-items');

    var schedSaveBtn = document.getElementById('cache-sched-save');

    var schedRunNowBtn = document.getElementById('cache-sched-run-now');

    var schedLastRunEl = document.getElementById('cache-sched-last-run');

    var schedEnabledOverview = document.getElementById('cache-sched-enabled-overview');

    var schedWeekday = document.getElementById('cache-sched-weekday');

    var schedWeekdayRow = document.getElementById('cache-sched-weekday-row');

    var schedMonthday = document.getElementById('cache-sched-monthday');

    var schedMonthdayRow = document.getElementById('cache-sched-monthday-row');

    var schedMinute = document.getElementById('cache-sched-minute');

    var schedMaxage = document.getElementById('cache-sched-maxage');

    var schedNextRunEl = document.getElementById('cache-sched-next-run');

    if (!listEl) return;

    var currentItems = [];  // 当前 stats 列表

    var currentConfig = null;

    // 字节格式化（与后端保持一致）

    function fmtSize(n) {

      n = parseInt(n, 10) || 0;

      if (n < 1024) return n + ' B';

      if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';

      if (n < 1024 * 1024 * 1024) return (n / 1024 / 1024).toFixed(2) + ' MB';

      return (n / 1024 / 1024 / 1024).toFixed(2) + ' GB';

    }

    function toast(msg) {

      var old = document.getElementById('cache-toast');

      if (old) old.remove();

      var div = document.createElement('div');

      div.id = 'cache-toast';

      div.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#333;color:#fff;padding:10px 20px;border-radius:8px;z-index:9999;font-size:13px;max-width:80vw;text-align:center;';

      div.textContent = msg;

      document.body.appendChild(div);

      setTimeout(function () { div.remove(); }, 3000);

    }

    function iconFor(key) {

      var m = {

        'botpy_log': { c: 'warn', e: '📄' },

        'bot_log': { c: 'warn', e: '📄' },

        'bot_stdout_log': { c: 'warn', e: '📄' },

        'bot_stderr_log': { c: 'warn', e: '📄' },

        'data_logs': { c: 'purple', e: '📑' },

        'novel_cache': { c: '', e: '🖼️' },

        'admin_media': { c: 'green', e: '🎬' },

        'pycache': { c: 'purple', e: '⚙️' },

      };

      var v = m[key] || { c: '', e: '🗂️' };

      return '<div class="ico ' + v.c + '">' + v.e + '</div>';

    }

    function renderList() {

      if (!currentItems || !currentItems.length) {

        listEl.innerHTML = '<div style="padding:32px;text-align:center;color:var(--muted);">暂无缓存数据，请刷新</div>';

        return;

      }

      var rows = currentItems.map(function (it) {

        var sizeHtml = it.size_bytes > 0

          ? '<div class="size">' + fmtSize(it.size_bytes) + '<span class="files">' + it.file_count + ' 个文件</span></div>'

          : '<div class="size empty">空</div>';

        return '<div class="cache-item" data-key="' + escapeHtml(it.key) + '">' +

          '<label class="ck"><input type="checkbox" class="cache-item-ck" data-key="' + escapeHtml(it.key) + '"' +

            (it.size_bytes > 0 ? '' : ' disabled') + ' /></label>' +

          iconFor(it.key) +

          '<div class="info"><div class="label">' + escapeHtml(it.label) + '</div>' +

            '<div class="desc">' + escapeHtml(it.description || '') + '</div></div>' +

          sizeHtml +

          '<div></div>' +

        '</div>';

      }).join('');

      listEl.innerHTML = rows;

      // 绑定勾选

      listEl.querySelectorAll('.cache-item-ck').forEach(function (cb) {

        cb.addEventListener('change', updateSelectedSummary);

      });

      updateSelectedSummary();

    }

    function updateSelectedSummary() {

      var cks = listEl.querySelectorAll('.cache-item-ck');

      var selSize = 0;

      var selCount = 0;

      var nonEmptyCount = 0;

      cks.forEach(function (cb) {

        var key = cb.getAttribute('data-key');

        var it = currentItems.find(function (x) { return x.key === key; });

        if (it && it.size_bytes > 0) nonEmptyCount++;

        if (cb.checked && it) {

          selSize += it.size_bytes;

          selCount++;

        }

      });

      selectedSizeEl.textContent = fmtSize(selSize);

      selectedCountEl.textContent = selCount + ' 项';

      if (listSummaryEl) listSummaryEl.textContent = '（共 ' + currentItems.length + ' 项 / ' + nonEmptyCount + ' 项非空）';

      if (footSummaryEl) footSummaryEl.textContent = '已选 ' + selCount + ' / ' + nonEmptyCount + ' 项非空，预计释放 ' + fmtSize(selSize);

    }

    function loadStats(cb) {

      listEl.innerHTML = '<div style="padding:32px;text-align:center;color:var(--muted);">加载中…</div>';

      fetch(API_BASE + '/api/cache-stats', { cache: 'no-store' })

        .then(function (r) {

          if (!r.ok) throw new Error('HTTP ' + r.status);

          return r.json();

        })

        .then(function (data) {

          if (!data || !data.ok) throw new Error((data && data.error) || '返回异常');

          currentItems = data.items || [];

          if (totalSizeEl) totalSizeEl.textContent = data.total_size_human || '0 B';

          if (totalFilesEl) totalFilesEl.textContent = data.total_files + ' 个文件';

          renderList();

          if (typeof cb === 'function') cb();

        })

        .catch(function (e) {

          listEl.innerHTML = '<div style="padding:32px;text-align:center;color:#ef4444;">加载失败：' + escapeHtml(e.message) + '</div>';

        });

    }

    function loadConfig() {

      return fetch(API_BASE + '/api/cache-clean-config', { cache: 'no-store' })

        .then(function (r) { return r.json(); })

        .then(function (data) {

          if (data && data.ok && data.config) {

            currentConfig = data.config;

            applyConfigToUI();

            updateSchedSummary();

          }

        })

        .catch(function () { /* 静默 */ });

    }

    function updateScheduleRowVisibility() {

      var sc = (schedSchedule && schedSchedule.value) || (currentConfig && currentConfig.schedule) || 'daily';

      if (schedWeekdayRow) schedWeekdayRow.style.display = (sc === 'weekly') ? '' : 'none';

      if (schedMonthdayRow) schedMonthdayRow.style.display = (sc === 'monthly') ? '' : 'none';

    }

    function applyConfigToUI() {

      if (!currentConfig) return;

      if (schedEnabled) schedEnabled.checked = !!currentConfig.enabled;

      if (schedSchedule) schedSchedule.value = currentConfig.schedule || 'daily';

      if (schedHour) schedHour.value = String(currentConfig.hour != null ? currentConfig.hour : 3);

      if (schedWeekday) schedWeekday.value = String(currentConfig.weekday != null ? currentConfig.weekday : 0);

      if (schedMonthday) schedMonthday.value = String(currentConfig.month_day != null ? currentConfig.month_day : 1);

      if (schedMinute) schedMinute.value = String(currentConfig.minute != null ? currentConfig.minute : 0);

      if (schedMaxage) schedMaxage.value = String(currentConfig.max_age_days != null ? currentConfig.max_age_days : 0);

      if (schedEnabledOverview) schedEnabledOverview.checked = !!currentConfig.enabled;

      updateScheduleRowVisibility();

    }

    function updateSchedSummary() {

      if (!currentConfig) return;

      if (schedStateEl) {

        schedStateEl.textContent = currentConfig.enabled ? '已启用' : '关闭';

        schedStateEl.style.color = currentConfig.enabled ? '#059669' : 'var(--muted)';

      }

      if (schedSubEl) {

        if (currentConfig.enabled) {

          var hour = currentConfig.hour != null ? currentConfig.hour : 3;

          var minute = currentConfig.minute != null ? currentConfig.minute : 0;

          var wd = currentConfig.weekday != null ? currentConfig.weekday : 0;

          var md = currentConfig.month_day != null ? currentConfig.month_day : 1;

          var wlist = ['一', '二', '三', '四', '五', '六', '日'];

          var schedMap = { daily: '每天', weekly: '每周' + wlist[wd], monthly: '每月 ' + md + ' 号' };

          schedSubEl.textContent = (schedMap[currentConfig.schedule] || '每天') + ' ' + String(hour).padStart(2, '0') + ':' + String(minute).padStart(2, '0');

        } else {

          schedSubEl.textContent = '未启用';

        }

      }

      if (schedNextRunEl) {

        if (currentConfig.enabled && currentConfig.next_run) {

          schedNextRunEl.textContent = '下次执行：' + currentConfig.next_run;

        } else if (currentConfig.enabled) {

          schedNextRunEl.textContent = '下次执行：—';

        } else {

          schedNextRunEl.textContent = '下次执行：未启用';

        }

      }

      if (schedLastRunEl) {

        if (currentConfig.last_run) {

          schedLastRunEl.textContent = '上次自动清理：' + currentConfig.last_run;

        } else {

          schedLastRunEl.textContent = '尚未自动清理过';

        }

      }

      if (lastRunEl && currentConfig.last_run) {

        lastRunEl.textContent = currentConfig.last_run;

        lastRunSubEl.textContent = '系统已自动清理过';

      } else if (lastRunEl) {

        lastRunEl.textContent = '—';

        lastRunSubEl.textContent = '尚未清理过';

      }

    }

    function renderSchedItems() {

      if (!schedItems || !currentItems || !currentItems.length) {

        // 用 default 渲染（即使 stats 还没来）

        return;

      }

      var sel = (currentConfig && currentConfig.items) || [];

      schedItems.innerHTML = currentItems.map(function (it) {

        var checked = sel.indexOf(it.key) >= 0;

        return '<label class="opt"><input type="checkbox" class="cache-sched-ck" data-key="' + escapeHtml(it.key) + '"' +

          (checked ? ' checked' : '') + ' />' +

          escapeHtml(it.label) + ' <span class="muted" style="font-size:11.5px;">(' + fmtSize(it.size_bytes) + ')</span></label>';

      }).join('');

    }

    function getSelectedItems() {

      var cks = listEl.querySelectorAll('.cache-item-ck');

      var out = [];

      cks.forEach(function (cb) {

        if (cb.checked) out.push(cb.getAttribute('data-key'));

      });

      return out;

    }

    function doClean() {

      var items = getSelectedItems();

      if (!items.length) {

        toast('请先勾选要清理的项');

        return;

      }

      var labels = items.map(function (k) {

        var it = currentItems.find(function (x) { return x.key === k; });

        return it ? it.label : k;

      });

      if (!window.confirm('确定清理以下 ' + items.length + ' 项？\n\n· ' + labels.join('\n· ') + '\n\n该操作不可撤销（但仅清理白名单内缓存/日志文件，不会影响数据）。')) {

        return;

      }

      if (cleanBtn) cleanBtn.disabled = true;

      toast('清理中…');

      fetch(API_BASE + '/api/cache-clean', {

        method: 'POST', headers: { 'Content-Type': 'application/json' },

        body: JSON.stringify({ items: items })

      })

        .then(function (r) {

          if (!r.ok) return r.text().then(function (t) { throw new Error('HTTP ' + r.status + ' · ' + t.slice(0, 120)); });

          return r.json();

        })

        .then(function (data) {

          if (!data || !data.ok) throw new Error((data && data.error) || '清理失败');

          toast('✅ 已清理 ' + (data.deleted_files || 0) + ' 个文件，释放 ' + (data.freed_human || '0 B'));

          // 刷新 stats

          loadStats(function () { loadConfig(); });

        })

        .catch(function (e) {

          toast('❌ 清理失败：' + e.message);

        })

        .then(function () {

          if (cleanBtn) cleanBtn.disabled = false;

        });

    }

    function saveConfig() {

      if (!currentConfig) currentConfig = { enabled: false, schedule: 'daily', hour: 3, weekday: 0, month_day: 1, minute: 0, max_age_days: 0, items: [], last_run: '' };

      var enabled = !!(schedEnabled && schedEnabled.checked);

      var schedule = (schedSchedule && schedSchedule.value) || 'daily';

      var hour = parseInt((schedHour && schedHour.value) || '3', 10);

      if (isNaN(hour) || hour < 0) hour = 0;

      if (hour > 23) hour = 23;

      var weekday = parseInt((schedWeekday && schedWeekday.value) || '0', 10);

      if (isNaN(weekday) || weekday < 0) weekday = 0;

      if (weekday > 6) weekday = 6;

      var monthDay = parseInt((schedMonthday && schedMonthday.value) || '1', 10);

      if (isNaN(monthDay) || monthDay < 1) monthDay = 1;

      if (monthDay > 28) monthDay = 28;

      var minute = parseInt((schedMinute && schedMinute.value) || '0', 10);

      if (isNaN(minute) || minute < 0) minute = 0;

      if (minute > 59) minute = 59;

      var maxAge = parseInt((schedMaxage && schedMaxage.value) || '0', 10);

      if (isNaN(maxAge) || maxAge < 0) maxAge = 0;

      if (maxAge > 365) maxAge = 365;

      var items = [];

      if (schedItems) {

        schedItems.querySelectorAll('.cache-sched-ck').forEach(function (cb) {

          if (cb.checked) items.push(cb.getAttribute('data-key'));

        });

      }

      var payload = { enabled: enabled, schedule: schedule, hour: hour, weekday: weekday, month_day: monthDay, minute: minute, max_age_days: maxAge, items: items };

      if (schedSaveBtn) schedSaveBtn.disabled = true;

      fetch(API_BASE + '/api/cache-clean-config', {

        method: 'POST', headers: { 'Content-Type': 'application/json' },

        body: JSON.stringify(payload)

      })

        .then(function (r) {

          if (!r.ok) return r.text().then(function (t) { throw new Error('HTTP ' + r.status + ' · ' + t.slice(0, 120)); });

          return r.json();

        })

        .then(function (data) {

          if (!data || !data.ok) throw new Error((data && data.error) || '保存失败');

          currentConfig = data.config;

          applyConfigToUI();

          updateSchedSummary();

          toast('✅ 配置已保存');

        })

        .catch(function (e) {

          toast('❌ 保存失败：' + e.message);

        })

        .then(function () {

          if (schedSaveBtn) schedSaveBtn.disabled = false;

        });

    }

    function runScheduleNow() {

      if (!currentConfig) {

        toast('请先保存配置');

        return;

      }

      if (!currentConfig.items || !currentConfig.items.length) {

        toast('定时清理项为空，请先勾选并保存');

        return;

      }

      if (!window.confirm('立即按当前定时清理配置执行？\n\n将清理：' + currentConfig.items.join(', ') + '\n\n该操作不可撤销。')) {

        return;

      }

      if (schedRunNowBtn) schedRunNowBtn.disabled = true;

      toast('执行中…');

      fetch(API_BASE + '/api/cache-clean', {

        method: 'POST', headers: { 'Content-Type': 'application/json' },

        body: JSON.stringify({ items: currentConfig.items, max_age_days: currentConfig.max_age_days || 0 })

      })

        .then(function (r) {

          if (!r.ok) return r.text().then(function (t) { throw new Error('HTTP ' + r.status + ' · ' + t.slice(0, 120)); });

          return r.json();

        })

        .then(function (data) {

          if (!data || !data.ok) throw new Error((data && data.error) || '执行失败');

          toast('✅ 已执行：' + (data.freed_human || '0 B') + ' / ' + (data.deleted_files || 0) + ' 个文件');

          // 同步 last_run 到 UI（虽然后端定时调度器才会写 last_run，但这里假装）

          if (lastRunEl) {

            lastRunEl.textContent = new Date().toLocaleString('zh-CN', { hour12: false });

            lastRunSubEl.textContent = '刚刚手动触发';

          }

          loadStats(function () { loadConfig(); });

        })

        .catch(function (e) {

          toast('❌ 执行失败：' + e.message);

        })

        .then(function () {

          if (schedRunNowBtn) schedRunNowBtn.disabled = false;

        });

    }

    // 初始化 0-23 时刻下拉

    if (schedHour && !schedHour.options.length) {

      for (var h = 0; h < 24; h++) {

        var op = document.createElement('option');

        op.value = String(h);

        op.textContent = String(h).padStart(2, '0');

        schedHour.appendChild(op);

      }

      schedHour.value = '3';

    }

    // 初始化 0-59 分钟下拉

    if (schedMinute && !schedMinute.options.length) {

      for (var mi = 0; mi < 60; mi++) {

        var om = document.createElement('option');

        om.value = String(mi);

        om.textContent = String(mi).padStart(2, '0');

        schedMinute.appendChild(om);

      }

      schedMinute.value = '0';

    }

    // 初始化 1-28 日期下拉

    if (schedMonthday && !schedMonthday.options.length) {

      for (var dm = 1; dm <= 28; dm++) {

        var od = document.createElement('option');

        od.value = String(dm);

        od.textContent = String(dm);

        schedMonthday.appendChild(od);

      }

      schedMonthday.value = '1';

    }

    // 事件

    if (refreshBtn) refreshBtn.addEventListener('click', function () { loadStats(); loadConfig(); });

    if (cleanBtn) cleanBtn.addEventListener('click', doClean);

    if (selectAllBtn) selectAllBtn.addEventListener('click', function () {

      listEl.querySelectorAll('.cache-item-ck:not(:disabled)').forEach(function (cb) { cb.checked = true; });

      updateSelectedSummary();

    });

    if (selectNoneBtn) selectNoneBtn.addEventListener('click', function () {

      listEl.querySelectorAll('.cache-item-ck').forEach(function (cb) { cb.checked = false; });

      updateSelectedSummary();

    });

    if (selectInvertBtn) selectInvertBtn.addEventListener('click', function () {

      listEl.querySelectorAll('.cache-item-ck:not(:disabled)').forEach(function (cb) { cb.checked = !cb.checked; });

      updateSelectedSummary();

    });

    if (selectEmptyBtn) selectEmptyBtn.addEventListener('click', function () {

      listEl.querySelectorAll('.cache-item-ck').forEach(function (cb) {

        cb.checked = cb.disabled ? false : true;

      });

      updateSelectedSummary();

    });

    if (schedSaveBtn) schedSaveBtn.addEventListener('click', saveConfig);

    if (schedRunNowBtn) schedRunNowBtn.addEventListener('click', runScheduleNow);

    if (schedSchedule) schedSchedule.addEventListener('change', updateScheduleRowVisibility);

    if (schedEnabled) schedEnabled.addEventListener('change', function () {

      if (schedEnabledOverview) schedEnabledOverview.checked = schedEnabled.checked;

    });

    if (schedEnabledOverview) schedEnabledOverview.addEventListener('change', function () {

      if (schedEnabled) schedEnabled.checked = schedEnabledOverview.checked;

    });

    // 初次加载：先拉 config 再拉 stats（stats 渲染后才能渲染 sched items）

    loadConfig().then(function () {

      loadStats(function () { renderSchedItems(); });

    });

    // 暴露给外部（如其他模块在清理后主动刷新）

    window.__cacheCenter = { loadStats: loadStats, loadConfig: loadConfig };

  })();

  // ============================================================

  // 备份中心（data/ + 关键配置打包为 ZIP，便于框架升级 / 迁移）

  // ============================================================

  (function backupCenter() {
    var listEl = document.getElementById('backup-list');
    var createBtn = document.getElementById('backup-create-btn');
    var refreshBtn = document.getElementById('backup-refresh-btn');
    if (!listEl || !createBtn) return;

    function esc(s) {
      return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
      });
    }

    function render(backups) {
      if (!backups || !backups.length) {
        listEl.innerHTML = '<div style="padding:18px;text-align:center;color:var(--muted);">暂无备份，点击「创建备份」生成第一个。</div>';
        return;
      }
      var html = '';
      backups.forEach(function (b) {
        html += '<div style="display:flex;justify-content:space-between;align-items:center;padding:12px 14px;border:1px solid var(--border);border-radius:10px;margin-bottom:10px;gap:12px;">' +
          '<div style="min-width:0;">' +
            '<div style="font-weight:600;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + esc(b.name) + '</div>' +
            '<div style="font-size:12px;color:var(--muted);margin-top:3px;">' + esc(b.created) + ' · ' + esc(b.size_human) + '</div>' +
          '</div>' +
          '<div style="display:flex;gap:8px;flex:none;">' +
            '<a class="btn btn-ghost" href="' + API_BASE + '/api/backup?action=download&name=' + encodeURIComponent(b.name) + '" target="_blank" rel="noopener">⬇ 下载</a>' +
            '<button class="btn btn-ghost" data-del="' + esc(b.name) + '" type="button">🗑 删除</button>' +
          '</div>' +
        '</div>';
      });
      listEl.innerHTML = html;
      Array.prototype.forEach.call(listEl.querySelectorAll('[data-del]'), function (btn) {
        btn.addEventListener('click', function () {
          var name = btn.getAttribute('data-del');
          if (!confirm('确定删除备份 ' + name + ' 吗？此操作不可恢复。')) return;
          deleteBackup(name);
        });
      });
    }

    function load() {
      fetch(API_BASE + '/api/backup?action=list', { cache: 'no-store' })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          if (!j.ok) { render([]); return; }
          render(j.backups || []);
        })
        .catch(function () { render([]); });
    }

    function createBackup() {
      createBtn.disabled = true;
      createBtn.textContent = '⏳ 打包中…';
      fetch(API_BASE + '/api/backup', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'create' })
      })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          if (j && j.ok) { load(); }
          else { alert('创建失败：' + ((j && j.error) || '未知错误')); }
        })
        .catch(function () { alert('创建失败：请确认机器人(bot)运行中'); })
        .then(function () { createBtn.disabled = false; createBtn.textContent = '➕ 创建备份'; });
    }

    function deleteBackup(name) {
      fetch(API_BASE + '/api/backup', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'delete', name: name })
      })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          if (j && j.ok) { load(); }
          else { alert('删除失败：' + ((j && j.error) || '未知错误')); }
        })
        .catch(function () { alert('删除失败：请确认机器人(bot)运行中'); });
    }

    if (createBtn) createBtn.addEventListener('click', createBackup);
    if (refreshBtn) refreshBtn.addEventListener('click', load);

    window.__backupCenter = { load: load };
  })();

  // ============================================================

  // 运行健康（bot_health 指标看板）

  // ============================================================

  (function healthCenter() {

    var pageEl = document.getElementById('page-health');

    if (!pageEl) return;

    var refreshBtn = document.getElementById('health-refresh-btn');

    var pauseBtn = document.getElementById('health-pause-btn');

    var lastUpdateEl = document.getElementById('health-last-update');

    var wsStatusEl = document.getElementById('health-ws-status');

    var uptimeEl = document.getElementById('health-uptime');

    var cmdEl = document.getElementById('health-cmd');

    var cmdDetailEl = document.getElementById('health-cmd-detail');

    var eventEl = document.getElementById('health-event');

    var dedupEl = document.getElementById('health-dedup');

    var aiEl = document.getElementById('health-ai');

    var aiDetailEl = document.getElementById('health-ai-detail');

    var circuitEl = document.getElementById('health-circuit');

    var circuitDetailEl = document.getElementById('health-circuit-detail');

    var pluginTimeoutEl = document.getElementById('health-plugin-timeout');

    var pipelineThresholdEl = document.getElementById('health-pipeline-threshold');

    var botsBody = document.getElementById('health-bots-body');

    var pluginsBody = document.getElementById('health-plugins-body');

    var pipelineBody = document.getElementById('health-pipeline-body');

    var circuitBody = document.getElementById('health-circuit-body');



    var PIPELINE_ORDER = ["message-fetch", "pre-process", "dispatch-log", "dispatch", "dispatch-respond", "produce-respond", "ai-think", "respond", "send"];

    var botNames = {};

    var paused = false;

    var timer = null;



    function fmtUptime(s) {

      s = Math.floor(Number(s) || 0);

      if (s < 60) return s + ' 秒';

      if (s < 3600) return Math.floor(s / 60) + ' 分 ' + (s % 60) + ' 秒';

      var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);

      return h + ' 时 ' + m + ' 分';

    }

    function resolveName(appid) {

      if (appid === '_shared') return '共享/未归属';

      if (botNames[appid]) return botNames[appid];

      return appid;

    }

    function collectAppids(d) {

      var set = {};

      function add(map) { if (map) Object.keys(map).forEach(function (k) { set[k] = 1; }); }

      add(d.metrics.command); add(d.metrics.event); add(d.metrics.dedup);

      add(d.ai); add(d.plugins); add(d.pipeline_stages); add(d.circuit_breaker);

      return Object.keys(set);

    }

    function emptyRow(colspan, msg) {

      return '<tr class="empty-row"><td colspan="' + colspan + '"><div class="empty">'

        + escapeHtml(msg || '暂无数据') + '</div></td></tr>';

    }



    function loadBotNames() {

      fetch(API_BASE + '/api/bots')

        .then(function (r) { return r.json(); })

        .then(function (j) {

          (j.bots || []).forEach(function (b) {

            var id = String(b.appid || '');

            if (id) botNames[id] = b.name_rt || b.name || id;

          });

        })

        .catch(function () {});

    }



    function loadHealth() {

      if (paused) return;

      if (!pageEl.classList.contains('active')) return;

      fetch(API_BASE + '/api/health', { cache: 'no-store' })

        .then(function (r) { return r.json(); })

        .then(function (d) {

          if (lastUpdateEl) lastUpdateEl.textContent = '更新于 ' + new Date().toLocaleTimeString();

          render(d);

        })

        .catch(function () {});

    }



    function render(d) {

      if (!d || !d.metrics) return;

      var m = d.metrics;

      var ws = m.ws || {};

      var online = !!ws.online;

      if (wsStatusEl) {

        wsStatusEl.textContent = online ? '🟢 已连接' : '🔴 已断开';

        wsStatusEl.style.color = online ? '#1f9d55' : '#d33';

      }

      if (uptimeEl) uptimeEl.textContent = '运行时长 ' + fmtUptime(d.uptime_s) + ' · 连接 ' + (ws.connect || 0) + ' / 断开 ' + (ws.disconnect || 0);



      var cg = 0, cc = 0;

      Object.keys(m.command || {}).forEach(function (a) { cg += (m.command[a].group || 0); cc += (m.command[a].c2c || 0); });

      if (cmdEl) cmdEl.textContent = (cg + cc);

      if (cmdDetailEl) cmdDetailEl.textContent = '群 ' + cg + ' · 私聊 ' + cc;



      var ev = 0; Object.keys(m.event || {}).forEach(function (a) { ev += (m.event[a] || 0); });

      if (eventEl) eventEl.textContent = ev;



      var dd = 0; Object.keys(m.dedup || {}).forEach(function (a) { dd += (m.dedup[a] || 0); });

      if (dedupEl) dedupEl.textContent = dd;



      var ac = 0, af = 0, at = 0;

      Object.keys(d.ai || {}).forEach(function (a) { ac += (d.ai[a].count || 0); af += (d.ai[a].fail || 0); at += (d.ai[a].timeout || 0); });

      if (aiEl) aiEl.textContent = ac;

      if (aiDetailEl) aiDetailEl.textContent = '失败 ' + af + ' · 超时 ' + at;



      var anyOpen = false;

      Object.keys(d.circuit_breaker || {}).forEach(function (a) { if ((d.circuit_breaker[a].state || '') === 'open') anyOpen = true; });

      if (circuitEl) {

        circuitEl.textContent = anyOpen ? '⚠️ 开启(异常)' : '🟢 闭合(正常)';

        circuitEl.style.color = anyOpen ? '#d33' : '#1f9d55';

      }

      if (circuitDetailEl) circuitDetailEl.textContent = '连续失败≥' + 5 + ' 或 窗口失败率>0.5 即开启';



      if (pluginTimeoutEl) {

        var ltp = d.last_timeout_plugin || {};

        var ltpStr = Object.keys(ltp).map(function (a) { return resolveName(a) + ':' + ltp[a]; }).join(' , ');

        pluginTimeoutEl.textContent = '超时阈值 ' + (d.plugin_timeout_ms || 0) + 'ms'

          + (ltpStr ? ' · 最近超时 ' + ltpStr : '');

      }

      if (pipelineThresholdEl) pipelineThresholdEl.textContent = '慢阈值 ' + (d.pipeline_threshold_ms || 0) + 'ms';



      // 各 Bot 指标

      var appids = collectAppids(d);

      if (botsBody) {

        if (!appids.length) {

          botsBody.innerHTML = emptyRow(7, '暂无机器人运行数据');

        } else {

          botsBody.innerHTML = appids.map(function (a) {

            var cmd = (m.command || {})[a] || { group: 0, c2c: 0 };

            var evv = (m.event || {})[a] || 0;

            var ddv = (m.dedup || {})[a] || 0;

            var ai = (d.ai || {})[a] || { count: 0, fail: 0 };

            return '<tr><td>' + escapeHtml(resolveName(a)) + '</td><td>' + cmd.group + '</td><td>' + cmd.c2c

              + '</td><td>' + evv + '</td><td>' + ddv + '</td><td>' + ai.count + '</td><td>' + ai.fail + '</td></tr>';

          }).join('');

        }

      }



      // 插件执行统计

      if (pluginsBody) {

        var pRows = [];

        Object.keys(d.plugins || {}).forEach(function (a) {

          var pmap = d.plugins[a];

          Object.keys(pmap).forEach(function (name) {

            var st = pmap[name];

            pRows.push({ a: a, name: name, st: st });

          });

        });

        pRows.sort(function (x, y) { return (y.st.count || 0) - (x.st.count || 0); });

        if (!pRows.length) {

          pluginsBody.innerHTML = emptyRow(8, '暂无插件执行记录');

        } else {

          pluginsBody.innerHTML = pRows.map(function (r) {

            var st = r.st;

            return '<tr><td>' + escapeHtml(resolveName(r.a)) + '</td><td>' + escapeHtml(r.name)

              + '</td><td>' + (st.count || 0) + '</td><td>' + (st.avg_ms || 0) + '</td><td>' + (st.max_ms || 0)

              + '</td><td>' + (st.slow || 0) + '</td><td>' + (st.timeout || 0) + '</td><td>' + (st.error || 0) + '</td></tr>';

          }).join('');

        }

      }



      // Pipeline 阶段耗时

      if (pipelineBody) {

        var plRows = [];

        Object.keys(d.pipeline_stages || {}).forEach(function (a) {

          var pmap = d.pipeline_stages[a];

          Object.keys(pmap).forEach(function (stage) {

            plRows.push({ a: a, stage: stage, st: pmap[stage] });

          });

        });

        plRows.sort(function (x, y) {

          var ix = PIPELINE_ORDER.indexOf(x.stage), iy = PIPELINE_ORDER.indexOf(y.stage);

          if (ix < 0) ix = 99; if (iy < 0) iy = 99;

          return ix - iy;

        });

        if (!plRows.length) {

          pipelineBody.innerHTML = emptyRow(6, '暂无 Pipeline 计时');

        } else {

          pipelineBody.innerHTML = plRows.map(function (r) {

            var st = r.st;

            return '<tr><td>' + escapeHtml(resolveName(r.a)) + '</td><td>' + escapeHtml(r.stage)

              + '</td><td>' + (st.count || 0) + '</td><td>' + (st.avg_ms || 0) + '</td><td>' + (st.max_ms || 0)

              + '</td><td>' + (st.slow || 0) + '</td></tr>';

          }).join('');

        }

      }



      // 电路熔断

      if (circuitBody) {

        var cbs = Object.keys(d.circuit_breaker || {});

        if (!cbs.length) {

          circuitBody.innerHTML = emptyRow(5, '暂无电路状态');

        } else {

          circuitBody.innerHTML = cbs.map(function (a) {

            var cb = d.circuit_breaker[a];

            var open = (cb.state || '') === 'open';

            var stateHtml = '<span style="color:' + (open ? '#d33' : '#1f9d55') + ';font-weight:600;">'

              + escapeHtml(cb.state || 'closed') + '</span>';

            return '<tr><td>' + escapeHtml(resolveName(a)) + '</td><td>' + stateHtml

              + '</td><td>' + (cb.consecutive_fail || 0) + '</td><td>' + (cb.fail_ratio || 0)

              + '</td><td>' + (cb.window_size || 0) + '</td></tr>';

          }).join('');

        }

      }

    }



    function start() {

      loadBotNames();

      loadHealth();

      if (timer) return;

      timer = setInterval(loadHealth, 3000);

    }

    function stop() {

      if (timer) { clearInterval(timer); timer = null; }

    }



    if (refreshBtn) refreshBtn.addEventListener('click', function () { loadHealth(); });

    if (pauseBtn) pauseBtn.addEventListener('click', function () {

      paused = !paused;

      pauseBtn.textContent = paused ? '▶ 继续' : '⏸ 暂停';

      if (!paused) loadHealth();

    });



    // 页面隐藏/显示时控制轮询（仅在运行健康页激活时拉取）

    window.healthCenter = { start: start, stop: stop, load: loadHealth };

    // 启动轮询（loadHealth 内部会判断页面是否激活）

    // ============================================================

    // 运行设置中心（全局 / 机器人 / 群 三层作用域 KV）

    // ============================================================

    (function runtimeSettingsCenter() {

      var pageEl = document.getElementById('page-runtime-settings');

      if (!pageEl) return;

      var scopeSel = document.getElementById('rt-scope');

      var idField = document.getElementById('rt-id-field');

      var idInput = document.getElementById('rt-id');

      var idLabel = document.getElementById('rt-id-label');

      var scopeHint = document.getElementById('rt-scope-hint');

      var connEl = document.getElementById('rt-conn-status');

      var bodyEl = document.getElementById('runtime-settings-body');

      var saveBtn = document.getElementById('rt-save-btn');

      var resetAllBtn = document.getElementById('rt-reset-all-btn');

      var reloadBtn = document.getElementById('rt-reload-btn');

      var timer = null;

      var pollMs = 5000;

      var lastKeys = [];



      function curScope() { return scopeSel.value; }

      function curId() { return (curScope() === 'global') ? '' : (idInput.value || '').trim(); }



      function showStatus(msg, cls) {

        if (!connEl) return;

        connEl.className = 'conn-status ' + (cls || 'conn-unknown');

        connEl.textContent = msg;

      }



      function ctrlId(key) { return 'rt-ctrl-' + key.replace(/\./g, '_'); }



      function ctrlHtml(k) {

        var id = ctrlId(k.key);

        if (k.type === 'bool') {

          return '<label class="switch"><input type="checkbox" id="' + id + '"><span class="slider"></span></label>';

        }

        if (k.type === 'int') {

          return '<input type="number" id="' + id + '" class="input rt-input">';

        }

        return '<input type="text" id="' + id + '" class="input rt-input">';

      }



      function renderKeys(keys, overrides) {

        bodyEl.innerHTML = '';

        keys.forEach(function (k) {

          var changed = overrides && Object.prototype.hasOwnProperty.call(overrides, k.key);

          var effStr = (k.type === 'bool') ? (k.effective ? '开启' : '关闭') : String(k.effective);

          var row = document.createElement('div');

          row.className = 'rt-row';

          row.innerHTML =

            '<div class="rt-row-main">' +

              '<div class="rt-row-label">' + escapeHtml(k.label) + ' <span class="rt-tag">' + escapeHtml(k.type) + '</span>' +

                (changed ? ' <span class="rt-changed" title="本作用域已覆盖">已覆盖</span>' : '') + '</div>' +

              '<div class="rt-row-desc">' + escapeHtml(k.desc) + '</div>' +

              '<div class="rt-row-eff">当前生效：<b>' + escapeHtml(effStr) + '</b></div>' +

            '</div>' +

            '<div class="rt-row-ctrl">' +

              ctrlHtml(k) +

              '<button class="btn btn-ghost rt-reset-one" data-key="' + escapeHtml(k.key) + '" type="button" title="清除本作用域的覆盖">重置</button>' +

            '</div>';

          bodyEl.appendChild(row);

          var ctrl = document.getElementById(ctrlId(k.key));

          if (k.type === 'bool') {

            ctrl.checked = !!k.value;

          } else {

            ctrl.value = (k.value === '' || k.value === null || k.value === undefined) ? '' : k.value;

          }

        });

      }



      function load() {

        var scope = curScope(), id = curId();

        showStatus('正在加载运行设置…', 'conn-unknown');

        fetch(API_BASE + '/api/runtime-settings?scope=' + encodeURIComponent(scope) + '&id=' + encodeURIComponent(id))

          .then(function (r) { return r.json(); })

          .then(function (j) {

            if (!j.ok) { showStatus('加载失败：' + (j.error || '未知错误'), 'conn-err'); return; }

            lastKeys = j.keys || [];

            renderKeys(j.keys, j.overrides);

            if (scope === 'global') {

              scopeHint.textContent = '全局默认（所有机器人 / 群继承）';

            } else if (id) {

              scopeHint.textContent = '已针对 ' + scope + '：' + id + ' 设置覆盖';

            } else {

              scopeHint.textContent = '请填写 ' + (scope === 'bot' ? '机器人 appid' : '群 openid');

            }

            showStatus('已加载 ' + j.keys.length + ' 项（作用域：' + scope + (id ? ' / ' + id : '') + '）', 'conn-ok');

          })

          .catch(function (e) { showStatus('加载异常：' + e, 'conn-err'); });

      }



      function collectValues() {

        var rows = Array.prototype.slice.call(bodyEl.querySelectorAll('.rt-row'));

        var out = [];

        rows.forEach(function (row) {

          var key = row.querySelector('.rt-reset-one').getAttribute('data-key');

          var ctrl = row.querySelector('.switch input') || row.querySelector('.rt-input');

          var val;

          if (ctrl.type === 'checkbox') val = ctrl.checked;

          else if (ctrl.type === 'number') val = (ctrl.value === '' ? '' : Number(ctrl.value));

          else val = ctrl.value;

          out.push({ key: key, value: val });

        });

        return out;

      }



      function save() {

        var scope = curScope(), id = curId();

        if (scope !== 'global' && !id) { showStatus('请先填写 ' + (scope === 'bot' ? '机器人 appid' : '群 openid'), 'conn-err'); return; }

        var rawVals = collectValues();

        var vals = [];

        rawVals.forEach(function (p) {

          var k = null;

          for (var _i = 0; _i < lastKeys.length; _i++) { if (lastKeys[_i].key === p.key) { k = lastKeys[_i]; break; } }

          var eff = k ? k.effective : null;

          // 仅保存与当前生效值不同的键，避免把默认值也写成覆盖

          if (JSON.stringify(p.value) !== JSON.stringify(eff)) vals.push(p);

        });

        if (!vals.length) { showStatus('没有需要保存的变更', 'conn-ok'); return; }

        showStatus('正在保存…', 'conn-unknown');

        var chain = Promise.resolve();

        vals.forEach(function (p) {

          chain = chain.then(function () {

            return fetch(API_BASE + '/api/runtime-settings', {

              method: 'POST',

              headers: { 'Content-Type': 'application/json' },

              body: JSON.stringify({ action: 'save', scope: scope, id: id, key: p.key, value: p.value })

            }).then(function (r) { return r.json(); });

          });

        });

        chain.then(function () {

          showStatus('已保存 ' + vals.length + ' 项到 ' + scope + (id ? ' / ' + id : ''), 'conn-ok');

          load();

        }).catch(function (e) { showStatus('保存失败：' + e, 'conn-err'); });

      }



      function resetAll() {

        var scope = curScope(), id = curId();

        if (scope !== 'global' && !id) { showStatus('请先填写 ' + (scope === 'bot' ? '机器人 appid' : '群 openid'), 'conn-err'); return; }

        fetch(API_BASE + '/api/runtime-settings', {

          method: 'POST', headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify({ action: 'reset-all', scope: scope, id: id })

        }).then(function (r) { return r.json(); }).then(function () { showStatus('已重置本作用域', 'conn-ok'); load(); });

      }



      function resetOne(key) {

        var scope = curScope(), id = curId();

        if (scope !== 'global' && !id) { showStatus('请先填写 ' + (scope === 'bot' ? '机器人 appid' : '群 openid'), 'conn-err'); return; }

        fetch(API_BASE + '/api/runtime-settings', {

          method: 'POST', headers: { 'Content-Type': 'application/json' },

          body: JSON.stringify({ action: 'reset', scope: scope, id: id, key: key })

        }).then(function (r) { return r.json(); }).then(function () { showStatus('已重置：' + key, 'conn-ok'); load(); });

      }



      scopeSel.addEventListener('change', function () {

        var s = curScope();

        idField.style.display = (s === 'global') ? 'none' : '';

        idLabel.textContent = (s === 'bot') ? '机器人 appid' : '群 openid';

        load();

      });

      idInput.addEventListener('blur', load);

      if (saveBtn) saveBtn.addEventListener('click', save);

      if (resetAllBtn) resetAllBtn.addEventListener('click', resetAll);

      if (reloadBtn) reloadBtn.addEventListener('click', load);

      bodyEl.addEventListener('click', function (e) {

        var btn = e.target.closest('.rt-reset-one');

        if (btn) resetOne(btn.getAttribute('data-key'));

      });



      function start() {

        // 读取控制台刷新间隔作为轮询周期

        fetch(API_BASE + '/api/runtime-settings?scope=global&id=')

          .then(function (r) { return r.json(); }).then(function (j) {

            if (j.ok) {

              var f = (j.keys || []).filter(function (k) { return k.key === 'console.refresh_interval_ms'; })[0];

              if (f && f.effective) pollMs = Math.max(1000, parseInt(f.effective, 10) || 5000);

            }

          }).catch(function () {});

        load();

        if (timer) return;

        timer = setInterval(function () {

          if (pageEl.classList.contains('active')) load();

        }, pollMs);

      }

      function stop() { if (timer) { clearInterval(timer); timer = null; } }

      window.runtimeSettingsCenter = { start: start, stop: stop, load: load };

      start();

    })();



    start();

  })();

})();

