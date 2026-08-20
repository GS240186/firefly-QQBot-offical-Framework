# 小流萤 QQ 机器人

小流萤是一个基于腾讯官方 [botpy](https://bot.q.qq.com/wiki/develop/pythonsdk/) SDK 开发的 QQ 官方机器人（频道机器人）。
它自带一个**网页管理控制台**，并内置了原神/星铁面板、群管理、插件市场等常用功能。

本说明面向**完全没接触过编程的小白**，跟着下面 5 步做，就能把它跑起来。

> ⚠️ 重要提示（先看）：
>
> 1. `config.yaml` **只起说明作用**，bot 真正读取的不是它。**真正的配置入口是 `modules/config.py` 和 `data/bots.json`**，详见「第 3 步：填写配置」。
> 2. `data/bots.json` 是运行时多机器人凭证文件，每次启动会自动重新生成；清空它能让机器人列表回到空状态。
> 3. 修改任何代码后，必须先停掉旧进程、清理 `__pycache__`、再 `python bot.py` 重启（详见「第 5 步：启动机器人」）。

---

## 一、开始前，你需要准备两样东西

1. **一台电脑（Windows 推荐）**，能正常上网。
2. **一个 QQ 机器人账号（AppID / Token / Secret）**。
   去 [QQ 开放平台](https://q.qq.com) 注册并创建一个「机器人」应用，创建成功后就能看到这三个值。
   （这是官方的「频道机器人」，不是你的个人 QQ 号，也不需要会员。）

> 小贴士：如果你只是想先看看界面，可以先用 QQ 开放平台的「沙箱环境」测试，不影响正式机器人。

---

## 二、5 步跑起来（小白版）

### 第 1 步：安装 Python

1. 打开 https://www.python.org/downloads/ ，下载最新版的 Python（3.8 以上即可，推荐 3.11）。
2. 安装时**一定要勾选「Add Python to PATH」**（添加到环境变量），否则后面会报错。
3. 安装完成后，按 `Win + R`，输入 `cmd` 回车，在黑框里输入：

   ```bash
   python --version
   ```

   如果显示出 `Python 3.x.x` 就说明装好了。

### 第 2 步：拿到机器人的「钥匙」

登录 [QQ 开放平台](https://q.qq.com)，进入你创建的机器人，复制下面三个值备用：

- **AppID**
- **Token**
- **Secret**

> 实际生效的是 **AppID + Secret**（botpy 用这两个去拿 access token）。
> 「Token」是 QQ 开放平台上对凭证的统称，并不是一个独立的字段。

### 第 3 步：填写配置（重要！）

新手**只需要关心一个文件**：`modules/config.py`。

用记事本打开它，把文件最上面这两行改成你自己的值：

```python
# modules/config.py
APPID = "你的AppID"
SECRET = "你的Secret"
```

如果你要沙箱测试，再把 `BOT_ENVIRONMENT` 改成 `"sandbox"`（同一文件里）：

```python
BOT_ENVIRONMENT = "sandbox"   # 测试用；正式上线改成 "production"
```

> ⚠️ `config.yaml` 在项目里**只是一个说明性占位文件**，里面的 `appid/token` 不会被读取。**改它没用！**
>
> 想跑多机器人（同一个 bot 进程里跑多个机器人实例）时，**不要手动改 config.py**，而是去管理控制台「机器人管理」里添加；它会写到 `data/bots.json` 里，运行时生效。

### 第 4 步：安装依赖

在本文件夹地址栏输入 `cmd` 回车，执行：

```bash
pip install -r requirements.txt
```

等待它跑完（第一次会比较慢，耐心等）。

### 第 5 步：启动机器人

**不要直接双击 `go.cmd`** — `go.cmd` 只有一行 `python bot.py`，双击运行后窗口会立即关闭，看不到报错。

推荐做法（手动命令行）：

1. 在本文件夹地址栏输入 `cmd` 回车，打开命令行。
2. 先确认没有旧的 bot 进程在跑：

   ```bash
   tasklist | findstr python
   ```

   如果有输出，执行 `taskkill /F /IM python.exe` 结束它们。
3. 清理缓存（修改代码后必做，否则可能加载到旧的 .pyc）：

   ```bash
   rd /s /q __pycache__
   rd /s /q lib\__pycache__
   rd /s /q modules\__pycache__
   ```
4. 启动：

   ```bash
   python bot.py
   ```

看到「**管理控制台已启动，访问地址: http://127.0.0.1:9988/**」就说明启动成功了。
控制台会**自动用 Edge 浏览器**打开（如果电脑里装了 Edge）。

如果想省事、又想看日志，可以在第 4 步前先 `go.cmd` 启动一次，再立刻去看当前目录的 `botpy.log` 日志。

---

## 三、第一次打开控制台，要做两件重要的事

控制台是你管理机器人的「后台」，为了保护它，**第一次打开会要求你初始化并设置一道访问口令**：

1. **初始化向导**：按页面提示填写基础信息，完成初始化。
2. **设置访问口令**：设置一个 6 位以上的密码（请牢记！）。

> 重要：设置完之后，**以后每次启动或重启机器人，打开控制台都要先输入这道访问口令**才能进入。
> 这是为了防止别人随便进你的后台。

**如果忘了访问口令怎么办？**
把本文件夹里 `data/admin_auth.json` 这个文件删掉，然后重启机器人，就会重新走一遍初始化向导、重新设置口令。

---

## 四、怎么跟机器人聊天、用功能

机器人跑起来并加入某个 QQ 频道后：

1. 在频道里 **@ 机器人** 再发消息，它才会回应。
2. 常用功能用「指令前缀」触发：
   - 原神相关：消息以 **`#`** 开头（例如发 `#原神` 看菜单）
   - 星铁相关：消息以 **`*`** 开头（例如发 `*星铁` 看菜单）
3. 具体能查什么，在 QQ 里发 `#` 或 `*` 就能看到功能菜单。

---

## 五、控制台里能干什么

打开 http://127.0.0.1:9988/ 并输入访问口令后，你会看到：

- **仪表盘**：查看机器人运行状态、电脑 CPU / 内存 / 显卡占用等。
- **机器人管理**：**新增 / 删除 / 启用 / 停用机器人**。所有改动会写到 `data/bots.json`，自动生效（已运行的实例下次重连时切换）。
- **插件**：启用 / 关闭功能插件，也能从插件市场安装新插件。
- **群管理**：查看群成员、审批加群请求、设置禁言等。
- **数据中心**：查看运行统计与缓存数据。
- **游戏面板**：原神 / 星铁角色面板、圣遗物评分、伤害计算等。

不同页面的具体按钮都有中文标注，跟着点就行。

---

## 六、清空 / 重新初始化

如果出现「我明明没配置机器人却自动出现一个」、「机器人列表乱套」、「想完全重置」等情况，按下面做：

### 6.1 清空机器人列表（回到初始空状态）

1. 停掉 bot 进程（`taskkill /F /IM python.exe`）。
2. 把 `modules/config.py` 里的 `APPID` 和 `SECRET` 改成空串：

   ```python
   APPID = ""
   SECRET = ""
   ```
3. 删除 `data/bots.json`。
4. 重新 `python bot.py` 启动。

启动后日志里如果出现「**尚未启用任何 QQ 机器人。请在控制台菜单『机器人管理』中添加凭证并启用，控制台将自动连接。**」就说明清空成功。

### 6.2 重置控制台访问口令

1. 停掉 bot 进程。
2. 删除 `data/admin_auth.json`。
3. 重新 `python bot.py` 启动 → 重新走一遍初始化向导、重新设口令。

### 6.3 完全重置（清掉所有运行数据）

警告：以下操作会**删除所有缓存、群资料、用户资料、统计数据**等，请先备份 `data/` 目录。

```bash
rd /s /q data\bots
rd /s /q data\market_cache
del data\bots.json
del data\admin_auth.json
del data\*.json
rd /s /q __pycache__ lib\__pycache__ modules\__pycache__
```

然后 `python bot.py` 重新启动。

---

## 七、常见问题（排错）

**1. 提示「python 不是内部或外部命令」**
说明第 1 步没勾选「Add Python to PATH」。重新安装 Python 并勾选那一项，或者重启电脑后再试。

**2. 浏览器打不开 / 提示无法访问**
- 确认机器人已经启动成功（看命令行窗口或 `botpy.log` 末尾是否有「管理控制台已启动」）。
- 确认访问地址是 `http://127.0.0.1:9988/` （注意是 9988 端口）。
- 如果提示端口被占用，关掉其他可能占用 9988 的程序再重启。

**3. 机器人连不上 QQ / 没反应 / 一直报「invalid appid or secret」**
- **检查 `modules/config.py` 第 5-6 行的 `APPID` / `SECRET` 是否填对**（注意：是 `config.py`，不是 `config.yaml`）。
- 确认 QQ 开放平台里机器人是「已上线」状态。
- 沙箱测试请把 `modules/config.py` 里的 `BOT_ENVIRONMENT` 改成 `"sandbox"`，并且 appid/secret 也用沙箱的值。
- 如果改完仍然显示旧的机器人：删除 `data/bots.json` 再重启（见「6.1 清空机器人列表」）。

**4. 我没配置任何机器人，为什么管理后台里出现了一个？**
这是**种子机制**：第一次运行时 `data/bots.json` 不存在，bot 会从 `modules/config.py` 里的 `APPID` / `SECRET` 播种一条默认记录到 `data/bots.json`。
解决方法：把 `modules/config.py` 里的 `APPID` / `SECRET` 改成空串 + 删除 `data/bots.json` 后重启（见「6.1」）。

**5. 忘记访问口令**
见「三、第一次打开控制台」最后一段：删掉 `data/admin_auth.json` 重启即可重设。

**6. 改完代码没生效 / 行为怪异**
99% 是 `__pycache__` 没清。停掉 bot 进程 → `rd /s /q __pycache__ lib\__pycache__ modules\__pycache__` → 重新 `python bot.py` 启动。

**7. 双击 `go.cmd` 窗口立刻关闭 / 看不到报错**
因为 `go.cmd` 只有一行 `python bot.py`，双击在 Windows 下会闪退。请改用「第 5 步」里的命令行方式启动。

---

## 八、项目结构（了解即可，不用改）

```
小流萤bot/
├── bot.py              # 机器人主程序（同时也负责启动网页控制台）
├── console_server.py   # 网页控制台后端（运行在 9988 端口，提供 /api/* 接口）
├── config.yaml         # ⚠️ 仅为占位说明文件，bot 不会读取它
├── config.py → modules/config.py   # ✅ 真正的全局配置（含 APPID / SECRET / 环境 / API key）
├── requirements.txt    # Python 依赖清单
├── go.cmd              # Windows 一键启动（= python bot.py，会闪退，建议用命令行）
├── admin/              # 控制台前端页面（双击 admin/index.html 也可直接打开）
├── lib/                # 核心功能库（原神/星铁面板等）
├── modules/            # 内置功能模块
├── plugins/            # 外置插件（改了会热加载，免重启）
├── data/               # 运行数据（自动生成）
│   ├── bots.json       # 机器人凭证列表（运行时由「机器人管理」维护）
│   ├── admin_auth.json # 控制台访问口令
│   ├── bots/           # 各机器人独立数据
│   ├── market_cache/   # 插件市场缓存
│   └── *.json          # 群资料 / 签到 / 配置 等
├── docs/               # 开发文档
├── PLUGIN_DEV_GUIDE.md # 插件开发指南
└── README.md           # 本文件
```

---

## 九、给想二次开发的人

- 想自己写插件，请看 `PLUGIN_DEV_GUIDE.md` 和 `docs/` 目录。
- 外置插件放在 `plugins/` 下，保存后几秒内自动生效（后台有看门狗），不用重启。
- 核心库改动在 `lib/`，改完需要重启机器人。
- 增加 / 修改内置模块在 `modules/`，改完需要重启机器人并清 `__pycache__`。
- `data/bots.json` 的字段含义（不要手改，建议走控制台）：

  ```json
  {
    "bots": [
      {
        "appid": "你的AppID",
        "secret": "你的Secret",
        "environment": "production 或 sandbox",
        "event_mode": "websocket 或 webhook",
        "enabled": true,
        "name": "可选，机器人显示名"
      }
    ]
  }
  ```

> 说明：本仓库**不含任何真实的机器人密钥或个人信息**。使用前请务必在 `modules/config.py` 填写你自己的 AppID / Secret，并自行设置控制台访问口令。
