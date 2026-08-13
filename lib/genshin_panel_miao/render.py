# -*- coding: utf-8 -*-
"""
渲染: renderData dict -> 写 JSON -> node miao_panel/render.mjs -> Chrome 截图 -> PNG bytes
"""

import asyncio
import json
import os
import subprocess
import tempfile
import sys
from typing import Optional

# miao_panel 目录 (node 脚本所在): 项目根/miao_panel
_PROJ_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_MIAO_PANEL = os.path.join(_PROJ_DIR, "miao_panel")
_RENDER_MJS_SRC = os.path.join(_MIAO_PANEL, "render.mjs")

# node 可执行 (优先 Yunzai 的 node? 用系统 node 22)
_NODE = r"C:\Users\123\.workbuddy\binaries\node\versions\22.22.2\node.exe"
if not os.path.isfile(_NODE):
    _NODE = "node"

# 渲染要在 Yunzai 目录跑 (import art-template/puppeteer 需要其 node_modules)
_YZ_DIR = r"C:\Users\123\Desktop\Yunzai"
# render.mjs 必须复制到 Yunzai 目录 (node_modules 解析), 脚本路径用副本
_RENDER_MJS = os.path.join(_YZ_DIR, "render.mjs")


def _check_env() -> str:
    """检查 node 脚本与 Yunzai 是否就绪; 返回错误消息或空串."""
    import sys
    if not os.path.isdir(_YZ_DIR):
        msg = "Yunzai 目录不存在: %s" % _YZ_DIR
        print("[render_panel] %s" % msg, file=sys.stderr, flush=True)
        return msg
    if not os.path.isfile(os.path.join(_YZ_DIR, "node_modules", "art-template", "package.json")):
        msg = "Yunzai 缺少 art-template 依赖"
        print("[render_panel] %s" % msg, file=sys.stderr, flush=True)
        return msg
    if not os.path.isfile(os.path.join(_YZ_DIR, "node_modules", "puppeteer", "package.json")):
        msg = "Yunzai 缺少 puppeteer 依赖"
        print("[render_panel] %s" % msg, file=sys.stderr, flush=True)
        return msg
    # 启动时 (__init__.py _sync_render_mjs) 已尝试同步 render.mjs.
    # 此处兜底再 sync 一次 (应对路径异常/外部删除)
    if not os.path.isfile(_RENDER_MJS):
        try:
            if os.path.isfile(_RENDER_MJS_SRC):
                import shutil
                shutil.copyfile(_RENDER_MJS_SRC, _RENDER_MJS)
                print("[render_panel] 兜底同步 render.mjs 成功", file=sys.stderr, flush=True)
        except Exception as e:
            print("[render_panel] 兜底同步失败: %s" % e, file=sys.stderr, flush=True)
    if not os.path.isfile(_RENDER_MJS):
        msg = "渲染脚本缺失: %s (源=%s exists=%s)" % (
            _RENDER_MJS, _RENDER_MJS_SRC, os.path.isfile(_RENDER_MJS_SRC))
        print("[render_panel] %s" % msg, file=sys.stderr, flush=True)
        return msg
    return ""


async def render_panel(render_data: dict, timeout: int = 120) -> Optional[bytes]:
    """
    renderData dict -> PNG bytes.
    失败返回 None (调用方回退文本); 所有失败原因 print 到 stderr (bot 控制台可见).
    """
    import sys

    err = _check_env()
    if err:
        print("[render_panel] 环境检查失败: %s" % err, file=sys.stderr, flush=True)
        return None

    # 启动时已同步 render.mjs 到 Yunzai 目录 (见 __init__.py _sync_render_mjs)

    # 写 JSON 输入
    fd, json_path = tempfile.mkstemp(suffix=".json", prefix="miao_panel_")
    png_path = None
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(render_data, f, ensure_ascii=False)
        png_path = os.path.join(tempfile.gettempdir(), "miao_panel_out_%d.png" % os.getpid())

        proc = subprocess.run(
            [_NODE, _RENDER_MJS, json_path, png_path],
            cwd=_YZ_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
        if proc.returncode != 0:
            print("[render_panel] node 子进程返回码 %d" % proc.returncode, file=sys.stderr, flush=True)
            print("[render_panel] stdout: %s" % proc.stdout.strip()[:500], file=sys.stderr, flush=True)
            print("[render_panel] stderr: %s" % proc.stderr.strip()[:500], file=sys.stderr, flush=True)
            return None
        if not os.path.isfile(png_path):
            print("[render_panel] node 成功退出但 PNG 未生成: %s" % png_path, file=sys.stderr, flush=True)
            return None
        with open(png_path, "rb") as f:
            data = f.read()
        try:
            os.unlink(png_path)
        except OSError:
            pass
        return data
    except subprocess.TimeoutExpired:
        print("[render_panel] node 子进程超时 ({}s)".format(timeout), file=sys.stderr, flush=True)
        return None
    except Exception as e:
        print("[render_panel] 异常: {}: {}".format(type(e).__name__, e), file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return None
    finally:
        try:
            os.unlink(json_path)
        except OSError:
            pass
