# -*- coding: utf-8 -*-
"""
音乐系统模块
以QQ音乐搜索为主引擎，支持多音源切换。

功能：
1. 随机音乐（"随机音乐"）- 从QQ音乐热歌榜随机抽取一首
2. 点歌 / 选歌
   - "点歌 歌名"        -> 列出多个版本，回复"选歌 序号"选择
   - "点歌 歌名 歌手"    -> 直接发送匹配的歌曲
3. 音源选择（"音源选择"）- QQ音乐/网易云/酷狗/酷我 四大音源

说明：QQ群机器人发送音乐以「封面图 + 歌曲信息 + 播放链接」形式呈现。
QQ音乐API无需登录即可搜索、获取封面和免费试听播放地址。
"""

import json
import random

from modules.common import (
    ChatScene,
    send_text,
    send_text_with_keyboard,
    send_image_for_scene,
    send_audio_whole_for_scene,
    load_json,
    save_json,
    build_keyboard_multi,
    build_keyboard_command,
    clean_content,
    logger,
    http_get,
    format_duration,
)

# ============================================================
# QQ音乐 API 配置
# ============================================================

_QQ_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 搜索请求头
_QQ_SEARCH_HEADERS = {
    "User-Agent": _QQ_UA,
    "Referer": "https://y.qq.com",
}

# 获取播放地址请求头
_QQ_PLAY_HEADERS = {
    "User-Agent": _QQ_UA,
    "Referer": "https://y.qq.com",
}

# 网易云API（优先使用 config.py 中的配置，便于替换为自建服务）
try:
    from modules.config import NETEASE_API_BASE as _NETEASE_API_BASE  # noqa
except Exception:
    _NETEASE_API_BASE = "https://autumnfish.cn"

# 酷狗音乐配置（优先使用 config.py 中的配置，缺省时给出内置兜底值）
try:
    from modules.config import (
        KUGOU_API_BASE, KUGOU_APPID, KUGOU_PLATID, KUGOU_MID,
        KUGOU_DFID, KUGOU_SIGN_PREFIX, KUGOU_SECRET, KUGOU_PLAY_API,
    )
except Exception:
    KUGOU_API_BASE = "https://www.kugou.com"
    KUGOU_APPID = "1014"
    KUGOU_PLATID = "4"
    KUGOU_MID = "8888"
    KUGOU_DFID = ""
    KUGOU_SIGN_PREFIX = "OIllegeO"
    KUGOU_SECRET = "BAIDU_SECRET_KEY"
    KUGOU_PLAY_API = ""

# 酷我音乐配置（OIAPI 免鉴权，替换原 search.kuwo.cn 不稳的 r.s 接口）
# 说明：OIAPI /api/Kuwo 支持两种模式
#  - 列表模式: ?msg=xxx        → data 是 10 条结果 list（每项含 song/singer/rid/picture/time/album/types）
#  - 单首模式: ?msg=xxx&n=N&page=1 → data 是单 dict（含 url 播放直链）
# 选第 N 个歌曲时，必须用单首模式再调一次拿 url
OIAPI_KUWO_URL = "https://oiapi.net/api/Kuwo"
OIAPI_KUWO_TIMEOUT = 12
OIAPI_KUWO_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
# 酷我音频直链的 Referer（部分 oss 资源防盗链）
OIAPI_KUWO_PLAY_REFERER = "https://kuwo.cn/"

import hashlib

# 通用UA
_UA_HEADERS = {"User-Agent": _QQ_UA}


