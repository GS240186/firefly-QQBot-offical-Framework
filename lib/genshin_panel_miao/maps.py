# -*- coding: utf-8 -*-
"""
静态映射 + Enka 词条 -> miao 词条 key 转换 (对齐 miao-plugin resources/meta-gs/artifact/extra.js)

关键映射 (attrMap):
  miao key:  atk/atkPlus/def/defPlus/hp/hpPlus/cpct/cdmg/mastery/recharge/dmg/phy/heal
  标题:      大攻击/小攻击/大防御/小防御/大生命/小生命/暴击率/暴击伤害/元素精通/充能效率/元素伤害/物伤加成/治疗加成

artisKeyTitle 是对象 {key: 标题} — 不是数组! 模板 {{artisKeyTitle[ds.main?.key]}} 按 key 查标题。
"""

import os
import json

# miao-plugin 资源根 (唯一依赖: 图标/字体/模板全在这里)
MIAO_RES = r"C:\Users\123\Desktop\Yunzai\miao-plugin\resources"

# ---- Enka propId -> miao 词条 key (圣遗物主/副词条) ----
ENKA_ARTI_PROP2KEY = {
    "FIGHT_PROP_HP": "hpPlus",           # 小生命 (数值)
    "FIGHT_PROP_HP_PERCENT": "hp",       # 大生命 (%)
    "FIGHT_PROP_ATTACK": "atkPlus",      # 小攻击
    "FIGHT_PROP_ATTACK_PERCENT": "atk",  # 大攻击
    "FIGHT_PROP_DEFENSE": "defPlus",     # 小防御
    "FIGHT_PROP_DEFENSE_PERCENT": "def", # 大防御
    "FIGHT_PROP_CRITICAL": "cpct",       # 暴击率
    "FIGHT_PROP_CRITICAL_HURT": "cdmg",  # 暴击伤害
    "FIGHT_PROP_ELEMENT_MASTERY": "mastery",  # 元素精通
    "FIGHT_PROP_CHARGE_EFFICIENCY": "recharge",  # 充能效率
    "FIGHT_PROP_HEAL_ADD": "heal",       # 治疗加成
    "FIGHT_PROP_PHYSICAL_ADD_HURT": "phy",  # 物伤加成
    # 元素伤害加成 -> dmg (取最大元素)
    "FIGHT_PROP_FIRE_ADD_HURT": "dmg",
    "FIGHT_PROP_WATER_ADD_HURT": "dmg",
    "FIGHT_PROP_GRASS_ADD_HURT": "dmg",
    "FIGHT_PROP_ELEC_ADD_HURT": "dmg",
    "FIGHT_PROP_WIND_ADD_HURT": "dmg",
    "FIGHT_PROP_ICE_ADD_HURT": "dmg",
    "FIGHT_PROP_ROCK_ADD_HURT": "dmg",
}

# miao attrMap: key -> {title, format} (从 extra.js 摘录)
ARTI_KEY_TITLE = {
    "atk": "大攻击", "atkPlus": "小攻击",
    "def": "大防御", "defPlus": "小防御",
    "hp": "大生命", "hpPlus": "小生命",
    "cpct": "暴击率", "cdmg": "暴击伤害",
    "mastery": "元素精通", "recharge": "充能效率",
    "dmg": "元素伤害", "phy": "物伤加成", "heal": "治疗加成",
}

# allAttr 区短名 (模板 sTitle)
ARTI_SHORT_TITLE = {
    "暴击率": "暴击", "暴击伤害": "爆伤", "充能效率": "充能",
    "元素精通": "精通", "大生命": "生命", "大攻击": "攻击",
    "大防御": "防御", "小生命": "生命", "小攻击": "攻击",
    "小防御": "防御", "元素伤害": "伤害", "治疗加成": "治疗",
    "物伤加成": "物伤",
}

# 是否为百分比词条
PCT_KEYS = {"atk", "def", "hp", "cpct", "cdmg", "recharge", "dmg", "phy", "heal"}

# 通用词条权重 (无角色配置时的兜底, 满 100 为有用词条)
CHAR_WEIGHT_DEFAULT = {
    "cpct": 100, "cdmg": 100, "atk": 80, "hp": 60,
    "def": 50, "mastery": 75, "recharge": 50, "dmg": 60,
    "phy": 50, "heal": 50, "atkPlus": 30, "hpPlus": 30, "defPlus": 30,
}

