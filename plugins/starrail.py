# -*- coding: utf-8 -*-
"""崩铁面板 v4 (2026-08-12): playwright 直截 Enka 展柜 + 多UID绑定/删除 + 1881x432 顶部信息条 + 1920x900 角色详情.

指令 (全部必须带 * 前缀):
  *星铁绑定uid<UID>   追加绑定,默认切换到最新账号
  *星铁uid列表        列出已绑定账号,默认账号左侧打勾 ✓
  *切换账户<N>        切换默认账号 (1-based)
  *星铁删除账户<N>    删除第 N 个账号 (1-based),默认账号索引同步调整
  *更新面板           截取展柜顶部信息条 + 角色头像栏 (clip 1876x250, 隐藏 Enka 顶导, 不含下方角色面板区), 匹配用户参考图#3
  *星铁<角色名>       点击头像切到目标角色, 开启 副词条强化状况+副词条解析,
                      等全部图片 (含立绘 canvas, 最多 20s) 完全加载完成后, 截完整角色面板 (full_page 全屏, 避免截图不完整)
                      (找不到 -> 该角色未放置展柜或展柜未打开。)

数据源: https://enka.network/hsr/<uid>/  (playwright headless chromium, 无 JSON 解析)
发图:   PNG -> modules.common.send_local_image_for_scene (msg_type=7 富媒体)

关键点 (2026-08-11 调整):
- 更新面板: viewport 1876x900, 隐藏 Enka 顶导后 clip 1876x250, 只含顶部玩家信息+角色头像栏 (不含下方角色面板区).
- 立绘等待: 主立绘 canvas 数据长度连续稳定 + 最多 20s 超时, 确保立绘加载完才截取/发送.
- 新增 星铁删除账户<N> 指令 (删除后若 active 失效 -> 矫正为 0 或 最后一个).
- 角色详情 viewport 1920x900, 只 clip 1920x560 截"角色面板"一屏 (立绘+属性+遗器), 不截整页; 副词条强化/解析开关; canvas polling 1s 内长度稳定.

无 avocado, 无 miao 模板, 无 sr_adapter. 旧 lib/genshin_panel_miao/sr_* / data/sr_maps.json
已废弃 (孤立死代码, 沙箱 safe-delete 拦截无法物理删除, 效果等价).
"""
import asyncio
import json
import os
import re


_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(os.path.dirname(_PLUGIN_DIR), "data")
_BIND_FILE = os.path.join(_DATA_DIR, "sr_bindings.json")

# ---- 命令正则 (全部要求 * 前缀触发) ----
_BIND_RE = re.compile(r"^\*\s*星铁绑定\s*uid\s*(\d{4,12})\s*$", re.IGNORECASE)
_LIST_RE = re.compile(r"^\*\s*星铁\s*uid\s*列表\s*$", re.IGNORECASE)
_SWITCH_RE = re.compile(r"^\*\s*切换账户\s*(\d+)\s*$")
_DELETE_RE = re.compile(r"^\*\s*星铁删除账户\s*(\d+)\s*$")
_UPDATE_RE = re.compile(r"^\*\s*更新面板\s*$")
# 兜底: *星铁<任意非空> 视为查角色
_CHAR_RE = re.compile(r"^\*\s*星铁\s*(\S.*?)\s*$")

# ---- Enka DOM 选择器 (Svelte 类名带 hash, 不依赖 svelte-hash) ----
_NAME_SEL = ".card-host .name.svelte-yux6ke"          # 详情面板角色名
_AVATAR_SEL = ".CharacterList .avatar.svelte-dxdrgu.live"  # 角色头像列

