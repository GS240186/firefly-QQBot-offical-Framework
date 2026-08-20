# -*- coding: utf-8 -*-
"""
棋类（五子棋 / 中国象棋）运行时会话管理（供 games.py 复用）

设计目标（对应群聊/私聊棋类功能逻辑优化）：
1. 每群/私聊可同时存在多局相互独立的棋局，每局有唯一编号（方便用户区分）。
2. 二人对战只接受对应两个人的指令（路由由 games.py 按 players 过滤）。
3. 2 分钟超时：某局任意一方未进行操作（落子/认输等）则主动回复
   「xx 编号N 超时已自动结束～」并清理该局。
4. 群聊回复时由 games.py 负责 @ 对应用户。

说明：棋局棋盘/玩家等数据仍持久化在 GOMOKU_DATA_FILE / XIANGQI_DATA_FILE
（改为 group -> {game_id: game} 嵌套结构）；本模块仅负责内存中的
超时计时器与编号元数据，无法序列化进 JSON。
"""

import asyncio
import time

from modules.common import (
    send_text,
    send_group_markdown,
    logger,
    ChatScene,
)

# (chat_id, game_type, game_id) -> 计时元数据
#   ts    : 最近活动时间戳
#   task  : 超时等待任务
#   api   : botpy client
#   scene : ChatScene
#   owner : 发起者 openid（群聊 @ 用）
#   label : 棋类展示名（五子棋 / 中国象棋）
_REG = {}
_TIMEOUT = 120  # 秒


def _key(chat_id, game_type, game_id):
    return (chat_id, game_type, game_id)


def chess_arm(chat_id, game_type, game_id, api, scene, owner, label, on_timeout=None):
    """登记/重置某局超时计时器。

    on_timeout: 可选异步回调，签名 (api, scene, chat_id, game_type, game_id, owner, label)，
                超时触发时（发送超时消息后）调用，用于把文件中的棋局置为 ended。
    """
    key = _key(chat_id, game_type, game_id)
    old = _REG.get(key)
    if old and old.get("task"):
        try:
            old["task"].cancel()
        except Exception:
            pass
    _REG[key] = {
        "ts": time.time(),
        "task": None,
        "api": api,
        "scene": scene,
        "owner": owner,
        "label": label,
        "on_timeout": on_timeout,
    }
    try:
        loop = asyncio.get_event_loop()
        _REG[key]["task"] = loop.create_task(_timeout(chat_id, game_type, game_id))
    except Exception as e:
        logger.error("[CHESS] 创建超时任务失败: %s" % e)


def chess_touch(chat_id, game_type, game_id):
    """重置某局活动时间（落子/认输等交互时调用）。"""
    e = _REG.get(_key(chat_id, game_type, game_id))
    if e:
        e["ts"] = time.time()


def chess_cancel(chat_id, game_type, game_id):
    """取消某局超时计时并移除元数据（棋局结束时调用）。"""
    e = _REG.pop(_key(chat_id, game_type, game_id), None)
    if e and e.get("task"):
        try:
            e["task"].cancel()
        except Exception:
            pass


async def _timeout(chat_id, game_type, game_id):
    await asyncio.sleep(_TIMEOUT)
    e = _REG.get(_key(chat_id, game_type, game_id))
    if not e:
        return
    # 期间若有互动，ts 会被刷新，跳过本次超时（已由新计时器接管）
    if time.time() - e.get("ts", 0) < _TIMEOUT:
        return
    api = e.get("api")
    scene = e.get("scene")
    owner = e.get("owner")
    label = e.get("label", "棋局")
    on_timeout = e.get("on_timeout")
    try:
        if scene == ChatScene.GROUP and owner:
            await send_group_markdown(
                api, chat_id,
                "<@!%s> %s 编号%d 超时已自动结束～" % (owner, label, game_id)
            )
        else:
            await send_text(api, scene, chat_id,
                            "%s 编号%d 超时已自动结束～" % (label, game_id))
    except Exception as ex:
        logger.error("[CHESS] 超时消息发送失败: %s" % ex)
    # 文件棋局置为 ended，避免超时后仍被判定为进行中
    if on_timeout:
        try:
            await on_timeout(api, scene, chat_id, game_type, game_id, owner, label)
        except Exception as ex:
            logger.error("[CHESS] 超时回调失败: %s" % ex)
    _REG.pop(_key(chat_id, game_type, game_id), None)