# ---- 圣遗物套装: Enka setId(5位) 前两位 = 套装组, 映射到套装目录名 ----
# Enka 150xx -> miao data.json 400xxx 套装组. 通过 miao artifact/imgs 目录反查.
def load_set_dir_map():
    """构建 {set_group_2digit: 套装目录名} — 扫描 miao meta-gs/artifact/imgs/ 目录."""
    base = os.path.join(MIAO_RES, "meta-gs", "artifact", "imgs")
    out = {}
    if not os.path.isdir(base):
        return out
    for name in sorted(os.listdir(base)):
        d = os.path.join(base, name)
        if os.path.isdir(d):
            out[name] = name
    return out

SET_DIRS = load_set_dir_map()

# Enka setId (15043) -> 前两位 (15) -> miao 套装组名
# 注意: miao 里 ArtifactSet.get(name) 对 5 位 setId 取前 2 位, 再用 alias 匹配套装组.
# 这里直接: 15043 -> 黄金剧团 (由 Enka 世界数据确定, 手工维护常用映射)
ENKA_SET_ID2NAME = {
    "15017": "千岩牢固",
    "15001": "角斗士的终幕礼",
    "15020": "绝缘之旗印",
    "15024": "来歆余响",
    "15018": "苍白之火",
    "15043": "黄金剧团",     # 芙宁娜套
    "15038": "炽烈的炎之魔女",
    "15047": "沉沦之心",
    "15019": "水仙之梦",
    "15046": "逐影猎人",
    "15045": "昔时之歌",
    "15035": "谐律异想断章",
    "15033": "花海甘露之光",
    "15021": "追忆之注连",
    "15008": "被怜爱的少女",
    "15002": "流浪大地的乐团",
    "15025": "饰金之梦",
    "15016": "翠绿之影",
    "15007": "炽烈的炎之魔女",
    "15011": "如雷的盛怒",
    "15010": "平息鸣雷的尊者",
    "15009": "冰风迷途的勇士",
    "15012": "悠古的磐岩",
    "15013": "渡过烈火的贤人",
    "15014": "沉沦之心",
    "15015": "昔日宗室之仪",   # 宗室套 (Noblesse) — 经典辅助 4 件套
    "15006": "千岩牢固",
    "15005": "逆飞的流星",
    "15004": "渡火者的祝福",
    "15003": "逆飞的流星",
    "15022": "海染砗磲",
    "15023": "华馆梦醒形骸记",
    "15026": "辰砂往生录",
    "15027": "沙上楼阁史话",
    "15028": "深林的记忆",
    "15029": "乐园遗落之花",
    "15030": "黄金剧团",
    "15031": "黄金剧团",
    "15032": "沙上楼阁史话",
    "15034": "花海甘露之光",
    "15036": "未竟的遐思",
    "15039": "长夜之誓",
    "15040": "晨星与月的晓歌",
    "15041": "穹境示现之夜",
    "15042": "纺月的夜歌",
}

# v55: 社区新增套装 (miao 当前版本 meta-gs 无其 Enka setId, 但 artifact/imgs 图标目录已存在).
# 用 159xx 合成 id, 与真实 Enka 150xx 永不冲突, 仅供极限面板展示社区配装.
# 仅当名字在 SET_DIRS (有图标) 时才生效.
EXTRA_SET_ID2NAME = {
    "15901": "黑曜秘典",
    "15902": "深廊终曲",
    "15903": "回声之林夜话",
    "15904": "风起之日",
    "15905": "烬城勇者绘卷",
    "15906": "天之美赐",
    "15907": "影中沉凝的幻灭",
}

# miao data.json 套装组 3 位 ID -> 套装名 (itemId 前 3 位)
def load_item3_set_map():
    """构建 {套装组3位ID: 套装中文名}: 从 miao data.json 的 idxs 物品 ID 前 3 位收集."""
    out = {}
    dp = os.path.join(MIAO_RES, "meta-gs", "artifact", "data.json")
    if not os.path.isfile(dp):
        return out
    import json
    try:
        with open(dp, encoding="utf-8") as f:
            data = json.load(f)
        for sid, cfg in data.items():
            name = cfg.get("name", "")
            idxs = cfg.get("idxs", {}) or {}
            for item in idxs.values():
                iid = str(item.get("id", ""))
                if len(iid) >= 3:
                    out.setdefault(iid[:3], name)
    except Exception:
        pass
    return out


ITEM3_TO_SET = load_item3_set_map()