class MusicManager:
    """音乐系统 - 以QQ音乐为主引擎"""

    # 支持的音源
    SOURCES = ["QQ音乐", "网易云音乐", "酷狗音乐", "酷我音乐"]
    DEFAULT_SOURCE = "酷我音乐"
    MUSIC_SOURCE_FILE = "music_source.json"

    def __init__(self):
        self._search_cache = {}

    # ================================================================
    # 音源管理（按群持久化）
    # ================================================================

    def get_source(self, group_openid: str) -> str:
        data = load_json(self.MUSIC_SOURCE_FILE)
        return data.get(group_openid, self.DEFAULT_SOURCE)

    def set_source(self, group_openid: str, source: str):
        data = load_json(self.MUSIC_SOURCE_FILE)
        data[group_openid] = source
        save_json(self.MUSIC_SOURCE_FILE, data)

    # ================================================================
    # QQ音乐搜索（主引擎）
    # ================================================================

    async def search_qq(self, keyword: str, limit: int = 10) -> list:
        """
        QQ音乐搜索（c.y.qq.com 接口，无需登录）。
        返回歌曲列表，字段：name / artist / song_id / songmid / duration / cover / source
        """
        url = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"
        params = {
            "p": 1,
            "n": limit,
            "w": keyword,
            "format": "json",
        }
        data = await http_get(url, params=params, headers=_QQ_SEARCH_HEADERS, timeout=10)
        result = []
        try:
            lst = data["data"]["song"]["list"]
        except (KeyError, TypeError):
            lst = []

        for s in lst:
            songname = s.get("songname", "") or s.get("name", "") or s.get("title", "")
            if not songname:
                continue
            singers = "/".join(si.get("name", "") for si in s.get("singer", []))
            songmid = s.get("songmid", "")
            albummid = s.get("albummid", "")
            interval = s.get("interval", 0)

            # 付费状态: payplay=0 表示免费可播放, payplay=1 表示VIP
            pay = s.get("pay", {})
            is_free = pay.get("payplay", 1) == 0

            # 封面URL
            cover = ""
            if albummid:
                cover = "https://y.gtimg.cn/music/photo_new/T002R300x300M000%s.jpg" % albummid

            result.append({
                "name": songname,
                "artist": singers,
                "song_id": str(s.get("songid", "")),
                "songmid": songmid,
                "duration": int(interval) if interval else 0,
                "cover": cover,
                "source": "QQ音乐",
                "is_free": is_free,
            })
        return result

    async def get_qq_play_url(self, songmid: str) -> str:
        """
        获取QQ音乐免费试听播放地址（128k m4a）。
        通过 u.y.qq.com/cgi-bin/musicu.fcg 的 vkey.GetVkeyServer 模块获取。
        无需登录，返回完整播放URL，失败返回空字符串。
        """
        if not songmid:
            return ""

        # 构建请求体（JSON-RPC 风格）
        req_body = {
            "req_0": {
                "module": "vkey.GetVkeyServer",
                "method": "CgiGetVkey",
                "param": {
                    "guid": "358840384",
                    "songmid": [songmid],
                    "songtype": [0],
                    "uin": "0",
                    "loginflag": 1,
                    "platform": "20",
                },
            },
            "comm": {
                "uin": "0",
                "format": "json",
                "ct": 24,
                "cv": 0,
            },
        }

        url = "https://u.y.qq.com/cgi-bin/musicu.fcg"
        data = await http_get(
            url,
            params={"format": "json", "data": json.dumps(req_body)},
            headers=_QQ_PLAY_HEADERS,
            timeout=10,
        )

        try:
            req0 = data.get("req_0", {})
            sip_list = req0.get("data", {}).get("sip", [])
            midurlinfo = req0.get("data", {}).get("midurlinfo", [])
            if midurlinfo and sip_list:
                purl = midurlinfo[0].get("purl", "")
                if purl:
                    full_url = sip_list[0] + purl
                    logger.info("QQ音乐播放地址获取成功: songmid=%s, url=%s" % (songmid, full_url[:80]))
                    return full_url
                else:
                    logger.warning("QQ音乐播放地址为空(VIP歌曲?): songmid=%s" % songmid)
        except Exception as e:
            logger.warning("获取QQ音乐播放地址失败: songmid=%s, err=%s" % (songmid, e))

        return ""

    async def get_qq_toplist(self, topid: int = 26, limit: int = 100) -> list:
        """
        获取QQ音乐榜单歌曲（默认 topid=26 热歌榜，无需登录）。
        返回字段与 search_qq 一致，失败返回空列表。
        """
        url = "https://c.y.qq.com/v8/fcg-bin/fcg_v8_toplist_cp.fcg"
        params = {
            "topid": topid,
            "format": "json",
            "page": "detail",
            "type": "top",
            "tpl": 3,
            "platform": "h5",
        }
        data = await http_get(url, params=params, headers=_QQ_SEARCH_HEADERS, timeout=10)
        result = []
        songlist = data.get("songlist") or []
        for item in songlist[:limit]:
            s = item.get("data") or {}
            songname = s.get("songname", "")
            if not songname:
                continue
            singers = "/".join(si.get("name", "") for si in s.get("singer", []))
            songmid = s.get("songmid", "")
            albummid = s.get("albummid", "")
            interval = s.get("interval", 0)
            pay = s.get("pay", {})
            is_free = pay.get("payplay", 1) == 0
            cover = ""
            if albummid:
                cover = "https://y.gtimg.cn/music/photo_new/T002R300x300M000%s.jpg" % albummid
            result.append({
                "name": songname,
                "artist": singers,
                "song_id": str(s.get("songid", "")),
                "songmid": songmid,
                "duration": int(interval) if interval else 0,
                "cover": cover,
                "source": "QQ音乐",
                "is_free": is_free,
            })
        return result

    # ================================================================
    # 网易云搜索（备用）
    # ================================================================

    async def search_netease(self, keyword: str, limit: int = 10) -> list:
        """网易云音乐搜索（autumnfish 公共API）。如果公共API不可用会抛异常，由外层兜底到QQ音乐。"""
        data = await http_get(
            _NETEASE_API_BASE + "/search",
            params={"keywords": keyword, "limit": limit},
            timeout=10,
        )
        if not data:
            # 公共API不通/返回空，抛异常让外层 try/except 触发 QQ 音乐兜底
            raise RuntimeError("网易云公共API(%s)不可用" % _NETEASE_API_BASE)
        songs = (data.get("result") or {}).get("songs") or []
        if not songs:
            raise RuntimeError("网易云搜索无结果或API异常")
        result = []
        for s in songs:
            artists = "/".join(a.get("name", "") for a in s.get("artists", []))
            result.append({
                "name": s.get("name", ""),
                "artist": artists,
                "song_id": str(s.get("id", "")),
                "songmid": "",
                "duration": int(s.get("duration", 0) // 1000),
                "cover": "",
                "source": "网易云音乐",
                "is_free": True,
            })
        return result

    async def get_netease_detail(self, song_id: str) -> str:
        """获取网易云歌曲封面URL"""
        data = await http_get(
            _NETEASE_API_BASE + "/song/detail",
            params={"ids": song_id},
            timeout=10,
        )
        songs = data.get("songs") or []
        if songs:
            al = songs[0].get("al") or {}
            return al.get("picUrl", "")
        return ""

    async def get_netease_play_url(self, song_id: str) -> str:
        """获取网易云歌曲播放地址（128k，autumnfish 公共API）。失败返回空。"""
        if not song_id:
            return ""
        data = await http_get(
            _NETEASE_API_BASE + "/song/url",
            params={"id": song_id, "br": 128000},
            timeout=10,
        )
        try:
            url = (data.get("data") or {}).get("url", "")
            if url:
                logger.info("网易云播放地址获取成功: id=%s" % song_id)
                return url
            logger.warning("网易云播放地址为空(可能版权限制): id=%s" % song_id)
        except Exception as e:
            logger.warning("获取网易云播放地址失败: %s" % e)
        return ""

    # ================================================================
    # 酷狗搜索（备用）
    # ================================================================

    async def search_kugou(self, keyword: str, limit: int = 10) -> list:
        """酷狗音乐搜索"""
        data = await http_get(
            "http://mobilecdn.kugou.com/api/v3/search/song",
            params={"format": "json", "keyword": keyword, "page": 1, "pagesize": limit},
            headers=_UA_HEADERS, timeout=10,
        )
        result = []
        try:
            lst = data["data"]["info"]
        except (KeyError, TypeError):
            lst = []
        for s in lst:
            cover = s.get("imgUrl", "") or s.get("album_img", "")
            if cover and not cover.startswith("http"):
                cover = ("http://" + cover) if not cover.startswith("//") else ("https:" + cover)
            result.append({
                "name": self._clean_tag(s.get("songname", "")),
                "artist": s.get("singername", ""),
                "song_id": s.get("hash", ""),
                "songmid": "",
                "duration": int(s.get("duration", 0)),
                "cover": cover,
                "source": "酷狗音乐",
                "is_free": True,
            })
        return result

    async def get_kugou_play_url(self, song_hash: str) -> str:
        """
        获取酷狗歌曲播放地址。
        优先使用 config.py 的 KUGOU_PLAY_API 自定义代理（{hash} 占位）；
        否则走内置 getCdnIfo 接口（带签名）。失败返回空，由调用方降级为信息展示。
        注意：酷狗签名算法可能随官方调整变化，若内置接口失效请改用 KUGOU_PLAY_API。
        """
        if not song_hash:
            return ""

        # 方式1：用户自建/可用的代理接口（最稳，推荐）
        if KUGOU_PLAY_API:
            try:
                url = KUGOU_PLAY_API.format(hash=song_hash)
                data = await http_get(url, timeout=10)
                if isinstance(data, dict):
                    for k in ("url", "play_url", "data"):
                        v = data.get(k)
                        if isinstance(v, str) and v.startswith("http"):
                            return v
                        if isinstance(v, dict):
                            u = v.get("url") or v.get("play_url")
                            if u:
                                return u
            except Exception as e:
                logger.warning("酷狗自定义代理播放地址获取失败: %s" % e)
            return ""

        # 方式2：内置 getCdnIfo（需签名）
        dfid = KUGOU_DFID
        raw = "%s%sWINDOWS_CLIENT%s%s%s" % (
            KUGOU_SIGN_PREFIX, KUGOU_SECRET, dfid, song_hash, "kuwo"
        )
        sign = hashlib.md5(raw.encode("utf-8")).hexdigest()
        params = {
            "r": "play/getCdnIfo",
            "hash": song_hash,
            "dfid": dfid,
            "appid": KUGOU_APPID,
            "mid": KUGOU_MID,
            "platid": KUGOU_PLATID,
            "sign": sign,
        }
        try:
            data = await http_get(
                KUGOU_API_BASE + "/yy/index.php",
                params=params, headers=_UA_HEADERS, timeout=10,
            )
            url = (data.get("data") or {}).get("play_url", "") or (data.get("url") or "")
            if url:
                logger.info("酷狗播放地址获取成功: hash=%s" % song_hash[:16])
                return url
            logger.warning("酷狗播放地址为空(可能版权限制/VIP): hash=%s" % song_hash[:16])
        except Exception as e:
            logger.warning("获取酷狗播放地址失败: %s" % e)
        return ""

    # ================================================================
    # 酷我搜索（备用）
    # ================================================================

    async def search_kuwo(self, keyword: str, limit: int = 10) -> list:
        """
        酷我音乐搜索（OIAPI Kuwo 列表模式）。
        接口完全免鉴权；返回字段：name/artist/song_id/cover/duration/source/is_free
        同时写入两个隐藏字段 _oiapi_kw / _oiapi_n，用于 send_song_info 阶段再调
        OIAPI 单首模式拿播放直链。
        """
        data = await http_get(
            OIAPI_KUWO_URL,
            params={"msg": keyword},  # 不传 n/page，OIAPI 返回 10 条 list
            headers={"User-Agent": OIAPI_KUWO_UA},
            timeout=OIAPI_KUWO_TIMEOUT,
        )
        # 校验 OIAPI 标准返回
        if not isinstance(data, dict) or str(data.get("code")) != "1":
            raise RuntimeError(
                "酷我(OIAPI)接口不可用或返回异常: code=%s" % data.get("code") if isinstance(data, dict) else "non-dict"
            )
        items = data.get("data")
        if not isinstance(items, list) or not items:
            raise RuntimeError("酷我(OIAPI)搜索无结果或格式变更")
        result = []
        for i, s in enumerate(items[:limit], 1):
            try:
                duration = int(s.get("time") or 0)
            except (ValueError, TypeError):
                duration = 0
            result.append({
                "name": (s.get("song") or "").strip(),
                "artist": (s.get("singer") or "").strip(),
                "song_id": s.get("rid", ""),       # OIAPI 提供的 rid（如 MUSIC_324244）
                "songmid": "",
                "duration": duration,
                "cover": s.get("picture", "") or "",
                "source": "酷我音乐",
                "is_free": True,
                # 隐藏字段：用于播放时再调 OIAPI 单首模式拿 url
                "_oiapi_kw": keyword,
                "_oiapi_n": i,
            })
        return result

    async def get_kuwo_play_url(self, keyword: str, n: int) -> str:
        """
        酷我音乐播放直链（OIAPI 单首模式）。
        用 ?msg=xxx&n=N&page=1 拿 data.url（OSS 资源直链，Referer 来自 kuwo.cn）。
        失败返回空字符串；调用方应兜底到文本链接。
        """
        if not keyword or n < 1:
            return ""
        try:
            data = await http_get(
                OIAPI_KUWO_URL,
                params={"msg": keyword, "n": int(n), "page": 1},
                headers={"User-Agent": OIAPI_KUWO_UA},
                timeout=OIAPI_KUWO_TIMEOUT,
            )
        except Exception as e:
            logger.warning("酷我(OIAPI)取播放地址异常: keyword=%s n=%s err=%s" % (keyword, n, e))
            return ""
        if not isinstance(data, dict) or str(data.get("code")) != "1":
            logger.warning("酷我(OIAPI)取播放地址失败: code=%s" % (data.get("code") if isinstance(data, dict) else "non-dict"))
            return ""
        item = data.get("data")
        if not isinstance(item, dict):
            return ""
        return (item.get("url") or "").strip()

    # ================================================================
    # 统一搜索入口
    # ================================================================

    async def search(self, keyword: str, group_openid: str, limit: int = 10) -> list:
        """根据群当前音源搜索歌曲；任一音源不可用时自动兜底到QQ音乐。"""
        source = self.get_source(group_openid)
        try:
            if source == "QQ音乐":
                return await self.search_qq(keyword, limit)
            if source == "网易云音乐":
                return await self.search_netease(keyword, limit)
            if source == "酷狗音乐":
                return await self.search_kugou(keyword, limit)
            if source == "酷我音乐":
                return await self.search_kuwo(keyword, limit)
        except Exception as e:
            logger.error("搜索歌曲异常(音源=%s): %s" % (source, e))
            # 主音源失败时，自动兜底到QQ音乐
            if source != "QQ音乐":
                logger.info("主音源失败，兜底到QQ音乐搜索...")
                try:
                    return await self.search_qq(keyword, limit)
                except Exception as e2:
                    logger.error("QQ音乐兜底也失败: %s" % e2)
        return []

    @staticmethod
    def _clean_tag(text: str) -> str:
        if not text:
            return ""
        return text.replace("<em>", "").replace("</em>", "")

    # ================================================================
    # 发送歌曲信息
    # ================================================================

    async def send_song_info(self, api, song: dict, group_openid: str, msg_id: str = None,
                             scene: str = ChatScene.GROUP):
        """
        发送歌曲信息：语音试听 + 封面图 + 歌曲信息（支持群聊/私聊场景）。
        免费歌曲：下载音频以语音消息发送（file_type=3），附带歌曲信息文本。
        VIP歌曲：仅发送封面图 + 歌曲信息文本，提示VIP无法试听。
        """
        scene = scene or ChatScene.GROUP
        if not song:
            await send_text(api, scene, group_openid, "未找到相关歌曲～", msg_id=msg_id)
            return

        name = song.get("name", "")
        artist = song.get("artist", "")
        duration = song.get("duration", 0)
        cover = song.get("cover", "")
        source = song.get("source", "")
        is_free = song.get("is_free", False)
        # 显示用配置的音源(与「音源选择」菜单一致);若实际播放源不一致(搜索兜底)则注明
        configured_source = self.get_source(group_openid)
        if source and configured_source and source != configured_source:
            display_source = "%s（%s 兜底）" % (configured_source, source)
        else:
            display_source = configured_source or source

        # 网易云搜索结果不含封面，需单独获取详情
        if not cover and source == "网易云音乐" and song.get("song_id"):
            cover = await self.get_netease_detail(song["song_id"])
            song["cover"] = cover

        # 各音源获取播放链接
        play_url = ""
        if source == "QQ音乐" and song.get("songmid"):
            play_url = await self.get_qq_play_url(song["songmid"])
        elif source == "网易云音乐" and song.get("song_id"):
            play_url = await self.get_netease_play_url(song["song_id"])
        elif source == "酷狗音乐" and song.get("song_id"):
            play_url = await self.get_kugou_play_url(song["song_id"])
        elif source == "酷我音乐" and song.get("_oiapi_kw") and song.get("_oiapi_n"):
            play_url = await self.get_kuwo_play_url(song["_oiapi_kw"], song["_oiapi_n"])

        # 构建歌曲信息文本
        text_lines = [
            "🎵 %s" % (name or "未知歌曲"),
            "👤 歌手：%s" % (artist or "未知"),
        ]
        if duration > 0:
            text_lines.append("⏱ 时长：%s" % format_duration(duration))
        text_lines.append("📀 音源：%s" % display_source)

        if play_url:
            # 免费歌曲：歌曲信息 + 封面 + 语音试听（优先整条发送，超限回退分段）
            logger.info("开始发送语音音乐[%s]: %s - %s" % (scene, name, artist))
            text_lines.append("🎧 正在发送语音试听（整首歌）")
            info_text = "\n".join(text_lines)

            # 不同音源防盗链 Referer
            if source == "酷我音乐":
                _audio_headers = {"User-Agent": OIAPI_KUWO_UA, "Referer": OIAPI_KUWO_PLAY_REFERER}
            else:
                _audio_headers = _QQ_PLAY_HEADERS

            # 先发歌曲信息 + 封面图
            await send_text(api, scene, group_openid, info_text, msg_id=msg_id)
            if cover:
                try:
                    await send_image_for_scene(api, scene, group_openid, cover, msg_id=msg_id)
                except Exception as e:
                    logger.warning("发送封面图失败(不影响音乐): %s" % e)

            # 优先整条语音（不分段，标准音质）；整条失败（含低码率重试仍超限）则降级为文本链接，绝不分段
            audio_result = await send_audio_whole_for_scene(
                api, scene, group_openid, play_url,
                msg_id=msg_id,
                headers=_audio_headers,
            )
            if not audio_result:
                # 整条语音发送失败，降级为文本+链接（不分段）
                logger.warning("整条语音发送失败，降级为文本链接（不分段）")
                await send_text(api, scene, group_openid, "▶️ 试听链接：%s" % play_url, msg_id=msg_id)

        else:
            # 无法获取播放地址（VIP 歌曲或接口异常）
            if source == "QQ音乐" and is_free:
                text_lines.append("⚠️ 免费歌曲但获取播放地址失败，请稍后重试")
            elif source in ("网易云音乐", "酷狗音乐", "酷我音乐"):
                text_lines.append("🔒 暂无法获取试听链接（版权限制或接口异常）")
            else:
                text_lines.append("🔒 该歌曲为VIP歌曲，暂无法试听")
            info_text = "\n".join(text_lines)

            if cover:
                try:
                    await send_image_for_scene(api, scene, group_openid, cover, msg_id=msg_id)
                except Exception as e:
                    logger.warning("发送封面图失败: %s" % e)
            await send_text(api, scene, group_openid, info_text, msg_id=msg_id)

    # ================================================================
    # 随机音乐
    # ================================================================

    # 随机音乐榜单池：热歌榜26 / 流行指数4 / 内地榜27 / 网络歌曲28
    RANDOM_TOPLIST_IDS = [26, 4, 27, 28]
    # 榜单失败时的随机搜索关键词兜底池
    RANDOM_KEYWORDS = [
        "热门歌曲", "经典老歌", "流行金曲", "华语经典", "抖音热歌",
        "青春", "夏天", "回忆", "晚风", "星空", "告白", "民谣",
    ]

    async def handle_random(self, api, group_openid: str, msg_id: str = None,
                            scene: str = ChatScene.GROUP):
        """随机音乐：从QQ音乐榜单随机抽取一首免费歌曲（榜单失败时随机关键词搜索兜底）"""
        scene = scene or ChatScene.GROUP
        results = []

        # 1) 主通道：随机挑一个榜单拉取（热歌榜等，池大且免费标记准确）
        try:
            topid = random.choice(self.RANDOM_TOPLIST_IDS)
            results = await self.get_qq_toplist(topid, 100)
            if results:
                logger.info("随机音乐: 榜单 topid=%s 获取 %d 首" % (topid, len(results)))
        except Exception as e:
            logger.warning("随机音乐榜单获取异常: %s" % e)

        # 2) 兜底：随机关键词搜索（最多尝试2个不同关键词）
        if not results:
            for kw in random.sample(self.RANDOM_KEYWORDS, 2):
                try:
                    results = await self.search_qq(kw, 30)
                except Exception as e:
                    logger.warning("随机音乐搜索异常(kw=%s): %s" % (kw, e))
                    results = []
                if results:
                    logger.info("随机音乐: 关键词「%s」搜索兜底获取 %d 首" % (kw, len(results)))
                    break

        if not results:
            await send_text(api, scene, group_openid, "随机音乐获取失败，请稍后再试～", msg_id=msg_id)
            return

        # 优先选择免费歌曲
        free_songs = [s for s in results if s.get("is_free")]
        pool = free_songs if free_songs else results
        song = random.choice(pool)

        logger.info("随机音乐: %s - %s (free=%s)" % (
            song.get("name", ""), song.get("artist", ""), song.get("is_free", False)
        ))
        await self.send_song_info(api, song, group_openid, msg_id, scene=scene)

        keyboard = build_keyboard_command("再来一首", "随机音乐", button_id="btn_random_music", enter=True)
        await send_text_with_keyboard(
            api, scene, group_openid, "点击下方按钮再随机一首👇", keyboard, msg_id=msg_id
        )

    # ================================================================
    # 点歌 / 选歌
    # ================================================================

    async def handle_search(self, api, content: str, group_openid: str, msg_id: str = None,
                            scene: str = ChatScene.GROUP):
        """
        点歌处理：
        - '点歌 歌名'        -> 列表模式（返回多个版本，待"选歌 序号"选择）
        - '点歌 歌名 歌手'    -> 直接模式（按歌手过滤后直接发送）
        """
        scene = scene or ChatScene.GROUP
        rest = content[len("点歌"):].strip()
        if not rest:
            await send_text(api, scene, group_openid, "请输入歌曲名，例如：点歌 晴天", msg_id=msg_id)
            return

        # 提示搜索中
        await send_text(api, scene, group_openid, "🔍 正在搜索「%s」..." % rest, msg_id=msg_id)

        tokens = rest.split()
        if len(tokens) == 1:
            await self._search_and_list(api, tokens[0], group_openid, msg_id, scene=scene)
        else:
            song_kw = tokens[0]
            artist_kw = " ".join(tokens[1:])
            results = await self.search(song_kw, group_openid)
            matched = [r for r in results if artist_kw in r.get("artist", "")]
            if matched:
                # 优先选择免费歌曲
                free_matched = [r for r in matched if r.get("is_free")]
                await self.send_song_info(api, free_matched[0] if free_matched else matched[0], group_openid, msg_id, scene=scene)
            else:
                results2 = await self.search(rest, group_openid)
                if results2:
                    # 优先选择免费歌曲
                    free_results = [r for r in results2 if r.get("is_free")]
                    await self.send_song_info(api, free_results[0] if free_results else results2[0], group_openid, msg_id, scene=scene)
                else:
                    await send_text(
                        api, scene, group_openid, "未找到「%s」相关歌曲～" % rest, msg_id=msg_id
                    )

    async def _search_and_list(self, api, keyword: str, group_openid: str, msg_id: str = None,
                               scene: str = ChatScene.GROUP):
        """搜索并以编号列表形式返回多个版本，缓存结果供选歌使用"""
        results = await self.search(keyword, group_openid)
        if not results:
            await send_text(api, scene, group_openid, "未找到「%s」相关歌曲～" % keyword, msg_id=msg_id)
            return

        self._search_cache[group_openid] = results[:10]

        lines = ["🎵「%s」搜索结果：" % keyword]
        for i, r in enumerate(results[:10], 1):
            dur_str = ""
            if r.get("duration", 0) > 0:
                dur_str = " [%s]" % format_duration(r["duration"])
            # 标记免费🆓/VIP🔒
            free_tag = "🆓" if r.get("is_free") else "🔒"
            lines.append("%d. %s %s - %s%s" % (
                i, free_tag, r.get("name", ""), r.get("artist", ""), dur_str
            ))
        lines.append("\n🆓=可试听  🔒=VIP歌曲")
        lines.append("回复「选歌 序号」选择歌曲")
        await send_text(api, scene, group_openid, "\n".join(lines), msg_id=msg_id)

    async def handle_select(self, api, content: str, group_openid: str, msg_id: str = None,
                            scene: str = ChatScene.GROUP):
        """选歌处理：'选歌 序号'"""
        scene = scene or ChatScene.GROUP
        rest = content[len("选歌"):].strip()
        try:
            index = int(rest)
        except ValueError:
            await send_text(api, scene, group_openid, "请输入正确的序号，例如：选歌 1", msg_id=msg_id)
            return

        results = self._search_cache.get(group_openid, [])
        if not results:
            await send_text(
                api, scene, group_openid, "暂无搜索记录，请先使用「点歌 歌名」搜索", msg_id=msg_id
            )
            return
        if index < 1 or index > len(results):
            await send_text(
                api, scene, group_openid, "序号超出范围，请输入 1~%d 之间的数字" % len(results), msg_id=msg_id
            )
            return

        song = results[index - 1]

        # VIP歌曲自动推荐免费版本
        if not song.get("is_free", False) and song.get("source") == "QQ音乐":
            logger.info("选中VIP歌曲，搜索免费版本: %s" % song.get("name", ""))
            # 在已缓存的搜索结果中查找同名免费版本
            song_name = song.get("name", "").split("(")[0].strip()  # 去掉括号后缀
            free_alternatives = [
                r for r in results
                if r.get("is_free") and song_name in r.get("name", "")
            ]
            if free_alternatives:
                logger.info("找到免费版本: %s - %s" % (
                    free_alternatives[0].get("name", ""),
                    free_alternatives[0].get("artist", "")
                ))
                await send_text(
                    api, scene, group_openid,
                    "🔒 「%s」为VIP歌曲，已为你找到免费版本👇" % song.get("name", ""),
                    msg_id=msg_id,
                )
                await self.send_song_info(api, free_alternatives[0], group_openid, msg_id, scene=scene)
                return
            else:
                # 缓存中无免费版本，尝试重新搜索
                re_search = await self.search_qq(song_name, 20)
                free_re = [r for r in re_search if r.get("is_free")]
                if free_re:
                    logger.info("重新搜索找到免费版本: %s - %s" % (
                        free_re[0].get("name", ""), free_re[0].get("artist", "")
                    ))
                    await send_text(
                        api, scene, group_openid,
                        "🔒 「%s」为VIP歌曲，已为你找到免费版本👇" % song.get("name", ""),
                        msg_id=msg_id,
                    )
                    await self.send_song_info(api, free_re[0], group_openid, msg_id, scene=scene)
                    return

        await self.send_song_info(api, song, group_openid, msg_id, scene=scene)

    # ================================================================
    # 音源选择
    # ================================================================

    async def handle_source_select(self, api, group_openid: str, msg_id: str = None,
                                   scene: str = ChatScene.GROUP):
        """音源选择：展示音源按钮"""
        current = self.get_source(group_openid)
        buttons = []
        for src in self.SOURCES:
            label = "✅ %s" % src if src == current else src
            buttons.append({"label": label, "command": "音源 " + src, "enter": True})
        keyboard = build_keyboard_multi(buttons)
        text = "请选择音乐音源（当前：%s）" % current
        await send_text_with_keyboard(api, scene, group_openid, text, keyboard, msg_id=msg_id)

    async def handle_source_set(self, api, source: str, group_openid: str, msg_id: str = None,
                                scene: str = ChatScene.GROUP):
        """设置群音源"""
        if source not in self.SOURCES:
            await send_text(
                api, scene, group_openid, "不支持的音源，请发送「音源选择」查看可选音源", msg_id=msg_id
            )
            return
        self.set_source(group_openid, source)
        await send_text(api, scene, group_openid, "✅ 音源已切换为：%s" % source, msg_id=msg_id)

    # ================================================================
    # 命令入口
    # ================================================================

    async def handle_command(self, api, content, group_openid, member_openid, msg_id, scene=None):
        """
        处理音乐相关命令，返回 True 表示已处理。
        命令：随机音乐 / 点歌 / 选歌 / 音源选择 / 音源 XXX
        scene: "group" / "c2c" / "channel"（仅作语义提示）
        """
        content = clean_content(content).strip()
        scene = scene or ChatScene.GROUP

        # 随机音乐
        if content == "随机音乐":
            await self.handle_random(api, group_openid, msg_id, scene=scene)
            return True

        # 音源相关
        if content == "音源" or content == "音源选择":
            await self.handle_source_select(api, group_openid, msg_id, scene=scene)
            return True
        if content.startswith("音源"):
            source = content[len("音源"):].strip()
            await self.handle_source_set(api, source, group_openid, msg_id, scene=scene)
            return True

        # 点歌
        if content.startswith("点歌"):
            await self.handle_search(api, content, group_openid, msg_id, scene=scene)
            return True

        # 选歌
        if content.startswith("选歌"):
            await self.handle_select(api, content, group_openid, msg_id, scene=scene)
            return True

        return False
