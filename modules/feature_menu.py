"""
交互菜单（用户输入"帮助"看到的卡片 + 任意层级子菜单）

- 数据结构统一为 menu_tree（树形）：
    {
      "version": 2,
      "root": {
        "key": "__root__",
        "title": "",
        "buttons": [...],          # 顶层（"帮助"主菜单）按钮行
        "links": [...],            # 顶部信息/banner/yiyan 等
        "children": {              # 一级子菜单（"签到菜单"/"视频菜单"/...）
          "签到菜单": {
            "title": "📝 签到系统",
            "buttons": [...],
            "children": {
              "签到子菜单": { ... }    # 二级子菜单（任意层级都可嵌套）
            }
          },
          ...
        }
      }
    }

- 默认配置在 DEFAULT_TREE（首次启动 / 重置时使用）
- 用户自定义配置存到 data/menu_tree.yaml
- 提供 load_tree() / save_tree() / reset_tree() / build_keyboard()
- 支持条件显示：xxx_on / is_group / any_plugin:xx,yy / feedback_enabled / experience_group_enabled
- 支持变量引用：${feedback.form_url} / ${experience_group.url}
- 支持 required：button.required = ["plugin_key", ...]，要求外置插件至少一个开启才显示
- hot reload：每次 load_tree() 时检测文件 mtime，自动重读

向下兼容：
- 旧 submenus.yaml（14 个二级菜单平铺）会在首次读取时自动迁移到 menu_tree.root.children。
"""

import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

# 配置文件路径（项目根目录下 data/）
_CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
)
_TREE_FILE = os.path.join(_CONFIG_DIR, "menu_tree.yaml")
_LEGACY_FILE = os.path.join(_CONFIG_DIR, "submenus.yaml")
_FEATURE_MENU_FILE = os.path.join(_CONFIG_DIR, "feature_menu.yaml")