# 部分套装组在 miao 里目录名 (若 ENKA_SET_ID2NAME 未命中, 兜底取 miao imgs 目录)
def set_name_from_id(set_id):
    """Enka setId (3 位套装组或 5 位物品 ID) -> miao 套装中文名 (图标目录名)."""
    sid = str(set_id)
    if len(sid) == 5:
        name = ITEM3_TO_SET.get(sid[:3])
        if name and name in SET_DIRS:
            return name
        name = ENKA_SET_ID2NAME.get(sid)
        if name and name in SET_DIRS:
            return name
        name = EXTRA_SET_ID2NAME.get(sid)
        if name and name in SET_DIRS:
            return name
        return None
    # 3 位套装组
    name = ENKA_SET_ID2NAME.get(sid)
    if name and name in SET_DIRS:
        return name
    name = EXTRA_SET_ID2NAME.get(sid)
    if name and name in SET_DIRS:
        return name
    name = ITEM3_TO_SET.get(sid)
    if name and name in SET_DIRS:
        return name
    return None


def set_name_from_item_id(item_id):
    """Enka 圣遗物 itemId (5 位, 前 3 位套装组) -> 套装中文名."""
    sid = str(item_id)
    if len(sid) >= 3:
        name = ITEM3_TO_SET.get(sid[:3])
        if name and name in SET_DIRS:
            return name
    return None


# ---- 角色: avatarId -> 中文名 (从 miao meta-gs/character/*/data.json 构建) ----
def load_avatar_map():
    base = os.path.join(MIAO_RES, "meta-gs", "character")
    out = {}
    if not os.path.isdir(base):
        return out
    import json
    for name in sorted(os.listdir(base)):
        dp = os.path.join(base, name, "data.json")
        if not os.path.isfile(dp):
            continue
        try:
            with open(dp, encoding="utf-8") as f:
                d = json.load(f)
            aid = str(d.get("id", ""))
            if aid:
                out[aid] = d.get("name", name)
        except Exception:
            continue
    return out

AVATAR_ID2NAME = load_avatar_map()

# ---- 武器: Enka itemId -> 武器中文名 (从 miao meta-gs/weapon/*/*/data.json) ----
def load_weapon_map():
    base = os.path.join(MIAO_RES, "meta-gs", "weapon")
    out = {}
    if not os.path.isdir(base):
        return out
    import json
    for wtype in sorted(os.listdir(base)):
        tdir = os.path.join(base, wtype)
        if not os.path.isdir(tdir):
            continue
        for name in sorted(os.listdir(tdir)):
            dp = os.path.join(tdir, name, "data.json")
            if not os.path.isfile(dp):
                continue
            try:
                with open(dp, encoding="utf-8") as f:
                    d = json.load(f)
                wid = str(d.get("id", ""))
                if wid:
                    out[wid] = d.get("name", name)
            except Exception:
                continue
    return out

WEAPON_ID2NAME = load_weapon_map()


