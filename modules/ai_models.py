"""
AI 大模型统一接入层（OpenAI 兼容协议）
所有 provider 通过 base_url + api_key + model_id 接入，支持硅基流动 / DeepSeek / Kimi / Ollama / 自定义。
"""
import os
import json
import time
import threading
import urllib.request
import urllib.error
from typing import Optional, List, Dict, Tuple

from .common import logger, data_path

# ===== 配置 =====
_AI_MODELS_FILE = data_path("ai_models.json")
_REQUEST_TIMEOUT = 30  # 单次请求超时（秒）

# 内存缓存（启动加载 + 写文件后 reload）
_models_cache: List[Dict] = []
_models_lock = threading.Lock()


def _load_models():
    """从文件加载模型列表到内存"""
    global _models_cache
    try:
        if os.path.exists(_AI_MODELS_FILE):
            with open(_AI_MODELS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            _models_cache = data.get("models", [])
        else:
            _models_cache = []
    except Exception as e:
        logger.warning("[AI模型] 加载配置文件失败: %s" % e)
        _models_cache = []


def _save_models():
    """保存内存模型列表到文件"""
    try:
        os.makedirs(os.path.dirname(_AI_MODELS_FILE), exist_ok=True)
        with _models_lock:
            with open(_AI_MODELS_FILE, "w", encoding="utf-8") as f:
                json.dump({"models": _models_cache}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("[AI模型] 保存配置文件失败: %s" % e)


# 启动时加载一次
_load_models()


# ===== CRUD =====
def list_models() -> List[Dict]:
    """返回所有模型配置列表（拷贝）"""
    with _models_lock:
        return list(_models_cache)


def get_model(model_id: str) -> Optional[Dict]:
    """按 id 查找单个模型"""
    with _models_lock:
        for m in _models_cache:
            if m.get("id") == model_id:
                return dict(m)
    return None


def get_default_model() -> Optional[Dict]:
    """获取默认模型（is_default=True 的那一个，启用优先）"""
    with _models_lock:
        # 优先返回 is_default=True 且 enabled=True
        for m in _models_cache:
            if m.get("is_default") and m.get("enabled"):
                return dict(m)
        # 否则返回第一个 enabled
        for m in _models_cache:
            if m.get("enabled"):
                return dict(m)
        # 都没启用，返回第一个
        if _models_cache:
            return dict(_models_cache[0])
    return None


def add_model(model: Dict) -> Tuple[bool, str]:
    """新增一个模型。返回 (成功, 错误信息)"""
    with _models_lock:
        # id 必填且唯一
        mid = (model.get("id") or "").strip()
        if not mid:
            return False, "id 不能为空"
        for m in _models_cache:
            if m.get("id") == mid:
                return False, "id 已存在：%s" % mid
        # 必要字段校验
        for k in ("name", "base_url", "model_id"):
            if not model.get(k):
                return False, "%s 不能为空" % k
        # 兜底默认值
        new = {
            "id": mid,
            "name": model["name"],
            "provider": model.get("provider", "custom"),
            "base_url": model["base_url"].rstrip("/"),
            "api_key": model.get("api_key", ""),
            "model_id": model["model_id"],
            "enabled": bool(model.get("enabled", True)),
            "is_default": False,  # 新增的默认不是 default（避免误覆盖）
            "note": model.get("note", ""),
        }
        # 若当前没有任何 default，自动设为默认
        if not any(m.get("is_default") for m in _models_cache):
            new["is_default"] = True
        _models_cache.append(new)
    _save_models()
    logger.info("[AI模型] 新增：%s（%s，%s）" % (new["id"], new["name"], new["provider"]))
    return True, ""


def update_model(model_id: str, updates: Dict) -> Tuple[bool, str]:
    """更新一个模型。updates 中可包含 name/api_key/enabled/is_default/model_id/note 等。"""
    with _models_lock:
        for m in _models_cache:
            if m.get("id") == model_id:
                # is_default 互斥：只有一个可以是 default
                if "is_default" in updates and updates["is_default"]:
                    for other in _models_cache:
                        if other.get("id") != model_id:
                            other["is_default"] = False
                # 不允许改 id 和 provider（避免破坏引用）
                for k in ("name", "base_url", "api_key", "model_id", "enabled", "is_default", "note"):
                    if k in updates:
                        m[k] = updates[k]
                break
        else:
            return False, "模型不存在：%s" % model_id
    _save_models()
    logger.info("[AI模型] 更新：%s（%s）" % (model_id, ", ".join("%s=%s" % (k, v) for k, v in updates.items())))
    return True, ""


def delete_model(model_id: str) -> Tuple[bool, str]:
    """删除一个模型"""
    with _models_lock:
        for i, m in enumerate(_models_cache):
            if m.get("id") == model_id:
                # 不允许删除默认模型（避免 bot 找不到默认）
                if m.get("is_default"):
                    return False, "不能删除默认模型，请先将其他模型设为默认"
                _models_cache.pop(i)
                break
        else:
            return False, "模型不存在：%s" % model_id
    _save_models()
    logger.info("[AI模型] 删除：%s" % model_id)
    return True, ""


def set_default_model(model_id: str) -> Tuple[bool, str]:
    """将指定模型设为默认（同时清空其他 default）"""
    return update_model(model_id, {"is_default": True})


# ===== 调用 =====
def _do_request(model: Dict, messages: List[Dict], temperature: float = 0.7, max_tokens: int = 1024) -> Tuple[bool, str]:
    """统一 OpenAI 兼容 chat completions 请求"""
    url = model["base_url"].rstrip("/") + "/chat/completions"
    headers = {
        "Content-Type": "application/json",
    }
    if model.get("api_key"):
        headers["Authorization"] = "Bearer " + model["api_key"]
    payload = {
        "model": model["model_id"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers, method="POST",
        )
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            body = resp.read().decode("utf-8", "replace")
            data = json.loads(body)
            # OpenAI 兼容格式：choices[0].message.content
            if "choices" in data and len(data["choices"]) > 0:
                return True, data["choices"][0]["message"]["content"]
            # 部分 provider 错误格式
            if "error" in data:
                return False, "API 返回错误：%s" % str(data["error"])[:300]
            return False, "响应格式异常：%s" % str(data)[:300]
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        return False, "HTTP %d：%s" % (e.code, body)
    except urllib.error.URLError as e:
        return False, "网络错误：%s" % e.reason
    except Exception as e:
        return False, "异常：%s" % str(e)[:300]


def ai_chat(prompt: str, system: str = "", model_id: str = None, temperature: float = 0.7, max_tokens: int = 1024) -> Tuple[bool, str, str]:
    """统一对话接口。
    返回 (成功, 内容, 使用的模型id)
    model_id=None 时用默认模型。
    """
    target = get_model(model_id) if model_id else get_default_model()
    if not target:
        return False, "未配置任何 AI 模型，请到控制台「AI 模型」页面添加", ""
    if not target.get("enabled", True):
        return False, "模型「%s」已禁用，请到控制台启用或切换默认模型" % target.get("name", target.get("id")), target.get("id", "")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    ok, content = _do_request(target, messages, temperature=temperature, max_tokens=max_tokens)
    return ok, content, target.get("id", "")


def ai_test(model_id: str, prompt: str = "你好，请用一句话自我介绍。") -> Tuple[bool, str, str]:
    """连通性测试。返回 (成功, 响应内容或错误, 延迟ms)"""
    model = get_model(model_id)
    if not model:
        return False, "模型不存在：%s" % model_id, "0"
    messages = [{"role": "user", "content": prompt}]
    t0 = time.time()
    ok, content = _do_request(model, messages, temperature=0.5, max_tokens=64)
    elapsed_ms = str(int((time.time() - t0) * 1000))
    return ok, content, elapsed_ms