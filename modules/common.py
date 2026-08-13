# -*- coding: utf-8 -*-
"""
公共工具模块
提供消息发送、数据持久化、HTTP请求、按钮构建等通用功能
"""

import json
import os
import time
import re
import asyncio
import shutil
import aiohttp
from botpy import logging

logger = logging.get_logger()

# 控制台同步：安全导入，避免循环依赖
try:
    from console_server import record_bot_reply, increment_api_call
except ImportError:
    record_bot_reply = None
    increment_api_call = None

# 运行健康：安全导入指标采集（bot_health 仅依赖标准库，无循环依赖风险）
try:
    from modules.bot_health import record_stage as _bh_record_stage, get_request_appid as _bh_get_appid
except Exception:
    _bh_record_stage = None
    _bh_get_appid = None


def _bh_send_stage(stage, ms):
    """记录一个发送相关 pipeline 阶段（respond / send），appid 取自请求上下文。"""
    if _bh_record_stage is None or _bh_get_appid is None:
        return
    try:
        _bh_record_stage(_bh_get_appid() or "_shared", stage, float(ms))
    except Exception:
        pass

# 消息序号：基于时间戳，避免重启后与旧 msg_seq 冲突
_msg_seq_base = int(time.time() * 1000) % 1000000
_msg_seq_offset = 0


# ============ 场景常量与 chat_id 编码 ============

class ChatScene:
    """会话场景常量。群聊/私聊/频道三场景共享一套分发逻辑，通过 chat_id 前缀区分。"""
    GROUP = "group"      # 群聊
    C2C = "c2c"          # 用户与机器人私聊
    CHANNEL = "channel"  # 频道公域 @ 消息

# chat_id 前缀表（用于把不同场景的原生 ID 统一为带前缀的 chat_id，避免碰撞）
_SCENE_PREFIX = {
    ChatScene.GROUP: "g:",
    ChatScene.C2C: "u:",
    ChatScene.CHANNEL: "c:",
}


def make_chat_id(scene: str, raw_id: str) -> str:
    """
    把原生 ID（group_openid / user_openid / channel_id）统一编码为带场景前缀的 chat_id。
    示例：
        make_chat_id(ChatScene.GROUP, "ABC123")    -> "g:ABC123"
        make_chat_id(ChatScene.C2C,   "U_XYZ")     -> "u:U_XYZ"
        make_chat_id(ChatScene.CHANNEL,"CH_456")    -> "c:CH_456"
    """
    if not raw_id:
        return raw_id or ""
    prefix = _SCENE_PREFIX.get(scene, "")
    # 已是带前缀的 chat_id：直接返回
    if raw_id.startswith(("g:", "u:", "c:")):
        return raw_id
    return prefix + raw_id


def parse_chat_id(chat_id: str):
    """
    反解 chat_id -> (scene, raw_id)。
    未知前缀返回 (ChatScene.GROUP, chat_id) 兼容旧数据。
    """
    if not chat_id:
        return ChatScene.GROUP, ""
    if chat_id.startswith("u:"):
        return ChatScene.C2C, chat_id[2:]
    if chat_id.startswith("c:"):
        return ChatScene.CHANNEL, chat_id[2:]
    if chat_id.startswith("g:"):
        return ChatScene.GROUP, chat_id[2:]
    # 旧数据无前缀，兼容为群聊
    return ChatScene.GROUP, chat_id


def is_group_chat(chat_id: str) -> bool:
    """判断 chat_id 是否属于群聊场景（用于群管模块在私聊/频道中跳过）。"""
    return chat_id.startswith("g:") or (chat_id and not chat_id.startswith(("u:", "c:")))


def is_c2c_chat(chat_id: str) -> bool:
    """判断 chat_id 是否属于私聊场景。"""
    return chat_id.startswith("u:")


def is_channel_chat(chat_id: str) -> bool:
    """判断 chat_id 是否属于频道场景。"""
    return chat_id.startswith("c:")


# 消息去重缓存
_dedup_cache: dict = {}
_DEDUP_TTL = 10  # 秒

# msg_id 去重缓存（更准确，QQ 同一条消息重发场景）
_msg_id_cache: dict = {}
_MSG_ID_TTL = 30  # 秒，msg_id 唯一去重窗口可设大一些避免重连重发事件导致重复


def is_msg_duplicate(msg_id: str) -> bool:
    """
    基于 msg_id 的去重（同一条 QQ 消息只处理一次，TTL 内不重复）。
    msg_id 为 None 或空时返回 False（不去重）。
    """
    if not msg_id:
        return False
    now = time.time()
    expired = [k for k, t in _msg_id_cache.items() if now - t > _MSG_ID_TTL]
    for k in expired:
        _msg_id_cache.pop(k, None)
    if msg_id in _msg_id_cache:
        return True
    _msg_id_cache[msg_id] = now
    return False


def next_seq() -> int:
    """获取递增的消息序号（基于时间戳，重启不会冲突）"""
    global _msg_seq_offset
    _msg_seq_offset += 1
    return _msg_seq_base + _msg_seq_offset


def is_duplicate(chat_key: str, member_openid: str, content: str) -> bool:
    """
    检查是否为重复消息（同一用户同一内容在 TTL 内重复）。
    chat_key 在群聊时是 group_openid，私聊/频道时也可以是任意唯一标识。
    """
    now = time.time()
    expired = [k for k, t in _dedup_cache.items() if now - t > _DEDUP_TTL]
    for k in expired:
        _dedup_cache.pop(k, None)
    key = "%s|%s|%s" % (chat_key, member_openid, content)
    if key in _dedup_cache:
        return True
    _dedup_cache[key] = now
    return False


_TAG_RE = re.compile(r"<[^>]+>")


def clean_content(raw: str) -> str:
    """去除 QQ 群消息中的 @标记、表情等富文本标签"""
    return _TAG_RE.sub("", raw).strip()


# ============ 数据持久化 ============

def data_path(filename: str) -> str:
    """获取data目录下文件的完整路径"""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", filename)


def load_json(filename: str) -> dict:
    """加载JSON数据文件"""
    path = data_path(filename)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_json(filename: str, data: dict):
    """保存数据到JSON文件（原子写入，Windows 上不会因别的 handle 报 errno 13）

    步骤：1. 写到 <path>.tmp；2. os.replace 原子替换为正式文件。
    这样即使目标文件正被另一个进程以读/写 handle 占用，也不会失败。
    写入失败只记录日志，不再向上抛 PermissionError —— 否则会把整个
    指令处理链（视频解析/签到/游戏状态等）一次性崩掉。
    """
    path = data_path(filename)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(payload)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp, path)
    except Exception as e:
        logger.error("save_json 失败: %s -> %s" % (filename, e))


# ============ HTTP 请求 ============

async def http_get(url: str, params: dict = None, headers: dict = None, timeout: int = 10) -> dict:
    """异步GET请求（content_type=None 允许非 application/json 的响应体解析为JSON）"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status == 200:
                    return await resp.json(content_type=None)
                logger.error("HTTP GET失败: %s, status=%s" % (url, resp.status))
                return {}
    except Exception as e:
        logger.error("HTTP GET异常: %s, url=%s" % (e, url))
        return {}


async def http_get_text(url: str, params: dict = None, headers: dict = None, timeout: int = 10) -> str:
    """异步GET请求，返回文本"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status == 200:
                    return await resp.text()
                return ""
    except Exception as e:
        logger.error("HTTP GET TEXT异常: %s" % e)
        return ""


# ============ 第三方数据接口 ============

# 一言接口：优先 hitokoto 官方（返回 hitokoto/from/from_who，含书名与作者），
# 失败降级小渡 dwo.cc（纯文本，无出处）。两者均免 KEY、每次独立随机。
HITOKOTO_API_URL = "https://v1.hitokoto.cn/"
DWO_YIYAN_API_URL = "https://openapi.dwo.cc/api/yi"


async def fetch_yiyan(timeout: int = 5) -> dict:
    """拉取一条随机一言。

    返回 dict：{"text": 正文, "source": 书名/作品名, "author": 作者}。
    - 优先 hitokoto（带出处）；超时/异常则降级 dwo.cc（纯文本，source/author 为空）。
    - 无数据返回 {}，调用方据此隐藏整行（不影响主功能）。
    书名/作者按"有则带、无则不带"原则由 format_yiyan_line 拼接。
    """
    # 1) 优先 hitokoto 官方接口
    try:
        data = await http_get(HITOKOTO_API_URL, timeout=timeout)
        text = (data.get("hitokoto") or "").strip()
        if text:
            return {
                "text": text,
                "source": (data.get("from") or "").strip(),
                "author": (data.get("from_who") or "").strip(),
            }
    except Exception as e:
        logger.error("hitokoto 接口异常，降级 dwo.cc: %s" % e)
    # 2) 降级小渡 dwo.cc（纯文本，无出处）
    try:
        text = await http_get_text(DWO_YIYAN_API_URL, timeout=timeout)
        text = (text or "").strip()
        if text:
            return {"text": text, "source": "", "author": ""}
    except Exception as e:
        logger.error("一言接口异常: %s" % e)
    return {}


def format_yiyan_line(data: dict) -> str:
    """把一言数据格式化成引用块行（含书名/作者，缺失则省略）。

    返回形如：
      "\n> 科学会揭示真相。《守望先锋》莫伊拉"   （有书名+作者）
      "\n> 这就是命运石之门的选择！"             （无出处）
    无数据或为空时返回 ""（调用方隐藏整行）。书名/作者缺失时不带《》与署名。
    """
    if not data:
        return ""
    text = (data.get("text") or "").strip()
    if not text:
        return ""
    tail = ""
    source = (data.get("source") or "").strip()
    author = (data.get("author") or "").strip()
    if source:
        tail += "《%s》" % source
    if author:
        tail += author
    return "\n> " + text + tail


async def http_get_with_redirect(url: str, headers: dict = None, timeout: int = 15,
                                  allow_redirects: bool = True) -> tuple:
    """
    异步GET请求，返回 (文本, 最终URL, 状态码)。
    用于需要追踪重定向的场景（如抖音/快手短链接解析）。
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=timeout),
                                   allow_redirects=allow_redirects) as resp:
                text = await resp.text()
                return text, str(resp.url), resp.status
    except Exception as e:
        logger.error("HTTP GET(redirect)异常: %s, url=%s" % (e, url[:80]))
        return "", "", 0


async def http_post(url: str, json_data: dict = None, headers: dict = None, timeout: int = 10) -> dict:
    """异步POST请求"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=json_data, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status == 200:
                    return await resp.json(content_type=None)
                logger.error("HTTP POST失败: %s, status=%s" % (url, resp.status))
                return {}
    except Exception as e:
        logger.error("HTTP POST异常: %s" % e)
        return {}


