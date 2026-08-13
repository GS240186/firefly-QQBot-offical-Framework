# -*- coding: utf-8 -*-

"""

运行健康指标采集模块（bot_health）

集中采集机器人运行期的关键健康指标，供控制台「运行健康」页展示：

  - 命令处理器计数（群聊 / 私聊，按 bot appid 隔离）

  - 群事件处理器计数（入群/退群/成员变动等，按 appid 隔离）

  - 消息去重命中计数（按 appid 隔离）

  - 插件（功能模块）执行统计：调用次数 / 慢调用 / 超时 / 异常 / 平均与最大耗时，含 last_timeout_plugin

  - AI 调用统计：次数 / 失败 / 超时 / 平均与最大耗时，并驱动电路熔断状态机

  - Pipeline 9 阶段计时（message-fetch / pre-process / dispatch-log / dispatch /

    dispatch-respond / produce-respond / ai-think / respond / send），按 appid 隔离

  - WS 连接事件（connect / disconnect 计数、最近连接时间、当前在线状态）



设计原则：

  - 纯标准库，无第三方依赖，避免循环导入（console_server 会 import 本模块）。

  - 全部计数使用 threading.Lock 保护（botpy 事件循环 + 控制台线程并发写）。

  - 单条请求内的 appid 上下文用 contextvars 传递，await 期间自动跟随，

    解决多 bot 并发时的归属错乱（用于 respond/send 阶段的按 bot 归因）。

  - 电路熔断为「监控态」：根据 AI 调用失败率推导 open/closed，仅用于展示，

    不主动阻断 AI 调用，避免影响机器人主功能。

"""



import threading

import time

import contextvars

from collections import defaultdict, deque



# ============ 阈值（可被控制台覆盖，见 set_thresholds） ============

PIPELINE_THRESHOLD_MS = 1000.0   # 单个 pipeline 阶段超过该耗时记为「慢阶段」

PLUGIN_TIMEOUT_MS = 8000.0       # 单个插件执行超过该耗时记为「超时」

AI_CIRCUIT_CONSEC_FAIL = 5       # 连续 AI 失败达到该值 → 电路 open

AI_CIRCUIT_WINDOW = 20           # 电路失败率统计滑动窗口大小

AI_CIRCUIT_FAIL_RATIO = 0.5      # 窗口内失败率超过该值 → 电路 open



# Pipeline 阶段顺序（仅用于前端展示排序）

PIPELINE_STAGES = [

    "message-fetch",    # 事件进入 _dispatch_message 前的框架/网络开销

    "pre-process",      # clean_content + 去重判定

    "dispatch-log",     # record_message 落库

    "dispatch",         # 路由闸门（管理员/关键词/子功能/个人信息）决策耗时

    "dispatch-respond", # 功能模块遍历尝试的总耗时

    "produce-respond",  # 实际命中模块 handle_command 的耗时

    "ai-think",         # chat_with_ai_for_bot 调用耗时

    "respond",          # 组装发送 payload 耗时（common.send_text 内埋点）

    "send",             # 网络发送（HTTP POST）耗时（common.send_text 内埋点）

]



_lock = threading.Lock()



# ============ 进程级计数（按 appid 隔离） ============

_cmd = defaultdict(lambda: {"group": 0, "c2c": 0})      # appid -> {group, c2c}

_event = defaultdict(int)                                # appid -> 群事件处理数

_dedup = defaultdict(int)                                # appid -> 去重命中数



# 插件统计：appid -> {plugin_name: {count, slow, timeout, error, total_ms, max_ms}}

_plugin = defaultdict(lambda: defaultdict(lambda: {

    "count": 0, "slow": 0, "timeout": 0, "error": 0,

    "total_ms": 0.0, "max_ms": 0.0,

}))



# AI 统计：appid -> {count, fail, timeout, total_ms, max_ms}

_ai = defaultdict(lambda: {

    "count": 0, "fail": 0, "timeout": 0, "total_ms": 0.0, "max_ms": 0.0,

})



# 电路熔断：appid -> {state, consecutive_fail, window(list)}

_circuit = defaultdict(lambda: {"state": "closed", "consecutive_fail": 0, "window": deque(maxlen=AI_CIRCUIT_WINDOW)})



# Pipeline 阶段：appid -> {stage: {count, total_ms, max_ms, slow}}

_pipeline = defaultdict(lambda: defaultdict(lambda: {

    "count": 0, "total_ms": 0.0, "max_ms": 0.0, "slow": 0,

}))



# WS 连接：进程级（多 bot 累加）

_ws = {

    "connect": 0,

    "disconnect": 0,

    "last_connect_ts": 0.0,

    "online": False,

}



_first_connect_ts = 0.0          # 首次连接时间，用于计算进程运行时长

_last_timeout_plugin = {}        # appid -> 最近超时的插件名





# 单请求 appid 上下文（contextvars，await 安全）

REQ_APPID = contextvars.ContextVar("bot_appid", default="_shared")





# ============ 写入接口 ============



def set_request_appid(appid):

    """在请求入口设置当前 appid 上下文（供 respond/send 阶段归因）。"""

    REQ_APPID.set(appid or "_shared")





def get_request_appid():

    """读取当前请求上下文的 appid（供 common.py 埋点使用）。"""

    return REQ_APPID.get()





def record_command(appid, scene):

    """命令处理器 +1。scene: group / c2c / channel（channel 归到 c2c）。"""

    key = "c2c" if scene in ("c2c", "channel", "dm") else "group"

    with _lock:

        _cmd[appid][key] += 1





