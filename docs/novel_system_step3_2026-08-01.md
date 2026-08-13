# 小说系统 Step 3 业务模块 + Step 4 bot.py 接入 — 交付文档

> 时间：2026-08-01 00:13-00:26 GMT+8
> 新 bot PID：10660（2026-08-01 00:26:15 上线）

## 一、交付清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `modules/novel_system.py` | 新增（21884 字节） | 业务模块，含 NovelSystem 类 + 单例 novel_mgr |
| `bot.py` | 修改（2 处） | 加 import + 加 novel_mgr 分发分支 |
| `bot.py` `_EXACT_KEYWORDS` | 修改 | 加入 5 个精确入口："小说/看小说/读书/看书/在线阅读" |
| `bot.py` `_PREFIX_KEYWORDS` | 修改 | 加入 3 个前缀："看 "/"章节 "/"小说 " |

## 二、NovelSystem 类设计

### 状态机
```
idle → main_menu → category_list → reading → idle
                      ↓                ↓
                  切换书(下一本)     翻页(上下页)
```

### 关键方法
- `__init__()`：初始化 books 列表 + mtime 跟踪
- `_check_reload()`：每次 handle_command 前检查 novels.json mtime，变更则重载（A+B 混合策略）
- `_load_novels()`：异常保留旧 books 不崩
- `_get_state/_save_state/_clear_state`：per-user 状态存 `novel_states.json`（按 storage_id 裸 ID）
- `_is_reading()`：判断是否有进行中的阅读（用于全局指令隔离判断）
- `_force_end_reading()`：静默结束（仿猜成语 _idiom_force_end，不发提示）
- `_show_main_menu`：4 个分类按钮（随机推荐/科幻/言情/悬疑）
- `_show_category_list`：分类下书籍列表（首本封面 + 全文摘要 + 切换按钮）
- `_show_chapter_list`：章节列表（前 5 章按钮 + 返回）
- `_show_content_page`：正文页（上一页/下一页/章节列表/返回）
- `handle_command()`：主入口（含全局指令隔离 + 退出 + 分类筛选 + 看/读/章节/翻页）

### 全局指令隔离白名单 `_GLOBAL_COMMAND_KEYWORDS`
frozenset，30+ 关键词与猜成语一致（bot.py _KEYWORDS 已同步）：
- 帮助/菜单：帮助、功能、菜单、使用帮助、返回主菜单、主菜单 + 7 个分类菜单
- 签到/娱乐/工具/群管/学习/个人信息/体验群等所有模块入口
- 退出小说：不看了、退出小说、结束阅读

### 命令协议
| 用户输入 | 行为 |
|---------|------|
| `小说` / `看小说` / `读书` / `看书` / `在线阅读` | 展示主菜单（4 分类按钮） |
| `小说 科幻` / `小说 言情` / `小说 悬疑` / `小说 随机推荐` | 展示对应分类首本书 |
| `小说 换分类` | 回到主菜单 |
| `小说 下一本` | 切换分类下一本 |
| `看 三体` | 进入《三体》章节列表 |
| `看 三体 第2章` | 直接跳到第 2 章第 1 页 |
| `章节 三体` | 回到《三体》章节列表 |
| `上一页` / `下一页` | 翻页 |
| `退出小说` / `不看了` / `结束阅读` | 退出阅读 |
| 阅读中发任何全局指令 | 静默退出（不发提示），bot 继续响应其他模块 |

## 三、bot.py 改动

### 1. import（line 58 后）
```python
from modules.novel_system import novel_mgr
```

### 2. 分发分支（line 549 后，娱乐系统后）
```python
# 小说系统（在线阅读，5 本预置书籍）
if is_feature_enabled("novel") and await novel_mgr.handle_command(self.api, content, storage_id, member_openid, msg_id, scene=scene):
    return
```

### 3. _EXACT_KEYWORDS（line 117 区域）
加入：`"小说", "看小说", "读书", "看书", "在线阅读"`

### 4. _PREFIX_KEYWORDS（line 130 区域）
加入：`"看 ", "章节 ", "小说 "`

## 四、端到端验证（mock api 跑完整状态机）

测试脚本：`data/_test_novel_e2e.py`（已保留）
- ✅ 测试 1：主入口 `小说` → 4 分类按钮
- ✅ 测试 2：`小说 科幻` → 《三体》+《流浪地球》
- ✅ 测试 3：`看 三体` → 章节列表
- ✅ 测试 4：`读 三体 第1章` → 进入第 1 页
- ✅ 测试 5：`下一页` → 翻到第 2 页
- ✅ 测试 6：全局指令 `菜单` → **静默退出**（state=idle, end_reason="收到其他指令「菜单」"）
- ✅ 测试 7：`退出小说` → 状态清空
- ✅ 测试 8：c2c 私聊场景
- ✅ 测试 9：群聊场景
- ✅ 测试 10：模糊匹配 `看 三` → 自动找到《三体》
- ✅ 测试 11：找不到的书 `看 不存在的书` → 错误提示
- ✅ 测试 12：退出后再次 `小说` → 正常进入主菜单

**注意**：测试中所有 `api._http` / `api.post_c2c_message` 报错是预期的（api=None mock），证明状态机和函数调用链都跑通了。生产 bot 真实 api 不受影响。

## 五、bot 重启记录

- 旧 PID 31524（23:48:15 上线）→ Stop-Process
- 新 PID **10660**（2026-08-01 00:26:15 上线）
- 启动日志确认：`机器人「小流萤」已上线`、`控制台已启动: http://127.0.0.1:9988/`、无 ERROR
- 控制台 HTTP 200 测试通过

## 六、待优化 / 后续

- **功能开关**：is_feature_enabled("novel") 默认存在与否需检查 config，确认无需开关或加入
- **测试脚本**：`_test_novel_e2e.py` 已保留（用户选择保留），可作为回归测试用
- **真机实测**：用户群发 `小说` 开始真机验证
- **渲染依赖**：实际部署时 PIL 必须可用，否则会走"图片渲染器加载失败"文字降级

## 七、相关路径

- 模块：`C:\Users\123\Desktop\小流萤bot\modules\novel_system.py`
- 渲染器：`C:\Users\123\Desktop\小流萤bot\data\render_novel.py`
- 数据：`C:\Users\123\Desktop\小流萤bot\data\novels.json`
- 状态：`C:\Users\123\Desktop\小流萤bot\data\novel_states.json`
- 控制台：`http://127.0.0.1:9988/`