# -*- coding: utf-8 -*-
"""
插件注册表（内置插件 + 外置插件统一契约）

设计目标
--------
把 bot 的功能模块（签到/工具/学习/音乐/视频/图片/游戏/小说/群管，即 modules/ 下的
「内置插件」）与用户自定义扩展（plugins/ 下的「外置插件」）收敛为同一套契约：
每个插件注册一个 PluginDescriptor，对外暴露统一的 async dispatch(ctx)。

分发链（bot._handle_message_inner）改为按 DISPATCH_PLAN 顺序遍历注册表：
- 内置插件：由 bot.py 在 manager 实例化后注册，适配器精确复刻现有 handle_command 调用，
  保证行为零回归；
- 外置插件：由 scan_external_plugins() 用 importlib 动态加载 plugins/ 下模块，支持热加载。

约定
----
- 内置插件统一通过 register_plugin(PluginDescriptor(...)) 注册，key 与 is_feature_enabled 的功能开关键一致。
- 外置插件模块在 plugins/ 下，需暴露模块级 PLUGIN 描述符（dict，含 key/name/priority/handle/description）
  或定义 async def handle(ctx)->bool。
- PluginContext 携带分发所需的全部字段；各适配器只取自己需要的字段。
- 外置插件可用 ctx.reply(text) 便捷回复（底层走 modules.common.send_text）。
"""

import importlib.util
import io
import json as _json
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class PluginContext:
    """一次消息分发所需的统一上下文。所有字段均可选，分发前由 bot 填充。"""

    api: Any = None                 # botpy/api 客户端
    content: str = ""               # 已剥离前导 / 的消息文本
    storage_id: str = ""            # 裸 ID（各模块存储 key，与 is_waiting 一致）
    member_openid: str = ""         # 发送者 openid
    msg_id: str = ""                # 消息 id
    scene: str = ""                 # 场景（GROUP/C2C/...)
    target_id: str = ""             # 目标 ID（群管用，区别于 storage_id）
    member_role: str = ""           # 群成员角色（群管用）
    is_console_admin: bool = False  # 是否控制台管理员（群管用）
    member_nick: str = ""           # 发送者昵称（游戏等用）
    # ---- 框架级字段 ----
    is_group: bool = False          # 是否群聊
    event_type: str = ""            # 事件类型（AT/C2C/...）
    username: str = ""              # 发送者昵称（备用）
    event_id: str = ""              # 事件 id（回复用）

    bot: Any = None                  # MyClient 实例（适配器通过它调用 _time_plugin 计时埋点）
    perf: Any = None                 # 当前消息的 perf 计时字典
    bot_appid: str = ""              # 当前 bot 的 appid（供 is_feature_enabled 使用）
    # ---- 框架级会话/路由标志（由 bot 在分发前填充，供框架步骤使用）----
    is_waiting: bool = False         # 工具等待会话中
    is_gaming: bool = False          # 游戏进行中
    is_studying: bool = False        # 学习作答等待中
    is_at_or_dm: bool = False        # 被@ / 私聊（AI 兜底判定）

    def reply(self, text: str):
        """便捷回复：底层走 modules.common.send_text，参数沿用当前上下文。"""
        from modules.common import send_text
        return send_text(
            self.api, self.scene, self.target_id, text,
            msg_id=self.msg_id, event_id=self.event_id,
        )


@dataclass
class PluginDescriptor:
    """插件描述符。内置/外置共用。"""

    key: str                                         # 功能键，与 is_feature_enabled 一致
    name: str                                        # 展示名
    priority: int                                    # 排序，越小越靠前（仅同组内有意义）
    dispatch: Callable[[PluginContext], Any]         # async (ctx) -> bool（是否处理）
    is_external: bool = False                        # 是否外置插件
    is_waiting: Optional[Callable[[str, str], bool]] = None  # 可选：进行中会话预检 (storage_id, member_openid)
    init: Optional[Callable[[], Any]] = None         # 可选：启动初始化
    enabled_by_default: bool = True                  # 默认是否启用（受 is_feature_enabled 进一步控制）
    description: str = ""                            # 描述
    category: str = ""                               # 分类（如 "test" 测试插件），用于控制台分组/筛选
    handle_callback: Optional[Callable[..., Any]] = None  # 可选：按钮交互回调 (api, button_data, target_id, user_id, **kw) -> bool
    is_test_plugin: bool = False                     # 内置测试插件（不入市场、始终跟随主项目；如 demo_echo/ping/roll）
    session_check: Optional[Callable[[str], bool]] = None  # 可选：进行中会话预检 (storage_id) -> bool（is_gaming/is_reading 等）


# key -> PluginDescriptor
REGISTRY: dict = {}

# 注册表写入锁：热加载（后台线程）与分发（消息线程）并发访问 REGISTRY，
# 用锁保护写、分发处用 list(REGISTRY.values()) 快照避免迭代中修改。
_REG_LOCK = threading.RLock()

# 外置插件源文件路径 -> mtime（热加载检测）
_EXTERNAL_MTIMES: dict = {}

# 外置插件源文件路径 -> 注册时使用的 key（处理 key 变更/删除注销）
_EXTERNAL_KEYS: dict = {}

# 外置插件模块名 -> 模块对象（reload 用）
_EXTERNAL_MODULES: dict = {}

# 外置插件加载失败记录：path -> 错误信息（前端「插件配置」页可查）
_EXTERNAL_LOAD_ERRORS: dict = {}


# ----------------------------------------------------------------------------
# 外置插件启用状态（独立于 PluginDescriptor，避免热加载重建时丢失运行时状态）
# 持久化到 data/plugin_state.json；禁用 = 仅停止分发（仍保留在注册表/管理页）
# 注意：_DATA_DIR / _PLUGIN_STATE_FILE 依赖 _PROJECT_ROOT，在文件下方定义后再赋值。
# ----------------------------------------------------------------------------
_EXTERNAL_ENABLED: dict = {}   # key -> bool


def _load_plugin_state() -> None:
    """从 data/plugin_state.json 读取外置插件启用状态；文件不存在则全部默认启用。"""
    global _EXTERNAL_ENABLED
    _EXTERNAL_ENABLED = {}
    try:
        if os.path.isfile(_PLUGIN_STATE_FILE):
            with io.open(_PLUGIN_STATE_FILE, "r", encoding="utf-8-sig", errors="replace") as f:
                data = _json.loads(f.read())
            if isinstance(data, dict):
                for k, v in data.items():
                    _EXTERNAL_ENABLED[str(k)] = bool(v)
    except Exception as e:
        print("[plugin_registry] 读取 plugin_state.json 失败: %s" % e, flush=True)


