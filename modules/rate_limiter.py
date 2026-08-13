# -*- coding: utf-8 -*-
"""指令限速：滑动窗口限制同一用户单位时间内的指令次数。

- 配置键：framework.rate_limit.enabled / framework.rate_limit.window_ms（运行设置，三层作用域）
- 超限时返回 False，调用方应静默丢弃（不响应），避免影响线上主流程。
- 采用 (appid, uid, gid) 维度分别计数。
"""

import threading
import time
from collections import deque

# 默认窗口内最大指令数（framework.rate_limit.window_ms 仅控制窗口长度）
_RATE_MAX = 8

_lock = threading.Lock()
# 每个维度维护一个时间戳 deque（毫秒）
_hits = {}


def _get_eff(key, appid, gid):
    """惰性读取运行设置（避免模块加载期循环导入）。"""
    try:
        from console_server import get_runtime_setting_effective
        return get_runtime_setting_effective(key, appid=appid, group_id=gid)
    except Exception:
        return None


def is_allowed(appid, uid, gid):
    """返回是否允许本次指令。允许时记录一次命中；超限返回 False（静默丢弃）。"""
    try:
        enabled = bool(_get_eff("framework.rate_limit.enabled", appid, gid))
    except Exception:
        enabled = False
    if not enabled:
        return True
    try:
        window_ms = int(_get_eff("framework.rate_limit.window_ms", appid, gid) or 3000)
    except Exception:
        window_ms = 3000
    if window_ms <= 0:
        return True

    key = (str(appid), str(uid), str(gid))
    now = time.time() * 1000.0
    cutoff = now - window_ms
    with _lock:
        dq = _hits.get(key)
        if dq is None:
            dq = deque()
            _hits[key] = dq
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= _RATE_MAX:
            return False
        dq.append(now)
        return True
