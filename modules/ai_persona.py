# -*- coding: utf-8 -*-
"""AI 人格设置与知识库（按机器人物理隔离：data/bots/<appid>/ai_persona.json 等）。

- 人格：data/bots/<appid>/ai_persona.json -> {"personas": [{id,name,active,prompt,...}]}
- 知识库：data/bots/<appid>/ai_knowledge.json -> {"bases": [{id,name,active,items:[...]}]}

每个机器人独立文件；未单独配置的机器人回退 data/bots/_shared/（迁移自旧版全局文件）。
所有公开函数均接受 bot 参数（appid 或运行期 name_rt，经 resolve_bot_key 解析为稳定 appid）。
多人格单选使用中；多知识库可各自开启使用中并聚合注入 AI。
兼容旧版 {"prompt": "..."} / {"items": [...]} 结构。
"""
import os
import json
import threading
import time

from .common import logger, data_path
from console_server import resolve_bot_key

# 物理隔离根：未解析/默认机器人落到 _shared
_SHARED = "_shared"

# 每机器人内存缓存：appid -> {"personas":[], "persona_seq":0, "bases":[], "base_seq":0, "item_seq":0}
_state_by_bot = {}

_lock = threading.Lock()
_file_lock = threading.Lock()


def _resolve_appid(bot):
    if not bot:
        return _SHARED
    return resolve_bot_key(bot) or _SHARED


def _persona_file(appid):
    return data_path("bots/%s/ai_persona.json" % appid)


def _knowledge_file(appid):
    return data_path("bots/%s/ai_knowledge.json" % appid)


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _migrate_base(old_items):
    now = _now()
    for it in old_items:
        it.setdefault("enabled", True)
        it.setdefault("title", "")
        it.setdefault("content", "")
    return {
        "id": 1, "name": "默认知识库", "active": True,
        "created_at": now, "updated_at": now, "items": old_items,
    }


