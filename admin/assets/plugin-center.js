/* ============================================================
 *  小流萤 bot · 插件中心（重写版）
 *  - 完全独立的渲染模块：替换 charts.js 里散落的 pluginCenter IIFE
 *  - 区分错误原因：网络超时 / 被墙 / 404 / 解析失败 / 后端挂
 *  - 默认仓库从 config.yaml 读（plugin_market.repo_url / branch / subdir）
 *  - 暴露两个全局函数供 index.html 切换页时调用：
 *      XFY_PC_renderConfig()  : 渲染「插件配置」页
 *      XFY_PC_renderMarket()  : 渲染「插件市场」页
 * ============================================================ */
(function () {
  "use strict";

  if (typeof window === "undefined") return;

  var API_BASE = (typeof window.API_BASE === "string" && window.API_BASE) || "http://127.0.0.1:9988";
  var configBody = null;
  var marketBody = null;
  var lastConfigData = null;
  var lastMarketData = null;
  var _metaCache = {};   // {plugin_key: {display_name, description, priority, aliases, param_hint}}

  // ============== 通用工具 ==============
  function $(id) { return document.getElementById(id); }
  function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function showToast(msg, kind) {
    var old = $("xfy-pc-toast");
    if (old) old.remove();
    var div = document.createElement("div");
    div.id = "xfy-pc-toast";
    var bg = kind === "error" ? "#e74c3c" : (kind === "warn" ? "#f39c12" : "#333");
    div.style.cssText = "position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:" + bg + ";color:#fff;padding:10px 22px;border-radius:8px;z-index:100000;font-size:13px;box-shadow:0 6px 24px rgba(0,0,0,.18);max-width:80vw;";
    div.textContent = msg;
    document.body.appendChild(div);
    setTimeout(function () { if (div.parentNode) div.remove(); }, 2600);
  }

  function fetchJson(url, options) {
    options = options || {};
    var timeoutMs = (typeof options.timeout === "number") ? options.timeout : 8000;
    var retryOnAbort = (options.retryOnAbort === false) ? false : true;
    function doFetch() {
      // 自带 AbortController + 超时：不依赖 charts.js 的全局 window.fetch patch
      var controller = (typeof AbortController === "function") ? new AbortController() : null;
      var timer = null;
      var init = Object.assign({ cache: "no-store" }, options, {});
      delete init.timeout;
      delete init.retryOnAbort;
      if (controller) {
        init.signal = controller.signal;
        timer = setTimeout(function () { try { controller.abort(); } catch (e) {} }, timeoutMs);
      }
      return fetch(API_BASE + url, init)
        .then(function (r) {
          if (timer) clearTimeout(timer);
          if (!r.ok) {
            var err = new Error("HTTP " + r.status);
            err.status = r.status;
            err.code = classifyHttpError(r.status);
            throw err;
          }
          return r.json();
        })
        .catch(function (e) {
          if (timer) clearTimeout(timer);
          // 显式超时：抛 timeout 错（不带 retryOnAbort）
          if (controller && e && e.name === "AbortError") {
            var te = new Error("请求超时（" + timeoutMs + "ms）");
            te.code = "network_timeout";
            te.isTimeout = true;
            throw te;
          }
          throw e;
        });
    }
    return doFetch().catch(function (e) {
      // 页面切换造成的 AbortError 才会重试；显式 timeout 不重试
      if (retryOnAbort && e && (e.name === "AbortError" || /aborted/i.test(e.message || ""))) {
        return new Promise(function (resolve) {
          setTimeout(function () {
            doFetch().then(resolve).catch(function (e2) {
              var err = new Error(e2 && e2.message || "请求失败");
              err.code = e2 && e2.code || "backend_down";
              throw err;
            });
          }, 200);
        });
      }
      // 网络层错误（连接被拒、跨域等）= 后端挂了
      if (!e.status && !e.code) e.code = "backend_down";
      throw e;
    });
  }

  // ============== 插件元数据（_meta） ==============
  function _metaOf(key) {
    if (!key) return null;
    return _metaCache[key] || null;
  }
  function _displayNameOf(p) {
    var m = _metaOf(p.key);
    if (m && m.display_name) return m.display_name;
    return p.name || p.key || "";
  }
  function _descriptionOf(p) {
    var m = _metaOf(p.key);
    if (m && m.description) return m.description;
    return p.description || "";
  }
  function _aliasesToText(arr) {
    if (!arr) return "";
    if (Array.isArray(arr)) return arr.join("、");
    return String(arr);
  }
  function loadAllMetas() {
    return fetchJson("/api/plugins/meta?all=1", { timeout: 5000, retryOnAbort: true })
      .then(function (r) {
        if (r && r.ok && r.metas) {
          _metaCache = r.metas || {};
        }
        return r;
      })
      .catch(function () { return null; });
  }

  // ============== 错误文案（按 code） ==============
  var ERROR_GUIDE = {
    network_timeout: {
      title: "远程仓库响应超时",
      hint: "已自动尝试多镜像回退，仍超时。",
      action: "可改用 jsDelivr CDN：<br><code>https://cdn.jsdelivr.net/gh/GS240186/firefiy-QQofficial-bot-piugins@main/</code>"
    },
    network_dns: {
      title: "DNS 解析失败",
      hint: "无法解析仓库域名，请检查网络。",
      action: "若已配置代理，可切换到 jsDelivr / fastly.jsdelivr.net 镜像。"
    },
    network_refused: {
      title: "远程拒绝连接",
      hint: "仓库地址可能错误或被防火墙拦截。",
      action: "请检查「运行设置 → 插件市场」中的仓库地址。"
    },
    http_404: {
      title: "远程仓库未找到 index.json",
      hint: "返回 404，仓库地址或子目录配置有误。",
      action: "请确认仓库存在且 index.json 位于根目录或指定子目录下。"
    },
    http_5xx: {
      title: "远程仓库服务端错误",
      hint: "GitHub 或 CDN 当前不可用。",
      action: "请稍后重试，或切换到其他镜像。"
    },
    parse: {
      title: "index.json 解析失败",
      hint: "远程返回的不是合法 JSON。",
      action: "请确认 index.json 格式正确，或联系仓库作者。"
    },
    network_other: {
      title: "网络异常",
      hint: "无法连接远程仓库。",
      action: "请检查网络或稍后重试。"
    },
    backend_down: {
      title: "无法连接 bot 后端",
      hint: "请确认 bot 正在运行且监听 " + API_BASE + "。",
      action: "在「运行健康」页检查 bot 状态，或重启 bot。"
    },
    backend_error: {
      title: "bot 后端内部错误",
      hint: "后端处理请求时抛出异常。",
      action: "请稍后重试；若持续出现，查看 bot 日志（botpy.log / 控制台）。"
    },
    http_500: {
      title: "bot 后端返回 500",
      hint: "后端处理请求时出错。",
      action: "请稍后重试或查看 bot 日志。"
    },
  };

  function classifyHttpError(status) {
    if (status === 0 || !status) return "backend_down";
    if (status === 500) return "http_500";
    if (status === 404) return "http_404";
    if (status === 403) return "network_refused";
    if (status >= 500) return "http_5xx";
    return "backend_error";
  }

  function renderErrorBox(container, code, message, source) {
    var g = ERROR_GUIDE[code] || ERROR_GUIDE.network_other;
    var sourceTag = source === "cache_stale"
      ? '<span class="pc-source-tag pc-source-stale">陈旧缓存</span>'
      : (source === "cache" ? '<span class="pc-source-tag">本地缓存</span>' : "");
    container.innerHTML =
      '<div class="pc-error">' +
        '<div class="pc-error-icon">⚠️</div>' +
        '<div class="pc-error-body">' +
          '<div class="pc-error-title">' + escapeHtml(g.title) + ' ' + sourceTag + '</div>' +
          '<div class="pc-error-msg">' + escapeHtml(message || g.hint) + '</div>' +
          '<div class="pc-error-hint">' + g.hint + '</div>' +
          '<div class="pc-error-action">' + g.action + '</div>' +
        '</div>' +
        '<div class="pc-error-actions">' +
          '<button class="pc-btn pc-btn-primary" data-pc-action="retry">🔄 重试</button>' +
          '<button class="pc-btn" data-pc-action="open-settings">⚙️ 仓库设置</button>' +
        '</div>' +
      '</div>';
    // 绑定按钮
    var retry = container.querySelector('[data-pc-action="retry"]');
    if (retry) retry.addEventListener("click", function () {
      if (container === marketBody) XFY_PC_renderMarket(true);
    });
    var settings = container.querySelector('[data-pc-action="open-settings"]');
    if (settings) settings.addEventListener("click", function () {
      openRepoSettings();
    });
  }

  // ============== 仓库设置弹窗 ==============
  function openRepoSettings() {
    fetchJson("/api/plugins/market/repo")
      .then(function (j) {
        if (!j || !j.ok) {
          showToast("读取仓库配置失败", "error");
          return;
        }
        showRepoModal(j);
      })
      .catch(function () {
        showToast("无法连接 bot 后端", "error");
      });
  }

  function showRepoModal(info) {
    var old = $("xfy-pc-repo-modal");
    if (old) old.remove();
    var def = (info && info.default) || {};
    var eff = (info && info.effective) || {};
    var html =
      '<div class="pc-modal-mask" id="xfy-pc-repo-modal">' +
        '<div class="pc-modal">' +
          '<div class="pc-modal-head">' +
            '<h3>插件仓库设置</h3>' +
            '<button class="pc-modal-close" data-pc-modal-close>×</button>' +
          '</div>' +
          '<div class="pc-modal-body">' +
            '<div class="pc-form-row">' +
              '<label>仓库 URL</label>' +
              '<input id="pc-repo-url" type="text" placeholder="https://github.com/OWNER/REPO 或 jsDelivr" value="' + escapeHtml(eff.repo_url || "") + '">' +
              '<div class="pc-form-hint">支持 GitHub 完整 URL、jsDelivr CDN（推荐国内使用）；自动尝试多镜像回退。</div>' +
            '</div>' +
            '<div class="pc-form-row">' +
              '<label>index.json 子目录</label>' +
              '<input id="pc-repo-subdir" type="text" placeholder="留空表示根目录" value="' + escapeHtml(eff.subdir || "") + '">' +
            '</div>' +
            '<details class="pc-form-details">' +
              '<summary>默认值（来自 config.yaml）</summary>' +
              '<div class="pc-form-default">' +
                'URL：<code>' + escapeHtml(def.repo_url || "") + '</code><br>' +
                '分支：<code>' + escapeHtml(def.branch || "") + '</code><br>' +
                '子目录：<code>' + escapeHtml(def.subdir || "") + '</code>' +
              '</div>' +
            '</details>' +
            '<details class="pc-form-details">' +
              '<summary>拉取失败时怎么填</summary>' +
              '<pre class="pc-form-mirror">' + escapeHtml((info && info.mirror_hint) || "") + '</pre>' +
            '</details>' +
          '</div>' +
          '<div class="pc-modal-foot">' +
            '<button class="pc-btn" data-pc-modal-close>取消</button>' +
            '<button class="pc-btn pc-btn-primary" id="pc-repo-save">保存</button>' +
            '<button class="pc-btn" id="pc-repo-reset">恢复默认</button>' +
          '</div>' +
        '</div>' +
      '</div>';
    var wrap = document.createElement("div");
    wrap.innerHTML = html;
    document.body.appendChild(wrap.firstChild);
    bindModalClose();
    $("pc-repo-save").addEventListener("click", function () {
      var url = ($("pc-repo-url").value || "").trim();
      var subdir = ($("pc-repo-subdir").value || "").trim();
      fetchJson("/api/plugins/market/repo/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_url: url, subdir: subdir })
      })
        .then(function (j) {
          if (j && j.ok) {
            showToast("仓库已更新");
            closeModal();
            XFY_PC_renderMarket(true);
          } else {
            showToast("更新失败：" + (j && j.error), "error");
          }
        })
        .catch(function (e) {
          showToast("请求失败：" + (e && e.message), "error");
        });
    });
    $("pc-repo-reset").addEventListener("click", function () {
      fetchJson("/api/plugins/market/repo/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_url: "", subdir: "" })
      })
        .then(function (j) {
          if (j && j.ok) {
            showToast("已恢复默认");
            closeModal();
            XFY_PC_renderMarket(true);
          }
        });
    });
  }
  function bindModalClose() {
    var modal = $("xfy-pc-repo-modal");
    if (!modal) return;
    modal.querySelectorAll("[data-pc-modal-close]").forEach(function (b) {
      b.addEventListener("click", closeModal);
    });
    modal.addEventListener("click", function (e) {
      if (e.target === modal) closeModal();
    });
  }
  function closeModal() {
    var m = $("xfy-pc-repo-modal");
    if (m) m.remove();
  }

  // ============== 插件配置页 ==============
  function renderConfig() {
    if (!configBody) return;
    configBody.innerHTML = '<div class="pc-loading" id="pc-page-loading">加载插件列表中<span class="pc-dots">.</span></div>';
    var _dotsEl = configBody.querySelector('.pc-dots');
    var _dots = 0;
    var _loadingTimer = setInterval(function () {
      _dots = (_dots + 1) % 4;
      if (_dotsEl) _dotsEl.textContent = '.'.repeat(_dots);
    }, 350);
    Promise.all([
      fetchJson("/api/plugins", { timeout: 6000 }),
      fetchJson("/api/plugins/by-category", { timeout: 6000 }),
      loadAllMetas(),
    ])
      .then(function (results) {
        clearInterval(_loadingTimer);
        var data = results[0] || {};
        var byCatData = results[1] || {};
        lastConfigData = data;
        var plugs = data.plugins || [];

        // 加载失败提示 banner（外置插件 import 失败时显示）
        var loadErrors = data.load_errors || {};
        var errBanner = "";
        if (loadErrors && Object.keys(loadErrors).length) {
          var rows = Object.keys(loadErrors).map(function (p) {
            var name = p.split(/[\\/]/).pop();
            return '<div class="pc-err-row"><span class="pc-err-key">' + escapeHtml(name) + '</span><span class="pc-err-msg">' + escapeHtml(loadErrors[p]) + '</span></div>';
          }).join("");
          errBanner = '<div class="pc-err-banner">' +
            '<div class="pc-err-title">⚠️ ' + Object.keys(loadErrors).length + ' 个外置插件加载失败（已自动跳过，bot 主进程不受影响）</div>' +
            '<div class="pc-err-list">' + rows + '</div>' +
            '<div class="pc-err-tip">💡 修复后点「🔄 热加载」可重新扫描；常见原因：文件 BOM/语法错/缺依赖。详见 botpy.log。</div>' +
            '</div>';
        }

        if (!plugs.length) {
          configBody.innerHTML = errBanner + '<div class="pc-empty">当前没有已安装的插件。</div>';
          return;
        }
        var byCat = (byCatData.ok && byCatData.by_category) || {};
        var catNames = {
    life: "生活", tool: "工具", game: "娱乐", study: "学习",
    admin: "管理", chat: "聊天", fun: "趣味", image: "图片",
    video: "视频", music: "音乐", novel: "小说", test: "内置测试",
    entertainment: "娱乐", _misc: "其他",
  };
        function rowHtml(p) {
          var tag = p.is_external
            ? '<span class="pc-tag pc-tag-ext">外置</span>'
            : '<span class="pc-tag pc-tag-builtin">内置</span>';
          var descSrc = _descriptionOf(p);
          var desc = descSrc ? escapeHtml(descSrc) : '<span class="pc-muted">无描述</span>';
          var displayName = _displayNameOf(p);
          var meta = _metaOf(p.key);
          var aliasesHtml = "";
          if (meta && Array.isArray(meta.aliases) && meta.aliases.length) {
            aliasesHtml = ' <span class="pc-aliases" title="已配置别名">' +
              meta.aliases.map(function (a) { return '<span class="pc-alias-pill">' + escapeHtml(a) + '</span>'; }).join("") +
            '</span>';
          }
          // 名称旁标记"自定义"小角标
          var customMark = (meta && (meta.display_name !== p.name || meta.description !== p.description || (Array.isArray(meta.aliases) && meta.aliases.length)))
            ? ' <span class="pc-custom-mark" title="基础信息已自定义">✱</span>' : '';
          var sysOn = !!p.system_enabled;
          // 单「系统」总开关：写 is_feature_enabled，后端自动联动 _EXTERNAL_ENABLED
          var sysToggle =
            '<label class="pc-switch pc-switch-sys" title="系统总开关（关闭则插件完全不响应）">' +
              '<input type="checkbox" class="pc-toggle-sys" ' + (sysOn ? "checked" : "") +
              ' data-key="' + escapeHtml(p.key) + '">' +
              '<span class="pc-slider"></span></label>' +
            '<span class="pc-switch-label">' + (sysOn ? '已启用' : '已停用') + '</span>';
          // 「设置」按钮：弹出该插件的自定义配置面板（仅外置插件）
          var settingsBtn = p.is_external
            ? '<button type="button" class="pc-btn pc-btn-sm pc-btn-settings" data-key="' + escapeHtml(p.key) + '">⚙️ 设置</button>'
            : '<span class="pc-muted pc-pill" title="内置插件暂不支持自定义设置">无设置</span>';
          // 当总开关关掉时，附加灰底 + 禁用设置按钮
          var rowCls = sysOn ? "pc-row" : "pc-row pc-row-off";
          var settingsDisabled = sysOn ? '' : ' disabled';
          // 优先级也读 meta
          var prio = (meta && meta.priority != null) ? meta.priority : p.priority;
          return '<div class="' + rowCls + '">' +
            '<div class="pc-meta">' +
              '<div class="pc-name">' + escapeHtml(displayName) + customMark + ' ' + tag +
                ' <span class="pc-key">' + escapeHtml(p.key) + '</span>' + aliasesHtml + '</div>' +
              '<div class="pc-desc">' + desc + '</div>' +
            '</div>' +
            '<div class="pc-prio">优先级 ' + (prio != null ? prio : "-") + '</div>' +
            '<div class="pc-actions">' +
              '<div class="pc-toggle-block"><span class="pc-toggle-cap">系统</span>' + sysToggle + '</div>' +
              settingsBtn.replace('<button ', '<button ' + settingsDisabled) +
            '</div>' +
          '</div>';
        }
        var orderedCats = ["test"];
        Object.keys(catNames).forEach(function (c) { if (c !== "test" && byCat[c]) orderedCats.push(c); });
        Object.keys(byCat).forEach(function (c) { if (catNames[c] === undefined && byCat[c]) orderedCats.push(c); });
        var sections = orderedCats.map(function (cat) {
          var items = byCat[cat] || [];
          if (!items.length) return "";
          var cname = catNames[cat] || cat;
          var rows = items.map(function (d) {
            var meta = null;
            for (var i = 0; i < plugs.length; i++) { if (plugs[i].key === d.key) { meta = plugs[i]; break; } }
            return rowHtml(meta || Object.assign({ key: d.key, enabled: true }, d));
          }).join("");
          return '<div class="pc-section-title">📦 ' + escapeHtml(cname) + '<span class="pc-section-count">' + items.length + '</span></div>' +
                 '<div class="pc-list">' + rows + '</div>';
        }).join("");
        var listContainer = document.createElement('div');
        listContainer.className = 'pc-list-container';
        listContainer.innerHTML = sections || '<div class="pc-empty">当前没有已安装的插件。</div>';
        configBody.innerHTML =
          '<div class="pc-toolbar">' +
            '<div class="pc-view-toggle" role="tablist" aria-label="视图切换">' +
              '<button type="button" class="pc-view-btn active" data-view="list">列表</button>' +
              '<button type="button" class="pc-view-btn" data-view="grid">矩阵</button>' +
            '</div>' +
            '<button id="pc-reload-btn" class="pc-btn">🔄 热加载外置插件</button>' +
            '<span class="pc-hint">修改 plugins/ 下文件后点此立即生效，无需重启 bot</span>' +
            '<button id="pc-repo-settings" class="pc-btn pc-btn-link">⚙️ 仓库设置</button>' +
          '</div>' +
          (errBanner || '');
        configBody.appendChild(listContainer);
        // 绑定视图切换
        configBody.querySelectorAll('.pc-view-btn').forEach(function (btn) {
          btn.addEventListener('click', function () {
            var v = btn.getAttribute('data-view');
            configBody.querySelectorAll('.pc-view-btn').forEach(function (b) { b.classList.toggle('active', b === btn); });
            configBody.classList.remove('pc-view-list', 'pc-view-grid');
            configBody.classList.add('pc-view-' + v);
          });
        });
        // 默认视图：列表
        configBody.classList.add('pc-view-list');
        // 把 grid 数据备好（cardHtml 同 market 共享），隐藏在 grid container 里
        // 由于 row 改造成双开关较复杂，矩阵卡片仅展示关键信息 + 双开关的精简版
        // 矩阵卡片版（精简：单系统开关 + 设置按钮）
        function cardHtmlGrid(p) {
          var meta = null;
          for (var i = 0; i < plugs.length; i++) { if (plugs[i].key === p.key) { meta = plugs[i]; break; } }
          var pp = meta || p;
          var tag = pp.is_external
            ? '<span class="pc-tag pc-tag-ext">外置</span>'
            : '<span class="pc-tag pc-tag-builtin">内置</span>';
          var sysOn = !!pp.system_enabled;
          var cls = sysOn ? 'pc-card' : 'pc-card pc-card-off';
          var sysToggle =
            '<label class="pc-switch pc-switch-sys" title="系统总开关">' +
              '<input type="checkbox" class="pc-toggle-sys" ' + (sysOn ? "checked" : "") +
              ' data-key="' + escapeHtml(pp.key) + '">' +
              '<span class="pc-slider"></span></label>' +
            '<span class="pc-switch-label">' + (sysOn ? '已启用' : '已停用') + '</span>';
          var settingsBtn = pp.is_external
            ? '<button type="button" class="pc-btn pc-btn-sm pc-btn-settings" data-key="' + escapeHtml(pp.key) + '"' + (sysOn ? '' : ' disabled') + '>⚙️ 设置</button>'
            : '<span class="pc-muted pc-pill">无设置</span>';
          // 用 meta 的 display_name / description
          var displayName = _displayNameOf(pp);
          var descSrc = _descriptionOf(pp);
          var pmmeta = _metaOf(pp.key);
          var customMark = (pmmeta && (pmmeta.display_name !== pp.name || pmmeta.description !== pp.description || (Array.isArray(pmmeta.aliases) && pmmeta.aliases.length)))
            ? ' <span class="pc-custom-mark" title="基础信息已自定义">✱</span>' : '';
          var aliasesHtml = "";
          if (pmmeta && Array.isArray(pmmeta.aliases) && pmmeta.aliases.length) {
            aliasesHtml = '<div class="pc-card-aliases">' + pmmeta.aliases.map(function (a) { return '<span class="pc-alias-pill">' + escapeHtml(a) + '</span>'; }).join("") + '</div>';
          }
          return '<div class="' + cls + '" data-key="' + escapeHtml(pp.key) + '">' +
            '<div class="pc-card-head">' +
              '<div class="pc-card-title">' + escapeHtml(displayName) + customMark + ' ' + tag + '</div>' +
              '<div class="pc-card-key">' + escapeHtml(pp.key) + '</div>' +
            '</div>' +
            '<div class="pc-card-desc">' + (descSrc ? escapeHtml(descSrc) : '<span class="pc-muted">无描述</span>') + '</div>' +
            aliasesHtml +
            '<div class="pc-card-foot">' +
              '<div class="pc-toggle-block"><span class="pc-toggle-cap">系统</span>' + sysToggle + '</div>' +
              settingsBtn +
            '</div>' +
          '</div>';
        }

        var gridContainer = document.createElement('div');
        gridContainer.className = 'pc-grid-container';
        var gridSections = orderedCats.map(function (cat) {
          var items = byCat[cat] || [];
          if (!items.length) return "";
          var cname = catNames[cat] || cat;
          var cards = items.map(function (d) {
            var meta = null;
            for (var i = 0; i < plugs.length; i++) { if (plugs[i].key === d.key) { meta = plugs[i]; break; } }
            return cardHtmlGrid(meta || Object.assign({ key: d.key, enabled: true }, d));
          }).join("");
          return '<div class="pc-section-title">📦 ' + escapeHtml(cname) + '<span class="pc-section-count">' + items.length + '</span></div>' +
                 '<div class="pc-grid">' + cards + '</div>';
        }).join("");
        gridContainer.innerHTML = gridSections || '<div class="pc-empty">当前没有已安装的插件。</div>';
        configBody.appendChild(gridContainer);
        var reloadBtn = $("pc-reload-btn");
        if (reloadBtn) reloadBtn.addEventListener("click", function () {
          reloadBtn.disabled = true;
          reloadBtn.textContent = "⏳ 热加载中…";
          fetchJson("/api/plugins/reload", { method: "POST" })
            .then(function (d) {
              if (d && d.ok) {
                var s = d.stats || {};
                showToast("已热加载：新增 " + (s.loaded || 0) + " / 重载 " + (s.reloaded || 0) + " / 注销 " + (s.unregistered || 0) + (s.errors ? (" / 错误 " + s.errors) : ""));
                renderConfig();
              } else {
                showToast("热加载失败：" + (d && d.error), "error");
                reloadBtn.disabled = false;
                reloadBtn.textContent = "🔄 热加载外置插件";
              }
            })
            .catch(function () {
              showToast("⚠️ 热加载请求失败", "error");
              reloadBtn.disabled = false;
              reloadBtn.textContent = "🔄 热加载外置插件";
            });
        });
        var settingsBtn = $("pc-repo-settings");
        if (settingsBtn) settingsBtn.addEventListener("click", openRepoSettings);
      })
      .catch(function (e) {
        clearInterval(_loadingTimer);
        renderErrorBox(configBody, (e && e.code) || "backend_down", e && e.message);
      });
  }

  // ============== 插件市场页 ==============
  function renderMarket(force) {
    if (!marketBody) return;
    marketBody.innerHTML = '<div class="pc-loading" id="pc-market-loading">加载插件市场中<span class="pc-dots">.</span></div>';
    var _mDotsEl = marketBody.querySelector('.pc-dots');
    var _mDots = 0;
    var _mLoadingTimer = setInterval(function () {
      _mDots = (_mDots + 1) % 4;
      if (_mDotsEl) _mDotsEl.textContent = '.'.repeat(_mDots);
    }, 350);
    Promise.all([
      fetchJson("/api/plugins", { timeout: 6000 }),
      fetchJson("/api/plugins/market" + (force ? "?force=1" : ""), { timeout: 30000 }),
    ])
      .then(function (res) {
        clearInterval(_mLoadingTimer);
        var plugs = ((res[0] || {}).plugins) || [];
        var mp = res[1] || {};
        lastMarketData = mp;
        var remoteCatalog = mp.catalog || [];
        var builtinTest = mp.builtin_test || [];
        var repoUrl = mp.repo_url || "";
        var source = mp.source || mp.remote_source || "local_only";

        // 远端失败但有陈旧缓存
        if (mp.ok === false && !remoteCatalog.length) {
          renderErrorBox(marketBody, (mp.error_code || "network_other"), (mp.remote_error || mp.error_hint || "远程仓库不可用"), source);
          if (builtinTest.length) {
            marketBody.insertAdjacentHTML("beforeend",
              '<div class="pc-section-title">内置测试插件（随框架附带）</div>' +
              '<div class="pc-grid">' + builtinTest.map(function (c) { return cardHtml(c, false, plugs); }).join("") + '</div>'
            );
          }
          attachCardEvents();
          return;
        }
        if (mp.ok === false) {
          renderErrorBox(marketBody, mp.error_code || "network_other", mp.remote_error || "");
          return;
        }

        // 分类图标 & 颜色（按 plugin category 取）
        var CAT_META = {
          life:   { icon: "🌱", color: "#26c281" },
          tool:   { icon: "🛠", color: "#3b6ef5" },
          game:   { icon: "🎮", color: "#a55eea" },
          study:  { icon: "📚", color: "#00b894" },
          admin:  { icon: "🛡", color: "#ff6b6b" },
          chat:   { icon: "💬", color: "#6c8eff" },
          fun:    { icon: "🎲", color: "#fd79a8" },
          image:  { icon: "🖼", color: "#14b8a6" },
          video:  { icon: "🎬", color: "#ff9f43" },
          music:  { icon: "🎵", color: "#f06292" },
          novel:  { icon: "📖", color: "#8c5cff" },
          test:   { icon: "🧪", color: "#8b91b5" },
          entertainment: { icon: "🎲", color: "#fd79a8" },
          _misc:  { icon: "📦", color: "#8b91b5" },
        };
        function catMeta(c) { return CAT_META[c.category || "_misc"] || CAT_META._misc; }
        function statusOf(c) {
          if ((plugs || []).some(function (p) { return p.key === c.key; }) || c.installed) return "installed";
          return "available";
        }

        function cardHtml(c, isRemote, allPlugs) {
          var meta = catMeta(c);
          var status = statusOf(c);
          var tag = isRemote
            ? '<span class="pc-tag pc-tag-ext">仓库</span>'
            : '<span class="pc-tag pc-tag-builtin">内置</span>';
          var statusLabel = status === "installed"
            ? '<span class="pc-card-status pc-card-status-on">✓ 已装</span>'
            : '<span class="pc-card-status">未装</span>';
          var action = status === "installed"
            ? '<button class="pc-btn pc-btn-sm pc-btn-danger pc-act" data-act="uninstall" data-key="' + escapeHtml(c.key) + '">卸载</button>'
            : '<button class="pc-btn pc-btn-sm pc-btn-primary pc-act" data-act="install" data-key="' + escapeHtml(c.key) + '" data-raw="' + escapeHtml(c.raw_url || "") + '">安装</button>';
          var desc = c.description ? escapeHtml(c.description) : '<span class="pc-muted">暂无描述</span>';
          var firstChar = (c.name || c.key || "?").substring(0, 1).toUpperCase();
          return '<div class="pc-card" data-key="' + escapeHtml(c.key) + '" data-cat="' + escapeHtml(c.category || "_misc") + '" data-status="' + status + '" data-name="' + escapeHtml(c.name || c.key) + '">' +
            '<div class="pc-card-icon" style="background:linear-gradient(135deg,' + meta.color + '22,' + meta.color + '44);color:' + meta.color + ';">' +
              meta.icon +
            '</div>' +
            '<div class="pc-card-body">' +
              '<div class="pc-card-title">' + escapeHtml(c.name) + ' ' + tag + statusLabel + '</div>' +
              '<div class="pc-card-key">' + meta.icon + ' ' + escapeHtml(c.category || "其他") + ' · ' + escapeHtml(c.key) + '</div>' +
              '<div class="pc-card-desc">' + desc + '</div>' +
            '</div>' +
            '<div class="pc-card-foot">' + action + '</div>' +
          '</div>';
        }

        var sourceLabel = source === "remote" ? "实时拉取" :
                          source === "cache" ? "本地缓存（10 分钟内）" :
                          source === "cache_stale" ? "陈旧缓存" : "";
        var sourceTag = sourceLabel ? '<span class="pc-source-tag ' + (source === "cache_stale" ? "pc-source-stale" : "") + '">' + sourceLabel + '</span>' : "";

        // 收集全部分类（用于过滤器）
        var allCats = {};
        remoteCatalog.concat(builtinTest).forEach(function (c) {
          var cat = c.category || "_misc";
          allCats[cat] = (allCats[cat] || 0) + 1;
        });
        var catNames = { life: "生活", tool: "工具", game: "娱乐", study: "学习", admin: "管理", chat: "聊天", fun: "趣味", image: "图片", video: "视频", music: "音乐", novel: "小说", test: "内置测试", entertainment: "娱乐", _misc: "其他" };
        var filterChips = '<div class="pc-filter">' +
          '<button class="pc-chip pc-chip-active" data-cat="">全部 ' + (remoteCatalog.length + builtinTest.length) + '</button>' +
          Object.keys(allCats).sort().map(function (cat) {
            return '<button class="pc-chip" data-cat="' + escapeHtml(cat) + '">' + (catNames[cat] || cat) + ' ' + allCats[cat] + '</button>';
          }).join("") +
        '</div>';

        var html = '';
        html += '<div class="pc-market-head">' +
                  '<div class="pc-market-title">插件市场</div>' +
                  '<div class="pc-market-tools">' +
                    '<span class="pc-market-repo" title="' + escapeHtml(repoUrl) + '">' + escapeHtml(repoUrl) + '</span>' +
                    sourceTag +
                    '<input type="text" class="pc-search" id="pc-market-search" placeholder="搜索插件名 / key / 描述…" />' +
                    '<button class="pc-btn pc-btn-sm" id="pc-market-refresh">🔄 刷新</button>' +
                    '<button class="pc-btn pc-btn-sm" id="pc-market-settings">⚙️</button>' +
                  '</div>' +
                '</div>';

        if (mp.error) {
          html += '<div class="pc-warn">⚠️ 远程仓库拉取失败（' + escapeHtml(mp.error.message || "") + '），已使用 ' + (source === "cache_stale" ? "陈旧缓存" : "内置插件") + '。</div>';
        }

        html += filterChips;

        var total = remoteCatalog.length + builtinTest.length;
        if (total) {
          html += '<div class="pc-section-title" id="pc-market-section-remote">仓库插件（' + remoteCatalog.length + '）</div>';
          html += '<div class="pc-grid" id="pc-grid-remote">' + remoteCatalog.map(function (c) { return cardHtml(c, true, plugs); }).join('') + '</div>';
          if (builtinTest.length) {
            html += '<div class="pc-section-title" id="pc-market-section-builtin">内置测试插件（' + builtinTest.length + '）</div>';
            html += '<div class="pc-grid" id="pc-grid-builtin">' + builtinTest.map(function (c) { return cardHtml(c, false, plugs); }).join('') + '</div>';
          }
        } else if (!mp.error) {
          html += '<div class="pc-empty">仓库暂无插件</div>';
        }
        marketBody.innerHTML = html;

        $("pc-market-refresh").addEventListener("click", function () { renderMarket(true); });
        $("pc-market-settings").addEventListener("click", openRepoSettings);

        // 分类过滤
        marketBody.querySelectorAll(".pc-chip").forEach(function (b) {
          b.addEventListener("click", function () {
            marketBody.querySelectorAll(".pc-chip").forEach(function (x) { x.classList.remove("pc-chip-active"); });
            b.classList.add("pc-chip-active");
            applyMarketFilter();
          });
        });
        // 搜索
        var searchEl = $("pc-market-search");
        if (searchEl) {
          searchEl.addEventListener("input", applyMarketFilter);
        }
        function applyMarketFilter() {
          var activeChip = marketBody.querySelector(".pc-chip-active");
          var cat = activeChip ? activeChip.getAttribute("data-cat") : "";
          var q = (searchEl && searchEl.value || "").trim().toLowerCase();
          marketBody.querySelectorAll(".pc-card").forEach(function (card) {
            var c = card.getAttribute("data-cat") || "";
            var name = (card.getAttribute("data-name") || "").toLowerCase();
            var key = (card.getAttribute("data-key") || "").toLowerCase();
            var desc = (card.querySelector(".pc-card-desc") || {}).textContent || "";
            var matchCat = !cat || c === cat;
            var matchQuery = !q || name.indexOf(q) >= 0 || key.indexOf(q) >= 0 || desc.toLowerCase().indexOf(q) >= 0;
            card.style.display = (matchCat && matchQuery) ? "" : "none";
          });
          // 隐藏无可见卡的 section
          ["pc-grid-remote", "pc-grid-builtin"].forEach(function (gridId) {
            var grid = $(gridId);
            if (!grid) return;
            var visible = Array.from(grid.querySelectorAll(".pc-card")).some(function (c) { return c.style.display !== "none"; });
            var titleId = gridId === "pc-grid-remote" ? "pc-market-section-remote" : "pc-market-section-builtin";
            var title = $(titleId);
            if (title) title.style.display = visible ? "" : "none";
            grid.style.display = visible ? "" : "none";
          });
        }

        attachCardEvents();
      })
      .catch(function (e) {
        clearInterval(_mLoadingTimer);
        renderErrorBox(marketBody, (e && e.code) || "backend_down", e && e.message);
      });
  }

  function attachCardEvents() {
    if (!marketBody) return;
    marketBody.querySelectorAll(".pc-act").forEach(function (b) {
      if (b._binded) return;
      b._binded = true;
      b.addEventListener("click", function () {
        var act = b.getAttribute("data-act");
        var key = b.getAttribute("data-key");
        var raw = b.getAttribute("data-raw") || "";
        b.disabled = true;
        var origText = b.textContent;
        b.textContent = act === "install" ? "⏳ 安装中…" : "⏳ 卸载中…";
        var url = act === "install" ? "/api/plugins/market/install" : "/api/plugins/market/uninstall";
        var body = act === "install" ? { key: key, raw_url: raw } : { key: key };
        fetchJson(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        })
          .then(function (d) {
            if (d && d.ok) {
              showToast((act === "install" ? "安装" : "卸载") + "成功：" + key);
              renderMarket(false);
              if (typeof XFY_PC_renderConfig === "function") XFY_PC_renderConfig();
            } else {
              showToast((act === "install" ? "安装" : "卸载") + "失败：" + (d && (d.error || d.message)), "error");
              b.disabled = false;
              b.textContent = origText;
            }
          })
          .catch(function (e) {
            showToast("请求失败：" + (e && e.message), "error");
            b.disabled = false;
            b.textContent = origText;
          });
      });
    });
  }

  // ============== 启用/停用 开关 + 设置按钮 ==============
  function bindToggleEvents() {
    if (!configBody) return;
    // 系统总开关：单开关，后端自动联动外置插件开关
    configBody.addEventListener("change", function (e) {
      var t = e.target;
      if (!(t && t.matches)) return;
      if (!t.matches(".pc-toggle-sys")) return;
      var key = t.getAttribute("data-key");
      var enabled = !!t.checked;
      t.disabled = true;
      fetchJson("/api/plugins/set-enabled", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: key, enabled: enabled, kind: "system" }),
      })
        .then(function (j) {
          t.disabled = false;
          if (j && j.ok) {
            showToast("已" + (enabled ? "启用" : "停用") + "：" + key);
            renderConfig();
          } else {
            t.checked = !enabled;
            showToast("更新失败：" + (j && j.error), "error");
          }
        })
        .catch(function (e) {
          t.disabled = false;
          t.checked = !enabled;
          showToast("更新失败：" + (e && e.message), "error");
        });
    });
    // 「设置」按钮：弹出该插件的自定义配置面板
    configBody.addEventListener("click", function (e) {
      var btn = e.target.closest && e.target.closest(".pc-btn-settings");
      if (!btn) return;
      if (btn.disabled) return;
      var key = btn.getAttribute("data-key");
      if (!key) return;
      openPluginSettings(key, btn);
    });
  }

  // ============== 插件设置面板（modal） ==============
  function openPluginSettings(key, triggerBtn) {
    // 1) 打开一个浮层
    var modal = document.createElement("div");
    modal.className = "pc-modal-mask";
    modal.setAttribute("data-key", key);
    var plugName = (triggerBtn && triggerBtn.closest) ?
      ((triggerBtn.closest(".pc-row") || triggerBtn.closest(".pc-card")) ? null : null)
      : null;
    // 标题里优先用 _displayNameOf 找 meta 自定义名
    var _preMeta = _metaOf(key);
    var _preName = (_preMeta && _preMeta.display_name) || (function(){
      try { var p = (lastConfigData && lastConfigData.plugins || []).find(function(x){return x.key===key;}); if (p) return p.name; } catch(e){}
      return key;
    })();
    modal.innerHTML =
      '<div class="pc-modal">' +
        '<div class="pc-modal-head">' +
          '<div class="pc-modal-title">⚙️ ' + escapeHtml(_preName) + ' <span class="pc-modal-subkey">' + escapeHtml(key) + '</span> · 自定义设置</div>' +
          '<button type="button" class="pc-modal-close" aria-label="关闭">×</button>' +
        '</div>' +
        '<div class="pc-modal-body"><div class="pc-loading">加载配置…</div></div>' +
        '<div class="pc-modal-foot">' +
          '<button type="button" class="pc-btn pc-modal-cancel">取消</button>' +
          '<button type="button" class="pc-btn pc-btn-primary pc-modal-save">保存</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(modal);
    var body = modal.querySelector(".pc-modal-body");
    var saveBtn = modal.querySelector(".pc-modal-save");
    var cancelBtn = modal.querySelector(".pc-modal-cancel");
    var closeBtn = modal.querySelector(".pc-modal-close");

    function close() { modal.remove(); }
    cancelBtn.addEventListener("click", close);
    closeBtn.addEventListener("click", close);
    modal.addEventListener("click", function (e) { if (e.target === modal) close(); });

    // 加载状态：显示一个会跳动的进度点 + 倒计时
    var loadingTimer = null;
    var dots = 0;
    body.innerHTML = '<div class="pc-loading" id="pc-modal-loading-dots">加载配置中<span class="pc-dots">.</span></div>';
    var dotsEl = body.querySelector('.pc-dots');
    loadingTimer = setInterval(function () {
      dots = (dots + 1) % 4;
      if (dotsEl) dotsEl.textContent = '.'.repeat(dots);
    }, 350);

    // 2) 并行加载 meta + config
    Promise.all([
      fetchJson("/api/plugins/meta?key=" + encodeURIComponent(key), { timeout: 4000 }),
      fetchJson("/api/plugins/config?key=" + encodeURIComponent(key), { timeout: 4000 }),
    ])
      .then(function (rs) {
        clearInterval(loadingTimer);
        var metaR = rs[0] || {};
        var cfg = rs[1] || {};
        var meta = (metaR && metaR.ok) ? metaR.meta : {};
        // 更新 _metaCache
        if (metaR && metaR.ok) _metaCache[key] = meta;
        if (!cfg || !cfg.ok) {
          body.innerHTML =
            '<div class="pc-empty">⚠️ ' + escapeHtml((cfg && cfg.error) || "读取失败") +
            '<br><br><button type="button" class="pc-btn pc-btn-sm pc-modal-retry">🔄 重试</button></div>';
          saveBtn.disabled = true;
          var rb = body.querySelector(".pc-modal-retry");
          if (rb) rb.addEventListener("click", function () { openPluginSettings(key, null); close(); });
          return;
        }
        var schema = cfg.schema || [];
        var values = cfg.values || {};

        var metaBlock =
          '<div class="pc-meta-block">' +
            '<div class="pc-meta-block-title">🪪 基础信息 <span class="pc-meta-hint">显示名 / 触发指令 / 优先级 / 别名 / 参数提示</span></div>' +
            '<div class="pc-meta-stack">' +
              '<div class="pc-meta-stack-item">' +
                '<label>显示名</label>' +
                '<input type="text" class="pc-meta-input" data-meta="display_name" placeholder="（留空则使用插件默认名）" value="' + escapeHtml(meta.display_name || "") + '">' +
              '</div>' +
              '<div class="pc-meta-stack-item">' +
                '<label>触发指令 / 描述</label>' +
                '<textarea class="pc-meta-input" data-meta="description" rows="2" placeholder="如：发送「疾病信息 病名」查疾病">' + escapeHtml(meta.description || "") + '</textarea>' +
              '</div>' +
              '<div class="pc-meta-stack-item">' +
                '<label>优先级 <span class="pc-meta-hint">数字越小越靠前</span></label>' +
                '<input type="number" class="pc-meta-input" data-meta="priority" min="0" max="999" value="' + (meta.priority != null ? meta.priority : 50) + '">' +
              '</div>' +
              '<div class="pc-meta-stack-item">' +
                '<label>参数提示 <span class="pc-meta-hint">用户输错参数时显示</span></label>' +
                '<input type="text" class="pc-meta-input" data-meta="param_hint" placeholder="如：请输入疾病名" value="' + escapeHtml(meta.param_hint || "") + '">' +
              '</div>' +
              '<div class="pc-meta-stack-item">' +
                '<label>别名 <span class="pc-meta-hint">用 、 , 空格分隔，保存后 bot 立即生效</span></label>' +
                '<input type="text" class="pc-meta-input" data-meta="aliases" placeholder="如：疾病、查病、disease" value="' + escapeHtml(_aliasesToText(meta.aliases)) + '">' +
              '</div>' +
            '</div>' +
          '</div>';

        var configBlock = "";
        if (schema.length) {
          configBlock =
            '<div class="pc-form">' +
              '<div class="pc-form-title">⚙️ 插件运行参数 <span class="pc-meta-hint">由插件声明的 config_schema 控制</span></div>' +
              schema.map(function (f) { return renderField(f, values[f.key]); }).join("") +
            '</div>';
        } else {
          configBlock =
            '<div class="pc-form">' +
              '<div class="pc-form-title">⚙️ 插件运行参数</div>' +
              '<div class="pc-empty">该插件未声明 config_schema（无运行参数可配）。可在 <code>plugins/' + escapeHtml(key) + '/main.py</code> 头部添加 <code>config_schema</code>。</div>' +
            '</div>';
        }

        body.innerHTML = metaBlock + configBlock;

        saveBtn.onclick = function () {
          saveBtn.disabled = true;
          saveBtn.textContent = "保存中…";
          // 1) 收集 meta
          var metaPayload = {};
          body.querySelectorAll("[data-meta]").forEach(function (el) {
            metaPayload[el.getAttribute("data-meta")] = el.value;
          });
          // 2) 收集 config schema 值
          var newValues = schema.length ? collectValues(body, schema) : {};
          // 3) 先保存 meta（不依赖 schema），再保存 config
          var p1 = fetchJson("/api/plugins/meta", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ key: key, meta: metaPayload }),
          });
          var p2 = schema.length ? fetchJson("/api/plugins/config", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ key: key, values: newValues }),
          }) : Promise.resolve({ ok: true });
          Promise.all([p1, p2])
            .then(function (rs2) {
              var ok = rs2[0] && rs2[0].ok && (rs2[1] && rs2[1].ok);
              if (ok) {
                // 刷新 meta 缓存
                _metaCache[key] = {
                  display_name: metaPayload.display_name || "",
                  description: metaPayload.description || "",
                  priority: parseInt(metaPayload.priority, 10) || 50,
                  aliases: (metaPayload.aliases || "").split(/[,，、\s]+/).map(function (s) { return s.trim(); }).filter(Boolean),
                  param_hint: metaPayload.param_hint || "",
                };
                showToast("设置已保存：" + key);
                // 重渲染列表/卡片，让显示名/别名/描述实时更新
                renderConfig();
                close();
              } else {
                var err = (rs2[0] && rs2[0].error) || (rs2[1] && rs2[1].error) || "保存失败";
                showToast("保存失败：" + err, "error");
                saveBtn.disabled = false;
                saveBtn.textContent = "保存";
              }
            })
            .catch(function (e) {
              showToast("保存失败：" + (e && e.message), "error");
              saveBtn.disabled = false;
              saveBtn.textContent = "保存";
            });
        };
      })
      .catch(function (e) {
        clearInterval(loadingTimer);
        body.innerHTML = '<div class="pc-empty">⚠️ 加载失败：' + escapeHtml((e && e.message) || "") + '</div>';
        saveBtn.disabled = true;
      });
  }

  function renderField(f, value) {
    var k = escapeHtml(f.key);
    var label = escapeHtml(f.label || f.key);
    var desc = f.description ? '<div class="pc-field-desc">' + escapeHtml(f.description) + '</div>' : '';
    var v = (value === undefined || value === null) ? (f.default !== undefined ? f.default : "") : value;
    var t = (f.type || "string").toLowerCase();
    var inputHtml = "";
    if (t === "boolean" || t === "bool") {
      var on = !!v;
      inputHtml =
        '<label class="pc-switch">' +
          '<input type="checkbox" class="pc-field-input" data-type="boolean" data-key="' + k + '"' + (on ? ' checked' : '') + '>' +
          '<span class="pc-slider"></span>' +
        '</label>' +
        '<span class="pc-switch-label">' + (on ? '开启' : '关闭') + '</span>';
    } else if (t === "select") {
      var opts = (f.options || []).map(function (o) {
        var sv = String(o);
        return '<option value="' + escapeHtml(sv) + '"' + (sv === String(v) ? ' selected' : '') + '>' + escapeHtml(sv) + '</option>';
      }).join("");
      inputHtml = '<select class="pc-field-input" data-type="select" data-key="' + k + '">' + opts + '</select>';
    } else if (t === "number" || t === "int" || t === "float") {
      var min = f.min !== undefined ? ' min="' + escapeHtml(f.min) + '"' : '';
      var max = f.max !== undefined ? ' max="' + escapeHtml(f.max) + '"' : '';
      var step = (t === "float") ? ' step="any"' : '';
      inputHtml = '<input type="number" class="pc-field-input" data-type="number" data-key="' + k + '"' + min + max + step + ' value="' + escapeHtml(v) + '">';
    } else if (t === "textarea") {
      inputHtml = '<textarea class="pc-field-input" data-type="textarea" data-key="' + k + '" rows="3">' + escapeHtml(v) + '</textarea>';
    } else {
      inputHtml = '<input type="text" class="pc-field-input" data-type="string" data-key="' + k + '" value="' + escapeHtml(v) + '">';
    }
    return '<div class="pc-form-row">' +
      '<label class="pc-form-label">' + label + '</label>' +
      '<div class="pc-form-control">' + inputHtml + desc + '</div>' +
    '</div>';
  }

  function collectValues(container, schema) {
    var out = {};
    var inputs = container.querySelectorAll(".pc-field-input");
    inputs.forEach(function (inp) {
      var k = inp.getAttribute("data-key");
      var t = inp.getAttribute("data-type");
      if (t === "boolean") {
        out[k] = !!inp.checked;
      } else if (t === "number") {
        out[k] = inp.value === "" ? null : Number(inp.value);
      } else if (t === "select") {
        out[k] = inp.value;
      } else if (t === "textarea") {
        out[k] = inp.value;
      } else {
        out[k] = inp.value;
      }
    });
    return out;
  }

  // ============== 初始化 ==============
  function init() {
    configBody = $("plugin-config-body");
    marketBody = $("plugin-market-body");
    bindToggleEvents();
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  // 暴露给 index.html 切换页时调用
  window.XFY_PC_renderConfig = renderConfig;
  window.XFY_PC_renderMarket = function (force) { renderMarket(!!force); };
})();
