# -*- coding: utf-8 -*-
"""
原神查询外置插件 (小流萤 · plugins/) — 练度面板 + UID 绑定 + 角色名直查 + 面板缓存

数据源：Enka Network 公开 API (https://enka.network/api/uid/{uid})
- 无需米游社 cookie / 登录 / 封号风险
- 玩家冒险等阶 / 世界等级 / 展示角色练度

触发方式（群里或私聊 @机器人）：
  1) 原神绑定 123456789     → 绑定 UID 到发送者 openid
     (已绑定后) 原神 角色名  → 直接查该角色面板，无需每次发 UID
     例：原神 胡桃 / 原神 芙宁娜
  2) #更新面板 [角色名] / #刷新面板 [角色名]
                           → 跳过 Enka 缓存强制重拉 (15 分钟 TTL)
  3) 原神 uid 123456789 [角色名]  (原格式仍可用，不绑也能查)
     原神面板 123456789 / ys 123456789 / 原神 123456789
  4) 原神解绑              → 删除绑定
  5) 我的原神 / 原神绑定查询 → 查看当前绑定
  6) 原神帮助              → 用法

持久化:
  data/genshin_bindings.json  -> {openid: {uid, updated_at}}
  data/cache/genshin_panel_<uid>.json  -> Enka JSON, TTL 15 分钟
"""

import asyncio
import json
import os
import re
import threading
import time
# 静态映射表与格式化助手统一从 lib.genshin_panel_miao.maps 导入 (单一数据源)
from lib.genshin_panel_miao.maps import (
    AVATAR_ID2NAME, WEAPON_ID2NAME, REGION_MAP,
    FIGHT_PROP, _PERCENT_PROPS, PIECE_NAMES,
    _fmt_stat, _weapon_name, _set_name,
)


PLUGIN = {
    "key": "genshin",
    "name": "原神查询",
    "priority": 500,
    "description": "原神玩家面板/练度查询 (Enka Network，无需 cookie)；UID 可绑定后下次发角色名直查",
}

# Enka 镜像列表 (参照 gsuid_core GenshinUID 的 ENKA_API=["enka","microgg"] 双镜像容灾)
# microgg (profile.microgg.cn) 是 Enka 国内加速镜像, 同一 GET /api/uid/{uid} 协议与 JSON 结构完全一致。
ENKA_MIRRORS = [
    ("enka", "https://enka.network/api/uid/{uid}"),
    ("microgg", "http://profile.microgg.cn/api/uid/{uid}"),
]
UA = "Mozilla/5.0 (XiaoLiuYingBot) genshin-plugin"
TIMEOUT = 12


# ---- 持久化路径 ----
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_PROJ_ROOT, "data")
_BINDING_PATH = os.path.join(_DATA_DIR, "genshin_bindings.json")
_CACHE_DIR = os.path.join(_DATA_DIR, "cache")
_CACHE_TTL = 15 * 60  # 15 分钟

# Enka 镜像偏好持久化 (经 #切换api 切换, 默认 enka)
_MIRROR_STATE_PATH = os.path.join(_DATA_DIR, "genshin_mirror.json")


def _load_default_mirror():
    try:
        if os.path.isfile(_MIRROR_STATE_PATH):
            with open(_MIRROR_STATE_PATH, "r", encoding="utf-8") as f:
                d = json.load(f)
                if d.get("mirror") in ("enka", "microgg"):
                    return d["mirror"]
    except Exception:
        pass
    return "enka"


