# -*- coding: utf-8 -*-
"""
v55: 极限面板配装数据源 — 跟随 Yunzai(miao-plugin) 同款社区使用率.

真实数据来源: miao-plugin apps/stat/HutaoApi.getLelaerData()
  -> https://api.lelaer.com/ys/getRoleAvg.php?star=all&lang=zh-Hans
榜首武器 / 榜首 4 件套 = 社区共识毕业配装 (与 Yunzai `#角色极限面板` 同源).

本模块职责:
  1. 抽取每角色榜首武器 + 榜首 4 件套 -> yunzai_lelaer_builds.json
     - 武器名 经 miao weapon/<type>/data.json 解析为 Enka itemId (= miao 武器 id)
     - 套装名 去尾 "2/4" 后反查 maps.ENKA_SET_ID2NAME 解析为合法 setId(图标存在)
  2. 从 miao 每武器 data.json 自动构建完整武器基础表 -> yunzai_weapon_base.json
     - {weapon_id: [基础攻击Lv90, 副词条key, 副词条数值]}
  3. 运行时 best_weapon(char) / best_sets(char) 取数, 未命中返回 None 让调用方回退手写表
  4. refresh_lelaer_builds(): 重新拉取 lelaer API 重建两份 JSON (含本地 weapon_base 重建)

调用方 (max_panel._make_max_raw) 用法:
    wp = LS.best_weapon(char) or _CHARACTER_BEST_WEAPON.get(char)
    sp = LS.best_sets(char)  or _CHARACTER_BEST_SET.get(char, (15009,15016))
未命中 lelaer 的角色 (如新角色/旅行者) 自动回退手写表, 不影响渲染.
"""

import os
import json
import urllib.request
import urllib.error

from . import maps as M

_DIR = os.path.dirname(os.path.abspath(__file__))
_BUILDS_PATH = os.path.join(_DIR, "yunzai_lelaer_builds.json")
_WBASE_PATH = os.path.join(_DIR, "yunzai_weapon_base.json")

LELAER_URL = "https://api.lelaer.com/ys/getRoleAvg.php?star=all&lang=zh-Hans"

# 2 件套兜底固定 15001 角斗士的终幕礼 (图标齐全, 永不冲突)
_SET2_DEFAULT = 15001

_WEAPON_TYPES = ("bow", "catalyst", "claymore", "polearm", "sword")


def _load_json(path):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


# ---- 模块级缓存 ----
BUILDS = _load_json(_BUILDS_PATH)
WEAPON_BASE = {int(k): tuple(v) for k, v in _load_json(_WBASE_PATH).items()}

# 套装中文名 -> [setId...] (来自 maps.ENKA_SET_ID2NAME)
_NAME2SETS = {}
for _sid, _name in M.ENKA_SET_ID2NAME.items():
    _NAME2SETS.setdefault(_name, []).append(_sid)


def _resolve_set_name_to_id(set_cn_name):
    """套装中文名 -> 一个合法 setId (其名在 SET_DIRS 有图标). 失败返回 None.

    解析顺序:
      1) ENKA_SET_ID2NAME 中的真实 Enka setId (社区经典套装, 如宗室 15015)
      2) EXTRA_SET_ID2NAME 中的合成 159xx id (miao 无 Enka id 但图标齐全的新套装)
    """
    if not set_cn_name:
        return None
    # 1) 真实 Enka 套装
    for sid in (_NAME2SETS.get(set_cn_name) or []):
        if M.set_name_from_id(sid):   # 非 None 表示可解析且有图标
            return int(sid)
    # 2) 合成新套装 (159xx, 与真实 Enka 150xx 不冲突)
    if set_cn_name in M.SET_DIRS:
        for sid, nm in M.EXTRA_SET_ID2NAME.items():
            if nm == set_cn_name:
                return int(sid)
    return None


# 武器名 -> (id, type) 由 miao weapon data 构建 (懒加载一次)
_WEAPON_NAME_MAP = None


