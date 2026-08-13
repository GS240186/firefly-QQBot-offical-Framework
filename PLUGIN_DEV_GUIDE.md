# 小流萤 插件开发指南（Plugin Development Guide）

> 本文档面向**想给小流萤（Xiaoliuying QQ 官方 Bot）编写扩展插件**的开发者。
> 小流萤采用「双轨插件系统」：内置功能模块（`modules/`）与用户外置插件（`plugins/`）共用同一套分发契约。
> 外置插件**无需改核心代码、无需重启 bot**，丢进 `plugins/` 目录即生效，非常适合二次开发与开源共建。

---

## 目录

1. [架构总览](#1-架构总览)
2. [五分钟上手：你的第一个插件](#2-五分钟上手你的第一个插件)
3. [插件契约详解](#3-插件契约详解)
4. [PluginContext 参考](#4-plugincontext-参考)
5. [回复与发送能力](#5-回复与发送能力)
6. [触发与匹配规则](#6-触发与匹配规则)
7. [热加载与插件生命周期](#7-热加载与插件生命周期)
8. [控制台与 HTTP 管理接口](#8-控制台与-http-管理接口)
9. [插件市场：发布你的插件](#9-插件市场发布你的插件)
10. [约定与最佳实践](#10-约定与最佳实践)
11. [进阶示例：带发图 + 调用内部能力的插件](#11-进阶示例带发图--调用内部能力的插件)
12. [常见问题 / 排错](#12-常见问题--排错)

---

## 1. 架构总览

小流萤把「功能模块」收敛为统一的 `PluginDescriptor`，所有消息走一条 `DISPATCH_PLAN` 分发链：

```
消息 → on_group/c2c/channel_message_create
     → _dispatch_message
     → _handle_message_inner
     → 构造 PluginContext(ctx)
     → 遍历 DISPATCH_PLAN：
          fw: game_idiom_preroute        （猜成语进行中优先）
          fw: subfeature_gate            （子功能开关门控）
          fw: profile_command            （绑群号/绑QQ/我的信息）
          plugin: checkin / tools / study / music / video / image / game
          fw: help_submenu_nav
          plugin: novel
          plugin: group_admin            （群管：违禁词/禁言/入群审批）
          fw: external_plugins  ★        （外置插件，按 priority 升序）
          fw: join_experience_group
          fw: help_menu
          fw: banned_word_noncmd         （非指令类违禁词检测）
          fw: ai_fallback                （AI 兜底回复）
```

**关键结论（写插件前必读）**

- 外置插件在 `external_plugins` 框架步骤里统一分发，**排在全部内置功能之后、AI 兜底之前**。
- 因此：内置功能已处理的消息不会再跑外置插件；外置插件命中（`return True`）后，后续步骤（含 AI 兜底）都不会执行。
- 外置插件之间按 `priority` **升序**执行（数字越小越靠前），同 `priority` 按文件名。

---

## 2. 五分钟上手：你的第一个插件

在仓库根目录的 `plugins/` 下新建 `hello.py`：

```python
# -*- coding: utf-8 -*-
"""示例外置插件：hello"""

PLUGIN = {
    "key": "hello",
    "name": "Hello 插件",
    "priority": 500,                 # 默认 500，越小越靠前
    "description": "发送「hello」机器人回「你好呀～」",
    "category": "demo",              # 控制台分组 / 市场分类
}

async def handle(ctx) -> bool:
    # ctx.content 是用户的原始消息文本（框架不剥离 "/"）
    text = (ctx.content or "").strip().lstrip("/").strip()   # 兼容 "/hello"
    if text != "hello":
        return False                 # 不处理 → 放行给后续步骤
    await ctx.reply("你好呀～ 这是来自外置插件的回复")
    return True                      # 已处理 → 分发链终止
```

**生效方式（任选其一）**

- 直接保存文件 → 后台热加载线程（约每 3 秒）会自动检测并加载；
- 或在控制台「功能配置 → 插件管理」点 **🔄 热加载** 立即生效。

之后在群里或私聊发送 `hello`（或 `/hello`），机器人即回「你好呀～」。

---

## 3. 插件契约详解

### 3.1 文件位置与命名

| 项 | 规则 |
|---|---|
| 目录 | `plugins/`（仓库根目录下） |
| 文件名 | `<key>.py`，**文件名除去 `.py` 即插件 key** |
| 下划线前缀 | **以 `_` 开头的文件会被跳过**（用于市场模板 `_tpl_*.txt`，不放进分发） |
| 编码 | UTF-8 即可；通过市场安装时框架会统一归一化为 `CRLF + BOM` |

### 3.2 `PLUGIN` 描述符

模块级 `PLUGIN` 字典，字段如下：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `key` | str | 是* | 插件唯一键，建议与文件名一致。缺省时取文件名 |
| `name` | str | 否 | 展示名（控制台/市场用）。缺省取 key |
| `priority` | int | 否 | 分发顺序，默认 `500` |
| `description` | str | 否 | 描述（控制台/市场用） |
| `category` | str | 否 | 分类标签，如 `"test"`/`"game"`/`"tool"`；用于控制台分组与市场筛选 |
| `handle` | callable | 否 | 分发函数；缺省时回退到模块级 `async def handle(ctx)` |

> *`key` 也可省略：此时从文件名推导。但**显式写 key 更稳妥**，尤其是文件名与导出键不一致时。

### 3.3 `handle(ctx) -> bool`

```python
async def handle(ctx) -> bool:
    ...
    return True    # 已处理，终止分发链
    # return False # 不处理，继续往后走（AI 兜底等）
```

- 返回 **`True`**：本插件认领这条消息，分发链立即终止（后续内置功能、AI 兜底都不再执行）。
- 返回 **`False`**：本插件不处理，交给链上的下一个步骤。

> ⚠️ 若 `handle` 抛异常，框架会捕获并记日志、当作 `False` 放行，**不会中断整条链**；但请在自己代码里做好容错，避免吞掉有用错误。

### 3.4 两种合法写法

**写法 A（推荐）：`PLUGIN` 字典 + `handle`**

```python
PLUGIN = {"key": "foo", "name": "Foo", "priority": 500, "category": "tool"}
async def handle(ctx) -> bool:
    ...
```

**写法 B：仅定义模块级 `handle`**（key 自动取文件名）

```python
async def handle(ctx) -> bool:
    ...
```

两种写法下，`PLUGIN` 都必须在 `handle` **之后**定义（框架先找到 `handle`，再解析 `PLUGIN`）。

---

## 4. PluginContext 参考

`handle(ctx)` 收到的 `ctx` 是 `PluginContext` 实例，框架在分发前已填充好。字段如下：

| 字段 | 类型 | 含义 |
|---|---|---|
| `api` | object | botpy/api 客户端，可用于高级原生调用 |
| `content` | str | **用户的原始消息文本**（未剥离 `/` 等前缀） |
| `scene` | str | 场景：`"group"` / `"c2c"` / `"channel"`（见下方常量） |
| `target_id` | str | 目标原生 ID（群 openid / 用户 openid / 频道 id） |
| `storage_id` | str | 存储键（裸 ID，与等待会话一致） |
| `msg_id` | str | 消息 ID（回复定位用） |
| `event_id` | str | 事件 ID（回复定位用） |
| `member_openid` | str | 发送者 openid |
| `member_nick` | str | 发送者昵称 |
| `member_role` | str | 群成员角色（`owner`/`admin`/`member`），私聊/频道为 `""` |
| `is_group` | bool | 是否群聊 |
| `event_type` | str | 事件类型（`AT`/`C2C`/`...`） |
| `is_at_or_dm` | bool | 是否被 @ 或私聊（AI 兜底判定用） |
| `is_console_admin` | bool | 是否控制台管理员 |
| `is_waiting` / `is_gaming` / `is_studying` | bool | 框架级会话/路由标志 |
| `bot` | object | `MyClient` 实例 |
| `bot_appid` | str | 当前 bot 的 appid（供功能开关使用） |

**场景常量（`modules.common.ChatScene`）**

```python
ChatScene.GROUP   = "group"    # 群聊
ChatScene.C2C     = "c2c"      # 用户与机器人私聊
ChatScene.CHANNEL = "channel"  # 频道公域 @ 消息
```

> 在插件里可用 `from modules.common import ChatScene` 拿到常量，避免硬编码字符串。

---

## 5. 回复与发送能力

### 5.1 最简便：`ctx.reply(text)`

```python
await ctx.reply("这是一条回复")
```

底层走 `modules.common.send_text`，自动按 `ctx.scene` 选择群/C2C/频道发送。

### 5.2 直接调用 `modules.common` 发送接口

需要更细控制（如发图、带按钮、指定 msg_id）时，直接 import 这些统一发送函数：

| 函数 | 说明 |
|---|---|
| `send_text(api, scene, target_id, content, msg_id=, event_id=)` | 发文本 |
| `send_text_with_keyboard(api, scene, target_id, content, keyboard, ...)` | 发文本 + 按钮 |
| `send_image_for_scene(api, scene, target_id, image_url, ...)` | 从 URL 发图 |
| `send_local_image_for_scene(api, scene, target_id, image_bytes, msg_id=, content="")` | 发本地图片（bytes） |
| `send_audio_for_scene(api, scene, target_id, audio_url, ...)` | 发语音（自动转 MP3） |

插件内用法示例：

```python
from modules.common import send_local_image_for_scene

async def handle(ctx) -> bool:
    if (ctx.content or "").strip() != "喵":
        return False
    with open("assets/cat.png", "rb") as f:
        data = f.read()
    # 发图前【不要】先 ctx.reply，否则会消耗 msg_id 导致发图失败
    await send_local_image_for_scene(ctx.api, ctx.scene, ctx.target_id, data, msg_id=ctx.msg_id)
    return True
```

> ⚠️ **发图/发媒体前不要先调用 `ctx.reply`**：`reply` 会消费 `ctx.msg_id`，之后再发图会因缺少消息上下文而失败。先发图、再决定是否补文字；或把文字作为 `content=` 参数随图一起发。

---

## 6. 触发与匹配规则

1. **`ctx.content` 是原始消息文本**——框架不像某些 bot 那样自动剥离 `/`。用户发 `/hello` 时 `ctx.content` 就是 `"/hello"`。
   - 想兼容 `/cmd` 写法，请自己在插件里 `text = ctx.content.lstrip("/").strip()`。
2. **游戏类指令前缀 `*` / `#` 会保留在 `content` 中**（如星铁 `*更新面板`、原神 `#十连`）。匹配时直接 `ctx.content.startswith("*")` 即可。
3. **@ 或不 @ 都能触发**：非 @ 的普通群聊消息也会放行到外置插件分发，所以你的指令无论用户是否 @ 机器人都能命中（AI 兜底仍保持 @/私聊才触发）。
4. **返回 `True` 阻断后续**：命中后后续内置功能与 AI 兜底都不执行；未命中务必 `return False` 放行。

---

## 7. 热加载与插件生命周期

- **自动热加载**：后台线程约每 3 秒检测 `plugins/*.py` 的 `mtime`，变更即重新加载并重新注册。
- **手动热加载**：控制台「功能配置 → 插件管理 → 🔄 热加载」等价于 `POST /api/plugins/reload?force=1`。
- **免重启**：对外置插件（`plugins/*.py`）的增删改**无需重启 bot**。
- **需重启的情况**：改动 `lib/*.py` 等被 `import` 的内部库——热加载不覆盖已 import 的模块对象，必须重启进程。
- **模块级全局状态**：热加载会重新 `exec` 模块，模块级变量会重建；需要跨消息持久化的状态，请写到 `data/` 下的 JSON 文件，而非模块级变量。
- **删除文件即卸载**：直接删掉 `plugins/<key>.py`，热加载线程会注销该插件。

---

## 8. 控制台与 HTTP 管理接口

控制台「功能配置 → 插件管理」背后是一组 HTTP 接口（bot 与控制台同进程，监听 `:9988`）：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/plugins` | 列出所有插件（内置+外置），含 `key/name/enabled/is_external/category/priority` |
| POST | `/api/plugins/reload?force=1` | 强制热加载全部外置插件 |
| POST | `/api/plugins/set-enabled` | 启停外置插件，body：`{"key":"<key>","enabled":true/false}` |
| GET | `/api/plugins/market?remote=1&force=1` | 拉取插件市场目录（`remote=1` 走 GitHub raw，`force=1` 忽略 10 分钟缓存） |
| POST | `/api/plugins/market/install` | 安装市场插件，body：`{"key":"<key>","raw_url":"<可选>"}` |
| POST | `/api/plugins/market/uninstall` | 卸载市场插件，body：`{"key":"<key>"}` |

**启用状态持久化**：外置插件的启停状态存于 `data/plugin_state.json`（key→bool）。删除文件或改代码不影响该状态；卸载/重新安装后沿用之前的启用设置（未记录则默认启用）。

---

## 9. 插件市场：发布你的插件

小流萤支持从 GitHub 拉取远程插件仓库并一键安装。市场本质是一个 `index.json`（含插件清单）+ 每个插件的源码文件。**`index.json` 既可放在仓库根目录，也可放在 `插件市场/` 子目录** —— bot 会按以下顺序尝试：
1. `<base>/index.json`（仓库根目录）
2. `<base>/插件市场/index.json`（子目录，作为回退）

也就是说：**目录名不是强制的**。如果你不想用 `插件市场/` 这个名字，把 `index.json` 直接放在仓库根目录即可。

### 9.1 目录结构（扁平，无子目录）

```
<你的仓库>/
├── index.json                 # 总目录（仅列 key + path；bot 一次拉取）
├── README.md
├── <key>.py                   # 插件源码（与外置插件同契约），平铺在根
└── <key>.meta.json            # 单插件元数据（展示字段：name/description/category/priority）
```

> 本仓库（GS240186/firefiy-QQofficial-bot-piugins）已采用扁平结构：`index.json` 直接放根目录，与各 `<key>.py` / `<key>.meta.json` 平铺。

### 9.2 `index.json` 字段（极简）

`index.json` 只负责「有哪些插件、源码在哪」，展示信息全部交给 `<key>.meta.json`：

```json
{
  "version": 2,
  "note": "扁平结构：每个插件 <key>.py + <key>.meta.json 平铺在仓库根目录（无子目录）。index.json 仅列 key 与 path。",
  "plugins": [
    { "key": "genshin", "path": "genshin.py" },
    { "key": "genshin_miao", "path": "genshin_miao.py" },
    { "key": "starrail", "path": "starrail.py" }
  ]
}
```

| 字段 | 说明 |
|---|---|
| `key` | 插件唯一键（同时是安装后的文件名 `plugins/<key>.py`） |
| `path` | 相对仓库根的源码路径，如 `genshin.py` |

> 兼容：若索引项自带 `name` / `description` / `category` / `priority`，bot 直接用不再读 meta；否则从 `<key>.meta.json` 读取（仅填充缺失字段）。

### 9.3 `<key>.meta.json` 字段

```json
{
  "key": "genshin",
  "name": "原神查询",
  "description": "原神玩家面板/练度查询 (Enka Network，无需 cookie)；UID 可绑定后下次发角色名直查",
  "priority": 500,
  "category": "game"
}
```

### 9.4 用脚手架脚本生成

仓库自带 `outputs/gen_market_scaffold.py`，读取 `plugins/` 下指定插件、生成**扁平**的 `plugins-market/` 结构（`<key>.py` + `<key>.meta.json` 平铺 + 极简 `index.json`）：

```bash
# 修改脚本顶部 KEYS = ["roll", "ping", "demo_echo"] 为你要发布的插件
python outputs/gen_market_scaffold.py
```

把生成的 `plugins-market/` 内容（含根目录 `index.json`）push 到仓库默认分支即可，bot 通过 raw URL 拉取。无需任何特定目录名。

### 9.5 远程仓库地址约定

bot 端常量（`modules/plugin_registry.py`）：

```python
REMOTE_MARKET_OWNER  = "GS240186"
REMOTE_MARKET_REPO   = "firefiy-QQofficial-bot-piugins"   # 注意：仓库名拼写历史遗留为 piugins
REMOTE_MARKET_BRANCH = "main"
REMOTE_MARKET_DIR    = "插件市场"                         # 仅作为「index.json 在子目录」时的回退目录名
REMOTE_MARKET_BASE   = "https://raw.githubusercontent.com/%s/%s/%s/" % (...)  # 默认只到分支层
```

> 想让 bot 从**你自己的仓库**拉市场，修改这几个常量（或对应的配置项）指向你的仓库即可。
> 拉取时按以下顺序尝试 `index.json`：① `<base>index.json`（根目录，本仓库采用）→ ② `<base>/<REMOTE_MARKET_DIR>/index.json`（子目录回退）。
>
> **控制台「插件市场」页可直接粘贴任意仓库地址**（`https://github.com/OWNER/REPO` 或 `https://raw.githubusercontent.com/OWNER/REPO[/...]`，缺失分支时自动补默认分支）。扁平仓库填到分支层即可，bot 会在该基址下找 `index.json` 与 `<key>.py` / `<key>.meta.json`。

---

## 10. 约定与最佳实践

1. **编码**：源码 UTF-8。手写可 `LF 无 BOM`；通过市场安装时框架会归一化为 `CRLF + BOM`，两种都能正常 `import`。
2. **key 命名**：英文/数字，与文件名一致；不要用中文或空格（会作为文件名与模块名）。
3. **priority**：默认 `500`；想排在更前就改小，更后就改大。
4. **category**：给一个稳定的分类标签，便于控制台分组与市场筛选（如 `tool`/`game`/`test`）。
5. **异常处理**：`handle` 内做好 `try/except`，避免单条异常影响整条分发链（框架虽会兜底，但会丢失你的错误上下文）。
6. **不要回显敏感/违禁词**：群管会检测并撤回含违禁词的消息，插件自身也应注意内容合规。
7. **调用内部能力**：插件可 `from modules.xxx import yyy` 复用 `common`/`plugin_registry` 等模块；`lib/*.py` 的改动需重启才生效。
8. **持久化状态**：跨消息的数据写到 `data/<your_key>_state.json`，不要依赖模块级变量（热加载会重建）。
9. **幂等与可重入**：热加载会重复执行模块顶层代码，顶层只做轻量定义，重活放进 `handle` 或 `init` 回调。
10. **不阻塞事件循环**：耗时操作（网络/IO）请用 `await` 异步接口或 `asyncio.to_thread`，勿用同步长阻塞。

---

## 11. 进阶示例：带发图 + 调用内部模块的插件

下面示例演示：解析参数、读取本地图片发送、并复用 `modules.common` 的发送能力。

```python
# -*- coding: utf-8 -*-
"""示例：每日一句（daily）— 解析「daily」触发，发一张配图 + 文字"""
import os
import json

PLUGIN = {
    "key": "daily",
    "name": "每日一句",
    "priority": 500,
    "description": "发送「daily」随机回一句名言 + 配图",
    "category": "tool",
}

_QUOTES = [
    "种一棵树最好的时间是十年前，其次是现在。",
    "Stay hungry, stay foolish.",
    "不积跬步，无以至千里。",
]

async def handle(ctx) -> bool:
    if (ctx.content or "").strip().lstrip("/").strip() != "daily":
        return False

    # 调用内部发送接口
    from modules.common import send_text
    quote = _QUOTES[hash(ctx.member_openid) % len(_QUOTES)]
    await send_text(ctx.api, ctx.scene, ctx.target_id, "📜 " + quote,
                    msg_id=ctx.msg_id, event_id=ctx.event_id)

    # 可选：发一张本地配图
    img = os.path.join(os.path.dirname(__file__), "assets", "daily.png")
    if os.path.isfile(img):
        from modules.common import send_local_image_for_scene
        with open(img, "rb") as f:
            await send_local_image_for_scene(ctx.api, ctx.scene, ctx.target_id,
                                             f.read(), msg_id=ctx.msg_id)
    return True
```

> 把图片放到 `plugins/assets/daily.png`（随插件一起发布），或改为从 URL 用 `send_image_for_scene` 发送。

---

## 12. 常见问题 / 排错

**Q1：插件放进去没反应？**
- 文件名是否以 `_` 开头？是则会被跳过，去掉下划线前缀。
- key 是否与已有插件冲突？重复 key 以最后注册为准。
- 是否 `return False` 导致被放行？用 `print`/`logger` 在 `handle` 里打点，或点控制台「热加载」后看 bot 日志。

**Q2：为什么 `ctx.content` 里带 `/`？**
- 框架不剥离 `/`（见 §6）。想兼容 `/cmd`，自己 `lstrip("/")`。

**Q3：改了 `lib/` 下的代码不生效？**
- 内部库需重启 bot；只有 `plugins/*.py` 支持热加载（见 §7）。

**Q4：发图失败 / 没发出去？**
- 发图前是否先 `ctx.reply` 了？`reply` 会消耗 `msg_id`，导致后续发图缺少上下文（见 §5.2）。

**Q5：想发到自己的插件市场？**
- 修改 `modules/plugin_registry.py` 里的 `REMOTE_MARKET_OWNER/REPO/BRANCH`，指向你的仓库（见 §9.5）。

**Q6：外置插件和内置模块怎么共存？**
- 完全解耦：外置插件在 `external_plugins` 步骤统一分发，排在内置功能之后。两者通过同一 `PluginContext` 契约协作，互不侵入。

---

> 文档基于小流萤 `modules/plugin_registry.py`、`bot.py`（DISPATCH_PLAN / `_fw_external_plugins`）、`modules/common.py` 与 `plugins-market/` 实际实现整理，适用于开源二次开发。欢迎提 PR 补充示例与修正。
