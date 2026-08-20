# botpy 机器人

# 官方文档: https://bot.q.qq.com/wiki/develop/pythonsdk/

# 功能：群管系统 + 签到系统 + 视频系统 + 音乐系统 + 娱乐系统 + 工具系统

import os

import re

import time

import json

import asyncio

import threading

import botpy

from botpy import logging

from botpy.interaction import Interaction

from botpy.message import GroupMessage

from botpy.types.message import Message

# 菜单顶部封面图采用本地文件 assets/menu_banner.{jpg,png,webp,gif}，

# 由 _send_help 在每次发菜单时优先上传发送（详见 _send_help）。

# ===== 小流萤体验群（菜单底部「加入小流萤体验群」链接按钮）=====
#
# 加群方式：QQ 链接按钮（type=0），点击后直接进入群聊界面。
# 群链接为腾讯官方「universal-share」加群分享链接；qun.qq.com 为腾讯自家域，
# QQ 链接按钮白名单内可直接跳转，无需发送二维码。
#
# ⚠️ 开源注意：体验群链接会暴露真实群号与邀请人 openid，请勿硬编码到本文件！
# 真正生效的位置是「控制台 → 运行设置 → 体验群加入链接」(运行时配置 experience_group.url)，
# 留空则菜单里不会显示「加入体验群」按钮。
EXPERIENCE_GROUP_JOIN_URL = ""

from modules.common import (

    logger,

    clean_content,

    is_duplicate,

    is_msg_duplicate,

    ChatScene,

    make_chat_id,

    is_group_chat,

    next_seq,

    send_text,

    send_text_with_keyboard,

    send_local_image_for_scene,

    send_group_text,

    send_group_image,

    send_group_text_with_keyboard,

    build_keyboard_multi,

    build_keyboard_command,

    fetch_yiyan,

    format_yiyan_line,

)

from modules.config import APPID, SECRET

from modules import bot_manager

def _avatar_url(openid, appid=None):

    """根据 openid 生成 QQ 官方头像 URL（可指定 bot appid）。"""

    if not openid or not (appid or APPID):

        return ""

    return "https://thirdqq.qlogo.cn/qqapp/%s/%s/100" % (appid or APPID, openid)

# 强制 stdout/stderr 用 UTF-8，避免 Windows 默认 GBK 让中文日志变成乱码

try:

    sys.stdout.reconfigure(encoding="utf-8")

    sys.stderr.reconfigure(encoding="utf-8")

except Exception:

    pass


from modules.group_admin import GroupAdminManager

# 框架级全局实例：用于分发前的违禁词预检（modules/group_admin.py 作为共享库，
# 始终存在；plugins/group_admin/ 目录包是可选插件，处理插件级群管功能）
group_admin = GroupAdminManager()



from modules.plugin_registry import PluginContext, PluginDescriptor, register_plugin, get_plugin, get_external_plugins, scan_external_plugins, reload_external_plugins, is_plugin_enabled, snapshot_plugins, get_plugin_module_attr

from console_server import (

    start_console_server, update_status, record_message, console_log,

    record_bot_reply, increment_api_call,

    get_group_display_name, get_user_avatar_url,

    bind_group_qq_number, bind_user_qq_number,

    get_group_qq_number, get_user_qq_number,

    _restart_bot, _shutdown_bot, _get_status_data,

    fetch_and_save_qq_info, get_user_detail_info,

    is_feature_enabled, register_bot_bridge, append_ws_log, get_runtime_setting_effective,

    GROUP_BOT_MAP, USER_BOT_MAP,

    is_sub_feature_enabled, resolve_sub_feature, sub_feature_key_for_cmd,

    get_master_feature, get_sub_features_by_master,

    update_group_contact, remove_group_contact,

    update_friend_contact, remove_friend_contact,

    chat_with_ai_for_bot, get_default_ai_provider,

    inc_groups_joined_today, inc_groups_left_today,

    inc_friends_added_today, inc_friends_removed_today,

    sync_contact_from_message,

    _rollover_today_counters_if_needed, _status,

)

# 预热 AI 人格模块：避免运行期处理 AI 消息时 `from modules.ai_persona import
# build_ai_context` 与控制台 HTTP 线程的同模块 import 在全局 import 锁上竞争死锁
# （导致 /api/ai/persona、/api/ai/knowledge 等端点长时间无响应）。
import modules.ai_persona as _ai_persona_mod  # noqa: E402,F401

from modules.rate_limiter import is_allowed as _rate_is_allowed

from modules.bot_health import (

    record_command, record_event, record_dedup, record_plugin,

    record_ai_call, record_stage, record_ws, set_request_appid,

    PLUGIN_TIMEOUT_MS,

)

# ============ 指令计数 ============

_cmd_counter = [0]

def _bot_status_command_count():

    _cmd_counter[0] += 1

    return _cmd_counter[0]

# ============ 模块实例 ============


# 群管菜单：机器人是否为本群管理员的缓存 group_openid -> (is_admin, expire_ts)

_BOT_ADMIN_STATUS_CACHE = {}






# ============ 内置插件注册（统一插件契约）============

# 每个内置功能模块注册一个 PluginDescriptor；dispatch 适配器精确复刻原 _time_plugin 调用，

# 保证功能行为零回归。分发链改造（DISPATCH_PLAN 注册表驱动）见 _dispatch_via_registry（任务 #390）。


# 注册内置插件：priority 与后续 DISPATCH_PLAN 顺序一致（越小越靠前）








# ============ 外置插件热加载看门狗 ============

# 周期性扫描 plugins/ 目录，对变更/新增/删除的文件重注册，无需重启 bot（用户明确要求）。

_EXTERNAL_PLUGIN_WATCH_INTERVAL = 3.0  # 秒

def _external_plugin_watcher():

    """后台守护线程：周期性热加载外置插件。改 plugins/ 下文件即时生效。"""

    while True:

        try:

            stats = reload_external_plugins()

            if any(stats.values()):

                logger.info("[plugin] 外置插件热加载: %s" % stats)

        except Exception as e:

            logger.error("[plugin] 外置插件热加载异常: %s" % e)

        time.sleep(_EXTERNAL_PLUGIN_WATCH_INTERVAL)

# ============ 分发计划（注册表驱动）============

# 框架级特殊步骤与插件（内置 + 外置，统一走 plugin_registry）按固定顺序交织。

# 条目：("plugin", key) 走注册表 dispatch；(<"fw", name) 走 _run_fw_step 对应的框架步骤。

# 顺序精确保留原 _handle_message_inner 的内联分发行为（含游戏优先路由 / 子功能门控 /

# 个人信息指令 / 帮助子菜单导航 / 体验群 / 帮助菜单 / 违禁词 / AI 兜底的相对位置）。

DISPATCH_PLAN = [

    ("fw", "game_idiom_preroute"),       # 猜成语进行中优先

    ("fw", "subfeature_gate"),           # 子功能（按钮级）开关门控

    ("fw", "profile_command"),           # 绑群号/绑QQ/我的信息

    ("plugin", "checkin"),

    # 注：tools/study/video/image/game 已拆细为 tool_*/study_*/video_*/image_*/game_* 目录包，
    # 由下方 external_plugins fw 步骤按 priority 统一分发（聚合 key 在注册表不存在，此处留空）。

    ("plugin", "music"),

    ("fw", "help_submenu_nav"),          # 帮助子菜单导航 + 返回主菜单（必须在 novel 之前）

    ("plugin", "novel"),

    ("plugin", "group_admin"),           # 适配器内置 is_group 门控

    ("fw", "external_plugins"),          # 外置插件（按各自 priority 排序，置于内置之后）

    ("fw", "join_experience_group"),     # 加入体验群

    ("fw", "help_menu"),                 # 帮助菜单

    ("fw", "banned_word_noncmd"),        # 非指令消息违禁词（仅群聊，不终止分发）

    ("fw", "ai_fallback"),               # AI 对话兜底（最后）

]

# ============ 关键词触发机制 ============

# 精确匹配关键词（消息内容完全等于这些词才触发）

_EXACT_KEYWORDS = {

    # 签到

    "签到", "签到排名", "签到查询", "抽奖",

    # 视频

    "帅哥视频", "风景视频", "变装视频", "cos视频", "漫剪视频", "游戏视频",

    # 音乐

    "随机音乐", "音源", "音源选择",

    # 娱乐

    "五子棋", "五子棋AI", "AI对战", "五子棋双人", "二人对战", "五子棋排行",

    "选择黑方", "选择白方", "猜成语", "脑筋急转弯", "急转弯", "猜谜语", "谜语", "猜谜",

    "象棋", "象棋AI", "象棋AI红", "象棋AI黑", "象棋双人", "象棋双人红", "象棋双人黑", "象棋排行", "结束象棋",

    "认输", "结束棋局", "结束对局",

    # 工具

    "视频解析", "取消", "天气",

    "导航", "导航规划", "旅游", "旅游查询", "景点",

    # 群管

    "违禁词设置", "整点报时", "报时开关",

    "报时设置", "报时间隔设置", "报时时段设置", "立即报时",

    "入群通知", "入群欢迎词设置", "入群通知开关",

    # 个人信息设置

    "我的信息",

    # 帮助

    "帮助", "功能", "菜单", "使用帮助",

    # 帮助子菜单导航

    "签到菜单", "视频菜单", "音乐菜单", "娱乐菜单", "工具菜单", "群管菜单", "学习菜单", "小说菜单", "返回主菜单",

    # 学习系统（只保留「学习菜单」作为主菜单入口；「学习」「学习系统」过于通用，在群里聊天时被 @机器人 说这两个词很容易被误触发主菜单，反而吞掉了 AI 对话路径；需要进入学习系统时，请点主菜单里的「✚ 学习」按钮，或直接发送「学习菜单」/科目名）

    "学习菜单", "知识问答", "常识", "问答", "驾考", "驾考学习", "考驾照",
    "小学数学", "数学题", "数学",
    "古诗文", "古诗", "诗词",

    # 小说系统（精确匹配入口）

    "小说", "看小说", "读书", "看书", "在线阅读",

    # 体验群

    "加入体验群", "体验群", "加群", "加群二维码",

}

# 前缀匹配关键词（消息以这些词开头才触发，用于带参数的指令）

_PREFIX_KEYWORDS = [

    "点歌", "选歌", "音源",

    "下棋", "落子",

    "违禁词添加", "违禁词删除",

    "绑群号", "绑QQ",

    "天气 ",

    "王者",

    # 学习系统查询前缀

    "古诗文 ", "古诗 ", "诗词 ",

    # 工具系统查询前缀

    "导航 ", "旅游 ",

    # 整点报时（按群独立）设置参数：间隔 N / 时段 X-Y

    # 注意：去掉尾部空格，让『间隔1』『间隔 1』两种写法都能路由到群管处理器。

    "间隔", "时段",

    "欢迎词",

    # 小说系统（前缀匹配："看 书名" / "看 书名 第N章" / "章节 书名" / "小说 分类" / "读 书名" / "读 书名 第N章"）

    "看 ", "读 ", "章节 ", "小说 ",

]

# 插件元数据（_meta）动态合并的别名集合。启动时 + 每次保存 meta 后热重载。
# 这里只追加"额外别名"，不修改原 _EXACT_KEYWORDS 内的硬编码。
_EXTRA_TRIGGER_ALIASES: set = set()


def _refresh_plugin_meta_aliases() -> None:
    """从 plugin_center 读取所有外置插件 _meta.aliases，合并到 _EXTRA_TRIGGER_ALIASES。
    控制台保存 meta 后会自动调用本函数（plugin_center.save_plugin_meta 末尾触发）。
    """
    try:
        from modules import plugin_center
        metas = plugin_center.get_all_plugin_metas() or {}
    except Exception:
        return
    new_set: set = set()
    for k, m in metas.items():
        for a in (m.get("aliases") or []):
            a2 = str(a).strip()
            if a2:
                new_set.add(a2)
    _EXTRA_TRIGGER_ALIASES.clear()
    _EXTRA_TRIGGER_ALIASES.update(new_set)
    logger.info("[触发词] 合并 meta 别名完成，共 %d 个额外别名", len(new_set))


def _is_trigger(content: str) -> bool:

    """检查消息是否匹配任何触发关键词"""

    if not content:

        return False

    if content in _EXACT_KEYWORDS:

        return True

    if _EXTRA_TRIGGER_ALIASES and content in _EXTRA_TRIGGER_ALIASES:

        return True

    for kw in _PREFIX_KEYWORDS:

        if content.startswith(kw):

            return True

    return False

# ===== 管理员指令（重启 / 关机 / 状态）=====

# 名单存于 data/admin_list.json，元素为 QQ 号或 openid（字符串）。

# 控制台可编辑名单；名单内成员在 QQ 聊天中发送指令，机器人执行并回复。

# 依赖 from console_server import (...) 中的 _restart_bot / _shutdown_bot / _get_status_data。

_ADMIN_LIST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "admin_list.json")

_admin_cache = {"mtime": 0.0, "admins": set()}

def _load_admin_set():

    """读取管理员集合（带 mtime 缓存，文件变更后自动重载）。"""

    try:

        mtime = os.path.getmtime(_ADMIN_LIST_FILE)

    except OSError:

        mtime = 0.0

    if mtime != _admin_cache["mtime"]:

        _admin_cache["mtime"] = mtime

        admins = set()

        try:

            with open(_ADMIN_LIST_FILE, "r", encoding="utf-8") as _f:

                _data = json.load(_f)

            if isinstance(_data, dict) and isinstance(_data.get("admins"), list):

                for _x in _data["admins"]:

                    _s = str(_x).strip()

                    if _s:

                        admins.add(_s)

        except (OSError, ValueError):

            pass

        _admin_cache["admins"] = admins

    return _admin_cache["admins"]

_ADMIN_COMMANDS = {

    "restart": ["重启", "重开", "restart", "reboot"],

    "shutdown": ["关机", "停止", "关闭", "shutdown", "stop"],

    "status": ["状态", "运行状态", "status", "stat"],

    "help": ["管理员帮助", "管理帮助", "admin", "admin help", "管理指令"],

}

