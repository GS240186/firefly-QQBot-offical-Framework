# -*- coding: utf-8 -*-

"""
小说系统模块（古典名著本地库版）

数据源：data/classic_novels.json（6 本古典名著，含正文，公有领域）

  - 书库：本地 JSON，含 {title, author, intro, category, chapters:[{title, content}]}

  - 阅读：进入书库 -> 看某本 -> 章节目录 -> 按章分页阅读（本地 PIL 渲染图片发送）

设计要点：

  - 纯本地，不依赖任何外部 API / 网络，不会出现连不上源站 / 850019 / 外链等问题

  - 状态机：idle -> library(书库) -> reading(某书某章某页)

  - 全局指令隔离：阅读中输入「菜单/帮助/签到」等非小说指令时，静默退出阅读交给其它功能

  - 渲染层 render_novel（data/render_novel.py）：render_book_cover / render_chapter_list /
    render_content_page / get_page_count
"""

import os
import re
import json
import asyncio
import random
import importlib.util

from botpy import logging
from modules.common import (
    send_text,
    send_text_with_keyboard,
    send_local_image_for_scene,
    load_json,
    save_json,
    data_path,
)

logger = logging.get_logger()

# ============ 路径 ============
_NOVEL_FILE = data_path("classic_novels.json")
_STATE_FILE = data_path("novel_states.json")

# 渲染器 render_novel（data/render_novel.py），用绝对路径加载，避免 data 非 package 问题
_RENDER_PATH = data_path("render_novel.py")
try:
    _spec = importlib.util.spec_from_file_location("render_novel", _RENDER_PATH)
    render_novel = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(render_novel)
except Exception as e:  # noqa
    render_novel = None
    logger.error("渲染器 render_novel 加载失败: %s" % e)