# ============================================================
# 角色别名表: 用于 resolve_char_name 把玩家输入的昵称/简称
# 映射到 miao 标准名字 (与 AVATAR_ID2NAME values 对应)
# ============================================================
# 键小写. 仅收录全平台通用昵称/俗称/角色定位别名 (玩家常见用法)
# 已包含 miao data.json 自带的 abbr (char_abbr)
CHAR_ALIAS_TO_NAME = {
    # 雷电将军
    "雷神": "雷电将军", "雷电": "雷电将军", "将军": "雷电将军",
    "raiden": "雷电将军", "raiden shogun": "雷电将军", "baal": "雷电将军",
    # 芙宁娜
    "芙宁娜": "芙宁娜", "芙芙": "芙宁娜", "furina": "芙宁娜",
    "水神": "芙宁娜",
    # 纳西妲
    "纳西妲": "纳西妲", "草神": "纳西妲", "小草神": "纳西妲",
    "nahida": "纳西妲",
    # 胡桃
    "胡桃": "胡桃", "hu tao": "胡桃", "hutao": "胡桃", "胡堂主": "胡桃",
    # 甘雨
    "甘雨": "甘雨", "ganyu": "甘雨",
    # 钟离
    "钟离": "钟离", "zhongli": "钟离", "岩神": "钟离", "岩王": "钟离",
    # 雷电将军 / 神里绫华 / 八重神子 / 夜兰 / 九条裟罗
    "绫华": "神里绫华", "神里": "神里绫华", "ayaka": "神里绫华",
    "神子": "八重神子", "八重": "八重神子", "八重樱": "八重神子", "yae": "八重神子",
    "夜兰": "夜兰", "yelan": "夜兰",
    "九条": "九条裟罗", "裟罗": "九条裟罗", "kujou": "九条裟罗",
    # 神里绫人 / 枫原万叶 / 温迪 / 提纳里 / 艾尔海森
    "绫人": "神里绫人", "万叶": "枫原万叶", "叶天帝": "枫原万叶", "kazuha": "枫原万叶",
    "温迪": "温迪", "风神": "温迪", "巴巴托斯": "温迪", "venti": "温迪",
    "提纳里": "提纳里", "tighnari": "提纳里",
    "海森": "艾尔海森", "海哥": "艾尔海森", "alhaitham": "艾尔海森",
    # 流浪者 / 散兵
    "流浪者": "流浪者", "散兵": "流浪者", "国崩": "流浪者", "wanderer": "流浪者",
    "风男": "流浪者",
    # 妮露 / 莫娜 / 迪卢克 / 可莉 / 魈 / 阿贝多
    "妮露": "妮露", "nilou": "妮露",
    "莫娜": "莫娜", "mona": "莫娜", "水魔兽": "莫娜",
    "迪卢克": "迪卢克", "卢姥爷": "迪卢克", "diluc": "迪卢克",
    "可莉": "可莉", "klee": "可莉",
    "魈": "魈", "xiao": "魈", "护法夜叉": "魈", "夜叉": "魈",
    "阿贝多": "阿贝多", "albedo": "阿贝多",
    # 达达利亚 / 荒泷一斗 / 珊瑚宫心海 / 琴 / 菲谢尔
    "达达利鸭": "达达利亚", "公子": "达达利亚", "鸭鸭": "达达利亚", "tartaglia": "达达利亚", "childe": "达达利亚",
    "一斗": "荒泷一斗", "荒泷": "荒泷一斗", "itto": "荒泷一斗",
    "心海": "珊瑚宫心海", "海祈": "珊瑚宫心海", "kokomi": "珊瑚宫心海",
    "琴": "琴", "团长": "琴", "jean": "琴",
    "皇女": "菲谢尔", "菲谢尔": "菲谢尔", "fischl": "菲谢尔",
    # 刻晴 / 迪希雅 / 提纳里
    "刻晴": "刻晴", "keqing": "刻晴",
    "迪希雅": "迪希雅", "沙漠猫": "迪希雅", "dehya": "迪希雅",
    # 哥伦比娅 / 玛薇卡 / 希格雯 / 千织 / 克洛琳德
    "哥伦比娅": "哥伦比娅", "哥伦比": "哥伦比娅", "columbina": "哥伦比娅",
    "玛薇卡": "玛薇卡", "火女": "玛薇卡", "mavuika": "玛薇卡",
    "希格雯": "希格雯", "sigewinne": "希格雯",
    "千织": "千织", "chiori": "千织",
    "克洛琳德": "克洛琳德", "克洛": "克洛琳德", "clorinde": "克洛琳德",
    # 阿蕾奇诺 / 那维莱特
    "阿蕾奇诺": "阿蕾奇诺", "老爹": "阿蕾奇诺", "父女": "阿蕾奇诺", "arlecchino": "阿蕾奇诺", "红": "阿蕾奇诺",
    "那维莱特": "那维莱特", "水龙王": "那维莱特", "那维": "那维莱特", "neuvillette": "那维莱特",
    # 申鹤 / 罗莎莉亚 / 烟绯 / 砂糖 / 久岐忍 / 九条 / 五郎
    "申鹤": "申鹤", "shenhe": "申鹤",
    "罗莎莉亚": "罗莎莉亚", "罗莎": "罗莎莉亚", "rosaria": "罗莎莉亚",
    "烟绯": "烟绯", "yanfei": "烟绯",
    "砂糖": "砂糖", "sucrose": "砂糖",
    "久岐忍": "久岐忍", "忍": "久岐忍", "kuki": "久岐忍",
    "五郎": "五郎", "gorou": "五郎",
    # 林尼 / 琳妮特 / 菲米尼 / 绮良良 / 夏洛蒂 / 艾梅莉埃
    "林尼": "林尼", "lyney": "林尼",
    "琳妮特": "琳妮特", "琳妮": "琳妮特", "lynette": "琳妮特",
    "菲米尼": "菲米尼", "freminet": "菲米尼",
    "绮良良": "绮良良", "绮良": "绮良良", "kira": "绮良良",
    "夏洛蒂": "夏洛蒂", "夏洛": "夏洛蒂", "charlotte": "夏洛蒂",
    "艾梅莉埃": "艾梅莉埃", "爱梅": "艾梅莉埃", "emilie": "艾梅莉埃",
    # 早柚 / 烟绯 / 夜兰 (上面已有) / 莱欧斯利 / 林尼 / 妮露 (上面已有)
    "早柚": "早柚", "sayu": "早柚", "小狸猫": "早柚",
    "莱欧斯利": "莱欧斯利", "莱欧": "莱欧斯利", "wriothesley": "莱欧斯利",
    # 莉奈娅 / 菈乌玛 / 玛拉妮 / 卡齐娜
    "莉奈娅": "莉奈娅", "linney": "莉奈娅",
    "菈乌玛": "菈乌玛", "lauma": "菈乌玛",
    "玛拉妮": "玛拉妮", "mualani": "玛拉妮",
    "卡齐娜": "卡齐娜", "kachina": "卡齐娜",
    # 爱可菲 / 伊法 / 尼可 / 伊涅芙 / 希诺宁 / 恰斯卡 / 塔利雅 / 欧洛伦 / 雅珂达 / 蓝砚 / 丝柯克
    "爱可菲": "爱可菲", "escoffier": "爱可菲", "爱可": "爱可菲",
    "伊法": "伊法", "ifa": "伊法",
    "尼可": "尼可", "ika": "尼可",
    "伊涅芙": "伊涅芙", "ineffa": "伊涅芙",
    "希诺宁": "希诺宁", "chiori": "希诺宁", "citlali": "希诺宁",
    "恰斯卡": "恰斯卡", "chasca": "恰斯卡",
    "塔利雅": "塔利雅", "taliah": "塔利雅", "talia": "塔利雅",
    "欧洛伦": "欧洛伦", "ororon": "欧洛伦",
    "雅珂达": "雅珂达", "iagarto": "雅珂达", "yacolta": "雅珂达",
    "蓝砚": "蓝砚", "lan yan": "蓝砚", "lanyan": "蓝砚",
    "丝柯克": "丝柯克", "skirk": "丝柯克",
    "兹白": "兹白", "zibai": "兹白",
    "奇偶": "奇偶·男性", "嘉明": "嘉明", "gaming": "嘉明",
    "坎蒂丝": "坎蒂丝", "candace": "坎蒂丝",
    "托马": "托马", "thoma": "托马",
    "莱依拉": "莱依拉", "layla": "莱依拉",
    "瑶瑶": "瑶瑶", "yaoyao": "瑶瑶",
    "菲林斯": "菲林斯", "furina de Fontaine"[:20]: "菲林斯",  # safety
    "夏沃蕾": "夏沃蕾", "chevreuse": "夏沃蕾",
    "枫丹": "枫丹",
    "梦见月瑞希": "梦见月瑞希", "梦月": "梦见月瑞希", "月瑞希": "梦见月瑞希",
    "杜林": "杜林", "durin": "杜林",
    "爱诺": "爱诺", "aino": "爱诺",
    "法尔伽": "法尔伽", "fajue": "法尔伽", "faqar": "法尔伽",
    "洛恩": "洛恩", "loan": "洛恩",
    "赛索斯": "赛索斯", "赛索": "赛索斯",
    "赛诺": "赛诺", "cyno": "赛诺",
    "白术": "白术", "baizhu": "白术",
    "芭芭拉": "芭芭拉", "芭芭": "芭芭拉", "barbara": "芭芭拉",
    "珐露珊": "珐露珊", "faruzan": "珐露珊",
    "班尼特": "班尼特", "点赞哥": "班尼特", "bennett": "班尼特",
    "迪奥娜": "迪奥娜", "dio": "迪奥娜", "diona": "迪奥娜",
    "柯莱": "柯莱", "collei": "柯莱",
    "雷泽": "雷泽", "razor": "雷泽",
    "安柏": "安柏", "amber": "安柏",
    "香菱": "香菱", "xiangling": "香菱",
    "行秋": "行秋", "xingqiu": "行秋",
    "北斗": "北斗", "beidou": "北斗",
    "凝光": "凝光", "ningguang": "凝光",
    "七七": "七七", "qiqi": "七七",
    "丽莎": "丽莎", "lisa": "丽莎",
    "凯亚": "凯亚", "kaeya": "凯亚",
    "诺艾尔": "诺艾尔", "诺艾尔": "诺艾尔", "noelle": "诺艾尔",
    "辛焱": "辛焱", "xinyan": "辛焱",
    "重云": "重云", "chongyun": "重云",
    "瑶瑶": "瑶瑶", "yaoyao": "瑶瑶",
    "鹿野院平藏": "鹿野院平藏", "鹿野": "鹿野院平藏", "heizou": "鹿野院平藏",
    "鹿野院": "鹿野院平藏",
    "赛诺": "赛诺", "cyno": "赛诺",
    "夏洛蒂": "夏洛蒂", "charlotte": "夏洛蒂",
    "绮良良": "绮良良", "kuki shinobu": "绮良良",  # err 占位
    "琳妮特": "琳妮特",
    "夏洛蒂": "夏洛蒂",
    "流浪者": "流浪者",
    "玛薇卡": "玛薇卡",
}