def _match_admin_command(content):

    if not content:

        return None

    _c = content.strip().lower()

    if not _c:

        return None

    for _cmd, _aliases in _ADMIN_COMMANDS.items():

        if _c in _aliases:

            return _cmd

    return None

def _format_admin_status():

    try:

        _s = _get_status_data()

    except Exception as _e:  # noqa: BLE001

        return "⚠️ 获取状态失败：%s" % _e

    _ag = _s.get("active_games", {}) or {}

    _game_str = "五子棋 %s / 成语 %s" % (_ag.get("gomoku", 0), _ag.get("idiom", 0))

    _online = "✅ 在线" if _s.get("online") else "⭕ 离线"

    # CPU / 内存 / GPU 占用

    _cpu = _s.get("cpu") or {}

    _cpu_p = _cpu.get("percent") if isinstance(_cpu, dict) else None

    _cpu_str = ("%.1f%%" % _cpu_p) if _cpu_p is not None else "N/A"

    _mem = _s.get("mem")

    if isinstance(_mem, dict) and _mem.get("percent") is not None:

        _mem_str = "%.1f%% (%s/%sGB)" % (

            _mem["percent"],

            _mem.get("used_gb", "?"),

            _mem.get("total_gb", "?"),

        )

    else:

        _mem_str = "N/A"

    _gpu = _s.get("gpu") or {}

    _gpu_lines = []

    if _gpu.get("available") and _gpu.get("devices"):

        for _i, _d in enumerate(_gpu["devices"]):

            _du = _d.get("util_percent")

            _mu = _d.get("mem_used_mb")

            _mt = _d.get("mem_total_mb")

            _seg = []

            if _du is not None:

                _seg.append("负载%d%%" % _du)

            if _mu is not None and _mt is not None:

                _seg.append("显存%.1f/%.1fGB" % (_mu / 1024.0, _mt / 1024.0))

            _tag = "GPU%d" % _i if len(_gpu["devices"]) > 1 else "GPU"

            _gpu_lines.append("%s %s%s" % (

                _tag, _d.get("name", "未知显卡"),

                (" " + " ".join(_seg)) if _seg else "",

            ))

    else:

        _gpu_lines = ["无"]

    _gpu_str = "  |  ".join(_gpu_lines)

    return "\n".join([

        "🤖 %s 运行状态" % (_s.get("bot_name") or "机器人"),

        "──────────────",

        "%s（已运行 %s）" % (_online, _s.get("uptime_str") or "00:00:00"),

        "💬 消息总数：%s" % _s.get("message_count", 0),

        "📟 指令次数：%s" % _s.get("command_count", 0),

        "🌐 API 调用：%s" % _s.get("api_call_count", 0),

        "🎮 活跃游戏：%s" % _game_str,

        "🚫 违禁词数：%s" % _s.get("banned_word_count", 0),

        "👥 活跃会话：%s" % _s.get("active_groups", 0),

        "💻 CPU 占用：%s" % _cpu_str,

        "🧠 内存占用：%s" % _mem_str,

        "🎛 GPU 占用：%s" % _gpu_str,

    ])

async def _handle_admin_command(api, scene, target_id, cmd, msg_id, event_id):

    """执行管理员指令并回复。重启/关机调用 console_server 的同名函数（与控制台按钮共用一套逻辑）。"""

    if cmd == "restart":

        await send_text(api, scene, target_id, "🔄 收到管理员指令：正在重启机器人…",

                        msg_id=msg_id, event_id=event_id)

        try:

            _restart_bot()

        except Exception as _e:  # noqa: BLE001

            logger.error("[管理员] 重启失败: %s" % _e)

        return

    if cmd == "shutdown":

        await send_text(api, scene, target_id, "⏻ 收到管理员指令：正在关闭机器人…",

                        msg_id=msg_id, event_id=event_id)

        try:

            _shutdown_bot()

        except Exception as _e:  # noqa: BLE001

            logger.error("[管理员] 关机失败: %s" % _e)

        return

    if cmd == "status":

        await send_text(api, scene, target_id, _format_admin_status(),

                        msg_id=msg_id, event_id=event_id)

        return

    if cmd == "help":

        await send_text(api, scene, target_id,

                        "👑 管理员指令：\n• 重启 / restart\n• 关机 / shutdown\n"

                        "• 状态 / status\n• 管理员帮助 / admin",

                        msg_id=msg_id, event_id=event_id)

        return

# @所有人 检测：QQ内嵌格式中 @everyone 解析为 @所有人 标签

# 参考: https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/message_format.html

_AT_EVERYONE_RE = re.compile(r'@everyone', re.IGNORECASE)

def _extract_first_image_url(attachments) -> str:

    """从消息 attachments 中提取第一张图片的 URL（不存在返回空字符串）。"""

    if not attachments:

        return ""

    for att in attachments:

        if not att:

            continue

        # botpy 2.x 的 attachment 可能是对象或字典

        content_type = (

            getattr(att, "content_type", "") or

            (att.get("content_type") if isinstance(att, dict) else "")

        )

        if content_type and content_type.startswith("image/"):

            url = (

                getattr(att, "url", "") or

                (att.get("url") if isinstance(att, dict) else "")

            )

            if url:

                return url

    return ""

def _is_at_everyone(raw: str) -> bool:

    """检测消息是否包含 @所有人/@everyone（群@全体成员）"""

    if not raw:

        return False

    if _AT_EVERYONE_RE.search(raw):

        return True

    if '@所有人' in raw or '@全部成员' in raw:

        return True

    return False

# ============ botpy 群消息事件修复 ============

def _patch_botpy_group_member_events():

    """



    修复 botpy 1.2.1 缺陷：botpy.connection.ConnectionState 缺少



    parse_group_member_add / parse_group_member_remove 解析器，



    导致 QQ 平台推送的「群用户添加 / 群用户移除」事件被静默丢弃，



    即便已在 q.qq.com 后台「回调配置 -> 群事件」勾选订阅。



    这里补注册解析器并分发到 on_group_member_add / on_group_member_remove。







    前提：QQ 平台默认走 WebSocket 推送事件，前提是「没有配置 Webhook 回调 URL」。



    若发现 patch 已生效但收不到事件，多半是已在 q.qq.com 配了 Webhook，



    需另开独立 HTTP 回调服务（端口 80/443/8080/8443）走 WebHook 通道。



    """

    from botpy.connection import ConnectionState

    from types import SimpleNamespace

    if not hasattr(ConnectionState, "parse_group_member_add"):

        def parse_group_member_add(self, payload):

            try:

                d = payload.get("d", {}) or {}

                evt = SimpleNamespace(

                group_openid=d.get("group_openid", "") or d.get("group_id", "") or "",

                member_openid=d.get("member_openid", "") or d.get("openid", "") or d.get("user_openid", "") or "",

                username=d.get("username", "") or d.get("nickname", "") or "",

                nickname=d.get("group_nickname", "") or d.get("member_nickname", "") or d.get("nickname", "") or "",

                )

                logger.info("[botpy 补丁] 收到 group_member_add 事件, payload.d=%s" % d)

                self._dispatch("group_member_add", evt)

            except Exception as _e:

                logger.warning("parse_group_member_add 异常: %s" % _e)

        ConnectionState.parse_group_member_add = parse_group_member_add

        logger.info("已补注册 parse_group_member_add 事件解析器")

    if not hasattr(ConnectionState, "parse_group_member_remove"):

        def parse_group_member_remove(self, payload):

            try:

                d = payload.get("d", {}) or {}

                evt = SimpleNamespace(

                group_openid=d.get("group_openid", "") or d.get("group_id", "") or "",

                member_openid=d.get("member_openid", "") or d.get("openid", "") or d.get("user_openid", "") or "",

                username=d.get("username", "") or d.get("nickname", "") or "",

                nickname=d.get("group_nickname", "") or d.get("member_nickname", "") or d.get("nickname", "") or "",

                )

                logger.info("[botpy 补丁] 收到 group_member_remove 事件, payload.d=%s" % d)

                self._dispatch("group_member_remove", evt)

            except Exception as _e:

                logger.warning("parse_group_member_remove 异常: %s" % _e)

        ConnectionState.parse_group_member_remove = parse_group_member_remove

        logger.info("已补注册 parse_group_member_remove 事件解析器")

def _patch_botpy_intents_group_member():

    """







    修复 botpy 1.2.1 缺陷：botpy.flags.Intents 枚举里缺了 GROUP_MEMBER 位 (1 << 24)。







    QQ 平台 WS 推送 GROUP_MEMBER_ADD / GROUP_MEMBER_REMOVE 需要订阅此位才能收到。







    官方文档 https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/group_member_add.html







    误标为 GROUP_AND_C2C_EVENT (1<<25)，实测订阅位是 24（社区已验证）。







    """

    from botpy.flags import Intents

    if hasattr(Intents, "group_member"):

        return

    try:

        from botpy.flags import Flag

        def _flag_value(_):

            return 1 << 24

        flag_obj = Flag(_flag_value)

        try:

            flag_obj.__set_name__(Intents, "group_member")

        except Exception:

            pass

        Intents.group_member = flag_obj

        if hasattr(Intents, "VALID_FLAGS"):

            Intents.VALID_FLAGS["group_member"] = flag_obj

        logger.info("[botpy 补丁] 已补注册 GROUP_MEMBER intent (1<<24)，用于接收群用户添加/移除事件")

    except Exception as _e:

        logger.warning("补注册 group_member intent 失败: %s" % _e)

def _patch_botpy_gateway_sniff():

    """







    临时调试用：把 botpy gateway WS 收到的每条消息的 t 字段打印到 INFO 日志，







    方便排查哪些事件经过了 botpy WS、哪些被未知事件吞掉。







    """

    try:

        from botpy.gateway import BotWebSocket

        orig = BotWebSocket.on_message

        if getattr(orig, "_welcome_sniff", False):

            return

        import json as _json

        async def on_message_sniff(self, ws, message):

            try:

                m = _json.loads(message)

                t = m.get("t") or ""

                if t:

                    logger.info("[botpy sniff] WS 收到事件 t=%s" % t)

            except Exception:

                pass

            return await orig(self, ws, message)

        on_message_sniff._welcome_sniff = True

        BotWebSocket.on_message = on_message_sniff

        logger.info("[botpy 补丁] WS gateway sniff 已启用（每个事件 t 字段都会进日志）")

    except Exception as _e:

        logger.warning("WS sniff 启用失败: %s" % _e)

def _patch_botpy_group_event():

    """







    修复 botpy 1.2.1 缺陷：







    1. botpy 未注册 group_message_create 事件解析器，







       导致群聊全量消息（不@机器人）无法接收。







       补注册解析器，分发到独立的 on_group_message_create 事件。







       需群主在群设置中开启「允许机器人接收群内全部消息」。







    2. botpy 的 GroupMessage._User 类只解析 member_openid，







       丢弃了 QQ 事件中的 username 字段。







       补注册 username 解析，用于获取用户真实昵称。







    3. 补注册 member_role 字段解析（owner/admin/member），







       用于群管系统的管理员权限判断。







       参考: https://bot.qq.com/wiki/develop/api-v2/server-inter/message/send-receive/event.html







    """

    from botpy.connection import ConnectionState

    # 修补1：补注册 group_message_create 事件解析器

    if not hasattr(ConnectionState, "parse_group_message_create"):

        def parse_group_message_create(self, payload):

            _message = GroupMessage(self.api, payload.get("id", None), payload.get("d", {}))

            self._dispatch("group_message_create", _message)

        ConnectionState.parse_group_message_create = parse_group_message_create

        logger.info("已补注册 group_message_create 事件解析器（支持不@机器人触发）")

    # 修补2：扩展 GroupMessage._User 类，解析 username 和 member_role 字段

    from botpy.message import GroupMessage

    _orig_user_init = GroupMessage._User.__init__

    def _patched_user_init(self, data):

        _orig_user_init(self, data)

        self.username = data.get("username", None)

        self.nickname = data.get("nickname", None)

        self.member_role = data.get("member_role", None)

        self.bot = data.get("bot", None)

        self.id = data.get("id", None)

    GroupMessage._User.__init__ = _patched_user_init

    logger.info("已扩展 GroupMessage._User 解析 username + member_role 字段")

def _patch_botpy_ws_health():

    """监控 WS 连接断开事件，供运行健康页展示。







    包装 botpy 网关的 on_close / on_error（若存在且为协程），在断开时记录一次 WS disconnect。



    """

    try:

        import asyncio

        from botpy.gateway import BotWebSocket

        for _meth in ("on_close", "on_error"):

            _orig = getattr(BotWebSocket, _meth, None)

            if _orig is None or getattr(_orig, "_health_patch", False):

                continue

            if not asyncio.iscoroutinefunction(_orig):

                continue

            def _make(orig):

                async def _hook(self, *a, **k):

                    try:

                        record_ws("disconnect")

                    except Exception:

                        pass

                    return await orig(self, *a, **k)

                _hook._health_patch = True

                return _hook

            setattr(BotWebSocket, _meth, _make(_orig))

        logger.info("[botpy 补丁] WS 健康监控已启用（disconnect 事件埋点）")

    except Exception as _e:

        logger.warning("WS 健康补丁启用失败: %s" % _e)

_patch_botpy_intents_group_member()

_patch_botpy_gateway_sniff()

_patch_botpy_group_event()

_patch_botpy_group_member_events()

_patch_botpy_ws_health()

# ============ 主客户端 ============

# ============ 问题反馈（腾讯文档收集表）============

# 用户发「反馈 / 建议 / 问题反馈 / 功能建议」等词，回一条简短的引导消息

# 附带一个「📝 反馈」链接按钮，点击直接跳转到收集表（QQ 链接按钮支持 docs.qq.com）。
# 真正生效的位置是「控制台 → 运行设置 → 问题反馈表单链接」(运行时配置 feedback.form_url)，
# 留空则菜单不显示「反馈」按钮。⚠️ 开源部署请留空或填你自己的问卷链接，避免暴露个人表单 ID。
_FEEDBACK_FORM_URL = ""

