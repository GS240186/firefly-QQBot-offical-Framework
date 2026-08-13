# -*- coding: utf-8 -*-
"""
小说系统图片渲染器（最小可用版本）。
novel_system.py 期望的接口：
    - render_book_cover(book) -> str (图片绝对路径)
    - render_chapter_list(book) -> str
    - render_content_page(book, chapter, page_no, total_pages) -> str
    - get_page_count(chapter) -> int
设计目标：
    - 依赖最小：仅 Pillow + 系统字体
    - 即使章节正文为空（仅含 title）也不报错
    - 输出图片存放在 data/cache/novel_img/，供 _send_image 读取
"""

import os
import time

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # 极端环境无 Pillow
    Image = None
    ImageDraw = None
    ImageFont = None


# ============ 路径与字体 ============

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_CACHE_DIR = os.path.join(_THIS_DIR, "cache", "novel_img")
os.makedirs(_CACHE_DIR, exist_ok=True)

# 找一个能渲染中文的字体（Windows 自带）
_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyh.ttf",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _load_font(size: int):
    if ImageFont is None:
        return None
    for fp in _FONT_CANDIDATES:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size=size)
            except Exception:
                continue
    return ImageFont.load_default()


_FONT_BIG = None
_FONT_MID = None
_FONT_SMALL = None


def _fonts():
    global _FONT_BIG, _FONT_MID, _FONT_SMALL
    if _FONT_BIG is None:
        _FONT_BIG = _load_font(36)
        _FONT_MID = _load_font(24)
        _FONT_SMALL = _load_font(18)
    return _FONT_BIG, _FONT_MID, _FONT_SMALL


# ============ 颜色与画板 ============

_BG_COLOR = (250, 246, 232)         # 米黄底
_FG_COLOR = (60, 40, 20)            # 深棕字
_ACCENT_COLOR = (170, 80, 40)       # 朱红
_RULE_COLOR = (200, 180, 150)       # 浅金边


def _new_canvas(w: int = 720, h: int = 480, title: str = ""):
    if Image is None:
        raise RuntimeError("Pillow 未安装，无法渲染小说图片")
    img = Image.new("RGB", (w, h), _BG_COLOR)
    draw = ImageDraw.Draw(img)
    # 边框
    draw.rectangle([(6, 6), (w - 7, h - 7)], outline=_RULE_COLOR, width=2)
    if title:
        big, _, _ = _fonts()
        # 标题居中
        try:
            tw = draw.textlength(title, font=big)
        except Exception:
            tw = len(title) * 18
        draw.text(((w - tw) / 2, 24), title, fill=_ACCENT_COLOR, font=big)
        # 分隔线
        draw.line([(60, 78), (w - 60, 78)], fill=_RULE_COLOR, width=1)
    return img, draw


# ============ 通用：把多行文本按行高写到画板 ============

def _draw_wrapped_text(draw, text: str, font, x: int, y: int, max_w: int,
                        line_gap: int = 8, max_lines: int = 18):
    if not text:
        return y
    lines = []
    cur = ""
    for ch in text:
        candidate = cur + ch
        try:
            cw = draw.textlength(candidate, font=font)
        except Exception:
            cw = len(candidate) * 14
        if cw > max_w and cur:
            lines.append(cur)
            cur = ch
            if len(lines) >= max_lines:
                break
        else:
            cur = candidate
    if cur and len(lines) < max_lines:
        lines.append(cur)
    for i, ln in enumerate(lines):
        draw.text((x, y + i * (font.size + line_gap)), ln, fill=_FG_COLOR, font=font)
    return y + len(lines) * (font.size + line_gap)


# ============ 业务接口 ============