# ---- 截图区域 (2026-08-11 调整: 立绘等待 20s; 更新面板只截顶部信息+头像栏; 角色详情只截角色面板) ----
# 更新面板: 只截顶部玩家信息条 + 角色头像栏, 不含下方"当前角色面板"区域 (用户参考图#3)
_HEADER_CLIP = {"x": 0, "y": 0, "width": 1876, "height": 250}
_HEADER_VIEWPORT = {"width": 1876, "height": 900}                # 用 900 给页面渲染空间, clip 后只剩 250
# 角色详情: 截完整角色面板 (full_page 全屏, 避免截图不完整; 不再用 clip)
_DETAIL_CLIP = {"x": 0, "y": 0, "width": 1920, "height": 1080}  # 保留占位, 实际用 full_page
_DETAIL_VIEWPORT = {"width": 1920, "height": 900}                # 角色详情专用 viewport


# ====== 绑定数据 ======
def _load_binds():
    try:
        with open(_BIND_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_binds(d):
    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
        tmp = _BIND_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _BIND_FILE)
    except Exception as e:
        print("[starrail] save err: %s" % e, flush=True)


def get_active_uid(openid):
    binds = _load_binds()
    info = binds.get(str(openid or ""))
    if not info:
        return None
    uids = info.get("uids", [])
    if not uids:
        return None
    active = info.get("active", len(uids) - 1)
    if active < 0 or active >= len(uids):
        active = len(uids) - 1
    return uids[active]


def add_binding(openid, uid):
    binds = _load_binds()
    info = binds.setdefault(str(openid or ""), {"uids": [], "active": 0})
    uids = info["uids"]
    if uid in uids:
        info["active"] = uids.index(uid)
    else:
        uids.append(uid)
        info["active"] = len(uids) - 1
    _save_binds(binds)
    return info


def list_bindings(openid):
    return _load_binds().get(str(openid or ""))


def switch_active(openid, idx_1based):
    binds = _load_binds()
    info = binds.get(str(openid or ""))
    if not info or not info.get("uids"):
        return None, "未绑定任何账号"
    uids = info["uids"]
    idx = idx_1based - 1
    if idx < 0 or idx >= len(uids):
        return None, "无效账号编号,有效范围 1-%d" % len(uids)
    info["active"] = idx
    binds[str(openid or "")] = info
    _save_binds(binds)
    return uids[idx], None


def remove_binding(openid, idx_1based):
    """删除第 idx_1based 个账号 (1-based). 返回 (removed_uid, err_msg)."""
    binds = _load_binds()
    key = str(openid or "")
    info = binds.get(key)
    if not info or not info.get("uids"):
        return None, "未绑定任何账号"
    uids = info["uids"]
    idx = idx_1based - 1
    if idx < 0 or idx >= len(uids):
        return None, "无效账号编号,有效范围 1-%d" % len(uids)
    removed_uid = uids.pop(idx)
    old_active = info.get("active", len(uids))  # 删前 idx 仍有效
    if not uids:
        # 删空列表 -> 删除整个 info
        binds.pop(key, None)
    else:
        # 调整 active 索引
        if old_active == idx:
            # 删的就是当前 active -> 指向第一个
            info["active"] = 0
        elif old_active > idx:
            # 删的在 active 之前 -> active 索引减 1
            info["active"] = old_active - 1
        # else: active 索引未变 (old_active < idx)
        # 兜底越界
        if info["active"] >= len(uids):
            info["active"] = len(uids) - 1
        binds[key] = info
    _save_binds(binds)
    return removed_uid, None


# ====== Enka 截图 ======
async def _open_enka(uid, *, viewport_w=1280, viewport_h=900):
    """打开 Enka 展柜, 等待基础内容加载. 返回 (pw, browser, page). 调用方负责关闭."""
    from playwright.async_api import async_playwright
    url = "https://enka.network/hsr/%s/" % uid
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
    )
    ctx = await browser.new_context(
        viewport={"width": viewport_w, "height": viewport_h},
        device_scale_factor=1.0,
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        locale="zh-CN",
    )
    page = await ctx.new_page()
    await page.goto(url, wait_until="domcontentloaded", timeout=90000)
    try:
        await page.wait_for_function(
            "document.body && document.body.innerText.includes('开拓等级')",
            timeout=30000,
        )
    except Exception:
        pass
    try:
        await page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass
    return pw, browser, page