# ============================================================
# 默认树（顶层 = 主菜单；一级子菜单 = 原 14 个二级菜单）
# ============================================================
def _build_default_tree() -> Dict[str, Any]:
    return {
        "version": 2,
        "root": {
            "key": "__root__",
            "banner": "https://i.ibb.co/bjzNps00/P-2026-0805-025230.png",
            "title": "小流萤功能菜单",
            "intro": ["飞萤扑火，向死而生。我为自我而战，直至一切燃烧殆尽。"],
            "yiyan": {
                "enabled": True,
                "format": "## {hitokoto}  ——{from_who}《{from}》",
            },
            "buttons": [
                [
                    {"label": "📝 签到",   "data": "签到菜单",     "show_if": "checkin_on"},
                    {"label": "🎬 视频",   "data": "视频菜单",     "show_if": "video_on"},
                    {"label": "🎵 音乐",   "data": "音乐菜单",     "show_if": "music_on"},
                    {"label": "🖼️ 图片",   "data": "图片菜单",     "show_if": "image_on"},
                ],
                [
                    {"label": "🎮 娱乐",   "data": "娱乐菜单",     "show_if": "game_on"},
                    {"label": "🛠 工具",   "data": "工具菜单",     "show_if": "tools_on"},
                    {"label": "📖 小说",   "data": "小说菜单",     "show_if": "novel_on"},
                ],
                [
                    {"label": "📚 学习",      "data": "学习菜单",     "show_if": "study_on"},
                    {"label": "⚙️ 群管",      "data": "群管菜单",     "show_if": "group_admin_on AND is_group"},
                    {"label": "🎮 游戏工具",  "data": "游戏工具菜单", "show_if": "any_plugin:genshin_miao,genshin,starrail,ww_gacha"},
                ],
            ],
            "links": [
                {"label": "📝 反馈",          "url": "${feedback.form_url}",        "show_if": "feedback_enabled"},
                {"label": "🏠 加入小流萤体验群", "url": "${experience_group.url}",   "show_if": "experience_group_enabled"},
            ],
            "children": {
                "签到菜单": _sub_default("📝 签到系统", [
                    [["📝 每日签到", "签到"], ["🏆 签到排名", "签到排名"], ["🎰 积分抽奖", "抽奖"]],
                    [["📋 签到查询", "签到查询"], ["🔙 返回主菜单", "返回主菜单"]],
                ]),
                "视频菜单": _sub_default("🎬 视频系统", [
                    [["帅哥视频", "帅哥视频"], ["风景视频", "风景视频"], ["变装视频", "变装视频"], ["cos视频", "cos视频"], ["漫剪视频", "漫剪视频"]],
                    [["游戏视频", "游戏视频"], ["🔙 返回主菜单", "返回主菜单"]],
                ]),
                "音乐菜单": _sub_default("🎵 音乐系统", [
                    [["🎵 随机音乐", "随机音乐"], ["🔀 切换音源", "音源选择"], ["🎤 点歌", "点歌 ", False]],
                    [["🔙 返回主菜单", "返回主菜单"]],
                ]),
                "娱乐菜单": _sub_default("🎮 娱乐系统\n💡 棋类对战 · 抽签占卜 · 运势查询 · 趣味问答", [
                    [["🎮 五子棋", "五子棋"], ["🐉 中国象棋", "象棋"], ["🧩 猜成语", "猜成语"]],
                    [["🎲 观音灵签", "求签"], ["🃏 塔罗牌", "塔罗牌"], ["🔮 答案之书", "答案之书 ", False]],
                    [["✨ 今日运势", "运势 ", False], ["💕 今日老婆", "今日老婆"], ["🧠 脑筋急转弯", "脑筋急转弯"], ["🎭 猜谜语", "猜谜语"]],
                    [["🔙 返回主菜单", "返回主菜单"]],
                ]),
                "工具菜单": _sub_default("🛠 工具系统\n💡 绑QQ/绑群号 可在控制台显示真实头像资料", [
                    [["🎬 视频解析", "视频解析"], ["🌤 天气查询", "天气 ", False], ["🎮 王者信息", "王者 ", False]],
                    [["🏥 疾病信息", "疾病信息"], ["🗑️ 垃圾分类", "垃圾分类"], ["🔤 单词详解", "单词 ", False]],
                    [["🧭 导航规划", "导航"], ["🏞️ 旅游查询", "旅游"]],
                    [["👤 我的信息", "我的信息"], ["🔗 绑QQ号", "绑QQ ", False]],
                    [["🔙 返回主菜单", "返回主菜单"]],
                ]),
                "群管菜单": _sub_default(
                    "⚙️ 群管系统\n"
                    "💡 违禁词：添加/删除需管理员（列表由控制台管理，不在群内展示）；命中违禁词后按各群设置自动禁言触发用户\n"
                    "🔇 禁言管理：每群独立禁言时长，违禁词触发后自动禁言该用户（需群主/管理员）\n"
                    "⚠️ 使用群管功能需：① 将机器人设为群管理员 ② 为机器人开启「主动发言权限」（否则撤回/禁言/踢人等主动操作无法执行） · 整点报时菜单（开关/间隔/时段）需群主/管理员",
                    [
                        [["🔇 禁言管理", "禁言管理"]],
                        [["🚫 违禁词", "违禁词"]],
                        [["⏰ 整点报时", "整点报时"]],
                        [["📥 入群通知", "入群通知"]],
                        [["🔙 返回主菜单", "返回主菜单"]],
                    ],
                ),
                "学习菜单": _sub_default("📚 学习系统\n💡 知识问答 · 驾考学习 · 小学数学 · 古诗文查询", [
                    [["❓ 知识问答", "知识问答"], ["🚗 驾考学习", "驾考学习"]],
                    [["🔢 小学数学", "小学数学"], ["📜 古诗文", "古诗文"]],
                    [["🔙 返回主菜单", "返回主菜单"]],
                ]),
                "小说菜单": _sub_default("📚 在线小说\n💡 发送「小说 书名」即可搜索阅读，例如「小说 斗破苍穹」；也支持「看 书名 / 读 书名」", [
                    [["🔥 斗破苍穹", "小说 斗破苍穹"], ["🔥 大奉打更人", "小说 大奉打更人"]],
                    [["🔥 诡秘之主", "小说 诡秘之主"], ["🎲 随机推荐", "小说 随机推荐"]],
                    [["❌ 退出阅读", "退出小说"]],
                    [["🔙 返回主菜单", "返回主菜单"]],
                ]),
                "图片菜单": _sub_default("🖼️ 图片系统\n💡 随机高清美图：二次元 / 原神 / 风景 / 小姐姐\n💡 还可发送「角色图库」按角色名检索专属相册", [
                    [["🎨 二次元", "二次元"], ["🏞️ 风景", "风景"], ["🌄 随机壁纸", "随机壁纸"]],
                    [["🐉 原神cos", "原神cos"], ["⚔️ 原神", "原神"], ["💃 小姐姐", "小姐姐"]],
                    [["🌟 角色图库", "角色图库"]],
                    [["🔙 返回主菜单", "返回主菜单"]],
                ]),
                "游戏工具菜单": _sub_default("🎮 游戏工具\n💡 选择游戏：原神 / 崩铁 / 鸣潮", [
                    [
                        ["✨ 原神菜单", "原神菜单", True, ["genshin_miao", "genshin"]],
                        ["⚡ 崩铁菜单", "崩铁菜单", True, ["starrail"]],
                        ["🌊 鸣潮抽卡", "鸣潮菜单", True, ["ww_gacha"]],
                    ],
                    [["🔙 返回主菜单", "返回主菜单"]],
                ]),
                "鸣潮菜单": _sub_default("🌊 鸣潮模拟抽卡\n💡 点击直接发送指令，仅供娱乐", [
                    [
                        ["🌊 鸣潮十连", "鸣潮十连", True, ["ww_gacha"]],
                        ["🌊 鸣潮单抽", "鸣潮单抽", True, ["ww_gacha"]],
                        ["🌊 鸣潮卡池", "鸣潮卡池", True, ["ww_gacha"]],
                    ],
                    [
                        ["🌊 鸣潮状态", "鸣潮状态", True, ["ww_gacha"]],
                        ["🌊 鸣潮重置", "鸣潮重置", True, ["ww_gacha"]],
                        ["🌊 鸣潮帮助", "鸣潮帮助", True, ["ww_gacha"]],
                    ],
                    [["🔙 返回主菜单", "返回主菜单"]],
                ]),
                "原神菜单": _sub_default("✨ 原神系统\n💡 所有指令需以 # 开头\n💡 提示：先 #🔗 绑定uid 再 #🔄 更新面板", [
                    [
                        ["#🔗 绑定uid", "#原神绑定uid", False, ["genshin_miao", "genshin"]],
                        ["#🔄 更新面板", "#更新面板", True, ["genshin_miao", "genshin"]],
                        ["#🔍 角色面板", "#原神 ", False, ["genshin_miao", "genshin"]],
                    ],
                    [
                        ["#🔎 查uid", "#原神uid ", False, ["genshin_miao", "genshin"]],
                        ["#🔀 切换api", "#切换api", True, ["genshin_miao", "genshin"]],
                        ["#💯 圣遗物评分", "#圣遗物评分", True, ["genshin_miao", "genshin"]],
                    ],
                    [
                        ["#🗡 伤害计算", "#伤害计算", True, ["genshin_miao", "genshin"]],
                        ["#🎲 十连", "#十连", True, ["genshin_miao", "genshin"]],
                        ["#📖 功能说明", "#原神帮助", True, ["genshin_miao", "genshin"]],
                    ],
                    [["🔙 返回主菜单", "返回主菜单"]],
                ]),
                "崩铁菜单": _sub_default("⚡ 崩坏：星穹铁道\n💡 所有指令需以 * 开头\n💡 提示：先 *🔗 绑定uid 再 *🔄 更新面板", [
                    [
                        ["*🔗 绑定uid", "*星铁绑定uid", False, ["starrail"]],
                        ["*📋 uid列表", "*星铁uid列表", True, ["starrail"]],
                        ["*🔄 更新面板", "*更新面板", True, ["starrail"]],
                    ],
                    [
                        ["*🔀 切换账户", "*切换账户", False, ["starrail"]],
                        ["*🗑 删除账户", "*星铁删除账户", False, ["starrail"]],
                        ["*🔍 查角色", "*星铁 ", False, ["starrail"]],
                    ],
                    [["🔙 返回主菜单", "返回主菜单"]],
                ]),
            },
        },
    }


