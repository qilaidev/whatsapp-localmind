---
name: whatsapp-localmind
description: macOS WhatsApp 本地群聊信息提取与结构化清洗能力层 (CLI & MCP)。提供只读原子快照、群成员实名与 @lid 跨表还原、增量游标拉取 (--after-id)、150字引用链还原、撤回消息剔除及沙盒媒体附件按需导出。
---

# WhatsApp-LocalMind 本地提取能力层 (`whatsapp-localmind` CLI & MCP)

本技能是纯粹的 **macOS WhatsApp 本地群聊只读数据提取能力底座**，与微信提取层（`wechat-localmind`）100% 物理隔离、绝对解耦。仅以离线只读模式（`sqlite3_backup` 热备快照 + `mode=ro`）提取群聊（`@g.us`）数据与沙盒内媒体附件，**100% 拦截个人私聊（`@s.whatsapp.net` / `@lid` 私聊），绝不包含任何消息发送或原库写回逻辑**，零外部网络请求、零封号风险。

## 可执行程序调用方式

按以下优先级调用 CLI（纯 Python 标准库实现，零第三方依赖）：
1. 全局命令：直接运行 `whatsapp-localmind <subcommand>`（或 `~/.local/bin/whatsapp-localmind <subcommand>`）。
2. 技能内置脚本：运行本技能目录下的 `scripts/whatsapp-localmind <subcommand>`。

---

## 核心子命令与参数契约

### 1. 环境与 TCC 权限自检 (`doctor`)
检查本地 WhatsApp 数据库可读性、macOS `Full Disk Access` 权限、最新消息时间与全局最大游标 `global_latest_msg_id`：
```bash
whatsapp-localmind doctor --format json
```

### 2. 获取可访问群聊列表与最新游标 (`groups`)
列出所有符合当前黑白名单策略的群聊及其 `chat_id` (`@g.us`)、`latest_msg_id`、过去 24h 消息数、群成员数：
```bash
whatsapp-localmind groups [--keyword <关键词>] [--include-blocked] --format json
```

### 3. 提取群聊清洗后消息流 (`fetch`)
支持 **全局增量游标模式 (`--after-id`)** 与 **时间窗口模式 (`--since`)**：
```bash
# 按时间窗口提取（默认附带前 10 条历史上下文缓冲窗，输出标准 Markdown 对话流并自动折叠连续“收到/OK”噪音）
whatsapp-localmind fetch --chats ALL_ALLOWED --since 12h --format md

# 按全局单调递增游标无重无漏增量提取（输出结构化 JSON）
whatsapp-localmind fetch --chats ALL_ALLOWED --after-id 128500 --format json

# 提取指定单个或多个群聊并强制立即刷新 SQLite 热备快照
whatsapp-localmind fetch --chats "1203630xxx@g.us" --since 24h --fresh --format md
```

### 4. 跨群关键词检索 (`search`)
在所有放行群聊中搜索正文、图片配文（Caption）或文档文件名包含关键词的消息（每条命中自动附带同群前后各 3 条上下文消息）：
```bash
whatsapp-localmind search --query "报价单" --since 30d --context 3 --format md
```

### 5. 按需受控导出沙盒内语音/文档/图片实体 (`export-media`)
当消息流中出现 `local_available: true` 的未转写长语音（`.opus`）或关键文档（`.pdf` / `.xlsx`）时，凭 `msg_id` 导出至共享缓存目录供上层多模态 Skill 读取：
```bash
whatsapp-localmind export-media --msg-ids 128498,128499 --format json
```

### 6. 身份锚点与群黑白名单配置 (`config`)
```bash
# 查看当前配置
whatsapp-localmind config show

# 设置本人群昵称与手机号后 4 位（用于将本人消息标记为 [我(姓名)] 及还原 [@我(姓名)]）
whatsapp-localmind config set-identity --name "张工" --phone-suffix "8888"

# 屏蔽特定生活/亲友群（黑名单模式默认开启）
whatsapp-localmind config block "1203630xxx@g.us"
```

---

## 标准流与退出码契约

- **`stdout`**：100% 仅输出纯净的 JSON 或 Markdown 结构化结果（可直接通过管道传给 `jq`）。
- **`stderr`**：输出错误详情 JSON（含 `error_code`、`exit_code`、`message`）。
- **POSIX 退出码**：
  - `0` (`EXIT_SUCCESS`)：执行成功
  - `1` (`EXIT_USAGE_ERROR`)：参数错误
  - `2` (`EXIT_ENV_OR_PERM_ERROR`)：数据库不存在或缺少 macOS `Full Disk Access` 权限
  - `3` (`EXIT_POLICY_DENIED`)：隐私策略拦截（尝试访问一对一私聊或黑名单群聊）
  - `4` (`EXIT_RESOURCE_NOT_FOUND`)：目标 `msg_id` 不存在或附件尚未在客户端下载到本地
  - `5` (`EXIT_INTERNAL_DB_ERROR`)：SQLite 内部异常