def record_event(appid):

    """群生命周期事件处理器 +1。"""

    with _lock:

        _event[appid] += 1





def record_dedup(appid):

    """消息去重命中 +1。"""

    with _lock:

        _dedup[appid] += 1





def record_plugin(appid, name, ms, timed_out=False, error=False):

    """记录一次插件（功能模块）执行。



    ms: 耗时（毫秒）；timed_out: 是否超过 PLUGIN_TIMEOUT_MS；error: 是否抛异常。

    """

    ms = float(ms)

    with _lock:

        st = _plugin[appid][name]

        st["count"] += 1

        st["total_ms"] += ms

        if ms > st["max_ms"]:

            st["max_ms"] = ms

        if ms > PIPELINE_THRESHOLD_MS:

            st["slow"] += 1

        if error:

            st["error"] += 1

        if timed_out or ms > PLUGIN_TIMEOUT_MS:

            st["timeout"] += 1

            _last_timeout_plugin[appid] = name





def record_ai_call(appid, ms, ok, timed_out=False):

    """记录一次 AI 调用并驱动电路熔断状态机。



    ok: 是否成功；timed_out: 是否超时失败。

    """

    ms = float(ms)

    with _lock:

        st = _ai[appid]

        st["count"] += 1

        st["total_ms"] += ms

        if ms > st["max_ms"]:

            st["max_ms"] = ms

        cb = _circuit[appid]

        cb["window"].append(bool(ok))

        if ok:

            cb["consecutive_fail"] = 0

        else:

            st["fail"] += 1

            if timed_out:

                st["timeout"] += 1

            cb["consecutive_fail"] += 1

        # 推导熔断状态

        if cb["consecutive_fail"] >= AI_CIRCUIT_CONSEC_FAIL:

            cb["state"] = "open"

        else:

            w = list(cb["window"])

            if w and (sum(1 for x in w if not x) / len(w)) > AI_CIRCUIT_FAIL_RATIO:

                cb["state"] = "open"

            else:

                cb["state"] = "closed"





def record_stage(appid, stage, ms):

    """记录一个 pipeline 阶段耗时（毫秒）。"""

    if stage not in PIPELINE_STAGES:

        return

    ms = float(ms)

    with _lock:

        st = _pipeline[appid][stage]

        st["count"] += 1

        st["total_ms"] += ms

        if ms > st["max_ms"]:

            st["max_ms"] = ms

        if ms > PIPELINE_THRESHOLD_MS:

            st["slow"] += 1





def record_ws(kind):

    """记录 WS 连接事件。kind: 'connect' / 'disconnect'。"""

    global _first_connect_ts

    with _lock:

        if kind == "connect":

            _ws["connect"] += 1

            _ws["last_connect_ts"] = time.time()

            _ws["online"] = True

            if _first_connect_ts == 0.0:

                _first_connect_ts = time.time()

        elif kind == "disconnect":

            _ws["disconnect"] += 1

            _ws["online"] = False





# ============ 读取接口 ============



def _avg(total, count):

    return round(total / count, 2) if count else 0.0





def build_snapshot():

    """构建供 /api/health 返回的健康快照（可 JSON 序列化）。"""

    with _lock:

        now = time.time()

        uptime_s = round(now - _first_connect_ts, 1) if _first_connect_ts else 0.0



        cmd = {a: dict(v) for a, v in _cmd.items()}

        event = {a: v for a, v in _event.items()}

        dedup = {a: v for a, v in _dedup.items()}



        plugin = {}

        for a, pmap in _plugin.items():

            plugin[a] = {}

            for name, st in pmap.items():

                plugin[a][name] = {

                    "count": st["count"],

                    "slow": st["slow"],

                    "timeout": st["timeout"],

                    "error": st["error"],

                    "avg_ms": _avg(st["total_ms"], st["count"]),

                    "max_ms": round(st["max_ms"], 1),

                }



        ai = {}

        for a, st in _ai.items():

            ai[a] = {

                "count": st["count"],

                "fail": st["fail"],

                "timeout": st["timeout"],

                "avg_ms": _avg(st["total_ms"], st["count"]),

                "max_ms": round(st["max_ms"], 1),

            }



        circuit = {}

        for a, cb in _circuit.items():

            w = list(cb["window"])

            fail_ratio = round(sum(1 for x in w if not x) / len(w), 2) if w else 0.0

            circuit[a] = {

                "state": cb["state"],

                "consecutive_fail": cb["consecutive_fail"],

                "fail_ratio": fail_ratio,

                "window_size": len(w),

            }



        pipeline = {}

        for a, pmap in _pipeline.items():

            pipeline[a] = {}

            for stage, st in pmap.items():

                pipeline[a][stage] = {

                    "count": st["count"],

                    "avg_ms": _avg(st["total_ms"], st["count"]),

                    "max_ms": round(st["max_ms"], 1),

                    "slow": st["slow"],

                }



        return {

            "metrics": {

                "command": cmd,

                "event": event,

                "dedup": dedup,

                "ws": {

                    "connect": _ws["connect"],

                    "disconnect": _ws["disconnect"],

                    "last_connect_ts": _ws["last_connect_ts"],

                    "online": _ws["online"],

                },

            },

            "plugins": plugin,

            "ai": ai,

            "circuit_breaker": circuit,

            "pipeline_stages": pipeline,

            "last_timeout_plugin": {a: v for a, v in _last_timeout_plugin.items()},

            "pipeline_threshold_ms": PIPELINE_THRESHOLD_MS,

            "plugin_timeout_ms": PLUGIN_TIMEOUT_MS,

            "uptime_s": uptime_s,

        }
