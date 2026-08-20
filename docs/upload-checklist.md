# 小流萤 GitHub 上传清单（2026-08-20 更新版）

> 项目已开源准备完毕。
> 仓库路径：**`c:\Users\123\Desktop\小流萤bot\`**（之前 8-19 版的 `D:\小流萤bot-public\` 路径作废，以当前目录为准）。
> 仓库结构：**两个仓库**——插件仓库（市场来源）+ 主项目仓库（完整源码）。

---

## 〇、上传前隐私清理（已自动完成）

| 位置 | 改前 | 改后 |
|---|---|---|
| `bot.py:1238` | `_FEEDBACK_FORM_URL = "https://docs.qq.com/form/page/DWXNyWGJiZE9rZHFD"` | `""` + 注释指向控制台 |
| `bot.py:33-42` | `EXPERIENCE_GROUP_JOIN_URL` 硬编码含群号 729224936 + 邀请人 openid 的长 URL | `""` + 注释指向控制台（实际不生效，dead code） |
| `console_server.py:877-878` | `feedback.form_url` 默认值填了你的腾讯问卷 ID；`feedback.enabled=True` | 默认值清空 + `feedback.enabled=False` |
| `console_server.py:880` | `experience_group.url` 默认值填了你的体验群长 URL（**真暴露点**） | 默认值 `""` + 警告注释 |
| `modules/config.py` | `DWO_VIDEO_PARSE_KEY / DWO_QQ_CKEY / QQ_INFO_KEY / APIHZ_TQ_ID / APIHZ_TQ_KEY / XXAPI_KEY` 全填了你用过的 ckey | 全部清空成 `""` + 加获取地址注释 |

清理脚本（如果以后重置时跑）：

```powershell
# 1) 干掉所有 .pyc 缓存
Get-ChildItem -Recurse -Directory -Filter __pycache__ -ErrorAction SilentlyContinue |
  Remove-Item -Recurse -Force

# 2) 清理本地运行数据
Remove-Item -Force data\bots.json -ErrorAction SilentlyContinue
Remove-Item -Force data\admin_auth.json -ErrorAction SilentlyContinue
Remove-Item -Force data\bots\_shared\today_stats.json -ErrorAction SilentlyContinue
Remove-Item -Force *.log -ErrorAction SilentlyContinue

