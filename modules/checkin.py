# -*- coding: utf-8 -*-
"""
签到系统模块
提供每日签到、签到排行榜、签到查询功能。

数据存储（data/checkin_data.json）：
{
    "group_openid": {
        "member_openid": {
            "points": 100,            # 总积分
            "continuous": 5,          # 连续签到天数
            "last_date": "2026-07-30",# 最后签到日期 YYYY-MM-DD
            "total": 10               # 累计签到次数
        }
    }
}

积分规则：
    每次签到获得 = 基础积分(CHECKIN_BASE_POINTS) + 连续签到奖励
    连续签到奖励 = min(连续天数 * 5, CHECKIN_BONUS_CAP)
"""

from modules.common import (
    send_group_text,
    send_group_text_with_keyboard,
    send_text,
    send_text_with_keyboard,
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
    fetch_yiyan,
    format_yiyan_line,
)
from modules.config import CHECKIN_BASE_POINTS, CHECKIN_BONUS_CAP

# 导入开关判断，确保模块内部也能独立拒绝已关闭指令
from console_server import (
    is_feature_enabled, is_sub_feature_enabled, get_checkin_config,
    GROUP_BOT_MAP, USER_BOT_MAP, resolve_bot_key,
)

# 签到数据存储文件名（位于 data/ 目录下）
CHECKIN_FILE = "checkin_data.json"


def _resolve_checkin_appid(chat_id):
    """把群 / C2C 的 chat_id 解析为稳定 appid，用于物理隔离路由；无法解析回退 _shared。"""
    if not chat_id:
        return "_shared"
    _aid = GROUP_BOT_MAP.get(chat_id) or USER_BOT_MAP.get(chat_id)
    if _aid:
        return resolve_bot_key(_aid) or _aid
    return "_shared"


def _checkin_file_for(chat_id):
    """返回该 chat_id 对应的签到数据文件路径（data/bots/<appid>/checkin_data.json）。"""
    return "bots/%s/checkin_data.json" % _resolve_checkin_appid(chat_id)


