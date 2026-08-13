# -*- coding: utf-8 -*-
"""
面板列表图 (miao avatar-list.html) 数据构造

将 Enka 原始 JSON 转成 miao avatar-list.html 模板期望的 renderData:
{
  face: {name, level, banner, face, qFace},
  info: {activeDay, stats, statMap},
  uid,
  updateTime: {profile: 'YYYY-MM-DD HH:MM:SS'},
  avatars: [{name, abbr, elem, star, level, cons, face, gacha, talent, weapon, artisSet}],
  ...
}

Enka 字段真实结构 (2025-2026 网络返回, 与 miao mihoyo API 不同):
- skillLevelMap: {"10301": 10, "10302": 10, "10303": 10} -- 数字 ID 映射 a/e/q 等级
- talentIdList: None -- Enka Network 当前版本不返回 (云崽用的是米游社 cookie)
- fightPropMap["1002"]: 突破等级 (不是命座数)
- equipList[i].reliquary.setId: None -- Enka Network 不返回 (云崽用米游社), 需要从 itemId 前 3 位反查
"""

import os
import time

from . import maps as M


def _wtype_for_weapon(name):
    """从 meta-gs/weapon/<type>/<name> 反查武器类型."""
    base = os.path.join(M.MIAO_RES, "meta-gs", "weapon")
    if not os.path.isdir(base):
        return "sword"
    for wtype in sorted(os.listdir(base)):
        if os.path.isdir(os.path.join(base, wtype, name)):
            return wtype
    return "sword"


# Enka skillLevelMap 数字 ID -> a/e/q 反查 (按 miao getTalent 兜底分支: 无 talentId 时按出现顺序分配)
# 实际 miao 通过 char.meta.talentId 反查, 这里按数量简化: 收集到 3 个就停
_TALENT_KEYS = ["a", "e", "q"]


def _talent_levels(skill_level_map):
    """从 Enka skillLevelMap 解析 a/e/q 等级.

    实际 miao 通过 char.meta.talentId 反查 ID -> a/e/q; Enka 字段无 talentId 直接用顺序分配.
    """
    ta = te = tq = 1
    aeq_idx = 0
    for k, v in (skill_level_map or {}).items():
        try:
            lvl = int(v or 1)
        except (TypeError, ValueError):
            continue
        if aeq_idx == 0:
            ta = lvl
        elif aeq_idx == 1:
            te = lvl
        elif aeq_idx == 2:
            tq = lvl
        else:
            break
        aeq_idx += 1
    return ta, te, tq


def _cons_from_enka(av):
    """从 Enka 字段推断命座数.

    Enka Network 当前不返回 talentIdList/fetterIdCons. 兜底策略:
    1. 直接读 talentIdList (旧版 Enka 或某些代理可能返回)
    2. 计数解锁的命座 propMap ("1002"-"1007", 命座解锁时为 true/1). 注意 1002 也可能用于 promoteLevel.
    3. 默认 0.
    """
    # 路径 1: 直接 talentIdList 长度
    tid_list = av.get("talentIdList") or []
    if isinstance(tid_list, list) and tid_list:
        return len(tid_list)
    # 路径 2: propMap 命之座解锁 (每个命座 propMap 对应一个名字)
    pm = av.get("propMap", {}) or {}
    unlocked = 0
    for k in ("1002", "1003", "1004", "1005", "1006"):
        v = pm.get(k)
        if isinstance(v, dict):
            try:
                val = int(v.get("val", 0) or 0)
            except (TypeError, ValueError):
                continue
            if val >= 1:
                unlocked += 1
    return unlocked


def _artifact_set_name(equip):
    """从圣遗物 equip 提取套装名. Enka reliquary.setId 可能 None, 兜底用 itemId 前 3 位.

    返回套装中文名, 失败返空串.
    """
    rel = equip.get("reliquary") or {}
    set_id = rel.get("setId")
    if set_id:
        sname = M._set_name(set_id)
        if sname:
            return sname
    # Enka 返回 setId=None 时, 用 itemId 前 3 位反查套装组
    item_id = str(equip.get("itemId") or "")
    if len(item_id) >= 3:
        sname = M.set_name_from_item_id(item_id)
        if sname:
            return sname
    return ""


def _artifact_icons(equips):
    """从 5 件圣遗物提取**激活的套装**图标列表 (miao artisSet.imgs 语义).

    imgs 数组长度 = 玩家激活的套装数 (通常 1-2 个, 每 2/4 件套 = 一个图标),
    不是 5 个位置图标. avatar-card.html:50 `{{each avatar.artisSet?.imgs img}}` 直接渲染.
    """
    icon_urls = []
    seen = set()
    for e in (equips or []):
        if not (e.get("reliquary") or {}):
            continue
        sname = _artifact_set_name(e)
        if not sname or sname in seen or sname not in M.SET_DIRS:
            continue
        seen.add(sname)
        icon = M.artifact_icon_rel(sname, 0)
        if icon:
            icon_urls.append(icon)
    return icon_urls


