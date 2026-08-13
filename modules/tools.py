# -*- coding: utf-8 -*-
"""
工具系统模块
功能：视频解析（小渡聚合解析，支持抖音/快手/B站/小红书/视频号/YouTube/TikTok 等 20+ 平台，返回无水印视频/图集）
"""

import re
import json
import time
import urllib.parse
import urllib.request
from modules.common import (
    send_text,
    send_text_with_keyboard,
    send_video_bytes_for_scene,
    send_video_for_scene,
    send_image_for_scene,
    load_json,
    save_json,
    build_keyboard_multi,
    is_duplicate,
    clean_content,
    logger,
    http_get,
    http_post,
    http_get_text,
    http_get_with_redirect,
    _download_media_bytes_with_headers,
    _probe_video_duration,
    _head_content_length,
    format_duration,
    ChatScene,
    parse_chat_id,
)
from modules.config import (
    DWO_VIDEO_PARSE_KEY, DISEASE_API_URL, XXAPI_KEY,
    OIAPI_WASTE_URL, OIAPI_WASTE_TIMEOUT,
)

# ============ User-Agent ============
_UA_MOBILE = (
    "Mozilla/5.0 (Linux; Android 13; SM-G991B Build/TP1A.220624.014) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)
_UA_PC = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# ============ 数据文件名 ============
VIDEO_PARSE_STATE_FILE = "video_parse_state.json"  # 视频解析等待状态
DISEASE_STATE_FILE = "disease_state.json"  # 疾病信息查询等待状态
WASTE_STATE_FILE = "waste_state.json"  # 垃圾分类查询等待状态

# 疾病信息：常用疾病快捷查询（二级按钮）
# 6 个最常用疾病，按钮排版一行 5 个以内，QQ 渲染时 label 不会被截断
_DISEASE_COMMON = ["感冒", "高血压", "糖尿病", "胃炎", "头痛", "失眠"]

# 视频解析限制：最大时长 20 分钟（1200 秒），大小不限制（max_size_mb=0）
VIDEO_PARSE_MAX_DURATION = 1200

# 疾病信息查询（小小API - 常见疾病百科）
_DISEASE_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Authorization": "Bearer %s" % XXAPI_KEY,
}

# 垃圾分类（OIAPI WasteSorting）请求头（免鉴权，无需 ckey）
_WASTE_HEADERS = {"User-Agent": "Mozilla/5.0"}

# 垃圾分类：常用垃圾快捷查询（二级按钮）
# 选择原则：覆盖四大类别 + 日常高频 + 一词多义场景
_WASTE_COMMON = [
    "电池",          # 电池（多结果场景：同词不同类别）
    "过期药品",      # 过期药品
    "旧衣物",        # 旧衣物
    "外卖盒",        # 外卖盒
    "香蕉皮",        # 香蕉皮
    "废纸张",        # 废纸张
    "玻璃瓶",        # 玻璃瓶
]

# 垃圾分类 → emoji 映射（用于结果卡片美化）
_WASTE_CATEGORY_EMOJI = {
    "可回收垃圾": "♻️",
    "有害垃圾":   "☣️",
    "湿垃圾":     "🍃",
    "干垃圾":     "🗑️",
    "大件垃圾":   "📦",
}

# 文本排版用常量（疾病信息卡片分隔线 / 列表分隔符）
_BOX_LINE = "\u2501" * 9   # ━━━━━━━━━━
_LIST_SEP = "\u3001"        # 、


# ============ 支持的视频平台 ============
# 解析入口统一走小渡 /api/svparse；下面的域名用于识别用户分享的链接属于哪个平台，
# 平台名称会展示给用户。
VIDEO_PLATFORMS = {
    # 抖音
    "douyin.com": "抖音", "iesdouyin.com": "抖音", "v.douyin.com": "抖音",
    # 快手
    "kuaishou.com": "快手", "v.kuaishou.com": "快手", "ksapp.kuaishou.com": "快手",
    "gifshow.com": "快手",
    # 小红书
    "xiaohongshu.com": "小红书", "xhslink.com": "小红书",
    # B站
    "bilibili.com": "B站", "b23.tv": "B站",
    # 视频号
    "finder.video.qq.com": "视频号", "video.qq.com": "视频号",
    "weixin.qq.com": "视频号", "v.qq.com": "视频号",
    # 油管
    "youtube.com": "YouTube", "youtu.be": "YouTube",
    # TikTok
    "tiktok.com": "TikTok", "vm.tiktok.com": "TikTok",
    # 西瓜视频
    "ixigua.com": "西瓜视频",
    # 好看视频
    "haokan.baidu.com": "好看视频",
    # 微视
    "weishi.qq.com": "微视",
    # 梨视频
    "pearvideo.com": "梨视频",
    # 微博
    "weibo.com": "微博", "weibo.cn": "微博",
    # 知乎
    "zhihu.com": "知乎", "zhuanlan.zhihu.com": "知乎",
    # AcFun
    "acfun.cn": "AcFun",
    # 皮皮虾
    "pipix.com": "皮皮虾",
    # 最右
    "izuiyou.com": "最右",
}

# 英语单词详解接口
_WORD_API = "https://v2.xxapi.cn/api/englishwords"

