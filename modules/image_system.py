# -*- coding: utf-8 -*-
"""
图片系统模块
基于小小API 多个端点，随机返回高清图片：
- 二次元（acg）：精致二次元插画
- 风景（wallpaper）：震撼风景壁纸
- 随机壁纸（wallpaper，独立端点）
- 原神cos（yscos）：原神cosplay 图片
- 原神（ys）：原神游戏图
- 小姐姐（meinvpic）：高清美图

鉴权：小小API 支持无 Key 调用；填写 RANDOMPIC_API_KEY（=小小API统一密钥）可提高稳定性与额度，
以 Authorization: Bearer <key> 头携带。
"""

import asyncio
import random
import re as _re
import aiohttp
from modules.common import (
    ChatScene,
    send_text,
    send_text_with_keyboard,
    send_image_for_scene,
    build_keyboard_multi,
    clean_content,
    logger,
    http_get,
    http_get_with_redirect,
)
from modules.config import (
    RANDOMPIC_API_URL, RANDOMPIC_API_KEY,
    RANDOMBIZHI_API_URL,
    GENSHIN_API_URL, GENSHINCOS_API_URL,
    MEINVPIC_API_URL, MEINVPIC_API_KEY,
)

# 图片分类（顺序即按钮展示顺序）
IMAGE_CATEGORIES = ["二次元", "风景", "随机壁纸", "原神cos", "原神", "小姐姐"]

# 分类 → 小小API 接口配置（每个分类可指向不同端点 + 独立参数）
# 二次元 / 风景 共享 random4kPic（type 不同）；其余 4 类各自使用独立端点。
IMAGE_API_CONFIG = {
    "二次元":   {"url": RANDOMPIC_API_URL,    "params": {"type": "acg"}},
    "风景":     {"url": RANDOMPIC_API_URL,    "params": {"type": "wallpaper"}},
    "随机壁纸": {"url": RANDOMBIZHI_API_URL,  "params": {}},
    "原神cos":  {"url": GENSHINCOS_API_URL,   "params": {}},
    "原神":     {"url": GENSHIN_API_URL,      "params": {}},
    "小姐姐":   {"url": MEINVPIC_API_URL,     "params": {}},
}

# 请求头：携带小小API密钥（Authorization Bearer，复用同一密钥）
_REQ_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Authorization": "Bearer %s" % RANDOMPIC_API_KEY,
}

# ============ 随机图片（photo.likefirefly.com，免鉴权）============
# 接口：GET /api?list → JSON（all_count / text / data[]），每条 {name, count, url, urlcode}
#       GET /api?type=<name> → 302 跳到 QQ 群相册直链（qungz.photo.store.qq.com）
# 注意：referer 设置为 https://qq.com 以避免防盗链拦截；图片不在本地缓存。
PHOTO_API_BASE = "https://photo.likefirefly.com/api"
PHOTO_LIST_URL = PHOTO_API_BASE + "?list"
_PHOTO_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://qq.com",
}
PHOTO_TIMEOUT = 8            # 列表接口超时
PHOTO_IMAGE_TIMEOUT = 12     # 图片 URL 解析超时（含 302 跟随）
PHOTO_MENU_TOP_N = 9         # 菜单展示前 N 个分类（按 count 降序），3/行手工分排
PHOTO_CACHE_EMPTY_TS = 0.0   # 上次失败时间戳（用于节流重试，避免每个请求都打远端）


def _safe_id(name: str) -> str:
    """把分类名转成安全的按钮 ID（去除非 ASCII 安全字符，截断到 24 字符）。"""
    if not name:
        return "x"
    s = _re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not s:
        s = _re.sub(r"\s+", "_", name)[:24]
    return s[:24] or "x"