def _artifact_names(equips):
    """激活的套装名数组 (去重, 顺序按出现先后)."""
    names = []
    seen = set()
    for e in (equips or []):
        if not (e.get("reliquary") or {}):
            continue
        sname = _artifact_set_name(e)
        if sname and sname not in seen:
            seen.add(sname)
            names.append(sname)
    return names


def _build_one_avatar(aid, av, equips):
    """构造单个 avatar 字典给 miao avatar-card.html."""
    name = M.AVATAR_ID2NAME.get(str(aid), "")
    if not name:
        return None
    star = M.char_star(name)
    elem_zh = M.char_elem_name(name) or "火"

    cons = _cons_from_enka(av)
    level = int((av.get("propMap", {}) or {}).get("4001", {}).get("val", 0) or 0)

    ta, te, tq = _talent_levels(av.get("skillLevelMap"))

    # 武器: 从 equips 找 weapon 类型, 跳过圣遗物 (reliquary)
    weapon_eq = None
    for e in (equips or []):
        if e.get("weapon"):
            weapon_eq = e
            break
    if weapon_eq:
        wid = weapon_eq.get("weapon", {}) or {}
        wid_item_id = str(weapon_eq.get("itemId"))
        wname = M.WEAPON_ID2NAME.get(wid_item_id, "")
        wstar = 5
        wimg = ""
        if wname:
            wmeta = M.weapon_meta(wname) or {}
            try:
                wstar = int(wmeta.get("star") or 5)
            except (TypeError, ValueError):
                wstar = 5
            wimg = M.weapon_icon_rel(wname)
        aff = (wid.get("affixMap") or {})
        refine = (max(int(x) for x in aff.values()) + 1) if aff else 1
        weapon_obj = {"star": wstar, "img": wimg, "affix": refine, "name": wname, "level": wid.get("level", 0) or 0}
    else:
        weapon_obj = {"star": 5, "img": "", "affix": 1, "name": "", "level": 0}

    return {
        "name": name,
        "abbr": M.char_abbr(name),
        "elem": elem_zh,
        "star": star,
        "level": level,
        "cons": cons,
        "is_popularity": False,
        "face": M.char_face_rel(name),
        "gacha": M.char_gacha_rel(name),
        "qFace": M.char_qface_rel(name),
        "talent": {
            "a": {"level": ta, "original": ta},
            "e": {"level": te, "original": te},
            "q": {"level": tq, "original": tq},
        },
        "weapon": weapon_obj,
        "artisSet": {"imgs": _artifact_icons(equips), "names": _artifact_names(equips)},
    }


def build_avatar_list_data(raw, uid, face_name=None):
    """构造 miao avatar-list.html 模板的完整 renderData."""
    if not isinstance(raw, dict):
        return {"error": "数据格式异常"}
    player = raw.get("playerInfo", {}) or {}
    avatars_raw = raw.get("avatarInfoList", []) or []
    level = int(player.get("level", 0) or 0)

    face_name = face_name or (M.AVATAR_ID2NAME.get(str(avatars_raw[0].get("avatarId")), "") if avatars_raw else "")
    face_obj = {
        "name": player.get("nickname", "") or ("UID %s" % uid),
        "level": level,
        "banner": M.char_banner_rel(face_name),
        "face": M.char_face_rel(face_name),
        "qFace": M.char_qface_rel(face_name),
    }

    info = {
        "activeDay": player.get("onlineDays") or player.get("activeDay") or 0,
        "stats": {
            "achievement": int(player.get("finishAchievementNum", 0) or 0),
            "avatar": len(avatars_raw),
            "avatar5": sum(1 for a in avatars_raw if M.char_star(M.AVATAR_ID2NAME.get(str(a.get("avatarId")), "")) == 5),
        },
        "statMap": {
            "achievement": "成就",
            "avatar": "角色",
            "avatar5": "五星角色",
        },
    }

    avatars_out = []
    for a in avatars_raw:
        aid = a.get("avatarId")
        equips = a.get("equipList", []) or []
        one = _build_one_avatar(aid, a, equips)
        if one:
            avatars_out.append(one)

    update_time = time.strftime("%Y-%m-%d %H:%M:%S")

    return {
        "template": "character/avatar-list",
        "_tpl_file": "avatar-list.html",
        "save_id": uid,
        "uid": uid,
        "game": "gs",
        "mode": "avatar",
        "element": "hydro",
        "elem": "hydro",
        "face": face_obj,
        "info": info,
        "avatars": avatars_out,
        "updateTime": {"profile": update_time},
    }
