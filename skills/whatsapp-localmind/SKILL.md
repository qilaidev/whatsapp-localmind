---
name: whatsapp-localmind
description: macOS WhatsApp 本地全量聊天信息只读提取与结构化清洗能力层 (v4.0.0 CLI & MCP)。默认支持一对一私聊（@s.whatsapp.net / @lid / 手机号直查）、群聊（@g.us）、频道（@newsletter）与广播列表，提供 sqlite3_backup 只读原子快照、四级实名与 @lid 跨表桥接、增量游标拉取 (--after-id)、150字引用链还原、撤回消息剔除、可选会话范围策略 (config set-scope + 黑白名单)、5 个只读 MCP 工具及沙盒媒体附件按需导出。
---

# WhatsApp-LocalMind 本地全量提取能力层 (`whatsapp-localmind` CLI & MCP `v4.0.0`)

本技能是纯粹的 **macOS WhatsApp 本地全量聊天只读数据提取能力底座**，与微信提取层（`wechat-localmind`）100% 物理隔离、绝对解耦。仅以离线只读模式（`sqlite3_backup` 热备快照 + POSIX `flock` + `mode=ro`）读取 `ChatStorage.sqlite`、`LID.sqlite`、`ContactsV2.sqlite` 与 `Message/` 沙盒附件：

- **默认全量会话覆盖 (`chat_scope = "all"`)**：原生支持 **一对一私聊**（`@s.whatsapp.net`、`@lid` 及裸手机号如 `+86139...`，自动跨表桥接 `@lid` ↔ `@s.whatsapp.net`）、**群聊**（`@g.us`）、**频道**（`@newsletter`）与**广播列表**（`@broadcast`）；自动剔除瞬态动态 `status@broadcast`。
- **可选隐私范围与黑白名单过滤**：支持通过 `config set-scope <all|groups|direct|newsletter>`（或环境变量 `WHATSAPP_LOCALMIND_CHAT_SCOPE`）按需收紧可见范围，并配合 `blacklist`（默认）/ `whitelist` 规则对任意合法 JID 或手机号进行精准屏蔽/放行；越权访问统一返回退出码 `3`（`EXIT_POLICY_DENIED`）。
- **100% 离线只读与零风险**：绝不包含任何消息发送、已读回执篡改或原库写回逻辑，零外部网络请求、零封号风险。

## 可执行程序调用方式

按以下优先级调用 CLI（纯 Python 3.10+ 标准库实现，零第三方 pip 依赖）：
1. 全局命令：直接运行 `whatsapp-localmind <subcommand>`（或 `~/.local/bin/whatsapp-localmind <subcommand>`）。
2. 技能内置脚本：运行本技能目录下的 `scripts/whatsapp-localmind <subcommand>`。

---

## 核心子命令与参数契约（10 个子命令）

### 1. 环境与 TCC 权限自检 (`doctor`)
检查本地 WhatsApp 容器路径、`ChatStorage.sqlite` / `LID.sqlite` / `ContactsV2.sqlite` 可读性、macOS `Full Disk Access` 权限、私聊/群聊会话统计、`chat_scope` 策略与全局最大游标 `global_latest_msg_id`：
```bash
whatsapp-localmind doctor --format json
```

### 2. 列出可访问全量会话 (`chats` / `list-chats`)
默认列出当前 `chat_scope` 与黑白名单策略下允许的所有会话（含私聊、群聊、频道、广播），返回 `chat_id`、`chat_name`（及向后兼容 `group_name` 别名）、`chat_type`、`latest_msg_id`、过去 24h 消息数与参与人数：
```bash
# 列出全部允许会话
whatsapp-localmind chats --format json

# 按会话类型过滤：all | direct | group | newsletter | broadcast
whatsapp-localmind chats --type direct --format md
whatsapp-localmind chats --type group --keyword "供应链" --include-blocked --format json
```