class CheckInManager:
    """签到系统：每日签到 + 排行榜 + 查询"""

    def __init__(self):
        pass

    # ============ 数据读写 ============

    def _load_data(self, chat_id=None) -> dict:
        """加载签到数据（按 chat_id 路由到对应机器人的物理隔离文件）。"""
        return load_json(_checkin_file_for(chat_id))

    def _save_data(self, data: dict, chat_id=None):
        """保存签到数据（按 chat_id 路由到对应机器人的物理隔离文件）。"""
        save_json(_checkin_file_for(chat_id), data)

    def _get_user(self, data: dict, group_openid: str, member_openid: str) -> dict:
        """
        确保 data 中存在指定群、指定用户的记录（不存在则初始化），
        并兼容补全缺失字段，返回该用户数据的引用。
        """
        group = data.setdefault(group_openid, {})
        user = group.setdefault(member_openid, {
            "points": 0,
            "continuous": 0,
            "last_date": "",
            "total": 0,
            "nickname": "",
        })
        # 兼容旧数据，补全可能缺失的字段
        user.setdefault("points", 0)
        user.setdefault("continuous", 0)
        user.setdefault("last_date", "")
        user.setdefault("total", 0)
        user.setdefault("nickname", "")
        return user

    def _build_checkin_keyboard(self) -> dict:
        """构建「我也要签到」指令按钮（type=2, data=签到, enter=True，点击自动发送）"""
        return build_keyboard_command("我也要签到", "签到", enter=True)

    def _build_lottery_keyboard(self) -> dict:
        """构建「再抽一次」指令按钮（type=2, data=抽奖, enter=True，点击自动发送）"""
        return build_keyboard_command("再抽一次", "抽奖", enter=True)

    # ============ 签到 ============

    async def do_checkin(self, api, group_openid: str, member_openid: str, msg_id: str,
                         scene=None, target_id: str = None, member_nick: str = ""):
        """执行签到"""
        today = today_str()
        yesterday = yesterday_str()

        data = self._load_data(group_openid)
        user = self._get_user(data, group_openid, member_openid)

        # 今日已签到
        if user["last_date"] == today:
            await send_text(api, scene, target_id, "您今日已经签到过了", msg_id=msg_id)
            return

        # 计算连续签到天数：昨天签过则 +1，否则重置为 1
        if user["last_date"] == yesterday:
            user["continuous"] += 1
        else:
            user["continuous"] = 1

        # 本次获得积分 = 基础 + 连续奖励（连续奖励封顶，均可在后台配置）
        cfg = get_checkin_config()
        base = cfg.get("base_points", CHECKIN_BASE_POINTS)
        per = cfg.get("bonus_per_day", 5)
        cap = cfg.get("bonus_cap", CHECKIN_BONUS_CAP)
        bonus = min(user["continuous"] * per, cap)
        gained = base + bonus

        # 更新数据
        user["points"] += gained
        user["total"] += 1
        user["last_date"] = today
        # 记录/刷新用户真实昵称（优先群昵称），供排行榜展示
        if member_nick:
            user["nickname"] = member_nick
        self._save_data(data, group_openid)

        # 回复（带「我也要签到」按钮）
        reply = (
            "✅ 签到成功！\n"
            "🎲 本次获得：%d 积分\n"
            "🔥 连续签到：%d 天\n"
            "💰 总积分：%d\n"
            "📅 累计签到：%d 天"
        ) % (gained, user["continuous"], user["points"], user["total"])

        # 拉一条随机一言（带书名/作者，无出处则省略；失败时静默返回空行，不影响签到回复）
        yiyan_line = format_yiyan_line(await fetch_yiyan())
        if yiyan_line:
            reply += yiyan_line

        keyboard = self._build_checkin_keyboard()
        await send_text_with_keyboard(api, scene, target_id, reply, keyboard, msg_id=msg_id)

    # ============ 排行榜 ============

    async def show_ranking(self, api, group_openid: str, msg_id: str,
                           scene=None, target_id: str = None):
        """查看本群签到排行榜（积分前10）"""
        data = self._load_data(group_openid)
        group = data.get(group_openid, {})
        if not group:
            await send_text(api, scene, target_id, "本群暂无签到记录", msg_id=msg_id)
            return

        # 按积分降序，取前 10 名
        sorted_users = sorted(
            group.items(),
            key=lambda item: item[1].get("points", 0),
            reverse=True,
        )[:10]

        lines = ["🏆 签到排行榜"]
        for idx, (openid, info) in enumerate(sorted_users, 1):
            points = info.get("points", 0)
            continuous = info.get("continuous", 0)
            # 优先展示签到时记录的真实昵称，缺失时回退 openid 前 8 位
            display = info.get("nickname") or openid[:8]
            lines.append("%d. %s %d分（连续%d天）" % (idx, display, points, continuous))

        reply = "\n".join(lines)
        keyboard = self._build_checkin_keyboard()
        await send_text_with_keyboard(api, scene, target_id, reply, keyboard, msg_id=msg_id)

    # ============ 查询 ============

    async def show_status(self, api, group_openid: str, member_openid: str, msg_id: str,
                          scene=None, target_id: str = None):
        """查询自己的签到状态"""
        data = self._load_data(group_openid)
        group = data.get(group_openid, {})
        user = group.get(member_openid)

        if not user:
            await send_text(api, scene, target_id, "您还未签到过，发送「签到」开始签到吧～", msg_id=msg_id)
            return

        today = today_str()
        checked_today = (user.get("last_date", "") == today)
        nick = user.get("nickname") or "未记录"
        reply = (
            "📊 签到查询\n"
            "📛 昵称：%s\n"
            "💰 总积分：%d\n"
            "🔥 连续签到：%d 天\n"
            "📅 累计签到：%d 天\n"
            "🕒 最后签到：%s\n"
            "%s"
        ) % (
            nick,
            user.get("points", 0),
            user.get("continuous", 0),
            user.get("total", 0),
            user.get("last_date", "无"),
            "✅ 今日已签到" if checked_today else "❌ 今日未签到",
        )
        keyboard = self._build_checkin_keyboard()
        await send_text_with_keyboard(api, scene, target_id, reply, keyboard, msg_id=msg_id)

    # ============ 积分抽奖 ============

    async def do_lottery(self, api, group_openid: str, member_openid: str, msg_id: str,
                         scene=None, target_id: str = None, member_nick: str = ""):
        """消耗固定积分抽奖，按概率中奖返还随机积分。"""
        data = self._load_data(group_openid)
        user = self._get_user(data, group_openid, member_openid)
        if member_nick:
            user["nickname"] = member_nick

        cfg = get_checkin_config()
        cost = cfg.get("lottery_cost", 50)
        # 刷新昵称后先取最新积分判断
        cur = user.get("points", 0)
        if cur < cost:
            reply = (
                "🎰 积分抽奖\n"
                "💰 当前积分：%d\n"
                "❌ 积分不足，抽奖需 %d 积分\n"
                "快去「签到」攒积分吧～"
            ) % (cur, cost)
            await send_text(api, scene, target_id, reply, msg_id=msg_id)
            return

        # 扣费
        user["points"] -= cost

        # 抽奖逻辑：60% 中奖，中奖金额区间 [cost, cost*3] 随机
        import random
        won = random.random() < 0.6
        reward = 0
        if won:
            reward = random.randint(cost, cost * 3)

        # 写回：中奖则把奖励加回积分
        if won:
            user["points"] += reward
        self._save_data(data, group_openid)

        if won:
            reply = (
                "🎉 恭喜中奖！\n"
                "🎰 抽奖消耗：%d 积分\n"
                "💸 获得奖励：%d 积分\n"
                "💰 剩余积分：%d\n"
                "🍀 运气不错，再来一次？"
            ) % (cost, reward, user.get("points", 0))
        else:
            reply = (
                "🎰 抽奖结果\n"
                "💨 很遗憾未中奖\n"
                "💸 消耗：%d 积分\n"
                "💰 剩余积分：%d\n"
                "😤 再接再厉，下次一定中！"
            ) % (cost, user.get("points", 0))

        keyboard = self._build_lottery_keyboard()
        await send_text_with_keyboard(api, scene, target_id, reply, keyboard, msg_id=msg_id)

    # ============ 指令分发 ============

    async def handle_command(self, api, content: str, group_openid: str,
                             member_openid: str, msg_id: str, scene: str = None,
                             member_nick: str = "") -> bool:
        """
        分发签到指令，返回 True 表示已处理。
        scene: "group" / "c2c" / "channel"（仅作语义提示，实际通过 chat_id 前缀判断）

        支持指令：
            签到
            签到排名
            签到查询
        """
        # 总开关关闭时直接忽略，避免绕过外层门控被调用

        if not is_feature_enabled("checkin"):

            return False

        content = clean_content(content).strip()

        if content == "签到":

            if not is_sub_feature_enabled("checkin_sign"):

                return False

            await self.do_checkin(api, group_openid, member_openid, msg_id,
                                  scene=scene, target_id=group_openid,
                                  member_nick=member_nick)

            return True

        if content == "签到排名":

            if not is_sub_feature_enabled("checkin_rank"):

                return False

            await self.show_ranking(api, group_openid, msg_id,
                                    scene=scene, target_id=group_openid)

            return True

        if content == "签到查询":

            if not is_sub_feature_enabled("checkin_query"):

                return False

            await self.show_status(api, group_openid, member_openid, msg_id,
                                   scene=scene, target_id=group_openid)

            return True

        if content == "抽奖":

            if not is_sub_feature_enabled("checkin_lottery"):

                return False

            await self.do_lottery(api, group_openid, member_openid, msg_id,
                                  scene=scene, target_id=group_openid,
                                  member_nick=member_nick)

            return True

        return False