# 3) 检查残留隐私
Get-ChildItem -Recurse -Filter *.py | Select-String -Pattern 'DWXNyWGJiZE9rZHFD|729224936|EU1UX26RA2BPXWCWH8Z4|GSHGJ20060914|1fb99f34b2481d8d|GTgu8NdtARj1KdxHcyKh4SqFe4UvNpIl|qun\.qq\.com/universal-share'
```

如果输出为空，即可上传。

---

## 一、插件仓库上传清单（`GS240186/firefiy-QQofficial-bot-piugins`）

> 控制台「插件市场」的远程来源。**该仓库是单独的项目**，请从 `c:\Users\123\Desktop\小流萤bot\plugins-market\`（如果不存在则使用 `plugins/`）整理后单独推送。
> 详细结构以 8-19 版原清单为准（"9 插件 + index.json"）。

---

## 二、主项目仓库上传清单（建议名 `小流萤bot` / `firefly-qq-bot`）

> 上传内容 = 当前目录 `c:\Users\123\Desktop\小流萤bot\` 全部，但**排除 `.gitignore` 中列出的运行时数据、日志、缓存**。

### 根目录（必传）

| 文件 | 说明 |
|---|---|
| `bot.py` | 主入口（QQ 机器人 + 插件分发框架） |
| `console_server.py` | 控制台服务（9988 端口） |
| `README.md` | 项目说明 |
| `PLUGIN_DEV_GUIDE.md` | 插件开发指南 |
| `requirements.txt` | Python 依赖 |
| `config.yaml` | ⚠️ 仅作占位说明，**不生效**；真正的配置入口是 `modules/config.py` |
| `package.json` / `package-lock.json` | 辅助文件 |
| `go.cmd` | Windows 启动脚本（**注意：双击会闪退**，建议用 `python bot.py`） |
| `.gitignore` | **新增**：排除运行时数据 / 日志 / pycache |
| `find_plugs.py` | 插件扫描工具 |
| `_seed_menu_tree.py` | 菜单树初始化脚本 |
| `_write_default_menu_tree.py` | 菜单树默认写入脚本 |

### 目录（必传）

| 目录 | 内容 |
|---|---|
| `modules/` | 框架 + 共享库（bot_manager / config / plugin_registry / ai_models 等） |
| `plugins/` | **52 个外置插件**：9 目录包（checkin/tools/study/music/video/image/game/novel/group_admin）+ 9+ 单文件 + ww_gacha_data 等 |
| `plugins-market/` | 市场索引与分发副本（与插件仓库内容一致） |
| `admin/` | 控制台前端（index.html + setup.html + assets/） |
| `assets/` | 菜单封面等静态资源（menu_banner.{jpg,png,...}） |
| `lib/` | genshin_panel_miao 面板系统（⚠️ 含 Yunzai 硬编码路径，见注意事项） |
| `data/` | **首次上传留空**；运行时自动生成（`classic_novels.json` 等基础数据可单独提供 `data/_init/` 子目录） |
| `docs/` | 文档（upload-checklist.md 本文件 + novel_system_step3_2026-08-01.md） |

### 已排除（`.gitignore` 自动跳过）

- 所有 `__pycache__/` 和 `*.pyc`
- 所有 `.log`（含 `botpy.log`）
- `data/bots.json`（机器人凭证）
- `data/admin_auth.json`（控制台访问口令）
- `data/bots/`（各机器人独立数据 / 群资料）
- `data/market_cache/`（插件市场缓存）
- `data/*.json`（运行时自动生成）
- `.vscode/` `.idea/` 等编辑器配置
- `*.tmp` `*.bak` 等临时文件

### 上传后由接收者补的内容

- `modules/config.py` 里的 AppID / Secret / 各第三方 API key
- `data/bots.json` 第一次启动后会自动用 `modules/config.py` 的值种子生成
- `data/admin_auth.json` 第一次启动会强制走 `setup.html` 初始化向导
- 体验群加入链接（控制台 → 运行设置 → 体验群加入链接）
- 问题反馈表单链接（控制台 → 运行设置 → 问题反馈表单链接）

---

## 三、上传步骤（git 命令）

```powershell
# 1) 初始化主项目仓库
cd c:\Users\123\Desktop\小流萤bot
git init
git add .
git status   # 重点 review 一下 staged 文件，确认没有日志/凭证/隐私

git commit -m "init: 小流萤 QQ 机器人开源 v2026.08.20"
git remote add origin https://github.com/<your-github-username>/小流萤bot.git
git branch -M main
git push -u origin main
```

> ⚠️ 第一次 push 之前一定要先 `git status` 看一下 staged 文件列表，重点检查：
> - 没有 `botpy.log` / `*.log`
> - 没有 `data/bots.json` / `data/admin_auth.json`
> - 没有 `__pycache__/`
> - 没有 `*.pyc`
> - 没有大尺寸图库（`assets/wife/` 等 2.5G 素材）

---

## 四、上传后验证

1. 浏览器打开仓库的 `README.md` → 中文正常渲染
2. 克隆到另一台电脑 → 按 README「第 3 步：填写配置」修改 → `python bot.py` 启动 → 自动跳到 `setup.html` 设置访问口令 → 控制台能进
3. 控制台「机器人管理」手动添加一个机器人 → `data/bots.json` 自动写入
4. 在群里发 `#` 能看到菜单（多机器人 / 单机器人都能验证）

---

## 五、开源注意事项（README 中已声明）

- **genshin / genshin_miao 插件**：依赖 `lib/genshin_panel_miao` 且面板渲染需要**本机另装 Yunzai**（`C:\Users\123\Desktop\Yunzai\` 硬编码路径，未去除），无 Yunzai 环境下面板功能不可用（其余功能不受影响）
- **wife_today 图库**：2.5G 素材未随仓库分发，接收者需自行准备 `assets/wife/` 图片
- **第三方 API key**：源码中全部留空，使用对应功能前需自行到对应平台注册并填到 `modules/config.py`
- **体验群 / 反馈表单**：均通过控制台运行时设置 `experience_group.url` / `feedback.form_url` 维护，不会在源码里泄露个人 ID
- **config.yaml**：仅作占位说明，**不被 bot 读取**（README 已多处提醒）

---

## 六、变更记录

- **2026-08-20**：
  - 路径从 `D:\小流萤bot-public\` 改为 `c:\Users\123\Desktop\小流萤bot\`
  - 隐私清理：feedback / experience_group / 5 个第三方 API key 全部清空
  - 新增 `.gitignore`（之前缺失）
  - 新增 `〇、上传前隐私清理` 章节
  - README + 控制台说明文档同步重写（v2026.08.20）
- **2026-08-19**：原版初稿