async def _ensure_substat_toggles(page):
    """开启 Enka 副词条强化状况 + 副词条解析 (页面默认未勾)."""
    try:
        await page.evaluate(
            """() => {
                const cbs = Array.from(document.querySelectorAll('input[type=checkbox]'));
                const targets = ['副词条强化状况', '副词条解析'];
                for (const target of targets) {
                    for (const cb of cbs) {
                        const t = (cb.parentElement?.textContent || '').trim();
                        if (t.includes(target) && !cb.checked) {
                            cb.click();
                            break;
                        }
                    }
                }
            }"""
        )
    except Exception:
        pass


async def _wait_all_images_loaded(page):
    """等所有 <img> 解码 + 主立绘 canvas 数据稳定 -> 等网络空闲.
    必须图片与立绘 canvas 都完全绘制完再发送."""
    import time
    # 1. 滚动触发懒加载 (Enka 立绘/光锥等图常在切换后才异步加载)
    try:
        h = await page.evaluate("document.documentElement.scrollHeight")
        step = 300
        end = max(int(h or 1500), step)
        for y in range(0, end, step):
            await page.evaluate("window.scrollTo(0, %d)" % y)
            await asyncio.sleep(0.2)
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.3)
    except Exception:
        pass
    # 2. 触发一次所有 <img> decode
    try:
        await page.evaluate(
            """async () => {
                const imgs = Array.from(document.images);
                await Promise.all(imgs.map(img => {
                    if (img.complete) return Promise.resolve();
                    if (img.decode) return img.decode().catch(() => {});
                    return new Promise(r => { img.onload = r; img.onerror = r; });
                }));
            }"""
        )
    except Exception:
        pass
    # 3. 等主立绘 canvas 数据长度连续 1 秒内不再变化 (切换/下载/重绘都覆盖)
    deadline = time.time() + 20
    prev_len = -2
    while time.time() < deadline:
        try:
            cur_len = await page.evaluate(
                """() => {
                    let maxLen = 0;
                    for (const c of document.querySelectorAll('canvas')) {
                        if (c.width < 500 || c.height < 500) continue;
                        try { const l = c.toDataURL('image/png').length; if (l > maxLen) maxLen = l; } catch (e) {}
                    }
                    return maxLen;
                }"""
            )
            if cur_len > 1000 and cur_len == prev_len:
                await asyncio.sleep(1.0)
                again = await page.evaluate(
                    """() => {
                        let maxLen = 0;
                        for (const c of document.querySelectorAll('canvas')) {
                            if (c.width < 500 || c.height < 500) continue;
                            try { const l = c.toDataURL('image/png').length; if (l > maxLen) maxLen = l; } catch (e) {}
                        }
                        return maxLen;
                    }"""
                )
                if again == cur_len:
                    break
            prev_len = cur_len
        except Exception:
            pass
        await asyncio.sleep(0.4)
    # 4. 最后再等一次 networkidle
    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass


async def _wait_header_images_loaded(page):
    """v4 顶部信息条图片等待 (不涉及立绘 canvas, 仅 <img> + 网络空闲)."""
    try:
        await page.evaluate(
            """async () => {
                const imgs = Array.from(document.images);
                await Promise.all(imgs.map(img => {
                    if (img.complete) return Promise.resolve();
                    if (img.decode) return img.decode().catch(() => {});
                    return new Promise(r => { img.onload = r; img.onerror = r; });
                }));
            }"""
        )
    except Exception:
        pass
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    await asyncio.sleep(1)


