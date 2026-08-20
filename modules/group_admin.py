# -*- coding: utf-8 -*-

import aiohttp

"""

群管系统模块

提供违禁词过滤、管理员状态检测等群管理功能。



注意（QQ 机器人官方 API 限制）：

    1. 群消息仅提供 group_openid 与 member_openid，无法获取头像/昵称。

    2. 违禁词命中后撤回该消息并文字提醒；撤回需要机器人是群管理员，否则会失败。

    3. 撤回消息需要群主将机器人设置为群管理员，否则会失败。



数据存储（data/group_admin.json）：

{

    "group_openid": {

        "banned_words": ["违禁词1", "违禁词2"],   # 违禁词列表

    }

}

"""



from modules.common import (

    send_group_text,

    send_group_text_with_keyboard,
    send_group_markdown,
    send_group_image,

    recall_group_message,

    load_json,

    save_json,

    data_path,

    build_keyboard_command,

    build_keyboard_multi,

    build_keyboard_callback,

    is_duplicate,

    clean_content,

    next_seq,

    today_str,

    yesterday_str,

    logger,

    http_get,

    http_post,

    ChatScene,

    send_local_image_for_scene,

)


# 群管数据存储文件名（位于 data/ 目录下）

GROUP_ADMIN_FILE = "group_admin.json"