class ImageManager:
    """图片系统 - 随机4K图片（二次元 / 风景）"""

    def __init__(self):
        self.categories = list(IMAGE_CATEGORIES)
        # 随机图片分类缓存（[{name, count, url, urlcode}, ...]），启动后异步预热
        self.photo_categories = []
        self._photo_lock = asyncio.Lock()
        self._photo_last_fail_ts = 0.0

    # ============================================================
    # 拉取图片地址
    # ============================================================

    async def _fetch_image_url(self, category: str):
        """
        向对应小小API接口请求一张随机图片地址（按分类映射到独立端点/参数）。
        返回图片直链字符串，或 None（失败/无图）。
        """
        cfg = IMAGE_API_CONFIG.get(category)
        if not cfg:
            return None
        params = dict(cfg.get("params") or {})
        # 默认带 return=json（两个接口都支持；不强制也能返回 JSON，但显式更稳）
        params.setdefault("return", "json")
        try:
            data = await http_get(cfg["url"], params=params,
                                  headers=_REQ_HEADERS, timeout=10)
        except Exception as e:
            logger.error("图片接口请求异常[%s]: %s" % (category, e))
            return None
        if not isinstance(data, dict) or data.get("code") != 200:
            code = data.get("code") if isinstance(data, dict) else "None"
            msg = data.get("msg", "") if isinstance(data, dict) else ""
            logger.warning("图片接口返回异常[%s]: code=%s msg=%s" % (category, code, msg))
            return None
        url = data.get("data")
        if not isinstance(url, str) or not url.startswith("http"):
            logger.warning("图片接口未返回有效图片地址[%s]: %r" % (category, url))
            return None
        return url

    # ============================================================
    # 按钮构建（发送图片后附带"看其他类型"）
    # ============================================================

    def build_category_buttons(self, exclude: str = None) -> dict:
        """构建其他图片分类的快捷按钮（排除当前分类，单行展示）"""
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
    # 发送图片
    # ============================================================

    async def send_image(self, api, category: str, target_id: str,
                         msg_id: str = None, scene: str = ChatScene.GROUP):
        """发送指定分类的随机4K图片，并在下方附带其他分类按钮（群聊/私聊通用）"""
        if category not in self.categories:
            return False
        scene = scene or ChatScene.GROUP

        await send_text(
            api, scene, target_id,
            "🖼️ 正在为你寻找一张随机【%s】图片，请稍候..." % category,
            msg_id=msg_id,
        )

        url = await self._fetch_image_url(category)
        if not url:
            await send_text(
                api, scene, target_id,
                "😢 暂时没有找到【%s】图片，请稍后再试～" % category,
                msg_id=msg_id,
            )
            return True

        keyboard = self.build_category_buttons(exclude=category)
        result = await send_image_for_scene(
            api, scene, target_id, url,
            msg_id=msg_id, content="🖼️ %s" % category,
        )
        if result:
            await send_text_with_keyboard(
                api, scene, target_id, "还想看其他类型？👇", keyboard, msg_id=msg_id
            )
            logger.info("图片发送成功[%s/%s]: %s" % (scene, category, url))
            return True

        await send_text(
            api, scene, target_id,
            "😢 图片发送失败了，请稍后再试～",
            msg_id=msg_id,
        )
        logger.warning("图片发送失败(上传QQ失败)[%s]: %s" % (scene, category))
        return True

    # ============================================================
    # 随机图片（photo.likefirefly.com）
    # ============================================================

    async def _photo_fetch_categories(self, force: bool = False):
        """拉取分类列表，结果写入 self.photo_categories。

        - 失败时静默返回（不抛异常），并记录 30s 节流，避免每个请求都打远端。
        - force=True 强制刷新（用于菜单请求时确保拿到最新分类）。
        返回写入后的列表（失败时返回当前缓存，可能为空）。
        """
        import time as _t
        async with self._photo_lock:
            now = _t.time()
            # 有缓存且非强制刷新，且最近没失败 → 直接返回
            if not force and self.photo_categories:
                return self.photo_categories
            # 失败节流：30s 内不重试
            if not force and (now - self._photo_last_fail_ts) < 30:
                return self.photo_categories
            try:
                data = await http_get(
                    PHOTO_LIST_URL, params=None,
                    headers=_PHOTO_HEADERS, timeout=PHOTO_TIMEOUT,
                )
            except Exception as e:
                logger.warning("[photo] 分类列表请求异常: %s" % e)
                self._photo_last_fail_ts = now
                return self.photo_categories
            if not isinstance(data, dict):
                logger.warning("[photo] 分类列表返回非 dict: %r" % type(data))
                self._photo_last_fail_ts = now
                return self.photo_categories
            items = data.get("data")
            if not isinstance(items, list):
                logger.warning("[photo] 分类列表 data 字段非 list")
                self._photo_last_fail_ts = now
                return self.photo_categories
            cats = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                name = it.get("name")
                count = it.get("count")
                url = it.get("urlcode") or it.get("url") or ""
                if not isinstance(name, str) or not name or not url:
                    continue
                try:
                    cnt = int(count) if count is not None else 0
                except Exception:
                    cnt = 0
                cats.append({"name": name, "count": cnt, "urlcode": url})
            # 按图片数量降序
            cats.sort(key=lambda x: x.get("count", 0), reverse=True)
            self.photo_categories = cats
            logger.info("[photo] 分类缓存已刷新: %d 个分类" % len(cats))
            return self.photo_categories

    async def _photo_fetch_random_image_url(self, category: dict):
        """根据分类 dict（必须含 urlcode/name）请求一张随机图片，返回最终直链或 None。

        远端 /api?type=<name> 会 302 跳到 QQ 群相册直链。本方法直接用 aiohttp 跟随重定向
        并只取最终 URL（不读取 body），避免对二进制/空响应触发 UnicodeDecodeError。
        """
        url = category.get("urlcode") or category.get("url") or ""
        if not url:
            return None
        try:
            timeout = aiohttp.ClientTimeout(total=PHOTO_IMAGE_TIMEOUT)
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers=_PHOTO_HEADERS,
                    timeout=timeout, allow_redirects=True,
                ) as resp:
                    final = str(resp.url)
                    # aiohttp 已跟随重定向；final 即为最终直链
                    if 200 <= resp.status < 400 and final.startswith("http"):
                        return final
                    logger.warning("[photo] 图片返回异常[%s]: status=%s url=%s" %
                                    (category.get("name"), resp.status, final[:80]))
                    return None
        except Exception as e:
            logger.warning("[photo] 图片请求异常[%s]: %s" % (category.get("name"), e))
            return None

    def _photo_match_category(self, keyword: str):
        """按关键字在缓存中做子串模糊匹配，返回单个分类 dict 或 None。

        优先级：精确匹配 > 子串包含（按 count 降序取首个）。空关键字返回 None。
        """
        if not keyword:
            return None
        kw = keyword.strip().lower()
        if not kw:
            return None
        cats = self.photo_categories or []
        # 精确匹配（忽略大小写）
        for c in cats:
            if c["name"].lower() == kw:
                return c
        # 子串匹配（先按 name 长度升序，长名字短关键字误命中概率低）
        subs = [c for c in cats if kw in c["name"].lower()]
        if subs:
            subs.sort(key=lambda x: (len(x["name"]), -x.get("count", 0)))
            return subs[0]
        return None

    async def prewarm_photo(self):
        """启动时预热分类缓存（fire-and-forget，失败不影响主流程）。

        在 bot 的 on_ready 里调用一次；失败时下次菜单请求会 lazy 重试。
        """
        try:
            await self._photo_fetch_categories(force=True)
        except Exception as e:
            logger.debug("[photo] 预热失败（忽略）: %s" % e)

    def _photo_build_menu_keyboard(self, cats):
        """手工分排分类菜单键盘：前 PHOTO_MENU_TOP_N 个分类 3/行 + 全部随机 + 返回。

        cats: 分类列表（已按 count 降序）。为空时只显示「全部随机 / 返回」。
        """
        rows = []
        top = cats[:PHOTO_MENU_TOP_N]
        # 按 3 个一行分排
        for i in range(0, len(top), 3):
            chunk = top[i:i + 3]
            rows.append({"buttons": [
                {
                    "id": "btn_photo_" + _safe_id(c["name"]),
                    "render_data": {
                        "label": "◆ " + c["name"],
                        "visited_label": "◆ " + c["name"],
                        "style": 1,
                    },
                    "action": {
                        "type": 2,
                        "permission": {"type": 2},
                        "data": "角色图库 " + c["name"],
                        "enter": True,
                        "unsupport_tips": "请更新QQ版本",
                    },
                } for c in chunk
            ]})
        # 「全部随机」+「返回图片菜单」
        rows.append({"buttons": [
            {
                "id": "btn_photo_random_all",
                "render_data": {"label": "✦ 全部随机", "visited_label": "✦ 全部随机", "style": 1},
                "action": {
                    "type": 2, "permission": {"type": 2},
                    "data": "随机图片 全部", "enter": True,
                    "unsupport_tips": "请更新QQ版本",
                },
            },
            {
                "id": "btn_photo_back",
                "render_data": {"label": "← 返回菜单", "visited_label": "← 返回菜单", "style": 1},
                "action": {
                    "type": 2, "permission": {"type": 2},
                    "data": "图片菜单", "enter": True,
                    "unsupport_tips": "请更新QQ版本",
                },
            },
        ]})
        return {"content": {"rows": rows}}

    async def send_random_photo(self, api, target_id, msg_id,
                                category=None, scene=None):
        """发送一张随机图片。

        - category=None：从缓存随机挑一个分类；
        - category=dict：使用指定分类。
        失败时返回 False，由调用方提示用户。
        """
        scene = scene or ChatScene.GROUP
        cats = self.photo_categories or []
        if not cats:
            cats = await self._photo_fetch_categories(force=True)
        if not cats:
            await send_text(api, scene, target_id,
                            "😢 暂时拿不到图片分类列表，请稍后再试～", msg_id=msg_id)
            return False
        if category is None:
            category = random.choice(cats)
        label = category.get("name") or "未知"
        await send_text(api, scene, target_id,
                        "🎲 正在为你寻找【%s】角色图库图片，请稍候..." % label,
                        msg_id=msg_id)
        url = await self._photo_fetch_random_image_url(category)
        if not url:
            await send_text(api, scene, target_id,
                            "😢 这张图暂时拿不到，换个分类试试？", msg_id=msg_id)
            return True
        # 附带「再来一张 / 全部随机 / 返回菜单」按钮
        keyboard = {
            "content": {"rows": [
                {"buttons": [
                    {
                        "id": "btn_photo_re_" + _safe_id(label),
                        "render_data": {"label": "◆ 再来一张", "visited_label": "◆ 再来一张", "style": 1},
                        "action": {
                            "type": 2, "permission": {"type": 2},
                            "data": "角色图库 " + label, "enter": True,
                            "unsupport_tips": "请更新QQ版本",
                        },
                    },
                    {
                        "id": "btn_photo_back2",
                        "render_data": {"label": "✦ 全部随机", "visited_label": "✦ 全部随机", "style": 1},
                        "action": {
                            "type": 2, "permission": {"type": 2},
                            "data": "角色图库 全部", "enter": True,
                            "unsupport_tips": "请更新QQ版本",
                        },
                    },
                    {
                        "id": "btn_photo_back3",
                        "render_data": {"label": "← 返回菜单", "visited_label": "← 返回菜单", "style": 1},
                        "action": {
                            "type": 2, "permission": {"type": 2},
                            "data": "图片菜单", "enter": True,
                            "unsupport_tips": "请更新QQ版本",
                        },
                    },
                ]}
            ]}
        }
        result = await send_image_for_scene(
            api, scene, target_id, url,
            msg_id=msg_id, content="🎲 " + label,
        )
        if result:
            await send_text_with_keyboard(
                api, scene, target_id,
                "还想再看？再来一张 / 全部随机 / 返回菜单 👇",
                keyboard, msg_id=msg_id,
            )
            logger.info("[photo] 图片发送成功[%s/%s]: %s" % (scene, label, url[:80]))
            return True
        await send_text(api, scene, target_id,
                        "😢 图片发送失败了，请稍后再试～", msg_id=msg_id)
        logger.warning("[photo] 图片发送失败(上传QQ)[%s/%s]" % (scene, label))
        return True

    async def send_random_photo_menu(self, api, target_id, msg_id, scene=None):
        """展示「随机图片」分类选择菜单（top N + 全部随机 + 返回）。"""
        scene = scene or ChatScene.GROUP
        cats = await self._photo_fetch_categories(force=True)
        if not cats:
            await send_text(api, scene, target_id,
                            "😢 暂时拿不到图片分类列表，请稍后再试～", msg_id=msg_id)
            return True
        hint = ("🎲 角色图库（流萤专属相册）\n"
                "━━━━━━━━━━━━━━\n"
                "💡 这是按角色名检索的图库，与上方「二次元/原神」通用随机图不同\n"
                "💡 点击分类返回该角色随机一张图；点「全部随机」则全库随机\n"
                "🔍 也可发送「角色图库 关键字」模糊匹配，如「角色图库 流萤」"
                )
        keyboard = self._photo_build_menu_keyboard(cats)
        await send_text_with_keyboard(api, scene, target_id, hint, keyboard, msg_id=msg_id)
        return True

    # ============================================================
    # 命令入口
    # ============================================================

    async def handle_command(self, api, content, target_id, member_openid, msg_id, scene=None):
        """
        处理图片相关命令。
        命令：二次元 / 风景（小小API通用随机图）
        角色图库 [关键字|全部]（photo.likefirefly.com 流萤专属相册，按角色名检索）
        scene: "group" / "c2c" / "channel"
        """
        content = clean_content(content).strip()
        scene = scene or ChatScene.GROUP

        # 运行设置：媒体下载开关（关闭后不再出图）
        try:
            from console_server import get_runtime_setting_effective as _rse
            _dl_enabled = bool(_rse("media.download.enabled", group_id=(target_id if scene == ChatScene.GROUP else None)))
        except Exception:
            _dl_enabled = True
        if not _dl_enabled:
            await send_text(api, scene, target_id, "🚫 当前已关闭「媒体下载」功能（运行设置），暂不能出图～", msg_id=msg_id)
            return True

        # 角色图库（photo.likefirefly.com 流萤专属相册）：新名「角色图库」，
        # 同时保留「随机图片 / 随机图 / 看图」作为旧别名（兼容老习惯）。
        _RANDOM_ALIASES = ("角色图库", "随机图片", "随机图", "看图")
        if content in _RANDOM_ALIASES:
            await self.send_random_photo_menu(api, target_id, msg_id, scene=scene)
            return True
        _prefix_matched = None
        for _p in _RANDOM_ALIASES:
            if content.startswith(_p + " ") or content.startswith(_p + "\u3000"):
                _prefix_matched = _p
                break
        if _prefix_matched:
            keyword = content[len(_prefix_matched):].strip()
            if not keyword or keyword == "全部":
                await self.send_random_photo(api, target_id, msg_id, scene=scene)
                return True
            # 关键字模糊匹配：缓存为空先拉一次
            if not self.photo_categories:
                await self._photo_fetch_categories(force=True)
            cat = self._photo_match_category(keyword)
            if not cat:
                await send_text(
                    api, scene, target_id,
                    "😢 没找到「%s」相关的分类，发送「角色图库」查看分类菜单～" % keyword,
                    msg_id=msg_id,
                )
                return True
            await self.send_random_photo(api, target_id, msg_id, category=cat, scene=scene)
            return True
        if content.startswith("看图 ") or content.startswith("看图\u3000"):
            keyword = content[len("看图"):].strip()
            if keyword:
                if not self.photo_categories:
                    await self._photo_fetch_categories(force=True)
                cat = self._photo_match_category(keyword)
                if cat:
                    await self.send_random_photo(api, target_id, msg_id,
                                                 category=cat, scene=scene)
                    return True
                await send_text(
                    api, scene, target_id,
                    "😢 没找到「%s」相关的分类，发送「角色图库」查看分类菜单～" % keyword,
                    msg_id=msg_id,
                )
                return True

        if content in self.categories:
            await self.send_image(api, content, target_id, msg_id,
                                  scene=scene)
            return True
        return False