# ============ 消息发送 ============

async def send_group_text(api, group_openid: str, content: str, msg_id: str = None, event_id: str = None):
    """发送群聊纯文本消息（被动回复超限时自动转为主动消息重试）
    兼容 chat_id 前缀：若 group_openid 以 u: 或 c: 开头，自动路由到 C2C 或频道。
    """
    # 智能识别 chat_id 前缀，自动分发到正确的场景
    if group_openid.startswith("u:"):
        return await send_c2c_text(api, group_openid[2:], content, msg_id=msg_id, event_id=event_id)
    if group_openid.startswith("c:"):
        return await send_channel_text(api, group_openid[2:], content, msg_id=msg_id, event_id=event_id)

    if increment_api_call:
        increment_api_call()
    kwargs = {
        "group_openid": group_openid,
        "msg_type": 0,
        "content": content,
        "msg_seq": next_seq(),
    }
    if msg_id:
        kwargs["msg_id"] = msg_id
    if event_id:
        kwargs["event_id"] = event_id
    try:
        result = await api.post_group_message(**kwargs)
        if record_bot_reply:
            record_bot_reply(group_openid, content, "text")
        return result
    except Exception as e:
        err_msg = str(e)
        logger.error("发送群消息失败: %s" % e)
        # 被动回复超限：去掉 msg_id 重试（转为主动消息）
        if "被动回复" in err_msg and msg_id:
            logger.info("被动回复超限，转为主动消息重试...")
            kwargs.pop("msg_id", None)
            kwargs["msg_seq"] = next_seq()
            try:
                result = await api.post_group_message(**kwargs)
                if record_bot_reply:
                    record_bot_reply(group_openid, content, "text")
                return result
            except Exception as e2:
                logger.error("主动消息重试也失败: %s" % e2)


async def send_group_markdown(api, group_openid: str, content: str, msg_id: str = None, event_id: str = None):
    """发送群聊 markdown 消息（msg_type=2），支持 <@!member_openid> 真实 @ 提及。
    兼容 chat_id 前缀：若 group_openid 以 u: 或 c: 开头，自动路由到 C2C 或频道。
    """
    if group_openid.startswith("u:"):
        return await send_c2c_text(api, group_openid[2:], content, msg_id=msg_id, event_id=event_id)
    if group_openid.startswith("c:"):
        return await send_channel_text(api, group_openid[2:], content, msg_id=msg_id, event_id=event_id)

    if increment_api_call:
        increment_api_call()
    from botpy.http import Route

    payload = {
        "group_openid": group_openid,
        "msg_type": 2,  # markdown 消息
        "content": content,  # 文本降级内容
        "markdown": {"content": content},
        "msg_seq": next_seq(),
    }
    if msg_id:
        payload["msg_id"] = msg_id
    if event_id:
        payload["event_id"] = event_id

    try:
        route = Route("POST", "/v2/groups/{group_openid}/messages", group_openid=group_openid)
        result = await api._http.request(route, json=payload)
        logger.info("发送群 markdown 消息成功: %s" % result)
        if record_bot_reply:
            record_bot_reply(group_openid, content, "markdown")
        return result
    except Exception as e:
        err_msg = str(e)
        logger.error("发送群 markdown 消息失败: %s" % e)
        # 被动回复超限：去掉 msg_id 重试
        if "被动回复" in err_msg and msg_id:
            logger.info("被动回复超限，转为主动消息重试...")
            payload.pop("msg_id", None)
            payload["msg_seq"] = next_seq()
            try:
                result = await api._http.request(route, json=payload)
                logger.info("主动消息重试发送群 markdown 成功: %s" % result)
                if record_bot_reply:
                    record_bot_reply(group_openid, content, "markdown")
                return result
            except Exception as e2:
                logger.error("主动消息重试也失败: %s" % e2)
        return None


async def send_group_text_with_keyboard(api, group_openid: str, content: str, keyboard: dict,
                                        msg_id: str = None, event_id: str = None):
    """
    发送群聊消息+按钮
    兼容 chat_id 前缀：若 group_openid 以 u: 或 c: 开头，自动路由到 C2C 或频道。
    """
    # 智能识别 chat_id 前缀，自动分发到正确的场景
    if group_openid.startswith("u:"):
        return await send_c2c_text_with_keyboard(api, group_openid[2:], content, keyboard, msg_id=msg_id, event_id=event_id)
    if group_openid.startswith("c:"):
        return await send_channel_text_with_keyboard(api, group_openid[2:], content, keyboard, msg_id=msg_id, event_id=event_id)

    if increment_api_call:
        increment_api_call()
    from botpy.http import Route

    payload = {
        "group_openid": group_openid,
        "msg_type": 2,  # markdown 消息（按钮需要 markdown 基础）
        "content": content,  # 文本降级内容
        "markdown": {"content": content},  # markdown 内容（纯文本也能渲染）
        "msg_seq": next_seq(),
        "keyboard": keyboard,
    }
    if msg_id:
        payload["msg_id"] = msg_id
    if event_id:
        payload["event_id"] = event_id

    try:
        route = Route("POST", "/v2/groups/{group_openid}/messages", group_openid=group_openid)
        result = await api._http.request(route, json=payload)
        logger.info("发送群消息(带按钮)成功: %s" % result)
        if record_bot_reply:
            record_bot_reply(ChatScene.GROUP, make_chat_id(ChatScene.GROUP, group_openid), content, "keyboard")
        return result
    except Exception as e:
        err_msg = str(e)
        logger.error("发送群消息(带按钮)失败: %s" % e)
        # 被动回复超限：去掉 msg_id 重试
        if "被动回复" in err_msg and msg_id:
            logger.info("被动回复超限，转为主动消息重试...")
            payload.pop("msg_id", None)
            payload["msg_seq"] = next_seq()
            try:
                result = await api._http.request(route, json=payload)
                logger.info("主动消息重试成功: %s" % result)
                if record_bot_reply:
                    record_bot_reply(ChatScene.GROUP, make_chat_id(ChatScene.GROUP, group_openid), content, "keyboard")
                return result
            except Exception as e2:
                logger.error("主动消息重试也失败: %s" % e2)
        # 其他失败：降级为纯文本+按钮
        logger.info("尝试降级为纯文本+按钮...")
        payload["msg_type"] = 0
        payload.pop("markdown", None)
        payload.pop("msg_id", None)
        payload["msg_seq"] = next_seq()
        try:
            result = await api._http.request(route, json=payload)
            logger.info("降级发送成功: %s" % result)
            if record_bot_reply:
                record_bot_reply(ChatScene.GROUP, make_chat_id(ChatScene.GROUP, group_openid), content, "keyboard")
            return result
        except Exception as e2:
            logger.error("降级发送也失败: %s" % e2)


# ============ C2C（私聊）消息发送 ============

async def send_c2c_text(api, user_openid: str, content: str,
                        msg_id: str = None, event_id: str = None):
    """发送私聊纯文本消息（被动回复超限时自动转为主动消息重试）"""
    if increment_api_call:
        increment_api_call()
    chat_id = make_chat_id(ChatScene.C2C, user_openid)
    kwargs = {
        "openid": user_openid,
        "msg_type": 0,
        "content": content,
        "msg_seq": next_seq(),
    }
    if msg_id:
        kwargs["msg_id"] = msg_id
    if event_id:
        kwargs["event_id"] = event_id
    try:
        result = await api.post_c2c_message(**kwargs)
        if record_bot_reply:
            record_bot_reply(ChatScene.C2C, chat_id, content, "text")
        return result
    except Exception as e:
        err_msg = str(e)
        logger.error("发送私聊消息失败: %s" % e)
        if "被动回复" in err_msg and msg_id:
            logger.info("被动回复超限，转为主动消息重试...")
            kwargs.pop("msg_id", None)
            kwargs["msg_seq"] = next_seq()
            try:
                result = await api.post_c2c_message(**kwargs)
                if record_bot_reply:
                    record_bot_reply(ChatScene.C2C, chat_id, content, "text")
                return result
            except Exception as e2:
                logger.error("主动私聊消息重试也失败: %s" % e2)


async def send_c2c_text_with_keyboard(api, user_openid: str, content: str, keyboard: dict,
                                       msg_id: str = None, event_id: str = None):
    """发送私聊消息 + 按钮（markdown + keyboard）。"""
    if increment_api_call:
        increment_api_call()
    chat_id = make_chat_id(ChatScene.C2C, user_openid)
    from botpy.http import Route

    payload = {
        "openid": user_openid,
        "msg_type": 2,
        "content": content,
        "markdown": {"content": content},
        "msg_seq": next_seq(),
        "keyboard": keyboard,
    }
    if msg_id:
        payload["msg_id"] = msg_id
    if event_id:
        payload["event_id"] = event_id

    route = Route("POST", "/v2/users/{openid}/messages", openid=user_openid)
    try:
        result = await api._http.request(route, json=payload)
        logger.info("发送私聊消息(带按钮)成功: %s" % result)
        if record_bot_reply:
            record_bot_reply(ChatScene.C2C, chat_id, content, "keyboard")
        return result
    except Exception as e:
        err_msg = str(e)
        logger.error("发送私聊消息(带按钮)失败: %s" % e)
        if "被动回复" in err_msg and msg_id:
            logger.info("被动回复超限，转为主动消息重试...")
            payload.pop("msg_id", None)
            payload["msg_seq"] = next_seq()
            try:
                result = await api._http.request(route, json=payload)
                if record_bot_reply:
                    record_bot_reply(ChatScene.C2C, chat_id, content, "keyboard")
                return result
            except Exception as e2:
                logger.error("主动私聊重试失败: %s" % e2)
        # 降级为纯文本
        payload["msg_type"] = 0
        payload.pop("markdown", None)
        payload.pop("msg_id", None)
        payload["msg_seq"] = next_seq()
        try:
            result = await api._http.request(route, json=payload)
            if record_bot_reply:
                record_bot_reply(ChatScene.C2C, chat_id, content, "keyboard")
            return result
        except Exception as e2:
            logger.error("降级发送也失败: %s" % e2)