def _sub_default(title: str, rows: List[List[List[Any]]]) -> Dict[str, Any]:
    """把简写 rows 转成标准结构。每项: [label, data, enter=True, required=None]。"""
    out_rows: List[List[Dict[str, Any]]] = []
    for row in rows:
        out_row: List[Dict[str, Any]] = []
        for item in row:
            label = item[0]
            data = item[1] if len(item) > 1 else label
            enter = item[2] if len(item) > 2 else True
            required = item[3] if len(item) > 3 else None
            out_row.append({
                "label": label,
                "data": data,
                "enter": bool(enter),
                "required": required,
            })
        out_rows.append(out_row)
    return {
        "title": title,
        "buttons": out_rows,
        "children": {},
    }


# ============================================================
# 内存缓存
# ============================================================
_LOCK = threading.RLock()
_cached_tree: Optional[Dict[str, Any]] = None
_cached_mtime: float = 0.0


# ============================================================
# 极简 YAML 解析
# ============================================================
def _mini_yaml_load(text: str) -> Any:
    """极简 YAML 解析：仅支持 map / list / string / int / bool / null。"""
    lines = text.splitlines()
    return _parse_block([_strip_indent(ln) for ln in lines if ln.strip() and not ln.lstrip().startswith("#")])


def _strip_indent(line: str) -> str:
    return line[2:] if line.startswith("  ") else (line[1:] if line.startswith("\t") else line)


