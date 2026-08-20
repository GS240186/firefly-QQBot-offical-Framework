# -*- coding: utf-8 -*-

"""console_server 兼容桩（stub）。

历史原因：bot.py 早期版本依赖 console_server.py 提供业务工具函数

（_restart_bot、_shutdown_bot、_get_status_data、record_message、

is_feature_enabled、bind_*_qq_number 等）。原 console_server.py 与

Web 控制台服务（端口 9988、xiaoliu-console/）现已删除。

为保证 bot.py 能继续以 `python bot.py` 启动，本文件仅提供与

bot.py import 列表一致的函数符号。这些函数：

- 不再启动任何 HTTP / Web 服务（旧 9988 控制台已下线）

- 不影响 bot 的 QQ 收发逻辑

- 默认值保持「功能开启」「空列表」「假数据」语义，使上层调用

  (例如 is_feature_enabled) 不会因为 False 而关闭原有功能

如果将来要恢复完整控制台，请重写本文件或将 bot.py 改造为

直接 import 业务模块（modules.*）。

"""

import os

import sys

import time

import logging

logger = logging.getLogger("console_server")

import threading

import webbrowser

import re

import json as _json

import asyncio

import base64

import urllib.parse

import urllib.request

import urllib.error

from collections import deque

from datetime import datetime

import modules.bot_manager as bot_manager
import modules.bot_health as bot_health
import modules.plugin_registry as plugin_registry
import modules.plugin_center as plugin_center
import modules.feature_menu as feature_menu

# 数据根目录（尽早定义，供导入期调用的 per-bot 加载函数使用）
_DATA_ROOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

__all__ = [

    "start_console_server",

    "update_status",

    "record_message",

    "console_log",

    "record_bot_reply",

    "increment_api_call",

    "get_group_display_name",

    "get_user_avatar_url",

    "bind_group_qq_number",

    "bind_user_qq_number",

    "get_group_qq_number",

    "get_user_qq_number",

    "get_group_profile",

    "set_group_name",

    "_restart_bot",

    "_shutdown_bot",

    "_get_status_data",

    "fetch_and_save_qq_info",

    "get_user_detail_info",

    "is_feature_enabled",

    "register_bot_bridge",

    "is_sub_feature_enabled",

    "resolve_sub_feature",

    "sub_feature_key_for_cmd",

    "update_group_contact",

    "remove_group_contact",

    "update_friend_contact",

    "remove_friend_contact",

    "sync_contact_from_message",

    "append_ws_log",

]

_lock = threading.RLock()

_started_at = time.time()

_status = {

    "started_at": _started_at,

    "bot_pid": os.getpid(),

    "uptime_seconds": 0,

    "message_count": 0,

    "command_count": 0,

    "api_call_count": 0,

    "last_message": "",

    "last_message_at": "",

}

_features = {

    "checkin": True, "video": True, "music": True, "game": True,

    "tools": True, "study": True, "novel": True, "group_admin": True,

    "image": True, "image_acg": True, "image_wallpaper": True, "image_bizhi": True,

    "image_yscos": True, "image_ys": True, "image_meinvpic": True, "image_random": True,

    "game_qiuqian": True, "game_daanzi": True, "game_tarot": True, "game_horoscope": True,
    "tool_disease": True, "tool_waste": True, "tool_navigation": True, "tool_tourism": True,

    "ai": True,
    "study_quiz": True, "study_driving": True, "study_math": True, "study_poetry": True,

}

_sub_features = {}

_group_qq_bindings = {}

_user_qq_bindings = {}

# 绑定数据持久化：避免 bot 重启后用户需重新绑QQ / 绑群号，

# 进而让「我的信息」「群资料」等依赖绑定的功能重启后直接可用。

_QQ_BINDINGS_FILE = os.path.join(

    os.path.dirname(os.path.abspath(__file__)), "data", "qq_bindings.json"

)

# 群资料持久化：群名（可手动修改）、头像（根据绑定的 QQ 群号自动生成）

_GROUP_PROFILES_FILE = os.path.join(

    os.path.dirname(os.path.abspath(__file__)), "data", "group_profiles.json"

)

_group_profiles = {}

# 今日统计持久化：避免 bot 重启 / 关机后「今日进群 / 退群 / 加好友 / 删好友 / 单聊群聊消息」计数清零。

# 以本地自然日为周期（跨天在 _rollover_today_counters_if_needed 中重置），同日内跨重启保留。

_TODAY_STATS_FILE = os.path.join(

    os.path.dirname(os.path.abspath(__file__)), "data", "today_stats.json"

)

# 需要跨重启保留的「今日」计数键（message_count 等也是「今日消息」语义，故一并保留）

_TODAY_KEYS = (

    "groups_joined_today",

    "groups_left_today",

    "friends_added_today",

    "friends_removed_today",

    "message_count",

    "command_count",

    "api_call_count",

    "private_message_count",

    "group_message_count",
)

# 按机器人维度统计今日计数（与全局 _status 平行），用于仪表盘「按机器人切换查看」
_status_by_bot = {}

# ============ 原子写 + 损坏自恢复（修复重启后数据偶然消失） ============
# 根因：早期部分 _save_* 用 open(path,"w") + json.dump 直接覆盖，进程在重启 / 关机
# （os._exit 硬退出）打断的瞬间会留下「截断 / 损坏」的文件；下一次启动时 _load_*
# 解析失败返回空 -> 成员 / 单聊 / 群聊 / 管理员名单「凭空消失」。
# 修复：所有数据保存改为 写 .tmp -> fsync -> os.replace 原子替换；落盘前把当前
# 有效文件备份为 .bak；加载时若主文件损坏则自动从 .bak 恢复。

def _atomic_save_json(path, data, indent=None):
    """原子写 JSON：写临时文件 -> fsync -> 原子替换；替换前备份当前有效版本为 .bak。

    即使在 replace 瞬间被 os._exit 打断，磁盘上的正式文件也始终是「完整旧版」或
    「完整新版」，不会出现半截文件；极端情况下还能从 .bak 找回上一份好数据。
    """
    _d = os.path.dirname(path)
    try:
        if not os.path.isdir(_d):
            os.makedirs(_d, exist_ok=True)
    except Exception:
        pass
    # 备份当前有效文件（仅当存在且非空）
    try:
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            import shutil
            shutil.copyfile(path, path + ".bak")
    except Exception:
        pass
    _tmp = path + ".tmp"
    try:
        _payload = _json.dumps(data, ensure_ascii=False, indent=indent)
        with open(_tmp, "w", encoding="utf-8") as _f:
            _f.write(_payload)
            _f.flush()
            try:
                os.fsync(_f.fileno())
            except OSError:
                pass
        os.replace(_tmp, path)
        return True
    except Exception as _e:
        print("[console_server] 原子写失败 %s: %s" % (path, _e), flush=True)
        try:
            if os.path.isfile(_tmp):
                os.remove(_tmp)
        except Exception:
            pass
        return False


def _load_json_safe(path, default=None):
    """读取 JSON；主文件损坏 / 为空时自动尝试 .bak 备份恢复。都失败返回 default。"""
    for _p in (path, path + ".bak"):
        try:
            if os.path.isfile(_p) and os.path.getsize(_p) > 0:
                with open(_p, "r", encoding="utf-8") as _f:
                    return _json.load(_f)
        except Exception:
            continue
    return default if default is not None else {}


def _flush_all_data():
    """重启 / 关机前尽量把内存态数据落盘，避免 os._exit 硬退出时丢数据。"""
    for _fn in (_save_qq_bindings, lambda: _save_admin_list(_load_admin_list()),
                _save_group_info_cache, _save_members, _save_group_profiles,
                _save_group_names, _save_today_stats):
        try:
            _fn()
        except Exception:
            pass
    try:
        _BotMap._dirty = True
        _BotMap._last_flush = 0.0
        _BotMap._maybe_flush()
    except Exception:
        pass


def _save_qq_bindings():

    """把 QQ 号 / 群号绑定写入 data/qq_bindings.json（json 模块在此文件顶部以 _json 别名导入）。"""

    try:

        d = os.path.dirname(_QQ_BINDINGS_FILE)

        if not os.path.isdir(d):

            os.makedirs(d, exist_ok=True)

        with _lock:

            payload = {

                "users": dict(_user_qq_bindings),

                "groups": dict(_group_qq_bindings),

            }

        _atomic_save_json(_QQ_BINDINGS_FILE, payload)

    except Exception as e:

        print("[console_server] 保存QQ绑定失败: %s" % e, flush=True)

def _load_qq_bindings():

    try:

        data = _load_json_safe(_QQ_BINDINGS_FILE)
        if not isinstance(data, dict):
            return

        with _lock:

            _user_qq_bindings.update(

                {str(k): str(v) for k, v in (data.get("users") or {}).items()}

            )

            _group_qq_bindings.update(

                {str(k): str(v) for k, v in (data.get("groups") or {}).items()}

            )

        print(

            "[console_server] 已恢复QQ绑定: 用户 %d / 群 %d"

            % (len(_user_qq_bindings), len(_group_qq_bindings)),

            flush=True,

        )

    except Exception as e:

        print("[console_server] 加载QQ绑定失败: %s" % e, flush=True)

_load_qq_bindings()

def _load_group_profiles():

    global _group_profiles

    try:

        _profiles = {}

        _base = os.path.join(_DATA_ROOT_DIR, "bots")

        if os.path.isdir(_base):

            for _appid in os.listdir(_base):

                _fp = os.path.join(_base, _appid, "group_profiles.json")

                if not os.path.isfile(_fp):

                    continue

                try:

                    _d = _json.load(open(_fp, encoding="utf-8"))

                except Exception:

                    continue

                for _k, _v in (_d.get("profiles") or {}).items():

                    if isinstance(_v, dict):

                        _profiles[str(_k)] = {"name": str(_v.get("name","")), "avatar": str(_v.get("avatar","")), "qq": str(_v.get("qq","")), "ts": float(_v.get("ts",0) or 0)}

        if os.path.isfile(_GROUP_PROFILES_FILE):

            try:

                _d = _json.load(open(_GROUP_PROFILES_FILE, encoding="utf-8"))

                for _k, _v in (_d.get("profiles") or {}).items():

                    if isinstance(_v, dict):

                        _profiles[str(_k)] = {"name": str(_v.get("name","")), "avatar": str(_v.get("avatar","")), "qq": str(_v.get("qq","")), "ts": float(_v.get("ts",0) or 0)}

            except Exception:

                pass

        with _lock:

            _group_profiles = _profiles

        print("[console_server] 已恢复群资料: %d" % len(_group_profiles), flush=True)

    except Exception as e:

        print("[console_server] 加载群资料失败: %s" % e, flush=True)

def _save_group_profiles():

    """按机器人分桶把群资料写入 data/bots/<appid>/group_profiles.json。"""

    try:

        with _lock:

            _buckets = {}

            for _k, _v in _group_profiles.items():

                _bk = resolve_bot_key(GROUP_BOT_MAP.get(_k) or "")

                if not _bk:

                    _bk = "_shared"

                _buckets.setdefault(_bk, {})[_k] = _v

            for _bk, _items in _buckets.items():

                _f = _bot_file(_bk, "group_profiles.json")
                _atomic_save_json(_f, {"profiles": _items}, indent=2)

    except Exception as e:

        print("[console_server] 保存群资料失败: %s" % e, flush=True)

_load_group_profiles()

_group_names = {}

_user_avatars = {}

# 「有发言记录的群聊」集合持久化文件（openid 维度，跨重启 / 关机保留）

_GROUP_NAMES_FILE = os.path.join(

    os.path.dirname(os.path.abspath(__file__)), "data", "group_names.json"

)

def _load_group_names():

    """从磁盘恢复「有发言记录的群聊」集合（按机器人独立目录聚合），确保重启 / 关机后不归零。"""

    global _group_names

    try:

        _names = {}

        _base = os.path.join(_DATA_ROOT_DIR, "bots")

        if os.path.isdir(_base):

            for _appid in os.listdir(_base):

                _fp = os.path.join(_base, _appid, "group_names.json")

                if not os.path.isfile(_fp):

                    continue

                try:

                    _d = _json.load(open(_fp, encoding="utf-8"))

                except Exception:

                    continue

                if isinstance(_d, dict):

                    for _k, _v in _d.items():

                        if isinstance(_k, str) and _k:

                            _names[_k] = _v if isinstance(_v, str) else ""

        if os.path.isfile(_GROUP_NAMES_FILE):

            try:

                _d = _json.load(open(_GROUP_NAMES_FILE, encoding="utf-8"))

                if isinstance(_d, dict):

                    for _k, _v in _d.items():

                        if isinstance(_k, str) and _k:

                            _names[_k] = _v if isinstance(_v, str) else ""

            except Exception:

                pass

        with _lock:

            _group_names = _names

    except Exception as e:

        print("[console_server] 加载群发言记录失败（忽略）: %s" % e, flush=True)

def _save_group_names():

    """按机器人分桶原子落盘「有发言记录的群聊」集合。"""

    try:

        with _lock:

            _buckets = {}

            for _k, _v in _group_names.items():

                _bk = resolve_bot_key(GROUP_BOT_MAP.get(_k) or "")

                if not _bk:

                    _bk = "_shared"

                _buckets.setdefault(_bk, {})[_k] = _v

            for _bk, _items in _buckets.items():

                _f = _bot_file(_bk, "group_names.json")
                _atomic_save_json(_f, _items, indent=2)

    except Exception as e:

        print("[console_server] 保存群发言记录失败（忽略）: %s" % e, flush=True)

def _note_group_message(group_openid, nickname=""):

    """记录某群「有发言记录」（幂等）。新增群或补全群名时落盘，返回是否本次发生落盘。"""

    if not group_openid:

        return False

    with _lock:

        existed = group_openid in _group_names

        cur = _group_names.get(group_openid, "")

        new_name = (nickname or "")[:64]

        if not existed:

            # 新群：无论是否已知群名都计入（群名未知时存空串，后续补全）

            _group_names[group_openid] = new_name

            is_new = True

        elif new_name and not cur:

            # 既有群：仅当首次补全群名时落盘

            _group_names[group_openid] = new_name

            is_new = True

        else:

            is_new = False

    if is_new:

        _save_group_names()

    return is_new

_load_group_names()

# ====== 成员归集（用于「成员管理」页） ======

# 把机器人收到过的真实用户消息归集为成员档案，持久化到 data/members.json，

# 让「成员管理」页在 bot 重启后依然保留成员列表。


# ============================================================
# 多机器人物理隔离：每个机器人独立数据目录 data/bots/<appid>/
# 稳定主键用 appid（botpy 凭证，重启不变）；name_rt 仅运行时存在，用于解析。
# ============================================================

def _bot_data_dir(appid):
    d = os.path.join(_DATA_ROOT_DIR, "bots", str(appid))
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d

def _bot_file(appid, fname):
    return os.path.join(_bot_data_dir(appid), fname)

def resolve_bot_key(bot):
    """把传入的 bot 标识（name_rt / name / appid / 空）解析为稳定的 appid 字符串。
    无法解析时返回原值（保证不丢数据）。"""
    if not bot:
        return ""
    bot = str(bot).strip()
    if bot in _bot_bridges:
        return bot
    for _aid, _br in _bot_bridges.items():
        if _br.get("name") == bot or _br.get("appid") == bot:
            return _aid
    try:
        for _b in bot_manager.load_bots():
            if str(_b.get("appid")) == bot or (_b.get("name_rt") or _b.get("name")) == bot:
                return str(_b.get("appid"))
    except Exception:
        pass
    return bot

class _BotMap(dict):
    """GROUP_BOT_MAP / USER_BOT_MAP 的持久化子类：写入时落盘 data/group_bot_map.json（节流 5s）。"""
    _last_flush = 0.0
    _dirty = False
    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        _BotMap._dirty = True
        _BotMap._maybe_flush()
    @classmethod
    def _maybe_flush(cls):
        import time as _t
        _now = _t.time()
        if not cls._dirty:
            return
        if _now - cls._last_flush < 5:
            return
        cls._last_flush = _now
        cls._dirty = False
        try:
            _p = os.path.join(_DATA_ROOT_DIR, "group_bot_map.json")
            _atomic_save_json(_p, {"groups": dict(GROUP_BOT_MAP), "users": dict(USER_BOT_MAP)})
        except Exception:
            cls._dirty = True

def _load_group_bot_map():
    try:
        _p = os.path.join(_DATA_ROOT_DIR, "group_bot_map.json")
        if not os.path.isfile(_p):
            return
        _d = _json.load(open(_p, encoding="utf-8"))
        with _lock:
            GROUP_BOT_MAP.update({str(k): str(v) for k, v in (_d.get("groups") or {}).items()})
            USER_BOT_MAP.update({str(k): str(v) for k, v in (_d.get("users") or {}).items()})
    except Exception:
        pass

_members = {}

# ====== OIAPI Openid 反查昵称缓存（免鉴权官方渠道） ======

# 用于填 _upsert_member 时 author.username 为空 / 用户未绑 QQ 时无法反查昵称的洞。

# key: openid, value: nickname

_oiapi_nickname_cache = {}

_members_seq = 0

_MEMBERS_FILE = os.path.join(

    os.path.dirname(os.path.abspath(__file__)), "data", "members.json"

)

def _member_to_json(m):

    out = dict(m)

    out["sources"] = list(m.get("sources") or [])

    return out

def _save_members():

    try:

        with _lock:

            _buckets = {}

            for _k, _v in _members.items():

                _bk = resolve_bot_key(_v.get("bot") or "")

                if not _bk:

                    _bk = "_shared"

                _buckets.setdefault(_bk, {})[_k] = _v

            for _bk, _items in _buckets.items():

                _payload = {"seq": _members_seq, "members": {_kk: _member_to_json(_vv) for _kk, _vv in _items.items()}}

                _f = _bot_file(_bk, "members.json")
                _atomic_save_json(_f, _payload)

    except Exception as e:

        print("[console_server] 保存成员失败: %s" % e, flush=True)

def _load_members():

    global _members_seq

    try:

        _base = os.path.join(_DATA_ROOT_DIR, "bots")

        if os.path.isdir(_base):

            for _appid in os.listdir(_base):

                _merge_members_file(os.path.join(_base, _appid, "members.json"))

        if os.path.isfile(_MEMBERS_FILE):

            _merge_members_file(_MEMBERS_FILE)

        print("[console_server] 已恢复成员 %d 条" % len(_members), flush=True)

    except Exception as e:

        print("[console_server] 加载成员失败: %s" % e, flush=True)

def _merge_members_file(_fp):

    global _members_seq

    try:

        data = _load_json_safe(_fp)
        if not isinstance(data, dict):
            return 0

        with _lock:

            for k, v in (data.get("members") or {}).items():

                if isinstance(v, dict) and v.get("openid"):

                    v["sources"] = set(v.get("sources") or [])

                    _members[str(k)] = v

            _members_seq = max(_members_seq, int(data.get("seq", 0) or 0))

        return 1

    except Exception:

        return 0

_load_members()

# ============================================================

# 功能配置持久化

# ============================================================

_FEATURE_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "feature_configs.json")

_QA_RULES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "qa_rules.json")

_feature_configs = {}

_qa_rules = []

_qa_rules_seq = 0

def _load_feature_configs():

    global _feature_configs

    try:

        with open(_FEATURE_CONFIG_FILE, "r", encoding="utf-8") as f:

            data = _json.load(f)

        if isinstance(data, dict):

            _feature_configs = data

            print("[console_server] 已恢复功能配置 %d 条" % len(_feature_configs), flush=True)

    except Exception as e:

        print("[console_server] 加载功能配置失败: %s" % e, flush=True)

        _feature_configs = {}

def _save_feature_configs():

    try:

        tmp = _FEATURE_CONFIG_FILE + ".tmp"

        with open(tmp, "w", encoding="utf-8") as f:

            _json.dump(_feature_configs, f, ensure_ascii=False, indent=2)

        os.replace(tmp, _FEATURE_CONFIG_FILE)

    except Exception as e:

        print("[console_server] 保存功能配置失败: %s" % e, flush=True)
_RUNTIME_SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "runtime_settings.json")

# 运行设置：9 个默认键（三层作用域 global > bot > group > 默认值）
RUNTIME_SETTINGS_SCHEMA = {
    "ignore_bot_messages": {"type": "bool", "default": False, "label": "忽略其他机器人消息", "desc": "开启后，机器人将忽略来自其他 QQ 机器人账号的消息（按 全局/机器人/群 三层作用域生效）"},
    "command.prefix": {"type": "string", "default": "", "label": "指令前缀", "desc": "所有指令前必须加此前缀才会触发；留空表示兼容旧行为（关键词直接触发，/ 作为可选前缀）"},
    "framework.rate_limit.enabled": {"type": "bool", "default": False, "label": "启用指令限速", "desc": "开启后限制同一用户单位时间内的指令次数，超限静默丢弃"},
    "framework.rate_limit.window_ms": {"type": "int", "default": 3000, "label": "限速窗口(毫秒)", "desc": "滑动窗口长度，仅统计窗口内的指令次数"},
    "console.refresh_interval_ms": {"type": "int", "default": 5000, "label": "控制台刷新间隔(毫秒)", "desc": "前端各页面的数据轮询间隔"},
    "media.download.enabled": {"type": "bool", "default": True, "label": "允许媒体下载", "desc": "关闭后将不再响应随机图 / 角色图库等出图指令"},
    "media.download.max_file_bytes": {"type": "int", "default": 10485760, "label": "单文件大小上限(字节)", "desc": "超过此大小的缓存媒体将被清理（0 表示不限制）"},
    "media.storage.ttl_days": {"type": "int", "default": 7, "label": "媒体留存天数", "desc": "缓存媒体超过该天数将被清理（0 表示不限制）"},
    "media.storage.max_bytes": {"type": "int", "default": 104857600, "label": "媒体缓存上限(字节)", "desc": "缓存总大小超过此值时按最旧优先清理（0 表示不限制）"},
    "plugin.market.repo_url": {"type": "string", "default": "", "label": "插件市场仓库地址", "desc": "填仓库地址即可（github.com 或 raw.githubusercontent.com 均可；缺失分支自动补 main）。如 https://github.com/OWNER/REPO。留空使用默认仓库；保存后即时生效，无需重启。index.json 可放在根目录或「插件市场」子目录，bot 会自动依次尝试两个位置。"},
    "feedback.form_url": {"type": "string", "default": "", "label": "问题反馈表单链接", "desc": "用户点击「反馈」按钮后跳转的收集表链接，可在控制台功能配置中修改并即时热加载生效，无需重启。⚠️ 开源部署请填你自己的腾讯问卷/Google Forms 链接，留空则按钮不显示。"},
    "feedback.enabled": {"type": "bool", "default": False, "label": "启用问题反馈入口", "desc": "关闭后，菜单中的「反馈」按钮将不再显示，机器人也不再响应反馈相关关键词。⚠️ 开启前请先在「问题反馈表单链接」里填好你的收集表链接。"},
    "experience_group.enabled": {"type": "bool", "default": True, "label": "启用体验群入口", "desc": "关闭后，菜单中的「加入体验群」按钮将不再显示，机器人也不再响应加群相关关键词。"},
    "experience_group.url": {"type": "string", "default": "", "label": "体验群加入链接", "desc": "用户点击「加入体验群」按钮后跳转的加群分享链接，可在控制台功能配置中修改并即时热加载生效，无需重启。⚠️ 此链接会暴露真实群号与邀请人 openid，开源部署请留空或填你自己的链接。"},
}

_runtime_settings = {"global": {}, "bots": {}, "groups": {}}


# ============================================================
# 管理台品牌信息（侧边栏 logo + 标题）
# 独立于 runtime_settings，因为 logo 通常是 base64 图片、比较大
# 存放在 data/admin_brand.json
# ============================================================
_ADMIN_BRAND_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "admin_brand.json"
)
_admin_brand_cache = None
_admin_brand_mtime = 0.0
_admin_brand_lock = threading.Lock()


def _load_admin_brand() -> dict:
    """读取 data/admin_brand.json；带 mtime 缓存。"""
    global _admin_brand_cache, _admin_brand_mtime
    with _admin_brand_lock:
        try:
            _mt = os.path.getmtime(_ADMIN_BRAND_FILE) if os.path.exists(_ADMIN_BRAND_FILE) else 0.0
            if _admin_brand_cache is not None and abs(_mt - _admin_brand_mtime) < 0.001:
                return _admin_brand_cache
            if not os.path.exists(_ADMIN_BRAND_FILE):
                _admin_brand_cache = {"title": "小流萤管理后台", "logo": ""}
                _admin_brand_mtime = 0.0
                return _admin_brand_cache
            with open(_ADMIN_BRAND_FILE, "r", encoding="utf-8") as _f:
                _data = _json.load(_f) or {}
            _admin_brand_cache = {
                "title": str(_data.get("title") or "小流萤管理后台"),
                "logo": str(_data.get("logo") or ""),
                "logo_updated_at": int(_data.get("logo_updated_at") or 0),
            }
            _admin_brand_mtime = _mt
            return _admin_brand_cache
        except Exception:
            return {"title": "小流萤管理后台", "logo": ""}


def _save_admin_brand(brand: dict, reset: bool = False) -> tuple:
    """保存 data/admin_brand.json。reset=True 时清空。"""
    global _admin_brand_cache, _admin_brand_mtime
    with _admin_brand_lock:
        try:
            os.makedirs(os.path.dirname(_ADMIN_BRAND_FILE), exist_ok=True)
            if reset:
                _data = {"title": "小流萤管理后台", "logo": ""}
            else:
                _data = {
                    "title": str(brand.get("title") or "小流萤管理后台"),
                    "logo": str(brand.get("logo") or ""),
                    "logo_updated_at": int(__import__("time").time()),
                }
            # 原子写：先写临时文件再 rename
            _tmp = _ADMIN_BRAND_FILE + ".tmp"
            with open(_tmp, "w", encoding="utf-8") as _f:
                _json.dump(_data, _f, ensure_ascii=False)
            os.replace(_tmp, _ADMIN_BRAND_FILE)
            _admin_brand_cache = _data
            _admin_brand_mtime = os.path.getmtime(_ADMIN_BRAND_FILE)
            return (True, None)
        except Exception as _e:
            return (False, str(_e))


# ============================================================
# 流萤FM 音乐面板自定义（标题/副标题/唱片封面）
# ============================================================
_MUSIC_FM_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "music_fm.json"
)
_music_fm_cache = None
_music_fm_mtime = 0.0
_music_fm_lock = threading.Lock()

_MUSIC_FM_DEFAULTS = {
    "title": "流萤FM",
    "subtitle": "与流萤一起走在路上",
    "cover": "/admin/assets/music/cover.png",
}


def _load_music_fm() -> dict:
    """读取 data/music_fm.json；带 mtime 缓存。"""
    global _music_fm_cache, _music_fm_mtime
    with _music_fm_lock:
        try:
            _mt = os.path.getmtime(_MUSIC_FM_FILE) if os.path.exists(_MUSIC_FM_FILE) else 0.0
            if _music_fm_cache is not None and abs(_mt - _music_fm_mtime) < 0.001:
                return _music_fm_cache
            if not os.path.exists(_MUSIC_FM_FILE):
                _music_fm_cache = dict(_MUSIC_FM_DEFAULTS)
                _music_fm_mtime = 0.0
                return _music_fm_cache
            with open(_MUSIC_FM_FILE, "r", encoding="utf-8") as _f:
                _data = _json.load(_f) or {}
            _music_fm_cache = {
                "title": str(_data.get("title") or _MUSIC_FM_DEFAULTS["title"]),
                "subtitle": str(_data.get("subtitle") or _MUSIC_FM_DEFAULTS["subtitle"]),
                "cover": str(_data.get("cover") or _MUSIC_FM_DEFAULTS["cover"]),
            }
            _music_fm_mtime = _mt
            return _music_fm_cache
        except Exception:
            return dict(_MUSIC_FM_DEFAULTS)


def _save_music_fm(fm: dict, reset: bool = False) -> tuple:
    """保存 data/music_fm.json。reset=True 时清空为默认。"""
    global _music_fm_cache, _music_fm_mtime
    with _music_fm_lock:
        try:
            os.makedirs(os.path.dirname(_MUSIC_FM_FILE), exist_ok=True)
            if reset:
                _data = dict(_MUSIC_FM_DEFAULTS)
            else:
                _data = {
                    "title": str(fm.get("title") or _MUSIC_FM_DEFAULTS["title"]),
                    "subtitle": str(fm.get("subtitle") or _MUSIC_FM_DEFAULTS["subtitle"]),
                    "cover": str(fm.get("cover") or _MUSIC_FM_DEFAULTS["cover"]),
                }
            _tmp = _MUSIC_FM_FILE + ".tmp"
            with open(_tmp, "w", encoding="utf-8") as _f:
                _json.dump(_data, _f, ensure_ascii=False)
            os.replace(_tmp, _MUSIC_FM_FILE)
            _music_fm_cache = _data
            _music_fm_mtime = os.path.getmtime(_MUSIC_FM_FILE)
            return (True, None)
        except Exception as _e:
            return (False, str(_e))


def _load_runtime_settings():
    global _runtime_settings
    try:
        with open(_RUNTIME_SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = _json.load(f)
        if isinstance(data, dict):
            _runtime_settings = {
                "global": data.get("global", {}) or {},
                "bots": data.get("bots", {}) or {},
                "groups": data.get("groups", {}) or {},
            }
            print("[console_server] 已恢复运行设置 global=%d bots=%d groups=%d" % (
                len(_runtime_settings["global"]), len(_runtime_settings["bots"]), len(_runtime_settings["groups"])), flush=True)
            return
    except Exception as e:
        print("[console_server] 加载运行设置失败: %s" % e, flush=True)
    _runtime_settings = {"global": {}, "bots": {}, "groups": {}}


def _save_runtime_settings():
    try:
        tmp = _RUNTIME_SETTINGS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            _json.dump(_runtime_settings, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _RUNTIME_SETTINGS_FILE)
    except Exception as e:
        print("[console_server] 保存运行设置失败: %s" % e, flush=True)


def _coerce_runtime_value(key, raw):
    schema = RUNTIME_SETTINGS_SCHEMA.get(key)
    if schema is None:
        return None
    t = schema["type"]
    try:
        if t == "bool":
            if isinstance(raw, bool):
                return raw
            if isinstance(raw, str):
                return raw.strip().lower() in ("1", "true", "yes", "y", "on", "开", "开启")
            return bool(raw)
        if t == "int":
            return int(raw)
        if t == "string":
            return "" if raw is None else str(raw)
    except Exception:
        return schema["default"]
    return schema["default"]


def get_runtime_setting(key, scope="global", id=""):
    """返回指定作用域下的覆盖值；无覆盖返回 None。"""
    if scope == "global":
        return _runtime_settings.get("global", {}).get(key)
    bucket = "bots" if scope == "bot" else "groups"
    id = str(id or "").strip()
    if not id:
        return None
    return _runtime_settings.get(bucket, {}).get(id, {}).get(key)


def get_runtime_setting_effective(key, appid=None, group_id=None):
    """按 群 > 机器人 > 全局 > 默认值 优先级解析最终生效值。"""
    schema = RUNTIME_SETTINGS_SCHEMA.get(key)
    if schema is None:
        return None
    with _lock:
        if group_id:
            g = _runtime_settings.get("groups", {}).get(str(group_id))
            if isinstance(g, dict) and key in g:
                return g[key]
        if appid:
            b = _runtime_settings.get("bots", {}).get(str(appid))
            if isinstance(b, dict) and key in b:
                return b[key]
        gv = _runtime_settings.get("global", {})
        if key in gv:
            return gv[key]
    return schema["default"]


def set_runtime_setting(key, value, scope="global", id=""):
    if key not in RUNTIME_SETTINGS_SCHEMA:
        return False, "未知配置键: %s" % key
    if scope not in ("global", "bot", "group"):
        return False, "非法作用域: %s" % scope
    val = _coerce_runtime_value(key, value)
    with _lock:
        if scope == "global":
            _runtime_settings["global"][key] = val
        else:
            id = str(id or "").strip()
            if not id:
                return False, "%s 作用域需要 id" % scope
            bucket = "bots" if scope == "bot" else "groups"
            _runtime_settings.setdefault(bucket, {})
            _runtime_settings[bucket].setdefault(id, {})
            _runtime_settings[bucket][id][key] = val
    _save_runtime_settings()
    return True, ""


def reset_runtime_setting(key, scope="global", id=""):
    if scope not in ("global", "bot", "group"):
        return False, "非法作用域: %s" % scope
    with _lock:
        if scope == "global":
            _runtime_settings["global"].pop(key, None)
        else:
            id = str(id or "").strip()
            if not id:
                return False, "%s 作用域需要 id" % scope
            bucket = "bots" if scope == "bot" else "groups"
            d = _runtime_settings.get(bucket, {}).get(id)
            if d and key in d:
                del d[key]
    _save_runtime_settings()
    return True, ""


def reset_all_runtime_settings(scope="global", id=""):
    if scope not in ("global", "bot", "group"):
        return False, "非法作用域: %s" % scope
    with _lock:
        if scope == "global":
            _runtime_settings["global"] = {}
        else:
            id = str(id or "").strip()
            if not id:
                return False, "%s 作用域需要 id" % scope
            bucket = "bots" if scope == "bot" else "groups"
            if _runtime_settings.get(bucket):
                _runtime_settings[bucket].pop(id, None)
    _save_runtime_settings()
    return True, ""


def _enforce_runtime_media_storage():
    """按运行设置 media.storage.* / media.download.max_file_bytes 限制缓存媒体体积与留存。返回 (freed, deleted)。"""
    try:
        _ttl = int(get_runtime_setting_effective("media.storage.ttl_days") or 0)
        _max = int(get_runtime_setting_effective("media.storage.max_bytes") or 0)
        _max_file = int(get_runtime_setting_effective("media.download.max_file_bytes") or 0)
    except Exception:
        _ttl, _max, _max_file = 0, 0, 0
    if not _ttl and not _max and not _max_file:
        return 0, 0
    try:
        import time as _t
        root = _project_root()
        files = []
        for _key, _cat in _CACHE_CATEGORIES.items():
            if not _cat.get("deletable", True):
                continue
            _paths = _cat.get("paths") or ([_cat["path"]] if _cat.get("path") else [])
            _glob = _cat.get("glob") or "*"
            for _rel in _paths:
                _full = os.path.join(root, _rel)
                if not os.path.exists(_full):
                    continue
                if os.path.isfile(_full):
                    if _glob and not _fnmatch.fnmatch(os.path.basename(os.path.abspath(_full)), _glob):
                        continue
                    files.append(_full)
                elif os.path.isdir(_full):
                    for _r, _, _fs in os.walk(_full):
                        for _fn in _fs:
                            if _glob and not _fnmatch.fnmatch(_fn, _glob):
                                continue
                            files.append(os.path.join(_r, _fn))
        _now = _t.time()
        _deleted = 0
        _freed = 0
        # ttl 清理
        if _ttl:
            _cutoff = _now - _ttl * 86400.0
            _keep = []
            for _fp in files:
                try:
                    _st = os.stat(_fp)
                    if _st.st_mtime >= _cutoff:
                        _keep.append(_fp)
                    else:
                        _sz = _st.st_size
                        os.remove(_fp)
                        _freed += _sz
                        _deleted += 1
                except OSError:
                    _keep.append(_fp)
            files = _keep
        # 单文件大小上限清理
        if _max_file:
            _keep2 = []
            for _fp in files:
                try:
                    _sz = os.path.getsize(_fp)
                    if _sz > _max_file:
                        os.remove(_fp)
                        _freed += _sz
                        _deleted += 1
                    else:
                        _keep2.append(_fp)
                except OSError:
                    _keep2.append(_fp)
            files = _keep2
        # 体积上限清理（最旧优先）
        if _max:
            try:
                files.sort(key=lambda q: os.stat(q).st_mtime)
            except Exception:
                pass
            _total = 0
            for _fp in files:
                try:
                    _total += os.path.getsize(_fp)
                except OSError:
                    pass
            _i = 0
            while _total > _max and _i < len(files):
                try:
                    _sz = os.path.getsize(files[_i])
                    os.remove(files[_i])
                    _total -= _sz
                    _freed += _sz
                    _deleted += 1
                except OSError:
                    pass
                _i += 1
        if _deleted:
            print("[cache-clean] 运行设置媒体存储限制: 清理 %d 文件, 释放 %s" % (_deleted, _format_size(_freed)), flush=True)
        return _freed, _deleted
    except Exception as e:
        print("[cache-clean] 运行设置媒体存储限制失败: %s" % e, flush=True)
        return 0, 0

def _load_qa_rules():

    global _qa_rules, _qa_rules_seq

    try:

        _merged = []

        _base = os.path.join(_DATA_ROOT_DIR, "bots")

        if os.path.isdir(_base):

            for _appid in os.listdir(_base):

                _fp = os.path.join(_base, _appid, "qa_rules.json")

                if os.path.isfile(_fp):

                    try:

                        _merged.extend(_json.load(open(_fp, encoding="utf-8")) or [])

                    except Exception:

                        pass

        if os.path.isfile(_QA_RULES_FILE):

            try:

                _merged.extend(_json.load(open(_QA_RULES_FILE, encoding="utf-8")) or [])

            except Exception:

                pass

        _qa_rules = _merged

        _qa_rules_seq = max([r.get("id", 0) for r in _qa_rules] or [0])

        print("[console_server] 已恢复问答规则 %d 条" % len(_qa_rules), flush=True)

    except Exception as e:

        print("[console_server] 加载问答规则失败: %s" % e, flush=True)

        _qa_rules = []

        _qa_rules_seq = 0

def _save_qa_rules():

    try:

        with _lock:

            _buckets = {}

            for _r in _qa_rules:

                _bk = resolve_bot_key(_r.get("bot") or "")

                if not _bk:

                    _bk = "_shared"

                _buckets.setdefault(_bk, []).append(_r)

            for _bk, _items in _buckets.items():

                _f = _bot_file(_bk, "qa_rules.json")

                _tmp = _f + ".tmp"

                with open(_tmp, "w", encoding="utf-8") as _fh:

                    _json.dump(_items, _fh, ensure_ascii=False, indent=2)

                os.replace(_tmp, _f)

    except Exception as e:

        print("[console_server] 保存问答规则失败: %s" % e, flush=True)

# ============================================================

# 系统功能开关配置持久化

# ============================================================

_SYSTEM_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "system_config.json")

_system_switches = {}

# 多机器人独立功能开关：{appid: {key: bool}}。
# 运行时优先查本字段，未配置时回退 _system_switches（全局默认），
# 再回退 _features，最后默认开启。空 dict 表示该机器人完全跟随全局。
_bot_system_switches = {}

# 视频限制配置：parse=视频解析（抖音/B站无水印），system=视频系统（B站搜索/排行榜）

# max_duration: 最大时长（秒），0=不限制；max_mb: 最大大小（MB），0=不限制

_VIDEO_LIMITS_DEFAULT = {

    "parse":  {"max_duration": 1200, "max_mb": 0},

    "system": {"max_duration": 1200, "max_mb": 0},

}

_video_limits = {}

# ============================================================

# 缓存清理白名单与配置

# ============================================================

# 绝对可清理的缓存/日志白名单。任何数据文件（*.json 配置、members.json、admin_list.json、ai_providers.json 等）都不在白名单内。

# is_dir: True=目录（按 glob 扫描文件），False=单文件

_CACHE_CATEGORIES = {

    "botpy_log": {

        "label": "botpy SDK 日志",

        "path": "botpy.log",

        "is_dir": False,

        "description": "botpy 官方 SDK 的运行日志，体积通常最大（2-10MB）",

        "deletable": True,

    },

    "bot_log": {

        "label": "启动日志 bot.log",

        "path": "bot.log",

        "is_dir": False,

        "description": "机器人启动时写入的旧日志",

        "deletable": True,

    },

    "bot_stdout_log": {

        "label": "stdout 重定向日志",

        "path": "bot_stdout.log",

        "is_dir": False,

        "description": "启动时 stdout 流的输出重定向",

        "deletable": True,

    },

    "bot_stderr_log": {

        "label": "stderr 重定向日志",

        "path": "bot_stderr.log",

        "is_dir": False,

        "description": "启动时 stderr 流的输出重定向",

        "deletable": True,

    },

    "data_logs": {

        "label": "历史运行日志 data/logs",

        "path": "data/logs",

        "is_dir": True,

        "glob": "*.log",

        "description": "按 bot 划分的运行日志目录",

        "deletable": True,

    },

    "novel_cache": {

        "label": "小说图片缓存",

        "path": "data/cache/novel_img",

        "is_dir": True,

        "glob": "*",

        "description": "渲染小说插图时缓存的 PNG（重新渲染时自动重建）",

        "deletable": True,

    },

    "admin_media": {

        "label": "上传媒体文件",

        "path": "admin/media",

        "is_dir": True,

        "glob": "*",

        "description": "聊天上传/解析下载的图片/音频/视频缓存",

        "deletable": True,

    },

    "pycache": {

        "label": "Python 编译缓存",

        "paths": ["__pycache__", "modules/__pycache__", "admin/__pycache__", "data/__pycache__"],

        "is_dir": True,

        "glob": "*.pyc",

        "description": "Python .pyc 编译缓存（重启 bot 时自动重建，删除不影响功能）",

        "deletable": True,

    },

}

# 定时清理默认配置

_CACHE_CLEAN_DEFAULT = {

    "enabled": False,

    "schedule": "daily",   # daily / weekly / monthly

    "weekday": 0,          # 仅 weekly：0=周一 ... 6=周日

    "month_day": 1,        # 仅 monthly：1-28

    "hour": 3,             # 0-23

    "minute": 0,           # 0-59

    "max_age_days": 0,     # 0=不限制（删全部）；>0=只删 N 天前的文件

    "items": ["botpy_log", "bot_log", "bot_stdout_log", "bot_stderr_log", "data_logs", "novel_cache"],

    "last_run": "",

}

_cache_clean_config = {}

# 整点报时（自动）默认配置（按群独立）

_CHIME_DEFAULT = {

    "enabled": False,

    "interval_hours": 1,      # 每隔几小时在整点报时一次（1-24）

    "period_start": 0,        # 每日可报时时段起点（小时，0-23，含）

    "period_end": 23,         # 每日可报时时段终点（小时，0-23，含）

    "last_run": "",

}

_chime_groups = {}   # {group_openid: dict(同上)，每个群的设置相互独立}

# 签到积分规则（可在后台「功能配置 → 签到规则」页配置，无需改代码）

_CHECKIN_DEFAULT = {

    "base_points": 10,     # 每次签到固定基础积分

    "bonus_per_day": 5,    # 连续签到每天递增的奖励积分（第 N 天连签奖励 = N * bonus_per_day，封顶 bonus_cap）

    "bonus_cap": 200,      # 连签奖励单日封顶

    "lottery_cost": 50,    # 积分抽奖每次消耗积分

    "lottery_daily_limit": 2,  # 每日抽奖次数上限（0 = 不限制）

}

_checkin_config = dict(_CHECKIN_DEFAULT)

def _default_cache_clean():

    import copy as _copy

    return _copy.deepcopy(_CACHE_CLEAN_DEFAULT)

def _default_chime_group():

    import copy as _copy

    return _copy.deepcopy(_CHIME_DEFAULT)

def get_chime_group_config(group_openid):

    """返回指定群的整点报时配置（含默认值与数值校验）。"""

    out = dict(_default_chime_group())

    with _lock:

        src = _chime_groups.get(group_openid) or {}

    out.update(src)

    out["enabled"] = bool(out.get("enabled"))

    out["interval_hours"] = max(1, min(24, _coerce_int(out.get("interval_hours", 1), 1)))

    out["period_start"] = max(0, min(23, _coerce_int(out.get("period_start", 0), 0)))

    out["period_end"] = max(0, min(23, _coerce_int(out.get("period_end", 23), 23)))

    return out

def get_checkin_config():

    """返回签到积分规则配置（含默认值与数值校验），供 checkin.py 运行时读取。"""

    with _lock:

        src = dict(_checkin_config)

    base = max(0, _coerce_int(src.get("base_points", _CHECKIN_DEFAULT["base_points"]), _CHECKIN_DEFAULT["base_points"]))

    per = max(0, _coerce_int(src.get("bonus_per_day", _CHECKIN_DEFAULT["bonus_per_day"]), _CHECKIN_DEFAULT["bonus_per_day"]))

    cap = max(0, _coerce_int(src.get("bonus_cap", _CHECKIN_DEFAULT["bonus_cap"]), _CHECKIN_DEFAULT["bonus_cap"]))

    cost = max(1, _coerce_int(src.get("lottery_cost", _CHECKIN_DEFAULT["lottery_cost"]), _CHECKIN_DEFAULT["lottery_cost"]))

    limit = max(0, _coerce_int(src.get("lottery_daily_limit", _CHECKIN_DEFAULT["lottery_daily_limit"]), _CHECKIN_DEFAULT["lottery_daily_limit"]))

    return {

        "base_points": base,

        "bonus_per_day": per,

        "bonus_cap": cap,

        "lottery_cost": cost,

        "lottery_daily_limit": limit,

    }

def set_checkin_config(payload):

    """更新签到积分规则并持久化；返回校验后的最新配置。"""

    global _checkin_config

    if not isinstance(payload, dict):

        return get_checkin_config()

    with _lock:

        cfg = dict(_checkin_config)

        if payload.get("base_points") is not None:

            cfg["base_points"] = max(0, _coerce_int(payload.get("base_points"), cfg.get("base_points", _CHECKIN_DEFAULT["base_points"])))

        if payload.get("bonus_per_day") is not None:

            cfg["bonus_per_day"] = max(0, _coerce_int(payload.get("bonus_per_day"), cfg.get("bonus_per_day", _CHECKIN_DEFAULT["bonus_per_day"])))

        if payload.get("bonus_cap") is not None:

            cfg["bonus_cap"] = max(0, _coerce_int(payload.get("bonus_cap"), cfg.get("bonus_cap", _CHECKIN_DEFAULT["bonus_cap"])))

        if payload.get("lottery_cost") is not None:

            cfg["lottery_cost"] = max(1, _coerce_int(payload.get("lottery_cost"), cfg.get("lottery_cost", _CHECKIN_DEFAULT["lottery_cost"])))

        if payload.get("lottery_daily_limit") is not None:

            cfg["lottery_daily_limit"] = max(0, _coerce_int(payload.get("lottery_daily_limit"), cfg.get("lottery_daily_limit", _CHECKIN_DEFAULT["lottery_daily_limit"])))

        _checkin_config = cfg

    _save_system_config()

    return get_checkin_config()

def set_chime_group_enabled(group_openid, enabled):

    """设置指定群整点报时（自动）启用状态并持久化；返回最新配置。"""

    if not group_openid:

        return None

    enabled = bool(enabled)

    with _lock:

        cfg = dict(_chime_groups.get(group_openid) or _default_chime_group())

        if enabled and not cfg.get("last_run"):

            from datetime import datetime

            cfg["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cfg["enabled"] = enabled

        _chime_groups[group_openid] = cfg

    _save_system_config()

    return get_chime_group_config(group_openid)

def set_chime_group_interval(group_openid, hours):

    """设置指定群报时间隔（小时，1-24）；返回最新配置。"""

    if not group_openid:

        return None

    hours = max(1, min(24, _coerce_int(hours, 1)))

    with _lock:

        cfg = dict(_chime_groups.get(group_openid) or _default_chime_group())

        cfg["interval_hours"] = hours

        _chime_groups[group_openid] = cfg

    _save_system_config()

    return get_chime_group_config(group_openid)

def set_chime_group_period(group_openid, start, end):

    """设置指定群可报时时段（小时，0-23）；返回最新配置。"""

    if not group_openid:

        return None

    start = max(0, min(23, _coerce_int(start, 0)))

    end = max(0, min(23, _coerce_int(end, 23)))

    if start > end:

        start, end = end, start

    with _lock:

        cfg = dict(_chime_groups.get(group_openid) or _default_chime_group())

        cfg["period_start"] = start

        cfg["period_end"] = end

        _chime_groups[group_openid] = cfg

    _save_system_config()

    return get_chime_group_config(group_openid)

# 入群通知（按群独立）

_WELCOME_DEFAULT = {

    "welcome_enabled": True,   # 入群通知开关，默认打开

    "welcome_msg": "欢迎新同学加入本群", # 入群欢迎词

}

_welcome_groups = {}   # {group_openid: dict(同上)，每个群的设置相互独立}

def _default_welcome_group():

    import copy as _copy

    return _copy.deepcopy(_WELCOME_DEFAULT)

def get_welcome_group_config(group_openid):

    """返回指定群的入群通知配置（含默认值）。"""

    out = dict(_default_welcome_group())

    with _lock:

        src = _welcome_groups.get(group_openid) or {}

    out.update(src)

    out["welcome_enabled"] = bool(out.get("welcome_enabled", True))

    if not isinstance(out.get("welcome_msg"), str):

        out["welcome_msg"] = ""

    return out

def set_welcome_group_config(group_openid, **fields):

    """更新指定群的入群通知配置（仅允许修改白名单字段）并持久化；返回最新配置。"""

    if not group_openid:

        return None

    allowed = ("welcome_enabled", "welcome_msg")

    with _lock:

        cfg = dict(_welcome_groups.get(group_openid) or _default_welcome_group())

        for k in allowed:

            if k in fields:

                v = fields[k]

                if k == "welcome_enabled":

                    cfg[k] = bool(v)

                elif k == "welcome_msg":

                    cfg[k] = str(v or "")[:500]

        _welcome_groups[group_openid] = cfg

    _save_system_config()

    return get_welcome_group_config(group_openid)

def _days_in_month(y, m):

    from datetime import datetime

    if m == 12:

        nxt = datetime(y + 1, 1, 1)

    else:

        nxt = datetime(y, m + 1, 1)

    return (nxt - datetime(y, m, 1)).days

def _planned_time_for_date(cfg, date):

    """返回 date 当天应触发的 datetime（可能已过去），无则 None。"""

    from datetime import datetime, timedelta

    schedule = str(cfg.get("schedule") or "daily")

    hour = max(0, min(23, int(cfg.get("hour", 3) or 3)))

    minute = max(0, min(59, int(cfg.get("minute", 0) or 0)))

    if schedule == "weekly":

        wd = max(0, min(6, int(cfg.get("weekday", 0) or 0)))

        diff = (wd - date.weekday()) % 7

        d = date + timedelta(days=diff)

        return datetime(d.year, d.month, d.day, hour, minute)

    if schedule == "monthly":

        md = max(1, min(28, int(cfg.get("month_day", 1) or 1)))

        md = min(md, _days_in_month(date.year, date.month))

        try:

            return datetime(date.year, date.month, md, hour, minute)

        except Exception:

            return None

    return datetime(date.year, date.month, date.day, hour, minute)

def _next_trigger_after(cfg, now):

    """返回严格大于 now 的下一次触发时间（用于前端预览）。"""

    from datetime import datetime, timedelta

    today_p = _planned_time_for_date(cfg, now.date())

    if today_p and today_p > now:

        return today_p

    schedule = str(cfg.get("schedule") or "daily")

    if schedule == "daily":

        nxt = now.date() + timedelta(days=1)

    elif schedule == "weekly":

        wd = max(0, min(6, int(cfg.get("weekday", 0) or 0)))

        diff = (wd - now.weekday()) % 7

        diff = 7 if diff == 0 else diff

        nxt = now.date() + timedelta(days=diff)

    else:  # monthly

        y, m = now.year, now.month

        if m == 12:

            y, m = y + 1, 1

        else:

            m += 1

        nxt = datetime(y, m, 1).date()

    return _planned_time_for_date(cfg, nxt)

def _coerce_int(v, default=0):

    try:

        return int(v)

    except Exception:

        return default

def _default_video_limits():

    import copy as _copy

    return _copy.deepcopy(_VIDEO_LIMITS_DEFAULT)

# ============================================================

# 缓存清理：扫描 + 删除（白名单 + 路径校验）

# ============================================================

import fnmatch as _fnmatch

_PROJECT_ROOT_FOR_CACHE = None

def _project_root():

    global _PROJECT_ROOT_FOR_CACHE

    if _PROJECT_ROOT_FOR_CACHE is None:

        _PROJECT_ROOT_FOR_CACHE = os.path.dirname(os.path.abspath(__file__))

    return _PROJECT_ROOT_FOR_CACHE

def _scan_one_path(rel_path, glob_pattern):

    """扫描一个相对路径（文件或目录）按 glob 过滤，返回 (size, count, last_modified)。

    不存在/异常时返回 (0, 0, 0)。"""

    full = os.path.join(_project_root(), rel_path)

    total = 0

    count = 0

    latest = 0

    try:

        if os.path.isfile(full):

            if glob_pattern and not _fnmatch.fnmatch(os.path.basename(full), glob_pattern):

                return 0, 0, 0

            st = os.stat(full)

            return st.st_size, 1, st.st_mtime

        if os.path.isdir(full):

            for root, _, files in os.walk(full):

                for fn in files:

                    if glob_pattern and not _fnmatch.fnmatch(fn, glob_pattern):

                        continue

                    fp = os.path.join(root, fn)

                    try:

                        st = os.stat(fp)

                        total += st.st_size

                        count += 1

                        if st.st_mtime > latest:

                            latest = st.st_mtime

                    except OSError:

                        pass

    except OSError:

        pass

    return total, count, latest

def _scan_cache_category(cat):

    """扫描一个分类的 size/count/last_modified（多路径合并）。"""

    total_size = 0

    total_count = 0

    latest = 0

    paths = cat.get("paths") or ([cat["path"]] if cat.get("path") else [])

    glob_pattern = cat.get("glob") or "*"

    for p in paths:

        sz, cnt, lm = _scan_one_path(p, glob_pattern)

        total_size += sz

        total_count += cnt

        if lm > latest:

            latest = lm

    return total_size, total_count, latest

def _schedule_delete_on_reboot(path):
    """Windows 下将无法立即删除的占用文件登记为重启后删除（MOVEFILE_DELAY_UNTIL_REBOOT）。"""
    try:
        import sys
        if sys.platform != "win32":
            return
        import ctypes
        ctypes.windll.kernel32.MoveFileExW(path, None, 4)
    except Exception:
        pass


def _safe_remove_file(path):
    """删除单个文件；被其他进程占用（如运行中的 bot SDK 持有句柄）时自动多级降级：

    1) 直接 os.remove；
    2) 失败（文件被占用，Windows 下 os.rename 也会失败）则尝试把文件**截断为 0 字节**
       （Windows/Linux 下即使文件被另一进程以默认共享模式打开也能成功），立即释放
       磁盘空间，占用进程后续以 append 方式继续写入（日志场景安全）；
    3) 仍失败则登记为**重启后删除**（MOVEFILE_DELAY_UNTIL_REBOOT，Windows）。

    返回 (success, freed_bytes)。"""
    try:
        sz = os.path.getsize(path)
    except OSError:
        return False, 0
    # 1) 直接删除
    try:
        os.remove(path)
        return True, sz
    except OSError:
        pass
    # 2) 文件被占用：截断为 0 字节，立即释放空间（append 写入的日志安全）
    try:
        os.truncate(path, 0)
        return True, sz
    except OSError:
        pass
    # 3) 仍失败（极少）：登记重启后删除（仅 Windows 有效，失败静默）
    try:
        _schedule_delete_on_reboot(path)
        return True, sz
    except Exception:
        pass
    return False, 0


def _do_clean_cache(item_keys, max_age_days=0):

    """按白名单 key 列表删除缓存/日志文件，返回 (freed_bytes, deleted_files, details)。

    仅在 _CACHE_CATEGORIES 白名单内生效；路径必须位于 _project_root() 内。"""

    freed = 0

    deleted = 0

    details = []

    root = _project_root()

    import time as _time

    cutoff = (_time.time() - max_age_days * 86400.0) if max_age_days else 0

    seen_dirs = set()  # 去重避免一个目录被多次遍历

    for key in item_keys or []:

        cat = _CACHE_CATEGORIES.get(key)

        if not cat or not cat.get("deletable", True):

            details.append({

                "key": key, "label": key, "freed_bytes": 0, "deleted_files": 0, "error": "unknown category",

            })

            continue

        cat_freed = 0

        cat_deleted = 0

        err_msg = ""

        paths = cat.get("paths") or ([cat["path"]] if cat.get("path") else [])

        glob_pattern = cat.get("glob") or "*"

        for rel in paths:

            full = os.path.join(root, rel)

            # 防止逃逸：必须位于项目根下

            try:

                full_abs = os.path.abspath(full)

                if not full_abs.startswith(root):

                    err_msg = "path escape detected: %s" % rel

                    continue

            except Exception:

                continue

            if not os.path.exists(full):

                continue

            try:

                if os.path.isfile(full):

                    if glob_pattern and not _fnmatch.fnmatch(os.path.basename(full_abs), glob_pattern):

                        continue

                    try:

                        _st = os.stat(full_abs)

                        if max_age_days and _st.st_mtime >= cutoff:

                            continue

                        sz = _st.st_size

                        ok, sz = _safe_remove_file(full_abs)

                        if ok:

                            cat_freed += sz

                            cat_deleted += 1

                        else:

                            err_msg = "delete failed (file in use)"

                    except OSError as e:

                        err_msg = "delete failed: %s" % e

                elif os.path.isdir(full):

                    if full_abs in seen_dirs:

                        continue

                    seen_dirs.add(full_abs)

                    for r, _, files in os.walk(full):

                        for fn in files:

                            if glob_pattern and not _fnmatch.fnmatch(fn, glob_pattern):

                                continue

                            fp = os.path.join(r, fn)

                            try:

                                fp_abs = os.path.abspath(fp)

                                if not fp_abs.startswith(root):

                                    continue

                                _st = os.stat(fp_abs)

                                if max_age_days and _st.st_mtime >= cutoff:

                                    continue

                                sz = _st.st_size

                                ok, sz = _safe_remove_file(fp_abs)

                                if ok:

                                    cat_freed += sz

                                    cat_deleted += 1

                            except OSError:

                                pass

            except OSError as e:

                err_msg = "walk failed: %s" % e

        details.append({

            "key": key,

            "label": cat.get("label", key),

            "freed_bytes": cat_freed,

            "deleted_files": cat_deleted,

            "error": err_msg,

        })

        freed += cat_freed

        deleted += cat_deleted

    return freed, deleted, details

def _build_cache_stats_items(keys=None):

    """构造 API 返回的缓存统计列表。keys=None 表示全部。"""

    items = []

    for key, cat in _CACHE_CATEGORIES.items():

        if keys is not None and key not in keys:

            continue

        size, count, lm = _scan_cache_category(cat)

        items.append({

            "key": key,

            "label": cat.get("label", key),

            "description": cat.get("description", ""),

            "is_dir": bool(cat.get("is_dir")),

            "size_bytes": size,

            "file_count": count,

            "last_modified": int(lm),

        })

    return items

def _format_size(n):

    """字节数转人类可读字符串。"""

    try:

        n = int(n)

    except Exception:

        return "0 B"

    if n < 1024:

        return "%d B" % n

    if n < 1024 * 1024:

        return "%.1f KB" % (n / 1024.0)

    if n < 1024 * 1024 * 1024:

        return "%.2f MB" % (n / 1024.0 / 1024.0)

    return "%.2f GB" % (n / 1024.0 / 1024.0 / 1024.0)


# ============================================================
# 备份中心：将 data/ 与关键配置打包为 ZIP，便于框架升级 / 迁移
# ============================================================

_BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups")
_BACKUP_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_BACKUP_ROOT_CONFIGS = ("config.yaml", "system_config.json", "bots.json")


def _is_valid_backup_name(name):
    if not name or not name.startswith("backup_") or not name.endswith(".zip"):
        return False
    core = name[len("backup_"):-len(".zip")]
    if len(core) != 15 or core[8] != "_":
        return False
    return (core[:8] + core[9:]).isdigit()


def _create_backup():
    """打包 data/ 全量 + 根目录关键配置文件为 ZIP，返回元数据。"""
    import zipfile
    from datetime import datetime
    try:
        os.makedirs(_BACKUP_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = "backup_%s.zip" % stamp
        path = os.path.join(_BACKUP_DIR, name)
        root = os.path.dirname(os.path.abspath(__file__))
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            if os.path.isdir(_BACKUP_DATA_DIR):
                for base, _dirs, files in os.walk(_BACKUP_DATA_DIR):
                    for f in files:
                        fp = os.path.join(base, f)
                        try:
                            z.write(fp, os.path.relpath(fp, root))
                        except OSError:
                            continue
            for cf in _BACKUP_ROOT_CONFIGS:
                fp = os.path.join(root, cf)
                if os.path.isfile(fp):
                    try:
                        z.write(fp, cf)
                    except OSError:
                        continue
        size = os.path.getsize(path)
        return {"ok": True, "name": name, "size_bytes": size, "size_human": _format_size(size),
                "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _list_backups():
    if not os.path.isdir(_BACKUP_DIR):
        return []
    out = []
    for fn in sorted(os.listdir(_BACKUP_DIR)):
        if not fn.endswith(".zip"):
            continue
        fp = os.path.join(_BACKUP_DIR, fn)
        try:
            st = os.stat(fp)
            from datetime import datetime
            out.append({
                "name": fn,
                "size_bytes": st.st_size,
                "size_human": _format_size(st.st_size),
                "created": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            })
        except OSError:
            continue
    out.reverse()
    return out


def _delete_backup(name):
    if not _is_valid_backup_name(name):
        return False, "非法备份名"
    fp = os.path.join(_BACKUP_DIR, name)
    if not os.path.isfile(fp):
        return False, "备份不存在"
    try:
        os.remove(fp)
        return True, "已删除"
    except OSError as e:
        return False, str(e)


def _check_cache_clean_schedule(now=None):

    """每分钟检查：若今天应触发的时间点已过且今天尚未执行，则执行（错过自动补执行）。"""

    global _cache_clean_config

    if not _cache_clean_config or not _cache_clean_config.get("enabled"):

        return

    if not _cache_clean_config.get("items"):

        return

    from datetime import datetime

    if now is None:

        now = datetime.now()

    today_p = _planned_time_for_date(_cache_clean_config, now.date())

    if today_p is None:

        return

    last_run = str(_cache_clean_config.get("last_run") or "")

    last_run_date = last_run[:10] if last_run else ""

    today_str = now.strftime("%Y-%m-%d")

    # 补执行：今天计划时间点已过且今天还没执行过 -> 执行

    if now >= today_p and last_run_date != today_str:

        items = [k for k in (_cache_clean_config.get("items") or []) if k in _CACHE_CATEGORIES]

        if not items:

            return

        max_age = _coerce_int(_cache_clean_config.get("max_age_days", 0), 0)

        print("[cache-clean] 触发定时清理: schedule=%s items=%s max_age_days=%s" % (

            _cache_clean_config.get("schedule"), items, max_age), flush=True)

        freed, deleted, details = _do_clean_cache(items, max_age_days=max_age)
        try:
            _ms_freed, _ms_deleted = _enforce_runtime_media_storage()
            freed += _ms_freed
            deleted += _ms_deleted
        except Exception as _e:
            print("[cache-clean] 媒体存储限制执行异常: %s" % _e, flush=True)

        _cache_clean_config["last_run"] = now.strftime("%Y-%m-%d %H:%M:%S")

        try:

            _save_system_config()

        except Exception as e:

            print("[cache-clean] 保存 last_run 失败: %s" % e, flush=True)

        print("[cache-clean] 定时清理完成: 释放 %s, 删除 %d 文件, 详情=%d" % (

            _format_size(freed), deleted, len(details)), flush=True)

# 整点报时（自动）图片源，与 modules/group_admin.py 中 _CHIME_API_URL 保持一致

_CHIME_API_URL = "https://api.yuafeng.cn/API/ly/time.php"

async def _chime_broadcast(api, gids):

    """向多个群主动发送整点报时图（msg_id=None 即主动发言）。"""

    from modules.common import send_group_image

    ok = 0

    fail = 0

    for gid in gids:

        try:

            res = await send_group_image(api, gid, _CHIME_API_URL, msg_id=None)

            if res:

                ok += 1

            else:

                fail += 1

        except Exception as e:

            fail += 1

            print("[chime] 群 %s 报时失败: %s" % (gid, e), flush=True)

        # 轻微节流，避免触发平台频控

        await asyncio.sleep(1.0)

    print("[chime] 自动报时完成: 成功 %d, 失败 %d" % (ok, fail), flush=True)

def _aggregate_chime_groups():

    """从成员表聚合所有出现过的群 openid（与 /api/groups 同源）。"""

    try:

        with _admin_api_lock:

            items = list(_members.values())

        gids = set()

        for m in items:

            for gid in (m.get("groups") or []):

                if gid and gid != "-":

                    gids.add(gid)

        return gids

    except Exception as e:

        print("[chime] 聚合群列表失败: %s" % e, flush=True)

        return set()

def _dispatch_chime_broadcast(gids):

    """按群所属 bot 分别经各自的事件循环异步广播（调度线程调用）。"""

    by_appid = {}

    for gid in (gids or []):

        appid = GROUP_BOT_MAP.get(gid)

        by_appid.setdefault(appid, []).append(gid)

    dispatched = False

    for appid, gids_for in by_appid.items():

        bridge = get_bridge(appid)

        api = bridge.get("api") if bridge else None

        loop = bridge.get("loop") if bridge else None

        if api is None or loop is None or not loop.is_running():

            print("[chime] bot %s 桥接未就绪，跳过 %d 群" % (appid, len(gids_for)), flush=True)

            continue

        try:

            asyncio.run_coroutine_threadsafe(_chime_broadcast(api, gids_for), loop)

            print("[chime] 已提交自动报时广播(bot=%s)，目标群 %d 个" % (appid, len(gids_for)), flush=True)

            dispatched = True

        except Exception as e:

            print("[chime] 提交广播失败: %s" % e, flush=True)

    return dispatched

def _check_chime_schedule(now=None):

    """按群独立配置的整点报时：仅当 minute==0（整点），且落在各群时段/间隔内时，

    向该群主动推送报时图。每个群的设置相互独立。

    门控：仅当「整点报时」插件（plugins/chime）已安装时生效（可安装/卸载）。"""

    from datetime import datetime

    try:
        if plugin_registry.get_plugin("chime") is None:
            return
    except Exception:
        return

    if now is None:

        now = datetime.now()

    # 只有整点才报时

    if now.minute != 0:

        return

    with _lock:

        groups = {gid: dict(cfg) for gid, cfg in _chime_groups.items()}

    pending = []

    for gid, cfg in groups.items():

        if not cfg.get("enabled"):

            continue

        iv = max(1, min(24, _coerce_int(cfg.get("interval_hours", 1), 1)))

        if now.hour % iv != 0:

            continue

        ps = max(0, min(23, _coerce_int(cfg.get("period_start", 0), 0)))

        pe = max(0, min(23, _coerce_int(cfg.get("period_end", 23), 23)))

        if ps > pe:

            ps, pe = pe, ps

        if not (ps <= now.hour <= pe):

            continue

        last = str(cfg.get("last_run") or "")

        if last:

            try:

                ld = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")

            except Exception:

                ld = None

            if ld is not None and ld.year == now.year and ld.month == now.month and ld.day == now.day and ld.hour == now.hour:

                continue  # 本小时已报时，避免同小时重复

        pending.append(gid)

    if not pending:

        return

    # 先更新 last_run 并落盘（避免同一整点被重复提交）

    with _lock:

        stamp = now.strftime("%Y-%m-%d %H:%M:%S")

        for gid in pending:

            c = _chime_groups.get(gid)

            if c is not None:

                c["last_run"] = stamp

        _save_system_config()

    _dispatch_chime_broadcast(set(pending))

    print("[chime] 整点报时已向 %d 个群提交广播（%s）" % (len(pending), stamp), flush=True)

def _trigger_chime_now(group_openid=None):

    """立即向指定群（或全部已启用群）广播一次整点报时图（手动/测试用）。"""

    from datetime import datetime

    now = datetime.now()

    if group_openid:

        with _lock:

            cfg = _chime_groups.get(group_openid)

        if not cfg or not cfg.get("enabled"):

            return {"groups": 0, "dispatched": False, "message": "该群未启用自动报时"}

        gids = {group_openid}

    else:

        with _lock:

            gids = {gid for gid, cfg in _chime_groups.items() if cfg.get("enabled")}

    result = {"groups": len(gids), "dispatched": False, "message": ""}

    if not gids:

        result["message"] = "没有启用自动报时的群"

        return result

    dispatched = _dispatch_chime_broadcast(gids)

    result["dispatched"] = dispatched

    if dispatched:

        with _lock:

            stamp = now.strftime("%Y-%m-%d %H:%M:%S")

            for gid in gids:

                c = _chime_groups.get(gid)

                if c is not None:

                    c["last_run"] = stamp

            _save_system_config()

        result["message"] = "已向 %d 个群提交报时" % len(gids)

    else:

        result["message"] = "机器人桥接未就绪，报时失败"

    return result

def _load_system_config():

    global _system_switches, _video_limits, _cache_clean_config, _chime_groups, _checkin_config, _welcome_groups, _bot_system_switches

    try:

        with open(_SYSTEM_CONFIG_FILE, "r", encoding="utf-8") as f:

            data = _json.load(f)

        if isinstance(data, dict):

            _system_switches = data.get("switches", {}) or {}

            # 多机器人独立功能开关：{appid: {key: bool}}
            raw_bot_sw = data.get("bot_switches", {}) or {}

            if isinstance(raw_bot_sw, dict):

                cleaned_bot_sw = {}

                for _aid, _sw in raw_bot_sw.items():

                    if not _aid or not isinstance(_sw, dict):

                        continue

                    cleaned = {str(_k): bool(_v) for _k, _v in _sw.items()}

                    # 加载时也做一次剪枝：丢弃与全局生效值一致的键（兼容旧版无 trim 的数据）。
                    # 全局生效值：_system_switches[k] 若存在即用它，否则视为默认 True。
                    _aid_s = str(_aid)

                    trimmed = {}

                    for _k, _v in cleaned.items():

                        _gv = _system_switches.get(_k)

                        _gv_eff = bool(_gv) if _gv is not None else True

                        if _gv_eff != bool(_v):

                            trimmed[_k] = bool(_v)

                    if trimmed:

                        cleaned_bot_sw[_aid_s] = trimmed

                _bot_system_switches = cleaned_bot_sw

            else:

                _bot_system_switches = {}

            raw_limits = data.get("video_limits", {}) or {}

            merged = {}

            for key in ("parse", "system"):

                dft = _VIDEO_LIMITS_DEFAULT.get(key, {})

                src = raw_limits.get(key, {}) or {}

                merged[key] = {

                    "max_duration": _coerce_int(src.get("max_duration", dft.get("max_duration", 0)), 0),

                    "max_mb": _coerce_int(src.get("max_mb", dft.get("max_mb", 0)), 0),

                }

            _video_limits = merged

            # 加载定时清理配置

            raw_clean = data.get("cache_clean", {}) or {}

            dft_clean = _CACHE_CLEAN_DEFAULT

            schedule_v = str(raw_clean.get("schedule", dft_clean["schedule"])).strip().lower()

            if schedule_v not in ("daily", "weekly", "monthly"):

                schedule_v = dft_clean["schedule"]

            hour_v = _coerce_int(raw_clean.get("hour", dft_clean["hour"]), dft_clean["hour"])

            hour_v = max(0, min(23, hour_v))

            minute_v = _coerce_int(raw_clean.get("minute", dft_clean["minute"]), dft_clean["minute"])

            minute_v = max(0, min(59, minute_v))

            weekday_v = _coerce_int(raw_clean.get("weekday", dft_clean["weekday"]), dft_clean["weekday"])

            weekday_v = max(0, min(6, weekday_v))

            month_day_v = _coerce_int(raw_clean.get("month_day", dft_clean["month_day"]), dft_clean["month_day"])

            month_day_v = max(1, min(28, month_day_v))

            max_age_v = _coerce_int(raw_clean.get("max_age_days", dft_clean["max_age_days"]), 0)

            max_age_v = max(0, max_age_v)

            items_v = raw_clean.get("items", dft_clean["items"]) or dft_clean["items"]

            if not isinstance(items_v, list):

                items_v = dft_clean["items"]

            # 仅保留白名单 key

            items_v = [k for k in items_v if k in _CACHE_CATEGORIES]

            _cache_clean_config = {

                "enabled": bool(raw_clean.get("enabled", dft_clean["enabled"])),

                "schedule": schedule_v,

                "weekday": weekday_v,

                "month_day": month_day_v,

                "hour": hour_v,

                "minute": minute_v,

                "max_age_days": max_age_v,

                "items": items_v,

                "last_run": str(raw_clean.get("last_run", "") or ""),

            }

            # 加载整点报时（自动）配置（按群独立）

            _chime_groups = {}

            raw_groups = data.get("chime_groups", {}) or {}

            if not isinstance(raw_groups, dict):

                raw_groups = {}

            for gid, raw in raw_groups.items():

                if not gid:

                    continue

                if not isinstance(raw, dict):

                    raw = {}

                iv = max(1, min(24, _coerce_int(raw.get("interval_hours", _CHIME_DEFAULT["interval_hours"]), _CHIME_DEFAULT["interval_hours"])))

                ps = max(0, min(23, _coerce_int(raw.get("period_start", _CHIME_DEFAULT["period_start"]), _CHIME_DEFAULT["period_start"])))

                pe = max(0, min(23, _coerce_int(raw.get("period_end", _CHIME_DEFAULT["period_end"]), _CHIME_DEFAULT["period_end"])))

                if ps > pe:

                    ps, pe = pe, ps

                _chime_groups[gid] = {

                    "enabled": bool(raw.get("enabled", _CHIME_DEFAULT["enabled"])),

                    "interval_hours": iv,

                    "period_start": ps,

                    "period_end": pe,

                    "last_run": str(raw.get("last_run", "") or ""),

                }

            _enabled_chime = sum(1 for c in _chime_groups.values() if c.get("enabled"))

            # 加载入群通知配置（按群独立）

            _welcome_groups = {}

            raw_welcome = data.get("welcome_groups", {}) or {}

            if not isinstance(raw_welcome, dict):

                raw_welcome = {}

            for gid, raw in raw_welcome.items():

                if not gid:

                    continue

                if not isinstance(raw, dict):

                    raw = {}

                _welcome_groups[gid] = {

                    "welcome_enabled": bool(raw.get("welcome_enabled", _WELCOME_DEFAULT["welcome_enabled"])),

                    "welcome_msg": str(raw.get("welcome_msg", "") or "")[:500],

                }

            # 加载签到积分规则

            raw_checkin = data.get("checkin", {}) or {}

            if not isinstance(raw_checkin, dict):

                raw_checkin = {}

            _checkin_config = {

                "base_points": max(0, _coerce_int(raw_checkin.get("base_points", _CHECKIN_DEFAULT["base_points"]), _CHECKIN_DEFAULT["base_points"])),

                "bonus_per_day": max(0, _coerce_int(raw_checkin.get("bonus_per_day", _CHECKIN_DEFAULT["bonus_per_day"]), _CHECKIN_DEFAULT["bonus_per_day"])),

                "bonus_cap": max(0, _coerce_int(raw_checkin.get("bonus_cap", _CHECKIN_DEFAULT["bonus_cap"]), _CHECKIN_DEFAULT["bonus_cap"])),

                "lottery_cost": max(1, _coerce_int(raw_checkin.get("lottery_cost", _CHECKIN_DEFAULT["lottery_cost"]), _CHECKIN_DEFAULT["lottery_cost"])),

                "lottery_daily_limit": max(0, _coerce_int(raw_checkin.get("lottery_daily_limit", _CHECKIN_DEFAULT["lottery_daily_limit"]), _CHECKIN_DEFAULT["lottery_daily_limit"])),

            }

            print("[console_server] 已恢复系统开关 %d 项，视频限制 %d 组，缓存清理 %s，整点报时已配置 %d 群（启用 %d），签到积分规则已加载；多机器人覆盖 %d 个 bot" % (

                len(_system_switches), len(_video_limits),

                "启用" if _cache_clean_config["enabled"] else "关闭",

                len(_chime_groups), _enabled_chime, len(_bot_system_switches)), flush=True)

    except Exception as e:

        print("[console_server] 加载系统开关失败: %s" % e, flush=True)

        _system_switches = {}

        _bot_system_switches = {}

        _video_limits = _default_video_limits()

        _cache_clean_config = _default_cache_clean()

        _chime_groups = {}

        _checkin_config = dict(_CHECKIN_DEFAULT)

def _save_system_config():

    try:

        tmp = _SYSTEM_CONFIG_FILE + ".tmp"

        with open(tmp, "w", encoding="utf-8") as f:

            _json.dump({

                "switches": _system_switches,

                "bot_switches": _bot_system_switches,

                "video_limits": _video_limits,

            "cache_clean": _cache_clean_config,

            "chime_groups": _chime_groups,

            "checkin": _checkin_config,

            "welcome_groups": _welcome_groups,

        }, f, ensure_ascii=False, indent=2)

        os.replace(tmp, _SYSTEM_CONFIG_FILE)

        _enabled_chime = sum(1 for c in _chime_groups.values() if c.get("enabled"))

        print("[console_server] 系统配置已保存到 %s（全局开关 %d 项，视频限制 %d 组，缓存清理 %d 项，整点报时已配置 %d 群，启用 %d；多机器人覆盖 %d bot）" % (

            _SYSTEM_CONFIG_FILE, len(_system_switches), len(_video_limits),

            len(_cache_clean_config.get("items", [])), len(_chime_groups), _enabled_chime,

            len(_bot_system_switches)), flush=True)

    except Exception as e:

        print("[console_server] 保存系统配置失败: %s" % e, flush=True)

def get_video_limits():

    """返回视频限制配置（始终包含 parse/system 两组完整字段）。供业务模块运行时读取。"""

    return _video_limits

# ============================================================

# AI 供应商与敏感词持久化

# ============================================================

_AI_PROVIDERS_BY_BOT = {}  # appid -> list[provider]，按机器人物理隔离

_SENSITIVE_WORDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sensitive_words.json")

_sensitive_words = []

_sensitive_words_seq = 0

_ai_config = {"auto_revoke": False}

def _call_ocr(image_url, timeout=40):
    """调用 HunyuanOCR 图片识别辅助，返回识别文字（失败返回空串）。"""
    try:
        _u = "https://openapi.dwo.cc/api/ocr?url=" + urllib.parse.quote(image_url, safe="")
        _req = urllib.request.Request(_u, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(_req, timeout=timeout) as _r:
            _raw = _r.read().decode("utf-8", errors="replace")
        _data = _json.loads(_raw)
        if isinstance(_data, dict) and _data.get("code") == 200:
            return str(_data.get("data") or "")
    except Exception as e:
        print("[console_server] OCR 识别失败: %s" % e, flush=True)
    return ""

def _providers_file(appid):
    return _bot_file(appid, "ai_providers.json")

def _resolve_provider_appid(bot):
    if not bot:
        return "_shared"
    return resolve_bot_key(bot) or "_shared"

def _load_ai_providers(bot=""):
    """按机器人加载 AI 供应商列表（appid 优先，回退 _shared）。结果缓存于 _AI_PROVIDERS_BY_BOT。"""
    appid = _resolve_provider_appid(bot)
    if appid in _AI_PROVIDERS_BY_BOT:
        return _AI_PROVIDERS_BY_BOT[appid]
    lst = []
    try:
        _fp = _providers_file(appid)
        if os.path.exists(_fp):
            with open(_fp, "r", encoding="utf-8") as f:
                data = _json.load(f)
            if isinstance(data, list):
                lst = data
        elif appid != "_shared":
            _sf = _providers_file("_shared")
            if os.path.exists(_sf):
                with open(_sf, "r", encoding="utf-8") as f:
                    data = _json.load(f)
                if isinstance(data, list):
                    lst = data
        for _p in lst:
            try:
                _p["id"] = int(_p.get("id") or 0)
            except Exception:
                _p["id"] = 0
        print("[console_server] 已恢复 AI 供应商(%s) %d 条" % (appid, len(lst)), flush=True)
    except Exception as e:
        print("[console_server] 加载 AI 供应商失败(%s): %s" % (appid, e), flush=True)
        lst = []
    _AI_PROVIDERS_BY_BOT[appid] = lst
    return lst

def _coerce_id(value):

    """把任意 id 强转为 int（前端传过来的可能是字符串）。

    转换失败时返回原始值，避免破坏其它兼容性比对。"""

    if value is None:

        return None

    if isinstance(value, bool):

        return int(value)

    if isinstance(value, int):

        return value

    if isinstance(value, str):

        s = value.strip()

        if not s:

            return None

        try:

            return int(s)

        except ValueError:

            try:

                return int(float(s))

            except ValueError:

                return value

    try:

        return int(value)

    except Exception:

        return value

def _save_ai_providers(bot="", data=None):
    appid = _resolve_provider_appid(bot)
    if data is None:
        data = _AI_PROVIDERS_BY_BOT.get(appid, [])
    _AI_PROVIDERS_BY_BOT[appid] = data
    try:
        _fp = _providers_file(appid)
        _d = os.path.dirname(_fp)
        if not os.path.isdir(_d):
            os.makedirs(_d, exist_ok=True)
        tmp = _fp + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _fp)
    except Exception as e:
        print("[console_server] 保存 AI 供应商失败(%s): %s" % (appid, e), flush=True)

# --------------------------------------------------------------------------

# AI 大模型连接（OpenAI 兼容 / Ollama 本地）

# --------------------------------------------------------------------------

def _normalize_openai_endpoint(url):

    """把用户填写的 API 地址规范化为 /chat/completions 端点。"""

    base = (url or "").strip().rstrip("/")

    if not base:

        return ""

    if base.endswith("/chat/completions"):

        return base

    if base.endswith("/v1"):

        return base + "/chat/completions"

    return base + "/chat/completions"

def _build_messages_from_payload(payload):

    """从请求体构造 messages 列表。

    优先使用显式传入的 messages（前端持有完整对话上下文）；

    否则用 history + message 拼装单轮。

    """

    messages = payload.get("messages")

    if isinstance(messages, list) and messages:

        out = []

        for m in messages:

            if not isinstance(m, dict):

                continue

            role = str(m.get("role") or "").strip()

            content = m.get("content")

            content = "" if content is None else str(content)

            if role not in ("system", "user", "assistant", "tool"):

                role = "user"

            if not content.strip():

                continue

            out.append({"role": role, "content": content})

        if out:

            return out

    history = payload.get("history")

    message = str(payload.get("message") or "").strip()

    out = []

    if isinstance(history, list):

        for m in history:

            if not isinstance(m, dict):

                continue

            role = str(m.get("role") or "user").strip()

            content = str(m.get("content") or "")

            if role not in ("system", "user", "assistant"):

                role = "user"

            if content.strip():

                out.append({"role": role, "content": content})

    if message:

        out.append({"role": "user", "content": message})

    return out

def _http_post_json(endpoint, body, headers, timeout):

    data = _json.dumps(body).encode("utf-8")

    req = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")

    with urllib.request.urlopen(req, timeout=timeout) as resp:

        raw = resp.read().decode("utf-8", errors="replace")

    return _json.loads(raw)

def _call_openai_chat(provider, messages, timeout=90):

    endpoint = _normalize_openai_endpoint(provider.get("url"))

    if not endpoint:

        raise ValueError("API 地址无效")

    headers = {"Content-Type": "application/json"}

    key = (provider.get("key") or "").strip()

    if key:

        headers["Authorization"] = "Bearer " + key

    try:

        temperature = float(provider.get("temperature", 0.7) or 0.7)

    except Exception:

        temperature = 0.7

    body = {

        "model": provider.get("model") or "",

        "messages": messages,

        "temperature": temperature,

        "stream": False,

    }

    try:

        result = _http_post_json(endpoint, body, headers, timeout)

    except urllib.error.HTTPError as e:

        detail = ""

        try:

            detail = e.read().decode("utf-8", errors="replace")

        except Exception:

            pass

        raise ValueError("接口返回 HTTP %s：%s" % (e.code, detail[:400]))

    if not isinstance(result, dict):

        raise ValueError("接口返回格式异常")

    choices = result.get("choices")

    if not isinstance(choices, list) or not choices:

        if result.get("error"):

            err = result["error"]

            raise ValueError(err.get("message") if isinstance(err, dict) else str(err))

        raise ValueError("接口未返回 choices 字段（请检查 API 地址 / Key / 模型名）")

    msg = choices[0].get("message") or {}

    return str(msg.get("content") or "").strip()

def _call_ollama_chat(provider, messages, timeout=180):

    base = (provider.get("url") or "").strip().rstrip("/")

    if not base:

        raise ValueError("API 地址无效")

    endpoint = base + "/api/chat"

    headers = {"Content-Type": "application/json"}

    try:

        temperature = float(provider.get("temperature", 0.7) or 0.7)

    except Exception:

        temperature = 0.7

    body = {

        "model": provider.get("model") or "",

        "messages": messages,

        "stream": False,

        "options": {"temperature": temperature},

    }

    try:

        result = _http_post_json(endpoint, body, headers, timeout)

    except urllib.error.HTTPError as e:

        detail = ""

        try:

            detail = e.read().decode("utf-8", errors="replace")

        except Exception:

            pass

        raise ValueError("接口返回 HTTP %s：%s" % (e.code, detail[:400]))

    if not isinstance(result, dict):

        raise ValueError("接口返回格式异常")

    msg = result.get("message") or {}

    content = msg.get("content") if isinstance(msg, dict) else ""

    return str(content or "").strip()

def _call_provider_chat(provider, messages, timeout=90):

    ptype = str(provider.get("type") or "openai").strip().lower()

    if ptype == "ollama":

        return _call_ollama_chat(provider, messages, timeout=timeout)

    return _call_openai_chat(provider, messages, timeout=timeout)

def _resolve_provider_for_test(payload, bot=""):

    """测试连接：优先用已保存的 provider_id（按 bot 隔离），否则用表单中的临时配置。"""

    pid = _coerce_id(payload.get("provider_id"))

    if pid is not None:

        with _lock:

            for p in _load_ai_providers(bot):

                if p.get("id") == pid:

                    return dict(p)

    try:

        temperature = float(payload.get("temperature", 0.7) or 0.7)

    except Exception:

        temperature = 0.7

    return {

        "id": None,

        "name": str(payload.get("name") or "测试供应商").strip(),

        "type": str(payload.get("type") or "openai").strip(),

        "url": str(payload.get("url") or "").strip(),

        "key": str(payload.get("key") or "").strip(),

        "model": str(payload.get("model") or "").strip(),

        "temperature": temperature,

    }

# --------------------------------------------------------------------------

# 暴露给 bot.py 使用的 AI 对话接口

# --------------------------------------------------------------------------

def get_default_ai_provider(bot=""):

    """获取默认 AI 供应商（is_default=True 优先；否则返回第一个）。按 bot 隔离。

    返回 provider 字典（拷贝），没有则返回 None。"""

    with _lock:

        _ps = _load_ai_providers(bot)

        for p in _ps:

            if p.get("is_default"):

                return dict(p)


        if _ps:

            return dict(_ps[0])

    return None

def chat_with_ai_for_bot(messages, provider_id=None, timeout=90, bot=None):
    """bot.py 调用的 AI 对话接口。

    参数:

      messages: list[dict]，形如 [{"role": "user", "content": "..."}]
      provider_id: 供应商 id（int / str / None）；None 时按默认自配供应商
      timeout: 请求超时（秒）
    返回: (ok: bool, content: str, error: str, provider_name: str)
    """

    # 人格 + 知识库上下文（自配路径）
    try:
        from modules.ai_persona import build_ai_context
        _persona, _knowledge = build_ai_context(bot)
    except Exception as _e:
        logger.warning("[AI对话] 加载人格/知识库失败: %s" % _e)
        _persona, _knowledge = "", ""
    _final_messages = []
    if _persona:
        _final_messages.append({"role": "system", "content": _persona})
    if _knowledge:
        _final_messages.append({"role": "system", "content": _knowledge})
    _final_messages.extend(list(messages))

    # 自配路径
    with _lock:
        provider = None
        if provider_id is not None:
            pid = _coerce_id(provider_id)
            for p in _load_ai_providers(bot):
                if p.get("id") == pid:
                    provider = p
                    break
        if not provider:
            provider = get_default_ai_provider(bot)
    pname = (provider or {}).get("name") or "AI"
    if not provider:
        return False, "", "未配置任何 AI 供应商，请到管理后台「AI 模型」中添加", ""
    if not provider.get("url"):
        return False, "", "AI 供应商「%s」未填写 API 地址" % pname, pname
    if not provider.get("model"):
        return False, "", "AI 供应商「%s」未填写模型" % pname, pname
    try:
        reply = _call_provider_chat(provider, _final_messages, timeout=timeout)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        msg = "HTTP %d：%s" % (e.code, detail[:200])
        if e.code in (401, 403):
            msg = "鉴权失败（HTTP %d）：请检查 API Key 是否有效 / 已过期。%s" % (e.code, detail[:120])
        elif e.code == 429:
            msg = "请求过于频繁（HTTP 429），请稍后重试。%s" % detail[:120]
        return False, "", msg, pname
    except urllib.error.URLError as e:
        return False, "", "网络错误：%s" % _describe_urllib_err(e), pname
    except Exception as e:
        return False, "", "调用失败：%s" % str(e)[:200], pname
    if not reply:
        return False, "", "模型返回内容为空（可能 key 失效或余额不足）", pname
    return True, reply, "", pname
def _describe_urllib_err(e):

    reason = getattr(e, "reason", e)

    return "无法连接服务：%s" % reason

def _format_models_error(status, detail, provider):

    """将 /models 接口的 HTTP 错误转成更友好的中文提示。

    重点：401 + 「Token/Invalid token/key」通常是 API Key 无效/过期/复制不完整

    这类问题，统一返回带行动建议的错误信息而不是干巴巴的 HTTP 状态码。

    """

    body = (detail or "").strip()[:300]

    url = (provider.get("url") or "").strip()

    key_len = len((provider.get("key") or "").strip())

    # 兼容各家 401 信息：siliconflow 用 "Token is invalid" / Invalid token / 30014 等

    looks_unauth = False

    body_l = body.lower()

    if status in (401, 403):

        looks_unauth = True

    if any(k in body for k in ("Token is invalid", "Invalid token", "token invalid",

                                "API key", "ApiKey", "Invalid API Key",

                                "Incorrect API key", "missing credentials",

                                "未授权", "密钥错误", "认证失败")):

        looks_unauth = True

    if looks_unauth:

        host_hint = ""

        u = url.lower()

        if "siliconflow" in u:

            host_hint = "（硅基流动 SiliconFlow）"

        elif "openai.com" in u:

            host_hint = "（OpenAI）"

        elif "deepseek" in u:

            host_hint = "（DeepSeek）"

        elif "dashscope" in u or "aliyun" in u:

            host_hint = "（阿里云百炼/通义千问）"

        elif "moonshot" in u or "kimi" in u:

            host_hint = "（月之暗面 Kimi）"

        elif "zhipu" in u or "bigmodel" in u or "glm" in u:

            host_hint = "（智谱 GLM）"

        key_hint = "请检查密钥是否完整复制（常见错误：复制时漏掉末尾字符、含前后空格、复制成上一行残留）。"

        if key_len == 0:

            return "API Key 为空，未发送鉴权头%s。请在「API Key」输入框里填写密钥后再获取模型。" % host_hint

        if key_len < 20:

            key_hint += " 当前密钥仅 %d 位，偏短，请确认是否复制完整。" % key_len

        return "API Key 可能无效或已过期%s（HTTP %s）。%s原始响应：%s" % (

            host_hint, status, key_hint, body or "（空）",

        )

    if status == 404:

        return ("无法找到模型列表接口（HTTP 404），当前地址「%s」可能没有 /models 端点，"

                "请把「API 地址」改为仅含 base URL（如 https://api.example.com/v1）后重试。"

                "原始响应：%s" % (url or "（空）", body or "（空）"))

    if status == 429:

        return "接口返回 HTTP 429：触发限流，请稍后再试。原始响应：%s" % (body or "（空）")

    return "接口返回错误 %s：%s" % (status, body or "（无响应体）")

def _load_sensitive_words():

    global _sensitive_words, _sensitive_words_seq, _ai_config

    try:

        with open(_SENSITIVE_WORDS_FILE, "r", encoding="utf-8") as f:

            data = _json.load(f)

        if isinstance(data, dict):

            _sensitive_words = data.get("words", []) or []

            _ai_config = data.get("config", {}) or {"auto_revoke": False}

            _sensitive_words_seq = max([w.get("id", 0) for w in _sensitive_words] or [0])

            print("[console_server] 已恢复敏感词 %d 条" % len(_sensitive_words), flush=True)

    except Exception as e:

        print("[console_server] 加载敏感词失败: %s" % e, flush=True)

        _sensitive_words = []

        _sensitive_words_seq = 0

        _ai_config = {"auto_revoke": False}

def _save_sensitive_words():

    try:

        tmp = _SENSITIVE_WORDS_FILE + ".tmp"

        with open(tmp, "w", encoding="utf-8") as f:

            _json.dump({"words": _sensitive_words, "config": _ai_config}, f, ensure_ascii=False, indent=2)

        os.replace(tmp, _SENSITIVE_WORDS_FILE)

    except Exception as e:

        print("[console_server] 保存敏感词失败: %s" % e, flush=True)

_load_feature_configs()

_load_qa_rules()

_load_system_config()

_load_ai_providers()

_load_sensitive_words()

_load_runtime_settings()

# ============================================================

# 定时任务持久化与调度器

# ============================================================

_SCHEDULED_TASKS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "scheduled_tasks.json")

_scheduled_tasks = []

_scheduled_tasks_seq = 0

_scheduler_started = False

_scheduler_lock = threading.RLock()

_scheduler_last_minute = None

def _load_scheduled_tasks():

    global _scheduled_tasks, _scheduled_tasks_seq

    try:

        with open(_SCHEDULED_TASKS_FILE, "r", encoding="utf-8") as f:

            data = _json.load(f)

        if isinstance(data, dict) and isinstance(data.get("tasks"), list):

            _scheduled_tasks = data["tasks"]

            _scheduled_tasks_seq = max([t.get("id", 0) for t in _scheduled_tasks] or [0])

            print("[console_server] 已恢复定时任务 %d 条" % len(_scheduled_tasks), flush=True)

    except Exception as e:

        print("[console_server] 加载定时任务失败: %s" % e, flush=True)

        _scheduled_tasks = []

        _scheduled_tasks_seq = 0

def _save_scheduled_tasks():

    try:

        tmp = _SCHEDULED_TASKS_FILE + ".tmp"

        with open(tmp, "w", encoding="utf-8") as f:

            _json.dump({"tasks": _scheduled_tasks}, f, ensure_ascii=False, indent=2)

        os.replace(tmp, _SCHEDULED_TASKS_FILE)

    except Exception as e:

        print("[console_server] 保存定时任务失败: %s" % e, flush=True)

_load_scheduled_tasks()

def _parse_cron_field(field, min_val, max_val):

    """解析单个 cron 字段，返回该字段允许的值集合。支持 * / , -"""

    field = str(field).strip()

    if field == "*":

        return set(range(min_val, max_val + 1))

    values = set()

    for part in field.split(","):

        if "/" in part:

            base, step = part.split("/", 1)

            step = int(step)

            if base == "*":

                start, end = min_val, max_val

            elif "-" in base:

                start, end = map(int, base.split("-", 1))

            else:

                start = int(base)

                end = max_val

            values.update(range(start, end + 1, step))

        elif "-" in part:

            start, end = map(int, part.split("-", 1))

            values.update(range(start, end + 1))

        else:

            values.add(int(part))

    return values

def _match_cron(cron_expr, dt):

    """判断给定时间是否匹配 cron 表达式（5 字段：分 时 日 月 周）。"""

    try:

        parts = cron_expr.strip().split()

        if len(parts) != 5:

            return False

        minute, hour, day, month, weekday = parts

        if dt.minute not in _parse_cron_field(minute, 0, 59):

            return False

        if dt.hour not in _parse_cron_field(hour, 0, 23):

            return False

        if dt.day not in _parse_cron_field(day, 1, 31):

            return False

        if dt.month not in _parse_cron_field(month, 1, 12):

            return False

        # 星期：0 和 7 都表示周日；python weekday: 周一=0..周日=6，转换为 cron: 周一=1..周日=0

        wds = _parse_cron_field(weekday, 0, 7)

        if 7 in wds:

            wds.add(0)

        cron_wd = (dt.weekday() + 1) % 7

        if cron_wd not in wds:

            return False

        return True

    except Exception as e:

        print("[console_server] cron 匹配异常 %s: %s" % (cron_expr, e), flush=True)

        return False

async def _execute_scheduled_task(task):

    """执行单个定时任务：目前支持群聊任务发送文本/Markdown消息（按群所属 bot 路由）。"""

    global _bot_bridges

    try:

        group_openid = task.get("target_group") or ""

        bridge = get_bridge(GROUP_BOT_MAP.get(group_openid))

        if not bridge or not bridge.get("api"):

            print("[console_server] 定时任务 %s 执行失败: 机器人未就绪" % task.get("name"), flush=True)

            return False

        api = bridge["api"]

        task_type = task.get("type", "group")

        if task_type == "group":

            group_openid = task.get("target_group") or ""

            if not group_openid:

                print("[console_server] 定时任务 %s 缺少目标群" % task.get("name"), flush=True)

                return False

            from modules.common import send_group_text

            content = task.get("content") or ""

            await send_group_text(api, group_openid, content)

            print("[console_server] 定时任务 %s 已发送到群 %s" % (task.get("name"), group_openid), flush=True)

            return True

        else:

            # 系统任务预留：可扩展为清理缓存、刷新数据等

            print("[console_server] 系统任务 %s 执行完成" % task.get("name"), flush=True)

            return True

    except Exception as e:

        print("[console_server] 定时任务 %s 执行异常: %s" % (task.get("name"), e), flush=True)

        return False

def _mark_task_executed(task_id):

    """更新任务执行次数和上次执行时间。"""

    global _scheduled_tasks

    now = time.strftime("%Y-%m-%d %H:%M:%S")

    with _scheduler_lock:

        for t in _scheduled_tasks:

            if t.get("id") == task_id:

                t["exec_count"] = int(t.get("exec_count", 0)) + 1

                t["last_exec"] = now

                break

    _save_scheduled_tasks()

def _scheduler_tick():

    """每分钟检查一次是否有任务到期。"""

    global _scheduler_last_minute

    from datetime import datetime

    now = datetime.now()

    minute_key = (now.year, now.month, now.day, now.hour, now.minute)

    if minute_key == _scheduler_last_minute:

        return

    _scheduler_last_minute = minute_key

    # 优先：内置的缓存清理计划（不需持久化任务记录）

    try:

        _check_cache_clean_schedule(now)

    except Exception as e:

        print("[console_server] 缓存清理计划检查异常: %s" % e, flush=True)

    # 整点报时（自动）计划

    try:

        _check_chime_schedule(now)

    except Exception as e:

        print("[console_server] 整点报时计划检查异常: %s" % e, flush=True)

    with _scheduler_lock:

        tasks = [dict(t) for t in _scheduled_tasks]

    for task in tasks:

        if not task.get("enabled"):

            continue

        try:

            if _match_cron(task.get("cron", ""), now):

                # 在线程中异步执行，避免阻塞调度器

                def run(tid=task["id"], t=task):

                    bridge = get_bridge(GROUP_BOT_MAP.get(t.get("target_group")))

                    loop = bridge.get("loop") if bridge else None

                    if loop and loop.is_running():

                        future = asyncio.run_coroutine_threadsafe(_execute_scheduled_task(t), loop)

                        try:

                            future.result(timeout=30)

                            _mark_task_executed(tid)

                        except Exception as e:

                            print("[console_server] 定时任务 %s 执行超时或失败: %s" % (t.get("name"), e), flush=True)

                    else:

                        # 无事件循环时直接运行

                        asyncio.run(_execute_scheduled_task(t))

                        _mark_task_executed(tid)

                threading.Thread(target=run, daemon=True).start()

        except Exception as e:

            print("[console_server] 调度任务检查异常: %s" % e, flush=True)

def _scheduler_loop():

    """调度器守护线程主循环。"""

    while True:

        try:

            _scheduler_tick()

        except Exception as e:

            print("[console_server] 调度器循环异常: %s" % e, flush=True)

        time.sleep(15)

def _start_scheduled_tasks_scheduler():

    """启动定时任务调度器（幂等）。"""

    global _scheduler_started

    with _scheduler_lock:

        if _scheduler_started:

            return

        _scheduler_started = True

    t = threading.Thread(target=_scheduler_loop, name="xiaoliu-scheduler", daemon=True)

    t.start()

    print("[console_server] 定时任务调度器已启动", flush=True)

def _upsert_member(openid, bot, nickname, avatar, source_type, group_openid,
                   member_role=None):

    """把一条真实用户消息归集为成员（用于成员管理页）。

    member_role (str): QQ 平台事件 author.member_role（owner/admin/member）。
        传入合法值时同步写入"member_role"缓存并派生中文"group_role"。
        缺失/非法值时不更新这两字段，保留历史或默认"成员"。
    """

    global _members_seq

    if not openid or openid == "-":

        return

    try:

        with _lock:

            m = _members.get(openid)

            now = time.time()

            if m is None:

                _members_seq += 1

                m = {

                    "openid": openid,

                    "id": _members_seq,

                    "bot": bot or "小流萤",

                    "nickname": nickname or "",

                    "avatar": avatar or "",

                    "real_qq": _user_qq_bindings.get(openid, ""),

                    "sources": set(),

                    "groups": [],

                    "group_role": "成员",

                    "role": "普通成员",

                    "level": "Lv.1",

                    "msg_count": 0,

                    "first_seen": now,

                    "last_seen": now,

                    "member_role": None,

                }

                _members[openid] = m

            if nickname:

                m["nickname"] = nickname

            if avatar:

                m["avatar"] = avatar

            if bot:

                m["bot"] = bot

            if source_type in ("group", "private"):

                m["sources"].add(source_type)

            if group_openid and group_openid not in m["groups"]:

                m["groups"].append(group_openid)

            m["msg_count"] = m.get("msg_count", 0) + 1

            m["last_seen"] = now

            m["real_qq"] = _user_qq_bindings.get(openid, m.get("real_qq", ""))


            # 仅白名单 (owner/admin/member) 写回"member_role"缓存，并派生中文 group_role。
            # 私聊场景通常 member_role 为 None，此分支不进入。
            if member_role in ("owner", "admin", "member"):
                m["member_role"] = member_role
                m["group_role"] = {"owner": "群主", "admin": "管理员", "member": "成员"}[member_role]
                m["role"] = {"owner": "群主", "admin": "管理员", "member": "普通成员"}[member_role]

        _save_members()

    except Exception as e:

        print("[console_server] 归集成员失败: %s" % e, flush=True)

def _qq_avatar_url(openid):

    """根据 QQ 机器人 openid 生成头像 URL（腾讯官方接口）。"""

    if not openid:

        return ""

    try:

        from modules.config import APPID

        appid = APPID

    except Exception:

        appid = ""

    if not appid:

        return ""

    return "https://thirdqq.qlogo.cn/qqapp/%s/%s/100" % (appid, openid)

_messages = []

_max_messages = 500

_bot_bridge = None  # 兼容别名（部分旧调用），新代码统一用 _bot_bridges 字典

_bot_bridges = {}   # appid -> {"api", "loop", "name", "appid", "ts"}


def _get_bot_module():
    """返回正在运行的 bot 模块实例。
    bot.py 以 `python bot.py` 直接运行时模块名为 __main__ 而非 bot；
    console_server 内 `import bot` 会再创建一个独立模块实例（各自拥有独立的
    _BOT_THREADS / add_bot / remove_bot），导致热重载作用在错误的字典上、
    真实运行的 bot 线程永远不被启停。因此优先取 sys.modules['__main__']
    （即真正运行的 bot 模块），回退再尝试 import bot。
    """
    import sys
    _m = sys.modules.get("__main__")
    if _m is not None and hasattr(_m, "_apply_bots_diff"):
        return _m
    try:
        import bot as _b
        if hasattr(_b, "_apply_bots_diff"):
            return _b
    except Exception:
        pass
    return None


# 桥接缓存：把 WS 握手得到的 name_rt <-> appid 映射持久化，
# 使进程启动早期（WS 尚未连接、_bot_bridges 未填充）resolve_bot_key 仍可解析。
_BRIDGE_CACHE_FILE = os.path.join(_DATA_ROOT_DIR, "bots", "_shared", "bot_bridges.json")

def _save_bridge_cache():
    try:
        d = os.path.dirname(_BRIDGE_CACHE_FILE)
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        _cache = {}
        for _aid, _br in _bot_bridges.items():
            if not isinstance(_br, dict):
                continue
            _cache[_aid] = {
                "name": _br.get("name") or "",
                "avatar": _br.get("avatar") or "",
                "appid": _aid,
            }
        tmp = _BRIDGE_CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            _json.dump(_cache, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _BRIDGE_CACHE_FILE)
    except Exception:
        pass

def _load_bridge_cache():
    try:
        if not os.path.exists(_BRIDGE_CACHE_FILE):
            return
        with open(_BRIDGE_CACHE_FILE, "r", encoding="utf-8") as f:
            _cache = _json.load(f)
        if isinstance(_cache, dict):
            for _aid, _br in _cache.items():
                if not isinstance(_br, dict):
                    continue
                # 不覆盖运行时已注册的桥接（其 api 才是真实可用的）
                if _aid in _bot_bridges and _bot_bridges[_aid].get("api") is not None:
                    continue
                _bot_bridges.setdefault(_aid, {}).update({
                    "name": _br.get("name") or "",
                    "avatar": _br.get("avatar") or "",
                    "appid": _aid,
                })
    except Exception:
        pass

_load_bridge_cache()

GROUP_BOT_MAP = _BotMap()  # group_openid -> appid（按群路由全局广播，持久化）

USER_BOT_MAP = _BotMap()   # user_openid  -> appid（按用户路由，持久化）

_load_group_bot_map()

_restart_requested = False

_shutdown_requested = False

_pending_action = None        # 待执行的整机指令：'restart' / 'shutdown' / None

_pending_until = 0.0          # 缓冲到期的 unix 时间戳

_PENDING_DELAY = 5.0         # 指令生效前的缓冲秒数

def _start_today_stats_flusher():

    """后台守护线程：每 30s 把「今日」计数落盘，避免高频消息计数因重启丢失。"""

    def _loop():

        while True:

            try:

                _save_today_stats()

            except Exception:  # noqa: BLE001

                pass

            time.sleep(30)

    t = threading.Thread(

        target=_loop, name="xiaoliu-today-stats-flusher", daemon=True

    )

    t.start()

def start_console_server(open_browser=True):

    # 预热 AI 人格/知识库模块：避免运行期 HTTP 线程首次 `from modules.ai_persona
    # import ...` 与 bot 主线程处理 AI 消息时的同模块 import 在全局 import 锁上
    # 竞争，导致 /api/ai/persona、/api/ai/knowledge 等端点长时间无响应
    # （表现为控制台人格/知识库的「新建 / 保存 / 删除」全部点不动）。
    try:
        import modules.ai_persona  # noqa
    except Exception as _e:
        print("[console_server] 预热 AI 人格模块失败: %s" % _e, flush=True)

    # 开启机器人运行日志采集（stdout/stderr -> 日志中心）

    _install_console_tee()

    print(

        "[console_server] 管理后台已就绪，访问地址: http://127.0.0.1:9988/",

        flush=True,

    )

    # 启动管理后台 HTTP API（轻量，守护线程，不阻塞 bot 事件循环）

    try:

        _start_admin_api_server(host="127.0.0.1", port=9988)

    except Exception as e:

        print("[console_server] admin api 启动失败: %s" % e, flush=True)

    # 启动控制看门狗，使「重启 / 关机」指令真正生效

    try:

        _start_control_watchdog()

    except Exception as e:  # noqa: BLE001

        print("[console_server] 控制看门狗启动失败: %s" % e, flush=True)

    # 启动「今日统计」周期落盘守护线程，避免 bot 重启 / 关机丢失当天统计

    try:

        _start_today_stats_flusher()

    except Exception as e:  # noqa: BLE001

        print("[console_server] 今日统计落盘线程启动失败: %s" % e, flush=True)

    # 自动打开浏览器管理后台

    if open_browser:

        _open_admin_browser_later(host="127.0.0.1", port=9988)

    return True

def _open_admin_browser_later(host="127.0.0.1", port=9988):

    """后台等待 API 端口就绪后自动打开浏览器管理后台，失败则提示手动访问。"""

    def _wait_and_open():

        url = "http://%s:%d/" % (host, port)

        deadline = time.time() + 15

        while time.time() < deadline:

            try:

                urllib.request.urlopen(url, timeout=1)

                try:

                    webbrowser.open(url, new=2)

                    print("[console_server] 已自动打开管理后台: %s" % url, flush=True)

                except Exception as e:  # noqa: BLE001

                    print(

                        "[console_server] 自动打开浏览器失败，请手动访问 %s: %s" % (url, e),

                        flush=True,

                    )

                return

            except Exception:

                time.sleep(0.5)

        print("[console_server] 等待管理后台端口超时，请手动访问: %s" % url, flush=True)

    t = threading.Thread(

        target=_wait_and_open, name="xiaoliu-open-browser", daemon=True

    )

    t.start()

def update_status(**kwargs):

    with _lock:

        for k, v in kwargs.items():

            _status[k] = v

        _status["uptime_seconds"] = int(time.time() - _started_at)

    return True

def _collect_sys_stats():
    """采集整台电脑的资源占用（CPU / 内存 / GPU），用于状态面板。

    反映整机占用，而非仅机器人进程树：
    - CPU：整机所有逻辑核心的综合利用率（psutil.cpu_percent）
    - 内存：整机物理内存 used / total / 占比
    - GPU：所有 NVIDIA 显卡的利用率与显存占用（nvidia-smi --query-gpu）
    """
    stats = {
        "cpu": {"percent": None},
        "mem": None,
        "gpu": {"available": False, "devices": []},
    }

    try:
        import psutil

        # ---- CPU（整机综合利用率）----
        # cpu_percent(interval=None) 返回自上次调用以来的利用率；
        # 仪表盘按周期轮询，首次采样为 0.0，后续为真实值。
        _cpu_pct = psutil.cpu_percent(interval=None)
        stats["cpu"]["percent"] = round(_cpu_pct, 1) if _cpu_pct is not None else None
        try:
            stats["cpu"]["count"] = psutil.cpu_count(logical=True)
        except Exception:
            pass

        # ---- 内存（整机物理内存）----
        _vm = psutil.virtual_memory()
        _gb = 1024.0 ** 3
        stats["mem"] = {
            "percent": round(_vm.percent, 1),
            "used_gb": round(_vm.used / _gb, 2),
            "total_gb": round(_vm.total / _gb, 1),
        }
    except Exception:
        pass

    # ---- GPU（所有 NVIDIA 显卡的利用率与显存）----
    try:
        import subprocess
        try:
            _out = subprocess.run(
                ["nvidia-smi",
                 "--query-gpu=index,name,utilization.gpu,memory.used,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3,
            )
        except (FileNotFoundError, OSError):
            _out = None
        if _out is not None and _out.returncode == 0 and _out.stdout.strip():
            _devices = []
            for _line in _out.stdout.strip().splitlines():
                _parts = [p.strip() for p in _line.split(",")]
                if len(_parts) < 5:
                    continue
                try:
                    _name = _parts[1]
                    _util = float(_parts[2])
                    _mem_used = float(_parts[3])
                    _mem_total = float(_parts[4])
                except Exception:
                    continue
                _devices.append({
                    "name": _name,
                    "percent": round(_util, 1),
                    "util_percent": round(_util, 1),
                    "mem_used_mb": round(_mem_used, 1),
                    "mem_total_mb": round(_mem_total, 1),
                })
            if _devices:
                stats["gpu"] = {"available": True, "devices": _devices}
    except Exception:
        pass

    return stats


def _collect_network_latency(host="qq.com", timeout=1.5):

    """通过 ICMP ping 探测到目标主机的延迟（毫秒），失败返回 None。

    兼容 Windows / Linux / macOS，输出中英文均可解析。

    """

    try:

        import subprocess

        import re

        import sys

        if sys.platform.startswith("win"):

            cmd = ["ping", "-n", "1", "-w", str(int(timeout * 1000)), host]

        else:

            cmd = ["ping", "-c", "1", "-W", str(int(timeout)), host]

        out = subprocess.run(

            cmd, capture_output=True, timeout=timeout + 1.0,

        )

        # Windows 中文环境 ping 输出多为 GBK；先按 GBK 解码，失败再试 UTF-8

        text = ""

        for enc in ("gbk", "utf-8", "latin-1"):

            try:

                text = out.stdout.decode(enc, errors="ignore")

                break

            except Exception:

                pass

        m = re.search(r"(?:time|时间)\s*[=<]\s*([\d.]+)\s*ms", text, re.I)

        if m:

            try:

                v = float(m.group(1))

                return int(v) if v == int(v) else round(v, 1)

            except Exception:

                pass

    except Exception:

        pass

    return None

# 网速采样状态（模块级，跨请求保持以便计算真实速率）

_net_io_prev = None  # (bytes_recv, bytes_sent, ts)

def _collect_network_speed():

    """返回实时网速（字节/秒）：下行 recv_bps、上行 send_bps。

    通过两次采样 psutil.net_io_counters 的差值 / 时间差计算；

    首次调用（无基准）返回 None。

    """

    global _net_io_prev

    try:

        import psutil

        cur = psutil.net_io_counters()

        now = time.time()

        prev = _net_io_prev

        _net_io_prev = (cur.bytes_recv, cur.bytes_sent, now)

        if prev is None:

            return {"recv_bps": None, "send_bps": None}

        elapsed = now - prev[2]

        if elapsed <= 0:

            return {"recv_bps": None, "send_bps": None}

        recv_bps = max(0.0, (cur.bytes_recv - prev[0]) / elapsed)

        send_bps = max(0.0, (cur.bytes_sent - prev[1]) / elapsed)

        return {

            "recv_bps": round(recv_bps, 1),

            "send_bps": round(send_bps, 1),

        }

    except Exception:

        _net_io_prev = None

        return {"recv_bps": None, "send_bps": None}

def _format_uptime_str(sec):

    """把秒数格式化为运行时长字符串：不足一天显示 HH:MM:SS，超过一天显示 Nd HH:MM:SS。"""

    try:

        sec = int(sec)

    except Exception:

        sec = 0

    if sec < 0:

        sec = 0

    d = sec // 86400

    h = (sec % 86400) // 3600

    m = (sec % 3600) // 60

    s = sec % 60

    if d > 0:

        return "%d天%02d:%02d:%02d" % (d, h, m, s)

    return "%02d:%02d:%02d" % (h, m, s)

def _get_status_data():

    with _lock:

        _status["uptime_seconds"] = int(time.time() - _started_at)

        _status["uptime_str"] = _format_uptime_str(_status["uptime_seconds"])

        try:

            sys_stats = _collect_sys_stats()

            _status["cpu"] = sys_stats["cpu"]

            _status["mem"] = sys_stats["mem"]

            _status["gpu"] = sys_stats["gpu"]

            _status["banned_word_count"] = len(_sensitive_words)

            try:

                _au, _ag = _compute_active_counts()

                _status["active_groups"] = _ag

            except Exception:

                pass

        except Exception:

            pass

        _status["pending_action"] = _pending_action

        _status["pending_remaining"] = (

            max(0, int(round(_pending_until - time.time()))) if _pending_action else 0

        )

        return dict(_status)

def record_message(*args, **kwargs):

    with _lock:

        _status["message_count"] += 1

        _status["last_message_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:

            for a in reversed(args):

                if isinstance(a, str) and len(a) > 0:

                    _status["last_message"] = a[:120]

                    break

        except Exception:

            pass

        try:

            entry = {

                "ts": time.time(),

                "args": [str(a)[:200] for a in args],

                "kwargs": {k: str(v)[:200] for k, v in kwargs.items()},

            }

            _messages.append(entry)

            if len(_messages) > _max_messages:

                del _messages[: len(_messages) - _max_messages]

        except Exception:

            pass

    return True

def console_log(msg, *args, **kwargs):

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:

        line = "[console] " + (msg % args if args else msg)

    except Exception:

        line = "[console] " + str(msg)

    print(ts, line, flush=True)

def record_bot_reply(*args, chat_id=None, content=None, scene=None, target_id=None, msg_type="text",

                     media_url="", nickname="", avatar=""):

    """记录机器人主动发出的消息到消息中心（下行），供实时监控页展示双方消息。

    支持 modules/common.py 中的两种历史位置调用方式：

      1. record_bot_reply(chat_id, content, msg_type)

      2. record_bot_reply(scene, chat_id, content, msg_type)

    也支持关键字参数：chat_id / content / scene / target_id / msg_type / ...

    chat_id 支持 g: / u: / c: 前缀自动解析场景。

    """

    try:

        # 处理位置参数（兼容历史调用方式）

        if args:

            if len(args) == 3:

                # (chat_id, content, msg_type)

                chat_id, content, msg_type = args

            elif len(args) == 4:

                # (scene, chat_id, content, msg_type)

                scene, chat_id, content, msg_type = args

            else:

                # 不认识的参数数量，忽略

                return True

        # 从 chat_id 解析场景和 target_id

        _chat_id = chat_id or ""

        if _chat_id.startswith("g:"):

            scene, target_id = "group", _chat_id[2:]

        elif _chat_id.startswith("u:"):

            scene, target_id = "c2c", _chat_id[2:]

        elif _chat_id.startswith("c:"):

            scene, target_id = "channel", _chat_id[2:]

        elif _chat_id and not scene:

            # 无前缀且未显式指定场景时，默认按群聊处理

            scene, target_id = "group", _chat_id

        if not scene:

            scene = "group"

        session_type = "群聊" if scene == "group" else ("单聊" if scene == "c2c" else "系统")

        _scene = target_id if scene == "group" else "-"

        _sender = target_id if scene == "c2c" else "-"

        if msg_type in ("image", "voice", "video"):

            _content = {"image": "[图片]", "voice": "[语音]", "video": "[视频]"}.get(msg_type, "[媒体]")

        else:

            _content = content or ""

        media_type = msg_type if msg_type in ("image", "voice", "video") else ""

        append_ws_log("小流萤", session_type, "下行", _scene, _sender, _content,

                      nickname=nickname, avatar=avatar, to_message=True,

                      media_type=media_type, media_url=media_url)

    except Exception:

        pass

    return True

def increment_api_call(n=1):

    with _lock:

        _status["api_call_count"] = _status.get("api_call_count", 0) + int(n or 1)

    return _status["api_call_count"]

def fetch_and_save_qq_info(*args, **kwargs):

    """

    查询并保存QQ用户信息。

    入参：member_openid, qq_number（也兼容位置参数/kwargs）

    优先调用小渡API（QQ_INFO_KEY），无结果时降级到相见拾光API（SHWGIJ_KEY），

    再无则返回空字段（占位）。

    返回字段：qq/nickname/avatar/level/qid/energy/card/signature/age/

              expert_days/reg_time/reg_days/avatar_modified/monthly_vip/

              annual_vip/active_days/vip_level/vip_exp/vip_growth/

              normal_vip/super_vip/annual_fee_vip/opened_services

    错误诊断：最近一次的失败原因保存在 _status['last_qq_api_error']，供 bot.py 提示给用户。

    """

    # 解析参数

    member_openid = ""

    qq_number = ""

    if args:

        if len(args) >= 1:

            member_openid = str(args[0] or "")

        if len(args) >= 2:

            qq_number = str(args[1] or "")

    if "member_openid" in kwargs:

        member_openid = str(kwargs.get("member_openid") or member_openid)

    if "qq" in kwargs:

        qq_number = str(kwargs.get("qq") or qq_number)

    qq_number = str(qq_number or (kwargs.get("qq") or "")).strip()

    if not qq_number and args and len(args) > 0:

        # 旧调用：fetch_and_save_qq_info(qq) 这种

        qq_number = str(args[-1] or "").strip()

        member_openid = member_openid or ""

    # 占位默认值（任何 API 都不通时返回）

    placeholder = {

        "qq": qq_number,

        "nickname": "",

        "avatar": "",

        "level": 0,

        "vip_level": 0,

        "register_days": 0,

    }

    if not qq_number:

        return placeholder

    # 延迟导入（避免循环引用 & 启动慢）

    try:

        from modules.config import (

            DWO_QQ_FULL_URL, DWO_QQ_CKEY,

            DWO_QQ_INFO_URL, APIBYTE_QQ_INFO_URL, QQ_INFO_KEY, SHWGIJ_KEY,

        )  # noqa

    except Exception:

        DWO_QQ_FULL_URL, DWO_QQ_CKEY = "", ""

        DWO_QQ_INFO_URL, APIBYTE_QQ_INFO_URL, QQ_INFO_KEY, SHWGIJ_KEY = "", "", "", ""

    # 清掉旧错误

    with _lock:

        _status["last_qq_api_error"] = ""

    # ============================================================

    # 多源合并（按优先级，已填充字段不会被后续源覆盖）：

    #   0. OIAPI Openid（免鉴权官方渠道，仅 nickname；最高优先级）

    #   ① 川源 dwo xxcx（需 ckey，nickname/QID/qqLevel/regTime/signature/vip 等基础字段）

    #   ② 川源 dwo qqnet（免KEY，拿 detail_info/services: 会员/活跃天数/开通业务等）

    #   ③ APIBYTE（免KEY，nickname/avatar 兜底）

    #   ④ 小渡 API（兜底）

    #   ⑤ 相见拾光（兜底）

    # ============================================================

    merged = dict(placeholder)

    have_any = False

    def _merge(src):

        nonlocal have_any

        if not src:

            return

        for k, v in src.items():

            if v in ("", None, 0):

                continue

            if not merged.get(k):

                merged[k] = v

        if any(src.values()):

            have_any = True

    # 0. OIAPI Openid（免鉴权官方渠道，仅 nickname；最高优先级）

    if member_openid:

        oiapi_nick = _fetch_nickname_via_oiapi_openid(member_openid)

        if oiapi_nick:

            merged["nickname"] = oiapi_nick

            have_any = True

    # 1. 川源 dwo xxcx（拿 nickname/QID/qqLevel/regTime/signature/vip_level）

    if DWO_QQ_FULL_URL and DWO_QQ_CKEY:

        with _lock:

            _status["last_qq_api_error"] = "川源xxcx请求中…"

        _merge(_fetch_qq_via_dwo_xxcx(qq_number, DWO_QQ_FULL_URL, DWO_QQ_CKEY))

    # 2. 川源 dwo qqnet（active_days/opened_services/super_vip 等）

    if DWO_QQ_INFO_URL:

        with _lock:

            _status["last_qq_api_error"] = "川源qqnet请求中…"

        _merge(_fetch_qq_via_dwo(qq_number, DWO_QQ_INFO_URL))

    # 3. APIBYTE（昵称/头像）

    if APIBYTE_QQ_INFO_URL:

        with _lock:

            _status["last_qq_api_error"] = "APIBYTE请求中…"

        _merge(_fetch_qq_via_apibyte(qq_number, APIBYTE_QQ_INFO_URL))

    # 4. 小渡 API（兜底）

    if QQ_INFO_KEY:

        with _lock:

            _status["last_qq_api_error"] = "小渡API请求中…"

        _merge(_fetch_qq_via_xiaodu(qq_number, QQ_INFO_KEY))

    # 5. 相见拾光（兜底）

    if not merged.get("nickname") and SHWGIJ_KEY:

        with _lock:

            _status["last_qq_api_error"] = "相见拾光API请求中…"

        _merge(_fetch_qq_via_shwgij(qq_number, SHWGIJ_KEY))

    if have_any:

        if member_openid and merged.get("nickname"):

            update_friend_contact(member_openid, name=merged["nickname"],

                                   avatar=merged.get("avatar") or "")

        with _lock:

            _status["last_qq_api_error"] = ""

        return merged

    with _lock:

        if not DWO_QQ_FULL_URL and not DWO_QQ_INFO_URL and not APIBYTE_QQ_INFO_URL and not QQ_INFO_KEY and not SHWGIJ_KEY:

            _status["last_qq_api_error"] = "未配置任何 QQ 信息查询接口"

        else:

            _status["last_qq_api_error"] = (

                "所有可用 API 都返回空数据（DWO xxcx/qqnet / APIBYTE / 小渡 / 相见拾光 均失败）")

    return merged

# 川源/dwo xxcx API 错误日志节流：避免外部接口连续超时（默认 8s）时打印风暴刷屏。
# _status["last_qq_api_error"] 仍按调用方原逻辑逐次更新（前端要最新），仅 print 节流。
_qq_api_err_throttle = {}  # key -> {"count": int, "first_ts": float, "last_log_ts": float}
_QQ_API_ERR_LOG_WINDOW = 60  # 窗口秒数

def _throttled_err_log(key, msg):
    """节流打印第三方 QQ 接口的错误日志。
    - 首次失败立刻完整打印。
    - 同一 key 在 _QQ_API_ERR_LOG_WINDOW 秒内的后续失败仅累加计数，不再打印。
    - 窗口结束（下一次失败超过窗口间隔）时，打印一条汇总「近 Ns 累计失败 M 次」。
    """
    try:
        _now = time.time()
    except Exception:
        # 极端兜底：time 不可用时退化为旧行为
        print("[console_server] %s: %s" % (key, msg), flush=True)
        return
    with _lock:
        st = _qq_api_err_throttle.setdefault(key, {"count": 0, "first_ts": _now, "last_log_ts": 0.0})
        st["count"] += 1
        if _now - st["last_log_ts"] < _QQ_API_ERR_LOG_WINDOW:
            return
        suppressed = st["count"] - 1
        if suppressed > 0:
            full = "%s (近 %ds 累计失败 %d 次)" % (msg, _QQ_API_ERR_LOG_WINDOW, st["count"])
        else:
            full = msg
        print("[console_server] %s: %s" % (key, full), flush=True)
        st["count"] = 0
        st["first_ts"] = _now
        st["last_log_ts"] = _now


def _fetch_qq_via_dwo_xxcx(qq: str, base_url: str, ckey: str) -> dict:

    """川源 dwo.cc QQ信息查询（需 ckey，提供昵称/QID/等级/注册时间/签名/vip_level 等）。

    文档：https://api.dwo.cc/api/192

    接口：https://openapi.dwo.cc/api/qqxxcx

    返回结构：

      {"status":"ok","retcode":0,"data":{

        "uin":"2092115940","nick":"未命名","qqLevel":89,"qid":"lie5940",

        "longNick":"有没有可能...","regTime":1388536704,

        "is_vip":true,"is_years_vip":true,"vip_level":8,

        "age":0,"sex":"unknown","user_id":2092115940,

        "nickname":"未命名","long_nick":"有没有可能...",

        "reg_time":1388536704,"is_vip":true,"is_years_vip":true,

        "vip_level":8,"login_days":0

      }}

    """

    if not base_url or not ckey:

        return {}

    # 拼接 query：?qq=xxx&ckey=yyy

    sep = "&" if ("?" in base_url) else "?"

    url = "%s%sqq=%s&ckey=%s" % (base_url, sep, qq, ckey)

    try:

        import requests  # noqa

    except Exception:

        try:

            import urllib.request, urllib.parse

            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

            with urllib.request.urlopen(req, timeout=8) as r:

                raw = r.read().decode("utf-8", "ignore")

            data = _json.loads(raw) if raw else {}

        except Exception as e:

            _throttled_err_log("dwo xxcx", "请求失败: %s" % e)

            with _lock:

                _status["last_qq_api_error"] = "dwo xxcx 请求失败: %s" % e

            return {}

    else:

        try:

            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)

            data = r.json() if r.status_code == 200 else {}

        except Exception as e:

            _throttled_err_log("dwo xxcx", "请求失败: %s" % e)

            with _lock:

                _status["last_qq_api_error"] = "dwo xxcx 请求失败: %s" % e

            return {}

    if not isinstance(data, dict):

        return {}

    # 失败：status != ok 或 retcode != 0

    if data.get("status") != "ok" or data.get("retcode") not in (0, "0"):

        msg = data.get("message") or data.get("wording") or data.get("retcode")

        with _lock:

            _status["last_qq_api_error"] = "dwo xxcx: %s" % msg

        return {}

    node = data.get("data") or {}

    if not isinstance(node, dict):

        return {}

    # 昵称：优先 nick，否则 nickname；"未命名" 视为空

    nick = str(node.get("nick") or node.get("nickname") or "").strip()

    if nick in ("未命名", "未知", "null", "None"):

        nick = ""

    # 签名：longNick / long_nick

    signature = str(node.get("longNick") or node.get("long_nick") or "")

    # 注册时间戳

    reg_ts = node.get("regTime") or node.get("reg_time") or ""

    reg_time_str = ""

    reg_days = ""

    try:

        if reg_ts and str(reg_ts).replace("-", "").isdigit():

            ts = int(reg_ts)

            reg_time_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

            d = max(0, (int(time.time()) - ts) // 86400)

            years = d / 365.25

            reg_days = "%s 天 (≈%s 年)" % (d, round(years, 1))

    except Exception:

        pass

    # 等级：qqLevel

    try:

        level = int(node.get("qqLevel") or 0)

    except Exception:

        level = 0

    # vip 状态

    is_vip = bool(node.get("is_vip"))

    is_years = bool(node.get("is_years_vip"))

    try:

        vip_level = int(node.get("vip_level") or 0)

    except Exception:

        vip_level = 0

    # 头像：拼接官方头像兜底

    avatar = "https://q1.qlogo.cn/g?b=qq&nk=%s&s=640" % qq

    # 头像修改时间（richTime 是协议里的"最近一次修改个人资料/头像"时间戳）

    rich_ts = node.get("richTime")

    avatar_modified = ""

    try:

        if rich_ts and str(rich_ts).isdigit() and int(rich_ts) > 0:

            avatar_modified = datetime.fromtimestamp(int(rich_ts)).strftime("%Y-%m-%d %H:%M:%S")

    except Exception:

        pass

    # 达人天数：QQ 等级达人的连续登录天数

    # 川源 xxcx 接口里这个字段叫 login_days。

    # 注意：该接口对绝大多数账号返回 0，需要 dwo qqnet 的 iMaxLvlTotalDays

    # （最高等级累计天数）做兜底，或者 iMaxLvlRealDays（最高等级实际活跃天数）。

    expert_days = ""

    try:

        ld_raw = node.get("login_days")

        if ld_raw is not None and str(ld_raw).strip() not in ("", "0", "0.0", "0.00", "null", "None"):

            ld = float(ld_raw)

            if ld >= 1:

                expert_days = "%s 天" % (int(ld) if ld == int(ld) else round(ld, 1))

            else:

                expert_days = "%s 天 (≈%s 小时)" % (round(ld, 2), round(ld * 24, 1))

    except Exception:

        expert_days = str(node.get("login_days") or "")

    return {

        "qq": str(node.get("uin") or node.get("user_id") or qq),

        "nickname": nick,

        "avatar": avatar,

        "level": level,

        "qid": str(node.get("qid") or ""),

        "energy": "",                       # 能量：该接口未提供

        "card": str(node.get("college") or ""),  # 名片：拿 college 兜底

        "signature": signature,

        "age": str(node.get("age") or ""),

        "sex": str(node.get("sex") or ""),

        "expert_days": expert_days,

        "reg_time": reg_time_str,

        "reg_days": reg_days,

        "avatar_modified": avatar_modified,

        "vip_level": vip_level,

        "monthly_vip": "是" if is_vip else "否",

        "annual_vip": "是" if is_years else "否",

        "super_vip": "是" if (is_vip and vip_level >= 8) else "否",

        "normal_vip": "是" if (is_vip and vip_level < 8) else "否",

    }

def _fetch_qq_via_apibyte(qq: str, base_url: str) -> dict:

    """APIBYTE（apione.apibyte.cn）查询QQ基础资料（昵称/头像/邮箱/QQ空间）。

    免KEY，返回结构：

      {"code":200, "msg":"success", "data":{

          "qq":..., "name":..., "mail":..., "avatar":...,

          "qzone":..., "imgurl3":...（640尺寸头像）

      }}

    """

    if not base_url:

        return {}

    sep = "&" if ("?" in base_url) else "?"

    url = "%s%sqq=%s" % (base_url, sep, qq)

    data = {}

    try:

        import requests  # noqa

    except Exception:

        try:

            import urllib.request

            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

            with urllib.request.urlopen(req, timeout=8) as r:

                raw = r.read().decode("utf-8", "ignore")

            # 空响应/非 JSON：视为该源无数据，交给其它源兜底，不报错刷屏

            try:

                data = _json.loads(raw) if raw.strip() else {}

            except Exception:

                data = {}

        except Exception as e:

            _throttled_err_log("APIBYTE", "请求失败: %s" % e)

            with _lock:

                _status["last_qq_api_error"] = "APIBYTE请求失败: %s" % e

            return {}

    else:

        try:

            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)

            # 空响应/非 JSON：同上，视为无数据，不报错

            try:

                data = r.json() if r.status_code == 200 and r.content else {}

            except Exception:

                data = {}

        except Exception as e:

            _throttled_err_log("APIBYTE", "请求失败: %s" % e)

            with _lock:

                _status["last_qq_api_error"] = "APIBYTE请求失败: %s" % e

            return {}

    if not isinstance(data, dict) or not data:

        return {}

    if not isinstance(data, dict):

        return {}

    code = data.get("code")

    if code not in (0, 200, "0", "200"):

        msg = data.get("msg") or data.get("message") or code

        with _lock:

            _status["last_qq_api_error"] = "APIBYTE: %s" % msg

        return {}

    node = data.get("data") or {}

    if not isinstance(node, dict):

        return {}

    name = str(node.get("name") or "")

    # 头像：优先 imgurl3（640尺寸），否则 avatar，否则按 QQ 号拼官方头像

    avatar = str(node.get("imgurl3") or node.get("imgurl2")

                 or node.get("imgurl1") or node.get("avatar") or "")

    if not avatar:

        avatar = "https://q1.qlogo.cn/g?b=qq&nk=%s&s=640" % qq

    # "未命名" 视为空（apibyte 的 placeholder）

    if name in ("未命名", "未知", "null", "None", ""):

        name = ""

    return {

        "qq": str(node.get("qq") or qq),

        "nickname": name,

        "avatar": avatar,

        "mail": str(node.get("mail") or ""),

        "qzone": str(node.get("qzone") or ""),

    }

def _fetch_qq_via_dwo(qq: str, base_url: str) -> dict:

    """川源科技 openapi.dwo.cc（免KEY）查询QQ资料。

    接口文档：https://api.dwo.cc/api/15

    返回结构：

      {

        "code": 200, "message": "成功",

        "data": {

          "basic_info": {"qq/nickname/sex/age/level/qid/vip_level/...": {"value": ..., "description": ...}},

          "services":   [{"privilege": "svip", "name": "超级会员", "level": 8}, ...],

          "detail_info": {"iSVip/iVip/iYearVip/iTotalActiveDay/...": {"value": ...}}

        }

      }

    失败时 code != 200；成功时 data.basic_info 为空字典或列表，需容错。

    """

    if not base_url:

        return {}

    # 拼接 query：?qq=xxx（base_url 里可能已经有 ?query，这里简单处理）

    sep = "&" if ("?" in base_url) else "?"

    url = "%s%sqq=%s" % (base_url, sep, qq)

    try:

        import requests  # noqa

    except Exception:

        try:

            import urllib.request

            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

            with urllib.request.urlopen(req, timeout=8) as r:

                raw = r.read().decode("utf-8", "ignore")

            data = _json.loads(raw) if raw else {}

        except Exception as e:

            _throttled_err_log("川源API", "请求失败: %s" % e)

            with _lock:

                _status["last_qq_api_error"] = "川源API请求失败: %s" % e

            return {}

    else:

        try:

            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)

            data = r.json() if r.status_code == 200 else {}

        except Exception as e:

            _throttled_err_log("川源API", "请求失败: %s" % e)

            with _lock:

                _status["last_qq_api_error"] = "川源API请求失败: %s" % e

            return {}

    if not isinstance(data, dict):

        return {}

    code = data.get("code")

    if code not in (0, 200, "0", "200"):

        msg = data.get("msg") or data.get("message") or code

        with _lock:

            _status["last_qq_api_error"] = "川源API: %s" % msg

        return {}

    node = data.get("data") or {}

    if not isinstance(node, dict):

        return {}

    # basic_info：dict 或 []，字段都是 {"value":..., "description":...}

    def _bget(key, default=""):

        sub = node.get("basic_info") or {}

        if isinstance(sub, dict):

            v = sub.get(key) or {}

            if isinstance(v, dict):

                return v.get("value", default)

            return v if v is not None else default

        return default

    # detail_info：结构同上

    def _dget(key, default=""):

        sub = node.get("detail_info") or {}

        if isinstance(sub, dict):

            v = sub.get(key) or {}

            if isinstance(v, dict):

                return v.get("value", default)

            return v if v is not None else default

        return default

    # 注册时间戳 → 形如 "2014-01-01 12:34:56"

    reg_ts = _bget("regTime", "")

    reg_time_str = ""

    try:

        if reg_ts and str(reg_ts).isdigit():

            reg_time_str = datetime.fromtimestamp(int(reg_ts)).strftime("%Y-%m-%d %H:%M:%S")

    except Exception:

        reg_time_str = ""

    # 注册天数（按当前时间 - 注册时间计算）

    reg_days = ""

    try:

        if reg_ts and str(reg_ts).isdigit():

            reg_days = str(max(0, (int(time.time()) - int(reg_ts)) // 86400))

    except Exception:

        reg_days = ""

    # 头像修改：iAvatarModified 之类

    # services：开通业务汇总成 "超级会员Lv8;QQ会员"

    services = node.get("services") or []

    if isinstance(services, list):

        opened_services = ";".join(

            s.get("name", "") for s in services if isinstance(s, dict) and s.get("name")

        )

    else:

        opened_services = ""

    # 能量：QQ 资料里"能量"实际对应 dwo 协议的成长/升级相关字段

    # iBigClubGrowth = 大会员成长值(/天)

    # iNextLevelDay  = 升级剩余天数

    # speedStar/v2/v3 = 加速星星等级

    def _energy_str():

        parts = []

        growth = _dget("iBigClubGrowth", "")

        if growth not in ("", "0", 0, None):

            parts.append("成长 %s/天" % growth)

        nld = _dget("iNextLevelDay", "")

        if nld not in ("", "0", 0, None):

            parts.append("升级剩 %s 天" % nld)

        star = _dget("speedStar", "")

        if star not in ("", "0", 0, None):

            parts.append("加速星 %s" % star)

        return " · ".join(parts)

    energy = _energy_str()

    # 名片：iCard 之类

    card = ""

    # 达人天数：川源 dwo qqnet 协议的"达人"字段在 detail_info 里，

    # 但实际所有账号都返回 "0.0"，没真实数据。

    # 因此按优先级尝试多个字段：

    #   1) iMaxLvlRealDays  最高等级实际活跃天数（协议字段）

    #   2) iRealDays        实际活跃天数（协议字段）

    #   3) iSvrDays         SVR 端实际活跃天数（协议字段）

    #   4) iBaseDays        基础活跃天数（协议字段）

    #   5) iMaxLvlTotalDays 最高等级累计天数（年，例 9.6 → 9.6 年）作为兜底

    # 若全部无效，按 iMaxLvlTotalDays 折算成"达人天数"提示。

    def _is_real(v):

        if v in (None, ""):

            return False

        try:

            f = float(str(v).strip())

            return f > 0

        except Exception:

            return False

    expert_days = ""

    expert_src = ""

    for key in ("iMaxLvlRealDays", "iRealDays", "iSvrDays", "iBaseDays"):

        raw = _dget(key, "")

        if _is_real(raw):

            try:

                n = float(str(raw).strip())

                if n >= 1:

                    expert_days = "%s 天" % (int(n) if n == int(n) else round(n, 1))

                else:

                    expert_days = "%s 天 (≈%s 小时)" % (round(n, 2), round(n * 24, 1))

                expert_src = key

                break

            except Exception:

                pass

    if not expert_days:

        # 兜底：用 iMaxLvlTotalDays（年）换算成天数

        mlt = _dget("iMaxLvlTotalDays", "")

        if _is_real(mlt):

            try:

                years = float(str(mlt).strip())

                days = int(years * 365.25)

                if days > 0:

                    expert_days = "%s 天 (≈%s 年 Q龄)" % (days, round(years, 1))

                    expert_src = "iMaxLvlTotalDays"

            except Exception:

                pass

    # 头像是否修改：iAvatarModified

    avatar_modified = _dget("iAvatarModified", "")

    # 月大会员 / 年大会员：iVip / iYearVip

    i_vip = str(_dget("iVip", "0"))

    i_svip = str(_dget("iSVip", "0"))

    i_year_vip = str(_dget("iYearVip", "0"))

    monthly_vip = "是" if i_vip == "1" else "否"

    annual_vip = "是" if i_year_vip == "1" else "否"

    super_vip = "是" if i_svip == "1" else "否"

    # 普通会员 = isVip 且非 svip

    normal_vip = "是" if (i_vip == "1" and i_svip != "1") else "否"

    annual_fee_vip = annual_vip  # iYearVip 就是年费

    # 会员经验 / 成长：iVipExp / iVipGrowth（不一定存在）

    vip_exp = _dget("iVipExp", "")

    vip_growth = _dget("iBigClubGrowth", _dget("iVipGrowth", ""))

    # 注册天数 → 转成年

    reg_days_str = ""

    try:

        if reg_ts and str(reg_ts).isdigit():

            d = max(0, (int(time.time()) - int(reg_ts)) // 86400)

            years = d / 365.25

            # 顺带从 detail_info 里取"最高等级总活跃天数"（Q龄年）做兜底

            max_lvl_total = _dget("iMaxLvlTotalDays", "")

            if max_lvl_total and max_lvl_total not in ("0", 0, "0.0", None):

                reg_days_str = "%s 天 (≈%s 年 / Q龄 %s 年)" % (d, round(years, 1), max_lvl_total)

            else:

                reg_days_str = "%s 天 (≈%s 年)" % (d, round(years, 1))

    except Exception:

        reg_days_str = ""

    return {

        "qq": str(_bget("qq", qq)),

        "nickname": str(_bget("nickname", "") or _bget("name", "")),

        "avatar": str(_bget("avatar", "")),

        "level": int(_bget("level", 0) or 0),

        "qid": str(_bget("qid", "")),

        "energy": str(energy),

        "card": str(card),

        "signature": str(_bget("sing", "") or _bget("sign", "")),

        "age": str(_bget("age", "")),

        "sex": str(_bget("sex", "")),

        "expert_days": str(expert_days),

        "reg_time": str(reg_time_str),

        "reg_days": str(reg_days_str),

        "avatar_modified": str(avatar_modified),

        "monthly_vip": str(monthly_vip),

        "annual_vip": str(annual_vip),

        "active_days": str(_dget("iTotalActiveDay", "")),

        "vip_level": int(_bget("vip_level", 0) or 0),

        "vip_exp": str(vip_exp),

        "vip_growth": str(vip_growth),

        "normal_vip": str(normal_vip),

        "super_vip": str(super_vip),

        "annual_fee_vip": str(annual_fee_vip),

        "opened_services": str(opened_services),

    }

def _fetch_qq_via_xiaodu(qq: str, key: str) -> dict:

    """小渡API（https://xxapi.cn）查询QQ资料。"""

    try:

        import requests  # noqa

    except Exception:

        try:

            import urllib.request, urllib.parse

            url = "https://v2.xxapi.cn/api/qqinfo?qq=%s&key=%s" % (urllib.parse.quote(qq), urllib.parse.quote(key))

            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

            with urllib.request.urlopen(req, timeout=8) as r:

                raw = r.read().decode("utf-8", "ignore")

            data = _json.loads(raw) if raw else {}

        except Exception as e:

            print("[console_server] 小渡API请求失败: %s" % e, flush=True)

            return {}

    else:

        try:

            r = requests.get(

                "https://v2.xxapi.cn/api/qqinfo",

                params={"qq": qq, "key": key},

                headers={"User-Agent": "Mozilla/5.0"},

                timeout=8,

            )

            data = r.json() if r.status_code == 200 else {}

        except Exception as e:

            print("[console_server] 小渡API请求失败: %s" % e, flush=True)

            return {}

    if not isinstance(data, dict):

        return {}

    # 小渡的失败响应形如 {"code":-2, "msg":"未查询到该接口", "data":""}

    code = data.get("code")

    if code not in (None, 0, 200, "0", "200"):

        # code = -2 视为"接口不可用/KEY 无权访问"，不算业务错误

        if code == -2:

            with _lock:

                _status["last_qq_api_error"] = (

                    "小渡API: 该KEY无权访问 qqinfo 接口（达人天数等字段不可用）"

                )

            return {}

        # 真实业务错误：把 msg 透传给上层日志

        msg = data.get("msg", "")

        with _lock:

            _status["last_qq_api_error"] = "小渡API: %s" % (msg or code)

        return {}

    node = data.get("data") if isinstance(data.get("data"), dict) else data

    return {

        "qq": str(node.get("qq") or qq),

        "nickname": str(node.get("nickname") or node.get("name") or ""),

        "avatar": str(node.get("avatar") or node.get("headimg") or ""),

        "level": int(node.get("level") or 0),

        "qid": str(node.get("qid") or ""),

        "energy": str(node.get("energy") or ""),

        "card": str(node.get("card") or ""),

        "signature": str(node.get("signature") or node.get("sign") or ""),

        "age": str(node.get("age") or ""),

        "expert_days": str(node.get("expert_days") or ""),

        "reg_time": str(node.get("reg_time") or ""),

        "reg_days": str(node.get("reg_days") or ""),

        "avatar_modified": str(node.get("avatar_modified") or ""),

        "monthly_vip": str(node.get("monthly_vip") or ""),

        "annual_vip": str(node.get("annual_vip") or ""),

        "active_days": str(node.get("active_days") or ""),

        "vip_level": int(node.get("vip_level") or 0),

        "vip_exp": str(node.get("vip_exp") or ""),

        "vip_growth": str(node.get("vip_growth") or ""),

        "normal_vip": str(node.get("normal_vip") or ""),

        "super_vip": str(node.get("super_vip") or ""),

        "annual_fee_vip": str(node.get("annual_fee_vip") or ""),

        "opened_services": str(node.get("opened_services") or ""),

    }

def _fetch_qq_via_shwgij(qq: str, key: str) -> dict:

    """相见拾光API（https://api.shwgij.com）查询QQ资料。"""

    try:

        import requests  # noqa

    except Exception:

        try:

            import urllib.request, urllib.parse

            url = "https://api.shwgij.com/api/qqinfo?qq=%s&key=%s" % (urllib.parse.quote(qq), urllib.parse.quote(key))

            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

            with urllib.request.urlopen(req, timeout=8) as r:

                raw = r.read().decode("utf-8", "ignore")

            data = _json.loads(raw) if raw else {}

        except Exception as e:

            print("[console_server] 相见拾光API请求失败: %s" % e, flush=True)

            return {}

    else:

        try:

            r = requests.get(

                "https://api.shwgij.com/api/qqinfo",

                params={"qq": qq, "key": key},

                headers={"User-Agent": "Mozilla/5.0"},

                timeout=8,

            )

            data = r.json() if r.status_code == 200 else {}

        except Exception as e:

            print("[console_server] 相见拾光API请求失败: %s" % e, flush=True)

            return {}

    if not isinstance(data, dict):

        return {}

    if data.get("code") not in (0, 200, "0", "200") and "data" not in data:

        return {}

    node = data.get("data") if isinstance(data.get("data"), dict) else data

    return {

        "qq": str(node.get("qq") or qq),

        "nickname": str(node.get("nickname") or node.get("name") or ""),

        "avatar": str(node.get("avatar") or node.get("headimg") or ""),

        "level": int(node.get("level") or 0),

        "qid": str(node.get("qid") or ""),

        "energy": str(node.get("energy") or ""),

        "card": str(node.get("card") or ""),

        "signature": str(node.get("signature") or node.get("sign") or ""),

        "age": str(node.get("age") or ""),

        "expert_days": str(node.get("expert_days") or ""),

        "reg_time": str(node.get("reg_time") or ""),

        "reg_days": str(node.get("reg_days") or ""),

        "avatar_modified": str(node.get("avatar_modified") or ""),

        "monthly_vip": str(node.get("monthly_vip") or ""),

        "annual_vip": str(node.get("annual_vip") or ""),

        "active_days": str(node.get("active_days") or ""),

        "vip_level": int(node.get("vip_level") or 0),

        "vip_exp": str(node.get("vip_exp") or ""),

        "vip_growth": str(node.get("vip_growth") or ""),

        "normal_vip": str(node.get("normal_vip") or ""),

        "super_vip": str(node.get("super_vip") or ""),

        "annual_fee_vip": str(node.get("annual_fee_vip") or ""),

        "opened_services": str(node.get("opened_services") or ""),

    }

def _fetch_nickname_via_oiapi_openid(member_openid):

    """通过 OIAPI Openid 接口反查 QQ 用户昵称（免鉴权官方渠道）。

    文档：https://oiapi.net/api/Openid

    入参：openid（QQ Bot 平台用户 openid） + appid（机器人 appid）

    返回：{"code":1,"message":"昵称","data":{"openid":"...","nickname":"...","button":0,"age":0,"head_decorate":0}}

    成功 code=1，message / data.nickname 即昵称；失败 code=-1（参数错误 / openid 不存在）。

    鉴权：实测免 ckey（三种鉴权方式返回完全一致，无需任何 key）。

    用途：填 _upsert_member 时 author.username 为空 / 用户未绑 QQ 时无法反查昵称的洞。

    """

    if not member_openid:

        return ""

    with _lock:

        cached = _oiapi_nickname_cache.get(member_openid)

        if cached is not None:

            return cached

    try:

        from modules.config import (

            OIAPI_OPENID_URL, OIAPI_OPENID_APPID, OIAPI_OPENID_TIMEOUT, APPID,

        )

    except Exception:

        return ""

    if not OIAPI_OPENID_URL:

        return ""

    appid = (OIAPI_OPENID_APPID or APPID or "").strip()

    if not appid:

        return ""

    sep = "&" if ("?" in OIAPI_OPENID_URL) else "?"

    try:

        url = "%s%sopenid=%s&appid=%s" % (

            OIAPI_OPENID_URL, sep,

            urllib.parse.quote(member_openid, safe=""),

            urllib.parse.quote(appid, safe=""),

        )

    except Exception:

        return ""

    try:

        try:

            import requests

            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=OIAPI_OPENID_TIMEOUT)

            raw = r.text

        except Exception:

            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

            with urllib.request.urlopen(req, timeout=OIAPI_OPENID_TIMEOUT) as resp:

                raw = resp.read().decode("utf-8", "ignore")

        data = _json.loads(raw) if raw else {}

        if not isinstance(data, dict):

            return ""

        if str(data.get("code")) not in ("1",):

            return ""

        # message 与 data.nickname 都可能为昵称（实测都填了昵称）

        nick = str(data.get("message") or "").strip()

        node = data.get("data") or {}

        if isinstance(node, dict):

            node_nick = str(node.get("nickname") or "").strip()

            if node_nick:

                nick = node_nick

        if not nick:

            return ""

        with _lock:

            _oiapi_nickname_cache[member_openid] = nick

        return nick

    except Exception as e:

        print("[console_server] OIAPI Openid 反查失败: %s" % e, flush=True)

        return ""

def _refresh_member_nickname_from_oiapi(member_openid):

    """用 OIAPI 反查昵称并更新 _members 缓存，返回新昵称（失败返回空）。"""

    nick = _fetch_nickname_via_oiapi_openid(member_openid)

    if not nick:

        return ""

    with _lock:

        m = _members.get(member_openid)

        if m is not None:

            m["nickname"] = nick

            m["nickname_source"] = "oiapi"

            _save_members()

    return nick

def get_user_detail_info(member_openid):

    """返回该用户的完整资料 dict。

    流程：

      1. 拿 _user_qq_bindings 里该用户绑定的 QQ 号

      2. 调 fetch_and_save_qq_info 拿到 25 个详细字段（merge 时 OIAPI Openid 作为 nickname 最高优先级）

      3. 没绑 QQ 时用 OIAPI Openid 反查昵称兜底（之前直接用 openid 占位）

    bot.py「我的信息」会从这个 dict 里读 qq_nickname / qq_level / qq_active_days 等键，

    所以这里统一加 "qq_" 前缀再返回。

    """

    qq = get_user_qq_number(member_openid) or ""

    avatar = get_user_avatar_url(member_openid) or ""

    base = {

        "openid": member_openid,

        "qq": qq,

        "nickname": "",

        "avatar": avatar,

    }

    if not qq:

        # 未绑 QQ：用 OIAPI Openid 反查昵称兜底

        nick = _fetch_nickname_via_oiapi_openid(member_openid)

        if nick:

            base["nickname"] = nick

            base["nickname_source"] = "oiapi"

        return base

    try:

        info = fetch_and_save_qq_info(member_openid, qq) or {}

    except Exception as e:

        print("[console_server] get_user_detail_info 失败: %s" % e, flush=True)

        return base

    if not isinstance(info, dict):

        return base

    # 加 "qq_" 前缀的别名，方便 bot.py 直接用

    aliases = {

        "qq_nickname": "nickname",

        "qq_level": "level",

        "qq_qid": "qid",

        "qq_energy": "energy",

        "qq_card": "card",

        "qq_signature": "signature",

        "qq_age": "age",

        "qq_expert_days": "expert_days",

        "qq_reg_time": "reg_time",

        "qq_reg_days": "reg_days",

        "qq_avatar_modified": "avatar_modified",

        "qq_monthly_vip": "monthly_vip",

        "qq_annual_vip": "annual_vip",

        "qq_active_days": "active_days",

        "qq_vip_level": "vip_level",

        "qq_vip_exp": "vip_exp",

        "qq_vip_growth": "vip_growth",

        "qq_normal_vip": "normal_vip",

        "qq_super_vip": "super_vip",

        "qq_annual_fee_vip": "annual_fee_vip",

        "qq_opened_services": "opened_services",

    }

    for alias_key, src_key in aliases.items():

        val = info.get(src_key)

        if val not in (None, "", 0):

            base[alias_key] = val

    # nickname 兜底（避免空）

    if not base.get("nickname") and info.get("nickname"):

        base["nickname"] = info["nickname"]

    # avatar 兜底

    if not base.get("avatar") and info.get("avatar"):

        base["avatar"] = info["avatar"]

    return base

def get_group_display_name(group_openid):

    with _lock:

        return _group_names.get(group_openid, "")

def get_user_avatar_url(user_openid):

    with _lock:

        return _user_avatars.get(user_openid, "")

def get_member_cached_nickname(openid):

    """从 _members 缓存读用户昵称（仅本地，不调 OIAPI/外部 API）。

    入群通知优先用这个拿昵称，避免反复触发反查 HTTP 调用。

    无记录返回空字符串。

    """

    if not openid:

        return ""

    try:

        with _lock:

            m = _members.get(openid) or {}

            return (m.get("nickname") or "").strip()

    except Exception:

        return ""

# ===== 已绑定 QQ 用户的真实昵称/头像缓存（供消息监控界面展示） =====

_user_real_profiles = {}

_USER_PROFILE_TTL = 600  # 秒；10 分钟内重复请求不重新拉取

def get_user_real_profile(openid):

    """返回已绑定 QQ 用户的真实昵称/头像（带缓存）。

    未绑定 QQ、或拉取失败则返回 None；拉取成功返回

    {"nickname": str, "avatar": str, "qq": str, "ts": float}。

    """

    qq = get_user_qq_number(openid)

    if not qq:

        return None

    cached = _user_real_profiles.get(openid)

    if cached and (time.time() - cached.get("ts", 0)) < _USER_PROFILE_TTL:

        return cached

    try:

        info = get_user_detail_info(openid) or {}

    except Exception:

        info = {}

    real = {

        "nickname": info.get("nickname") or "",

        "avatar": info.get("avatar") or "",

        "qq": qq,

        "ts": time.time(),

    }

    _user_real_profiles[openid] = real

    return real

def invalidate_user_real_profile(openid):

    """绑定/解绑 QQ 后清空缓存，下次请求会刷新真实资料。"""

    _user_real_profiles.pop(openid, None)

def _group_avatar_url(qq_number):

    """根据 QQ 群号生成腾讯官方群头像 URL。"""

    if not qq_number:

        return ""

    qq = str(qq_number).strip()

    if not qq.isdigit():

        return ""

    return "https://p.qlogo.cn/gh/%s/%s/640" % (qq, qq)

def bind_group_qq_number(group_openid, qq_number):

    with _lock:

        if qq_number is None or qq_number == "":

            _group_qq_bindings.pop(group_openid, None)

            prof = _group_profiles.get(group_openid) or {}

            prof.pop("avatar", None)

            prof.pop("qq", None)

            if prof:

                _group_profiles[group_openid] = prof

            else:

                _group_profiles.pop(group_openid, None)

        else:

            qq = str(qq_number)

            _group_qq_bindings[group_openid] = qq

            _group_profiles[group_openid] = {

                "name": (_group_profiles.get(group_openid) or {}).get("name", ""),

                "avatar": _group_avatar_url(qq),

                "qq": qq,

                "ts": time.time(),

            }

    _save_qq_bindings()

    _save_group_profiles()

    return True

def get_group_profile(group_openid):

    """返回群的显示资料 {name, avatar, qq}；name 优先取用户手动设置的群名。"""

    with _lock:

        prof = _group_profiles.get(group_openid) or {}

        qq = _group_qq_bindings.get(group_openid, prof.get("qq", ""))

        name = prof.get("name", "")

        avatar = prof.get("avatar", "")

        if qq and not avatar:

            avatar = _group_avatar_url(qq)

        return {"name": name, "avatar": avatar, "qq": qq}

def set_group_name(group_openid, name):

    """手动设置群在控制台中的显示名称。"""

    if not group_openid:

        return False

    name = str(name or "").strip()

    with _lock:

        prof = _group_profiles.get(group_openid) or {}

        qq = _group_qq_bindings.get(group_openid, prof.get("qq", ""))

        prof["name"] = name

        prof["qq"] = qq

        if qq and not prof.get("avatar"):

            prof["avatar"] = _group_avatar_url(qq)

        prof["ts"] = time.time()

        _group_profiles[group_openid] = prof

    _save_group_profiles()

    return True

def bind_user_qq_number(user_openid, qq_number):

    with _lock:

        if qq_number is None or qq_number == "":

            _user_qq_bindings.pop(user_openid, None)

        else:

            _user_qq_bindings[user_openid] = str(qq_number)

    _save_qq_bindings()

    invalidate_user_real_profile(user_openid)

    return True

def get_group_qq_number(group_openid):

    with _lock:

        return _group_qq_bindings.get(group_openid, "")

def get_user_qq_number(user_openid):

    with _lock:

        return _user_qq_bindings.get(user_openid, "")

def update_group_contact(group_openid, name=None, **kwargs):

    with _lock:

        if name:

            _group_names[group_openid] = str(name)

    return True

def remove_group_contact(group_openid):

    """机器人被移出群聊时调用：彻底清理该群在所有数据结构里的痕迹并落盘。"""

    group_openid = str(group_openid or "").strip()

    if not group_openid:

        return False

    with _lock:

        _group_names.pop(group_openid, None)

        _group_qq_bindings.pop(group_openid, None)

        _group_profiles.pop(group_openid, None)

        # 把该群从所有成员的 groups 列表中剔除
        for _m in _members.values():

            _gs = _m.get("groups") or []

            if group_openid in _gs:

                _m["groups"] = [g for g in _gs if g != group_openid]


        # 从群-机器人映射里也剔除（pop 不会触发 _BotMap 节流落盘，这里手动标脏）

        GROUP_BOT_MAP.pop(group_openid, None)


    # 官方群信息缓存（独立锁）

    with _group_info_lock:

        _group_info_cache.pop(group_openid, None)


    # 落盘

    _save_qq_bindings()

    _save_group_names()

    _save_group_profiles()

    _save_members()

    _save_group_info_cache()

    try:

        # 直接写 group_bot_map.json（pop 不触发 _BotMap 节流，需手动落盘）

        _p = os.path.join(_DATA_ROOT_DIR, "group_bot_map.json")

        with open(_p + ".tmp", "w", encoding="utf-8") as _f:

            _json.dump({"groups": dict(GROUP_BOT_MAP), "users": dict(USER_BOT_MAP)}, _f, ensure_ascii=False)

        os.replace(_p + ".tmp", _p)

    except Exception as _e:

        print("[console_server] 落盘 group_bot_map 失败: %s" % _e, flush=True)

    return True

# ===== 今日事件计数器（进群 / 退群 / 加好友 / 删好友） =====

# 以本地自然日为周期，跨天自动清零，与「今日」语义一致。

_TODAY_EVENT_KEYS = (

    "groups_joined_today",

    "groups_left_today",

    "friends_added_today",

    "friends_removed_today",

)

def _rollover_today_counters_if_needed():

    """若本地日期已跨天，将今日计数清零（含消息/事件计数），并落盘。"""

    today = time.strftime("%Y-%m-%d")

    if _status.get("_today_event_date") != today:

        with _lock:
            _status["_today_event_date"] = today
            for _k in _TODAY_KEYS:
                _status[_k] = 0
                for _bb in _status_by_bot.values():
                    _bb[_k] = 0
        _save_today_stats()

def _inc_today_event(key, bot=""):
    with _lock:
        _rollover_today_counters_if_needed()
        _status[key] = _status.get(key, 0) + 1
        if bot:
            _bb = _status_by_bot.setdefault(bot, {})
            _bb[key] = _bb.get(key, 0) + 1
        _save_today_stats()

def inc_groups_joined_today(bot=""):
    """机器人今日被拉入群聊数 +1。"""
    _inc_today_event("groups_joined_today", bot)

def inc_groups_left_today(bot=""):
    """机器人今日被移出群聊数 +1。"""
    _inc_today_event("groups_left_today", bot)

def inc_friends_added_today(bot=""):
    """今日新增好友数 +1。"""
    _inc_today_event("friends_added_today", bot)

def inc_friends_removed_today(bot=""):
    """今日删除好友数 +1。"""
    _inc_today_event("friends_removed_today", bot)

# =====================================================================
# 今日小时级消息聚合（按自然日分桶；用于 admin 数据总览「今日活跃时段」图表）
# 数据源：record_message 包装层（最高频、最准确，不依赖 _message_logs 滚动上限）。
# 物理隔离：data/bots/_shared/hourly_messages.json。
# 结构：{"YYYY-MM-DD": {"total":[0]*24, "group":[0]*24, "private":[0]*24}}，保留最近 30 天。
# =====================================================================

# 与 today_stats 持久化同位置；旧根 data/hourly_messages.json 启动时一次性迁移。
_HOURLY_MSG_FILE = _bot_file("_shared", "hourly_messages.json")
_OLD_HOURLY_MSG_FILE = os.path.join(_DATA_ROOT_DIR, "hourly_messages.json")
_HOURLY_KEEP_DAYS = 30
_HOURLY_PERSIST_EVERY = 80  # 每累加 N 条脏计数触发落盘，降低高频 I/O 压力

# 内存主表（线程安全：所有读写均在 _lock 内）；结构见上方注释。
_hourly_msg_by_day = {}
_hourly_dirty = 0  # 自上次落盘以来未保存的累加条数


def _ensure_hourly_buckets():
    """获取今日小时分布；若不存在则初始化为 24 元素 0 数组并装入主表。"""
    today = time.strftime("%Y-%m-%d", time.localtime())
    bucket = _hourly_msg_by_day.get(today)
    if not isinstance(bucket, dict) or len(bucket.get("total") or []) != 24:
        bucket = {"total": [0] * 24, "group": [0] * 24, "private": [0] * 24}
        _hourly_msg_by_day[today] = bucket
    return bucket


def _prune_hourly_history():
    """裁剪 _HOURLY_KEEP_DAYS 天之前的旧日数据，避免字典无限膨胀。"""
    try:
        cutoff = (datetime.now() - timedelta(days=_HOURLY_KEEP_DAYS)).strftime("%Y-%m-%d")
        stale = [k for k in list(_hourly_msg_by_day.keys()) if k < cutoff]
        for k in stale:
            _hourly_msg_by_day.pop(k, None)
    except Exception:
        pass


def _save_hourly_messages():
    """原子落盘小时聚合；不抛异常。"""
    try:
        with _lock:
            payload = {"_saved_at": int(time.time()), "days": dict(_hourly_msg_by_day)}
        d = os.path.dirname(_HOURLY_MSG_FILE)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        tmp = _HOURLY_MSG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            _json.dump(payload, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _HOURLY_MSG_FILE)
    except Exception as e:  # noqa: BLE001
        try:
            logger.warning("[hourly_messages] 保存失败（忽略）: %s" % e)
        except Exception:
            pass


def _load_hourly_messages():
    """启动时从磁盘恢复小时聚合；一次性迁移旧根文件。仅保留最近 _HOURLY_KEEP_DAYS 天。"""
    src = _HOURLY_MSG_FILE if os.path.exists(_HOURLY_MSG_FILE) else (_OLD_HOURLY_MSG_FILE if os.path.exists(_OLD_HOURLY_MSG_FILE) else None)
    if not src:
        return
    try:
        with open(src, "r", encoding="utf-8") as f:
            data = _json.load(f)
        if not isinstance(data, dict):
            return
        days_raw = data.get("days") if "days" in data else data  # 兼容直接 dict-of-days
        if not isinstance(days_raw, dict):
            return
        with _lock:
            for k, v in days_raw.items():
                if not (isinstance(k, str) and isinstance(v, dict)):
                    continue
                b = v.get("total")
                if not (isinstance(b, list) and len(b) == 24 and all(isinstance(x, (int, float)) for x in b)):
                    continue
                gp = v.get("group")
                pv = v.get("private")
                bucket = {
                    "total": [int(x) for x in b],
                    "group": [int(x) for x in gp] if (isinstance(gp, list) and len(gp) == 24) else [0] * 24,
                    "private": [int(x) for x in pv] if (isinstance(pv, list) and len(pv) == 24) else [0] * 24,
                }
                _hourly_msg_by_day[k] = bucket
            _prune_hourly_history()
        # 若数据来自旧根，立刻迁移到 _shared 位置
        if src == _OLD_HOURLY_MSG_FILE:
            try:
                _save_hourly_messages()
            except Exception:
                pass
    except Exception as e:  # noqa: BLE001
        try:
            logger.warning("[hourly_messages] 加载失败（忽略）: %s" % e)
        except Exception:
            pass


def _record_hourly_message(scene):
    """record_message 包装层调用：按当前本地小时累加 total / group / private。
    scene 取 "group" / "private" / 其它（仅入 total）。"""
    global _hourly_dirty
    try:
        h = int(time.strftime("%H", time.localtime()))
        need_save = False
        with _lock:
            bucket = _ensure_hourly_buckets()
            bucket["total"][h] = bucket["total"][h] + 1
            if scene == "group":
                bucket["group"][h] = bucket["group"][h] + 1
            elif scene == "private":
                bucket["private"][h] = bucket["private"][h] + 1
            _hourly_dirty += 1
            if _hourly_dirty >= _HOURLY_PERSIST_EVERY:
                _hourly_dirty = 0
                need_save = True
        if need_save:
            _save_hourly_messages()
    except Exception:  # noqa: BLE001
        pass


def _snapshot_today_hourly():
    """返回今日 24h 分布快照（total/group/private），用于 /api/stats payload。"""
    with _lock:
        bucket = _ensure_hourly_buckets()
        return {
            "date": time.strftime("%Y-%m-%d", time.localtime()),
            "total": list(bucket["total"]),
            "group": list(bucket["group"]),
            "private": list(bucket["private"]),
        }


# 模块导入期执行：恢复历史并裁剪；任何异常不外抛
_load_hourly_messages()

def _load_today_stats():
    """启动时从磁盘恢复「今日」计数，使重启 / 关机不丢失当天统计。
    物理隔离：全局聚合存 data/bots/_shared/today_stats.json，
    每机器人明细存 data/bots/<appid>/today_stats.json（含 _appid / _bot_name 便于回挂）。
    兼容旧版单文件 data/today_stats.json（含 _by_bot）。"""
    try:
        # 1) 全局聚合：优先 _shared，其次旧根文件
        _shared_file = _bot_file("_shared", "today_stats.json")
        _loaded_global = False
        if os.path.exists(_shared_file):
            try:
                with open(_shared_file, "r", encoding="utf-8") as f:
                    data = _json.load(f)
                if isinstance(data, dict):
                    with _lock:
                        for k in _TODAY_KEYS:
                            if k in data and isinstance(data[k], (int, float)):
                                _status[k] = data[k]
                        if "_today_event_date" in data and isinstance(data["_today_event_date"], str):
                            _status["_today_event_date"] = data["_today_event_date"]
                    _loaded_global = True
            except Exception as e:
                logger.warning("[today_stats] 读取全局聚合失败（忽略）: %s" % e)
        if not _loaded_global and os.path.exists(_TODAY_STATS_FILE):
            try:
                with open(_TODAY_STATS_FILE, "r", encoding="utf-8") as f:
                    data = _json.load(f)
                if isinstance(data, dict):
                    with _lock:
                        for k in _TODAY_KEYS:
                            if k in data and isinstance(data[k], (int, float)):
                                _status[k] = data[k]
                        if "_today_event_date" in data and isinstance(data["_today_event_date"], str):
                            _status["_today_event_date"] = data["_today_event_date"]
            except Exception:
                pass

        # 2) 每机器人明细：遍历 data/bots/<appid>/today_stats.json
        _bots_root = os.path.join(_DATA_ROOT_DIR, "bots")
        with _lock:
            _status_by_bot.clear()
        if os.path.isdir(_bots_root):
            for _name in sorted(os.listdir(_bots_root)):
                if _name == "_shared":
                    continue
                _bd = os.path.join(_bots_root, _name)
                if not os.path.isdir(_bd):
                    continue
                _tf = os.path.join(_bd, "today_stats.json")
                if not os.path.exists(_tf):
                    continue
                try:
                    with open(_tf, "r", encoding="utf-8") as f:
                        _pd = _json.load(f)
                except Exception:
                    continue
                if not isinstance(_pd, dict):
                    continue
                _bn = _pd.get("_bot_name") or _name
                _pdate = _pd.get("_today_event_date")
                _gdate = _status.get("_today_event_date")
                # 仅当日期与全局一致才回挂（避免跨天旧数据污染）
                if _pdate and _gdate and _pdate != _gdate:
                    continue
                with _lock:
                    _entry = {}
                    for _k in _TODAY_KEYS:
                        if _k in _pd and isinstance(_pd[_k], (int, float)):
                            _entry[_k] = _pd[_k]
                    if "_groups" in _pd and isinstance(_pd["_groups"], list):
                        _entry["_groups"] = set(_pd["_groups"])
                    _status_by_bot[_bn] = _entry

        # 3) 兼容旧版 _by_bot：仅补充尚未出现的机器人
        if os.path.exists(_TODAY_STATS_FILE):
            try:
                with open(_TODAY_STATS_FILE, "r", encoding="utf-8") as f:
                    _old = _json.load(f)
                if isinstance(_old, dict):
                    _raw_by_bot = _old.get("_by_bot") or {}
                    if isinstance(_raw_by_bot, dict):
                        with _lock:
                            for _b, _bb in _raw_by_bot.items():
                                if not isinstance(_bb, dict):
                                    continue
                                if _b in _status_by_bot:
                                    continue
                                _status_by_bot[_b] = {
                                    _kk: (set(_vv) if isinstance(_vv, list) else _vv)
                                    for _kk, _vv in _bb.items()
                                }
            except Exception:
                pass
    except Exception as e:  # noqa: BLE001
        logger.warning("[today_stats] 加载失败（忽略）: %s" % e)

def _save_today_stats():
    """原子落盘「今日」计数（物理隔离）。
    全局聚合 -> data/bots/_shared/today_stats.json；
    每机器人明细 -> data/bots/<appid>/today_stats.json。绝不抛异常。"""
    def _write_json(fpath, payload):
        d = os.path.dirname(fpath)
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        tmp = fpath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            _json.dump(payload, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, fpath)

    try:
        _shared_file = _bot_file("_shared", "today_stats.json")
        with _lock:
            _global_data = {k: _status.get(k, 0) for k in _TODAY_KEYS}
            _global_data["_today_event_date"] = _status.get(
                "_today_event_date", time.strftime("%Y-%m-%d")
            )
            _by_bot_snapshot = {}
            for _bn, _bb in _status_by_bot.items():
                _appid = resolve_bot_key(_bn) or _bn
                if _appid == _bn:
                    # 尚未解析出稳定 appid（桥接未就绪），跳过该机器人明细落盘，避免中文目录名
                    continue
                _out = {_k: _bb.get(_k, 0) for _k in _TODAY_KEYS}
                if isinstance(_bb.get("_groups"), set):
                    _out["_groups"] = list(_bb["_groups"])
                _out["_appid"] = _appid
                _out["_bot_name"] = _bn
                _out["_today_event_date"] = _global_data["_today_event_date"]
                _by_bot_snapshot[_appid] = _out
        # 写全局聚合
        _write_json(_shared_file, _global_data)
        # 写每机器人明细
        for _appid, _out in _by_bot_snapshot.items():
            if not _appid:
                continue
            _f = _bot_file(_appid, "today_stats.json")
            _write_json(_f, _out)
    except Exception as e:  # noqa: BLE001
        logger.warning("[today_stats] 保存失败（忽略）: %s" % e)

# 模块导入时恢复当天统计（在 _status / _lock / 常量定义之后）

_load_today_stats()

# 任何正常退出（含非 os._exit 的路径）都再落盘一次，作为最后兜底

try:

    import atexit

    atexit.register(_save_today_stats)

except Exception:  # noqa: BLE001

    pass

def update_friend_contact(user_openid, name=None, avatar=None, **kwargs):

    with _lock:

        if avatar:

            _user_avatars[user_openid] = str(avatar)

    return True

def remove_friend_contact(user_openid):

    with _lock:

        _user_avatars.pop(user_openid, None)

        _user_qq_bindings.pop(user_openid, None)

    _save_qq_bindings()

    return True

def sync_contact_from_message(scene, target_id, **kwargs):

    name = kwargs.get("name")

    if scene == "group" and target_id:

        # 记录「有发言记录的群聊」：无论是否已知群名都计入，跨重启保留

        _note_group_message(target_id, name or "")

    elif scene in ("c2c", "c2c_message", "friend") and name:

        with _lock:

            _user_avatars.setdefault(target_id, "")

    return True

def _known_bot_list():

    """返回控制台已绑定机器人清单（含真实名/头像/实时连通），供公告「选机器人」下拉使用。"""

    bots = []

    try:

        for _b in bot_manager.load_bots():

            _aid = _b.get("appid") or ""

            _rt = _bot_bridges.get(_aid) or {}

            bots.append({

                "appid": _aid,

                "appid_masked": bot_manager.mask_appid(_aid),

                "name": _b.get("name") or "",

                "name_rt": (_rt.get("name") or _b.get("name") or ""),

                "avatar": (_rt.get("avatar") or ""),

                "connected": (_aid in _bot_bridges and _bot_bridges[_aid].get("api") is not None),

            })

    except Exception:

        bots = []

    return bots


def get_known_contacts():

    """汇总「已知会话」，供控制台公告定向发布选择受众。

    返回：{

      "groups":  [{"chat_id":"g:xxx","openid":"xxx","name":"群名/群ID","avatar":""}, ...],

      "persons": [{"chat_id":"u:xxx","openid":"xxx","name":"昵称/openid","avatar":""}, ...],

    }

    数据来源：消息中心历史（_message_logs）+ 群资料缓存，按最近活跃去重。

    """

    with _admin_api_lock:

        groups = {}

        persons = {}

        for it in _message_logs:

            t = it.get("type", "")

            scene = it.get("scene") or ""

            sender = it.get("sender") or ""

            goid = it.get("group_openid") or scene or ""

            if t == "群聊" and goid and goid != "-":

                if goid not in groups:

                    gprof = get_group_profile(goid) or {}

                    gname = gprof.get("name") or _group_names.get(goid) or goid

                    groups[goid] = {

                        "chat_id": "g:" + goid,

                        "openid": goid,

                        "name": gname,

                        "avatar": gprof.get("avatar") or "",
                        "bot": GROUP_BOT_MAP.get(goid) or "",

                    }

            elif t == "单聊" and sender and sender != "-":

                if sender not in persons:

                    pname = it.get("nickname") or ""

                    pavatar = it.get("avatar") or ""

                    if not pname:

                        rp = get_user_real_profile(sender)

                        if rp:

                            pname = rp.get("nickname") or pname

                            pavatar = rp.get("avatar") or pavatar

                    persons[sender] = {

                        "chat_id": "u:" + sender,

                        "openid": sender,

                        "name": pname or sender,

                        "avatar": pavatar,
                        "bot": USER_BOT_MAP.get(sender) or "",

                    }

        # 群资料里有绑定群号但未在消息中出现的，也纳入

        for goid, prof in _group_profiles.items():

            if goid not in groups:

                gname = prof.get("name") or _group_names.get(goid) or goid

                groups[goid] = {

                    "chat_id": "g:" + goid,

                    "openid": goid,

                    "name": gname,

                    "avatar": prof.get("avatar") or "",
                    "bot": GROUP_BOT_MAP.get(goid) or "",

                }

        
        # 群聊受众：从 GROUP_BOT_MAP 补充（机器人实际加入的所有群）。
        # _group_profiles 只保存 bot 处理过消息的群，通常远少于真实加入的群，
        # 会导致公告面板群聊列表看起来很少。GROUP_BOT_MAP 是 QQ 平台事件建立的
        # 机器人-群绑定关系，可信且持久，用它补全剩余群聊。
        for goid, gappid in GROUP_BOT_MAP.items():
            if goid in groups:
                continue
            gname = _group_names.get(goid) or ""
            gavatar = ""
            if not gname:
                _entry = _group_info_cache.get(goid) or {}
                _gdata = _entry.get("data") or {}
                gname = _gdata.get("name") or ""
                gavatar = _gdata.get("avatar") or ""
            groups[goid] = {
                "chat_id": "g:" + goid,
                "openid": goid,
                "name": gname or goid,
                "avatar": gavatar,
                "bot": gappid or "",
            }

        # 单聊受众：从持久化成员表补充（_message_logs 仅内存、重启即丢，
        # 会导致好友范围长期为空、无法选择也无法定向发布）。
        # 仅纳入有过「private」来源的真实单聊联系人。
        for openid, m in _members.items():
            if openid in persons:
                continue
            srcs = m.get("sources") or []
            if not isinstance(srcs, (list, tuple, set)):
                srcs = [srcs] if srcs else []
            if "private" in srcs:
                pname = m.get("nickname") or ""
                persons[openid] = {
                    "chat_id": "u:" + openid,
                    "openid": openid,
                    "name": pname or openid,
                    "avatar": m.get("avatar") or "",
                    "bot": USER_BOT_MAP.get(openid) or "",
                }
        return {

            "groups": list(groups.values()),

            "persons": list(persons.values()),
            "bots": _known_bot_list(),

        }


def set_feature_enabled_global(name, enabled, appid=None):
    """设置功能开关。供插件安装 hook 调用，自动启用 master 大类开关。
    appid=None 时操作全局 _system_switches；非空时按 bot 隔离写入 _bot_system_switches。
    """
    with _lock:
        if not name:
            return
        if appid:
            _bot_system_switches.setdefault(str(appid), {})
            _bot_system_switches[str(appid)][name] = bool(enabled)
        else:
            _system_switches[name] = bool(enabled)
        _save_system_config()


def is_feature_enabled(name, appid=None):

    """功能总开关：按 bot appid 优先读取后台「功能开关」持久化的 _bot_system_switches，
    否则回退全局 _system_switches，再否则 _features，皆无则默认开启。
    兼容旧调用：不传 appid 时按全局取值（行为与历史一致）。"""

    if not name:

        return True

    appid_s = (str(appid).strip() if appid else "")

    if appid_s:

        with _lock:

            bot_overrides = _bot_system_switches.get(appid_s)

            if isinstance(bot_overrides, dict) and name in bot_overrides:

                val = bool(bot_overrides[name])

                if not val and name in ("checkin", "video", "music", "game", "tools", "novel", "study", "group_admin"):

                    print("[console_server] 功能 %s 已关闭 (bot=%s)" % (name, appid_s), flush=True)

                return val

    with _lock:

        if name in _system_switches:

            val = bool(_system_switches[name])

            if not val and name in ("checkin", "video", "music", "game", "tools", "novel", "study", "group_admin"):

                print("[console_server] 功能 %s 已关闭" % name, flush=True)

            return val

        if name in _features:

            return bool(_features[name])

    return True
def is_sub_feature_enabled(name, appid=None):

    """子功能开关：与总开关同样的 appid 优先回退链。
    若子功能所属系统总开关（按 appid 隔离判断）被关闭，则强制视为关闭。"""

    if not name:

        return True

    master = _SUB_TO_MASTER.get(name)

    if master and not is_feature_enabled(master, appid=appid):

        return False

    appid_s = (str(appid).strip() if appid else "")

    if appid_s:

        with _lock:

            bot_overrides = _bot_system_switches.get(appid_s)

            if isinstance(bot_overrides, dict) and name in bot_overrides:

                return bool(bot_overrides[name])

    with _lock:

        if name in _system_switches:

            return bool(_system_switches[name])

        if name in _sub_features:

            return bool(_sub_features[name])

    return True

def _list_runtime_bots():
    """当前 bots.json + 桥接状态合并后的 bot 列表，每项 {appid, name, name_rt, connected, ...}。"""
    out = []
    try:
        _cfg_bots = bot_manager.load_bots()
    except Exception:
        _cfg_bots = []
    for _b in (_cfg_bots or []):
        _aid = str(_b.get("appid") or "").strip()
        if not _aid:
            continue
        _rt = _bot_bridges.get(_aid) or {}
        out.append({
            "appid": _aid,
            "name": _b.get("name") or "",
            "name_rt": _rt.get("name") or _b.get("name") or "",
            "avatar": _rt.get("avatar") or "",
            "enabled": bool(_b.get("enabled", True)),
            "connected": bool(_rt.get("api") is not None),
        })
    return out


_SUB_CMD_MAP = {

    "签到": "checkin_sign",

    "签到排名": "checkin_rank",

    "签到查询": "checkin_query",

    "抽奖": "checkin_lottery",

    "随机音乐": "music_random",

    "音源": "music_source",

    "音源选择": "music_source",

    "点歌": "music_search",

    "选歌": "music_select",

    "五子棋": "game_gomoku",

    "五子棋AI": "game_gomoku",

    "AI对战": "game_gomoku",

    "五子棋双人": "game_gomoku",

    "二人对战": "game_gomoku",

    "猜成语": "game_idiom",

    "求签": "game_qiuqian",

    "塔罗牌": "game_tarot",

    "答案之书": "game_daanzi",

    "象棋": "game_xiangqi",

    "象棋AI": "game_xiangqi",

    "象棋双人": "game_xiangqi",

    "天气": "tool_weather",

    "王者": "tool_wangzhe",

    "王者信息": "tool_wangzhe",

    "运势": "game_horoscope",

    "今日运势": "game_horoscope",

    "星座运势": "game_horoscope",

    "今日老婆": "game_wife_today",

    "抽老婆": "game_wife_today",

    "wife": "game_wife_today",

    "脑筋急转弯": "game_brain_teaser",

    "急转弯": "game_brain_teaser",

    "猜谜语": "game_riddle",

    "谜语": "game_riddle",

    "猜谜": "game_riddle",

    "单词": "tool_word",

    "单词查询": "tool_word",

    "查词": "tool_word",

    "疾病信息": "tool_disease",

    "垃圾分类": "tool_waste",    "垃圾分类": "tool_waste",

    "视频解析": "tool_video_parse",

    "导航": "tool_navigation",

    "导航规划": "tool_navigation",

    "旅游": "tool_tourism",

    "旅游查询": "tool_tourism",

    "景点": "tool_tourism",

    "小说": "novel_menu",

    "看小说": "novel_menu",

    "读书": "novel_menu",

    "看书": "novel_menu",

    "在线阅读": "novel_menu",

    "读小说": "novel_menu",

    "知识问答": "study_quiz",

    "常识": "study_quiz",

    "问答": "study_quiz",

    "驾考": "study_driving",

    "驾考学习": "study_driving",

    "考驾照": "study_driving",

    "小学数学": "study_math",

    "数学题": "study_math",

    "数学": "study_math",

    "古诗文": "study_poetry",

    "古诗": "study_poetry",

    "诗词": "study_poetry",

    "违禁词列表": "admin_banlist",

    "违禁词设置": "admin_banset",

    "违禁词添加": "admin_banadd",

    "违禁词删除": "admin_bandel",

    "整点报时": "admin_chime",

}

# 视频系统 6 大分类各自对应一个子开关

_VIDEO_SUB = {

    "帅哥视频": "video_shuaige",

    "风景视频": "video_fengjing",

    "变装视频": "video_bianzhuang",

    "cos视频": "video_cos",

    "漫剪视频": "video_manjian",

    "游戏视频": "video_youxi",

    "二次元": "image_acg",

    "风景": "image_wallpaper",

    "随机壁纸": "image_bizhi",

    "原神cos": "image_yscos",

    "原神": "image_ys",

    "小姐姐": "image_meinvpic",

    "角色图库": "image_random",

    "随机图片": "image_random",

    "随机图": "image_random",

    "看图": "image_random",

}

# 前缀匹配（注意顺序：先精确、再视频分类、再前缀）

_SUB_PREFIX_MAP = (

    ("点歌", "music_search"),

    ("选歌", "music_select"),

    ("音源", "music_source"),

    ("王者", "tool_wangzhe"),

    ("运势", "game_horoscope"),

    ("单词", "tool_word"),

    ("天气", "tool_weather"),

    ("答案之书 ", "game_daanzi"),

    ("疾病信息 ", "tool_disease"),

    ("垃圾分类 ", "tool_waste"),

    ("导航 ", "tool_navigation"),

    ("旅游 ", "tool_tourism"),

    ("违禁词添加", "admin_banadd"),

    ("违禁词删除", "admin_bandel"),

    ("看 ", "novel_read"),

    ("读 ", "novel_read"),

)

# 旧学科出题正则已下线（学习系统改为知识问答/驾考/古诗文），保留空匹配避免影响其它正则
_SUBJECT_RE = re.compile(r"^(?!x)x")

# 子功能 key -> 所属系统总开关 key（用于 is_sub_feature_enabled 级联判断）

_SUB_TO_MASTER = {

    "checkin_sign": "checkin", "checkin_rank": "checkin", "checkin_query": "checkin", "checkin_lottery": "checkin",

    "video_shuaige": "video", "video_fengjing": "video", "video_bianzhuang": "video",

    "video_cos": "video", "video_manjian": "video", "video_youxi": "video",

    "image_acg": "image", "image_wallpaper": "image", "image_bizhi": "image", "image_yscos": "image", "image_ys": "image", "image_meinvpic": "image", "image_random": "image",

    "music_random": "music", "music_source": "music", "music_search": "music", "music_select": "music",

    "game_gomoku": "game", "game_idiom": "game", "game_xiangqi": "game", "game_qiuqian": "game", "game_daanzi": "game", "game_tarot": "game", "game_horoscope": "game","game_qiuqian": "game", "game_daanzi": "game", "game_tarot": "game", "game_horoscope": "game",

    "tool_weather": "tools", "tool_wangzhe": "tools", "tool_navigation": "tools", "tool_tourism": "tools",
    "game_horoscope": "game", "game_wife_today": "game", "game_brain_teaser": "game", "game_riddle": "game",
    "tool_disease": "tools", "tool_waste": "tools",

    "novel_menu": "novel", "novel_read": "novel",

    "study_quiz": "study", "study_driving": "study", "study_math": "study", "study_poetry": "study",

    "admin_banlist": "group_admin", "admin_banset": "group_admin",

    "admin_banadd": "group_admin", "admin_bandel": "group_admin", "admin_automod": "group_admin",

    "admin_chime": "group_admin",

    "admin_mute": "group_admin", "admin_mute_automod": "group_admin",

}

def sub_feature_key_for_cmd(cmd):

    """根据命令文本返回对应的子功能 key；无法识别返回 None（表示不受子开关控制）。"""

    if not cmd:

        return None

    c = (cmd or "").strip()

    if c in _SUB_CMD_MAP:

        return _SUB_CMD_MAP[c]

    for vcat, vkey in _VIDEO_SUB.items():

        if c == vcat or c.startswith(vcat):

            return vkey

    for prefix, key in _SUB_PREFIX_MAP:

        if c.startswith(prefix):

            return key

    if _SUBJECT_RE.match(c):

        return "study_query"

    return None

def resolve_sub_feature(content):

    """供 bot.py 命令拦截门控使用：直接复用 sub_feature_key_for_cmd。"""

    return sub_feature_key_for_cmd(content)

def get_master_feature(sub_key):

    """返回子功能所属的系统总开关 key；不属于任何系统返回 None。"""

    return _SUB_TO_MASTER.get(sub_key) if sub_key else None

def get_sub_features_by_master(master_key):

    """返回指定系统下所有已注册子功能 key 列表。"""

    if not master_key:

        return []

    return [k for k, v in _SUB_TO_MASTER.items() if v == master_key]

def register_bot_bridge(api, loop=None, appid=None, name=None, avatar=""):

    """注册一个 bot 的桥接（多 bot 场景：按 appid 区分）。name / avatar 是从 QQ 端握手（WS HELLO）获得的真实资料，前端优先展示。"""

    global _bot_bridges

    key = appid or "_default"

    _bot_bridges[key] = {

        "api": api,

        "loop": loop,

        "name": name or "",

        "avatar": avatar or "",

        "appid": key,

        "ts": time.time(),

    }

    # 持久化桥接缓存，供下次启动早期 resolve_bot_key 使用
    try:
        _save_bridge_cache()
    except Exception:
        pass

    return True

def unregister_bot_bridge(appid):
    """热重载时调用：清掉指定 appid 的桥接与持久化缓存（_default 桥接保留）。"""
    global _bot_bridges
    key = str(appid or "")
    if not key or key == "_default":
        return False
    _bot_bridges.pop(key, None)
    try:
        _save_bridge_cache()
    except Exception:
        pass
    return True

def get_bridge(appid=None):

    """取指定 bot 的桥接；未指定或不存在时返回首个已就绪的桥接。"""

    if appid and appid in _bot_bridges:

        return _bot_bridges[appid]

    for b in _bot_bridges.values():

        if b.get("api") is not None:

            return b

    for b in _bot_bridges.values():

        return b

    return None

def get_bridge_for_chat(chat_id):

    """根据 chat_id(g:群/u:用户) 解析所属 bot 的桥接，失败回退首个就绪桥接。"""

    cid = str(chat_id or "")

    appid = None

    if cid.startswith("g:"):

        appid = GROUP_BOT_MAP.get(cid[2:])

    elif cid.startswith("u:"):

        appid = USER_BOT_MAP.get(cid[2:])

    return get_bridge(appid)

# ------------------------------------------------------------

# 控制台发消息（实时监控页：文本/表情/图片/语音/视频）

# ------------------------------------------------------------

_MEDIA_EXT = {"image": "png", "voice": "mp3", "video": "mp4"}

_ALLOWED_MEDIA_EXT = {

    "png", "jpg", "jpeg", "gif", "webp", "bmp",

    "mp3", "wav", "m4a", "amr", "silk", "ogg",

    "mp4", "webm", "mov",

}

def _media_ext(msg_type):

    return _MEDIA_EXT.get(msg_type, "bin")

def _safe_ext(ext):

    return ext in _ALLOWED_MEDIA_EXT

def _rand_hex(n=6):

    try:

        return os.urandom(n).hex()

    except Exception:

        return str(int(time.time() * 1000))

def _save_media_file(data, ext):

    """把控制台发出的富媒体保存到 admin/media，返回可经静态服务访问的相对 URL。"""

    bot_dir = os.path.dirname(os.path.abspath(__file__))

    media_dir = os.path.join(bot_dir, "admin", "media")

    os.makedirs(media_dir, exist_ok=True)

    fname = "msg_%d_%s.%s" % (int(time.time() * 1000), _rand_hex(6), ext)

    fpath = os.path.normpath(os.path.join(media_dir, fname))

    if not fpath.startswith(media_dir):

        raise ValueError("非法文件名")

    with open(fpath, "wb") as f:

        f.write(data)

    return "/admin/media/" + fname

async def _async_send_console_message(chat_id, msg_type, content, file_bytes):

    """在机器人事件循环中发送一条控制台消息，返回 (ok, error)。"""

    bridge = get_bridge_for_chat(chat_id)

    if not bridge or not bridge.get("api"):

        return (False, "机器人未就绪，无法发送")

    api = bridge["api"]

    from modules.common import (

        parse_chat_id, ChatScene, send_text, send_local_image_for_scene,

    )

    scene, target_id = parse_chat_id(chat_id)

    try:

        if msg_type in ("text", "emoji"):

            await send_text(api, scene, target_id, content or "")

            return (True, None)

        if msg_type == "image":

            if not file_bytes:

                return (False, "缺少图片数据")

            await send_local_image_for_scene(api, scene, target_id, file_bytes)

            return (True, None)

        return (False, "未知消息类型: %s" % msg_type)

    except Exception as e:

        return (False, str(e))

def _send_console_message(chat_id, msg_type, content, file_bytes):

    """线程安全包装：通过机器人事件循环发送消息并阻塞至完成。"""

    bridge = get_bridge_for_chat(chat_id)

    if not bridge or not bridge.get("api"):

        return (False, "机器人未就绪，无法发送")

    loop = bridge.get("loop")

    if loop is None or not loop.is_running():

        return (False, "机器人事件循环不可用")

    try:

        coro = _async_send_console_message(chat_id, msg_type, content, file_bytes)

        future = asyncio.run_coroutine_threadsafe(coro, loop)

        return future.result(timeout=120)

    except Exception as e:

        return (False, str(e))

def _push_announcement(targets, text):

    """把公告批量推送到指定受众（chat_id 列表）。返回 (成功列表, 失败列表)。

    每个 target 形如 "g:群openid" / "u:用户openid"；逐条通过机器人事件循环发送，

    单条失败不影响其它目标。整批操作在后台线程阻塞执行（HTTP 请求线程内），

    由 send_text 内部自己处理被动/主动消息重试。

    """

    ok_list = []

    fail_list = []

    for chat_id in targets:

        chat_id = str(chat_id or "").strip()

        if not chat_id or ":" not in chat_id:

            fail_list.append({"chat_id": chat_id, "error": "格式错误"})

            continue

        ok, err = _send_console_message(chat_id, "text", text, None)

        if ok:

            ok_list.append(chat_id)

        else:

            fail_list.append({"chat_id": chat_id, "error": err or "发送失败"})

    return ok_list, fail_list

# ------------------------------------------------------------
# 群基本信息（QQ 官方 GET /v2/groups/{group_openid}/info）
# ------------------------------------------------------------
# 频率限制：官方 30 QPM（按机器人 appid 独立计数）。
# 缓存：内存 + data/group_info_cache.json，默认 TTL 24 小时。
# 控制台可经 /api/group/official-info?refresh=1 强制刷新单个群，
# 或 /api/group/refresh-all 批量刷新所有已知群。
_GROUP_INFO_TTL = 86400.0        # 24 小时
_QPM_LIMIT = 30
_QPM_WINDOW = 60.0               # 1 分钟
_GROUP_INFO_CACHE_FILE = os.path.join(_DATA_ROOT_DIR, "group_info_cache.json")
_group_info_cache = {}           # openid -> {"data": dict, "ts": float, "appid": str}
_group_info_lock = threading.Lock()
_qpm_log = {}                    # appid -> deque[float]（每机器人独立 QPM 桶）


def _load_group_info_cache():
    global _group_info_cache
    _group_info_cache = _load_json_safe(_GROUP_INFO_CACHE_FILE) or {}
    if not isinstance(_group_info_cache, dict):
        _group_info_cache = {}


def _save_group_info_cache():
    try:
        if not os.path.isdir(_DATA_ROOT_DIR):
            os.makedirs(_DATA_ROOT_DIR, exist_ok=True)
        _atomic_save_json(_GROUP_INFO_CACHE_FILE, _group_info_cache, indent=2)
    except Exception as e:
        print("[console_server] save group_info_cache failed: %s" % e, flush=True)


def _qpm_acquire(appid, kind=None, limit=None):
    """QPM 令牌桶：返回 True=放行；False=已超。默认 30 QPM；kind 用于按端点分桶，limit 自定义上限（如审批 60 QPM）。"""
    now = time.time()
    _key = (appid or "default") + (("_" + kind) if kind else "")
    bucket = _qpm_log.setdefault(_key, deque())
    while bucket and now - bucket[0] > _QPM_WINDOW:
        bucket.popleft()
    _cap = limit if limit is not None else _QPM_LIMIT
    if len(bucket) >= _cap:
        return False
    bucket.append(now)
    return True


async def _async_fetch_group_info_via_qq(api, group_openid):
    """调官方 GET /v2/groups/{group_openid}/info，返回原始 dict 或抛异常。"""
    from botpy.http import Route
    route = Route("GET", "/v2/groups/{group_openid}/info", group_openid=group_openid)
    result = await api._http.request(route)
    return result if isinstance(result, dict) else {}


def _normalize_group_info(raw):
    """把官方返回的多种命名归一化到稳定字段，原始 dict 保留在 raw。"""
    def _first(*keys):
        for k in keys:
            v = raw.get(k)
            if v not in (None, "", 0):
                return v
        return None
    name = _first("group_name", "name", "groupName") or ""
    group_id = _first("group_id", "groupId", "group_code", "groupCode") or ""
    member_count = _first("group_member_num", "member_count", "memberCount", "member_num") or 0
    max_member_count = _first("max_member_count", "maxMemberCount", "max_member_num") or 0
    owner_openid = _first("owner_id", "owner_openid", "ownerOpenid", "owner") or ""
    try:
        member_count = int(member_count) if member_count else 0
    except Exception:
        member_count = 0
    try:
        max_member_count = int(max_member_count) if max_member_count else 0
    except Exception:
        max_member_count = 0

    # 群简介 / 群分类 / 群标签（QQ 官方接口原生字段）
    description = str(_first("group_finger_memo", "finger_memo", "description") or "").strip()
    category = str(_first("group_class_text", "class_text", "category") or "").strip()
    _tags_raw = raw.get("group_tags", raw.get("tags", []))
    if isinstance(_tags_raw, list):
        tags = [str(t).strip() for t in _tags_raw if t not in (None, "")]
    elif isinstance(_tags_raw, str):
        tags = [t.strip() for t in _tags_raw.replace("\\u0014", "\\n").split("\n") if t.strip()]
        if not tags:
            tags = [t.strip() for t in _tags_raw.split(",") if t.strip()]
    else:
        tags = []

    return {
        "name": str(name),
        "group_id": str(group_id),
        "member_count": member_count,
        "max_member_count": max_member_count,
        "owner_openid": str(owner_openid),
        "description": description,
        "category": category,
        "tags": tags,
        "raw": raw,
    }


def _fetch_group_info_via_qq_sync(openid, appid=None, force_refresh=False):
    """同步包装：缓存命中直接返回；过期或强制刷新则通过 bridge 调官方 /info。
    返回 (ok: bool, payload: dict)。payload 形如：
      {"cached": True, "expires_in": 12345, "name":..., "member_count":..., "raw": {...}}
    失败时 payload 是 {"error": "..."}。
    """
    openid = str(openid or "").strip()
    if not openid:
        return False, {"error": "openid 不能为空"}
    now = time.time()
    # 1) 缓存命中
    if not force_refresh:
        with _group_info_lock:
            entry = _group_info_cache.get(openid)
        if entry and (now - entry.get("ts", 0)) < _GROUP_INFO_TTL:
            data = entry.get("data") or {}
            return True, {
                "cached": True,
                "expires_in": int(_GROUP_INFO_TTL - (now - entry["ts"])),
                **data,
            }
    # 2) 取桥接
    bridge = get_bridge(appid) if appid else None
    if bridge is None:
        bridge = get_bridge_for_chat("g:" + openid)
    if bridge is None:
        bridge = get_bridge()
    if not bridge or not bridge.get("api"):
        return False, {"error": "机器人桥接不可用"}
    api = bridge["api"]
    loop = bridge.get("loop")
    if loop is None or not loop.is_running():
        return False, {"error": "机器人事件循环不可用"}
    bot_appid = str(bridge.get("appid") or appid or "default")
    # 3) 限流
    if not _qpm_acquire(bot_appid):
        return False, {"error": "频率限制：超过 30 QPM，请稍后再试"}
    # 4) 提交到机器人事件循环
    try:
        future = asyncio.run_coroutine_threadsafe(_async_fetch_group_info_via_qq(api, openid), loop)
        raw = future.result(timeout=15)
    except Exception as e:
        return False, {"error": "官方 /info 拉取失败：%s" % e}
    if not isinstance(raw, dict):
        return False, {"error": "官方 /info 返回非 dict：%r" % (raw,)}
    # 5) 解析 + 落缓存
    data = _normalize_group_info(raw)
    with _group_info_lock:
        _group_info_cache[openid] = {"data": data, "ts": now, "appid": bot_appid}
    _save_group_info_cache()
    return True, {
        "cached": False,
        "expires_in": int(_GROUP_INFO_TTL),
        **data,
    }

def _parse_rfc3339_to_ms(s):
    """RFC3339 / ISO-8601 时间字符串 → 毫秒时间戳。失败返回 0。
    支持尾部 'Z'（UTC），其他时区 '+HH:MM' / '-HH:MM' 由 fromisoformat 直接解析。"""
    if not s:
        return 0
    s = str(s).strip()
    if not s:
        return 0
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        _dt_obj = datetime.fromisoformat(s)
        return int(_dt_obj.timestamp() * 1000)
    except Exception:
        return 0


def _normalize_join_request_item(raw):
    """把 QQ 官方 JoinRequest 原始字段归一化（按官方 API 文档）。
    官方字段：join_request_id / risk_tips / union_openid / member_openid / username /
             apply_at(RFC3339) / apply_source(self_apply|invited) / invited_by / bot /
             verify_info{method,verify_message,review_qa_list[]}
    同时提供前端友好别名：display_name(=username) / message(=verify_message or risk_tips)
                       / apply_time_ms(apply_at 转毫秒)
    """
    if not isinstance(raw, dict):
        return None
    def _first(*keys):
        for k in keys:
            v = raw.get(k)
            if v not in (None, ""):
                return v
        return None
    join_request_id = str(_first("join_request_id", "joinRequestId", "request_id") or "").strip()
    member_openid = str(_first("member_openid", "memberOpenid", "openid") or "").strip()
    username = str(_first("username", "nickname", "nick") or "").strip()
    risk_tips = str(_first("risk_tips", "riskTips") or "").strip()
    union_openid = str(_first("union_openid", "unionOpenid") or "").strip()
    apply_at = str(_first("apply_at", "applyAt") or "").strip()
    apply_source = str(_first("apply_source", "applySource") or "").strip()
    invited_by = str(_first("invited_by", "invitedBy") or "").strip()
    _bot_raw = _first("bot", False)
    if isinstance(_bot_raw, bool):
        bot = _bot_raw
    else:
        bot = str(_bot_raw).strip().lower() in ("1", "true", "yes")
    # verify_info 嵌套对象（官方：VerifyInfo）
    vi_raw = raw.get("verify_info") or raw.get("verifyInfo") or {}
    vi = vi_raw if isinstance(vi_raw, dict) else {}
    verify_method = str(vi.get("method") or vi.get("auth_type") or vi.get("authType") or "").strip()
    verify_message = str(vi.get("verify_message") or vi.get("verifyMessage") or "").strip()
    qa_list = vi.get("review_qa_list") or vi.get("reviewQaList") or []
    qa_items = []
    if isinstance(qa_list, list):
        for q in qa_list:
            if isinstance(q, dict):
                qa_items.append({
                    "question": str(q.get("question") or "").strip(),
                    "answer": str(q.get("answer") or "").strip(),
                })
    apply_time_ms = _parse_rfc3339_to_ms(apply_at)
    return {
        # 官方字段（透传）
        "join_request_id": join_request_id,
        "member_openid": member_openid,
        "username": username,
        "risk_tips": risk_tips,
        "union_openid": union_openid,
        "apply_at": apply_at,
        "apply_source": apply_source,
        "invited_by": invited_by,
        "bot": bot,
        "verify_info": {
            "method": verify_method,
            "verify_message": verify_message,
            "review_qa_list": qa_items,
        },
        # 前端友好别名（向后兼容 + 减少重复解析）
        "display_name": username,
        "message": verify_message or risk_tips,
        "apply_time_ms": apply_time_ms,
        # 兼容老调用：time / nickname / avatar（avatar 不存在，置空）
        "time": apply_time_ms,
        "nickname": username,
        "avatar": "",
        "raw": raw,
    }


def _normalize_join_request_list(raw):
    if not isinstance(raw, dict):
        raw = {}
    # 官方响应：{"list": [...JoinRequest], "next_cursor": "..."}
    _items_raw = raw.get("list") or raw.get("join_requests") or raw.get("join_request_list") or raw.get("items") or raw.get("data") or []
    if not isinstance(_items_raw, list):
        _items_raw = []
    items = []
    for _x in _items_raw:
        n = _normalize_join_request_item(_x)
        if n:
            items.append(n)
    next_cursor = raw.get("next_cursor") or raw.get("cursor") or raw.get("nextCursor") or ""
    return {"items": items, "next_cursor": str(next_cursor), "raw": raw}


async def _async_fetch_join_requests(api, group_openid, cursor, limit):
    from botpy.http import Route
    route = Route("GET", "/v2/groups/{group_openid}/join_request_list", group_openid=group_openid)
    _params = {}
    if cursor:
        _params["cursor"] = str(cursor)
    try:
        _lim = int(limit) if limit else 20
    except Exception:
        _lim = 20
    if _lim > 100:
        _lim = 100
    if _lim < 1:
        _lim = 1
    _params["limit"] = _lim
    result = await api._http.request(route, params=_params)
    return result if isinstance(result, dict) else {}


async def _async_approval_join_request(api, group_openid, member_openid, action, reason, join_request_id=""):
    from botpy.http import Route
    # 官方：POST /v2/groups/{group_openid}/approval_join_request/{member_openid}
    # body：{"op": "approve"|"decline", "join_request_id": "...", "reject_reason"?: "..."}
    route = Route("POST", "/v2/groups/{group_openid}/approval_join_request/{member_openid}",
                  group_openid=group_openid, member_openid=member_openid)
    _op = str(action or "approve").strip().lower()
    if _op not in ("approve", "decline"):
        _op = "approve"
    _body = {"op": _op}
    if join_request_id:
        _body["join_request_id"] = str(join_request_id).strip()
    if reason:
        _body["reject_reason"] = str(reason)
    result = await api._http.request(route, json=_body)
    return result if isinstance(result, dict) else {}


# ====================== 群成员禁言（QQ 官方 /v2/groups/{openid}/restrict_chat_setting） ======================
# 官方端点：POST /v2/groups/{group_openid}/restrict_chat_setting
# 频限：60 QPM（按官方文档）
# 请求体：{"members": [{"op": "add"/"update"/"del",
#                        "member_openid": "...", "mute_expire_at": "RFC3339"}]}
#   - op=add：增加禁言（必填 mute_expire_at，RFC3339 时间字符串）
#   - op=update：更新到期时间（必填 mute_expire_at）
#   - op=del：解除禁言（mute_expire_at 可为空字符串表示立即解除）
# 限制：单次最多 10 个成员；只能禁言普通成员，不能操作群主/管理员/机器人。
# ----------------------------------------------------------------

def _format_mute_expire_at_rfc3339(seconds):
    """生成 RFC3339 格式的到期时间（本地时区偏移）。"""
    try:
        import datetime as _dt
        dt = _dt.datetime.now().astimezone() + _dt.timedelta(seconds=int(seconds))
        s = dt.strftime("%Y-%m-%dT%H:%M:%S%z")
        # 插入冒号到时区偏移 (e.g. +0800 -> +08:00)
        if len(s) >= 5 and s[-5] in ("+", "-") and s[-3] != ":":
            s = s[:-2] + ":" + s[-2:]
        return s
    except Exception:
        import datetime as _dt
        return (_dt.datetime.utcnow() + _dt.timedelta(seconds=int(seconds))).strftime("%Y-%m-%dT%H:%M:%SZ")


async def _async_set_member_mute(api, group_openid, member_openid, duration_seconds):
    """异步：单个成员下禁言（官方 /restrict_chat_setting）。"""
    try:
        from botpy.http import Route
        expire_at = _format_mute_expire_at_rfc3339(duration_seconds)
        route = Route("POST", "/v2/groups/{group_openid}/restrict_chat_setting",
                      group_openid=group_openid)
        body = {"members": [{"op": "add", "member_openid": member_openid,
                             "mute_expire_at": expire_at}]}
        result = await api._http.request(route, json=body)
        return True, (result if isinstance(result, dict) else {"raw": result})
    except Exception as e:
        return False, {"error": "official restrict_chat_setting exception: %s" % e}


def _mute_member_via_qq_sync(openid, member_openid, duration_seconds, appid=None):
    """同步包装：对单个成员下禁言（60 QPM kind=restrict_chat）。"""
    openid = str(openid or "").strip()
    member_openid = str(member_openid or "").strip()
    if not openid:
        return False, {"error": "openid 不能为空"}
    if not member_openid:
        return False, {"error": "member_openid 不能为空"}
    try:
        duration_seconds = max(1, int(duration_seconds))
    except Exception:
        return False, {"error": "duration 必须为正整数秒"}
    bridge = get_bridge(appid) if appid else None
    if bridge is None:
        bridge = get_bridge_for_chat("g:" + openid)
    if bridge is None:
        bridge = get_bridge()
    if not bridge or not bridge.get("api"):
        return False, {"error": "机器人桥接不可用"}
    api = bridge["api"]
    loop = bridge.get("loop")
    if loop is None or not loop.is_running():
        return False, {"error": "机器人事件循环不可用"}
    bot_appid = str(bridge.get("appid") or appid or "default")
    if not _qpm_acquire(bot_appid, kind="restrict_chat", limit=60):
        return False, {"error": "频率限制：超过 60 QPM，请稍后再试"}
    try:
        future = asyncio.run_coroutine_threadsafe(
            _async_set_member_mute(api, openid, member_openid, duration_seconds), loop
        )
        raw = future.result(timeout=15)
    except Exception as e:
        return False, {"error": "官方 /restrict_chat_setting 调用失败：%s" % e}
    return True, raw if isinstance(raw, dict) else {"raw": raw}


async def _async_unmute_member(api, group_openid, member_openid):
    """异步：解除单个成员禁言（op=del）。"""
    try:
        from botpy.http import Route
        route = Route("POST", "/v2/groups/{group_openid}/restrict_chat_setting",
                      group_openid=group_openid)
        body = {"members": [{"op": "del", "member_openid": member_openid}]}
        result = await api._http.request(route, json=body)
        return True, (result if isinstance(result, dict) else {"raw": result})
    except Exception as e:
        return False, {"error": "official restrict_chat_setting unmute exception: %s" % e}


def _unmute_member_via_qq_sync(openid, member_openid, appid=None):
    """同步包装：解除单个成员禁言（60 QPM kind=restrict_chat）。"""
    openid = str(openid or "").strip()
    member_openid = str(member_openid or "").strip()
    if not openid:
        return False, {"error": "openid 不能为空"}
    if not member_openid:
        return False, {"error": "member_openid 不能为空"}
    bridge = get_bridge(appid) if appid else None
    if bridge is None:
        bridge = get_bridge_for_chat("g:" + openid)
    if bridge is None:
        bridge = get_bridge()
    if not bridge or not bridge.get("api"):
        return False, {"error": "机器人桥接不可用"}
    api = bridge["api"]
    loop = bridge.get("loop")
    if loop is None or not loop.is_running():
        return False, {"error": "机器人事件循环不可用"}
    bot_appid = str(bridge.get("appid") or appid or "default")
    if not _qpm_acquire(bot_appid, kind="restrict_chat", limit=60):
        return False, {"error": "频率限制：超过 60 QPM，请稍后再试"}
    try:
        future = asyncio.run_coroutine_threadsafe(
            _async_unmute_member(api, openid, member_openid), loop
        )
        raw = future.result(timeout=15)
    except Exception as e:
        return False, {"error": "官方 /restrict_chat_setting 解除失败：%s" % e}
    return True, raw if isinstance(raw, dict) else {"raw": raw}


def _get_mute_group_config(openid):
    """读取单群的禁言配置（每群独立）。优先从 modules.group_admin 读取；不可用则读 data/group_admin.json。"""
    openid = str(openid or "").strip()
    try:
        from modules.group_admin import group_admin as _ga
        return {
            "mute_duration": int(_ga.get_mute_duration(openid) or 600),
            "mute_on_banword": bool(_ga.get_mute_on_banword(openid)),
        }
    except Exception:
        pass
    # fallback：直接读 data/group_admin.json
    try:
        path = os.path.join(_DATA_ROOT_DIR, "group_admin.json")
        if os.path.exists(path):
            d = _load_json_safe(path) or {}
            cfg = d.get(openid) or {}
            return {
                "mute_duration": max(1, int(cfg.get("mute_duration", 600) or 600)),
                "mute_on_banword": bool(cfg.get("mute_on_banword", True)),
            }
    except Exception:
        pass
    return {"mute_duration": 600, "mute_on_banword": True}


def _set_mute_group_config(openid, mute_duration=None, mute_on_banword=None):
    """设置单群的禁言配置（每群独立）。优先调 modules.group_admin 的 setter；否则直接改文件。"""
    openid = str(openid or "").strip()
    if not openid:
        return False, {"error": "openid 不能为空"}
    try:
        from modules.group_admin import group_admin as _ga
        changed = False
        if mute_duration is not None:
            try:
                _ga.set_mute_duration(openid, int(mute_duration))
                changed = True
            except Exception as e:
                return False, {"error": "set_mute_duration failed: %s" % e}
        if mute_on_banword is not None:
            try:
                _ga.set_mute_on_banword(openid, bool(mute_on_banword))
                changed = True
            except Exception as e:
                return False, {"error": "set_mute_on_banword failed: %s" % e}
        if not changed:
            return False, {"error": "mute_duration / mute_on_banword 至少提供一个"}
        return True, _get_mute_group_config(openid)
    except Exception:
        pass
    # fallback：直接改文件
    try:
        path = os.path.join(_DATA_ROOT_DIR, "group_admin.json")
        if os.path.exists(path):
            d = _load_json_safe(path) or {}
        else:
            d = {}
        cfg = d.setdefault(openid, {"banned_words": []})
        if mute_duration is not None:
            try:
                cfg["mute_duration"] = max(1, int(mute_duration))
            except Exception:
                return False, {"error": "mute_duration 必须为正整数秒"}
        if mute_on_banword is not None:
            cfg["mute_on_banword"] = bool(mute_on_banword)
        if not os.path.isdir(_DATA_ROOT_DIR):
            os.makedirs(_DATA_ROOT_DIR, exist_ok=True)
        _atomic_save_json(path, d, indent=2)
        return True, _get_mute_group_config(openid)
    except Exception as e:
        return False, {"error": "设置禁言配置失败：%s" % e}

def _get_banned_mute_config(openid):
    """读取单群的违禁词 + 禁言配置（每群独立）。优先从 modules.group_admin 读取。"""
    openid = str(openid or "").strip()
    try:
        from modules.group_admin import group_admin as _ga
        return {
            "banned_words": list(_ga.get_banned_words(openid) or []),
            "mute_duration": int(_ga.get_mute_duration(openid) or 600),
            "mute_on_banword": bool(_ga.get_mute_on_banword(openid)),
        }
    except Exception:
        pass
    try:
        path = os.path.join(_DATA_ROOT_DIR, "group_admin.json")
        if os.path.exists(path):
            d = _load_json_safe(path) or {}
            cfg = d.get(openid) or {}
            return {
                "banned_words": list(cfg.get("banned_words", []) or []),
                "mute_duration": max(1, int(cfg.get("mute_duration", 600) or 600)),
                "mute_on_banword": bool(cfg.get("mute_on_banword", True)),
            }
    except Exception:
        pass
    return {"banned_words": [], "mute_duration": 600, "mute_on_banword": True}


def _set_banned_mute_config(openid, banned_words=None, mute_duration=None, mute_on_banword=None):
    """设置单群的违禁词 + 禁言配置（每群独立）。优先调 modules.group_admin 的 setter。"""
    openid = str(openid or "").strip()
    if not openid:
        return False, {"error": "openid 不能为空"}
    try:
        from modules.group_admin import group_admin as _ga
        changed = False
        if banned_words is not None:
            try:
                _ga.set_banned_words(openid, list(banned_words))
                changed = True
            except Exception as e:
                return False, {"error": "set_banned_words failed: %s" % e}
        if mute_duration is not None:
            try:
                _ga.set_mute_duration(openid, int(mute_duration))
                changed = True
            except Exception as e:
                return False, {"error": "set_mute_duration failed: %s" % e}
        if mute_on_banword is not None:
            try:
                _ga.set_mute_on_banword(openid, bool(mute_on_banword))
                changed = True
            except Exception as e:
                return False, {"error": "set_mute_on_banword failed: %s" % e}
        if not changed:
            return False, {"error": "banned_words / mute_duration / mute_on_banword 至少提供一个"}
        return True, _get_banned_mute_config(openid)
    except Exception:
        pass
    try:
        path = os.path.join(_DATA_ROOT_DIR, "group_admin.json")
        if os.path.exists(path):
            d = _load_json_safe(path) or {}
        else:
            d = {}
        cfg = d.setdefault(openid, {"banned_words": []})
        if banned_words is not None:
            cfg["banned_words"] = [w.strip() for w in (banned_words or []) if w and w.strip()]
        if mute_duration is not None:
            try:
                cfg["mute_duration"] = max(1, int(mute_duration))
            except Exception:
                return False, {"error": "mute_duration 必须为正整数秒"}
        if mute_on_banword is not None:
            cfg["mute_on_banword"] = bool(mute_on_banword)
        if not os.path.isdir(_DATA_ROOT_DIR):
            os.makedirs(_DATA_ROOT_DIR, exist_ok=True)
        _atomic_save_json(path, d, indent=2)
        return True, _get_banned_mute_config(openid)
    except Exception as e:
        return False, {"error": "设置配置失败：%s" % e}


def _get_banword_log(openid=None, limit=200):
    """读取违禁词拦截日志（本地 data/banword_log.json），返回 list，最新在前。"""
    try:
        _path = os.path.join(_DATA_ROOT_DIR, "banword_log.json")
        if not os.path.exists(_path):
            return []
        with open(_path, "r", encoding="utf-8") as f:
            _logs = _json.load(f) or []
        if not isinstance(_logs, list):
            return []
        if openid:
            _logs = [x for x in _logs if str(x.get("group_openid") or "") == str(openid)]
        if limit and limit > 0:
            _logs = _logs[:limit]
        return _logs
    except Exception as _e:
        logger.warning("读取违禁词拦截日志失败: %s" % _e)
        return []


def _clear_banword_log(openid=None):
    """清空违禁词拦截日志；openid 提供时仅清空该群。返回被删除条数。"""
    try:
        _path = os.path.join(_DATA_ROOT_DIR, "banword_log.json")
        if not os.path.exists(_path):
            return 0
        if not openid:
            try:
                with open(_path, "r", encoding="utf-8") as f:
                    _logs = _json.load(f) or []
                _cnt = len(_logs) if isinstance(_logs, list) else 0
            except Exception:
                _cnt = 0
            try:
                os.remove(_path)
            except Exception:
                pass
            return _cnt
        with open(_path, "r", encoding="utf-8") as f:
            _logs = _json.load(f) or []
        if not isinstance(_logs, list):
            _logs = []
        _before = len(_logs)
        _logs = [x for x in _logs if str(x.get("group_openid") or "") != str(openid)]
        with open(_path, "w", encoding="utf-8") as f:
            _json.dump(_logs, f, ensure_ascii=False, indent=2)
        return _before - len(_logs)
    except Exception as _e:
        logger.warning("清空违禁词拦截日志失败: %s" % _e)
        return 0


def _fetch_join_requests_via_qq_sync(openid, appid=None, cursor="", limit=20):
    """拉入群申请列表（30 QPM，kind=jr_list 分桶）。"""
    openid = str(openid or "").strip()
    if not openid:
        return False, {"error": "openid 不能为空"}
    bridge = get_bridge(appid) if appid else None
    if bridge is None:
        bridge = get_bridge_for_chat("g:" + openid)
    if bridge is None:
        bridge = get_bridge()
    if not bridge or not bridge.get("api"):
        return False, {"error": "机器人桥接不可用"}
    api = bridge["api"]
    loop = bridge.get("loop")
    if loop is None or not loop.is_running():
        return False, {"error": "机器人事件循环不可用"}
    bot_appid = str(bridge.get("appid") or appid or "default")
    if not _qpm_acquire(bot_appid, kind="jr_list"):
        return False, {"error": "频率限制：超过 30 QPM，请稍后再试"}
    try:
        future = asyncio.run_coroutine_threadsafe(
            _async_fetch_join_requests(api, openid, cursor, limit), loop
        )
        raw = future.result(timeout=15)
    except Exception as e:
        return False, {"error": "官方 /join_request_list 拉取失败：%s" % e}
    if not isinstance(raw, dict):
        return False, {"error": "官方 /join_request_list 返回非 dict：%r" % (raw,)}
    norm = _normalize_join_request_list(raw)
    return True, norm


def _approval_join_request_via_qq_sync(openid, member_openid, action, reason, join_request_id="", appid=None):
    """审批入群申请（60 QPM，kind=jr_approval 分桶）。"""
    openid = str(openid or "").strip()
    member_openid = str(member_openid or "").strip()
    action = str(action or "").strip().lower()
    if not openid:
        return False, {"error": "openid 不能为空"}
    if not member_openid:
        return False, {"error": "member_openid 不能为空"}
    if action not in ("approve", "decline"):
        return False, {"error": "action 必须为 approve 或 decline"}
    bridge = get_bridge(appid) if appid else None
    if bridge is None:
        bridge = get_bridge_for_chat("g:" + openid)
    if bridge is None:
        bridge = get_bridge()
    if not bridge or not bridge.get("api"):
        return False, {"error": "机器人桥接不可用"}
    api = bridge["api"]
    loop = bridge.get("loop")
    if loop is None or not loop.is_running():
        return False, {"error": "机器人事件循环不可用"}
    bot_appid = str(bridge.get("appid") or appid or "default")
    if not _qpm_acquire(bot_appid, kind="jr_approval", limit=60):
        return False, {"error": "频率限制：超过 60 QPM，请稍后再试"}
    try:
        future = asyncio.run_coroutine_threadsafe(
            _async_approval_join_request(api, openid, member_openid, action, reason, join_request_id=join_request_id), loop
        )
        raw = future.result(timeout=15)
    except Exception as e:
        return False, {"error": "官方 /approval_join_request 调用失败：%s" % e}
    return True, {"data": raw if isinstance(raw, dict) else {}, "action": action}

# ------------------------------------------------------------
# 入群自动审批策略（bot 级：每个机器人最多 20 个策略，单策略最多关联 100 个群）
# 官方 v2 OpenAPI（botpy SDK 语义：策略为 bot 级，group_openids/group_ids 在 body 传入）：
#   POST   /v2/groups/join_approval_strategy                       创建
#   GET    /v2/groups/join_approval_strategy                       列表（支持 cursor/limit 分页）
#   PATCH  /v2/groups/join_approval_strategy/{strategy_id}         修改（is_enable/expire_at/group_action/remark）
#   DELETE /v2/groups/join_approval_strategy/{strategy_id}         删除
#   POST   /v2/groups/join_approval_strategy/{strategy_id}/execute 执行
#   POST   /v2/groups/join_approval_strategy/{strategy_id}/whitelist_users  增删白名单(op: add/delete, body: {op, whitelist_users[]})
# 注意：官方不提供 GET 白名单列表接口；只能拿到 whitelist_user_count 计数。
# 说明：控制台未实现 PATCH/DELETE 方法路由，统一用 POST + /update、/delete 子路径代替。
# 频率：官方未单列，统一按 60 QPM 分桶（kind=jas）。
# ------------------------------------------------------------

_JAS = "/api/group/join-approval/strategies"
_JAS_QPM_LIMIT = 60


def _normalize_join_approval_strategy(raw):
    if not isinstance(raw, dict):
        return {}
    def _first(*keys):
        for k in keys:
            v = raw.get(k)
            if v not in (None, ""):
                return v
        return None
    strategy_id = str(_first("strategy_id") or "")
    remark = str(_first("remark") or "")
    is_enable = str(_first("is_enable") or "off")
    group_openids = _first("group_openids", "group_list", "group_ids") or []
    if not isinstance(group_openids, list):
        group_openids = []
    created_at = _first("created_at", "create_time", "updated_at") or 0
    whitelist_user_count = _first(
        "whitelist_user_count", "total_whitelist", "whitelist_count", "whitelist_total"
    ) or 0
    try:
        whitelist_user_count = int(whitelist_user_count)
    except Exception:
        whitelist_user_count = 0
    expire_at = str(_first("expire_at") or "")
    updated_at = str(_first("updated_at") or "")
    return {
        "strategy_id": strategy_id,
        "remark": remark,
        "is_enable": is_enable,
        "group_openids": [str(x) for x in group_openids],
        "created_at": created_at,
        "expire_at": expire_at,
        "updated_at": updated_at,
        "whitelist_user_count": whitelist_user_count,
        "raw": raw,
    }


def _normalize_join_approval_strategy_list(raw):
    if not isinstance(raw, dict):
        raw = {}
    _items = raw.get("strategies") or raw.get("strategy_list") or raw.get("items") or raw.get("data") or []
    if not isinstance(_items, list):
        _items = []
    items = []
    for _x in _items:
        n = _normalize_join_approval_strategy(_x)
        if n.get("strategy_id"):
            items.append(n)
    next_cursor = raw.get("next_cursor") or raw.get("cursor") or ""
    total = raw.get("total", len(items))
    try:
        total = int(total)
    except Exception:
        total = len(items)
    return {"items": items, "next_cursor": str(next_cursor), "total": total, "raw": raw}


async def _async_create_join_approval_strategy(api, group_openids, group_ids, is_enable, remark):
    from botpy.http import Route
    route = Route("POST", "/v2/groups/join_approval_strategy")
    _body = {}
    if group_openids:
        _body["group_openids"] = [str(x) for x in group_openids]
    elif group_ids:
        _body["group_ids"] = [str(x) for x in group_ids]
    else:
        raise ValueError("group_openids 与 group_ids 至少提供一个")
    _body["is_enable"] = str(is_enable or "on").strip()
    if remark:
        _body["remark"] = str(remark)
    result = await api._http.request(route, json=_body)
    return result if isinstance(result, dict) else {}


async def _async_list_join_approval_strategies(api, limit, cursor):
    from botpy.http import Route
    route = Route("GET", "/v2/groups/join_approval_strategy")
    _params = {}
    try:
        _lim = int(limit) if limit else 20
    except Exception:
        _lim = 20
    if _lim > 100:
        _lim = 100
    if _lim < 1:
        _lim = 1
    _params["limit"] = _lim
    if cursor:
        _params["cursor"] = str(cursor)
    result = await api._http.request(route, params=_params)
    return result if isinstance(result, dict) else {}


async def _async_update_join_approval_strategy(api, strategy_id, is_enable, remark):
    from botpy.http import Route
    route = Route("PATCH", "/v2/groups/join_approval_strategy/{strategy_id}", strategy_id=str(strategy_id))
    _body = {}
    if is_enable is not None:
        _body["is_enable"] = str(is_enable).strip()
    if remark is not None:
        _body["remark"] = str(remark)
    result = await api._http.request(route, json=_body)
    return result if isinstance(result, dict) else {}


async def _async_delete_join_approval_strategy(api, strategy_id):
    from botpy.http import Route
    route = Route("DELETE", "/v2/groups/join_approval_strategy/{strategy_id}", strategy_id=str(strategy_id))
    result = await api._http.request(route)
    return result if isinstance(result, dict) else {}


async def _async_execute_join_approval_strategy(api, strategy_id):
    from botpy.http import Route
    route = Route("POST", "/v2/groups/join_approval_strategy/{strategy_id}/execute", strategy_id=str(strategy_id))
    result = await api._http.request(route, json={})
    return result if isinstance(result, dict) else {}


async def _async_update_whitelist(api, strategy_id, op, whitelist_users):
    from botpy.http import Route
    route = Route("POST", "/v2/groups/join_approval_strategy/{strategy_id}/whitelist_users", strategy_id=str(strategy_id))
    _body = {"op": str(op or "add").strip()}
    _users = []
    if isinstance(whitelist_users, list):
        _users = [str(x) for x in whitelist_users]
    elif isinstance(whitelist_users, str):
        _users = [x.strip() for x in whitelist_users.replace("\n", ",").replace(" ", ",").split(",") if x.strip()]
    _body["whitelist_users"] = _users
    result = await api._http.request(route, json=_body)
    return result if isinstance(result, dict) else {}


def _run_jas_coroutine(coro_factory, appid=None):
    """通用：取桥接并在 bot 事件循环内执行入群审批策略相关协程。返回 (ok, payload)。"""
    bridge = get_bridge(appid) if appid else get_bridge()
    if not bridge or not bridge.get("api"):
        return False, {"error": "机器人桥接不可用"}
    api = bridge["api"]
    loop = bridge.get("loop")
    if loop is None or not loop.is_running():
        return False, {"error": "机器人事件循环不可用"}
    bot_appid = str(bridge.get("appid") or appid or "default")
    if not _qpm_acquire(bot_appid, kind="jas", limit=_JAS_QPM_LIMIT):
        return False, {"error": "频率限制：超过 %d QPM，请稍后再试" % _JAS_QPM_LIMIT}
    try:
        future = asyncio.run_coroutine_threadsafe(coro_factory(api), loop)
        raw = future.result(timeout=20)
    except Exception as e:
        return False, {"error": "官方接口调用失败：%s" % e}
    return True, (raw if isinstance(raw, dict) else {})


def _jas_sid_from_path(path, suffix):
    pre = _JAS + "/"
    if not (path.startswith(pre) and path.endswith(suffix)):
        return None
    sid = path[len(pre):-len(suffix)]
    return sid if sid and "/" not in sid else None


def _create_join_approval_strategy_via_qq_sync(group_openids, group_ids, is_enable, remark, appid=None):
    if not group_openids and not group_ids:
        return False, {"error": "group_openids 与 group_ids 至少提供一个"}
    return _run_jas_coroutine(
        lambda api: _async_create_join_approval_strategy(api, group_openids, group_ids, is_enable, remark),
        appid=appid,
    )


def _list_join_approval_strategies_via_qq_sync(appid=None, limit=20, cursor=""):
    ok, raw = _run_jas_coroutine(lambda api: _async_list_join_approval_strategies(api, limit, cursor), appid=appid)
    if not ok:
        return ok, raw
    return True, _normalize_join_approval_strategy_list(raw)


def _update_join_approval_strategy_via_qq_sync(strategy_id, is_enable=None, remark=None, appid=None):
    return _run_jas_coroutine(
        lambda api: _async_update_join_approval_strategy(api, strategy_id, is_enable, remark),
        appid=appid,
    )


def _delete_join_approval_strategy_via_qq_sync(strategy_id, appid=None):
    return _run_jas_coroutine(
        lambda api: _async_delete_join_approval_strategy(api, strategy_id),
        appid=appid,
    )


def _execute_join_approval_strategy_via_qq_sync(strategy_id, appid=None):
    return _run_jas_coroutine(
        lambda api: _async_execute_join_approval_strategy(api, strategy_id),
        appid=appid,
    )


def _update_join_approval_whitelist_via_qq_sync(strategy_id, op, whitelist_users, appid=None):
    return _run_jas_coroutine(
        lambda api: _async_update_whitelist(api, strategy_id, op, whitelist_users),
        appid=appid,
    )

# 入群申请列表：仅返回机器人是群管理员的群。
# 判定来源：官方 `GET /v2/groups/{openid}/bot_state` -> member_role。
#   member_role 取值：member / owner / admin；
#   admin 与 owner 都视为「可审批入群申请」，归入下拉。
#   缓存每群 10 分钟，避免每次进入页面都逐群探测；探测失败按不可判定处理、不误判。
_JR_ADMIN_TTL = 600
_jr_admin_cache = {}

def _all_group_openids():
    """聚合所有出现过的群 openid（与 /api/groups 对齐）。

    来源（按覆盖度优先级合并）：
      1. GROUP_BOT_MAP：用户在「群聊管理 → 群机器人映射」手动配置的群（持久化于 data/group_bot_map.json）
      2. _group_profiles：机器人已写过该群资料
      3. _group_qq_bindings：原神 / 星铁绑定表中曾出现过的群
      4. _members (C2C 用户) 中每个用户的 groups 字段
      5. _group_names：事件中见过的群
    即便某些群从来没有活动消息也能被探测到。
    """
    _gids = set()
    try:
        _gids.update(GROUP_BOT_MAP.keys())
    except Exception:
        pass
    try:
        _gids.update(_group_profiles.keys())
    except Exception:
        pass
    try:
        _gids.update(_group_qq_bindings.keys())
    except Exception:
        pass
    with _admin_api_lock:
        _ms = list(_members.values())
    for _m in _ms:
        for _g in (_m.get("groups") or []):
            if _g and _g != "-":
                _gids.add(_g)
    try:
        _gids.update(_group_names.keys())
    except Exception:
        pass
    return sorted(_gids)


def _group_display_name(gid):
    _prof = _group_profiles.get(gid) or {}
    _custom = (str(_prof.get("name") or "").strip())
    _e = _group_info_cache.get(gid) or {}
    _off = ""
    if _e.get("ts") and (time.time() - _e.get("ts", 0)) < _GROUP_INFO_TTL:
        _off = str((_e.get("data") or {}).get("name", "") or "").strip()
    return _off or _custom or (("群 " + gid[-4:]) if len(gid) >= 4 else gid)


async def _async_fetch_bot_state(api, group_openid):
    """调用官方 `GET /v2/groups/{openid}/bot_state`。

    返回 raw dict；由调用方在 botpy 的事件循环内执行。
    """
    _route = Route("GET", "/v2/groups/{group_openid}/bot_state", group_openid=group_openid)
    return await api._http.request(_route, params={})


def _normalize_bot_state(raw):
    """从官方响应中抽取 member_role；返回 str，取值 member/owner/admin 或 ''（无法判断）。"""
    if not isinstance(raw, dict):
        return ""
    # 官方外层结构有时是 {member_openid, joined_at, allow_proactive_msg, recv_msg_setting, member_role}
    # 有时包在 data 字段下
    _obj = raw
    for _k in ("data",):
        _inner = raw.get(_k)
        if isinstance(_inner, dict) and ("member_role" in _inner or "member_openid" in _inner):
            _obj = _inner
            break
    _role = str(_obj.get("member_role") or "").strip().lower()
    return _role


def _fetch_bot_state_via_qq_sync(group_openid, appid=None):
    """同步包装：跨线程调用 botpy 的 bot_state。结果 (ok, role_str_or_error, denied)。

    role 取值：'member' / 'owner' / 'admin' / '' (官方未返回 / 非成员 code!=0)。
    denied：True 表示官方返回接口无权限（11253 白名单），bot_state 接口不可用。
    """
    bridge = get_bridge(appid) if appid else get_bridge()
    if not bridge:
        return False, {"error": "桥接不可用：未找到 bot"}, False
    api = bridge.get("api")
    loop = bridge.get("loop")
    if api is None or loop is None:
        return False, {"error": "桥接不可用：未找到对应的 bot/api/事件循环"}, False
    bot_appid = str(bridge.get("appid") or appid or "default")
    if not _qpm_acquire(bot_appid, kind="bot_state", limit=60):
        return False, {"error": "频率限制：超过 60 QPM，请稍后再试"}, False
    try:
        _future = asyncio.run_coroutine_threadsafe(
            _async_fetch_bot_state(api, group_openid), loop
        )
        _raw = _future.result(timeout=15)
        _diag = globals().setdefault("_BOT_STATE_DIAG", {"n": 0})
        if _diag["n"] < 3:
            _diag["n"] += 1
            try:
                logger.warning("[bot_state][diag] openid=%s raw=%r", group_openid, _raw)
            except Exception:
                pass
    except Exception as _e:
        _msg = str(_e)
        # 官方接口无权限（仅白名单机器人可用）也会抛异常，需识别为 denied
        _denied = any(_k in _msg for _k in ("11253", "白名单", "接口访问权限", "无接口访问权限", "无权限"))
        _diag = globals().setdefault("_BOT_STATE_DIAG", {"n": 0})
        if _diag["n"] < 3:
            _diag["n"] += 1
            try:
                logger.warning("[bot_state][diag] openid=%s exc=%s", group_openid, _msg)
            except Exception:
                pass
        return False, {"error": "官方 /bot_state 调用失败：%s" % _e}, _denied
    if not isinstance(_raw, dict):
        return False, {"error": "/bot_state 响应异常：%r" % (_raw,)}, False
    _code = _raw.get("code")
    _code_str = str(_code) if _code is not None else ""
    if _code_str == "11253":
        # 白名单未授权：bot_state 接口不可用，无法判定管理员身份
        return False, {"error": "/bot_state 返回 11253（接口未授权/白名单）"}, True
    if _code not in (None, 0, "0"):
        # 非管理员（机器人非成员/无权限/未在该群等），过滤掉、不缓存 role
        return True, "", False
    _role = _normalize_bot_state(_raw)
    return True, _role, False


def _probe_bot_admin(gid):
    """探测某群机器人角色。

    返回 (role_str, definitive, denied)：
      - role_str: 'admin' / 'owner' / 'member' / '' （官方未返回角色）
      - definitive: True 表示可信（可缓存）；False 表示因频率限制/桥接不可用等无法判定。
      - denied: True 表示 bot_state 接口无权限（11253 白名单），整批探测均不可用。
    """
    _ok, _result, _denied = _fetch_bot_state_via_qq_sync(gid)
    if _ok:
        _role = _result if isinstance(_result, str) else ""
        # 即使是 member/'' 也属于「已确定」，可缓存（避免反复探测）
        return _role, True, _denied
    _err = str((_result or {}).get("error", ""))
    if any(_k in _err for _k in ("频率限制", "QPM", "桥接不可用", "事件循环不可用", "拉取失败")):
        return "", False, _denied
    # 其他错误（含 11253 白名单）：当成非管理员 + 已知，避免每轮都试；并标记 denied
    return "", True, _denied


# 启动时加载缓存
_load_group_info_cache()

def _restart_bot():

    global _restart_requested

    _restart_requested = True

    print("[console_server] _restart_bot requested (current process should exit)", flush=True)

    try:

        sys.stdout.flush()

    except Exception:

        pass

    return True

def _shutdown_bot():

    global _shutdown_requested

    _shutdown_requested = True

    print("[console_server] _shutdown_bot requested", flush=True)

    return True

# ============================================================

# 控制看门狗：真正执行重启 / 关机

# 说明：_restart_bot / _shutdown_bot 只设置标志位，本看门狗在后台线程中

# 轮询这些标志位并触发进程级操作，否则控制台/QQ 的指令只会置标志位而无实际效果。

# 由于 go.cmd 用 `start /B` 启动、没有监督进程，必须通过进程内 os.execv 重启

# 或 os._exit 终止来达到「重启 / 关机」目的。

# ============================================================

_control_watchdog_started = False

def _close_current_window():

    """尽力关闭承载当前进程的控制台窗口，然后终止本进程（关机 / 重启后清理旧窗口）。"""

    try:

        import psutil

        me = psutil.Process(os.getpid())

        # 向上查找控制台宿主（conhost / cmd），一并结束以真正关闭窗口

        for p in [me] + me.parents():

            try:

                nm = (p.name() or "").lower()

            except Exception:

                nm = ""

            if nm in ("conhost.exe", "cmd.exe"):

                try:

                    p.kill()

                except Exception:

                    pass

    except Exception:

        pass

    try:
        _flush_all_data()
        os._exit(0)
    except Exception:
        pass

def _shutdown_now():

    """关机：关闭当前运行窗口，直接终止进程。"""

    print("[console_server] 关机指令生效，正在关闭当前运行窗口", flush=True)

    try:

        sys.stdout.flush()

        sys.stderr.flush()

    except Exception:

        pass

    # 关机前先把「今日」计数落盘，避免关机导致当天统计清零

    try:

        _save_today_stats()

    except Exception:  # noqa: BLE001

        pass

    _close_current_window()

def _get_main_script_path():

    """返回主脚本（bot.py）的绝对路径，用于重启时精确复用同一启动命令。

    优先取 __main__.__file__（即真正被 python 直接运行的脚本），

    回退到 sys.argv[0]，最后回退到本模块路径。

    """

    try:

        import __main__

        _mf = getattr(__main__, "__file__", "")

        if _mf:

            return os.path.abspath(_mf)

    except Exception:

        pass

    if sys.argv:

        return os.path.abspath(sys.argv[0])

    return os.path.abspath(__file__)

def _close_admin_server_socket():

    """关闭当前进程的 9988 监听套接字，让新进程能干净地重新绑定端口。

    必须在 os._exit 之前调用，否则旧套接字仍占用端口，新进程绑定 9988 会失败。

    """

    global _admin_httpd, _admin_api_started

    _h = _admin_httpd

    if _h is None:

        return

    try:

        _h.shutdown()

    except Exception:

        pass

    try:

        _h.server_close()

    except Exception:

        pass

    _admin_httpd = None

    _admin_api_started = False

    print("[console_server] 已关闭旧 admin api 端口监听，准备重启", flush=True)

def _restart_in_new_window():

    """重启：启动一个独立的新进程运行机器人，再退出当前进程。

    相比旧版（依赖 go.cmd + 可见控制台窗口），改进点：

    - 直接用 sys.executable 运行主脚本，不依赖 PATH 中的 `python` 与 go.cmd；

    - 以 CREATE_NEW_CONSOLE + 隐藏窗口启动，沿用原本「无可见窗口」的运行模式；

    - 先关闭本进程 9988 监听套接字，避免新进程因端口被占用而启动失败；

    - 新进程启动后确认其仍存活，才退出旧进程（安全阀，避免误杀）；

    - 若新进程启动失败，保留当前进程继续运行，不盲目退出。

    """

    print("[console_server] 重启指令生效，正在启动新进程并退出当前进程", flush=True)

    try:

        sys.stdout.flush()

        sys.stderr.flush()

    except Exception:

        pass

    # 重启前先把「今日」计数落盘，确保新进程启动时能从磁盘恢复到重启前的数值

    try:

        _save_today_stats()

    except Exception:  # noqa: BLE001

        pass

    import subprocess

    _exe = sys.executable

    _script = _get_main_script_path()

    _args = list(sys.argv[1:])

    _cwd = os.getcwd()

    # 先关闭本进程端口监听，给新进程让出 9988

    _close_admin_server_socket()

    # 清理残留的 render.mjs Node 渲染进程（占着旧端口 / 挂死的 puppeteer），
    # 避免新进程渲染时 EADDRINUSE。按命令行精确匹配 render.mjs，不误伤其他 node。
    try:
        _ps_kill = (
            "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | "
            "Where-Object { $_.CommandLine -match 'render\\\\.mjs' } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", _ps_kill],
            capture_output=True, timeout=15,
        )
    except Exception:  # noqa: BLE001
        pass

    _create_new = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)

    _si = None

    try:

        _si = subprocess.STARTUPINFO()

        _si.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)

        _si.wShowWindow = getattr(subprocess, "SW_HIDE", 0)

    except Exception:

        _si = None

    _spawned = False

    try:

        _child = subprocess.Popen(

            [_exe, _script] + _args,

            cwd=_cwd,

            creationflags=_create_new,

            startupinfo=_si,

            close_fds=True,

        )

        print("[console_server] 新进程已启动(PID=%s): %s %s"

              % (_child.pid, _exe, _script), flush=True)

        # 安全阀：给新进程一点时间完成启动；若它在 2 秒内退出，说明启动失败，

        # 此时保留当前进程继续运行，而不是把 bot 彻底杀掉。

        try:

            _child.wait(timeout=2.0)

            print("[console_server] 新进程启动后退出了，重启未完成，保留当前进程",

                  flush=True)

            _spawned = False

        except Exception:

            # 超时 = 新进程仍在运行 = 启动成功

            _spawned = True

    except Exception as _e:  # noqa: BLE001

        print("[console_server] 新进程启动失败: %s，尝试回退就地重启" % _e, flush=True)

        try:

            _close_admin_server_socket()
            _flush_all_data()
            os.execv(_exe, [_exe, _script] + _args)  # 成功则不返回

        except Exception as _e2:  # noqa: BLE001

            print("[console_server] 回退重启也失败: %s，保留当前进程继续运行" % _e2,

                  flush=True)

            _spawned = False

    if _spawned:
        try:
            _flush_all_data()
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        os._exit(0)

    else:

        # 重启失败：恢复端口监听标志，避免后续重复触发且无进程接管

        print("[console_server] 重启失败，当前进程将继续运行", flush=True)

def _control_watchdog_loop():

    global _restart_requested, _shutdown_requested, _pending_action, _pending_until

    import sys

    import subprocess

    while True:

        try:

            now = time.time()

            # 收到指令：进入缓冲期，不直接执行

            if _restart_requested or _shutdown_requested:

                _pending_action = "shutdown" if _shutdown_requested else "restart"

                _pending_until = now + _PENDING_DELAY

                _restart_requested = False

                _shutdown_requested = False

                print(

                    "[console_server] 收到%s指令，%d 秒后生效"

                    % (_pending_action, int(_PENDING_DELAY)),

                    flush=True,

                )

            # 缓冲到期：执行对应动作

            if _pending_action and now >= _pending_until:

                _action = _pending_action

                _pending_action = None

                if _action == "restart":

                    _restart_in_new_window()

                else:

                    _shutdown_now()

        except Exception as _e:  # noqa: BLE001

            print("[console_server] 控制看门狗异常: %s" % _e, flush=True)

        try:

            time.sleep(1.0)

        except Exception:

            pass

def _start_control_watchdog():

    global _control_watchdog_started

    if _control_watchdog_started:

        return

    _control_watchdog_started = True

    _t = threading.Thread(

        target=_control_watchdog_loop, name="xiaoliu-control", daemon=True

    )

    _t.start()

    print("[console_server] 控制看门狗已启动（重启/关机指令将真正生效）", flush=True)

# ============================================================

# 管理员名单（data/admin_list.json）

# 与 bot.py 共用同一文件；bot.py 以 mtime 缓存，写文件后自动重载。

# 元素为 QQ 号或 openid（字符串）。

# ============================================================

_ADMIN_LIST_FILE = os.path.join(

    os.path.dirname(os.path.abspath(__file__)), "data", "admin_list.json"

)

def _load_admin_list():

    """读取管理员名单，返回去重后的有序字符串列表。"""

    _data = _load_json_safe(_ADMIN_LIST_FILE)
    if isinstance(_data, dict) and isinstance(_data.get("admins"), list):
        _seen = []
        for _x in _data["admins"]:
            _s = str(_x).strip()
            if _s and _s not in _seen:
                _seen.append(_s)
        return _seen

    return []

def _save_admin_list(admins):

    """写入管理员名单（去重），确保目录存在。返回 {ok, admins} 或 {ok:False, error}。"""

    _clean = []

    for _x in admins:

        _s = str(_x).strip()

        if _s and _s not in _clean:

            _clean.append(_s)

    try:

        _d = os.path.dirname(_ADMIN_LIST_FILE)

        if not os.path.isdir(_d):

            os.makedirs(_d, exist_ok=True)

        _atomic_save_json(_ADMIN_LIST_FILE, {"admins": _clean}, indent=2)

    except OSError as _e:

        return {"ok": False, "error": "写入管理员名单失败: %s" % _e}

    return {"ok": True, "admins": _clean}

# ============================================================

# 管理后台 HTTP API（9988 端口）

# ============================================================

# 设计目标：

# - 不引入第三方依赖（用标准库 BaseHTTPRequestHandler），

#   跑在守护线程里，不阻塞 bot 主事件循环。

# - 暴露：

#     GET  /api/stats          —— 实时 KPI

#     GET  /api/series?days=N  —— 趋势图（前端用 localStorage 累积）

#     GET  /api/announcement   —— 公告列表

#     POST /api/announcement   —— 发布公告

#     GET  /api/ws-logs       —— WebSocket 日志（机器人连接状态/上行/下行）

#     GET  /api/health         —— 健康检查

# ============================================================

import re

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from urllib.parse import urlparse, parse_qs

_admin_api_started = False

_admin_httpd = None  # 保存监听套接字实例，便于重启前先关闭以释放 9988 端口

_admin_api_lock = threading.RLock()

_announcements = []  # list of {tag, body, ts}

# WebSocket 日志（机器人上行/下行事件流）

# 每条形如: {"ts":"2026/08/02 06:00:16","idx":1,"bot":"小流萤","type":"系统",

#            "direction":"system","scene":"-","sender":"-","content":"机器人[未验证-appid...]"}

_ws_logs = []  # 最多保留 500 条

_ws_logs_max = 500

_ws_log_seq = 0  # 序号自增

# 消息中心专用历史（与 WS 控制台日志相互独立：清空控制台日志不影响消息记录）

_message_logs = []

_message_logs_max = 1000

# 机器人运行日志（cmd 窗口 stdout/stderr 的实时镜像）

# 通过 _install_console_tee() 把 sys.stdout/stderr 同时写入真实流与下方缓冲区，

# 供「日志中心 · 机器人运行日志」展示。

_bot_console = []          # 每条: {"idx","ts","text"}

_bot_console_max = 1500

_bot_console_seq = 0

_bot_console_lock = threading.Lock()

_console_tee_installed = False

class _TeeStream:

    """把写入同时转发到真实流（保留 cmd 窗口实时输出）与机器人运行日志缓冲区。"""

    def __init__(self, real_stream):

        self._real = real_stream

        self._buf = ""

        self._lock = threading.Lock()

    def write(self, data):

        try:

            self._real.write(data)

            self._real.flush()

        except Exception:

            pass

        if isinstance(data, (bytes, bytearray)):

            try:

                data = data.decode("utf-8", errors="replace")

            except Exception:

                data = repr(data)

        with self._lock:

            self._buf += data

            while "\n" in self._buf:

                line, self._buf = self._buf.split("\n", 1)

                _bot_console_append(line.rstrip("\r"))

        try:

            return len(data)

        except Exception:

            return 0

    def flush(self):

        try:

            self._real.flush()

        except Exception:

            pass

    def __getattr__(self, name):

        return getattr(self._real, name)

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# 运行日志级别识别：先按显式标记，再按关键字

_LEVEL_ERROR_RE = re.compile(

    r"(\[ERROR\]|\[CRITICAL\]|\[FATAL\]|\bERROR\b|\bCRITICAL\b|\bFATAL\b|"

    r"Traceback|异常|出错|失败|error:|Exception|Error:|Failed)",

    re.IGNORECASE,

)

_LEVEL_WARN_RE = re.compile(

    r"(\[WARN(ING)?\]|\bWARN(ING)?\b|警告|warn:|Warning:)",

    re.IGNORECASE,

)

def _detect_level(line):

    if _LEVEL_ERROR_RE.search(line):

        return "ERROR"

    if _LEVEL_WARN_RE.search(line):

        return "WARN"

    return "INFO"

def _bot_console_append(line):

    global _bot_console_seq

    # 去掉 ANSI 颜色转义码，避免网页里出现 [1;33m 这类乱码

    line = _ANSI_RE.sub("", line)

    level = _detect_level(line)

    with _bot_console_lock:

        _bot_console_seq += 1

        _bot_console.append({

            "idx": _bot_console_seq,

            "ts": time.strftime("%Y/%m/%d %H:%M:%S"),

            "text": line,

            "level": level,

        })

        if len(_bot_console) > _bot_console_max:

            del _bot_console[: len(_bot_console) - _bot_console_max]

def _install_console_tee():

    """重定向 sys.stdout/stderr 到 _TeeStream，捕获机器人运行日志。

    同时把已存在的 logging StreamHandler（含 botpy 自带的 logger）重新指向

    新的流，并 patch StreamHandler.emit 兜底后续新建的 handler，避免 [INFO]

    这类日志绕过捕获器、只显示在 cmd 窗口而不进日志中心。

    """

    global _console_tee_installed, _tee_stdout, _tee_stderr

    if _console_tee_installed:

        return

    try:

        orig_out = sys.stdout

        orig_err = sys.stderr

        _tee_stdout = _TeeStream(orig_out)

        _tee_stderr = _TeeStream(orig_err)

        sys.stdout = _tee_stdout

        sys.stderr = _tee_stderr

        _repoint_logging_streams(orig_out, orig_err)

        _patch_streamhandler_emit(orig_out, orig_err)

        _console_tee_installed = True

        _bot_console_append("[console_server] 运行日志采集已开启（stdout/stderr 镜像）")

    except Exception:

        pass

_tee_stdout = None

_tee_stderr = None

_orig_streamhandler_emit = None

_orig_out_ref = None

_orig_err_ref = None

def _repoint_logging_streams(orig_out, orig_err):

    """把每个 logger 上仍指向原始流的 StreamHandler 重新指向镜像流。"""

    originals = {orig_out, orig_err, sys.__stdout__, sys.__stderr__}

    for lg in [logging.getLogger()] + list(logging.Logger.manager.loggerDict.values()):

        if not isinstance(lg, logging.Logger):

            continue

        for h in lg.handlers:

            try:

                s = getattr(h, "stream", None)

                if s in originals:

                    h.stream = _tee_stderr if s in (orig_err, sys.__stderr__) else _tee_stdout

            except Exception:

                pass

def _patched_streamhandler_emit(self, record):

    s = getattr(self, "stream", None)

    originals = {sys.__stdout__, sys.__stderr__, _orig_out_ref, _orig_err_ref}

    if s in originals:

        self.stream = _tee_stderr if s in (sys.__stderr__, _orig_err_ref) else _tee_stdout

    return _orig_streamhandler_emit(self, record)

def _patch_streamhandler_emit(orig_out, orig_err):

    global _orig_streamhandler_emit, _orig_out_ref, _orig_err_ref

    _orig_out_ref, _orig_err_ref = orig_out, orig_err

    if _orig_streamhandler_emit is None:

        _orig_streamhandler_emit = logging.StreamHandler.emit

    if not getattr(logging.StreamHandler.emit, "_patched", False):

        logging.StreamHandler.emit = _patched_streamhandler_emit

        logging.StreamHandler.emit._patched = True

def append_ws_log(bot, type_, direction, scene, sender, content, nickname="", avatar="", to_message=True,

                 media_type="", media_url="", group_openid=""):

    """追加一条 WebSocket 日志。供 bot.py / console_server.record_message 调用。

    to_message=False 时只写入控制台日志（_ws_logs），不写入消息中心历史（_message_logs），

    例如「日志已清空」占位符不应污染消息记录。

    media_type / media_url 用于承载富媒体消息（图片/语音/视频）的展示信息。

    group_openid 用于群聊场景保留完整群 openid，避免 scene 字段被截断后无法匹配群资料。

    """

    global _ws_log_seq

    with _admin_api_lock:

        _ws_log_seq += 1

        _scene = str(scene or "-")

        _group_openid = str(group_openid or scene or "-")

        entry = {

            "idx": _ws_log_seq,

            "ts": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),

            "bot": str(bot or "小流萤")[:32],

            "type": str(type_ or "系统")[:16],

            "direction": str(direction or "system")[:16],

            "scene": _scene[:128],

            "group_openid": _group_openid[:128],

            "sender": str(sender or "-")[:64],

            "nickname": str(nickname or "")[:32],

            "avatar": str(avatar or "")[:256],

            "content": str(content or "")[:500],

            "media_type": str(media_type or "")[:16],

            "media_url": str(media_url or "")[:512],

        }

        _ws_logs.append(entry)

        if len(_ws_logs) > _ws_logs_max:

            del _ws_logs[: len(_ws_logs) - _ws_logs_max]

        # 同步写入消息中心专用历史（独立于控制台日志，清空控制台不影响消息记录）

        if to_message:

            _message_logs.append(entry)

            if len(_message_logs) > _message_logs_max:

                del _message_logs[: len(_message_logs) - _message_logs_max]

    return entry

# 启动时插入一条占位系统日志（玄机风格：连接状态展示）

append_ws_log("小流萤", "系统", "system", "-", "-",

              "机器人[未验证-appid...]")

def _classify_message(args, kwargs):

    """根据 record_message 的入参推断场景：group / private / unknown。"""

    try:

        scene = kwargs.get("scene") or kwargs.get("type") or ""

        if scene:

            s = str(scene).lower()

            if "group" in s:

                return "group"

            if "c2c" in s or "private" in s or "friend" in s:

                return "private"

        for a in args:

            if not isinstance(a, str):

                continue

            if "group_message" in a or "群消息" in a:

                return "group"

            if "c2c_message" in a or "私聊" in a:

                return "private"

    except Exception:

        pass

    return "unknown"

# 给 record_message 套一层，累加分类计数

# 同时同步写一条 WebSocket 日志（玄机风格：所有事件都进 WS 日志表）

_orig_record_message = record_message

def record_message(*args, **kwargs):
    bot = str(kwargs.get("bot") or "小流萤")
    with _lock:
        scene = _classify_message(args, kwargs)
        if scene == "group":
            _status["group_message_count"] = _status.get("group_message_count", 0) + 1
            _bb = _status_by_bot.setdefault(bot, {})
            _bb["group_message_count"] = _bb.get("group_message_count", 0) + 1
            _gid = str(kwargs.get("target_id") or "").strip()
            if _gid:
                _bb.setdefault("_groups", set()).add(_gid)
        elif scene == "private":
            _status["private_message_count"] = _status.get("private_message_count", 0) + 1
            _bb = _status_by_bot.setdefault(bot, {})
            _bb["private_message_count"] = _bb.get("private_message_count", 0) + 1
        _status["message_count"] = _status.get("message_count", 0) + 1
        _bb = _status_by_bot.setdefault(bot, {})
        _bb["message_count"] = _bb.get("message_count", 0) + 1

    # 小时级聚合：今日活跃时段图表数据源；不影响 _status 计数，仅内存 + 周期落盘。
    try:
        _record_hourly_message(scene)
    except Exception:
        pass

    # 立即落盘「今日」计数：单聊 / 群聊消息属于高频事件，

    # 仅靠 30s 周期 flusher 可能在重启 / 关机前丢失最近若干条，故消息产生即落盘。

    try:

        _save_today_stats()

    except Exception:  # noqa: BLE001

        pass

    # 同步写 WS 日志（用第一个非空字符串作"内容"）

    try:

        content = ""

        for a in reversed(args):

            if isinstance(a, str) and a.strip():

                content = a[:200]

                break

        if not content:

            content = _status.get("last_message", "") or "(空消息)"

        direction = "上行" if scene in ("group", "private") else "system"

        type_ = "群聊" if scene == "group" else ("单聊" if scene == "private" else "系统")

        scene_label = {

            "group": "group_message",

            "private": "c2c_message",

            "unknown": "-",

        }.get(scene, "-")

        # 群/单聊的真实目标 ID（group_openid / user_openid / channel_id），优先用 target_id

        target_id = str(kwargs.get("target_id") or "").strip()

        scene_value = target_id or scene_label

        # 用户标识：优先 member_openid / user_openid（稳定 ID），用于会话分组与头像

        openid = str(kwargs.get("member_openid") or kwargs.get("user_openid") or "")[:64]

        # 昵称：官方事件字段 username（群消息/私聊事件里已解析）

        nickname = str(kwargs.get("username") or "")[:32]

        # 单聊 / 群聊发送者昵称缺失兜底：通过 OIAPI Openid 接口反查（带内存缓存，命中即秒回）。
        # 解决消息记录里发送者列显示成 openid[:8] 而不是真实昵称的问题（2026-08-08）。
        if not nickname and openid and openid != "-":
            try:
                _oiapi_nick = _fetch_nickname_via_oiapi_openid(openid)
                if _oiapi_nick:
                    nickname = _oiapi_nick[:32]
            except Exception:
                pass

        # 记录「有发言记录的群聊」并持久化（仅新增或补全群名时落盘）

        if scene == "group" and target_id:

            try:

                _note_group_message(target_id, nickname or "")

            except Exception:  # noqa: BLE001

                pass

        # 计算头像 URL 并缓存

        avatar_url = _qq_avatar_url(openid) if openid else ""

        if avatar_url:

            with _lock:

                _user_avatars[openid] = avatar_url

        # 归集为成员（仅真实用户消息：群聊 / 单聊）

        if openid and openid != "-" and scene in ("group", "private"):

            _src = "group" if scene == "group" else "private"

            _grp = target_id if scene == "group" else ""

            _upsert_member(openid, str(kwargs.get("bot") or "小流萤"), nickname, avatar_url, _src, _grp, member_role=kwargs.get("member_role"))

        append_ws_log(

            bot=str(kwargs.get("bot") or "小流萤"),

            type_=type_,

            direction=direction,

            scene=scene_value,

            sender=openid or "-",

            content=content,

            nickname=nickname,

            avatar=avatar_url,

        )

    except Exception:

        pass

    return _orig_record_message(*args, **kwargs)

def _today_start_ts():

    """返回本地今天 00:00:00 的时间戳（用于按自然日统计活跃）。"""

    now = time.localtime()

    return time.mktime((now.tm_year, now.tm_mon, now.tm_mday, 0, 0, 0, 0, 0, -1))

def _compute_active_counts(bot=None):

    """统计「今日」活跃用户数与活跃群聊数（基于成员最后活跃时间）。

    活跃用户：last_seen 落在今天的去重用户（成员表本身按 openid 去重）。

    活跃群聊：今天有成员活跃的群 openid 去重数。

    此前这两个值从未被赋值，导致前端 KPI 与图表恒为 0。

    """

    midnight = _today_start_ts()

    active_users = 0

    active_groups = set()

    with _lock:
        for m in _members.values():
            if bot and (m.get("bot") or "小流萤") != bot:
                continue
            if (m.get("last_seen") or 0) >= midnight:

                active_users += 1

                for g in (m.get("groups") or []):

                    if g:

                        active_groups.add(g)

    return active_users, len(active_groups)

def _merged_per_bot_today():
    """归并「今日」计数器：返回 (appid -> canonical label, appid -> 合并计数器字典)。

    canonical label 优先级：桥接真实名 name_rt > bots.json 备注名 name > appid。
    _status_by_bot 中同一只 bot 可能以不同 key（中文名/旧 appid）写入，本函数按 appid 归并，
    避免多机器人对比图出现重复条目。不调用 _compute_kpi，避免递归。
    """
    _label_of = {}
    try:
        for _b in bot_manager.load_bots():
            _aid = str(_b.get('appid') or '').strip()
            if not _aid:
                continue
            _rt = _bot_bridges.get(_aid) or {}
            _label = (_rt.get('name') or _b.get('name_rt') or _b.get('name') or _aid).strip()
            if _label:
                _label_of[_aid] = _label
    except Exception:
        pass
    try:
        with _lock:
            _status_keys = list(_status_by_bot.keys())
    except Exception:
        _status_keys = []
    for _bn in _status_keys:
        _aid = (resolve_bot_key(_bn) or str(_bn)).strip()
        if _aid:
            _label_of.setdefault(_aid, _bn)
    try:
        with _lock:
            _snapshot = dict(_status_by_bot)
    except Exception:
        _snapshot = {}
    _aid_to_bb = {}
    for _bn, _bb in _snapshot.items():
        _aid = (resolve_bot_key(_bn) or str(_bn)).strip()
        if not _aid:
            continue
        _m = _aid_to_bb.setdefault(_aid, {})
        for _k in _TODAY_KEYS:
            if _k == '_groups':
                _gs = _m.setdefault('_groups', set())
                _ss = _bb.get('_groups')
                if isinstance(_ss, set):
                    _gs |= _ss
                elif isinstance(_ss, list):
                    _gs |= set(_ss)
            elif isinstance(_bb.get(_k), (int, float)):
                _m[_k] = _m.get(_k, 0) + _bb[_k]
    return _label_of, _aid_to_bb


def _compute_per_bot():
    # 每个机器人的今日 KPI 汇总，键统一走「QQ 平台真实昵称 name_rt 或 appid」。
    # 同一只 bot 在不同运行周期可能以不同 key 写入 _status_by_bot
    # （如「机器人 1905365716」/「恶龙遐蝶」/appid），本函数按 appid 归并计数器，
    # 避免多机器人对比图重复显示一条「机器人 1905365716」+一条「恶龙遐蝶」。
    # 1) appid -> canonical label（name_rt > name > appid）
    _label_of = {}
    try:
        for _b in bot_manager.load_bots():
            _aid = str(_b.get('appid') or '').strip()
            if not _aid:
                continue
            _rt = _bot_bridges.get(_aid) or {}
            _label = (_rt.get('name') or _b.get('name_rt') or _b.get('name') or _aid).strip()
            if _label:
                _label_of[_aid] = _label
    except Exception:
        pass
    # 2) _status_by_bot 里出现过的孤立 key 也参与归并（即使没在 bots.json 注册）
    try:
        with _lock:
            _status_keys = list(_status_by_bot.keys())
    except Exception:
        _status_keys = []
    for _bn in _status_keys:
        _aid = (resolve_bot_key(_bn) or str(_bn)).strip()
        if _aid:
            _label_of.setdefault(_aid, _bn)
    # 3) 按 aid 归并 _status_by_bot 计数器
    try:
        with _lock:
            _snapshot = dict(_status_by_bot)
    except Exception:
        _snapshot = {}
    _aid_to_bb = {}
    for _bn, _bb in _snapshot.items():
        _aid = (resolve_bot_key(_bn) or str(_bn)).strip()
        if not _aid:
            continue
        _m = _aid_to_bb.setdefault(_aid, {})
        for _k in _TODAY_KEYS:
            if _k == '_groups':
                _gs = _m.setdefault('_groups', set())
                _ss = _bb.get('_groups')
                if isinstance(_ss, set):
                    _gs |= _ss
                elif isinstance(_ss, list):
                    _gs |= set(_ss)
            elif isinstance(_bb.get(_k), (int, float)):
                _m[_k] = _m.get(_k, 0) + _bb[_k]
    # 4) 按 aid 输出 one-per-bot KPI（label 用 canonical）
    _out = {}
    for _aid, _label in _label_of.items():
        try:
            _out[_label] = _compute_kpi(_label)
        except Exception:
            _out[_label] = {}
        _bb = _aid_to_bb.get(_aid, {})
        for _k in _TODAY_KEYS:
            if _k == '_groups':
                _gs = _bb.get('_groups', set())
                _out[_label]['_groups'] = _gs
                _out[_label]['groups_total'] = len(_gs)
            elif _k in _bb:
                _out[_label][_k] = _bb[_k]
    return _out


def _compute_kpi(bot=""):

    with _lock:

        s = dict(_status)

    bot_pid = s.get("bot_pid") or os.getpid()

    uptime = int(time.time() - _started_at)

    # 尝试从 config 拿真实 AppID（兼容多种命名）

    bot_appid = ""

    bot_verified = True

    try:

        from modules import config as _cfg  # type: ignore

        for _k in ("BOT_APPID", "APPID", "APP_ID", "QQBOT_APPID"):

            v = getattr(_cfg, _k, None)

            if v:

                bot_appid = str(v)

                break

        if not bot_appid:

            bot_verified = False

    except Exception:

        pass

    # 多机器人状态：合并 bots.json 配置与运行时桥接

    try:

        _cfg_bots = bot_manager.load_bots()

        _rt_bots = []

        for _b in _cfg_bots:

            _aid = _b["appid"]

            _rt = _bot_bridges.get(_aid) or {}

            _rt_bots.append({

                "appid": _aid,

                "appid_masked": bot_manager.mask_appid(_aid),

                "name": _b.get("name") or "",

                # 优先级：桥接中的真实名称 / 头像 > 配置里的备注名

                "name_rt": (_rt.get("name") or _b.get("name") or ""),

                "avatar": (_rt.get("avatar") or ""),

                "environment": _b.get("environment", "sandbox"),

                "event_mode": _b.get("event_mode", "websocket"),

                "enabled": bool(_b.get("enabled", True)),

                "connected": bool(_rt.get("api") is not None),

            })

        s["bots"] = _rt_bots

        s["bot_count"] = len(_rt_bots)

    except Exception:

        pass

    # === 暴露给 KPI (供 dashboard 卡片展示每个 bot 真实状态) ===
    _stats_rt_bots = _rt_bots if "_rt_bots" in dir() else []
    _stats_total = len(_stats_rt_bots)
    _stats_online_total = sum(1 for _b in _stats_rt_bots if _b.get("connected"))
    # === 为每个机器人补充真实今日统计（多实例数据总览用） ===
    if not bot and _stats_rt_bots:
        try:
            _mb_label_of, _mb_aid_to_bb = _merged_per_bot_today()
        except Exception:
            _mb_label_of, _mb_aid_to_bb = {}, {}
        # 成员按机器人归集：count + 最近活跃（取成员档案 last_seen 最大值作为代理）
        _members_by_bot = {}
        try:
            with _lock:
                _mb_members = list(_members.values())
            for _m in _mb_members:
                _bl = str((_m.get("bot") or "小流萤")).strip()
                _e = _members_by_bot.setdefault(_bl, {"count": 0, "max_ls": 0})
                _e["count"] += 1
                _ls = _m.get("last_seen") or 0
                if isinstance(_ls, (int, float)) and _ls > _e["max_ls"]:
                    _e["max_ls"] = _ls
        except Exception:
            pass
        # 群按机器人归集（GROUP_BOT_MAP: group_openid -> appid；未归属的群（_shared）不计入任何单实例）
        _groups_by_bot = {}
        try:
            with _lock:
                _gn = dict(_group_names)
                _gbm = dict(GROUP_BOT_MAP) if isinstance(GROUP_BOT_MAP, dict) else {}
            for _gid in _gn.keys():
                _gaid = resolve_bot_key(_gbm.get(_gid) or "")
                if _gaid:
                    _groups_by_bot[_gaid] = _groups_by_bot.get(_gaid, 0) + 1
        except Exception:
            pass
        for _bot in _stats_rt_bots:
            _aid = str(_bot.get("appid") or "").strip()
            _label = (_bot.get("name_rt") or _bot.get("name") or _aid).strip()
            _bb = _mb_aid_to_bb.get(_aid, {}) or {}
            _mem = _members_by_bot.get(_label, {}) or {}
            _mc = _bb.get("message_count", 0) or 0
            _pm = _bb.get("private_message_count", 0) or 0
            _gm = _bb.get("group_message_count", 0) or 0
            _gtotal = _groups_by_bot.get(_aid, 0)
            try:
                _ci = _compute_checkin_stats(bot_filter=_label).get("today_checkins", 0) or 0
            except Exception:
                _ci = 0
            _max_ls = _mem.get("max_ls", 0) or 0
            _last_active = ""
            if _max_ls:
                try:
                    _last_active = time.strftime("%Y-%m-%d %H:%M", time.localtime(_max_ls))
                except Exception:
                    _last_active = ""
            _bot["messages_today"] = _mc
            _bot["private_messages_today"] = _pm
            _bot["group_messages_today"] = _gm
            _bot["groups_total"] = _gtotal
            _bot["members_total"] = _mem.get("count", 0) or 0
            _bot["checkins_today"] = _ci
            _bot["last_active_at"] = _last_active
    # 活跃插件数：直接取插件注册表中的插件总数（内置 + 外置），含热加载的外置插件
    try:
        active_plugins = plugin_registry.count_plugins()
    except Exception:
        active_plugins = 0

    # 今日活跃用户 / 活跃群聊（基于成员真实互动时间统计）

    _au, _ag = _compute_active_counts()

    # 系统资源占用（CPU / 内存 / GPU），供仪表盘实时状态条使用

    _sys = _collect_sys_stats()

    # 网络延迟（毫秒）与实时网速（字节/秒）

    _network_latency = _collect_network_latency()

    _network_speed = _collect_network_speed()

    # 今日 / 昨日签到人数（来自机器人签到系统）

    _ci_today, _ci_yesterday = _count_today_checkins()
    result = {

        "online": bool(s.get("online", True)),

        "bot_name": s.get("bot_name") or "小流萤",

        "bot_avatar": s.get("bot_avatar") or "",

        "bot_pid": bot_pid,

        "bot_appid": bot_appid,

        "bot_verified": bot_verified,

        "uptime_seconds": uptime,

        "uptime_str": _format_uptime_str(uptime),

        # KPI

        "robots_total": _stats_total,

        "robots_online": _stats_online_total,

        "messages_today": s.get("message_count", 0),

        "messages_total": s.get("message_count", 0),

        "checkins_today": _ci_today,

        "checkins_yesterday_delta": _ci_today - _ci_yesterday,

        "groups_total": len(_group_names),

        "members_total": len(_members),

        "active_plugins": active_plugins,

        "private_messages": s.get("private_message_count", 0),

        "group_messages": s.get("group_message_count", 0),

        "active_users_today": _au,

        "active_groups_today": _ag,

        "groups_joined_today": s.get("groups_joined_today", 0),

        "groups_left_today": s.get("groups_left_today", 0),

        "friends_added_today": s.get("friends_added_today", 0),

        "friends_removed_today": s.get("friends_removed_today", 0),

        "api_call_count": s.get("api_call_count", 0),

        "last_message": s.get("last_message", ""),

        "last_message_at": s.get("last_message_at", ""),

        "cpu": _sys.get("cpu"),

        "mem": _sys.get("mem"),

        "gpu": _sys.get("gpu"),

        "network_latency": _network_latency,

        "network_speed": _network_speed,

        "as_of": int(time.time()),

        # 今日小时级消息分布（today peak hours），供 admin 数据总览图表渲染
        "hourly_messages": _snapshot_today_hourly(),

        # === 按机器人维度的真实状态 (供 dashboard 卡片显示每个 bot 名称/连接/启用) ===
        "bots": _stats_rt_bots,
    }

    # ===== 按机器人维度覆盖（仪表盘「按机器人切换查看」） =====
    if bot:
        _bb = _status_by_bot.get(bot, {}) or {}
        _ci_bot = _compute_checkin_stats(bot_filter=bot).get("today_checkins", 0)
        _au_bot, _ag_bot = _compute_active_counts(bot)
        _members_bot = sum(1 for m in _members.values() if (m.get("bot") or "小流萤") == bot)
        _groups_bot = len(_bb.get("_groups", set()) or set())
        _bots_list = s.get("bots") or []
        _bot_info = next((b for b in _bots_list if (b.get("name_rt") or b.get("name")) == bot), {})
        _bot_online = bool(_bot_info.get("connected"))
        result["robots_total"] = 1
        result["robots_online"] = 1 if _bot_online else 0
        result["messages_today"] = _bb.get("message_count", 0)
        result["messages_total"] = _bb.get("message_count", 0)
        result["private_messages"] = _bb.get("private_message_count", 0)
        result["group_messages"] = _bb.get("group_message_count", 0)
        result["checkins_today"] = _ci_bot
        result["checkins_yesterday_delta"] = 0
        result["groups_total"] = _groups_bot
        result["members_total"] = _members_bot
        result["active_users_today"] = _au_bot
        result["active_groups_today"] = _ag_bot
        result["groups_joined_today"] = _bb.get("groups_joined_today", 0)
        result["groups_left_today"] = _bb.get("groups_left_today", 0)
        result["friends_added_today"] = _bb.get("friends_added_today", 0)
        result["friends_removed_today"] = _bb.get("friends_removed_today", 0)
        # 覆盖 bot 元信息（之前一直返回硬编码的 bots.json 默认值，切到非首 bot 时显示错乱）
        result["bot_name"] = _bot_info.get("name_rt") or _bot_info.get("name") or bot
        result["bot_avatar"] = _bot_info.get("avatar") or result.get("bot_avatar", "")
        result["bot_appid"] = _bot_info.get("appid") or bot
        result["bot_verified"] = True
        return result

    return result

def _today_date_str():

    """返回本地当前日期 YYYY-MM-DD。"""

    return time.strftime("%Y-%m-%d", time.localtime())

def _load_checkin_data():
    """加载签到数据：物理隔离下合并 data/bots/<appid>/checkin_data.json 与 _shared，
    并兼容旧根 data/checkin_data.json。返回 group_openid -> members 合并字典。"""
    merged = {}
    _roots = []
    # 各机器人明细 + _shared
    _bots_root = os.path.join(_DATA_ROOT_DIR, "bots")
    if os.path.isdir(_bots_root):
        for _name in sorted(os.listdir(_bots_root)):
            _p = os.path.join(_bots_root, _name, "checkin_data.json")
            if os.path.exists(_p):
                _roots.append(_p)
    # 旧根兼容（迁移前的全局文件，若存在则合并；后写以覆盖，保留较新记录）
    _old = os.path.join(_DATA_ROOT_DIR, "checkin_data.json")
    if os.path.exists(_old):
        _roots.append(_old)
    for _p in _roots:
        try:
            with open(_p, "r", encoding="utf-8") as f:
                _d = _json.load(f)
            if isinstance(_d, dict):
                for _g, _m in _d.items():
                    if not isinstance(_m, dict):
                        continue
                    _dest = merged.setdefault(_g, {})
                    for _u, _info in _m.items():
                        _dest[_u] = _info
        except Exception:
            continue
    return merged

def _count_today_checkins():

    """统计今日/昨日签到人数（来自机器人签到系统 data/checkin_data.json）。

    早期 KPI 里「今日签到」误用 command_count（指令总次数）充当，数值失真；

    此函数直接读取签到系统落盘数据，按 last_date 匹配自然日，得到真实签到人数。

    返回 (今日签到人数, 昨日签到人数)。

    """

    data = _load_checkin_data()

    now = time.localtime()

    today = time.strftime("%Y-%m-%d", now)

    yesterday = time.strftime("%Y-%m-%d", time.localtime(time.mktime(now) - 86400))

    t_cnt = 0

    y_cnt = 0

    for members in data.values():

        if not isinstance(members, dict):

            continue

        for info in members.values():

            if not isinstance(info, dict):

                continue

            ld = str(info.get("last_date") or "")

            if ld == today:

                t_cnt += 1

            elif ld == yesterday:

                y_cnt += 1

    return t_cnt, y_cnt

def _compute_checkin_stats(bot_filter="", group_filter=""):

    """

    计算签到统计数据。

    bot_filter: 按成员档案中的 bot 字段筛选（空字符串表示不过滤）

    group_filter: 按群 openid 筛选（空字符串表示不过滤）

    返回字典，包含今日签到人数、签到成员数、最高连续、平均连续、记录列表等。

    """

    data = _load_checkin_data()

    today = _today_date_str()

    records = []

    total_continuous = 0

    max_continuous = 0

    checked_user_keys = set()  # (group, member) 去重

    # 先把成员表按 openid 建立昵称/机器人索引

    with _lock:

        member_index = {}

        for m in _members.values():

            oid = str(m.get("openid") or "")

            if oid:

                member_index[oid] = m

    for group_openid, members in data.items():

        if not isinstance(members, dict):

            continue

        if group_filter and group_openid != group_filter:

            continue

        for member_openid, info in members.items():

            if not isinstance(info, dict):

                continue

            continuous = int(info.get("continuous") or 0)

            total = int(info.get("total") or 0)

            last_date = str(info.get("last_date") or "")

            points = int(info.get("points") or 0)

            # 按机器人筛选：优先用成员档案中的 bot，未找到则默认"小流萤"

            member = member_index.get(member_openid, {})

            bot_name = str(member.get("bot") or "小流萤").strip()

            nickname = str(member.get("nickname") or "").strip()

            if bot_filter and bot_name != bot_filter:

                continue

            checked_today = (last_date == today)

            if checked_today:

                checked_user_keys.add((group_openid, member_openid))

            total_continuous += continuous

            if continuous > max_continuous:

                max_continuous = continuous

            display_name = nickname or ("用户" + member_openid[:8])

            records.append({

                "bot": bot_name,

                "member_openid": member_openid,

                "member_name": display_name,

                "group_openid": group_openid,

                "total": total,

                "continuous": continuous,

                "last_date": last_date or "-",

                "checked_today": checked_today,

                "gold": 0,        # 小流萤签到系统目前无金币字段，占位

                "points": points,

            })

    total_members = len(records)

    avg_continuous = round(total_continuous / total_members, 1) if total_members else 0

    today_checkins = len(checked_user_keys)

    # 可用筛选项

    bots = sorted(set((r["bot"] or "小流萤") for r in records))

    groups = sorted(set((r["group_openid"] or "") for r in records if r["group_openid"]))

    return {

        "today_checkins": today_checkins,

        "total_members": total_members,

        "max_continuous": max_continuous,

        "avg_continuous": avg_continuous,

        "today": today,

        "bots": bots,

        "groups": groups,

        "records": records,

    }

def _update_config_py(appid, secret, event_mode, environment):

    """更新 modules/config.py 中的机器人凭证与运行配置。"""

    bot_dir = os.path.dirname(os.path.abspath(__file__))

    path = os.path.join(bot_dir, "modules", "config.py")

    if not os.path.isfile(path):

        return False, "未找到 modules/config.py"

    try:

        with open(path, "r", encoding="utf-8") as f:

            text = f.read()

        # 替换 APPID / SECRET（保留引号风格）

        text = re.sub(

            r'^(\s*APPID\s*=\s*)["\'][^"\']*["\']',

            r'\1"%s"' % appid.replace('"', '\\"'),

            text,

            flags=re.MULTILINE,

        )

        text = re.sub(

            r'^(\s*SECRET\s*=\s*)["\'][^"\']*["\']',

            r'\1"%s"' % secret.replace('"', '\\"'),

            text,

            flags=re.MULTILINE,

        )

        # 追加/更新事件接收方式与环境（如不存在）

        if not re.search(r'^\s*BOT_EVENT_MODE\s*=', text, flags=re.MULTILINE):

            text += '\n\n# 机器人事件接收方式 (websocket / webhook)\nBOT_EVENT_MODE = "%s"\n' % event_mode

        else:

            text = re.sub(

                r'^(\s*BOT_EVENT_MODE\s*=\s*)["\'][^"\']*["\']',

                r'\1"%s"' % event_mode,

                text,

                flags=re.MULTILINE,

            )

        if not re.search(r'^\s*BOT_ENVIRONMENT\s*=', text, flags=re.MULTILINE):

            text += '\n# 机器人运行环境 (sandbox / production)\nBOT_ENVIRONMENT = "%s"\n' % environment

        else:

            text = re.sub(

                r'^(\s*BOT_ENVIRONMENT\s*=\s*)["\'][^"\']*["\']',

                r'\1"%s"' % environment,

                text,

                flags=re.MULTILINE,

            )

        with open(path, "w", encoding="utf-8") as f:

            f.write(text)

        return True, ""

    except Exception as e:

        return False, "写入 modules/config.py 失败: %s" % e

def _update_config_yaml(appid, secret, event_mode, environment):

    """更新 config.yaml 中的机器人凭证与运行配置，保持与 config.py 一致。"""

    bot_dir = os.path.dirname(os.path.abspath(__file__))

    path = os.path.join(bot_dir, "config.yaml")

    if not os.path.isfile(path):

        return True, ""  # 可选文件，不存在则忽略

    try:

        with open(path, "r", encoding="utf-8") as f:

            text = f.read()

        text = re.sub(

            r'^(\s*appid\s*:\s*)["\']?[^\s"\']*["\']?',

            r'\1"%s"' % appid.replace('"', '\\"'),

            text,

            flags=re.MULTILINE,

        )

        text = re.sub(

            r'^(\s*token\s*:\s*)["\']?[^\s"\']*["\']?',

            r'\1"%s"' % secret.replace('"', '\\"'),

            text,

            flags=re.MULTILINE,

        )

        if not re.search(r'^\s*event_mode\s*:', text, flags=re.MULTILINE):

            text += '\n# 事件接收方式: websocket / webhook\nevent_mode: "%s"\n' % event_mode

        else:

            text = re.sub(

                r'^(\s*event_mode\s*:\s*)["\']?[^\s"\']*["\']?',

                r'\1"%s"' % event_mode,

                text,

                flags=re.MULTILINE,

            )

        if not re.search(r'^\s*environment\s*:', text, flags=re.MULTILINE):

            text += '\n# 运行环境: sandbox / production\nenvironment: "%s"\n' % environment

        else:

            text = re.sub(

                r'^(\s*environment\s*:\s*)["\']?[^\s"\']*["\']?',

                r'\1"%s"' % environment,

                text,

                flags=re.MULTILINE,

            )

        with open(path, "w", encoding="utf-8") as f:

            f.write(text)

        return True, ""

    except Exception as e:

        return False, "写入 config.yaml 失败: %s" % e

# ====== 初始化向导数据存取 ======

_ADMIN_AUTH_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "admin_auth.json")

def _load_admin_auth():

    try:

        with _lock:

            if not os.path.isfile(_ADMIN_AUTH_PATH):

                return {}

            with open(_ADMIN_AUTH_PATH, "r", encoding="utf-8") as f:

                obj = _json.loads(f.read() or "{}")

            return obj if isinstance(obj, dict) else {}

    except Exception:

        return {}

def _save_admin_auth(payload):

    try:

        os.makedirs(os.path.dirname(_ADMIN_AUTH_PATH), exist_ok=True)

        tmp = _ADMIN_AUTH_PATH + ".tmp"

        with open(tmp, "w", encoding="utf-8") as f:

            f.write(_json.dumps(payload, ensure_ascii=False, indent=2))

            f.flush()

            try:

                os.fsync(f.fileno())

            except Exception:

                pass

        os.replace(tmp, _ADMIN_AUTH_PATH)

        return True

    except Exception as e:

        return False, str(e)

def _hash_password(pwd):

    import hashlib

    return hashlib.sha256(str(pwd or "").encode("utf-8")).hexdigest()
_CONSOLE_SESSIONS = {}  # token -> 过期时间戳(epoch)；仅存内存，进程重启即清空 -> 每次启动需重新输入口令
_CONSOLE_SESSIONS_LOCK = threading.Lock()
_CONSOLE_TOKEN_TTL = 24 * 3600  # 令牌有效期 24h
_CONSOLE_COOKIE = "console_token"
_CONSOLE_PUBLIC_PATHS = (
    "/", "/favicon.ico",
    "/api/setup/status", "/api/setup/password", "/api/setup/complete",
    "/api/console/login", "/api/console/logout",
    "/api/health",
)


# ===== 控制台背景音乐 =====
_MUSIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "admin", "assets", "music")
_MUSIC_ALLOWED_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".wma"}
_MUSIC_MIME = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".aac": "audio/aac",
    ".wma": "audio/x-ms-wma",
}


def _safe_music_filename(name):
    """只保留安全文件名（保留字母数字、中文、空格、点、中划线、下划线），限制长度与扩展名。"""
    base = os.path.basename(name).strip()
    if not base:
        return ""
    ext = os.path.splitext(base)[1].lower()
    if ext not in _MUSIC_ALLOWED_EXTS:
        return ""
    stem = os.path.splitext(base)[0]
    stem = re.sub(r'[^\w\u4e00-\u9fff\s\-]', "_", stem)
    stem = re.sub(r'\s+', " ", stem).strip()
    stem = stem[:60] or "music"
    final = stem + ext
    # 若重名，加序号
    path = os.path.join(_MUSIC_DIR, final)
    if not os.path.exists(path):
        return final
    idx = 1
    while idx < 1000:
        candidate = os.path.join(_MUSIC_DIR, f"{stem} ({idx}){ext}")
        if not os.path.exists(candidate):
            return f"{stem} ({idx}){ext}"
        idx += 1
    return ""


def _list_music_files():
    try:
        os.makedirs(_MUSIC_DIR, exist_ok=True)
    except Exception:
        pass
    items = []
    if not os.path.isdir(_MUSIC_DIR):
        return items
    for name in sorted(os.listdir(_MUSIC_DIR)):
        path = os.path.join(_MUSIC_DIR, name)
        if not os.path.isfile(path):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext not in _MUSIC_ALLOWED_EXTS:
            continue
        try:
            st = os.stat(path)
            items.append({
                "name": name,
                "size": st.st_size,
                "ts": int(st.st_mtime),
                "url": "/api/music/play/" + name,
            })
        except Exception:
            continue
    return items


def _send_audio_stream(self, fs_path):
    ext = os.path.splitext(fs_path)[1].lower()
    mime = _MUSIC_MIME.get(ext, "application/octet-stream")
    try:
        with open(fs_path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)
    except Exception as e:
        self._send_json(500, {"ok": False, "error": "读取音频失败", "detail": str(e)})


def _console_token_valid(token):
    if not token:
        return False
    with _CONSOLE_SESSIONS_LOCK:
        exp = _CONSOLE_SESSIONS.get(token)
        if not exp:
            return False
        if time.time() > exp:
            _CONSOLE_SESSIONS.pop(token, None)
            return False
    return True


_CONSOLE_LOGIN_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>小流萤 · 管理后台 · 访问口令</title>
<style>
  :root{ --primary:#5b6cff; --primary-deep:#4453e8; --accent:#8c5cff; --cyan:#59d6ff; --ink:#1f2240; --ink2:#4a4f73; --muted:#8b91b5; --err:#e0566b; --ok:#2bb673; }
  *{box-sizing:border-box;}
  body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;font-family:-apple-system,"Segoe UI",Roboto,"Microsoft YaHei",sans-serif;color:var(--ink);background:linear-gradient(135deg,#eef0fa 0%,#f3eefb 100%);overflow:hidden;position:relative;}
  body::before,body::after{content:"";position:absolute;border-radius:50%;filter:blur(70px);opacity:.5;z-index:0;}
  body::before{width:520px;height:520px;background:radial-gradient(circle,#ae8cff 0%,transparent 70%);top:-180px;left:-140px;}
  body::after{width:480px;height:480px;background:radial-gradient(circle,#7fe0ff 0%,transparent 70%);bottom:-180px;right:-140px;}
  .card{position:relative;z-index:1;width:368px;padding:34px 30px;background:rgba(255,255,255,0.72);backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);border:1px solid rgba(255,255,255,0.85);border-radius:20px;box-shadow:0 22px 60px rgba(91,108,255,0.18);}
  .brand{display:flex;align-items:center;gap:11px;margin-bottom:6px;}
  .logo{width:36px;height:36px;border-radius:11px;background:linear-gradient(135deg,var(--primary),var(--accent));display:flex;align-items:center;justify-content:center;color:#fff;font-weight:800;font-size:19px;box-shadow:0 8px 18px rgba(91,108,255,0.35);}
  .title{font-size:21px;font-weight:800;letter-spacing:.4px;background:linear-gradient(90deg,var(--primary),var(--accent),var(--cyan));-webkit-background-clip:text;background-clip:text;color:transparent;}
  .sub{color:var(--ink2);font-size:13px;margin-bottom:24px;}
  label{display:block;font-size:13px;color:var(--ink2);margin-bottom:8px;font-weight:600;}
  input{width:100%;padding:13px 15px;background:rgba(255,255,255,0.9);border:1px solid #dfe2f0;border-radius:12px;color:var(--ink);font-size:16px;letter-spacing:2px;outline:none;transition:border-color .2s,box-shadow .2s;}
  input:focus{border-color:var(--primary);box-shadow:0 0 0 4px rgba(91,108,255,0.12);}
  button{margin-top:20px;width:100%;padding:13px;border:none;border-radius:12px;background:linear-gradient(135deg,var(--primary),var(--accent));color:#fff;font-size:15px;font-weight:700;cursor:pointer;box-shadow:0 10px 24px rgba(91,108,255,0.3);transition:transform .12s,box-shadow .2s;}
  button:hover{box-shadow:0 14px 30px rgba(91,108,255,0.42);}
  button:active{transform:translateY(1px);}
  button:disabled{opacity:.6;cursor:default;}
  .err{color:var(--err);font-size:13px;min-height:18px;margin-top:12px;text-align:center;font-weight:600;}
</style>
</head>
<body>
  <div class="ff-halo" aria-hidden="true">
    <span class="ff-ring r1"></span>
    <span class="ff-ring r2"></span>
    <span class="ff-ring r3"></span>
    <canvas id="ff-orbit-canvas"></canvas>
  </div>
  <div class="ff-top" aria-hidden="true"></div>
  <style>
  /* 流萤：自底部上升的萤火（第三种设计，区别于初始化页与控制台） */
  .ff-halo{position:fixed;inset:0;z-index:0;pointer-events:none;display:flex;align-items:center;justify-content:center;}
  .ff-halo .ff-ring{position:absolute;border-radius:50%;border:1px solid rgba(46,230,170,0.20);}
  .ff-halo .r1{width:320px;height:320px;animation:ff-ring 6s ease-in-out infinite;}
  .ff-halo .r2{width:440px;height:440px;animation:ff-ring 8s ease-in-out infinite reverse;}
  .ff-halo .r3{width:580px;height:580px;animation:ff-ring 10s ease-in-out infinite;}
  .ff-halo canvas{position:absolute;width:100%;height:100%;display:block;}
  @keyframes ff-ring{0%,100%{transform:scale(1);opacity:.45;}50%{transform:scale(1.06);opacity:.85;}}
  .ff-top{position:fixed;left:0;right:0;top:0;height:150px;background:linear-gradient(to bottom, rgba(46,230,170,0.12) 0%, rgba(46,230,170,0.04) 40%, transparent 100%);pointer-events:none;z-index:0;}
  @media (prefers-reduced-motion: reduce){ .ff-halo .ff-ring{animation:none !important;} .ff-orbit-canvas{display:none !important;} }
  </style>
  <div class="card">
    <div class="brand">
      <div class="logo">萤</div>
      <div class="title">小流萤 管理后台</div>
    </div>
    <div class="sub">请输入访问口令以进入控制台</div>
    <label for="pw">访问口令</label>
    <input id="pw" type="password" inputmode="numeric" autocomplete="off" placeholder="访问口令" maxlength="64"/>
    <button id="btn" type="button">进入控制台</button>
    <div class="err" id="err"></div>
  </div>
  <script>
    function login(){
      var pw = document.getElementById('pw').value || '';
      var err = document.getElementById('err');
      var btn = document.getElementById('btn');
      err.textContent = '';
      if(!pw){ err.textContent = '请输入访问口令'; return; }
      btn.disabled = true; btn.textContent = '校验中…';
      fetch('/api/console/login', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({password:pw})})
        .then(function(r){ return r.json().then(function(j){ return {ok:r.ok, j:j}; }); })
        .then(function(res){
          if(res.ok && res.j && res.j.ok){
            window.location.replace('/admin/index.html');
          } else {
            err.textContent = (res.j && res.j.error) ? res.j.error : '访问口令错误';
            btn.disabled = false; btn.textContent = '进入控制台';
          }
        })
        .catch(function(){ err.textContent = '请求失败，请重试'; btn.disabled = false; btn.textContent = '进入控制台'; });
    }
    document.getElementById('btn').addEventListener('click', login);
    document.getElementById('pw').addEventListener('keydown', function(e){ if(e.key==='Enter') login(); });
    document.getElementById('pw').focus();
  </script>
  <script>
  /* 登录/设口令页 · 流萤卡片光晕（第三种设计：同心圆环 + 轨道萤光，区别于前面两种） */
  (function(){
    var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var canvas = document.getElementById('ff-orbit-canvas');
    if(!canvas || reduce) return;
    var ctx = canvas.getContext('2d');
    var W=0,H=0,dpr=Math.min(window.devicePixelRatio||1,2);
    function resize(){ W=window.innerWidth; H=window.innerHeight; canvas.width=Math.floor(W*dpr); canvas.height=Math.floor(H*dpr); ctx.setTransform(dpr,0,0,dpr,0,0); }
    resize(); window.addEventListener('resize',resize);
    var COL=['46,230,170','170,255,215','22,200,140'];
    var N=10;
    var dots=[];
    for(var i=0;i<N;i++){
      dots.push({
        a:(Math.PI*2/N)*i + Math.random()*0.3,
        rad:180 + Math.random()*150,
        sp:0.12 + Math.random()*0.18,
        dir:Math.random()<0.5?1:-1,
        r:1.4 + Math.random()*2.2,
        ph:Math.random()*Math.PI*2,
        sp2:0.6 + Math.random()*1.0,
        col:COL[i % COL.length]
      });
    }
    var last=0, frame=33;
    function draw(t){
      if(t-last<frame){ requestAnimationFrame(draw); return; }
      last=t; ctx.clearRect(0,0,W,H);
      var cx=W/2, cy=H/2;
      for(var i=0;i<dots.length;i++){
        var d=dots[i];
        d.a += d.sp*d.dir*0.01;
        d.ph += 0.012*d.sp2;
        var rr = d.rad + Math.sin(d.ph)*14;
        var x = cx + Math.cos(d.a)*rr;
        var y = cy + Math.sin(d.a)*rr;
        var tw = 0.3 + 0.5*(0.5+0.5*Math.sin(d.ph*1.6));
        var g=ctx.createRadialGradient(x,y,0,x,y,d.r*5);
        g.addColorStop(0,'rgba('+d.col+','+tw.toFixed(3)+')');
        g.addColorStop(1,'rgba('+d.col+',0)');
        ctx.fillStyle=g; ctx.beginPath(); ctx.arc(x,y,d.r*5,0,Math.PI*2); ctx.fill();
        ctx.fillStyle='rgba('+d.col+','+Math.min(1,tw+0.16).toFixed(3)+')';
        ctx.beginPath(); ctx.arc(x,y,d.r*0.6,0,Math.PI*2); ctx.fill();
      }
      requestAnimationFrame(draw);
    }
    requestAnimationFrame(draw);
  })();
  </script>
</body>
</html>"""

_CONSOLE_SETPASS_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>小流萤 · 管理后台 · 设置访问口令</title>
<style>
  :root{ --primary:#5b6cff; --primary-deep:#4453e8; --accent:#8c5cff; --cyan:#59d6ff; --ink:#1f2240; --ink2:#4a4f73; --muted:#8b91b5; --err:#e0566b; --ok:#2bb673; }
  *{box-sizing:border-box;}
  body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;font-family:-apple-system,"Segoe UI",Roboto,"Microsoft YaHei",sans-serif;color:var(--ink);background:linear-gradient(135deg,#eef0fa 0%,#f3eefb 100%);overflow:hidden;position:relative;}
  body::before,body::after{content:"";position:absolute;border-radius:50%;filter:blur(70px);opacity:.5;z-index:0;}
  body::before{width:520px;height:520px;background:radial-gradient(circle,#ae8cff 0%,transparent 70%);top:-180px;left:-140px;}
  body::after{width:480px;height:480px;background:radial-gradient(circle,#7fe0ff 0%,transparent 70%);bottom:-180px;right:-140px;}
  .card{position:relative;z-index:1;width:380px;padding:34px 30px;background:rgba(255,255,255,0.72);backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);border:1px solid rgba(255,255,255,0.85);border-radius:20px;box-shadow:0 22px 60px rgba(91,108,255,0.18);}
  .brand{display:flex;align-items:center;gap:11px;margin-bottom:6px;}
  .logo{width:36px;height:36px;border-radius:11px;background:linear-gradient(135deg,var(--primary),var(--accent));display:flex;align-items:center;justify-content:center;color:#fff;font-weight:800;font-size:19px;box-shadow:0 8px 18px rgba(91,108,255,0.35);}
  .title{font-size:21px;font-weight:800;letter-spacing:.4px;background:linear-gradient(90deg,var(--primary),var(--accent),var(--cyan));-webkit-background-clip:text;background-clip:text;color:transparent;}
  .sub{color:var(--ink2);font-size:13px;margin-bottom:24px;}
  label{display:block;font-size:13px;color:var(--ink2);margin-bottom:8px;font-weight:600;}
  input{width:100%;padding:13px 15px;background:rgba(255,255,255,0.9);border:1px solid #dfe2f0;border-radius:12px;color:var(--ink);font-size:16px;letter-spacing:2px;outline:none;transition:border-color .2s,box-shadow .2s;}
  input:focus{border-color:var(--primary);box-shadow:0 0 0 4px rgba(91,108,255,0.12);}
  button{margin-top:20px;width:100%;padding:13px;border:none;border-radius:12px;background:linear-gradient(135deg,var(--primary),var(--accent));color:#fff;font-size:15px;font-weight:700;cursor:pointer;box-shadow:0 10px 24px rgba(91,108,255,0.3);transition:transform .12s,box-shadow .2s;}
  button:hover{box-shadow:0 14px 30px rgba(91,108,255,0.42);}
  button:active{transform:translateY(1px);}
  button:disabled{opacity:.6;cursor:default;}
  .err{color:var(--err);font-size:13px;min-height:18px;margin-top:12px;text-align:center;font-weight:600;}
</style>
</head>
<body>
  <div class="ff-halo" aria-hidden="true">
    <span class="ff-ring r1"></span>
    <span class="ff-ring r2"></span>
    <span class="ff-ring r3"></span>
    <canvas id="ff-orbit-canvas"></canvas>
  </div>
  <div class="ff-top" aria-hidden="true"></div>
  <style>
  /* 流萤：自底部上升的萤火（第三种设计，区别于初始化页与控制台） */
  .ff-halo{position:fixed;inset:0;z-index:0;pointer-events:none;display:flex;align-items:center;justify-content:center;}
  .ff-halo .ff-ring{position:absolute;border-radius:50%;border:1px solid rgba(46,230,170,0.20);}
  .ff-halo .r1{width:320px;height:320px;animation:ff-ring 6s ease-in-out infinite;}
  .ff-halo .r2{width:440px;height:440px;animation:ff-ring 8s ease-in-out infinite reverse;}
  .ff-halo .r3{width:580px;height:580px;animation:ff-ring 10s ease-in-out infinite;}
  .ff-halo canvas{position:absolute;width:100%;height:100%;display:block;}
  @keyframes ff-ring{0%,100%{transform:scale(1);opacity:.45;}50%{transform:scale(1.06);opacity:.85;}}
  .ff-top{position:fixed;left:0;right:0;top:0;height:150px;background:linear-gradient(to bottom, rgba(46,230,170,0.12) 0%, rgba(46,230,170,0.04) 40%, transparent 100%);pointer-events:none;z-index:0;}
  @media (prefers-reduced-motion: reduce){ .ff-halo .ff-ring{animation:none !important;} .ff-orbit-canvas{display:none !important;} }
  </style>
  <div class="card">
    <div class="brand">
      <div class="logo">萤</div>
      <div class="title">小流萤 管理后台</div>
    </div>
    <div class="sub">检测到尚未设置访问口令，请先设置后再进入</div>
    <label for="pw">设置访问口令（6 位数字）</label>
    <input id="pw" type="password" inputmode="numeric" autocomplete="off" placeholder="访问口令" maxlength="64"/>
    <label for="pw2">确认访问口令</label>
    <input id="pw2" type="password" inputmode="numeric" autocomplete="off" placeholder="再次输入" maxlength="64"/>
    <button id="btn" type="button">保存并设置口令</button>
    <div class="err" id="err"></div>
  </div>
  <script>
    function setpass(){
      var pw = document.getElementById('pw').value || '';
      var pw2 = document.getElementById('pw2').value || '';
      var err = document.getElementById('err');
      var btn = document.getElementById('btn');
      err.textContent = '';
      if(pw.length < 6){ err.textContent = '访问口令至少 6 位'; return; }
      if(pw !== pw2){ err.textContent = '两次输入不一致'; return; }
      btn.disabled = true; btn.textContent = '保存中…';
      fetch('/api/console/set-password', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({password:pw, confirm:pw2})})
        .then(function(r){ return r.json().then(function(j){ return {ok:r.ok, j:j}; }); })
        .then(function(res){
          if(res.ok && res.j && res.j.ok){
            err.style.color = '#2bb673'; err.textContent = '口令已设置，正在进入…';
            fetch('/api/console/login', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({password:pw})})
              .then(function(r2){ return r2.json().then(function(j2){ return {ok:r2.ok, j:j2}; }); })
              .then(function(res2){ window.location.replace('/admin/index.html'); })
              .catch(function(){ window.location.replace('/admin/index.html'); });
          } else {
            err.textContent = (res.j && res.j.error) ? res.j.error : '设置失败';
            btn.disabled = false; btn.textContent = '保存并设置口令';
          }
        })
        .catch(function(){ err.textContent = '请求失败，请重试'; btn.disabled = false; btn.textContent = '保存并设置口令'; });
    }
    document.getElementById('btn').addEventListener('click', setpass);
    document.getElementById('pw2').addEventListener('keydown', function(e){ if(e.key==='Enter') setpass(); });
    document.getElementById('pw').focus();
  </script>
  <script>
  /* 登录/设口令页 · 流萤卡片光晕（第三种设计：同心圆环 + 轨道萤光，区别于前面两种） */
  (function(){
    var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var canvas = document.getElementById('ff-orbit-canvas');
    if(!canvas || reduce) return;
    var ctx = canvas.getContext('2d');
    var W=0,H=0,dpr=Math.min(window.devicePixelRatio||1,2);
    function resize(){ W=window.innerWidth; H=window.innerHeight; canvas.width=Math.floor(W*dpr); canvas.height=Math.floor(H*dpr); ctx.setTransform(dpr,0,0,dpr,0,0); }
    resize(); window.addEventListener('resize',resize);
    var COL=['46,230,170','170,255,215','22,200,140'];
    var N=10;
    var dots=[];
    for(var i=0;i<N;i++){
      dots.push({
        a:(Math.PI*2/N)*i + Math.random()*0.3,
        rad:180 + Math.random()*150,
        sp:0.12 + Math.random()*0.18,
        dir:Math.random()<0.5?1:-1,
        r:1.4 + Math.random()*2.2,
        ph:Math.random()*Math.PI*2,
        sp2:0.6 + Math.random()*1.0,
        col:COL[i % COL.length]
      });
    }
    var last=0, frame=33;
    function draw(t){
      if(t-last<frame){ requestAnimationFrame(draw); return; }
      last=t; ctx.clearRect(0,0,W,H);
      var cx=W/2, cy=H/2;
      for(var i=0;i<dots.length;i++){
        var d=dots[i];
        d.a += d.sp*d.dir*0.01;
        d.ph += 0.012*d.sp2;
        var rr = d.rad + Math.sin(d.ph)*14;
        var x = cx + Math.cos(d.a)*rr;
        var y = cy + Math.sin(d.a)*rr;
        var tw = 0.3 + 0.5*(0.5+0.5*Math.sin(d.ph*1.6));
        var g=ctx.createRadialGradient(x,y,0,x,y,d.r*5);
        g.addColorStop(0,'rgba('+d.col+','+tw.toFixed(3)+')');
        g.addColorStop(1,'rgba('+d.col+',0)');
        ctx.fillStyle=g; ctx.beginPath(); ctx.arc(x,y,d.r*5,0,Math.PI*2); ctx.fill();
        ctx.fillStyle='rgba('+d.col+','+Math.min(1,tw+0.16).toFixed(3)+')';
        ctx.beginPath(); ctx.arc(x,y,d.r*0.6,0,Math.PI*2); ctx.fill();
      }
      requestAnimationFrame(draw);
    }
    requestAnimationFrame(draw);
  })();
  </script>
</body>
</html>"""


class _AdminAPIHandler(BaseHTTPRequestHandler):

    server_version = "XiaoLiuyingAdminAPI/1.0"

    def _send_json(self, code, payload, extra_headers=None):

        body = _json.dumps(payload, ensure_ascii=False).encode("utf-8")

        try:

            self.send_response(code)

            self.send_header("Content-Type", "application/json; charset=utf-8")

            self.send_header("Content-Length", str(len(body)))

            self.send_header("Access-Control-Allow-Origin", "*")

            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

            self.send_header("Access-Control-Allow-Headers", "Content-Type")

            self.send_header("Cache-Control", "no-store")

            if extra_headers:
                for _k, _v in extra_headers.items():
                    self.send_header(_k, _v)

            self.end_headers()

            self.wfile.write(body)

        except (ConnectionAbortedError, BrokenPipeError):

            pass  # 客户端已断开，静默忽略

        except OSError as e:

            if getattr(e, "winerror", None) in (10053, 10054) or e.errno == 32:

                return  # 连接被客户端中止

            raise

    def _send_text(self, code, text, content_type="text/plain; charset=utf-8"):

        body = text.encode("utf-8")

        try:

            self.send_response(code)

            self.send_header("Content-Type", content_type)

            self.send_header("Content-Length", str(len(body)))

            self.send_header("Access-Control-Allow-Origin", "*")

            self.end_headers()

            self.wfile.write(body)

        except (ConnectionAbortedError, BrokenPipeError):

            pass  # 客户端已断开，静默忽略

        except OSError as e:

            if getattr(e, "winerror", None) in (10053, 10054) or e.errno == 32:

                return  # 连接被客户端中止

            raise

    def log_message(self, format, *args):

        return  # 静默

    def do_OPTIONS(self):

        self.send_response(204)

        self.send_header("Access-Control-Allow-Origin", "*")

        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")

        self.send_header("Access-Control-Allow-Headers", "Content-Type")

        self.end_headers()

    def _console_token_from_request(self):
        auth = self.headers.get("Authorization") or ""
        if auth.startswith("Bearer "):
            return auth[7:].strip()
        t = self.headers.get("X-Console-Token")
        if t:
            return t.strip()
        cookie = self.headers.get("Cookie") or ""
        for part in cookie.split(";"):
            part = part.strip()
            if part.startswith(_CONSOLE_COOKIE + "="):
                return part.split("=", 1)[1].strip()
        from urllib.parse import urlparse as _up, parse_qs as _pq
        q = _pq(_up(self.path).query)
        tv = q.get("token", [""])[0]
        return tv.strip() if tv else None

    def _console_auth_required(self, path):
        """返回 None 表示放行；否则已发送拦截响应（登录页 / 设口令页 / 401）。"""
        auth = _load_admin_auth()
        has_pw = bool(auth.get("password_hash"))
        token = self._console_token_from_request()
        if path in _CONSOLE_PUBLIC_PATHS:
            return None
        if not has_pw:
            # 尚未设置访问口令：强制先进入「设置访问口令」页面
            if not auth.get("initialized"):
                return None  # 首次启动尚未初始化，放行初始化向导（向导内含设口令步骤）
            # 已初始化但口令缺失（异常/被清空）：每次启动/重启都强制设口令，禁止进入控制台
            if path in ("/admin/index.html", "/admin/setup.html"):
                self._send_setpass_page()
                return "setpass"
            if path.startswith("/api/"):
                if path == "/api/console/set-password":
                    return None  # 设口令接口本身放行
                self._send_json(401, {"ok": False, "error": "尚未设置访问口令，请先设置访问口令", "code": "NO_PASSWORD"})
                return "noauth"
            return None
        # 已设置访问口令：常规登录守卫（每次启动/重启需重新登录，内存令牌重启即清空）
        if path in ("/admin/index.html", "/admin/setup.html"):
            if _console_token_valid(token):
                return None
            self._send_login_page()
            return "login"
        if path.startswith("/api/"):
            if _console_token_valid(token):
                return None
            self._send_json(401, {"ok": False, "error": "未登录或登录已失效，请重新输入访问口令", "code": "NO_AUTH"})
            return "noauth"
        return None

    def _send_login_page(self):
        data = _CONSOLE_LOGIN_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (ConnectionAbortedError, BrokenPipeError, OSError):
            pass


    def _send_setpass_page(self):
        data = _CONSOLE_SETPASS_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (ConnectionAbortedError, BrokenPipeError, OSError):
            pass


    def do_GET(self):

        u = urlparse(self.path)

        path = u.path.rstrip("/") or "/"

        _gate = self._console_auth_required(path)
        if _gate:
            return

        if path == "/api/setup/status":

            auth = _load_admin_auth()

            with _lock:

                appid = str(_status.get("bot_appid") or "").strip()

            has_password = bool(auth.get("password_hash"))

            has_bot = bool(appid)

            initialized = bool(auth.get("initialized", False))

            if has_bot and has_password:

                step = 3

            elif has_password:

                step = 2

            else:

                step = 1

            masked = (appid[:4] + "****" + appid[-4:]) if appid and len(appid) > 8 else (appid or "")

            self._send_json(200, {

                "ok": True,

                "initialized": initialized,

                "has_password": has_password,

                "has_bot": has_bot,

                "appid_masked": masked,

                "environment": str(_status.get("bot_environment") or ""),

                "event_mode": str(_status.get("bot_event_mode") or ""),

                "step": step,

            })

        elif path == "/api/console/password-status":
            # 供控制台「修改访问口令」弹窗判断：是否已设置访问口令。
            auth = _load_admin_auth()
            self._send_json(200, {
                "ok": True,
                "set": bool(auth.get("password_hash")),
                "set_at": str(auth.get("password_set_at") or ""),
            })

        elif path == "/api/music/list":
            self._send_json(200, {"ok": True, "items": _list_music_files(), "cover": "/admin/assets/music/cover.png"})

        elif path.startswith("/api/music/play/"):
            name = path[len("/api/music/play/"):]
            try:
                from urllib.parse import unquote
                name = unquote(name)
            except Exception:
                pass
            name = os.path.basename(name)
            if not name:
                self._send_json(400, {"ok": False, "error": "缺少文件名"})
                return
            ext = os.path.splitext(name)[1].lower()
            if ext not in _MUSIC_ALLOWED_EXTS:
                self._send_json(403, {"ok": False, "error": "不支持的音频格式"})
                return
            fs_path = os.path.join(_MUSIC_DIR, name)
            fs_path = os.path.normpath(fs_path)
            bot_dir = os.path.dirname(os.path.abspath(__file__))
            if not fs_path.startswith(_MUSIC_DIR) or not os.path.isfile(fs_path):
                self._send_json(404, {"ok": False, "error": "文件不存在"})
                return
            _send_audio_stream(self, fs_path)

        elif path == "/api/health":

            try:

                _snap = bot_health.build_snapshot()

                _snap["ok"] = True

                _snap["pid"] = os.getpid()

                self._send_json(200, _snap)

            except Exception as _e:

                self._send_json(200, {"ok": True, "pid": os.getpid(), "error": str(_e)})

        elif path == "/api/runtime-settings":

            q = parse_qs(u.query)
            _rscope = q.get("scope", ["global"])[0] or "global"
            if _rscope not in ("global", "bot", "group"):
                _rscope = "global"
            _rid = q.get("id", [""])[0] or ""
            with _lock:
                if _rscope == "global":
                    _overrides = dict(_runtime_settings.get("global", {}))
                else:
                    _bucket = "bots" if _rscope == "bot" else "groups"
                    _overrides = dict(_runtime_settings.get(_bucket, {}).get(str(_rid), {}) or {})
            _keys = []
            for _k, _sch in RUNTIME_SETTINGS_SCHEMA.items():
                _eff = get_runtime_setting_effective(
                    _k,
                    appid=(str(_rid) if _rscope == "bot" else None),
                    group_id=(str(_rid) if _rscope == "group" else None),
                )
                _keys.append({
                    "key": _k,
                    "type": _sch["type"],
                    "label": _sch.get("label", _k),
                    "desc": _sch.get("desc", ""),
                    "default": _sch["default"],
                    "value": _overrides.get(_k, _sch["default"]),
                    "effective": _eff,
                })
            self._send_json(200, {
                "ok": True,
                "scope": _rscope,
                "id": _rid,
                "keys": _keys,
                "overrides": _overrides,
        })

        elif path == "/api/admin/brand":
            # 管理台品牌信息（侧边栏 logo + 标题），独立于 runtime_settings
            # 存放在 data/admin_brand.json（base64 图可能很大）
            try:
                _brand = _load_admin_brand()
            except Exception as _e:
                self._send_json(500, {"ok": False, "error": "读取品牌信息失败: %s" % _e})
                return
            self._send_json(200, {
                "ok": True,
                "title": _brand.get("title") or "小流萤管理后台",
                "logo": _brand.get("logo") or "",            # base64 data URL 或 空字符串
                "logo_updated_at": _brand.get("logo_updated_at") or 0,
            })

        elif path == "/api/admin/music-fm":
            # 流萤FM 音乐面板自定义：标题/副标题/唱片封面
            try:
                _fm = _load_music_fm()
            except Exception as _e:
                self._send_json(500, {"ok": False, "error": "读取失败: %s" % _e})
                return
            self._send_json(200, {
                "ok": True,
                "title": _fm.get("title") or "流萤FM",
                "subtitle": _fm.get("subtitle") or "与流萤一起走在路上",
                "cover": _fm.get("cover") or "/admin/assets/music/cover.png",
            })

        elif path == "/api/bots":

            try:

                _bs = bot_manager.load_bots()

                # 预生成带桥接信息（真实名称 / 头像 / 实时连通）的列表

                _rows = []

                for _b in _bs:

                    _aid = _b["appid"]

                    _rt = _bot_bridges.get(_aid) or {}

                    _rows.append({

                        "appid": _aid,

                        "appid_masked": bot_manager.mask_appid(_aid),

                        "name": _b.get("name") or "",

                        # 优先级：桥接中的真实名称 / 头像 > 配置里的备注名

                        "name_rt": (_rt.get("name") or _b.get("name") or ""),

                        "avatar": (_rt.get("avatar") or ""),

                        "environment": _b.get("environment", "sandbox"),

                        "event_mode": _b.get("event_mode", "websocket"),

                        "enabled": bool(_b.get("enabled", True)),

                        # 实时连通状态：该 appid 的桥接是否已注册且 api 就绪

                        "connected": (

                            _aid in _bot_bridges

                            and _bot_bridges[_aid].get("api") is not None

                        ),

                    })

                self._send_json(200, {"ok": True, "bots": _rows})

            except Exception as e:

                self._send_json(500, {"ok": False, "error": str(e)})

        elif path == "/api/stats":
            _q = parse_qs(u.query)
            _bot_param = (lambda q: (parse_qs(u.query).get("bot", [""])[0] if q else "") or "")(_q)
            _bot_param = str(_bot_param).strip()
            _resp = _compute_kpi(_bot_param)
            if not _bot_param:
                try:
                    _resp["per_bot"] = _compute_per_bot()
                except Exception:
                    pass
            self._send_json(200, _resp)

        elif path == "/api/series":

            q = parse_qs(u.query)

            try:

                days = int(q.get("days", ["7"])[0])

            except Exception:

                days = 7

            days = max(1, min(days, 90))

            self._send_json(200, {

                "days": days,

                "echo_only": True,

                "hint": "前端请用 localStorage 按日期 key 累积并展示",

            })

        elif path == "/api/announcement":

            with _admin_api_lock:

                self._send_json(200, {"items": list(_announcements)})

        elif path == "/api/known-contacts":

            self._send_json(200, get_known_contacts())

        elif path == "/api/ws-logs":

            q = parse_qs(u.query)

            try:

                limit = int(q.get("limit", ["100"])[0])

            except Exception:

                limit = 100

            limit = max(1, min(limit, _ws_logs_max))

            # 按 bot 过滤（前端 WS 筛选下拉联动；空=全部）
            bot_filter = (parse_qs(u.query).get("bot", [""])[0] or "").strip()

            with _admin_api_lock:

                # 默认按时间倒序（最新在上）；若有 bot 过滤，从全量中筛该 bot 的最后 limit 条
                if bot_filter:
                    src = [r for r in _ws_logs if (r.get("bot") or "").strip() == bot_filter]
                else:
                    src = _ws_logs
                items = list(reversed(src[-limit:]))

                # WebSocket 状态：和 bot 在线状态联动

                connected = bool(_status.get("online", True))

                ws_state = "已连接" if connected else "未连接"

                # 日志中出现的机器人名（供前端「机器人筛选栏」使用，始终返回全量，与当前 bot 过滤无关）

                bots = sorted(set((r.get("bot") or "").strip() for r in _ws_logs if (r.get("bot") or "").strip()))

                payload = {

                    "connected": connected,

                    "ws_state": ws_state,

                    "total": len(_ws_logs),

                    "bots": bots,

                    "items": items,

                }

            self._send_json(200, payload)

        elif path == "/api/bot-console":

            q = parse_qs(u.query)

            try:

                limit = int(q.get("limit", ["1500"])[0])

            except Exception:

                limit = 1500

            limit = max(1, min(limit, _bot_console_max))

            with _bot_console_lock:

                items = list(reversed(_bot_console[-limit:]))

                payload = {

                    "total": len(_bot_console),

                    "items": items,

                }

            self._send_json(200, payload)

        elif path == "/api/message-logs":

            q = parse_qs(u.query)

            try:

                limit = int(q.get("limit", ["500"])[0])

            except Exception:

                limit = 500

            limit = max(1, min(limit, _message_logs_max))

            with _admin_api_lock:

                # 默认按时间倒序（最新在上）；此历史独立于 WS 控制台日志

                _raw_items = list(reversed(_message_logs[-limit:]))

                # 为每条记录解析官方/自定义群名，避免前端直接展示原始 openid
                items = []
                for _it in _raw_items:
                    _copy = dict(_it)
                    _g = _copy.get("group_openid") or _copy.get("scene") or ""
                    _copy["group_name"] = _group_display_name(_g) if _g else ""
                    items.append(_copy)

                connected = bool(_status.get("online", True))

                payload = {

                    "connected": connected,

                    "total": len(_message_logs),

                    "items": items,

                }

            self._send_json(200, payload)

        elif path == "/api/user-profiles":

            # 返回用户在消息监控界面的展示资料：

            #   - 已绑 QQ：原逻辑（昵称 + 头像 + qq）

            #   - 未绑 QQ 但最近消息日志里出现过：用 OIAPI Openid 官方接口反查昵称兜底

            #     （解决单聊会话显示成「C28490EC」这种原始 openid 的问题）

            profiles = {}

            try:

                with _lock:

                    bound = dict(_user_qq_bindings)

                    # 收集最近消息日志里出现的所有 sender openid（去重，按出现时间倒序）

                    seen_openids = []

                    seen_set = set()

                    try:

                        logs = list(_message_logs[-500:])

                    except Exception:

                        logs = []

                    for entry in reversed(logs):

                        sender = str(entry.get("sender") or "").strip()

                        if not sender or sender == "-" or sender in seen_set:

                            continue

                        seen_set.add(sender)

                        seen_openids.append(sender)

                        if len(seen_openids) >= 200:  # 截断，避免单轮过载

                            break

                # 1. 已绑 QQ 用户：原逻辑（昵称/头像/qq，含 DWO/APIBYTE/小渡 等多源合并）

                for openid, qq in bound.items():

                    try:

                        prof = get_user_real_profile(openid)

                    except Exception:

                        prof = None

                    if prof:

                        profiles[openid] = {

                            "nickname": prof.get("nickname") or "",

                            "avatar": prof.get("avatar") or "",

                            "qq": qq,

                        }

                # 2. 未绑 QQ 但最近消息里出现过的用户：用 OIAPI 反查昵称兜底

                #    注：_fetch_nickname_via_oiapi_openid 已有内存缓存；冷启首次较慢，

                #    第二次轮询会因缓存命中而秒回。最多处理前 30 个新 openid，避免阻塞响应。

                # 不再限 30：200 个 openid 全量尝试 OIAPI 反查（缓存命中秒回，未命中走 HTTP）。
                # 解决未绑 QQ 用户的发送者长期显示成 openid[:8] 的问题（2026-08-08）。
                to_fetch = [oid for oid in seen_openids if oid not in profiles]

                fetched_nicks = []

                for oid in to_fetch:

                    try:

                        nick = _fetch_nickname_via_oiapi_openid(oid)

                    except Exception:

                        nick = ""

                    if nick:

                        profiles[oid] = {

                            "nickname": nick,

                            "avatar": "",

                            "qq": "",

                            "source": "oiapi",

                        }

                        fetched_nicks.append((oid, nick))

                # 3. 顺手把 OIAPI 反查到的昵称写回 _members（持久化到 members.json）

                #    这样成员管理页 / 群聊 @ 等场景也能复用，不必每个地方都重新反查。

                if fetched_nicks:

                    try:

                        with _lock:

                            changed = False

                            for oid, nick in fetched_nicks:

                                m = _members.get(oid)

                                if m is not None and (not m.get("nickname") or m.get("nickname") == "-"):

                                    m["nickname"] = nick

                                    m["nickname_source"] = "oiapi"

                                    changed = True

                            if changed:

                                _save_members()

                    except Exception:

                        pass

            except Exception:

                pass

            self._send_json(200, {"profiles": profiles})

        elif path == "/api/group-profiles":

            # 返回已绑定 QQ 群号的群资料（群名/头像），供消息监控界面展示

            profiles = {}

            try:

                with _lock:

                    bound = dict(_group_qq_bindings)

                for openid, qq in bound.items():

                    try:

                        prof = get_group_profile(openid)

                    except Exception:

                        prof = None

                    if prof:

                        profiles[openid] = {

                            "name": prof.get("name") or "",

                            "avatar": prof.get("avatar") or "",

                            "qq": qq,

                        }

            except Exception:

                pass

            self._send_json(200, {"profiles": profiles})

        elif path == "/api/members":

            q = parse_qs(u.query)

            bot = parse_qs(u.query).get("bot", [""])[0]

            source = q.get("source", [""])[0]

            group = q.get("group", [""])[0]

            group_role = q.get("group_role", [""])[0]

            keyword = (q.get("keyword", [""])[0] or "").strip().lower()

            with _admin_api_lock:

                items = list(_members.values())

            groups_set = set()

            for m in items:

                for g in (m.get("groups") or []):

                    groups_set.add(g)

            filtered = []

            for m in items:

                if bot and (m.get("bot") or "") != bot:

                    continue

                srcs = set(m.get("sources") or [])

                if source == "private" and "private" not in srcs:

                    continue

                if source == "group" and "group" not in srcs:

                    continue

                if source == "both" and not ("group" in srcs and "private" in srcs):

                    continue

                if group and group not in (m.get("groups") or []):

                    continue

                if group_role and (m.get("group_role") or "") != group_role:

                    continue

                if keyword:

                    hay = " ".join([

                        str(m.get("nickname", "")),

                        str(m.get("openid", "")),

                        str(m.get("real_qq", "")),

                        str(m.get("bot", "")),

                    ]).lower()

                    if keyword not in hay:

                        continue

                filtered.append(m)

            filtered.sort(key=lambda x: x.get("last_seen", 0), reverse=True)

            out = []

            for idx, m in enumerate(filtered, 1):

                srcs = set(m.get("sources") or [])

                if "group" in srcs and "private" in srcs:

                    src_disp = "全部"

                elif "group" in srcs:

                    src_disp = "群聊"

                elif "private" in srcs:

                    src_disp = "单聊"

                else:

                    src_disp = "-"

                out.append({

                    "idx": idx,

                    "id": m.get("id"),

                    "bot": m.get("bot") or "小流萤",

                    "nickname": m.get("nickname") or "(未命名)",

                    "avatar": m.get("avatar") or "",

                    "code": "M%04d" % (m.get("id") or 0),

                    "openid": m.get("openid"),

                    "real_qq": m.get("real_qq") or "-",

                    "role": m.get("role") or "普通成员",

                    "group_role": m.get("group_role") or "成员",

                    "source": src_disp,

                    "level": m.get("level") or "Lv.1",

                    "msg_count": m.get("msg_count", 0),

                    "groups": m.get("groups") or [],

                    "first_seen": m.get("first_seen", 0),

                    "last_seen": m.get("last_seen", 0),

                })

            # bot_names 严格走运行时真实名（_bot_bridges.name > bots.json.name_rt），

            # 跳过仅有 cfg.name 备注名的，避免「机器人 1905365716」进 dropdown（与 /api/groups 同源修复）。

            bot_names = set()

            _seen_aids = set()

            try:

                for _aid, _br in (_bot_bridges.items() if isinstance(_bot_bridges, dict) else []):

                    _n = (_br.get("name") if isinstance(_br, dict) else "") or ""

                    if _n:

                        bot_names.add(str(_n))

                    _seen_aids.add(str(_aid))

            except Exception:

                pass

            try:

                for _b in bot_manager.load_bots():

                    _aid2 = str(_b.get("appid") or "")

                    if _aid2 in _seen_aids:

                        continue

                    _n = _b.get("name_rt") or ""

                    if _n:

                        bot_names.add(str(_n))

            except Exception:

                pass

            # 当前在线 bot 兜底：避免 0 成员时选择机器人下拉为空

            _cur_appid = str(_status.get("appid") or "").strip()

            _cur_name = ""

            if _cur_appid:

                try:

                    _br = (_bot_bridges.get(_cur_appid) if isinstance(_bot_bridges, dict) else None) or {}

                    _cur_name = (_br.get("name") or "").strip()

                except Exception:

                    pass

            if not _cur_name:

                _cur_name = str(_status.get("bot_name") or "").strip()

            if _cur_name:

                bot_names.add(_cur_name)

            payload = {

                "total": len(out),

                "groups": sorted(groups_set),

                "bots": sorted(bot_names),

                "items": out,

            }

            self._send_json(200, payload)

        elif path == "/api/profiles":

            q = parse_qs(u.query)

            bot = str(parse_qs(u.query).get("bot", [""])[0]).strip()

            with _admin_api_lock:

                items = list(_members.values())

            current_bot = str(_status.get("bot_name") or "小流萤").strip()

            # 2026-08-08: bot 列表以 bots.json 当前真实注册的为准（避免历史 members
            # 残留的 bot 名称重新出现在 dropdown；同时过滤 items 时也用 bots.json
            # 白名单做绝统计（已删除 bot 的原始记录不写入统计）
            try:
                _registered = list(bot_manager.load_bots() or [])
            except Exception:
                _registered = []
            _registered_labels = set()
            for _rb in _registered:
                _lbl = str(_rb.get("name_rt") or _rb.get("name") or _rb.get("appid") or "").strip()
                if _lbl:
                    _registered_labels.add(_lbl)
            bot_names = set(_registered_labels)
            if current_bot and current_bot in _registered_labels:
                bot_names.add(current_bot)
            if not bot_names and current_bot:
                bot_names.add(current_bot)

            if not bot:
                self._send_json(200, {"ok": False, "error": "请先选择机器人", "bots": sorted(bot_names)})
                return

            now = time.time()
            one_day = 86400
            filtered = [m for m in items if (str(m.get("bot") or current_bot).strip()) in bot_names and (str(m.get("bot") or current_bot).strip()) == bot]

            source_counts = {"单聊": 0, "群聊": 0, "全部": 0}

            group_role_counts = {"群主": 0, "管理员": 0, "成员": 0}

            level_counts = {}

            active_today = 0

            for m in filtered:

                srcs = set(m.get("sources") or [])

                if "group" in srcs and "private" in srcs:

                    src = "全部"

                elif "group" in srcs:

                    src = "群聊"

                elif "private" in srcs:

                    src = "单聊"

                else:

                    src = "-"

                if src in source_counts:

                    source_counts[src] += 1

                gr = m.get("group_role") or "成员"

                if gr in group_role_counts:

                    group_role_counts[gr] += 1

                lv = m.get("level") or "Lv.1"

                level_counts[lv] = level_counts.get(lv, 0) + 1

                if (m.get("last_seen") or 0) >= now - one_day:

                    active_today += 1

            self._send_json(200, {

                "ok": True,

                "bot": bot,

                "total": len(filtered),

                "active_today": active_today,

                "source_counts": source_counts,

                "group_role_counts": group_role_counts,

                "level_counts": level_counts,

                "bots": sorted(bot_names),

            })

        elif path == "/api/groups":

            q = parse_qs(u.query)

            bot = str(parse_qs(u.query).get("bot", [""])[0]).strip()

            keyword = (q.get("keyword", [""])[0] or "").strip().lower()

            with _admin_api_lock:

                items = list(_members.values())

            current_bot = str(_status.get("bot_name") or "").strip()


            def _appid_to_name(aid):

                """把 appid 解析为运行时真实机器人名（_bot_bridges.name 优先 -> bots.json）。"""

                if not aid:

                    return ""

                aid = str(aid)

                try:

                    _br = (_bot_bridges.get(aid) if isinstance(_bot_bridges, dict) else None) or {}

                    if _br.get("name"):

                        return _br["name"]

                except Exception:

                    pass

                try:

                    for _b in bot_manager.load_bots():

                        if str(_b.get("appid")) == aid:

                            return (_b.get("name_rt") or _b.get("name") or aid)

                except Exception:

                    pass

                return aid


            # bot_names 优先 _bot_bridges.name（QQ 真实昵称），否则 bots.json.name_rt。

            # 跳过 bots.json 仅有 cfg.name 备注名的，避免「机器人 1905365716」进 dropdown。

            bot_names = set()

            _seen_aids = set()

            try:

                for _aid, _br in (_bot_bridges.items() if isinstance(_bot_bridges, dict) else []):

                    _n = (_br.get("name") if isinstance(_br, dict) else "") or ""

                    if _n:

                        bot_names.add(str(_n))

                    _seen_aids.add(str(_aid))

            except Exception:

                pass

            try:

                for _b in bot_manager.load_bots():

                    _aid2 = str(_b.get("appid") or "")

                    if _aid2 in _seen_aids:

                        continue

                    _n = _b.get("name_rt") or ""

                    if _n:

                        bot_names.add(str(_n))

            except Exception:

                pass

            if current_bot:

                bot_names.add(current_bot)

            # 聚合群统计

            stats = {}

            for m in items:

                for gid in (m.get("groups") or []):

                    if not gid or gid == "-":

                        continue

                    if gid not in stats:

                        stats[gid] = {"members": set(), "msg_count": 0, "last_seen": 0}

                    stats[gid]["members"].add(m.get("openid") or m.get("id"))

                    stats[gid]["msg_count"] += m.get("msg_count", 0)

                    ls = m.get("last_seen") or 0

                    if ls > stats[gid]["last_seen"]:

                        stats[gid]["last_seen"] = ls

            out = []

            for gid, s in sorted(stats.items(), key=lambda x: x[1]["last_seen"], reverse=True):

                real_qq = _group_qq_bindings.get(gid, "")

                prof = _group_profiles.get(gid) or {}

                custom_name = (prof.get("name") or "").strip()

                # 官方群名（缓存命中时优先使用，否则退回自定义名）
                _official_entry = _group_info_cache.get(gid) or {}
                _official_name = (
                    (_official_entry.get("data") or {}).get("name", "").strip()
                    if (_official_entry.get("ts") and (time.time() - _official_entry.get("ts", 0)) < _GROUP_INFO_TTL)
                    else ""
                )
                display_name = _official_name or custom_name or ("群 " + gid[-4:] if len(gid) >= 4 else gid)

                # 按 GROUP_BOT_MAP 拿真实 appid -> 真实机器人名；未登记(为空或在 _shared)标为未分配

                try:

                    _real_aid = (GROUP_BOT_MAP.get(gid) if isinstance(GROUP_BOT_MAP, dict) else "") or ""

                except Exception:

                    _real_aid = ""

                _bot_label = _appid_to_name(_real_aid) if _real_aid else "未分配"

                item = {

                    "id": gid,

                    "bot": _bot_label,

                    "name": display_name,
                    "custom_name": custom_name,
                    "official_name": _official_name,

                    "openid": gid,

                    "real_qq": real_qq or "-",

                    "member_count": len(s["members"]),

                    "message_count": s["msg_count"],

                    "last_message": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(s["last_seen"])) if s["last_seen"] else "-",

                    # QQ 官方群信息（缓存命中时附带，不发请求）
                    "official_info": (
                        (lambda _e: (dict(_e["data"], ts=_e["ts"] * 1000) if _e and _e.get("data") else None))(
                            _group_info_cache.get(gid)
                        )
                        if (time.time() - _group_info_cache.get(gid, {}).get("ts", 0)) < _GROUP_INFO_TTL
                        else None
                    ),

                }

                if bot and item["bot"] != bot:

                    continue

                if keyword:

                    hay = " ".join([item["name"], item["openid"], item["real_qq"], item["bot"]]).lower()

                    if keyword not in hay:

                        continue

                out.append(item)

            self._send_json(200, {"total": len(out), "bots": sorted(bot_names), "items": out})

        elif path == "/api/group/detail":

            q = parse_qs(u.query)

            gid = str(q.get("openid", [""])[0]).strip()

            if not gid:

                self._send_json(400, {"ok": False, "error": "openid 不能为空"})

                return

            with _admin_api_lock:

                items = list(_members.values())

            with _lock:

                prof = dict(_group_profiles.get(gid) or {})

                real_qq = _group_qq_bindings.get(gid, "")

            members_in = []

            msg_count = 0

            last_seen = 0

            for m in items:

                groups = m.get("groups") or []

                if gid not in groups:

                    continue

                members_in.append({

                    "openid": m.get("openid") or m.get("id") or "",

                    "nickname": m.get("nickname") or "(未命名)",

                    "code": m.get("code") or "",

                    "real_qq": m.get("real_qq") or "",

                    "msg_count": m.get("msg_count", 0),

                    "last_seen": m.get("last_seen") or 0,

                })

                msg_count += m.get("msg_count", 0)

                ls = m.get("last_seen") or 0

                if ls > last_seen:

                    last_seen = ls

            members_in.sort(key=lambda x: (x.get("last_seen") or 0), reverse=True)

            current_bot = str(_status.get("bot_name") or "小流萤").strip()

            # 先取官方缓存（供头像兜底），不发起新请求
            _ginfo_entry = _group_info_cache.get(gid)
            _cached_official = (
                _ginfo_entry.get("data")
                if (_ginfo_entry and _ginfo_entry.get("ts") and (time.time() - _ginfo_entry.get("ts", 0)) < _GROUP_INFO_TTL)
                else None
            )

            avatar = prof.get("avatar", "")

            if not avatar and real_qq:

                avatar = _group_avatar_url(real_qq)

            custom_name = (prof.get("name") or "").strip()

            _official_name = (_cached_official.get("name") or "").strip() if _cached_official else ""
            display_name = _official_name or custom_name or ("群 " + gid[-4:] if len(gid) >= 4 else gid)

            self._send_json(200, {

                "ok": True,

                "group": {

                    "openid": gid,

                    "name": display_name,
                    "official_name": _official_name,

                    "custom_name": custom_name,

                    "real_qq": real_qq,

                    "avatar": avatar,

                    "bot": current_bot,

                    "member_count": len(members_in),

                    "message_count": msg_count,

                    "last_message": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_seen)) if last_seen else "-",

                    "last_seen": last_seen,

                    # QQ 官方群信息（缓存命中时附带；未命中不发请求以免触发 30 QPM）
                    "official_info": (
                        (dict(_cached_official, ts=_ginfo_entry["ts"] * 1000) if _cached_official else None)
                    ),

                },

                "members": members_in,

            })

        elif path == "/api/group/official-info":
            # 群基本信息（QQ 官方 GET /v2/groups/{group_openid}/info），带 24h TTL 缓存
            # query: openid=<群openid>&refresh=0|1&appid=<可选 bot appid>
            try:
                _q = parse_qs(u.query)
                _gid = str(_q.get("openid", [""])[0]).strip()
                _refresh = _q.get("refresh", ["0"])[0] in ("1", "true", "True")
                _aid = _q.get("appid", [""])[0].strip() or None
                if not _gid:
                    self._send_json(400, {"ok": False, "error": "openid 不能为空"})
                    return
                _ok, _payload = _fetch_group_info_via_qq_sync(_gid, appid=_aid, force_refresh=_refresh)
                if not _ok:
                    self._send_json(503, {"ok": False, "error": _payload.get("error", "拉取失败")})
                    return
                self._send_json(200, {"ok": True, **_payload})
            except Exception as _e:
                logger.exception("/api/group/official-info 失败")
                self._send_json(500, {"ok": False, "error": str(_e)})

        elif path == "/api/group/refresh-all":
            # 批量刷新所有已知群官方信息（按 GROUP_BOT_MAP 取 appid；遵守 30 QPM）
            length = int(self.headers.get("Content-Length", "0") or 0)
            _raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
            try:
                _payload = _json.loads(_raw) if _raw else {}
            except Exception:
                _payload = {}
            try:
                with _lock:
                    _known = sorted(set(list(GROUP_BOT_MAP.keys()) + list(_group_profiles.keys()) + list(_group_qq_bindings.keys())))
                _results = []
                _ok_count = 0
                _err_count = 0
                for _gid in _known:
                    _aid = GROUP_BOT_MAP.get(_gid) or None
                    _ok, _pl = _fetch_group_info_via_qq_sync(_gid, appid=_aid, force_refresh=True)
                    if _ok:
                        _ok_count += 1
                        _results.append({"openid": _gid, "ok": True, "name": _pl.get("name", "")})
                    else:
                        _err_count += 1
                        _results.append({"openid": _gid, "ok": False, "error": _pl.get("error", "失败")})
                self._send_json(200, {"ok": True, "total": len(_known), "ok_count": _ok_count, "err_count": _err_count, "results": _results})
            except Exception as _e:
                logger.exception("/api/group/refresh-all 失败")
                self._send_json(500, {"ok": False, "error": str(_e)})

        elif path == "/api/group/join-requests":
            # 入群申请列表（QQ 官方 GET /v2/groups/{openid}/join_request_list；30 QPM）
            # query: openid=<群openid>&appid=<bot>&cursor=<分页游标>&limit=<默认20，最大100>
            try:
                _q = parse_qs(u.query)
                _gid = str(_q.get("openid", [""])[0]).strip()
                _aid = _q.get("appid", [""])[0].strip() or None
                _cursor = _q.get("cursor", [""])[0]
                try:
                    _limit = int(_q.get("limit", ["20"])[0])
                except Exception:
                    _limit = 20
                if not _gid:
                    self._send_json(400, {"ok": False, "error": "openid 不能为空"})
                    return
                _ok, _payload = _fetch_join_requests_via_qq_sync(_gid, appid=_aid, cursor=_cursor, limit=_limit)
                if not _ok:
                    self._send_json(503, {"ok": False, "error": _payload.get("error", "拉取失败")})
                    return
                self._send_json(200, {"ok": True, **_payload})
            except Exception as _e:
                logger.exception("/api/group/join-requests 失败")
                self._send_json(500, {"ok": False, "error": str(_e)})

        elif path == "/api/group/bots":
            # 列出全部已配置机器人（appid + 名称 + 是否在线 + 已绑定群数）。
            # 用于「入群申请列表」页改版后按机器人聚合。
            try:
                _bots_out = []
                _seen = set()
                _bridge_map = _bot_bridges if isinstance(_bot_bridges, dict) else {}
                _gbm = dict(GROUP_BOT_MAP) if isinstance(GROUP_BOT_MAP, dict) else {}
                try:
                    _config_bots = list(bot_manager.load_bots() or [])
                except Exception:
                    _config_bots = []
                # 先扫 bots.json（保留顺序，仅启用）
                for _b in _config_bots:
                    _aid = str(_b.get("appid") or "").strip()
                    if not _aid or _aid in _seen:
                        continue
                    _seen.add(_aid)
                    _cfg_name = str(_b.get("name_rt") or _b.get("name") or _aid).strip()
                    _live_name = str((_bridge_map.get(_aid) or {}).get("name") or "").strip()
                    _online = False
                    try:
                        _br = _bridge_map.get(_aid) or {}
                        _online = bool(_br.get("api")) and (_br.get("loop") is not None)
                    except Exception:
                        pass
                    _group_count = sum(1 for _aid2 in _gbm.values() if str(_aid2) == _aid)
                    _bots_out.append({
                        "appid": _aid,
                        "name": _live_name or _cfg_name,
                        "config_name": _cfg_name,
                        "online": _online,
                        "group_count": _group_count,
                    })
                # 加上 GROUP_BOT_MAP 中存在但 bots.json 未列出的孤儿 appid（兜底展示）
                for _gid, _aid2 in _gbm.items():
                    _aid = str(_aid2 or "").strip()
                    if not _aid or _aid in _seen:
                        continue
                    _seen.add(_aid)
                    _live_name = str((_bridge_map.get(_aid) or {}).get("name") or "").strip()
                    _group_count = sum(1 for _aid3 in _gbm.values() if str(_aid3) == _aid)
                    _bots_out.append({
                        "appid": _aid,
                        "name": _live_name or _aid,
                        "config_name": "",
                        "online": False,
                        "group_count": _group_count,
                        "orphan": True,
                    })
                _bots_out.sort(key=lambda b: ((b.get("name") or b.get("appid") or ""), b.get("appid") or ""))
                self._send_json(200, {"ok": True, "bots": _bots_out, "total": len(_bots_out)})
            except Exception as _e:
                logger.exception("/api/group/bots 失败")
                self._send_json(500, {"ok": False, "error": str(_e)})

        elif path == "/api/group/join-requests/aggregate":
            # 聚合探测：按 robot 列出该机器人所有绑定群的入群申请（按群分组）。
            # 通过官方 join_request_list 响应的 code 字段过滤「机器人非管理员」群（自动跳过）；
            # 30 QPM 限制下超额的群标记为 rate_limit；其它错误（桥接/网络/解析）标记为 error。
            # query: appid=<bot> (必填) & limit=<每群最多页数，默认 20>
            try:
                _q = parse_qs(u.query)
                _aid = str(_q.get("appid", [""])[0]).strip()
                if not _aid:
                    self._send_json(400, {"ok": False, "error": "appid 不能为空"})
                    return
                try:
                    _limit = int(_q.get("limit", ["20"])[0])
                except Exception:
                    _limit = 20
                if _limit < 1:
                    _limit = 1
                if _limit > 100:
                    _limit = 100
                _gbm = dict(GROUP_BOT_MAP) if isinstance(GROUP_BOT_MAP, dict) else {}
                _gids = sorted([str(g) for g, a in _gbm.items() if str(a) == _aid])
                if not _gids:
                    self._send_json(200, {
                        "ok": True,
                        "appid": _aid,
                        "total_groups": 0,
                        "ok_groups": 0,
                        "empty_groups": 0,
                        "not_admin_groups": 0,
                        "rate_limit_groups": 0,
                        "error_groups": 0,
                        "groups": [],
                        "items": [],
                        "note": "该机器人当前没有映射到任何群（data/group_bot_map.json 中无记录）；机器人需在群内收发过消息才会被自动登记。",
                    })
                    return
                _groups_out = []
                _ok_groups = 0
                _empty_groups = 0
                _not_admin_groups = 0
                _rate_limit_groups = 0
                _error_groups = 0
                _hit_rate_limit = False
                # botpy 在「机器人非该群管理员」时会抛出 not group admin 异常（非 dict 返回），
                # 无法用官方 code 字段识别，所以异常文本里反向识别：
                _not_admin_markers = (
                    "not group admin",
                    "is not a group admin",
                    "not administrator",
                    "管理员",
                    "permission",
                    "not_admin",
                )
                for _gid in _gids:
                    if _hit_rate_limit:
                        # 本轮 QPM 已耗尽：剩下的群全部标记 rate_limit，不再消耗 _qpm
                        _groups_out.append({
                            "openid": _gid,
                            "name": _group_display_name(_gid),
                            "status": "rate_limit",
                            "items": [],
                            "error": "本轮 QPM 已耗尽（30 QPM / 单机器人）",
                        })
                        _rate_limit_groups += 1
                        continue
                    _ok, _payload = _fetch_join_requests_via_qq_sync(_gid, appid=_aid, cursor="", limit=_limit)
                    if not _ok:
                        _err = str((_payload.get("error", "") if isinstance(_payload, dict) else "") or "失败")
                        _err_lower = _err.lower()
                        _is_not_admin = any(_mk in _err_lower for _mk in _not_admin_markers)
                        if _is_not_admin:
                            _groups_out.append({
                                "openid": _gid,
                                "name": _group_display_name(_gid),
                                "status": "not_admin",
                                "items": [],
                                "error": _err,
                            })
                            _not_admin_groups += 1
                        elif ("频率限制" in _err) or ("qpm" in _err_lower) or ("30 qpm" in _err_lower):
                            _hit_rate_limit = True
                            _rate_limit_groups += 1
                            _groups_out.append({
                                "openid": _gid,
                                "name": _group_display_name(_gid),
                                "status": "rate_limit",
                                "items": [],
                                "error": _err,
                            })
                        else:
                            _error_groups += 1
                            _groups_out.append({
                                "openid": _gid,
                                "name": _group_display_name(_gid),
                                "status": "error",
                                "items": [],
                                "error": _err,
                            })
                        continue
                    # 探测成功，再看官方响应 code（防御 + 应对未来 QQ 调整）
                    _raw = (_payload.get("raw") if isinstance(_payload, dict) else None) or {}
                    if isinstance(_raw, dict):
                        _code = _raw.get("code")
                        if _code not in (None, 0, "0", 0):
                            _groups_out.append({
                                "openid": _gid,
                                "name": _group_display_name(_gid),
                                "status": "not_admin",
                                "items": [],
                                "error_code": _code,
                                "error_message": str(_raw.get("message", "") or ""),
                            })
                            _not_admin_groups += 1
                            continue
                    _items = (_payload.get("items") if isinstance(_payload, dict) else None) or []
                    if not _items:
                        _empty_groups += 1
                        _groups_out.append({
                            "openid": _gid,
                            "name": _group_display_name(_gid),
                            "status": "empty",
                            "items": [],
                            "next_cursor": str(_payload.get("next_cursor", "") or ""),
                        })
                    else:
                        _ok_groups += 1
                        _items_out = []
                        for _it in _items:
                            _it2 = dict(_it)
                            _it2["_group_openid"] = _gid
                            _it2["_group_name"] = _group_display_name(_gid)
                            _it2["_appid"] = _aid
                            _items_out.append(_it2)
                        _groups_out.append({
                            "openid": _gid,
                            "name": _group_display_name(_gid),
                            "status": "ok",
                            "items": _items_out,
                            "next_cursor": str(_payload.get("next_cursor", "") or ""),
                        })
                _status_order = {"ok": 0, "empty": 1, "not_admin": 2, "rate_limit": 3, "error": 4}
                _groups_out.sort(key=lambda g: (_status_order.get(g.get("status"), 9), g.get("name") or "", g.get("openid") or ""))
                self._send_json(200, {
                    "ok": True,
                    "appid": _aid,
                    "total_groups": len(_gids),
                    "ok_groups": _ok_groups,
                    "empty_groups": _empty_groups,
                    "not_admin_groups": _not_admin_groups,
                    "rate_limit_groups": _rate_limit_groups,
                    "error_groups": _error_groups,
                    "groups": _groups_out,
                    "note": ("按群依次探测，已自动跳过「机器人非管理员」的群（官方 code 非 0 即视为非管理员）；单机器人 30 QPM 限制下，超额的群本轮标记为 rate_limit（约 60 秒后会自动恢复），下次点刷新可继续推进。" if _rate_limit_groups else "按群依次探测，已自动跳过「机器人非管理员」的群。"),
                })
            except Exception as _e:
                logger.exception("/api/group/join-requests/aggregate 失败")
                self._send_json(500, {"ok": False, "error": str(_e)})


        elif path == "/api/group/banword-mute":
            # 群禁言/违禁词自动禁言 配置（每群独立：mute_duration + mute_on_banword）
            # GET  查 openid 配置：{ok, openid, config: {mute_duration, mute_on_banword}}
            try:
                _q = parse_qs(u.query)
                _gid = str(_q.get("openid", [""])[0]).strip()
                if not _gid:
                    self._send_json(400, {"ok": False, "error": "openid 不能为空"}); return
                cfg = _get_mute_group_config(_gid)
                self._send_json(200, {"ok": True, "openid": _gid, "config": cfg})
            except Exception as _e:
                logger.exception("/api/group/banword-mute GET 失败")
                self._send_json(500, {"ok": False, "error": str(_e)})
            return

        elif path == "/api/group/banned-mute":
            # 违禁词 + 禁言 综合管理（每群独立：banned_words + mute_duration + mute_on_banword）
            # GET  查 openid 配置：{ok, openid, config:{banned_words, mute_duration, mute_on_banword}}
            try:
                _q = parse_qs(u.query)
                _gid = str(_q.get("openid", [""])[0]).strip()
                if not _gid:
                    self._send_json(400, {"ok": False, "error": "openid 不能为空"}); return
                cfg = _get_banned_mute_config(_gid)
                self._send_json(200, {"ok": True, "openid": _gid, "config": cfg})
            except Exception as _e:
                logger.exception("/api/group/banned-mute GET 失败")
                self._send_json(500, {"ok": False, "error": str(_e)})
            return

        elif path == "/api/group/banword-log":
            # 违禁词拦截日志 GET：?openid=&limit=  -> {ok, logs:[...], total}
            try:
                _q = parse_qs(u.query)
                _gid = str(_q.get("openid", [""])[0]).strip()
                try:
                    _limit = int(_q.get("limit", ["200"])[0] or "200")
                except Exception:
                    _limit = 200
                _logs = _get_banword_log(_gid or None, _limit)
                self._send_json(200, {"ok": True, "logs": _logs, "total": len(_logs)})
            except Exception as _e:
                logger.exception("/api/group/banword-log GET 失败")
                self._send_json(500, {"ok": False, "error": str(_e)})
            return

        elif path == "/api/group/admin-groups":
            # 仅返回机器人是群管理员/群主的群（用于入群申请列表 / 入群审批策略下拉）。
            # 通过官方 `GET /v2/groups/{openid}/bot_state` 探测 member_role，结果按群缓存 10 分钟。
            try:
                _now = time.time()
                _gids = _all_group_openids()
                _groups = []
                _probed_admin = 0
                _probed_member = 0
                _probed_other = 0
                _probed_error = 0
                _probed_skipped = 0
                _cached_hits = 0
                _samples = []
                _bot_state_denied = False
                for _gid in _gids:
                    _cached = _jr_admin_cache.get(_gid)
                    if _cached and (_now - _cached.get("ts", 0)) < _JR_ADMIN_TTL:
                        _role = str(_cached.get("role") or "")
                        _cached_hits += 1
                    else:
                        _role, _definitive, _denied = _probe_bot_admin(_gid)
                        if _denied:
                            _bot_state_denied = True
                        if not _definitive:
                            _probed_skipped += 1
                            if len(_samples) < 5:
                                _samples.append({"openid": _gid[-8:], "name": _group_display_name(_gid), "role": "skipped", "error": "transient(频率限制或桥接不可用)"})
                            continue
                        _jr_admin_cache[_gid] = {"role": _role, "ts": _now}
                    if _role in ("admin", "owner"):
                        _probed_admin += 1
                        _groups.append({"openid": _gid, "name": _group_display_name(_gid), "role": _role})
                    elif _role == "member":
                        _probed_member += 1
                        if len(_samples) < 5:
                            _samples.append({"openid": _gid[-8:], "name": _group_display_name(_gid), "role": "member"})
                    elif _role == "":
                        _probed_other += 1
                        if len(_samples) < 5:
                            _samples.append({"openid": _gid[-8:], "name": _group_display_name(_gid), "role": "non_member_or_unknown"})
                    else:
                        _probed_other += 1
                        if len(_samples) < 5:
                            _samples.append({"openid": _gid[-8:], "name": _group_display_name(_gid), "role": _role})

                # 兜底：bot_state 接口未授权（白名单 11253）导致无法精确判定管理员时，
                # 退化为「机器人所在群」（GROUP_BOT_MAP 中实际收发过消息的群）作为候选，
                # 避免入群申请列表下拉为空。这些群不一定都是管理员，选中后若拉不到申请即说明非管理员。
                _warning = ""
                if not _groups:
                    # bot_state 未确认出任何管理员群：可能接口未授权(11253)/返回异常，或机器人确非管理员。
                    # 兜底到「机器人所在群」（GROUP_BOT_MAP）作为候选，避免下拉为空；这些群不保证都是管理员。
                    if _bot_state_denied:
                        _warning = ("bot_state 接口未授权（仅白名单机器人可用，官方返回 11253），"
                                    "无法精确判定管理员身份。已按「机器人所在群」兜底展示（推断，不保证都是管理员），"
                                    "请到 QQ 开放平台为机器人申请 bot_state 白名单后精确筛选；"
                                    "选中某群后若拉不到入群申请，说明该群机器人并非管理员。")
                    else:
                        _warning = ("bot_state 未确认出任何管理员群（可能机器人确非管理员，或接口返回异常/达频率上限），"
                                    "已按「机器人所在群」兜底展示（推断，不保证都是管理员）；"
                                    "选中某群后若拉不到入群申请，说明该群机器人并非管理员。")
                    _seen = set(_g.get("openid") for _g in _groups)
                    for _gid in _gids:
                        if _gid in _seen:
                            continue
                        # 仅把「机器人在该群有活动」的群作为候选，降低误报
                        if _gid not in GROUP_BOT_MAP:
                            continue
                        _groups.append({"openid": _gid, "name": _group_display_name(_gid), "role": "member", "inferred": True})

                _groups.sort(key=lambda _g: (_g.get("name") or "", _g.get("openid") or ""))
                self._send_json(200, {
                    "ok": True,
                    "groups": _groups,
                    "total_groups": len(_gids),
                    "cached": _cached_hits,
                    "warning": _warning,
                    "stats": {
                        "admin_or_owner": _probed_admin,
                        "member": _probed_member,
                        "other": _probed_other,
                        "skipped": _probed_skipped,
                        "denied": 1 if _bot_state_denied else 0,
                    },
                    "samples": _samples,
                })
            except Exception as _e:
                logger.exception("/api/group/admin-groups 失败")
                self._send_json(500, {"ok": False, "error": str(_e)})

        elif path == _JAS:
            # 入群自动审批策略列表（官方 GET /v2/groups/join_approval_strategy）
            try:
                _q = parse_qs(u.query)
                _aid = _q.get("appid", [""])[0].strip() or None
                try:
                    _limit = int(_q.get("limit", ["20"])[0])
                except Exception:
                    _limit = 20
                _cursor = _q.get("cursor", [""])[0]
                _ok, _payload = _list_join_approval_strategies_via_qq_sync(appid=_aid, limit=_limit, cursor=_cursor)
                if not _ok:
                    self._send_json(503, {"ok": False, "error": _payload.get("error", "拉取失败")})
                    return
                self._send_json(200, {"ok": True, **_payload})
            except Exception as _e:
                logger.exception("/api/group/join-approval/strategies 失败")
                self._send_json(500, {"ok": False, "error": str(_e)})

        elif path == "/api/c2c-users":

            q = parse_qs(u.query)
            bot = str(q.get("bot", [""])[0]).strip()
            keyword = (q.get("keyword", [""])[0] or "").strip().lower()

            def _appid_to_name_c2c(aid):
                if not aid:
                    return ""
                aid = str(aid)
                try:
                    _br = (_bot_bridges.get(aid) if isinstance(_bot_bridges, dict) else None) or {}
                    if _br.get("name"):
                        return _br["name"]
                except Exception:
                    pass
                try:
                    for _b in bot_manager.load_bots():
                        if str(_b.get("appid")) == aid:
                            return (_b.get("name_rt") or _b.get("name") or aid)
                except Exception:
                    pass
                return aid

            with _admin_api_lock:
                items = list(_members.values())

            bot_names = set()
            _seen_aids = set()
            try:
                for _aid, _br in (_bot_bridges.items() if isinstance(_bot_bridges, dict) else []):
                    _n = (_br.get("name") if isinstance(_br, dict) else "") or ""
                    if _n:
                        bot_names.add(str(_n))
                    _seen_aids.add(str(_aid))
            except Exception:
                pass
            try:
                for _b in bot_manager.load_bots():
                    _aid2 = str(_b.get("appid") or "")
                    if _aid2 in _seen_aids:
                        continue
                    _n = _b.get("name_rt") or ""
                    if _n:
                        bot_names.add(str(_n))
            except Exception:
                pass

            out = []
            for m in items:
                srcs = m.get("sources") or []
                if "private" not in srcs:
                    continue
                bot_label = _appid_to_name_c2c(m.get("bot"))
                item = {
                    "openid": m.get("openid") or "",
                    "bot": bot_label,
                    "nickname": m.get("nickname") or "-",
                    "real_qq": m.get("real_qq") or "-",
                    "msg_count": m.get("msg_count") or 0,
                    "last_seen": m.get("last_seen") or 0,
                    "groups": m.get("groups") or [],
                    "avatar": m.get("avatar") or "",
                }
                if bot and item["bot"] != bot:
                    continue
                if keyword:
                    hay = " ".join([item["nickname"], item["openid"], item["real_qq"], item["bot"]]).lower()
                    if keyword not in hay:
                        continue
                out.append(item)

            out.sort(key=lambda x: (x["last_seen"] or 0), reverse=True)
            for it in out:
                it["last_seen"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(it["last_seen"])) if it["last_seen"] else "-"

            self._send_json(200, {"total": len(out), "bots": sorted(bot_names), "items": out})

        elif path == "/api/c2c-user/detail":

            q = parse_qs(u.query)
            openid = str(q.get("openid", [""])[0]).strip()
            if not openid:
                self._send_json(400, {"ok": False, "error": "openid 不能为空"})
                return

            def _appid_to_name_c2c(aid):
                if not aid:
                    return ""
                aid = str(aid)
                try:
                    _br = (_bot_bridges.get(aid) if isinstance(_bot_bridges, dict) else None) or {}
                    if _br.get("name"):
                        return _br["name"]
                except Exception:
                    pass
                try:
                    for _b in bot_manager.load_bots():
                        if str(_b.get("appid")) == aid:
                            return (_b.get("name_rt") or _b.get("name") or aid)
                except Exception:
                    pass
                return aid

            try:
                m = _members.get(openid)
                if not m:
                    self._send_json(404, {"ok": False, "error": "用户不存在"})
                    return
                groups = []
                for gid in (m.get("groups") or []):
                    if not gid or gid == "-":
                        continue
                    prof = _group_profiles.get(gid) or {}
                    gname = (prof.get("name") or "").strip() or ("群 " + gid[-4:] if len(gid) >= 4 else gid)
                    groups.append({"openid": gid, "name": gname})
                self._send_json(200, {
                    "ok": True,
                    "user": {
                        "openid": m.get("openid"),
                        "bot": _appid_to_name_c2c(m.get("bot")),
                        "nickname": m.get("nickname") or "-",
                        "real_qq": m.get("real_qq") or "-",
                        "msg_count": m.get("msg_count") or 0,
                        "last_seen": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(m.get("last_seen") or 0)) if m.get("last_seen") else "-",
                        "avatar": m.get("avatar") or "",
                        "sources": list(m.get("sources") or []),
                    },
                    "groups": groups,
                })
            except Exception as _e:
                import traceback as _tb
                self._send_json(500, {"ok": False, "error": "detail 异常: %s" % _e, "trace": _tb.format_exc()})

        elif path == "/api/checkin-stats":

            q = parse_qs(u.query)

            bot = str(parse_qs(u.query).get("bot", [""])[0]).strip()

            group = str(q.get("group", [""])[0]).strip()

            stats = _compute_checkin_stats(bot_filter=bot, group_filter=group)

            # 按最近签到倒序、连续天数倒序排序

            stats["records"].sort(

                key=lambda r: (str(r.get("last_date") or ""), r.get("continuous", 0)),

                reverse=True

            )

            self._send_json(200, {"ok": True, **stats})

        elif path == "/api/plugins":
            # 列出当前注册表中的所有插件（内置 + 外置），附带 system_enabled（系统总开关）
            try:
                _data = plugin_center.list_installed_plugins()
                _load_errors = plugin_registry.get_external_load_errors() if hasattr(plugin_registry, "get_external_load_errors") else {}
            except Exception as _e:
                self._send_json(500, {"ok": False, "error": str(_e)})
                return
            self._send_json(200, {
                "ok": True,
                "plugins": _data,
                "count": len(_data),
                "load_errors": _load_errors,
            })

        elif path == "/api/plugins/by-category":
            # 按 category 分组返回已装插件（前端按大类聚合显示用）
            try:
                _by_cat = plugin_center.plugins_by_category()
                self._send_json(200, {
                    "ok": True,
                    "by_category": _by_cat,
                    "count": sum(len(v) for v in _by_cat.values()),
                })
            except Exception as _e:
                self._send_json(500, {"ok": False, "code": "backend_error", "error": str(_e)})
            return


        elif path == "/api/plugins/market":
            # 插件市场：默认拉取远程 GitHub 仓库（用户自定义仓库地址热加载生效）；
            # 内置测试插件单独作为 builtin_test 返回，不进入仓库目录。
            try:
                _q = parse_qs(u.query)
                _force = _q.get("force", ["0"])[0] in ("1", "true", "True")
                _payload = plugin_center.get_market_payload(force_remote=_force)
                # 保持向后兼容：旧前端读 catalog / builtin_test / repo_url / remote_source / remote_error
                _payload["remote_source"] = _payload.get("source")
                _err = _payload.get("error")
                _payload["remote_error"] = _err.get("message") if _err else None
                _payload["error_code"] = _err.get("code") if _err else None
                _payload["error_hint"] = _err.get("hint") if _err else None
                self._send_json(200, _payload)
            except Exception as _e:
                self._send_json(500, {"ok": False, "code": "backend_error", "error": str(_e)})
        elif path == "/api/plugins/market/repo":
            # 返回当前生效与默认的仓库配置（前端「运行设置」展示 + 重置按钮）
            try:
                self._send_json(200, plugin_center.get_repo_info())
            except Exception as _e:
                self._send_json(500, {"ok": False, "code": "backend_error", "error": str(_e)})
        elif path == "/api/feature-menu":
            # 读功能菜单配置（用于控制台编辑页）
            try:
                menu = feature_menu.load_menu(force=True)
                ctx = {
                    "is_group": True,
                    "checkin_on": True, "video_on": True, "music_on": True,
                    "image_on": True, "game_on": True, "tools_on": True,
                    "study_on": True, "novel_on": True, "group_admin_on": True,
                    "feedback_enabled": True, "experience_group_enabled": True,
                    "feedback.form_url": "https://docs.qq.com/form/example",
                    "experience_group.url": "https://qun.qq.com/example",
                }
                self._send_json(200, {
                    "ok": True,
                    "menu": menu,
                    "ctx": ctx,
                    "preview_keyboard": feature_menu.build_keyboard(menu, ctx),
                })
            except Exception as _e:
                self._send_json(500, {"ok": False, "code": "backend_error", "error": str(_e)})
        elif path == "/api/feature-menu/reset":
            # 恢复默认
            try:
                ok, msg = feature_menu.reset_menu()
                self._send_json(200 if ok else 500, {"ok": ok, "message": msg})
            except Exception as _e:
                self._send_json(500, {"ok": False, "code": "backend_error", "error": str(_e)})
        elif path == "/api/submenus":
            # 读二级菜单配置（兼容旧版：自动从菜单树取 root.children）
            try:
                data = feature_menu.load_submenus(force=True)
                self._send_json(200, {"ok": True, "submenus": data})
            except Exception as _e:
                self._send_json(500, {"ok": False, "code": "backend_error", "error": str(_e)})
        elif path == "/api/submenus/reset":
            # 恢复默认二级菜单（实际恢复整个菜单树）
            try:
                ok, msg = feature_menu.reset_submenus()
                self._send_json(200 if ok else 500, {"ok": ok, "message": msg})
            except Exception as _e:
                self._send_json(500, {"ok": False, "code": "backend_error", "error": str(_e)})
        elif path == "/api/menu/tree":
            # 读交互菜单树（任意层级）
            try:
                tree = feature_menu.load_tree(force=True)
                ctx = {
                    "is_group": True,
                    "checkin_on": True, "video_on": True, "music_on": True,
                    "image_on": True, "game_on": True, "tools_on": True,
                    "study_on": True, "novel_on": True, "group_admin_on": True,
                    "feedback_enabled": True, "experience_group_enabled": True,
                    "feedback.form_url": "https://docs.qq.com/form/example",
                    "experience_group.url": "https://qun.qq.com/example",
                }
                self._send_json(200, {
                    "ok": True,
                    "tree": tree,
                    "ctx": ctx,
                    "paths": feature_menu.list_all_paths(),
                })
            except Exception as _e:
                self._send_json(500, {"ok": False, "code": "backend_error", "error": str(_e)})
        elif path == "/api/menu/tree/reset":
            # 恢复默认菜单树
            try:
                ok, msg = feature_menu.reset_tree()
                self._send_json(200 if ok else 500, {"ok": ok, "message": msg})
            except Exception as _e:
                self._send_json(500, {"ok": False, "code": "backend_error", "error": str(_e)})
        elif path == "/api/menu/tree/debug":
            # 调试：直接展示原始 yaml 内容 + 解析后的结构（不缓存）
            try:
                import os as _os
                import json as _json
                raw_text = ""
                if _os.path.isfile(feature_menu._TREE_FILE):
                    with open(feature_menu._TREE_FILE, "r", encoding="utf-8") as _f:
                        raw_text = _f.read()
                # 兜底避免 NoneType
                try:
                    raw_parsed = feature_menu._mini_yaml_load(raw_text) if raw_text.strip() else {}
                except Exception as _parse_e:
                    raw_parsed = {"_parse_error": str(_parse_e)}
                # dump 时 JSON 不支持 set / tuple —— 全部转 list
                def _safe(v):
                    try:
                        _json.dumps(v)
                        return v
                    except Exception:
                        return repr(v)
                self._send_json(200, {
                    "ok": True,
                    "file": feature_menu._TREE_FILE,
                    "file_exists": _os.path.isfile(feature_menu._TREE_FILE),
                    "raw_text_len": len(raw_text),
                    "raw_first_200": raw_text[:200],
                    "raw_last_200": raw_text[-200:],
                    "raw_parsed_type": type(raw_parsed).__name__,
                    "raw_parsed_value": _safe(raw_parsed),
                    "raw_parsed_root_type": type(raw_parsed.get("root", None)).__name__ if isinstance(raw_parsed, dict) else None,
                    "raw_parsed_root_value": _safe(raw_parsed.get("root", None)) if isinstance(raw_parsed, dict) else None,
                    "raw_root_banner": (raw_parsed.get("root", {}) or {}).get("banner") if isinstance(raw_parsed, dict) else None,
                    "raw_root_children_count": len((raw_parsed.get("root", {}) or {}).get("children") or {}) if isinstance(raw_parsed, dict) and isinstance(raw_parsed.get("root"), dict) else None,
                })
            except Exception as _e:
                import traceback as _tb
                self._send_json(500, {"ok": False, "code": "backend_error", "error": str(_e), "trace": _tb.format_exc()})
        elif path == "/api/feature-config":

            q = parse_qs(u.query)

            module = q.get("module", [""])[0]

            if not module:

                self._send_json(400, {"ok": False, "error": "缺少 module 参数"})

                return

            defaults = {

                "signin": {

                    "积分最小值": 1, "积分最大值": 10,

                    "金币最小值": 50, "金币最大值": 1000,

                    "每日加金币": 50, "加金币上限": 500,

                    "补签花费金币": 500, "每月补签次数上限": 3, "补签天数范围": 7,

                }

            }

            with _lock:

                cfg = _feature_configs.get(module, {})

                merged = dict(defaults.get(module, {}))

                merged.update(cfg)

            self._send_json(200, {"ok": True, "module": module, "config": merged})

        elif path == "/api/system-config":

            q = parse_qs(u.query)

            query_bot = str(q.get("bot", [""])[0] or "").strip()

            with _lock:

                switches = dict(_system_switches)

                bot_switches = {aid: dict(sw) for aid, sw in _bot_system_switches.items()}

                video_limits = dict(_video_limits)

            # 附带在线 bot 列表，方便前端构建「目标机器人」下拉。
            bots_payload = []

            try:

                for _b in _list_runtime_bots():

                    _aid = str(_b.get("appid") or "").strip()

                    if not _aid:

                        continue

                    _label = _b.get("name_rt") or _b.get("name") or _aid

                    bots_payload.append({"appid": _aid, "name": _label, "connected": bool(_b.get("connected"))})

            except Exception:

                pass

            # 若查询参数指定 bot，附带「当前生效」（bot 覆盖 > 全局 > 默认）开关，便于前端直接渲染

            effective = None

            if query_bot:

                effective = {}

                for _k in list(switches.keys()):

                    if _k in bot_switches.get(query_bot, {}):

                        effective[_k] = bool(bot_switches[query_bot][_k])

                    else:

                        effective[_k] = bool(switches.get(_k, True))

            self._send_json(200, {"ok": True, "switches": switches, "bot_switches": bot_switches, "bots": bots_payload, "current_bot": query_bot, "effective": effective, "video_limits": video_limits})

        elif path == "/api/cache-stats":

            q = parse_qs(u.query)

            keys_param = (q.get("keys", [""])[0] or "").strip()

            keys = None

            if keys_param:

                keys = [k.strip() for k in keys_param.split(",") if k.strip() and k.strip() in _CACHE_CATEGORIES]

            items = _build_cache_stats_items(keys)

            total_bytes = sum(it["size_bytes"] for it in items)

            total_files = sum(it["file_count"] for it in items)

            self._send_json(200, {

                "ok": True,

                "items": items,

                "total_bytes": total_bytes,

                "total_files": total_files,

                "total_size_human": _format_size(total_bytes),

            })

        elif path == "/api/cache-clean-config":

            from datetime import datetime

            _cfg_out = dict(_cache_clean_config)

            try:

                _cfg_out["next_run"] = _next_trigger_after(_cache_clean_config, datetime.now()).strftime("%Y-%m-%d %H:%M") if _cache_clean_config.get("enabled") else ""

            except Exception:

                _cfg_out["next_run"] = ""

            self._send_json(200, {"ok": True, "config": _cfg_out})

        elif path == "/api/backup":
            from datetime import datetime
            q = parse_qs(u.query)
            action = (q.get("action", ["list"])[0] or "list").strip()
            if action == "download":
                name = (q.get("name", [""])[0] or "").strip()
                if not _is_valid_backup_name(name):
                    self._send_json(400, {"ok": False, "error": "非法备份名"})
                    return
                fp = os.path.join(_BACKUP_DIR, name)
                if not os.path.isfile(fp):
                    self._send_json(404, {"ok": False, "error": "备份不存在"})
                    return
                try:
                    with open(fp, "rb") as _fh:
                        _data = _fh.read()
                except OSError as _e:
                    self._send_json(500, {"ok": False, "error": str(_e)})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Length", str(len(_data)))
                self.send_header("Content-Disposition", 'attachment; filename="%s"' % name)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                try:
                    self.wfile.write(_data)
                except (ConnectionAbortedError, BrokenPipeError, OSError):
                    pass
                return
            self._send_json(200, {"ok": True, "backups": _list_backups(), "backup_dir": _BACKUP_DIR})

        elif path == "/api/chime-config":
            q = parse_qs(u.query)

            group = (q.get("group", [""])[0] or "").strip()

            if group:

                self._send_json(200, {"ok": True, "config": get_chime_group_config(group)})

            else:

                with _lock:

                    allg = {gid: dict(c) for gid, c in _chime_groups.items()}

                self._send_json(200, {"ok": True, "config": {}, "groups": allg})

        elif path == "/api/welcome-config":

            q = parse_qs(u.query)

            group = (q.get("group", [""])[0] or "").strip()

            if group:

                self._send_json(200, {"ok": True, "config": get_welcome_group_config(group)})

            else:

                with _lock:

                    allw = {gid: dict(c) for gid, c in _welcome_groups.items()}

                self._send_json(200, {"ok": True, "config": {}, "groups": allw})

        elif path == "/api/checkin-config":

            self._send_json(200, {"ok": True, "config": get_checkin_config()})

        elif path == "/api/qa-rules":

            q = parse_qs(u.query)

            keyword = (q.get("keyword", [""])[0] or "").strip().lower()

            bot = parse_qs(u.query).get("bot", [""])[0]

            page = int(q.get("page", ["1"])[0] or 1)

            page_size = int(q.get("page_size", ["20"])[0] or 20)

            with _lock:

                items = list(_qa_rules)

            if bot:

                items = [r for r in items if r.get("bot") == bot]

            if keyword:

                items = [r for r in items if keyword in (r.get("keyword") or "").lower() or keyword in (r.get("answer") or "").lower()]

            total = len(items)

            start = (page - 1) * page_size

            end = start + page_size

            page_items = items[start:end]

            bots = sorted({r.get("bot") or "小流萤" for r in _qa_rules}) or ["小流萤"]

            self._send_json(200, {"ok": True, "total": total, "page": page, "page_size": page_size, "bots": bots, "items": page_items})

        elif path == "/api/ai/providers":

            _bot = parse_qs(u.query).get("bot", [""])[0]

            with _lock:

                items = list(_load_ai_providers(_bot))

            self._send_json(200, {"ok": True, "providers": items})

        elif path == "/api/ai/sensitive-words":

            with _lock:

                words = list(_sensitive_words)

                auto_revoke = bool(_ai_config.get("auto_revoke", False))

            self._send_json(200, {"ok": True, "words": words, "auto_revoke": auto_revoke})

        elif path == "/api/ai/persona":

            try:

                _bot = parse_qs(u.query).get("bot", [""])[0]

                from modules.ai_persona import get_personas, get_active_persona

                personas = get_personas(_bot)

                active = get_active_persona(_bot)

                self._send_json(200, {

                    "ok": True,

                    "personas": personas,

                    "active_id": (active.get("id") if active else None),

                })

            except Exception as _e:

                logger.warning("[AI人格] GET 失败: %s" % _e)

                self._send_json(200, {"ok": True, "personas": [], "active_id": None})

            return

        elif path == "/api/ai/knowledge":

            try:

                _bot = parse_qs(u.query).get("bot", [""])[0]

                from modules.ai_persona import get_all_knowledge_bases

                bases = get_all_knowledge_bases(_bot)

            except Exception as _e:

                bases = []

                logger.warning("[AI知识库] GET 失败: %s" % _e)

            self._send_json(200, {"ok": True, "bases": bases})

        elif path == "/api/scheduled-tasks":

            q = parse_qs(u.query)

            bot_filter = parse_qs(u.query).get("bot", [""])[0]

            with _scheduler_lock:

                tasks = [dict(t) for t in _scheduled_tasks]

            if bot_filter:

                tasks = [t for t in tasks if (t.get("bot") or "") == bot_filter]

            self._send_json(200, {"ok": True, "tasks": tasks})

        elif path == "/api/admin/list":

            with _admin_api_lock:

                admins = _load_admin_list()

            self._send_json(200, {"ok": True, "admins": admins, "count": len(admins)})

        elif path == "/api/admin/status":

            self._send_json(200, {"ok": True, "status": _get_status_data()})

        elif path == "/":

            # 根路径直接重定向到 /admin/index.html

            self.send_response(302)

            self.send_header("Location", "/admin/index.html")

            self.send_header("Content-Length", "0")

            self.end_headers()

        elif path == "/api/plugins/config":
            # 读取外置插件的自定义配置（GET）
            _q = urllib.parse.urlparse(self.path).query
            _qs = urllib.parse.parse_qs(_q)
            _key = (_qs.get("key") or [""])[0].strip()
            if not _key:
                self._send_json(400, {"ok": False, "code": "bad_request", "error": "缺少 key"})
                return
            try:
                r = plugin_center.get_plugin_config(_key)
            except Exception as _e:
                logger.exception("读取插件配置失败")
                self._send_json(500, {"ok": False, "error": "读取失败：%s" % _e})
                return
            self._send_json(200, r)
            return

        elif path == "/api/plugins/meta":
            # 插件基础信息（_meta）：GET 部分
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query or "")
            want_all = qs.get("all", ["0"])[0] in ("1", "true", "yes")
            if want_all:
                try:
                    data = plugin_center.get_all_plugin_metas()
                    self._send_json(200, {"ok": True, "metas": data})
                except Exception as _e:
                    logger.exception("读取所有插件 meta 失败")
                    self._send_json(500, {"ok": False, "error": "%s" % _e})
                return
            _key = (qs.get("key", [""])[0] or "").strip()
            if not _key:
                self._send_json(400, {"ok": False, "code": "bad_request", "error": "缺少 key"})
                return
            try:
                r = plugin_center.get_plugin_meta(_key)
            except Exception as _e:
                logger.exception("读取插件 meta 失败")
                self._send_json(500, {"ok": False, "error": "%s" % _e})
                return
            status = 200 if r.get("ok") else 400
            self._send_json(status, r)
            return

        elif path == "/favicon.ico":
            # 浏览器自动请求 favicon，返回 204 避免 404 控制台噪声（所有管理页通用）
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        else:

            # 静态文件服务：admin/ 目录

            self._serve_static(path)

    def _serve_static(self, path):

        """提供 admin/ 目录下的静态文件（HTML / JS / CSS / 字体等）。"""

        # 拒绝路径穿越

        if ".." in path or path.startswith("//"):

            self._send_json(403, {"error": "forbidden", "path": path})

            return

        # 根路径或 /admin 跳到 /admin/index.html

        if path == "/admin" or path == "/admin/":

            self.send_response(302)

            self.send_header("Location", "/admin/index.html")

            self.send_header("Content-Length", "0")

            self.end_headers()

            return

        # 去掉前导 /

        rel = path.lstrip("/")

        # 把 urlencoded 中文路径还原

        try:

            from urllib.parse import unquote

            rel = unquote(rel)

        except Exception:

            pass

        # 解析真实文件路径（相对 bot 工作目录）

        bot_dir = os.path.dirname(os.path.abspath(__file__))

        fs_path = os.path.join(bot_dir, rel)

        fs_path = os.path.normpath(fs_path)

        # 必须在 bot 目录内

        if not fs_path.startswith(bot_dir):

            self._send_json(403, {"error": "forbidden", "path": path})

            return

        if not os.path.isfile(fs_path):

            self._send_json(404, {"error": "not_found", "path": path})

            return

        # 根据扩展名推断 mime

        ext = os.path.splitext(fs_path)[1].lower()

        mime = {

            ".html": "text/html; charset=utf-8",

            ".htm": "text/html; charset=utf-8",

            ".js": "application/javascript; charset=utf-8",

            ".css": "text/css; charset=utf-8",

            ".json": "application/json; charset=utf-8",

            ".svg": "image/svg+xml",

            ".png": "image/png",

            ".jpg": "image/jpeg",

            ".jpeg": "image/jpeg",

            ".gif": "image/gif",

            ".webp": "image/webp",

            ".bmp": "image/bmp",

            ".ico": "image/x-icon",

            ".mp3": "audio/mpeg",

            ".wav": "audio/wav",

            ".m4a": "audio/mp4",

            ".ogg": "audio/ogg",

            ".amr": "audio/amr",

            ".mp4": "video/mp4",

            ".webm": "video/webm",

            ".mov": "video/quicktime",

            ".ttf": "font/ttf",

            ".woff": "font/woff",

            ".woff2": "font/woff2",

        }.get(ext, "application/octet-stream")

        try:

            with open(fs_path, "rb") as f:

                data = f.read()

            self.send_response(200)

            self.send_header("Content-Type", mime)

            self.send_header("Content-Length", str(len(data)))

            self.send_header("Cache-Control", "no-store")

            self.end_headers()

            self.wfile.write(data)

        except Exception as e:

            self._send_json(500, {"error": "read_failed", "detail": str(e)})

    def do_POST(self):

        u = urlparse(self.path)

        path = u.path.rstrip("/") or "/"

        _gate = self._console_auth_required(path)
        if _gate:
            return

        if path == "/api/plugins/market/repo/update":
            # 更新运行时仓库基址 + 子目录（不落盘，bot 重启后回退到 config.yaml 默认）
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                raw = self.rfile.read(length) if length > 0 else b"{}"
                _body = _json.loads(raw.decode("utf-8", errors="replace") or "{}")
                _url = (_body.get("repo_url") or "").strip()
                _subdir = (_body.get("subdir") or "").strip()
                plugin_registry.set_remote_market_base(_url, subdir=_subdir or None)
                self._send_json(200, plugin_center.get_repo_info())
            except Exception as _e:
                self._send_json(500, {"ok": False, "code": "backend_error", "error": str(_e)})
            return

        if path == "/api/announcement":

            length = int(self.headers.get("Content-Length", "0") or 0)

            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"

            try:

                payload = _json.loads(raw) if raw else {}

            except Exception:

                payload = {}

            body = str(payload.get("body") or "").strip()

            tag = str(payload.get("tag") or "通知")[:16]

            if not body:

                self._send_json(400, {"ok": False, "error": "公告内容不能为空"})

                return

            scope = str(payload.get("scope") or "all")[:16]

            if scope not in ("all", "groups", "persons", "custom"):

                scope = "all"

            item = {

                "tag": tag,

                "body": body[:500],

                "ts": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),

                "scope": scope,

                "target_count": int(payload.get("target_count") or 0),

            }

            with _admin_api_lock:

                _announcements.insert(0, item)

                del _announcements[50:]

            # 定向发布：若指定了受众（chat_id 列表）且机器人已就绪，则真正推送到 QQ

            targets = payload.get("targets")

            results = None

            if isinstance(targets, list) and targets:

                ok_list, fail_list = _push_announcement(targets, item["body"])

                results = {"total": len(targets), "ok": len(ok_list), "failed": len(fail_list), "failed_list": fail_list}

            self._send_json(200, {"ok": True, "item": item, "push": results})

        elif path == "/api/ws-logs/clear":

            with _admin_api_lock:

                _ws_logs.clear()

                append_ws_log("小流萤", "系统", "system", "-", "-", "日志已清空", to_message=False)

            self._send_json(200, {"ok": True, "total": len(_ws_logs)})

        elif path == "/api/bot-console/clear":

            with _bot_console_lock:

                _bot_console.clear()

            self._send_json(200, {"ok": True, "total": 0})

        elif path == "/api/send-message":

            length = int(self.headers.get("Content-Length", "0") or 0)

            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"

            try:

                payload = _json.loads(raw) if raw else {}

            except Exception:

                payload = {}

            chat_id = str(payload.get("chat_id") or "").strip()

            msg_type = str(payload.get("msg_type") or "text").strip().lower()

            content = str(payload.get("content") or "")

            file_data = payload.get("file_data") or ""

            file_name = str(payload.get("file_name") or "")

            if not chat_id:

                self._send_json(400, {"ok": False, "error": "缺少 chat_id"})

                return

            if msg_type not in ("text", "emoji", "image"):

                self._send_json(400, {"ok": False, "error": "不支持的消息类型: %s" % msg_type})

                return

            media_url = ""

            file_bytes = None

            if msg_type in ("image",):

                if not file_data:

                    self._send_json(400, {"ok": False, "error": "缺少媒体文件数据"})

                    return

                try:

                    if isinstance(file_data, str) and file_data.startswith("data:") and "," in file_data:

                        b64 = file_data.split(",", 1)[1]

                    else:

                        b64 = file_data

                    file_bytes = base64.b64decode(b64)

                except Exception as e:

                    self._send_json(400, {"ok": False, "error": "文件解码失败: %s" % e})

                    return

                if not file_bytes:

                    self._send_json(400, {"ok": False, "error": "媒体文件为空"})

                    return

                try:

                    ext = os.path.splitext(file_name)[1].lower().lstrip(".")

                    if not _safe_ext(ext):

                        ext = _media_ext(msg_type)

                    media_url = _save_media_file(file_bytes, ext)

                except Exception as e:

                    self._send_json(500, {"ok": False, "error": "媒体保存失败: %s" % e})

                    return

            ok, err = _send_console_message(chat_id, msg_type, content, file_bytes)

            if not ok:

                self._send_json(500, {"ok": False, "error": err})

                return

            # 下行消息已由 _send_console_message -> modules/common.py 中的发送函数通过

            # record_bot_reply 记录到消息中心，这里不再重复 append_ws_log。

            self._send_json(200, {"ok": True, "media_url": media_url, "msg_type": msg_type})

        elif path == "/api/setup/password":

            length = int(self.headers.get("Content-Length", "0") or 0)

            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"

            try:

                payload = _json.loads(raw) if raw else {}

            except Exception:

                payload = {}

            pwd = str(payload.get("password") or "").strip()

            if not re.fullmatch(r"\d{6}", pwd):

                self._send_json(400, {"ok": False, "error": "请输入 6 位数字口令"})

                return

            auth = _load_admin_auth()

            auth["password_hash"] = _hash_password(pwd)

            auth["password_set_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

            ok = _save_admin_auth(auth)

            if not ok:

                self._send_json(500, {"ok": False, "error": "保存失败"})

                return

            self._send_json(200, {"ok": True, "message": "访问口令已设置"})

        elif path == "/api/setup/complete":

            auth = _load_admin_auth()

            auth["initialized"] = True

            auth["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

            ok = _save_admin_auth(auth)

            if not ok:

                self._send_json(500, {"ok": False, "error": "保存失败"})

                return

            self._send_json(200, {"ok": True, "message": "初始化已完成"})

        elif path == "/api/console/login":
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
            try:
                payload = _json.loads(raw) if raw else {}
            except Exception:
                payload = {}
            pwd = str(payload.get("password") or "").strip()
            _auth = _load_admin_auth()
            if not _auth.get("password_hash"):
                self._send_json(403, {"ok": False, "error": "尚未设置访问口令，请先完成初始化向导"})
                return
            if _hash_password(pwd) != _auth["password_hash"]:
                self._send_json(401, {"ok": False, "error": "访问口令错误"})
                return
            import secrets
            _token = secrets.token_hex(32)
            with _CONSOLE_SESSIONS_LOCK:
                _CONSOLE_SESSIONS[_token] = time.time() + _CONSOLE_TOKEN_TTL
            self._send_json(200, {"ok": True, "message": "登录成功"},
                             extra_headers={"Set-Cookie": "%s=%s; Path=/; Max-Age=%d; HttpOnly; SameSite=Lax" % (_CONSOLE_COOKIE, _token, _CONSOLE_TOKEN_TTL)})
            return

        elif path == "/api/console/logout":
            _tok = self._console_token_from_request()
            if _tok:
                with _CONSOLE_SESSIONS_LOCK:
                    _CONSOLE_SESSIONS.pop(_tok, None)
            self._send_json(200, {"ok": True},
                             extra_headers={"Set-Cookie": "%s=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax" % _CONSOLE_COOKIE})
            return

        elif path == "/api/console/set-password":
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
            try:
                payload = _json.loads(raw) if raw else {}
            except Exception:
                payload = {}
            pwd = str(payload.get("password") or "").strip()
            confirm = str(payload.get("confirm") or "").strip()
            _auth = _load_admin_auth()
            if _auth.get("password_hash"):
                self._send_json(403, {"ok": False, "error": "访问口令已设置，请先登录后再修改"})
                return
            if len(pwd) < 6:
                self._send_json(400, {"ok": False, "error": "访问口令至少 6 位"})
                return
            if pwd != confirm:
                self._send_json(400, {"ok": False, "error": "两次输入的访问口令不一致"})
                return
            _auth["password_hash"] = _hash_password(pwd)
            if not _save_admin_auth(_auth):
                self._send_json(500, {"ok": False, "error": "保存失败"})
                return
            self._send_json(200, {"ok": True, "message": "访问口令已设置"})
            return

        elif path == "/api/console/change-password":
            # 修改访问口令：需已登录 + 校验当前口令 + 新口令 6 位纯数字；
            # 成功后清空所有会话令牌并请求整机重启，强制使用新口令重新登录。
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
            try:
                payload = _json.loads(raw) if raw else {}
            except Exception:
                payload = {}
            cur = str(payload.get("current_password") or "").strip()
            new = str(payload.get("new_password") or "").strip()
            confirm = str(payload.get("confirm") or "").strip()
            _auth = _load_admin_auth()
            if not _auth.get("password_hash"):
                self._send_json(403, {"ok": False, "error": "尚未设置访问口令，请先设置访问口令"})
                return
            if not cur:
                self._send_json(400, {"ok": False, "error": "请输入当前访问口令"})
                return
            if _hash_password(cur) != _auth["password_hash"]:
                self._send_json(401, {"ok": False, "error": "当前访问口令错误"})
                return
            if not re.fullmatch(r"\d{6}", new):
                self._send_json(400, {"ok": False, "error": "新访问口令须为 6 位数字"})
                return
            if new != confirm:
                self._send_json(400, {"ok": False, "error": "两次输入的新访问口令不一致"})
                return
            _auth["password_hash"] = _hash_password(new)
            _auth["password_set_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            if not _save_admin_auth(_auth):
                self._send_json(500, {"ok": False, "error": "保存失败"})
                return
            # 清空内存会话令牌（重启后亦会清空），强制所有用户重新登录
            with _CONSOLE_SESSIONS_LOCK:
                _CONSOLE_SESSIONS.clear()
            # 请求整机重启：看门狗会在 _PENDING_DELAY 秒后真正重启，
            # 重启后内存令牌清空，用户必须输入新口令才能进入控制台。
            _restart_bot()
            self._send_json(200, {"ok": True, "message": "访问口令已修改，机器人即将重启，请稍后用新口令登录", "restart": True})
            return

        elif path == "/api/music/upload":
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
            try:
                payload = _json.loads(raw) if raw else {}
            except Exception:
                payload = {}
            filename = str(payload.get("filename") or "").strip()
            data = payload.get("data") or ""
            if not filename or not data:
                self._send_json(400, {"ok": False, "error": "缺少文件名或音频数据"})
                return
            ext = os.path.splitext(filename)[1].lower()
            if ext not in _MUSIC_ALLOWED_EXTS:
                self._send_json(400, {"ok": False, "error": "仅支持上传 %s 格式的音频" % ", ".join(sorted(_MUSIC_ALLOWED_EXTS))})
                return
            try:
                os.makedirs(_MUSIC_DIR, exist_ok=True)
            except Exception as e:
                self._send_json(500, {"ok": False, "error": "创建音乐目录失败", "detail": str(e)})
                return
            safe_name = _safe_music_filename(filename)
            if not safe_name:
                self._send_json(400, {"ok": False, "error": "文件名不合法"})
                return
            try:
                if isinstance(data, str) and "," in data:
                    b64 = data.split(",", 1)[1]
                else:
                    b64 = data
                file_bytes = base64.b64decode(b64)
            except Exception as e:
                self._send_json(400, {"ok": False, "error": "音频数据解码失败", "detail": str(e)})
                return
            try:
                save_path = os.path.join(_MUSIC_DIR, safe_name)
                with open(save_path, "wb") as f:
                    f.write(file_bytes)
            except Exception as e:
                self._send_json(500, {"ok": False, "error": "保存音频失败", "detail": str(e)})
                return
            self._send_json(200, {
                "ok": True,
                "message": "上传成功",
                "item": {
                    "name": safe_name,
                    "size": len(file_bytes),
                    "url": "/api/music/play/" + safe_name,
                },
            })
            return

        elif path in ("/api/bots", "/api/bots/add", "/api/bots/update"):

            length = int(self.headers.get("Content-Length", "0") or 0)

            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"

            try:

                payload = _json.loads(raw) if raw else {}

            except Exception:

                payload = {}

            appid = str(payload.get("appid") or "").strip()

            secret = str(payload.get("secret") or "").strip()

            environment = str(payload.get("environment") or "sandbox").strip().lower()

            event_mode = str(payload.get("event_mode") or "websocket").strip().lower()

            name = str(payload.get("name") or "").strip()

            enabled = payload.get("enabled", True)

            if environment not in ("sandbox", "production"):

                environment = "sandbox"

            if event_mode not in ("websocket", "webhook"):

                event_mode = "websocket"

            if not appid or not secret:

                self._send_json(400, {"ok": False, "error": "AppID 和 Secret 不能为空"})

                return

            ok1, err1 = bot_manager.upsert_bot(appid, secret, environment, event_mode, name, enabled)

            if not ok1:

                self._send_json(500, {"ok": False, "error": err1})

                return

            append_ws_log("小流萤", "系统", "system", "-", "-",

                "机器人已保存 [AppID: %s, 环境: %s, 事件: %s]" % (appid, environment, event_mode))

            # 保存后自动热重载：按 appid 粒度启停 bot 线程，不重启整个进程。
            # 用户在「机器人管理」保存凭证后会立即连接 / 重连，不必再点重启。
            try:
                _bot_module = _get_bot_module()
                _diff = _bot_module._apply_bots_diff()
                _msg = "已保存并即时生效 (added=%s, removed=%s, reloaded=%s)" % (
                    _diff.get("added"), _diff.get("removed"), _diff.get("reloaded"))
                self._send_json(200, {"ok": True, "message": _msg, "diff": _diff,
                    "appid": appid, "environment": environment, "event_mode": event_mode})
            except Exception as _e:
                logger.exception("/api/bots 保存后热重载失败")
                self._send_json(200, {"ok": True,
                    "message": "已保存，但热重载失败：%s（可在列表中点「全量刷新」重试）" % _e,
                    "appid": appid, "environment": environment, "event_mode": event_mode})

        elif path == "/api/bots/set-enabled":
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
            try:
                payload = _json.loads(raw) if raw else {}
            except Exception:
                payload = {}
            appid = str(payload.get("appid") or "").strip()
            enabled = bool(payload.get("enabled", False))
            if not appid:
                self._send_json(400, {"ok": False, "error": "appid 不能为空"})
                return
            ok1, err1 = bot_manager.set_enabled(appid, enabled)
            if not ok1:
                self._send_json(400, {"ok": False, "error": err1})
                return
            # 即时热重载（按 appid 粒度启停，其他 bot 不受影响）
            try:
                _bot_module = _get_bot_module()
                _diff = _bot_module._apply_bots_diff()
                _msg = "已" + ("启用" if enabled else "禁用") + "，即时生效 (added=%s, removed=%s, reloaded=%s)" % (
                    _diff.get("added"), _diff.get("removed"), _diff.get("reloaded"),
                )
                self._send_json(200, {"ok": True, "message": _msg, "diff": _diff})
            except Exception as _e:
                logger.exception("启用状态变更后热重载失败")
                self._send_json(200, {"ok": True, "message": "已保存，热重载失败：%s" % _e})

        elif path == "/api/plugins/set-enabled":
            # 切换插件启用状态。body: {key, enabled, kind?}
            # kind=system: 写系统总开关（_system_switches，bot 主代码生效），并自动联动 _EXTERNAL_ENABLED
            # kind=plugin: 只写插件级开关（仅外置 _EXTERNAL_ENABLED）
            # 默认 all: 两个都写（兼容旧调用）
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
                payload = _json.loads(raw) if raw else {}
            except Exception:
                payload = {}
            key = (payload.get("key") or "").strip()
            enabled = bool(payload.get("enabled", True))
            kind = (payload.get("kind") or "all").strip()
            if not key:
                self._send_json(400, {"ok": False, "code": "bad_request", "error": "缺少 key"})
                return
            r = plugin_center.set_enabled(key, enabled, kind=kind)
            status = 200 if r.get("ok") else 400
            self._send_json(status, r)

        elif path == "/api/plugins/config":
            # 保存外置插件的自定义配置（POST）
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
                payload = _json.loads(raw) if raw else {}
            except Exception:
                payload = {}
            _key = (payload.get("key") or "").strip()
            _values = payload.get("values") or {}
            if not _key:
                self._send_json(400, {"ok": False, "code": "bad_request", "error": "缺少 key"})
                return
            if not isinstance(_values, dict):
                self._send_json(400, {"ok": False, "code": "bad_request", "error": "values 必须是 dict"})
                return
            try:
                r = plugin_center.save_plugin_config(_key, _values)
            except Exception as _e:
                logger.exception("保存插件配置失败")
                self._send_json(500, {"ok": False, "error": "保存失败：%s" % _e})
                return
            status = 200 if r.get("ok") else 400
            self._send_json(status, r)

        elif path == "/api/plugins/meta":
            # 插件基础信息（_meta）：POST 保存（GET 路由在 do_GET 里）
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
                payload = _json.loads(raw) if raw else {}
            except Exception:
                payload = {}
            _key = (payload.get("key") or "").strip()
            _meta = payload.get("meta") or {}
            if not _key:
                self._send_json(400, {"ok": False, "code": "bad_request", "error": "缺少 key"})
                return
            if not isinstance(_meta, dict):
                self._send_json(400, {"ok": False, "code": "bad_request", "error": "meta 必须是 dict"})
                return
            try:
                r = plugin_center.save_plugin_meta(_key, _meta)
            except Exception as _e:
                logger.exception("保存插件 meta 失败")
                self._send_json(500, {"ok": False, "error": "%s" % _e})
                return
            status = 200 if r.get("ok") else 400
            self._send_json(status, r)

        elif path == "/api/feature-menu":
            # 保存功能菜单配置（POST）
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
                payload = _json.loads(raw) if raw else {}
            except Exception:
                payload = {}
            menu = payload.get("menu")
            if not isinstance(menu, dict):
                self._send_json(400, {"ok": False, "code": "bad_request", "error": "缺少 menu 对象"})
                return
            ok, msg = feature_menu.save_menu(menu)
            self._send_json(200 if ok else 500, {"ok": ok, "message": msg})

        elif path == "/api/submenus":
            # 保存二级菜单配置（POST，兼容旧版：内部会写入菜单树）
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
                payload = _json.loads(raw) if raw else {}
            except Exception:
                payload = {}
            data = payload.get("submenus")
            if not isinstance(data, dict):
                self._send_json(400, {"ok": False, "code": "bad_request", "error": "缺少 submenus 对象"})
                return
            ok, msg = feature_menu.save_submenus(data)
            self._send_json(200 if ok else 500, {"ok": ok, "message": msg})

        elif path == "/api/menu/tree":
            # 保存交互菜单树（任意层级）
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
                payload = _json.loads(raw) if raw else {}
            except Exception:
                payload = {}
            tree = payload.get("tree")
            if not isinstance(tree, dict):
                self._send_json(400, {"ok": False, "code": "bad_request", "error": "缺少 tree 对象"})
                return
            ok, msg = feature_menu.save_tree(tree)
            self._send_json(200 if ok else 500, {"ok": ok, "message": msg})

        elif path == "/api/bots/delete":

            length = int(self.headers.get("Content-Length", "0") or 0)

            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"

            try:

                payload = _json.loads(raw) if raw else {}

            except Exception:

                payload = {}

            appid = str(payload.get("appid") or "").strip()

            if not appid:

                self._send_json(400, {"ok": False, "error": "appid 不能为空"})

                return

            ok1, err1 = bot_manager.remove_bot(appid)

            if not ok1:

                self._send_json(400, {"ok": False, "error": err1})

                return

            # 即时停掉该 bot 客户端线程
            try:
                _bot_module = _get_bot_module()
                _diff = _bot_module._apply_bots_diff()
                self._send_json(200, {"ok": True, "message": "已删除并即时停用", "diff": _diff})
            except Exception as _e:
                logger.exception("删除后热重载失败")
                self._send_json(200, {"ok": True, "message": "已保存，删除即时停用失败：%s" % _e})

        elif path == "/api/bots/reload":
            # 全量热重载：按 bots.json 与当前运行线程 diff，按 appid 粒度启停；
            # 不再触发整进程 _restart_bot()，避免其他 bot 全部断连。
            try:
                _bot_module = _get_bot_module()
                _diff = _bot_module._apply_bots_diff()
                self._send_json(200, {
                    "ok": True,
                    "message": "已应用配置变更 (added=%s, removed=%s, reloaded=%s, kept=%s)" % (
                        len(_diff.get("added", [])), len(_diff.get("removed", [])),
                        len(_diff.get("reloaded", [])), len(_diff.get("kept", [])),
                    ),
                    "diff": _diff,
                })
            except Exception as _e:
                logger.exception("/api/bots/reload 热重载失败")
                self._send_json(500, {"ok": False, "error": "热重载失败：%s" % _e})

        elif path == "/api/plugins/reload":
            # 手动触发外置插件热加载（等价于控制台「🔄 热加载」按钮）。
            # force=True：忽略 mtime，重新加载所有 plugins/ 下外置插件。
            try:
                _stats = plugin_registry.reload_external_plugins(force=True)
                self._send_json(200, {"ok": True, "message": "外置插件已热加载", "stats": _stats})
            except Exception as _e:
                logger.exception("/api/plugins/reload 失败")
                self._send_json(500, {"ok": False, "error": "热加载失败：%s" % _e})


        elif path in ("/api/plugins/market/install", "/api/plugins/market/uninstall"):
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
            try:
                payload = _json.loads(raw) if raw else {}
            except Exception:
                payload = {}
            _key = str(payload.get("key") or "").strip()
            if not _key:
                self._send_json(400, {"ok": False, "code": "bad_request", "error": "缺少 key 参数"})
                return
            try:
                if path == "/api/plugins/market/install":
                    _raw_url = str(payload.get("raw_url") or "").strip()
                    _res = plugin_center.install_plugin(_key, _raw_url or None)
                else:
                    _res = plugin_center.uninstall_plugin(_key)
            except Exception as _e:
                logger.exception("%s 失败" % path)
                self._send_json(500, {"ok": False, "code": "backend_error", "error": str(_e)})
                return
            if not _res.get("ok"):
                self._send_json(400, _res)
                return
            _verb = "安装" if path.endswith("install") else "卸载"
            self._send_json(200, {"ok": True, "message": _verb + "成功", "reloaded": _res.get("reloaded", False)})
        elif path == "/api/bind-bot":

            length = int(self.headers.get("Content-Length", "0") or 0)

            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"

            try:

                payload = _json.loads(raw) if raw else {}

            except Exception:

                payload = {}

            appid = str(payload.get("appid") or "").strip()

            secret = str(payload.get("secret") or "").strip()

            event_mode = str(payload.get("event_mode") or "websocket").strip().lower()

            environment = str(payload.get("environment") or "sandbox").strip().lower()

            if event_mode not in ("websocket", "webhook"):

                event_mode = "websocket"

            if environment not in ("sandbox", "production"):

                environment = "sandbox"

            if not appid or not secret:

                self._send_json(400, {"ok": False, "error": "AppID 和 App Secret 不能为空"})

                return

            ok1, err1 = _update_config_py(appid, secret, event_mode, environment)

            if not ok1:

                self._send_json(500, {"ok": False, "error": err1})

                return

            ok2, err2 = _update_config_yaml(appid, secret, event_mode, environment)

            if not ok2:

                self._send_json(500, {"ok": False, "error": err2})

                return

            # 同步写入多机器人配置（bots.json），使其与 config.py 保持一致

            try:

                bot_manager.upsert_bot(appid, secret, environment, event_mode)

            except Exception as _e:

                print("[console_server] bind-bot 同步 bots.json 失败: %s" % _e, flush=True)

            # 立即热重载该 bot 凭据（按 appid 粒度：凭据变更则停旧启新，其他 bot 不动）
            try:
                _bot_module = _get_bot_module()
                _diff = _bot_module._apply_bots_diff()
            except Exception as _e:
                print("[console_server] bind-bot 热重载失败: %s" % _e, flush=True)
                _diff = {}

            # 更新内存中的状态，让前端立即感知已绑定

            with _lock:

                _status["bot_appid"] = appid

                _status["bot_verified"] = True

            append_ws_log(

                "小流萤", "系统", "system", "-", "-",

                "机器人凭证已更新 [AppID: %s, 环境: %s, 事件: %s]" % (appid, environment, event_mode)

            )

            self._send_json(200, {

                "ok": True,

                "message": "凭证已保存（%s / %s），已即时生效" % (environment, event_mode),

                "appid": appid,

                "environment": environment,

                "event_mode": event_mode,

            })

        elif path == "/api/members/unbind":

            length = int(self.headers.get("Content-Length", "0") or 0)

            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"

            try:

                payload = _json.loads(raw) if raw else {}

            except Exception:

                payload = {}

            openid = str(payload.get("openid") or "").strip()

            if not openid:

                self._send_json(400, {"ok": False, "error": "openid 不能为空"})

                return

            # 清除该成员的 QQ 号绑定（头像缓存也一并清掉）

            remove_friend_contact(openid)

            with _lock:

                m = _members.get(openid)

                if m is not None:

                    m["real_qq"] = ""

            _save_members()

            self._send_json(200, {"ok": True, "openid": openid, "message": "已解绑真实QQ号"})

        elif path == "/api/members/delete":

            length = int(self.headers.get("Content-Length", "0") or 0)

            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"

            try:

                payload = _json.loads(raw) if raw else {}

            except Exception:

                payload = {}

            openid = str(payload.get("openid") or "").strip()

            if not openid:

                self._send_json(400, {"ok": False, "error": "openid 不能为空"})

                return

            # 从成员库彻底移除，并清理 friend_contact 头像缓存

            with _lock:

                existed = _members.pop(openid, None)

            remove_friend_contact(openid)

            _save_members()

            if not existed:

                self._send_json(404, {"ok": False, "openid": openid, "error": "成员不存在"})

                return

            self._send_json(200, {"ok": True, "openid": openid, "message": "已删除成员"})

        elif path == "/api/members/delete-batch":

            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
            try:
                payload = _json.loads(raw) if raw else {}
            except Exception:
                payload = {}
            _openids = payload.get("openids") or []
            if payload.get("openid"):
                _openids = [payload.get("openid")]
            if not isinstance(_openids, list):
                _openids = [_openids] if _openids else []
            _openids = [str(o).strip() for o in _openids if str(o).strip()]
            _deleted = []
            _failed = []
            with _lock:
                for _oid in _openids:
                    _existed = _members.pop(_oid, None) is not None
                    _user_avatars.pop(_oid, None)
                    _user_qq_bindings.pop(_oid, None)
                    if _existed:
                        _deleted.append(_oid)
                    else:
                        _failed.append(_oid)
            if _deleted:
                _save_members()
            if _openids:
                _save_qq_bindings()
            self._send_json(200, {
                "ok": True,
                "deleted": _deleted,
                "failed": _failed,
                "deleted_count": len(_deleted),
                "failed_count": len(_failed),
                "message": ("已批量删除 %d 个成员" % len(_deleted)) + (("，%d 个不存在" % len(_failed)) if _failed else ""),
            })

        elif path == "/api/members/fetch_nickname":

            length = int(self.headers.get("Content-Length", "0") or 0)

            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"

            try:

                payload = _json.loads(raw) if raw else {}

            except Exception:

                payload = {}

            openid = str(payload.get("openid") or "").strip()

            if not openid:

                self._send_json(400, {"ok": False, "error": "openid 不能为空"})

                return

            nick = _refresh_member_nickname_from_oiapi(openid)

            if nick:

                self._send_json(200, {"ok": True, "openid": openid, "nickname": nick})

            else:

                self._send_json(200, {"ok": False, "openid": openid, "error": "反查失败（openid 不存在 / 网络错误）"})

        elif path in ("/api/group/delete", "/api/group/delete-batch"):

            length = int(self.headers.get("Content-Length", "0") or 0)

            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"

            try:

                payload = _json.loads(raw) if raw else {}

            except Exception:

                payload = {}

            # 兼容单删 / 批删两种入参
            _raw_list = payload.get("openids") or payload.get("openid_list") or []
            if isinstance(_raw_list, str):
                _raw_list = [_raw_list]
            _batch = []
            for _x in _raw_list:
                _s = str(_x or "").strip()
                if _s:
                    _batch.append(_s)
            _single = str(payload.get("openid") or "").strip()
            if _single and _single not in _batch:
                _batch.append(_single)
            if not _batch:
                self._send_json(400, {"ok": False, "error": "openid / openids 不能为空"})

                return

            # 批量：用 remove_group_contact（已含 _members + _group_profiles + qq_bindings + GROUP_BOT_MAP + _group_info_cache 全清理 + 落盘）
            _deleted, _failed = [], []
            for _gid in _batch:
                try:
                    if remove_group_contact(_gid):
                        _deleted.append(_gid)
                    else:
                        _failed.append({"openid": _gid, "error": "无效 openid"})
                except Exception as _ex:
                    _failed.append({"openid": _gid, "error": str(_ex)})

            self._send_json(200, {

                "ok": True,

                "deleted": _deleted,

                "failed": _failed,

                "deleted_count": len(_deleted),

                "failed_count": len(_failed),

                "message": ("已删除 %d 个群" % len(_deleted)) + (("；%d 个失败" % len(_failed)) if _failed else ""),

            })

            return

        elif path == "/api/group/join-requests/approval":
            # 入群申请审批（QQ 官方 POST /v2/groups/{openid}/approval_join_request/{member_openid}；60 QPM）
            # 官方 body：{"op": "approve"|"decline", "join_request_id": "...", "reject_reason"?: "..."}
            # 本接口 body：{openid, member_openid, action: "approve"|"decline", join_request_id, reason?, appid?}
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
            try:
                payload = _json.loads(raw) if raw else {}
            except Exception:
                payload = {}
            _gid = str(payload.get("openid") or "").strip()
            _mid = str(payload.get("member_openid") or "").strip()
            _act = str(payload.get("action") or "").strip().lower()
            _reason = str(payload.get("reason") or payload.get("reject_reason") or "").strip()
            _jrid = str(payload.get("join_request_id") or payload.get("joinRequestId") or "").strip()
            _aid = str(payload.get("appid") or "").strip() or None
            if not _gid or not _mid:
                self._send_json(400, {"ok": False, "error": "openid / member_openid 不能为空"})
                return
            if not _jrid:
                self._send_json(400, {"ok": False, "error": "join_request_id 不能为空（每条申请的唯一 ID，审批必须传）"})
                return
            _ok, _payload = _approval_join_request_via_qq_sync(_gid, _mid, _act, _reason, join_request_id=_jrid, appid=_aid)
            if not _ok:
                self._send_json(503, {"ok": False, "error": _payload.get("error", "审批失败")})
                return
            self._send_json(200, {"ok": True, "action": _act, "join_request_id": _jrid, **_payload})


        elif path == "/api/group/banword-mute":
            # 群禁言/违禁词自动禁言 配置（每群独立：mute_duration + mute_on_banword）
            # GET  查 openid 配置：{ok, openid, config: {mute_duration, mute_on_banword}}
            # POST 设 openid 配置：body {openid, mute_duration?, mute_on_banword?, appid?}
            try:
                if self.command == "GET":
                    _q = parse_qs(u.query)
                    _gid = str(_q.get("openid", [""])[0]).strip()
                    if not _gid:
                        self._send_json(400, {"ok": False, "error": "openid 不能为空"}); return
                    cfg = _get_mute_group_config(_gid)
                    self._send_json(200, {"ok": True, "openid": _gid, "config": cfg})
                    return
                length = int(self.headers.get("Content-Length", "0") or 0)
                _raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
                try:
                    _payload = _json.loads(_raw) if _raw else {}
                except Exception:
                    _payload = {}
                _gid = str(_payload.get("openid") or "").strip()
                if not _gid:
                    self._send_json(400, {"ok": False, "error": "openid 不能为空"}); return
                _dur = _payload.get("mute_duration")
                _on = _payload.get("mute_on_banword")
                _ok, _resp = _set_mute_group_config(_gid, mute_duration=_dur, mute_on_banword=_on)
                if not _ok:
                    self._send_json(503, {"ok": False, "error": _resp.get("error", "配置失败")})
                    return
                self._send_json(200, {"ok": True, "openid": _gid, "config": _resp})
            except Exception as _e:
                logger.exception("/api/group/banword-mute 失败")
                self._send_json(500, {"ok": False, "error": str(_e)})
            return


        elif path == "/api/group/banned-mute":
            # 违禁词 + 禁言 综合管理（每群独立：banned_words + mute_duration + mute_on_banword）
            # POST body: {openid, banned_words?, mute_duration?, mute_on_banword?, appid?}
            try:
                if self.command == "GET":
                    _q = parse_qs(u.query)
                    _gid = str(_q.get("openid", [""])[0]).strip()
                    if not _gid:
                        self._send_json(400, {"ok": False, "error": "openid 不能为空"}); return
                    cfg = _get_banned_mute_config(_gid)
                    self._send_json(200, {"ok": True, "openid": _gid, "config": cfg})
                    return
                length = int(self.headers.get("Content-Length", "0") or 0)
                _raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
                try:
                    _payload = _json.loads(_raw) if _raw else {}
                except Exception:
                    _payload = {}
                _gid = str(_payload.get("openid") or "").strip()
                if not _gid:
                    self._send_json(400, {"ok": False, "error": "openid 不能为空"}); return
                _ok, _resp = _set_banned_mute_config(_gid,
                    banned_words=_payload.get("banned_words"),
                    mute_duration=_payload.get("mute_duration"),
                    mute_on_banword=_payload.get("mute_on_banword"))
                if not _ok:
                    self._send_json(503, {"ok": False, "error": _resp.get("error", "配置失败")})
                    return
                self._send_json(200, {"ok": True, "openid": _gid, "config": _resp})
            except Exception as _e:
                logger.exception("/api/group/banned-mute 失败")
                self._send_json(500, {"ok": False, "error": str(_e)})
            return

        elif path == "/api/group/banword-log":
            # 违禁词拦截日志（本地 data/banword_log.json）
            # GET  ?openid=&limit=        -> {ok, logs:[...], total}
            # POST {clear:true, openid?}  -> {ok, cleared}
            try:
                if self.command == "GET":
                    _q = parse_qs(u.query)
                    _gid = str(_q.get("openid", [""])[0]).strip()
                    try:
                        _limit = int(_q.get("limit", ["200"])[0] or "200")
                    except Exception:
                        _limit = 200
                    _logs = _get_banword_log(_gid or None, _limit)
                    self._send_json(200, {"ok": True, "logs": _logs, "total": len(_logs)})
                    return
                length = int(self.headers.get("Content-Length", "0") or 0)
                _raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
                try:
                    _payload = _json.loads(_raw) if _raw else {}
                except Exception:
                    _payload = {}
                if _payload.get("clear"):
                    _gid = str(_payload.get("openid") or "").strip() or None
                    _del = _clear_banword_log(_gid)
                    self._send_json(200, {"ok": True, "cleared": _del})
                else:
                    self._send_json(400, {"ok": False, "error": "需要 clear=true"})
            except Exception as _e:
                logger.exception("/api/group/banword-log 失败")
                self._send_json(500, {"ok": False, "error": str(_e)})
            return

        elif path == "/api/group/mute-member":
            # 群成员禁言（官方 POST /v2/groups/{openid}/restrict_chat_setting；60 QPM）
            # body: {openid, member_openid, duration?, appid?}
            #  duration 省略时读取本群 mute_duration 配置（每群独立）
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                _raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
                try:
                    _payload = _json.loads(_raw) if _raw else {}
                except Exception:
                    _payload = {}
                _gid = str(_payload.get("openid") or "").strip()
                _mid = str(_payload.get("member_openid") or "").strip()
                _aid = str(_payload.get("appid") or "").strip() or None
                _dur_in = _payload.get("duration")
                if not _gid or not _mid:
                    self._send_json(400, {"ok": False, "error": "openid / member_openid 不能为空"}); return
                if _dur_in is None or _dur_in == "":
                    _cfg = _get_mute_group_config(_gid)
                    _dur = int(_cfg.get("mute_duration", 600) or 600)
                else:
                    try:
                        _dur = int(_dur_in)
                    except Exception:
                        self._send_json(400, {"ok": False, "error": "duration 必须为正整数秒"}); return
                    if _dur < 1:
                        self._send_json(400, {"ok": False, "error": "duration 必须为正整数秒"}); return
                _ok, _resp = _mute_member_via_qq_sync(_gid, _mid, _dur, appid=_aid)
                if not _ok:
                    self._send_json(503, {"ok": False, "error": _resp.get("error", "禁言失败")})
                    return
                self._send_json(200, {"ok": True, "openid": _gid, "member_openid": _mid,
                                      "duration": _dur, **_resp})
            except Exception as _e:
                logger.exception("/api/group/mute-member 失败")
                self._send_json(500, {"ok": False, "error": str(_e)})
            return


        elif path == "/api/group/unmute-member":
            # 解除群成员禁言（官方 POST /v2/groups/{openid}/restrict_chat_setting op=del；60 QPM）
            # body: {openid, member_openid, appid?}
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                _raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
                try:
                    _payload = _json.loads(_raw) if _raw else {}
                except Exception:
                    _payload = {}
                _gid = str(_payload.get("openid") or "").strip()
                _mid = str(_payload.get("member_openid") or "").strip()
                _aid = str(_payload.get("appid") or "").strip() or None
                if not _gid or not _mid:
                    self._send_json(400, {"ok": False, "error": "openid / member_openid 不能为空"}); return
                _ok, _resp = _unmute_member_via_qq_sync(_gid, _mid, appid=_aid)
                if not _ok:
                    self._send_json(503, {"ok": False, "error": _resp.get("error", "解除禁言失败")})
                    return
                self._send_json(200, {"ok": True, "openid": _gid, "member_openid": _mid, **_resp})
            except Exception as _e:
                logger.exception("/api/group/unmute-member 失败")
                self._send_json(500, {"ok": False, "error": str(_e)})
            return


        elif path == _JAS:
            # 创建入群自动审批策略（官方 POST /v2/groups/join_approval_strategy）
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
            try:
                payload = _json.loads(raw) if raw else {}
            except Exception:
                payload = {}
            _aid = str(payload.get("appid") or "").strip() or None
            _gids = payload.get("group_openids") or []
            _gids2 = payload.get("group_ids") or []
            _enable = str(payload.get("is_enable") or "on").strip()
            _remark = str(payload.get("remark") or "").strip()
            _ok, _payload = _create_join_approval_strategy_via_qq_sync(_gids, _gids2, _enable, _remark, appid=_aid)
            if not _ok:
                self._send_json(503, {"ok": False, "error": _payload.get("error", "创建失败")})
                return
            self._send_json(200, {"ok": True, **_payload})

        elif path.startswith(_JAS + "/") and path.endswith("/update"):
            # 修改策略（is_enable / remark；官方 PATCH，这里用 /update 子路径代替）
            _sid = _jas_sid_from_path(path, "/update")
            if not _sid:
                self._send_json(400, {"ok": False, "error": "strategy_id 无效"})
                return
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
            try:
                payload = _json.loads(raw) if raw else {}
            except Exception:
                payload = {}
            _aid = str(payload.get("appid") or "").strip() or None
            _enable = payload.get("is_enable")
            _remark = payload.get("remark")
            if _enable is None and _remark is None:
                self._send_json(400, {"ok": False, "error": "is_enable 或 remark 至少提供一个"})
                return
            _ok, _payload = _update_join_approval_strategy_via_qq_sync(_sid, is_enable=_enable, remark=_remark, appid=_aid)
            if not _ok:
                self._send_json(503, {"ok": False, "error": _payload.get("error", "修改失败")})
                return
            self._send_json(200, {"ok": True, **_payload})

        elif path.startswith(_JAS + "/") and path.endswith("/execute"):
            # 执行策略（官方 POST .../execute）
            _sid = _jas_sid_from_path(path, "/execute")
            if not _sid:
                self._send_json(400, {"ok": False, "error": "strategy_id 无效"})
                return
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
            try:
                payload = _json.loads(raw) if raw else {}
            except Exception:
                payload = {}
            _aid = str(payload.get("appid") or "").strip() or None
            _ok, _payload = _execute_join_approval_strategy_via_qq_sync(_sid, appid=_aid)
            if not _ok:
                self._send_json(503, {"ok": False, "error": _payload.get("error", "执行失败")})
                return
            self._send_json(200, {"ok": True, **_payload})

        elif path.startswith(_JAS + "/") and path.endswith("/whitelist"):
            # 增删白名单（op: add/delete；官方 POST .../whitelist）
            _sid = _jas_sid_from_path(path, "/whitelist")
            if not _sid:
                self._send_json(400, {"ok": False, "error": "strategy_id 无效"})
                return
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
            try:
                payload = _json.loads(raw) if raw else {}
            except Exception:
                payload = {}
            _aid = str(payload.get("appid") or "").strip() or None
            _op = str(payload.get("op") or "add").strip()
            _users = payload.get("whitelist_users") or []
            _ok, _payload = _update_join_approval_whitelist_via_qq_sync(_sid, _op, _users, appid=_aid)
            if not _ok:
                self._send_json(503, {"ok": False, "error": _payload.get("error", "白名单操作失败")})
                return
            self._send_json(200, {"ok": True, **_payload})

        elif path.startswith(_JAS + "/") and path.endswith("/delete"):
            # 删除策略（官方 DELETE，这里用 /delete 子路径代替）
            _sid = _jas_sid_from_path(path, "/delete")
            if not _sid:
                self._send_json(400, {"ok": False, "error": "strategy_id 无效"})
                return
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
            try:
                payload = _json.loads(raw) if raw else {}
            except Exception:
                payload = {}
            _aid = str(payload.get("appid") or "").strip() or None
            _ok, _payload = _delete_join_approval_strategy_via_qq_sync(_sid, appid=_aid)
            if not _ok:
                self._send_json(503, {"ok": False, "error": _payload.get("error", "删除失败")})
                return
            self._send_json(200, {"ok": True, **_payload})

        elif path == "/api/group/admin-groups":
            # 仅返回机器人是群管理员/群主的群（用于入群申请列表下拉）。
            # 通过官方 `GET /v2/groups/{openid}/bot_state` 探测 member_role，结果按群缓存 10 分钟。
            try:
                _now = time.time()
                _gids = _all_group_openids()
                _groups = []
                _probed_admin = 0
                _probed_member = 0
                _probed_other = 0
                _probed_error = 0
                _probed_skipped = 0
                _cached_hits = 0
                _samples = []
                _bot_state_denied = False
                for _gid in _gids:
                    _cached = _jr_admin_cache.get(_gid)
                    if _cached and (_now - _cached.get("ts", 0)) < _JR_ADMIN_TTL:
                        _role = str(_cached.get("role") or "")
                        _cached_hits += 1
                    else:
                        _role, _definitive, _denied = _probe_bot_admin(_gid)
                        if _denied:
                            _bot_state_denied = True
                        if not _definitive:
                            _probed_skipped += 1
                            if len(_samples) < 5:
                                _samples.append({"openid": _gid[-8:], "name": _group_display_name(_gid), "role": "skipped", "error": "transient(频率限制或桥接不可用)"})
                            continue
                        _jr_admin_cache[_gid] = {"role": _role, "ts": _now}
                    if _role in ("admin", "owner"):
                        _probed_admin += 1
                        _groups.append({"openid": _gid, "name": _group_display_name(_gid), "role": _role})
                    elif _role == "member":
                        _probed_member += 1
                        if len(_samples) < 5:
                            _samples.append({"openid": _gid[-8:], "name": _group_display_name(_gid), "role": "member"})
                    elif _role == "":
                        _probed_other += 1
                        if len(_samples) < 5:
                            _samples.append({"openid": _gid[-8:], "name": _group_display_name(_gid), "role": "non_member_or_unknown"})
                    else:
                        _probed_other += 1
                        if len(_samples) < 5:
                            _samples.append({"openid": _gid[-8:], "name": _group_display_name(_gid), "role": _role})

                # 兜底：bot_state 接口未授权（白名单 11253）导致无法精确判定管理员时，
                # 退化为「机器人所在群」（GROUP_BOT_MAP 中实际收发过消息的群）作为候选。
                _warning = ""
                if _bot_state_denied:
                    _warning = ("bot_state 接口未授权（仅白名单机器人可用，官方返回 11253），"
                                "无法精确判定管理员身份。已按「机器人所在群」兜底展示（不保证都是管理员），"
                                "请到 QQ 开放平台为机器人申请 bot_state 白名单后精确筛选；"
                                "选中某群后若拉不到入群申请，说明该群机器人并非管理员。")
                    _seen = set(_g.get("openid") for _g in _groups)
                    for _gid in _gids:
                        if _gid in _seen:
                            continue
                        if _gid not in GROUP_BOT_MAP:
                            continue
                        _groups.append({"openid": _gid, "name": _group_display_name(_gid), "role": "member", "inferred": True})

                # 按群名稳定排序，下拉体验更友好
                _groups.sort(key=lambda _g: (_g.get("name") or "", _g.get("openid") or ""))
                self._send_json(200, {
                    "ok": True,
                    "groups": _groups,
                    "total_groups": len(_gids),
                    "cached": _cached_hits,
                    "warning": _warning,
                    "stats": {
                        "admin_or_owner": _probed_admin,
                        "member": _probed_member,
                        "other": _probed_other,
                        "skipped": _probed_skipped,
                        "denied": 1 if _bot_state_denied else 0,
                    },
                    "samples": _samples,
                })
            except Exception as _e:
                logger.exception("/api/group/admin-groups 失败")
                self._send_json(500, {"ok": False, "error": str(_e)})

        elif path == "/api/admin/brand":
            # 保存/重置管理台品牌信息
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
            try:
                _payload = _json.loads(raw) if raw else {}
            except Exception:
                _payload = {}
            _action = str(_payload.get("action") or "save").strip()
            try:
                if _action == "reset":
                    _ok, _err = _save_admin_brand({"title": "小流萤管理后台", "logo": ""}, reset=True)
                else:
                    _title = str(_payload.get("title") or "小流萤管理后台").strip()
                    _logo = str(_payload.get("logo") or "").strip()
                    if len(_title) > 64:
                        self._send_json(400, {"ok": False, "error": "标题过长（最多 64 字符）"})
                        return
                    # logo 限制 2MB（base64 后约 2.7MB）
                    if len(_logo) > 2 * 1024 * 1024:
                        self._send_json(400, {"ok": False, "error": "图片过大（最大 2MB）"})
                        return
                    # 仅接受 image/ 开头或 data:image/ 开头
                    if _logo and not (_logo.startswith("data:image/") or _logo.startswith("http://") or _logo.startswith("https://")):
                        self._send_json(400, {"ok": False, "error": "logo 必须是 data URL 或 http(s) URL"})
                        return
                    _ok, _err = _save_admin_brand({"title": _title, "logo": _logo})
                if not _ok:
                    self._send_json(500, {"ok": False, "error": _err or "保存失败"})
                    return
                self._send_json(200, {"ok": True, "action": _action})
            except Exception as _e:
                self._send_json(500, {"ok": False, "error": "保存品牌信息失败: %s" % _e})

        elif path == "/api/admin/music-fm":
            # 保存/重置流萤FM
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
            try:
                _payload = _json.loads(raw) if raw else {}
            except Exception:
                _payload = {}
            _action = str(_payload.get("action") or "save").strip()
            try:
                if _action == "reset":
                    _ok, _err = _save_music_fm({}, reset=True)
                else:
                    _title = str(_payload.get("title") or "流萤FM").strip()[:64]
                    _subtitle = str(_payload.get("subtitle") or "与流萤一起走在路上").strip()[:128]
                    _cover = str(_payload.get("cover") or "/admin/assets/music/cover.png").strip()
                    if _cover and not (_cover.startswith("data:image/") or _cover.startswith("http://") or _cover.startswith("https://") or _cover.startswith("/")):
                        self._send_json(400, {"ok": False, "error": "封面必须是 data URL / http(s) / 站内路径"})
                        return
                    if len(_cover) > 2 * 1024 * 1024:
                        self._send_json(400, {"ok": False, "error": "封面图片过大（最大 2MB）"})
                        return
                    _ok, _err = _save_music_fm({"title": _title, "subtitle": _subtitle, "cover": _cover})
                if not _ok:
                    self._send_json(500, {"ok": False, "error": _err or "保存失败"})
                    return
                self._send_json(200, {"ok": True, "action": _action})
            except Exception as _e:
                self._send_json(500, {"ok": False, "error": "保存流萤FM配置失败: %s" % _e})

        elif path == "/api/runtime-settings":

            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
            try:
                payload = _json.loads(raw) if raw else {}
            except Exception:
                payload = {}
            action = str(payload.get("action") or "").strip()
            scope = str(payload.get("scope") or "global").strip()
            rid = str(payload.get("id") or "").strip()
            if scope not in ("global", "bot", "group"):
                scope = "global"
            key = str(payload.get("key") or "").strip()
            if action == "save":
                if not key:
                    self._send_json(400, {"ok": False, "error": "缺少 key"})
                    return
                ok, err = set_runtime_setting(key, payload.get("value"), scope, rid)
                if not ok:
                    self._send_json(400, {"ok": False, "error": err})
                    return
                self._send_json(200, {"ok": True, "action": "save"})
            elif action == "reset":
                if not key:
                    self._send_json(400, {"ok": False, "error": "缺少 key"})
                    return
                ok, err = reset_runtime_setting(key, scope, rid)
                self._send_json(200, {"ok": ok, "error": err})
            elif action == "reset-all":
                ok, err = reset_all_runtime_settings(scope, rid)
                self._send_json(200, {"ok": ok, "error": err})
            elif action == "reload":
                _load_runtime_settings()
                self._send_json(200, {"ok": True, "action": "reload"})
            else:
                self._send_json(400, {"ok": False, "error": "未知 action: %s" % action})
            return

        elif path == "/api/feature-config":

            length = int(self.headers.get("Content-Length", "0") or 0)

            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"

            try:

                payload = _json.loads(raw) if raw else {}

            except Exception:

                payload = {}

            module = str(payload.get("module") or "").strip()

            config = payload.get("config")

            if not module or not isinstance(config, dict):

                self._send_json(400, {"ok": False, "error": "module 和 config 不能为空"})

                return

            # 只保留数值字段，防止乱写

            cleaned = {}

            for k, v in config.items():

                if isinstance(v, (int, float)):

                    cleaned[k] = v

                elif isinstance(v, str):

                    try:

                        cleaned[k] = int(v)

                    except Exception:

                        try:

                            cleaned[k] = float(v)

                        except Exception:

                            pass

            with _lock:

                _feature_configs[module] = cleaned

            _save_feature_configs()

        elif path == "/api/c2c-user/delete":

            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
            try:
                payload = _json.loads(raw) if raw else {}
            except Exception:
                payload = {}
            openid = str(payload.get("openid") or "").strip()
            if not openid:
                self._send_json(400, {"ok": False, "error": "openid 不能为空"})
                return
            with _lock:
                existed = _members.pop(openid, None) is not None
            if existed:
                _save_members()
            self._send_json(200, {
                "ok": True,
                "openid": openid,
                "deleted": existed,
                "message": ("已删除用户记录" if existed else "用户不存在"),
            })

        elif path == "/api/c2c-user/delete-batch":

            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
            try:
                payload = _json.loads(raw) if raw else {}
            except Exception:
                payload = {}
            _openids = payload.get("openids") or []
            if payload.get("openid"):
                _openids = [payload.get("openid")]
            if not isinstance(_openids, list):
                _openids = [_openids] if _openids else []
            _openids = [str(o).strip() for o in _openids if str(o).strip()]
            _deleted = []
            _failed = []
            with _lock:
                for _oid in _openids:
                    _existed = _members.pop(_oid, None) is not None
                    _user_avatars.pop(_oid, None)
                    _user_qq_bindings.pop(_oid, None)
                    if _existed:
                        _deleted.append(_oid)
                    else:
                        _failed.append(_oid)
            if _deleted:
                _save_members()
            if _openids:
                _save_qq_bindings()
            self._send_json(200, {
                "ok": True,
                "deleted": _deleted,
                "failed": _failed,
                "deleted_count": len(_deleted),
                "failed_count": len(_failed),
                "message": ("已批量删除 %d 个用户" % len(_deleted)) + (("，%d 个不存在" % len(_failed)) if _failed else ""),
            })

        elif path == "/api/system-config":

            global _system_switches, _video_limits

            length = int(self.headers.get("Content-Length", "0") or 0)

            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"

            try:

                payload = _json.loads(raw) if raw else {}

            except Exception:

                payload = {}

            if not isinstance(payload, dict):

                self._send_json(400, {"ok": False, "error": "请求体必须为对象"})

                return

            target_bot = str(payload.get("bot") or "").strip()

            # 开关（可选）：target_bot 给定时写入该 bot 维度，否则写全局

            if "switches" in payload:

                switches = payload.get("switches")

                if not isinstance(switches, dict):

                    self._send_json(400, {"ok": False, "error": "switches 必须为对象"})

                    return

                cleaned = {}

                for k, v in switches.items():

                    cleaned[str(k)] = bool(v)

                if target_bot:

                    with _lock:

                        # 关键：只保留与全局生效值不一致的键，避免 bot_switches 被默认值撑爆。
                        # 全局生效值：_system_switches[k] 若存在即用它，否则视为默认 True。
                        # 例：全局 music_random 未设置（默认 true），bot=true → 不存储；bot=false → 才存储为覆盖。
                        trimmed = {}

                        for _k, _v in cleaned.items():

                            _gv = _system_switches.get(_k)

                            _gv_eff = bool(_gv) if _gv is not None else True

                            if _gv_eff != bool(_v):

                                trimmed[_k] = bool(_v)

                        # 空 dict 直接清空（全部跟随全局）

                        if trimmed:

                            _bot_system_switches[target_bot] = trimmed

                        else:

                            _bot_system_switches.pop(target_bot, None)

                        persisted_bot_sw = {aid: dict(sw) for aid, sw in _bot_system_switches.items()}

                    print("[console_server] 收到系统开关保存请求(bot=%s)，输入 %d 项 → 剪枝保留 %d 项" % (target_bot, len(cleaned), len(trimmed)), flush=True)

                else:

                    with _lock:

                        _system_switches = cleaned

                    print("[console_server] 收到系统开关保存请求(全局)，keys=%s" % list(cleaned.keys()), flush=True)

            # 显式重置某 bot 的覆盖（POST {bot:X, reset:true}）：清空该 bot 的所有覆盖项

            if payload.get("reset") and target_bot:

                with _lock:

                    _bot_system_switches.pop(target_bot, None)

                print("[console_server] 已重置 bot=%s 的功能覆盖" % target_bot, flush=True)

            # 视频限制（可选）

            if "video_limits" in payload:

                vl = payload.get("video_limits")

                if not isinstance(vl, dict):

                    self._send_json(400, {"ok": False, "error": "video_limits 必须为对象"})

                    return

                merged = {}

                for key in ("parse", "system"):

                    dft = _VIDEO_LIMITS_DEFAULT.get(key, {})

                    src = vl.get(key)

                    if not isinstance(src, dict):

                        src = {}

                    merged[key] = {

                        "max_duration": _coerce_int(src.get("max_duration", dft.get("max_duration", 0)), 0),

                        "max_mb": _coerce_int(src.get("max_mb", dft.get("max_mb", 0)), 0),

                    }

                print("[console_server] 收到视频限制保存请求: %s" % merged, flush=True)

                with _lock:

                    _video_limits = merged

            _save_system_config()

            with _lock:

                out = {"ok": True,

                       "switches": dict(_system_switches),

                       "video_limits": dict(_video_limits)}

            self._send_json(200, out)

        elif path == "/api/cache-clean":

            length = int(self.headers.get("Content-Length", "0") or 0)

            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"

            try:

                payload = _json.loads(raw) if raw else {}

            except Exception:

                payload = {}

            keys = payload.get("items") or []

            if not isinstance(keys, list):

                self._send_json(400, {"ok": False, "error": "items 必须为数组"})

                return

            # 白名单过滤（忽略未知 key）

            valid_keys = [k for k in keys if k in _CACHE_CATEGORIES]

            if not valid_keys:

                self._send_json(400, {"ok": False, "error": "没有有效的清理项"})

                return

            try:

                max_age = _coerce_int(payload.get("max_age_days") or 0, 0)

                freed, deleted, details = _do_clean_cache(valid_keys, max_age_days=max_age)
                try:
                    _ms_freed, _ms_deleted = _enforce_runtime_media_storage()
                    freed += _ms_freed
                    deleted += _ms_deleted
                except Exception as _e:
                    print("[cache-clean] 媒体存储限制执行异常: %s" % _e, flush=True)

            except Exception as e:

                self._send_json(500, {"ok": False, "error": "清理失败: %s" % e})

                return

            print("[cache-clean] 手动清理: items=%s freed=%s deleted=%d" % (

                valid_keys, _format_size(freed), deleted), flush=True)

            # 重新统计受影响的项

            new_items = _build_cache_stats_items(valid_keys)

            new_items_map = {it["key"]: it for it in new_items}

            for d in details:

                d["size_after"] = new_items_map.get(d["key"], {}).get("size_bytes", 0)

                d["count_after"] = new_items_map.get(d["key"], {}).get("file_count", 0)

            self._send_json(200, {

                "ok": True,

                "freed_bytes": freed,

                "freed_human": _format_size(freed),

                "deleted_files": deleted,

                "details": details,

            })

        elif path == "/api/cache-clean-config":

            global _cache_clean_config

            length = int(self.headers.get("Content-Length", "0") or 0)

            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"

            try:

                payload = _json.loads(raw) if raw else {}

            except Exception:

                payload = {}

            dft = _CACHE_CLEAN_DEFAULT

            enabled = bool(payload.get("enabled", dft["enabled"]))

            schedule = str(payload.get("schedule") or dft["schedule"]).strip().lower()

            if schedule not in ("daily", "weekly", "monthly"):

                schedule = dft["schedule"]

            try:

                hour = int(payload.get("hour", dft["hour"]))

            except Exception:

                hour = dft["hour"]

            hour = max(0, min(23, hour))

            try:

                minute = int(payload.get("minute", dft["minute"]))

            except Exception:

                minute = dft["minute"]

            minute = max(0, min(59, minute))

            try:

                weekday = int(payload.get("weekday", dft["weekday"]))

            except Exception:

                weekday = dft["weekday"]

            weekday = max(0, min(6, weekday))

            try:

                month_day = int(payload.get("month_day", dft["month_day"]))

            except Exception:

                month_day = dft["month_day"]

            month_day = max(1, min(28, month_day))

            max_age = _coerce_int(payload.get("max_age_days", dft["max_age_days"]), 0)

            max_age = max(0, max_age)

            items = payload.get("items")

            if not isinstance(items, list) or not items:

                items = dft["items"]

            items = [k for k in items if k in _CACHE_CATEGORIES]

            with _lock:

                _cache_clean_config = {

                    "enabled": enabled,

                    "schedule": schedule,

                    "weekday": weekday,

                    "month_day": month_day,

                    "hour": hour,

                    "minute": minute,

                    "max_age_days": max_age,

                    "items": items,

                    "last_run": str(_cache_clean_config.get("last_run") or ""),

                }

            _save_system_config()

            _cfg_out = dict(_cache_clean_config)

            try:

                _cfg_out["next_run"] = _next_trigger_after(_cache_clean_config, datetime.now()).strftime("%Y-%m-%d %H:%M") if enabled else ""

            except Exception:

                _cfg_out["next_run"] = ""

            self._send_json(200, {"ok": True, "config": _cfg_out})

        elif path == "/api/backup":
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
            try:
                payload = _json.loads(raw) if raw else {}
            except Exception:
                payload = {}
            action = str(payload.get("action") or "list").strip()
            if action == "create":
                self._send_json(200, _create_backup())
                return
            if action == "delete":
                name = str(payload.get("name") or "").strip()
                ok, msg = _delete_backup(name)
                self._send_json(200, {"ok": ok, "error": (None if ok else msg)})
                return
            self._send_json(200, {"ok": True, "backups": _list_backups()})

        elif path == "/api/chime-config":
            length = int(self.headers.get("Content-Length", "0") or 0)

            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"

            try:

                payload = _json.loads(raw) if raw else {}

            except Exception:

                payload = {}

            group = str(payload.get("group_openid") or "").strip()

            if not group:

                self._send_json(400, {"ok": False, "error": "缺少 group_openid"})

                return

            enabled = bool(payload.get("enabled"))

            with _lock:

                cfg = dict(_chime_groups.get(group) or _default_chime_group())

                cfg["enabled"] = enabled

                iv = payload.get("interval_hours")

                if iv is not None:

                    cfg["interval_hours"] = max(1, min(24, _coerce_int(iv, cfg.get("interval_hours", 1))))

                ps = payload.get("period_start")

                if ps is not None:

                    cfg["period_start"] = max(0, min(23, _coerce_int(ps, cfg.get("period_start", 0))))

                pe = payload.get("period_end")

                if pe is not None:

                    cfg["period_end"] = max(0, min(23, _coerce_int(pe, cfg.get("period_end", 23))))

                # 首次启用且从未运行过：以当前时间为基准，避免开启瞬间突发

                if enabled and not cfg.get("last_run"):

                    cfg["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                _chime_groups[group] = cfg

            _save_system_config()

            self._send_json(200, {"ok": True, "config": get_chime_group_config(group)})

        elif path == "/api/welcome-config":

            length = int(self.headers.get("Content-Length", "0") or 0)

            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"

            try:

                payload = _json.loads(raw) if raw else {}

            except Exception:

                payload = {}

            group = str(payload.get("group_openid") or "").strip()

            if not group:

                self._send_json(400, {"ok": False, "error": "缺少 group_openid"})

                return

            fields = {}

            if "welcome_enabled" in payload:

                fields["welcome_enabled"] = bool(payload["welcome_enabled"])

            if "welcome_msg" in payload:

                fields["welcome_msg"] = str(payload["welcome_msg"] or "")

            try:

                cfg = set_welcome_group_config(group, **fields) if fields else get_welcome_group_config(group)

                self._send_json(200, {"ok": True, "config": cfg})

            except Exception as e:

                self._send_json(200, {"ok": False, "error": str(e)})

        elif path == "/api/chime-trigger":

            length = int(self.headers.get("Content-Length", "0") or 0)

            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"

            try:

                payload = _json.loads(raw) if raw else {}

            except Exception:

                payload = {}

            group = str(payload.get("group_openid") or "").strip()

            try:

                result = _trigger_chime_now(group if group else None)

                self._send_json(200, {"ok": True, "result": result})

            except Exception as e:

                self._send_json(200, {"ok": False, "error": str(e)})

        elif path == "/api/checkin-config":

            length = int(self.headers.get("Content-Length", "0") or 0)

            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"

            try:

                payload = _json.loads(raw) if raw else {}

            except Exception:

                payload = {}

            try:

                cfg = set_checkin_config(payload)

                self._send_json(200, {"ok": True, "config": cfg})

            except Exception as e:

                self._send_json(200, {"ok": False, "error": str(e)})

        elif path == "/api/group-profile":

            length = int(self.headers.get("Content-Length", "0") or 0)

            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"

            try:

                payload = _json.loads(raw) if raw else {}

            except Exception:

                payload = {}

            openid = str(payload.get("openid") or "").strip()

            name = str(payload.get("name") or "").strip()

            if not openid:

                self._send_json(400, {"ok": False, "error": "openid 不能为空"})

                return

            ok = set_group_name(openid, name)

            if ok:

                prof = get_group_profile(openid)

                self._send_json(200, {"ok": True, "openid": openid, "profile": prof})

            else:

                self._send_json(500, {"ok": False, "error": "保存群名失败"})

        elif path == "/api/qa-rules/save":

            length = int(self.headers.get("Content-Length", "0") or 0)

            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"

            try:

                payload = _json.loads(raw) if raw else {}

            except Exception:

                payload = {}

            rule_id = payload.get("id")

            keyword = str(payload.get("keyword") or "").strip()

            match_type = str(payload.get("match_type") or "精确").strip()

            answer = str(payload.get("answer") or "").strip()

            cooldown = int(payload.get("cooldown") or 0)

            enabled = bool(payload.get("enabled", True))

            bot = str(payload.get("bot") or "小流萤").strip()

            answer_type = str(payload.get("answer_type") or "文本").strip()

            scope = str(payload.get("scope") or "").strip()

            if not keyword or not answer:

                self._send_json(400, {"ok": False, "error": "关键词和回复内容不能为空"})

                return

            if match_type not in ("精确", "包含", "前缀", "后缀", "模糊"):

                match_type = "精确"

            if answer_type not in ("文本", "Markdown"):

                answer_type = "文本"

            with _lock:

                global _qa_rules_seq

                if rule_id is not None:

                    for r in _qa_rules:

                        if r.get("id") == rule_id:

                            r["keyword"] = keyword

                            r["match_type"] = match_type

                            r["answer"] = answer

                            r["cooldown"] = cooldown

                            r["enabled"] = enabled

                            r["bot"] = bot

                            r["answer_type"] = answer_type

                            r["scope"] = scope

                            r["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

                            _save_qa_rules()

                            self._send_json(200, {"ok": True, "item": r})

                            return

                    self._send_json(404, {"ok": False, "error": "规则不存在"})

                    return

                _qa_rules_seq += 1

                new_rule = {

                    "id": _qa_rules_seq,

                    "keyword": keyword,

                    "match_type": match_type,

                    "answer": answer,

                    "cooldown": cooldown,

                    "enabled": enabled,

                    "bot": bot,

                    "answer_type": answer_type,

                    "scope": scope,

                    "hits": 0,

                    "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),

                    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),

                }

                _qa_rules.append(new_rule)

                _save_qa_rules()

            self._send_json(200, {"ok": True, "item": new_rule})

        elif path == "/api/qa-rules/delete":

            length = int(self.headers.get("Content-Length", "0") or 0)

            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"

            try:

                payload = _json.loads(raw) if raw else {}

            except Exception:

                payload = {}

            rule_id = payload.get("id")

            if rule_id is None:

                self._send_json(400, {"ok": False, "error": "id 不能为空"})

                return

            with _lock:

                before = len(_qa_rules)

                _qa_rules[:] = [r for r in _qa_rules if r.get("id") != rule_id]

                deleted = before - len(_qa_rules)

                if deleted:

                    _save_qa_rules()

            self._send_json(200, {"ok": True, "deleted": deleted})

        elif path == "/api/ai/providers":

            length = int(self.headers.get("Content-Length", "0") or 0)

            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"

            try:

                payload = _json.loads(raw) if raw else {}

            except Exception:

                payload = {}

            _bot = str(payload.get("bot") or "")

            pid = _coerce_id(payload.get("id"))

            name = str(payload.get("name") or "").strip()

            ptype = str(payload.get("type") or "openai").strip()

            url = str(payload.get("url") or "").strip()

            key = str(payload.get("key") or "").strip()

            model = str(payload.get("model") or "").strip()

            if not name or not url or not model:

                self._send_json(400, {"ok": False, "error": "名称、API 地址和模型不能为空"})

                return

            if ptype not in ("openai", "ollama"):

                ptype = "openai"

            with _lock:

                if pid is not None:

                    for p in _load_ai_providers(_bot):

                        if p.get("id") == pid:

                            p["name"] = name

                            p["type"] = ptype

                            p["url"] = url

                            if key:

                                p["key"] = key

                            p["model"] = model

                            p["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

                            _save_ai_providers(_bot)

                            self._send_json(200, {"ok": True, "item": p})

                            return

                    self._send_json(404, {"ok": False, "error": "供应商不存在"})

                    return

                _new_id = max([p.get("id", 0) for p in _load_ai_providers(_bot)] or [0]) + 1

                new_p = {

                    "id": _new_id,

                    "name": name,

                    "type": ptype,

                    "url": url,

                    "key": key,

                    "model": model,

                    "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),

                    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),

                }

                _load_ai_providers(_bot).append(new_p)

                _save_ai_providers(_bot)

            self._send_json(200, {"ok": True, "item": new_p})

        elif path == "/api/ai/sensitive-words":

            length = int(self.headers.get("Content-Length", "0") or 0)

            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"

            try:

                payload = _json.loads(raw) if raw else {}

            except Exception:

                payload = {}

            action = payload.get("action")

            if action == "set_auto_revoke":

                with _lock:

                    _ai_config["auto_revoke"] = bool(payload.get("enabled", False))

                    _save_sensitive_words()

                self._send_json(200, {"ok": True, "auto_revoke": _ai_config["auto_revoke"]})

                return

            wid = payload.get("id")

            if wid is not None and "word" not in payload:

                # 仅更新启用状态

                with _lock:

                    for w in _sensitive_words:

                        if w.get("id") == wid:

                            w["enabled"] = bool(payload.get("enabled", True))

                            w["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

                            _save_sensitive_words()

                            self._send_json(200, {"ok": True, "item": w})

                            return

                self._send_json(404, {"ok": False, "error": "敏感词不存在"})

                return

            word = str(payload.get("word") or "").strip()

            scope = str(payload.get("scope") or "global").strip()

            category = str(payload.get("category") or "通用").strip()

            enabled = bool(payload.get("enabled", True))

            if not word:

                self._send_json(400, {"ok": False, "error": "敏感词不能为空"})

                return

            if scope not in ("global", "bot", "group"):

                scope = "global"

            with _lock:

                global _sensitive_words_seq

                if wid is not None:

                    for w in _sensitive_words:

                        if w.get("id") == wid:

                            w["word"] = word

                            w["scope"] = scope

                            w["category"] = category

                            w["enabled"] = enabled

                            w["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

                            _save_sensitive_words()

                            self._send_json(200, {"ok": True, "item": w})

                            return

                    self._send_json(404, {"ok": False, "error": "敏感词不存在"})

                    return

                _sensitive_words_seq += 1

                new_w = {

                    "id": _sensitive_words_seq,

                    "word": word,

                    "scope": scope,

                    "category": category,

                    "enabled": enabled,

                    "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),

                    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),

                }

                _sensitive_words.append(new_w)

                _save_sensitive_words()

            self._send_json(200, {"ok": True, "item": new_w})

        elif path == "/api/ai/persona":

            length = int(self.headers.get("Content-Length", "0") or 0)

            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"

            try:

                payload = _json.loads(raw) if raw else {}

            except Exception:

                payload = {}

            action = str(payload.get("action") or "").strip()

            _bot = str(payload.get("bot") or "")

            try:

                from modules.ai_persona import (

                    add_persona, update_persona, delete_persona,

                    set_active_persona, clear_active_persona,

                )

                if action == "delete":

                    pid = int(payload.get("id"))

                    ok = delete_persona(pid, bot=_bot)

                    self._send_json(200, {"ok": ok, "deleted": 1 if ok else 0})

                elif action == "set_active":

                    pid = int(payload.get("id"))

                    if pid == -1:

                        ok, msg = clear_active_persona(bot=_bot)

                    else:

                        ok, msg = set_active_persona(pid, bot=_bot)

                    self._send_json(200, {"ok": ok, "error": msg} if ok else {"ok": False, "error": msg})

                else:

                    pid = payload.get("id")

                    name = str(payload.get("name") or "").strip()

                    prompt = str(payload.get("prompt") or "")

                    active = bool(payload.get("active", False))

                    if action == "update" and pid not in (None, ""):

                        ok, msg = update_persona(

                            int(pid), name=name, prompt=prompt, active=active, bot=_bot)

                        self._send_json(200, {"ok": ok, "error": msg} if ok else {"ok": False, "error": msg})

                    else:

                        ok, msg, pid_new = add_persona(name, prompt, active=active, bot=_bot)

                        self._send_json(200, {"ok": ok, "persona_id": pid_new} if ok else {"ok": False, "error": msg})

            except Exception as _e:

                self._send_json(200, {"ok": False, "error": "操作失败：%s" % str(_e)[:200]})

            return

        elif path == "/api/ai/knowledge":

            length = int(self.headers.get("Content-Length", "0") or 0)

            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"

            try:

                payload = _json.loads(raw) if raw else {}

            except Exception:

                payload = {}

            action = str(payload.get("action") or "").strip()

            _bot = str(payload.get("bot") or "")

            try:

                from modules.ai_persona import (

                    add_knowledge_base, update_knowledge_base, delete_knowledge_base,

                    add_knowledge_item, update_knowledge_item, delete_knowledge_item,

                )

                if action == "add_base":

                    ok, msg, bid = add_knowledge_base(

                        str(payload.get("name") or "").strip(),

                        active=bool(payload.get("active", True)),

                        bot=_bot,

                    )

                    self._send_json(200, {"ok": ok, "base_id": bid} if ok else {"ok": False, "error": msg})

                elif action == "update_base":

                    bid = int(payload.get("id"))

                    ok, msg = update_knowledge_base(

                        bid,

                        name=payload.get("name"),

                        active=payload.get("active"),

                        bot=_bot,

                    )

                    self._send_json(200, {"ok": True} if ok else {"ok": False, "error": msg})

                elif action == "delete_base":

                    bid = int(payload.get("id"))

                    ok = delete_knowledge_base(bid, bot=_bot)

                    self._send_json(200, {"ok": True, "deleted": 1 if ok else 0} if ok else {"ok": False, "error": "知识库不存在"})

                elif action == "add_item":

                    bid = int(payload.get("base_id"))

                    ok, msg = add_knowledge_item(

                        bid,

                        str(payload.get("title") or "").strip(),

                        str(payload.get("content") or "").strip(),

                        bot=_bot,

                    )

                    self._send_json(200, {"ok": True} if ok else {"ok": False, "error": msg})

                elif action == "update_item":

                    bid = int(payload.get("base_id"))

                    iid = int(payload.get("id"))

                    ok, msg = update_knowledge_item(

                        bid, iid,

                        title=payload.get("title"),

                        content=payload.get("content"),

                        enabled=payload.get("enabled"),

                        bot=_bot,

                    )

                    self._send_json(200, {"ok": True} if ok else {"ok": False, "error": msg})

                elif action == "delete_item":

                    bid = int(payload.get("base_id"))

                    iid = int(payload.get("id"))

                    ok = delete_knowledge_item(bid, iid, bot=_bot)

                    self._send_json(200, {"ok": True, "deleted": 1 if ok else 0} if ok else {"ok": False, "error": "条目不存在"})

                else:

                    self._send_json(200, {"ok": False, "error": "未知 action: %s" % action})

            except Exception as _e:

                self._send_json(200, {"ok": False, "error": "操作失败：%s" % str(_e)[:200]})

            return

        elif path == "/api/ai/chat":

            length = int(self.headers.get("Content-Length", "0") or 0)

            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"

            try:

                payload = _json.loads(raw) if raw else {}

            except Exception:

                payload = {}

            _bot = str(payload.get("bot") or "")

            _pid_raw = payload.get("provider_id")

            print("[console_server] /api/ai/chat bot=%s provider=%s" % (_bot, _pid_raw), flush=True)

            messages = _build_messages_from_payload(payload)

            if not messages:

                self._send_json(400, {"ok": False, "error": "消息不能为空"})

                return

            provider_id = _coerce_id(_pid_raw)

            with _lock:

                provider = None

                for p in _load_ai_providers(_bot):

                    if p.get("id") == provider_id:

                        provider = p

                        break

            if not provider:

                avail = ", ".join(["#%d %s" % (p.get("id"), p.get("name") or "?") for p in _load_ai_providers(_bot)]) or "（无）"

                if provider_id is None or provider_id == "":

                    self._send_json(400, {"ok": False, "error": "未选择供应商，请先在「模型管理」中添加",

                                          "available_providers": [p.get("id") for p in _load_ai_providers(_bot)]})

                else:

                    self._send_json(400, {"ok": False,

                                          "error": "供应商不存在（id=%s），请先在「模型管理」中添加。可用：%s" % (provider_id, avail),

                                          "available_providers": [p.get("id") for p in _load_ai_providers(_bot)]})

                return

            # 注入人格设置 + 知识库上下文（使后台 AI 对话测试同样生效）

            try:

                from modules.ai_persona import build_ai_context

                _p, _k = build_ai_context(str(payload.get("bot") or ""))

            except Exception:

                _p, _k = "", ""

            _chat_messages = []

            if _p:

                _chat_messages.append({"role": "system", "content": _p})

            if _k:

                _chat_messages.append({"role": "system", "content": _k})

            _chat_messages.extend(list(messages))

            try:

                reply = _call_provider_chat(provider, _chat_messages)

            except urllib.error.HTTPError as e:

                detail = ""

                try:

                    detail = e.read().decode("utf-8", errors="replace")

                except Exception:

                    pass

                self._send_json(200, {"ok": False, "error": "接口返回错误 %s：%s" % (e.code, detail[:300])})

                return

            except urllib.error.URLError as e:

                self._send_json(200, {"ok": False, "error": _describe_urllib_err(e)})

                return

            except Exception as e:

                self._send_json(200, {"ok": False, "error": "调用失败：%s" % str(e)})

                return

            if not reply:

                self._send_json(200, {"ok": False, "error": "模型返回内容为空"})

                return

            self._send_json(200, {"ok": True, "reply": reply, "model": provider.get("model")})

        elif path == "/api/ai/providers/test":

            length = int(self.headers.get("Content-Length", "0") or 0)

            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"

            try:

                payload = _json.loads(raw) if raw else {}

            except Exception:

                payload = {}

            provider = _resolve_provider_for_test(payload, bot=str(payload.get("bot") or ""))

            if not provider.get("url") or not provider.get("model"):

                self._send_json(200, {"ok": False, "error": "请填写 API 地址和模型"})

                return

            test_msg = str(payload.get("message") or "你好，请只回复「连接成功」四个字。").strip()

            test_messages = [{"role": "user", "content": test_msg}]

            t0 = time.time()

            try:

                reply = _call_provider_chat(provider, test_messages)

                elapsed = int((time.time() - t0) * 1000)

                if not reply:

                    self._send_json(200, {"ok": False, "error": "模型返回内容为空", "elapsed_ms": elapsed})

                else:

                    self._send_json(200, {"ok": True, "message": "连接成功",

                                          "reply": reply[:200], "elapsed_ms": elapsed})

            except urllib.error.HTTPError as e:

                detail = ""

                try:

                    detail = e.read().decode("utf-8", errors="replace")

                except Exception:

                    pass

                self._send_json(200, {"ok": False, "error": "接口返回错误 %s：%s" % (e.code, detail[:300])})

            except urllib.error.URLError as e:

                self._send_json(200, {"ok": False, "error": _describe_urllib_err(e)})

            except Exception as e:

                self._send_json(200, {"ok": False, "error": "调用失败：%s" % str(e)})

            return

        elif path == "/api/ai/providers/models":

            length = int(self.headers.get("Content-Length", "0") or 0)

            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"

            try:

                payload = _json.loads(raw) if raw else {}

            except Exception:

                payload = {}

            provider = _resolve_provider_for_test(payload, bot=str(payload.get("bot") or ""))

            if not provider.get("url"):

                self._send_json(200, {"ok": False, "error": "请填写 API 地址"})

                return

            ptype = str(provider.get("type") or "openai").strip().lower()

            endpoint = ""

            try:

                if ptype == "ollama":

                    base = provider["url"].rstrip("/")

                    endpoint = base + "/api/tags"

                    req = urllib.request.Request(endpoint, headers={"Content-Type": "application/json"})

                    with urllib.request.urlopen(req, timeout=20) as resp:

                        data = _json.loads(resp.read().decode("utf-8", errors="replace"))

                    models = [m.get("name") for m in (data.get("models") or []) if m.get("name")]

                else:

                    base = provider["url"].rstrip("/")

                    # 自动去除常见的 chat 端点尾缀以推出 /models

                    for tail in ("/chat/completions", "/completions", "/messages", "/responses"):

                        if base.endswith(tail):

                            base = base[: -len(tail)].rstrip("/")

                            break

                    endpoint = base + "/models"

                    key = (provider.get("key") or "").strip()

                    headers = {"Content-Type": "application/json"}

                    if key:

                        headers["Authorization"] = "Bearer " + key

                    req = urllib.request.Request(endpoint, headers=headers)

                    with urllib.request.urlopen(req, timeout=20) as resp:

                        data = _json.loads(resp.read().decode("utf-8", errors="replace"))

                    models = [m.get("id") for m in (data.get("data") or []) if m.get("id")]

                self._send_json(200, {"ok": True, "models": models, "endpoint": endpoint})

            except urllib.error.HTTPError as e:

                detail = ""

                try:

                    detail = e.read().decode("utf-8", errors="replace")

                except Exception:

                    pass

                err_msg = _format_models_error(e.code, detail, provider)

                self._send_json(200, {"ok": False, "error": err_msg, "endpoint": endpoint})

            except urllib.error.URLError as e:

                self._send_json(200, {"ok": False, "error": _describe_urllib_err(e), "endpoint": endpoint})

            except Exception as e:

                self._send_json(200, {"ok": False, "error": "获取模型列表失败：%s" % str(e), "endpoint": endpoint})

            return

        elif path == "/api/scheduled-tasks":

            length = int(self.headers.get("Content-Length", "0") or 0)

            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"

            try:

                payload = _json.loads(raw) if raw else {}

            except Exception:

                payload = {}

            # 仅更新启用状态

            tid = payload.get("id")

            if tid is not None and "name" not in payload:

                with _scheduler_lock:

                    for t in _scheduled_tasks:

                        if t.get("id") == tid:

                            t["enabled"] = bool(payload.get("enabled", True))

                            t["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

                            _save_scheduled_tasks()

                            self._send_json(200, {"ok": True, "item": t})

                            return

                self._send_json(404, {"ok": False, "error": "任务不存在"})

                return

            name = str(payload.get("name") or "").strip()

            bot = str(payload.get("bot") or "").strip()

            task_type = str(payload.get("type") or "group").strip()

            cron = str(payload.get("cron") or "").strip()

            target_type = str(payload.get("target_type") or "指定群聊").strip()

            target_group = str(payload.get("target_group") or "").strip()

            msg_type = str(payload.get("msg_type") or "text").strip()

            content = str(payload.get("content") or "").strip()

            enabled = bool(payload.get("enabled", True))

            if not name:

                self._send_json(400, {"ok": False, "error": "任务名称不能为空"})

                return

            if not bot:

                self._send_json(400, {"ok": False, "error": "请选择机器人"})

                return

            if not cron:

                self._send_json(400, {"ok": False, "error": "Cron 表达式不能为空"})

                return

            if task_type not in ("group", "system"):

                task_type = "group"

            if msg_type not in ("text", "markdown"):

                msg_type = "text"

            if task_type == "group" and not target_group:

                self._send_json(400, {"ok": False, "error": "请选择目标群"})

                return

            with _scheduler_lock:

                global _scheduled_tasks_seq

                if tid is not None:

                    for t in _scheduled_tasks:

                        if t.get("id") == tid:

                            t["name"] = name

                            t["bot"] = bot

                            t["type"] = task_type

                            t["cron"] = cron

                            t["target_type"] = target_type

                            t["target_group"] = target_group

                            t["msg_type"] = msg_type

                            t["content"] = content

                            t["enabled"] = enabled

                            t["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

                            _save_scheduled_tasks()

                            self._send_json(200, {"ok": True, "item": t})

                            return

                    self._send_json(404, {"ok": False, "error": "任务不存在"})

                    return

                _scheduled_tasks_seq += 1

                new_t = {

                    "id": _scheduled_tasks_seq,

                    "name": name,

                    "bot": bot,

                    "type": task_type,

                    "cron": cron,

                    "target_type": target_type,

                    "target_group": target_group,

                    "msg_type": msg_type,

                    "content": content,

                    "enabled": enabled,

                    "exec_count": 0,

                    "last_exec": None,

                    "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),

                    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),

                }

                _scheduled_tasks.append(new_t)

                _save_scheduled_tasks()

            self._send_json(200, {"ok": True, "item": new_t})

            return

        elif path == "/api/admin/add":

            length = int(self.headers.get("Content-Length", "0") or 0)

            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"

            try:

                payload = _json.loads(raw) if raw else {}

            except Exception:

                payload = {}

            _id = str(payload.get("id") or "").strip()

            if not _id:

                self._send_json(400, {"ok": False, "error": "管理员 ID（QQ号或openid）不能为空"})

                return

            with _admin_api_lock:

                _admins = _load_admin_list()

                if _id in _admins:

                    self._send_json(200, {"ok": True, "admins": _admins, "message": "该管理员已存在"})

                    return

                _admins.append(_id)

                _res = _save_admin_list(_admins)

            if not _res.get("ok"):

                self._send_json(500, _res)

                return

            self._send_json(200, {"ok": True, "admins": _res["admins"], "message": "已添加管理员 %s" % _id})

            return

        elif path == "/api/admin/remove":

            length = int(self.headers.get("Content-Length", "0") or 0)

            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"

            try:

                payload = _json.loads(raw) if raw else {}

            except Exception:

                payload = {}

            _id = str(payload.get("id") or "").strip()

            if not _id:

                self._send_json(400, {"ok": False, "error": "管理员 ID 不能为空"})

                return

            with _admin_api_lock:

                _admins = _load_admin_list()

                if _id not in _admins:

                    self._send_json(200, {"ok": True, "admins": _admins, "message": "该管理员不在名单中"})

                    return

                _admins = [a for a in _admins if a != _id]

                _res = _save_admin_list(_admins)

            if not _res.get("ok"):

                self._send_json(500, _res)

                return

            self._send_json(200, {"ok": True, "admins": _res["admins"], "message": "已移除管理员 %s" % _id})

            return

        elif path == "/api/admin/restart":

            try:

                _restart_bot()

            except Exception as _e:  # noqa: BLE001

                self._send_json(500, {"ok": False, "error": "重启失败: %s" % _e})

                return

            self._send_json(200, {"ok": True, "message": "已发送重启指令，机器人即将重启"})

            return

        elif path == "/api/admin/shutdown":

            try:

                _shutdown_bot()

            except Exception as _e:  # noqa: BLE001

                self._send_json(500, {"ok": False, "error": "关机失败: %s" % _e})

                return

            self._send_json(200, {"ok": True, "message": "已发送关机指令，机器人即将关闭"})

            return

        else:

            self._send_json(404, {"error": "not_found", "path": path})

    def do_DELETE(self):

        u = urlparse(self.path)

        path = u.path.rstrip("/") or "/"

        q = parse_qs(u.query)

        if path == "/api/ai/providers":

            _bot = parse_qs(u.query).get("bot", [""])[0]

            try:

                pid = int(q.get("id", [""])[0])

            except Exception:

                self._send_json(400, {"ok": False, "error": "id 无效"})

                return

            with _lock:

                _ps = _load_ai_providers(_bot)

                before = len(_ps)

                _ps[:] = [p for p in _ps if p.get("id") != pid]

                deleted = before - len(_ps)

                if deleted:

                    _save_ai_providers(_bot)

            self._send_json(200, {"ok": True, "deleted": deleted})

        elif path == "/api/ai/sensitive-words":

            try:

                wid = int(q.get("id", [""])[0])

            except Exception:

                self._send_json(400, {"ok": False, "error": "id 无效"})

                return

            with _lock:

                before = len(_sensitive_words)

                _sensitive_words[:] = [w for w in _sensitive_words if w.get("id") != wid]

                deleted = before - len(_sensitive_words)

                if deleted:

                    _save_sensitive_words()

            self._send_json(200, {"ok": True, "deleted": deleted})

        elif path == "/api/ai/knowledge":

            kind = q.get("kind", ["item"])[0]

            _bot = parse_qs(u.query).get("bot", [""])[0]

            try:

                if kind == "base":

                    bid = int(q.get("id", [""])[0])

                else:

                    bid = int(q.get("base_id", [""])[0])

                    wid = int(q.get("id", [""])[0])

            except Exception:

                self._send_json(400, {"ok": False, "error": "参数无效"})

                return

            try:

                if kind == "base":

                    from modules.ai_persona import delete_knowledge_base

                    ok = delete_knowledge_base(bid, bot=_bot)

                    self._send_json(200, {"ok": True, "deleted": 1 if ok else 0} if ok else {"ok": False, "error": "知识库不存在"})

                else:

                    from modules.ai_persona import delete_knowledge_item

                    ok = delete_knowledge_item(bid, wid, bot=_bot)

                    self._send_json(200, {"ok": True, "deleted": 1 if ok else 0} if ok else {"ok": False, "error": "条目不存在"})

            except Exception as _e:

                self._send_json(200, {"ok": False, "error": "删除失败：%s" % str(_e)[:200]})

            return

        elif path == "/api/scheduled-tasks":

            try:

                tid = int(q.get("id", [""])[0])

            except Exception:

                self._send_json(400, {"ok": False, "error": "id 无效"})

                return

            with _scheduler_lock:

                before = len(_scheduled_tasks)

                _scheduled_tasks[:] = [t for t in _scheduled_tasks if t.get("id") != tid]

                deleted = before - len(_scheduled_tasks)

                if deleted:

                    _save_scheduled_tasks()

            self._send_json(200, {"ok": True, "deleted": deleted})

        else:

            self._send_json(404, {"error": "not_found", "path": path})

def _start_admin_api_server(host="127.0.0.1", port=9988):

    global _admin_api_started, _admin_httpd

    with _admin_api_lock:

        if _admin_api_started:

            return True

        import time as _tt

        httpd = None

        for _attempt in range(10):

            try:

                httpd = ThreadingHTTPServer((host, port), _AdminAPIHandler)

                break

            except OSError as e:

                if _attempt < 9:

                    print("[console_server] admin api 端口 %d 暂被占用，重试(%d/10): %s"

                          % (port, _attempt + 1, e), flush=True)

                    try:

                        _tt.sleep(0.5)

                    except Exception:

                        pass

                else:

                    print("[console_server] admin api 端口 %d 不可用: %s" % (port, e),

                          flush=True)

                    return False

        try:

            t = threading.Thread(

                target=httpd.serve_forever,

                name="xiaoliu-admin-api",

                daemon=True,

            )

            t.start()

            _admin_httpd = httpd

            _admin_api_started = True

            print("[console_server] admin api listening on http://%s:%d/" % (host, port), flush=True)

            # 启动定时任务调度器

            try:

                _start_scheduled_tasks_scheduler()

            except Exception as e:

                print("[console_server] 启动定时任务调度器失败: %s" % e, flush=True)

            return True

        except Exception as e:

            print("[console_server] admin api 启动异常: %s" % e, flush=True)

            return False

