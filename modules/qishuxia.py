# -*- coding: utf-8 -*-
"""
在线小说源（https://www.qishuxia.com）。

纯标准库实现，GBK 解码。提供三个接口：
  - search_books(keyword, limit=10) -> [{"book_id","title","author"}]
  - get_book(book_id) -> {"book_id","title","author","first_chapter_id"}
  - get_chapter(book_id, chapter_id) -> {"title","content","next_id","prev_id"}

说明：
  - 书籍详情页 /book/<id>/ 的章节列表是 JS 动态加载的，纯 HTML 拿不到，
    因此 get_book 只返回「首章 id」，章节靠 get_chapter 的 next_id 流式跟随（id 连续）。
  - 网络请求均为同步阻塞（urllib），调用方应在 asyncio.to_thread 中执行。
  - 任何网络 / 解析失败都会抛 QishuXiaError，由上层捕获并提示。
  - 搜索端点 (/modules/article/search.php) 需要 session cookie，首次请求前会自动预热；
    若当前会话触发搜索冷却，会自动尝试新会话重试。
"""

import re
import ssl
import time
import http.cookiejar
import urllib.request
import urllib.parse
import urllib.error

BASE = "https://www.qishuxia.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
_TIMEOUT = 12

_BOOK_TTL = 3600  # 书籍详情缓存 1 小时


class QishuXiaError(Exception):
    pass


_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

_cj = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(_cj),
    urllib.request.HTTPSHandler(context=_ssl_ctx),
)


def _new_opener():
    """为每次搜索新建一个独立会话，避免站点对同一 session 的 30 秒搜索冷却。"""
    cj = http.cookiejar.CookieJar()
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj),
        urllib.request.HTTPSHandler(context=_ssl_ctx),
    )


_book_cache = {}

_SEARCH_TTL = 300
_search_cache = {}


def _ensure_session():
    """搜索端点需要 session cookie，首次访问首页建立会话。"""
    if list(_cj):
        return
    try:
        _opener.open(
            urllib.request.Request(BASE + "/", headers={"User-Agent": UA}),
            timeout=_TIMEOUT).read()
    except Exception:
        pass


