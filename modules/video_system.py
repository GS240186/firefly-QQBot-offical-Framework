# -*- coding: utf-8 -*-
"""
视频系统模块
通过B站搜索获取视频，支持6类视频：帅哥视频、风景视频、变装视频、cos视频、漫剪视频、游戏视频

取流策略：
1. B站搜索：按分类关键词搜索B站视频，按后台配置的时长上限筛选短视频
2. B站排行榜：搜索失败时按分区排行榜获取
3. 本地兜底：API均失败时回退到 data/video_links.json

B站视频下载需要 Referer 头，否则会被拒绝（403）。
"""

import random

from modules.common import (
    ChatScene,
    send_text,
    send_text_with_keyboard,
    send_video_for_scene,
    send_video_bytes_for_scene,
    load_json,
    build_keyboard_multi,
    clean_content,
    logger,
    http_get,
    _download_media_bytes_with_headers,
)

# 视频分类（顺序即按钮展示顺序）
VIDEO_CATEGORIES = ["帅哥视频", "风景视频", "变装视频", "cos视频", "漫剪视频", "游戏视频"]

# 本地精选视频链接文件
VIDEO_LINKS_FILE = "video_links.json"

# ============================================================
# B站 API 配置
# ============================================================

_BILI_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 搜索用的请求头（带Cookie绕过基础反爬）
_BILI_SEARCH_HEADERS = {
    "User-Agent": _BILI_UA,
    "Referer": "https://search.bilibili.com",
    "Cookie": "buvid3=0C5E5D37-1B2A-4F3B-8D6E-9F0A1B2C3D4E5F60-infoc",
}

# 通用API请求头（获取cid、playurl等）
_BILI_API_HEADERS = {
    "User-Agent": _BILI_UA,
    "Referer": "https://www.bilibili.com",
}

# 下载视频用的请求头（必须有Referer）
_BILI_DOWNLOAD_HEADERS = {
    "User-Agent": _BILI_UA,
    "Referer": "https://www.bilibili.com",
}

# 每个分类的B站搜索关键词（按优先级排列）
_BILI_KEYWORDS = {
    "帅哥视频": ["帅哥", "小哥哥日常", "男神"],
    "风景视频": ["风景航拍", "治愈风景", "自然风光"],
    "变装视频": ["变装", "变装视频", "卡点变装"],
    "cos视频": ["cosplay", "cos正片", "cos"],
    "漫剪视频": ["动漫混剪", "AMV", "MAD"],
    "游戏视频": ["游戏集锦", "游戏高光", "游戏精彩操作"],
}

# B站排行榜分区ID（搜索失败时的兜底）
_BILI_RID_MAP = {
    "帅哥视频": 5,      # 娱乐
    "风景视频": 160,    # 生活
    "变装视频": 155,    # 时尚
    "cos视频": 155,     # 时尚
    "漫剪视频": 1,      # 动画
    "游戏视频": 4,      # 游戏
}

# 视频最大时长（秒），超过则跳过（默认 20 分钟，运行时可被后台配置覆盖）
_MAX_DURATION = 1200  # 20分钟

# 视频大小限制（MB），0=不限制（运行时可被后台配置覆盖）
_MAX_VIDEO_MB = 0


def _get_system_limits():
    """读取视频系统（B站搜索/排行榜）运行时限制，缺省回退到模块默认。"""
    try:
        from console_server import get_video_limits
        return get_video_limits().get("system", {}) or {}
    except Exception:
        return {}