def _parse_block(lines: List[str]) -> Any:
    if not lines:
        return None
    first = lines[0].lstrip()
    # 单行场景优先判定（避免误走 map 分支）
    if len(lines) == 1:
        s = lines[0].strip()
        # 1) list 元素（"- xxx"）→ 走 list 分支
        if s.startswith("- "):
            return _parse_block_item(s[2:])
        # 2) inline dict（"{k: v, k: v}"）→ 走 inline dict 分支
        if s.startswith("{") and s.endswith("}"):
            return _parse_block_item(s)
        # 3) 单行标量（无论是否含 :）→ 直接当 scalar
        return _parse_scalar(s)
    if first.startswith("- "):
        items: List[Any] = []
        cur_lines: List[str] = []
        for ln in lines:
            stripped = ln.lstrip()
            if stripped.startswith("- "):
                if cur_lines:
                    items.append(_parse_block(cur_lines))
                cur_lines = [stripped[2:]]
            else:
                cur_lines.append(ln)
        if cur_lines:
            items.append(_parse_block(cur_lines))
        return [_parse_block_item(x) for x in items]
    out: Dict[str, Any] = {}
    cur_key: Optional[str] = None
    cur_val_lines: List[str] = []
    for ln in lines:
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        if ":" in ln and not ln.lstrip().startswith("-"):
            if cur_key is not None and cur_val_lines:
                out[cur_key] = _parse_block(cur_val_lines)
            k, v = ln.split(":", 1)
            cur_key = k.strip()
            v_strip = v.strip()
            if v_strip:
                # 值在同一行（如 "key: __root__"）→ 立即 flush
                out[cur_key] = _parse_scalar(v_strip)
                cur_key = None
                cur_val_lines = []
            else:
                # 值是嵌套块（如 "root:" "buttons:" "children:"）→ 继续累积后续行
                cur_val_lines = []
        else:
            cur_val_lines.append(ln)
    if cur_key is not None and cur_val_lines:
        out[cur_key] = _parse_block(cur_val_lines)
    return out


def _parse_block_item(item: Any) -> Any:
    if isinstance(item, list):
        return _parse_block(item)
    if isinstance(item, dict):
        return item
    s = item.strip()
    if s.startswith("{") and s.endswith("}"):
        inner = s[1:-1].strip()
        if not inner:
            return {}
        out: Dict[str, Any] = {}
        for part in _split_inline_map(inner):
            if ":" in part:
                k, v = part.split(":", 1)
                out[k.strip()] = _parse_scalar(v.strip())
        return out
    return _parse_scalar(s)


def _split_inline_map(s: str) -> List[str]:
    out: List[str] = []
    depth = 0
    in_quote = False
    quote_char = ""
    last = 0
    i = 0
    while i < len(s):
        ch = s[i]
        if in_quote:
            if ch == quote_char and s[i - 1:i] != "\\":
                in_quote = False
        else:
            if ch in ('"', "'"):
                in_quote = True
                quote_char = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            elif ch == "," and depth == 0:
                out.append(s[last:i])
                last = i + 1
        i += 1
    if last < len(s):
        out.append(s[last:])
    return out


def _parse_scalar(s: str) -> Any:
    s = s.strip()
    if not s:
        return ""
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    if s.lower() in ("true", "yes", "on"):
        return True
    if s.lower() in ("false", "no", "off"):
        return False
    if s.lower() in ("null", "~", ""):
        return None
    try:
        if "." not in s and "e" not in s.lower():
            return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _mini_yaml_dump(data: Any, indent: int = 0) -> str:
    pad = "  " * indent
    lines: List[str] = []
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, dict):
                if not v:
                    lines.append(f"{pad}{k}: {{}}")
                else:
                    lines.append(f"{pad}{k}:")
                    lines.append(_mini_yaml_dump(v, indent + 1))
            elif isinstance(v, list):
                if not v:
                    lines.append(f"{pad}{k}: []")
                else:
                    lines.append(f"{pad}{k}:")
                    lines.append(_mini_yaml_dump(v, indent + 1))
            else:
                lines.append(f"{pad}{k}: {_yaml_scalar(v)}")
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                # 若 dict 中含 list 字段（如 buttons/links/children），用 block 模式而非 inline
                # 否则 inline 模式会把 list 序列化成 "[{...}]" 字符串，再次加载时丢失结构
                if any(isinstance(vv, list) for vv in item.values()):
                    lines.append(f"{pad}-")
                    lines.append(_mini_yaml_dump(item, indent + 1))
                else:
                    inline = ", ".join(
                        f"{kk}: {_yaml_scalar(vv)}" for kk, vv in item.items()
                    )
                    lines.append(f"{pad}- {{{inline}}}")
            elif isinstance(item, list):
                lines.append(f"{pad}-")
                lines.append(_mini_yaml_dump(item, indent + 1))
            else:
                lines.append(f"{pad}- {_yaml_scalar(item)}")
    return "\n".join(lines) + ("\n" if lines else "")