async def _hide_enka_top_nav(page):
    """v5 隐藏 Enka 顶部导航栏 (用户参考图不含顶导, 只要玩家信息条+角色头像栏).
    找 y<70 且 width>1000 的固定/绝对定位元素 (顶导) -> display:none."""
    try:
        await page.evaluate(
            """() => {
                for (const sel of ['nav', 'header', '[class*=navbar]', '[class*=enka-nav]', '[class*=header-bar]', '[class*=Header]']) {
                    for (const el of document.querySelectorAll(sel)) {
                        el.style.setProperty('display', 'none', 'important');
                    }
                }
                // 兜底: 任何 y<70 + width>1000 + position 非 static 的元素
                const all = Array.from(document.querySelectorAll('body *'));
                for (const el of all) {
                    const r = el.getBoundingClientRect();
                    if (r.top < 0 || r.top > 70 || r.height > 80 || r.width < 1000) continue;
                    const pos = getComputedStyle(el).position;
                    if (pos === 'fixed' || pos === 'absolute' || pos === 'sticky') {
                        el.style.setProperty('display', 'none', 'important');
                    }
                }
            }"""
        )
    except Exception:
        pass


async def _capture_showcase_header(uid):
    """v5 截取 1876x396 顶部信息条 + 角色头像栏 + 当前选中角色起始 (用户参考图规格)."""
    pw, browser, page = await _open_enka(
        uid, viewport_w=_HEADER_VIEWPORT["width"], viewport_h=_HEADER_VIEWPORT["height"]
    )
    try:
        # 1. 隐藏 Enka 顶部导航栏 (用户参考图不含顶导)
        await _hide_enka_top_nav(page)
        await asyncio.sleep(0.5)
        # 2. 等所有 <img> 解码 + networkidle (顶部无立绘 canvas, 不需要 canvas polling)
        await _wait_header_images_loaded(page)
        # 3. 截 1876x396 (含玩家信息 + CharacterList + 当前选中 character display 起始)
        return await page.screenshot(clip=_HEADER_CLIP, type="png")
    finally:
        await browser.close()
        await pw.stop()


async def _capture_character_detail(uid, char_name):
    """点击角色头像切到目标 -> 开启副词条开关 -> 等全部图加载 -> 截完整角色面板(full_page).
    返回 (png_bytes, status)  status='ok'|'not_found'|'shot_err'."""
    pw, browser, page = await _open_enka(
        uid, viewport_w=_DETAIL_VIEWPORT["width"], viewport_h=_DETAIL_VIEWPORT["height"]
    )
    try:
        target = char_name.strip()

        async def _current_name():
            try:
                txt = await page.evaluate(
                    "(sel) => { const e = document.querySelector(sel); return e ? e.textContent.trim() : ''; }",
                    _NAME_SEL,
                )
                return txt or ""
            except Exception:
                return ""

        # 1. 默认显示首位角色; 若不是目标则遍历头像点击
        cur = await _current_name()
        matched = (cur == target)
        if not matched:
            avatars = await page.query_selector_all(_AVATAR_SEL)
            for av in avatars:
                try:
                    await av.click()
                except Exception:
                    continue
                try:
                    await page.wait_for_function(
                        "(args) => { const e = document.querySelector(args.sel); return e && e.textContent.trim() === args.target; }",
                        arg={"sel": _NAME_SEL, "target": target},
                        timeout=5000,
                    )
                except Exception:
                    await asyncio.sleep(0.8)
                cur = await _current_name()
                if cur == target:
                    matched = True
                    break
        if not matched:
            return None, "not_found"

        # 2. 开启 副词条强化状况 + 副词条解析 (Enka 默认未勾)
        await _ensure_substat_toggles(page)
        await asyncio.sleep(0.8)

        # 3. 等所有 <img> + 主立绘 canvas 数据稳定 (切到非首位角色时立绘从云端下载, ~10s)
        await _wait_all_images_loaded(page)
        await asyncio.sleep(1)

        # 4. 截完整角色面板 (full_page 全屏, 含立绘+属性+遗器, 不截整页)
        try:
            png = await page.screenshot(full_page=True, type="png")
        except Exception as e:
            return None, "shot_err:%s" % e
        return png, "ok"
    finally:
        await browser.close()
        await pw.stop()


