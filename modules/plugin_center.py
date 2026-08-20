"""
插件中心：后端渲染层

- 负责聚合「已装插件 + 远程仓库目录 + 内置测试插件」三源数据
- 区分错误类型（网络/超时/404/解析/后端挂），为前端返回结构化 error.code
- 提供统一的 install / uninstall / set-enabled / reload 入口
- 不再依赖 charts.js 里的前端散落逻辑

错误码约定（error.code）
------------------------
- not_initialized   : 后端进程未就绪（极少见）
- network_timeout   : 远程仓库拉取超时（多见于国内被墙）
- network_dns       : DNS 解析失败
- network_refused   : 远程拒绝连接
- http_404          : index.json 404（仓库或子目录错）
- http_5xx          : 远程 5xx
- parse             : index.json 不是合法 JSON
- backend_down      : 本地后端 HTTP 接口连不上（用户截图典型场景）
"""

import io
import json as _json
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import re
from typing import Any, Dict, List, Optional


# 复用 plugin_registry 已有的工具
from modules import plugin_registry as _pr


_LOCK = threading.RLock()


# ============================================================
# 错误归类
# ============================================================
def _classify_remote_error(err: Exception) -> Dict[str, str]:
    """把 urllib/socket 异常归类为 {code, message, hint}。"""
    s = str(err) or ""
    low = s.lower()
    code = "network_other"
    hint = "请稍后重试，或在「运行设置 → 插件市场」切换到 jsDelivr 镜像。"

    if isinstance(err, socket.timeout) or "timed out" in low or ("timeout" in low and "read" in low):
        code = "network_timeout"
        hint = (
            "远程仓库响应超时，多见于国内访问 raw.githubusercontent.com 被墙。\n"
            "建议改用 jsDelivr CDN：\n"
            "  https://cdn.jsdelivr.net/gh/GS240186/firefiy-QQofficial-bot-piugins@main/\n"
            "或备选 gh-proxy.com 镜像。"
        )
    elif isinstance(err, urllib.error.HTTPError):
        if err.code == 404:
            code = "http_404"
            hint = (
                "远程仓库未找到 index.json。请确认仓库地址正确，"
                "且 index.json 位于仓库根目录或指定子目录下。"
            )
        elif 500 <= err.code < 600:
            code = "http_5xx"
            hint = "远程仓库服务端错误，请稍后重试。"
        else:
            code = "http_%d" % err.code
            hint = "远程仓库返回 HTTP %d。" % err.code
    elif isinstance(err, urllib.error.URLError):
        reason = getattr(err, "reason", None)
        if isinstance(reason, socket.gaierror):
            code = "network_dns"
            hint = "DNS 解析失败，请检查网络或仓库域名。"
        elif "ConnectionRefused" in str(reason) or "refused" in low:
            code = "network_refused"
            hint = "远程拒绝连接，请检查仓库地址或代理设置。"
        else:
            code = "network_other"
            hint = "网络错误：%s" % (reason or s)
    elif "Temporary failure in name resolution" in s or "no such host" in low:
        code = "network_dns"
        hint = "DNS 解析失败，请检查网络。"
    return {"code": code, "message": s, "hint": hint}


