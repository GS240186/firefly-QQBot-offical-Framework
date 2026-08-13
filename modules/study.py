# -*- coding: utf-8 -*-
"""
学习系统模块
功能：语文 / 英语 / 数学 / 物理 / 化学 / 生物 / 历史 / 政治 / 地理 九个科目，
      点击按钮后选择「文字题目」或「图片题目」，
      由 Qwen3-1.7B 大模型直接生成【一整道完整题目】 + 答案 + 解析并返回。
  - 每次只出「一整道」完整题目，整题一次性发送，不拆断、不截断。
  - 文字类题目：根据字数长度选择「可复制放大格式」(markdown 卡片) 或「纯文字」发送。
  - 图片类题目：把 AI 生成的题目渲染成图片，直接发送真实图片（不发送图片链接）。
  - 答案与题目分离：题目先发，点「✍️ 作答」按钮进入作答模式，用户发送答案后由 Qwen3-1.7B 判断正误，
    判定后均展示标准答案+解析（合并了原「回答」按钮的看解析能力），并附「➡️ 下一题」「🔙 返回主菜单」；
    点「🔑 答案」按钮仅发送答案（不含解析）。
搜索后端：Qwen3-1.7B（https://openapi.dwo.cc/api/Qwen3_1.7B，免 KEY）。
"""

import re
import os
import io
import time
import asyncio
import json
import urllib.parse
import urllib.request
import urllib.error
import socket
from modules.common import (
    send_text,
    send_text_with_keyboard,
    send_local_image_for_scene,
    logger,
    ChatScene,
)
from modules import config

# ============ User-Agent ============
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Qwen3-1.7B 配置（AI 出题后端）
_QWEN_URL = getattr(config, "QWEN_ENDPOINT", "https://openapi.dwo.cc/api/Qwen3_1.7B")
_QWEN_TIMEOUT = getattr(config, "QWEN_TIMEOUT", 60)
_QWEN_MODEL = getattr(config, "QWEN_MODEL", "") or ""
# 失败自动重试：3 次最多，间隔 2s/4s 指数退避（仅对网络瞬时抖动重试）
_QWEN_RETRY_MAX = int(getattr(config, "QWEN_RETRY_MAX", 3))
_QWEN_RETRY_BACKOFF = float(getattr(config, "QWEN_RETRY_BACKOFF", 2.0))

# 渲染题目图片时使用的系统中文字体（Windows 默认存在）
_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\msyhbd.ttc",
]

# ============ 科目配置 ============
SUBJECTS = ["语文", "英语", "数学", "物理", "化学", "生物", "历史", "政治", "地理"]
_SUBJECT_LABEL = {
    "语文": "📖 语文",
    "英语": "🔤 英语",
    "数学": "➗ 数学",
    "物理": "🔭 物理",
    "化学": "🧪 化学",
    "生物": "🌱 生物",
    "历史": "📜 历史",
    "政治": "🏛 政治",
    "地理": "🌍 地理",
}

# 「换一批」时轮换使用的出题角度提示，提升题目多样性
_VARIANTS = [
    "基础巩固", "进阶提高", "易错专项", "期中期末真题", "生活应用", "经典题型",
]

# 各学科「代表性关键词」——用于本地快检：若生成题目不含任一关键词，
# 视为「可能偏科」，再交由 Qwen 模型做最终判定（避免无谓的二次 API 调用）。
# 仅作为一级粗筛，宁可漏报（触发模型校验）也不要误杀正常题目。
_SUBJECT_KEYWORDS = {
    "语文": ["阅读", "古诗", "文言文", "作文", "词语", "句子", "修辞", "诗词", "文学",
            "标点", "成语", "字音", "字形", "默写", "诗歌", "散文", "小说", "课文",
            "文段", "赏析", "填空", "选择", "注音", "翻译文言文"],
    "英语": ["单词", "语法", "时态", "句型", "翻译", "词汇", "reading", "单选", "完形",
            "cloze", "阅读理解", "choose", "填空", "English", "sentence", "verb",
            "noun", "时态", "语态", "代词", "介词", "短文", "对话"],
    "数学": ["函数", "方程", "计算", "几何", "三角形", "圆", "概率", "统计", "代数",
            "不等式", "数列", "向量", "导数", "积分", "平方", "根号", "周长", "面积",
            "体积", "角", "坐标", "解析", "集合", "矩阵", "sin", "cos", "tan"],
    "物理": ["力", "速度", "加速度", "功", "能量", "电压", "电流", "电阻", "电路",
            "牛顿", "磁场", "光", "波", "密度", "压强", "动量", "电场", "电荷",
            "运动", "机械能", "功率", "浮力", "惯性"],
    "化学": ["元素", "反应", "分子", "原子", "离子", "酸碱", "盐", "氧化还原", "化合",
            "溶液", "摩尔", "燃烧", "催化", "化学", "方程式", "质量", "气体", "沉淀",
            "中和", "电解质", "有机物"],
    "生物": ["细胞", "DNA", "基因", "蛋白质", "光合作用", "呼吸", "进化", "生态", "酶",
            "染色体", "分裂", "种群", "遗传", "神经", "生物", "器官", "组织", "血液",
            "免疫", "病毒"],
    "历史": ["朝代", "战争", "革命", "皇帝", "世纪", "条约", "秦始皇", "唐朝", "宋朝",
            "明朝", "清朝", "改革", "运动", "古代", "近代", "现代", "丝绸之路", "诸侯",
            "封建", "君主", "制度史", "事件"],
    "政治": ["国家", "政府", "人民", "法律", "宪法", "制度", "民主", "经济", "社会",
            "公民", "政策", "政党", "价值观", "哲学", "矛盾", "实践", "权利", "义务",
            "市场", "分配", "治理"],
    "地理": ["地形", "气候", "河流", "山脉", "地球", "赤道", "经纬", "板块", "人口",
            "城市", "农业", "工业", "洋流", "季风", "海拔", "区域", "降水", "气温",
            "植被", "土壤", "资源", "交通"],
}