_FEEDBACK_ALIASES = ("反馈", "问题反馈", "功能建议", "意见反馈", "建议箱", "建议")

_FEEDBACK_MSG = (

    "💬 小流萤 · 问题反馈与功能建议\n"

    "━━━━━━━━━━━━━━━━━━━\n"

    "遇到 bug / 想要新功能？欢迎填写下方收集表，"

    "我会逐条查看 👇"

)

def _build_feedback_keyboard():

    """构造反馈引导消息的 inline keyboard：单行 📝 反馈 链接按钮，点击直达收集表。"""

    return {

        "content": {

            "rows": [

                {

                    "buttons": [

                        # 因 _make_link_btn 是实例方法，键盘结构手动拼装（type=0 链接按钮）

                        {

                            "id": "btn_feedback_link",

                            "render_data": {

                                "label": "📝 反馈",

                                "visited_label": "📝 反馈",

                                "style": 1,

                            },

                            "action": {

                                "type": 0,

                                "permission": {"type": 2},

                                "data": get_runtime_setting_effective("feedback.form_url"),

                                "unsupport_tips": "请更新QQ版本",

                            },

                        }

                    ]

                }

            ]

        }

    }

def _is_feedback_cmd(text: str) -> bool:

    """判断消息是否命中反馈触发词（兼容 / 前缀）。"""

    t = text.strip().lstrip("/").strip()

    if not t:

        return False

    for a in _FEEDBACK_ALIASES:

        if t == a or t.startswith(a):

            return True

    return False

