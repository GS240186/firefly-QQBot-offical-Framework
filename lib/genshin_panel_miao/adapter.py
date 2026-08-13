# -*- coding: utf-8 -*-
"""
Enka raw -> miao-plugin profile-detail 模板 renderData 映射 (v6)

字段规范完全对齐 miao-plugin/resources/character/profile-detail.html 的用法:
  data.name/abbr/cons/level/talent/imgs/costumeSplash/dataSource/updateTime/weapon
  attr.{hp,atk,def,mastery,cpct,cdmg,recharge,dmg} + Base + Plus  (Plus 无 + 号, 模板自带 +)
  artisDetail.{charWeight, allAttr, mark, markClass, msg, classTitle, artis}
  artisKeyTitle: 对象 {atk:'大攻击', hp:'大生命', ...}  (不是数组!)
  dmgCalc.{dmgData, enemyLv, enemyName, createdBy}
"""

import os
import sys
import json
import re
import math
from typing import Optional, List, Dict, Any

from . import maps as M


# ============================================================================
# 数值格式化 (对齐 miao Format.js: comma / pct)
# ============================================================================

def _comma(v, n=0):
    """Format.comma: 千分位. hp n=0, 其它 n=1."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "0"
    if n <= 0:
        return "{:,.0f}".format(round(f))
    return "{:,.1f}".format(f)


def _pct(v, mul=100.0):
    """Format.pct: 0.701 -> '70.1%'"""
    try:
        f = float(v) * mul
    except (TypeError, ValueError):
        return "0.0%"
    return "{:.1f}%".format(f)


def _pct1(v, mul=100.0):
    """不带 % 的百分数 (用于 Plus 计算后统一加 %)."""
    try:
        return float(v) * mul
    except (TypeError, ValueError):
        return 0.0


# ============================================================================
# 伤害计算 (Python 侧简化版, 对齐 miao calc.js 输出格式)
# ============================================================================

# 记录本次 Node 计算实际返回的伤害规则创建者 (calc_auto.js → "组团伤害", calc.js → "喵喵")
_LAST_DMG_CREATEDBY = ["喵喵"]

# 芙宁娜 专属伤害行 (HP 倍率) — 数值对齐用户示例图
_DMG_ROWS = {
    "芙宁娜": [
        {"label": "E众水歌唱治疗", "scale": "hp", "mult": 0.193, "heal": True},
        {"label": "E海微玛夫人[海马]·伤害", "scale": "hp", "mult": 0.097},
        {"label": "E乌瑟勋爵[章鱼]·伤害", "scale": "hp", "mult": 0.179},
        {"label": "E谢贝蕾妲小姐[螃蟹]·伤害", "scale": "hp", "mult": 0.249},
        {"label": "E谢贝蕾妲小姐[螃蟹]·蒸发", "scale": "hp", "mult": 0.249, "vape": True},
        {"label": "Q万众狂欢·治疗", "scale": "hp", "mult": 0.855, "heal": True},
        {"label": "Q万众狂欢伤害·蒸发", "scale": "hp", "mult": 0.169, "vape": True},
    ],
    "哥伦比娅": [
        {"label": "满buff 特殊重击「月震涨落」三段伤害", "scale": "atk", "mult": 1.50},
        {"label": "E技能伤害", "scale": "atk", "mult": 2.65},
        {"label": "满buff 引力波浪·持续伤害", "scale": "atk", "mult": 4.31},
        {"label": "满buff 引力干涉·月曜电击伤害", "scale": "atk", "mult": 4.31},
        {"label": "满buff 引力干涉·月曜陨石伤害", "scale": "atk", "mult": 4.31},
        {"label": "满buff 引力干涉·月曜爆炸伤害", "scale": "atk", "mult": 4.31},
    ],
}

_GENERIC_DMG = [
    {"label": "普攻", "scale": "atk", "mult": 0.75},
    {"label": "重击", "scale": "atk", "mult": 1.50},
    {"label": "元素战技", "scale": "atk", "mult": 2.80},
    {"label": "元素爆发", "scale": "atk", "mult": 4.50},
]


def _build_dmg_data(cn_name: str, fpm: dict, talent: dict = None, weapon: dict = None,
                    sets: dict = None, elem: str = "", level: int = 90) -> List[dict]:
    """调用 Node miao 伤害计算器 (完整复刻 miao DmgCalc 引擎).
    fpm: fightPropMap; talent: {a,e,q} 等级; weapon: {name,affix,type}; sets: {套装名: 件数}."""
    try:
        import subprocess
        import tempfile
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        script = os.path.join(base_dir, "miao_panel", "dmg_calc.mjs")
        node = r"C:\Users\123\.workbuddy\binaries\node\versions\22.22.2\node.exe"
        if not os.path.isfile(node):
            node = "node"
        yz_dir = r"C:\Users\123\Desktop\Yunzai"
        # 同步脚本到 Yunzai 目录 (import miao 模块需要其 node_modules)
        import shutil
        try:
            shutil.copyfile(script, os.path.join(yz_dir, "dmg_calc.mjs"))
        except OSError:
            pass
        hp = float(fpm.get("2000") or 0)
        atk = float(fpm.get("2001") or 0)
        dmg_bonus = 0.0
        # Enka fightPropMap 元素伤害 prop: 24-30 (旧) + 40-46 (新: 火水雷草风冰岩) + 29 (物理)
        for k in list(range(24, 31)) + list(range(40, 47)) + [29]:
            if k == 28:
                continue
            dmg_bonus = max(dmg_bonus, float(fpm.get(str(k)) or 0))
        inp = {
            "charName": cn_name,
            "level": int(level or 90),
            "cons": 0,
            "elem": elem or "hydro",
            "enemyLv": 103,
            "talent": {k: int(v) for k, v in (talent or {}).items() if k in ("a", "e", "q")} or {"a": 10, "e": 10, "q": 10},
            "attrs": {
                "hp": hp, "hpBase": float(fpm.get("_hp_base") or 0),
                "atk": atk, "atkBase": float(fpm.get("_atk_base") or 0),
                "def": float(fpm.get("2002") or 0), "defBase": float(fpm.get("_def_base") or 0),
                "mastery": float(fpm.get("28") or 0),
                "cpct": float(fpm.get("20") or 0) * 100,
                "cdmg": float(fpm.get("22") or 0) * 100,
                "recharge": float(fpm.get("23") or 0) * 100,
                "dmg": dmg_bonus * 100,
            },
            "weapon": weapon or {},
            "sets": sets or {},
        }
        fd, in_path = tempfile.mkstemp(suffix=".json", prefix="dmg_in_")
        out_path = os.path.join(tempfile.gettempdir(), "dmg_out_%d.json" % os.getpid())
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(inp, f, ensure_ascii=False)
        proc = subprocess.run([node, "dmg_calc.mjs", in_path, out_path],
                              cwd=yz_dir, capture_output=True, text=True, encoding="utf-8", timeout=60)
        try:
            os.unlink(in_path)
        except OSError:
            pass
        if proc.returncode != 0:
            print("[dmg_calc] FAIL rc=%s stderr=%s" % (proc.returncode, proc.stderr[-800:] or ""), file=__import__('sys').stderr, flush=True)
            return []
        if not proc.stderr:
            pass  # OK
        elif "DMG_OK" not in (proc.stdout or ""):
            print("[dmg_calc] WARN stderr=%s stdout=%s" % (proc.stderr[-500:], (proc.stdout or "")[-500:]), file=__import__('sys').stderr, flush=True)
        with open(out_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        try:
            os.unlink(out_path)
        except OSError:
            pass
        _LAST_DMG_CREATEDBY[0] = str(data.get("createdBy") or "喵喵")[:15]
        rows = []
        for r in data.get("ret", []):
            dmg = r.get("dmg")
            avg = r.get("avg")
            # dmg_calc.mjs 中 dmgRet.dmg=NaN 序列化为 null, 转成 "NaN" 字符串
            if dmg is None or dmg == "NaN":
                dmg_disp = "NaN"
            else:
                try:
                    dmg_disp = _comma(int(float(dmg)), 0)
                except (TypeError, ValueError):
                    dmg_disp = "NaN"
            try:
                avg_disp = _comma(int(float(avg)), 0) if avg else "—"
            except (TypeError, ValueError):
                avg_disp = "—"
            rows.append({
                "title": r.get("title", ""),
                "dmg": dmg_disp,
                "avg": avg_disp,
                "unit": "",
            })
        return rows
    except Exception as e:
        print("[dmg_calc] EXC:", repr(e), file=__import__('sys').stderr)
        return []


# ============================================================================
# 圣遗物主/副词条 -> miao 词条 key
# ============================================================================

def _arti_prop_key(prop_id: str) -> str:
    return M.ENKA_ARTI_PROP2KEY.get(prop_id, "")


def _fmt_arti_value(key: str, raw_value) -> str:
    """Enka 副词条 statValue: 实际是百分比数值形式 (8.82 = 8.82%), 不再 * 100.
    数值词条 (atkPlus 等) 直接 _comma."""
    try:
        f = float(raw_value)
    except (TypeError, ValueError):
        return "0"
    if key in M.PCT_KEYS:
        return "{:.1f}%".format(f)
    return _comma(f, 1)


# ============================================================================
# 主入口
# ============================================================================

def build_render_data(raw: dict, uid: str, detail: str) -> Optional[dict]:
    """Enka raw -> miao renderData dict. 找不到角色返回 None."""
    if not isinstance(raw, dict) or "playerInfo" not in raw:
        return None
    target = _find_avatar(raw, detail)
    if target is None:
        return None

    aid = str(target.get("avatarId"))
    cn_name = M.AVATAR_ID2NAME.get(aid, "")
    if not cn_name:
        return None

    meta = M.char_meta(cn_name) or {}
    elem = meta.get("elem", "") or ""
    base_attr = meta.get("baseAttr", {}) or {}

    level = ((target.get("propMap") or {}).get("4001") or {}).get("val", 0) or 90
    cons = len(target.get("talentIdList") or []) or 0
    friendship = (target.get("fetterInfo") or {}).get("expLevel", 0) or 10
    fpm = target.get("fightPropMap", {}) or {}

    equips_raw = target.get("equipList", []) or []
    # 按 miao Avatar.setArtisData 区分: 武器有 weapon 字段, 圣遗物有 reliquary 字段
    weapon_raw = None
    artifacts_raw = []
    for eq in equips_raw:
        if "weapon" in eq:
            weapon_raw = eq
        elif "reliquary" in eq:
            artifacts_raw.append(eq)
    # 诊断日志 (Enka 拉取情况: 玩家公开范围/限频会导致圣遗物缺失)
    print(f"[genshin_panel] {cn_name} uid={uid} equipList={len(equips_raw)} 武器={'有' if weapon_raw else '无'} 圣遗物={len(artifacts_raw)}", file=sys.stderr, flush=True)
    weapon = _build_weapon(weapon_raw) if weapon_raw else None
    artifacts = _build_artifacts(artifacts_raw)

    # 8 项面板属性
    attr = _build_attr(fpm, base_attr)

    # 圣遗物评分
    artis_detail = _build_artis_detail(artifacts, weapon, cn_name, cons, elem)

    # 0 圣遗物时显示友好提示 (Enka 未拉到/玩家未公开)
    if not artifacts:
        artis_detail["mark"] = "—"
        artis_detail["markClass"] = ""
        artis_detail["classTitle"] = "暂无圣遗物数据"
        artis_detail["msg"] = "Enka 未拉到圣遗物 (玩家公开范围受限或 API 限频)"

    # 伤害表 (Node miao 引擎: 完整复刻 calc.js + DmgCalc)
    fpm_dmg = dict(fpm)
    fpm_dmg["_hp_base"] = base_attr.get("hp", 0)
    fpm_dmg["_atk_base"] = base_attr.get("atk", 0)
    fpm_dmg["_def_base"] = base_attr.get("def", 0)
    talent_lv = {}
    tmap = {str(sk): k for k, sk in (meta.get("talentId") or {}).items()}
    skm = target.get("skillLevelMap", {}) or {}
    for sk, lv in skm.items():
        key = tmap.get(str(sk))
        if key in ("a", "e", "q"):
            talent_lv[key] = int(lv)
    if not talent_lv:
        talent_lv = {"a": 10, "e": 10, "q": 10}
    # 武器精炼 + 类型 (node 计算用)
    w_node = None
    if weapon:
        w_node = {"name": weapon.get("name", ""), "affix": weapon.get("affix", 1),
                  "type": weapon.get("type") or "sword"}
    # 圣遗物套装统计 (node 计算用)
    set_counts = {}
    for a in artifacts:
        sname = a.get("set_name") or ""
        if sname:
            set_counts[sname] = set_counts.get(sname, 0) + 1
    sets_node = {s: (4 if c >= 4 else (2 if c >= 2 else 0)) for s, c in set_counts.items() if c >= 2}
    dmg_data = _build_dmg_data(cn_name, fpm_dmg, talent_lv, w_node, sets_node, elem, level)

    # 角色 data
    data = {
        "name": cn_name,
        "abbr": meta.get("abbr") or cn_name,
        "cons": cons,
        "level": level,
        "talent": _build_talent(target, cn_name),
        "dataSource": "Enka Network",
        "updateTime": "",
        "weapon": weapon or {},
        "imgs": _build_imgs(cn_name, weapon),
        "costumeSplash": M.char_splash_rel(cn_name),
    }

    # 排名统计已移除 (用户要求删除)

    return {
        "uid": uid,
        "save_id": uid,
        "game": "gs",
        "mode": "profile",
        "bodyClass": "char-%s" % cn_name,
        "elem": elem,
        "element": elem,
        "data": data,
        "attr": attr,
        "artisDetail": artis_detail,
        "artisKeyTitle": dict(M.ARTI_KEY_TITLE),
        "dmgCalc": {
            "dmgData": dmg_data,
            "enemyLv": 103,
            "enemyName": "小宝",
            "createdBy": _LAST_DMG_CREATEDBY[0],
        },
        "weapon": weapon or None,
        # 切到项目自有模板 (绝对路径让 render.mjs 直接读取)
        "_tpl_file": os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "profile-detail.html"),
        # 兼容: 供外部拿角色名
        "char_name": cn_name,
    }


# miao usefulAttr 完整表 (resources/meta-gs/artifact/artis-mark.js)
# 键为大词条 (hp/atk/def/cpct/cdmg/mastery/dmg/phy/recharge/heal)
USEFUL_ATTR = {
    "芭芭拉": {"hp": 100, "atk": 50, "cpct": 50, "cdmg": 50, "dmg": 80, "recharge": 55, "heal": 100},
    "甘雨": {"atk": 75, "cpct": 100, "cdmg": 100, "mastery": 75, "dmg": 100},
    "雷电将军": {"atk": 75, "cpct": 100, "cdmg": 100, "mastery": 0, "dmg": 75, "recharge": 90},
    "神里绫人": {"hp": 50, "atk": 75, "cpct": 100, "cdmg": 100, "dmg": 100, "recharge": 30},
    "八重神子": {"atk": 75, "cpct": 100, "cdmg": 100, "mastery": 75, "dmg": 75, "recharge": 55},
    "申鹤": {"atk": 100, "cpct": 50, "cdmg": 50, "dmg": 80, "recharge": 100},
    "云堇": {"atk": 75, "def": 100, "cpct": 80, "cdmg": 80, "dmg": 80, "recharge": 80},
    "荒泷一斗": {"atk": 50, "def": 100, "cpct": 100, "cdmg": 100, "dmg": 100, "recharge": 30},
    "五郎": {"def": 50, "cpct": 50, "cdmg": 50, "dmg": 30, "recharge": 100},
    "班尼特": {"hp": 100, "atk": 50, "cpct": 50, "cdmg": 50, "dmg": 80, "recharge": 100, "heal": 100},
    "枫原万叶": {"mastery": 100, "dmg": 80, "recharge": 75},
    "行秋": {"atk": 75, "cpct": 100, "cdmg": 100, "dmg": 100, "recharge": 75},
    "钟离": {"hp": 100, "atk": 30, "cpct": 40, "cdmg": 40, "dmg": 80, "recharge": 55},
    "神里绫华": {"atk": 85, "cpct": 100, "cdmg": 100, "dmg": 100, "recharge": 45},
    "香菱": {"atk": 75, "cpct": 100, "cdmg": 100, "mastery": 75, "dmg": 100, "recharge": 75},
    "胡桃": {"hp": 80, "atk": 50, "cpct": 100, "cdmg": 100, "mastery": 75, "dmg": 100},
    "温迪": {"atk": 100, "cpct": 100, "cdmg": 100, "dmg": 100, "recharge": 45},
    "珊瑚宫心海": {"hp": 100, "atk": 50, "cpct": 0, "cdmg": 0, "mastery": 75, "dmg": 100, "recharge": 55, "heal": 100},
    "莫娜": {"atk": 75, "cpct": 100, "cdmg": 100, "mastery": 75, "dmg": 100, "recharge": 75},
    "阿贝多": {"def": 75, "cpct": 100, "cdmg": 100, "dmg": 100},
    "迪奥娜": {"hp": 100, "atk": 50, "cpct": 50, "cdmg": 50, "dmg": 80, "recharge": 90, "heal": 100},
    "优菈": {"atk": 75, "cpct": 100, "cdmg": 100, "dmg": 40, "phy": 100, "recharge": 55},
    "达达利亚": {"atk": 75, "cpct": 100, "cdmg": 100, "mastery": 75, "dmg": 100, "recharge": 30},
    "魈": {"atk": 75, "cpct": 100, "cdmg": 100, "dmg": 100, "recharge": 55},
    "宵宫": {"atk": 75, "cpct": 100, "cdmg": 100, "mastery": 75, "dmg": 100},
    "九条裟罗": {"atk": 75, "cpct": 100, "cdmg": 100, "dmg": 100, "recharge": 100},
    "琴": {"atk": 100, "dmg": 80, "phy": 80, "recharge": 75, "heal": 100},
    "菲谢尔": {"atk": 75, "cpct": 100, "cdmg": 100, "mastery": 75, "dmg": 100, "phy": 60},
    "罗莎莉亚": {"atk": 75, "cpct": 100, "cdmg": 100, "dmg": 70, "phy": 80, "recharge": 30},
    "可莉": {"atk": 75, "cpct": 100, "cdmg": 100, "mastery": 75, "dmg": 100, "recharge": 30},
    "凝光": {"atk": 75, "cpct": 100, "cdmg": 100, "dmg": 100, "recharge": 30},
    "北斗": {"atk": 75, "cpct": 100, "cdmg": 100, "mastery": 45, "dmg": 100, "recharge": 100},
    "刻晴": {"atk": 75, "cpct": 100, "cdmg": 100, "mastery": 75, "dmg": 100, "phy": 100},
    "托马": {"hp": 100, "atk": 50, "cpct": 50, "cdmg": 50, "mastery": 75, "dmg": 80, "recharge": 75},
    "迪卢克": {"atk": 75, "cpct": 100, "cdmg": 100, "mastery": 75, "dmg": 100},
    "诺艾尔": {"atk": 50, "def": 90, "cpct": 100, "cdmg": 100, "dmg": 100, "recharge": 70},
    "旅行者": {"atk": 75, "cpct": 100, "cdmg": 100, "dmg": 100, "recharge": 55},
    "重云": {"atk": 75, "cpct": 100, "cdmg": 100, "mastery": 75, "dmg": 100, "recharge": 55},
    "七七": {"atk": 100, "cpct": 100, "cdmg": 100, "dmg": 95, "phy": 99, "recharge": 75, "heal": 100},
    "凯亚": {"atk": 75, "cpct": 100, "cdmg": 100, "dmg": 100, "phy": 100, "recharge": 30},
    "烟绯": {"atk": 75, "cpct": 100, "cdmg": 100, "mastery": 75, "dmg": 100, "recharge": 30},
    "早柚": {"atk": 75, "cpct": 50, "cdmg": 50, "mastery": 100, "dmg": 100, "recharge": 55, "heal": 100},
    "安柏": {"atk": 75, "cpct": 100, "cdmg": 100, "mastery": 75, "dmg": 100, "phy": 100},
    "丽莎": {"atk": 75, "cpct": 100, "cdmg": 100, "mastery": 30, "dmg": 100, "recharge": 75},
    "埃洛伊": {"atk": 75, "cpct": 100, "cdmg": 100, "dmg": 100},
    "辛焱": {"atk": 75, "def": 75, "cpct": 100, "cdmg": 100, "dmg": 100, "phy": 100},
    "砂糖": {"atk": 50, "cpct": 50, "cdmg": 50, "mastery": 100, "dmg": 80, "recharge": 75},
    "雷泽": {"atk": 75, "cpct": 100, "cdmg": 100, "dmg": 100, "phy": 100},
    "夜兰": {"hp": 80, "cpct": 100, "cdmg": 100, "dmg": 100, "recharge": 55},
    "久岐忍": {"hp": 100, "atk": 50, "cpct": 50, "cdmg": 50, "mastery": 100, "dmg": 100, "recharge": 55, "heal": 100},
    "鹿野院平藏": {"atk": 75, "cpct": 100, "cdmg": 100, "mastery": 30, "dmg": 100, "recharge": 30},
    "提纳里": {"atk": 75, "cpct": 100, "cdmg": 100, "mastery": 90, "dmg": 100, "recharge": 30},
    "柯莱": {"atk": 75, "cpct": 100, "cdmg": 100, "mastery": 75, "dmg": 100, "recharge": 75},
    "赛诺": {"atk": 75, "cpct": 100, "cdmg": 100, "mastery": 75, "dmg": 100, "recharge": 55},
    "坎蒂丝": {"hp": 100, "atk": 50, "cpct": 100, "cdmg": 100, "dmg": 95, "recharge": 75},
    "妮露": {"hp": 100, "cpct": 30, "cdmg": 30, "mastery": 80, "dmg": 80, "recharge": 30},
    "纳西妲": {"atk": 55, "cpct": 100, "cdmg": 100, "mastery": 100, "dmg": 100, "recharge": 55},
    "多莉": {"hp": 100, "atk": 50, "cpct": 50, "cdmg": 50, "dmg": 80, "recharge": 75, "heal": 100},
    "莱依拉": {"hp": 100, "cpct": 50, "cdmg": 50, "dmg": 80, "recharge": 35},
    "流浪者": {"atk": 80, "cpct": 100, "cdmg": 100, "dmg": 100, "recharge": 35},
    "珐露珊": {"atk": 75, "cpct": 100, "cdmg": 100, "dmg": 100, "recharge": 100},
    "瑶瑶": {"hp": 100, "atk": 75, "cpct": 30, "cdmg": 30, "mastery": 75, "dmg": 100, "recharge": 75, "heal": 100},
    "艾尔海森": {"atk": 55, "cpct": 100, "cdmg": 100, "mastery": 100, "dmg": 100, "recharge": 35},
    "迪希雅": {"hp": 75, "atk": 75, "cpct": 100, "cdmg": 100, "mastery": 100, "dmg": 100, "recharge": 55},
    "米卡": {"hp": 75, "atk": 55, "cpct": 50, "cdmg": 50, "dmg": 75, "phy": 75, "recharge": 55, "heal": 100},
    "白术": {"hp": 100, "cpct": 30, "cdmg": 30, "mastery": 50, "dmg": 80, "recharge": 100, "heal": 100},
    "卡维": {"atk": 75, "cpct": 100, "cdmg": 100, "mastery": 75, "dmg": 100, "recharge": 75},
    "绮良良": {"hp": 100, "atk": 50, "cpct": 50, "cdmg": 50, "dmg": 80, "recharge": 30},
    "林尼": {"atk": 75, "cpct": 100, "cdmg": 100, "dmg": 100, "recharge": 30},
    "琳妮特": {"atk": 75, "cpct": 100, "cdmg": 100, "dmg": 100, "recharge": 75},
    "菲米尼": {"atk": 75, "cpct": 100, "cdmg": 100, "dmg": 100, "phy": 100, "recharge": 55},
    "那维莱特": {"hp": 100, "cpct": 100, "cdmg": 100, "dmg": 100, "recharge": 55},
    "莱欧斯利": {"atk": 75, "cpct": 100, "cdmg": 100, "mastery": 75, "dmg": 100, "recharge": 45},
    "芙宁娜": {"hp": 100, "atk": 0, "def": 0, "cpct": 100, "cdmg": 100, "mastery": 0, "dmg": 95, "phy": 0, "recharge": 75, "heal": 95},
    "夏洛蒂": {"atk": 85, "cpct": 50, "cdmg": 50, "dmg": 80, "recharge": 100, "heal": 100},
    "娜维娅": {"atk": 75, "cpct": 100, "cdmg": 100, "dmg": 100, "recharge": 55},
    "夏沃蕾": {"hp": 100, "cpct": 50, "cdmg": 50, "dmg": 80, "recharge": 55, "heal": 55},
    "闲云": {"atk": 100, "cpct": 50, "cdmg": 50, "dmg": 80, "recharge": 100, "heal": 75},
    "嘉明": {"atk": 75, "cpct": 100, "cdmg": 100, "mastery": 75, "dmg": 100, "recharge": 55},
    "千织": {"atk": 50, "def": 75, "cpct": 100, "cdmg": 100, "dmg": 100, "recharge": 55},
    "阿蕾奇诺": {"atk": 75, "cpct": 100, "cdmg": 100, "mastery": 75, "dmg": 100, "recharge": 30},
    "赛索斯": {"atk": 30, "cpct": 100, "cdmg": 100, "mastery": 100, "dmg": 100, "recharge": 55},
    "克洛琳德": {"atk": 100, "cpct": 100, "cdmg": 100, "mastery": 30, "dmg": 100, "recharge": 35},
    "希格雯": {"hp": 100, "cpct": 100, "cdmg": 100, "dmg": 95, "recharge": 30, "heal": 100},
    "艾梅莉埃": {"atk": 100, "cpct": 100, "cdmg": 100, "mastery": 30, "dmg": 100, "recharge": 55},
    "卡齐娜": {"def": 75, "cpct": 100, "cdmg": 100, "dmg": 100, "recharge": 75},
    "玛拉妮": {"hp": 100, "cpct": 100, "cdmg": 100, "mastery": 100, "dmg": 100, "recharge": 45},
    "基尼奇": {"atk": 85, "cpct": 100, "cdmg": 100, "dmg": 100, "recharge": 50},
    "希诺宁": {"def": 100, "cpct": 30, "cdmg": 30, "dmg": 80, "recharge": 100, "heal": 100},
    "恰斯卡": {"atk": 85, "cpct": 100, "cdmg": 100, "mastery": 30, "dmg": 85, "recharge": 40},
    "欧洛伦": {"atk": 75, "cpct": 100, "cdmg": 100, "mastery": 50, "dmg": 100, "recharge": 75},
    "玛薇卡": {"atk": 75, "cpct": 100, "cdmg": 100, "mastery": 85, "dmg": 100},
    "茜特菈莉": {"atk": 50, "cpct": 50, "cdmg": 50, "mastery": 100, "dmg": 80, "recharge": 100},
    "蓝砚": {"atk": 100, "cpct": 50, "cdmg": 50, "mastery": 30, "dmg": 80, "recharge": 75},
    "梦见月瑞希": {"mastery": 100, "dmg": 80, "recharge": 45, "heal": 95},
    "伊安珊": {"atk": 100, "cpct": 50, "cdmg": 50, "dmg": 80, "recharge": 100},
    "瓦雷莎": {"atk": 90, "cpct": 100, "cdmg": 100, "dmg": 100, "recharge": 40},
    "爱可菲": {"atk": 100, "cpct": 100, "cdmg": 100, "dmg": 99, "recharge": 75, "heal": 95},
    "伊法": {"atk": 75, "cpct": 50, "cdmg": 50, "mastery": 100, "dmg": 80, "recharge": 35, "heal": 100},
    "丝柯克": {"atk": 100, "cpct": 100, "cdmg": 100, "dmg": 100},
    "塔利雅": {"hp": 100, "atk": 50, "cpct": 50, "cdmg": 50, "dmg": 80, "recharge": 100},
    "伊涅芙": {"atk": 75, "cpct": 100, "cdmg": 100, "mastery": 75, "recharge": 40},
    "菈乌玛": {"atk": 25, "cpct": 50, "cdmg": 50, "mastery": 100, "recharge": 100},
    "爱诺": {"atk": 75, "cpct": 100, "cdmg": 100, "mastery": 75, "dmg": 100, "recharge": 40},
    "菲林斯": {"atk": 100, "cpct": 100, "cdmg": 100, "mastery": 50, "recharge": 50},
    "奈芙尔": {"cpct": 100, "cdmg": 100, "mastery": 100, "recharge": 20},
    "杜林": {"atk": 75, "cpct": 100, "cdmg": 100, "mastery": 75, "dmg": 100, "recharge": 20},
    "雅珂达": {"atk": 100, "cpct": 50, "cdmg": 50, "dmg": 80, "recharge": 100, "heal": 100},
    "哥伦比娅": {"hp": 100, "cpct": 100, "cdmg": 100, "mastery": 75, "recharge": 100},
    "兹白": {"def": 100, "cpct": 100, "cdmg": 100, "mastery": 60, "recharge": 40},
    "叶洛亚": {"def": 50, "cpct": 50, "cdmg": 50, "mastery": 100, "dmg": 80, "recharge": 100},
    "法尔伽": {"atk": 100, "cpct": 100, "cdmg": 100, "dmg": 99, "recharge": 20},
    "莉奈娅": {"def": 100, "cpct": 100, "cdmg": 100, "mastery": 50, "recharge": 50, "heal": 99},
    "尼可": {"atk": 100, "recharge": 50},
    "布伦妮": {"atk": 100, "cpct": 100, "cdmg": 100, "dmg": 99, "recharge": 100},
    "洛恩": {"atk": 100, "cpct": 100, "cdmg": 100, "dmg": 100, "recharge": 30},
    "桑多涅": {"atk": 100, "cpct": 100, "cdmg": 100, "mastery": 75, "recharge": 40},
}


# ============================================================================
# miao ArtisMark 完整算法 (复刻 Yunzai/miao-plugin/models/artis/)
# 词条基础数据 (extra.js: basicNum=3.885, attrPct)
# ============================================================================
ARTI_ATTR_MAP = {
    "atk": {"title": "大攻击", "format": "pct", "value": 5.8275},
    "atkPlus": {"title": "小攻击", "format": "comma", "value": 19.425, "base": "atk"},
    "def": {"title": "大防御", "format": "pct", "value": 7.284375},
    "defPlus": {"title": "小防御", "format": "comma", "value": 23.31, "base": "def"},
    "hp": {"title": "大生命", "format": "pct", "value": 5.8275},
    "hpPlus": {"title": "小生命", "format": "comma", "value": 298.659375, "base": "hp"},
    "cpct": {"title": "暴击率", "format": "pct", "value": 3.885},
    "cdmg": {"title": "暴击伤害", "format": "pct", "value": 7.77},
    "mastery": {"title": "元素精通", "format": "comma", "value": 23.31},
    "recharge": {"title": "充能效率", "format": "pct", "value": 6.475},
    "dmg": {"title": "元素伤害", "format": "pct", "value": 5.8275},
    "phy": {"title": "物伤加成", "format": "pct", "value": 7.284375},
    "heal": {"title": "治疗加成", "format": "pct", "value": 4.482692307692307},
}

# 各位置允许的主词条 (extra.js mainAttr, idx 3=沙 4=杯 5=冠)
MAIN_ATTR_BY_POS = {
    3: ["atk", "def", "hp", "mastery", "recharge"],
    4: ["atk", "def", "hp", "mastery", "dmg", "phy"],
    5: ["atk", "def", "hp", "mastery", "heal", "cpct", "cdmg"],
}
# 副词条池 (extra.js subAttr)
SUB_ATTR_LIST = ["atk", "atkPlus", "def", "defPlus", "hp", "hpPlus", "mastery", "recharge", "cpct", "cdmg"]


def _miao_cfg_attrs(attr_weight: dict, base_attr: dict) -> dict:
    """ArtisMarkCfg.getCfg 的 attrs 表: {key: {weight, fixWeight, mark, value}}."""
    attrs = {}
    for key, cfg in ARTI_ATTR_MAP.items():
        k = cfg.get("base", "")
        weight = attr_weight.get(k or key, 0)
        if not weight:
            continue
        value = cfg["value"]
        if not k:
            mark = weight / value
            fix_weight = weight
        else:
            plus = 520 if k == "atk" else 0
            base = base_attr.get(k, 14000) or 14000
            mark = weight / ARTI_ATTR_MAP[k]["value"] / (base + plus) * 100
            fix_weight = weight * value / ARTI_ATTR_MAP[k]["value"] / (base + plus) * 100
        attrs[key] = {"weight": weight, "fixWeight": fix_weight, "mark": mark, "value": value}
    return attrs


def _miao_get_max_attr(attrs: dict, attr_list, max_len=1, ban_attr=""):
    """按 fixWeight 降序取前 max_len, 排除 ban_attr."""
    tmp = [(a, attrs[a]["fixWeight"]) for a in attr_list
           if a != ban_attr and a in attrs]
    tmp.sort(key=lambda x: -x[1])
    return [a for a, _ in tmp[:max_len]]


def _miao_pos_max_mark(attrs: dict) -> dict:
    """ArtisMark.getMaxMark: posMaxMark {1..5, m1..m5}."""
    ret = {}
    for idx in range(1, 6):
        total_mark = 0
        m_mark = 0
        if idx == 1:
            m_attr = "hpPlus"
        elif idx == 2:
            m_attr = "atkPlus"
        else:
            cands = _miao_get_max_attr(attrs, MAIN_ATTR_BY_POS[idx])
            if cands:
                m_attr = cands[0]
                m_mark = attrs[m_attr]["fixWeight"]
                total_mark += m_mark * 2
            else:
                m_attr = MAIN_ATTR_BY_POS[idx][0]
        s_attrs = _miao_get_max_attr(attrs, SUB_ATTR_LIST, 4, m_attr)
        for a_idx, attr in enumerate(s_attrs):
            total_mark += attrs[attr]["fixWeight"] * (6 if a_idx == 0 else 1)
        ret[idx] = total_mark
        ret["m" + str(idx)] = m_mark
    return ret


# 元素词条 key -> 角色元素匹配 (Format.isElem/sameElem)
_ELEM_KEY_MAP = {
    "hydro": "hydro", "pyro": "pyro", "cryo": "cryo", "electro": "electro",
    "geo": "geo", "anemo": "anemo", "dendro": "dendro",
    "fire": "pyro", "water": "hydro", "ice": "cryo", "elec": "electro",
    "rock": "geo", "wind": "anemo", "grass": "dendro",
}


def _miao_is_elem_key(key: str) -> bool:
    """该 key 是否是元素伤害词条."""
    return key in _ELEM_KEY_MAP


def _miao_same_elem(elem: str, key: str) -> bool:
    """主词条元素与角色元素是否一致."""
    return _ELEM_KEY_MAP.get(key) == elem or key == elem


def _miao_arti_mark(attrs: dict, pos_max_mark: dict, idx: int, main: dict, subs: list, elem: str) -> float:
    """ArtisMark.getMark: 单件圣遗物评分.
    idx = 圣遗物位置 (1=花 2=羽 3=沙 4=杯 5=冠), 只有 idx>=3 主词条计分.
    """
    key = main.get("key") or ""
    if not key:
        return 0.0
    ret = 0.0
    fix_pct = 1.0
    if idx >= 3:
        main_key = key
        if key != "recharge":
            if idx == 4:
                if _miao_same_elem(elem, key):
                    main_key = "dmg"
            m_max = pos_max_mark.get("m" + str(idx), 0)
            fix_pct = min(max((attrs.get(main_key, {}).get("weight", 0) / m_max) if m_max > 0 else 1, 0), 1) if m_max > 0 else 1
            if main_key in ("atk", "hp", "def") and attrs.get(main_key, {}).get("weight", 0) >= 75:
                fix_pct = 1
        try:
            m_val = float(str(main.get("value") or 0).replace("%", "").replace(",", ""))
        except (TypeError, ValueError):
            m_val = 0.0
        ret += attrs.get(main_key, {}).get("mark", 0) * m_val / 4
    for s in subs:
        sk = s.get("key") or ""
        if not sk:
            continue
        try:
            sv = float(str(s.get("value") or 0).replace("%", "").replace(",", ""))
        except (TypeError, ValueError):
            sv = 0.0
        ret += attrs.get(sk, {}).get("mark", 0) * sv
    p_max = pos_max_mark.get(idx, 0)
    return ret * (1 + fix_pct) / 2 / p_max * 66 if p_max > 0 else 0


def _miao_mark_class(mark) -> str:
    """ArtisMark.getMarkClass 评级档位."""
    for thresh, cls in [(7, "D"), (14, "C"), (21, "B"), (28, "A"), (35, "S"),
                        (42, "SS"), (49, "SSS"), (56, "ACE"), (70, "MAX")]:
        if mark < thresh:
            return cls
    return "MAX"


def _miao_get_attr_weight(cn_name: str, cons: int = 0, weapon_name: str = "") -> dict:
    """角色评分权重 (CharCfg.getArtisCfg + usefulAttr).
    cons>=4 芙宁娜特判 (artis.js 自定义规则)."""
    base = dict(USEFUL_ATTR.get(cn_name, USEFUL_ATTR.get("旅行者", {})))
    # 芙宁娜高命特判 (artis.js): cons>=4 recharge=60, cons==6 mastery=45
    if cn_name == "芙宁娜" and cons >= 4:
        base = dict(base)
        base["recharge"] = 60
        if cons == 6:
            base["mastery"] = 45
    return base


def _arti_sub_max(k):
    v = ARTI_ATTR_VALUE.get(k, 0)
    return v * 4 if v > 0 else 0

def _find_avatar(raw, detail):
    for av in raw.get("avatarInfoList", []) or []:
        aid = str(av.get("avatarId"))
        name = M.AVATAR_ID2NAME.get(aid, "")
        if detail and (detail in name or name in detail):
            return av
    return None


# ============================================================================
# 8 项面板属性 (对齐 miao ProfileDetail.js 的 attr 生成)
# ============================================================================

def _build_attr(fpm: dict, base_attr: dict) -> dict:
    """attr.{hp,atk,def,mastery,cpct,cdmg,recharge,dmg} + Base + Plus (Plus 无 + 号)."""
    out = {}

    # 数值型 (comma): hp n=0, atk/def/mastery n=1
    for key, nid, n in (("hp", "2000", 0), ("atk", "2001", 1), ("def", "2002", 1), ("mastery", "28", 1)):
        total = float(fpm.get(nid) or 0)
        base = float(base_attr.get(key) or 0)
        out[key] = _comma(total, n)
        out[key + "Base"] = _comma(base, n)
        out[key + "Plus"] = _comma(total - base, n)

    # 百分比型 (pct): cpct/cdmg/recharge 基础值分别为 5%/50%/100%
    base_map = {"cpct": 0.05, "cdmg": 0.50, "recharge": 1.0}
    for key, nid in (("cpct", "20"), ("cdmg", "22"), ("recharge", "23")):
        total = float(fpm.get(nid) or 0)
        base = base_map[key]
        out[key] = _pct(total)
        out[key + "Base"] = _pct(base)
        out[key + "Plus"] = _pct(total - base)

    # dmg: 取最大元素/物理伤害加成 (排除 28=元素精通)
    # Enka prop: 24-30 (旧元素系) + 40-46 (新: 火水雷草风冰岩) + 29 (物理)
    dmg_total = 0.0
    for nid in list(range(24, 31)) + list(range(40, 47)) + [29]:
        if nid == 28:
            continue
        dmg_total = max(dmg_total, float(fpm.get(str(nid)) or 0))
    out["dmg"] = _pct(dmg_total)
    out["dmgBase"] = _pct(0.0)
    out["dmgPlus"] = _pct(dmg_total)

    return out


# ============================================================================
# 圣遗物
# ============================================================================

def _arti_pos(mkey: str) -> int:
    """按主词条 key 推断圣遗物位置 (miao: 1=花 2=羽 3=沙 4=杯 5=冠)."""
    if mkey == "hpPlus":
        return 1
    if mkey == "atkPlus":
        return 2
    if mkey in ("dmg", "phy"):
        return 4
    if mkey in ("heal", "cpct", "cdmg"):
        return 5
    return 3  # atk/def/hp/mastery/recharge 大词条 -> 沙


def _build_artifacts(artifacts_raw) -> List[dict]:
    """Enka 圣遗物列表 -> miao 词条结构 [{key, title, value, upNum}], 含位置 pos."""
    out = []
    for idx, a in enumerate(artifacts_raw):
        af = a.get("flat", {}) or {}
        rel = a.get("reliquary", {}) or {}
        set_id = rel.get("setId")
        set_name = M.set_name_from_id(set_id) if set_id else None
        # Enka 新版: reliquary.setId 常为 None, 从 itemId 前 3 位反查套装
        if not set_name:
            set_name = M.set_name_from_item_id(a.get("itemId"))

        # 主词条
        mainst = af.get("reliquaryMainstat", {}) or {}
        mkey = _arti_prop_key(mainst.get("mainPropId", ""))
        mval = mainst.get("statValue", 0)

        # 副词条
        subs = []
        for s in af.get("reliquarySubstats", []) or []:
            k = _arti_prop_key(s.get("appendPropId", ""))
            if not k:
                continue
            subs.append({
                "key": k,
                "value": _fmt_arti_value(k, s.get("statValue", 0)),
                "upNum": int(s.get("extraLevel", 0) or 0),
            })

        out.append({
            "piece": "artis%d" % (idx + 1),
            "pos": _arti_pos(mkey),
            "set_name": set_name or "",
            "set_id": str(set_id) if set_id else "",
            "level": max((rel.get("level") or 1) - 1, 0),
            "star": af.get("rankLevel", 0) or 5,
            "main": {"key": mkey, "value": _fmt_arti_value(mkey, mval)} if mkey else {"key": "", "value": ""},
            "subs": subs,
            "mark": 0,
            "markClass": "C",
        })
    return out


def _build_artis_detail(artifacts: List[dict], weapon: Optional[dict], cn_name: str = "",
                        cons: int = 0, elem: str = "") -> dict:
    """
    完整复刻 miao ProfileAvatar.getArtisMark():
      charWeight / allAttr / mark / markClass / classTitle / artis
    评分 = ArtisMark.getMark (idx 1-5, 花/羽主词条不计分)
    """
    counts = {}
    pct_vals = {}
    for a in artifacts:
        # miao Artis.getAllAttr: 主词条不计入 allAttr (add(arti.main) 被注释),
        # 评分区只统计副词条累计
        for s in a.get("subs", []):
            _acc(counts, pct_vals, s["key"], s["value"])

    # 角色评分权重 (usefulAttr + 芙宁娜特判) + 基础属性
    attr_weight = _miao_get_attr_weight(cn_name, cons)
    base_attr = _base_attr(cn_name)

    # miao getCfg: 词条 mark 表 + 位置最高分
    attrs = _miao_cfg_attrs(attr_weight, base_attr)
    pos_max_mark = _miao_pos_max_mark(attrs)

    # 按位置排序圣遗物 (花1 羽2 沙3 杯4 冠5)
    artifacts_sorted = sorted(artifacts, key=lambda a: a.get("pos", 3))

    all_attr = _build_all_attr(counts, pct_vals, attr_weight)

    total_mark = 0.0
    artis = []
    for idx, a in enumerate(artifacts_sorted):
        pos = a.get("pos", idx + 1)
        mark = _miao_arti_mark(attrs, pos_max_mark, pos, a.get("main") or {}, a.get("subs") or [], elem)
        total_mark += mark
        artis.append(_arti_card(a, pos, mark, attr_weight))

    mark_class = _miao_mark_class(total_mark / 5.0)

    return {
        "charWeight": {k: v["weight"] for k, v in attrs.items()},
        "allAttr": all_attr,
        "mark": "{:.1f}".format(total_mark),
        "markClass": mark_class,
        "msg": "圣遗物总分 {:.1f} · 评级 {}".format(total_mark, mark_class),
        "classTitle": cn_name + "-通用",
        "artis": artis,
    }


def _acc(counts, pct_vals, key, value_str):
    """累计词条值: 百分比和数值分开."""
    try:
        f = float(str(value_str).replace("%", "").replace(",", ""))
    except (TypeError, ValueError):
        return
    if key in M.PCT_KEYS:
        pct_vals[key] = pct_vals.get(key, 0.0) + f
    else:
        counts[key] = counts.get(key, 0.0) + f


def _score_one(key, value_str, char_weight, base_attr=None, main=False) -> float:
    """miao attrMap 比例 + 简化归一化: (val/max) * weight * 0.30.
    主词条 max=ARTI_MAIN_MAX (主词条最大值), 副词条 max=4 * attrMap 单次提升值.
    char_weight 决定词条权重 (cpct/cdmg=100, atk=75 等)."""
    try:
        f = float(str(value_str).replace("%", "").replace(",", ""))
    except (TypeError, ValueError):
        return 0.0
    weight = char_weight.get(key, 0)
    if weight <= 0:
        return 0.0
    if main:
        max_val = ARTI_MAIN_MAX.get(key, 0)
    else:
        max_val = _arti_sub_max(key)
    if max_val <= 0:
        return 0.0
    pct = min(f / max_val, 1.0)
    return pct * weight * 0.21


def _build_all_attr(counts, pct_vals, char_weight) -> List[dict]:
    """圣遗物评分区 9 格小方块: {title, key, value, eff}.
    只统计副词条 (主词条不计入), 排除元素伤害/物伤 (副词条不可能有),
    按角色权重从高到低优先展示 (角色偏好的词条在前)."""
    # 所有可能的副词条 key (排除 dmg/phy 等主词条专用)
    keys_order = ["cpct", "cdmg", "atk", "hp", "def", "mastery", "recharge",
                  "atkPlus", "hpPlus", "defPlus"]
    # 按角色权重排序 (权重高 = 角色偏好的词条优先展示)
    keys_order = sorted(keys_order, key=lambda k: char_weight.get(k, 0), reverse=True)
    out = []
    for key in keys_order:
        if key in pct_vals:
            val_str = "{:.1f}%".format(pct_vals[key])
            out.append({"title": M.ARTI_KEY_TITLE.get(key, key), "key": key,
                        "value": val_str, "eff": _arti_eff(key, val_str)})
        elif key in counts:
            val_str = "{:,.1f}".format(counts[key])
            out.append({"title": M.ARTI_KEY_TITLE.get(key, key), "key": key,
                        "value": val_str, "eff": _arti_eff(key, val_str)})
        if len(out) >= 9:
            break
    while len(out) < 9:
        out.append({"title": "", "key": "", "value": "", "eff": 0})
    return out


def _score_arti(a, char_weight, base_attr) -> float:
    """单件圣遗物评分 (miao ArtisMark.getMark 简化版): 主 + 副累加."""
    main = a.get("main") or {}
    if not main.get("key"):
        return 0.0
    ret = _score_one(main["key"], main["value"], char_weight, base_attr, main=True)
    for s in a.get("subs", []):
        ret += _score_one(s["key"], s["value"], char_weight, base_attr, main=False)
    return ret


# miao ArtisMark.getMarkClass 阈值 (单件 mark 分数)
_MARK_CLASS_THRESH = [
    (7, "D"), (14, "C"), (21, "B"), (28, "A"), (35, "S"),
    (42, "SS"), (49, "SSS"), (56, "ACE"), (70, "MAX"),
]


def _arti_eff(key: str, value_str) -> float:
    """副词条等效词条数 (miao ArtisAttr: eff = value / attrMap[key].value).
    例: 暴击伤害 27.2% / 单次满档 7.77% = 3.5 词条."""
    cfg = ARTI_ATTR_MAP.get(key)
    if not cfg:
        return 0.0
    try:
        f = float(str(value_str).replace("%", "").replace(",", ""))
    except (TypeError, ValueError):
        return 0.0
    max_v = float(cfg.get("value", 0) or 0)
    if max_v <= 0:
        return 0.0
    return round(f / max_v, 1)


def _arti_card(a, pos, mark, char_weight) -> dict:
    """圣遗物卡字段 (对齐模板 ad.artis 用法)."""
    set_name = a.get("set_name") or ""
    img = M.artifact_icon_rel(set_name, pos - 1) if set_name else ""
    abbr = set_name or "圣遗物"
    main_title = M.ARTI_KEY_TITLE.get((a.get("main") or {}).get("key", ""), "")
    attrs = []
    for s in a.get("subs", []):
        attrs.append({
            "key": s["key"],
            "value": s["value"],
            "upNum": s.get("upNum", 0),
            "eff": _arti_eff(s["key"], s["value"]),
        })
    mark_class = _miao_mark_class(mark)
    return {
        "name": abbr,
        "abbr": abbr,
        "img": img,
        "level": a.get("level", 0),
        "mark": round(mark, 1),
        "markClass": mark_class,
        "main": {"key": (a.get("main") or {}).get("key", ""), "value": (a.get("main") or {}).get("value", "")},
        "attrs": attrs,
        "mainTitle": main_title,
    }


# miao ArtisMark.getMarkClass 阈值 (单件 mark 分级)
_MARK_CLASS_THRESH = [
    (7, "D"), (14, "C"), (21, "B"), (28, "A"), (35, "S"),
    (42, "SS"), (49, "SSS"), (56, "ACE"), (70, "MAX"),
]


def _char_weight(cn_name: str) -> dict:
    """按角色名取权重表; 芙宁娜用专属配置, 其他用通用默认."""
    base = dict(M.CHAR_WEIGHT_DEFAULT)
    profile = CHAR_WEIGHT_PROFILES.get(cn_name)
    if profile:
        for k, v in profile.items():
            base[k] = v
    return base


def _base_attr(cn_name: str) -> dict:
    """角色基础属性 (HP/ATK/DEF) — 用于小词条 mark 计算."""
    meta = M.char_meta(cn_name) or {}
    return meta.get("baseAttr", {}) or {}


# miao ArtisMark.getMarkClass 阈值 (单件 mark 分级)
_MARK_CLASS_THRESH = [
    (7, "D"), (14, "C"), (21, "B"), (28, "A"), (35, "S"),
    (42, "SS"), (49, "SSS"), (56, "ACE"), (70, "MAX"),
]


def _mark_class(mark) -> str:
    """miao getMarkClass 风格: 单件 mark 分级."""
    for thresh, cls in _MARK_CLASS_THRESH:
        if mark < thresh:
            return cls
    return "MAX"


# ============================================================================
# 武器
# ============================================================================

def _build_weapon(w) -> Optional[dict]:
    if not w:
        return None
    flat = w.get("flat", {}) or {}
    wid = w.get("weapon", {}) or {}
    item_id = str(w.get("itemId"))
    name = M.WEAPON_ID2NAME.get(item_id, "")
    if not name:
        return None
    wmeta = M.weapon_meta(name) or {}

    level = wid.get("level", 0) or 90
    aff = wid.get("affixMap", {}) or {}
    refine = (max(int(x) for x in aff.values()) + 1) if aff else 1

    # 武器被动效果描述 (含数值加成): affixData.text + datas[0..n][refine-1] 替换 $[0..n] 占位符
    # 不展示背景故事 (data.json.desc), 只展示被动效果 (affixData.text)
    affix_desc = ""
    affix_data = wmeta.get("affixData") or {}
    affix_text = affix_data.get("text", "") or ""
    affix_datas = affix_data.get("datas", {}) or {}
    if affix_text and affix_datas:
        affix_desc = affix_text
        # datas 是 dict {"0": [...], "1": [...]} 数组, 按当前精炼索引 (refine 1-5)
        for idx_str, vals in affix_datas.items():
            placeholder = "$[%s]" % idx_str
            if placeholder in affix_desc and vals:
                try:
                    val = vals[refine - 1]
                    affix_desc = affix_desc.replace(placeholder, str(val))
                except (IndexError, TypeError):
                    pass

    # 武器主属性 (武器攻击力)
    wstats = flat.get("weaponStats", []) or []
    atk_base = 0.0
    bonus_key = ""
    bonus_val = 0.0
    if len(wstats) >= 1:
        atk_base = float(wstats[0].get("statValue", 0) or 0)
    if len(wstats) >= 2:
        bonus_key = _arti_prop_key(wstats[1].get("appendPropId", ""))
        bonus_val = float(wstats[1].get("statValue", 0) or 0)

    attrs = {"atkBase": _comma(atk_base, 1)}
    if bonus_key:
        # weaponStats.statValue 是百分比数值形式 (51.8 = 51.8%), mul=1 不再 * 100
        if bonus_key in M.PCT_KEYS:
            attrs[bonus_key] = "{:.1f}%".format(bonus_val)
        else:
            attrs[bonus_key] = _comma(bonus_val, 1)

    return {
        "name": name,
        "sName": name,
        "star": flat.get("rankLevel", 0) or 5,
        "affix": refine,
        "level": level,
        "img": M.weapon_icon_rel(name),
        "type": wmeta.get("weapon") or "",
        "attrs": attrs,
        # 武器被动效果描述 (含数值加成), 不展示背景故事 (data.json.desc)
        # 模板 {{@weapon.desc?.desc}} 用 ?. 短路防 weapon.desc 为 null
        "desc": {"desc": affix_desc},
    }


# ============================================================================
# 角色天赋 / 图标
# ============================================================================

def _build_talent(target, cn_name) -> dict:
    meta = M.char_meta(cn_name) or {}
    talent_id_map = meta.get("talentId", {}) or {}
    skill_to_key = {str(sk): k for sk, k in talent_id_map.items()}
    skm = target.get("skillLevelMap", {}) or {}
    by_key = {}
    for sk, lv in skm.items():
        key = skill_to_key.get(str(sk))
        if key in ("a", "e", "q"):
            by_key[key] = int(lv)
    out = {}
    for k in ("a", "e", "q"):
        lv = by_key.get(k, 0)
        out[k] = {"level": lv, "original": lv}
    return out


def _build_imgs(cn_name, weapon=None) -> dict:
    """角色图标字典 (对齐 miao CharImg.js getImgs).
    a = common/item/atk-{weaponType}.webp
    e/q = talentCons[key] > 0 ? icons/cons-{talentCons[key]}.webp : icons/talent-{key}.webp
    weapon: 优先用传入的 (来自 Enka equipList.weapon.type), 否则从 data.json 读
    """
    imgs = {}
    weapon_type = (weapon or {}).get("type") or M._read_char_field(cn_name, "weapon") if hasattr(M, "_read_char_field") else None
    talent_cons = M._read_char_field(cn_name, "talentCons") if hasattr(M, "_read_char_field") else None
    weapon_type = weapon_type or "sword"
    for k in ("a", "e", "q"):
        imgs[k] = M.char_icon_rel(cn_name, k, weapon_type=weapon_type, talent_cons=talent_cons)
    for n in range(1, 7):
        imgs["cons%d" % n] = M.char_cons_icon_rel(cn_name, n)
    # passive0..4 (miao 也传给模板, 备用)
    for i in range(5):
        p = os.path.join(M.MIAO_RES, "meta-gs", "character", cn_name, "icons", "passive-%d.webp" % i)
        rel = "meta-gs/character/%s/icons/passive-%d.webp" % (cn_name, i)
        imgs["passive%d" % i] = rel if os.path.isfile(p) else ""
    imgs["splash"] = M.char_splash_rel(cn_name)
    imgs["costumeSplash"] = M.char_splash_rel(cn_name)
    return imgs


# ============================================================================
# 渲染入口 (供 plugins/genshin.py 调用)
# ============================================================================

def build_card(raw: dict, uid: str, detail: str) -> Optional[dict]:
    """兼容旧接口名: 返回 renderData dict (旧 build_card 的替代)."""
    return build_render_data(raw, uid, detail)