def _save_plugin_state() -> None:
    """原子写回 data/plugin_state.json（调用方需持有 _REG_LOCK）。"""
    try:
        if not os.path.isdir(_DATA_DIR):
            os.makedirs(_DATA_DIR, exist_ok=True)
        tmp = _PLUGIN_STATE_FILE + ".tmp"
        with io.open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(_json.dumps(_EXTERNAL_ENABLED, ensure_ascii=False, indent=2))
        os.replace(tmp, _PLUGIN_STATE_FILE)
    except Exception as e:
        print("[plugin_registry] 写入 plugin_state.json 失败: %s" % e, flush=True)


def is_plugin_enabled(key: str) -> bool:
    """外置插件是否启用。未记录状态默认 True（启用）。"""
    with _REG_LOCK:
        return _EXTERNAL_ENABLED.get(key, True)


def set_plugin_enabled(key: str, enabled: bool) -> bool:
    """设置外置插件启用状态并持久化。返回是否成功。"""
    with _REG_LOCK:
        _EXTERNAL_ENABLED[key] = bool(enabled)
        _save_plugin_state()
    return True


def register_plugin(desc: PluginDescriptor) -> PluginDescriptor:
    """注册一个插件（内置或外置）。重复 key 以最后一次为准。"""
    with _REG_LOCK:
        REGISTRY[desc.key] = desc
    return desc


def unregister_plugin(key: str) -> None:
    with _REG_LOCK:
        REGISTRY.pop(key, None)


def _auto_enable_master_category(desc: 'PluginDescriptor') -> None:
    """安装后 hook：按插件的 category 自动启用对应 master 大类开关（如装 category=image 子插件
    自动开 is_feature_enabled('image')），让用户装完即看到大类生效。软依赖 console_server。"""
    if not desc or not desc.category:
        return
    try:
        import console_server  # 软依赖：bot 启动时 console_server 已加载
        console_server.set_feature_enabled_global(desc.category, True)
    except Exception as _e:
        try:
            print("[plugin_registry] 自动启用大类开关 %s 失败: %s" % (desc.category, _e), flush=True)
        except Exception:
            pass


def get_all_plugins_by_category() -> dict:
    """按 category 分组返回当前所有已注册插件（含内置+外置），供控制台菜单聚合显示。

    返回: {category: [PluginDescriptor, ...]}，顺序按 priority。
    """
    out = {}
    for d in snapshot_plugins():
        cat = d.category or "_misc"
        out.setdefault(cat, []).append(d)
    for cat in out:
        out[cat].sort(key=lambda x: x.priority)
    return out


def get_external_plugins_by_category() -> dict:
    """按 category 分组返回外置插件。"""
    out = {}
    for d in get_external_plugins():
        cat = d.category or "_misc"
        out.setdefault(cat, []).append(d)
    for cat in out:
        out[cat].sort(key=lambda x: x.priority)
    return out


def get_plugin_module_attr(key: str, attr: str, default=None):
    """按 key 获取已加载插件模块的属性（如 fw 步骤需要的模块级函数）。找不到返回 default。"""
    mod_name = "external_plugin_%s" % key
    mod = _EXTERNAL_MODULES.get(mod_name)
    if mod is None:
        return default
    return getattr(mod, attr, default)


def get_plugin(key: str) -> Optional[PluginDescriptor]:
    with _REG_LOCK:
        return REGISTRY.get(key)


def snapshot_plugins() -> list:
    """返回当前注册表所有描述符的快照列表（线程安全，供分发遍历使用）。"""
    with _REG_LOCK:
        return list(REGISTRY.values())


def get_builtin_plugins() -> list:
    return sorted((d for d in REGISTRY.values() if not d.is_external),
                  key=lambda d: d.priority)


def get_external_plugins() -> list:
    return sorted((d for d in REGISTRY.values() if d.is_external),
                  key=lambda d: d.priority)


def get_all_plugins() -> list:
    return sorted(REGISTRY.values(), key=lambda d: (d.is_external, d.priority))


def count_plugins() -> int:
    """活跃插件总数（内置 + 外置），供控制台 active_plugins 统计。"""
    return len(REGISTRY)


# ----------------------------------------------------------------------------
# 外置插件加载 / 热加载
# ----------------------------------------------------------------------------

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # modules/ -> 项目根
_PLUGINS_DIR = os.path.join(_PROJECT_ROOT, "plugins")
_DATA_DIR = os.path.join(_PROJECT_ROOT, "data")


# ----------------------------------------------------------------------------
# 目录包插件支持（plugins/<key>/manifest.json + main.py + assets/）
# 单文件 .py 与目录包两种形态共存：目录包能携带数据资源、声明依赖，利于开源分发。
# ----------------------------------------------------------------------------

def _iter_plugin_entries() -> list:
    """遍历 plugins/ 下的插件条目，返回 [(kind, key, path), ...]。

    kind: "file" 单文件 <key>.py | "dir" 目录包（含 manifest.json）。
    以下划线开头的文件/目录视为私有（模板/备份），跳过。
    """
    entries = []
    if not os.path.isdir(_PLUGINS_DIR):
        return entries
    for fn in sorted(os.listdir(_PLUGINS_DIR)):
        if fn.startswith("_"):
            continue
        path = os.path.join(_PLUGINS_DIR, fn)
        if fn.endswith(".py") and os.path.isfile(path):
            entries.append(("file", fn[:-3], path))
        elif os.path.isdir(path) and os.path.isfile(os.path.join(path, "manifest.json")):
            entries.append(("dir", fn, path))
    return entries


def _plugin_main_path(kind: str, key: str, path: str) -> str:
    """目录包的主入口 main.py；单文件即文件本身。"""
    return os.path.join(path, "main.py") if kind == "dir" else path


def _read_manifest(kind: str, key: str, path: str):
    """读取目录包 manifest.json；单文件返回 None。失败返回 None（不阻断加载）。"""
    if kind != "dir":
        return None
    try:
        with io.open(os.path.join(path, "manifest.json"), "r", encoding="utf-8-sig", errors="replace") as f:
            m = _json.load(f)
        return m if isinstance(m, dict) else None
    except Exception:
        return None


def _entry_mtime(kind: str, key: str, path: str) -> float:
    """条目变更检测时间戳：主入口 + manifest + 目录自身 mtime 取最大。"""
    mtimes = []
    for p in (path, _plugin_main_path(kind, key, path), os.path.join(path, "manifest.json")):
        try:
            mtimes.append(os.path.getmtime(p))
        except OSError:
            pass
    return max(mtimes) if mtimes else 0.0