_CHAR_NAME_LOOKUP = None


def _build_char_name_lookup():
    """构建小写查询表: 标准名 + 全部别名. 缓存."""
    global _CHAR_NAME_LOOKUP
    if _CHAR_NAME_LOOKUP is not None:
        return _CHAR_NAME_LOOKUP
    valid = set((name or "").lower() for name in AVATAR_ID2NAME.values() if name)
    # miao abbr (简称)
    for v in valid:
        for abbr_v in CHAR_ALIAS_TO_NAME.values():
            pass  # alias 已通过 CHAR_ALIAS_TO_NAME 提供
    table = {}
    # 标准名 + AVATAR_ID2NAME 全部标准角色都进表
    for name in AVATAR_ID2NAME.values():
        if not name:
            continue
        table[name.lower()] = name
    # 别名映射
    for alias, real_name in CHAR_ALIAS_TO_NAME.items():
        if real_name in AVATAR_ID2NAME.values():
            table[alias.lower()] = real_name
    _CHAR_NAME_LOOKUP = table
    return table


def resolve_char_name(query):
    """把玩家输入的角色名/别名解析为 miao 标准角色名 (AVATAR_ID2NAME 值).

    Args:
        query: 玩家输入字符串 (中/英/昵称)

    Returns:
        str 标准名, 若无法解析返回 None
    """
    if not query:
        return None
    q = str(query).strip().lower()
    table = _build_char_name_lookup()
    # 直接匹配
    if q in table:
        return table[q]
    # 去除常见后缀 (面板/详情)
    for suffix in ("面板", "详情", "查询", "查"):
        if q.endswith(suffix):
            q2 = q[: -len(suffix)].strip()
            if q2 in table:
                return table[q2]
    return None


