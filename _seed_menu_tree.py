"""一次性脚本：生成 data/menu_tree.yaml（默认菜单树 / "以前的方式"）。

自包含：不依赖项目模块；内置完整默认树 + 极简 YAML 序列化。
运行：python d:\\小流萤bot\\_seed_menu_tree.py
"""
import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "menu_tree.yaml")


# ============================================================
# 极简 YAML dump（与 modules/feature_menu.py 的 _mini_yaml_dump 一致）
# ============================================================
def _yaml_scalar(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if v is None:
        return "null"
    s = str(v)
    if any(c in s for c in [":", "#", "{", "}", "[", "]", ",", "&", "*", "!", "|", ">", "'", '"', "%", "@", "`"]):
        s = '"' + s.replace('"', '\\"') + '"'
    return s


def _mini_yaml_dump(data, indent=0):
    pad = "  " * indent
    lines = []
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
                inline = ", ".join(f"{kk}: {_yaml_scalar(vv)}" for kk, vv in item.items())
                lines.append(f"{pad}- {{{inline}}}")
            elif isinstance(item, list):
                lines.append(f"{pad}-")
                lines.append(_mini_yaml_dump(item, indent + 1))
            else:
                lines.append(f"{pad}- {_yaml_scalar(item)}")
    return "\n".join(lines) + ("\n" if lines else "")


# ============================================================
# 默认树（与 modules/feature_menu.py _build_default_tree 等价）
# ============================================================
def _sub_default(title, rows):
    out_rows = []
    for row in rows:
        out_row = []
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
    return {"title": title, "buttons": out_rows, "children": {}}


TREE = {
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
                {"label": "📝 签到",   "data": "签到菜单", "show_if": "checkin_on"},
                {"label": "🎬 视频",   "data": "视频菜单", "show_if": "video_on"},
                {"label": "🎵 音乐",   "data": "音乐菜单", "show_if": "music_on"},
                {"label": "🖼️ 图片",   "data": "图片菜单", "show_if": "image_on"},
            ],
            [
                {"label": "🎮 娱乐",   "data": "娱乐菜单", "show_if": "game_on"},
                {"label": "🛠 工具",   "data": "工具菜单", "show_if": "tools_on"},
                {"label": "📖 小说",   "data": "小说菜单", "show_if": "novel_on"},
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


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    body = _mini_yaml_dump(TREE)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("# 小流萤 bot · 交互菜单树配置（任意层级）\n")
        f.write("# 数据结构：root = 主菜单；root.children = 一级子菜单；每个子菜单可再嵌套 children = 二级子菜单；以此类推\n")
        f.write("# 按钮字段：label（显示名）/ data（点击后机器人收到的指令）/ enter（true/false）/ required（外置插件 key 列表，null=不限）/ show_if（条件显示，主菜单按钮用）\n")
        f.write("# 修改后 bot 会自动重读（hot reload），无需重启\n\n")
        f.write(body)
    print("已写入:", OUT)
    print("主菜单标题:", TREE["root"]["title"])
    print("主菜单按钮行数:", len(TREE["root"]["buttons"]))
    print("子菜单数量:", len(TREE["root"]["children"]))
    print("子菜单列表:", list(TREE["root"]["children"].keys()))


if __name__ == "__main__":
    main()