### 3. 向后兼容群聊列表 (`groups` / `list-groups`)
等效于 `chats --type group`，仅返回 `@g.us` 群聊（JSON 同时保留 `groups` 与 `chats` 字段）：
```bash
whatsapp-localmind groups [--keyword <关键词>] [--include-blocked] --format json
```

### 4. 提取清洗后消息流 (`fetch`)
支持 **全量/分组/单会话通配**、**`--type` 类型过滤**、**全局增量游标 (`--after-id`)** 与 **时间窗口 (`--since`)**，自动完成四级实名还原（兜底标签为 `联系人(+XX-XXXX)` / `联系人#XXXX`）、白名单 `@提及`、150 字父消息引用链并剔除撤回消息：
```bash
# 提取所有允许会话（含私聊、群聊、频道）最近 12h 消息，输出 Markdown 并折叠连续“收到/OK”噪音
whatsapp-localmind fetch --chats ALL_ALLOWED --since 12h --format md

# 仅提取全部私聊 (ALL_DIRECT) 或全部群聊 (ALL_GROUPS)
whatsapp-localmind fetch --chats ALL_DIRECT --since 24h --format md
whatsapp-localmind fetch --chats ALL_GROUPS --after-id 128500 --format json

# 提取指定会话（支持 @s.whatsapp.net、@lid、@g.us、@newsletter 或裸手机号）并强制刷新快照
whatsapp-localmind fetch --chats "8613900008888@s.whatsapp.net,1203630xxx@g.us" --since 24h --fresh --format md

# 也可通过 --type 在通配或显式清单基础上二次过滤
whatsapp-localmind fetch --chats ALL_ALLOWED --type direct --since 7d --limit 500 --format json
```

### 5. 跨会话关键词检索 (`search`)
在允许会话范围内搜索正文、图片配文（Caption）或文档文件名包含关键词的消息（每条命中自动附带前后各 `N` 条上下文消息）：
```bash
# 全局检索（默认 ALL_ALLOWED）
whatsapp-localmind search --query "报价单" --since 30d --context 3 --format md

# 限定仅在私聊或指定会话中检索
whatsapp-localmind search --query "合同" --type direct --since 30d --format json
whatsapp-localmind search --query "排期" --chats ALL_GROUPS --limit 50 --format md
```

### 6. 按需受控导出沙盒内语音/文档/图片实体 (`export-media`)
当消息流中出现 `local_available: true` 的未转写长语音（`.opus`）或关键文档（`.pdf` / `.xlsx`）时，凭 `msg_id` 导出至 `snapshot/media/` 并返回绝对路径（导出前强制校验所属会话未被 `chat_scope` 或黑白名单拦截）：
```bash
whatsapp-localmind export-media --msg-ids 128498,128499 --format json
```

### 7. 身份锚点、会话范围与黑白名单配置 (`config`)
```bash
# 查看当前配置（含 chat_scope、filter_mode、identity、blacklist_chats、whitelist_chats）
whatsapp-localmind config show

# 设置本人显示名称与手机号后 4 位（用于将本人消息标记为 [我(姓名)] 及还原 [@我(姓名)]）
whatsapp-localmind config set-identity --name "张工" --phone-suffix "8888"

# 按需调整全局会话可见范围：all (默认) | groups | direct | newsletter
whatsapp-localmind config set-scope all
whatsapp-localmind config set-scope groups

# 切换过滤模式（blacklist 默认 | whitelist）
whatsapp-localmind config set-mode blacklist
whatsapp-localmind config set-mode whitelist

# 对任意合法 JID（@s.whatsapp.net / @lid / @g.us / @newsletter）或裸手机号执行屏蔽/放行
whatsapp-localmind config block "1203630xxx@g.us" "+8613800138000"
whatsapp-localmind config unblock "1203630xxx@g.us"
whatsapp-localmind config allow "8613900008888@s.whatsapp.net"
whatsapp-localmind config disallow "8613900008888@s.whatsapp.net"
```