class GroupAdminManager:

    """群管系统：违禁词过滤。

    权限模型：所有群管操作（设置 / 添加 / 删除）仅限
    群主、群管理员或控制台管理员（data/admin_list.json）执行，
    其余成员调用会被统一拒绝。
    """



    def __init__(self):

        pass




    # ============ 数据读写 ============



    def _load_data(self) -> dict:

        """加载全部群管配置"""

        return load_json(GROUP_ADMIN_FILE)



    def _save_data(self, data: dict):

        """保存全部群管配置"""

        save_json(GROUP_ADMIN_FILE, data)



    def _ensure_group_config(self, data: dict, group_openid: str) -> dict:

        """

        确保 data 中存在指定群的配置（不存在则初始化默认配置），

        并兼容补全缺失字段，返回该群配置的引用。

        """

        if group_openid not in data:

            data[group_openid] = {

                "banned_words": [],

                "mute_duration": 600,        # 默认禁言 10 分钟

                "mute_on_banword": True,     # 默认：违禁词触发后自动禁言该用户

            }

        cfg = data[group_openid]

        # 兼容旧数据，补全可能缺失的字段

        cfg.setdefault("banned_words", [])

        cfg.setdefault("mute_duration", 600)

        cfg.setdefault("mute_on_banword", True)

        return cfg



    def _get_group_config(self, group_openid: str) -> dict:

        """获取单个群的配置（不存在则初始化）"""

        data = self._load_data()

        return self._ensure_group_config(data, group_openid)



    # ============ 管理员状态检测 ============



    async def check_admin_status(self, api, group_openid: str) -> bool:

        """

        检测机器人是否为该群管理员。



        实现方式：尝试撤回一条不存在的测试消息ID，根据返回错误判断权限：

          - 错误为「权限不足」类 -> 非管理员，返回 False

          - 错误为「消息不存在」类或无异常 -> 有操作权限，返回 True



        说明：该方法为尽力检测（best-effort），QQ API 未提供直接查询

              群成员权限的接口，只能通过撤回操作的错误码间接判断。

        """

        from botpy.http import Route

        try:

            route = Route(

                "DELETE",

                "/v2/groups/{group_openid}/messages/{message_id}",

                group_openid=group_openid,

                message_id="0",  # 不存在的消息ID，仅用于权限探测

            )

            await api._http.request(route)

            # 走到这里说明未抛异常（极少情况），视为有权限

            return True

        except Exception as e:

            err = str(e)

            logger.info("管理员权限探测返回错误: %s" % err)

            # 命中权限不足相关关键词 -> 非管理员

            deny_keywords = ["权限", "permission", "denied", "forbidden", "无权", "12003"]

            if any(k.lower() in err.lower() for k in deny_keywords):

                return False

            # 其余错误（如消息不存在）说明具备操作权限，仅消息无效

            return True



    # ============ 管理员权限检测 ============



    @staticmethod

    def _is_admin(member_role: str) -> bool:

        """

        判断用户是否为群主或管理员。

        member_role 取自 QQ 事件 author.member_role 字段：

          - "owner"  → 群主

          - "admin"  → 管理员

          - "member" → 普通成员

        参考: https://bot.qq.com/wiki/develop/api-v2/server-inter/message/send-receive/event.html

        """

        return member_role in ("owner", "admin")



    # ============ 违禁词功能 ============



    # ---- 违禁词读取/设置（供控制台「违禁词和禁言管理」使用，无需 api）----
    def get_banned_words(self, group_openid):
        cfg = self._get_group_config(group_openid)
        return list(cfg.get("banned_words", []))

    def set_banned_words(self, group_openid, words):
        data = self._load_data()
        cfg = self._ensure_group_config(data, group_openid)
        cfg["banned_words"] = [w.strip() for w in (words or []) if w and w.strip()]
        self._save_data(data)
        return list(cfg["banned_words"])

    async def check_banned_word(self, api, content: str, group_openid: str,
                                 msg_id: str, member_openid: str = "") -> bool:

        """

        检测消息是否命中违禁词。

        命中则撤回消息并文字提醒；若该群「违禁词自动禁言」开关开启，则对触发用户执行禁言。

        参数：

            member_openid  触发用户 openid（QQ 事件 author.member_openid）；

                           提供且该群 mute_on_banword=True 时会调用 mute_member。

        返回 True 表示命中违禁词并已处理，False 表示未命中。

        建议在 bot 主消息处理流程中：先调用 handle_command 处理指令，

        若未被指令处理，再调用本方法做违禁词过滤。

        """

        config = self._get_group_config(group_openid)

        banned_words = config.get("banned_words", [])

        if not banned_words:

            return False



        # 命中检测（任一违禁词作为子串出现即视为命中）

        hit_word = None

        for word in banned_words:

            if word and word in content:

                hit_word = word

                break

        if not hit_word:

            return False



        # 尝试撤回违规消息

        ok = await recall_group_message(api, group_openid, msg_id)

        if not ok:

            # 撤回失败 -> 机器人非管理员，此时原消息仍在，可用 msg_id 被动回复

            await send_group_text(

                api, group_openid,

                "请设置机器人为管理员，否则无法使用该功能",

                msg_id=msg_id,

            )

        else:

            # 撤回成功 -> 发送提醒（原消息已被撤回，先尝试被动回复，失败则主动发送）

            notify = "⚠️ 检测到违禁词，消息已撤回"

            result = await send_group_text(api, group_openid, notify, msg_id=msg_id)

            if result is None:

                # 被动回复失败（原消息已撤回导致 msg_id 失效），回退为主动消息

                await send_group_text(api, group_openid, notify)

        # ---- 违禁词触发后自动禁言该用户（每群独立开关/时长）----

        try:

            mute_on = bool(config.get("mute_on_banword", True))

        except Exception:

            mute_on = True

        _muted = False
        _mute_dur = 0
        if mute_on and member_openid:

            try:

                dur = int(config.get("mute_duration", 600) or 600)

                if dur < 1:

                    dur = 600

                mute_ok, mute_msg = self.mute_member(group_openid, member_openid, duration=dur)

                if mute_ok:
                    _muted = True
                    _mute_dur = dur

                    tip = ("🚫 已对触发用户执行禁言 %d 秒（每群独立设置）。" % dur)

                    await send_group_text(api, group_openid, tip)

                else:

                    logger.warning("违禁词自动禁言失败 group=%s member=%s err=%s"

                                   % (group_openid, member_openid, mute_msg))

            except Exception as e:

                logger.warning("违禁词自动禁言异常: %s" % e)

        # 记录拦截日志（本地 data/banword_log.json，不发送到 QQ）
        self._log_banword_hit(
            group_openid, member_openid, hit_word,
            recalled=ok, muted=_muted, mute_duration=_mute_dur,
        )

        return True


    def _log_banword_hit(self, group_openid, member_openid, word, recalled, muted, mute_duration):
        """记录一次违禁词拦截（撤回 / 禁言）。写入 data/banword_log.json（本地日志，不发送到 QQ）。"""

        try:
            import datetime as _dt

            logs = load_json("banword_log.json") or []

            if not isinstance(logs, list):
                logs = []

            entry = {
                "ts": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                "group_openid": group_openid,
                "member_openid": member_openid or "",
                "word": word or "",
                "recalled": bool(recalled),
                "muted": bool(muted),
                "mute_duration": int(mute_duration) if mute_duration else 0,
            }

            logs.insert(0, entry)

            # 仅保留最近 1000 条，避免无限增长
            if len(logs) > 1000:
                logs = logs[:1000]

            save_json("banword_log.json", logs)

        except Exception as e:
            logger.warning("写入违禁词拦截日志失败: %s" % e)


    async def _add_banned_word(self, api, word: str, group_openid: str, msg_id: str):

        """添加违禁词"""

        word = word.strip()

        if not word:

            await send_group_text(api, group_openid, "请输入需要添加的违禁词", msg_id=msg_id)

            return

        data = self._load_data()

        config = self._ensure_group_config(data, group_openid)

        banned = config["banned_words"]

        if word in banned:

            await send_group_text(api, group_openid, "违禁词已存在", msg_id=msg_id)

            return

        banned.append(word)

        self._save_data(data)

        await send_group_text(

            api, group_openid,

            "违禁词已添加",

            msg_id=msg_id,

        )



    async def _remove_banned_word(self, api, word: str, group_openid: str, msg_id: str):

        """删除违禁词"""

        word = word.strip()

        if not word:

            await send_group_text(api, group_openid, "请输入需要删除的违禁词", msg_id=msg_id)

            return

        data = self._load_data()

        config = data.get(group_openid, {})

        banned = config.get("banned_words", [])

        if word not in banned:

            await send_group_text(api, group_openid, "该违禁词不存在", msg_id=msg_id)

            return

        banned.remove(word)

        self._save_data(data)

        await send_group_text(api, group_openid, "违禁词已删除", msg_id=msg_id)







    # ============ 禁言功能（QQ 官方 POST /v2/groups/{openid}/restrict_chat_setting） ============
    #
    # 官方接口（参考 QQ 机器人官方文档「设置群成员禁言」）：
    #   端点：POST /v2/groups/{group_openid}/restrict_chat_setting
    #   频限：60 QPM
    #   请求体：{"members": [{"op": "add"/"update"/"del",
    #                          "member_openid": "...", "mute_expire_at": "RFC3339"}]}
    #   说明：op=add 增加禁言；op=update 更新到期时间；op=del 解除禁言
    #         mute_expire_at 为 RFC3339 时间字符串（如 2026-08-05T11:23:05+08:00），
    #         op=del 时可不传或传空字符串表示立即解除。
    #   限制：单次最多 10 个成员；只能禁言普通成员，不能操作群主/管理员/机器人。
    # ----------------------------------------------------------------

    @staticmethod
    def _format_rfc3339(dt):
        """把 datetime 转成 RFC3339（带时区偏移），供官方 mute_expire_at 使用。"""
        try:
            import datetime as _dt
            if dt.tzinfo is None:
                # 视为本地时间（与控制台/服务器一致）
                dt = dt.astimezone()
            # 输出到秒级、保留时区偏移，例如 2026-08-12T17:30:00+08:00
            return dt.strftime("%Y-%m-%dT%H:%M:%S%z")
        except Exception:
            # fallback: 用当前 UTC 时间 + duration
            import datetime as _dt
            return (_dt.datetime.utcnow() + _dt.timedelta(seconds=600)).strftime("%Y-%m-%dT%H:%M:%SZ")

    async def _async_set_member_mute(self, api, group_openid: str, member_openid: str,
                                     duration_seconds: int):
        """异步：对单个成员下禁言。返回 (ok: bool, payload: dict|str)。"""
        try:
            import datetime as _dt
            from botpy.http import Route
            expire = _dt.datetime.now().astimezone() + _dt.timedelta(seconds=int(duration_seconds))
            mute_expire_at = self._format_rfc3339(expire)
            route = Route("POST", "/v2/groups/{group_openid}/restrict_chat_setting",
                          group_openid=group_openid)
            body = {"members": [{"op": "add", "member_openid": member_openid,
                                 "mute_expire_at": mute_expire_at}]}
            result = await api._http.request(route, json=body)
            return True, (result if isinstance(result, dict) else {"raw": result})
        except Exception as e:
            return False, "official restrict_chat_setting exception: %s" % e

    async def _async_unmute_member(self, api, group_openid: str, member_openid: str):
        """异步：解除单个成员禁言（op=del）。"""
        try:
            from botpy.http import Route
            route = Route("POST", "/v2/groups/{group_openid}/restrict_chat_setting",
                          group_openid=group_openid)
            body = {"members": [{"op": "del", "member_openid": member_openid}]}
            result = await api._http.request(route, json=body)
            return True, (result if isinstance(result, dict) else {"raw": result})
        except Exception as e:
            return False, "official restrict_chat_setting unmute exception: %s" % e

    def mute_member(self, group_openid: str, member_openid: str,
                    duration: int = None, appid: str = None):
        """同步包装：从任意线程发起成员禁言（60 QPM，kind=restrict_chat）。

        duration 为 None 时读取本群配置的 mute_duration（每群独立）。
        """
        group_openid = str(group_openid or "").strip()
        member_openid = str(member_openid or "").strip()
        if not group_openid or not member_openid:
            return False, "group_openid / member_openid 不能为空"
        if duration is None:
            cfg = self._get_group_config(group_openid)
            duration = int(cfg.get("mute_duration", 600) or 600)
        duration = max(1, int(duration))

        try:
            from console_server import (
                _qpm_acquire, get_bridge, get_bridge_for_chat,
                _mute_member_via_qq_sync,
            )
        except Exception:
            _qpm_acquire = None
            get_bridge = None
            get_bridge_for_chat = None
            _mute_member_via_qq_sync = None

        # 优先用 console_server 提供的统一桥接 + QPM
        if _mute_member_via_qq_sync is not None:
            return _mute_member_via_qq_sync(group_openid, member_openid, duration, appid=appid)

        # 兜底：直接尝试 get_bridge（在没有 console_server 的环境也能跑）
        if _qpm_acquire is None or get_bridge is None:
            return False, "console_server 不可用，无法桥接到 bot 事件循环"
        bot_appid = str(appid or "default")
        if not _qpm_acquire(bot_appid, kind="restrict_chat", limit=60):
            return False, "频率限制：超过 60 QPM，请稍后再试"
        bridge = get_bridge(appid) if appid else None
        if bridge is None:
            bridge = get_bridge_for_chat("g:" + group_openid) if get_bridge_for_chat else None
        if bridge is None:
            bridge = get_bridge()
        if not bridge or not bridge.get("api"):
            return False, "机器人桥接不可用"
        api = bridge["api"]; loop = bridge.get("loop")
        if loop is None or not loop.is_running():
            return False, "机器人事件循环不可用"
        import asyncio
        try:
            fut = asyncio.run_coroutine_threadsafe(
                self._async_set_member_mute(api, group_openid, member_openid, duration), loop)
            raw = fut.result(timeout=15)
            return True, raw
        except Exception as e:
            return False, "官方 restrict_chat_setting 调用失败：%s" % e

    def unmute_member(self, group_openid: str, member_openid: str, appid: str = None):
        """同步包装：解除单个成员禁言。"""
        group_openid = str(group_openid or "").strip()
        member_openid = str(member_openid or "").strip()
        if not group_openid or not member_openid:
            return False, "group_openid / member_openid 不能为空"
        try:
            from console_server import (
                _qpm_acquire, get_bridge, get_bridge_for_chat,
                _unmute_member_via_qq_sync,
            )
        except Exception:
            _qpm_acquire = None; get_bridge = None; get_bridge_for_chat = None
            _unmute_member_via_qq_sync = None
        if _unmute_member_via_qq_sync is not None:
            return _unmute_member_via_qq_sync(group_openid, member_openid, appid=appid)
        if _qpm_acquire is None or get_bridge is None:
            return False, "console_server 不可用，无法桥接到 bot 事件循环"
        bot_appid = str(appid or "default")
        if not _qpm_acquire(bot_appid, kind="restrict_chat", limit=60):
            return False, "频率限制：超过 60 QPM，请稍后再试"
        bridge = get_bridge(appid) if appid else None
        if bridge is None:
            bridge = get_bridge_for_chat("g:" + group_openid) if get_bridge_for_chat else None
        if bridge is None:
            bridge = get_bridge()
        if not bridge or not bridge.get("api"):
            return False, "机器人桥接不可用"
        api = bridge["api"]; loop = bridge.get("loop")
        if loop is None or not loop.is_running():
            return False, "机器人事件循环不可用"
        import asyncio
        try:
            fut = asyncio.run_coroutine_threadsafe(
                self._async_unmute_member(api, group_openid, member_openid), loop)
            raw = fut.result(timeout=15)
            return True, raw
        except Exception as e:
            return False, "官方 restrict_chat_setting 解除失败：%s" % e

    # ---- 配置读写（每群独立） ----

    def get_mute_duration(self, group_openid: str) -> int:
        cfg = self._get_group_config(group_openid)
        try:
            return max(1, int(cfg.get("mute_duration", 600) or 600))
        except Exception:
            return 600

    def set_mute_duration(self, group_openid: str, duration: int) -> int:
        data = self._load_data()
        cfg = self._ensure_group_config(data, group_openid)
        try:
            d = int(duration)
        except Exception:
            d = 600
        if d < 1:
            d = 1
        cfg["mute_duration"] = d
        self._save_data(data)
        return d

    def get_mute_on_banword(self, group_openid: str) -> bool:
        cfg = self._get_group_config(group_openid)
        return bool(cfg.get("mute_on_banword", True))

    def set_mute_on_banword(self, group_openid: str, enabled: bool) -> bool:
        data = self._load_data()
        cfg = self._ensure_group_config(data, group_openid)
        cfg["mute_on_banword"] = bool(enabled)
        self._save_data(data)
        return bool(enabled)

    # ---- 菜单渲染 ----

    async def _send_mute_parent(self, api, group_openid: str, msg_id: str):
        """禁言管理父菜单（二级）。列出本群当前禁言时长与自动处理开关。"""
        cfg = self._get_group_config(group_openid)
        dur = self.get_mute_duration(group_openid)
        auto_on = self.get_mute_on_banword(group_openid)
        auto_text = "✅ 已开启" if auto_on else "⏹ 已关闭"
        text = (
            "🔇 禁言管理\n"
            "当前禁言时长：%d 秒（每群独立设置）\n"
            "违禁词自动禁言：%s\n"
            "点击下方按钮操作（仅群主/群管理员/控制台管理员可改）：" % (dur, auto_text)
        )
        keyboard = build_keyboard_multi([
            {"label": "⏱ 禁言时长设置", "command": "禁言时长设置", "id": "btn_mute_dur", "enter": False},
            {"label": "🎚 禁言自动处理", "command": "禁言自动处理", "id": "btn_mute_auto", "enter": False},
            {"label": "🔙 返回群管菜单", "command": "群管菜单", "id": "btn_mute_back", "enter": False},
        ])
        await send_group_text_with_keyboard(api, group_openid, text, keyboard, msg_id=msg_id)

    async def _send_mute_settings(self, api, group_openid: str, msg_id: str):
        """禁言设置子菜单：时长切换 / 自动处理切换。"""
        dur = self.get_mute_duration(group_openid)
        auto_on = self.get_mute_on_banword(group_openid)
        auto_text = "✅ 开启" if auto_on else "⏹ 关闭"
        text = (
            "⚙️ 禁言设置\n"
            "时长：%d 秒 ｜ 自动处理：%s\n"
            "快速档位（点击即可）：" % (dur, auto_text)
        )
        keyboard = build_keyboard_multi([
            {"label": "时长 60秒",   "command": "禁言时长 60",   "id": "btn_mute_dur_60",  "enter": False},
            {"label": "时长 10分",   "command": "禁言时长 600",  "id": "btn_mute_dur_600", "enter": False},
            {"label": "时长 1小时",  "command": "禁言时长 3600", "id": "btn_mute_dur_3600","enter": False},
            {"label": "时长 24小时", "command": "禁言时长 86400","id": "btn_mute_dur_86400","enter": False},
            {"label": ("🚫 自动处理：关闭" if auto_on else "✅ 自动处理：开启"),
             "command": ("禁言自动关" if auto_on else "禁言自动开"),
             "id": "btn_mute_auto_toggle", "enter": False},
            {"label": "🔙 返回禁言菜单", "command": "禁言管理", "id": "btn_mute_back2", "enter": False},
        ])
        await send_group_text_with_keyboard(api, group_openid, text, keyboard, msg_id=msg_id)


    # ============ 违禁词设置子菜单 ============



    async def _send_banned_word_settings(self, api, group_openid: str, msg_id: str):

        """发送违禁词设置子菜单（带按钮）"""

        text = "🔧 违禁词设置\n点击下方按钮操作："

        keyboard = build_keyboard_multi([

            {"label": "➕ 添加违禁词", "command": "违禁词添加 ", "id": "btn_bw_add", "enter": False},

            {"label": "➖ 删除违禁词", "command": "违禁词删除 ", "id": "btn_bw_del", "enter": False},


        ])

        await send_group_text_with_keyboard(api, group_openid, text, keyboard, msg_id=msg_id)



    async def _send_banned_word_parent(self, api, group_openid: str, msg_id: str):
        """违禁词父菜单：展开『列表 / 设置 / 返回群管菜单』三个二级按钮。"""
        text = ("🚫 违禁词\n"
                "🔧 设置 / 添加 / 删除需群主、群管理员或控制台管理员（列表由控制台管理，不在群内展示）\n"
                "点击下方按钮操作：")
        keyboard = build_keyboard_multi([
            {"label": "🔧 违禁词设置", "command": "违禁词设置", "id": "btn_bw_set", "enter": False},
            {"label": "🔙 返回群管菜单", "command": "群管菜单", "id": "btn_bw_back", "enter": False},
        ])
        await send_group_text_with_keyboard(api, group_openid, text, keyboard, msg_id=msg_id)

    async def _send_chime_menu(self, api, group_openid: str, msg_id: str):
        """整点报时主菜单（二级按钮）。"""
        try:
            from console_server import get_chime_group_config, _coerce_int
            cfg = get_chime_group_config(group_openid)
            state = "✅ 已开启" if cfg.get("enabled") else "⏹ 已关闭"
            iv = _coerce_int(cfg.get("interval_hours", 1), 1)
            ps = _coerce_int(cfg.get("period_start", 0), 0)
            pe = _coerce_int(cfg.get("period_end", 23), 23)
            text = ("⏰ 整点报时（自动）\n当前状态：%s｜每 %d 小时｜时段 %02d:00–%02d:00\n"
                    "点击下方按钮操作（仅群主/管理员可改）：" % (state, iv, ps, pe))
        except Exception:
            text = "⏰ 整点报时（自动）\n点击下方按钮操作（仅群主/管理员可改）："
        keyboard = build_keyboard_multi([
            {"label": "报时开关", "command": "报时开关", "id": "btn_chime_toggle", "enter": False},
            {"label": "报时设置", "command": "报时设置", "id": "btn_chime_set", "enter": False},
            {"label": "立即报时", "command": "立即报时", "id": "btn_chime_now", "enter": False},
        ])
        await send_group_text_with_keyboard(api, group_openid, text, keyboard, msg_id=msg_id)


    async def _send_chime_settings_menu(self, api, group_openid: str, msg_id: str):
        """报时设置子菜单（间隔/时段）。"""
        text = "⚙️ 报时设置\n选择要修改的项目："
        keyboard = build_keyboard_multi([
            {"label": "报时间隔设置", "command": "报时间隔设置", "id": "btn_chime_iv", "enter": False},
            {"label": "报时时段设置", "command": "报时时段设置", "id": "btn_chime_pd", "enter": False},
        ])
        await send_group_text_with_keyboard(api, group_openid, text, keyboard, msg_id=msg_id)


    # ============ 入群通知 ============

    _WELCOME_DEFAULT_TEXT = (
        "{mention} 👋🏻 欢迎加入本群~\n"
        "\n"
        "✈ 群规速览\n"
        " - 请勿发送广告、政治、色情违规内容\n"
        " - 交流请保持庄重，互相尊重\n"
        " - 如有问题，请 @群主/管理员\n"
        " - 祝您在本群玩的开心"
    )  # 入群欢迎词为空时的兜底文案（参考 QQ 模板卡片默认布局）

    # 去重：同一群+同一成员 5 秒内只发一次。防 WS 重连回放 / 多实例残留进程重复触发。
    _welcome_sent_recently = {}  # {(group_openid, member_openid): expire_ts(float, time.time()+5)}
    _WELCOME_DEDUPE_WINDOW = 5.0

    async def _send_welcome_menu(self, api, group_openid: str, msg_id: str):
        """入群通知主菜单（二级按钮）。"""
        try:
            from console_server import get_welcome_group_config
            cfg = get_welcome_group_config(group_openid)
            state = "✅ 已开启" if cfg.get("welcome_enabled") else "⏹ 已关闭"
            wm = (cfg.get("welcome_msg") or "").strip() or "（未设置，使用默认）"
            text = ("📥 入群通知\n当前开关：%s\n入群欢迎词：%s\n"
                    "点击下方按钮操作（仅群主/管理员可改）：" % (state, wm))
        except Exception:
            text = "📥 入群通知\n点击下方按钮操作（仅群主/管理员可改）："
        keyboard = build_keyboard_multi([
            {"label": "入群欢迎词设置", "command": "入群欢迎词设置", "id": "btn_welcome_set", "enter": False},
            {"label": "入群通知开关", "command": "入群通知开关", "id": "btn_welcome_toggle", "enter": False},
        ])
        await send_group_text_with_keyboard(api, group_openid, text, keyboard, msg_id=msg_id)

    async def _send_welcome_on_add(self, api, group_openid: str, member_openid: str, username: str = "", nickname: str = "", bot_appid: str = ""):
        """新成员入群通知：单条气泡（msg_type=7 富媒体，base64 直传用户头像）。

        caption 是纯文本不解析 `<@!openid>`。因此 @昵称显礼成黑色普通文字。
        头像：bot 侧 aiohttp 下载 q.qlogo.cn/qqapp/{APPID}/{openid}/640 字节，base64 直传 QQ（绕开开放平台公网图片转存的问题）。
        充阳 @昵称的方式：msg_type=2 原生 mark（蓝色可点击 @提及）。
        """
        try:
            # ---- 去重闸门：同群+同成员 5s 内只发一次 ----
            # 防止 WS 重连回放事件 / 多残留 bot 进程 / 用户多次点击入群按钮 等导致重复欢迎
            import time
            try:
                _now = time.time()
                # 顺手清理过期键（最多保留 64 条防内存膨胀）
                if len(self._welcome_sent_recently) > 64:
                    self._welcome_sent_recently = {
                        k: v for k, v in self._welcome_sent_recently.items() if v > _now
                    }
                _key = (group_openid or "", member_openid or "")
                _exp = self._welcome_sent_recently.get(_key, 0.0)
                if _exp > _now:
                    logger.info("[入群通知] 去重跳过: 群=%s 成员=%s (剩余 %.1fs)" % (
                        group_openid, (member_openid or "")[:8], _exp - _now))
                    return
                self._welcome_sent_recently[_key] = _now + self._WELCOME_DEDUPE_WINDOW
            except Exception:
                pass
            from console_server import get_welcome_group_config
            cfg = get_welcome_group_config(group_openid)
            if not cfg.get("welcome_enabled"):
                return
            welcome = (cfg.get("welcome_msg") or "").strip() or self._WELCOME_DEFAULT_TEXT
            # 解析真实昵称：事件字段 > members.json 缓存 > OIAPI 反查 > openid[:8] > "新同学"
            raw_name = (nickname or username or "").strip()
            if not raw_name and member_openid:
                try:
                    from console_server import get_member_cached_nickname
                    cached = get_member_cached_nickname(member_openid)
                    if cached:
                        raw_name = cached
                except Exception:
                    pass
            # 冷启动充阳：库里无记录（从未聊过）时调 OIAPI 反查真实昵称
            if not raw_name and member_openid:
                try:
                    import asyncio
                    from console_server import _refresh_member_nickname_from_oiapi
                    oiapi_nick = await asyncio.to_thread(_refresh_member_nickname_from_oiapi, member_openid)
                    if oiapi_nick:
                        raw_name = oiapi_nick
                except Exception:
                    pass
            if not raw_name and member_openid:
                # 最后兜底：openid 前 8 位。日志里明确标记，避免误以为是真实昵称
                raw_name = member_openid[:8]
                logger.warning("[入群通知] 昵称解析全失败，回退 openid 前 8 位: 群=%s 成员=%s" % (
                    group_openid, member_openid))
            if not raw_name:
                raw_name = "新同学"
            # caption 用字面 @昵称（msg_type=7 content 不解析 <@!openid>）
            if "{mention}" in welcome:
                text = welcome.replace("{mention}", "@" + raw_name)
            else:
                text = "@%s %s" % (raw_name, welcome)
            # 下载头像字节 → 直接传 raw bytes（_upload_group_file 内部会 base64 上传）
            if member_openid:
                avatar_bytes = await self._download_avatar_bytes(member_openid, bot_appid)
                if avatar_bytes:
                    await send_local_image_for_scene(api, ChatScene.GROUP, group_openid, avatar_bytes, content=text)
                else:
                    # 头像下载失败：充阳发纯文本
                    await send_group_text(api, group_openid, text)
            else:
                await send_group_text(api, group_openid, text)
        except Exception as e:
            logger.error("入群通知发递失败: %s" % e)

    async def _download_avatar_bytes(self, member_openid: str, bot_appid: str = "") -> bytes:
        """从 q.qlogo.cn 下载用户头像字节（沙箱实测可达）。失败返回空字节。
        尺寸限定 100x100（QQ 标准头像尺寸），避免富媒体气泡里头像过大撑满整图。
        """
        try:
            import aiohttp
            from modules.config import APPID
            url = "https://q.qlogo.cn/qqapp/%s/%s/100" % (bot_appid or APPID, member_openid)
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
                async with session.get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://qq.com"}) as resp:
                    if resp.status == 200:
                        return await resp.read()
        except Exception as e:
            logger.warning("下载头像失败[%s]: %s" % (member_openid[:8], e))
        return b""

