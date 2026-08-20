# -*- coding: utf-8 -*-
"""
趣味问答公共工具（共享给 fun_brainteaser / fun_riddle）

会话管理：key = (chat_id, qtype) -> session
答案匹配：normalize + 宽松包含
提供开题/换题/作答/看答案/结束/超时 等标准动作。

注意：所有消息发送函数（send_text / send_text_with_keyboard / send_group_markdown）
都从 modules.common 借用，避免重复实现。
"""

import asyncio
import logging
import re
import time

from modules.common import (
    ChatScene,
    logger as _logger,
    send_group_markdown as _send_group_markdown,
    send_text as _send_text,
    send_text_with_keyboard as _send_text_with_keyboard,
)

logger = _logger

# 会话：(chat_id, qtype) -> dict
#   owner     : 发起者 openid
#   scene     : ChatScene.GROUP / C2C / CHANNEL
#   api       : botpy client 引用
#   label     : 功能展示名（"脑筋急转弯" / "猜谜语"）
#   data      : 题目数据 {"answer": "..."} 或扩展字段
#   ts        : 最近活动时间戳
#   task      : 超时等待任务
_QA = {}
_QA_TIMEOUT = 120  # 秒

# 群内 @ 模板
def qa_mention(scene, openid):
    if scene == ChatScene.GROUP and openid:
        return "<@!%s> " % openid
    return ""


# ============================================================
#                        文本工具
# ============================================================
def _normalize(s):
    """去前缀（答案: / 答: / 谜底:），strip 空白。"""
    s = (s or "").strip()
    s = re.sub(r"^(答案|答|谜底|正确|正确答案)[:：]\s*", "", s)
    return s.strip()


def _is_correct(user, correct):
    """宽松包含匹配：忽略标点和大小写，只要相等或互相包含。"""
    u = _normalize(user)
    c = _normalize(correct)
    if not u or not c:
        return False
    pat = re.compile(r"[\s，。！？、；：\"\"''（）()\[\]【】]")
    u = pat.sub("", u).lower()
    c = pat.sub("", c).lower()
    if not u or not c:
        return False
    return u == c or c in u or u in c


# ============================================================
#                        会话查询
# ============================================================
def _key(chat_id, qtype):
    return (chat_id, qtype)


def qa_is_active(chat_id, qtype):
    return _key(chat_id, qtype) in _QA


def qa_get(chat_id, qtype):
    return _QA.get(_key(chat_id, qtype))


def qa_owner_openid(chat_id, qtype):
    s = _QA.get(_key(chat_id, qtype))
    return s.get("owner") if s else None


def qa_is_owner(chat_id, qtype, openid):
    s = _QA.get(_key(chat_id, qtype))
    return bool(s) and s.get("owner") == openid


def qa_label(chat_id, qtype):
    s = _QA.get(_key(chat_id, qtype))
    return s.get("label", "") if s else ""


# ============================================================
#                        会话生命周期
# ============================================================
def qa_start(chat_id, qtype, owner, scene, api, label, data):
    key = _key(chat_id, qtype)
    if key in _QA:
        return False
    _QA[key] = {
        "owner": owner,
        "scene": scene,
        "api": api,
        "label": label,
        "data": data or {},
        "ts": time.time(),
        "task": None,
    }
    _qa_arm(chat_id, qtype)
    return True


def qa_continue(chat_id, qtype, data):
    s = _QA.get(_key(chat_id, qtype))
    if not s:
        return False
    s["data"] = data or {}
    s["ts"] = time.time()
    _qa_arm(chat_id, qtype)
    return True


def qa_touch(chat_id, qtype):
    s = _QA.get(_key(chat_id, qtype))
    if s:
        s["ts"] = time.time()
        _qa_arm(chat_id, qtype)


def qa_end(chat_id, qtype):
    key = _key(chat_id, qtype)
    s = _QA.pop(key, None)
    if s and s.get("task"):
        try:
            s["task"].cancel()
        except Exception:
            pass


def _qa_arm(chat_id, qtype):
    """(重置) 启动一个超时任务，_QA_TIMEOUT 秒后若仍未活动则自动结束。"""
    s = _QA.get(_key(chat_id, qtype))
    if not s:
        return
    if s.get("task"):
        try:
            s["task"].cancel()
        except Exception:
            pass
    try:
        loop = asyncio.get_event_loop()
        s["task"] = loop.create_task(_qa_timeout(chat_id, qtype))
    except Exception as e:
        logger.error("[QA] 创建超时任务失败: %s" % e)


async def _qa_timeout(chat_id, qtype):
    await asyncio.sleep(_QA_TIMEOUT)
    s = _QA.get(_key(chat_id, qtype))
    if not s:
        return
    if time.time() - s.get("ts", 0) < _QA_TIMEOUT:
        return
    owner = s.get("owner")
    scene = s.get("scene")
    api = s.get("api")
    label = s.get("label", "")
    try:
        text = "%s%s作答超时已自动结束～" % (qa_mention(scene, owner), label)
        await qa_send(api, scene, chat_id, text, mention_openid=None)
    except Exception as e:
        logger.error("[QA] 超时消息发送失败: %s" % e)
    _QA.pop(_key(chat_id, qtype), None)


# ============================================================
#                        发送助手（基于 modules.common）
# ============================================================
async def qa_send(api, scene, chat_id, text, mention_openid=None, msg_id=None, event_id=None):
    """发文本：群 @ 提及时拼 <@!openid> 前缀，私聊不拼。"""
    content = text or ""
    if mention_openid and scene == ChatScene.GROUP:
        content = "%s%s" % (qa_mention(scene, mention_openid), content)
    if scene == ChatScene.GROUP:
        return await _send_group_markdown(api, chat_id, content, msg_id=msg_id, event_id=event_id)
    return await _send_text(api, scene, chat_id, content, msg_id=msg_id, event_id=event_id)


async def qa_send_kb(api, scene, chat_id, text, pairs, mention_openid=None,
                     msg_id=None, event_id=None, btn_prefix="qa"):
    """发带键盘消息。pairs = ((label, data), ...)。"""
    content = text or ""
    if mention_openid and scene == ChatScene.GROUP:
        content = "%s%s" % (qa_mention(scene, mention_openid), content)
    rows = []
    for l, d in pairs:
        rows.append({
            "buttons": [{
                "id": "btn_%s_%s" % (btn_prefix, d),
                "render_data": {"label": l, "visited_label": l, "style": 1},
                "action": {
                    "type": 2,
                    "permission": {"type": 2},
                    "data": d,
                    "enter": True,
                    "unsupport_tips": "请更新QQ版本",
                },
            }]
        })
    keyboard = {"content": {"rows": rows}}
    try:
        if scene == ChatScene.GROUP:
            return await _send_text_with_keyboard(api, scene, chat_id, content, keyboard, msg_id=msg_id, event_id=event_id)
        return await _send_text_with_keyboard(api, scene, chat_id, content, keyboard, msg_id=msg_id, event_id=event_id)
    except Exception as e:
        logger.error("[QA] 发送键盘失败: %s" % e)
        # fallback：纯文本
        return await qa_send(api, scene, chat_id, text, mention_openid=mention_openid, msg_id=msg_id, event_id=event_id)