# 启用状态持久化文件路径（依赖 _PROJECT_ROOT，故在此定义）
_DATA_DIR = os.path.join(_PROJECT_ROOT, "data")
_PLUGIN_STATE_FILE = os.path.join(_DATA_DIR, "plugin_state.json")

# 模块加载时读取一次持久化状态（缺文件则全部默认启用）
try:
    _load_plugin_state()
except Exception:
    pass


def _load_external_module(mod_name: str, file_path: str):
    """从文件路径动态导入一个模块。失败返回 None，并把错误信息写入 _EXTERNAL_LOAD_ERRORS。"""
    try:
        spec = importlib.util.spec_from_file_location(mod_name, file_path)
        if spec is None or spec.loader is None:
            _EXTERNAL_LOAD_ERRORS[file_path] = "无法构造 spec（文件可能不存在或不是 .py）"
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        spec.loader.exec_module(module)
        # 成功加载 → 清除该文件的历史错误
        _EXTERNAL_LOAD_ERRORS.pop(file_path, None)
        return module
    except Exception as e:
        msg = "%s: %s" % (type(e).__name__, e)
        print("[plugin_registry] 外置插件 %s 加载失败: %s" % (file_path, msg), flush=True)
        _EXTERNAL_LOAD_ERRORS[file_path] = msg
        return None


def get_external_load_errors() -> dict:
    """返回外置插件加载失败记录 {file_path: error_msg}，供前端展示。"""
    return dict(_EXTERNAL_LOAD_ERRORS)


def clear_external_load_errors() -> None:
    """清空加载失败记录（用于热加载前清零）。"""
    _EXTERNAL_LOAD_ERRORS.clear()


def _resolve_external(file_path: str, module, manifest: dict = None, fallback_key: str = ""):
    """从模块 + manifest 解析 (key, name, priority, dispatch, description, category, deps, is_waiting, handle_callback)。

    - manifest（目录包 manifest.json）字段优先级最高；
    - 其次模块级 PLUGIN dict；
    - 无有效 handle/dispatch 返回 None。
    """
    fn = os.path.basename(file_path)
    plugin_meta = dict(manifest or {}) if isinstance(manifest, dict) else {}
    mod_meta = getattr(module, "PLUGIN", None)
    if isinstance(mod_meta, dict):
        for k, v in mod_meta.items():
            plugin_meta.setdefault(k, v)
    handle = getattr(module, "handle", None)
    dispatch = plugin_meta.get("handle") or handle
    if dispatch is None:
        # 允许 manifest 声明 enable 函数（无 handle 时不参与消息分发，仅作启停标记）
        if not (plugin_meta.get("enable") or plugin_meta.get("init")):
            print("[plugin_registry] 插件 %s 未提供 handle/PLUGIN，跳过" % fn, flush=True)
            return None
    key = str(plugin_meta.get("key") or fallback_key or (fn[:-3] if fn.endswith(".py") else ""))
    if not key:
        return None
    name = str(plugin_meta.get("name") or key)
    try:
        priority = int(plugin_meta.get("priority", 500))
    except Exception:
        priority = 500
    description = str(plugin_meta.get("description") or "")
    category = str(plugin_meta.get("category") or "")
    deps = plugin_meta.get("dependencies") or []
    if not isinstance(deps, list):
        deps = []
    is_waiting = plugin_meta.get("is_waiting") or getattr(module, "is_waiting", None)
    handle_callback = plugin_meta.get("handle_callback") or getattr(module, "handle_callback", None)
    session_check = plugin_meta.get("session_check") or getattr(module, "session_check", None)
    is_test_plugin = bool(plugin_meta.get("is_test_plugin") or getattr(module, "is_test_plugin", False))
    return key, name, priority, dispatch, description, category, deps, is_waiting, handle_callback, session_check, is_test_plugin


def _register_entry(kind: str, key: str, path: str, stats: dict = None) -> bool:
    """加载并注册一个插件条目（单文件或目录包）。成功返回 True。"""
    main_path = _plugin_main_path(kind, key, path)
    mod_name = "external_plugin_%s" % key
    module = _load_external_module(mod_name, main_path)
    if module is None:
        if stats is not None:
            stats["errors"] += 1
        return False
    _EXTERNAL_MODULES[mod_name] = module
    manifest = _read_manifest(kind, key, path)
    resolved = _resolve_external(main_path, module, manifest=manifest, fallback_key=key)
    if resolved is None:
        if stats is not None:
            stats["errors"] += 1
        return False
    key2, name, priority, dispatch, description, category, deps, is_waiting, handle_callback, session_check, is_test_plugin = resolved
    # key 变更时先注销旧 key
    old_key = _EXTERNAL_KEYS.get(path)
    if old_key and old_key != key2 and get_plugin(old_key) and get_plugin(old_key).is_external:
        unregister_plugin(old_key)
    register_plugin(PluginDescriptor(
        key=key2, name=name, priority=priority, dispatch=dispatch,
        is_external=True, description=description, category=category,
        is_waiting=is_waiting, handle_callback=handle_callback,
        session_check=session_check, is_test_plugin=is_test_plugin,
    ))
    _EXTERNAL_MTIMES[path] = _entry_mtime(kind, key, path)
    _EXTERNAL_KEYS[path] = key2
    return True


def scan_external_plugins() -> list:
    """首次扫描 plugins/ 目录（单文件 + 目录包），加载并注册所有外置插件。返回加载的 key 列表。"""
    loaded = []
    for kind, key, path in _iter_plugin_entries():
        if _register_entry(kind, key, path):
            loaded.append(_EXTERNAL_KEYS.get(path))
    return [k for k in loaded if k]


def reload_external_plugins(force=False) -> dict:
    """热加载：扫描 plugins/（单文件 + 目录包），对变更/新增条目重新加载，对删除条目注销。

    force=True 时忽略 mtime，强制重新加载所有外置插件（用于控制台「热加载」按钮）。

    返回统计 {loaded, reloaded, unregistered, errors}。
    """
    stats = {"loaded": 0, "reloaded": 0, "unregistered": 0, "errors": 0}
    present = {}

    for kind, key, path in _iter_plugin_entries():
        present[path] = True
        mod_name = "external_plugin_%s" % key
        mtime = _entry_mtime(kind, key, path)
        changed = force or (mod_name not in _EXTERNAL_MODULES) or (_EXTERNAL_MTIMES.get(path) != mtime)
        if not changed:
            continue
        was_loaded = path in _EXTERNAL_MTIMES
        if _register_entry(kind, key, path, stats=stats):
            if was_loaded:
                stats["reloaded"] += 1
            else:
                stats["loaded"] += 1

    # 已删除的条目：注销对应外置插件
    for path in list(_EXTERNAL_MTIMES.keys()):
        if path not in present:
            old_key = _EXTERNAL_KEYS.get(path)
            if old_key and get_plugin(old_key) and get_plugin(old_key).is_external:
                unregister_plugin(old_key)
                stats["unregistered"] += 1
            _EXTERNAL_MTIMES.pop(path, None)
            _EXTERNAL_KEYS.pop(path, None)
            # 模块名从 entry 推导：目录包=目录名，单文件=文件名
            base = os.path.basename(path)
            if os.path.isdir(path) or base.endswith(".py"):
                cand = base[:-3] if base.endswith(".py") else base
                _EXTERNAL_MODULES.pop("external_plugin_%s" % cand, None)

    return stats