class MyClient(botpy.Client):

    """QQ 群聊机器人主客户端（支持多实例并发）"""

    def __init__(self, intents, cfg):

        super().__init__(intents=intents)

        self.bot_appid = cfg["appid"]

        self.bot_secret = cfg["secret"]

        self.bot_name = cfg.get("name") or cfg["appid"]

    async def on_ready(self):

        logger.info("机器人「%s」已上线，准备就绪！" % self.robot.name)

        # 运行健康：记录 WS 连接事件

        try:

            record_ws("connect")

        except Exception:

            pass

        # 启动控制台 Web 服务器并自动打开浏览器

        # 先按自然日滚动清零：跨天时把昨日的「今日」计数（消息/进退群/加删好友等）归零；

        # 同天内不触发，从而保留刚从磁盘加载的当日计数（避免重启/关机把它们清零）。

        try:

            _rollover_today_counters_if_needed()

        except Exception:

            pass

        # 保留已持久化的「今日」计数（消息 / 指令 / API 调用），不再硬编码为 0，

        # 否则每次 on_ready 都会把磁盘里恢复的值清零，导致重启 / 关机丢失当天统计。

        update_status(

            online=True,

            start_time=time.time(),

            bot_name=self.robot.name,

            bot_avatar=getattr(self.robot, "avatar", ""),

            message_count=_status.get("message_count", 0),

            command_count=_status.get("command_count", 0),

            api_call_count=_status.get("api_call_count", 0),

            active_games={"gomoku": 0, "idiom": 0},

            music_playing=None,

            video_playing=None,

        )

        # 启动时预热「角色图库」分类缓存（失败不影响主流程，下次菜单请求会懒重试）

        _image_prewarm = get_plugin_module_attr("image_random", "prewarm_photo")

        try:

            if _image_prewarm is not None:

                await _image_prewarm()

        except Exception:

            pass

        # 注册机器人桥接（控制台公告等主动推送功能依赖它）

        try:

            register_bot_bridge(self.api, asyncio.get_running_loop(), self.bot_appid, self.robot.name, getattr(self.robot, "avatar", "") or "")

        except Exception as e:

            logger.error("注册控制台桥接失败: %s" % e)

        global _console_started

        if not _console_started:

            start_console_server(open_browser=True)

            _console_started = True

        logger.info("控制台已启动: http://127.0.0.1:9988/")

        logger.info("已注册接口: GET/POST /api/admin/list（管理员名单增删）")

        # 打印当前系统开关状态，便于确认控制台配置是否成功加载

        try:

            from console_server import _system_switches as _sw

            _on = [k for k, v in _sw.items() if v]

            _off = [k for k, v in _sw.items() if not v]

            logger.info("系统开关加载: 开启=%s 关闭=%s" % (_on, _off))

        except Exception:

            pass

        # 系统状态采集预热：把第一帧 cpu/mem/gpu 拍到 stdout，便于排查 N/A。

        try:

            _st = _get_status_data()

            _cpu = _st.get("cpu") or {}

            _mem = _st.get("mem") or {}

            _gpu = _st.get("gpu") or {}

            logger.info(

                "系统状态采集就绪: CPU=%s%% 内存=%s%% GPU=%s",

                _cpu.get("percent"),

                _mem.get("percent"),

                (_gpu.get("name") or "无") if _gpu.get("available") else "无",

            )

        except Exception as e:

            logger.warning("系统状态采集预热失败: %s" % e)

    # ============ 频道消息 ============

    async def on_at_message_create(self, message: Message):

        """监听频道公域 @ 机器人消息事件"""

        channel_id = getattr(message, "channel_id", "") or ""

        user_openid = getattr(message.author, "id", "") or ""

        if not channel_id or not user_openid:

            logger.warning("频道消息缺少 channel_id 或 author.id")

            return

        username = getattr(message.author, "username", "") or ""

        await self._dispatch_message(

            scene=ChatScene.CHANNEL,

            target_id=channel_id,

            user_openid=user_openid,

            content=message.content or "",

            msg_id=message.id,

            event_id=message.event_id if hasattr(message, "event_id") else None,

            username=username,

            event_type="CHANNEL_AT",

            attachments=getattr(message, "attachments", None) or [],

            author=message.author,

            recv_ts=time.perf_counter(),

        )

    # ============ C2C 私聊消息 ============

    async def on_c2c_message_create(self, message: Message):

        """监听用户私聊（C2C）消息事件"""

        user_openid = ""

        # C2C 消息的发送者信息在 message.author 中，可能为 User 对象

        author = getattr(message, "author", None)

        if author:

            user_openid = (

                getattr(author, "id", None) or

                getattr(author, "user_openid", None) or

                ""

            )

        if not user_openid:

            logger.warning("私聊消息缺少 author.id / user_openid")

            return

        username = getattr(author, "username", "") or ""

        await self._dispatch_message(

            scene=ChatScene.C2C,

            target_id=user_openid,

            user_openid=user_openid,

            content=message.content or "",

            msg_id=message.id,

            event_id=message.event_id if hasattr(message, "event_id") else None,

            username=username,

            event_type="C2C",

            attachments=getattr(message, "attachments", None) or [],

            author=author,

            recv_ts=time.perf_counter(),

        )

    async def on_direct_message_create(self, message: Message):

        """监听频道内私信（用户 → 机器人）事件"""

        user_openid = ""

        author = getattr(message, "author", None)

        if author:

            user_openid = (

                getattr(author, "id", None) or

                getattr(author, "user_openid", None) or

                ""

            )

        # 频道私信的 chat 标识：使用 guild_id + author.id 组合

        guild_id = getattr(message, "guild_id", "") or ""

        # 这里使用 user_openid 作为 target（因为私信是 1:1 关系）

        if not user_openid:

            logger.warning("频道私信缺少 author.id / user_openid")

            return

        username = getattr(author, "username", "") or ""

        await self._dispatch_message(

            scene=ChatScene.C2C,  # 复用 C2C 处理逻辑（无群管概念）

            target_id=user_openid,

            user_openid=user_openid,

            content=message.content or "",

            msg_id=message.id,

            event_id=message.event_id if hasattr(message, "event_id") else None,

            username=username,

            event_type="DM",

            attachments=getattr(message, "attachments", None) or [],

            author=author,

            recv_ts=time.perf_counter(),

        )

    # ============ 群聊消息（核心分发） ============

    async def on_group_at_message_create(self, message: GroupMessage):

        """群聊 @ 消息事件"""

        group_openid = getattr(message, "group_openid", "") or ""

        member_openid = getattr(message.author, "member_openid", "") or ""

        if not group_openid or not member_openid:

            logger.warning("群@消息缺少 group_openid 或 member_openid")

            return

        await self._dispatch_message(

            scene=ChatScene.GROUP,

            target_id=group_openid,

            user_openid=member_openid,

            content=message.content or "",

            msg_id=message.id,

            event_id=message.event_id if hasattr(message, "event_id") else None,

            username=getattr(message.author, "username", "") or "",

            event_type="AT",

            recv_ts=time.perf_counter(),

            attachments=getattr(message, "attachments", None) or [],

            author=message.author,

        )

    async def on_group_message_create(self, message: GroupMessage):

        """群聊全量消息事件（不@机器人也能触发）"""

        group_openid = getattr(message, "group_openid", "") or ""

        member_openid = getattr(message.author, "member_openid", "") or ""

        if not group_openid or not member_openid:

            return

        # 识别 @机器人：扫 mentions 列表里 是否有 bot=True 成员

        # botpy 的 GROUP_MESSAGE_CREATE 事件也带 mentions 字段，可以识别 是否 @机器人

        _at_bot = False

        try:

            _mentions = getattr(message, "mentions", None) or []

            for _m in _mentions:

                # GroupMessage._User 已补上 bot / id 字段

                if getattr(_m, "bot", False):

                    _at_bot = True

                    break

        except Exception:

            pass

        _real_event_type = "AT" if _at_bot else "ALL"

        await self._dispatch_message(

            scene=ChatScene.GROUP,

            target_id=group_openid,

            user_openid=member_openid,

            content=message.content or "",

            msg_id=message.id,

            event_id=message.event_id if hasattr(message, "event_id") else None,

            username=getattr(message.author, "username", "") or "",

            event_type=_real_event_type,

            recv_ts=time.perf_counter(),

            attachments=getattr(message, "attachments", None) or [],

            author=message.author,

        )

    # ============ 群 / 好友 / 频道 生命周期事件（用于持久化通讯录） ============

    async def on_group_add_robot(self, event):

        """机器人被加入群聊"""

        group_openid = getattr(event, "group_openid", "") or ""

        if not group_openid:

            return

        record_event(self.bot_appid)

        GROUP_BOT_MAP[group_openid] = self.bot_appid

        logger.info("[通讯录事件] 机器人被加入群聊: %s" % group_openid)

        update_group_contact(group_openid)

        inc_groups_joined_today(bot=((getattr(self, "robot", None) and getattr(self.robot, "name", None)) or self.bot_name))

        try:

            append_ws_log(

                bot=((getattr(self, "robot", None) and getattr(self.robot, "name", None)) or self.bot_name),

                type_="机器人入群",

                direction="system",

                scene=group_openid,

                sender="-",

                content="机器人被加入群聊: %s" % group_openid,

            )

        except Exception:

            pass

    async def on_group_del_robot(self, event):

        """机器人被移出群聊"""

        group_openid = getattr(event, "group_openid", "") or ""

        if not group_openid:

            return

        record_event(self.bot_appid)

        logger.info("[通讯录事件] 机器人被移出群聊: %s" % group_openid)

        remove_group_contact(group_openid)

        inc_groups_left_today(bot=((getattr(self, "robot", None) and getattr(self.robot, "name", None)) or self.bot_name))

        try:

            append_ws_log(

                bot=((getattr(self, "robot", None) and getattr(self.robot, "name", None)) or self.bot_name),

                type_="机器人退群",

                direction="system",

                scene=group_openid,

                sender="-",

                content="机器人被移出群聊: %s" % group_openid,

            )

        except Exception:

            pass

    async def on_group_member_add(self, event):

        """用户加入群聊"""

        group_openid = getattr(event, "group_openid", "") or ""

        member_openid = getattr(event, "member_openid", "") or getattr(event, "openid", "") or ""

        if not group_openid:

            return

        record_event(self.bot_appid)

        GROUP_BOT_MAP[group_openid] = self.bot_appid

        logger.info("[通讯录事件] 用户加入群聊: 群=%s 成员=%s" % (group_openid, member_openid or "未知"))

        try:

            append_ws_log(

                bot=((getattr(self, "robot", None) and getattr(self.robot, "name", None)) or self.bot_name),

                type_="用户加入群",

                direction="system",

                scene=group_openid,

                sender=member_openid or "-",

                content="用户加入群聊: %s" % group_openid,

                nickname=getattr(event, "username", "") or "",

                avatar=_avatar_url(member_openid),

            )

        except Exception:

            pass

        # 入群通知（读取本群开关，开启才发送；方法内部已捕获异常）

        try:

            await group_admin._send_welcome_on_add(

                self.api, group_openid, member_openid,

                username=getattr(event, "username", "") or "",

                nickname=getattr(event, "nickname", "") or "",

                bot_appid=self.bot_appid,

            )

        except Exception as e:

            logger.error("入群通知调用失败: %s" % e)

    async def on_group_member_remove(self, event):

        """用户离开群聊"""

        group_openid = getattr(event, "group_openid", "") or ""

        member_openid = getattr(event, "member_openid", "") or getattr(event, "openid", "") or ""

        if not group_openid:

            return

        record_event(self.bot_appid)

        logger.info("[通讯录事件] 用户离开群聊: 群=%s 成员=%s" % (group_openid, member_openid or "未知"))

        try:

            append_ws_log(

                bot=((getattr(self, "robot", None) and getattr(self.robot, "name", None)) or self.bot_name),

                type_="用户离开群",

                direction="system",

                scene=group_openid,

                sender=member_openid or "-",

                content="用户离开群聊: %s" % group_openid,

                nickname=getattr(event, "username", "") or "",

                avatar=_avatar_url(member_openid),

            )

        except Exception:

            pass

        # 退群事件仅记录，不再发送退群通知（退群功能已移除）

    async def on_friend_add(self, event):

        """用户添加机器人为好友"""

        user_openid = getattr(event, "openid", "") or ""

        if not user_openid:

            return

        logger.info("[通讯录事件] 用户加为好友: %s" % user_openid)

        update_friend_contact(user_openid)

        inc_friends_added_today(bot=((getattr(self, "robot", None) and getattr(self.robot, "name", None)) or self.bot_name))

        try:

            append_ws_log(

                bot=((getattr(self, "robot", None) and getattr(self.robot, "name", None)) or self.bot_name),

                type_="好友添加",

                direction="system",

                scene="-",

                sender=user_openid,

                content="用户添加机器人为好友",

                nickname=getattr(event, "username", "") or "",

                avatar=_avatar_url(user_openid),

            )

        except Exception:

            pass

    async def on_friend_del(self, event):

        """用户删除机器人好友"""

        user_openid = getattr(event, "openid", "") or ""

        if not user_openid:

            return

        logger.info("[通讯录事件] 用户删除好友: %s" % user_openid)

        remove_friend_contact(user_openid)

        inc_friends_removed_today(bot=((getattr(self, "robot", None) and getattr(self.robot, "name", None)) or self.bot_name))

        try:

            append_ws_log(

                bot=((getattr(self, "robot", None) and getattr(self.robot, "name", None)) or self.bot_name),

                type_="好友删除",

                direction="system",

                scene="-",

                sender=user_openid,

                content="用户删除机器人好友",

                nickname=getattr(event, "username", "") or "",

                avatar=_avatar_url(user_openid),

            )

        except Exception:

            pass

    async def on_channel_create(self, event):

        """子频道创建"""

        channel_id = getattr(event, "channel_id", "") or getattr(event, "id", "") or ""

        guild_id = getattr(event, "guild_id", "") or ""

        if not channel_id:

            return

        logger.info("[通讯录事件] 子频道创建: %s" % channel_id)

        try:

            append_ws_log(

                bot=((getattr(self, "robot", None) and getattr(self.robot, "name", None)) or self.bot_name),

                type_="频道创建",

                direction="system",

                scene=channel_id,

                sender="-",

                content="子频道创建: %s (频道: %s)" % (channel_id, guild_id or "-"),

            )

        except Exception:

            pass

    async def on_channel_destroy(self, event):

        """子频道删除"""

        channel_id = getattr(event, "channel_id", "") or getattr(event, "id", "") or ""

        guild_id = getattr(event, "guild_id", "") or ""

        if not channel_id:

            return

        logger.info("[通讯录事件] 子频道删除: %s" % channel_id)

        try:

            append_ws_log(

                bot=((getattr(self, "robot", None) and getattr(self.robot, "name", None)) or self.bot_name),

                type_="频道删除",

                direction="system",

                scene=channel_id,

                sender="-",

                content="子频道删除: %s (频道: %s)" % (channel_id, guild_id or "-"),

            )

        except Exception:

            pass

    async def _dispatch_message(self, scene: str, target_id: str, user_openid: str,

                                content: str, msg_id: str = None, event_id: str = None,

                                username: str = "", event_type: str = "",

                                attachments: list = None, author = None,

                                recv_ts: float = None):

        """







        统一的消息分发入口（群聊/私聊/频道共用）。







        - scene: ChatScene.GROUP / C2C / CHANNEL







        - target_id: 原生 ID（group_openid / user_openid / channel_id）







        - recv_ts: 事件进入处理函数的时间戳（用于 message-fetch 阶段计时）







        """

        # 运行健康：设置请求级 appid 上下文（供 respond/send 阶段按 bot 归因），

        # 并标记 message-fetch 阶段（事件进入 _dispatch_message 前的框架/网络开销）

        set_request_appid(self.bot_appid)

        _perf = {"appid": self.bot_appid, "plugin_total_ms": 0.0, "produce_ms": 0.0, "finalized": False}

        _t_enter = time.perf_counter()

        if recv_ts:

            record_stage(self.bot_appid, "message-fetch", (_t_enter - recv_ts) * 1000.0)

        chat_id = make_chat_id(scene, target_id)

        is_group = (scene == ChatScene.GROUP)

        # 运行设置：忽略其他机器人消息（群 > 机器人 > 全局 三层作用域）

        try:

            _author_bot = bool(getattr(author, "bot", False)) if author else False

        except Exception:

            _author_bot = False

        if _author_bot:

            _is_self = (str(user_openid) == str(self.bot_appid))

            if not _is_self:

                try:

                    _ignore = get_runtime_setting_effective(

                        "ignore_bot_messages",

                        appid=self.bot_appid,

                        group_id=(target_id if is_group else None),

                    )

                except Exception:

                    _ignore = False

                if _ignore:

                    logger.info("[_dispatch_message] 按运行设置忽略机器人消息: chat_id=%s" % chat_id)

                    return

        # 群管权限上下文：author.member_role 是平台权威来源（owner/admin/member）。

        # 安全策略：缺失或非白名单值一律按"member"（普通成员）处理，禁止默认升级

        # 为 owner——避免事件字段缺失导致任何群成员都获得整点报时/违禁词等管理权。

        # 私聊/频道场景无此概念时 member_role 为 None，不参与权限判断。

        try:

            member_role = getattr(author, "member_role", None) if author else None

        except Exception:

            member_role = None

        if member_role not in ("owner", "admin", "member"):

            member_role = "member" if is_group else None

        # 真实展示昵称：优先群昵称(nickname)，回退 QQ 昵称(username)

        try:

            member_nick = (getattr(author, "nickname", "") or username) if author else username

        except Exception:

            member_nick = username

        logger.info("[_dispatch_message] 进入: chat_id=%s event_type=%s msg_id=%s" % (chat_id, event_type, msg_id))

        # 同步消息来源到通讯录（事件持久化，补全 group_add_robot / friend_add 未覆盖的场景）

        try:

            if is_group:

                sync_contact_from_message("group", target_id, name=username)

                GROUP_BOT_MAP[target_id] = self.bot_appid

            elif scene == ChatScene.C2C:

                sync_contact_from_message("c2c", target_id, name=username)

                USER_BOT_MAP[target_id] = self.bot_appid

        except Exception as e:

            logger.debug("[通讯录] 消息同步联系人失败: %s" % e)

        # 去除富文本标签（@标记、表情等），让关键词匹配能正常工作

        # 频道场景尤其需要：用户在频道 @bot 时会带 <@!botid> 前缀

        _t_pre = time.perf_counter()

        content = clean_content(content)

        # 调试：首次记录 author 对象结构

        if not getattr(self, "_author_logged", False):

            logger.info("[%s] 消息 author 字段: %s" % (scene, repr({"openid": user_openid, "username": username})))

            self._author_logged = True

        # 调试：首次记录原始消息内容

        if not getattr(self, "_raw_logged", False):

            logger.info("[%s] raw content: %s" % (scene, repr(content)))

            self._raw_logged = True

        # 无视 @所有人 消息（仅群聊）

        if is_group and _is_at_everyone(content):

            return

        # 去重：使用 chat_id 作为 key（基于 msg_id 准确去重，同一 QQ 消息不会重发处理）

        dedup_key = "%s|%s|%s" % (chat_id, user_openid, content)

        if msg_id and is_msg_duplicate(msg_id):

            logger.info("[_dispatch_message] msg_id 去重命中，跳过: msg_id=%s event_type=%s" % (msg_id, event_type))

            record_dedup(self.bot_appid)

            return

        if is_duplicate(chat_id, user_openid, content):

            logger.info("[_dispatch_message] 去重命中，跳过: key=%s" % dedup_key)

            record_dedup(self.bot_appid)

            return

        else:

            logger.info("[_dispatch_message] 去重未命中（处理中）: key=%s event_type=%s" % (dedup_key, event_type))

            # 运行健康：pre-process 阶段（clean_content + 去重判定）耗时

            record_stage(self.bot_appid, "pre-process", (time.perf_counter() - _t_pre) * 1000.0)

        # 记录用户消息到控制台（带场景）

        _t_log = time.perf_counter()

        try:

            if is_group:

                record_message(chat_id, "", user_openid[:8], content,

                               is_bot=False, member_openid=user_openid, username=username, member_role=member_role, scene=scene, target_id=target_id, bot=((getattr(self, "robot", None) and getattr(self.robot, "name", None)) or self.bot_name))

            else:

                # 新风格：record_message(scene, chat_id, group_name, sender, content, is_bot, member_openid, username)

                record_message(scene, chat_id, "", user_openid[:8], content,

                               is_bot=False, member_openid=user_openid, username=username, member_role=member_role, scene=scene, target_id=target_id, bot=((getattr(self, "robot", None) and getattr(self.robot, "name", None)) or self.bot_name))

        except Exception as e:

            logger.warning("[_dispatch_message] record_message 失败（不影响主流程）: %s" % e)

        # 运行健康：dispatch-log 阶段（record_message 落库）耗时

        record_stage(self.bot_appid, "dispatch-log", (time.perf_counter() - _t_log) * 1000.0)

        await self._handle_message(scene, target_id, user_openid, content, msg_id,

                                   username=username, event_type=event_type,

                                   member_role=member_role, attachments=attachments,

                                   member_nick=member_nick, perf=_perf)

    async def _handle_message(self, scene: str, target_id: str, member_openid: str,

                              content: str, msg_id: str, username: str = "",

                              event_type: str = "", event_id: str = None,

                              member_role: str = None, attachments: list = None,

                              member_nick: str = "", perf=None):

        """







        统一处理消息指令（群聊/私聊/频道共用）。







        - 关键词触发：只有消息匹配关键词、或处于游戏/等待状态时才处理。







        - 群管功能仅在群聊场景生效。















        关键：传给各模块的 "group_openid" 参数使用**裸 ID**（不带 chat_id 前缀），







        这样模块内部的 data[group_openid] 存储 key 保持稳定，与历史数据兼容。







        """

        # 顶层 try-except：捕获所有异常并打印日志（避免被 botpy 默认吞掉）

        try:

            await self._handle_message_inner(scene, target_id, member_openid, content, msg_id,

                                              username=username, event_type=event_type,

                                              event_id=event_id, attachments=attachments,

                                              member_nick=member_nick, perf=perf)

        except Exception as e:

            logger.error("[_handle_message] 未捕获异常: %s" % e)

            import traceback

            logger.error(traceback.format_exc())

    # ============ 运行健康：插件计时 / Pipeline 收尾 ============

    async def _time_plugin(self, feat, coro, _perf, *args, **kwargs):

        """计时并埋点一次插件（功能模块）调用。coro 为 mgr.handle_command 协程。"""

        _ts = time.perf_counter()

        try:

            _r = await coro(*args, **kwargs)

        except Exception:

            _ms = (time.perf_counter() - _ts) * 1000.0

            record_plugin(self.bot_appid, feat, _ms, error=True)

            raise

        _ms = (time.perf_counter() - _ts) * 1000.0

        record_plugin(self.bot_appid, feat, _ms)

        if _r:

            record_stage(self.bot_appid, "produce-respond", _ms)

        if _perf is not None:

            _perf["plugin_total_ms"] = float(_perf.get("plugin_total_ms", 0.0)) + _ms

        return _r

    def _finalize_pipeline(self, _perf):

        """收尾 pipeline：记录 dispatch-respond 阶段（插件遍历总耗时）。"""

        if _perf is None:

            return

        _total = float(_perf.get("plugin_total_ms", 0.0))

        if _total > 0:

            record_stage(_perf.get("appid") or self.bot_appid, "dispatch-respond", _total)

    async def _handle_message_inner(self, scene: str, target_id: str, member_openid: str,

                                     content: str, msg_id: str, username: str = "",

                                     event_type: str = "", event_id: str = None,

                                     member_role: str = None, attachments: list = None,

                                     member_nick: str = "", perf=None):

        chat_id = make_chat_id(scene, target_id)  # 仅用于控制台消息记录的 key

        _t_dispatch_start = time.perf_counter()

        is_group = (scene == ChatScene.GROUP)

        # 群管权限上下文：member_role 由上层（_dispatch_message）透传真实值（owner/admin/member）。

        # 注意：此处不可再用 "owner" 兜底覆盖，否则所有群成员都会被当成群主，权限校验形同虚设。

        # 控制台管理员（data/admin_list.json 中的 QQ 号或 openid）同样视为有权限。

        _is_console_admin = False

        if is_group:

            _sender_qq = get_user_qq_number(member_openid) or ""

            _is_console_admin = (str(_sender_qq) in _load_admin_set()) or (member_openid in _load_admin_set())

        # ---- 管理员指令（重启 / 关机 / 状态）----

        # 在触发词闸门之前拦截：管理员发送指令即执行并回复；非管理员则放行给普通分发，

        # 避免遮挡已有的功能关键词。

        _admin_cmd = _match_admin_command(content)

        if _admin_cmd is not None:

            _sender_qq = get_user_qq_number(member_openid) or ""

            _is_admin = (str(_sender_qq) in _load_admin_set()) or (member_openid in _load_admin_set())

            if _is_admin:

                await _handle_admin_command(self.api, scene, target_id, _admin_cmd,

                                            msg_id, event_id)

                return

        # 传给各模块的 storage_id：裸 ID（兼容历史数据）

        storage_id = target_id

        # 关键词触发检测：非关键词消息只做违禁词检测（仅群聊）

        # 关键词触发检测：非关键词消息只做违禁词检测（仅群聊）

        is_kw = _is_trigger(content)

        # 运行设置：指令前缀（默认空 = 兼容旧行为，关键词直接触发；设置非空前缀后必须带此前缀才视为指令）

        _cmd_prefix = get_runtime_setting_effective(

            "command.prefix",

            appid=self.bot_appid,

            group_id=(target_id if is_group else None),

        ) or ""

        _stripped = None

        if not is_kw:

            if _cmd_prefix:

                if content.startswith(_cmd_prefix):

                    _stripped = content[len(_cmd_prefix):].lstrip()

            else:

                # 默认兼容：允许可选 "/" 前缀

                if content.startswith("/"):

                    _stripped = content[1:].lstrip()

        _is_cmd = bool(is_kw or _stripped)

        # 运行设置：指令限速（滑动窗口，超限静默丢弃，不影响线上主流程）

        if _is_cmd:

            if not _rate_is_allowed(self.bot_appid, member_openid, (target_id if is_group else "")):

                logger.info("[_handle_message_inner] 指令超速，已静默丢弃: chat_id=%s user=%s" % (chat_id, member_openid[:8]))

                return

        # 支持 / 前缀：除管理员指令外，所有功能指令都能用 /xxx 触发（自动剥离前导 / 后再分发到各模块）

        # 例：/帮助、/菜单、/签到、/点歌 晴天、/看 三国、/绑群号 12345、/小说、/二次元、/原神cos、/求签 ...

        # 剥离后交给各模块按各自规则匹配（触发词 / 子功能命令 / 精确匹配指令等），无需逐一登记。

        # 例外：管理员指令（重启 / 状态 / 管理员帮助 / 关机）即使带 / 前缀也不在此处处理，仍走上方管理员拦截逻辑。

        if _stripped and _match_admin_command(_stripped) is None:

            content = _stripped

            is_kw = True

        # is_waiting / has_active_session 使用 storage_id（裸 ID），保持与各模块存储 key 一致
        # 等待会话预检：遍历注册表所有插件的 is_waiting（工具/视频解析/疾病/垃圾分类等任一等待态即放行）
        is_waiting = False
        for _wdesc in snapshot_plugins():
            _wfn = getattr(_wdesc, "is_waiting", None)
            if _wfn is None:
                continue
            try:
                if _wfn(storage_id, member_openid):
                    is_waiting = True
                    break
            except Exception as _e:
                logger.warning("[dispatch] 插件 %s 等待预检异常: %s" % (_wdesc.key, _e))

        # 进行中游戏会话：遍历 game 分类插件（game_gomoku/game_idiom/game_xiangqi）的 session_check，
        # 任一为 True 即视为游戏进行中（插件未装时 False）。game_core 共享棋局文件，判断准确。
        is_gaming = False
        for _gdesc in snapshot_plugins():
            if getattr(_gdesc, "category", "") != "game":
                continue
            if _gdesc.session_check is None:
                continue
            try:
                if _gdesc.session_check(storage_id):
                    is_gaming = True
                    break
            except Exception as _e:
                logger.warning("[dispatch] game 会话预检异常: %s" % _e)

        # 学习系统作答模式：等待用户提交答案时，普通文本也要放行给 study 判定

        is_studying = False

        # 小说阅读中：「上一章 / 下一章 / 目录 / 返回书库 / 退出」等控制按钮不是触发词，需放行给 novel 处理
        is_reading = False
        if is_feature_enabled("novel", appid=self.bot_appid):
            _novel_desc = get_plugin("novel")
            if _novel_desc is not None and _novel_desc.session_check is not None:
                try:
                    is_reading = _novel_desc.session_check(storage_id)
                except Exception as _e:
                    logger.warning("[dispatch] novel 会话预检异常: %s" % _e)

        # ---- 问题反馈（腾讯文档收集表）----

        # 进行中的游戏/工具/学习/小说会话不拦截，优先交给对应模块处理

        if not (is_waiting or is_gaming or is_studying or is_reading) and _is_feedback_cmd(content) and get_runtime_setting_effective("feedback.enabled"):

            await send_text_with_keyboard(

                self.api, scene, target_id, _FEEDBACK_MSG,

                _build_feedback_keyboard(),

                msg_id=msg_id, event_id=event_id,

            )

            return

        # ---- AI 对话路由标记 ----

        # 被@机器人 / 频道@机器人 / 私聊 的消息，若所有功能模块均未处理，则兜底进入 AI 自由对话。

        # 注意：AI 必须放在功能模块分发【之后】作为兜底（见函数末尾），否则单聊中"模块精确匹配"的指令

        # （求签 / 原神cos / 二次元 / 答案之书 / 疾病信息 等不在 _EXACT_KEYWORDS 的指令）会被 AI 提前吞掉、无法响应。

        is_at_or_dm = event_type in ("AT", "CHANNEL_AT", "C2C", "DIRECT_MESSAGE", "DM")

        if not (is_kw or is_waiting or is_gaming or is_studying or is_reading):

            # 非指令消息：仅群聊做违禁词检测

            if is_group:

                await group_admin.check_banned_word(self.api, content, target_id, msg_id, member_openid=member_openid)

            # 被@ / 私聊 的非指令消息：放行到末尾 AI 兜底（不在此提前 return），

            # 让功能模块先有机会处理；普通群聊消息（未@）同样放行到功能模块分发（@或不@都能触发指令），

            if not is_at_or_dm and not is_group:

                return

        logger.info("收到指令[%s/%s]: %s" % (scene, event_type, content))

        update_status(command_count=_bot_status_command_count())

        # 运行健康：命令处理器计数（群聊 / 私聊，按 bot 隔离）

        record_command(self.bot_appid, scene)

                # ============ 注册表驱动分发（DISPATCH_PLAN）============

        # 框架级特殊步骤与插件（内置 + 外置，统一走 plugin_registry）按固定顺序交织，

        # 精确保留原内联分发行为（含游戏优先路由 / 子功能门控 / 帮助子菜单导航 / AI 兜底等位置）。

        _ctx = PluginContext(

            api=self.api, content=content, storage_id=storage_id,

            member_openid=member_openid, msg_id=msg_id, scene=scene,

            target_id=target_id, member_role=member_role,

            is_console_admin=_is_console_admin, member_nick=member_nick,

            is_group=is_group, event_type=event_type, username=username,

            event_id=event_id, bot=self, perf=perf, bot_appid=self.bot_appid,

            is_waiting=is_waiting, is_gaming=is_gaming, is_studying=is_studying,

            is_at_or_dm=is_at_or_dm,

        )

        # 运行健康：dispatch 阶段（路由闸门决策）耗时

        record_stage(self.bot_appid, "dispatch", (time.perf_counter() - _t_dispatch_start) * 1000.0)

        for _step in DISPATCH_PLAN:

            _kind, _arg = _step

            if _kind == "plugin":

                _desc = get_plugin(_arg)

                if _desc is None:

                    continue

                try:

                    _handled = await _desc.dispatch(_ctx)

                except Exception as _e:

                    logger.error("[dispatch] 插件 %s 执行异常: %s" % (_arg, _e))

                    _handled = False

                if _handled:

                    return

            elif _kind == "fw":

                try:

                    _handled = await self._run_fw_step(_arg, _ctx)

                except Exception as _e:

                    logger.error("[dispatch] 框架步骤 %s 执行异常: %s" % (_arg, _e))

                    _handled = False

                if _handled:

                    return