# ============ 键盘构造（多行） ============
def _build_kb(buttons_config, per_row=5):
    rows = []
    for i in range(0, len(buttons_config), per_row):
        row_btns = buttons_config[i:i + per_row]
        buttons = []
        for cfg in row_btns:
            label = cfg["label"]
            cmd = cfg["command"]
            buttons.append({
                "id": "nv_" + re.sub(r"[^0-9a-zA-Z\u4e00-\u9fa5]", "", cmd)[:18],
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
        rows.append({"buttons": buttons})
    return {"content": {"rows": rows}}


class NovelSystem:
    def __init__(self):
        self._books = []
        self._mtime = 0
        self._states = {}
        self._load_states()
        self._reload_books()

    # ---- 数据加载 ----
    def _reload_books(self):
        try:
            mtime = os.path.getmtime(_NOVEL_FILE)
            if self._books and mtime == self._mtime:
                return
            with open(_NOVEL_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            raw = data.get("books", []) if isinstance(data, dict) else (data or [])
            norm = []
            for b in raw:
                if not isinstance(b, dict):
                    continue
                norm.append({
                    "title": b.get("title", "无名"),
                    "author": b.get("author", ""),
                    "intro": b.get("intro", ""),
                    "category": b.get("category", ""),
                    "chapters": b.get("chapters", []) or [],
                })
            self._books = norm
            self._mtime = mtime
            logger.info("小说书库加载完成：%d 本" % len(self._books))
        except Exception as e:
            logger.error("小说书库加载失败: %s" % e)

    def _check_reload(self):
        self._reload_books()

    # ---- 状态 ----
    def _load_states(self):
        try:
            self._states = load_json(_STATE_FILE) or {}
        except Exception:
            self._states = {}
        # 过滤不兼容的旧状态（如旧版在线小说残留的 book_id 字段），只保留本地库版结构
        clean = {}
        for sid, st in self._states.items():
            if isinstance(st, dict) and isinstance(st.get("book_index"), int) \
                    and "chapter_idx" in st and "page" in st:
                clean[sid] = st
        self._states = clean

    def _save_states(self):
        try:
            save_json(_STATE_FILE, self._states)
        except Exception as e:
            logger.warning("小说状态保存失败: %s" % e)

    def _get_state(self, storage_id):
        return self._states.get(storage_id)

    def _save_state(self, storage_id, state):
        if state is None:
            self._states.pop(storage_id, None)
        else:
            self._states[storage_id] = state
        self._save_states()

    def _is_reading(self, storage_id):
        st = self._states.get(storage_id)
        return bool(st and st.get("book_index") is not None)

    def _force_end_reading(self, storage_id):
        if storage_id in self._states:
            self._states.pop(storage_id, None)
            self._save_states()

    # ---- 找书 ----
    def _find_book(self, title):
        title = (title or "").strip()
        if not title:
            return None
        for i, b in enumerate(self._books):
            if b["title"] == title:
                return i
        for i, b in enumerate(self._books):
            if title in b["title"] or b["title"] in title:
                return i
        return None

    # ---- 主入口 ----
    async def handle_command(self, api, content, storage_id, member_openid, msg_id, scene):
        self._check_reload()
        if not self._books:
            return False
        text = (content or "").strip()

        if self._is_reading(storage_id):
            return await self._handle_reading(api, text, storage_id, msg_id, scene)

        # 精确入口
        if text in ("小说", "看小说", "读书", "看书", "在线阅读"):
            await self._show_library(api, storage_id, msg_id, scene)
            return True
        # 前缀：看/读
        if text.startswith("看 ") or text.startswith("读 "):
            return await self._start_book_by_title(api, text[2:].strip(), storage_id, msg_id, scene)
        if text.startswith("章节 "):
            return await self._show_chapter_list_by_title(api, text[3:].strip(), storage_id, msg_id, scene)
        if text.startswith("小说 "):
            sub = text[3:].strip()
            if sub in ("随机推荐", "随机"):
                return await self._random_book(api, storage_id, msg_id, scene)
            # 视为「小说 书名」搜索
            return await self._start_book_by_title(api, sub, storage_id, msg_id, scene)
        return False

    # ---- 阅读中 ----
    async def _handle_reading(self, api, text, storage_id, msg_id, scene):
        st = self._states.get(storage_id)
        if st is None:
            return False

        if text in ("小说", "看小说", "读书", "看书", "在线阅读"):
            self._force_end_reading(storage_id)
            await self._show_library(api, storage_id, msg_id, scene)
            return True
        if text in ("退出小说", "不看了", "结束阅读", "退出阅读"):
            self._force_end_reading(storage_id)
            await send_text(api, scene, storage_id, "已退出阅读。发送「小说」可重新进入书库。", msg_id=msg_id)
            return True
        if text in ("返回书库", "书库", "返回"):
            self._force_end_reading(storage_id)
            await self._show_library(api, storage_id, msg_id, scene)
            return True
        if text in ("章节列表", "目录", "章节"):
            await self._show_chapter_list(api, st, storage_id, msg_id, scene)
            return True
        if text == "上一页":
            return await self._turn_page(api, st, storage_id, msg_id, scene, -1)
        if text == "下一页":
            return await self._turn_page(api, st, storage_id, msg_id, scene, 1)
        if text.startswith("看 ") or text.startswith("读 "):
            return await self._start_book_by_title(api, text[2:].strip(), storage_id, msg_id, scene)
        m = re.match(r"^第\s*(\d+)\s*(回|章|卷)?$", text)
        if m:
            return await self._goto_chapter(api, st, storage_id, msg_id, scene, int(m.group(1)) - 1)
        # 其它指令：静默退出阅读，交给其它功能处理
        self._force_end_reading(storage_id)
        return False

    # ---- 书库 ----
    async def _show_library(self, api, storage_id, msg_id, scene):
        books = self._books
        btns = []
        for b in books:
            btns.append({"label": b["title"], "command": "看 %s" % b["title"]})
        btns.append({"label": "🎲 随机推荐", "command": "小说 随机推荐"})
        btns.append({"label": "❌ 退出", "command": "退出小说"})
        kb = _build_kb(btns, per_row=2)
        total_chaps = sum(len(b["chapters"]) for b in books)
        await send_text_with_keyboard(
            api, scene, storage_id,
            "📖 古典名著在线书库\n共 %d 本，%d 回，可点击阅读（全书本地存储）：\n"
            "《三国演义》《水浒传》《西游记》《红楼梦》《聊斋志异》《封神演义》"
            % (len(books), total_chaps),
            kb, msg_id=msg_id)

    # ---- 进入某书 ----
    async def _start_book_by_title(self, api, title, storage_id, msg_id, scene):
        idx = self._find_book(title)
        if idx is None:
            await send_text(api, scene, storage_id,
                            "没找到《%s》，请发送「小说」从书库选择。" % title, msg_id=msg_id)
            return True
        await self._enter_book(api, idx, storage_id, msg_id, scene, 0, 1)
        return True

    async def _enter_book(self, api, book_idx, storage_id, msg_id, scene, chapter_idx=0, page=1):
        book = self._books[book_idx]
        self._states[storage_id] = {
            "book_index": book_idx,
            "chapter_idx": chapter_idx,
            "page": page,
        }
        self._save_states()

        # 封面图
        if render_novel is not None:
            try:
                cover = render_novel.render_book_cover(book)
                await self._send_local_img(api, scene, storage_id, cover, msg_id)
            except Exception as e:
                logger.warning("封面渲染失败: %s" % e)
            # 章节目录图
            try:
                chap_img = render_novel.render_chapter_list(book)
                await self._send_local_img(api, scene, storage_id, chap_img, msg_id)
            except Exception as e:
                logger.warning("章节图渲染失败: %s" % e)

        await self._show_chapter_content(api, self._states[storage_id], storage_id, msg_id, scene)

    # ---- 章节目录（按书名） ----
    async def _show_chapter_list_by_title(self, api, title, storage_id, msg_id, scene):
        idx = self._find_book(title)
        if idx is None:
            await send_text(api, scene, storage_id,
                            "没找到《%s》，请发送「小说」从书库选择。" % title, msg_id=msg_id)
            return True
        self._states[storage_id] = {"book_index": idx, "chapter_idx": 0, "page": 1}
        self._save_states()
        st = self._states[storage_id]
        if render_novel is not None:
            try:
                chap_img = render_novel.render_chapter_list(self._books[idx])
                await self._send_local_img(api, scene, storage_id, chap_img, msg_id)
            except Exception as e:
                logger.warning("章节图渲染失败: %s" % e)
        await self._show_chapter_list(api, st, storage_id, msg_id, scene)
        return True

    # ---- 章节目录 ----
    async def _show_chapter_list(self, api, st, storage_id, msg_id, scene):
        book = self._books[st["book_index"]]
        chs = book["chapters"]
        if render_novel is not None:
            try:
                chap_img = render_novel.render_chapter_list(book)
                await self._send_local_img(api, scene, storage_id, chap_img, msg_id)
            except Exception as e:
                logger.warning("章节图渲染失败: %s" % e)
        btns = []
        for i in range(min(5, len(chs))):
            btns.append({"label": "第%d回" % (i + 1), "command": "第%d回" % (i + 1)})
        if len(chs) > 5:
            btns.append({"label": "更多章节", "command": "章节列表"})
        btns.append({"label": "📄 当前章", "command": "第%d回" % (st["chapter_idx"] + 1)})
        btns.append({"label": "📚 书库", "command": "返回书库"})
        kb = _build_kb(btns, per_row=3)
        await send_text_with_keyboard(
            api, scene, storage_id,
            "《%s》共 %d 回，选择章节开始阅读：" % (book["title"], len(chs)),
            kb, msg_id=msg_id)
        return True

    # ---- 正文 ----
    async def _show_chapter_content(self, api, st, storage_id, msg_id, scene):
        book = self._books[st["book_index"]]
        chs = book["chapters"]
        ci = st["chapter_idx"]
        if ci < 0 or ci >= len(chs):
            ci = 0
        ch = chs[ci]
        total = render_novel.get_page_count(ch) if render_novel else 1
        page = max(1, min(st["page"], total))
        st["page"] = page
        self._save_states()

        if render_novel is not None:
            try:
                img = render_novel.render_content_page(book, ch, page, total)
                await self._send_local_img(
                    api, scene, storage_id, img, msg_id,
                    content="《%s》· %s" % (book["title"], ch.get("title", "")))
            except Exception as e:
                logger.error("正文渲染失败: %s" % e)
                await send_text(api, scene, storage_id, "本章渲染失败：%s" % e, msg_id=msg_id)
        else:
            await send_text(api, scene, storage_id,
                            "渲染器不可用（缺少 Pillow），无法显示图片。", msg_id=msg_id)

        kb = _build_kb([
            {"label": "⬆️ 上一页", "command": "上一页"},
            {"label": "⬇️ 下一页", "command": "下一页"},
            {"label": "📑 目录", "command": "章节列表"},
            {"label": "📚 书库", "command": "返回书库"},
            {"label": "❌ 退出", "command": "退出小说"},
        ], per_row=5)
        await send_text_with_keyboard(
            api, scene, storage_id,
            "第 %d/%d 回 · 第 %d/%d 页" % (ci + 1, len(chs), page, total),
            kb, msg_id=msg_id)

    # ---- 翻页 ----
    async def _turn_page(self, api, st, storage_id, msg_id, scene, delta):
        book = self._books[st["book_index"]]
        chs = book["chapters"]
        ci = st["chapter_idx"]
        total = render_novel.get_page_count(chs[ci]) if render_novel else 1
        new_page = st["page"] + delta
        if new_page < 1:
            if ci > 0:
                ci -= 1
                new_page = render_novel.get_page_count(chs[ci]) if render_novel else 1
            else:
                new_page = 1
        elif new_page > total:
            if ci < len(chs) - 1:
                ci += 1
                new_page = 1
            else:
                new_page = total
        st["chapter_idx"] = ci
        st["page"] = new_page
        self._save_states()
        await self._show_chapter_content(api, st, storage_id, msg_id, scene)
        return True

    # ---- 跳章 ----
    async def _goto_chapter(self, api, st, storage_id, msg_id, scene, n):
        book = self._books[st["book_index"]]
        chs = book["chapters"]
        if n < 0 or n >= len(chs):
            await send_text(api, scene, storage_id,
                            "没有第 %d 回，本书共 %d 回。" % (n + 1, len(chs)), msg_id=msg_id)
            return True
        st["chapter_idx"] = n
        st["page"] = 1
        self._save_states()
        await self._show_chapter_content(api, st, storage_id, msg_id, scene)
        return True

    # ---- 随机 ----
    async def _random_book(self, api, storage_id, msg_id, scene):
        if not self._books:
            return False
        idx = random.randrange(len(self._books))
        await self._enter_book(api, idx, storage_id, msg_id, scene, 0, 1)
        return True

    # ---- 本地图片发送 ----
    async def _send_local_img(self, api, scene, storage_id, path, msg_id, content=""):
        try:
            with open(path, "rb") as f:
                data = f.read()
            await send_local_image_for_scene(api, scene, storage_id, data, msg_id=msg_id, content=content)
        except Exception as e:
            logger.error("发送本地图片失败: %s" % e)


# 单例
novel_mgr = NovelSystem()