# ----------------------------------------------------------------------------
# 插件市场：可安装的模板
# ----------------------------------------------------------------------------
# 模板源文件以 _tpl_<key>.txt 形式存放在 plugins/ 下，因以 "_" 开头不会被
# scan_external_plugins 扫描；安装时复制为 <key>.py 并触发热加载。

_MARKET_TEMPLATE_FILES = {}
_MARKET_META = {}


def get_market_catalog() -> list:
    """返回插件市场目录（本地模板，单文件 .py 或目录包 _tpl_<key>/），含每项是否已安装。
    过滤掉已注册为内置测试插件的项（is_test_plugin=True 不进入市场）。"""
    catalog = []
    for key, filename in _MARKET_TEMPLATE_FILES.items():
        # 过滤内置测试插件：若插件已注册且 is_test_plugin=True，跳过
        _d = get_plugin(key)
        if _d is not None and _d.is_test_plugin:
            continue
        name, description, category = _MARKET_META.get(key, (key, "", ""))
        installed = os.path.isfile(os.path.join(_PLUGINS_DIR, key + ".py")) or (
            os.path.isdir(os.path.join(_PLUGINS_DIR, key))
            and os.path.isfile(os.path.join(_PLUGINS_DIR, key, "manifest.json"))
        )
        catalog.append({
            "key": key,
            "name": name,
            "description": description,
            "category": category,
            "installed": installed,
            "source": "local",
        })
    return catalog


# ----------------------------------------------------------------------------
# 远程插件市场（GitHub raw）：作为外置插件的下载来源
# 扁平结构：仓库根直接平铺 index.json + 每插件 <key>.py + <key>.meta.json（无子目录，目录名不强求）。
# index.json 仅列 key + path；展示用的 name/description/category/priority 从各 <key>.meta.json 读取（见 _enrich_with_meta）。
# index_subdir 仅作为「index.json 在子目录」时的回退目录名，根目录平铺优先。
# 默认仓库地址统一从 config.yaml 的 plugin_market 段读取：
#   plugin_market:
#     repo_url: "https://github.com/OWNER/REPO"
#     branch: "main"
#     index_subdir: ""           # index.json 所在子目录（留空=根）
# ----------------------------------------------------------------------------
def _load_market_defaults_from_config() -> tuple:
    """从 config.yaml 读取插件市场默认配置。返回 (repo_url, branch, subdir)。"""
    try:
        import yaml  # PyYAML
        with io.open(_PROJECT_ROOT + os.sep + "config.yaml", "r", encoding="utf-8-sig") as f:
            cfg = yaml.safe_load(f) or {}
        pm = cfg.get("plugin_market") or {}
        return (
            (pm.get("repo_url") or "").strip(),
            (pm.get("branch") or "main").strip() or "main",
            (pm.get("index_subdir") or "").strip(),
        )
    except Exception:
        return ("", "main", "")


_DFLT_REPO_URL, _DFLT_BRANCH, _DFLT_SUBDIR = _load_market_defaults_from_config()
# 兼容旧调用：常量保留，由 config.yaml 默认值驱动
REMOTE_MARKET_OWNER = ""
REMOTE_MARKET_REPO = ""
REMOTE_MARKET_BRANCH = _DFLT_BRANCH
REMOTE_MARKET_DIR = _DFLT_SUBDIR
# 默认 raw 基址（当 config.yaml 未指定或与默认仓库一致时使用）
# 实际生效由 get_remote_market_base() 控制，会应用运行时覆盖
REMOTE_MARKET_BASE = "https://raw.githubusercontent.com/GS240186/firefiy-QQofficial-bot-piugins/%s/" % _DFLT_BRANCH
_MARKET_CACHE_DIR = os.path.join(_DATA_DIR, "market_cache")
_MARKET_CACHE_FILE = os.path.join(_MARKET_CACHE_DIR, "index.json")
_MARKET_CACHE_TTL = 86400  # 远程目录缓存 24 小时（国内拉取不稳，延长缓存时间）

# 自定义插件仓库基址覆盖（由控制台「插件市场」页设置，热加载生效，无需重启）
_REMOTE_MARKET_BASE_OVERRIDE = None
# 自定义「子目录」覆盖（与基址覆盖配对使用）
_REMOTE_MARKET_SUBDIR_OVERRIDE = None


def _normalize_market_base_url(url):
    """自动规整：
    - https://github.com/xxx → https://raw.githubusercontent.com/xxx
    - 去 /blob/ 段
    - 末尾补 /
    不再做 BRANCH/DIR 自动补全 —— 用户直接粘贴仓库 URL，目录由 get_remote_market_catalog 多路径尝试定位。
    """
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("https://github.com/"):
        url = "https://raw.githubusercontent.com/" + url[len("https://github.com/"):]
    if "/blob/" in url:
        url = url.replace("/blob/", "/", 1)
    if not url.endswith("/"):
        url += "/"
    # 智能补 BRANCH：路径只有 OWNER/REPO（2 段）时自动补 REMOTE_MARKET_BRANCH，
    # 让「直接粘 https://github.com/OWNER/REPO」也能跑通。DIR 不补，由
    # get_remote_market_catalog 多路径尝试根 + REMOTE_MARKET_DIR 子目录。
    if url.startswith("https://raw.githubusercontent.com/"):
        tail = url[len("https://raw.githubusercontent.com/"):].rstrip("/")
        parts = [p for p in tail.split("/") if p]
        if len(parts) == 2:
            owner, repo = parts
            url = "https://raw.githubusercontent.com/%s/%s/%s/" % (owner, repo, REMOTE_MARKET_BRANCH)
    return url