def _save_default_mirror(m):
    try:
        os.makedirs(os.path.dirname(_MIRROR_STATE_PATH), exist_ok=True)
        with open(_MIRROR_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump({"mirror": m}, f, ensure_ascii=False)
    except Exception:
        pass


_DEFAULT_MIRROR = _load_default_mirror()


def switch_api():
    """切换默认 Enka 镜像 (enka <-> microgg), 与 gsuid_core 的 switch_api 对应."""
    global _DEFAULT_MIRROR
    _DEFAULT_MIRROR = "microgg" if _DEFAULT_MIRROR == "enka" else "enka"
    _save_default_mirror(_DEFAULT_MIRROR)
    url = dict(ENKA_MIRRORS).get(_DEFAULT_MIRROR)
    return "🔀 已切换 Enka 默认镜像为：%s（%s）" % (_DEFAULT_MIRROR, url)


_FILE_LOCK = threading.RLock()  # 防止多线程并发读写 bindings.json 损坏


def _cache_path(uid):
    return os.path.join(_CACHE_DIR, "genshin_panel_%s.json" % uid)


def _load_bindings():
    with _FILE_LOCK:
        if not os.path.isfile(_BINDING_PATH):
            return {}
        try:
            with open(_BINDING_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}


def _save_bindings(b):
    """原子写入 (Windows 也不丢)."""
    with _FILE_LOCK:
        os.makedirs(os.path.dirname(_BINDING_PATH), exist_ok=True)
        tmp = _BINDING_PATH + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(b, f, ensure_ascii=False, indent=2)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            os.replace(tmp, _BINDING_PATH)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def get_binding(openid):
    if not openid:
        return None
    info = _load_bindings().get(openid) or {}
    uid = str(info.get("uid") or "")
    return uid or None


def set_binding(openid, uid):
    if not openid or not uid:
        return
    b = _load_bindings()
    b[openid] = {"uid": str(uid), "updated_at": time.time()}
    _save_bindings(b)


def clear_binding(openid):
    if not openid:
        return
    b = _load_bindings()
    if openid in b:
        del b[openid]
        _save_bindings(b)


# ---- Enka 缓存 ----

def _read_cache(uid):
    """返回 (raw_dict, age_secs) 或 (None, _). TTL 外返 None."""
    p = _cache_path(uid)
    if not os.path.isfile(p):
        return None
    try:
        age = time.time() - os.path.getmtime(p)
        if age > _CACHE_TTL:
            return None
        with open(p, "r", encoding="utf-8") as f:
            return (json.load(f), age)
    except Exception:
        return None


def _write_cache(uid, raw):
    p = _cache_path(uid)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _invalidate_cache(uid):
    p = _cache_path(uid)
    for path in (p, p + ".tmp"):
        try:
            os.unlink(path)
        except OSError:
            pass


# ---- 触发正则 ----

_HELP_RE = re.compile(r"^#\s*(?:原神|ys|genshin)\s*(?:帮助|help|用法)$", re.IGNORECASE)
# 原神绑定 123456789 / 原神绑定uid123456789
_BIND_RE = re.compile(r"^#\s*(?:原神|ys|genshin)\s*绑定\s*(?:uid[:\s]*)?(\d{8,11})\s*$", re.IGNORECASE)
_UNBIND_RE = re.compile(r"^#\s*(?:原神|ys|genshin)\s*(?:解绑|取消绑定|删除绑定)\s*$", re.IGNORECASE)
_MY_RE = re.compile(r"^#\s*(?:我的原神|原神绑定(?:查询|状态)|原神绑定信息)\s*$", re.IGNORECASE)
_REFRESH_RE = re.compile(r"^\s*#\s*(?:更新面板|刷新面板)\s*(.*)$")
# 原神 uid 123456789 [角色] / ys 123456789 / 原神面板 123456789
# uid/面板 可选 → 同时支持 `原神 123456789 角色名` 和 `原神 uid 123456789 角色名`
_TRIGGER_RE = re.compile(
    r"^#\s*(?:原神|ys|genshin)\s*(?:uid|uid:|面板)?\s*(\d{8,11})\s*(.*)$", re.IGNORECASE
)
# 角色名直查: 原神 胡桃  (已绑定用户) — 不匹配"绑定/uid/面板/帮助/更新/刷新/解绑"等关键词
# 角色名直查 (需已绑定 UID): 支持三种格式
#   原神 角色名    (主入口)
#   角色名 面板     (云崽风格简写)
#   #角色名 面板    (有 # 前缀 + "面板" 后缀)
_CHAR_ONLY_RE = re.compile(
    r"^#\s*(?:原神|ys|genshin)\s+"
    r"(?!绑定|uid|uid:|列表|详情|查|查询|帮助|help|用法|刷新|更新|解绑|取消绑定)"
    r"([一-龥A-Za-z·\u3000]{2,8})\s*$"
)
# 负向预查 (?!更新面板|刷新面板) 关键：避免与 #更新面板/#刷新面板 刷新指令语法重叠
# （否则 #更新面板 / #刷新面板 会被本正则误判为「角色名=更新/刷新」的面板查询，二者冲突）
_CHAR_PANEL_RE = re.compile(
    r"^#\s*(?:原神|ys|genshin)?\s*(?!更新面板|刷新面板)([一-龥A-Za-z·\u3000]{2,8})\s*面板\s*$"
)
# 切换 Enka 镜像 (参照 gsuid_core switch_api): #切换api / 切换enka / 切换镜像
_SWITCH_RE = re.compile(r"^\s*#\s*(?:切换\s*api|切换\s*enka|切换\s*镜像)\s*$", re.IGNORECASE)


_HELP_TEXT = (
    "【原神查询 · 用法】\n"
    "⚠️ 所有指令必须以 # 开头\n"
    "1. 绑定 UID：#原神绑定 123456789\n"
    "   绑定后无需每次发 UID，直接发「#原神 角色名」即可。\n"
    "   例：#原神 胡桃 / #原神 芙宁娜\n"
    "2. 强制刷新：#更新面板 [角色名]\n"
    "   (Enka 默认 15 分钟缓存，刷新绕过)\n"
    "3. 原格式仍可用：#原神 uid 123456789 [角色名]\n"
    "4. 查绑定：#我的原神    解绑：#原神解绑\n"
    "数据源：Enka Network 公开 API（无需 cookie），双镜像容灾：\n"
    "  enka.network + profile.microgg.cn (国内加速)，任一不可用自动切换。\n"
    "5. 切换镜像：#切换api   (enka ↔ microgg，持久化)\n"
    "提示：对方需在游戏内打开「角色展柜」才能查到角色练度。"
)


# ============================================================
# Enka 查询 / 解析 / 文本回退
# ============================================================

async def query_enka(uid, use_cache=True):
    """拉取 Enka 玩家面板 (use_cache=True 时先尝试本地 15 分钟缓存).
    返回 (raw_data, 来源) 或 ({"error": ...}, "error").

    gsuid_core 风格双镜像容灾: 默认镜像 (_DEFAULT_MIRROR) 优先, 失败自动切换另一个镜像重试。
    来源字段为 "cache" / "enka" / "microgg", 供前端展示实际命中镜像。
    """
    if use_cache:
        cached = _read_cache(uid)
        if cached:
            return cached[0], "cache"
    try:
        import aiohttp
    except Exception:
        return {"error": "运行环境缺少 aiohttp"}, "error"

    # 镜像顺序: 默认镜像优先, 其余作为容灾回退
    order = [m for m in ENKA_MIRRORS if m[0] == _DEFAULT_MIRROR] + \
            [m for m in ENKA_MIRRORS if m[0] != _DEFAULT_MIRROR]

    last_err = None
    for name, url_tpl in order:
        url = url_tpl.format(uid=uid)
        try:
            async with aiohttp.ClientSession(headers={"User-Agent": UA}) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as resp:
                    if resp.status == 200:
                        raw = await resp.json(content_type=None)
                        _write_cache(uid, raw)
                        return raw, name
                    if resp.status == 404:
                        # 玩家不存在 / 未开展柜 —— 换镜像也不会变, 直接报明确错误
                        return ({"error": "UID %s 不存在或未开启角色展柜（Enka 返回 404）。" % uid}, "error")
                    if resp.status == 429:
                        last_err = "镜像 %s 请求过于频繁（HTTP 429），请稍后再试。" % name
                    elif resp.status in (500, 502, 503, 504):
                        last_err = "镜像 %s 暂时不可用（HTTP %s）。" % (name, resp.status)
                    else:
                        last_err = "镜像 %s 返回 HTTP %s（UID %s 可能不存在或服务器维护）。" % (name, resp.status, uid)
        except asyncio.TimeoutError:
            last_err = "镜像 %s 查询超时（网络不太稳定），尝试下一个镜像…" % name
        except Exception as e:
            last_err = "镜像 %s 查询失败：%s" % (name, e)
        # 非 404 的 HTTP 错误或异常: 继续尝试下一个镜像
    if last_err:
        return ({"error": last_err + "\n可发送「#切换api」更换默认镜像后重试。"}, "error")
    return ({"error": "所有 Enka 镜像均不可用，请稍后重试或发送「#切换api」。"}, "error")


def parse_enka(data, uid):
    if not isinstance(data, dict):
        return {"error": "数据格式异常"}
    if "playerInfo" not in data:
        return {"error": "Enka 服务器维护中，或该 UID 不存在。可发送「#切换api」更换镜像后重试。"}
    player = data.get("playerInfo", {})
    chars = []
    for c in data.get("avatarInfoList", []) or []:
        aid = str(c.get("avatarId"))
        name = AVATAR_ID2NAME.get(aid, "角色#%s" % aid)
        level = c.get("propMap", {}).get("4001", {}).get("val", 0)
        friendship = c.get("fetterInfo", {}).get("expLevel", 0)
        equips = c.get("equipList", []) or []
        weapon = None
        if equips:
            w = equips[-1]
            wf = w.get("flat", {})
            wlevel = w.get("weapon", {}).get("level", 0)
            refine = 1
            aff = w.get("weapon", {}).get("affixMap", {})
            if aff:
                refine = max(aff.values()) + 1
            wstats = wf.get("weaponStats", []) or []
            wmain = _fmt_stat(wstats[0]["appendPropId"], wstats[0]["statValue"]) if wstats else ""
            weapon = {"name": _weapon_name(w.get("itemId")), "level": wlevel, "refine": refine, "main": wmain}
        artifacts = []
        for idx, a in enumerate(equips[:-1] if equips else []):
            af = a.get("flat", {})
            rel = a.get("reliquary", {})
            piece = PIECE_NAMES[idx] if idx < len(PIECE_NAMES) else "圣遗物%d" % (idx + 1)
            setn = _set_name(rel.get("setId"))
            alevel = (rel.get("level") or 1) - 1
            main = af.get("reliquaryMainstat", {}) or {}
            main_str = _fmt_stat(main.get("mainPropId", ""), main.get("statValue", 0)) if main else ""
            subs = []
            for s in af.get("reliquarySubstats", []) or []:
                subs.append(_fmt_stat(s.get("appendPropId", ""), s.get("statValue", 0)))
            artifacts.append({"piece": piece, "set": setn, "level": alevel, "main": main_str, "subs": subs})
        talents = []
        skm = c.get("skillLevelMap", {}) or {}
        labels = ["普攻", "战技", "爆发"]
        for i, (k, v) in enumerate(skm.items()):
            if i < 3:
                talents.append({"label": labels[i], "level": v})
            else:
                talents.append({"label": "天赋%d" % (i - 2), "level": v})
        chars.append({"name": name, "level": level, "friendship": friendship,
                      "weapon": weapon, "artifacts": artifacts, "talents": talents})
    chars.sort(key=lambda x: -int(x["level"] or 0))
    return {
        "uid": uid,
        "nickname": player.get("nickname", ""),
        "level": player.get("level", 0),
        "world_level": player.get("worldLevel", 0),
        "achievements": player.get("finishAchievementNum", 0),
        "region": data.get("region", ""),
        "signature": (player.get("signature") or "").strip(),
        "raw": data,
        "chars": chars,
    }


def render_text(panel, detail_name=None):
    if "error" in panel:
        return "❌ 原神查询失败：" + panel["error"]
    region = REGION_MAP.get(panel.get("region", ""), panel.get("region", ""))
    lines = []
    lines.append("【原神面板】%s" % panel["nickname"])
    lines.append("UID %s · %s" % (panel["uid"], region or "未知区服"))
    lines.append("冒险等级 %s · 世界等级 %s · 成就 %s" % (panel["level"], panel["world_level"], panel["achievements"]))
    sig = panel.get("signature")
    if sig:
        lines.append("签名：%s" % sig)
    chars = panel.get("chars", [])
    if not chars:
        lines.append("— 未展示角色展柜（请在游戏内打开角色展柜）—")
        return "\n".join(lines)
    if detail_name:
        target = None
        for c in chars:
            if detail_name in c["name"] or c["name"] in detail_name:
                target = c
                break
        if not target:
            lines.append("未找到角色「%s」，展示角色：%s" % (detail_name, "、".join(c["name"] for c in chars)))
            return "\n".join(lines)
        lines.append("")
        lines.append("【%s 练度】Lv%s 好感%s" % (target["name"], target["level"], target["friendship"]))
        w = target["weapon"]
        if w:
            lines.append("武器：%s Lv%s 精炼%s（%s）" % (w["name"], w["level"], w["refine"], w["main"]))
        lines.append("圣遗物：")
        for a in target["artifacts"]:
            lines.append("  · %s · %s +%s" % (a["piece"], a["set"], a["level"]))
            lines.append("    主：%s" % a["main"])
            if a["subs"]:
                lines.append("    副：" + " / ".join(a["subs"]))
        tl = " ".join("%s%d" % (t["label"], t["level"]) for t in target["talents"])
        lines.append("天赋：%s" % tl)
        return "\n".join(lines)
    lines.append("展示角色 %d 个：" % len(chars))
    for c in chars:
        w = c["weapon"]
        wstr = "%s 精%s" % (w["name"], w["refine"]) if w else "无武器"
        sets = []
        for a in c["artifacts"]:
            if a["set"] not in sets:
                sets.append(a["set"])
        sstr = "+".join(sets) if sets else "无圣遗物"
        lines.append("  · %s Lv%s 好感%s | %s | %s" % (c["name"], c["level"], c["friendship"], wstr, sstr))
    lines.append("（发送「原神 uid %s 角色名」查看单角色练度）" % panel["uid"])
    return "\n".join(lines)


# ============================================================
# 渲染单角色面板图 (本地缓存 + 重新拉 Enka 走 force_refresh)
# ============================================================

def _resolve_alias(query):
    """把玩家输入的角色名/昵称解析成 miao 标准名. 解析失败返 None.

    注意: 若 query 本身就是 AVATAR_ID2NAME 中某角色的标准名, 也解析为该名.
    """
    if not query:
        return None
    try:
        from lib.genshin_panel_miao.maps import resolve_char_name
        return resolve_char_name(query)
    except Exception:
        return None


async def _send_char_panel(ctx, raw, uid, char_name):
    """由 raw Enka dict 直接渲染单角色面板图 (失败回退文本)."""
    try:
        from lib.genshin_panel_miao.adapter import build_card
        from lib.genshin_panel_miao.render import render_panel
        card = build_card(raw, uid, char_name)
        if card:
            png = await render_panel(card)
            if png:
                try:
                    from modules.common import send_local_image_for_scene
                    await send_local_image_for_scene(
                        ctx.api, ctx.scene, ctx.target_id, png,
                        content="%s 的练度面板" % card["char_name"],
                    )
                    return True
                except Exception as e:
                    await ctx.reply("（面板图发送失败: %s，已回退文本）\n%s" % (
                        e, render_text(parse_enka(raw, uid), detail_name=char_name)
                    ))
                    return True
            await ctx.reply("（面板图渲染失败，请查看 bot 控制台 stderr 输出；已回退文本）\n"
                            + render_text(parse_enka(raw, uid), detail_name=char_name))
            return True
    except Exception as e:
        panel = parse_enka(raw, uid)
        await ctx.reply("（面板图处理异常: %s，已回退文本）\n" % e
                        + render_text(panel, detail_name=char_name))
        return True
    return False


async def _send_panel_list(ctx, raw, uid):
    """渲染并发送玩家面板列表图 (miao avatar-list.html: 头像+命座+Lv+武器+圣遗物套装).

    失败时回退到 render_text 文本列表.
    """
    try:
        from lib.genshin_panel_miao.panel_list import build_avatar_list_data
        from lib.genshin_panel_miao.render import render_panel
        render_data = build_avatar_list_data(raw, uid)
        if not render_data.get("avatars"):
            await ctx.reply("⚠️ 该 UID 无展示角色数据 (请在游戏内打开角色展柜)。")
            return True
        png = await render_panel(render_data)
        if png:
            try:
                from modules.common import send_local_image_for_scene
                nickname = (raw.get("playerInfo") or {}).get("nickname") or ("UID %s" % uid)
                await send_local_image_for_scene(
                    ctx.api, ctx.scene, ctx.target_id, png,
                    content="📋 %s 的角色面板列表 (%d 角色)" % (nickname, len(render_data["avatars"])),
                )
                return True
            except Exception as e:
                await ctx.reply("（面板列表图发送失败: %s，已回退文本）\n%s" % (
                    e, render_text(parse_enka(raw, uid))
                ))
                return True
        await ctx.reply("（面板列表图渲染失败，请查看 bot 控制台 stderr 输出；已回退文本）\n"
                        + render_text(parse_enka(raw, uid)))
        return True
    except Exception as e:
        await ctx.reply("（面板列表图处理异常: %s，已回退文本）\n" % e
                        + render_text(parse_enka(raw, uid)))
        return True


# ============================================================
# 主分发
# ============================================================

async def handle(ctx) -> bool:
    content = (ctx.content or "").strip()
    if not content:
        return False

    # 1) 帮助
    if _HELP_RE.match(content):
        await ctx.reply(_HELP_TEXT)
        return True

    # 2) 绑定 UID
    m = _BIND_RE.match(content)
    if m:
        uid = m.group(1)
        set_binding(ctx.member_openid, uid)
        await ctx.reply(
            "✅ 已绑定 UID %s\n"
            "下次直接发「#原神 角色名」即可查询（例：#原神 胡桃）。\n"
            "强制刷新：#更新面板 [角色名]    解绑：#原神解绑" % uid
        )
        return True

    # 3) 解绑
    if _UNBIND_RE.match(content):
        clear_binding(ctx.member_openid)
        await ctx.reply("✅ 已解绑原神 UID。")
        return True

    # 4) 查绑定
    if _MY_RE.match(content):
        uid = get_binding(ctx.member_openid)
        if uid:
            await ctx.reply(
                "✅ 当前绑定 UID: %s\n"
                "发送「#原神 角色名」直查；强制刷新：#更新面板 [角色名]。" % uid
            )
        else:
            await ctx.reply("⚠️ 当前未绑定 UID。发送「#原神绑定 <UID>」绑定。")
        return True

    # 4.5) 切换 Enka 镜像 (gsuid_core switch_api 对应)
    if _SWITCH_RE.match(content):
        await ctx.reply(switch_api())
        return True

    # 5) 强制刷新 (绕过缓存)
    m = _REFRESH_RE.match(content)
    if m:
        uid = get_binding(ctx.member_openid)
        if not uid:
            await ctx.reply("⚠️ 请先发「#原神绑定 <UID>」绑定你的UID。")
            return True
        # 区分「用户没提供角色名」（应走面板列表）和「提供了但解析失败」（应报错）
        raw_name = (m.group(1) or "").strip()
        if raw_name:
            # 去掉可选前缀词（角色/详情/面板/查询/查）
            cleaned = re.sub(r"^(?:角色|详情|面板|查询|查)\s*", "", raw_name).strip()
            char_name = _resolve_alias(cleaned) if cleaned else None
            if char_name is None:
                await ctx.reply("⚠️ 无法识别角色名「%s」。请输入标准名 (如 胡桃/芙宁娜/雷电将军) 或别名 (如 雷神/水神/芙芙/护法夜叉)。" % raw_name)
                return True
        else:
            char_name = None  # 空输入：走「全角色面板列表」分支
        _invalidate_cache(uid)  # 确保 force_refresh 真的拉到新数据
        raw, source = await query_enka(uid, use_cache=False)
        if "error" in raw:
            await ctx.reply("❌ " + raw["error"])
            return True
        panel = parse_enka(raw, uid)
        if not char_name:
            # 无角色名: 渲染面板列表图 (miao avatar-list.html 风格)
            await _send_panel_list(ctx, raw, uid)
            return True
        # 单角色: 校验存在
        names = [c["name"] for c in panel.get("chars", [])]
        if not any(char_name == n or char_name in n or n in char_name for n in names):
            await ctx.reply("🔄 已刷新 UID %s。\n未找到角色「%s」，展示角色：%s" %
                            (uid, char_name, "、".join(names)))
            return True
        await ctx.reply("🔄 已刷新 (来源: %s)" % ("缓存" if source == "cache" else source))
        await _send_char_panel(ctx, raw, uid, char_name)
        return True

    # 6) 原格式: 原神 uid 123456789 [角色]
    m = _TRIGGER_RE.match(content)
    if m:
        uid = m.group(1)
        extra = (m.group(2) or "").strip()
        char_name = re.sub(r"^(?:角色|详情|查询|查|面板)\s*", "", extra).strip() or None
        if char_name:
            resolved = _resolve_alias(char_name)
            if resolved is None:
                await ctx.reply("⚠️ 无法识别角色名「%s」。请输入标准名或别名。" % char_name)
                return True
            char_name = resolved
        raw, source = await query_enka(uid, use_cache=True)
        if "error" in raw:
            await ctx.reply("❌ " + raw["error"])
            return True
        panel = parse_enka(raw, uid)
        if char_name:
            names = [c["name"] for c in panel.get("chars", [])]
            if not any(char_name == n or char_name in n or n in char_name for n in names):
                await ctx.reply(render_text(panel) + "\n\n⚠️ 未找到角色「%s」" % char_name)
                return True
            note = "⚡ 来源: %s 缓存" % source if source == "cache" else "🔄 来源: %s 实时" % source
            await ctx.reply(note)
            await _send_char_panel(ctx, raw, uid, char_name)
            return True
        # 无角色名: 渲染面板列表图 (与 #更新面板 行为一致)
        await _send_panel_list(ctx, raw, uid)
        return True

    # 7) 角色名直查: #原神 胡桃 / #胡桃面板 (已绑定用户)
    char_m = _CHAR_ONLY_RE.match(content) or _CHAR_PANEL_RE.match(content)
    if char_m:
        uid = get_binding(ctx.member_openid)
        if not uid:
            await ctx.reply("⚠️ 你还没绑定 UID。请先发「#原神绑定 <UID>」绑定。")
            return True
        raw_name = re.sub(r"^(?:角色|详情|面板|查询|查)\s*", "", char_m.group(1)).strip()
        if not raw_name or len(raw_name) < 2:
            return False
        char_name = _resolve_alias(raw_name)
        if char_name is None:
            await ctx.reply("⚠️ 无法识别角色名「%s」。请输入标准名 (胡桃/芙宁娜/雷电将军) 或别名 (雷神/水神/芙芙/护法夜叉)。" % raw_name)
            return True
        raw, source = await query_enka(uid, use_cache=True)
        if "error" in raw:
            await ctx.reply("❌ " + raw["error"])
            return True
        panel = parse_enka(raw, uid)
        names = [c["name"] for c in panel.get("chars", [])]
        if not any(char_name == n or char_name in n or n in char_name for n in names):
            await ctx.reply(render_text(panel) + "\n\n⚠️ 未找到角色「%s」" % char_name)
            return True
        note = "⚡ 来源: %s 缓存" % source if source == "cache" else "🔄 来源: %s 实时" % source
        await ctx.reply(note)
        await _send_char_panel(ctx, raw, uid, char_name)
        return True

    return False
