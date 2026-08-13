# 插件市场（远程下载源）

小流萤 bot 的「插件市场」远程下载源。**采用扁平结构**：所有文件平铺在仓库根目录，无子目录。

> **目录名不强求。** bot 会先试仓库根目录的 `index.json`，找不到时再回退到 `插件市场/index.json`。本仓库已把 `index.json` 直接放根目录，与 `<key>.py` / `<key>.meta.json` 平铺。
>
> **控制台「插件市场」页支持任意形态仓库地址**：`https://github.com/OWNER/REPO` 与 `https://raw.githubusercontent.com/...` 都行；缺失分支时自动补默认分支。

## 目录结构（扁平）

```
<仓库根>/
├── index.json              # 总目录（bot 运行时拉取它）—— 仅列 key + path
├── README.md               # 本文件
├── <key>.py                # 插件源码（外置插件契约：模块级 PLUGIN dict + async handle(ctx)）
└── <key>.meta.json         # 插件元信息（展示字段：name/description/category/priority）
```

示例（本仓库实际内容）：

```
├── index.json
├── README.md
├── genshin.py
├── genshin.meta.json
├── starrail.py
└── starrail.meta.json
```

## index.json 字段（极简）

`index.json` 只负责「有哪些插件、源码在哪」，展示信息全部交给 `<key>.meta.json`：

```json
{
  "version": 2,
  "note": "扁平结构：每个插件 <key>.py + <key>.meta.json 平铺在仓库根目录（无子目录）。index.json 仅列 key 与 path。",
  "plugins": [
    { "key": "genshin", "path": "genshin.py" },
    { "key": "starrail", "path": "starrail.py" }
  ]
}
```

| 字段 | 说明 |
| --- | --- |
| `key` | 插件唯一标识；也是安装后的文件名 `plugins/<key>.py` |
| `path` | 相对仓库根目录的源码路径，如 `genshin.py` |

> 兼容说明：若索引项自带 `name` / `description` / `category` / `priority`，bot 直接用，不再读 meta；否则从 `<key>.meta.json` 读取（仅填充缺失字段）。

## <key>.meta.json 字段

```json
{
  "key": "genshin",
  "name": "原神查询",
  "description": "原神玩家面板/练度查询 (Enka Network，无需 cookie)；UID 可绑定后下次发角色名直查",
  "priority": 500,
  "category": "game"
}
```

| 字段 | 说明 |
| --- | --- |
| `key` | 与索引一致 |
| `name` | 控制台展示名 |
| `description` | 一句话描述（控制台卡片展示） |
| `category` | 分组标签，如 `game` / `test` |
| `priority` | 加载优先级（数值越大越先匹配） |

## 外置插件契约（<key>.py）

`<key>.py` 需暴露：

```python
PLUGIN = {
    "key": "<key>",
    "name": "显示名",
    "priority": 500,
    "description": "一句话描述",
    "category": "test",        # 可选，用于控制台分组
}

async def handle(ctx) -> bool:
    # ctx.content 已是去掉前缀的指令文本
    # ctx.reply(text) 直接回复
    return True  # 已处理（不再往下传）
```

## 如何让 bot 拉到这个市场

1. 把整个仓库推送到 GitHub（默认分支 `main`），`index.json` 在仓库根目录。
2. bot 代码里已配置默认远程源：
   - owner = `GS240186`
   - repo = `firefiy-QQofficial-bot-piugins`
   - branch = `main`
3. 控制台「插件市场」页**按以下顺序尝试拉取**：
   1. `<base>/index.json`（仓库根目录，本仓库采用此方式）
   2. `<base>/插件市场/index.json`（子目录回退）
   点「安装」会先从 `index.json` 拿 `path` 拼出 `<key>.py` 的 raw 地址下载到 `plugins/<key>.py`，再读 `<key>.meta.json` 补全展示字段并热加载。

### 自定义插件仓库（热加载，无需重启）

控制台「插件市场」页顶部有「自定义插件仓库 raw 基址」输入框。填写你自己的仓库地址
（如 `https://github.com/OWNER/REPO`，**无需带分支、无需带目录名**；bot 自动补默认分支并找根目录 `index.json`），
点「保存」即可立即切换市场源，无需重启 bot。留空则用默认仓库。

> 若仓库默认分支是 `master` 而不是 `main`，改 `modules/plugin_registry.py` 里
> `REMOTE_MARKET_BRANCH = "main"` 为 `"master"` 后重启 bot。

### 测试插件不在仓库内

`roll` / `ping` / `demo_echo` 等测试插件随框架内置（源码在 `plugins/_tpl_*.txt`），
在控制台「插件市场」页以「内置测试插件」分组提供安装，**不进入本仓库目录**，
避免污染对外分享的插件源。
