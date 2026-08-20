/* ============================================================
 *  小流萤 bot · 交互设置（菜单树编辑器 · 任意层级）
 *  - 单 Tab 设计：左侧树形选择器 + 面包屑导航 + 右侧编辑器
 *  - 任意层级菜单都可以新增 / 删除 / 编辑（按钮行 / 按钮）
 *  - 实时预览 + 保存 / 重新加载 / 恢复默认
 * ============================================================ */
(function () {
  "use strict";
  if (typeof window === "undefined") return;

  var API_BASE = (typeof window.API_BASE === "string" && window.API_BASE) || "http://127.0.0.1:9988";

  // ============== 状态 ==============
  var state = {
    tree: null,         // 整个菜单树 {version, root}
    ctx: null,
    paths: [],          // 所有节点路径（含 root）
    currentPath: [],    // 当前编辑节点路径；[] 表示 root
    dirty: false,
  };

  // ============== 工具 ==============
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
    var old = $("xfy-fm-toast");
    if (old) old.remove();
    var div = document.createElement("div");
    div.id = "xfy-fm-toast";
    var bg = kind === "error" ? "#e74c3c" : (kind === "warn" ? "#f39c12" : "#16a34a");
    div.style.cssText = "position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:" + bg + ";color:#fff;padding:10px 22px;border-radius:8px;z-index:100000;font-size:13px;box-shadow:0 6px 24px rgba(0,0,0,.18);max-width:80vw;";
    div.textContent = msg;
    document.body.appendChild(div);
    setTimeout(function () { if (div.parentNode) div.remove(); }, 2400);
  }

  // 克隆节点（深拷贝 children dict）
  function cloneNode(node) {
    if (!node || typeof node !== "object") return node;
    var out = {};
    for (var k in node) {
      if (k === "children" && node[k] && typeof node[k] === "object") {
        var cc = {};
        for (var ck in node[k]) {
          cc[ck] = cloneNode(node[k][ck]);
        }
        out[k] = cc;
      } else if (Array.isArray(node[k])) {
        out[k] = node[k].map(function (x) {
          if (x && typeof x === "object") return JSON.parse(JSON.stringify(x));
          return x;
        });
      } else {
        out[k] = node[k];
      }
    }
    return out;
  }

  // 沿 path 获取节点
  function getNodeAtPath(path) {
    if (!state.tree) return null;
    var node = state.tree.root;
    for (var i = 0; i < path.length; i++) {
      if (!node || !node.children) return null;
      node = node.children[path[i]];
    }
    return node;
  }

  // 沿 path 获取父节点
  function getParentAtPath(path) {
    if (!path || !path.length) return null;
    var parentPath = path.slice(0, -1);
    return getNodeAtPath(parentPath);
  }

  // 节点 key 是否在 path 上
  function isOnCurrentPath(key, path) {
    return path.length > 0 && path[path.length - 1] === key;
  }

  // 路径转字符串（用于面包屑）
  function pathToString(path) {
    if (!path.length) return "主菜单（用户输入『帮助』看到的卡片）";
    return "主菜单 / " + path.join(" / ");
  }

  // 路径转显示名
  function pathToName(path) {
    if (!path.length) return "主菜单";
    return path[path.length - 1];
  }

  // ============== 条件显示的可用变量（主菜单按钮 show_if） ==============
  var CONDITION_OPTIONS = [
    { v: "",                                    l: "始终显示" },
    { v: "is_group",                            l: "群聊时显示" },
    { v: "checkin_on",                          l: "系统开关·签到 on" },
    { v: "video_on",                            l: "系统开关·视频 on" },
    { v: "music_on",                            l: "系统开关·音乐 on" },
    { v: "image_on",                            l: "系统开关·图片 on" },
    { v: "game_on",                             l: "系统开关·娱乐 on" },
    { v: "tools_on",                            l: "系统开关·工具 on" },
    { v: "study_on",                            l: "系统开关·学习 on" },
    { v: "novel_on",                            l: "系统开关·小说 on" },
    { v: "group_admin_on",                      l: "系统开关·群管 on" },
    { v: "group_admin_on AND is_group",         l: "群管开启 且 群聊" },
    { v: "any_plugin:genshin_miao,genshin,starrail,ww_gacha",
                                                l: "原神/星铁/鸣潮 任一开启" },
    { v: "feedback_enabled",                    l: "反馈 URL 已配置" },
    { v: "experience_group_enabled",            l: "体验群 URL 已配置" },
  ];

  // ============== 入口 ==============
  function render() {
    var body = $("feature-menu-body");
    if (!body) return;
    body.innerHTML =
      '<div class="fm-loading">加载中...</div>'
    ;
    loadFromServer();
  }

  // ============== 加载 / 重新加载 ==============
  function loadFromServer() {
    fetch(API_BASE + "/api/menu/tree")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data && data.ok) {
          state.tree = data.tree;
          state.ctx = data.ctx;
          state.paths = data.paths || [[]];
          // 保留当前路径（如果还在），否则切到 root
          var node = getNodeAtPath(state.currentPath);
          if (!node) state.currentPath = [];
          state.dirty = false;
          renderLayout();
        } else {
          $("feature-menu-body").innerHTML =
            '<div class="fm-loading">加载失败：' + escapeHtml((data && (data.error || data.message)) || "未知错误") + '</div>';
        }
      })
      .catch(function (e) {
        $("feature-menu-body").innerHTML =
          '<div class="fm-loading">网络错误：' + escapeHtml(e.message) + '</div>';
      });
  }

  // ============== 主布局：左树 + 右上 + 右下 ==============
  function renderLayout() {
    var body = $("feature-menu-body");
    if (!body) return;

    body.innerHTML =
      '<div class="fm-toolbar">' +
        '<button class="fm-btn fm-btn-primary" id="fm-save">💾 保存全部</button>' +
        '<button class="fm-btn" id="fm-reload">↻ 重新加载</button>' +
        '<button class="fm-btn fm-btn-danger" id="fm-reset">⏮ 恢复默认</button>' +
        '<button class="fm-btn" id="fm-preview">👁 预览当前节点</button>' +
        '<span class="fm-dirty" id="fm-dirty"></span>' +
      '</div>' +
      '<div class="fm-tree-layout">' +
        '<div class="fm-tree-side">' +
          '<div class="fm-tree-side-title">菜单树（点击切换）</div>' +
          '<div class="fm-tree-list" id="fm-tree-list"></div>' +
        '</div>' +
        '<div class="fm-tree-main">' +
          '<div class="fm-breadcrumb" id="fm-breadcrumb"></div>' +
          '<div id="fm-tree-editor"></div>' +
        '</div>' +
      '</div>'
    ;
    renderTreeSide();
    renderBreadcrumb();
    renderEditor();
    bindToolbar();
    markDirty(false);
  }

  // ============== 左侧树 ==============
  function renderTreeSide() {
    var wrap = $("fm-tree-list");
    if (!wrap || !state.tree) return;
    var root = state.tree.root;
    var html = "";
    // 根节点
    var rootActive = state.currentPath.length === 0 ? " active" : "";
    html += '<div class="fm-tree-item fm-tree-root' + rootActive + '" data-path="">' +
      '<span class="fm-tree-icon">🏠</span>' +
      '<span class="fm-tree-label">主菜单</span>' +
    '</div>';
    html += '<div class="fm-tree-children">' + renderTreeChildren(root.children || {}, 0) + '</div>';
    wrap.innerHTML = html;
    Array.prototype.forEach.call(wrap.querySelectorAll(".fm-tree-item"), function (el) {
      el.onclick = function (e) {
        if (e.target.classList.contains("fm-tree-toggle")) return;
        var dp = el.getAttribute("data-path");
        var path = dp === "" ? [] : dp.split("|");
        if (state.dirty) {
          if (!confirm("有未保存的修改，确定要切换吗？")) return;
        }
        state.currentPath = path;
        state.dirty = false;
        renderLayout();
      };
    });
    // 折叠/展开
    Array.prototype.forEach.call(wrap.querySelectorAll(".fm-tree-toggle"), function (t) {
      t.onclick = function (e) {
        e.stopPropagation();
        var li = t.parentElement;
        var sub = li.querySelector(".fm-tree-children");
        if (!sub) return;
        var collapsed = li.classList.toggle("fm-collapsed");
        t.textContent = collapsed ? "▶" : "▼";
      };
    });
  }

  function renderTreeChildren(children, depth) {
    var html = "";
    var keys = Object.keys(children || {});
    if (!keys.length) return "";
    keys.forEach(function (k) {
      var sub = children[k];
      var hasChildren = sub && sub.children && Object.keys(sub.children).length > 0;
      var dp = state.currentPath.slice(0, depth).concat([k]);
      var pathStr = dp.join("|");
      var active = isOnCurrentPath(k, state.currentPath) ? " active" : "";
      var collapsed = isCollapsedOnPath(dp) ? " fm-collapsed" : "";
      html += '<div class="fm-tree-li' + active + collapsed + '" data-depth="' + depth + '">' +
        '<div class="fm-tree-item" data-path="' + escapeHtml(pathStr) + '">' +
          (hasChildren
            ? '<span class="fm-tree-toggle">' + (collapsed ? "▶" : "▼") + '</span>'
            : '<span class="fm-tree-toggle fm-tree-toggle-empty">·</span>') +
          '<span class="fm-tree-icon">' + (hasChildren ? "📂" : "📄") + '</span>' +
          '<span class="fm-tree-label">' + escapeHtml(k) + '</span>' +
        '</div>';
      if (hasChildren) {
        html += '<div class="fm-tree-children">' + renderTreeChildren(sub.children, depth + 1) + '</div>';
      }
    });
    return html;
  }

  // 判断某路径前缀是否在折叠状态（默认全部展开）
  function _collapsedCache() {
    if (!state._collapsed) state._collapsed = {};
    return state._collapsed;
  }
  function isCollapsedOnPath(dp) {
    return !!_collapsedCache()[dp.join("|")];
  }

  // ============== 面包屑 ==============
  function renderBreadcrumb() {
    var wrap = $("fm-breadcrumb");
    if (!wrap) return;
    var parts = ['<span class="fm-crumb' + (state.currentPath.length === 0 ? " active" : "") + '" data-i="0">主菜单</span>'];
    state.currentPath.forEach(function (p, i) {
      parts.push('<span class="fm-crumb-sep">/</span>');
      var cls = (i === state.currentPath.length - 1) ? "fm-crumb active" : "fm-crumb";
      parts.push('<span class="' + cls + '" data-i="' + (i + 1) + '">' + escapeHtml(p) + '</span>');
    });
    wrap.innerHTML = parts.join("");
    Array.prototype.forEach.call(wrap.querySelectorAll(".fm-crumb"), function (el) {
      el.onclick = function () {
        var i = parseInt(el.getAttribute("data-i"), 10);
        if (state.dirty) {
          if (!confirm("有未保存的修改，确定要跳转吗？")) return;
        }
        state.currentPath = state.currentPath.slice(0, i);
        state.dirty = false;
        renderLayout();
      };
    });
  }

  // ============== 右侧编辑器 ==============
  function renderEditor() {
    var wrap = $("fm-tree-editor");
    if (!wrap) return;
    var node = getNodeAtPath(state.currentPath);
    if (!node) {
      wrap.innerHTML = '<div class="fm-loading">节点不存在</div>';
      return;
    }
    var isRoot = state.currentPath.length === 0;
    var children = node.children || {};
    var childKeys = Object.keys(children);

    // 头部：标题 + 操作
    var html = "";
    // 节点 key 编辑（仅子节点）
    if (!isRoot) {
      html += '<div class="fm-card">' +
        '<h2>节点设置</h2>' +
        '<div class="fm-row"><label>节点 key（作为子菜单名 / 用户点击的 data）</label>' +
          '<input type="text" id="fm-node-key" value="' + escapeHtml(pathToName(state.currentPath)) + '" placeholder="签到菜单"></div>' +
        '<div class="fm-row"><label>节点标题（用户看到的卡片内 markdown 文字）</label>' +
          '<textarea id="fm-node-title" rows="2" placeholder="📝 签到系统">' + escapeHtml(node.title || "") + '</textarea></div>' +
        '<div class="fm-tip">💡 修改 key 后将作为子菜单在树中显示（data = 这个 key）。</div>' +
      '</div>';
    } else {
      // root 节点
      html += '<div class="fm-card">' +
        '<h2>主菜单设置</h2>' +
        '<div class="fm-row"><label>顶部图 URL（markdown 内嵌图片）</label>' +
          '<input type="text" id="fm-banner" value="' + escapeHtml(node.banner || "") + '" placeholder="https://..."></div>' +
        '<div class="fm-row"><label>标题</label>' +
          '<input type="text" id="fm-title" value="' + escapeHtml(node.title || "") + '" placeholder="小流萤功能菜单"></div>' +
        '<div class="fm-row"><label>引言（每行一句）</label>' +
          '<textarea id="fm-intro" rows="3" placeholder="每行一句">' + escapeHtml((node.intro || []).join("\n")) + '</textarea></div>' +
        '<div class="fm-row"><label>随机一言</label>' +
          '<label class="fm-check"><input type="checkbox" id="fm-yiyan-on" ' + ((node.yiyan && node.yiyan.enabled) ? 'checked' : '') + '> 启用</label>' +
          '<input type="text" id="fm-yiyan-fmt" value="' + escapeHtml((node.yiyan && node.yiyan.format) || "") + '" placeholder="## {hitokoto}  ——{from_who}《{from}》" style="margin-top:6px;"></div>' +
      '</div>';
    }

    // 按钮行（root 与 子节点都用同一组）
    html += '<div class="fm-card">' +
      '<div class="fm-card-head"><h2>按钮行</h2>' +
        '<button class="fm-btn fm-btn-sm" id="fm-add-row">+ 新增行</button>' +
      '</div>' +
      '<div class="fm-rows" id="fm-rows"></div>' +
    '</div>';

    // 底部链接（仅 root）
    if (isRoot) {
      html += '<div class="fm-card">' +
        '<h2>底部链接</h2>' +
        '<div class="fm-links" id="fm-links"></div>' +
        '<button class="fm-btn fm-btn-sm" id="fm-add-link">+ 新增链接</button>' +
      '</div>';
    }

    // 子菜单管理（任何节点都可建下级）
    html += '<div class="fm-card">' +
      '<div class="fm-card-head"><h2>子菜单（' + childKeys.length + '）</h2>' +
        '<button class="fm-btn fm-btn-sm" id="fm-add-child">+ 新增子菜单</button>' +
      '</div>' +
      '<div class="fm-child-list" id="fm-child-list"></div>' +
    '</div>';

    // 当前节点操作（删除，仅子节点可删）
    if (!isRoot) {
      html += '<div class="fm-card fm-card-danger">' +
        '<h2>危险操作</h2>' +
        '<button class="fm-btn fm-btn-danger" id="fm-del-node">🗑 删除此菜单（包含其全部子菜单和按钮）</button>' +
      '</div>';
    }

    html += '<div class="fm-tip">' +
      '<strong>💡 编辑提示：</strong><br>' +
      '• 任意节点都可以新增 / 删除子菜单，实现无限层级<br>' +
      '• 主菜单按钮的 <code>show_if</code> 用条件过滤（如 <code>checkin_on</code> 表示签到系统开关 on 时才显示）<br>' +
      '• 子菜单按钮的 <code>enter</code>：true=发消息，false=仅触发交互卡片<br>' +
      '• <code>required</code>：外置插件 key（逗号分隔），任一启用时按钮才显示<br>' +
      '• 「返回主菜单」按钮的 data 写 <code>返回主菜单</code> 即可（bot 内置）' +
    '</div>';

    wrap.innerHTML = html;

    // 渲染按钮行 + 链接 + 子菜单列表
    renderRows();
    if (isRoot) renderLinks();
    renderChildList();
    bindEditor();
  }

  // ============== 按钮行渲染 ==============
  function renderRows() {
    var wrap = $("fm-rows");
    if (!wrap) return;
    var node = getNodeAtPath(state.currentPath);
    if (!node) return;
    var rows = node.buttons || [];
    var isRoot = state.currentPath.length === 0;
    var html = "";
    rows.forEach(function (row, ri) {
      html += '<div class="fm-row-block" data-row="' + ri + '">' +
        '<div class="fm-row-head">' +
          '<span class="fm-row-label">第 ' + (ri + 1) + ' 行</span>' +
          '<button class="fm-btn fm-btn-sm" data-act="row-up" data-ri="' + ri + '">↑ 上移</button>' +
          '<button class="fm-btn fm-btn-sm" data-act="row-down" data-ri="' + ri + '">↓ 下移</button>' +
          '<button class="fm-btn fm-btn-sm" data-act="row-add-btn" data-ri="' + ri + '">+ 按钮</button>' +
          '<button class="fm-btn fm-btn-sm fm-btn-danger" data-act="row-del" data-ri="' + ri + '">删除行</button>' +
        '</div>' +
        '<div class="fm-btns" data-ri="' + ri + '">';
      (row || []).forEach(function (btn, bi) {
        html += renderButtonHtml(ri, bi, btn, isRoot);
      });
      html += '</div></div>';
    });
    if (!rows.length) {
      html = '<div class="fm-empty">还没有按钮行，点击下方「+ 新增行」开始</div>';
    }
    wrap.innerHTML = html;
    bindRowEvents();
  }

  function renderButtonHtml(ri, bi, btn, isRoot) {
    var condOptions = CONDITION_OPTIONS.map(function (o) {
      var sel = (btn.show_if || "") === o.v ? ' selected' : '';
      return '<option value="' + escapeHtml(o.v) + '"' + sel + '>' + escapeHtml(o.l) + '</option>';
    }).join('');
    var enterSel = (btn.enter === false) ? '' : ' selected';
    var enterNoSel = (btn.enter === false) ? ' selected' : '';
    var requiredStr = Array.isArray(btn.required) ? btn.required.join(",") : (btn.required || "");
    // 主菜单用 show_if；子菜单用 enter + required
    var showIfRow = isRoot
      ? '<div class="fm-row"><label>条件显示（show_if）</label><select class="fm-b-cond">' + condOptions + '</select></div>'
      : '';
    var enterRow = isRoot ? '' :
      '<div class="fm-row"><label>enter（点击后是否发消息）</label>' +
        '<select class="fm-b-enter">' +
          '<option value="true"' + enterSel + '>true · 发消息</option>' +
          '<option value="false"' + enterNoSel + '>false · 不发消息（仅触发交互）</option>' +
        '</select></div>' +
      '<div class="fm-row"><label>required（外置插件 key，逗号分隔；留空 = 不限）</label>' +
        '<input type="text" class="fm-b-req" value="' + escapeHtml(requiredStr) + '" placeholder="genshin_miao, genshin"></div>';
    return '<div class="fm-btn-block" data-ri="' + ri + '" data-bi="' + bi + '">' +
      '<div class="fm-btn-head">' +
        '<span class="fm-btn-label">按钮 ' + (bi + 1) + '</span>' +
        '<button class="fm-btn fm-btn-sm" data-act="btn-up" data-ri="' + ri + '" data-bi="' + bi + '">↑</button>' +
        '<button class="fm-btn fm-btn-sm" data-act="btn-down" data-ri="' + ri + '" data-bi="' + bi + '">↓</button>' +
        '<button class="fm-btn fm-btn-sm fm-btn-danger" data-act="btn-del" data-ri="' + ri + '" data-bi="' + bi + '">×</button>' +
      '</div>' +
      '<div class="fm-btn-body">' +
        '<div class="fm-row"><label>显示名（emoji + 文字）</label>' +
          '<input type="text" class="fm-b-label" value="' + escapeHtml(btn.label || "") + '" placeholder="📝 按钮"></div>' +
        '<div class="fm-row"><label>点击后机器人收到（指令）</label>' +
          '<input type="text" class="fm-b-data" value="' + escapeHtml(btn.data || "") + '" placeholder="签到菜单"></div>' +
        showIfRow +
        enterRow +
      '</div>' +
    '</div>';
  }

  // ============== 链接渲染（仅 root） ==============
  function renderLinks() {
    var wrap = $("fm-links");
    if (!wrap) return;
    var node = getNodeAtPath(state.currentPath);
    if (!node) return;
    var links = node.links || [];
    var html = "";
    links.forEach(function (lk, li) {
      var condOptions = CONDITION_OPTIONS.map(function (o) {
        var sel = (lk.show_if || "") === o.v ? ' selected' : '';
        return '<option value="' + escapeHtml(o.v) + '"' + sel + '>' + escapeHtml(o.l) + '</option>';
      }).join('');
      html += '<div class="fm-link-block" data-li="' + li + '">' +
        '<div class="fm-btn-head">' +
          '<span class="fm-btn-label">链接 ' + (li + 1) + '</span>' +
          '<button class="fm-btn fm-btn-sm fm-btn-danger" data-act="link-del" data-li="' + li + '">×</button>' +
        '</div>' +
        '<div class="fm-btn-body">' +
          '<div class="fm-row"><label>显示名</label>' +
            '<input type="text" class="fm-l-label" value="' + escapeHtml(lk.label || "") + '" placeholder="📝 反馈"></div>' +
          '<div class="fm-row"><label>URL（自由填写；也支持 <code>${...}</code> 变量）</label>' +
            '<input type="text" class="fm-l-url" value="' + escapeHtml(lk.url || "") + '" placeholder="https://example.com 或 ${feedback.form_url}"></div>' +
          '<div class="fm-row"><label>条件显示（默认始终显示；选其它条件后仅满足时显示）</label>' +
            '<select class="fm-l-cond">' + condOptions + '</select></div>' +
        '</div>' +
      '</div>';
    });
    if (!links.length) html = '<div class="fm-empty">还没有底部链接</div>';
    wrap.innerHTML = html;
    bindLinkEvents();
  }

  // ============== 子菜单列表渲染 ==============
  function renderChildList() {
    var wrap = $("fm-child-list");
    if (!wrap) return;
    var node = getNodeAtPath(state.currentPath);
    if (!node) return;
    var children = node.children || {};
    var keys = Object.keys(children);
    var html = "";
    if (!keys.length) {
      html = '<div class="fm-empty">还没有子菜单（点击「+ 新增子菜单」创建）</div>';
    } else {
      keys.forEach(function (k) {
        var sub = children[k];
        var subKeys = sub && sub.children ? Object.keys(sub.children) : [];
        var btnCount = 0;
        (sub.buttons || []).forEach(function (r) { btnCount += (r || []).length; });
        html += '<div class="fm-child-item" data-key="' + escapeHtml(k) + '">' +
          '<div class="fm-child-info">' +
            '<div class="fm-child-name">📂 ' + escapeHtml(k) + '</div>' +
            '<div class="fm-child-meta">' + btnCount + ' 个按钮 · ' + subKeys.length + ' 个子菜单</div>' +
          '</div>' +
          '<div class="fm-child-actions">' +
            '<button class="fm-btn fm-btn-sm" data-act="child-go" data-key="' + escapeHtml(k) + '">→ 进入编辑</button>' +
            '<button class="fm-btn fm-btn-sm fm-btn-danger" data-act="child-del" data-key="' + escapeHtml(k) + '">×</button>' +
          '</div>' +
        '</div>';
      });
    }
    wrap.innerHTML = html;
    bindChildListEvents();
  }

  // ============== 事件绑定 ==============
  function bindToolbar() {
    $("fm-save").onclick = onSave;
    $("fm-reload").onclick = function () {
      if (state.dirty && !confirm("有未保存的修改，确定要重新加载吗？")) return;
      state.dirty = false;
      loadFromServer();
    };
    $("fm-reset").onclick = onReset;
    $("fm-preview").onclick = showPreview;
  }

  function bindEditor() {
    var isRoot = state.currentPath.length === 0;
    if (isRoot) {
      ["fm-banner", "fm-title", "fm-intro", "fm-yiyan-on", "fm-yiyan-fmt"].forEach(function (id) {
        var el = $(id);
        if (!el) return;
        var ev = el.tagName === "INPUT" && el.type === "checkbox" ? "change" : "input";
        el.addEventListener(ev, function () { collectTopRoot(); markDirty(true); });
      });
      $("fm-add-link").onclick = function () {
        var node = getNodeAtPath(state.currentPath);
        node.links = node.links || [];
        node.links.push({ label: "新链接", url: "" });
        renderLinks();
        markDirty(true);
      };
    } else {
      var keyEl = $("fm-node-key");
      var titleEl = $("fm-node-title");
      if (keyEl) {
        keyEl.addEventListener("input", function () {
          var newKey = keyEl.value.trim();
          var oldKey = pathToName(state.currentPath);
          if (!newKey || newKey === oldKey) return;
          var parent = getParentAtPath(state.currentPath);
          if (!parent) return;
          // 重命名：在父节点的 children 中替换 key
          if (parent.children[newKey]) {
            showToast("已存在同名子菜单", "error");
            return;
          }
          var sub = parent.children[oldKey];
          delete parent.children[oldKey];
          parent.children[newKey] = sub;
          // 更新当前路径
          state.currentPath = state.currentPath.slice(0, -1).concat([newKey]);
          // 同步更新所有引用了 oldKey 的按钮 data（深度搜索整棵树）
          renameDataReferences(state.tree, oldKey, newKey);
          renderLayout();
          markDirty(true);
        });
      }
      if (titleEl) {
        titleEl.addEventListener("input", function () {
          var node = getNodeAtPath(state.currentPath);
          if (node) node.title = titleEl.value;
          markDirty(true);
        });
      }
      var delBtn = $("fm-del-node");
      if (delBtn) {
        delBtn.onclick = function () {
          var nodeName = pathToName(state.currentPath);
          if (!confirmDelete(
            "🗑 确认删除菜单「" + nodeName + "」？\n\n" +
            "• 该菜单及其所有子菜单、按钮将被删除\n" +
            "• 其他菜单中引用此 key 的按钮将变为无效\n" +
            "• 此操作仅在控制台生效，需要点「保存全部」才落盘"
          )) return;
          var parent = getParentAtPath(state.currentPath);
          var key = pathToName(state.currentPath);
          if (parent && parent.children) {
            delete parent.children[key];
            state.currentPath = state.currentPath.slice(0, -1);
            renderLayout();
            markDirty(true);
          }
        };
      }
    }
    $("fm-add-row").onclick = function () {
      var node = getNodeAtPath(state.currentPath);
      node.buttons = node.buttons || [];
      var newBtn = { label: "新按钮", data: "新指令" };
      if (!isRoot) { newBtn.enter = true; newBtn.required = null; }
      else { newBtn.show_if = ""; }
      node.buttons.push([newBtn]);
      renderRows();
      markDirty(true);
    };
    $("fm-add-child").onclick = function () {
      var node = getNodeAtPath(state.currentPath);
      var key = prompt("新子菜单 key（用户点击时会发送这个文本）", "新子菜单");
      if (!key) return;
      key = key.trim();
      if (!key) return;
      node.children = node.children || {};
      if (node.children[key]) {
        showToast("已存在同名子菜单", "error");
        return;
      }
      node.children[key] = {
        title: "📂 " + key,
        buttons: [
          [{ label: "🔙 返回主菜单", data: "返回主菜单", enter: true, required: null }],
        ],
        children: {},
      };
      renderTreeSide();
      renderChildList();
      markDirty(true);
    };
  }

  // 整棵树中，把引用了 oldKey 的按钮 data 改成 newKey
  function renameDataReferences(node, oldKey, newKey) {
    if (!node || typeof node !== "object") return;
    if (Array.isArray(node.buttons)) {
      node.buttons.forEach(function (row) {
        if (Array.isArray(row)) {
          row.forEach(function (b) {
            if (b && b.data === oldKey) b.data = newKey;
          });
        }
      });
    }
    if (node.children && typeof node.children === "object") {
      Object.keys(node.children).forEach(function (k) {
        renameDataReferences(node.children[k], oldKey, newKey);
      });
    }
  }

  function bindRowEvents() {
    var wrap = $("fm-rows");
    if (!wrap) return;
    var node = getNodeAtPath(state.currentPath);
    if (!node) return;
    var isRoot = state.currentPath.length === 0;
    var rows = node.buttons || [];
    wrap.querySelectorAll("[data-act]").forEach(function (btn) {
      btn.onclick = function () {
        var act = btn.getAttribute("data-act");
        var ri = parseInt(btn.getAttribute("data-ri") || "0", 10);
        var bi = parseInt(btn.getAttribute("data-bi") || "-1", 10);
        if (act === "row-up" && ri > 0) {
          var t = rows[ri - 1]; rows[ri - 1] = rows[ri]; rows[ri] = t;
        } else if (act === "row-down" && ri < rows.length - 1) {
          var t2 = rows[ri + 1]; rows[ri + 1] = rows[ri]; rows[ri] = t2;
        } else if (act === "row-del") {
          var rowBtnCount = (rows[ri] || []).length;
          if (!confirmDelete(
            "🗑 确认删除第 " + (ri + 1) + " 行按钮？\n\n" +
            "• 该行包含 " + rowBtnCount + " 个按钮\n" +
            "• 删除后此行所有按钮将不可恢复"
          )) return;
          rows.splice(ri, 1);
        } else if (act === "row-add-btn") {
          var nb = { label: "新按钮", data: "新指令" };
          if (!isRoot) { nb.enter = true; nb.required = null; }
          else { nb.show_if = ""; }
          rows[ri].push(nb);
        } else if (act === "btn-up" && bi > 0) {
          var b = rows[ri][bi - 1]; rows[ri][bi - 1] = rows[ri][bi]; rows[ri][bi] = b;
        } else if (act === "btn-down" && bi < rows[ri].length - 1) {
          var b2 = rows[ri][bi + 1]; rows[ri][bi + 1] = rows[ri][bi]; rows[ri][bi] = b2;
        } else if (act === "btn-del") {
          var delBtnLabel = (rows[ri] && rows[ri][bi] && rows[ri][bi].label) || "未命名";
          if (!confirmDelete(
            "🗑 确认删除按钮「" + delBtnLabel + "」？\n\n" +
            "• 该按钮将被移除\n" +
            "• 删除后不可恢复"
          )) return;
          rows[ri].splice(bi, 1);
        }
        renderRows();
        markDirty(true);
      };
    });
    wrap.querySelectorAll(".fm-btn-block").forEach(function (blk) {
      var ri = parseInt(blk.getAttribute("data-ri"), 10);
      var bi = parseInt(blk.getAttribute("data-bi"), 10);
      var fields = isRoot ? ["label", "data", "cond"] : ["label", "data", "enter", "req"];
      fields.forEach(function (f) {
        var cls = ".fm-b-" + f;
        var el = blk.querySelector(cls);
        if (!el) return;
        var ev = (el.tagName === "SELECT") ? "change" : "input";
        el.addEventListener(ev, function () {
          var btn = rows[ri][bi];
          if (f === "label") btn.label = el.value;
          else if (f === "data") btn.data = el.value;
          else if (f === "cond") btn.show_if = el.value;
          else if (f === "enter") btn.enter = (el.value === "true");
          else if (f === "req") {
            var v = el.value.trim();
            btn.required = v ? v.split(",").map(function (s) { return s.trim(); }).filter(function (s) { return s; }) : null;
          }
          markDirty(true);
        });
      });
    });
  }

  function bindLinkEvents() {
    var wrap = $("fm-links");
    if (!wrap) return;
    var node = getNodeAtPath(state.currentPath);
    if (!node) return;
    var links = node.links || [];
    wrap.querySelectorAll("[data-act='link-del']").forEach(function (btn) {
      btn.onclick = function () {
        var li = parseInt(btn.getAttribute("data-li") || "0", 10);
        var linkLabel = (links[li] && links[li].label) || "未命名";
        if (!confirmDelete(
          "🗑 确认删除底部链接「" + linkLabel + "」？\n\n" +
          "• 该链接及其 URL 配置将被移除\n" +
          "• 删除后不可恢复"
        )) return;
        links.splice(li, 1);
        renderLinks();
        markDirty(true);
      };
    });
    wrap.querySelectorAll(".fm-link-block").forEach(function (blk) {
      var li = parseInt(blk.getAttribute("data-li"), 10);
      ["label", "url", "cond"].forEach(function (f) {
        var cls = ".fm-l-" + f;
        var el = blk.querySelector(cls);
        if (!el) return;
        el.addEventListener("input", function () {
          var lk = links[li];
          if (f === "label") lk.label = el.value;
          else if (f === "url") lk.url = el.value;
          else if (f === "cond") lk.show_if = el.value;
          markDirty(true);
        });
        el.addEventListener("change", function () {
          if (f === "cond") {
            links[li].show_if = el.value;
            markDirty(true);
          }
        });
      });
    });
  }

  function bindChildListEvents() {
    var wrap = $("fm-child-list");
    if (!wrap) return;
    wrap.querySelectorAll("[data-act='child-go']").forEach(function (btn) {
      btn.onclick = function () {
        var k = btn.getAttribute("data-key");
        state.currentPath = state.currentPath.concat([k]);
        state.dirty = false;
        renderLayout();
      };
    });
    wrap.querySelectorAll("[data-act='child-del']").forEach(function (btn) {
      btn.onclick = function () {
        var k = btn.getAttribute("data-key");
        if (!confirmDelete(
          "🗑 确认删除子菜单「" + k + "」？\n\n" +
          "• 其所有子菜单和按钮将一并删除\n" +
          "• 其他菜单中引用此 key 的按钮将变为无效"
        )) return;
        var node = getNodeAtPath(state.currentPath);
        if (node && node.children) {
          delete node.children[k];
          renderTreeSide();
          renderChildList();
          markDirty(true);
        }
      };
    });
  }

  function collectTopRoot() {
    var node = getNodeAtPath(state.currentPath);
    if (!node) return;
    node.banner = $("fm-banner").value;
    node.title = $("fm-title").value;
    node.intro = $("fm-intro").value.split("\n").filter(function (s) { return s.trim(); });
    node.yiyan = node.yiyan || {};
    node.yiyan.enabled = $("fm-yiyan-on").checked;
    node.yiyan.format = $("fm-yiyan-fmt").value;
  }

  function markDirty(d) {
    state.dirty = d;
    var el = $("fm-dirty");
    if (el) el.textContent = d ? "● 有未保存的修改" : "";
  }

  // ============== 统一二次确认 ==============
  // 用于所有删除操作，防止误触
  function confirmDelete(message) {
    // 第一次确认
    if (!confirm(message)) return false;
    // 第二次确认（强提示）
    if (!confirm("⚠️ 再次确认：此操作不可撤销，确定要删除吗？")) return false;
    return true;
  }

  // ============== 保存 / 重置 / 预览 ==============
  function onSave() {
    // 收集主菜单的 banner/title/intro/yiyan
    if (state.currentPath.length === 0) collectTopRoot();
    // 收集当前节点的 title（如果还在编辑器中）
    if (state.currentPath.length > 0) {
      var tEl = $("fm-node-title");
      var node = getNodeAtPath(state.currentPath);
      if (tEl && node) node.title = tEl.value;
    }
    fetch(API_BASE + "/api/menu/tree", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tree: state.tree })
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.ok) {
          showToast("✅ 菜单树保存成功（bot 已热重载）", "ok");
          markDirty(false);
        } else {
          showToast("❌ " + (data.message || data.error || "保存失败"), "error");
        }
      })
      .catch(function (e) { showToast("❌ 网络错误：" + e.message, "error"); });
  }

  function onReset() {
    if (!confirmDelete(
      "⏮ 确认恢复全部菜单树为默认？\n\n" +
      "• 所有自定义内容（按钮 / 子菜单）将丢失\n" +
      "• 主菜单的 banner/标题/引言也会被还原"
    )) return;
    fetch(API_BASE + "/api/menu/tree/reset", { method: "POST" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.ok) {
          showToast("✅ 已恢复默认（bot 已热重载）", "ok");
          state.dirty = false;
          state.currentPath = [];
          loadFromServer();
        } else {
          showToast("❌ " + (data.message || data.error || "恢复失败"), "error");
        }
      })
      .catch(function (e) { showToast("❌ 网络错误：" + e.message, "error"); });
  }

  function showPreview() {
    if (state.currentPath.length === 0) {
      // 主菜单预览
      if (state.tree && state.tree.root) {
        collectTopRoot();
        var r = state.tree.root;
        showPreviewModal(
          r.banner, r.title, r.intro || [],
          (r.buttons || []).map(function (row) {
            return (row || []).map(function (b) { return { label: b.label, type: "btn" }; });
          }),
          (r.links || []).map(function (l) { return { label: l.label, type: "link" }; })
        );
      }
    } else {
      var node = getNodeAtPath(state.currentPath);
      if (!node) return;
      var tEl = $("fm-node-title");
      if (tEl) node.title = tEl.value;
      showPreviewModal(
        "", node.title || pathToName(state.currentPath), [],
        node.buttons || [],
        []
      );
    }
  }

  function showPreviewModal(banner, title, intro, buttonRows, links) {
    var modal = $("xfy-fm-preview-modal");
    if (modal) modal.remove();
    modal = document.createElement("div");
    modal.id = "xfy-fm-preview-modal";
    modal.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:99999;display:flex;align-items:center;justify-content:center;padding:24px;";
    var card = document.createElement("div");
    card.style.cssText = "background:#fff;border-radius:14px;max-width:520px;width:100%;max-height:90vh;overflow:auto;box-shadow:0 20px 60px rgba(0,0,0,.25);";
    var introHtml = (intro || []).map(function (s) { return '<div>' + escapeHtml(s).replace(/\\n/g, "<br>") + '</div>'; }).join("");
    var rowsHtml = (buttonRows || []).map(function (row) {
      var btns = (row || []).map(function (b) {
        return '<button class="fm-qq-btn">' + escapeHtml(b.label || "") + '</button>';
      }).join("");
      return '<div class="fm-qq-row">' + btns + '</div>';
    }).join("");
    var linksHtml = (links || []).map(function (l) {
      return '<div class="fm-qq-row"><button class="fm-qq-btn fm-qq-link">' + escapeHtml(l.label || "") + '</button></div>';
    }).join("");
    card.innerHTML =
      '<div style="padding:18px 20px;border-bottom:1px solid #e0e2f0;display:flex;align-items:center;justify-content:space-between;background:#fafbfc;border-radius:14px 14px 0 0;">' +
        '<h2 style="margin:0;font-size:15px;font-weight:700;color:#1f2240 !important;letter-spacing:0.3px;">📱 QQ 消息预览（模拟）</h2>' +
        '<button id="fm-preview-close" title="关闭预览" style="background:#f0f2f7;border:0;width:28px;height:28px;border-radius:6px;font-size:20px;line-height:1;cursor:pointer;color:#4a5072;display:flex;align-items:center;justify-content:center;transition:background .12s;" onmouseover="this.style.background=\'#e0e4ee\';this.style.color=\'#1f2240\';" onmouseout="this.style.background=\'#f0f2f7\';this.style.color=\'#4a5072\';">×</button>' +
      '</div>' +
      '<div style="padding:20px;background:#ffffff;color:#1f2240;">' +
        (banner ? '<img src="' + escapeHtml(banner) + '" style="width:150px;height:150px;border-radius:8px;display:block;margin:0 auto 12px;" onerror="this.style.display=\'none\'">' : '') +
        (title ? '<div style="font-size:14px;color:#1f2240;font-weight:600;line-height:1.7;white-space:pre-wrap;margin-bottom:12px;padding:10px 12px;background:#f4f6fa;border-radius:6px;border-left:3px solid #3b6ef5;">' + escapeHtml(title) + '</div>' : '') +
        (introHtml ? '<div style="text-align:center;color:#4a5072;font-size:13px;line-height:1.7;margin-bottom:12px;padding:8px 12px;background:#fafbfc;border-radius:6px;">' + introHtml + '</div>' : '') +
        '<div class="fm-qq-keyboard">' + rowsHtml + linksHtml + '</div>' +
      '</div>';
    modal.appendChild(card);
    document.body.appendChild(modal);
    modal.onclick = function (e) { if (e.target === modal) modal.remove(); };
    $("fm-preview-close").onclick = function () { modal.remove(); };
  }

  // ============== 入口暴露 ==============
  window.XFY_FM_renderMenu = function () {
    state.currentPath = [];
    state.dirty = false;
    render();
  };
})();