# 文本题目超过该字数 -> 使用「可复制放大格式」(markdown 卡片)，否则纯文字发送
_TEXT_LONG_THRESHOLD = 500
# 图片题目单次发送的最大张数
_IMAGE_MAX = 4
# 图片题目：单张图片最多渲染的行数（超出自动分页）
_IMAGE_LINES_PER_PAGE = 34


def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "")


def _clean(s: str, limit: int = 0) -> str:
    """去 HTML 实体、压缩空白、截断"""
    s = _html_unescape(_strip_tags(s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    if limit and len(s) > limit:
        s = s[:limit].rstrip() + "…"
    return s


# 轻量 HTML 实体反转义（避免引入额外依赖）
def _html_unescape(s: str) -> str:
    try:
        import html as _html_mod
        return _html_mod.unescape(s)
    except Exception:
        return s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", "\"").replace("&#39;", "'")


def _sanitize_markdown(s: str) -> str:
    """
    去除会干扰 QQ markdown 渲染的结构性字符。
    注意：刻意保留「*」，避免破坏数学乘号（如 2*3）等；仅去掉标题/引用/表格等结构符号。
    """
    return (
        s.replace("#", "")
        .replace(">", "")
        .replace("|", "")
        .replace("\\", "")
        .replace("`", "")
    )


class StudyManager:
    """学习系统 - 语文/英语/数学/物理/化学/生物/历史/政治/地理 AI 出题（文字/图片，单题完整发送）"""

    def __init__(self):
        # (storage_id, subject, qtype) -> 换一批轮换序号
        self._variant = {}
        # (storage_id, subject, qtype) -> 上次的主题（换一批时沿用）
        self._last_topic = {}
        # (storage_id, subject) -> 已生成、待查看的答案+解析（点「查看答案」按钮后发送）
        self._pending_answer = {}
        # storage_id -> 正在等待用户提交答案的科目（点「✍️ 作答」后设置）
        self._awaiting_answer = {}
        # (storage_id, subject) -> 上次出题的题型（文字/图片），用于「下一题」沿用
        self._last_qtype = {}

    # ================================================================
    #                        入口分发
    # ================================================================
    async def handle_command(self, api, content, group_openid, member_openid, msg_id, scene=None):
        """
        统一入口。返回 True 表示已处理。
        指令：
          - 学习菜单                              → 显示科目选择菜单
          - 语文 / 英语 / 数学 / 物理 ...      → 显示该科目的「文字/图片」子菜单
          - 物理文字 / 化学图片               → 对应题型搜索
          - 物理文字 牛顿定律 / 历史文字 朝代  → 带主题搜索
          - 物理文字 换一批 / 化学图片 换一批  → 换一组结果
          - 回答 物理 / 回答 历史             → 查看刚才题目的答案+解析
        注意：「学习」「学习系统」已从精确匹配关键词移除（见 bot.py _EXACT_KEYWORDS 注释），
        因为群里聊天时 @机器人 说这两个词容易被误触发主菜单，会吞掉 AI 对话路径。
        """
        if scene is None:
            scene = ChatScene.GROUP
        text = (content or "").strip()

        # 学习系统入口菜单（只保留「学习菜单」，由按钮点击触发；「学习」「学习系统」已不再走此路径）
        if text == "学习菜单":
            await self._send_menu(api, scene, group_openid, msg_id)
            return True

        # ===== 作答判定模式：若正在等待用户提交答案 =====
        if self.is_awaiting_answer(group_openid):
            # 返回主菜单：退出作答模式，交给 bot.py 主菜单
            if text == "返回主菜单":
                self._awaiting_answer.pop(group_openid, None)
                return False
            # 关键修复：用户在等待答案模式下经常误以为需要加「作答」前缀才提交
            # （如「作答 1和2」「作答 数学1和2」）。这种文本如果被识别为
            # 「作答 科目」指令，会退出等待模式并提示「未知科目」，导致用户
            # 看不到答案判定结果。处理策略：
            #   ① 文本以「作答」开头且后面是已知科目（明确意图重新进入该科目
            #      作答模式），按原指令逻辑处理；
            #   ② 其它情况（任意其他文本），剥离「作答」前缀，把剩余内容
            #      作为答案提交。
            if text.startswith("作答"):
                m_redoe = re.match(r"^作答\s+(\S+)$", text)
                if m_redoe and m_redoe.group(1) in SUBJECTS:
                    # 明确意图：重新进入某科目作答模式
                    self._awaiting_answer.pop(group_openid, None)
                    # 不 return，继续走下面「作答 科目」分支
                else:
                    # 其它情况：剥离「作答」前缀，剩余内容作为答案提交
                    subj = self._awaiting_answer.get(group_openid)
                    self._awaiting_answer.pop(group_openid, None)
                    stripped = re.sub(r"^作答\s*", "", text).strip()
                    if stripped:
                        await self._judge_answer(api, scene, group_openid, subj, stripped, msg_id)
                    # 剥离后为空（用户只发了「作答」两个字）则不报错、直接结束
                    return True
            # 仅当文本命中「正式指令格式」时才退出作答并正常处理；
            # 普通自由文本（用户的回答）一律视作答案去判定，避免「答案是2」被误判为指令。
            # 关键：必须带 qtype（文字/图片）或主题（换一批/主题词）才算指令；
            # 单独的科目名（如「历史」「数学」）可能是用户的答案文本，不应退出作答模式。
            _is_cmd = (
                re.match(r"^(语文|英语|数学|物理|化学|生物|历史|政治|地理)(文字|图片)(?:\s+.+)?$", text)
                or re.match(r"^(作答|回答|查看答案|答案)\s+\S+$", text)
                or re.match(r"^(学习|签到|视频|音乐|娱乐|工具|群管|帮助|菜单|功能|加入|体验|点歌|下棋|"
                            r"天气|王者|绑群号|绑QQ|违禁词|我的信息)$", text)
            )
            if _is_cmd:
                self._awaiting_answer.pop(group_openid, None)
                # 不 return，继续往下走正常指令逻辑
            else:
                subj = self._awaiting_answer.get(group_openid)
                self._awaiting_answer.pop(group_openid, None)
                await self._judge_answer(api, scene, group_openid, subj, text, msg_id)
                return True

        # 作答：进入「等待用户提交答案」状态（点按钮「✍️ 作答」或回复「作答 语文」）
        m = re.match(r"^作答\s+(\S+)$", text)
        if m:
            subject = m.group(1)
            if subject in SUBJECTS:
                await self._start_answering(api, scene, group_openid, msg_id, subject)
            else:
                await send_text(
                    api, scene, group_openid,
                    "📚 未知科目「%s」，无法进入作答。可用：%s。" % (subject, " / ".join(SUBJECTS)),
                    msg_id=msg_id,
                )
            return True

        # 科目 / 题型触发
        m = re.match(r"^(语文|英语|数学|物理|化学|生物|历史|政治|地理)(文字|图片)?(?:\s+(.+))?$", text)
        if m:
            subject = m.group(1)
            qtype_raw = m.group(2)          # None 表示仅输入了科目（如「语文」）
            qtype = qtype_raw or "文字"
            tail = (m.group(3) or "").strip()
            topic = ""
            again = False
            if tail == "换一批":
                again = True
            elif tail:
                topic = tail

            if qtype_raw is None and not tail:
                # 「语文」仅科目、无类型无主题 -> 显示子菜单
                await self._send_submenu(api, scene, group_openid, msg_id, subject)
                return True
            # 其余情况（语文文字 / 语文图片 / 语文文字 古诗 / 语文图片 换一批 等）直接进入查询
            await self._query(api, scene, group_openid, msg_id, subject, qtype, topic, again)
            return True

        # 回答（题目卡片上的「🔓 回答」按钮，或回复「回答 语文」；兼容旧指令「查看答案」）
        # 发送「答案+解析」完整段
        m = re.match(r"^(回答|查看答案)\s+(\S+)$", text)
        if m:
            subject = m.group(2)
            if subject in SUBJECTS:
                await self._send_answer(api, scene, group_openid, msg_id, subject, only=False)
            else:
                await send_text(
                    api, scene, group_openid,
                    "📚 未知科目「%s」，无法查看回答。可用：%s。" % (subject, " / ".join(SUBJECTS)),
                    msg_id=msg_id,
                )
            return True

        # 仅看答案（题目卡片上的「🔑 答案」按钮，或回复「答案 语文」）
        # 仅发送「答案：…」部分，不含解析
        m = re.match(r"^(答案)\s+(\S+)$", text)
        if m:
            subject = m.group(2)
            if subject in SUBJECTS:
                await self._send_answer(api, scene, group_openid, msg_id, subject, only=True)
            else:
                await send_text(
                    api, scene, group_openid,
                    "📚 未知科目「%s」，无法查看答案。可用：%s。" % (subject, " / ".join(SUBJECTS)),
                    msg_id=msg_id,
                )
            return True

        return False

    # ================================================================
    #                        科目菜单
    # ================================================================
    async def _send_menu(self, api, scene, target_id, msg_id):
        title = (
            "📚 学习系统\n"
            "━━━━━━━━━━━━━━━\n"
            "选择科目，AI（Qwen3-1.7B）将为你生成题目与解析\n"
            "（点科目后可选择「文字题目」或「图片题目」）"
        )
        rows = [{
            "buttons": [
                self._btn(_SUBJECT_LABEL["语文"], "语文"),
                self._btn(_SUBJECT_LABEL["英语"], "英语"),
                self._btn(_SUBJECT_LABEL["数学"], "数学"),
                self._btn(_SUBJECT_LABEL["物理"], "物理"),
            ]
        }, {
            "buttons": [
                self._btn(_SUBJECT_LABEL["化学"], "化学"),
                self._btn(_SUBJECT_LABEL["生物"], "生物"),
                self._btn(_SUBJECT_LABEL["历史"], "历史"),
                self._btn(_SUBJECT_LABEL["政治"], "政治"),
            ]
        }, {
            "buttons": [
                self._btn(_SUBJECT_LABEL["地理"], "地理"),
                self._btn("🔙 返回主菜单", "返回主菜单"),
            ]
        }]
        keyboard = {"content": {"rows": rows}}
        try:
            await send_text_with_keyboard(api, scene, target_id, title, keyboard, msg_id=msg_id)
        except Exception as e:
            logger.error("[学习] 发送科目菜单失败: %s" % e)
            await send_text(api, scene, target_id, title, msg_id=msg_id)

    # ================================================================
    #                     科目 -> 题型子菜单
    # ================================================================
    async def _send_submenu(self, api, scene, target_id, msg_id, subject):
        label = _SUBJECT_LABEL[subject]
        title = (
            "📚 %s · 选择题目类型\n"
            "━━━━━━━━━━━━━\n"
            "请选择你想要的题型："
        ) % label
        rows = [{
            "buttons": [
                self._btn("📝 文字题目", "%s文字" % subject),
                self._btn("🖼 图片题目", "%s图片" % subject),
            ]
        }, {
            "buttons": [self._btn("🔙 返回主菜单", "返回主菜单")],
        }]
        keyboard = {"content": {"rows": rows}}
        try:
            await send_text_with_keyboard(api, scene, target_id, title, keyboard, msg_id=msg_id)
        except Exception as e:
            logger.error("[学习] 发送题型子菜单失败: %s" % e)
            await send_text(api, scene, target_id, title, msg_id=msg_id)

    @staticmethod
    def _btn(label, command):
        return {
            "id": "btn_" + command,
            "render_data": {"label": label, "visited_label": label, "style": 1},
            "action": {
                "type": 2,
                "permission": {"type": 2},
                "data": command,
                "enter": True,
                "unsupport_tips": "请更新QQ版本",
            },
        }

    # ================================================================
    #                        Qwen3-1.7B 出题
    # ================================================================
    @staticmethod
    def _build_prompt(subject: str, topic: str, variant: str = None) -> str:
        """构造让大模型出题目的系统指令（每次只出一整道完整题目）。"""
        scope = "「%s」相关主题" % topic if topic else "该科目常见内容"
        angle = "（侧重：%s）" % variant if variant else ""
        return (
            "你是一位【只负责%s】的资深初中/高中老师。你出的每一道题都必须严格属于「%s」学科，"
            "不得混入其他学科的知识点。请围绕%s%s，出一整道典型且完整的题目，"
            "并附上【答案】与【解析】。\n"
            "要求：\n"
            "1. 必须是【一整道】完整、独立的题目（包含题干与必要已知条件），难度适中、贴近考试常见考法；\n"
            "2. 只出 1 道题，用「第1题」开头，不要再出第 2、3 题；\n"
            "3. 题目之后紧跟「答案：」与「解析：」；\n"
            "4. 只输出题目、答案、解析，不要寒暄、不要重复指令、不要使用 Markdown 代码块；\n"
            "5. 答案与解析必须一致（答案栏填写的最终结果要和解析计算出的结果相同）；\n"
            "6. 数学公式一律用纯文本表达，严禁 LaTeX / TeX 符号：\n"
            "   - 不用 $ 包裹公式；\n"
            "   - 分数写成 (2x+1)/(x-3)；\n"
            "   - 根号写成 sqrt(x) 或 √(x)；\n"
            "   - 乘号写成 * （如 2*3）；\n"
            "   - 幂写成 x^2；\n"
            "   - 不要出现反斜杠 \\ 与命令式写法（如 \\frac、\\sqrt）。\n"
            "7. 题目正文中不要出现「答案」二字（答案只写在「答案：」字段），"
            "以便系统将题目与答案自动分开展示。\n"
            "8. 题目必须严格属于「%s」学科；若你对某个知识点归属不确定，"
            "请选择该学科最经典、无争议的题目，严禁产出其他学科的题目。\n"
            "请直接开始出这一整道题。"
            % (subject, subject, scope, angle, subject)
        )

    # 哪些异常算「可重试」（网络瞬时抖动/CDN 边节点失效）
    _RETRYABLE_EXC = (socket.timeout, ConnectionError, urllib.error.URLError)

    def _call_qwen_sync(self, prompt: str) -> str:
        """同步调用 Qwen3-1.7B，返回模型生成的文本；失败返回空串。
        失败自动重试：次数由 _QWEN_RETRY_MAX 控制，间隔 _QWEN_RETRY_BACKOFF 指数退避。
        仅 5xx / Timeout / 连接错误 / URLError 这类网络抖动触发；解析错误/代码异常立即返回。
        """
        payload = {"prompt": prompt}
        if _QWEN_MODEL:
            payload["model"] = _QWEN_MODEL
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": _UA,
            "Accept": "application/json",
        }

        last_err = None
        for attempt in range(1, _QWEN_RETRY_MAX + 1):
            try:
                req = urllib.request.Request(_QWEN_URL, data=data, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=_QWEN_TIMEOUT) as resp:
                    obj = json.loads(resp.read().decode("utf-8", "ignore"))
                # HTTP 200：处理业务码
                if obj.get("code") not in (200, None):
                    # 4xx 业务错误（如 429 限流、KEY 无效）立即返回，不重试
                    if isinstance(obj.get("code"), int) and 400 <= obj["code"] < 500:
                        logger.error("[学习] Qwen3 业务错误 (4xx): %s" % obj)
                        return ""
                    # 5xx 平台侧故障：可重试
                    last_err = "HTTP %s: %s" % (obj.get("code"), obj.get("msg"))
                    logger.warning("[学习] Qwen3 返回 5xx，第 %d/%d 次重试: %s"
                                   % (attempt, _QWEN_RETRY_MAX, last_err))
                else:
                    d = obj.get("data") or {}
                    text = (d.get("content") or obj.get("msg") or "").strip()
                    if text:
                        if attempt > 1:
                            logger.info("[学习] Qwen3 第 %d 次重试成功" % attempt)
                        return text
                    # 200 但 content 为空：可能是上游临时问题，可重试
                    last_err = "Qwen3 返回 200 但 content 为空"
                    logger.warning("[学习] %s，第 %d/%d 次重试" % (last_err, attempt, _QWEN_RETRY_MAX))
            except urllib.error.HTTPError as e:
                # HTTP 4xx 业务错误：不重试；5xx/CDN 错误：重试
                if 400 <= e.code < 500:
                    logger.error("[学习] Qwen3 HTTP %s (4xx，不重试): %s" % (e.code, e))
                    return ""
                last_err = "HTTP %s: %s" % (e.code, e)
                logger.warning("[学习] Qwen3 %s，第 %d/%d 次重试" % (last_err, attempt, _QWEN_RETRY_MAX))
            except self._RETRYABLE_EXC as e:
                last_err = "%s: %s" % (type(e).__name__, e)
                logger.warning("[学习] Qwen3 网络抖动 %s，第 %d/%d 次重试" % (last_err, attempt, _QWEN_RETRY_MAX))
            except Exception as e:
                # 其它异常（JSON 解析、未知错误）立即返回，避免静默吞掉
                logger.error("[学习] Qwen3 调用异常 (不重试): %s" % e)
                return ""

            # 重试间隔：第 N 次失败后等 2^(N-1) * BACKOFF 秒（2 / 4 / 8）
            if attempt < _QWEN_RETRY_MAX:
                time.sleep(_QWEN_RETRY_BACKOFF * (2 ** (attempt - 1)))

        logger.error("[学习] Qwen3 经 %d 次重试仍失败：%s" % (_QWEN_RETRY_MAX, last_err))
        return ""

    # ================================================================
    #              学科一致性校验（两级：本地快检 + 模型判定）
    # ================================================================
    @staticmethod
    def _validate_subject_local(subject: str, content: str) -> bool:
        """一级校验：本地关键词粗筛。命中任一学科关键词即视为通过（不触发模型校验）。"""
        kws = _SUBJECT_KEYWORDS.get(subject)
        if not kws:
            return True
        for kw in kws:
            if kw in (content or ""):
                return True
        return False

    async def _validate_subject_by_model(self, subject: str, content: str) -> bool:
        """二级校验：交由 Qwen3-1.7B 判定题目是否属于该学科。
        校验失败（异常）时默认通过，避免阻断正常出题干。
        """
        prompt = (
            "请判断下面这道题是否属于「%s」学科。\n题目：%s\n"
            "只回答「是」或「否」两个字，不要解释。" % (subject, (content or "")[:500])
        )
        try:
            r = await asyncio.to_thread(self._call_qwen_sync, prompt)
        except Exception as e:
            logger.error("[学习] 学科校验异常: %s" % e)
            return True
        r = (r or "").strip()
        if r[:2].startswith("否"):
            return False
        if "否" in r[:6]:
            return False
        return True

    async def _generate_question(self, subject: str, topic: str, variant: str = None,
                                 max_retry: int = 1) -> str:
        """
        统一出题入口：调用 Qwen3-1.7B 生成题目，并做学科一致性校验。
        - 本地关键词快检命中 -> 直接采用；
        - 本地未命中 -> 模型判定，判定通过则采用；
        - 判定偏离学科 -> 最多 max_retry 次「纠正重出」，每次都加强学科约束；
        - 若反复偏离，返回最后一次内容（尽量可用），由调用方提示用户可「换一批」。
        返回题目原始文本（含答案+解析），空串表示接口失败。
        """
        prompt = self._build_prompt(subject, topic, variant)
        try:
            content = await asyncio.to_thread(self._call_qwen_sync, prompt)
        except Exception as e:
            logger.error("[学习] 出题异常(%s): %s" % (subject, e))
            content = ""
        if not content:
            return ""

        # 一级：本地快检命中即采用，省去模型校验调用
        if self._validate_subject_local(subject, content):
            return content
        # 二级：模型判定
        if await self._validate_subject_by_model(subject, content):
            return content

        # 偏离学科：纠正重出
        logger.warning("[学习] 题目偏离学科(%s)，启动纠正重出" % subject)
        for _ in range(max_retry):
            prompt2 = (
                self._build_prompt(subject, topic, variant)
                + "\n\n（重要：你刚才生成的题目不属于「%s」学科，请务必重新出一道"
                  "严格属于「%s」学科的典型题目，不要混入其他学科内容。）"
                  % (subject, subject)
            )
            try:
                content2 = await asyncio.to_thread(self._call_qwen_sync, prompt2)
            except Exception as e:
                logger.error("[学习] 纠正出题异常(%s): %s" % (subject, e))
                break
            if not content2:
                break
            if self._validate_subject_local(subject, content2) \
                    or await self._validate_subject_by_model(subject, content2):
                return content2
            content = content2  # 仍偏离，继续下一轮（若还有次数）
        return content

    # ================================================================
    #                  题目图片渲染（PIL -> PNG bytes）
    # ================================================================
    @staticmethod
    def _render_text_to_images(text: str, max_pages: int = 4):
        """
        把题目文本渲染成一张或多张 PNG 图片的 bytes 列表（用于图片题目直发）。
        依赖 Pillow + 系统中文字体；若不可用返回空列表（调用方降级为文字卡片）。
        """
        try:
            from PIL import Image, ImageDraw, ImageFont
        except Exception as e:
            logger.error("[学习] 图片渲染缺少 Pillow: %s" % e)
            return []

        font_path = None
        for p in _FONT_CANDIDATES:
            if os.path.exists(p):
                font_path = p
                break
        if not font_path:
            logger.error("[学习] 未找到中文字体，无法渲染题目图片")
            return []

        try:
            font = ImageFont.truetype(font_path, 30)
            font_title = ImageFont.truetype(font_path, 36)
        except Exception as e:
            logger.error("[学习] 加载字体失败: %s" % e)
            return []

        # 画布参数
        width = 960
        margin_x = 50
        margin_y = 50
        line_h = 46
        max_chars = 26  # 每行大约字符数（中文按全角估算）

        # 预处理：按换行符拆，超长行按字符数硬折行
        raw_lines = []
        for para in (text or "").split("\n"):
            para = para.rstrip()
            if not para:
                raw_lines.append("")
                continue
            for i in range(0, len(para), max_chars):
                raw_lines.append(para[i:i + max_chars])

        # 按页切分
        pages = []
        cur = []
        for ln in raw_lines:
            cur.append(ln)
            if len(cur) >= _IMAGE_LINES_PER_PAGE:
                pages.append(cur)
                cur = []
        if cur:
            pages.append(cur)
        pages = pages[:max_pages]

        images = []
        for idx, lines in enumerate(pages, 1):
            h = margin_y * 2 + len(lines) * line_h + 30
            img = Image.new("RGB", (width, h), (255, 255, 255))
            draw = ImageDraw.Draw(img)
            y = margin_y
            for ln in lines:
                fnt = font_title if (ln.startswith("第") and "题" in ln) else font
                # 标题行加粗蓝字，其余黑色
                color = (20, 20, 120) if (ln.startswith("第") and "题" in ln) else (30, 30, 30)
                draw.text((margin_x, y), ln, font=fnt, fill=color)
                y += line_h
            if len(pages) > 1:
                draw.text((width - 160, h - 40), "（%d/%d）" % (idx, len(pages)),
                          font=font, fill=(150, 150, 150))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            images.append(buf.getvalue())
        return images

    # ================================================================
    #                   题目 / 答案 拆分与查看答案
    # ================================================================
    @staticmethod
    def _split_qa(content: str):
        """
        把模型生成的「题目+答案+解析」拆成 (题目, 答案+解析, 仅答案) 三部分。
        - 以第一个「答案：」位置切分，其前为题目，其后为「答案+解析」。
        - 「答案+解析」中以第一个「解析：」再切分，其前为「仅答案」。
        - 找不到分隔时相应部分返回空串。
        """
        content = (content or "").strip()
        idx = -1
        for marker in ("答案：", "答案:"):
            i = content.find(marker)
            if i >= 0:
                idx = i
                break
        if idx < 0:
            return content, "", ""
        question = content[:idx].strip()
        rest = content[idx:].strip()  # 「答案：...解析：...」整段
        # 在「答案+解析」中切出仅答案部分（答案到解析之前）
        only = rest
        aj_idx = -1
        for marker in ("解析：", "解析:"):
            j = rest.find(marker)
            if j >= 0:
                aj_idx = j
                break
        if aj_idx >= 0:
            only = rest[:aj_idx].strip()
        return question, rest, only

    async def _send_answer(self, api, scene, target_id, msg_id, subject, only=False):
        """发送已生成、等待查看的答案（+解析 或 仅答案）。

        only=False  -> 「🔓 回答」按钮：发送「答案：…解析：…」整段
        only=True   -> 「🔑 答案」按钮：仅发送「答案：…」（不含解析）
        """
        key = (target_id, subject)
        entry = self._pending_answer.get(key)
        if not entry:
            await send_text(
                api, scene, target_id,
                "📚 %s\n━━━━━━━━━━━━━\n当前没有可查看的答案，请先发一道题目～" % _SUBJECT_LABEL[subject],
                msg_id=msg_id,
            )
            return

        ans = entry.get("only") if only else entry.get("full")
        if not ans:
            # 退化：仅答案缺失时回退到完整答案，避免按钮点了没反应
            ans = entry.get("full") or ""
        msg = _sanitize_markdown(ans)
        if len(msg) > 4000:
            msg = msg[:3900].rstrip() + "\n…（内容较多已截断）"

        rows = [{
            "buttons": [
                self._btn("🔙 返回主菜单", "返回主菜单"),
            ]
        }]
        keyboard = {"content": {"rows": rows}}
        try:
            await send_text_with_keyboard(api, scene, target_id, msg, keyboard, msg_id=msg_id)
        except Exception as e:
            logger.error("[学习] 发送答案失败: %s" % e)
            await send_text(api, scene, target_id, msg, msg_id=msg_id)

    # ================================================================
    #                     作答模式：进入 / 待判状态查询
    # ================================================================
    def is_awaiting_answer(self, storage_id):
        """是否正在等待该 storage_id 的用户提交答案（作答模式）。"""
        return storage_id in self._awaiting_answer

    async def _start_answering(self, api, scene, target_id, msg_id, subject):
        """进入作答模式：提示用户发送答案，等待其回复后进行 AI 批改。"""
        subject_label = _SUBJECT_LABEL.get(subject, subject)
        entry = self._pending_answer.get((target_id, subject))
        if not entry:
            # 即使没有标准答案，也要让用户能作答（AI 可以根据题目本身判断是否合理）
            self._awaiting_answer[target_id] = subject
            await send_text(
                api, scene, target_id,
                "✍️ %s · 作答模式\n━━━━━━━━━━━━━\n"
                "请直接发送你的答案，我会请 Qwen3-1.7B 帮你批改。\n"
                "（注：本题未提取到参考答案，将以题目为依据判定是否合理）\n"
                "答完将给出【下一题】入口。" % subject_label,
                msg_id=msg_id,
            )
            return
        self._awaiting_answer[target_id] = subject
        await send_text(
            api, scene, target_id,
            "✍️ %s · 作答模式\n━━━━━━━━━━━━━\n"
            "请直接发送你的答案，我会请 Qwen3-1.7B 帮你批改（判断正误）。\n"
            "答完将给出【下一题】入口。" % subject_label,
            msg_id=msg_id,
        )

    async def _judge_answer(self, api, scene, target_id, subject, user_answer, msg_id):
        """
        调用 Qwen3-1.7B 判定用户答案正误，并发送批改结果：
          - 正确：✅ + 一句话点评 + 「➡️ 下一题」「🔙 返回主菜单」
          - 错误：❌ + 标准正确答案 + 「➡️ 下一题」「🔙 返回主菜单」
        """
        # 防御：subject 为 None（异常状态）时，给出提示并退出
        if not subject or subject not in SUBJECTS:
            logger.warning("[学习] 判定时 subject 无效: %r (target=%s)" % (subject, target_id))
            await send_text(
                api, scene, target_id,
                "📚 当前没有待批改的题目，请重新出一道题～",
                msg_id=msg_id,
            )
            return

        entry = self._pending_answer.get((target_id, subject)) or {}
        question = entry.get("question", "")
        ref_full = entry.get("full", "")
        # 给阅卷模型喂「干净的标准答案」（仅答案部分），避免把自身可能不一致的解析也塞进去干扰判定
        ref_only = entry.get("only", "") or ref_full

        prompt = self._build_judge_prompt(question, ref_only, user_answer)
        verdict_text = ""
        # 优先使用控制台配置的 AI 模型（默认模型）；失败则 fallback 到内置 Qwen3-1.7B
        try:
            from modules import ai_models
            ok, content, used = ai_models.ai_chat(prompt, temperature=0.3, max_tokens=512)
            if ok and content:
                verdict_text = content
                logger.debug("[学习] 判题使用 AI 模型: %s" % used)
            else:
                logger.warning("[学习] AI 模型判题失败，回退到 Qwen3-1.7B: %s" % content)
                verdict_text = await asyncio.to_thread(self._call_qwen_sync, prompt)
        except Exception as e:
            logger.warning("[学习] ai_models 调用异常，回退: %s" % e)
            try:
                verdict_text = await asyncio.to_thread(self._call_qwen_sync, prompt)
            except Exception as e2:
                logger.error("[学习] 判定异常: %s" % e2)

        correct = self._parse_verdict(verdict_text)
        qtype = self._last_qtype.get((target_id, subject), "文字")
        next_cmd = "%s%s" % (subject, qtype)
        subject_label = _SUBJECT_LABEL.get(subject, subject)

        ref = _sanitize_markdown(ref_full) if ref_full else "（暂无参考答案）"
        if len(ref) > 4000:
            ref = ref[:3900].rstrip() + "\n…（内容较多已截断）"

        if correct:
            comment = self._extract_comment(verdict_text)
            body = ("\n" + comment) if comment else ""
            msg = (
                "📚 %s · 批改结果\n━━━━━━━━━━━━━\n"
                "✅ 回答正确！👍%s\n\n"
                "📖 参考答案：\n%s" % (subject_label, body, ref)
            )
        else:
            msg = (
                "📚 %s · 批改结果\n━━━━━━━━━━━━━\n"
                "❌ 回答错误\n━━━━━━━━━━━━━\n"
                "正确答案：\n%s" % (subject_label, ref)
            )

        rows = [{
            "buttons": [
                self._btn("➡️ 下一题", next_cmd),
                self._btn("🔙 返回主菜单", "返回主菜单"),
            ]
        }]
        keyboard = {"content": {"rows": rows}}
        try:
            await send_text_with_keyboard(api, scene, target_id, msg, keyboard, msg_id=msg_id)
        except Exception as e:
            logger.error("[学习] 发送批改结果失败: %s" % e)
            await send_text(api, scene, target_id, msg, msg_id=msg_id)

    @staticmethod
    def _build_judge_prompt(question: str, ref: str, user_answer: str) -> str:
        """构造阅卷 prompt：让 Qwen3-1.7B 判断学生回答是否正确。"""
        return (
            "你是阅卷老师，请判断学生的回答是否与标准答案一致。\n"
            "【题目】\n%s\n\n"
            "【标准答案】\n%s\n\n"
            "【学生回答】\n%s\n\n"
            "规则：只要学生回答的最终结果、关键要点与标准答案一致"
            "（允许表述/单位/格式不同、允许步骤略写），就判「正确」；"
            "若答错、不完整或存在关键错误，判「错误」。\n"
            "输出格式（严格遵守，只输出两行）：\n"
            "第一行：仅写「正确」或「错误」两个汉字，不要加其它字；\n"
            "第二行：用一句话点评（若错误，点明正确结论）。"
        ) % (question, ref, user_answer)

    @staticmethod
    def _parse_verdict(text):
        """从阅卷结果中解析正误：优先看第一行结论，避免后文点评里的「错误」误判。

        返回 True = 正确，False = 错误/不确定。
        防御策略：无法解析时默认判错（保守，避免给错误答案判正确）。
        """
        lines = [l.strip() for l in (text or "").split("\n") if l.strip()]
        if not lines:
            return False
        first = lines[0]
        # 优先识别明确的否定词（含变体）
        neg_words = ("不正确", "不对", "错误", "答错", "有误", "答偏", "不一致")
        pos_words = ("正确", "一致", "正确无误", "对的")
        for w in neg_words:
            if w in first:
                return False
        for w in pos_words:
            if w in first:
                return True
        # 第一行没有明确结论时，退回全文判断
        t = "\n".join(lines)
        for w in neg_words:
            if w in t:
                return False
        for w in pos_words:
            if w in t:
                return True
        # 完全无法解析：保守判错
        return False

    @staticmethod
    def _extract_comment(text):
        """取阅卷结果的第二行作为点评（无则返回空串）。"""
        lines = [l.strip() for l in (text or "").split("\n") if l.strip()]
        if len(lines) >= 2:
            return lines[1]
        return ""

    # ================================================================
    #                        题目查询路由
    # ================================================================
    async def _query(self, api, scene, target_id, msg_id, subject, qtype, topic="", again=False):
        key = (target_id, subject, qtype)
        # 记录本次题型，供「下一题」按钮沿用（文字/图片）
        self._last_qtype[(target_id, subject)] = qtype

        # 换一批：沿用上次主题并轮换修饰词
        if again:
            topic = self._last_topic.get(key, topic)
            idx = (self._variant.get(key, -1) + 1) % len(_VARIANTS)
            self._variant[key] = idx
            variant = _VARIANTS[idx]
        elif topic:
            self._last_topic[key] = topic
            variant = None
        else:
            variant = None

        if qtype == "图片":
            await self._query_images(api, scene, target_id, msg_id, subject, topic, variant)
        else:
            await self._query_text(api, scene, target_id, msg_id, subject, topic, variant)

    # ================================================================
    #                        文字题目
    # ================================================================
    async def _query_text(self, api, scene, target_id, msg_id, subject, topic, variant):
        # 提示语
        await send_text(
            api, scene, target_id,
            "📚 %s · 文字题目\n━━━━━━━━━━━━━\n"
            "正在请 Qwen3-1.7B 为你出题，请稍候…" % _SUBJECT_LABEL[subject],
            msg_id=msg_id,
        )

        try:
            content = await self._generate_question(subject, topic, variant)
        except Exception as e:
            logger.error("[学习] 出题异常(%s): %s" % (subject, e))
            content = ""

        if not content:
            await send_text(
                api, scene, target_id,
                "📚 %s · 文字题目\n━━━━━━━━━━━━━\n"
                "AI 出题失败（接口超时或限流）。\n"
                "稍后再试，或换个主题，例如「%s文字 古诗」「%s文字 函数」。" % (
                    _SUBJECT_LABEL[subject], subject, subject),
                msg_id=msg_id,
            )
            return

        # 题目与答案拆分：题目先发，答案存待查看（点按钮后发送）
        question, answer_full, answer_only = self._split_qa(content)
        if answer_full:
            self._pending_answer[(target_id, subject)] = {
                "full": answer_full,
                "only": answer_only,
                "question": question,
            }

        msg = _sanitize_markdown(question)
        if len(msg) > 4000:
            msg = msg[:3900].rstrip() + "\n…（内容较多已截断）"

        # 键盘卡片：第 1 行「作答（含看解析）/答案」，第 2 行「换一批/返回主菜单」
        rows = [{
            "buttons": [
                self._btn("✍️ 作答", "作答 %s" % subject),
                self._btn("🔑 答案", "答案 %s" % subject),
            ]
        }, {
            "buttons": [
                self._btn("🔄 换一批", "%s文字 换一批" % subject),
                self._btn("🔙 返回主菜单", "返回主菜单"),
            ]
        }]
        keyboard = {"content": {"rows": rows}}
        try:
            await send_text_with_keyboard(api, scene, target_id, msg, keyboard, msg_id=msg_id)
        except Exception as e:
            logger.error("[学习] 发送文字题目(markdown)失败: %s" % e)
            await send_text(api, scene, target_id, msg, msg_id=msg_id)

    # ================================================================
    #                        图片题目
    # ================================================================
    async def _query_images(self, api, scene, target_id, msg_id, subject, topic, variant):
        # 提示语
        await send_text(
            api, scene, target_id,
            "📚 %s · 图片题目\n━━━━━━━━━━━━━\n"
            "正在请 Qwen3-1.7B 出题并渲染成图片，请稍候…" % _SUBJECT_LABEL[subject],
            msg_id=msg_id,
        )

        try:
            content = await self._generate_question(subject, topic, variant)
        except Exception as e:
            logger.error("[学习] 图片出题异常(%s): %s" % (subject, e))
            content = ""

        if not content:
            await send_text(
                api, scene, target_id,
                "📚 %s · 图片题目\n━━━━━━━━━━━━━\n"
                "AI 出题失败（接口超时或限流）。\n"
                "可改用「%s文字」查看文字题目～" % (_SUBJECT_LABEL[subject], subject),
                msg_id=msg_id,
            )
            return

        # 题目与答案拆分：图片只渲染题目，答案存待查看（点按钮后发送）
        question, answer_full, answer_only = self._split_qa(content)
        if answer_full:
            self._pending_answer[(target_id, subject)] = {
                "full": answer_full,
                "only": answer_only,
                "question": question,
            }

        # 把题目渲染成图片（PIL），直发真实图片
        img_bytes_list = self._render_text_to_images(question, max_pages=_IMAGE_MAX)
        if not img_bytes_list:
            # 渲染失败（缺 Pillow / 字体）：降级为文字卡片（仍带查看答案按钮）
            logger.warning("[学习] 题目图片渲染失败，降级为文字卡片")
            msg = _sanitize_markdown(question)
            rows = [{
                "buttons": [
                    self._btn("✍️ 作答", "作答 %s" % subject),
                    self._btn("🔑 答案", "答案 %s" % subject),
                ]
            }, {
                "buttons": [
                    self._btn("🔄 换一批", "%s图片 换一批" % subject),
                    self._btn("🔙 返回主菜单", "返回主菜单"),
                ]
            }]
            keyboard = {"content": {"rows": rows}}
            try:
                await send_text_with_keyboard(api, scene, target_id, msg, keyboard, msg_id=msg_id)
            except Exception:
                await send_text(api, scene, target_id, msg, msg_id=msg_id)
            return

        sent = 0
        for idx, img_bytes in enumerate(img_bytes_list, 1):
            try:
                res = await send_local_image_for_scene(
                    api, scene, target_id, img_bytes, msg_id=msg_id,
                    content="📚 %s · 图片题目（%d/%d）" % (_SUBJECT_LABEL[subject], idx, len(img_bytes_list)))
                if res is not None:
                    sent += 1
            except Exception as e:
                logger.error("[学习] 发送题目图片失败: %s" % e)

        # 结果汇总 + 作答（含看解析）/ 答案 / 换一批 / 返回按钮
        rows = [{
            "buttons": [
                self._btn("✍️ 作答", "作答 %s" % subject),
                self._btn("🔑 答案", "答案 %s" % subject),
            ]
        }, {
            "buttons": [
                self._btn("🔄 换一批", "%s图片 换一批" % subject),
                self._btn("🔙 返回主菜单", "返回主菜单"),
            ]
        }]
        keyboard = {"content": {"rows": rows}}
        footer = "共发送 %d 张题目图片 · 由 Qwen3-1.7B 生成" % sent
        try:
            await send_text_with_keyboard(api, scene, target_id, footer, keyboard, msg_id=msg_id)
        except Exception:
            await send_text(api, scene, target_id, footer, msg_id=msg_id)

    # ================================================================
    #                        学科网搜索（已弃用，保留占位）
    # ================================================================
    # 注：学习系统题目搜索后端已于 2026-07-31 由学科网(zxxk) 切换为
    # Qwen3-1.7B 大模型直接出题（见 _call_qwen_sync / _query_text / _query_images）。
    # 以下方法如需回退可保留，否则可删除。