class ToolsManager:
    """工具系统 - 视频解析"""

    def __init__(self):
        pass

    def _state_key(self, group_openid, member_openid):
        """生成状态存储键（群+用户唯一标识）

        兼容老数据：如果 group_openid 带前缀（如 'g:xxx'），先去掉。
        之前 bot.py 把带前缀的 chat_id 传给 handle_callback，导致状态 key
        出现 'g:xxx|yyy' 格式的脏数据，这里做一次防御性清理。
        """
        if group_openid and ":" in str(group_openid):
            # 可能是 'g:xxx' / 'u:xxx' / 'c:xxx'
            try:
                _, raw = parse_chat_id(group_openid)
                group_openid = raw
            except Exception:
                # parse 失败就保留原值
                pass
        return "%s|%s" % (group_openid, member_openid)

    def _extract_video_url(self, text: str) -> str:
        """从消息文本中提取视频链接（兼容各种分享格式）

        支持：
        - 纯 URL: https://v.douyin.com/abc/
        - 抖音分享: 11.11 复制打开抖音 https://v.douyin.com/abc/ 复制此链接...
        - B 站分享: 【标题】 https://b23.tv/abc 复制链接...
        - 含中文标点的混合文本

        Returns: 提取到的 URL，找不到返回 None
        """
        # 先尝试更宽松的匹配（排除常见中文标点 + 半角标点）
        m = re.search(r"https?://[^\s，,。<>\"'」】！!？?；;：:]+", text, re.IGNORECASE)
        if m:
            url = m.group(0)
            # 去掉末尾可能的标点残留
            url = url.rstrip(".,;:!?。，；：！？、")
            return url
        return None

    def is_waiting(self, group_openid: str, member_openid: str) -> bool:
        """检查用户是否处于等待输入状态（视频解析 / 疾病信息查询 / 垃圾分类）

        兼容老数据：之前 bot.py 把带前缀的 chat_id 传给 handle_callback，
        状态文件里写入了 'g:xxx|yyy' 格式的 key。这里同时尝试：
          - 新格式 key（裸 ID）
          - 老格式 key（带 g: / u: / c: 前缀）
        """
        video_states = load_json(VIDEO_PARSE_STATE_FILE)
        key = self._state_key(group_openid, member_openid)
        if video_states.get(key, {}).get("waiting"):
            return True
        # 老数据兼容：尝试带前缀的 key
        if group_openid and ":" not in str(group_openid):
            for prefix in ("g:", "u:", "c:"):
                old_key = "%s%s|%s" % (prefix, group_openid, member_openid)
                if video_states.get(old_key, {}).get("waiting"):
                    return True
        disease_states = load_json(DISEASE_STATE_FILE)
        if disease_states.get(key, {}).get("waiting"):
            return True
        # 垃圾分类（多候选列表等用户选序号）：写入了 WASTE_STATE_FILE 但未在原检查中，
        # 导致用户在群里发序号（纯数字非触发词）被 bot.py 当作非指令直接 return，机器人无响应。
        waste_states = load_json(WASTE_STATE_FILE)
        if waste_states.get(key, {}).get("waiting"):
            return True
        return False

    # ================================================================
    #                       视频解析
    # ================================================================

    async def _video_parse_start(self, api, target_id, member_openid, scene=None, msg_id=None, event_id=None):
        """用户点击按钮后，设置等待状态并提示输入链接

        target_id 是裸 ID（与 handle_callback 调用方约定一致）。
        """
        if scene is None:
            scene = ChatScene.GROUP
        # 防御：如果传入了带前缀的 chat_id，先剥掉
        if target_id and ":" in str(target_id):
            try:
                _, target_id = parse_chat_id(target_id)
            except Exception:
                pass
        states = load_json(VIDEO_PARSE_STATE_FILE)
        states[self._state_key(target_id, member_openid)] = {"waiting": True}
        save_json(VIDEO_PARSE_STATE_FILE, states)
        await send_text(
            api, scene, target_id,
            "请@机器人发送视频链接（支持抖音/快手/B站/小红书/视频号/油管/TikTok等20+平台）\n发送「取消」可取消解析",
            msg_id=msg_id,
            event_id=event_id,
        )

    def _detect_platform(self, url):
        """从URL中检测视频平台"""
        url_lower = url.lower()
        for domain, name in VIDEO_PLATFORMS.items():
            if domain in url_lower:
                return name
        return "未知平台"

    # ================================================================
    #                   平台专属解析器
    #   每个解析器返回: (video_url, title, cover, download_headers)
    #   video_url 为 None 表示解析失败
    #   download_headers 为 None 表示下载时不需要特殊请求头
    # ================================================================

    async def _parse_douyin(self, url):
        """
        抖音直接解析 - iesdouyin 分享页 _ROUTER_DATA 方法。
        原理: 手机端分享页会在 HTML 中嵌入 window._ROUTER_DATA，
              包含完整视频信息（无水印），无需签名计算，长期稳定。
        """
        headers = {
            "User-Agent": _UA_MOBILE,
            "Referer": "https://www.douyin.com",
        }

        # 1. 跟随重定向获取视频ID
        _, final_url, _ = await http_get_with_redirect(url, headers=headers)
        id_match = re.search(r"/video/(\d+)", final_url)
        if not id_match:
            id_match = re.search(r"/video/(\d+)", url)
        if not id_match:
            logger.error("抖音解析: 未找到视频ID, url=%s" % url[:80])
            return None, "", "", None

        video_id = id_match.group(1)
        logger.info("抖音解析: 视频ID=%s" % video_id)

        # 2. 请求 iesdouyin 分享页
        share_url = "https://www.iesdouyin.com/share/video/%s/" % video_id
        html, _, status = await http_get_with_redirect(share_url, headers=headers, timeout=15)
        if not html:
            logger.error("抖音解析: 分享页请求失败, status=%s" % status)
            return None, "", "", None

        # 3. 提取 _ROUTER_DATA
        match = re.search(r'window\._ROUTER_DATA\s*=\s*(\{.*?\})\s*</script>', html, re.DOTALL)
        if not match:
            match = re.search(r'_ROUTER_DATA\s*=\s*(\{.*?\});', html, re.DOTALL)
        if not match:
            logger.error("抖音解析: 未找到 _ROUTER_DATA")
            return None, "", "", None

        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError as e:
            logger.error("抖音解析: JSON解析失败: %s" % e)
            return None, "", "", None

        # 4. 提取视频信息
        try:
            video_info_res = data["loaderData"]["video_(id)/page"]["videoInfoRes"]
            item_list = video_info_res.get("item_list", [])
            
            # item_list 为空: 视频可能已被删除或不可访问
            if not item_list:
                filter_list = video_info_res.get("filter_list", [])
                reason = ""
                if filter_list:
                    reason = filter_list[0].get("filter_reason", "")
                logger.error("抖音解析: 视频不可访问, reason=%s, video_id=%s" % (reason, video_id))
                return None, "", "", None

            item = item_list[0]
            title = item.get("desc", "") or "抖音视频"
            author = item.get("author", {}).get("nickname", "")
            video_info = item.get("video", {})
            cover = ""
            if video_info.get("cover", {}).get("url_list"):
                cover = video_info["cover"]["url_list"][0]
            video_uri = video_info.get("play_addr", {}).get("uri", "")
            images = item.get("images", [])

            # 图集类型: 返回图片列表
            if images and not video_uri:
                image_urls = []
                for img in images:
                    url_list = img.get("url_list", [])
                    if url_list:
                        image_urls.append(url_list[0])
                if image_urls:
                    logger.info("抖音解析: 图集类型, %d张图片" % len(image_urls))
                    return ("images", image_urls), "%s - %s" % (title, author), cover, None

            # 视频类型: 构造无水印地址
            if video_uri and "mp3" not in video_uri:
                video_url = "https://www.douyin.com/aweme/v1/play/?video_id=" + video_uri
            elif video_uri:
                video_url = video_uri
            else:
                logger.error("抖音解析: 无视频地址")
                return None, "", "", None

            full_title = "%s - %s" % (title, author) if author else title
            download_headers = {"User-Agent": _UA_MOBILE, "Referer": "https://www.douyin.com"}
            logger.info("抖音解析成功: %s" % full_title[:50])
            return video_url, full_title, cover, download_headers

        except (KeyError, IndexError) as e:
            logger.error("抖音解析: 提取视频信息失败: %s" % e)
            return None, "", "", None

    async def _parse_bilibili(self, url):
        """
        B站直接解析 - 官方API。
        1. 处理 b23.tv 短链接重定向
        2. 提取 BV 号
        3. 调用官方 API 获取 cid 和标题
        4. 调用播放地址 API 获取视频直链
        """
        headers = {"User-Agent": _UA_PC}

        # 1. 处理短链接
        if "b23.tv" in url:
            _, final_url, _ = await http_get_with_redirect(url, headers=headers)
            if final_url:
                url = final_url
            logger.info("B站解析: 短链接重定向 -> %s" % url[:80])

        # 2. 提取 BV 号
        bv_match = re.search(r"(BV\w+)", url)
        if not bv_match:
            logger.error("B站解析: 未找到BV号, url=%s" % url[:80])
            return None, "", "", None
        bvid = bv_match.group(1)
        logger.info("B站解析: BV号=%s" % bvid)

        # 3. 获取视频信息
        info = await http_get(
            "https://api.bilibili.com/x/web-interface/view",
            params={"bvid": bvid}, headers=headers, timeout=10,
        )
        if not info or info.get("code") != 0:
            logger.error("B站解析: 获取视频信息失败, code=%s" % (info.get("code") if info else "None"))
            return None, "", "", None

        data = info.get("data", {})
        title = data.get("title", "") or "B站视频"
        cover = data.get("pic", "")
        cid = data.get("cid", "")
        if not cid:
            logger.error("B站解析: 无cid")
            return None, title, cover, None

        # 4. 获取播放地址 - 逐级降级确保文件不超25MB
        # qn: 64=720P, 32=480P, 16=360P
        download_headers = {"User-Agent": _UA_PC, "Referer": "https://www.bilibili.com"}
        max_bytes = 25 * 1024 * 1024  # 25MB

        for qn in [64, 32, 16]:
            play = await http_get(
                "https://api.bilibili.com/x/player/playurl",
                params={"bvid": bvid, "cid": cid, "qn": qn, "fnval": 1, "fnver": 0},
                headers=headers, timeout=10,
            )
            if not play or play.get("code") != 0:
                continue

            durl = play.get("data", {}).get("durl", [])
            if not durl:
                continue

            video_url = durl[0].get("url", "")
            file_size = durl[0].get("size", 0)

            if not video_url:
                continue

            # 检查文件大小，超限则降级
            if file_size and file_size > max_bytes:
                qn_name = {64: "720P", 32: "480P", 16: "360P"}.get(qn, str(qn))
                logger.info("B站解析: %s文件过大(%.1fMB > 25MB)，降级" % (qn_name, file_size / 1024 / 1024))
                continue

            logger.info("B站解析成功[%s]: %s" % ({64: "720P", 32: "480P", 16: "360P"}.get(qn, str(qn)), title[:50]))
            return video_url, title, cover, download_headers

        # 所有清晰度都超限: 返回最低清晰度的URL，由下载函数处理
        if durl and video_url:
            logger.warning("B站解析: 所有清晰度均超25MB，返回360P")
            return video_url, title, cover, download_headers

        logger.error("B站解析: 获取播放地址失败")
        return None, title, cover, None

    async def _parse_via_xiaodu(self, url):
        """
        小渡短视频聚合解析 (openapi.dwo.cc/api/svparse)。
        支持 20+ 平台：抖音 / 快手 / 小红书 / B站 / 视频号 / 油管 / TikTok /
        西瓜视频 / 好看视频 / 微视 / 梨视频 / 微博 / 知乎 / AcFun 等。

        返回值与平台专属解析器保持一致：
          (video_url, title, cover, download_headers)
        - video_url 为 None 表示解析失败
        - 当 data.type == "image" 时返回 (("images", [...]), title, cover, None)
          以便 _video_parse_query 走 _send_image_gallery 分支
        - download_headers 为 None 表示下载时不需要特殊请求头
        """
        if not DWO_VIDEO_PARSE_KEY:
            logger.error("小渡视频解析: 未配置 DWO_VIDEO_PARSE_KEY")
            return None, "", "", None

        # 小渡 GET 接口对部分 CDN 资源要求 Referer：常见视频号/QQ/B站直链下载时附上 UA 即可。
        headers = {"User-Agent": _UA_PC}
        try:
            data = await http_get(
                "https://openapi.dwo.cc/api/svparse",
                params={"url": url, "ckey": DWO_VIDEO_PARSE_KEY},
                headers=headers,
                timeout=20,
            )
        except Exception as e:
            logger.error("小渡视频解析: 请求异常: %s" % e)
            return None, "", "", None

        if not data:
            logger.error("小渡视频解析: 响应为空 url=%s" % url[:80])
            return None, "", "", None
        if data.get("code") != 200:
            logger.error("小渡视频解析: 失败 code=%s msg=%s url=%s" % (
                data.get("code"), data.get("msg"), url[:80]))
            return None, "", "", None

        payload = data.get("data") or {}
        if not isinstance(payload, dict) or not payload:
            logger.error("小渡视频解析: data 字段为空 url=%s" % url[:80])
            return None, "", "", None

        ctype = payload.get("type", "video")
        title = (payload.get("title") or payload.get("desc") or "").strip()
        cover = payload.get("cover") or ""

        # 图集类型 (type=image)：data.images 是 URL 数组
        if ctype == "image":
            images = payload.get("images") or []
            images = [u for u in images if isinstance(u, str) and u.startswith("http")]
            if images:
                logger.info("小渡视频解析: 图集类型, %d张图片, title=%s" % (len(images), title[:50]))
                return ("images", images), title, cover, None
            logger.error("小渡视频解析: 图集类型但 images 为空 url=%s" % url[:80])
            return None, title, cover, None

        # 视频类型 (type=video)
        video_url = payload.get("url") or ""
        if not video_url:
            # 回退到 video_backup 第一个
            backups = payload.get("video_backup") or []
            for bk in backups:
                if isinstance(bk, dict) and bk.get("url"):
                    video_url = bk["url"]
                    break
                if isinstance(bk, str) and bk.startswith("http"):
                    video_url = bk
                    break
        if not video_url:
            logger.error("小渡视频解析: 未返回视频地址 url=%s" % url[:80])
            return None, title, cover, None

        # B站 CDN (upos-sz-mirrorcos.bilivideo.com 等) 需要 Referer 才能下载到视频字节
        download_headers = None
        url_lower = video_url.lower()
        if "bilivideo.com" in url_lower or "bilibili.com" in url_lower:
            download_headers = {
                "User-Agent": _UA_PC,
                "Referer": "https://www.bilibili.com",
            }

        logger.info("小渡视频解析成功[%s]: %s" % (ctype, title[:50]))
        return video_url, title, cover, download_headers

    async def _video_parse_query(self, api, url, group_openid, member_openid, msg_id, scene=None):
        """执行视频解析 - 平台专属解析优先，第三方API回退

        scene 用于决定发送目标（C2C/CHANNEL 也支持视频解析）
        """
        if scene is None:
            scene = ChatScene.GROUP
        # 防御：如果传入了带前缀的 chat_id，先剥掉
        if group_openid and ":" in str(group_openid):
            try:
                _, group_openid = parse_chat_id(group_openid)
            except Exception:
                pass

        # 清除等待状态
        states = load_json(VIDEO_PARSE_STATE_FILE)
        key = self._state_key(group_openid, member_openid)
        if key in states:
            del states[key]
            save_json(VIDEO_PARSE_STATE_FILE, states)

        platform = self._detect_platform(url)

        await send_text(
            api, scene, group_openid, "正在解析%s视频..." % platform, msg_id=msg_id
        )

        # 解析策略：
        #   1. 所有平台先尝试小渡 /api/svparse（支持 20+ 平台，统一入口）
        #   2. 抖音/B站：若小渡失败，回退到平台专属解析器（iesdouyin/官方API），
        #      这两个解析器有 B站 Referer 校验和 25MB 大小降级等兜底逻辑
        video_url = None
        title = ""
        cover = ""
        download_headers = None

        video_url, title, cover, download_headers = await self._parse_via_xiaodu(url)

        if not video_url and platform == "抖音":
            logger.info("抖音：尝试专属解析器兜底...")
            video_url, title, cover, download_headers = await self._parse_douyin(url)
        elif not video_url and platform == "B站":
            logger.info("B站：尝试专属解析器兜底...")
            video_url, title, cover, download_headers = await self._parse_bilibili(url)

        # 解析失败
        if not video_url:
            await send_text(
                api, scene, group_openid,
                "视频解析失败\n可能原因：视频已被删除/链接已失效/平台限制\n请确认链接有效后重试",
                msg_id=msg_id,
            )
            return

        # 图集类型: 发送图片
        if isinstance(video_url, tuple) and video_url[0] == "images":
            image_urls = video_url[1]
            await self._send_image_gallery(api, group_openid, image_urls, title, cover, msg_id, scene)
            return

        # 构建提示文本
        content = "视频解析成功！\n平台：%s" % platform
        if title:
            content += "\n标题：%s" % title

        # 发送视频（带特殊请求头时需要先下载再上传）
        if download_headers:
            # 视频解析限制（运行时读取后台配置，0=不限制）
            try:
                from console_server import get_video_limits
                _vl = get_video_limits().get("parse", {}) or {}
            except Exception:
                _vl = {}
            try:
                _max_dur = int(_vl.get("max_duration", VIDEO_PARSE_MAX_DURATION))
            except Exception:
                _max_dur = VIDEO_PARSE_MAX_DURATION
            try:
                _max_mb = int(_vl.get("max_mb", 0))
            except Exception:
                _max_mb = 0
            video_bytes = await _download_media_bytes_with_headers(
                video_url, headers=download_headers, timeout=120, max_size_mb=_max_mb
            )
            if video_bytes:
                # 时长限制，超限拒绝发送（max_duration<=0 表示不限制）
                try:
                    dur = await _probe_video_duration(video_bytes)
                except Exception:
                    dur = 0.0
                if _max_dur > 0 and dur > _max_dur:
                    await send_text(
                        api, scene, group_openid,
                        "视频超过时长上限（最大 %d 分钟），无法发送" % int(_max_dur / 60),
                        msg_id=msg_id,
                    )
                    return
                result = await send_video_bytes_for_scene(
                    api, scene, group_openid, video_bytes,
                    content=content, msg_id=msg_id, fallback_link=url
                )
                if result is None:
                    # send_video_bytes_for_scene 内部已降级发外链文字，这里仅补充一句
                    await send_text(
                        api, scene, group_openid,
                        content + "\n\n（视频过大/上传失败，已发送外链，请点击查看）",
                        msg_id=msg_id,
                    )
                return
            else:
                logger.error("视频下载失败(带headers): %s" % video_url[:80])
                await send_text(
                    api, scene, group_openid,
                    content + "\n\n视频下载失败，可能是链接已失效",
                    msg_id=msg_id,
                )
                return

        # 普通视频: 直接通过URL发送（场景无关）
        result = await send_video_for_scene(
            api, scene, group_openid, video_url,
            msg_id=msg_id, content=content, fallback_link=url
        )
        if result is None:
            await send_text(
                api, scene, group_openid,
                content + "\n\n视频发送失败，可能是视频链接已失效或格式不支持",
                msg_id=msg_id,
            )

    async def _send_image_gallery(self, api, group_openid, image_urls, title, cover, msg_id, scene=None):
        """发送图集（多张图片）"""
        if scene is None:
            scene = ChatScene.GROUP
        content = "图集解析成功！\n标题：%s\n共%d张图片" % (title, len(image_urls))
        await send_text(api, scene, group_openid, content, msg_id=msg_id)

        # 逐张发送图片（最多9张，QQ 群限制）
        for i, img_url in enumerate(image_urls[:9]):
            try:
                result = await send_image_for_scene(
                    api, scene, group_openid, img_url,
                    msg_id=None,
                    content="第%d张" % (i + 1) if i == 0 else "",
                )
                if result is None:
                    logger.warning("发送图集第%d张失败" % (i + 1))
            except Exception as e:
                logger.error("发送图集第%d张异常: %s" % (i + 1, e))

    # ================================================================
    #                       天气查询
    # ================================================================

    async def _query_weather(self, api, city, group_openid, msg_id, scene=None):
        """
        查询指定城市天气（小渡API - 高德数据源）
        接口: https://openapi.dwo.cc/api/tianqi
        参数: districtId=城市名(如「南昌市」), ckey=API密钥
        返回: {"code":1,"data":{...},"message":"请求成功","status":200}
        """
        if scene is None:
            scene = ChatScene.GROUP
        try:
            from modules.config import QQ_INFO_KEY
        except ImportError:
            QQ_INFO_KEY = ""

        if not QQ_INFO_KEY:
            await send_text(
                api, scene, group_openid,
                "天气查询功能未配置API密钥，请联系管理员",
                msg_id=msg_id,
            )
            return

        import urllib.parse
        import urllib.request
        import json as _json

        headers = {"User-Agent": _UA_PC}

        # 小渡API 要求市级名称带「市」后缀（如「南昌市」），省级带「省」；
        # 用户常只输入「南昌」，这里自动补全常见行政区划后缀后重试。
        suffixes = ("省", "市", "区", "县", "自治区", "自治州", "盟", "地区")
        candidates = []
        if not city.endswith(suffixes):
            candidates.append(city + "市")
        candidates.append(city)

        last_err = ""
        for cand in candidates:
            city_encoded = urllib.parse.quote(cand)
            url = "https://openapi.dwo.cc/api/tianqi?districtId=%s&ckey=%s" % (city_encoded, QQ_INFO_KEY)
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    raw = resp.read().decode("utf-8")
                data = _json.loads(raw)

                # 小渡天气返回：code=1 成功
                if data.get("code") == 1 and data.get("data"):
                    d = data["data"]
                    city_name = d.get("city", cand)
                    weather = d.get("weather", "")
                    temp = d.get("temp", "")
                    feels = d.get("feelsLike", "")
                    humidity = d.get("rh", "")
                    low = d.get("lowTemp", "")
                    high = d.get("highTemp", "")
                    wind = d.get("wind", "")
                    date_str = d.get("date", "")
                    day_str = d.get("day", "")
                    report_time = d.get("dateTime", "")

                    msg = (
                        "🌤 天气查询\n"
                        "━━━━━━━━━━\n"
                        "📍 %s\n"
                        "🌀 天气：%s\n"
                        "🌡 当前温度：%s\n"
                        "🤚 体感温度：%s\n"
                        "🌡 温度区间：%s ~ %s\n"
                        "💧 湿度：%s\n"
                        "🍃 风力：%s\n"
                        "📅 %s %s\n"
                        "🕐 %s\n" % (
                            city_name,
                            weather,
                            temp,
                            feels,
                            low, high,
                            humidity,
                            wind,
                            date_str, day_str,
                            report_time,
                        )
                    )
                    await send_text(api, scene, group_openid, msg, msg_id=msg_id)
                    return
                else:
                    last_err = data.get("message") or data.get("info") or "查询失败"
                    # 城市格式/未找到时尝试下一个候选（如补「市」）
                    continue
            except Exception as e:
                logger.error("天气查询异常: %s" % e)
                last_err = "请求异常"
                continue

        # 所有候选都失败
        await send_text(
            api, scene, group_openid,
            "天气查询失败：%s\n请输入正确的城市名，如：天气 南昌市" % last_err,
            msg_id=msg_id,
        )

    # ================================================================
    #                  常见疾病信息查询（小小API / xxapi.cn）
    # ================================================================

    async def _disease_fetch(self, word):
        """
        调用小小API常见疾病信息接口（disease），传入疾病名，返回 data（list 中取第一个）。
        失败返回 None。
        """
        try:
            data = await http_get(
                DISEASE_API_URL,
                params={'word': word},
                headers=_DISEASE_HEADERS,
                timeout=10,
            )
        except Exception as e:
            logger.error('\u75be\u75c5\u4fe1\u606f\u67e5\u8be2\u63a5\u53e3\u8bf7\u6c42\u5f02\u5e38: %s' % e)
            return None

        if not isinstance(data, dict) or data.get('code') != 200:
            code = data.get('code') if isinstance(data, dict) else 'None'
            logger.warning('\u75be\u75c5\u4fe1\u606f\u63a5\u53e3\u8fd4\u56de\u5f02\u5e38: code=%s' % code)
            return None

        d = data.get('data')
        if not d:
            return None
        # data 可能是列表（取第一个）或单个 dict
        if isinstance(d, list):
            if not d:
                return None
            d = d[0]
        return d

    @staticmethod
    def _fmt_list(v):
        """将列表/字符串统一格式化为逗号分隔文本"""
        if not v:
            return '\u6682\u65e0'
        if isinstance(v, list):
            return _LIST_SEP.join(str(x) for x in v) if v else '\u6682\u65e0'
        return str(v)

    @staticmethod
    def _truncate(s, n):
        """过长文案截断，避免单条消息超出群聊阅读舒适区"""
        if not s:
            return '\u6682\u65e0'
        s = str(s)
        return s if len(s) <= n else s[:n] + '\u2026'

    def _disease_format(self, word, d, mode='summary'):
        """格式化疾病信息
        mode='summary':     摘要（主消息，markdown 表格语法，仿 QQ 签到日历样式
                            -> 顶部标题 + QQ 原生表格 + 底部数据来源）
        mode='detail':      完整 markdown 表格版（带全部字段，无 padding 段）
        mode='screen':      超长完整版（markdown 表格 + 健康提示 padding，>=4500 字符
                            触发 QQ 原生 markdown 自动折叠 -> 用户点「点击查看全文」进入
                            QQ 原生全屏深色页面，QQ 自带底部「换行/复制」按钮）
        mode='copy':        纯文本版（无 markdown 符号，便于手机长按复制）
        mode='short_copy':  短纯文本摘要（<=300 字符，用于「复制」按钮 enter=True 自动填入输入框）
        """
        name = d.get('name') or word
        desc = d.get('desc') or d.get('description') or '\u6682\u65e0'
        cause = d.get('cause') or '\u6682\u65e0'
        get_way = d.get('get_way') or '\u6682\u65e0'
        get_prob = d.get('get_prob') or '\u6682\u65e0'
        cure_way = self._fmt_list(d.get('cure_way'))
        cure_department = self._fmt_list(d.get('cure_department'))
        cure_lasttime = d.get('cure_lasttime') or '\u6682\u65e0'
        cured_prob = d.get('cured_prob') or '\u6682\u65e0'
        cost_money = d.get('cost_money') or '\u6682\u65e0'
        check = self._fmt_list(d.get('check'))
        drug = self._fmt_list(d.get('drug_detail'))
        acompany = self._fmt_list(d.get('acompany'))
        prevent = d.get('prevent') or '\u6682\u65e0'
        category = self._fmt_list(d.get('category'))

        def _cell(v, n=80):
            """表格单元格：单行（换行/回车替换为空格），`|` 转义以免破坏表格语法；过长截断"""
            if not v or v == '\u6682\u65e0':
                return '\u6682\u65e0'
            v = str(v).replace('\r', ' ').replace('\n', ' ').replace('|', '\\|')
            return self._truncate(v, n)

        # ========== 复制模式：纯文本，无 markdown 符号，手机长按可整段复制 ==========
        if mode == 'copy':
            lines = [
                '\u3010%s\u3011' % name,
                _BOX_LINE,
                '\u5206\u7c7b\uff1a%s' % category,
                '\u7b80\u4ecb\uff1a%s' % desc,
                '\u75c5\u56e0\uff1a%s' % cause,
                '\u4f20\u64ad\u9014\u5f84\uff1a%s' % get_way,
                '\u60a3\u75c5\u6982\u7387\uff1a%s' % get_prob,
                '\u5c31\u8bca\u79d1\u5ba4\uff1a%s' % cure_department,
                '\u6cbb\u7597\u65b9\u6cd5\uff1a%s' % cure_way,
                '\u6cbb\u7597\u5468\u671f\uff1a%s' % cure_lasttime,
                '\u6cbb\u6108\u7387\uff1a%s' % cured_prob,
                '\u53c2\u8003\u8d39\u7528\uff1a%s' % cost_money,
                '\u68c0\u67e5\u9879\u76ee\uff1a%s' % check,
            ]
            if drug and drug != '\u6682\u65e0':
                lines.append('\u5e38\u7528\u836f\u7269\uff1a%s' % drug)
            if acompany and acompany != '\u6682\u65e0':
                lines.append('\u5e76\u53d1\u75c5\uff1a%s' % acompany)
            lines.append('\u9884\u9632\uff1a%s' % prevent)
            lines.append(_BOX_LINE)
            lines.append('\u6570\u636e\u6765\u6e90\uff1a\u5c0f\u5c0fAPI\uff08\u4ec5\u4f9b\u53c2\u8003\uff0c\u8eab\u4f53\u4e0d\u9002\u8bf7\u5c31\u533b\uff09')
            return '\n'.join(lines)

        # ========== 全屏模式 / 详情模式：完整 markdown 表格 ==========
        if mode in ('screen', 'detail'):
            n = 200 if mode == 'screen' else 100
            rows = [
                ('\U0001F4C2 \u5206\u7c7b', _cell(category, n)),
                ('\U0001F4DD \u7b80\u4ecb', _cell(desc, n)),
                ('\U0001F9A0 \u75c5\u56e0', _cell(cause, n)),
                ('\U0001F6B6 \u4f20\u64ad\u9014\u5f84', _cell(get_way, n)),
                ('\U0001F4CA \u60a3\u75c5\u6982\u7387', _cell(get_prob, n)),
                ('\U0001F3E5 \u5c31\u8bca\u79d1\u5ba4', _cell(cure_department, n)),
                ('\U0001F48A \u6cbb\u7597\u65b9\u6cd5', _cell(cure_way, n)),
                ('\u23f3 \u6cbb\u7597\u5468\u671f', _cell(cure_lasttime, n)),
                ('\u2705 \u6cbb\u6108\u7387', _cell(cured_prob, n)),
                ('\U0001F4B0 \u53c2\u8003\u8d39\u7528', _cell(cost_money, n)),
                ('\U0001F52C \u68c0\u67e5\u9879\u76ee', _cell(check, n)),
            ]
            if drug and drug != '\u6682\u65e0':
                rows.append(('\U0001F489 \u5e38\u7528\u836f\u7269', _cell(drug, n)))
            if acompany and acompany != '\u6682\u65e0':
                rows.append(('\u26a0\ufe0f \u5e76\u53d1\u75c5', _cell(acompany, n)))
            rows.append(('\U0001F6E1 \u9884\u9632', _cell(prevent, n)))

            # 生成 markdown 表格
            table_lines = ['| \u9879\u76ee | \u5185\u5bb9 |', '| --- | --- |']
            for k, v in rows:
                table_lines.append('| %s | %s |' % (k, v))
            table = '\n'.join(table_lines)

            if mode == 'screen':
                lines = [
                    '# \U0001F3E5 %s \u5b8c\u6574\u4fe1\u606f' % name,
                    '',
                    '> \U0001F4AC \u672c\u9875\u5e26\u6709\u6240\u6709\u5b57\u6bb5\u7684\u5b8c\u6574\u5185\u5bb9\uff0c\u9002\u5408\u5168\u5c4f\u67e5\u770b\u3002\u5982\u9700\u590d\u5236\u6587\u672c\uff0c\u8bf7\u70b9\u5168\u5c4f\u9875\u9762\u5e95\u90e8\u7684\u300c\u590d\u5236\u300d\u6309\u94ae\u3002',
                    '',
                    table,
                    '',
                    _BOX_LINE,
                    '',
                    '> \U0001F4AC *\u6570\u636e\u6765\u6e90\uff1a\u5c0f\u5c0fAPI\uff08\u4ec5\u4f9b\u53c2\u8003\uff0c\u8eab\u4f53\u4e0d\u9002\u8bf7\u5c31\u533b\uff09*',
                    '',
                    '> \U0001F4DD *\u751f\u6210\u65f6\u95f4\uff1a%s*' % time.strftime('%Y-%m-%d %H:%M'),
                ]
                text = '\n'.join(lines)
                # 表格紧凑，需要补充多段「健康提示」padding 段，确保总长稳定 >=4500 触发 QQ 原生自动折叠
                # padding 段用 blockquote（>）包裹 + 健康类提示语，视觉自然不喧宾夺主
                if len(text) < 4500:
                    pad_block = (
                        '\n\n%s\n\n'
                        '> \u26a0\ufe0f **\u533b\u7597\u63d0\u793a**\uff1a\u672c\u8bcd\u6761\u4ec5\u4f9b\u53c2\u8003\uff0c\u4e0d\u4ee3\u66ff\u4e13\u4e1a\u8bca\u65ad\u3002\u5982\u51fa\u73b0\u4ee5\u4e0b\u60c5\u5f62\u8bf7\u53ca\u65f6\u5c31\u533b\uff1a\n'
                        '>\n'
                        '> - \U0001F489 \u9ad8\u70e7\u3001\u6301\u7eed\u5934\u75db\u3001\u89c6\u7269\u6a21\u7cca\n'
                        '> - \U0001F4A7 \u5455\u5410\u3001\u8179\u6cfb\u3001\u9ed1\u4fbf/\u4fbf\u8840\n'
                        '> - \U0001F525 \u80f8\u75db\u3001\u5fc3\u60e8\u3001\u547c\u5438\u56f0\u96be\n'
                        '> - \U0001F9A0 \u610f\u8bc6\u4e0d\u6e05\u3001\u8f6c\u53d8\u52a3\u5316\n'
                        '>\n'
                        '> \U0001F3E5 **\u5c31\u8bca\u6307\u5f15**\uff1a\u521d\u8bca\u9009\u62e9\u4e09\u7532\u533b\u9662\u76f8\u5173\u79d1\u5ba4\uff0c\u590d\u67e5\u53ef\u9009\u4e13\u79d1\u533b\u9662\u3002\u5e26\u597d\u95ee\u53a8\u3001\u5f53\u524d\u7528\u836f\u3001\u8fc7\u654f\u53f2\u3002\n'
                        '>\n'
                        '> \U0001F48A **\u7528\u836f\u63d0\u9192**\uff1a\u4e25\u683c\u9075\u533b\u5631\u670d\u836f\uff0c\u4e0d\u8981\u81ea\u884c\u8c03\u6574\u836f\u91cf\u6216\u505c\u836f\u3002\u51fa\u73b0\u4e0d\u826f\u53cd\u5e94\u53ca\u65f6\u54a8\u8be2\u533b\u751f\u3002\n'
                        '>\n'
                        '> \U0001F4DC **\u5065\u5eb7\u7ba1\u7406**\uff1a\u5747\u8861\u996e\u98df\u3001\u9002\u91cf\u8fd0\u52a8\u3001\u5b88\u65f6\u4f5c\u606f\u3001\u5fc3\u7406\u5e73\u8861\u662f\u591a\u6570\u6162\u75c5\u7ba1\u63a7\u7684\u57fa\u7840\u3002\n'
                        '\n%s\n'
                    ) % (_BOX_LINE, _BOX_LINE)
                    full_pad = ''
                    while len(text) + len(full_pad) < 4500:
                        full_pad += pad_block
                    lines.append('')
                    lines.extend(full_pad.strip().splitlines())
                    text = '\n'.join(lines)
                return text
            else:  # detail
                lines = [
                    '# \U0001F3E5 %s' % name,
                    '',
                    table,
                    '',
                    _BOX_LINE,
                    '*\u6570\u636e\u6765\u6e90\uff1a\u5c0f\u5c0fAPI\uff08\u4ec5\u4f9b\u53c2\u8003\uff09*',
                ]
                return '\n'.join(lines)

        # ========== 短纯文本模式：<=300 字符（用于「复制」按钮 enter=True 自动填入输入框） ==========
        # QQ inline button action.data 限制约 1KB（中文 3 字节），300 中文字符 ~ 900 字节，安全余量充足
        # 短文本不适合用表格（管道符会让用户复制后清理不便），保持列表形式
        if mode == 'short_copy':
            lines = [
                '\U0001F3E5 %s' % name,
                _BOX_LINE,
                '\u5206\u7c7b\uff1a%s' % category,
                '\u7b80\u4ecb\uff1a%s' % self._truncate(desc, 60),
                '\u75c5\u56e0\uff1a%s' % self._truncate(cause, 50),
                '\u5c31\u8bca\uff1a%s | \u6cbb\u7597\uff1a%s' % (cure_department, cure_way),
                '\u6cbb\u6108\u7387\uff1a%s | \u8d39\u7528\uff1a%s' % (cured_prob, cost_money),
                _BOX_LINE,
                '\u5b8c\u6574\u7248\u8bf7\u70b9\u300c\u25b2 \u5168\u5c4f\u300d\u6309\u94ae',
            ]
            return '\n'.join(lines)

        # ========== 摘要模式：主消息，markdown 表格（仿 QQ 签到日历样式）
        # 仅保留 5 行核心字段（QQ 群聊表格卡片渲染有最大可视高度，超出行数会被裁掉）。
        # 病因/治愈率/检查/药物/预防等次要字段，用户可发「疾病信息 复制 病名」拿到纯文本全文。 ==========
        rows = [
            ('\U0001F4C2 \u5206\u7c7b', _cell(category, 20)),
            ('\U0001F4DD \u7b80\u4ecb', _cell(desc, 50)),
            ('\U0001F3E5 \u5c31\u8bca', _cell(cure_department, 20)),
            ('\U0001F48A \u6cbb\u7597', _cell(cure_way, 30)),
            ('\U0001F4B0 \u8d39\u7528', _cell(cost_money, 25)),
        ]
        table_lines = ['| \u9879\u76ee | \u5185\u5bb9 |', '| --- | --- |']
        for k, v in rows:
            table_lines.append('| %s | %s |' % (k, v))
        table = '\n'.join(table_lines)

        lines = [
            '# \U0001F3E5 %s' % name,
            '',
            table,
            '',
            '> \U0001F4AC \u9700\u67e5\u770b\u5b8c\u6574\u4fe1\u606f\uff08\u542b\u5e76\u53d1\u75c5/\u68c0\u67e5/\u836f\u7269/\u9884\u9632\u7b49\u5168\u90e8\u5b57\u6bb5\uff09\uff0c\u53ef\u53d1\u9001\u300c\u75be\u75c5\u4fe1\u606f \u590d\u5236 %s\u300d\u83b7\u53d6\u7eaf\u6587\u672c\u7248' % word,
            _BOX_LINE,
            '*\u6570\u636e\u6765\u6e90\uff1a\u5c0f\u5c0fAPI\uff08\u4ec5\u4f9b\u53c2\u8003\uff09*',
        ]
        return '\n'.join(lines)

    async def disease_info(self, api, group_openid, member_openid, msg_id, word, scene=None):
        """调用疾病信息接口并发送结果（带 再查一次 / 返回主菜单 按钮）。"""
        if scene is None:
            scene = ChatScene.GROUP
        # 进入查询即退出等待态（用 member_openid 清，msg_id 不能作 state key）
        self._disease_clear_waiting(group_openid, member_openid)
        if not word:
            await send_text(
                api, scene, group_openid,
                '\U0001F3E5 \u75be\u75c5\u4fe1\u606f\n' + _BOX_LINE + '\n'
                '\u7528\u6cd5\uff1a\u75be\u75c5\u4fe1\u606f \u75be\u75c5\u540d\n'
                '\u793a\u4f8b\uff1a\u75be\u75c5\u4fe1\u606f \u611f\u5192 / \u75be\u75c5\u4fe1\u606f \u9ad8\u8840\u538b\n\n'
                '\u67e5\u8be2\u5e38\u89c1\u75c5\u60a3\u7684\u7b80\u4ecb\u3001\u75c5\u56e0\u3001\u6cbb\u7597\u7b49\u4fe1\u606f',
                msg_id=msg_id,
            )
            return

        await send_text(
            api, scene, group_openid,
            '\U0001F3E5 \u6b63\u5728\u67e5\u8be2\u300c%s\u300d\u7684\u76f8\u5173\u4fe1\u606f...\u8bf7\u7a0d\u5019...' % word,
            msg_id=msg_id,
        )

        d = await self._disease_fetch(word)
        if not d:
            await send_text(
                api, scene, group_openid,
                '\U0001F622 \u672a\u67e5\u8be2\u5230\u300c%s\u300d\u7684\u76f8\u5173\u4fe1\u606f\uff0c\u8bf7\u68c0\u67e5\u540d\u79f0\u662f\u5426\u6b63\u786e\uff5e' % word,
                msg_id=msg_id,
            )
            return

        text = self._disease_format(word, d, mode='summary')
        keyboard = build_keyboard_multi([
            {'label': '\U0001F504 \u518d\u67e5\u4e00\u6b21', 'command': '\u75be\u75c5\u4fe1\u606f', 'enter': False},
            {'label': '\U0001F519 \u8fd4\u56de\u4e3b\u83dc\u5355', 'command': '\u8fd4\u56de\u4e3b\u83dc\u5355', 'enter': False},
        ])
        await send_text_with_keyboard(
            api, scene, group_openid,
            text, keyboard, msg_id=msg_id,
        )
        logger.info('\u75be\u75c5\u4fe1\u606f\u67e5\u8be2\u6210\u529f[%s]: word=%s' % (scene, word))

    async def _disease_show_copy(self, api, group_openid, msg_id, word, scene=None):
        """点「复制全文」按钮后调用：发送纯文本版（无 markdown 符号），便于手机长按复制。"""
        if scene is None:
            scene = ChatScene.GROUP
        d = await self._disease_fetch(word)
        if not d:
            await send_text(
                api, scene, group_openid,
                '\U0001F622 \u672a\u67e5\u8be2\u5230\u300c%s\u300d\u7684\u76f8\u5173\u4fe1\u606f\uff0c\u8bf7\u68c0\u67e5\u540d\u79f0\u662f\u5426\u6b63\u786e' % word,
                msg_id=msg_id,
            )
            return
        text = self._disease_format(word, d, mode='copy')
        # 纯文本：直接 send_text，不带 markdown 也不带按钮，长按可整段复制
        await send_text(api, scene, group_openid, text, msg_id=msg_id)

    def _disease_clear_waiting(self, group_openid, member_openid):
        """清除当前用户的疾病查询等待态（查询完成 / 退出时调用）。"""
        try:
            states = load_json(DISEASE_STATE_FILE)
            key = self._state_key(group_openid, member_openid)
            if states.pop(key, None) is not None:
                save_json(DISEASE_STATE_FILE, states)
        except Exception:
            pass

    async def _disease_start(self, api, target_id, member_openid, scene=None, msg_id=None, event_id=None):
        """点击「疾病信息」按钮后进入等待态：提示输入疾病名，并展示常用疾病二级按钮。"""
        if scene is None:
            scene = ChatScene.GROUP
        if target_id and ":" in str(target_id):
            try:
                _, target_id = parse_chat_id(target_id)
            except Exception:
                pass
        states = load_json(DISEASE_STATE_FILE)
        states[self._state_key(target_id, member_openid)] = {"waiting": True}
        save_json(DISEASE_STATE_FILE, states)
        # 二级按钮：常用疾病快捷查询 + 返回主菜单
        # 不再加 emoji 前缀（QQ 端部分 emoji 渲染成奇怪图标且吃 label 宽度）
        buttons = [
            {"label": "\u25c6 %s" % d, "command": "\u75be\u75c5\u4fe1\u606f %s" % d, "enter": False}
            for d in _DISEASE_COMMON
        ]
        buttons.append({"label": "\u8fd4\u56de\u4e3b\u83dc\u5355", "command": "\u8fd4\u56de\u4e3b\u83dc\u5355", "enter": False})
        keyboard = build_keyboard_multi(buttons)
        await send_text_with_keyboard(
            api, scene, target_id,
            '\U0001F3E5 \u75be\u75c5\u4fe1\u606f\n' + _BOX_LINE + '\n'
            '\u8bf7\u76f4\u63a5\u53d1\u9001\u8981\u67e5\u8be2\u7684\u75be\u75c5\u540d\u79f0\uff0c\u6216\u70b9\u51fb\u4e0b\u65b9\u5e38\u7528\u75c5\u75be\u6309\u94ae\uff1a\n'
            '\u793a\u4f8b\uff1a\u75be\u75c5\u4fe1\u606f \u611f\u5192\n\u53d1\u9001\u300c\u53d6\u6d88\u300d\u53ef\u9000\u51fa',
            keyboard, msg_id=msg_id, event_id=event_id,
        )

    # ================================================================
    #                  垃圾分类查询（OIAPI WasteSorting）
    # ================================================================
    async def _waste_fetch(self, word, n=None):
        """调用 OIAPI WasteSorting。
        - n=None: 返回数据 payload（含 list 候选阵列）；失败返回 None
        - n=int:  返回单条 dict {waste, name, _list}; n 越界返回 None
        接口状态：code=1 成功；code=-2 未匹配（换个词）
        """
        try:
            params = {"word": word}
            if n is not None:
                params["n"] = n
            data = await http_get(
                OIAPI_WASTE_URL,
                params=params,
                headers=_WASTE_HEADERS,
                timeout=OIAPI_WASTE_TIMEOUT,
            )
        except Exception as e:
            logger.error("垃圾分类接口请求异常: %s" % e)
            return None
        if not isinstance(data, dict) or data.get("code") != 1:
            logger.warning("垃圾分类接口返回异常: code=%s msg=%s" % (data.get("code"), data.get("message")))
            return None
        payload = data.get("data") or {}
        if n is None:
            return payload
        # 单条模式：data.waste/name 已是接口填写好的结果，直接用。list 只作为上下文参考。
        single = {
            "waste": payload.get("waste") or "",
            "name": payload.get("name") or "",
            "_list": payload.get("list") or [],
        }
        if not single["waste"] or not single["name"]:
            return None
        return single

    def _waste_format_top(self, word, info):
        """单条结果卡片：♻️ X 是 Y 垃圾 + emoji、来源"""
        waste = info.get("waste") or word
        name = info.get("name") or ""
        if not name:
            return "🗑️ 垃圾分类\n" + _BOX_LINE + "\n未找到「%s」对应的分类" % word
        emoji = _WASTE_CATEGORY_EMOJI.get(name, "🗑️")
        return "🗑️ 垃圾分类\n" + _BOX_LINE + "\n%s %s\n物品：%s\n类别：%s %s" % (emoji, name, waste, emoji, name)

    def _waste_format_list(self, word, info):
        """多候选阵列卡片：展示前 max_show 个候选 + 提示选序号"""
        lst = info.get("list") or []
        if not lst:
            return "🗑️ 垃圾分类\n" + _BOX_LINE + "\n未找到「%s」对应的分类信息" % word
        max_show = 8
        shown = lst[:max_show]
        lines = ["🗑️ 垃圾分类", _BOX_LINE, "关键词：%s" % word, "找到 %d 个相关物品：" % len(lst), ""]
        for i, w in enumerate(shown, 1):
            lines.append("%d. %s" % (i, w))
        if len(lst) > max_show:
            lines.append("… 共 %d 个，仅显示前 %d 个" % (len(lst), max_show))
        lines.append("")
        lines.append("请回复序号 1-%d 选择具体物品" % max_show)
        lines.append("发送「取消」可退出")
        return "\n".join(lines)

    def _waste_clear_waiting(self, group_openid, member_openid):
        """清除垃圾分类等待态（查询完成 / 退出时调用）"""
        try:
            states = load_json(WASTE_STATE_FILE)
            key = self._state_key(group_openid, member_openid)
            if states.pop(key, None) is not None:
                save_json(WASTE_STATE_FILE, states)
        except Exception:
            pass

    async def _waste_start(self, api, target_id, member_openid, scene=None, msg_id=None, event_id=None):
        """点击「垃圾分类」按钮后进入等待态：提示输入垃圾名，并展示常用垃圾二级按钮。"""
        if scene is None:
            scene = ChatScene.GROUP
        if target_id and ":" in str(target_id):
            try:
                _, target_id = parse_chat_id(target_id)
            except Exception:
                pass
        states = load_json(WASTE_STATE_FILE)
        states[self._state_key(target_id, member_openid)] = {"waiting": True}
        save_json(WASTE_STATE_FILE, states)
        # 二级按钮：常用垃圾快捷查询 + 返回主菜单（3+3+2 三行布局，避免 5 个挤一行被压成 "..."）
        row1_labels = _WASTE_COMMON[:3]   # 电池 / 过期药品 / 外卖盒
        row2_labels = _WASTE_COMMON[3:6]  # 旧衣物 / 香蕉皮 / 废纸张
        row3_labels = _WASTE_COMMON[6:]   # 玻璃瓶（剩余）
        rows_spec = [
            [("◽ %s" % d, "垃圾分类 %s" % d) for d in row1_labels],
            [("◽ %s" % d, "垃圾分类 %s" % d) for d in row2_labels],
            [(("◽ %s" % d) if d else "", ("垃圾分类 %s" % d) if d else "") for d in row3_labels],
            [("🔙 返回主菜单", "返回主菜单")],
        ]
        rows = []
        for spec in rows_spec:
            btns = []
            for label, cmd in spec:
                if not cmd:
                    continue
                btns.append({
                    "id": "btn_" + cmd,
                    "render_data": {
                        "label": label,
                        "visited_label": label,
                        "style": 1,
                    },
                    "action": {
                        "type": 2,
                        "permission": {"type": 2},
                        "data": cmd,
                        "enter": False,
                        "unsupport_tips": "请更新QQ版本",
                    },
                })
            if btns:
                rows.append({"buttons": btns})
        keyboard = {"content": {"rows": rows}}
        await send_text_with_keyboard(
            api, scene, target_id,
            "🗑️ 垃圾分类\n" + _BOX_LINE + "\n"
            "请直接发送要查询的垃圾名称，或点击下方常用垃圾按钮：\n"
            "示例：垃圾分类 电池\n"
            "支持别称与细分（如「过期药品」「外卖盒」「果皮」）\n"
            "发送「取消」可退出",
            keyboard, msg_id=msg_id, event_id=event_id,
        )

    async def _waste_query(self, api, word, target_id, member_openid, msg_id, scene=None):
        """拿到垃圾名后查询：列表长度 1 → 直接给结论；>1 → 展示候选 + 记入上下文等待选序号"""
        if scene is None:
            scene = ChatScene.GROUP
        word = (word or "").strip()
        if not word:
            await send_text(api, scene, target_id, "🗑️ 垃圾分类\n" + _BOX_LINE + "\n请输入垃圾名称", msg_id=msg_id)
            return
        info = await self._waste_fetch(word, n=None)
        if not info:
            await send_text(
                api, scene, target_id,
                "🗑️ 垃圾分类\n" + _BOX_LINE + "\n未找到「%s」的分类信息，请换个更具体的名称试试" % word,
                msg_id=msg_id,
            )
            return
        lst = info.get("list") or []
        if len(lst) <= 1:
            # 单条匹配：直接 n=1 拿最终结论
            single = await self._waste_fetch(word, n=1)
            if not single:
                await send_text(
                    api, scene, target_id,
                    "🗑️ 垃圾分类\n" + _BOX_LINE + "\n未找到「%s」的分类信息，请换个更具体的名称试试" % word,
                    msg_id=msg_id,
                )
                return
            await send_text(api, scene, target_id, self._waste_format_top(word, single), msg_id=msg_id)
            self._waste_clear_waiting(target_id, member_openid)
            return
        # 多候选：记入上下文 + 展示候选列表
        states = load_json(WASTE_STATE_FILE)
        states[self._state_key(target_id, member_openid)] = {
            "waiting": True,
            "last_word": word,
            "_list": lst,
        }
        save_json(WASTE_STATE_FILE, states)
        await send_text(api, scene, target_id, self._waste_format_list(word, info), msg_id=msg_id)

    async def _waste_pick(self, api, n, target_id, member_openid, msg_id, scene=None):
        """用户在等待态中选序号：取出列表第 N 个 + 调 n=N 拿最终结论"""
        if scene is None:
            scene = ChatScene.GROUP
        states = load_json(WASTE_STATE_FILE)
        key = self._state_key(target_id, member_openid)
        state = states.get(key, {})
        word = state.get("last_word", "")
        if not word:
            await send_text(api, scene, target_id, "会话已过期，请重新发送「垃圾分类 XXX」", msg_id=msg_id)
            self._waste_clear_waiting(target_id, member_openid)
            return
        single = await self._waste_fetch(word, n=n)
        if not single:
            max_show = 8
            await send_text(api, scene, target_id, "序号无效，请重新选择 1-%d 之间的数字" % max_show, msg_id=msg_id)
            return
        await send_text(api, scene, target_id, self._waste_format_top(word, single), msg_id=msg_id)
        self._waste_clear_waiting(target_id, member_openid)

    # ================================================================
    #                  单词详解查询（小小API / xxapi.cn）
    # ================================================================

    async def _query_word(self, api, word_input, group_openid, msg_id, scene=None):
        """查询英语单词详解（小小API，可选 Bearer Key）

        接口: https://v2.xxapi.cn/api/englishwords
        参数: word=英文单词
        """
        if scene is None:
            scene = ChatScene.GROUP

        word = (word_input or "").strip()
        if not word:
            await send_text(
                api, scene, group_openid,
                """🔤 单词详解
━━━━━━━━━━
请输入要查询的英文单词，例如：
单词 cancel""",
                msg_id=msg_id,
            )
            return

        # 取首个空白前的词，避免连打
        word = word.split()[0]
        if not word:
            await send_text(
                api, scene, group_openid,
                """🔤 单词详解
━━━━━━━━━━
未识别到有效单词，请发送英文单词，例如：
单词 cancel""",
                msg_id=msg_id,
            )
            return

        try:
            from modules.config import XXAPI_KEY
        except ImportError:
            XXAPI_KEY = ""

        headers = {"User-Agent": "xiaoxiaoapi/1.0.0 (https://xxapi.cn)"}
        if XXAPI_KEY:
            headers["Authorization"] = "Bearer %s" % XXAPI_KEY

        try:
            data = await http_get(
                _WORD_API,
                params={"word": word},
                headers=headers,
                timeout=10,
            )
        except Exception as e:
            logger.error("单词详解请求异常: %s" % e)
            data = {}

        if not data or data.get("code") != 200:
            await send_text(
                api, scene, group_openid,
                "单词详解查询失败，请稍后重试",
                msg_id=msg_id,
            )
            return

        d = data.get("data", {}) or {}
        if not d.get("word"):
            await send_text(
                api, scene, group_openid,
                "未找到单词「%s」的释义，请检查拼写" % word,
                msg_id=msg_id,
            )
            return

        word_name = d.get("word", word)
        book = d.get("bookId", "")
        uk = d.get("ukphone", "")
        us = d.get("usphone", "")
        uks = d.get("ukspeech", "")
        uss = d.get("usspeech", "")

        lines = ["🔤 %s · 单词详解" % word_name, "━━━━━━━━━━"]
        if book:
            lines.append("📚 词库：%s" % book)
        if uk or us:
            lines.append("🔊 英 [%s]   美 [%s]" % (uk, us))

        trans = d.get("translations", []) or []
        if trans:
            lines.append("🗣 释义：")
            for t in trans:
                lines.append("  %s. %s" % (t.get("pos", ""), t.get("tran_cn", "")))

        phrases = d.get("phrases", []) or []
        if phrases:
            lines.append("📖 常见短语：")
            for p in phrases[:8]:
                lines.append("  %s  %s" % (p.get("p_content", ""), p.get("p_cn", "")))
            if len(phrases) > 8:
                lines.append("  …共 %d 条" % len(phrases))

        rel = d.get("relWords", []) or []
        if rel:
            lines.append("🌱 同根词：")
            for grp in rel[:8]:
                pos = grp.get("Pos", "")
                for h in (grp.get("Hwds", []) or []):
                    lines.append("  %s. %s  %s" % (pos, h.get("hwd", ""), (h.get("tran", "") or "").strip()))

        syns = d.get("synonyms", []) or []
        if syns:
            lines.append("🔁 近义词：")
            for s in syns[:6]:
                sw = ", ".join(w.get("word", "") for w in (s.get("Hwds", []) or []))
                lines.append("  %s. %s（%s）" % (s.get("pos", ""), s.get("tran", ""), sw))

        sents = d.get("sentences", []) or []
        if sents:
            lines.append("💡 例句：")
            for se in sents[:4]:
                lines.append("  %s" % se.get("s_content", ""))
                lines.append("  ↳ %s" % se.get("s_cn", ""))

        if uks or uss:
            lines.append("🎧 发音音频：")
            if uks:
                lines.append("  英音：%s" % uks)
            if uss:
                lines.append("  美音：%s" % uss)

        await send_text(api, scene, group_openid, chr(10).join(lines), msg_id=msg_id)

    # ================================================================
    #                  王者荣耀信息查询（小渡API）
    # ================================================================
    WZRY_HERO_CACHE = "wzry_heros.json"     # 英雄列表缓存（24h）
    _WZRY_SOURCE = "https://api.wzryqz.cn"  # 备用数据源（小渡接口异常时降级，二者同源）
    _WZRY_PLAT_LABELS = {
        "aqq": "安卓QQ", "awx": "安卓微信",
        "iqq": "苹果QQ", "iwx": "苹果微信",
    }

    def _xd_wangzhe_sync(self, hero, ckey):
        """调用小渡API查询王者荣耀战力（优先数据源）。

        接口: https://openapi.dwo.cc/api/wzry?msg=<英雄名>&ckey=<key>
        返回结构理论上与 wzryqz 一致（android_qq/apple_qq/... 含
        Top10/Top100/province/city/county 等字段）。
        成功返回 {平台码: data}，否则返回 None。
        """
        import urllib.request
        import urllib.parse
        import json as _json
        url = "https://openapi.dwo.cc/api/wzry?msg=%s" % urllib.parse.quote(hero)
        if ckey:
            url += "&ckey=" + urllib.parse.quote(ckey)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA_PC})
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode("utf-8", "ignore")
            data = _json.loads(raw)
        except Exception as e:
            logger.warning("[王者] 小渡API调用失败: %s" % e)
            return None
        if not isinstance(data, dict):
            return None
        # 映射小渡平台键 -> 标准平台码
        keymap = {
            "android_qq": "aqq", "android_vx": "awx",
            "apple_qq": "iqq", "apple_vx": "iwx",
        }
        out = {}
        for k, v in data.items():
            code = keymap.get(k, k)
            if isinstance(v, dict) and "error" not in v and ("Top10" in v or "name" in v):
                out[code] = v
        return out if out else None

    def _xd_wzdata_sync(self, hero_cname, ckey):
        """调用小渡API查询英雄语言/图像信息。

        接口: https://openapi.dwo.cc/api/wzdata?name=<英雄名>&key=<key>
        返回: {
            "name", "title", "role", "region", "spell", "background",
            "avatar_small": "头像图URL",
            "lines": "语音台词文本",
            "voice": "语音音频URL"
        }
        其中 lines/voice 可能为空或不存在（接口文档示例有，实际视英雄而定）。
        成功返回 dict，否则返回 None。
        """
        import urllib.request
        import urllib.parse
        import json as _json
        if not hero_cname:
            return None
        url = "https://openapi.dwo.cc/api/wzdata?name=%s" % urllib.parse.quote(hero_cname)
        if ckey:
            url += "&key=" + urllib.parse.quote(ckey)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA_PC})
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode("utf-8", "ignore")
            data = _json.loads(raw)
            if isinstance(data, dict) and data.get("code") == 200:
                return data.get("data")
        except Exception as e:
            logger.warning("[王者] wzdata调用失败: %s" % e)
        return None

    def _wzry_hero_list_sync(self):
        """获取英雄列表（带24h缓存）。返回 list[dict]."""
        import json as _json
        import os
        import time
        from modules.config import DATA_DIR
        cache_path = os.path.join(DATA_DIR, self.WZRY_HERO_CACHE)
        try:
            if os.path.exists(cache_path):
                age = time.time() - os.path.getmtime(cache_path)
                if age < 86400:
                    with open(cache_path, "r", encoding="utf-8") as f:
                        cached = _json.load(f)
                    if isinstance(cached, list) and cached:
                        return cached
        except Exception:
            pass
        try:
            import urllib.request
            req = urllib.request.Request(
                self._WZRY_SOURCE + "/getheros",
                headers={"User-Agent": _UA_PC})
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode("utf-8", "ignore")
            heros = _json.loads(raw)
            if isinstance(heros, list) and heros:
                try:
                    with open(cache_path, "w", encoding="utf-8") as f:
                        _json.dump(heros, f, ensure_ascii=False)
                except Exception:
                    pass
                return heros
        except Exception as e:
            logger.warning("[王者] 英雄列表获取失败: %s" % e)
        return []

    def _wzry_gethero_sync(self, hero_cname, platform):
        """查询单个平台战力数据。返回 dict 或 None。"""
        import urllib.request
        import urllib.parse
        import json as _json
        url = "%s/gethero?hero=%s&platform=%s" % (
            self._WZRY_SOURCE, urllib.parse.quote(hero_cname), platform)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA_PC})
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode("utf-8", "ignore")
            d = _json.loads(raw)
            if isinstance(d, dict) and d.get("code") == 200:
                return d.get("data")
        except Exception as e:
            logger.warning("[王者] 平台%s查询失败: %s" % (platform, e))
        return None

    @staticmethod
    def _resolve_hero(name, heros):
        """模糊匹配英雄：cname > title > id_name > 包含匹配。"""
        name = (name or "").strip()
        if not name:
            return None
        for h in heros:
            if h.get("cname") == name:
                return h
        for h in heros:
            if h.get("title") == name:
                return h
        for h in heros:
            if (h.get("id_name") or "").lower() == name.lower():
                return h
        for h in heros:
            cn = h.get("cname", "")
            if name in cn or cn in name:
                return h
        for h in heros:
            if name in (h.get("title") or ""):
                return h
        return None

    @staticmethod
    def _lowest(regions):
        """取战力门槛最低的地区。regions: [{loc,val}]。"""
        if not isinstance(regions, list) or not regions:
            return None
        best = None
        for r in regions:
            try:
                val = int(r.get("val", 0))
            except Exception:
                continue
            loc = r.get("loc", "")
            if best is None or val < best[1]:
                best = (loc, val)
        return best

    @staticmethod
    def _extract_power(data):
        """从平台数据中提取战力门槛。返回 dict 或 None。"""
        if not isinstance(data, dict):
            return None
        top10 = data.get("Top10")
        top100 = data.get("Top100")
        if top10 is None and top100 is None:
            return None
        return {
            "top10": top10, "top100": top100,
            "province": ToolsManager._lowest(data.get("province")),
            "city": ToolsManager._lowest(data.get("city")),
            "county": ToolsManager._lowest(data.get("county")),
            "updatetime": data.get("updatetime", ""),
            "photo": data.get("photo", ""),
            "hero_type": data.get("hero_type", ""),
        }

    async def _query_wangzhe(self, api, arg, group_openid, msg_id, scene=None):
        """王者荣耀信息查询（小渡API 优先，异常降级到备用源）"""
        import asyncio
        if scene is None:
            scene = ChatScene.GROUP
        parts = (arg or "").split()
        hero_q = parts[0] if parts else ""
        plat_kw = parts[1] if len(parts) > 1 else ""

        if not hero_q:
            await send_text(
                api, scene, group_openid,
                "🎮 王者信息\n━━━━━━━━━━\n"
                "用法：王者 英雄名\n"
                "示例：王者 后羿\n"
                "指定平台：王者 后羿 微信 / 安卓 / ios\n"
                "不指定则查询全部4个平台战力",
                msg_id=msg_id,
            )
            return

        # 平台筛选
        if plat_kw:
            kw = plat_kw.lower()
            if "微信" in plat_kw or "wx" in kw:
                plats = [("awx", "安卓微信"), ("iwx", "苹果微信")]
            elif "ios" in kw or "苹果" in plat_kw or "iphone" in kw:
                plats = [("iqq", "苹果QQ"), ("iwx", "苹果微信")]
            elif "qq" in kw:
                plats = [("aqq", "安卓QQ"), ("iqq", "苹果QQ")]
            elif "安卓" in plat_kw or "az" in kw or "android" in kw:
                plats = [("aqq", "安卓QQ"), ("awx", "安卓微信")]
            else:
                plats = [("aqq", "安卓QQ"), ("awx", "安卓微信"),
                         ("iqq", "苹果QQ"), ("iwx", "苹果微信")]
        else:
            plats = [("aqq", "安卓QQ"), ("awx", "安卓微信"),
                     ("iqq", "苹果QQ"), ("iwx", "苹果微信")]

        # 1) 尝试小渡API（优先）
        try:
            from modules.config import QQ_INFO_KEY
        except ImportError:
            QQ_INFO_KEY = ""
        xd = await asyncio.to_thread(self._xd_wangzhe_sync, hero_q, QQ_INFO_KEY)
        xd_valid = isinstance(xd, dict) and bool(xd)
        source = "小渡API" if xd_valid else "小渡API(暂不可用，已切换备用源)"

        # 2) 解析英雄（用于称号/皮肤/图片；始终解析，英雄列表有24h缓存开销极低）
        heros = await asyncio.to_thread(self._wzry_hero_list_sync)
        matched = self._resolve_hero(hero_q, heros)
        qname = matched.get("cname") if matched else hero_q

        # 3) 获取英雄语言/图像信息（小渡 wzdata）
        wzdata = await asyncio.to_thread(self._xd_wzdata_sync, qname, QQ_INFO_KEY)

        # 4) 获取各平台战力
        if xd_valid:
            power = {}
            for code, _ in plats:
                d = xd.get(code)
                if d:
                    power[code] = self._extract_power(d)
        else:
            tasks = [asyncio.to_thread(self._wzry_gethero_sync, qname, code)
                     for code, _ in plats]
            results = await asyncio.gather(*tasks)
            power = {}
            for (code, _), d in zip(plats, results):
                if d:
                    power[code] = self._extract_power(d)

        # 仅保留有数据的平台
        power = {k: v for k, v in power.items() if v}
        if not power:
            await send_text(
                api, scene, group_openid,
                "🎮 王者信息\n未找到「%s」的战力数据。\n请检查英雄名是否正确（如：王者 后羿）。\n可用英雄示例：李白、鲁班七号、妲己、赵云。" % hero_q,
                msg_id=msg_id,
            )
            return

        # 5) 组装消息
        if matched:
            title = matched.get("title", "")
            skins = [s for s in (matched.get("skin_name") or "").split("|") if s]
            htype = matched.get("hero_type", "")
            base = "🦸 %s（%s）\n🏷 称号：%s\n🌟 皮肤：%d款" % (
                matched.get("cname", ""), htype, title, len(skins))
            photo = ""
        else:
            base = "🦸 %s" % hero_q
            photo = ""
            for v in power.values():
                if v.get("photo"):
                    photo = v["photo"]
                    break

        # 优先使用 wzdata 的头像，其次备用源 photo
        avatar = ""
        if isinstance(wzdata, dict):
            avatar = wzdata.get("avatar_small") or ""
        if not avatar and photo:
            avatar = photo

        lines = ["🎮 王者荣耀 · 英雄信息", "━━━━━━━━━━", base]

        # 地区/背景/语音（wzdata 提供时展示）
        if isinstance(wzdata, dict):
            region = wzdata.get("region", "")
            background = wzdata.get("background", "")
            voice_text = wzdata.get("lines", "")
            voice_url = wzdata.get("voice", "")
            if region:
                lines.append("🗺 区域：%s" % region)
            if background:
                lines.append("📜 背景：%s" % background)
            if voice_text:
                lines.append("🗣 台词：%s" % voice_text)
            if voice_url:
                lines.append("🔊 语音：%s" % voice_url)
        elif photo:
            lines.append("🔗 资料图：%s" % photo)
        lines.append("")

        for code, label in plats:
            p = power.get(code)
            if not p:
                continue
            lines.append("📊 战力门槛（%s）" % label)
            if p.get("top10") is not None:
                lines.append("🥇 国标Top10：%s" % p["top10"])
            if p.get("top100") is not None:
                lines.append("🥈 国标Top100：%s" % p["top100"])
            if p.get("province"):
                lines.append("🏆 省标最低：%s %s" % (p["province"][0], p["province"][1]))
            if p.get("city"):
                lines.append("🏙 市标最低：%s %s" % (p["city"][0], p["city"][1]))
            if p.get("county"):
                lines.append("📍 县标最低：%s %s" % (p["county"][0], p["county"][1]))
            if p.get("updatetime"):
                lines.append("🕐 更新：%s" % p["updatetime"])
            lines.append("")

        msg = "\n".join(lines)

        # 头像与战力信息合并为同一条消息发送（图文消息携带文本 content）
        if avatar:
            try:
                result = await send_image_for_scene(
                    api, scene, group_openid, avatar,
                    msg_id=msg_id,
                    content=msg,
                )
                if result is not None:
                    return
                logger.warning("[王者] 头像图片发送失败，降级为纯文本（%s）" % avatar)
            except Exception as e:
                logger.error("[王者] 头像图片发送异常，降级为纯文本: %s" % e)
        # 无头像 或 图片发送失败时，发送纯文本
        await send_text(api, scene, group_openid, msg, msg_id=msg_id)

    # ================================================================
    #                       命令处理入口
    # ================================================================

    async def handle_command(self, api, content, group_openid, member_openid, msg_id, scene=None):
        """
        处理工具系统命令，返回 True 表示已处理

        兼容性说明：
        - scene: "group" / "c2c" / "channel"（推荐传入，未传入时按 GROUP 处理）
        - group_openid: target_id（裸 ID，不带前缀；与各模块存储 key 保持一致）
        """
        # 兜底：如果没传 scene，按 GROUP 处理
        if scene is None:
            scene = ChatScene.GROUP
        text = content.strip()

        # ========== 天气查询 ==========
        if text == "天气":
            await send_text(
                api, scene, group_openid,
                "🌤 天气查询\n"
                "━━━━━━━━━━\n"
                "用法：天气 城市名\n"
                "示例：天气 南昌\n"
                "支持省/市/区，如：天气 杭州西湖区",
                msg_id=msg_id,
            )
            return True

        if text.startswith("天气 ") or text.startswith("天气\u3000"):
            city = text[2:].strip()
            if city:
                await self._query_weather(api, city, group_openid, msg_id, scene)
                return True

        # ========== 王者荣耀信息查询 ==========
        if text == "王者" or text == "王者信息":
            await send_text(
                api, scene, group_openid,
                "🎮 王者信息\n━━━━━━━━━━\n"
                "用法：王者 英雄名\n"
                "示例：王者 后羿\n"
                "指定平台：王者 后羿 微信 / 安卓 / ios\n"
                "不指定则查询全部4个平台战力\n"
                "结果包含：头像、区域、背景、台词、语音、战力门槛",
                msg_id=msg_id,
            )
            return True

        if text.startswith("王者 ") or text.startswith("王者\u3000"):
            arg = text[2:].strip()
            await self._query_wangzhe(api, arg, group_openid, msg_id, scene)
            return True

        # ========== 单词详解查询（小小API） ==========
        if text == "单词" or text == "单词查询" or text == "查词":
            await send_text(
                api, scene, group_openid,
                """🔤 单词详解
━━━━━━━━━━
用法：单词 英文单词
示例：单词 cancel / 单词 beautiful""",
                msg_id=msg_id,
            )
            return True

        if text.startswith("单词 "):
            w = text[2:].strip()
            if w:
                await self._query_word(api, w, group_openid, msg_id, scene)
                return True
            await send_text(
                api, scene, group_openid,
                """🔤 单词详解
━━━━━━━━━━
请输入要查询的英文单词，例如：
单词 cancel""",
                msg_id=msg_id,
            )
            return True

        # ========== 常见疾病信息查询（小小API） ==========
        if text == '\u75be\u75c5\u4fe1\u606f':
            await self._disease_start(api, group_openid, member_openid, scene=scene, msg_id=msg_id)
            return True

        if text.startswith('\u75be\u75c5\u4fe1\u606f ') or text.startswith('\u75be\u75c5\u4fe1\u606f\u3000'):
            rest = text[4:].strip()
            # 子命令：复制 <病名> → 发纯文本版（手机长按复制用）
            if rest.startswith('\u590d\u5236 '):
                word = rest[2:].strip()
                if word:
                    await self._disease_show_copy(api, group_openid, msg_id, word, scene)
                    return True
            # 通用疾病查询
            if rest:
                await self.disease_info(api, group_openid, member_openid, msg_id, rest, scene)
                return True
            await send_text(
                api, scene, group_openid,
                '\U0001F3E5 \u75be\u75c5\u4fe1\u606f\n' + _BOX_LINE + '\n\u8bf7\u8f93\u5165\u8981\u67e5\u8be2\u7684\u75be\u75c5\u540d\uff0c\u4f8b\u5982\uff1a\n\u75be\u75c5\u4fe1\u606f \u611f\u5192',
                msg_id=msg_id,
            )
            return True

        # ========== 垃圾分类查询（OIAPI WasteSorting） ==========
        if text == "垃圾分类":
            await self._waste_start(api, group_openid, member_openid, scene=scene, msg_id=msg_id)
            return True

        if text.startswith("垃圾分类 ") or text.startswith("垃圾分类　"):
            rest = text[4:].strip()
            if rest:
                # 直接传参模式：调用后不进等待态，但查询内部会处理多候选场景
                await self._waste_query(api, rest, group_openid, member_openid, msg_id, scene)
                return True
            await send_text(
                api, scene, group_openid,
                "🗑️ 垃圾分类\n" + _BOX_LINE + "\n请输入要查询的垃圾名称，例如：\n垃圾分类 电池",
                msg_id=msg_id,
            )
            return True

        # ========== 显式命令 ==========
        # 点击「视频解析」按钮后，直接进入等待状态并提示用户 @机器人 发送视频链接
        # （不再展示多余的"开始视频解析"二级按钮，缩短操作路径）
        if text == "视频解析":
            await self._video_parse_start(api, group_openid, member_openid, scene=scene, msg_id=msg_id)
            return True

        # ========== 视频解析等待状态 ==========
        # key 兼容：写入和读取都用裸 ID（与历史数据保持一致）
        video_states = load_json(VIDEO_PARSE_STATE_FILE)
        video_key = self._state_key(group_openid, member_openid)
        if video_key in video_states and video_states[video_key].get("waiting"):
            if text == "取消":
                del video_states[video_key]
                save_json(VIDEO_PARSE_STATE_FILE, video_states)
                await send_text(api, scene, group_openid, "已取消视频解析", msg_id=msg_id)
                return True
            # 从消息中提取 URL（支持抖音/B站��整分享文本）
            url = self._extract_video_url(text)
            if url:
                # 校验是否为支持的平台
                if self._detect_platform(url) == "未知平台":
                    await send_text(
                        api, scene, group_openid,
                        "暂不支持该链接，目前支持抖音/快手/B站/小红书/视频号/油管/TikTok等20+平台\n发送「取消」可取消解析",
                        msg_id=msg_id,
                    )
                    return True
                await self._video_parse_query(api, url, group_openid, member_openid, msg_id, scene)
                return True
            else:
                await send_text(
                    api, scene, group_openid,
                    "未识别到视频链接，请发送抖音/快手/B站/小红书等平台的分享链接\n发送「取消」可取消解析",
                    msg_id=msg_id,
                )
                return True

        # ========== 疾病信息等待状态 ==========
        disease_states = load_json(DISEASE_STATE_FILE)
        disease_key = self._state_key(group_openid, member_openid)
        if disease_states.get(disease_key, {}).get("waiting"):
            if text == "取消":
                self._disease_clear_waiting(group_openid, member_openid)
                await send_text(api, scene, group_openid, "已退出疾病信息查询", msg_id=msg_id)
                return True
            if text == "返回主菜单":
                # 清除等待态后交给 bot.py 主菜单导航（不在此 return）
                self._disease_clear_waiting(group_openid, member_openid)
            else:
                word = text.strip()
                if word:
                    await self.disease_info(api, group_openid, member_openid, msg_id, word, scene)
                    return True
                await send_text(
                    api, scene, group_openid,
                    "\U0001F3E5 请发送要查询的疾病名称，或点击上方常用疾病按钮\n发送「取消」可退出",
                    msg_id=msg_id,
                )
                return True

        # ========== 垃圾分类等待状态 ==========
        waste_states = load_json(WASTE_STATE_FILE)
        waste_key = self._state_key(group_openid, member_openid)
        if waste_states.get(waste_key, {}).get("waiting"):
            if text == "取消":
                self._waste_clear_waiting(group_openid, member_openid)
                await send_text(api, scene, group_openid, "已退出垃圾分类查询", msg_id=msg_id)
                return True
            if text == "返回主菜单":
                # 清除等待态后交给 bot.py 主菜单导航（不在此 return）
                self._waste_clear_waiting(group_openid, member_openid)
            else:
                # 纯数字 → 选上一轮列表第 N 个
                if text.isdigit():
                    await self._waste_pick(api, int(text), group_openid, member_openid, msg_id, scene)
                    return True
                # 含中文等有意义文本 → 当作新垃圾名查询
                word = text.strip()
                if word:
                    await self._waste_query(api, word, group_openid, member_openid, msg_id, scene)
                    return True
                await send_text(
                    api, scene, group_openid,
                    "🗑️ 请发送要查询的垃圾名称，或点击上方常用垃圾按钮\n发送「取消」可退出",
                    msg_id=msg_id,
                )
                return True

        return False

    async def handle_callback(self, api, data, target_id, member_openid, scene=None,
                              msg_id=None, event_id=None):
        """
        处理回调按钮点击事件，返回 True 表示已处理
        需要在 bot.py 的 on_interaction_create 中调用此方法

        - target_id: target_id（裸 ID；老调用可能传 chat_id，内部会兼容）
        - member_openid: 点击按钮的用户 openid
        - scene: ChatScene.GROUP / C2C / CHANNEL（未传则按 GROUP 处理）
        - event_id: 互动事件ID（用于被动回复）
        """
        if data == "video_parse_start":
            # 历史保留：旧版"开始视频解析"二级按钮点击（现已由「视频解析」按钮直接进入）
            await self._video_parse_start(
                api, target_id, member_openid,
                scene=scene, msg_id=msg_id, event_id=event_id
            )
            return True

        return False