# ============ 整点报时 ============


    _CHIME_API_URL = "https://api.yuafeng.cn/API/ly/time.php"


    async def _chime(self, api, group_openid: str, msg_id: str):
        """整点报时：调用第三方 API 获取当前整点报时图并发送。

        仅限群主 / 群管理员 / 控制台管理员触发（由 handle_command 闸门把关）。

        获取 / 上传 / 发送任一步失败都会降级为文字提示。
        """
        try:
            result = await send_group_image(api, group_openid, self._CHIME_API_URL, msg_id=msg_id)
            if not result:
                await send_group_text(api, group_openid, "⏰ 整点报时获取失败，请稍后再试", msg_id=msg_id)
        except Exception as e:
            logger.error("整点报时失败: %s" % e)
            await send_group_text(api, group_openid, "⏰ 整点报时获取失败：%s" % e, msg_id=msg_id)


    # ============ 指令分发 ============



    async def handle_command(self, api, content: str, group_openid: str,
                             member_openid: str, msg_id: str,
                             member_role: str = "", is_console_admin: bool = False) -> bool:
        """
        分发群管指令，返回 True 表示已处理。

        权限模型（分两类）：

            A. 整点报时   —— 仅限群主 / 群管理员 / 控制台管理员

            B. 违禁词     —— 设置 / 添加 / 删除 仅限群主 / 群管理员 / 控制台管理员（列表由控制台管理）

        member_role 取自 QQ 事件 author.member_role 字段（owner / admin / member）。

        支持指令：

            整点报时                （需权限：群主/管理员/控制台管理员，打开报时菜单）

            报时开关                （需权限：切换本群自动报时）

            报时设置                （需权限：打开间隔/时段设置子菜单）

            报时间隔设置 / 间隔 N   （需权限：设置每 N 小时在整点报时一次）

            报时时段设置 / 时段 X-Y （需权限：设置每日可报时时段 0-23）

            立即报时                （需权限：手动发送当前整点报时图）

            违禁词设置              （需权限：打开设置子菜单）

            违禁词添加 词           （需权限）

            违禁词删除 词           （需权限）

            禁言管理                （需权限：打开禁言父菜单）

            禁言设置                （需权限：打开禁言设置子菜单）

            禁言时长设置            （需权限：提示输入『禁言时长 N』）

            禁言时长 N              （需权限：设置本群禁言时长（秒），每群独立）

            禁言自动处理            （需权限：切换本群违禁词自动禁言开关）

            禁言自动开 / 禁言自动关 （需权限：显式开/关）

            禁言 <openid|@qq> [秒]  （需权限：手动禁言指定成员；秒数省略用本群时长）

            解除禁言 <openid|@qq>   （需权限：解除指定成员禁言）
        """

        content = clean_content(content).strip()

        # ---- 先识别是否为群管指令 ----
        # 不是群管指令就直接 return False，让消息继续往下分发（AI 兜底、其他模块）。
        # 这样避免非指令文本（如"生物钟"）误触发权限闸门并吞掉消息。
        is_chime_cmd = (content == "整点报时")
        is_chime_toggle_cmd = (content == "报时开关")
        is_chime_settings_cmd = (content == "报时设置")
        is_chime_interval_cmd = (content == "报时间隔设置")
        is_chime_period_cmd = (content == "报时时段设置")
        is_chime_now_cmd = (content == "立即报时")
        is_chime_interval_set = content.startswith("间隔")
        is_chime_period_set = content.startswith("时段")

        is_welcome_cmd = (content == "入群通知")
        is_welcome_welcome_cmd = (content == "入群欢迎词设置")
        is_welcome_toggle_cmd = (content == "入群通知开关")
        is_welcome_set_welcome = content.startswith("欢迎词 ")

        is_banword_cmd = (
            content == "违禁词设置"
            or content.startswith("违禁词添加 ")
            or content.startswith("违禁词删除 ")
        )
        is_banword_parent_cmd = (content == "违禁词")

        # ---- 禁言指令识别 ----
        is_mute_parent_cmd = (content == "禁言管理")
        is_mute_settings_cmd = (content == "禁言设置" or content == "禁言时长设置" or content == "禁言自动处理")
        is_mute_duration_set = content.startswith("禁言时长 ")
        is_mute_auto_on = (content == "禁言自动开")
        is_mute_auto_off = (content == "禁言自动关")
        is_mute_member_cmd = content.startswith("禁言 ")
        is_unmute_member_cmd = content.startswith("解除禁言 ")

        if not (is_chime_cmd or is_chime_toggle_cmd or is_chime_settings_cmd
                or is_chime_interval_cmd or is_chime_period_cmd or is_chime_now_cmd
                or is_chime_interval_set or is_chime_period_set
                or is_welcome_cmd or is_welcome_welcome_cmd
                or is_welcome_toggle_cmd or is_welcome_set_welcome
                or is_banword_cmd or is_banword_parent_cmd
                or is_mute_parent_cmd or is_mute_settings_cmd
                or is_mute_duration_set or is_mute_auto_on or is_mute_auto_off
                or is_mute_member_cmd or is_unmute_member_cmd):
            return False

        # ---- 整点报时（自动）主菜单：管理员入口 ----
        if is_chime_cmd:
            if not self._has_privilege(member_role, is_console_admin):
                await send_group_text(
                    api, group_openid,
                    "⚠️ 整点报时仅限群主、群管理员或控制台管理员使用，您当前无权限。",
                    msg_id=msg_id,
                )
                return True
            await self._send_chime_menu(api, group_openid, msg_id)
            return True

        # ---- 报时开关：切换本群自动报时（需管理员） ----
        if is_chime_toggle_cmd:
            if not self._has_privilege(member_role, is_console_admin):
                await send_group_text(
                    api, group_openid,
                    "⚠️ 报时开关仅限群主、群管理员或控制台管理员使用，您当前无权限。",
                    msg_id=msg_id,
                )
                return True
            try:
                from console_server import set_chime_group_enabled, get_chime_group_config, _coerce_int
                cfg = get_chime_group_config(group_openid)
                new_cfg = set_chime_group_enabled(group_openid, not cfg.get("enabled"))
                state = "✅ 已开启" if new_cfg.get("enabled") else "⏹ 已关闭"
                iv = _coerce_int(new_cfg.get("interval_hours", 1), 1)
                ps = _coerce_int(new_cfg.get("period_start", 0), 0)
                pe = _coerce_int(new_cfg.get("period_end", 23), 23)
                tip = ""
                if new_cfg.get("enabled"):
                    tip = ("\n⚠️ 自动报时会由机器人在整点向本群主动推送报时图，需要机器人「主动发言权限」"
                           "（每日 %02d:00–%02d:00，每 %d 小时一次）。" % (ps, pe, iv))
                await send_group_text(
                    api, group_openid,
                    "⏰ 本群整点报时（自动）%s（每 %d 小时，时段 %02d:00–%02d:00）。%s" % (state, iv, ps, pe, tip),
                    msg_id=msg_id,
                )
            except Exception as e:
                logger.error("报时开关切换失败: %s" % e)
                await send_group_text(
                    api, group_openid,
                    "⏰ 报时开关切换失败：%s" % e,
                    msg_id=msg_id,
                )
            return True

        # ---- 报时设置：打开子菜单（需管理员） ----
        if is_chime_settings_cmd:
            if not self._has_privilege(member_role, is_console_admin):
                await send_group_text(
                    api, group_openid,
                    "⚠️ 报时设置仅限群主、群管理员或控制台管理员使用，您当前无权限。",
                    msg_id=msg_id,
                )
                return True
            await self._send_chime_settings_menu(api, group_openid, msg_id)
            return True

        # ---- 报时间隔设置：提示回复格式（需管理员） ----
        if is_chime_interval_cmd:
            if not self._has_privilege(member_role, is_console_admin):
                await send_group_text(
                    api, group_openid,
                    "⚠️ 报时间隔设置仅限群主、群管理员或控制台管理员使用，您当前无权限。",
                    msg_id=msg_id,
                )
                return True
            try:
                from console_server import get_chime_group_config, _coerce_int
                cfg = get_chime_group_config(group_openid)
                iv = _coerce_int(cfg.get("interval_hours", 1), 1)
                await send_group_text(
                    api, group_openid,
                    "⏰ 本群当前报时间隔：每 %d 小时在整点报时一次。\n请直接回复『间隔 N』设置（N 为 1-24 的整数，例如：间隔 2）。" % iv,
                    msg_id=msg_id,
                )
            except Exception as e:
                logger.error("报时间隔设置提示失败: %s" % e)
                await send_group_text(api, group_openid, "⏰ 操作失败：%s" % e, msg_id=msg_id)
            return True

        # ---- 报时时段设置：提示回复格式（需管理员） ----
        if is_chime_period_cmd:
            if not self._has_privilege(member_role, is_console_admin):
                await send_group_text(
                    api, group_openid,
                    "⚠️ 报时时段设置仅限群主、群管理员或控制台管理员使用，您当前无权限。",
                    msg_id=msg_id,
                )
                return True
            try:
                from console_server import get_chime_group_config, _coerce_int
                cfg = get_chime_group_config(group_openid)
                ps = _coerce_int(cfg.get("period_start", 0), 0)
                pe = _coerce_int(cfg.get("period_end", 23), 23)
                await send_group_text(
                    api, group_openid,
                    "⏰ 本群当前可报时时段：%02d:00–%02d:00。\n请直接回复『时段 起-止』设置（0-23 小时，24 小时制，例如：时段 9-21）。" % (ps, pe),
                    msg_id=msg_id,
                )
            except Exception as e:
                logger.error("报时时段设置提示失败: %s" % e)
                await send_group_text(api, group_openid, "⏰ 操作失败：%s" % e, msg_id=msg_id)
            return True

        # ---- 间隔 N：设置本群报时间隔（需管理员） ----
        if is_chime_interval_set:
            if not self._has_privilege(member_role, is_console_admin):
                await send_group_text(
                    api, group_openid,
                    "⚠️ 报时间隔设置仅限群主、群管理员或控制台管理员使用，您当前无权限。",
                    msg_id=msg_id,
                )
                return True
            try:
                from console_server import set_chime_group_interval, _coerce_int
                num = content[len("间隔"):].strip()
                iv = _coerce_int(num, 0)
                if iv < 1 or iv > 24:
                    await send_group_text(api, group_openid, "⏰ 间隔需为 1-24 的整数（小时）。请回复例如：间隔 2", msg_id=msg_id)
                    return True
                cfg = set_chime_group_interval(group_openid, iv)
                await send_group_text(api, group_openid, "⏰ 已设置本群报时间隔：每 %d 小时在整点报时一次。" % _coerce_int(cfg.get("interval_hours", iv), iv), msg_id=msg_id)
            except Exception as e:
                logger.error("设置报时间隔失败: %s" % e)
                await send_group_text(api, group_openid, "⏰ 设置失败：%s" % e, msg_id=msg_id)
            return True

        # ---- 时段 起-止：设置本群报时时段（需管理员） ----
        if is_chime_period_set:
            if not self._has_privilege(member_role, is_console_admin):
                await send_group_text(
                    api, group_openid,
                    "⚠️ 报时时段设置仅限群主、群管理员或控制台管理员使用，您当前无权限。",
                    msg_id=msg_id,
                )
                return True
            try:
                import re as _re
                from console_server import set_chime_group_period, _coerce_int
                seg = content[len("时段"):].strip()
                m = _re.search(r"(\d{1,2})\s*[-~到至]\s*(\d{1,2})", seg)
                if not m:
                    m = _re.match(r"(\d{1,2})\s+(\d{1,2})", seg)
                if not m:
                    await send_group_text(api, group_openid, "⏰ 格式有误。请回复例如：时段 9-21（0-23 小时）", msg_id=msg_id)
                    return True
                s = _coerce_int(m.group(1), -1)
                e = _coerce_int(m.group(2), -1)
                if s < 0 or s > 23 or e < 0 or e > 23:
                    await send_group_text(api, group_openid, "⏰ 小时需在 0-23 之间。请回复例如：时段 9-21", msg_id=msg_id)
                    return True
                cfg = set_chime_group_period(group_openid, s, e)
                await send_group_text(api, group_openid, "⏰ 已设置本群可报时时段：%02d:00–%02d:00。" % (_coerce_int(cfg.get("period_start"), s), _coerce_int(cfg.get("period_end"), e)), msg_id=msg_id)
            except Exception as e:
                logger.error("设置报时时段失败: %s" % e)
                await send_group_text(api, group_openid, "⏰ 设置失败：%s" % e, msg_id=msg_id)
            return True

        # ---- 立即报时：手动发送当前整点报时图（需管理员） ----
        if is_chime_now_cmd:
            if not self._has_privilege(member_role, is_console_admin):
                await send_group_text(
                    api, group_openid,
                    "⚠️ 立即报时仅限群主、群管理员或控制台管理员使用，您当前无权限。",
                    msg_id=msg_id,
                )
                return True
            await self._chime(api, group_openid, msg_id)
            return True

        # ---- 入群通知：主菜单（需管理员） ----
        if is_welcome_cmd:
            if not self._has_privilege(member_role, is_console_admin):
                await send_group_text(
                    api, group_openid,
                    "⚠️ 入群通知仅限群主、群管理员或控制台管理员使用，您当前无权限。",
                    msg_id=msg_id,
                )
                return True
            await self._send_welcome_menu(api, group_openid, msg_id)
            return True

        # ---- 入群通知开关：切换本群入群通知（需管理员） ----
        if is_welcome_toggle_cmd:
            if not self._has_privilege(member_role, is_console_admin):
                await send_group_text(
                    api, group_openid,
                    "⚠️ 入群通知开关仅限群主、群管理员或控制台管理员使用，您当前无权限。",
                    msg_id=msg_id,
                )
                return True
            try:
                from console_server import get_welcome_group_config, set_welcome_group_config
                cfg = get_welcome_group_config(group_openid)
                new_cfg = set_welcome_group_config(group_openid, welcome_enabled=not cfg.get("welcome_enabled"))
                state = "✅ 已开启" if new_cfg.get("welcome_enabled") else "⏹ 已关闭"
                await send_group_text(
                    api, group_openid,
                    "📥 本群入群通知%s。" % state,
                    msg_id=msg_id,
                )
            except Exception as e:
                logger.error("入群通知开关切换失败: %s" % e)
                await send_group_text(api, group_openid, "📥 入群通知开关切换失败：%s" % e, msg_id=msg_id)
            return True

        # ---- 入群欢迎词设置：提示回复格式（需管理员） ----
        if is_welcome_welcome_cmd:
            if not self._has_privilege(member_role, is_console_admin):
                await send_group_text(
                    api, group_openid,
                    "⚠️ 入群欢迎词设置仅限群主、群管理员或控制台管理员使用，您当前无权限。",
                    msg_id=msg_id,
                )
                return True
            try:
                from console_server import get_welcome_group_config
                cfg = get_welcome_group_config(group_openid)
                cur = (cfg.get("welcome_msg") or "").strip() or "（未设置，使用默认：%s）" % self._WELCOME_DEFAULT_TEXT.format(mention="@新成员")
                await send_group_text(
                    api, group_openid,
                    "📥 本群当前入群欢迎词：%s\n请直接回复『欢迎词 你的欢迎语』设置（例如：欢迎词 欢迎来到小流萤的群～）。回复『欢迎词 』（留空）可清空为默认。" % cur,
                    msg_id=msg_id,
                )
            except Exception as e:
                logger.error("入群欢迎词设置提示失败: %s" % e)
                await send_group_text(api, group_openid, "📥 操作失败：%s" % e, msg_id=msg_id)
            return True

        # ---- 欢迎词 X：设置本群入群欢迎词（需管理员） ----
        if is_welcome_set_welcome:
            if not self._has_privilege(member_role, is_console_admin):
                await send_group_text(
                    api, group_openid,
                    "⚠️ 设置入群欢迎词仅限群主、群管理员或控制台管理员使用，您当前无权限。",
                    msg_id=msg_id,
                )
                return True
            try:
                from console_server import set_welcome_group_config
                word = content[len("欢迎词 "):].strip()
                set_welcome_group_config(group_openid, welcome_msg=word)
                if word:
                    await send_group_text(api, group_openid, "📥 已设置本群入群欢迎词：%s" % word, msg_id=msg_id)
                else:
                    await send_group_text(api, group_openid, "📥 已清空入群欢迎词，将使用默认文案。", msg_id=msg_id)
            except Exception as e:
                logger.error("设置入群欢迎词失败: %s" % e)
                await send_group_text(api, group_openid, "📥 设置失败：%s" % e, msg_id=msg_id)
            return True

        # ---- 违禁词：父菜单（展开列表 / 设置，每群独立） ----
        if is_banword_parent_cmd:
            await self._send_banned_word_parent(api, group_openid, msg_id)
            return True

        # ---- 违禁词：设置 / 添加 / 删除仅管理员（列表改由控制台管理，不在群内展示）----
        if content == "违禁词设置":
            if not self._has_privilege(member_role, is_console_admin):
                await send_group_text(
                    api, group_openid,
                    "⚠️ 违禁词设置仅限群主、群管理员或控制台管理员使用，您当前无权限。",
                    msg_id=msg_id,
                )
                return True
            await self._send_banned_word_settings(api, group_openid, msg_id)
            return True

        if content.startswith("违禁词添加 "):
            if not self._has_privilege(member_role, is_console_admin):
                await send_group_text(
                    api, group_openid,
                    "⚠️ 添加违禁词仅限群主、群管理员或控制台管理员使用，您当前无权限。",
                    msg_id=msg_id,
                )
                return True
            await self._add_banned_word(api, content[len("违禁词添加 "):], group_openid, msg_id)
            return True

        if content.startswith("违禁词删除 "):
            if not self._has_privilege(member_role, is_console_admin):
                await send_group_text(
                    api, group_openid,
                    "⚠️ 删除违禁词仅限群主、群管理员或控制台管理员使用，您当前无权限。",
                    msg_id=msg_id,
                )
                return True
            await self._remove_banned_word(api, content[len("违禁词删除 "):], group_openid, msg_id)
            return True

        # ---- 禁言管理：父菜单（需管理员） ----
        if is_mute_parent_cmd:
            if not self._has_privilege(member_role, is_console_admin):
                await send_group_text(
                    api, group_openid,
                    "⚠️ 禁言管理仅限群主、群管理员或控制台管理员使用，您当前无权限。",
                    msg_id=msg_id,
                )
                return True
            await self._send_mute_parent(api, group_openid, msg_id)
            return True

        # ---- 禁言设置 / 禁言时长设置 / 禁言自动处理：统一跳到子菜单（需管理员） ----
        if is_mute_settings_cmd:
            if not self._has_privilege(member_role, is_console_admin):
                await send_group_text(
                    api, group_openid,
                    "⚠️ 禁言设置仅限群主、群管理员或控制台管理员使用，您当前无权限。",
                    msg_id=msg_id,
                )
                return True
            if content == "禁言自动处理":
                # 直接切换开关
                cur = self.get_mute_on_banword(group_openid)
                new_v = self.set_mute_on_banword(group_openid, not cur)
                state = "✅ 已开启" if new_v else "⏹ 已关闭"
                await send_group_text(
                    api, group_openid,
                    "🎚 本群违禁词自动禁言：%s（每群独立设置）。" % state,
                    msg_id=msg_id,
                )
                return True
            if content == "禁言时长设置":
                dur = self.get_mute_duration(group_openid)
                await send_group_text(
                    api, group_openid,
                    "⏱ 本群当前禁言时长：%d 秒。\n请直接回复『禁言时长 N』设置（N 为正整数秒，例如：禁言时长 600 = 10 分钟）。" % dur,
                    msg_id=msg_id,
                )
                return True
            # content == "禁言设置" → 子菜单
            await self._send_mute_settings(api, group_openid, msg_id)
            return True

        # ---- 禁言时长 N：设置本群禁言时长（需管理员） ----
        if is_mute_duration_set:
            if not self._has_privilege(member_role, is_console_admin):
                await send_group_text(
                    api, group_openid,
                    "⚠️ 设置禁言时长仅限群主、群管理员或控制台管理员使用，您当前无权限。",
                    msg_id=msg_id,
                )
                return True
            try:
                num = content[len("禁言时长 "):].strip()
                dur = int(num)
                if dur < 1:
                    await send_group_text(
                        api, group_openid,
                        "⏱ 禁言时长需为正整数秒。请回复例如：禁言时长 600（10 分钟）",
                        msg_id=msg_id,
                    )
                    return True
                new_dur = self.set_mute_duration(group_openid, dur)
                await send_group_text(
                    api, group_openid,
                    "⏱ 已设置本群禁言时长：%d 秒（每群独立，违禁词触发后按此时长自动禁言触发用户）。" % new_dur,
                    msg_id=msg_id,
                )
            except Exception as e:
                logger.error("设置禁言时长失败: %s" % e)
                await send_group_text(api, group_openid, "⏱ 设置失败：%s" % e, msg_id=msg_id)
            return True

        # ---- 禁言自动开 / 禁言自动关（需管理员） ----
        if is_mute_auto_on or is_mute_auto_off:
            if not self._has_privilege(member_role, is_console_admin):
                await send_group_text(
                    api, group_openid,
                    "⚠️ 切换禁言自动处理仅限群主、群管理员或控制台管理员使用，您当前无权限。",
                    msg_id=msg_id,
                )
                return True
            new_v = self.set_mute_on_banword(group_openid, is_mute_auto_on)
            state = "✅ 已开启" if new_v else "⏹ 已关闭"
            await send_group_text(
                api, group_openid,
                "🎚 本群违禁词自动禁言：%s（每群独立设置）。" % state,
                msg_id=msg_id,
            )
            return True

        # ---- 禁言 <openid|@qq> [秒]（需管理员） ----
        if is_mute_member_cmd:
            if not self._has_privilege(member_role, is_console_admin):
                await send_group_text(
                    api, group_openid,
                    "⚠️ 禁言指定用户仅限群主、群管理员或控制台管理员使用，您当前无权限。",
                    msg_id=msg_id,
                )
                return True
            import re as _re
            seg = content[len("禁言 "):].strip()
            m = _re.match(r"(.+?)(?:\s+(\d+))?$", seg)
            target = (m.group(1).strip() if m else seg)
            try:
                dur = int(m.group(2)) if (m and m.group(2)) else None
            except Exception:
                dur = None
            if not target:
                await send_group_text(
                    api, group_openid,
                    "🔇 格式：禁言 <openid|@qq> [秒数]\n秒数省略时使用本群禁言时长。",
                    msg_id=msg_id,
                )
                return True
            ok, msg = self.mute_member(group_openid, target, duration=dur)
            if ok:
                actual = self.get_mute_duration(group_openid) if dur is None else dur
                await send_group_text(
                    api, group_openid,
                    "🔇 已对成员 %s 执行禁言 %d 秒（每群独立时长）。" % (target, actual),
                    msg_id=msg_id,
                )
            else:
                await send_group_text(
                    api, group_openid,
                    "🔇 禁言失败：%s\n提示：机器人必须是群管理员；只能禁言普通成员。" % msg,
                    msg_id=msg_id,
                )
            return True

        # ---- 解除禁言 <openid|@qq>（需管理员） ----
        if is_unmute_member_cmd:
            if not self._has_privilege(member_role, is_console_admin):
                await send_group_text(
                    api, group_openid,
                    "⚠️ 解除禁言仅限群主、群管理员或控制台管理员使用，您当前无权限。",
                    msg_id=msg_id,
                )
                return True
            target = content[len("解除禁言 "):].strip()
            if not target:
                await send_group_text(
                    api, group_openid,
                    "🔇 格式：解除禁言 <openid|@qq>",
                    msg_id=msg_id,
                )
                return True
            ok, msg = self.unmute_member(group_openid, target)
            if ok:
                await send_group_text(
                    api, group_openid,
                    "🔇 已解除成员 %s 的禁言。" % target,
                    msg_id=msg_id,
                )
            else:
                await send_group_text(
                    api, group_openid,
                    "🔇 解除禁言失败：%s" % msg,
                    msg_id=msg_id,
                )
            return True

        return False

    @staticmethod
    def _has_privilege(member_role: str, is_console_admin: bool) -> bool:
        """群主 / 群管理员 / 控制台管理员 任一满足即有权限。"""
        return GroupAdminManager._is_admin(member_role) or bool(is_console_admin)