# 国内访问 raw.githubusercontent.com 易被墙 / 丢包导致超时。
# 最稳方案：原始 URL 失败时按顺序回退到 jsDelivr CDN、Fastly、gh-proxy.com。
# jsDelivr：Cloudflare 全球节点，国内可达性最好（推荐主用）
#   https://cdn.jsdelivr.net/gh/OWNER/REPO@BRANCH/<file>
# jsDelivr Fastly：另一个 CDN 兜底
#   https://fastly.jsdelivr.net/gh/OWNER/REPO@BRANCH/<file>
# gh-proxy.com：多云代理，部分网络可达
#   https://gh-proxy.com/https://raw.githubusercontent.com/OWNER/REPO/BRANCH/<file>
# 注意：jsDelivr 有 12h CDN 缓存，commit 后要等缓存过期（或加 ?t=now 旁路缓存）。
_MARKET_MIRROR_HINT = (
    "若拉取失败或超时，可尝试：\n"
    "  1. 切换到 jsDelivr CDN：https://cdn.jsdelivr.net/gh/OWNER/REPO@BRANCH/\n"
    "  2. 浏览器打开下面 URL 验证 JSON 拉取正常\n"
    "  3. 联系仓库维护者检查 index.json 是否存在"
)


def _build_mirror_candidates(base_url: str) -> list:
    """根据 base_url 构造多个镜像候选 URL 列表（按稳定性排序）。

    原始 URL 在最前；其他镜像自动从 GitHub raw 或 jsDelivr 派生。
    非 GitHub 仓库（如 GitLab、码云等）只返回原始 URL。

    镜像优先级（实测国内可达性排序，2026-08-20）：
    1. 原始 base（用户配置）
    2. gitee.com（国内代码托管，国内服务器，最稳最快）
    3. cdn.jsdelivr.net（jsDelivr CDN，国内可达性较好）
    4. fastly.jsdelivr.net（jsDelivr Fastly 备选 CDN）
    5. raw.githubusercontent.com（GitHub 原始源，海外可达）
    6. gh-proxy.com（个人代理，2026-08 实测 404，不推荐）
    7. mirror.ghproxy.com（ghproxy 备用节点，未实测）
    8. ghps.cc（另一开源代理，未实测）
    """
    if not base_url:
        return []
    base_url = base_url.rstrip("/") + "/"
    out = [base_url]
    owner = repo = branch = sub = None

    # 解析 raw.githubusercontent.com：https://raw.githubusercontent.com/OWNER/REPO/BRANCH/<sub>/
    if base_url.startswith("https://raw.githubusercontent.com/"):
        tail = base_url[len("https://raw.githubusercontent.com/"):].rstrip("/")
        parts = [p for p in tail.split("/") if p]
        if len(parts) >= 3:
            owner, repo, branch = parts[0], parts[1], parts[2]
            sub = "/".join(parts[3:])
    # 解析 jsDelivr CDN：https://cdn.jsdelivr.net/gh/OWNER/REPO@BRANCH/<sub>/
    elif base_url.startswith("https://cdn.jsdelivr.net/gh/") or base_url.startswith("https://fastly.jsdelivr.net/gh/"):
        prefix_len = len("https://cdn.jsdelivr.net/gh/") if base_url.startswith("https://cdn.jsdelivr.net/gh/") else len("https://fastly.jsdelivr.net/gh/")
        tail = base_url[prefix_len:].rstrip("/")
        m = re.match(r"^([^/]+)/([^/@]+)@([^/]+)(?:/(.*))?$", tail)
        if m:
            owner, repo, branch = m.group(1), m.group(2), m.group(3)
            sub = m.group(4) or ""
    # 解析 github.com：https://github.com/OWNER/REPO[/BRANCH[/sub]]
    elif base_url.startswith("https://github.com/"):
        tail = base_url[len("https://github.com/"):].rstrip("/")
        parts = [p for p in tail.split("/") if p and p != "blob"]
        if len(parts) >= 2:
            owner, repo = parts[0], parts[1]
            if len(parts) >= 3:
                branch = parts[2]
            else:
                branch = "main"
            sub = "/".join(parts[3:]) if len(parts) >= 4 else ""
    # 解析 gitee.com：https://gitee.com/OWNER/REPO/raw/BRANCH/<sub>/
    elif base_url.startswith("https://gitee.com/"):
        tail = base_url[len("https://gitee.com/"):].rstrip("/")
        parts = [p for p in tail.split("/") if p]
        if len(parts) >= 4 and parts[2] == "raw":
            owner, repo, branch = parts[0], parts[1], parts[3]
            sub = "/".join(parts[4:])

    if not (owner and repo and branch):
        return out

    sub_suffix = ("/" + sub) if sub else ""
    # 构造一个 raw 路径（用于代理）
    raw_path = "raw.githubusercontent.com/%s/%s/%s%s/" % (owner, repo, branch, sub_suffix)

    # 优先级排序：原始 base 在最前；其他按稳定性添加（去重）
    def _add(url):
        if url and url not in out:
            out.append(url)

    # 镜像 1：gitee（国内代码托管，最稳最快）
    if not base_url.startswith("https://gitee.com/"):
        _add("https://gitee.com/%s/%s/raw/%s%s/" % (owner, repo, branch, sub_suffix))
    # 镜像 2-3：jsDelivr CDN（国内 Cloudflare 节点，备用）
    _add("https://cdn.jsdelivr.net/gh/%s/%s@%s%s/" % (owner, repo, branch, sub_suffix))
    _add("https://fastly.jsdelivr.net/gh/%s/%s@%s%s/" % (owner, repo, branch, sub_suffix))
    # 镜像 4：raw.githubusercontent.com（GitHub 原始源，海外可达）
    if not base_url.startswith("https://raw.githubusercontent.com/"):
        _add("https://raw.githubusercontent.com/%s/%s/%s%s/" % (owner, repo, branch, sub_suffix))
    # 镜像 5-7：国内代理（2026-08-20 实测 gh-proxy 404，不推荐主用，作为兜底）
    _add("https://gh-proxy.com/" + raw_path)
    _add("https://mirror.ghproxy.com/" + raw_path)
    _add("https://ghps.cc/" + raw_path)
    return out


def _http_get_text_with_fallback(candidate_paths, timeout=8, retries=1) -> tuple:
    """按候选路径顺序拉取文本，任意一个成功就返回 (text, used_base)。
    失败时尝试下一个；全部失败抛出最后一个错误。
    """
    last_err = None
    for path in candidate_paths:
        try:
            txt = _http_get_text(path, timeout=timeout, retries=retries)
            used_base = path.rsplit("/", 1)[0] + "/"
            return txt, used_base
        except Exception as e:
            last_err = e
            continue
    if last_err is not None:
        raise last_err
    raise RuntimeError("no candidate paths")


def _is_timeout_error(err_text: str) -> bool:
    """判断 URL 错误是否为网络超时（区别于 404 / DNS / 编码错误）。"""
    s = (err_text or "").lower()
    return ("timed out" in s) or ("timeout" in s and "read" in s)


