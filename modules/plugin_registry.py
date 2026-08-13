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

# 启用状态持久化文件路径（依赖 _PROJECT_ROOT，故在此定义）
_DATA_DIR = os.path.join(_PROJECT_ROOT, "data")
_PLUGIN_STATE_FILE = os.path.join(_DATA_DIR, "plugin_state.json")

# 模块加载时读取一次持久化状态（缺文件则全部默认启用）
try:
    _load_plugin_state()
except Exception:
    pass


def _load_external_module(mod_name: str, file_path: str):
    """从文件路径动态导入一个模块。失败返回 None。"""
    try:
        spec = importlib.util.spec_from_file_location(mod_name, file_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        spec.loader.exec_module(module)
        return module
    except Exception as e:
        print("[plugin_registry] 外置插件 %s 加载失败: %s" % (file_path, e), flush=True)
        return None


def _resolve_external(file_path: str, module):
    """从模块解析 (key, name, priority, dispatch, description, category)。无有效 handle 返回 None。"""
    fn = os.path.basename(file_path)
    plugin_meta = getattr(module, "PLUGIN", None)
    handle = getattr(module, "handle", None)
    if plugin_meta and isinstance(plugin_meta, dict):
        key = str(plugin_meta.get("key") or fn[:-3])
        name = str(plugin_meta.get("name") or key)
        try:
            priority = int(plugin_meta.get("priority", 500))
        except Exception:
            priority = 500
        dispatch = plugin_meta.get("handle") or handle
        description = str(plugin_meta.get("description") or "")
        category = str(plugin_meta.get("category") or "")
    elif handle is not None:
        key = fn[:-3]
        name = key
        priority = 500
        dispatch = handle
        description = ""
        category = ""
    else:
        print("[plugin_registry] 外置插件 %s 未提供 PLUGIN 或 handle，跳过" % fn, flush=True)
        return None
    if dispatch is None:
        return None
    return key, name, priority, dispatch, description, category


def scan_external_plugins() -> list:
    """首次扫描 plugins/ 目录，加载并注册所有外置插件。返回加载的描述符列表。"""
    loaded = []
    if not os.path.isdir(_PLUGINS_DIR):
        return loaded
    for fn in sorted(os.listdir(_PLUGINS_DIR)):
        if not fn.endswith(".py") or fn.startswith("_"):
            continue
        file_path = os.path.join(_PLUGINS_DIR, fn)
        if not os.path.isfile(file_path):
            continue
        mod_name = "external_plugin_%s" % fn[:-3]
        module = _load_external_module(mod_name, file_path)
        if module is None:
            continue
        _EXTERNAL_MODULES[mod_name] = module
        resolved = _resolve_external(file_path, module)
        if resolved is None:
            continue
        key, name, priority, dispatch, description, category = resolved
        register_plugin(PluginDescriptor(
            key=key, name=name, priority=priority, dispatch=dispatch,
            is_external=True, description=description, category=category,
        ))
        _EXTERNAL_MTIMES[file_path] = os.path.getmtime(file_path)
        _EXTERNAL_KEYS[file_path] = key
        loaded.append(key)
    return loaded


def reload_external_plugins(force=False) -> dict:
    """热加载：扫描 plugins/，对变更/新增文件重新加载并重新注册，对删除文件注销。

    force=True 时忽略 mtime，强制重新加载所有外置插件（用于控制台「热加载」按钮）。

    返回统计 {loaded, reloaded, unregistered, errors}。
    """
    stats = {"loaded": 0, "reloaded": 0, "unregistered": 0, "errors": 0}
    present_files = set()

    if os.path.isdir(_PLUGINS_DIR):
        for fn in sorted(os.listdir(_PLUGINS_DIR)):
            if not fn.endswith(".py") or fn.startswith("_"):
                continue
            file_path = os.path.join(_PLUGINS_DIR, fn)
            if not os.path.isfile(file_path):
                continue
            present_files.add(file_path)
            mod_name = "external_plugin_%s" % fn[:-3]
            mtime = os.path.getmtime(file_path)
            changed = force or (mod_name not in _EXTERNAL_MODULES) or (_EXTERNAL_MTIMES.get(file_path) != mtime)
            if not changed:
                continue
            module = _load_external_module(mod_name, file_path)
            if module is None:
                stats["errors"] += 1
                continue
            _EXTERNAL_MODULES[mod_name] = module
            resolved = _resolve_external(file_path, module)
            if resolved is None:
                stats["errors"] += 1
                continue
            key, name, priority, dispatch, description, category = resolved
            # key 变更时先注销旧 key
            old_key = _EXTERNAL_KEYS.get(file_path)
            if old_key and old_key != key and get_plugin(old_key) and get_plugin(old_key).is_external:
                unregister_plugin(old_key)
            register_plugin(PluginDescriptor(
                key=key, name=name, priority=priority, dispatch=dispatch,
                is_external=True, description=description, category=category,
            ))
            _EXTERNAL_MTIMES[file_path] = mtime
            _EXTERNAL_KEYS[file_path] = key
            if old_key is not None:
                stats["reloaded"] += 1
            else:
                stats["loaded"] += 1

    # 已删除的文件：注销对应外置插件
    for file_path in list(_EXTERNAL_MTIMES.keys()):
        if file_path not in present_files:
            old_key = _EXTERNAL_KEYS.get(file_path)
            if old_key and get_plugin(old_key) and get_plugin(old_key).is_external:
                unregister_plugin(old_key)
                stats["unregistered"] += 1
            _EXTERNAL_MTIMES.pop(file_path, None)
            _EXTERNAL_KEYS.pop(file_path, None)
            mod_name = "external_plugin_%s" % os.path.basename(file_path)[:-3]
            _EXTERNAL_MODULES.pop(mod_name, None)

    return stats


# ----------------------------------------------------------------------------
# 插件市场：可安装的模板
# ----------------------------------------------------------------------------
# 模板源文件以 _tpl_<key>.txt 形式存放在 plugins/ 下，因以 "_" 开头不会被
# scan_external_plugins 扫描；安装时复制为 <key>.py 并触发热加载。

_MARKET_TEMPLATE_FILES = {
    "demo_echo": "_tpl_demo_echo.txt",
    "ping": "_tpl_ping.txt",
    "roll": "_tpl_roll.txt",
}

_MARKET_META = {
    "demo_echo": ("回声插件", "发送「echo 内容」原样回显，最基础的触发器示例。", "test"),
    "ping": ("Ping 插件", "发送「ping」机器人回「pong」，用于连通性自测。", "test"),
    "roll": ("Roll 骰子", "发送「roll 100」随机抽 1~N 的整数（默认 100）。", "test"),
}


def get_market_catalog() -> list:
    """返回插件市场目录（本地模板），含每项是否已安装（plugins/<key>.py 是否存在）。"""
    catalog = []
    for key, filename in _MARKET_TEMPLATE_FILES.items():
        name, description, category = _MARKET_META.get(key, (key, "", ""))
        installed = os.path.isfile(os.path.join(_PLUGINS_DIR, key + ".py"))
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
# REMOTE_MARKET_DIR 仅作为「index.json 在子目录」时的回退目录名，根目录平铺优先。
# ----------------------------------------------------------------------------
REMOTE_MARKET_OWNER = "GS240186"
REMOTE_MARKET_REPO = "firefiy-QQofficial-bot-piugins"
REMOTE_MARKET_BRANCH = "main"   # 若仓库默认分支是 master，改成 "master"
# 仓库根目录下「index.json 所在目录」名（仅作为回退路径，用户也可直接把 index.json 放在根目录）
REMOTE_MARKET_DIR = "插件市场"
# 默认基址只到分支层；index.json 既可放在根目录（<base>index.json），也可放在子目录（<base>/<DIR>/index.json），由 get_remote_market_catalog 多路径尝试。
REMOTE_MARKET_BASE = "https://raw.githubusercontent.com/%s/%s/%s/" % (
    REMOTE_MARKET_OWNER, REMOTE_MARKET_REPO, REMOTE_MARKET_BRANCH
)
_MARKET_CACHE_DIR = os.path.join(_DATA_DIR, "market_cache")
_MARKET_CACHE_FILE = os.path.join(_MARKET_CACHE_DIR, "index.json")
_MARKET_CACHE_TTL = 600  # 远程目录缓存 10 分钟

# 自定义插件仓库基址覆盖（由控制台「插件市场」页设置，热加载生效，无需重启）
_REMOTE_MARKET_BASE_OVERRIDE = None


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


# 国内访问 raw.githubusercontent.com 易被墙 / 丢包导致超时，
# 推荐改用 jsDelivr CDN（Cloudflare 全球节点，国内可达性最好）：
#   https://cdn.jsdelivr.net/gh/OWNER/REPO@BRANCH/
# 备选 gh-proxy.com（多云代理，部分网络可达）：
#   https://gh-proxy.com/https://raw.githubusercontent.com/OWNER/REPO/BRANCH/
# 注意：jsDelivr 有 12h CDN 缓存，commit 后要等缓存过期（或加 @main/<file>?ts=now 旁路缓存）。
_MARKET_MIRROR_HINT = (
    "国内访问 raw.githubusercontent.com 常被墙 / 丢包。推荐改用 jsDelivr CDN：\n"
    "  https://cdn.jsdelivr.net/gh/OWNER/REPO@BRANCH/\n"
    "例（本项目）：https://cdn.jsdelivr.net/gh/GS240186/firefiy-QQofficial-bot-piugins@main/\n"
    "备选 gh-proxy.com（多云代理）：https://gh-proxy.com/https://raw.githubusercontent.com/OWNER/REPO/BRANCH/\n"
    "请先在浏览器打开 index.json 验证能拉到 JSON 再填入"
)


def _is_timeout_error(err_text: str) -> bool:
    """判断 URL 错误是否为网络超时（区别于 404 / DNS / 编码错误）。"""
    s = (err_text or "").lower()
    return ("timed out" in s) or ("timeout" in s and "read" in s)


def set_remote_market_base(base_url):
    """设置自定义插件仓库 raw 基址（如 https://raw.githubusercontent.com/OWNER/REPO/BRANCH/插件市场/）。
    传空字符串 / None 恢复默认仓库。
    自动规整：github.com → raw.githubusercontent.com、去 /blob/、补尾 /。
    扁平仓库填到分支层即可（如 https://github.com/OWNER/REPO 或 .../REPO/BRANCH/），
    bot 会在该基址下找 index.json 与 <key>.py / <key>.meta.json。"""
    global _REMOTE_MARKET_BASE_OVERRIDE
    base_url = _normalize_market_base_url(base_url)
    _REMOTE_MARKET_BASE_OVERRIDE = base_url or None


def get_remote_market_base():
    """返回当前生效的插件仓库 raw 基址（自定义覆盖优先，否则默认仓库）。"""
    return _REMOTE_MARKET_BASE_OVERRIDE or REMOTE_MARKET_BASE


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
    """
    base = get_remote_market_base()
    candidate_paths = [base + "index.json"]
    if REMOTE_MARKET_DIR:
        candidate_paths.append(base.rstrip("/") + "/" + REMOTE_MARKET_DIR + "/index.json")
    now = time.time()
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
                "plugins": [_mark_remote_installed(p) for p in cached.get("plugins", [])]}
    raw = None
    last_err = ""
    for path in candidate_paths:
        try:
            raw = _http_get_text(path)
            break
        except Exception as e:
            last_err = str(e)
            continue
    if raw is None:
        _hint = "（请确认 URL 正确，且 index.json 在仓库内可访问；可放在根目录或「%s」子目录下）" % REMOTE_MARKET_DIR
        if _is_timeout_error(last_err):
            _hint += "\n" + _MARKET_MIRROR_HINT
        if cached is not None:
            return {"ok": True, "source": "cache", "stale": True,
                    "plugins": [_mark_remote_installed(p) for p in cached.get("plugins", [])],
                    "error": "远程拉取失败，使用缓存：%s%s" % (last_err, _hint)}
        return {"ok": False, "error": "远程目录拉取失败：%s%s" % (last_err, _hint), "plugins": []}
    try:
        data = _json.loads(raw)
    except Exception as e:
        return {"ok": False, "error": "远程目录 JSON 解析失败：%s" % e, "plugins": []}
    plugins = _enrich_with_meta([_mark_remote_installed(p) for p in data.get("plugins", [])])
    try:
        if not os.path.isdir(_MARKET_CACHE_DIR):
            os.makedirs(_MARKET_CACHE_DIR, exist_ok=True)
        with io.open(_MARKET_CACHE_FILE, "w", encoding="utf-8") as f:
            # 缓存已合并 meta 的成品，避免每次命中缓存都重新拉 meta
            _json.dump({"plugins": plugins}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return {"ok": True, "source": "remote", "plugins": plugins}


def _mark_remote_installed(item: dict) -> dict:
    """给远程目录项补全 installed / source / raw_url / meta_url。"""
    it = dict(item)
    key = it.get("key")
    it["installed"] = bool(key) and os.path.isfile(os.path.join(_PLUGINS_DIR, key + ".py"))
    it["source"] = "remote"
    rel = it.get("path") or (key + ".py")
    it["raw_url"] = get_remote_market_base() + rel
    # meta 文件名优先用索引显式给的 meta 字段；否则按扁平约定推导为 <key>.meta.json
    it["meta_url"] = get_remote_market_base() + (it.get("meta") or (key + ".meta.json"))
    return it


def _enrich_with_meta(plugins: list) -> list:
    """用每个插件的 <key>.meta.json 补全 name/description/category/priority。

    极简索引（index.json 仅 key+path）时这些展示字段缺失，从同目录的
    <key>.meta.json 读取。规则：仅填充索引中缺失/为空的字段，故富索引
    （自带 name 等）不会被覆盖。meta 拉取失败则跳过，name 兜底为 key。
    """
    out = []
    for it in plugins:
        it = dict(it)
        meta_url = it.get("meta_url") or ""
        if meta_url:
            try:
                raw = _http_get_text(meta_url, timeout=8, retries=2)
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
    """从远程 raw URL 安装插件到 plugins/<key>.py，并触发热加载。"""
    if not raw_url:
        return {"ok": False, "error": "缺少远程地址 raw_url"}
    if not key:
        return {"ok": False, "error": "缺少插件 key"}
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
    return {"ok": True, "reloaded": True}


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
    """从模板安装一个市场插件到 plugins/<key>.py，并触发热加载。"""
    if key not in _MARKET_TEMPLATE_FILES:
        return {"ok": False, "error": "未知的市场插件：%s" % key}
    if os.path.isfile(os.path.join(_PLUGINS_DIR, key + ".py")):
        return {"ok": False, "error": "该插件已安装"}
    src = _read_market_template(key)
    if not src:
        return {"ok": False, "error": "模板文件缺失"}
    out_path = os.path.join(_PLUGINS_DIR, key + ".py")
    # 统一写入 CRLF + BOM，符合项目约定
    body = src.replace(chr(13)+chr(10), chr(10)).replace(chr(10), chr(13)+chr(10))
    with io.open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(body)
    reload_external_plugins(force=True)
    return {"ok": True, "reloaded": True}


def uninstall_external_plugin(key: str) -> dict:
    """卸载一个外置插件（删除 plugins/<key>.py）并触发热加载。
    放开「仅市场模板」限制：任何已安装在 plugins/ 下的外置插件均可卸载。"""
    if not key or "/" in key or "\\" in key:
        return {"ok": False, "error": "非法插件 key"}
    file_path = os.path.join(_PLUGINS_DIR, key + ".py")
    if not os.path.isfile(file_path):
        return {"ok": False, "error": "该插件未安装"}
    try:
        os.remove(file_path)
    except Exception as e:
        return {"ok": False, "error": "删除失败：%s" % e}
    reload_external_plugins(force=True)
    return {"ok": True, "reloaded": True}
