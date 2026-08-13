# -*- coding: utf-8 -*-
"""多机器人凭证管理。

把「单个写死在 config.py 的 APPID/SECRET」升级为「data/bots.json 里的机器人列表」，
支持同时绑定并运行多个 QQ 官方机器人（参考 XuanJi 的多实例设计）。

- 首次运行（bots.json 不存在）会从 modules/config.py 的 APPID/SECRET 播种一个默认 bot，
  保证既有单 bot 部署零迁移成本。
- 每个 bot 记录：appid / secret / environment(sandbox|production) /
  event_mode(websocket|webhook) / enabled / name。
- 运行时由 bot.py 读取 get_enabled_bots() 并发启动多个 botpy 客户端。
"""

import os
import json

from . import config

# bots.json 路径：项目根 / data / bots.json
_BOT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_BOT_DIR)
BOTS_FILE = os.path.join(_PROJECT_ROOT, "data", "bots.json")


def _default_bots():
    """从 config.py 播种默认单 bot（仅在 bots.json 缺失时使用）。"""
    appid = getattr(config, "APPID", "") or ""
    secret = getattr(config, "SECRET", "") or ""
    env = getattr(config, "BOT_ENVIRONMENT", "sandbox") or "sandbox"
    mode = getattr(config, "BOT_EVENT_MODE", "websocket") or "websocket"
    if appid and secret:
        return [{
            "appid": str(appid).strip(),
            "secret": str(secret).strip(),
            "environment": env,
            "event_mode": mode,
            "enabled": True,
            "name": "",
        }]
    return []


def _normalize(bot):
    appid = str(bot.get("appid", "") or "").strip()
    secret = str(bot.get("secret", "") or "").strip()
    env = str(bot.get("environment", "sandbox") or "sandbox").strip().lower()
    mode = str(bot.get("event_mode", "websocket") or "websocket").strip().lower()
    if env not in ("sandbox", "production"):
        env = "sandbox"
    if mode not in ("websocket", "webhook"):
        mode = "websocket"
    return {
        "appid": appid,
        "secret": secret,
        "environment": env,
        "event_mode": mode,
        "enabled": bool(bot.get("enabled", True)),
        "name": str(bot.get("name", "") or "").strip(),
    }


def load_bots():
    """返回全部 bot（已规范化、过滤掉 appid/secret 为空的）。"""
    if not os.path.isfile(BOTS_FILE):
        bots = _default_bots()
        save_bots(bots)
        return bots
    try:
        with open(BOTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            raw = data.get("bots", []) or []
        elif isinstance(data, list):
            raw = data
        else:
            raw = []
        out = []
        for b in raw:
            nb = _normalize(b)
            if nb["appid"] and nb["secret"]:
                out.append(nb)
        return out
    except Exception as e:
        print("[bot_manager] 读取 bots.json 失败，回退默认: %s" % e, flush=True)
        return _default_bots()


def save_bots(bots):
    """原子写回 bots.json。"""
    os.makedirs(os.path.dirname(BOTS_FILE), exist_ok=True)
    tmp = BOTS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"bots": bots}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, BOTS_FILE)
    return True


def get_enabled_bots():
    """返回已启用的 bot 列表。"""
    return [b for b in load_bots() if b.get("enabled")]


def get_bot(appid):
    for b in load_bots():
        if b["appid"] == appid:
            return b
    return None


def upsert_bot(appid, secret, environment="sandbox", event_mode="websocket",
               name="", enabled=True):
    """新增或更新一个 bot（按 appid 去重）。"""
    appid = str(appid or "").strip()
    secret = str(secret or "").strip()
    if not appid or not secret:
        return False, "AppID 和 Secret 不能为空"
    bots = load_bots()
    for b in bots:
        if b["appid"] == appid:
            b["secret"] = secret
            b["environment"] = environment
            b["event_mode"] = event_mode
            b["enabled"] = bool(enabled)
            if name:
                b["name"] = name
            save_bots(bots)
            return True, None
    bots.append(_normalize({
        "appid": appid,
        "secret": secret,
        "environment": environment,
        "event_mode": event_mode,
        "enabled": enabled,
        "name": name or ("机器人 %s" % appid),
    }))
    save_bots(bots)
    return True, None


def remove_bot(appid):
    bots = load_bots()
    new = [b for b in bots if b["appid"] != appid]
    if len(new) == len(bots):
        return False, "未找到该机器人"
    save_bots(new)
    return True, None


def set_enabled(appid, enabled):
    bots = load_bots()
    found = False
    for b in bots:
        if b["appid"] == appid:
            b["enabled"] = bool(enabled)
            found = True
    if not found:
        return False, "未找到该机器人"
    save_bots(bots)
    return True, None


def mask_appid(appid):
    """脱敏展示：YOUR_APPID -> 10****41。"""
    appid = str(appid or "")
    if len(appid) <= 4:
        return appid
    return appid[:2] + "****" + appid[-2:]