def set_remote_market_base(base_url, subdir=None):
    """设置自定义插件仓库 raw 基址（如 https://raw.githubusercontent.com/OWNER/REPO/BRANCH/插件市场/）。
    传空字符串 / None 恢复默认仓库。
    自动规整：github.com → raw.githubusercontent.com、去 /blob/、补尾 /。
    扁平仓库填到分支层即可（如 https://github.com/OWNER/REPO 或 .../REPO/BRANCH/），
    bot 会在该基址下找 index.json 与 <key>.py / <key>.meta.json。
    subdir：可显式指定 index.json 所在子目录（与基址独立维护）。"""
    global _REMOTE_MARKET_BASE_OVERRIDE, _REMOTE_MARKET_SUBDIR_OVERRIDE
    base_url = _normalize_market_base_url(base_url)
    _REMOTE_MARKET_BASE_OVERRIDE = base_url or None
    if subdir is not None:
        _REMOTE_MARKET_SUBDIR_OVERRIDE = (subdir or "").strip() or None


def get_remote_market_subdir():
    """返回当前生效的「index.json 子目录」覆盖。None 表示使用 config.yaml 默认值。"""
    return _REMOTE_MARKET_SUBDIR_OVERRIDE


def get_remote_market_default():
    """返回 config.yaml 中的默认仓库配置 (repo_url, branch, subdir)。"""
    return (_DFLT_REPO_URL or "https://github.com/GS240186/firefiy-QQofficial-bot-piugins", _DFLT_BRANCH, _DFLT_SUBDIR)


def get_remote_market_base():
    """返回当前生效的插件仓库 raw 基址。
    优先级：运行时覆盖 > config.yaml plugin_market.repo_url > 硬编码默认仓库。
    """
    if _REMOTE_MARKET_BASE_OVERRIDE:
        return _REMOTE_MARKET_BASE_OVERRIDE
    if _DFLT_REPO_URL:
        norm = _normalize_market_base_url(_DFLT_REPO_URL)
        if norm:
            return norm
    return REMOTE_MARKET_BASE