# ============ 按钮交互回调 ============

    # ============ 框架级分发步骤（DISPATCH_PLAN 的 "fw" 条目）============

    async def _run_fw_step(self, name: str, ctx: PluginContext) -> bool:

        if name == "game_idiom_preroute":

            return await self._fw_game_idiom_preroute(ctx)

        if name == "subfeature_gate":

            return await self._fw_subfeature_gate(ctx)

        if name == "profile_command":

            return await self._fw_profile_command(ctx)

        if name == "help_submenu_nav":

            return await self._fw_help_submenu_nav(ctx)

        if name == "external_plugins":

            return await self._fw_external_plugins(ctx)

        if name == "join_experience_group":

            return await self._fw_join_experience_group(ctx)

        if name == "help_menu":

            return await self._fw_help_menu(ctx)

        if name == "banned_word_noncmd":

            return await self._fw_banned_word_noncmd(ctx)

        if name == "ai_fallback":

            return await self._fw_ai_fallback(ctx)

        return False

    async def _fw_game_idiom_preroute(self, ctx: PluginContext) -> bool:

        # 猜成语进行中优先路由：判定函数与分发均从 game_idiom 插件注册表获取（插件未装时放行）
        _idiom_check = get_plugin_module_attr("game_idiom", "idiom_session_check")

        if _idiom_check is None:

            return False

        try:

            if not _idiom_check(ctx.storage_id):

                return False

        except Exception:

            return False

        if not is_feature_enabled("game", appid=ctx.bot_appid):

            return True

        _game_desc = get_plugin("game_idiom")

        if _game_desc is None or _game_desc.dispatch is None:

            return True

        return bool(await _game_desc.dispatch(ctx))

    async def _fw_subfeature_gate(self, ctx: PluginContext) -> bool:

        if ctx.is_waiting or ctx.is_gaming or ctx.is_studying:

            return False

        _sub_key = resolve_sub_feature(ctx.content)

        if _sub_key is None:

            return False

        _master_key = get_master_feature(_sub_key)

        if _master_key and not is_feature_enabled(_master_key, appid=ctx.bot_appid):

            return True

        if not is_sub_feature_enabled(_sub_key, appid=ctx.bot_appid):

            await send_text(ctx.api, ctx.scene, ctx.target_id,

                            "⚠️ 该功能已关闭，如需使用请在控制台「功能开关」中开启。",

                            msg_id=ctx.msg_id, event_id=ctx.event_id)

            return True

        return False

    async def _fw_profile_command(self, ctx: PluginContext) -> bool:

        return await self._handle_profile_command(

            ctx.scene, ctx.content, ctx.target_id, ctx.member_openid, ctx.msg_id, username=ctx.username)

    async def _fw_help_submenu_nav(self, ctx: PluginContext) -> bool:

        _CATEGORY_MENUS = {

            "签到菜单", "视频菜单", "音乐菜单",

            "娱乐菜单", "工具菜单", "群管菜单", "学习菜单", "小说菜单",

            "图片菜单", "图片",

            "游戏工具菜单", "原神菜单", "崩铁菜单", "鸣潮菜单",

        }

        _CATEGORY_FEATURE = {

            "签到菜单": "checkin", "视频菜单": "video", "音乐菜单": "music",

            "娱乐菜单": "game", "工具菜单": "tools", "群管菜单": "group_admin",

            "学习菜单": "study", "小说菜单": "novel", "图片菜单": "image", "图片": "image",

        }

        if ctx.content in _CATEGORY_MENUS:

            _feat = _CATEGORY_FEATURE.get(ctx.content)

            if _feat and not is_feature_enabled(_feat, appid=ctx.bot_appid):

                return True

            if ctx.content == "群管菜单" and not ctx.is_group:

                await send_text(ctx.api, ctx.scene, ctx.target_id,

                                "⚙️ 群管功能仅在群聊中可用", msg_id=ctx.msg_id, event_id=ctx.event_id)

                return True

            await self._send_help_category(ctx.scene, ctx.target_id, ctx.content, ctx.msg_id, ctx.event_id)

            return True

        if ctx.content == "返回主菜单":

            await self._send_help(ctx.scene, ctx.target_id, ctx.msg_id, ctx.event_id)

            return True

        return False

    async def _fw_external_plugins(self, ctx: PluginContext) -> bool:

        for _desc in sorted(get_external_plugins(), key=lambda d: d.priority):

            try:

                # 分发闸门：禁用（仅停止分发）的外置插件直接跳过
                if not is_plugin_enabled(_desc.key):
                    continue

                if await _desc.dispatch(ctx):

                    return True

            except Exception as _e:

                logger.error("[dispatch] 外置插件 %s 执行异常: %s" % (_desc.key, _e))

        return False

    async def _fw_join_experience_group(self, ctx: PluginContext) -> bool:

        if not get_runtime_setting_effective("experience_group.enabled"):
            return False

        if ctx.content in ("加入体验群", "体验群", "加群", "加群二维码"):

            await send_text_with_keyboard(

                ctx.api, ctx.scene, ctx.target_id,

                "🏠 小流萤体验群\n点击下方按钮即可加入群聊～",

                {"content": {"rows": [{"buttons": [self._make_group_join_btn()]}]}},

                msg_id=ctx.msg_id, event_id=ctx.event_id,

            )

            return True

        return False

    async def _fw_help_menu(self, ctx: PluginContext) -> bool:

        logger.info("[_handle_message] 准备走帮助菜单分支: content=%r scene=%s" % (ctx.content, ctx.scene))

        if ctx.content in ("帮助", "功能", "菜单", "使用帮助"):

            logger.info("[_handle_message] 命中帮助菜单，调用 _send_help")

            try:

                await self._send_help(ctx.scene, ctx.target_id, ctx.msg_id, ctx.event_id)

            except Exception as _e:

                logger.error("[_handle_message] _send_help 调用异常: %s" % _e)

                import traceback

                logger.error(traceback.format_exc())

            return True

        return False

    async def _fw_banned_word_noncmd(self, ctx: PluginContext) -> bool:

        if ctx.is_group:

            await group_admin.check_banned_word(ctx.api, ctx.content, ctx.target_id, ctx.msg_id, member_openid=getattr(ctx, "member_openid", "") or "")

        return False

    async def _fw_ai_fallback(self, ctx: PluginContext) -> bool:

        _ai_on = is_feature_enabled("ai", appid=ctx.bot_appid)

        logger.info("[AI对话] 兜底进入 is_group=%s is_at_or_dm=%s ai=%s content=%r",
                    ctx.is_group,
                    ctx.is_at_or_dm,
                    _ai_on,
                    ctx.content)

        if not _ai_on:
            return False

        # 群聊下 AI 兜底只响应 @ 机器人的消息
        if ctx.is_group and not ctx.is_at_or_dm:
            logger.info("[AI对话] 群聊非@消息，跳过兜底")
            return False

        # 过滤功能指令：以 / # ! 开头的消息不进入 AI（避免与签到、老婆等功能指令冲突）
        _text = (ctx.content or "").strip()
        if _text and _text[0] in "/#!":
            logger.info("[AI对话] 疑似指令消息(%s)，跳过兜底", _text[:20])
            return False

        if not _text:
            return False

        self._finalize_pipeline(ctx.perf)

        _img_url = _extract_first_image_url(getattr(ctx, "attachments", None) or [])
        await self._handle_ai_chat(ctx.scene, ctx.target_id, ctx.content, ctx.msg_id, ctx.event_id, ctx.event_type, image_url=_img_url)

        return True

    async def on_interaction_create(self, interaction: Interaction):

        """







        监听回调按钮(type=1)点击事件。







        指令按钮(type=2)不触发此事件，会自动填入输入框。







        """

        logger.info("收到按钮交互回调: event_id=%s" % interaction.event_id)

        # 先回应交互，避免客户端 loading

        try:

            await self.api.on_interaction_result(interaction.event_id, code=0)

        except Exception as e:

            logger.error("回应交互失败: %s" % e)

        # 解析回调数据

        try:

            button_data = interaction.data.resolved.button_data

            button_id = interaction.data.resolved.button_id

        except Exception:

            button_data = ""

            button_id = ""

        # 识别场景（从 interaction 中读取 group_openid / guild_id / user_openid 等）

        group_openid = getattr(interaction, "group_openid", None) or ""

        member_openid = getattr(interaction, "group_member_openid", None) or ""

        guild_id = getattr(interaction, "guild_id", None) or ""

        user_openid = getattr(interaction, "user_openid", None) or ""

        # 决定 chat_id 与场景

        if group_openid:

            chat_id = make_chat_id(ChatScene.GROUP, group_openid)

            scene = ChatScene.GROUP

            target_id = group_openid

            user_id = member_openid

        elif user_openid:

            # C2C 或频道私信

            chat_id = make_chat_id(ChatScene.C2C, user_openid)

            scene = ChatScene.C2C

            target_id = user_openid

            user_id = user_openid

        elif guild_id:

            # 频道子频道

            chat_id = make_chat_id(ChatScene.CHANNEL, guild_id)

            scene = ChatScene.CHANNEL

            target_id = guild_id

            user_id = member_openid or user_openid

        else:

            logger.warning("按钮回调缺少场景标识")

            return

        logger.info(

            "按钮交互详情: scene=%s, button_id=%s, button_data=%s, chat=%s, user=%s"

            % (scene, button_id, button_data, chat_id, user_id)

        )

        # 分发到插件注册表（内置 + 外置统一）：按钮回调按注册顺序遍历，
        # 任一插件的 handle_callback 返回 True 即停止（tools/game 等各自处理自己的按钮）。
        # 注意：传 target_id（裸 ID）+ scene，不要传 chat_id（带前缀），
        # 否则插件内部 state key 会变成 "g:xxx|yyy"，与 handle_command 中的 "xxx|yyy" 不一致。
        if button_data:
            for _pdesc in snapshot_plugins():
                _cb = getattr(_pdesc, "handle_callback", None)
                if _cb is None:
                    continue
                try:
                    handled = await _cb(
                        self.api, button_data, target_id, user_id,
                        scene=scene,
                        event_id=interaction.event_id,
                    )
                except Exception as _e:
                    logger.error("[dispatch] 插件 %s 按钮回调异常: %s" % (_pdesc.key, _e))
                    handled = False
                if handled:
                    return

    # ============ AI 对话（被@机器人 / 私聊时调用） ============

    async def _handle_ai_chat(self, scene: str, target_id: str, content: str,

                              msg_id: str, event_id: str, event_type: str = "", image_url: str = ""):

        """处理 AI 自由对话。







        场景：



          - 群聊被 @机器人（event_type=AT）



          - 频道被 @机器人（event_type=CHANNEL_AT）



          - 用户私聊（C2C）



          - 频道私信（DIRECT_MESSAGE）







        流程：直接同步阻塞调用 AI，拿到结果后回复。同步调用是因为 bot.py 入口处理已是异步事件循环，



        此处单独启线程调用 urllib 会阻塞事件循环，因此直接同步调用并依赖 30~90s 的



        provider 超时上限。



        """

        if not content or not content.strip():

            return

        logger.info("[AI对话] 触发 event_type=%s content=%r" % (event_type, content[:60]))

        # 图片识别辅助：AI 对话开启时，将图片 OCR 文字并入提问（HunyuanOCR）
        if image_url and is_feature_enabled("ai", appid=self.bot_appid):
            try:
                from console_server import _call_ocr
                _ocr = _call_ocr(image_url)
                if _ocr:
                    _tag = "[图片识别内容]\n" + _ocr
                    content = (content + "\n" + _tag) if content.strip() else _tag
            except Exception as _oe:
                logger.warning("[AI对话] OCR 辅助失败: %s" % _oe)

        # 同步调用 AI（会阻塞当前事件循环，直到 provider 响应或超时）

        _ai_ts = time.perf_counter()

        try:

            ok, reply, err, pname = await asyncio.to_thread(
                chat_with_ai_for_bot,
                [{"role": "user", "content": content}],
                timeout=60,
                bot=self.bot_appid,
            )

        except Exception as e:

            # 运行健康：AI 调用异常计入失败 + 电路熔断

            _ai_ms = (time.perf_counter() - _ai_ts) * 1000.0

            record_ai_call(self.bot_appid, _ai_ms, ok=False, timed_out=True)

            record_stage(self.bot_appid, "ai-think", _ai_ms)

            logger.error("[AI对话] 调用异常: %s" % e)

            await send_text(self.api, scene, target_id,

                            "⚠️ AI 调用异常：%s" % str(e)[:120],

                            msg_id=msg_id, event_id=event_id)

            return

        def _sanitize_ai_err(err):
            """避免把原始 HTTP 错误 JSON 直接发到 QQ。"""
            if not err:
                return "AI 调用失败，请稍后再试"
            _e = str(err)
            _lower = _e.lower()
            if ("http 429" in _lower or
                ("1305" in _e and "overloaded" in _lower) or
                ("temporarily" in _lower and "overloaded" in _lower)):
                return "AI 服务暂时繁忙，请稍后再试~"
            if "{" in _e and "\"error\"" in _e:
                return "AI 服务暂时不可用，请稍后再试~"
            return _e[:120]

        if not ok:

            # 运行健康：AI 调用返回失败计入失败 + 电路熔断

            _ai_ms = (time.perf_counter() - _ai_ts) * 1000.0

            record_ai_call(self.bot_appid, _ai_ms, ok=False, timed_out=False)

            record_stage(self.bot_appid, "ai-think", _ai_ms)

            logger.warning("[AI对话] 调用失败: %s" % err)

            await send_text(self.api, scene, target_id,

                            "⚠️ %s" % _sanitize_ai_err(err),

                            msg_id=msg_id, event_id=event_id)

            return

        # 运行健康：AI 调用成功计入统计 + ai-think 阶段

        _ai_ms = (time.perf_counter() - _ai_ts) * 1000.0

        record_ai_call(self.bot_appid, _ai_ms, ok=True)

        record_stage(self.bot_appid, "ai-think", _ai_ms)

        # 截断过长回复（QQ 消息建议 < 1500 字符，超长分片由前端/调用方处理；这里只简单截断）

        if len(reply) > 1500:

            reply = reply[:1500] + "\n…（回复过长已截断）"

        try:

            await send_text(self.api, scene, target_id, reply,

                            msg_id=msg_id, event_id=event_id)

        except Exception as e:

            logger.error("[AI对话] 发送回复失败: %s" % e)

            return

        # 记录到控制台消息中心

        try:

            _chat_id = make_chat_id(scene, target_id)

            _scn = "group" if scene == ChatScene.GROUP else ("c2c" if scene == ChatScene.C2C else "channel")

            record_bot_reply(chat_id=_chat_id, content=reply, scene=_scn,

                             target_id=target_id, msg_type="text")

        except Exception:

            pass

        logger.info("[AI对话] 成功 model=%s prompt_len=%d reply_len=%d" %

                    (pname, len(content), len(reply)))

    # ============ 个人信息设置 ============

    async def _handle_profile_command(self, scene: str, content: str, target_id: str, member_openid: str,

                                  msg_id: str, username: str = "", event_id: str = None) -> bool:

        """







        处理个人信息设置指令：







        - 绑群号 XXX    → 仅群聊场景（绑定QQ群号）







        - 绑QQ XXX      → 三场景通用（绑定个人QQ号）







        - 我的信息       → 三场景通用







        返回 True 表示已处理，False 表示不匹配。







        """

        is_group = (scene == ChatScene.GROUP)

        # 绑群号（仅群聊）

        if content.startswith("绑群号"):

            if not is_group:

                await send_text(self.api, scene, target_id,

                                "💡 绑群号仅在群聊中可用\n请在群聊中发送「绑群号」指令",

                                msg_id=msg_id, event_id=event_id)

                return True

            qq_str = content[3:].strip()

            if not qq_str:

                old_qq = get_group_qq_number(target_id)

                hint = "当前已绑定群号：%s" % old_qq if old_qq else "当前未绑定群号"

                await send_text(

                    self.api, scene, target_id,

                    "请输入QQ群号，例如：绑群号 123456789\n💡 绑定后控制台将自动显示真实群头像\n%s" % hint,

                    msg_id=msg_id, event_id=event_id,

                )

                return True

            if not qq_str.isdigit() or len(qq_str) < 5 or len(qq_str) > 12:

                await send_text(self.api, scene, target_id, "群号格式不正确，请输入5-12位数字",

                                msg_id=msg_id, event_id=event_id)

                return True

            old_qq = get_group_qq_number(target_id)

            bind_group_qq_number(target_id, qq_str)

            logger.info("群 %s 绑定QQ群号: %s → %s" % (target_id[:8], old_qq or "无", qq_str))

            await send_text(

                self.api, scene, target_id,

                "✅ 群号绑定成功！\n群号：%s\n💡 控制台将自动显示真实群头像" % qq_str,

                msg_id=msg_id, event_id=event_id,

            )

            return True

        # 绑QQ（三场景通用）

        if content.startswith("绑QQ"):

            qq_str = content[3:].strip()

            if not qq_str:

                old_qq = get_user_qq_number(member_openid)

                hint = "当前已绑定QQ：%s" % old_qq if old_qq else "当前未绑定QQ"

                await send_text(

                    self.api, scene, target_id,

                    "请输入你的QQ号，例如：绑QQ 10001\n💡 绑定后控制台将自动显示真实头像和QQ资料\n%s" % hint,

                    msg_id=msg_id, event_id=event_id,

                )

                return True

            if not qq_str.isdigit() or len(qq_str) < 5 or len(qq_str) > 12:

                await send_text(self.api, scene, target_id, "QQ号格式不正确，请输入5-12位数字",

                                msg_id=msg_id, event_id=event_id)

                return True

            old_qq = get_user_qq_number(member_openid)

            bind_user_qq_number(member_openid, qq_str)

            await send_text(

                self.api, scene, target_id,

                "✅ QQ号绑定成功！\nQQ：%s\n🔍 正在查询QQ资料..." % qq_str,

                msg_id=msg_id, event_id=event_id,

            )

            # 在独立线程中查询QQ信息（避免阻塞异步事件循环）

            import threading as _threading

            _loop = asyncio.get_event_loop()

            _api = self.api

            _scene = scene

            _target = target_id

            _member = member_openid

            def _do_fetch():

                info = fetch_and_save_qq_info(_member, qq_str)

                logger.info("用户 %s 绑定QQ %s，查询结果: nick=%s, level=%s" % (

                    _member[:8], qq_str, info.get("nickname", ""), info.get("level", "")))

                nick = info.get("nickname", "")

                level = info.get("level", "")

                if nick or level:

                    filled = sum(1 for k in ["nickname","level","qid","energy","card",

                        "signature","age","expert_days","reg_time","reg_days",

                        "avatar_modified","monthly_vip","annual_vip","active_days",

                        "vip_level","vip_exp","vip_growth","normal_vip","super_vip",

                        "annual_fee_vip","opened_services"] if info.get(k))

                    result_msg = "✅ QQ资料查询完成！\n昵称：%s\n等级：%s\n共获取 %d/21 项资料\n发送「我的信息」查看完整资料卡" % (

                        nick or "未知", level or "未知", filled)

                else:

                    result_msg = ("⚠️ QQ资料查询完成，但未获取到详细信息\n"

                        "昵称：%s\n"

                        "💡 提示：如需查看等级/会员等详细资料，请联系管理员配置API密钥" % (nick or "未知"))

                try:

                    asyncio.run_coroutine_threadsafe(

                        send_text(_api, _scene, _target, result_msg),

                        _loop

                    )

                except Exception as e:

                    logger.error("发送QQ资料查询结果失败: %s" % e)

            _threading.Thread(target=_do_fetch, daemon=True).start()

            logger.info("用户 %s 绑定QQ号: %s → %s" % (member_openid[:8], old_qq or "无", qq_str))

            return True

        # 我的信息（三场景通用）

        if content == "我的信息":

            info = get_user_detail_info(member_openid) or {}

            # 容错：info 来自 console_server.get_user_detail_info，仅返回

            # {openid, qq, nickname, avatar} 这 4 个字段——之前的代码用了

            # is_bound_qq/name/qq_number/qq_nickname 等不存在的字段会直接 KeyError。

            qq_number = info.get("qq") or ""

            is_bound_qq = bool(qq_number)

            # 当前会话名

            if scene == ChatScene.GROUP:

                group_name = get_group_display_name(target_id)

                group_qq = get_group_qq_number(target_id)

            elif scene == ChatScene.CHANNEL:

                group_name = "频道"

                group_qq = ""

            else:

                group_name = "私聊"

                group_qq = ""

            # 群昵称（从QQ事件 username 字段获取，缺失时回退到 info 里的 nickname）

            group_nick = username or info.get("nickname") or info.get("name") or "未设置"

            if is_bound_qq:

                # 已绑定QQ：显示完整资料

                v = lambda key: info.get(key, "") or "暂无"

                lines = [

                    "📋 QQ资料信息卡",

                    "━━━━━━━━━━━━━",

                    "昵称：%s" % v("qq_nickname"),

                    "账号：%s" % qq_number,

                    "群昵称：%s" % group_nick,

                    "等级：%s" % v("qq_level"),

                    "QID：%s" % v("qq_qid"),

                    "能量：%s" % v("qq_energy"),

                    "名片：%s" % v("qq_card"),

                    "签名：%s" % v("qq_signature"),

                    "年龄：%s" % v("qq_age"),

                    "达人天数：%s" % v("qq_expert_days"),

                    "注册时间：%s" % v("qq_reg_time"),

                    "注册天数：%s" % v("qq_reg_days"),

                    "头像修改：%s" % v("qq_avatar_modified"),

                    "月大会员：%s" % v("qq_monthly_vip"),

                    "年大会员：%s" % v("qq_annual_vip"),

                    "活跃天数：%s" % v("qq_active_days"),

                    "会员等级：%s" % v("qq_vip_level"),

                    "会员经验：%s" % v("qq_vip_exp"),

                    "会员成长：%s" % v("qq_vip_growth"),

                    "普通会员：%s" % v("qq_normal_vip"),

                    "超级会员：%s" % v("qq_super_vip"),

                    "年费会员：%s" % v("qq_annual_fee_vip"),

                    "开通业务：%s" % v("qq_opened_services"),

                    "━━━━━━━━━━━━━",

                ]

                info_text = "\n".join(lines)

                # 头像/图片消息仅群聊场景支持

                if scene == ChatScene.GROUP:

                    avatar_url = info.get("avatar") or (

                        "http://q1.qlogo.cn/g?b=qq&nk=%s&s=640" % qq_number)

                    result = await send_group_image(

                        self.api, target_id, avatar_url, msg_id=msg_id, content=info_text

                    )

                    if result is None:

                        await send_text(self.api, scene, target_id, info_text, msg_id=msg_id, event_id=event_id)

                else:

                    await send_text(self.api, scene, target_id, info_text, msg_id=msg_id, event_id=event_id)

            else:

                # 未绑定QQ：显示基础信息并提示绑定

                lines = [

                    "📋 我的信息",

                    "━━━━━━━━━━━━━",

                    "昵称：%s" % group_nick,

                    "群昵称：%s" % group_nick,

                    "头像：%s" % ("已设置" if info.get("avatar") else "默认头像"),

                    "━━━━━━━━━━━━━",

                    "💡 绑定QQ号后可查看完整资料：",

                    "昵称/账号/等级/QID/能量/名片/签名",

                    "年龄/达人天数/注册时间/注册天数",

                    "头像修改/会员等级/会员经验/会员成长",

                    "月大会员/年大会员/活跃天数",

                    "普通会员/超级会员/年费会员/开通业务",

                    "━━━━━━━━━━━━━",

                    "发送「绑QQ 你的QQ号」开始绑定",

                ]

                await send_text(self.api, scene, target_id, "\n".join(lines),

                                msg_id=msg_id, event_id=event_id)

            return True

        return False

    # ============ 帮助菜单 ============

    def _make_btn(self, label, command, enter=True, btn_id=None):

        """构建指令按钮(type=2)：点击后自动填入并发送指令"""

        return {

            "id": btn_id or ("btn_" + command),

            "render_data": {"label": label, "visited_label": label, "style": 1},

            "action": {

                "type": 2,

                "permission": {"type": 2},

                "data": command,

                "enter": enter,

                "unsupport_tips": "请更新QQ版本",

            },

        }

    def _make_link_btn(self, label, url, btn_id=None, tips=None, style=0):

        """构建链接按钮(type=0)：点击后跳转到指定 URL / scheme"""

        return {

            "id": btn_id or "btn_link",

            "render_data": {"label": label, "visited_label": label, "style": style},

            "action": {

                "type": 0,               # 链接按钮

                "permission": {"type": 2},  # 所有人可点击

                "data": url,

                "unsupport_tips": tips or "请更新QQ版本后重试",

            },

        }

    def _make_group_join_btn(self):

        """「加入小流萤体验群」链接按钮：点击直接跳转腾讯官方加群分享链接，进入群聊界面。







        qun.qq.com 为腾讯自家域，QQ 链接按钮白名单内可直接跳转，无需发送二维码。







        """

        return self._make_link_btn(

            "🏠 加入小流萤体验群", get_runtime_setting_effective("experience_group.url"), btn_id="btn_join_group"

        )

    async def _send_help(self, scene: str, target_id: str, msg_id: str, event_id: str = None):

        """发送主功能菜单（6大分类按钮，点击进入子菜单）







        流程：菜单封面图以 markdown 内嵌图片形式，与文字+按钮合并为单条消息发送。







        """

        logger.info("[_send_help] 进入帮助菜单发送: scene=%s target=%s msg_id=%s" % (scene, target_id, msg_id))

        try:

            is_group = (scene == ChatScene.GROUP)

            # 各功能开关状态（用于动态过滤按钮行 + help_text）

            # 当系统总开关开启但所有子功能都关闭时，也视为整个分类不可用，

            # 避免主菜单还展示一个空分类入口。

            def _cat_on(master):
                # 插件动态化：master 聚合 key 已拆细（tool_*/study_*/video_*/image_*/game_*）时，
                # 该分类下任一子插件已安装且开启即显示分类入口；无任何子插件时隐藏。
                _master_desc = get_plugin(master)
                if _master_desc is None:
                    _subs = get_sub_features_by_master(master)
                    if not _subs:
                        return False
                    if not is_feature_enabled(master, appid=self.bot_appid):
                        return False
                    return any(
                        get_plugin(k) is not None and is_sub_feature_enabled(k, appid=self.bot_appid)
                        for k in _subs
                    )
                if not is_feature_enabled(master, appid=self.bot_appid):
                    return False
                subs = get_sub_features_by_master(master)
                return any(is_sub_feature_enabled(k, appid=self.bot_appid) for k in subs) if subs else True

            checkin_on = _cat_on("checkin")

            video_on = _cat_on("video")

            music_on = _cat_on("music")

            game_on = _cat_on("game")

            tools_on = _cat_on("tools")

            study_on = _cat_on("study")

            novel_on = _cat_on("novel")

            image_on = _cat_on("image")

            group_admin_on = _cat_on("group_admin")

            # 各功能专属小提示（仅开启时显示）

            tips = []

            tips.append("飞萤扑火，向死而生。我为自我而战，直至一切燃烧殆尽。")

            tips_block = ("\n".join(tips) + "\n") if tips else ""

            # 拉一条随机一言（带书名/作者，无出处则省略；失败时静默返回空行，不影响菜单发送）

            yiyan_line = format_yiyan_line(await fetch_yiyan())

            # === 新版：从 data/feature_menu.yaml 读配置生成 keyboard ===
            # 默认配置与原 12 个硬编码按钮完全一致，支持控制台编辑 + hot reload
            try:
                from modules import feature_menu as _fm
                _menu = _fm.load_menu()
                help_text = _fm.build_help_text(_menu, yiyan_line)
            except Exception as _e:
                logger.warning("[_send_help] 读 feature_menu 失败，回退硬编码: %s" % _e)
                _menu = None
                help_text = (

                    "![menu_banner#150px #150px](https://i.ibb.co/bjzNps00/P-2026-0805-025230.png)\n"

                    "# 小流萤功能菜单\n"

                    f"{tips_block}"

                    f"{yiyan_line}"

                )

            # 动态按钮行（按开关过滤，避免显示禁用功能入口）

            def _row(*pairs):

                # pairs: (label, command) 元组列表

                return {"buttons": [self._make_btn(lbl, cmd) for lbl, cmd in pairs]}

            def _btn(pairs, enabled, label, cmd):

                return (label, cmd) if enabled else None

            # === 构建 ctx 供 _fm.build_keyboard 使用 ===
            _fm_ctx = {
                "is_group": is_group,
                "checkin_on": checkin_on,
                "video_on": video_on,
                "music_on": music_on,
                "image_on": image_on,
                "game_on": game_on,
                "tools_on": tools_on,
                "study_on": study_on,
                "novel_on": novel_on,
                "group_admin_on": group_admin_on,
                "feedback_enabled": bool(get_runtime_setting_effective("feedback.enabled")),
                "experience_group_enabled": bool(get_runtime_setting_effective("experience_group.enabled")),
            }
            try:
                _feedback_url = get_runtime_setting_effective("feedback.form_url") or ""
                _exp_url = get_runtime_setting_effective("experience_group.url") or ""
            except Exception:
                _feedback_url = ""
                _exp_url = ""
            _fm_ctx["feedback.form_url"] = _feedback_url
            _fm_ctx["experience_group.url"] = _exp_url

            if _menu is not None:
                # === 新版：让 feature_menu 生成 keyboard ===
                try:
                    keyboard = _fm.build_keyboard(_menu, _fm_ctx)
                    # 转回 bot.py 现有结构（key 不变，rows 是 list of {"buttons": [...]})
                    rows = keyboard.get("content", {}).get("rows", [])
                except Exception as _e2:
                    logger.warning("[_send_help] build_keyboard 失败，回退硬编码: %s" % _e2)
                    rows = None
            else:
                rows = None

            if rows is None:
                # === 兜底：原硬编码逻辑（如果 feature_menu 加载失败）===
                rows = []

                # 第1行：签到 + 视频 + 音乐（仅显示开启项）

                r1 = list(filter(None, [

                    _btn(None, checkin_on, "📝 签到", "签到菜单"),

                    _btn(None, video_on, "🎬 视频", "视频菜单"),

                    _btn(None, music_on, "🎵 音乐", "音乐菜单"),

                    _btn(None, image_on, "🖼️ 图片", "图片菜单"),

                ]))

                if r1:

                    rows.append({"buttons": [self._make_btn(l, c) for l, c in r1]})

                # 第2行：娱乐 + 工具 + 小说（novel 仅开启时显示）

                r2 = list(filter(None, [

                    _btn(None, game_on, "🎮 娱乐", "娱乐菜单"),

                    _btn(None, tools_on, "🛠 工具", "工具菜单"),

                    _btn(None, novel_on, "📖 小说", "小说菜单"),

                ]))

                if r2:

                    rows.append({"buttons": [self._make_btn(l, c) for l, c in r2]})

                # 第3行：学习（始终独立行）；群管仅群聊且开启

                r3 = []

                if study_on:

                    r3.append(("📚 学习", "学习菜单"))

                if is_group and group_admin_on:

                    r3.append(("⚙️ 群管", "群管菜单"))

                # 游戏工具聚合按钮（原神 + 崩铁 + 鸣潮），任一游戏插件在控制台启用时显示；全禁用则不显示
                try:
                    if any(is_plugin_enabled(k) for k in ("genshin_miao", "genshin", "starrail", "ww_gacha")):
                        r3.append(("🎮 游戏工具", "游戏工具菜单"))
                except Exception:
                    pass

                if r3:

                    rows.append({"buttons": [self._make_btn(l, c) for l, c in r3]})

                # 反馈入口（受「反馈开关」控制，QQ 链接按钮，点击直接跳转收集表）

                # docs.qq.com 在 QQ 链接按钮白名单内，type=0 链接按钮全版本可用

                rows.append({"buttons": [self._make_link_btn(

                    "📝 反馈", get_runtime_setting_effective("feedback.form_url"), btn_id="btn_feedback_link")]})

                # 最后一行：加入体验群（链接按钮，独占一行更醒目）

                rows.append({"buttons": [self._make_group_join_btn()]})

            # 兜底：所有功能都关闭时，至少显示"全部已关闭"提示，并清掉功能按钮行

            if not (checkin_on or video_on or music_on or game_on or tools_on or study_on or novel_on or image_on or (is_group and group_admin_on)):

                help_text = "![menu_banner#150px #150px](https://i.ibb.co/bjzNps00/P-2026-0805-025230.png)\n# 小流萤功能菜单\n━━━━━━━━━━━━━━━\n⚠️ 当前所有功能均已关闭\n请在控制台开启后重试"

                rows = [{"buttons": [self._make_group_join_btn()]}]

            # 按运行设置开关过滤体验群/反馈菜单按钮
            _filtered = []
            for _r in rows:
                _btns = _r.get("buttons") or []
                _keep = True
                for _b in _btns:
                    _bid = _b.get("id")
                    if _bid and _bid.startswith("btn_menu_link_") and "experience_group" in (_b.get("action", {}).get("data", "")) and not get_runtime_setting_effective("experience_group.enabled"):
                        _keep = False
                        break
                    if _bid and _bid.startswith("btn_menu_link_") and "form_url" in str(_b.get("render_data", {}).get("label", "")) and not get_runtime_setting_effective("feedback.enabled"):
                        _keep = False
                        break
                if _keep:
                    _filtered.append(_r)
            rows = _filtered

            keyboard = {"content": {"rows": rows}}

            await self._send_help_combined(scene, target_id, help_text, keyboard, msg_id, event_id)

            return True

        except Exception as e:

            logger.error("[_send_help] 异常: %s" % e)

            import traceback

            logger.error(traceback.format_exc())

            try:

                await send_text(self.api, scene, target_id,

                                "# 小流萤功能菜单\n签到/视频/音乐/娱乐/工具/群管\n发送「帮助」查看详情",

                                msg_id=msg_id, event_id=event_id)

            except Exception:

                pass

            return None

    async def _send_help_combined(self, scene: str, target_id: str, help_text: str,

                                   keyboard: dict,

                                   msg_id: str, event_id: str = None):

        """单条消息：markdown + 按钮。



        



        图片以 markdown 内嵌图片形式，与文字+按钮合并在单条消息中（不再单独发图）。



        



        """

        try:

            result = await send_text_with_keyboard(

                self.api, scene, target_id, help_text, keyboard, msg_id=msg_id, event_id=event_id,

            )

            if result is None:

                logger.warning("[_send_help_combined] 发送失败，降级为纯文本")

                await send_text(self.api, scene, target_id, help_text, msg_id=msg_id, event_id=event_id)

        except Exception as e:

            logger.error("[_send_help_combined] 异常: %s" % e)

            import traceback

            logger.error(traceback.format_exc())

            await send_text(self.api, scene, target_id, help_text, msg_id=msg_id, event_id=event_id)

    async def _is_bot_group_admin(self, group_openid: str) -> bool:

        """带缓存检测机器人是否本群管理员；best-effort，探测异常时默认视为管理员（不误报）。"""

        import time as _t

        _now = _t.time()

        _hit = _BOT_ADMIN_STATUS_CACHE.get(group_openid)

        if _hit and _hit[1] > _now:

            return _hit[0]

        try:

            _ok = await group_admin.check_admin_status(self.api, group_openid)

        except Exception:

            _ok = True

        _BOT_ADMIN_STATUS_CACHE[group_openid] = (_ok, _now + 300)

        return _ok

    async def _send_help_category(self, scene: str, target_id: str, category: str, msg_id: str, event_id: str = None):

        """发送分类子菜单（具体功能按钮 + 返回主菜单）。任意层级都走这个函数。"""

        try:

            is_group = (scene == ChatScene.GROUP)

            if category == "图片":

                category = "图片菜单"

            # === 新版：从 menu_tree.yaml 读节点生成子菜单 keyboard（任意层级）===
            try:
                from modules import feature_menu as _fm
                _node = _fm.get_node([category])
            except Exception as _e:
                logger.warning("[_send_help_category] 读 menu_tree 失败: %s" % _e)
                _node = None

            if not _node:
                # 未配置 → 静默返回（避免报错）
                return

            title = _node.get("title", f"# {category}")

            if category == "群管菜单" and is_group:

                try:

                    if not await self._is_bot_group_admin(target_id):

                        title += ("\n\n❌ 检测到当前机器人不是本群管理员，撤回 / 禁言 / 踢人等主动操作将无法执行。"

                                  "请群主在群设置中将机器人设为管理员并开启「主动发言权限」。")

                except Exception:

                    pass

            rows = []

            for row_buttons in (_node.get("buttons") or []):

                btns = []

                for btn in (row_buttons or []):

                    cmd = btn.get("data", "")
                    label = btn.get("label", "")
                    enter = bool(btn.get("enter", True))
                    required = btn.get("required")

                    if not label or not cmd:
                        continue

                    # 子功能开关：关闭则不显示该按钮（导航类按钮无对应开关，始终显示）
                    _sk = sub_feature_key_for_cmd(cmd)
                    if _sk is not None and not is_sub_feature_enabled(_sk, appid=self.bot_appid):
                        continue
                    # 外置插件开关：对应插件在控制台禁用则不显示该按钮（required 可为单 key 或 key 列表）
                    if required:
                        _reqs = required if isinstance(required, (list, tuple, set)) else [required]
                        if _reqs and not any(is_plugin_enabled(k) for k in _reqs):
                            continue

                    btns.append(self._make_btn(label, cmd, enter=enter))

                if btns:

                    rows.append({"buttons": btns})

            # 按运行设置开关过滤体验群/反馈菜单按钮
            _filtered = []
            for _r in rows:
                _btns = _r.get("buttons") or []
                _keep = True
                for _b in _btns:
                    _bid = _b.get("id")
                    if _bid == "btn_join_group" and not get_runtime_setting_effective("experience_group.enabled"):
                        _keep = False
                        break
                    if _bid == "btn_feedback_link" and not get_runtime_setting_effective("feedback.enabled"):
                        _keep = False
                        break
                if _keep:
                    _filtered.append(_r)
            rows = _filtered

            keyboard = {"content": {"rows": rows}}

            await send_text_with_keyboard(

                self.api, scene, target_id, title, keyboard, msg_id=msg_id, event_id=event_id,

            )

        except Exception as e:

            logger.error("[_send_help_category] 异常: %s" % e)

            import traceback

            logger.error(traceback.format_exc())