# ============================================================
# 远程目录拉取（带错误码）
# ============================================================
def fetch_remote_catalog(force: bool = False) -> Dict[str, Any]:
    """拉取远程仓库 index.json。返回：
    {
      ok: bool,
      catalog: [...],                # 远程插件列表
      builtin_test: [...],           # 内置测试插件
      repo_url: str,
      source: 'cache' | 'remote' | 'cache_stale' | 'local_only',
      error: { code, message, hint }  # 仅失败时
    }
    """
    base = _pr.get_remote_market_base()
    builtin_test = _pr.get_market_catalog() or []
    out = {
        "ok": True,
        "catalog": [],
        "builtin_test": builtin_test,
        "repo_url": base,
        "source": "local_only",
    }

    # 命中本地缓存（10 分钟内）
    cache_file = _pr._MARKET_CACHE_FILE
    now = time.time()
    cached = None
    try:
        if os.path.isfile(cache_file) and not force:
            age = now - os.path.getmtime(cache_file)
            if age < _pr._MARKET_CACHE_TTL:
                with io.open(cache_file, "r", encoding="utf-8") as f:
                    cached = _json.load(f)
    except Exception:
        cached = None

    if cached is not None and not force:
        return {
            "ok": True,
            "catalog": [_pr._mark_remote_installed(p) for p in cached.get("plugins", [])],
            "builtin_test": builtin_test,
            "repo_url": base,
            "source": "cache",
        }

    # 尝试远程拉取
    subdir = _pr.get_remote_market_subdir() or _pr.REMOTE_MARKET_DIR
    cache_bust = "?t=%d" % int(now) if force else ""
    candidate_paths = [base + "index.json" + cache_bust]
    if subdir:
        candidate_paths.append(base.rstrip("/") + "/" + subdir + "/index.json" + cache_bust)

    raw = None
    last_err = None
    for path in candidate_paths:
        try:
            raw = _pr._http_get_text(path)
            break
        except Exception as e:
            last_err = e
            continue

    if raw is None:
        cls = _classify_remote_error(last_err) if last_err else {"code": "network_other", "message": "unknown", "hint": ""}
        # 降级：返回陈旧缓存
        if cached is not None:
            return {
                "ok": True,
                "catalog": [_pr._mark_remote_installed(p) for p in cached.get("plugins", [])],
                "builtin_test": builtin_test,
                "repo_url": base,
                "source": "cache_stale",
                "error": cls,
            }
        return {
            "ok": False,
            "catalog": [],
            "builtin_test": builtin_test,
            "repo_url": base,
            "source": "local_only",
            "error": cls,
        }

    # 解析 JSON
    try:
        data = _json.loads(raw)
    except Exception as e:
        return {
            "ok": False,
            "catalog": [],
            "builtin_test": builtin_test,
            "repo_url": base,
            "source": "local_only",
            "error": {
                "code": "parse",
                "message": "index.json 不是合法 JSON：%s" % e,
                "hint": "请确认远程仓库的 index.json 格式正确。",
            },
        }

    plugins = _pr._enrich_with_meta(
        [_pr._mark_remote_installed(p) for p in data.get("plugins", [])],
        bust=force,
    )

    # 写缓存
    try:
        cache_dir = _pr._MARKET_CACHE_DIR
        if not os.path.isdir(cache_dir):
            os.makedirs(cache_dir, exist_ok=True)
        with io.open(cache_file, "w", encoding="utf-8") as f:
            _json.dump({"plugins": plugins}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    return {
        "ok": True,
        "catalog": plugins,
        "builtin_test": builtin_test,
        "repo_url": base,
        "source": "remote",
    }


# ============================================================
# 已装插件列表（含系统总开关状态）
# ============================================================
def list_installed_plugins() -> List[Dict[str, Any]]:
    """返回已注册插件（内置 + 外置），每条附带：
    - system_enabled: bot 主代码里 is_feature_enabled(key) 的当前值（True=系统总开关开启）
    - enabled:        插件级开关（外置走 _EXTERNAL_ENABLED，内置统一为 True）
    - is_external:    是否外置
    - is_master:      是否 master 类别（如 "signin" 这种大类）
    前端可用 is_available = system_enabled && enabled 计算"是否真正生效"。
    """
    out = []
    switches = _get_system_switches_snapshot()
    for d in _pr.snapshot_plugins():
        # 跳过测试插件（demo_echo/ping/roll 等）：它们跟随主项目，不属于用户可管理项
        if d.is_test_plugin:
            continue
        # 1) 内置 master 类别（如 signin/video/...）也展示，用于让用户看到总开关位置
        # 2) 外置插件：和 master 同 key 时显示在 master 下；不同 key 时单独成行
        sys_key = d.key  # 系统总开关的 key = 插件 key
        system_enabled = switches.get(sys_key)
        if system_enabled is None:
            # 缺省视为开启（与 console_server 默认行为一致）
            system_enabled = True
        out.append({
            "key": d.key,
            "name": d.name,
            "description": d.description,
            "category": d.category or "_misc",
            "priority": d.priority,
            "is_external": bool(d.is_external),
            "enabled": _pr.is_plugin_enabled(d.key) if d.is_external else True,
            "system_enabled": bool(system_enabled),
            "is_test_plugin": bool(d.is_test_plugin),
        })
    return out


def _get_system_switches_snapshot() -> Dict[str, bool]:
    """从 console_server 读取系统总开关快照（不依赖进程内单例，方便测试）。"""
    try:
        import console_server  # 软依赖
        if hasattr(console_server, "_system_switches"):
            return dict(console_server._system_switches)
        if hasattr(console_server, "get_system_switches"):
            return dict(console_server.get_system_switches() or {})
    except Exception:
        pass
    return {}


# ============================================================
# 按 category 分组（前端聚合展示用）
# ============================================================
def plugins_by_category() -> Dict[str, List[Dict[str, Any]]]:
    """按 category 分组（内置+外置），保留顺序：test > 已知分类 > 其他。"""
    out: Dict[str, List[Dict[str, Any]]] = {}
    switches = _get_system_switches_snapshot()
    for d in _pr.snapshot_plugins():
        if d.is_test_plugin:
            continue
        cat = d.category or "_misc"
        sys_enabled = switches.get(d.key)
        if sys_enabled is None:
            sys_enabled = True
        out.setdefault(cat, []).append({
            "key": d.key,
            "name": d.name,
            "description": d.description,
            "priority": d.priority,
            "is_external": bool(d.is_external),
            "system_enabled": bool(sys_enabled),
        })
    for cat in out:
        out[cat].sort(key=lambda x: (x.get("priority") or 9999, x.get("key") or ""))
    return out


# ============================================================
# 安装 / 卸载 / 启用切换 / 热加载
# ============================================================
def install_plugin(key: str, raw_url: Optional[str] = None) -> Dict[str, Any]:
    """统一入口：远程目录插件走 install_remote_market_plugin，本地模板走 install_market_plugin。"""
    if not key:
        return {"ok": False, "code": "bad_request", "error": "缺少插件 key"}
    if raw_url:
        return _pr.install_remote_market_plugin(key, raw_url)
    return _pr.install_market_plugin(key)


def uninstall_plugin(key: str) -> Dict[str, Any]:
    """卸载插件：删除文件并注销注册表项。"""
    if not key:
        return {"ok": False, "code": "bad_request", "error": "缺少插件 key"}
    # 单文件
    p = os.path.join(_pr._PLUGINS_DIR, key + ".py")
    if os.path.isfile(p):
        try:
            os.remove(p)
        except Exception as e:
            return {"ok": False, "code": "io_error", "error": "删除文件失败：%s" % e}
        _pr.unregister_plugin(key)
        _pr.reload_external_plugins(force=True)
        return {"ok": True, "removed": p}
    # 目录包
    d = os.path.join(_pr._PLUGINS_DIR, key)
    if os.path.isdir(d) and os.path.isfile(os.path.join(d, "manifest.json")):
        import shutil
        try:
            shutil.rmtree(d, ignore_errors=True)
        except Exception as e:
            return {"ok": False, "code": "io_error", "error": "删除目录失败：%s" % e}
        _pr.unregister_plugin(key)
        _pr.reload_external_plugins(force=True)
        return {"ok": True, "removed": d}
    return {"ok": False, "code": "not_found", "error": "插件未安装"}


def set_enabled(key: str, enabled: bool, kind: str = "all") -> Dict[str, Any]:
    """切换插件启用状态。
    - kind="system" : 写 _system_switches（is_feature_enabled），并自动联动 _EXTERNAL_ENABLED
                       （系统总开关 = 整个插件对外可见性；开=启用，关=禁用）
    - kind="plugin" : 只写 _EXTERNAL_ENABLED（仅外置有意义）
    - kind="all"    : 两个都写（兼容旧调用）
    简化为单「系统」开关后，kind="system" 是前端唯一入口，自动联动外置开关。
    """
    if not key:
        return {"ok": False, "code": "bad_request", "error": "缺少插件 key"}
    d = _pr.get_plugin(key)
    is_ext = bool(d and d.is_external)
    written = []
    if (kind == "plugin" or kind == "all") and is_ext:
        _pr.set_plugin_enabled(key, bool(enabled))
        written.append("plugin")
    if kind == "system" or kind == "all":
        try:
            import console_server
            if hasattr(console_server, "set_feature_enabled_global"):
                console_server.set_feature_enabled_global(key, bool(enabled))
                written.append("system")
        except Exception as e:
            return {"ok": False, "code": "system_switch_failed", "error": "写系统开关失败：%s" % e}
        # 联动：外置插件的系统总开关关闭时，同步关闭外置开关（避免被绕过）
        if is_ext:
            try:
                _pr.set_plugin_enabled(key, bool(enabled))
                if "plugin" not in written:
                    written.append("plugin")
            except Exception:
                pass
    return {"ok": True, "key": key, "enabled": bool(enabled), "written": written, "is_external": is_ext}


# ============================================================
# 插件自定义配置（config.yaml / config.json）
# ============================================================
def _plugin_dir(key: str) -> Optional[str]:
    """根据 plugin key 返回插件目录绝对路径。"""
    if not key:
        return None
    safe = "".join(c for c in key if c.isalnum() or c in ("_", "-", "."))
    if not safe or safe != key:
        return None
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugins", safe)
    return base if os.path.isdir(base) else None


def _plugin_config_path(key: str) -> Optional[str]:
    """返回 config.yaml 或 config.json 路径（优先 yaml，不存在则用 json，都不存在则返回 yaml 默认路径）。"""
    d = _plugin_dir(key)
    if not d:
        return None
    yp = os.path.join(d, "config.yaml")
    jp = os.path.join(d, "config.json")
    if os.path.isfile(yp):
        return yp
    if os.path.isfile(jp):
        return jp
    return yp  # 默认保存到 config.yaml


def get_plugin_config(key: str) -> Dict[str, Any]:
    """读取外置插件的自定义配置。返回：
    {ok, key, exists, values, schema, defaults, path}
    - values: 当前配置 dict
    - schema: 插件声明的 schema（来自 PLUGIN_DICT["config_schema"] 或 plugin.main 模块的 PLUGIN_CONFIG_SCHEMA）
    - defaults: schema 中每个字段的 default 聚合
    - path: 配置文件绝对路径
    """
    if not key:
        return {"ok": False, "code": "bad_request", "error": "缺少 key"}
    d = _pr.get_plugin(key)
    if not d or not d.is_external:
        return {"ok": False, "code": "not_external", "error": "该插件不是外置插件或未安装"}
    path = _plugin_config_path(key)
    values: Dict[str, Any] = {}
    exists = False
    if path and os.path.isfile(path):
        exists = True
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read()
            if path.endswith(".json"):
                values = _json.loads(raw) if raw.strip() else {}
            else:
                # 极简 yaml：仅支持 key: value / key: [a, b] / 嵌套字典
                values = _mini_yaml_load(raw)
        except Exception as e:
            return {"ok": False, "code": "read_failed", "error": "读取配置失败：%s" % e}

    # schema 抓取：优先 importlib 直接 import 模块拿 PLUGIN 字典，fallback 到 dispatch.__globals__
    schema: List[Dict[str, Any]] = []
    try:
        # 1) 优先 importlib.import_module 拿模块顶层 PLUGIN 字典（最可靠）
        #    支持两种结构：plugins.<key>.main（目录包） / plugins.<key>（单文件）
        try:
            import importlib
            for mod_name in (f"plugins.{key}.main", f"plugins.{key}"):
                try:
                    mod = importlib.import_module(mod_name)
                    pl = getattr(mod, "PLUGIN", None)
                    if isinstance(pl, dict) and isinstance(pl.get("config_schema"), list):
                        schema = list(pl["config_schema"])
                        break
                    pl_schema = getattr(mod, "PLUGIN_CONFIG_SCHEMA", None)
                    if isinstance(pl_schema, list):
                        schema = list(pl_schema)
                        break
                except ImportError:
                    continue
                except Exception:
                    continue
        except Exception:
            pass
        # 2) fallback: 从 PluginDescriptor 的 dispatch / handle_callback 函数的 __globals__ 找 PLUGIN
        if not schema and d is not None:
            cand = d.dispatch if d.dispatch else (d.handle_callback if d.handle_callback else None)
            if cand is not None and getattr(cand, "__globals__", None):
                g = cand.__globals__
                plugin_dict = g.get("PLUGIN")
                if isinstance(plugin_dict, dict) and isinstance(plugin_dict.get("config_schema"), list):
                    schema = list(plugin_dict["config_schema"])
    except Exception:
        schema = []

    # 计算 defaults
    defaults: Dict[str, Any] = {}
    for f in schema:
        if isinstance(f, dict) and "key" in f and "default" in f:
            defaults[f["key"]] = f["default"]

    # 合并：defaults ⊇ values（缺失字段补默认）
    merged: Dict[str, Any] = dict(defaults)
    if isinstance(values, dict):
        for k, v in values.items():
            merged[k] = v

    return {
        "ok": True,
        "key": key,
        "exists": exists,
        "values": merged,
        "schema": schema,
        "defaults": defaults,
        "path": path,
    }


def save_plugin_config(key: str, values: Dict[str, Any]) -> Dict[str, Any]:
    """保存外置插件的自定义配置。会按 schema 做轻量校验。"""
    cfg = get_plugin_config(key)
    if not cfg.get("ok"):
        return cfg
    path = cfg.get("path") or _plugin_config_path(key)
    schema = cfg.get("schema") or []

    # 校验：按 schema 过滤未知字段 / 转换类型
    cleaned: Dict[str, Any] = {}
    allowed_keys = set()
    for f in schema:
        if not isinstance(f, dict) or "key" not in f:
            continue
        k = f["key"]
        allowed_keys.add(k)
        v = values.get(k, f.get("default"))
        t = (f.get("type") or "string").lower()
        try:
            if t == "number" or t == "int" or t == "float":
                v = float(v) if v is not None and v != "" else f.get("default", 0)
                if t == "int":
                    v = int(v)
            elif t == "boolean" or t == "bool":
                v = bool(v) and str(v).lower() not in ("false", "0", "no", "")
            elif t == "select":
                if "options" in f and v not in f["options"]:
                    v = f.get("default", f["options"][0] if f["options"] else None)
            else:
                v = "" if v is None else str(v)
        except Exception:
            v = f.get("default")
        cleaned[k] = v
    # schema 为空时：直接接受所有 values
    if not schema:
        for k, v in values.items():
            if isinstance(v, (str, int, float, bool, list)):
                cleaned[k] = v

    # 写文件（yaml 走极简 dump，json 走 json.dump）
    try:
        if path and path.endswith(".json"):
            with open(path, "w", encoding="utf-8") as f:
                _json.dump(cleaned, f, ensure_ascii=False, indent=2)
        else:
            assert path, "无法确定配置文件路径"
            with open(path, "w", encoding="utf-8") as f:
                f.write(_mini_yaml_dump(cleaned))
    except Exception as e:
        return {"ok": False, "code": "write_failed", "error": "写入失败：%s" % e}

    return {"ok": True, "key": key, "saved": cleaned, "path": path, "message": "已保存"}


# ============================================================
#  插件元数据（_meta）：从控制台可编辑的"基础信息"
#  - display_name: 显示名（覆盖 PLUGIN["name"]）
#  - description: 描述/触发指令（覆盖 PLUGIN["description"]）
#  - priority: 排序优先级（覆盖 PLUGIN["priority"]）
#  - aliases: 额外别名列表（合并到 _EXACT_KEYWORDS）
#  - param_hint: 参数错误时提示文案
#  存储：plugins/<key>/config.yaml 的 _meta 段（与 config values 共存）
# ============================================================

_META_FIELDS = ("display_name", "description", "priority", "aliases", "param_hint")


def _read_plugin_yaml_raw(key: str) -> Dict[str, Any]:
    """读取 plugins/<key>/config.yaml 原始 dict（用于提取 _meta）。"""
    path = _plugin_config_path(key)
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception:
        return {}
    if path.endswith(".json"):
        try:
            return _json.loads(text)
        except Exception:
            return {}
    try:
        return _mini_yaml_load(text)
    except Exception:
        return {}


def get_plugin_meta(key: str) -> Dict[str, Any]:
    """读取插件元数据（控制台可编辑的基础信息）。"""
    if not key:
        return {"ok": False, "code": "bad_request", "error": "缺少 key"}
    raw = _read_plugin_yaml_raw(key)
    meta = raw.get("_meta") or {}
    if not isinstance(meta, dict):
        meta = {}

    # 兜底：与 PLUGIN dict 合并，给前端默认值
    defaults: Dict[str, Any] = {}
    try:
        d = _pr.get_plugin(key)
        if d is not None and d.is_external:
            cand = d.dispatch if d.dispatch else (d.handle_callback if d.handle_callback else None)
            if cand is not None and getattr(cand, "__globals__", None):
                plugin_dict = cand.__globals__.get("PLUGIN")
                if isinstance(plugin_dict, dict):
                    defaults["display_name"] = plugin_dict.get("name") or d.name or key
                    defaults["description"] = plugin_dict.get("description") or ""
                    defaults["priority"] = plugin_dict.get("priority") or 50
                    defaults["aliases"] = list(plugin_dict.get("aliases") or []) if isinstance(plugin_dict.get("aliases"), list) else []
                    defaults["param_hint"] = plugin_dict.get("param_hint") or ""
    except Exception:
        pass

    # 任何字段缺省时用 PLUGIN 兜底
    for f in _META_FIELDS:
        if f not in meta or meta.get(f) is None:
            if f in defaults:
                meta[f] = defaults[f]
        # 补 default
    if "aliases" not in meta or not isinstance(meta.get("aliases"), list):
        meta["aliases"] = list(defaults.get("aliases") or [])

    return {
        "ok": True,
        "key": key,
        "meta": {
            "display_name": str(meta.get("display_name") or ""),
            "description": str(meta.get("description") or ""),
            "priority": int(meta.get("priority") or defaults.get("priority") or 50),
            "aliases": [str(a).strip() for a in (meta.get("aliases") or []) if str(a).strip()],
            "param_hint": str(meta.get("param_hint") or ""),
        },
        "path": _plugin_config_path(key),
    }


def save_plugin_meta(key: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    """保存插件元数据（基础信息）。保留 _meta 之外的 config 字段。"""
    if not key:
        return {"ok": False, "code": "bad_request", "error": "缺少 key"}
    path = _plugin_config_path(key)
    if not path:
        return {"ok": False, "code": "no_plugin_dir", "error": "未找到插件目录"}

    # 读取原始数据，保留非 _meta 段
    raw = _read_plugin_yaml_raw(key)
    if "_meta" in raw and not isinstance(raw["_meta"], dict):
        del raw["_meta"]
    new_meta: Dict[str, Any] = {}
    for f in _META_FIELDS:
        if f == "priority":
            try:
                new_meta[f] = int(meta.get(f) or 50)
            except Exception:
                new_meta[f] = 50
        elif f == "aliases":
            aliases = meta.get(f) or []
            if isinstance(aliases, str):
                # 支持 "a, b, c" / "a、b、c" / "a b c" 三种分隔
                aliases = re.split(r"[,，、\s]+", aliases)
            if not isinstance(aliases, list):
                aliases = []
            new_meta[f] = [str(a).strip() for a in aliases if str(a).strip()]
        else:
            new_meta[f] = "" if meta.get(f) is None else str(meta.get(f))
    raw["_meta"] = new_meta

    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if path.endswith(".json"):
            with open(path, "w", encoding="utf-8") as f:
                _json.dump(raw, f, ensure_ascii=False, indent=2)
        else:
            with open(path, "w", encoding="utf-8") as f:
                f.write(_mini_yaml_dump(raw))
    except Exception as e:
        return {"ok": False, "code": "write_failed", "error": "写入失败：%s" % e}

    # 通知 bot 热更新触发指令
    try:
        from bot import _refresh_plugin_meta_aliases
        _refresh_plugin_meta_aliases()
    except Exception:
        pass

    return {"ok": True, "key": key, "saved_meta": new_meta, "path": path, "message": "已保存基础信息"}


def get_all_plugin_metas() -> Dict[str, Dict[str, Any]]:
    """批量读取所有外置插件的 meta（供 bot 启动/重载用）。返回 {key: {display_name, description, priority, aliases, param_hint}}"""
    out: Dict[str, Dict[str, Any]] = {}
    try:
        for d in _pr.list_external_plugins():
            r = get_plugin_meta(d.key)
            if r.get("ok"):
                out[d.key] = r["meta"]
    except Exception:
        pass
    return out


def _mini_yaml_load(text: str) -> Dict[str, Any]:
    """极简 yaml 解析：仅支持 key: value / 列表 / 嵌套 dict（2 空格缩进）。"""
    out: Dict[str, Any] = {}
    stack = [(-1, out)]  # (indent, dict)
    for line in text.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        s = line.strip()
        if ":" not in s:
            continue
        k, _, v = s.partition(":")
        k = k.strip()
        v = v.strip()
        # 找到当前 indent 对应的父 dict
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1] if stack else out
        if v == "":
            new_dict: Dict[str, Any] = {}
            parent[k] = new_dict
            stack.append((indent, new_dict))
        elif v.startswith("[") and v.endswith("]"):
            try:
                inner = v[1:-1].strip()
                if inner:
                    items = [x.strip().strip("'\"") for x in inner.split(",")]
                else:
                    items = []
                parent[k] = items
            except Exception:
                parent[k] = v
        elif v.lower() in ("true", "false"):
            parent[k] = (v.lower() == "true")
        else:
            # 尝试解析为数字
            try:
                if "." in v:
                    parent[k] = float(v)
                else:
                    parent[k] = int(v)
            except Exception:
                parent[k] = v.strip("'\"")
    return out


def _mini_yaml_dump(obj: Dict[str, Any], indent: int = 0) -> str:
    """极简 yaml dump：嵌套 dict 用 2 空格缩进。"""
    lines: List[str] = []
    pad = "  " * indent
    for k, v in obj.items():
        if isinstance(v, dict):
            lines.append("%s%s:" % (pad, k))
            lines.append(_mini_yaml_dump(v, indent + 1))
        elif isinstance(v, list):
            items = ", ".join(("'%s'" % str(x)) if not isinstance(x, (int, float, bool)) else str(x) for x in v)
            lines.append("%s%s: [%s]" % (pad, k, items))
        elif isinstance(v, bool):
            lines.append("%s%s: %s" % (pad, k, "true" if v else "false"))
        elif isinstance(v, (int, float)):
            lines.append("%s%s: %s" % (pad, k, v))
        else:
            s = str(v).replace("'", "\\'")
            lines.append("%s%s: '%s'" % (pad, k, s))
    return "\n".join(lines) + ("\n" if lines else "")


def reload_external() -> Dict[str, Any]:
    """热加载外置插件。"""
    stats = _pr.reload_external_plugins(force=True) or {}
    return {"ok": True, "stats": stats}


# ============================================================
# 一站式：聚合渲染插件中心两页需要的数据
# ============================================================
def get_config_payload(force_remote: bool = False) -> Dict[str, Any]:
    """聚合「插件配置」页所需数据。"""
    return {
        "ok": True,
        "plugins": list_installed_plugins(),
        "by_category": plugins_by_category(),
    }


def get_market_payload(force_remote: bool = False) -> Dict[str, Any]:
    """聚合「插件市场」页所需数据。"""
    return fetch_remote_catalog(force=force_remote)


def get_repo_info() -> Dict[str, Any]:
    """返回当前生效与默认的仓库配置，供「运行设置」展示。"""
    return {
        "ok": True,
        "effective": {
            "repo_url": _pr.get_remote_market_base(),
            "subdir": _pr.get_remote_market_subdir(),
        },
        "default": {
            "repo_url": _pr._DFLT_REPO_URL or "https://github.com/GS240186/firefiy-QQofficial-bot-piugins",
            "branch": _pr._DFLT_BRANCH or "main",
            "subdir": _pr._DFLT_SUBDIR or "",
        },
        "mirror_hint": _pr._MARKET_MIRROR_HINT,
    }