def _load_into(appid, st):
    """从磁盘加载 appid 的人格/知识到 st（内存缓存）。"""
    # 人格
    pf = _persona_file(appid)
    try:
        if os.path.exists(pf):
            with open(pf, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and "personas" not in d and "prompt" in d:
                p = (d.get("prompt") or "").strip()
                st["personas"] = [{
                    "id": 1, "name": "默认人格", "active": True,
                    "prompt": p, "created_at": _now(), "updated_at": _now(),
                }] if p else []
            else:
                personas = (d.get("personas", []) if isinstance(d, dict) else []) or []
                for p in personas:
                    p.setdefault("id", 0)
                    p.setdefault("name", "未命名人格")
                    p.setdefault("active", False)
                    p.setdefault("prompt", "")
                    p.setdefault("created_at", "")
                    p.setdefault("updated_at", "")
                st["personas"] = personas
            st["persona_seq"] = max([int(p.get("id", 0) or 0) for p in st["personas"]] or [0])
    except Exception as e:
        logger.warning("[AI人格] 加载失败(%s): %s" % (appid, e))
        st["personas"] = []
    # 知识库
    kf = _knowledge_file(appid)
    try:
        if os.path.exists(kf):
            with open(kf, "r", encoding="utf-8") as f:
                d = json.load(f)
            bases = d.get("bases")
            if bases is None and isinstance(d, dict) and "items" in d:
                bases = [_migrate_base(d.get("items", []) or [])]
            bases = bases or []
            for b in bases:
                b.setdefault("name", "未命名知识库")
                b.setdefault("active", True)
                b.setdefault("items", [])
                b.setdefault("created_at", "")
                b.setdefault("updated_at", "")
                for it in b["items"]:
                    it.setdefault("enabled", True)
                    it.setdefault("title", "")
                    it.setdefault("content", "")
            st["bases"] = bases
            st["base_seq"] = max([int(b.get("id", 0) or 0) for b in st["bases"]] or [0])
            max_item = 0
            for b in st["bases"]:
                for it in b.get("items", []):
                    max_item = max(max_item, int(it.get("id", 0) or 0))
            st["item_seq"] = max_item
    except Exception as e:
        logger.warning("[AI知识库] 加载失败(%s): %s" % (appid, e))
        st["bases"] = []


def _get_state(appid):
    with _lock:
        st = _state_by_bot.get(appid)
        if st is not None:
            return st
        st = {"personas": [], "persona_seq": 0, "bases": [], "base_seq": 0, "item_seq": 0}
        _state_by_bot[appid] = st
        if os.path.exists(_persona_file(appid)) or os.path.exists(_knowledge_file(appid)):
            _load_into(appid, st)
        elif appid != _SHARED and (os.path.exists(_persona_file(_SHARED)) or os.path.exists(_knowledge_file(_SHARED))):
            # 回退 _shared（仅读取，写入仍落本 bot 文件）
            _load_into(_SHARED, st)
        return st


def _save_persona(appid):
    st = _get_state(appid)
    try:
        fpath = _persona_file(appid)
        d = os.path.dirname(fpath)
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        with _file_lock:
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump({"personas": st["personas"]}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("[AI人格] 保存失败(%s): %s" % (appid, e))


def _save_knowledge(appid):
    st = _get_state(appid)
    try:
        fpath = _knowledge_file(appid)
        d = os.path.dirname(fpath)
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        with _file_lock:
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump({"bases": st["bases"]}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("[AI知识库] 保存失败(%s): %s" % (appid, e))


def _find_persona(st, pid):
    for p in st["personas"]:
        if p.get("id") == pid:
            return p
    return None


def _find_base(st, base_id):
    for b in st["bases"]:
        if b.get("id") == base_id:
            return b
    return None


# ===== 人格（多人格，单选使用中） =====
def get_persona_prompt(bot=""):
    """返回当前「使用中」人格的 prompt；无人格或都未启用则返回空。"""
    st = _get_state(_resolve_appid(bot))
    with _lock:
        for p in st["personas"]:
            if p.get("active", False):
                return (p.get("prompt", "") or "").strip()
    return ""


def get_personas(bot=""):
    """返回全部人格（深拷贝），供后台展示。"""
    st = _get_state(_resolve_appid(bot))
    with _lock:
        return json.loads(json.dumps(st["personas"]))


def get_active_persona(bot=""):
    """返回当前「使用中」的人格 dict（深拷贝）或 None。"""
    st = _get_state(_resolve_appid(bot))
    with _lock:
        for p in st["personas"]:
            if p.get("active", False):
                return json.loads(json.dumps(p))
    return None


def add_persona(name="", prompt="", active=False, bot=""):
    appid = _resolve_appid(bot)
    st = _get_state(appid)
    name = (name or "").strip() or "未命名人格"
    with _lock:
        st["persona_seq"] += 1
        now = _now()
        persona = {
            "id": st["persona_seq"], "name": name, "active": bool(active),
            "prompt": (prompt or "").strip(), "created_at": now, "updated_at": now,
        }
        st["personas"].append(persona)
    _save_persona(appid)
    logger.info("[AI人格] 新建(%s)：%s（active=%s）" % (appid, name, persona["active"]))
    return True, "", persona["id"]


def update_persona(pid, name=None, prompt=None, active=None, bot=""):
    appid = _resolve_appid(bot)
    st = _get_state(appid)
    with _lock:
        p = _find_persona(st, pid)
        if not p:
            return False, "人格不存在"
        if name is not None:
            p["name"] = (name.strip() or p["name"])
        if prompt is not None:
            p["prompt"] = prompt.strip()
        if active is not None:
            p["active"] = bool(active)
        p["updated_at"] = _now()
    _save_persona(appid)
    return True, ""


def delete_persona(pid, bot=""):
    appid = _resolve_appid(bot)
    st = _get_state(appid)
    with _lock:
        before = len(st["personas"])
        st["personas"] = [p for p in st["personas"] if p.get("id") != pid]
        if len(st["personas"]) < before:
            _save_persona(appid)
            return True
    return False


def set_active_persona(pid, bot=""):
    """将 pid 设为「使用中」，其余全部取消。返回 (ok, msg)。"""
    appid = _resolve_appid(bot)
    st = _get_state(appid)
    with _lock:
        found = False
        for p in st["personas"]:
            if p.get("id") == pid:
                p["active"] = True
                found = True
            else:
                p["active"] = False
        if found:
            _save_persona(appid)
            return True, ""
    return False, "人格不存在"


def clear_active_persona(bot=""):
    """取消所有人格的「使用中」状态（回到模型默认人设）。"""
    appid = _resolve_appid(bot)
    st = _get_state(appid)
    with _lock:
        changed = False
        for p in st["personas"]:
            if p.get("active", False):
                p["active"] = False
                changed = True
        if changed:
            _save_persona(appid)
    return True, ""


# ===== 知识库（多库） =====
def get_all_knowledge_bases(bot=""):
    """返回全部知识库（含条目），供后台管理展示。返回深拷贝。"""
    st = _get_state(_resolve_appid(bot))
    with _lock:
        return json.loads(json.dumps(st["bases"]))


def get_active_knowledge_items(bot=""):
    """聚合所有「使用中」知识库里 enabled 的条目 -> [{"title","content"}]。"""
    st = _get_state(_resolve_appid(bot))
    with _lock:
        out = []
        for b in st["bases"]:
            if not b.get("active", True):
                continue
            for it in b.get("items", []):
                if it.get("enabled", True):
                    out.append({
                        "title": it.get("title", "") or "",
                        "content": it.get("content", "") or "",
                    })
        return out


def add_knowledge_base(name="", active=True, bot=""):
    appid = _resolve_appid(bot)
    st = _get_state(appid)
    name = (name or "").strip() or "未命名知识库"
    with _lock:
        st["base_seq"] += 1
        now = _now()
        base = {
            "id": st["base_seq"], "name": name, "active": bool(active),
            "created_at": now, "updated_at": now, "items": [],
        }
        st["bases"].append(base)
    _save_knowledge(appid)
    logger.info("[AI知识库] 新建知识库(%s)：%s（active=%s）" % (appid, name, base["active"]))
    return True, "", base["id"]


def update_knowledge_base(base_id, name=None, active=None, bot=""):
    appid = _resolve_appid(bot)
    st = _get_state(appid)
    with _lock:
        b = _find_base(st, base_id)
        if not b:
            return False, "知识库不存在"
        if name is not None:
            b["name"] = (name.strip() or b["name"])
        if active is not None:
            b["active"] = bool(active)
        b["updated_at"] = _now()
    _save_knowledge(appid)
    return True, ""


def delete_knowledge_base(base_id, bot=""):
    appid = _resolve_appid(bot)
    st = _get_state(appid)
    with _lock:
        before = len(st["bases"])
        st["bases"] = [b for b in st["bases"] if b.get("id") != base_id]
        if len(st["bases"]) < before:
            _save_knowledge(appid)
            return True
    return False


def add_knowledge_item(base_id, title, content, bot=""):
    appid = _resolve_appid(bot)
    st = _get_state(appid)
    title = (title or "").strip()
    content = (content or "").strip()
    if not title or not content:
        return False, "标题和内容均不能为空"
    with _lock:
        b = _find_base(st, base_id)
        if not b:
            return False, "知识库不存在"
        st["item_seq"] += 1
        now = _now()
        b["items"].append({
            "id": st["item_seq"], "title": title, "content": content,
            "enabled": True, "created_at": now, "updated_at": now,
        })
        b["updated_at"] = now
    _save_knowledge(appid)
    logger.info("[AI知识库] 新增（库#%s,%s）：%s" % (base_id, appid, title))
    return True, ""


def update_knowledge_item(base_id, item_id, title=None, content=None, enabled=None, bot=""):
    appid = _resolve_appid(bot)
    st = _get_state(appid)
    with _lock:
        b = _find_base(st, base_id)
        if not b:
            return False, "知识库不存在"
        for it in b.get("items", []):
            if it.get("id") == item_id:
                if title is not None:
                    it["title"] = title.strip()
                if content is not None:
                    it["content"] = content.strip()
                if enabled is not None:
                    it["enabled"] = bool(enabled)
                it["updated_at"] = _now()
                b["updated_at"] = it["updated_at"]
                _save_knowledge(appid)
                return True, ""
    return False, "条目不存在"


def delete_knowledge_item(base_id, item_id, bot=""):
    appid = _resolve_appid(bot)
    st = _get_state(appid)
    with _lock:
        b = _find_base(st, base_id)
        if not b:
            return False
        before = len(b["items"])
        b["items"] = [it for it in b["items"] if it.get("id") != item_id]
        if len(b["items"]) < before:
            b["updated_at"] = _now()
            _save_knowledge(appid)
            return True
    return False


def build_ai_context(bot=""):
    """返回 (persona_prompt, knowledge_context) 供注入 AI 调用。"""
    persona = get_persona_prompt(bot)
    items = get_active_knowledge_items(bot)
    knowledge_text = ""
    if items:
        blocks = []
        for it in items:
            blocks.append("【%s】\n%s" % (it.get("title", ""), it.get("content", "")))
        knowledge_text = (
            "以下是已知知识库内容，当问题与其中主题相关时，请优先参考并使用这些信息作答：\n"
            + "\n\n".join(blocks)
        )
    return persona, knowledge_text
