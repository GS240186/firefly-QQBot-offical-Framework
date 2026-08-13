# -*- coding: utf-8 -*-
"""
示例外置插件：Roll 骰子（roll）

发送「roll」或「roll 100」随机抽一个 1~N 的整数（默认上限 100）。
放在 plugins/ 下即被自动加载，支持热加载（不重启 bot）。
删除本文件或点控制台「插件管理 → 热加载」即可停用。
"""

import random

PLUGIN = {
    "key": "roll",
    "name": "Roll 骰子",
    "priority": 500,
    "description": "发送「roll 100」随机抽 1~N 的整数（默认 100）",
    "category": "test",
}

_TRIGGER = "roll"


async def handle(ctx) -> bool:
    """统一分发入口。返回 True 表示已处理，False 表示放行。"""
    content = (ctx.content or "").strip()
    if content != _TRIGGER and not content.startswith(_TRIGGER + " "):
        return False
    arg = content[len(_TRIGGER):].strip()
    try:
        n = int(arg) if arg else 100
    except ValueError:
        n = 100
    if n < 1:
        n = 100
    await ctx.reply("🎲 你 roll 出了 %d（1~%d）" % (random.randint(1, n), n))
    return True