# ============ 启动 ============

_console_started = False

def _build_intents():

    """构建订阅意图（每个 bot 客户端独立一份）。"""

    intents = botpy.Intents(

        public_guild_messages=True,

        public_messages=True,

        direct_message=True,

        interaction=True,

    )

    if hasattr(intents, "group_member"):

        intents.group_member = True

    return intents

# ===== 热重载支撑（按 appid 粒度启停 bot 线程，不重启整个进程） =====

_BOT_THREADS = {}   # appid -> {"thread", "stop_event", "cfg"}

_BOT_LOCK = threading.Lock()

def _run_bot_in_thread(cfg, stop_event):

    """在独立线程中启动一个 botpy 客户端（每个 bot 拥有自己的事件循环）。



    stop_event.set() 时由 remove_bot 经事件循环线程触发 client.stop()。"""

    appid = str(cfg.get("appid") or "")

    # botpy Client.__init__ 内部调用 asyncio.get_event_loop()，而工作线程默认没有

    # 当前事件循环（Python 3.10+ 会抛 RuntimeError）。必须先在子线程里 set 一个。

    try:

        loop = asyncio.new_event_loop()

        asyncio.set_event_loop(loop)

        client = MyClient(_build_intents(), cfg)

        # 把 client/loop 引用写回 _BOT_THREADS，供 remove_bot 经事件循环线程干净停止

        with _BOT_LOCK:

            if appid in _BOT_THREADS:

                _BOT_THREADS[appid]["client"] = client

                _BOT_THREADS[appid]["loop"] = loop

        client.run(appid=cfg["appid"], secret=cfg["secret"])

    except Exception as e:

        # loop.stop() 经事件循环线程触发 client.run() 退出时会抛

        # “Event loop stopped before Future completed”，这是预期的热重载

        # 停止路径，记 INFO 即可，不应算作运行异常。

        if "Event loop stopped before Future completed" in str(e):

            logger.info("[bot] 机器人 %s 已通过热重载停止" % cfg.get("appid"))

        else:

            logger.error("[bot] 机器人 %s 运行异常: %s" % (cfg.get("appid"), e))

    finally:

        # 客户端退出后清理 _bot_bridges 注册

        try:

            from console_server import unregister_bot_bridge

            unregister_bot_bridge(cfg.get("appid"))

        except Exception:

            logger.exception("[bot] 清桥接失败")

        # 释放 stop_event（让 remove_bot 可以 join 后清理字典项）

        try:

            stop_event.set()

        except Exception:

            pass