class VideoManager:
    """视频系统 - 通过B站搜索获取视频"""

    def __init__(self):
        self.categories = list(VIDEO_CATEGORIES)

    # ============================================================
    # B站搜索
    # ============================================================

    async def _bili_search(self, keyword: str) -> list:
        """
        搜索B站视频，返回 [{bvid, title, duration}, ...]
        只返回时长 <= 配置上限的短视频。
        """
        url = "https://api.bilibili.com/x/web-interface/search/type"
        params = {
            "search_type": "video",
            "keyword": keyword,
            "page": 1,
            "page_size": 20,
            "order": "totalrank",
        }
        data = await http_get(url, params=params, headers=_BILI_SEARCH_HEADERS, timeout=10)
        if not data or data.get("code") != 0:
            code = data.get("code") if data else "None"
            msg = data.get("message", "") if data else ""
            logger.warning("B站搜索失败: keyword=%s, code=%s, msg=%s" % (keyword, code, msg))
            return []

        results = data.get("data", {}).get("result", [])
        videos = []
        _max_dur = _get_system_limits().get("max_duration", _MAX_DURATION)
        for item in results:
            bvid = item.get("bvid")
            if not bvid:
                continue
            # 解析时长 "3:25" → 秒
            duration = self._parse_duration(item.get("duration", "0:00"))
            if _max_dur > 0 and duration > _max_dur:
                continue
            # 清理标题中的 <em> 高亮标签
            title = item.get("title", "")
            title = title.replace('<em class="keyword">', "").replace("</em>", "")
            videos.append({"bvid": bvid, "title": title, "duration": duration})
        return videos

    async def _bili_get_cid(self, bvid: str) -> int:
        """通过 bvid 获取视频的 cid"""
        url = "https://api.bilibili.com/x/web-interface/view"
        params = {"bvid": bvid}
        data = await http_get(url, params=params, headers=_BILI_API_HEADERS, timeout=10)
        if data and data.get("code") == 0:
            return data.get("data", {}).get("cid", 0)
        return 0

    async def _bili_get_play_url(self, bvid: str, cid: int, qn: int = 32) -> str:
        """
        获取B站视频播放地址（durl格式）。
        qn: 16=360P, 32=480P, 64=720P(需登录)
        返回视频直链URL（下载时需要Referer头）。
        """
        url = "https://api.bilibili.com/x/player/playurl"
        params = {
            "bvid": bvid,
            "cid": cid,
            "qn": qn,
            "fnval": 1,   # 返回 durl 格式
            "fnver": 0,
            "fourk": 0,
        }
        data = await http_get(url, params=params, headers=_BILI_API_HEADERS, timeout=10)
        if data and data.get("code") == 0:
            durl = data.get("data", {}).get("durl", [])
            if durl:
                return durl[0].get("url", "")
        return ""

    async def _bili_ranking(self, rid: int) -> list:
        """
        获取B站分区排行榜视频，返回 [{bvid, title, duration}, ...]
        """
        url = "https://api.bilibili.com/x/web-interface/ranking/v2"
        params = {"rid": rid, "type": "all"}
        data = await http_get(url, params=params, headers=_BILI_API_HEADERS, timeout=10)
        if data and data.get("code") == 0:
            items = data.get("data", {}).get("list", [])
            videos = []
            _max_dur = _get_system_limits().get("max_duration", _MAX_DURATION)
            for item in items:
                bvid = item.get("bvid")
                duration = item.get("duration", 0)
                if bvid and isinstance(duration, int) and (_max_dur <= 0 or duration <= _max_dur):
                    videos.append({
                        "bvid": bvid,
                        "title": item.get("title", ""),
                        "duration": duration,
                    })
            return videos
        return []

    # ============================================================
    # 核心：从B站获取视频
    # ============================================================

    async def _fetch_from_bilibili(self, category: str) -> tuple:
        """
        从B站获取视频。
        返回 (video_bytes, title) 或 (None, None)

        策略：
        1. 按分类关键词搜索B站
        2. 搜索失败则按分区排行榜获取
        3. 随机选择短视频，获取播放地址
        4. 下载视频bytes（带Referer头），先480P后360P
        """
        videos = []

        # ---- 1. 搜索关键词 ----
        keywords = _BILI_KEYWORDS.get(category, [])
        for kw in keywords:
            results = await self._bili_search(kw)
            if results:
                videos = results
                logger.info("B站搜索[%s]关键词'%s'获取%d个视频" % (category, kw, len(videos)))
                break

        # ---- 2. 搜索失败，尝试排行榜 ----
        if not videos:
            rid = _BILI_RID_MAP.get(category)
            if rid:
                videos = await self._bili_ranking(rid)
                if videos:
                    logger.info("B站排行榜[rid=%s]获取[%s]%d个视频" % (rid, category, len(videos)))

        if not videos:
            logger.warning("B站无搜索结果和排行榜数据: %s" % category)
            return None, None

        # ---- 3. 随机打乱，尝试下载 ----
        random.shuffle(videos)
        for video in videos[:8]:  # 最多尝试8个
            bvid = video["bvid"]
            title = video["title"]

            # 获取 cid
            cid = await self._bili_get_cid(bvid)
            if not cid:
                continue

            # 先 480P 后 360P
            _max_mb = _get_system_limits().get("max_mb", _MAX_VIDEO_MB)
            for qn in [32, 16]:
                play_url = await self._bili_get_play_url(bvid, cid, qn=qn)
                if not play_url:
                    continue

                # 下载视频（需要 Referer 头）
                video_bytes = await _download_media_bytes_with_headers(
                    play_url, headers=_BILI_DOWNLOAD_HEADERS,
                    timeout=60, max_size_mb=_max_mb,
                )
                if video_bytes:
                    size_mb = len(video_bytes) / 1024 / 1024
                    logger.info("B站视频下载成功: bvid=%s qn=%d size=%.1fMB" % (bvid, qn, size_mb))
                    return video_bytes, title

        logger.warning("B站视频下载全部失败: %s" % category)
        return None, None

    # ============================================================
    # 本地兜底
    # ============================================================

    async def _fetch_from_local(self, category: str) -> str:
        """从本地精选列表获取视频URL"""
        data = load_json(VIDEO_LINKS_FILE)
        links = data.get(category) or []
        if links:
            return random.choice(links)
        return ""

    # ============================================================
    # 工具方法
    # ============================================================

    @staticmethod
    def _parse_duration(duration_str: str) -> int:
        """将B站时长字符串 '3:25' 解析为秒数"""
        try:
            parts = duration_str.split(":")
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except (ValueError, IndexError):
            pass
        return 0

    # ============================================================
    # 按钮构建
    # ============================================================

    def build_category_buttons(self, exclude: str = None) -> dict:
        """构建其他视频分类的快捷按钮（排除当前分类，单行展示）"""
        buttons = []
        for cat in self.categories:
            if cat == exclude:
                continue
            buttons.append({
                "label": cat,
                "command": cat,
                "enter": True,
            })
        return build_keyboard_multi(buttons)

    # ============================================================
    # 发送视频
    # ============================================================

    async def send_video(self, api, category: str, group_openid: str, msg_id: str = None,
                         scene: str = ChatScene.GROUP):
        """发送指定分类的视频，并在下方附带其他分类按钮（群聊/私聊通用）"""
        if category not in self.categories:
            return False
        scene = scene or ChatScene.GROUP

        # 先发送"正在搜索"提示
        await send_text(
            api, scene, group_openid,
            "🎬 正在从B站搜索【%s】，请稍候..." % category,
            msg_id=msg_id,
        )

        keyboard = self.build_category_buttons(exclude=category)

        # ---- 1. B站搜索 ----
        video_bytes, title = await self._fetch_from_bilibili(category)
        if video_bytes:
            display_title = title[:30] if title else category
            send_result = await send_video_bytes_for_scene(
                api, scene, group_openid, video_bytes,
                content="🎥 %s" % display_title,
                msg_id=msg_id,
            )
            if send_result:
                await send_text_with_keyboard(
                    api, scene, group_openid, "还可以看看其他类型视频👇", keyboard, msg_id=msg_id
                )
                logger.info("B站视频发送成功[%s/%s]: %s" % (scene, category, display_title))
                return True
            else:
                logger.error("B站视频发送失败(上传QQ失败)[%s]: %s" % (scene, category))

        # ---- 2. 本地兜底 ----
        local_url = await self._fetch_from_local(category)
        if local_url:
            logger.info("使用本地兜底视频[%s]: %s" % (scene, category))
            send_result = await send_video_for_scene(api, scene, group_openid, local_url, msg_id=msg_id)
            if send_result:
                await send_text_with_keyboard(
                    api, scene, group_openid, "还可以看看其他类型视频👇", keyboard, msg_id=msg_id
                )
                return True

        # ---- 3. 全部失败 ----
        text = "暂无【%s】视频资源，请稍后再试～\n可以先看看其他类型视频👇" % category
        await send_text_with_keyboard(api, scene, group_openid, text, keyboard, msg_id=msg_id)
        logger.warning("无可用视频资源[%s]: %s" % (scene, category))
        return True

    # ============================================================
    # 命令入口
    # ============================================================

    async def handle_command(self, api, content, group_openid, member_openid, msg_id, scene=None):
        """
        处理视频相关命令。
        命令：帅哥视频 / 风景视频 / 变装视频 / cos视频 / 漫剪视频 / 游戏视频
        scene: "group" / "c2c" / "channel"（决定走群接口还是私聊接口）
        """
        content = clean_content(content).strip()
        if content in self.categories:
            await self.send_video(api, content, group_openid, msg_id,
                                  scene=scene or ChatScene.GROUP)
            return True
        return False