def _build_weapon_name_map():
    global _WEAPON_NAME_MAP
    if _WEAPON_NAME_MAP is not None:
        return _WEAPON_NAME_MAP
    mp = {}
    base = os.path.join(M.MIAO_RES, "meta-gs", "weapon")
    for _type in _WEAPON_TYPES:
        dp = os.path.join(base, _type, "data.json")
        if not os.path.isfile(dp):
            continue
        try:
            with open(dp, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue
        for _wid, _val in d.items():
            _nm = _val.get("name")
            if _nm:
                mp.setdefault(_nm, (str(_wid), _type))
    _WEAPON_NAME_MAP = mp
    return mp


def _normalize_set_name(raw):
    """lelaer 套装名 '炽烈的炎之魔女4' -> '炽烈的炎之魔女'."""
    s = (raw or "").strip()
    s = s.rstrip("24")   # 去尾 2/4 (套装件数)
    return s.strip()


def _build_weapon_base(bonus_keys_out=None):
    """全量自动构建 {weapon_id_str: [atk_lv90, bonus_key, bonus_val]}.

    跳过 1/2 星起步武器 (无 atk.90 也无副词条, 永不用于毕业面板).
    """
    base = os.path.join(M.MIAO_RES, "meta-gs", "weapon")
    out = {}
    for _type in _WEAPON_TYPES:
        idx = os.path.join(base, _type, "data.json")
        if not os.path.isfile(idx):
            continue
        try:
            with open(idx, encoding="utf-8") as f:
                index = json.load(f)
        except Exception:
            continue
        for _wid_str, meta in index.items():
            _nm = meta.get("name")
            if not _nm:
                continue
            wdp = os.path.join(base, _type, _nm, "data.json")
            if not os.path.isfile(wdp):
                continue
            try:
                with open(wdp, encoding="utf-8") as f:
                    w = json.load(f)
            except Exception:
                continue
            attr = w.get("attr") or {}
            atk = (attr.get("atk") or {}).get("90")
            if atk is None:
                continue   # 1/2 星无 Lv90
            bonus_key = attr.get("bonusKey")
            bonus_val = (attr.get("bonusData") or {}).get("90") or 0
            if bonus_keys_out is not None and bonus_key:
                bonus_keys_out.add(bonus_key)
            out[str(_wid_str)] = [atk, bonus_key or "", bonus_val]
    return out


def parse_lelaer_payload(payload):
    """lelaer API 返回 dict -> (builds, weapon_base, report).

    builds: {标准角色名: {"weapon":{name,id,type,rate}, "set":{name,id,rate,piece}}}
    weapon_base: {weapon_id_str: [atk, bonus_key, bonus_val]}
    report: {unmapped_weapon, unmapped_set, bonus_keys, total}
    """
    _build_weapon_name_map()
    result = (payload or {}).get("result") or []
    builds = {}
    unmapped_weapon = []
    unmapped_set = []
    bonus_keys = set()

    for item in result:
        role = item.get("role")
        if not role:
            continue
        rname = M.resolve_char_name(role) or role

        # ---- 武器: 取榜首 ----
        wlist = item.get("weapon") or []
        wname = wrate = wid = wtype = None
        if wlist:
            top = wlist[0]
            wname = top.get("name")
            wrate = top.get("rate")
            m = _WEAPON_NAME_MAP.get(wname) if wname else None
            if m:
                wid, wtype = m
            else:
                unmapped_weapon.append((role, wname))
        # ---- 套装: 取榜首 ----
        slist = item.get("artifacts_set") or []
        sname = srate = sid = spiece = None
        if slist:
            top = slist[0]
            raw_name = top.get("name")
            srate = top.get("rate")
            cn = _normalize_set_name(raw_name)
            sname = cn
            sid = _resolve_set_name_to_id(cn)
            if raw_name and raw_name[-1] in ("2", "4"):
                spiece = int(raw_name[-1])
            if sid is None:
                unmapped_set.append((role, raw_name, cn))

        builds[rname] = {
            "weapon": ({"name": wname, "id": wid, "type": wtype, "rate": wrate}
                       if (wname and wid) else None),
            "set": ({"name": sname, "id": sid, "rate": srate, "piece": spiece}
                    if (sname and sid) else None),
        }

    weapon_base = _build_weapon_base(bonus_keys)
    report = {
        "total": len(builds),
        "weapon_base": len(weapon_base),
        "unmapped_weapon": unmapped_weapon,
        "unmapped_set": unmapped_set,
        "bonus_keys": sorted(bonus_keys),
    }
    return builds, weapon_base, report


# ============================================================================
# 运行时取数接口 (调用方 max_panel._make_max_raw 使用)
# ============================================================================

def best_weapon(char_name):
    """返回 (id, name, type) 或 None (让调用方回退手写 _CHARACTER_BEST_WEAPON)."""
    rname = M.resolve_char_name(char_name) or char_name
    b = BUILDS.get(rname)
    if not b:
        return None
    w = b.get("weapon")
    if not w or not w.get("id"):
        return None
    return (int(w["id"]), w["name"], w["type"])


def best_sets(char_name):
    """返回 (set4_id, set2_id=15001) 或 None (让调用方回退手写 _CHARACTER_BEST_SET)."""
    rname = M.resolve_char_name(char_name) or char_name
    b = BUILDS.get(rname)
    if not b:
        return None
    s = b.get("set")
    if not s or not s.get("id"):
        return None
    return (int(s["id"]), _SET2_DEFAULT)


# ============================================================================
# 刷新: 重新拉取 lelaer API 重建 JSON
# ============================================================================

def fetch_lelaer_payload():
    """HTTP GET lelaer API, 返回解析后的 dict. 失败抛异常."""
    req = urllib.request.Request(
        LELAER_URL, headers={"User-Agent": "Mozilla/5.0 (lelaer build sync)"}
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8"))


def refresh_lelaer_builds(payload=None, write=True):
    """重建两份 JSON 并热更新模块缓存.

    payload: 可选, 直接传入已解析的 lelaer dict (离线用); 为 None 时实时拉取.
    返回 report 字典.
    """
    global BUILDS, WEAPON_BASE
    if payload is None:
        payload = fetch_lelaer_payload()
    builds, weapon_base, report = parse_lelaer_payload(payload)
    BUILDS = builds
    WEAPON_BASE = {int(k): tuple(v) for k, v in weapon_base.items()}
    if write:
        with open(_BUILDS_PATH, "w", encoding="utf-8") as f:
            json.dump(builds, f, ensure_ascii=False, indent=1)
        with open(_WBASE_PATH, "w", encoding="utf-8") as f:
            json.dump(weapon_base, f, ensure_ascii=False, indent=1)
    return report


if __name__ == "__main__":
    # 离线构建: 优先用 /tmp/lelaer.json 快照; 否则实时拉取
    snap = "/tmp/lelaer.json"
    if os.path.exists(snap):
        with open(snap, encoding="utf-8") as f:
            payload = json.load(f)
    else:
        payload = fetch_lelaer_payload()
    rep = refresh_lelaer_builds(payload=payload)
    print("== lelaer 配装构建报告 ==")
    print("角色数:", rep["total"])
    print("武器基础表:", rep["weapon_base"])
    print("副词条 bonusKey 集合:", rep["bonus_keys"])
    print("未映射武器(名不在 miao):", rep["unmapped_weapon"])
    print("未映射套装(名无法解析):", rep["unmapped_set"])