def main():

    # 订阅：频道公域消息 + 群/C2C 公域消息 + 频道私信 + 互动事件（回调按钮）

    # public_guild_messages: 触发 on_at_message_create（频道 @ 机器人）

    # public_messages:       触发 on_group_at_message_create / on_c2c_message_create / on_group_message_create

    # direct_message:        触发 on_direct_message_create（频道内私信）

    # interaction:           触发 on_interaction_create（按钮回调）

    intents = botpy.Intents(

        public_guild_messages=True,

        public_messages=True,

        direct_message=True,

        interaction=True,

    )

    # 订阅 bit 24 (GROUP_MEMBER)，用于接收 GROUP_MEMBER_ADD / GROUP_MEMBER_REMOVE

    # 官方文档误标为 1<<25，实测订阅位是 24（参见 _patch_botpy_intents_group_member）

    if hasattr(intents, "group_member"):

        intents.group_member = True

    # 先启动管理后台（即使没有任何启用的 bot，也要把控制面板拉起来，让用户能进入「机器人管理」添加凭证）

    global _console_started

    if not _console_started:

        try:
            # 调试用：在 bot 启动时输出关键文件 mtime，方便确认 console_server.py / feature_menu.py 是否新版本
            import os as _dbg_os
            import time as _dbg_time
            for _f in (
                os.path.join(os.path.dirname(__file__), "console_server.py"),
                os.path.join(os.path.dirname(__file__), "modules", "feature_menu.py"),
                os.path.join(os.path.dirname(__file__), "data", "menu_tree.yaml"),
            ):
                try:
                    _m = _dbg_os.path.getmtime(_f)
                    logger.info("[启动] %s  mtime=%s  size=%d" % (_f, _dbg_time.strftime('%Y-%m-%d %H:%M:%S', _dbg_time.localtime(_m)), _dbg_os.path.getsize(_f)))
                except Exception as _ee:
                    logger.info("[启动] %s  不存在: %s" % (_f, _ee))
            logger.info("[启动] 🚀 调用 start_console_server...")
            start_console_server(open_browser=True)
            _console_started = True
            logger.info("[启动] ✅ 控制台已启动  http://127.0.0.1:9988")
        except Exception as e:
            logger.error("启动管理后台失败: %s" % e)
            return

    # 加载已启用的机器人列表（支持多 bot 并发，参考 XuanJi 设计）

    bots = bot_manager.get_enabled_bots()

    if not bots:

        # 不再 return：保持进程运行，让用户在控制面板「机器人管理」中保存后走 _bot_diff_and_reload 热添加，无需重启。

        logger.warning("尚未启用任何 QQ 机器人。请在控制面板「机器人管理」中添加凭证并启用，控制台将自动连接。")

    else:

        for cfg in bots:

            add_bot(cfg)

        logger.info("已加载 %d 个机器人配置" % len(bots))

    # 外置插件：首次扫描注册 + 启动热加载看门狗（改 plugins/ 下文件无需重启 bot 即生效）

    try:

        _loaded = scan_external_plugins()

        if _loaded:

            logger.info("[plugin] 已加载外置插件: %s" % _loaded)

        # 启动时合并外置插件 _meta 别名到触发词表（控制台保存 meta 后会自动再刷一次）
        try:
            _refresh_plugin_meta_aliases()
        except Exception as _e:
            logger.warning("[触发词] 启动时合并 meta 别名失败: %s" % _e)

        _w = threading.Thread(target=_external_plugin_watcher, name="ext-plugin-watcher", daemon=True)

        _w.start()

    except Exception as e:

        logger.error("[plugin] 外置插件初始化失败: %s" % e)

    # 主线程保持存活：控制台与所有 bot 均跑在守护线程上，若主线程直接返回，

    # 进程会立即退出并杀掉守护线程（表现为 botpy 登录中途被掐断，日志出现

    # “can't register atexit after shutdown” / ThreadPoolExecutor 导入失败），

    # 9988 也会随之消失。故主线程在此永久阻塞，由控制看门狗 / 外部 taskkill 终止。

    try:

        while True:

            time.sleep(3600)

    except KeyboardInterrupt:

        logger.info("[bot] 收到中断信号，准备退出")