def _http_get_text(url: str, timeout: int = 12, retries: int = 2) -> str:
    """用标准库拉取文本，带 UA；socket.timeout / URLError 自动重试。

    - 中文（如「插件市场」目录段）先用 urllib.parse.quote 单独编码非 ASCII 段，
      避免 urlopen 内部 ASCII encode 抛 UnicodeEncodeError。
    - 保留 scheme / path / query 分隔符（: / ? & = # %）以及 @（jsDelivr 用 @<version> 切分支，
      编码成 %40 会让 jsDelivr 返回 400 Bad Request）。
    - 单次 timeout 默认 12s，默认重试 2 次（最坏约 36s）。
    """
    import urllib.parse
    import urllib.request
    encoded = urllib.parse.quote(url, safe=":/?&=#%@")
    last_err = None
    for attempt in range(max(1, retries)):
        try:
            req = urllib.request.Request(encoded, headers={"User-Agent": "workbuddy-plugin-market"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except (socket.timeout, urllib.error.URLError) as e:
            last_err = e
            continue
        except Exception:
            raise
    if last_err is not None:
        raise last_err
    raise RuntimeError("unreachable")


def get_remote_market_catalog(force_refresh: bool = False) -> dict:
    """从 GitHub raw 拉取远程目录；带本地缓存（TTL）。返回 {"ok", "source", "plugins"}。
    source: cache（命中缓存）/ remote（刚拉取）/ 失败时为 cache(stale) 或 error。
    多路径尝试：先试 <base>/index.json；若 404 且 REMOTE_MARKET_DIR 非空，再试
    <base>/<REMOTE_MARKET_DIR>/index.json 作为回退（兼容旧仓库把 index.json 放在子目录的场景）。
    当 force_refresh=True 时，在 URL 后加时间戳，绕过 jsDelivr 等 CDN 缓存。

    最稳方案：原始 base 失败时按顺序回退到 jsDelivr CDN、jsDelivr Fastly、gh-proxy.com，
    任意一个成功就用它，并把 used_base 注入到插件项的 raw_url / meta_url。
    """
    base = get_remote_market_base()
    now = time.time()
    cache_bust = "?t=%d" % int(now) if force_refresh else ""
    subdir = _REMOTE_MARKET_SUBDIR_OVERRIDE if _REMOTE_MARKET_SUBDIR_OVERRIDE is not None else REMOTE_MARKET_DIR

    # 构造多镜像候选基址
    bases = _build_mirror_candidates(base)

    # 构造所有候选 index.json 路径（每镜像 × 根/subdir）
    # 注意：jsDelivr 有 12h CDN 缓存，加 cache_bust 会让它回源被墙超时。
    # 所以只有「原始 base + raw.githubusercontent.com」才加 cache_bust（旁路的是 CDN 缓存或无缓存的源）。
    # jsDelivr 走自身 CDN 缓存，访问更快。
    candidate_paths = []
    for b in bases:
        # jsDelivr / Fastly 镜像：不加 cache_bust（依赖其 CDN 缓存，反而更稳）
        is_jsdelivr = "jsdelivr.net/gh/" in b
        bust = "" if is_jsdelivr else cache_bust
        candidate_paths.append(b.rstrip("/") + "/index.json" + bust)
        if subdir:
            candidate_paths.append(b.rstrip("/") + "/" + subdir + "/index.json" + bust)

    cached = None
    if os.path.isfile(_MARKET_CACHE_FILE) and not force_refresh:
        try:
            age = now - os.path.getmtime(_MARKET_CACHE_FILE)
            if age < _MARKET_CACHE_TTL:
                with io.open(_MARKET_CACHE_FILE, "r", encoding="utf-8") as f:
                    cached = _json.load(f)
        except Exception:
            cached = None
    if cached is not None:
        return {"ok": True, "source": "cache",
                "plugins": [_mark_remote_installed(p, base=get_remote_market_base()) for p in cached.get("plugins", [])]}
    raw = None
    used_base = None
    last_err = ""
    tried = []
    # 单镜像超时 4s + 0 重试 = 4s × N 个镜像（最坏 4s × 6 = 24s，可接受）
    # gh-proxy 系列优先（前 3 个），多数情况下 1-2 个就命中，国内可用
    for path in candidate_paths:
        try:
            raw = _http_get_text(path, timeout=4, retries=0)
            used_base = path.rsplit("/", 1)[0] + "/"
            print("[plugin_market] OK: %s" % path, flush=True)
            break
        except Exception as e:
            err_msg = "%s: %s" % (type(e).__name__, e)
            last_err = err_msg
            print("[plugin_market] FAIL: %s (%s)" % (path, err_msg), flush=True)
            continue
    if raw is None:
        _hint = "（请确认 URL 正确，且 index.json 在仓库内可访问；可放在根目录或「%s」子目录下）" % REMOTE_MARKET_DIR
        if _is_timeout_error(last_err):
            _hint += "\n" + _MARKET_MIRROR_HINT
        _hint += "\n已尝试以下镜像：\n  - " + "\n  - ".join(tried)
        if cached is not None:
            return {"ok": True, "source": "cache", "stale": True,
                    "plugins": [_mark_remote_installed(p, base=get_remote_market_base()) for p in cached.get("plugins", [])],
                    "error": "远程拉取失败，使用缓存：%s%s" % (last_err, _hint)}
        return {"ok": False, "error": "远程目录拉取失败：%s%s" % (last_err, _hint), "plugins": []}
    try:
        data = _json.loads(raw)
    except Exception as e:
        return {"ok": False, "error": "远程目录 JSON 解析失败：%s" % e, "plugins": []}
    # 使用成功回退的镜像 base 标记所有插件，确保后续安装 URL 走同一个稳定源
    plugins = _enrich_with_meta(
        [_mark_remote_installed(p, base=used_base) for p in data.get("plugins", [])],
        bust=force_refresh, meta_base=used_base)
    try:
        if not os.path.isdir(_MARKET_CACHE_DIR):
            os.makedirs(_MARKET_CACHE_DIR, exist_ok=True)
        with io.open(_MARKET_CACHE_FILE, "w", encoding="utf-8") as f:
            # 缓存已合并 meta 的成品，避免每次命中缓存都重新拉 meta
            _json.dump({"plugins": plugins}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return {"ok": True, "source": "remote", "plugins": plugins}


def _mark_remote_installed(item: dict, base: str = None) -> dict:
    """给远程目录项补全 installed / source / raw_url / meta_url。

    kind 支持两种形态：
    - "file"（默认）：单文件 <key>.py，path 形如 "demo_echo.py"
    - "dir"：目录包 <key>/（含 manifest.json），path 形如 "tool_weather/main.py"（安装时按目录包下载）

    base：可显式传入 base 覆盖（用于多镜像回退时统一用成功的镜像 base）。
    """
    it = dict(item)
    key = it.get("key")
    kind = it.get("kind") or ("dir" if str(it.get("path") or "").endswith("/main.py") else "file")
    it["kind"] = kind
    if kind == "dir":
        it["installed"] = bool(key) and (
            os.path.isdir(os.path.join(_PLUGINS_DIR, key))
            and os.path.isfile(os.path.join(_PLUGINS_DIR, key, "manifest.json"))
        )
    else:
        it["installed"] = bool(key) and os.path.isfile(os.path.join(_PLUGINS_DIR, key + ".py"))
    it["source"] = "remote"
    use_base = (base or get_remote_market_base()).rstrip("/") + "/"
    rel = it.get("path") or (key + ".py")
    it["raw_url"] = use_base + rel
    # meta 文件名优先用索引显式给的 meta 字段；否则按扁平约定推导为 <key>.meta.json
    it["meta_url"] = use_base + (it.get("meta") or (key + ".meta.json"))
    return it


def _enrich_with_meta(plugins: list, bust: bool = False, meta_base: str = None) -> list:
    """用每个插件的 <key>.meta.json 补全 name/description/category/priority。
    极简索引（index.json 仅 key+path）时这些展示字段缺失，从同目录的
    <key>.meta.json 读取。规则：仅填充索引中缺失/为空的字段，故富索引
    （自带 name 等）不会被覆盖。meta 拉取失败则跳过，name 兜底为 key。
    bust=True 时给 meta 请求加时间戳，绕过 CDN 缓存，但不污染返回的 meta_url。
    meta_base：用于把 _http_get_text 拉 meta 的 base 同步为成功的镜像 base
                （若 meta_url 已含绝对 URL，则以 meta_url 为准；否则按 meta_base 拼接）。
    """
    out = []
    ts = "?t=%d" % int(time.time()) if bust else ""
    for it in plugins:
        it = dict(it)
        meta_url = it.get("meta_url") or ""
        # 如果 meta_url 是相对路径（没有 http://），用 meta_base 拼接
        if meta_url and not meta_url.startswith("http"):
            base = (meta_base or get_remote_market_base()).rstrip("/") + "/"
            meta_url = base + meta_url
        if meta_url:
            try:
                raw = _http_get_text(meta_url + ts, timeout=8, retries=1)
                m = _json.loads(raw)
                for fld in ("name", "description", "category", "priority"):
                    if not it.get(fld):
                        v = m.get(fld)
                        if v not in (None, ""):
                            it[fld] = v
            except Exception:
                pass
        if not it.get("name"):
            it["name"] = it.get("key") or ""
        out.append(it)
    return out


def install_remote_market_plugin(key: str, raw_url: str = None) -> dict:
    """从远程 raw URL 安装插件，并触发热加载。

    支持两种形态：
    - 单文件：raw_url 指向 <key>.py → 下载写入 plugins/<key>.py
    - 目录包：raw_url 指向 <key>/main.py → 按 index.json 中 files 字段逐个下载到 plugins/<key>/
      若索引项 requires_common=true，自动下载 _common/ 共享库（如尚未安装）。
    """
    if not raw_url:
        return {"ok": False, "error": "缺少远程地址 raw_url"}
    if not key:
        return {"ok": False, "error": "缺少插件 key"}
    base = get_remote_market_base()

    is_dir = raw_url.endswith("/main.py")
    if is_dir:
        return _install_remote_dir_plugin(key, raw_url, base)
    if os.path.isfile(os.path.join(_PLUGINS_DIR, key + ".py")):
        return {"ok": False, "error": "该插件已安装（如需覆盖请先卸载）"}
    try:
        src = _http_get_text(raw_url, timeout=15, retries=2)
    except Exception as e:
        extra = ("\n" + _MARKET_MIRROR_HINT) if _is_timeout_error(str(e)) else ""
        return {"ok": False, "error": "下载失败：%s%s" % (e, extra)}
    if not src.strip():
        return {"ok": False, "error": "下载内容为空"}
    out_path = os.path.join(_PLUGINS_DIR, key + ".py")
    body = src.replace("\r\n", "\n").replace("\n", "\r\n")
    with io.open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(body)
    reload_external_plugins(force=True)
    _auto_enable_master_category(get_plugin(key))
    return {"ok": True, "reloaded": True}


def _install_remote_dir_plugin(key: str, main_raw_url: str, base: str) -> dict:
    """远程安装目录包插件：按 files 字段逐个下载到 plugins/<key>/。"""
    dir_path = os.path.join(_PLUGINS_DIR, key)
    if os.path.isdir(dir_path) and os.path.isfile(os.path.join(dir_path, "manifest.json")):
        return {"ok": False, "error": "该插件已安装（如需覆盖请先卸载）"}

    # 从 index.json 缓存中查找该插件的 files 列表
    files_list = None
    requires_common = False
    catalog_data = None
    try:
        if os.path.isfile(_MARKET_CACHE_FILE):
            with io.open(_MARKET_CACHE_FILE, encoding="utf-8") as f:
                catalog_data = _json.load(f)
    except Exception:
        pass
    if catalog_data:
        for p in catalog_data.get("plugins", []):
            if p.get("key") == key:
                files_list = p.get("files")
                requires_common = p.get("requires_common", False)
                break

    if not files_list:
        files_list = ["main.py", "manifest.json"]

    os.makedirs(dir_path, exist_ok=True)
    dir_prefix = key + "/"
    downloaded = 0
    for rel in files_list:
        url = base + dir_prefix + rel
        try:
            content = _http_get_text(url, timeout=15, retries=2)
        except Exception as e:
            extra = ("\n" + _MARKET_MIRROR_HINT) if _is_timeout_error(str(e)) else ""
            import shutil as _sh
            _sh.rmtree(dir_path, ignore_errors=True)
            return {"ok": False, "error": "下载 %s 失败：%s%s" % (rel, e, extra)}
        out_file = os.path.join(dir_path, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(out_file), exist_ok=True)
        body = content.replace("\r\n", "\n").replace("\n", "\r\n")
        with io.open(out_file, "w", encoding="utf-8-sig", newline="") as f:
            f.write(body)
        downloaded += 1

    # 自动安装 _common 共享库
    if requires_common:
        common_dir = os.path.join(_PLUGINS_DIR, "_common")
        if not os.path.isdir(common_dir):
            res = _install_remote_common(base)
            if not res.get("ok"):
                import shutil as _sh
                _sh.rmtree(dir_path, ignore_errors=True)
                return res

    reload_external_plugins(force=True)
    _auto_enable_master_category(get_plugin(key))
    return {"ok": True, "reloaded": True, "files": downloaded}


def _install_remote_common(base: str) -> dict:
    """下载 _common/ 共享库到 plugins/_common/（目录包插件依赖）。"""
    common_dir = os.path.join(_PLUGINS_DIR, "_common")
    os.makedirs(common_dir, exist_ok=True)
    _COMMON_FILES = [
        "__init__.py",
        "game_core.py",
        "image_core.py",
        "study_core.py",
        "tools_core.py",
        "video_core.py",
    ]
    for rel in _COMMON_FILES:
        url = base + "_common/" + rel
        try:
            content = _http_get_text(url, timeout=15, retries=2)
        except Exception as e:
            extra = ("\n" + _MARKET_MIRROR_HINT) if _is_timeout_error(str(e)) else ""
            return {"ok": False, "error": "下载 _common/%s 失败：%s%s" % (rel, e, extra)}
        out_file = os.path.join(common_dir, rel)
        body = content.replace("\r\n", "\n").replace("\n", "\r\n")
        with io.open(out_file, "w", encoding="utf-8-sig", newline="") as f:
            f.write(body)
    return {"ok": True}


def _read_market_template(key: str):
    """读取市场模板源文本；不存在返回 None。"""
    filename = _MARKET_TEMPLATE_FILES.get(key)
    if not filename:
        return None
    tpl_path = os.path.join(_PLUGINS_DIR, filename)
    if not os.path.isfile(tpl_path):
        return None
    with io.open(tpl_path, "r", encoding="utf-8-sig", errors="replace") as f:
        return f.read()


def install_market_plugin(key: str) -> dict:
    """从模板安装一个市场插件并触发热加载。

    支持两种模板形态：
    - 单文件：_tpl_<key>.txt → plugins/<key>.py
    - 目录包：_tpl_<key>/（含 manifest.json）→ plugins/<key>/（整体复制）
    """
    if key not in _MARKET_TEMPLATE_FILES:
        return {"ok": False, "error": "未知的市场插件：%s" % key}
    filename = _MARKET_TEMPLATE_FILES.get(key)
    tpl_path = os.path.join(_PLUGINS_DIR, filename)
    installed = os.path.isfile(os.path.join(_PLUGINS_DIR, key + ".py")) or (
        os.path.isdir(os.path.join(_PLUGINS_DIR, key))
        and os.path.isfile(os.path.join(_PLUGINS_DIR, key, "manifest.json"))
    )
    if installed:
        return {"ok": False, "error": "该插件已安装"}
    out_path = os.path.join(_PLUGINS_DIR, key + ".py")
    if os.path.isfile(tpl_path):
        src = _read_market_template(key)
        if not src:
            return {"ok": False, "error": "模板文件缺失"}
        # 统一写入 CRLF + BOM，符合项目约定
        body = src.replace(chr(13) + chr(10), chr(10)).replace(chr(10), chr(13) + chr(10))
        with io.open(out_path, "w", encoding="utf-8-sig", newline="") as f:
            f.write(body)
    elif os.path.isdir(tpl_path) and os.path.isfile(os.path.join(tpl_path, "manifest.json")):
        import shutil
        dst_dir = os.path.join(_PLUGINS_DIR, key)
        try:
            shutil.copytree(tpl_path, dst_dir)
        except Exception as e:
            return {"ok": False, "error": "复制目录包失败：%s" % e}
    else:
        return {"ok": False, "error": "模板缺失（既非文件也非目录包）"}
    reload_external_plugins(force=True)
    _auto_enable_master_category(get_plugin(key))
    return {"ok": True, "reloaded": True}


def uninstall_external_plugin(key: str) -> dict:
    """卸载一个外置插件并触发热加载。支持单文件 plugins/<key>.py 与目录包 plugins/<key>/（含 manifest.json）。
    放开「仅市场模板」限制：任何已安装的外置插件均可卸载。"""
    if not key or "/" in key or "\\" in key or "." in key:
        return {"ok": False, "error": "非法插件 key"}
    file_path = os.path.join(_PLUGINS_DIR, key + ".py")
    dir_path = os.path.join(_PLUGINS_DIR, key)
    if os.path.isfile(file_path):
        target = file_path
    elif os.path.isdir(dir_path) and os.path.isfile(os.path.join(dir_path, "manifest.json")):
        target = dir_path
    else:
        return {"ok": False, "error": "该插件未安装"}
    try:
        if os.path.isdir(target):
            import shutil
            shutil.rmtree(target)
        else:
            os.remove(target)
    except Exception as e:
        return {"ok": False, "error": "删除失败：%s" % e}
    reload_external_plugins(force=True)
    return {"ok": True, "reloaded": True}
