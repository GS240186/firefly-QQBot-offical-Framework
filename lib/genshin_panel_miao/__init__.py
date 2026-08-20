# -*- coding: utf-8 -*-
"""
lib/genshin_panel_miao — 用 Yunzai miao-plugin 原生模板渲染原神面板。

数据流:
  Enka raw (plugins/genshin.py 已拉取)
    -> adapter.build_render_data(raw, uid, detail)   [Enka -> miao renderData dict]
    -> render.render_panel(data)                      [写 JSON -> node render.mjs -> Chrome 截图]
    -> PNG bytes

模板: C:/Users/123/Desktop/Yunzai/miao-plugin/resources/character/profile-detail.html
脚本: miao_panel/render.mjs (读 JSON 输入, 输出 PNG)
"""

import os
import sys
import shutil

# ============================================================================
# 启动时一次性同步 render.mjs 到 Yunzai 目录
# (node 脚本必须在 Yunzai 目录跑才能解析 art-template/puppeteer 的 node_modules)
# 这里在模块 import 时就同步好, 不依赖每次 render_panel 调用
# ============================================================================

_YZ_DIR = r"C:\Users\123\Desktop\Yunzai"
_RENDER_SRC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "miao_panel", "render.mjs"
)
_RENDER_DST = os.path.join(_YZ_DIR, "render.mjs")


def _sync_render_mjs():
    """启动同步: 把项目内的 render.mjs 复制到 Yunzai 目录 (供 node 用).

    该原神/星铁面板功能依赖本机 Yunzai + miao-plugin 资源，属可选功能；
    当源文件或 Yunzai 目录缺失时静默跳过（仅打印一次调试提示），
    不再以 stderr error 形式刷屏，避免干扰主流程。
    """
    if not os.path.isfile(_RENDER_SRC):
        # 源脚本缺失：本机未部署 miao_panel，该功能本就不可用，静默跳过
        print("[lib.genshin_panel_miao] render.mjs 源缺失，面板渲染功能不可用（可选功能，已跳过）", flush=True)
        return
    try:
        dst_dir = os.path.dirname(_RENDER_DST)
        if not os.path.isdir(dst_dir):
            # 目标 Yunzai 目录不存在，同样静默跳过
            print("[lib.genshin_panel_miao] Yunzai 目录不存在，面板渲染功能不可用（可选功能，已跳过）", flush=True)
            return
        src_mtime = os.path.getmtime(_RENDER_SRC)
        if os.path.isfile(_RENDER_DST):
            dst_mtime = os.path.getmtime(_RENDER_DST)
            if src_mtime <= dst_mtime:
                return  # 已是最新
        # 拷贝 (覆盖)
        shutil.copyfile(_RENDER_SRC, _RENDER_DST)
        print("[lib.genshin_panel_miao] render.mjs 已同步 -> %s" % _RENDER_DST, flush=True)
    except Exception as e:
        print("[lib.genshin_panel_miao] 同步失败: %s: %s (src=%s dst=%s)" % (
            type(e).__name__, e, _RENDER_SRC, _RENDER_DST), flush=True)


_sync_render_mjs()