def add_bot(cfg):

    """线程安全地添加一个 bot client 线程；appid 已存在则跳过。"""

    appid = str(cfg.get("appid") or "")

    if not appid:

        return False, "appid 缺失"

    with _BOT_LOCK:

        if appid in _BOT_THREADS:

            return False, "bot %s 已在运行" % appid

        stop_event = threading.Event()

        t = threading.Thread(

            target=_run_bot_in_thread, args=(cfg, stop_event),

            name="bot-%s" % appid, daemon=True,

        )

        t.start()

        _BOT_THREADS[appid] = {"thread": t, "stop_event": stop_event, "cfg": cfg}

    logger.info("[bot] 新增 bot-%s", appid)

    return True, "已启动"

def remove_bot(appid):

    """线程安全地停止并清理一个 bot client；不存在则跳过。"""

    appid = str(appid or "")

    with _BOT_LOCK:

        info = _BOT_THREADS.pop(appid, None)

    if not info:

        return False, "bot %s 不存在" % appid

    # botpy 的 Client 没有 stop() 方法，它靠 self.loop.run_until_complete 阻塞运行。

    # 因此在事件循环线程内调用 loop.stop() 即可让 client.run() 返回（run_until_complete

    # 会抛 RuntimeError 被外层捕获），线程随后干净退出并解注册桥接。不引入额外 watcher 线程。

    client = info.get("client")

    loop = info.get("loop") or getattr(client, "loop", None)

    if loop is not None and loop.is_running():

        try:

            loop.call_soon_threadsafe(loop.stop)

        except Exception:

            logger.exception("[bot-%s] call_soon_threadsafe(loop.stop) 失败", appid)

    # 给 client.run() 一点时间干净退出，最多等 6s

    info["thread"].join(timeout=6)

    logger.info("[bot] 已停 bot-%s", appid)

    return True, "已停止"

def reload_bot(appid, new_cfg):

    """凭据变更：停旧启新；凭据相同则 no-op；若尚未运行则 add。"""

    appid = str(appid or "")

    with _BOT_LOCK:

        old = _BOT_THREADS.get(appid)

    if old is None:

        return add_bot(new_cfg)

    if old["cfg"].get("secret") == new_cfg.get("secret"):

        return True, "no-op"

    ok, msg = remove_bot(appid)

    if not ok:

        return False, msg

    return add_bot(new_cfg)

def list_running_bots():

    """返回 [(appid, cfg), ...] 列表，cfg 是副本。"""

    with _BOT_LOCK:

        return [(aid, dict(info["cfg"])) for aid, info in _BOT_THREADS.items()]

def _apply_bots_diff():

    """应用 bots.json 的最新配置到运行中的 bot 集合（按 appid 粒度）。



    返回 {"added": [...], "removed": [...], "reloaded": [...], "kept": [...]}。



    控制台 /api/bots/reload 调用此函数即可即时生效，无需重启进程。"""

    new_bots = bot_manager.load_bots()

    old_running = list_running_bots()

    old_cfg_map = {aid: cfg for aid, cfg in old_running}

    summary = {"added": [], "removed": [], "reloaded": [], "kept": []}

    # 1) 已不在 json 中 / 禁用 -> 停

    for aid in list(old_cfg_map.keys()):

        nb = next((b for b in new_bots if str(b.get("appid") or "") == aid), None)

        if not nb or not nb.get("enabled"):

            ok, _ = remove_bot(aid)

            if ok:

                summary["removed"].append(aid)

    # 2) json 里有且启用的 -> add / reload / keep

    for nb in new_bots:

        aid = str(nb.get("appid") or "")

        if not aid or not nb.get("enabled"):

            continue

        if aid in old_cfg_map:

            if old_cfg_map[aid].get("secret") != nb.get("secret"):

                ok, _ = reload_bot(aid, nb)

                if ok:

                    summary["reloaded"].append(aid)

            else:

                summary["kept"].append(aid)

        else:

            ok, _ = add_bot(nb)

            if ok:

                summary["added"].append(aid)

    logger.info("[bot] 热重载 diff: %s", summary)

    return summary

    # 主线程保持存活（看门狗 / 控制台在各自线程运行）

    try:

        while True:

            time.sleep(3600)

    except KeyboardInterrupt:

        logger.info("收到退出信号")

if __name__ == "__main__":

    main()