# ============ 频道消息发送 ============

async def send_channel_text(api, channel_id: str, content: str,
                            msg_id: str = None, event_id: str = None):
    """发送频道公域纯文本消息（msg_id 被动回复超限时自动重试）"""
    if increment_api_call:
        increment_api_call()
    chat_id = make_chat_id(ChatScene.CHANNEL, channel_id)
    kwargs = {
        "channel_id": channel_id,
        "content": content,
        "msg_seq": next_seq(),
    }
    if msg_id:
        kwargs["msg_id"] = msg_id
    if event_id:
        kwargs["event_id"] = event_id
    try:
        result = await api.post_message(**kwargs)
        if record_bot_reply:
            record_bot_reply(ChatScene.CHANNEL, chat_id, content, "text")
        return result
    except Exception as e:
        err_msg = str(e)
        logger.error("发送频道消息失败: %s" % e)
        if "被动回复" in err_msg and msg_id:
            logger.info("被动回复超限，转为主动消息重试...")
            kwargs.pop("msg_id", None)
            kwargs["msg_seq"] = next_seq()
            try:
                result = await api.post_message(**kwargs)
                if record_bot_reply:
                    record_bot_reply(ChatScene.CHANNEL, chat_id, content, "text")
                return result
            except Exception as e2:
                logger.error("主动频道消息重试也失败: %s" % e2)


async def send_channel_text_with_keyboard(api, channel_id: str, content: str, keyboard: dict,
                                          msg_id: str = None, event_id: str = None):
    """发送频道消息 + 按钮（markdown + keyboard）。"""
    if increment_api_call:
        increment_api_call()
    chat_id = make_chat_id(ChatScene.CHANNEL, channel_id)
    from botpy.http import Route

    payload = {
        "channel_id": channel_id,
        "msg_type": 2,
        "content": content,
        "markdown": {"content": content},
        "msg_seq": next_seq(),
        "keyboard": keyboard,
    }
    if msg_id:
        payload["msg_id"] = msg_id
    if event_id:
        payload["event_id"] = event_id

    route = Route("POST", "/channels/{channel_id}/messages", channel_id=channel_id)
    try:
        result = await api._http.request(route, json=payload)
        logger.info("发送频道消息(带按钮)成功: %s" % result)
        if record_bot_reply:
            record_bot_reply(ChatScene.CHANNEL, chat_id, content, "keyboard")
        return result
    except Exception as e:
        err_msg = str(e)
        logger.error("发送频道消息(带按钮)失败: %s" % e)
        if "被动回复" in err_msg and msg_id:
            payload.pop("msg_id", None)
            payload["msg_seq"] = next_seq()
            try:
                result = await api._http.request(route, json=payload)
                if record_bot_reply:
                    record_bot_reply(ChatScene.CHANNEL, chat_id, content, "keyboard")
                return result
            except Exception as e2:
                logger.error("主动频道重试失败: %s" % e2)
        # 降级为纯文本
        payload["msg_type"] = 0
        payload.pop("markdown", None)
        payload.pop("msg_id", None)
        payload["msg_seq"] = next_seq()
        try:
            result = await api._http.request(route, json=payload)
            if record_bot_reply:
                record_bot_reply(ChatScene.CHANNEL, chat_id, content, "keyboard")
            return result
        except Exception as e2:
            logger.error("降级发送也失败: %s" % e2)


# ============ 场景无关的统一发送接口 ============

async def send_text(api, scene: str, target_id: str, content: str,
                    msg_id: str = None, event_id: str = None):
    """
    场景无关的统一发送接口（按 scene 自动选择群/C2C/频道）。
    - scene: ChatScene.GROUP / C2C / CHANNEL
    - target_id: 对应的原生 ID（group_openid / user_openid / channel_id）
    """
    # 运行健康：respond（场景路由准备）→ send（网络发送）阶段拆分计时
    _t_resp = time.perf_counter()
    if scene == ChatScene.GROUP:
        _t_send = time.perf_counter()
        _r = await send_group_text(api, target_id, content, msg_id=msg_id, event_id=event_id)
    elif scene == ChatScene.C2C:
        _t_send = time.perf_counter()
        _r = await send_c2c_text(api, target_id, content, msg_id=msg_id, event_id=event_id)
    elif scene == ChatScene.CHANNEL:
        _t_send = time.perf_counter()
        _r = await send_channel_text(api, target_id, content, msg_id=msg_id, event_id=event_id)
    else:
        logger.error("未知 scene: %s" % scene)
        return None
    _bh_send_stage("respond", (_t_send - _t_resp) * 1000.0)
    _bh_send_stage("send", (time.perf_counter() - _t_send) * 1000.0)
    return _r


async def send_text_with_keyboard(api, scene: str, target_id: str, content: str, keyboard: dict,
                                  msg_id: str = None, event_id: str = None):
    """场景无关的统一发送接口（带按钮）。"""
    # 运行健康：respond（场景路由准备）→ send（网络发送）阶段拆分计时
    _t_resp = time.perf_counter()
    if scene == ChatScene.GROUP:
        _t_send = time.perf_counter()
        _r = await send_group_text_with_keyboard(api, target_id, content, keyboard, msg_id=msg_id, event_id=event_id)
    elif scene == ChatScene.C2C:
        _t_send = time.perf_counter()
        _r = await send_c2c_text_with_keyboard(api, target_id, content, keyboard, msg_id=msg_id, event_id=event_id)
    elif scene == ChatScene.CHANNEL:
        _t_send = time.perf_counter()
        _r = await send_channel_text_with_keyboard(api, target_id, content, keyboard, msg_id=msg_id, event_id=event_id)
    else:
        logger.error("未知 scene: %s" % scene)
        return None
    _bh_send_stage("respond", (_t_send - _t_resp) * 1000.0)
    _bh_send_stage("send", (time.perf_counter() - _t_send) * 1000.0)
    return _r


async def send_for_chat(api, chat_id: str, content: str,
                        msg_id: str = None, event_id: str = None):
    """
    根据 chat_id 前缀自动判断场景并发送文本（向后兼容老代码：传入带前缀的 chat_id）。
    - chat_id 以 "g:" 开头 → 群聊
    - chat_id 以 "u:" 开头 → C2C 私聊
    - chat_id 以 "c:" 开头 → 频道
    - 无前缀或旧数据 → 视为群聊
    """
    scene, raw_id = parse_chat_id(chat_id)
    return await send_text(api, scene, raw_id, content, msg_id=msg_id, event_id=event_id)


async def send_for_chat_with_keyboard(api, chat_id: str, content: str, keyboard: dict,
                                      msg_id: str = None, event_id: str = None):
    """根据 chat_id 前缀自动判断场景并发送带按钮的消息。"""
    scene, raw_id = parse_chat_id(chat_id)
    return await send_text_with_keyboard(api, scene, raw_id, content, keyboard, msg_id=msg_id, event_id=event_id)


async def _download_media_bytes(url: str, timeout: int = 20, max_size_mb: int = 25) -> bytes:
    """
    下载媒体文件为 bytes，失败返回 None。
    - timeout: 总超时秒数
    - max_size_mb: 最大文件大小（MB），<=0 表示不限制
    - 使用通用下载请求头（User-Agent / Accept），当前媒体源无需 Referer
    """
    try:
        max_bytes = max_size_mb * 1024 * 1024 if max_size_mb and max_size_mb > 0 else None
        headers = _build_download_headers(url)
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers,
                                    timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status == 200:
                    # 检查 Content-Length 是否超限（max_bytes 为 None 表示不限制）
                    content_length = resp.headers.get("Content-Length", "")
                    if max_bytes is not None and content_length and int(content_length) > max_bytes:
                        logger.error("文件过大(%.1fMB > %dMB)，跳过: %s" % (
                            int(content_length) / 1024 / 1024, max_size_mb, url[:80]))
                        return None
                    # 分块读取，防止超大文件
                    chunks = []
                    total = 0
                    async for chunk in resp.content.iter_chunked(1024 * 256):  # 256KB chunks
                        total += len(chunk)
                        if max_bytes is not None and total > max_bytes:
                            logger.error("下载超过大小限制(%dMB)，中止: %s" % (max_size_mb, url[:80]))
                            return None
                        chunks.append(chunk)
                    return b"".join(chunks)
                logger.error("下载媒体失败: status=%s, url=%s" % (resp.status, url[:80]))
                return None
    except Exception as e:
        logger.error("下载媒体异常: %s, url=%s" % (e, url[:80]))
        return None


# ============================================================
# 下载请求头构造 + 图片 magic bytes 校验
# ============================================================


def _build_download_headers(url: str) -> dict:
    """
    构造下载媒体（图片/视频/音频）用的通用请求头。
    当前所有媒体源（图片 CDN / 视频 / 音频）均无需防盗链 Referer，
    故只返回基础 UA / Accept 头即可，保持最小可用集合。
    """
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }


def _looks_like_image(data: bytes) -> bool:
    """
    通过 magic bytes 校验数据是否真是图片。
    支持：JPEG / PNG / GIF / WebP / BMP
    """
    if not data or len(data) < 12:
        return False
    # JPEG: FF D8 FF
    if data[:3] == b"\xff\xd8\xff":
        return True
    # PNG: 89 50 4E 47 0D 0A 1A 0A
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    # GIF: 47 49 46 38
    if data[:4] in (b"GIF87a", b"GIF89a"):
        return True
    # WebP: RIFF .... WEBP
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    # BMP: 42 4D
    if data[:2] == b"BM":
        return True
    return False