def render_book_cover(book: dict) -> str:
    """书籍封面图"""
    title = book.get("title", "无名")
    author = book.get("author", "")
    intro = book.get("intro", "")
    chapters = book.get("chapters", []) or []
    chap_n = len(chapters) if isinstance(chapters, list) else int(chapters or 0)

    img, draw = _new_canvas(720, 480, title="《" + title + "》")
    _, mid, small = _fonts()

    # 作者
    draw.text((60, 100), "作者：" + str(author), fill=_ACCENT_COLOR, font=mid)

    # 章节数
    draw.text((60, 140), "章节：%d 回" % chap_n, fill=_FG_COLOR, font=mid)

    # 简介
    draw.text((60, 190), "简介：", fill=_ACCENT_COLOR, font=mid)
    _draw_wrapped_text(draw, intro or "（暂无简介）", small,
                       x=60, y=230, max_w=600, line_gap=6, max_lines=10)

    # 落款
    draw.text((60, 440), "—— 小流萤在线书库 ——", fill=_RULE_COLOR, font=small)

    out = os.path.join(_CACHE_DIR, "cover_%d_%d.png" % (
        abs(hash(title)) % 100000, int(time.time() * 1000) % 100000))
    img.save(out, "PNG")
    return out


def render_chapter_list(book: dict) -> str:
    """章节目录图"""
    title = book.get("title", "")
    chapters = book.get("chapters", []) or []
    if not isinstance(chapters, list):
        chapters = []

    img, draw = _new_canvas(720, 540, title="《%s》· 章节目录" % title)
    _, mid, small = _fonts()

    y = 100
    for idx, ch in enumerate(chapters[:18]):
        if isinstance(ch, dict):
            ch_title = ch.get("title") or ch.get("name") or "第%d回" % (idx + 1)
        else:
            ch_title = str(ch) or "第%d回" % (idx + 1)
        draw.text((80, y), "%3d. %s" % (idx + 1, ch_title),
                  fill=_FG_COLOR, font=mid)
        y += 40
        if y > 480:
            break
    if len(chapters) > 18:
        draw.text((80, y), "……（共 %d 章，仅显示前 18 章）" % len(chapters),
                  fill=_ACCENT_COLOR, font=small)

    out = os.path.join(_CACHE_DIR, "chap_%d_%d.png" % (
        abs(hash(title)) % 100000, int(time.time() * 1000) % 100000))
    img.save(out, "PNG")
    return out


def get_page_count(chapter) -> int:
    """根据章节内容长度估算页数（每页约 380 字）。"""
    if isinstance(chapter, dict):
        text = chapter.get("content") or chapter.get("text") or chapter.get("body") or ""
    else:
        text = str(chapter) if chapter else ""
    if not text:
        return 1
    n = max(1, (len(text) + 379) // 380)
    return min(n, 20)  # 单章最多 20 页（避免图片爆炸）


def render_content_page(book: dict, chapter, page_no: int = 1,
                        total_pages: int = 1) -> str:
    """正文页图"""
    title = book.get("title", "")
    if isinstance(chapter, dict):
        ch_title = chapter.get("title") or chapter.get("name") or ""
        text = chapter.get("content") or chapter.get("text") or chapter.get("body") or ""
    else:
        ch_title = ""
        text = str(chapter) if chapter else ""

    img, draw = _new_canvas(720, 560, title="《%s》" % title)
    _, mid, small = _fonts()

    # 章节标题
    if ch_title:
        draw.text((60, 90), "· " + ch_title, fill=_ACCENT_COLOR, font=mid)
        start_y = 140
    else:
        start_y = 100

    # 翻到当前页
    if text:
        per_page = 380
        seg = text[(page_no - 1) * per_page: page_no * per_page]
    else:
        seg = "（本章暂无正文内容，敬请期待后续更新……）"

    _draw_wrapped_text(draw, seg, small,
                       x=60, y=start_y, max_w=600, line_gap=8, max_lines=18)

    # 页脚
    draw.text((60, 520), "—— 第 %d / %d 页 ——" % (page_no, total_pages),
              fill=_RULE_COLOR, font=small)

    out = os.path.join(_CACHE_DIR, "page_%d_%d_%d.png" % (
        abs(hash(title)) % 100000,
        abs(hash(str(chapter))) % 100000,
        int(time.time() * 1000) % 100000))
    img.save(out, "PNG")
    return out