def _fetch(url, data=None, opener=None, _retried=False):
    """抓取 URL，返回解码后的 HTML 文本。失败抛 QishuXiaError。"""
    op = opener or _opener
    headers = {"User-Agent": UA, "Referer": BASE + "/"}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with op.open(req, timeout=_TIMEOUT) as r:
            raw = r.read()
            enc = r.headers.get_content_charset()
            if not enc:
                head = raw[:600].decode("utf-8", "ignore")
                m = re.search(r'charset=["\']?([\w-]+)', head, re.I)
                enc = m.group(1).lower() if m else "gbk"
            if enc == "utf-8":
                try:
                    return raw.decode("utf-8")
                except Exception:
                    enc = "gbk"
            return raw.decode(enc, errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 403 and not _retried:
            _ensure_session()
            return _fetch(url, data=data, opener=op, _retried=True)
        raise QishuXiaError("网络请求失败(HTTP %s)" % e.code)
    except Exception as e:
        raise QishuXiaError("网络请求失败: %s" % e)


def search_books(keyword, limit=10):
    """按书名搜索，返回前 limit 本（去重）。"""
    keyword = (keyword or "").strip()
    if not keyword:
        return []

    now = time.time()
    cached = _search_cache.get(keyword)
    if cached and now - cached[0] < _SEARCH_TTL:
        return cached[1][:limit]

    _ensure_session()
    # 站点官方搜索表单：POST /modules/article/search.php，字段 searchkey，GBK 编码
    try:
        payload = urllib.parse.urlencode(
            {"searchkey": keyword}, encoding="gbk").encode("gbk")
    except Exception as e:
        raise QishuXiaError("搜索编码失败: %s" % e)

    url = BASE + "/modules/article/search.php"
    try:
        html = _fetch(url, data=payload)
    except QishuXiaError:
        # 全局会话受限时，尝试用新会话重试
        html = _fetch(url, data=payload, opener=_new_opener())

    # 站点对频繁搜索会返回提示页；换一个新会话再试一次
    if "搜索的间隔时间不得少于" in html:
        html = _fetch(url, data=payload, opener=_new_opener())
        if "搜索的间隔时间不得少于" in html:
            if cached:
                return cached[1][:limit]
            raise QishuXiaError("搜索太频繁，请稍后再试")

    results = []
    seen = set()
    # 结果页为表格行：<li>...<span class="s2"><a href=".../book/id/">书名</a></span>...
    # <span class="s4">作者</span>...</li>
    for li in re.findall(r"<li>(.*?)</li>", html, re.S):
        m = re.search(
            r'<span class=["\']s2["\']>\s*<a[^>]+href=["\']%s/book/(\d+)/["\'][^>]*>([^<]+)</a>'
            % re.escape(BASE), li)
        if not m:
            continue
        bid = m.group(1)
        if bid in seen:
            continue
        title = m.group(2).strip()
        if not title:
            continue
        ma = re.search(r'<span class=["\']s4["\']>([^<]*)</span>', li)
        author = ma.group(1).strip() if ma else ""
        seen.add(bid)
        results.append({"book_id": bid, "title": title, "author": author})

    # 优先把书名完全匹配、或包含关键词的结果排在前面，提升随机推荐一致性
    def _sort_key(item):
        t = item["title"]
        if t == keyword:
            return (0, 0)
        if keyword in t:
            return (1, len(t))
        return (2, len(t))

    results.sort(key=_sort_key)
    _search_cache[keyword] = (time.time(), results)
    return results[:limit]


def get_book(book_id, use_cache=True):
    """获取书籍详情：标题、作者、首章 id。"""
    if use_cache and book_id in _book_cache:
        ts, data = _book_cache[book_id]
        if time.time() - ts < _BOOK_TTL:
            return data

    url = BASE + "/book/%s/" % book_id
    html = _fetch(url)

    title = ""
    mt = re.search(r'<title>([^<]+)</title>', html)
    if mt:
        title = mt.group(1).split("_")[0].split("(")[0].strip()

    author = ""
    ma = re.search(
        r'<span>([^<]*)</span>\s*<a[^>]+href=["\'][^"\']*/book/%s/["\']' % re.escape(book_id),
        html)
    if ma:
        author = ma.group(1).strip()

    # 首章 id：「开始阅读」按钮的 href（href 在前、>开始阅读< 在后）
    first_id = "1"
    mb = re.search(
        r'href=["\']([^"\']*/book/%s/(\d+)\.html)["\'][^>]*>\s*开始阅读'
        % re.escape(book_id), html)
    if mb:
        first_id = mb.group(2)

    data = {"book_id": book_id, "title": title, "author": author,
            "first_chapter_id": first_id}
    _book_cache[book_id] = (time.time(), data)
    return data


def get_chapter(book_id, chapter_id):
    """获取章节正文与上下章导航，返回 {title,content,next_id,prev_id}。"""
    url = BASE + "/book/%s/%s.html" % (book_id, chapter_id)
    html = _fetch(url)

    content = ""
    mc = re.search(r'<div[^>]*id=["\']content["\'][^>]*>(.*?)</div>', html, re.S | re.I)
    if mc:
        raw = mc.group(1)
        raw = re.sub(r'<script.*?</script>', '', raw, flags=re.S | re.I)
        raw = re.sub(r'<style.*?</style>', '', raw, flags=re.S | re.I)
        raw = re.sub(r'<br\s*/?>', '\n', raw, flags=re.I)
        raw = re.sub(r'</p>', '\n', raw, flags=re.I)
        raw = re.sub(r'<[^>]+>', '', raw)
        raw = (raw.replace('&nbsp;', ' ').replace('&amp;', '&')
                   .replace('&lt;', '<').replace('&gt;', '>'))
        lines = [ln.strip() for ln in raw.split('\n')]
        cleaned = []
        for ln in lines:
            if not ln:
                continue
            if re.search(r'第\s*\d+\s*/\s*\d+\s*页', ln):
                continue
            if '本章未完' in ln or '点击下一页' in ln:
                continue
            if ln.startswith('『') and '书签' in ln:
                continue
            cleaned.append(ln)
        content = "\n".join(cleaned)

    title = ""
    mh = re.search(r'<h1[^>]*>([^<]+)</h1>', html, re.I)
    if mh:
        title = mh.group(1).strip()
    else:
        mt = re.search(r'<title>([^<]+)</title>', html)
        if mt:
            title = mt.group(1).split("_")[0].strip()

    # 上下章导航（相对链接 3.html / 目录页 /book/<id>/）
    next_id = None
    prev_id = None
    for m in re.finditer(
            r'<a[^>]*href=["\']([^"\']+)["\'][^>]*>\s*(下一章|上[一章]+|上一章|目录|返回)\s*</a>',
            html, re.I):
        label = m.group(2).strip()
        href = m.group(1)
        mm = re.search(r'(\d+)\.html', href)
        if label == "下一章":
            if mm:
                next_id = mm.group(1)
        elif label in ("上一章", "上章"):
            if mm:
                prev_id = mm.group(1)

    return {"title": title, "content": content,
            "next_id": next_id, "prev_id": prev_id}
