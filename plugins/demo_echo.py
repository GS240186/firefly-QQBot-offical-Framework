# -*- coding: utf-8 -*-
"""
示例外置插件：回声（demo_echo）

这是「外置插件」的模板与演示。把它放在 plugins/ 目录下即可被自动加载：
- 无需重启 bot —— 热加载线程每 3 秒检测一次文件变更并重新注册；
- 也可在控制台「功能配置 → 插件管理」点「🔄 热加载」立即重新加载。

统一契约（详见 modules/plugin_registry.py）
------------------------------------------
- 模块级 PLUGIN dict 描述元信息：key / name / priority / handle / description。
- handle(ctx) 是统一分发入口：
    * 返回 True  表示本插件已处理这条消息，分发链就此终止；
    * 返回 False 表示不处理，继续往后走（AI 兜底等）。
- 通过 ctx.reply(text) 便捷回复；ctx 携带的完整字段见 PluginContext。

玩法：在群里或私聊发送「echo 任意内容」，机器人会原样回显；只发「echo」会提示用法。
（仅作演示，生产环境如不需要可直接删除本文件，或把触发词改掉。）
"""

PLUGIN = {
    "key": "demo_echo",
    "name": "回声插件",
    # 外置插件默认排在最后（数字越大越靠后）；如需提前，改小即可。
    "priority": 500,
    "description": "示例外置插件：发送「echo 内容」原样回显",
    "category": "test",
}

_TRIGGER = "echo"


async def handle(ctx) -> bool:
    """统一分发入口。返回 True 表示已处理，False 表示放行。"""
    content = (ctx.content or "").strip()
    # 触发词：单独 "echo" 或 "echo ..." 都算命中（用于提示 / 回显）
    if content != _TRIGGER and not content.startswith(_TRIGGER + " "):
        return False

    payload = content[len(_TRIGGER):].strip()
    if not payload:
        await ctx.reply("请在 echo 后输入要回显的内容，例如：echo 你好")
        return True

    await ctx.reply("回声：" + payload)
    return True