def _yaml_scalar(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if v is None:
        return "null"
    s = str(v)
    # 含特殊字符或非 ASCII（中文/emoji）时强制加引号
    if any(ord(c) > 127 for c in s) or any(c in s for c in [":", "#", "{", "}", "[", "]", ",", "&", "*", "!", "|", ">", "'", '"', "%", "@", "`"]):
        s = '"' + s.replace('"', '\\"') + '"'
    return s


# ============================================================
# 加载/保存（带 mtime 检测 + 文件不存在回退默认）
# ============================================================
def _ensure_default_file():
    global _cached_tree, _cached_mtime
    if not os.path.isfile(_TREE_FILE):
        os.makedirs(_CONFIG_DIR, exist_ok=True)
        default = _build_default_tree()
        with open(_TREE_FILE, "w", encoding="utf-8") as f:
            f.write("# 小流萤 bot · 交互菜单树配置（任意层级）\n")
            f.write("# 数据结构：root = 主菜单；root.children = 一级子菜单；每个子菜单可再嵌套 children = 二级子菜单；以此类推\n")
            f.write("# 按钮字段：label（显示名）/ data（点击后机器人收到的指令）/ enter（true/false）/ required（外置插件 key 列表，null=不限）/ show_if（条件显示，主菜单按钮用）\n")
            f.write("# 修改后 bot 会自动重读（hot reload），无需重启\n\n")
            f.write(_mini_yaml_dump(default))
        _cached_tree = default
        try:
            _cached_mtime = os.path.getmtime(_TREE_FILE)
        except OSError:
            _cached_mtime = 0.0


def _migrate_legacy() -> Optional[Dict[str, Any]]:
    """从旧 submenus.yaml + feature_menu.yaml 迁移到新树结构。"""
    if not os.path.isfile(_LEGACY_FILE):
        return None
    try:
        with open(_LEGACY_FILE, "r", encoding="utf-8") as f:
            legacy_text = f.read()
        legacy = _mini_yaml_load(legacy_text) if legacy_text.strip() else {}
    except Exception:
        legacy = {}

    # 主菜单（旧 feature_menu.yaml）
    banner = "https://i.ibb.co/bjzNps00/P-2026-0805-025230.png"
    title = "小流萤功能菜单"
    intro = ["飞萤扑火，向死而生。我为自我而战，直至一切燃烧殆尽。"]
    yiyan = {"enabled": True, "format": "## {hitokoto}  ——{from_who}《{from}》"}
    main_buttons = [
        [
            {"label": "📝 签到", "data": "签到菜单", "show_if": "checkin_on"},
            {"label": "🎬 视频", "data": "视频菜单", "show_if": "video_on"},
            {"label": "🎵 音乐", "data": "音乐菜单", "show_if": "music_on"},
            {"label": "🖼️ 图片", "data": "图片菜单", "show_if": "image_on"},
        ],
        [
            {"label": "🎮 娱乐", "data": "娱乐菜单", "show_if": "game_on"},
            {"label": "🛠 工具", "data": "工具菜单", "show_if": "tools_on"},
            {"label": "📖 小说", "data": "小说菜单", "show_if": "novel_on"},
        ],
        [
            {"label": "📚 学习", "data": "学习菜单", "show_if": "study_on"},
            {"label": "⚙️ 群管", "data": "群管菜单", "show_if": "group_admin_on AND is_group"},
            {"label": "🎮 游戏工具", "data": "游戏工具菜单", "show_if": "any_plugin:genshin_miao,genshin,starrail,ww_gacha"},
        ],
    ]
    links = [
        {"label": "📝 反馈", "url": "${feedback.form_url}", "show_if": "feedback_enabled"},
        {"label": "🏠 加入小流萤体验群", "url": "${experience_group.url}", "show_if": "experience_group_enabled"},
    ]

    if os.path.isfile(_FEATURE_MENU_FILE):
        try:
            with open(_FEATURE_MENU_FILE, "r", encoding="utf-8") as f:
                fm_text = f.read()
            fm = _mini_yaml_load(fm_text) if fm_text.strip() else {}
            if isinstance(fm, dict):
                if "banner" in fm:
                    banner = fm.get("banner") or banner
                if "title" in fm:
                    title = fm.get("title") or title
                if isinstance(fm.get("intro"), list):
                    intro = list(fm["intro"])
                if isinstance(fm.get("yiyan"), dict):
                    yiyan = dict(fm["yiyan"])
                if isinstance(fm.get("rows"), list):
                    main_buttons = fm["rows"]
                if isinstance(fm.get("links"), list):
                    links = fm["links"]
        except Exception:
            pass

    # 子菜单（旧 submenus.yaml）
    children: Dict[str, Any] = {}
    if isinstance(legacy, dict):
        for k, v in legacy.items():
            if isinstance(v, dict):
                children[k] = {
                    "title": v.get("title", k),
                    "buttons": v.get("buttons", []) or [],
                    "children": {},
                }

    return {
        "version": 2,
        "root": {
            "key": "__root__",
            "banner": banner,
            "title": title,
            "intro": intro,
            "yiyan": yiyan,
            "buttons": main_buttons,
            "links": links,
            "children": children,
        },
    }


def _normalize_node(node: Optional[Dict[str, Any]], default_node: Optional[Dict[str, Any]] = None, is_root: bool = False) -> Dict[str, Any]:
    """归一化节点结构。is_root=True 时保留 banner/intro/yiyan/links 等主菜单特有字段。"""
    out: Dict[str, Any] = {
        "key": (node or {}).get("key", "__root__" if is_root else "__node__"),
        "title": (node or {}).get("title", ""),
        "buttons": (node or {}).get("buttons", []) or [],
    }
    # 顶层 root 保留额外字段（不论 key 值如何）
    if is_root:
        out["banner"] = (node or {}).get("banner", "")
        out["intro"] = (node or {}).get("intro", []) or []
        yiyan = (node or {}).get("yiyan") or {"enabled": True, "format": ""}
        out["yiyan"] = yiyan
        out["links"] = (node or {}).get("links", []) or []
    # 子节点
    children_in = (node or {}).get("children", {}) or {}
    if isinstance(children_in, dict):
        out["children"] = {k: _normalize_node(v) for k, v in children_in.items() if isinstance(v, dict)}
    else:
        out["children"] = {}
    return out


def _normalize_tree(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return _build_default_tree()
    root_in = data.get("root")
    if not isinstance(root_in, dict):
        root_in = {}
    # 通过调用参数显式标记 root，不再依赖 key 值判断
    normalized_root = _normalize_node(root_in, is_root=True)
    normalized_root["key"] = "__root__"
    return {"version": 2, "root": normalized_root}


def load_tree(force: bool = False) -> Dict[str, Any]:
    """读取菜单树配置（带 mtime 缓存）。"""
    global _cached_tree, _cached_mtime
    with _LOCK:
        _ensure_default_file()
        try:
            mtime = os.path.getmtime(_TREE_FILE)
        except OSError:
            mtime = 0
        if (not force
                and _cached_tree is not None
                and abs(mtime - _cached_mtime) < 0.001):
            return _cached_tree
        # 文件不存在 / 解析失败 → 尝试从旧版迁移
        text = ""
        try:
            with open(_TREE_FILE, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception:
            text = ""
        data = _mini_yaml_load(text) if text.strip() else {}
        if not data or "root" not in data:
            migrated = _migrate_legacy()
            if migrated:
                _cached_tree = _normalize_tree(migrated)
            else:
                _cached_tree = _normalize_tree(_build_default_tree())
        else:
            _cached_tree = _normalize_tree(data)
        try:
            _cached_mtime = os.path.getmtime(_TREE_FILE)
        except OSError:
            _cached_mtime = 0.0
        return _cached_tree


def save_tree(tree: Dict[str, Any]) -> Tuple[bool, str]:
    """保存菜单树配置。"""
    global _cached_tree, _cached_mtime
    with _LOCK:
        try:
            os.makedirs(_CONFIG_DIR, exist_ok=True)
            normalized = _normalize_tree(tree)
            with open(_TREE_FILE, "w", encoding="utf-8") as f:
                f.write(_mini_yaml_dump(normalized))
            _cached_tree = normalized
            try:
                _cached_mtime = os.path.getmtime(_TREE_FILE)
            except OSError:
                _cached_mtime = 0.0
            return True, "保存成功"
        except Exception as e:
            return False, f"保存失败: {e}"


def reset_tree() -> Tuple[bool, str]:
    """恢复默认菜单树。"""
    global _cached_tree, _cached_mtime
    with _LOCK:
        try:
            os.makedirs(_CONFIG_DIR, exist_ok=True)
            default = _build_default_tree()
            with open(_TREE_FILE, "w", encoding="utf-8") as f:
                f.write(_mini_yaml_dump(default))
            _cached_tree = _normalize_tree(default)
            try:
                _cached_mtime = os.path.getmtime(_TREE_FILE)
            except OSError:
                _cached_mtime = 0.0
            return True, "已恢复默认"
        except Exception as e:
            return False, f"重置失败: {e}"


# ============================================================
# 节点操作辅助
# ============================================================
def get_node(path: List[str]) -> Optional[Dict[str, Any]]:
    """通过路径获取节点。path=[] → root；path=["签到菜单"] → 一级子节点。"""
    tree = load_tree()
    node = tree.get("root")
    for p in path:
        if not isinstance(node, dict):
            return None
        node = (node.get("children") or {}).get(p)
    return node


def list_all_paths() -> List[List[str]]:
    """返回所有节点路径（含 root 空路径）。"""
    tree = load_tree()
    paths: List[List[str]] = [[]]

    def walk(node: Dict[str, Any], current: List[str]):
        for k, v in (node.get("children") or {}).items():
            child_path = current + [k]
            paths.append(child_path)
            if isinstance(v, dict):
                walk(v, child_path)

    walk(tree.get("root", {}), [])
    return paths


# ============================================================
# 条件求值 / 变量替换
# ============================================================
_VAR_PATTERN = re.compile(r"\$\{([a-zA-Z0-9_.]+)\}")


def _resolve_var(name: str, ctx: Dict[str, Any]) -> str:
    return str(ctx.get(name, ""))


def _replace_vars(text: str, ctx: Dict[str, Any]) -> str:
    return _VAR_PATTERN.sub(lambda m: _resolve_var(m.group(1), ctx), text or "")


def _is_plugin_enabled(plugin_key: str, ctx: Dict[str, Any]) -> bool:
    try:
        from modules import plugin_registry as _pr
        return bool(_pr.is_plugin_enabled(plugin_key))
    except Exception:
        return bool(ctx.get("plugins", {}).get(plugin_key, False))


def _eval_condition(expr: Optional[str], ctx: Dict[str, Any]) -> bool:
    if not expr:
        return True
    expr = expr.strip()
    if " AND " in expr or " OR " in expr:
        if " AND " in expr:
            parts = [p.strip() for p in expr.split(" AND ")]
            return all(_eval_condition(p, ctx) for p in parts)
        if " OR " in expr:
            parts = [p.strip() for p in expr.split(" OR ")]
            return any(_eval_condition(p, ctx) for p in parts)
    if expr.startswith("any_plugin:"):
        keys = [k.strip() for k in expr[len("any_plugin:"):].split(",") if k.strip()]
        return any(_is_plugin_enabled(k, ctx) for k in keys)
    if expr == "is_group":
        return bool(ctx.get("is_group", False))
    if expr.endswith("_on"):
        return bool(ctx.get(expr, False))
    if expr.endswith("_enabled"):
        return bool(ctx.get(expr, False))
    return bool(ctx.get(expr, False))


def _check_required(required: Any) -> bool:
    """按钮 required 检查：None/空 = 始终显示；否则要求列表中任一外置插件启用。"""
    if not required:
        return True
    if isinstance(required, str):
        keys = [k.strip() for k in required.split(",") if k.strip()]
    elif isinstance(required, list):
        keys = [str(k).strip() for k in required if str(k).strip()]
    else:
        return True
    if not keys:
        return True
    for k in keys:
        if _is_plugin_enabled(k, {}):
            return True
    return False


# ============================================================
# 构建 keyboard
# ============================================================
def _make_button_id(prefix: str, idx: int) -> str:
    return f"{prefix}_{int(time.time() * 1000) % 100000}_{idx}"


def _build_buttons_row(buttons: List[Dict[str, Any]], ctx: Dict[str, Any], prefix: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for i, btn in enumerate(buttons or []):
        if not _eval_condition(btn.get("show_if"), ctx):
            continue
        if not _check_required(btn.get("required")):
            continue
        label = _replace_vars(btn.get("label", ""), ctx)
        data = _replace_vars(btn.get("data", ""), ctx)
        if not label or not data:
            continue
        enter = bool(btn.get("enter", True))
        out.append({
            "id": _make_button_id(prefix, i),
            "render_data": {"label": label, "visited_label": label, "style": 0},
            "action": {
                "type": 2,
                "permission": {"type": 2},
                "data": data,
                "enter": enter,
            },
        })
    return out


def build_keyboard(menu: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """根据主菜单配置 + ctx 生成 keyboard JSON。"""
    rows: List[Dict[str, Any]] = []
    # 按钮行
    for i, row in enumerate(menu.get("buttons", []) or []):
        btns = _build_buttons_row(row, ctx, f"btn_menu_{i}")
        if btns:
            rows.append({"buttons": btns})
    # 链接行
    for link in menu.get("links", []) or []:
        if not _eval_condition(link.get("show_if"), ctx):
            continue
        label = _replace_vars(link.get("label", ""), ctx)
        url = _replace_vars(link.get("url", ""), ctx)
        if not label or not url:
            continue
        rows.append({"buttons": [{
            "id": _make_button_id("btn_menu_link", 0),
            "render_data": {"label": label, "visited_label": label, "style": 0},
            "action": {
                "type": 0,
                "permission": {"type": 2},
                "data": url,
                "unsupport_tips": "请更新QQ版本后重试",
            },
        }]})
    return {"content": {"rows": rows}}


def build_submenu_keyboard(
    category: str,
    ctx: Optional[Dict[str, Any]] = None,
    is_group: bool = False,
) -> Dict[str, Any]:
    """通过 category（菜单 key）构建子菜单 keyboard。任意层级都走这个函数。"""
    tree = load_tree()
    node = (tree.get("root", {}).get("children", {}) or {}).get(category)
    if not node:
        return {"content": {"rows": []}}
    rows: List[Dict[str, Any]] = []
    for i, row in enumerate(node.get("buttons", []) or []):
        btns: List[Dict[str, Any]] = []
        for j, btn in enumerate(row or []):
            if not _check_required(btn.get("required")):
                continue
            label = btn.get("label", "")
            data = btn.get("data", "")
            enter = bool(btn.get("enter", True))
            if not label or not data:
                continue
            btns.append({
                "id": _make_button_id(f"btn_sub_{category}_{i}", j),
                "render_data": {"label": label, "visited_label": label, "style": 0},
                "action": {
                    "type": 2,
                    "permission": {"type": 2},
                    "data": data,
                    "enter": enter,
                },
            })
        if btns:
            rows.append({"buttons": btns})
    return {"content": {"rows": rows}}


def build_submenu_text(category: str) -> str:
    tree = load_tree()
    node = (tree.get("root", {}).get("children", {}) or {}).get(category)
    if not node:
        return f"# {category}\n"
    return node.get("title", f"# {category}")


def get_submenu(category: str) -> Optional[Dict[str, Any]]:
    tree = load_tree()
    return (tree.get("root", {}).get("children", {}) or {}).get(category)


# ============================================================
# 向下兼容：旧 API（submenus.yaml / feature_menu.yaml）
# ============================================================
def load_menu(force: bool = False) -> Dict[str, Any]:
    """兼容旧 API。从 root 节点读主菜单字段。"""
    tree = load_tree(force=force)
    root = tree.get("root", {})
    return {
        "banner": root.get("banner", ""),
        "title": root.get("title", ""),
        "intro": root.get("intro", []),
        "yiyan": root.get("yiyan", {}),
        "rows": root.get("buttons", []),
        "links": root.get("links", []),
    }


def save_menu(menu: Dict[str, Any]) -> Tuple[bool, str]:
    """兼容旧 API。保存主菜单字段。"""
    tree = load_tree()
    root = tree.get("root", {})
    root["banner"] = menu.get("banner", root.get("banner", ""))
    root["title"] = menu.get("title", root.get("title", ""))
    root["intro"] = menu.get("intro", root.get("intro", []))
    root["yiyan"] = menu.get("yiyan", root.get("yiyan", {}))
    root["buttons"] = menu.get("rows", root.get("buttons", []))
    root["links"] = menu.get("links", root.get("links", []))
    return save_tree(tree)


def reset_menu() -> Tuple[bool, str]:
    return reset_tree()


def load_submenus(force: bool = False) -> Dict[str, Any]:
    """兼容旧 API。从 root.children 读所有一级子菜单。"""
    tree = load_tree(force=force)
    children = (tree.get("root", {}).get("children", {}) or {})
    out: Dict[str, Any] = {}
    for k, v in children.items():
        out[k] = {
            "title": v.get("title", k),
            "buttons": v.get("buttons", []) or [],
        }
    return out


def save_submenus(data: Dict[str, Any]) -> Tuple[bool, str]:
    """兼容旧 API。只更新一级子菜单。"""
    tree = load_tree()
    root = tree.get("root", {})
    children = root.get("children", {}) or {}
    for k, v in (data or {}).items():
        if not isinstance(v, dict):
            continue
        if k in children and isinstance(children[k], dict):
            children[k]["title"] = v.get("title", children[k].get("title", k))
            children[k]["buttons"] = v.get("buttons", children[k].get("buttons", []))
        else:
            children[k] = {
                "title": v.get("title", k),
                "buttons": v.get("buttons", []),
                "children": {},
            }
    root["children"] = children
    return save_tree(tree)


def reset_submenus() -> Tuple[bool, str]:
    return reset_tree()