def list_char_aliases():
    """输出常用别名 (调试用)."""
    return sorted(CHAR_ALIAS_TO_NAME.items())



def char_meta(name):
    """角色 data.json 内容 (elem/baseAttr/talentId/weapon/abbr)."""
    import json
    dp = os.path.join(MIAO_RES, "meta-gs", "character", name, "data.json")
    if not os.path.isfile(dp):
        return {}
    try:
        with open(dp, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def weapon_meta(name):
    """武器 data.json (star/attr)."""
    import json
    base = os.path.join(MIAO_RES, "meta-gs", "weapon")
    if not os.path.isdir(base):
        return {}
    for wtype in sorted(os.listdir(base)):
        dp = os.path.join(base, wtype, name, "data.json")
        if os.path.isfile(dp):
            try:
                with open(dp, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
    return {}


def weapon_icon_rel(name):
    """武器图标相对 _res_path 路径 (meta-gs/weapon/<type>/<name>/icon.webp)."""
    base = os.path.join(MIAO_RES, "meta-gs", "weapon")
    if not os.path.isdir(base):
        return ""
    for wtype in sorted(os.listdir(base)):
        p = os.path.join(base, wtype, name, "icon.webp")
        if os.path.isfile(p):
            return "meta-gs/weapon/%s/%s/icon.webp" % (wtype, name)
    return ""


def char_icon_rel(name, key, weapon_type=None, talent_cons=None):
    """天赋图标相对路径 (对齐 miao CharImg.js:119-122 CharImg.getImgs).

    imgs.a 永远 = /common/item/atk-{weaponType}.webp (按武器类型, 所有角色共用)
    imgs.e/q = talentCons[key] > 0 -> icons/cons-{talentCons[key]}.webp;
               否则 icons/talent-{key}.webp (部分角色才有, 不存在时返空串)
    """
    if not name:
        return ""
    if key == "a":
        # 普攻图标按武器类型, miao CharImg.js:119
        wt = weapon_type or _read_char_field(name, "weapon") or "sword"
        path = f"common/item/atk-{wt}.webp"
        full = os.path.join(MIAO_RES, path)
        return path if os.path.isfile(full) else ""
    if key in ("e", "q"):
        tc = talent_cons if isinstance(talent_cons, dict) else (_read_char_field(name, "talentCons") or {})
        cons_n = (tc or {}).get(key, 0) * 1
        if cons_n > 0:
            path = f"meta-gs/character/{name}/icons/cons-{cons_n}.webp"
            full = os.path.join(MIAO_RES, path)
            if os.path.isfile(full):
                return path
        # 兜底: 角色专属 icons/talent-{e/q}.webp (仅少数角色有)
        path = f"meta-gs/character/{name}/icons/talent-{key}.webp"
        full = os.path.join(MIAO_RES, path)
        return path if os.path.isfile(full) else ""
    return ""


def char_cons_icon_rel(name, n):
    p = os.path.join(MIAO_RES, "meta-gs", "character", name, "icons", "cons-%d.webp" % n)
    return "meta-gs/character/%s/icons/cons-%d.webp" % (name, n) if os.path.isfile(p) else ""


def char_splash_rel(name):
    """角色立绘相对路径 (character-img/<name>/01.jpg)."""
    p = os.path.join(MIAO_RES, "character-img", name, "01.jpg")
    return "character-img/%s/01.jpg" % name if os.path.isfile(p) else ""


def char_face_rel(name):
    """角色头像 (meta-gs/character/<name>/imgs/face.webp, 用于面板列表)."""
    if not name:
        return ""
    p = os.path.join(MIAO_RES, "meta-gs", "character", name, "imgs", "face.webp")
    return "meta-gs/character/%s/imgs/face.webp" % name if os.path.isfile(p) else ""


def char_qface_rel(name):
    """q 版头像 (imgs/face-q.webp, 缺失时回退 face)."""
    if not name:
        return ""
    p1 = os.path.join(MIAO_RES, "meta-gs", "character", name, "imgs", "face-q.webp")
    if os.path.isfile(p1):
        return "meta-gs/character/%s/imgs/face-q.webp" % name
    return char_face_rel(name) or ""


def char_gacha_rel(name):
    """抽卡卡面 (imgs/gacha.webp, 缺失回退 splash)."""
    if not name:
        return ""
    p = os.path.join(MIAO_RES, "meta-gs", "character", name, "imgs", "gacha.webp")
    if os.path.isfile(p):
        return "meta-gs/character/%s/imgs/gacha.webp" % name
    return char_splash_rel(name) or ""


def char_banner_rel(name):
    """角色 banner 图 (imgs/banner.webp, 用于面板列表头背景)."""
    if not name:
        return ""
    p = os.path.join(MIAO_RES, "meta-gs", "character", name, "imgs", "banner.webp")
    return "meta-gs/character/%s/imgs/banner.webp" % name if os.path.isfile(p) else ""


def char_abbr(name):
    """角色简称 (data.json 顶层 abbr, 缺失回退 name)."""
    if not name:
        return ""
    return _read_char_field(name, "abbr") or name


def char_elem_name(name):
    """角色元素中文 (data.json 顶层 elem, 例 '火'). 缺失返空串."""
    return _read_char_field(name, "elem") or ""


def char_star(name):
    """角色星级 (data.json 顶层 star, 4/5). 缺失返 5."""
    s = _read_char_field(name, "star") or 0
    return s if s in (4, 5) else 5


# 角色 data.json 字段读缓存 ({name: {field: value}})
_CHAR_FIELD_CACHE = {}


def _read_char_field(name, field):
    """读 meta-gs/character/<name>/data.json 顶层字段 (weapon/talentCons 等). 结果缓存."""
    if not name:
        return None
    if name not in _CHAR_FIELD_CACHE:
        p = os.path.join(MIAO_RES, "meta-gs", "character", name, "data.json")
        try:
            with open(p, "r", encoding="utf-8") as f:
                _CHAR_FIELD_CACHE[name] = json.load(f)
        except (OSError, ValueError):
            _CHAR_FIELD_CACHE[name] = {}
    return _CHAR_FIELD_CACHE[name].get(field)


def artifact_icon_rel(set_name, slot_idx):
    """圣遗物图标相对路径: meta-gs/artifact/imgs/<set>/<slot+1>.webp"""
    if not set_name or set_name not in SET_DIRS:
        return ""
    p = os.path.join(MIAO_RES, "meta-gs", "artifact", "imgs", set_name, "%d.webp" % (slot_idx + 1))
    return "meta-gs/artifact/imgs/%s/%d.webp" % (set_name, slot_idx + 1) if os.path.isfile(p) else ""


# ============================================================================
# 兼容 plugins/genshin.py 旧引用 (原 lib.genshin_panel.maps 符号)
# ============================================================================

REGION_MAP = {
    "cn_gf01": "天空岛", "cn_gf02": "世界树", "cn_qd01": "天空岛(QD)",
    "cn_qd02": "世界树(QD)", "os_usa": "美服", "os_euro": "欧服",
    "os_asia": "亚服", "os_cht": "台服",
}

PIECE_NAMES = ["生之花", "死之羽", "时之沙", "空之杯", "理之冠"]

# Enka fightProp 编号 -> 属性中文名 (展示用)
FIGHT_PROP = {
    "FIGHT_PROP_HP": "生命值", "FIGHT_PROP_HP_PERCENT": "生命值%",
    "FIGHT_PROP_ATTACK": "攻击力", "FIGHT_PROP_ATTACK_PERCENT": "攻击力%",
    "FIGHT_PROP_DEFENSE": "防御力", "FIGHT_PROP_DEFENSE_PERCENT": "防御力%",
    "FIGHT_PROP_ELEMENT_MASTERY": "元素精通",
    "FIGHT_PROP_CHARGE_EFFICIENCY": "元素充能",
    "FIGHT_PROP_CRITICAL": "暴击率", "FIGHT_PROP_CRITICAL_HURT": "暴击伤害",
    "FIGHT_PROP_HEAL_ADD": "治疗加成", "FIGHT_PROP_HEALED_ADD": "受治疗加成",
    "FIGHT_PROP_PHYSICAL_ADD_HURT": "物理伤害加成",
    "FIGHT_PROP_FIRE_ADD_HURT": "火元素伤害加成",
    "FIGHT_PROP_WATER_ADD_HURT": "水元素伤害加成",
    "FIGHT_PROP_GRASS_ADD_HURT": "草元素伤害加成",
    "FIGHT_PROP_ELEC_ADD_HURT": "雷元素伤害加成",
    "FIGHT_PROP_WIND_ADD_HURT": "风元素伤害加成",
    "FIGHT_PROP_ICE_ADD_HURT": "冰元素伤害加成",
    "FIGHT_PROP_ROCK_ADD_HURT": "岩元素伤害加成",
}

_PERCENT_PROPS = {
    "FIGHT_PROP_HP_PERCENT", "FIGHT_PROP_ATTACK_PERCENT", "FIGHT_PROP_DEFENSE_PERCENT",
    "FIGHT_PROP_CHARGE_EFFICIENCY",
    "FIGHT_PROP_CRITICAL", "FIGHT_PROP_CRITICAL_HURT",
    "FIGHT_PROP_HEAL_ADD", "FIGHT_PROP_HEALED_ADD",
    "FIGHT_PROP_PHYSICAL_ADD_HURT", "FIGHT_PROP_FIRE_ADD_HURT",
    "FIGHT_PROP_WATER_ADD_HURT", "FIGHT_PROP_GRASS_ADD_HURT",
    "FIGHT_PROP_ELEC_ADD_HURT", "FIGHT_PROP_WIND_ADD_HURT",
    "FIGHT_PROP_ICE_ADD_HURT", "FIGHT_PROP_ROCK_ADD_HURT",
}


def _fmt_stat(prop_id: str, value):
    """Enka statValue (0.466) -> 展示串 (46.6% / 4,779)."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return "0"
    if prop_id in _PERCENT_PROPS:
        return "{:.1f}%".format(f * 100)
    return "{:,.0f}".format(round(f))


def _weapon_name(item_id):
    """Enka 武器 itemId -> 中文名."""
    return WEAPON_ID2NAME.get(str(item_id), "武器#%s" % item_id)


def _set_name(set_id):
    """Enka 圣遗物 setId -> 套装中文名."""
    name = set_name_from_id(set_id)
    return name or ("圣遗物#%s" % set_id if set_id else "圣遗物")