# ====== 插件入口 ======
async def handle(ctx):
    content = (ctx.content or "").strip()
    if not content:
        return False

    openid = str(ctx.member_openid or "")

    # 1) 星铁绑定uid<UID>
    m = _BIND_RE.match(content)
    if m:
        uid = m.group(1)
        info = add_binding(openid, uid)
        idx = info["active"] + 1
        cur_uid = info["uids"][info["active"]]
        if len(info["uids"]) == 1:
            await ctx.reply("✅ 星铁uid%s绑定成功" % uid)
        else:
            await ctx.reply(
                "✅ 星铁uid%s绑定成功\n当前默认账号%d：%s\n共绑定 %d 个账号,可发送「*星铁uid列表」查看"
                % (uid, idx, cur_uid, len(info["uids"]))
            )
        return True

    # 2) 星铁uid列表
    m = _LIST_RE.match(content)
    if m:
        info = list_bindings(openid)
        if not info or not info.get("uids"):
            await ctx.reply("⚠️ 你还未绑定任何星铁账号,请发「*星铁绑定uid<UID>」。")
            return True
        uids = info["uids"]
        active = info["active"]
        lines = ["你的星铁账号："]
        for i, uid in enumerate(uids):
            mark = "✓" if i == active else " "
            lines.append("%s账号%d：%s" % (mark, i + 1, uid))
        await ctx.reply("\n".join(lines))
        return True

    # 3) 切换账户<N>
    m = _SWITCH_RE.match(content)
    if m:
        idx = int(m.group(1))
        uid, err = switch_active(openid, idx)
        if err:
            await ctx.reply("⚠️ %s" % err)
            return True
        await ctx.reply("✅ 已切换到账号%d：%s" % (idx, uid))
        return True

    # 4) 星铁删除账户<N>
    m = _DELETE_RE.match(content)
    if m:
        idx = int(m.group(1))
        removed_uid, err = remove_binding(openid, idx)
        if err:
            await ctx.reply("⚠️ %s" % err)
            return True
        await ctx.reply("✅ 已删除账户%d：%s" % (idx, removed_uid))
        return True

    # 5) 更新面板
    m = _UPDATE_RE.match(content)
    if m:
        uid = get_active_uid(openid)
        if not uid:
            await ctx.reply("⚠️ 请先发「*星铁绑定uid<UID>」绑定你的星铁 UID。")
            return True
        try:
            png = await _capture_showcase_header(uid)
        except Exception as e:
            await ctx.reply("❌ Enka 截图失败: %s" % e)
            return True
        try:
            from modules.common import send_local_image_for_scene
            await send_local_image_for_scene(
                ctx.api, ctx.scene, ctx.target_id, png,
                content="星铁更新面板 · UID %s" % uid,
            )
            return True
        except Exception as e:
            await ctx.reply("❌ 发送图片失败: %s" % e)
            return True

    # 6) 星铁<角色名>
    m = _CHAR_RE.match(content)
    if m:
        rest = m.group(1).strip()
        # 去掉常见前缀词
        rest = re.sub(r"^(?:面板|详情|角色|查询|查)\s*", "", rest).strip()
        if not rest:
            return False
        uid = get_active_uid(openid)
        if not uid:
            await ctx.reply("⚠️ 请先发「*星铁绑定uid<UID>」绑定你的星铁 UID。")
            return True
        try:
            png, status = await _capture_character_detail(uid, rest)
        except Exception as e:
            await ctx.reply("❌ Enka 截图失败: %s" % e)
            return True
        if status != "ok" or png is None:
            await ctx.reply("该角色未放置展柜或展柜未打开。")
            return True
        try:
            from modules.common import send_local_image_for_scene
            await send_local_image_for_scene(
                ctx.api, ctx.scene, ctx.target_id, png,
                content="星铁 %s · UID %s" % (rest, uid),
            )
            return True
        except Exception as e:
            await ctx.reply("❌ 发送图片失败: %s" % e)
            return True

    return False


# PLUGIN 注册必须在 handle 定义之后 (外置插件 import 阶段即读 PLUGIN.handle)
PLUGIN = {
    "key": "starrail",
    "name": "星铁面板",
    "priority": 470,
    "description": "playwright 截 Enka 展柜/角色详情;支持多UID绑定/列表/切换/删除/更新面板/查角色",
    "handle": handle,
}