async def _head_content_length(url: str, headers: dict = None, timeout: int = 10) -> int:
    """HEAD 探测返回 Content-Length（字节数），失败 / 解析不到返回 -1。

    用于「大文件过滤」：在真正下载之前先 HEAD 一次，过大就不下载、不浪费流量
    直接退到「外链卡片」分支。
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.head(url, headers=headers,
                                    timeout=aiohttp.ClientTimeout(total=timeout),
                                    allow_redirects=True) as resp:
                if resp.status in (200, 206, 302, 307):
                    cl = resp.headers.get("Content-Length", "")
                    try:
                        n = int(cl)
                        return n if n > 0 else -1
                    except (TypeError, ValueError):
                        return -1
                return -1
    except Exception as e:
        logger.warning("HEAD 探测失败: %s, url=%s" % (e, url[:80]))
        return -1


async def _download_media_bytes_with_headers(url: str, headers: dict = None,
                                              timeout: int = 30, max_size_mb: int = 25) -> bytes:
    """
    下载媒体文件为 bytes（支持自定义请求头，用于B站等需要Referer的网站）。
    - headers: 自定义请求头（如 {"Referer": "https://www.bilibili.com"}）
    - timeout: 总超时秒数
    - max_size_mb: 最大文件大小（MB），<=0 表示不限制
    """
    try:
        max_bytes = max_size_mb * 1024 * 1024 if max_size_mb and max_size_mb > 0 else None
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status == 200:
                    content_length = resp.headers.get("Content-Length", "")
                    if max_bytes is not None and content_length and int(content_length) > max_bytes:
                        logger.error("文件过大(%.1fMB > %dMB)，跳过: %s" % (
                            int(content_length) / 1024 / 1024, max_size_mb, url[:80]))
                        return None
                    chunks = []
                    total = 0
                    async for chunk in resp.content.iter_chunked(1024 * 256):
                        total += len(chunk)
                        if max_bytes is not None and total > max_bytes:
                            logger.error("下载超过大小限制(%dMB)，中止: %s" % (max_size_mb, url[:80]))
                            return None
                        chunks.append(chunk)
                    return b"".join(chunks)
                logger.error("下载媒体失败: status=%s, url=%s" % (resp.status, url[:80]))
                return None
    except Exception as e:
                logger.error("下载媒体异常: %s, url=%s" % (e, url[:80]))
                return None


async def _probe_video_duration(video_bytes: bytes) -> float:
    """
    用 ffprobe 探测视频时长（秒）。
    返回 0.0 表示未知（未安装 ffprobe 或探测失败），调用方据此放行。
    """
    import os
    import tempfile
    import shutil
    import asyncio
    ffprobe = shutil.which("ffprobe") or r"C:\Program Files\ffmpeg\bin\ffprobe.exe"
    if not ffprobe or not os.path.exists(ffprobe):
        return 0.0
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
            tf.write(video_bytes)
            tmp = tf.name
        proc = await asyncio.create_subprocess_exec(
            ffprobe, "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1=nk=1", tmp,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await proc.communicate()
        text = (out or b"").decode("utf-8", "ignore").strip()
        if text:
            try:
                return float(text)
            except ValueError:
                return 0.0
    except Exception as e:
        logger.error("探测视频时长异常: %s" % e)
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except Exception:
                pass
    return 0.0


async def _upload_group_file(api, group_openid: str, file_type: int,
                          file_bytes: bytes = None, url: str = None) -> str:
    """
    上传富媒体文件到 QQ 群，返回 file_info。官方 API: POST /v2/groups/{group_openid}/files
    - file_type: 1=图片, 2=视频, 3=语音
    - 两种上传方式二选一：
        * url 模式（推荐，file_bytes=None 且给定 url）：让 QQ 服务器侧拉取文件。
          请求体不含 base64，体积极小，可发原始画质、绕开 stgw 网关的 body 体积 413。
          （botpy 官方 post_group_file 就是这种模式，仅传 url）
        * file_data 模式（url=None 且给定 file_bytes）：本地 bytes 经 base64 编码上传，
          会膨胀 ~33%，大文件易触发 413，仅作兜底。
    返回 file_info 字符串，失败返回 None。
    """
    from botpy.http import Route

    if url:
        payload = {
            "file_type": file_type,
            "url": url,
            "file_data": "",
            "srv_send_msg": False,
        }
        mode = "url"
        total = 90  # 服务器侧拉取可能耗时，放宽超时
    else:
        if not file_bytes:
            logger.error("上传群文件参数错误：既无 url 也无 file_bytes")
            return None
        import base64
        file_data_b64 = base64.b64encode(file_bytes).decode("utf-8")
        payload = {
            "file_type": file_type,
            "url": "",
            "file_data": file_data_b64,
            "srv_send_msg": False,
        }
        mode = "base64"
        total = 30

    await api._http.check_session()
    headers = dict(api._http._headers)
    route = Route("POST", "/v2/groups/{group_openid}/files", group_openid=group_openid)
    route.is_sandbox = api._http.is_sandbox

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(route.url, json=payload, headers=headers,
                                    timeout=aiohttp.ClientTimeout(total=total)) as resp:
                body = await resp.text()
                if resp.status in (200, 202, 204):
                    data = json.loads(body)
                    file_info = data.get("file_info", "")
                    logger.info("上传群文件成功(%s): file_type=%s, file_info=%s" % (mode, file_type, file_info[:50]))
                    return file_info
                logger.error("上传群文件失败(%s): status=%s, body=%s" % (mode, resp.status, body[:200]))
                return None
    except Exception as e:
        logger.error("上传群文件异常(%s): %s" % (mode, e))
        return None


async def _send_group_media(api, group_openid: str, file_info: str, msg_type: int,
                             content: str = "", msg_id: str = None):
    """
    发送带 media 的群消息（图文混排或富媒体）。
    - msg_type: 1=图文混排, 7=富媒体
    """
    if increment_api_call:
        increment_api_call()

    from botpy.http import Route

    async def _do_send(use_msg_id: bool):
        payload = {
            "group_openid": group_openid,
            "msg_type": msg_type,
            "content": content or "",
            "media": {"file_info": file_info},
            "msg_seq": next_seq(),
        }
        if msg_id and use_msg_id:
            payload["msg_id"] = msg_id

        route = Route("POST", "/v2/groups/{group_openid}/messages", group_openid=group_openid)
        return await api._http.request(route, json=payload)

    try:
        result = await _do_send(use_msg_id=True)
        logger.info("发送群媒体消息成功: %s" % result)
        if record_bot_reply:
            record_bot_reply(group_openid, content or "[媒体]", "media")
        return result
    except Exception as e:
        err_msg = str(e)
        logger.error("发送群媒体消息失败: %s" % e)
        # 被动回复超限：去掉 msg_id 重试
        if "被动回复" in err_msg and msg_id:
            logger.info("被动回复超限，转为主动消息重试...")
            try:
                result = await _do_send(use_msg_id=False)
                logger.info("主动消息重试发送群媒体消息成功: %s" % result)
                if record_bot_reply:
                    record_bot_reply(group_openid, content or "[媒体]", "media")
                return result
            except Exception as e2:
                logger.error("主动消息重试也失败: %s" % e2)
        return None


async def send_group_image(api, group_openid: str, image_url: str, msg_id: str = None, content: str = None):
    """
    发送群聊图片消息（URL方式）。
    先下载图片为 bytes，再用 base64 上传到 QQ 服务器获取 file_info，最后发送图文混排消息。
    - 使用通用下载请求头（User-Agent / Accept），当前媒体源无需 Referer
    - 下载后做 magic bytes 校验，HTML 错误页等非图片直接跳过
    """
    image_bytes = await _download_media_bytes(image_url)
    if not image_bytes:
        logger.error("下载图片失败，无法发送: %s" % image_url)
        return None
    if not _looks_like_image(image_bytes):
        logger.error("下载内容非图片（疑似防盗链 HTML/错误页）: url=%s head=%s" % (
            image_url[:80], image_bytes[:16].hex()))
        return None
    file_info = await _upload_group_file(api, group_openid, 1, image_bytes)
    if not file_info:
        return None
    # 统一走 msg_type=7 富媒体（不需要 markdown 模板权限，手机/PC 一致可见）。
    # content 字段作为 caption 纯文本（如 "🎲 退蝶" / "📋 我的信息"），不会被剥离。
    # 之前 content 非空时走 msg_type=1 图文混排需要 markdown 模板权限，
    # 无权限直接返 40034127 "消息发送失败，无markdown模板权限"，导致
    # 「角色图库」「我的信息」等带文字的图片在所有群都发不出去。
    # 现统一与 send_group_local_image / send_c2c_image 保持一致，避免模板权限依赖。
    if content:
        if isinstance(content, list):
            content_payload = json.dumps(content, ensure_ascii=False)
        else:
            content_payload = content
    else:
        content_payload = ""
    target_msg_type = 7
    return await _send_group_media(api, group_openid, file_info, msg_type=target_msg_type,
                                   content=content_payload, msg_id=msg_id)


def _compress_video_bytes(video_bytes: bytes, target_mb: int = 20) -> bytes:
    """
    用 ffmpeg 把视频降到适配 QQ 的大小（保底能发出去）。
    目标：压缩后 <= target_mb MB。QQ 视频软限制 30MB，但 113MB 4K 即使 720p/360p
    也可能超 25MB（stgw 网关实测 < 30MB 也会被 413），所以用 20MB 留余量。
    三段兜底：
      1) 720p + 视频 2000kbps 硬限（CRF28 + -b:v 2000k -maxrate 2000k -bufsize 4000k）
      2) 480p + 视频 1500kbps 硬限
      3) 360p + 视频 1000kbps 硬限
      4) 240p + 视频 600kbps + 音频 64k + 必要时减半时长  (极端兜底)
    返回压缩后的 bytes；失败返回 None。同步函数，调用方用 asyncio.to_thread 包裹。
    """
    import tempfile
    import subprocess
    try:
        import imageio_ffmpeg
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        logger.error("imageio-ffmpeg 未安装，无法压缩视频")
        return None

    tmp_dir = tempfile.mkdtemp(prefix="vid_conv_")
    input_path = os.path.join(tmp_dir, "input.mp4")
    try:
        with open(input_path, "wb") as f:
            f.write(video_bytes)

        # 获取原视频时长（秒），用于极端兜底的"剪半"
        try:
            probe = subprocess.run(
                [ffmpeg_path, "-i", input_path],
                capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            import re as _re
            m = _re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", probe.stderr)
            duration_sec = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0
        except Exception:
            duration_sec = 0

        # 逐级降级（h, crf, vb_kbps, ab_kbps, cut_half）
        # 5 档兜底：720p → 480p → 360p → 240p+剪半 → 160p+剪半
        # 实测 17.9MB 仍被 stgw 413 拒，目标拉到 10MB 留较大余量
        levels = [
            ("720", "28", "2000", "96",  False),
            ("480", "30", "1500", "96",  False),
            ("360", "32", "1000", "64",  False),
            ("240", "34", "600",  "48",  True),
            ("160", "36", "400",  "48",  True),
        ]
        last = None
        for h, crf, vb, ab, cut_half in levels:
            output_path = os.path.join(tmp_dir, "out_%s.mp4" % h)
            cmd = [
                ffmpeg_path, "-y", "-i", input_path,
            ]
            if cut_half and duration_sec > 0:
                cmd += ["-t", str(duration_sec / 2.0)]
            cmd += [
                "-vf", "scale=-2:%s" % h,
                "-c:v", "libx264",
                "-crf", crf, "-preset", "veryfast",
                "-b:v", "%sk" % vb, "-maxrate", "%sk" % vb, "-bufsize", "%sk" % (int(vb) * 2),
                "-c:a", "aac", "-b:a", "%sk" % ab,
                "-movflags", "+faststart",
                output_path,
            ]
            try:
                subprocess.run(cmd, capture_output=True, timeout=180)
            except Exception as e:
                logger.warning("ffmpeg 重编码失败(%sp): %s" % (h, e))
                continue
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                size_mb = os.path.getsize(output_path) / 1024 / 1024
                with open(output_path, "rb") as f:
                    data = f.read()
                logger.info("视频压缩 %sp: %.1fMB (目标<=%dMB)" % (h, size_mb, target_mb))
                if size_mb <= target_mb:
                    return data
                last = (size_mb, data)
        if last:
            # 已到 240p+剪半 仍超 20MB：返回产物，调用方再做兜底
            logger.warning("视频压缩后仍达 %.1fMB（>目标%dMB），作为兜底返回" % (last[0], target_mb))
            return last[1]
        return None
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


async def _head_content_length(url: str) -> int:
    """轻量探测远程视频大小（字节）。HEAD 优先，失败回退 Range GET。无法探测返回 0。"""
    try:
        async with aiohttp.ClientSession() as session:
            try:
                async with session.head(url, timeout=aiohttp.ClientTimeout(total=15), allow_redirects=True) as resp:
                    cl = resp.headers.get("Content-Length")
                    if cl:
                        return int(cl)
            except Exception:
                pass
            async with session.get(url, headers={"Range": "bytes=0-0"},
                                   timeout=aiohttp.ClientTimeout(total=15), allow_redirects=True) as r2:
                cr = r2.headers.get("Content-Range")
                if cr and "/" in cr:
                    return int(cr.split("/")[-1])
    except Exception as e:
        logger.warning("HEAD 探视频大小失败: %s" % e)
    return 0


async def send_group_video(api, group_openid: str, video_url: str, msg_id: str = None,
                           content: str = None, headers: dict = None,
                           fallback_link: str = None):
    """
    发送群聊视频消息。
    - 优先 url 模式直传（无需自定义请求头时）：QQ 服务器侧拉取原始文件，原画质、零转码、
      无 base64 膨胀，可有效绕开 stgw 网关 413。QQ Bot API 视频上限约 100MB。
    - 直传失败（>100MB / 防盗链 / 超时）则回退：下载放宽到 200MB，超 12MB 自动降画质重编码
    - 5 档降级（720/480/360/240+剪半/160+剪半），目标 10MB
    - 兜底仍超限或上传失败（413 等）时降级为发原视频链接文字，让用户在抖音/B站APP内自行打开
    - fallback_link: 失败时发给用户的外链；默认用 video_url 本身
    """
    # ① 优先 url 模式直传：QQ 服务器侧拉取原始文件 → 原画质、零转码、无 base64 膨胀、绕开 stgw 413。
    #    仅对「无需自定义请求头」的源尝试（带 headers 的源 QQ 服务器无法带 Referer 拉取，必败）。
    #    QQ Bot API 视频上限约 100MB，超限会被接口拒绝 → 落到下方下载/压缩兜底。
    if not headers:
        file_info = await _upload_group_file(api, group_openid, 2, url=video_url)
        if file_info:
            logger.info("视频 url 模式直传成功（原始画质），跳过下载/压缩")
            return await _send_group_media(api, group_openid, file_info, msg_type=7,
                                           content=content or "", msg_id=msg_id)
        logger.info("视频 url 模式直传失败，回退到下载+压缩方案")
    # ②.5 若远程视频 >100MB（官方 Bot API 视频硬上限），直接发原链接，避免压成糊片又费时
    if not headers:
        cl = await _head_content_length(video_url)
        if cl and cl > 100 * 1024 * 1024:
            link = fallback_link or video_url
            logger.info("视频 %.1fMB 超官方 Bot API 100MB 上限，直接发原链接" % (cl/1024/1024))
            from modules.common import send_text
            await send_text(api, "group", group_openid,
                            "⚠️ 视频文件过大（%.1fMB）超过官方机器人发送上限，请点击链接查看全画质：\n%s" % (cl/1024/1024, link),
                            msg_id=msg_id)
            return None
    # ② 兜底：下载到本地 → 超 12MB 降画质重编码（目标 10MB）→ base64 上传；失败则发外链
    if headers:
        video_bytes = await _download_media_bytes_with_headers(video_url, headers=headers, timeout=180, max_size_mb=200)
    else:
        video_bytes = await _download_media_bytes(video_url, timeout=180, max_size_mb=200)
    if not video_bytes:
        logger.error("下载视频失败，无法发送: %s" % video_url[:80])
        return None
    # 超 12MB 则降画质重编码（QQ stgw 网关实测 17.9MB 也会 413）
    if len(video_bytes) > 12 * 1024 * 1024:
        logger.info("视频 %.1fMB 超 QQ 上传软限，尝试降画质重编码..." % (len(video_bytes) / 1024 / 1024))
        compressed = await asyncio.to_thread(_compress_video_bytes, video_bytes, 10)
        if compressed:
            compressed_mb = len(compressed) / 1024 / 1024
            logger.info("视频压缩完成: %.1fMB → %.1fMB" % (len(video_bytes)/1024/1024, compressed_mb))
            video_bytes = compressed
    # 压缩后仍超 12MB（兜底失败）则不发视频，改发外链文字。
    # 注：上传走 base64 会膨胀 ~33%，12MB 原始 ≈ 16MB 请求体，留出网关体限余量
    if len(video_bytes) > 12 * 1024 * 1024:
        logger.warning("视频压缩后仍达 %.1fMB，降级为发外链" % (len(video_bytes)/1024/1024))
        link = fallback_link or video_url
        from modules.common import send_text
        await send_text(api, "group", group_openid,
                        "⚠️ 视频文件过大（%.1fMB）已自动降画质仍超出发送上限，请点击链接查看：\n%s" % (len(video_bytes)/1024/1024, link),
                        msg_id=msg_id)
        return None
    file_info = await _upload_group_file(api, group_openid, 2, video_bytes)
    if not file_info:
        # 上传失败（stgw 413 或其他），降级为外链文字
        link = fallback_link or video_url
        logger.warning("视频上传失败，降级为发外链: %s" % link[:80])
        from modules.common import send_text
        await send_text(api, "group", group_openid,
                        "⚠️ 视频上传失败，请点击链接查看：\n%s" % link,
                        msg_id=msg_id)
        return None
    return await _send_group_media(api, group_openid, file_info, msg_type=7,
                                   content=content or "", msg_id=msg_id)


async def send_group_video_bytes(api, group_openid: str, video_bytes: bytes,
                                  content: str = "", msg_id: str = None,
                                  fallback_link: str = None):
    """
    发送已下载的视频bytes到群聊。
    用于已自行下载视频（如B站视频带Referer头下载）的场景。
    超 12MB 自动降画质重编码（目标 10MB）；压缩后仍超 15MB 或上传失败时，
    降级为发 fallback_link 文字（一般是用户分享的原视频 URL）。
    """
    if len(video_bytes) > 12 * 1024 * 1024:
        logger.info("视频 %.1fMB 超 QQ 上传软限，尝试降画质重编码..." % (len(video_bytes) / 1024 / 1024))
        compressed = await asyncio.to_thread(_compress_video_bytes, video_bytes, 10)
        if compressed:
            logger.info("视频压缩完成: %.1fMB → %.1fMB" % (len(video_bytes)/1024/1024, len(compressed)/1024/1024))
            video_bytes = compressed
    if len(video_bytes) > 15 * 1024 * 1024:
        logger.warning("视频压缩后仍达 %.1fMB，降级为发外链" % (len(video_bytes)/1024/1024))
        from modules.common import send_text
        if fallback_link:
            await send_text(api, "group", group_openid,
                            "⚠️ 视频文件过大（%.1fMB）已自动降画质仍超出发送上限，请点击链接查看：\n%s" % (len(video_bytes)/1024/1024, fallback_link),
                            msg_id=msg_id)
        else:
            await send_text(api, "group", group_openid,
                            "⚠️ 视频文件过大（%.1fMB）已自动降画质仍超出发送上限" % (len(video_bytes)/1024/1024),
                            msg_id=msg_id)
        return None
    file_info = await _upload_group_file(api, group_openid, 2, video_bytes)
    if not file_info:
        # 上传失败（stgw 413 等），降级为外链文字
        from modules.common import send_text
        if fallback_link:
            logger.warning("视频上传失败，降级为发外链")
            await send_text(api, "group", group_openid,
                            "⚠️ 视频上传失败，请点击链接查看：\n%s" % fallback_link,
                            msg_id=msg_id)
        return None
    return await _send_group_media(api, group_openid, file_info, msg_type=7,
                                   content=content or "", msg_id=msg_id)


async def send_group_local_image(api, group_openid: str, image_bytes: bytes,
                                  content: str = "", msg_id: str = None):
    """
    发送本地图片（bytes）到群聊。
    使用 base64 上传到 QQ 服务器获取 file_info，再发送图文混排消息（msg_type=1）。
    注意：不支持同时发送 keyboard（media 与 keyboard 互斥）。
    """
    file_info = await _upload_group_file(api, group_openid, 1, image_bytes)
    if not file_info:
        return None
    return await _send_group_media(api, group_openid, file_info, msg_type=7,
                                   content=content, msg_id=msg_id)



async def send_group_audio(api, group_openid: str, audio_url: str, msg_id: str = None,
                            content: str = "", headers: dict = None):
    """
    发送群聊语音消息（整首歌分段发送，每段 <= 50s 且 <= 4MB，满足 QQ 语音限制）。
    - audio_url: 音频文件URL（m4a/mp3等）
    - headers: 自定义请求头（如QQ音乐需要Referer）
    - content: 仅单段短歌时作为该条语音的附加文本；多段时每段带「第 N/M 段」标签
    """
    return await _send_audio_segments(
        api, group_openid, audio_url, msg_id=msg_id, content=content, headers=headers,
        upload_fn=_upload_group_file, send_media_fn=_send_group_media,
    )

def _convert_to_mp3(audio_bytes: bytes, force: tuple = None) -> bytes:
    """
    将音频bytes转换为MP3格式（整首转换，不截断）。
    QQ Bot API file_type=3 官方支持 mp3 格式。
    整首歌会交给 _split_audio_to_segments 按 60s 上限切分后逐段发送。
    降级策略: 192k立体声 → 128k → 96k单声道 → 64k单声道（仅保格式兼容，不截断）。
    返回完整MP3格式bytes，失败返回None。

    force: 可选 (bitrate, channels, sample_rate)。指定后只用该级别转码，
           用于「整条语音上传失败 → 降码率整条重试」场景（把整首压到 < 4MB）。
    """
    import tempfile
    import subprocess
    import os
    try:
        import imageio_ffmpeg
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        logger.error("imageio-ffmpeg 未安装，无法转换音频格式")
        return None

    tmp_dir = tempfile.mkdtemp(prefix="audio_conv_")
    # 用 .audio 通用后缀，让 ffmpeg 自动嗅探格式（避免 m4a 误判 OGG）
    input_path = os.path.join(tmp_dir, "input.audio")

    try:
        # 写入原始音频
        with open(input_path, "wb") as f:
            f.write(audio_bytes)

        # 整首转换，不截断；逐级降级只为保证格式兼容与解码成功
        if force:
            quality_levels = [force]
        else:
            quality_levels = [
                ("192k", 2, 44100),
                ("128k", 2, 44100),
                ("96k",  1, 44100),
                ("64k",  1, 22050),
            ]

        for bitrate, channels, sample_rate in quality_levels:
            output_path = os.path.join(tmp_dir, "output.mp3")
            cmd = [
                ffmpeg_path, "-y", "-i", input_path,
                "-ac", str(channels),
                "-ar", str(sample_rate),
                "-acodec", "libmp3lame",
                "-ab", bitrate,
                output_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=120)
            if result.returncode != 0 or not os.path.exists(output_path):
                logger.warning("ffmpeg转换MP3失败[%s]: %s" % (bitrate, result.stderr[-200:] if result.stderr else ""))
                continue

            with open(output_path, "rb") as f:
                mp3_data = f.read()
            os.remove(output_path)

            ch_str = "立体声" if channels == 2 else "单声道"
            logger.info("音频转换MP3成功(整首): %s %s %dHz, %d bytes (%.1f KB)" % (
                bitrate, ch_str, sample_rate, len(mp3_data), len(mp3_data) / 1024
            ))
            return mp3_data

        logger.error("所有MP3码率级别均失败")
        return None

    except Exception as e:
        logger.error("音频转换MP3异常: %s" % e)
        return None
    finally:
        # 清理临时文件
        try:
            if os.path.exists(input_path):
                os.remove(input_path)
            output_path = os.path.join(tmp_dir, "output.mp3")
            if os.path.exists(output_path):
                os.remove(output_path)
            os.rmdir(tmp_dir)
        except Exception:
            pass


def _split_audio_to_segments(mp3_bytes: bytes, max_seconds: int = 50, max_mb: float = 3.8) -> list:
    """
    把整首 MP3 切成多个片段，每个片段时长 <= max_seconds 秒且大小 <= max_mb MB，
    以适配 QQ 语音消息「单条 <= 60s 且 <= 4MB」的限制。

    采用 ffmpeg segment 复用流（-c copy），不二次转码、无音质损失，
    切点在 MP3 帧边界，误差极小。返回片段 bytes 列表；失败返回空列表。
    """
    import tempfile
    import subprocess
    import os
    try:
        import imageio_ffmpeg
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        logger.error("imageio-ffmpeg 未安装，无法分段音频")
        return []

    tmp_dir = tempfile.mkdtemp(prefix="audio_seg_")
    full_path = os.path.join(tmp_dir, "full.mp3")
    try:
        with open(full_path, "wb") as f:
            f.write(mp3_bytes)

        out_pattern = os.path.join(tmp_dir, "seg_%03d.mp3")
        cmd = [
            ffmpeg_path, "-y", "-i", full_path,
            "-f", "segment",
            "-segment_time", str(max_seconds),
            "-reset_timestamps", "1",
            "-c", "copy",
            out_pattern,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=180)
        if proc.returncode != 0:
            logger.warning("ffmpeg分段失败: %s" % (proc.stderr[-200:] if proc.stderr else ""))

        segs = sorted(
            p for p in os.listdir(tmp_dir)
            if p.startswith("seg_") and p.endswith(".mp3")
        )
        result = []
        for p in segs:
            fp = os.path.join(tmp_dir, p)
            with open(fp, "rb") as f:
                data = f.read()
            if not data:
                continue
            # 兜底：单段仍严重超限则丢弃（理论上 50s 不会触发）
            if len(data) / 1024 / 1024 > max_mb * 2:
                logger.warning("分段 %s 仍超限(%.1fMB)，丢弃" % (p, len(data) / 1024 / 1024))
                continue
            result.append(data)

        logger.info("音频分段完成: 共 %d 段" % len(result))
        return result
    except Exception as e:
        logger.error("音频分段异常: %s" % e)
        return []
    finally:
        try:
            for p in os.listdir(tmp_dir):
                try:
                    os.remove(os.path.join(tmp_dir, p))
                except Exception:
                    pass
            os.rmdir(tmp_dir)
        except Exception:
            pass


async def _send_audio_segments(api, target_id: str, audio_url: str, msg_id: str = None,
                               content: str = "", headers: dict = None,
                               upload_fn=None, send_media_fn=None):
    """
    通用：下载音频 -> 整首转MP3 -> 分段 -> 逐段以语音消息(file_type=3)发送。
    每段时长 <= 50s、大小 <= 4MB，满足 QQ 语音限制；短歌(<=50s)仅一段，行为不变。
    返回是否至少有一段发送成功。
    """
    if headers:
        audio_bytes = await _download_media_bytes_with_headers(audio_url, headers=headers, timeout=30, max_size_mb=25)
    else:
        audio_bytes = await _download_media_bytes(audio_url, timeout=30, max_size_mb=25)
    if not audio_bytes:
        logger.error("下载音频失败，无法发送: %s" % audio_url[:80])
        return None
    logger.info("音频下载成功: %d bytes (%.1f KB)" % (len(audio_bytes), len(audio_bytes) / 1024))

    # 整首转 MP3（不截断）
    mp3_bytes = _convert_to_mp3(audio_bytes)
    if not mp3_bytes:
        logger.error("音频转换MP3失败，尝试直接分段原始音频")
        mp3_bytes = audio_bytes

    # 分段
    segs = _split_audio_to_segments(mp3_bytes)
    if not segs:
        logger.warning("分段失败，回退为整首单条发送（长歌可能超限失败）")
        segs = [mp3_bytes]
    total = len(segs)

    ok = False
    for i, seg in enumerate(segs, 1):
        seg_content = ""
        if total > 1:
            seg_content = "🎧 语音试听（第 %d/%d 段）" % (i, total)
        elif content:
            seg_content = content
        file_info = await upload_fn(api, target_id, 3, seg)  # file_type=3 语音
        if not file_info:
            logger.error("上传语音分段 %d/%d 失败" % (i, total))
            continue
        res = await send_media_fn(api, target_id, file_info, msg_type=7,
                                  content=seg_content, msg_id=msg_id)
        if res:
            ok = True
        else:
            logger.warning("发送语音分段 %d/%d 失败" % (i, total))
    return ok

async def send_group_audio_bytes(api, group_openid: str, audio_bytes: bytes,
                                  content: str = "", msg_id: str = None):
    """
    发送已下载的音频bytes到群聊（语音消息）。
    """
    file_info = await _upload_group_file(api, group_openid, 3, audio_bytes)
    if not file_info:
        return None
    return await _send_group_media(api, group_openid, file_info, msg_type=7,
                                   content=content or "", msg_id=msg_id)


def build_keyboard_command(label: str, command: str, button_id: str = None, enter: bool = False) -> dict:
    """
    构建指令按钮(type=2)的keyboard结构
    点击后自动在输入框填入 @bot command
    - enter=False: 仅填入输入框，不自动发送
    - enter=True: 自动填入并发送
    """
    return {
        "content": {
            "rows": [
                {
                    "buttons": [
                        {
                            "id": button_id or ("btn_" + command),
                            "render_data": {
                                "label": label,
                                "visited_label": label,
                                "style": 1,
                            },
                            "action": {
                                "type": 2,  # 指令按钮
                                "permission": {"type": 2},  # 所有人可操作
                                "data": command,
                                "enter": enter,
                                "unsupport_tips": "请更新QQ版本",
                            },
                        }
                    ]
                }
            ]
        }
    }


def build_keyboard_multi(buttons_config: list) -> dict:
    """
    构建多按钮keyboard结构
    buttons_config: [{"label": "按钮文字", "command": "指令", "id": "按钮ID", "enter": False}, ...]
    最多5个按钮一行
    """
    buttons = []
    for cfg in buttons_config:
        buttons.append({
            "id": cfg.get("id", "btn_" + cfg["command"]),
            "render_data": {
                "label": cfg["label"],
                "visited_label": cfg.get("visited_label", cfg["label"]),
                "style": cfg.get("style", 1),
            },
            "action": {
                "type": 2,
                "permission": {"type": 2},
                "data": cfg["command"],
                "enter": cfg.get("enter", False),
                "unsupport_tips": "请更新QQ版本",
            },
        })
    # QQ inline_keyboard 渲染宽度有限，每行超过 5 个按钮会强制压缩 label
    # 仅显示图标、文字被吞掉，这里真正按 5 个一行分排
    rows = []
    for i in range(0, len(buttons), 5):
        rows.append({"buttons": buttons[i:i+5]})
    return {"content": {"rows": rows}}


def build_keyboard_callback(label: str, callback_data: str, button_id: str = None) -> dict:
    """
    构建回调按钮(type=1)的keyboard结构
    点击后触发 INTERACTION_CREATE 事件
    """
    return {
        "content": {
            "rows": [
                {
                    "buttons": [
                        {
                            "id": button_id or ("cb_" + callback_data),
                            "render_data": {
                                "label": label,
                                "visited_label": label,
                                "style": 1,
                            },
                            "action": {
                                "type": 1,  # 回调按钮
                                "permission": {"type": 2},
                                "data": callback_data,
                                "unsupport_tips": "请更新QQ版本",
                            },
                        }
                    ]
                }
            ]
        }
    }


# ============ 群消息撤回 ============

async def recall_group_message(api, group_openid: str, message_id: str):
    """
    撤回群消息
    DELETE /v2/groups/{group_openid}/messages/{message_id}
    需要：机器人被群主设置为群管理员
    限制：发送超过2分钟的消息不可撤回
    """
    from botpy.http import Route
    try:
        route = Route("DELETE", "/v2/groups/{group_openid}/messages/{message_id}",
                      group_openid=group_openid, message_id=message_id)
        await api._http.request(route)
        logger.info("撤回群消息成功: %s" % message_id)
        return True
    except Exception as e:
        logger.error("撤回群消息失败: %s" % e)
        return False


async def recall_c2c_message(api, user_openid: str, message_id: str):
    """
    撤回私聊(C2C)消息
    DELETE /v2/users/{openid}/messages/{message_id}
    限制：发送超过2分钟的消息不可撤回
    """
    from botpy.http import Route
    try:
        route = Route("DELETE", "/v2/users/{openid}/messages/{message_id}",
                      openid=user_openid, message_id=message_id)
        await api._http.request(route)
        logger.info("撤回私聊消息成功: %s" % message_id)
        return True
    except Exception as e:
        logger.error("撤回私聊消息失败: %s" % e)
        return False


async def recall_message_for_scene(api, scene: str, target_id: str, message_id: str):
    """按场景撤回消息（群/私聊）。target_id 为对应原生 openid。"""
    if scene == "group":
        return await recall_group_message(api, target_id, message_id)
    elif scene == "c2c":
        return await recall_c2c_message(api, target_id, message_id)
    logger.warning("暂不支持撤回场景 %s 的消息" % scene)
    return False


# ============ 时间工具 ============

def today_str() -> str:
    """返回今天的日期字符串 YYYY-MM-DD"""
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d")


def yesterday_str() -> str:
    """返回昨天的日期字符串"""
    from datetime import datetime, timedelta
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


def format_duration(seconds: int) -> str:
    """将秒数格式化为 mm:ss"""
    m, s = divmod(seconds, 60)
    return "%02d:%02d" % (m, s)


# ============ C2C/CHANNEL 富媒体支持 ============
# 之前只有群聊有富媒体上传/发送，C2C 和频道都缺。
# 这里补齐两个场景的上传和发送，让视频解析等需要发媒体的功能也能在私聊/频道里工作。

async def _upload_c2c_file(api, user_openid: str, file_type: int,
                        file_bytes: bytes = None, url: str = None) -> str:
    """上传富媒体文件到 C2C（私聊），返回 file_info。官方 API: POST /v2/users/{openid}/files
    - file_type: 1=图片, 2=视频, 3=语音
    - url 模式（推荐）：QQ 服务器侧拉取，无 base64 膨胀，可发原始画质、绕开 413；
      file_data 模式（兜底）：本地 bytes 经 base64 编码上传。
    """
    from botpy.http import Route

    if url:
        payload = {
            "file_type": file_type,
            "url": url,
            "file_data": "",
            "srv_send_msg": False,
        }
        mode = "url"
        total = 90
    else:
        if not file_bytes:
            logger.error("上传C2C文件参数错误：既无 url 也无 file_bytes")
            return None
        import base64
        file_data_b64 = base64.b64encode(file_bytes).decode("utf-8")
        payload = {
            "file_type": file_type,
            "url": "",
            "file_data": file_data_b64,
            "srv_send_msg": False,
        }
        mode = "base64"
        total = 30

    await api._http.check_session()
    headers = dict(api._http._headers)
    route = Route("POST", "/v2/users/{openid}/files", openid=user_openid)
    route.is_sandbox = api._http.is_sandbox

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(route.url, json=payload, headers=headers,
                                    timeout=aiohttp.ClientTimeout(total=total)) as resp:
                body = await resp.text()
                if resp.status in (200, 202, 204):
                    data = json.loads(body)
                    file_info = data.get("file_info", "")
                    logger.info("上传C2C文件成功(%s): file_type=%s, file_info=%s" % (mode, file_type, file_info[:50]))
                    return file_info
                logger.error("上传C2C文件失败(%s): status=%s, body=%s" % (mode, resp.status, body[:200]))
                return None
    except Exception as e:
        logger.error("上传C2C文件异常(%s): %s" % (mode, e))
        return None


async def _send_c2c_media(api, user_openid: str, file_info: str, msg_type: int,
                          content: str = "", msg_id: str = None):
    """发送带 media 的 C2C（私聊）消息。

    - msg_type: 1=图文混排, 7=富媒体
    """
    if increment_api_call:
        increment_api_call()
    from botpy.http import Route

    async def _do_send(use_msg_id: bool):
        payload = {
            "msg_type": msg_type,
            "content": content or "",
            "media": {"file_info": file_info},
            "msg_seq": next_seq(),
        }
        if msg_id and use_msg_id:
            payload["msg_id"] = msg_id
        route = Route("POST", "/v2/users/{openid}/messages", openid=user_openid)
        return await api._http.request(route, json=payload)

    try:
        result = await _do_send(use_msg_id=True)
        logger.info("发送C2C媒体消息成功: %s" % result)
        if record_bot_reply:
            chat_id = "u:" + user_openid
            record_bot_reply(chat_id, content or "[媒体]", "media")
        return result
    except Exception as e:
        err_msg = str(e)
        logger.error("发送C2C媒体消息失败: %s" % e)
        if "被动回复" in err_msg and msg_id:
            try:
                result = await _do_send(use_msg_id=False)
                logger.info("主动重试发送C2C媒体消息成功: %s" % result)
                if record_bot_reply:
                    chat_id = "u:" + user_openid
                    record_bot_reply(chat_id, content or "[媒体]", "media")
                return result
            except Exception as e2:
                logger.error("主动重试发送C2C媒体也失败: %s" % e2)
        return None


async def send_c2c_video_bytes(api, user_openid: str, video_bytes: bytes,
                                content: str = "", msg_id: str = None,
                                fallback_link: str = None):
    """发送视频字节流到 C2C 私聊。

    用法：先用 _download_media_bytes_with_headers 下载视频（带 headers），
    再调本函数上传+发送。若超 12MB 自动降画质重编码（目标 10MB）；
    压缩后仍超 15MB 或上传失败，则降级为发外链文字。
    """
    if len(video_bytes) > 12 * 1024 * 1024:
        logger.info("视频 %.1fMB 超 QQ 上传软限，尝试降画质重编码..." % (len(video_bytes) / 1024 / 1024))
        compressed = await asyncio.to_thread(_compress_video_bytes, video_bytes, 10)
        if compressed:
            logger.info("视频压缩完成: %.1fMB → %.1fMB" % (len(video_bytes)/1024/1024, len(compressed)/1024/1024))
            video_bytes = compressed
    if len(video_bytes) > 15 * 1024 * 1024:
        link = fallback_link or ""
        logger.warning("视频压缩后仍达 %.1fMB，降级为发外链" % (len(video_bytes)/1024/1024))
        from modules.common import send_text
        if link:
            await send_text(api, "c2c", user_openid,
                            "⚠️ 视频文件过大（%.1fMB）已自动降画质仍超出发送上限，请点击链接查看：\n%s" % (len(video_bytes)/1024/1024, link),
                            msg_id=msg_id)
        else:
            await send_text(api, "c2c", user_openid,
                            "⚠️ 视频文件过大（%.1fMB）已自动降画质仍超出发送上限" % (len(video_bytes)/1024/1024),
                            msg_id=msg_id)
        return None
    file_info = await _upload_c2c_file(api, user_openid, 2, video_bytes)
    if not file_info:
        link = fallback_link or ""
        logger.warning("视频上传失败，降级为发外链")
        from modules.common import send_text
        if link:
            await send_text(api, "c2c", user_openid,
                            "⚠️ 视频上传失败，请点击链接查看：\n%s" % link,
                            msg_id=msg_id)
        else:
            await send_text(api, "c2c", user_openid,
                            "⚠️ 视频上传失败", msg_id=msg_id)
        return None
    return await _send_c2c_media(api, user_openid, file_info, msg_type=7,
                                 content=content, msg_id=msg_id)


async def send_c2c_video(api, user_openid: str, video_url: str, msg_id: str = None,
                          content: str = None, headers: dict = None,
                          fallback_link: str = None):
    """从 URL 下载视频并发送到 C2C 私聊。

    - headers: 自定义请求头（用于 B 站等需要 Referer 的网站）
    - 下载放宽到 200MB 硬上限；超 12MB 自动降画质重编码（目标 10MB）。
    - 上传失败时降级为发外链文字。
    - fallback_link: 失败时发给用户的外链，默认就是 video_url。
    """
    link_for_fallback = fallback_link or video_url
    # ① 优先 url 模式直传（无需自定义请求头的源）：原始画质、零转码、无 base64 膨胀、绕开 413
    if not headers:
        file_info = await _upload_c2c_file(api, user_openid, 2, url=video_url)
        if file_info:
            logger.info("C2C 视频 url 模式直传成功（原始画质），跳过下载/压缩")
            return await _send_c2c_media(api, user_openid, file_info, msg_type=7,
                                         content=content or "", msg_id=msg_id)
        logger.info("C2C 视频 url 模式直传失败，回退到下载+压缩方案")
    # ②.5 远程 >100MB 直接发链接
    if not headers:
        cl = await _head_content_length(video_url)
        if cl and cl > 100 * 1024 * 1024:
            link = link_for_fallback
            logger.info("C2C 视频 %.1fMB 超官方 Bot API 100MB 上限，直接发原链接" % (cl/1024/1024))
            from modules.common import send_text
            await send_text(api, "c2c", user_openid,
                            "⚠️ 视频文件过大（%.1fMB）超过官方机器人发送上限，请点击链接查看全画质：\n%s" % (cl/1024/1024, link),
                            msg_id=msg_id)
            return None
    # ② 兜底：下载到本地 → 交给 send_c2c_video_bytes 做压缩/外链
    if headers:
        video_bytes = await _download_media_bytes_with_headers(video_url, headers=headers, timeout=180, max_size_mb=200)
    else:
        video_bytes = await _download_media_bytes(video_url, timeout=180, max_size_mb=200)
    if not video_bytes:
        logger.error("下载视频失败，无法发送: %s" % video_url[:80])
        return None
    return await send_c2c_video_bytes(api, user_openid, video_bytes,
                                       content=content or "", msg_id=msg_id,
                                       fallback_link=link_for_fallback)


async def send_c2c_image(api, user_openid: str, image_url: str, msg_id: str = None,
                          content: str = None):
    """从 URL 下载图片并发送到 C2C 私聊。"""
    image_bytes = await _download_media_bytes(image_url)
    if not image_bytes:
        logger.error("下载图片失败: %s" % image_url)
        return None
    if not _looks_like_image(image_bytes):
        logger.error("下载内容非图片（疑似防盗链 HTML/错误页）: url=%s head=%s" % (
            image_url[:80], image_bytes[:16].hex()))
        return None
    file_info = await _upload_c2c_file(api, user_openid, 1, image_bytes)
    if not file_info:
        return None
    return await _send_c2c_media(api, user_openid, file_info, msg_type=7,
                                 content=content or "", msg_id=msg_id)


async def send_c2c_local_image(api, user_openid: str, image_bytes: bytes,
                                content: str = "", msg_id: str = None):
    """
    发送本地图片（bytes）到 C2C 私聊。
    逻辑与 send_group_local_image 一致，仅上传/发送走 C2C 接口。
    注意：不支持同时发送 keyboard（media 与 keyboard 互斥）。
    """
    file_info = await _upload_c2c_file(api, user_openid, 1, image_bytes)
    if not file_info:
        return None
    return await _send_c2c_media(api, user_openid, file_info, msg_type=7,
                                 content=content, msg_id=msg_id)



async def send_c2c_audio(api, user_openid: str, audio_url: str, msg_id: str = None,
                          content: str = "", headers: dict = None):
    """
    发送 C2C 私聊语音消息（整首歌分段发送，每段 <= 50s 且 <= 4MB）。
    逻辑与 send_group_audio 一致，仅上传/发送走 C2C 接口。
    """
    return await _send_audio_segments(
        api, user_openid, audio_url, msg_id=msg_id, content=content, headers=headers,
        upload_fn=_upload_c2c_file, send_media_fn=_send_c2c_media,
    )

async def send_c2c_audio_bytes(api, user_openid: str, audio_bytes: bytes,
                               content: str = "", msg_id: str = None):
    """发送已下载的音频bytes到C2C私聊（语音消息）。"""
    file_info = await _upload_c2c_file(api, user_openid, 3, audio_bytes)
    if not file_info:
        return None
    return await _send_c2c_media(api, user_openid, file_info, msg_type=7,
                                 content=content or "", msg_id=msg_id)


# ============ 场景无关的统一富媒体发送 ============
# 按 scene 路由到对应场景的发送函数，避免在每个模块里重复写 if/else。

async def send_video_bytes_for_scene(api, scene: str, target_id: str, video_bytes: bytes,
                                      content: str = "", msg_id: str = None,
                                      fallback_link: str = None):
    """场景无关的统一视频发送（已下载好视频字节的场景）

    scene: ChatScene.GROUP / C2C / CHANNEL
    CHANNEL 当前未实现视频上传（C2C API 不支持频道），会返回 None 并 log 警告。
    fallback_link: 上传失败时降级发给用户的外链（一般是用户分享的原视频 URL）。
    """
    if scene == ChatScene.GROUP:
        return await send_group_video_bytes(api, target_id, video_bytes, content=content, msg_id=msg_id,
                                            fallback_link=fallback_link)
    if scene == ChatScene.C2C:
        return await send_c2c_video_bytes(api, target_id, video_bytes, content=content, msg_id=msg_id,
                                          fallback_link=fallback_link)
    logger.warning("视频发送暂不支持 channel 场景（target=%s）" % target_id)
    return None


async def send_video_for_scene(api, scene: str, target_id: str, video_url: str,
                                msg_id: str = None, content: str = None, headers: dict = None,
                                fallback_link: str = None):
    """场景无关的统一视频发送（从 URL 下载后发送）"""
    if scene == ChatScene.GROUP:
        return await send_group_video(api, target_id, video_url, msg_id=msg_id,
                                      content=content, headers=headers,
                                      fallback_link=fallback_link)
    if scene == ChatScene.C2C:
        return await send_c2c_video(api, target_id, video_url, msg_id=msg_id,
                                    content=content, headers=headers,
                                    fallback_link=fallback_link)
    logger.warning("视频发送暂不支持 channel 场景（target=%s）" % target_id)
    return None


async def send_image_for_scene(api, scene: str, target_id: str, image_url: str,
                                msg_id: str = None, content: str = None):
    """场景无关的统一图片发送"""
    if scene == ChatScene.GROUP:
        return await send_group_image(api, target_id, image_url, msg_id=msg_id, content=content)
    if scene == ChatScene.C2C:
        return await send_c2c_image(api, target_id, image_url, msg_id=msg_id, content=content)
    logger.warning("图片发送暂不支持 channel 场景（target=%s）" % target_id)
    return None


async def send_local_image_for_scene(api, scene: str, target_id: str, image_bytes: bytes,
                                      msg_id: str = None, content: str = ""):
    """场景无关的统一本地图片（bytes）发送"""
    if scene == ChatScene.GROUP:
        return await send_group_local_image(api, target_id, image_bytes,
                                            content=content, msg_id=msg_id)
    if scene == ChatScene.C2C:
        return await send_c2c_local_image(api, target_id, image_bytes,
                                          content=content, msg_id=msg_id)
    logger.warning("本地图片发送暂不支持 channel 场景（target=%s）" % target_id)
    return None


async def send_audio_for_scene(api, scene: str, target_id: str, audio_url: str,
                                msg_id: str = None, content: str = "", headers: dict = None):
    """场景无关的统一语音发送（从 URL 下载转MP3后发送）"""
    if scene == ChatScene.GROUP:
        return await send_group_audio(api, target_id, audio_url, msg_id=msg_id,
                                      content=content, headers=headers)
    if scene == ChatScene.C2C:
        return await send_c2c_audio(api, target_id, audio_url, msg_id=msg_id,
                                    content=content, headers=headers)
    logger.warning("语音发送暂不支持 channel 场景（target=%s）" % target_id)
    return None


# ================================================================
# 整条语音发送（不分段）
# ================================================================

async def _send_audio_whole(api, target_id: str, audio_url: str, msg_id: str = None,
                            content: str = "", headers: dict = None,
                            upload_fn=None, send_media_fn=None):
    """
    下载音频 -> 整首转 MP3（标准音质，优先 192k/128k 立体声）-> 作为【单条】语音消息
    (file_type=3) 发送，不分段。
    仅受 QQ 语音消息的大小/时长上限约束；超出时发送失败（返回 False），调用方应回退分段。
    """
    if headers:
        audio_bytes = await _download_media_bytes_with_headers(audio_url, headers=headers, timeout=30, max_size_mb=25)
    else:
        audio_bytes = await _download_media_bytes(audio_url, timeout=30, max_size_mb=25)
    if not audio_bytes:
        logger.error("下载音频失败，无法发送整条语音: %s" % audio_url[:80])
        return False

    mp3_bytes = _convert_to_mp3(audio_bytes)
    if not mp3_bytes:
        logger.error("音频转换 MP3 失败，无法发送整条语音")
        return False

    file_info = await upload_fn(api, target_id, 3, mp3_bytes)  # file_type=3 语音
    if not file_info:
        # 整条上传失败（最可能是单条大小/时长隐性上限）。
        # 先用低码率（64k 单声道 ≈ 2.4MB/5min）把整首压到 < 4MB 重试一次。
        mb = len(mp3_bytes) / 1024 / 1024
        logger.warning("整条语音上传失败(%.1fMB)，尝试低码率整条重试" % mb)
        low_bytes = _convert_to_mp3(audio_bytes, force=("64k", 1, 22050))
        if low_bytes:
            file_info = await upload_fn(api, target_id, 3, low_bytes)
        if not file_info:
            logger.error("低码率整条上传仍失败（整条超限），回退分段")
            return False
        mp3_bytes = low_bytes
    res = await send_media_fn(api, target_id, file_info, msg_type=7,
                              content=content or "", msg_id=msg_id)
    if res:
        logger.info("整条语音发送成功: %d bytes (%.1f MB)" % (len(mp3_bytes), len(mp3_bytes) / 1024 / 1024))
        return True
    logger.warning("发送整条语音失败（可能超出 QQ 语音时长上限）")
    return False


async def send_group_audio_whole(api, group_openid: str, audio_url: str, msg_id: str = None,
                                 content: str = "", headers: dict = None):
    """整首歌作为单条群语音发送（不分段）"""
    return await _send_audio_whole(
        api, group_openid, audio_url, msg_id=msg_id, content=content, headers=headers,
        upload_fn=_upload_group_file, send_media_fn=_send_group_media,
    )


async def send_c2c_audio_whole(api, user_openid: str, audio_url: str, msg_id: str = None,
                               content: str = "", headers: dict = None):
    """整首歌作为单条 C2C 私聊语音发送（不分段）"""
    return await _send_audio_whole(
        api, user_openid, audio_url, msg_id=msg_id, content=content, headers=headers,
        upload_fn=_upload_c2c_file, send_media_fn=_send_c2c_media,
    )


async def send_audio_whole_for_scene(api, scene: str, target_id: str, audio_url: str,
                                     msg_id: str = None, content: str = "", headers: dict = None):
    """场景无关的统一「整条语音」发送（不分段）。"""
    if scene == ChatScene.GROUP:
        return await send_group_audio_whole(api, target_id, audio_url, msg_id=msg_id,
                                            content=content, headers=headers)
    if scene == ChatScene.C2C:
        return await send_c2c_audio_whole(api, target_id, audio_url, msg_id=msg_id,
                                          content=content, headers=headers)
    logger.warning("整条语音发送暂不支持 channel 场景（target=%s）" % target_id)
    return False