### 8. 清理导出媒体缓存与本地快照 (`clean`)
```bash
# 仅清理 snapshot/media/ 下导出的媒体文件，保留 SQLite 快照
whatsapp-localmind clean --media-only --format json

# 同时删除导出的媒体缓存与本地 SQLite 快照文件（默认 --all）
whatsapp-localmind clean --all --format json
```

### 9. 启动只读 MCP Stdio Server (`mcp-serve`)
```bash
whatsapp-localmind mcp-serve [--config <config.json>]
```

### 10. 安装 CLI 软链与技能包 (`install`)
```bash
whatsapp-localmind install --bin-dir ~/.local/bin --skill-dir ~/.gemini/config/skills
```

---

## 只读 MCP Stdio 工具契约（5 个工具，均声明 `readOnlyHint: true`）

| MCP Tool | 必填参数 | 关键可选参数 | 能力说明 |
| :--- | :--- | :--- | :--- |
| `whatsapp_list_chats` | 无 | `chat_type` (`all\|direct\|group\|newsletter\|broadcast`), `keyword`, `include_blocked`, `format`, `fresh` | 列出允许访问的全量 WhatsApp 会话（私聊/群聊/频道）及最新游标 |
| `whatsapp_list_groups` | 无 | `keyword`, `include_blocked`, `format`, `fresh` | 向后兼容列出允许访问的 `@g.us` 群聊列表 |
| `whatsapp_fetch_messages` | `chat_ids` (`string[]`) | `chat_type`, `after_msg_id`, `since` (`24h`), `until`, `context_buffer` (`10`), `limit_per_chat` (`500`), `fold_noise` (`true`), `format`, `fresh` | 支持 `["ALL_ALLOWED"]` / `["ALL_DIRECT"]` / `["ALL_GROUPS"]` 或指定 JID 数组提取清洗消息流 |
| `whatsapp_search_messages` | `query` (`string`) | `chat_ids`, `chat_type`, `since`, `context` (`3`), `limit` (`50`), `format`, `fresh` | 跨允许会话检索文本、配文与文档标题并附带前后上下文 |
| `whatsapp_export_media` | `msg_ids` (`int[]`) | `fresh` | 按 `msg_id` 导出沙盒内语音/文档/图片至 `snapshot/media/` 并返回绝对路径 |

---

## 环境变量、标准流与退出码契约

- **环境变量覆盖**：
  - `WHATSAPP_LOCALMIND_CONTAINER_DIR`：自定义 WhatsApp Group Container 目录路径
  - `WHATSAPP_LOCALMIND_SNAPSHOT_DIR`：自定义隔离快照与导出媒体缓存目录路径
  - `WHATSAPP_LOCALMIND_CHAT_SCOPE`：临时覆盖配置中的 `chat_scope`（`all | groups | direct | newsletter`）
- **`stdout`**：100% 仅输出纯净的 JSON 或 Markdown 结构化结果（可直接通过管道传给 `jq`）。
- **`stderr`**：输出错误详情 JSON（含 `error`、`error_code`、`exit_code`、`message`）。
- **POSIX 退出码**：
  - `0` (`EXIT_SUCCESS`)：执行成功
  - `1` (`EXIT_USAGE_ERROR`)：参数或时间格式错误
  - `2` (`EXIT_ENV_OR_PERM_ERROR`)：数据库不存在或缺少 macOS `Full Disk Access` (TCC) 权限
  - `3` (`EXIT_POLICY_DENIED`)：隐私策略拦截（`CHAT_SCOPE_DENIED` 超出 `chat_scope`、`CHAT_BLOCKED_BY_POLICY` 被黑白名单屏蔽、`STATUS_BROADCAST_DENIED` 访问 `status@broadcast`，或尝试导出已撤回/越界沙盒媒体）
  - `4` (`EXIT_RESOURCE_NOT_FOUND`)：目标会话/`msg_id` 不存在，或附件尚未在客户端下载到本地
  - `5` (`EXIT_INTERNAL_DB_ERROR`)：SQLite 内部异常
