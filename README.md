# WhatsApp LocalMind (`whatsapp-localmind`)

**WhatsApp LocalMind（`whatsapp-localmind`）** 是一个零第三方运行时依赖、严格只读的 CLI 与 JSON-RPC 2.0 MCP Stdio Server，专为 Claude Desktop、Cursor、Google Antigravity 等 AI Agent 提取并清洗 **macOS 本地 WhatsApp 群聊（`@g.us`）** 对话与沙盒附件。它纯基于 Python 3.10+ 标准库构建，通过 `sqlite3_backup` 在线热备与 POSIX `flock` 生成 `?mode=ro` 隔离快照（覆盖 `ChatStorage.sqlite`、`LID.sqlite`、`ContactsV2.sqlite`），在 SQL 与媒体层物理拦截一对一私聊（`@s.whatsapp.net` / `@lid`），完成 `@lid` 跨表实名还原与 Protobuf 引用链解析，且零网络请求、零封号风险。

[![CI](https://github.com/qilaidev/whatsapp-localmind/actions/workflows/ci.yml/badge.svg)](https://github.com/qilaidev/whatsapp-localmind/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](https://www.python.org/)
[![Zero Dependencies](https://img.shields.io/badge/Dependencies-Zero%20Runtime%20Deps-brightgreen.svg)](./pyproject.toml)
[![Platform: macOS](https://img.shields.io/badge/Platform-macOS-black.svg)](#快速开始安装与挂载)
[![MCP Server](https://img.shields.io/badge/MCP-Stdio%20Read--Only-6E56CF.svg)](#mcp-stdio-server-接入与工具契约)
[![Agent CLI](https://img.shields.io/badge/Agent-CLI%20%26%20SKILL.md-orange.svg)](./skills/whatsapp-localmind/SKILL.md)

**简体中文** | **[English](./README.en.md)** | **[llms.txt](./llms.txt)** | **[codemeta.json](./codemeta.json)** | **[SKILL.md](./skills/whatsapp-localmind/SKILL.md)** | **[SECURITY](./SECURITY.md)** | **[CONTRIBUTING](./CONTRIBUTING.md)** | **[CHANGELOG](./CHANGELOG.md)** | **[LICENSE](./LICENSE)**

> **`*-localmind` 本地即时通讯只读提取能力层家族**
>
> 本仓库与姊妹仓 [`wechat-localmind`](https://github.com/qilaidev/wechat-localmind)（macOS & Windows 微信本地群聊提取能力层）同属 `qilaidev` 下的 **`*-localmind` 本地聊天提取家族**，两仓严格遵循统一的五项架构哲学：
> **100% 离线只读快照 + 物理拦截一对一私聊 + 四级实名还原 + 单调增量游标 + CLI & MCP 双协议交付**。

---

## 核心事实卡（Entity Snapshot）

| 属性 | 规格与事实 |
| :--- | :--- |
| **项目标识** | `whatsapp-localmind`（Python 包名 `wa_localmind`，当前版本 `v3.2.0`） |
| **开源协议** | [MIT License](./LICENSE) |
| **运行环境与依赖** | **macOS** + Python `>= 3.10`（**100% Python 标准库实现，零第三方 pip 依赖**；读取真实容器需授权终端 `Full Disk Access`） |
| **本地数据源** | macOS WhatsApp CoreData 容器（`ChatStorage.sqlite`、`LID.sqlite`、`ContactsV2.sqlite` 与 `Message/` 沙盒附件） |
| **隐私边界** | **仅限群聊（`@g.us`）**；在 SQL 与媒体层物理拦截 `@s.whatsapp.net` / `@lid` 一对一私聊及状态广播（越权直接返回退出码 `3`） |
| **交付协议** | 9 个 POSIX CLI 子命令（含 `list-groups` 别名）+ 4 个只读 JSON-RPC 2.0 MCP Stdio 工具 + `SKILL.md` 智能体技能包 |
| **默认快照目录** | `~/Library/Application Support/WhatsApp-LocalMind/snapshot`（可通过 `WHATSAPP_LOCALMIND_SNAPSHOT_DIR` 自定义） |
| **维护方与生态归属** | [`qilaidev`](https://github.com/qilaidev) · [qilai 独立工程工作室 (`qilaidav.com`)](https://qilaidav.com) |

---

## 定位边界：它是什么 / 不是什么

| 维度 | 它是什么（What it is） | 它不是什么（What it is not） |
| :--- | :--- | :--- |
| **运行模式** | **100% 离线只读本地提取层**：通过 `sqlite3_backup` + `flock` 离线读取 macOS WhatsApp CoreData SQLite 容器 | **不是**协议机器人或自动化外挂：不登录 WhatsApp Web、不模拟点击、不连接远程服务器 |
| **访问范围** | **物理级 `@g.us` 群聊隔离引擎**：在 SQL 与媒体层强制拦截一对一私聊（`@s.whatsapp.net` / `@lid`）与状态广播 | **不是**全量聊天导出器：严禁读取私聊记录，支持黑名单/白名单双模过滤 |
| **写入能力** | **纯只读（Read-Only）**：以 `?mode=ro` 打开隔离快照，绝不修改或锁死运行中的原库 | **不是**消息发送工具：绝不包含发消息、改已读回执或写回原数据库的代码 |
| **交付形态** | **AI Agent 原生交付底座**：内置 9 个 CLI 子命令、4 个只读 MCP 工具与 `SKILL.md` | **不依赖**任何第三方 pip 包：无需安装 `protobuf`、`mcp`、`sqlite-vec` 等外部库 |

---

## 适用场景与方案对比（Alternatives Comparison）

### 典型适用场景

| 使用场景 | 推荐入口 / 命令 | 核心收益 |
| :--- | :--- | :--- |
| **AI Agent 每日跨群摘要与行动项梳理** | MCP `whatsapp_fetch_messages` 或 `fetch --chats ALL_ALLOWED --since 24h` | 自动完成 `@lid` 桥接实名、150 字引用链还原，并折叠「收到 / OK / +1」噪音 |
| **无重无漏的增量群聊监控管道** | `fetch --chats ALL_ALLOWED --after-id <msg_id> --format json` | 基于 `ZWAMESSAGE.Z_PK` 单调游标推进，附带前 10 条历史缓冲窗与越界 24h 自动降级 |
| **跨群检索报价单 / 合同 / 技术文档** | `search --query "报价单" --context 3` 或 MCP `whatsapp_search_messages` | 联合检索正文、图片 Caption 与文档标题（`ZAUTHORNAME`）并带前后语境 |
| **受控导出群内长语音与办公文件** | `export-media --msg-ids 128498 --format json` 或 MCP `whatsapp_export_media` | 安全复制沙盒内 `.opus` / `.pdf` / `.xlsx` / 图片至缓存并返回绝对路径 |

### 同类方案架构对比

> 基于真实架构与能力边界对比不同路径，不虚构跑分与性能数字。

| 对比维度 | **WhatsApp LocalMind** | 裸用 `sqlite3` CLI 直查原库 | 非官方 Web 协议机器人（如 Baileys / `whatsapp-web.js`） | 官方 WhatsApp Business Cloud API |
| :--- | :---: | :---: | :---: | :---: |
| **账号封禁与风控风险** | 零风险（100% 离线快照、零网络请求） | 零风险（离线只读） | 存在封号/风控风险（依赖非官方协议与长连接心跳） | 合规，但需企业号与云端 Webhook 审核 |
| **数据驻留与隐私性** | 100% 本地闭环，零第三方服务器 | 本地读取 | 需维持远程 WebSocket/无头浏览器会话 | 消息经由 Meta 云端路由 |
| **运行中数据库并发安全** | `sqlite3_backup` + `flock` 合并 `-wal`，`?mode=ro` 查询 | 直接打开易受 WAL 锁冲突或遗漏未落盘日志 | 不适用 | 不适用 |
| **一对一私聊物理隔离** | SQL 与媒体层强制 `@g.us`（越权返回退出码 `3`） | 需每次人工手写 SQL 过滤，易漏 | 无硬性隔离，默认接收全部个人会话 | 面向企业客服单号模型 |
| **`@lid` 匿名 ID 与 Protobuf 解析** | 自动桥接 `LID.sqlite` + 手写零依赖 Protobuf 解析器 | 需自行联查多库并反序列化二进制 `ZMETADATA` | 协议层直接返回事件 | JSON Webhook 原生结构 |
| **AI Agent 原生交付（MCP + 游标）** | 4 个只读 MCP 工具 + 9 个 CLI 子命令 + `SKILL.md` | 仅原始表行 | 需自行封装只读存储与 MCP 服务 | 需自建服务端接收并存储历史消息 |
| **主动发送消息 / 自动回复** | 不支持（架构层严格只读） | 不支持 | 支持 | 支持 |

---

## 合规与隐私安全声明

- **合法授权用途**：本工具严格仅用于**用户本人 macOS 设备上的个人本地群聊数据备份与经授权的离线研究**。使用本工具处理群聊数据时，请遵守所在地法律法规及群聊参与方的隐私约定。
- **100% 离线只读快照**：通过 `sqlite3_backup`（`sqlite3.Connection.backup`）与 POSIX `flock` 在独立目录（`~/Library/Application Support/WhatsApp-LocalMind/snapshot`）构建合并 `-wal` 日志的单文件只读快照，并以 `?mode=ro` 打开。**零网络请求、零进程注入、绝不写回原库、绝不发送消息**。
- **物理级 `@g.us` 隔离**：所有 SQL 查询（`src/wa_localmind/db.py`）与附件导出（`src/wa_localmind/media.py`）强制校验 `ZCONTACTJID LIKE '%@g.us'`，任何针对 `@s.whatsapp.net` / `@lid` 一对一私聊的访问都会立即被拦截并返回 `EXIT_POLICY_DENIED`（退出码 `3`）。

---

## 六大核心架构支柱

1. **SQLite Online Backup 原子快照与并发锁（100% 离线只读）**
   - 采用 SQLite Online Backup API（`sqlite3_backup`）与 POSIX `flock` 文件锁，在独立目录（`~/Library/Application Support/WhatsApp-LocalMind/snapshot`）生成合并 `-wal` 日志的单文件只读快照，并以 `?mode=ro` URI 模式打开，绝不触碰或锁死运行中的 WhatsApp 原库，**零封号风险、零外部网络请求**。
2. **`@g.us` 物理级私聊拦截与黑白名单隔离**
   - 在底层 SQL 查询（`src/wa_localmind/db.py`）与附件导出层（`src/wa_localmind/media.py`）双重强制校验 `ZCONTACTJID LIKE '%@g.us'`，**100% 物理拦截一对一私聊会话（`@s.whatsapp.net` / `@lid` 私聊）与状态广播**，支持黑名单（默认）与白名单双模切换。
3. **四级实名还原与 `@lid` 跨表匿名 ID 桥接**
   - 自动联合查询 `LID.sqlite`（`ZWAZACCOUNT`）、`ZWACHATSESSION`（一对一会话通讯录备注）、`ContactsV2.sqlite`、`ZWAGROUPMEMBER`、`ZWAPROFILEPUSHNAME` 与 `ZWAMESSAGE.ZPUSHNAME`，按 **通讯录备注 > 群内昵称 > PushName > 手机号后 4 位（`用户(xxxx)`）** 四级优先级还原真实身份，并自动识别本人发言（`ZISFROMME = 1` -> `我(姓名)`）。
4. **零依赖 Protobuf Wire 引用链解析与白名单 `@提及` 还原**
   - 内置纯 Python 零依赖 Protobuf Wire 解析器（`src/wa_localmind/protobuf_parser.py`）解码 `ZWAMEDIAITEM.ZMETADATA` 字节流，精准还原 **150 字父消息引用链**（`ZSTANZAID`）与群成员字典白名单 `@提及`（不误伤邮箱与订单号），自动剔除已撤回消息（`ZMESSAGETYPE = 14`）及系统/协议通知（`6, 10, 12, 14, 46, 66`）。
5. **全局单调增量游标（`--after-id`）与上下文缓冲窗**
   - 基于 `ZWAMESSAGE.Z_PK` 提供全局单调递增游标 `--after-id`，每次增量拉取默认附带前 10 条历史上下文缓冲窗（`is_context_buffer: true`）；当检测到客户端重装导致游标越界时，自动降级拉取过去 24 小时记录并输出 `CURSOR_RESET_FALLBACK` 结构化预警。
6. **高信噪比噪音折叠与沙盒多模态附件按需导出**
   - 自动提取图文配文 Caption（`ZWAMEDIAITEM.ZTITLE`）、文档真实文件名（`ZAUTHORNAME`）及长语音时长（`ZMOVIEDURATION`）；Markdown 模式下自动合并折叠连续的「收到 / OK / +1 / 纯表情」短确认噪音，支持通过 `export-media` 按需导出沙盒语音（`.opus`）与办公文档（`.pdf` / `.xlsx`）。

---

## 快速开始（安装与挂载）

前置要求：**macOS** + **Python `>= 3.10`**（零第三方 pip 依赖；首次读取真实 WhatsApp 容器目录需在「系统设置 -> 隐私与安全性 -> 完全磁盘访问权限 (Full Disk Access)」中授权终端）。

```bash
git clone https://github.com/qilaidev/whatsapp-localmind.git
cd whatsapp-localmind

# 一键软链挂载到 ~/.local/bin 并同步 AI Agent SKILL.md 技能包
./bin/whatsapp-localmind install --bin-dir ~/.local/bin --skill-dir ~/.gemini/config/skills

# 运行环境与 TCC 权限自检
whatsapp-localmind doctor --format md
```

---

## MCP Stdio Server 接入与工具契约

在支持 Model Context Protocol (MCP) 的客户端（Claude Desktop、Cursor、Google Antigravity、Codex 等）中添加以下只读配置（若 `~/.local/bin` 已加入 `PATH`，可直接使用 `whatsapp-localmind`）：

```json
{
  "mcpServers": {
    "whatsapp-localmind": {
      "command": "whatsapp-localmind",
      "args": ["mcp-serve"]
    }
  }
}
```

### 暴露的 4 个只读 MCP Tools

| Tool 名称 | 必填参数 | 可选参数与默认值 | 能力说明 |
| :--- | :--- | :--- | :--- |
| `whatsapp_list_groups` | 无 | `keyword` (`string`)、`include_blocked` (`false`)、`format` (`"json"` \| `"markdown"`)、`fresh` (`false`) | 列出可访问 WhatsApp 群聊（`@g.us`）、成员数、24h 消息量及最新单调游标 `latest_msg_id` |
| `whatsapp_fetch_messages` | `chat_ids` (`string[]`，群 JID 数组或 `["ALL_ALLOWED"]`) | `after_msg_id` (`int`，基于 `Z_PK`)、`since` (`"24h"`)、`until` (`string`)、`context_buffer` (`10`)、`limit_per_chat` (`500`，上限 `3000`)、`fold_noise` (`true`)、`format` (`"markdown"` \| `"json"`)、`fresh` (`false`) | 按全局单调游标或时间窗提取清洗后的群聊记录，自动完成四级实名、`@lid` 还原、150 字引用链解析并剔除撤回消息 |
| `whatsapp_search_messages` | `query` (`string`) | `chat_ids` (`string[]`)、`since` (`string`)、`context` (`3`)、`limit` (`50`)、`format` (`"markdown"` \| `"json"`) | 跨允许群聊检索消息正文与附件标题，返回匹配消息及前后各 N 条语境上下文 |
| `whatsapp_export_media` | `msg_ids` (`int[]`) | 无 | 按 `msg_id` 安全导出群内沙盒语音（`.opus`）、图片与办公文档（`.pdf`/`.xlsx`）至 `snapshot/media` 缓存目录并返回绝对路径 |

---

## CLI 子命令速查（9 个子命令）

1. **`doctor`** — 环境、TCC 权限与数据库可读性自检：
   ```bash
   whatsapp-localmind doctor --format md
   ```
2. **`config`** — 本人身份锚点与群黑白名单配置（支持 `show` / `set-identity` / `set-mode` / `block` / `unblock` / `allow` / `disallow`）：
   ```bash
   whatsapp-localmind config set-identity --name "张工" --phone-suffix "8888"
   whatsapp-localmind config block "120363000000000002@g.us"
   whatsapp-localmind config set-mode whitelist
   whatsapp-localmind config allow "120363000000000001@g.us"
   ```
3. **`groups`**（别名 `list-groups`）— 查看可访问群聊与最新游标：
   ```bash
   whatsapp-localmind groups --format md
   whatsapp-localmind groups --keyword "供应链" --include-blocked --format json
   ```
4. **`fetch`** — 按时间窗或单调游标提取清洗后消息流（支持 `--limit`、`--fold`/`--no-fold`、`-o`、`--fresh`）：
   ```bash
   whatsapp-localmind fetch --chats ALL_ALLOWED --since 24h --format md
   whatsapp-localmind fetch --chats ALL_ALLOWED --after-id 1500 --limit 200 --format json | jq .
   ```
5. **`search`** — 跨群关键词检索与上下文窗口：
   ```bash
   whatsapp-localmind search --query "报价单" --since 30d --context 3 --format md
   ```
6. **`export-media`** — 按 `msg_id` 导出群内沙盒附件：
   ```bash
   whatsapp-localmind export-media --msg-ids 128498,128499 --format json
   ```
7. **`clean`** — 清理导出媒体缓存（`--media-only`）或销毁本地快照（`--all`）：
   ```bash
   whatsapp-localmind clean --media-only
   ```
8. **`mcp-serve`** — 启动只读 JSON-RPC 2.0 MCP Stdio Server：
   ```bash
   whatsapp-localmind mcp-serve
   ```
9. **`install`** — 软链安装 CLI 到 `~/.local/bin` 并可选安装 `SKILL.md`：
   ```bash
   ./bin/whatsapp-localmind install --bin-dir ~/.local/bin --skill-dir ~/.gemini/config/skills
   ```

---

## 环境变量与 POSIX 退出码契约

### 环境变量覆盖
- `WHATSAPP_LOCALMIND_CONTAINER_DIR`：自定义 WhatsApp Group Container 目录路径
- `WHATSAPP_LOCALMIND_SNAPSHOT_DIR`：自定义只读快照与附件导出缓存目录路径

### POSIX 退出码
| 退出码 | 常量名 | 含义 |
| :--- | :--- | :--- |
| `0` | `EXIT_SUCCESS` | 执行成功 |
| `1` | `EXIT_USAGE_ERROR` | 命令行参数或时间格式错误 |
| `2` | `EXIT_ENV_OR_PERM_ERROR` | 数据库不存在或缺少 macOS `Full Disk Access` (TCC) 权限 |
| `3` | `EXIT_POLICY_DENIED` | 隐私策略拦截（尝试访问一对一私聊或黑名单屏蔽群聊） |
| `4` | `EXIT_RESOURCE_NOT_FOUND` | 目标群聊/`msg_id` 不存在，或附件尚未在客户端下载到本地 |
| `5` | `EXIT_INTERNAL_DB_ERROR` | SQLite 内部读取或快照备份异常 |

---

## 常见问题（FAQ）

<details>
<summary><strong>1. 使用 <code>whatsapp-localmind</code> 会导致 WhatsApp 账号被封禁吗？</strong></summary>

**零封号风险。** `whatsapp-localmind` 不连接任何 WhatsApp 服务器、不登录 WhatsApp Web、不注入客户端进程，也不发送任何消息；它仅通过 macOS 本地文件系统和 SQLite Online Backup API 离线读取 `ChatStorage.sqlite` 的只读快照。

</details>

<details>
<summary><strong>2. 如何确保 AI Agent 绝对不会读取我的一对一私聊记录？</strong></summary>

系统在底层 SQL 引擎与策略导出层实施双重物理隔离：所有 SQL 查询强制注入 `ZCONTACTJID LIKE '%@g.us'` 条件，且 `config.py` 与 `media.py` 在执行前校验目标 JID 必须以 `@g.us` 结尾。任何传入 `@s.whatsapp.net` 或 `@lid` 私聊 JID 的请求都会立即被拦截并返回退出码 `3`（`EXIT_POLICY_DENIED`）。

</details>

<details>
<summary><strong>3. 运行 <code>doctor</code> 提示缺少 Full Disk Access (TCC) 权限怎么办？</strong></summary>

打开 macOS **系统设置 -> 隐私与安全性 -> 完全磁盘访问权限（Full Disk Access）**，将正在使用的终端或 MCP 宿主应用（如 Terminal、iTerm2、Ghostty、VS Code、Cursor）加入允许列表并重启即可。

</details>

<details>
<summary><strong>4. 如果客户端重装或游标 <code>--after-id</code> 越界了怎么恢复？</strong></summary>

`fetch` 会自动检测请求游标是否大于当前数据库的 `global_latest_msg_id`。一旦检测到越界，工具会自动降级为拉取过去 24 小时的群聊消息（`query_mode: "cursor_reset_fallback_24h"`），并在 `meta.warnings` 中附加 `CURSOR_RESET_FALLBACK` 预警提示上游 Agent 重置游标。

</details>

<details>
<summary><strong>5. 应该优先使用 MCP Server 还是 CLI？</strong></summary>

在 Claude Desktop、Cursor 或 Google Antigravity 等原生支持 MCP 的宿主中对话时，推荐挂载 `whatsapp-localmind mcp-serve`；编写定时汇总脚本、Shell 管道（`jq`）或 `SKILL.md` 工作流时，直接使用 `whatsapp-localmind` CLI 更灵活。

</details>

<details>
<summary><strong>6. 为什么坚持零第三方 pip 依赖？</strong></summary>

本地隐私提取工具应当极度轻量、可审计且免疫供应链风险。`whatsapp-localmind` 完全基于 Python 3.10+ 标准库实现（包含手写 Protobuf Wire 解析器与 JSON-RPC 2.0 MCP Server），无需配置复杂虚拟环境即可直接运行。

</details>

<details>
<summary><strong>7. 群聊成员显示为匿名 <code>@lid</code> ID 时如何还原真实姓名？</strong></summary>

`QueryEngine` 会自动联合读取 `LID.sqlite`（`ZWAZACCOUNT`）、`ZWACHATSESSION`、`ContactsV2.sqlite`（`ZWAADDRESSBOOKCONTACT`）、`ZWAGROUPMEMBER` 与 `ZWAPROFILEPUSHNAME`，按「通讯录备注 > 群内昵称 > PushName > 手机号后 4 位」四级优先级桥接 `@lid` 与手机号 JID，将成员还原为可识别身份。

</details>

<details>
<summary><strong>8. 在 WhatsApp 客户端保持打开时读取 <code>ChatStorage.sqlite</code> 会锁库或丢数据吗？</strong></summary>

**不会锁库，也不会丢失尚未合并的 WAL 日志。** 工具使用 `sqlite3.Connection.backup()`（SQLite Online Backup API）配合 POSIX `flock` 原子复制，自动将 `-wal` 日志合并至独立快照文件，并以 `?mode=ro` 只读模式查询，绝不阻塞运行中的 WhatsApp 客户端。

</details>

<details>
<summary><strong>9. 用完后如何清理本地快照和导出的附件文件？</strong></summary>

运行 `whatsapp-localmind clean --all` 会清理导出的媒体缓存并销毁本地 `ChatStorage_snapshot.sqlite`、`ContactsV2_snapshot.sqlite` 与 `LID_snapshot.sqlite`；若仅需清理导出文件，运行 `whatsapp-localmind clean --media-only`。

</details>

---

## 仓库目录结构与单元测试

测试套件内置内存/临时目录 CoreData 仿真库与 Protobuf 元数据夹具，无需本机登录真实 WhatsApp 即可运行：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

```text
whatsapp-localmind/
├── README.md                        # 中文文档（架构、CLI / MCP 契约与 FAQ）
├── README.en.md                     # English Documentation
├── llms.txt                         # llmstxt.org AI 检索摘要契约
├── codemeta.json                    # CodeMeta 2.0 结构化软件元数据
├── LICENSE                          # MIT 开源许可证
├── SECURITY.md                      # 离线只读与 @g.us 隐私隔离安全策略
├── CONTRIBUTING.md                  # 贡献指南与测试规范
├── CHANGELOG.md                     # 版本变更记录
├── pyproject.toml                   # Python 包清单（>=3.10，零第三方运行时依赖）
├── bin/
│   └── whatsapp-localmind           # CLI 可执行入口
├── skills/
│   └── whatsapp-localmind/          # AI Agent SKILL.md 技能包
├── src/
│   └── wa_localmind/                # 核心只读快照、CoreData 解析与 MCP Server 模块
└── tests/
    └── test_wa_localmind.py         # CoreData 快照、私聊拦截、@lid 映射与 MCP 契约测试
```

---

<details>
<summary><strong>检索意图与高频词索引（Search Intent & Query Mapping）</strong></summary>

| 用户问题 / 检索意图 | 典型检索词（中 / 英） | 对应能力与文档定位 |
| :--- | :--- | :--- |
| 让 Claude / Cursor 安全读取 macOS WhatsApp 群 | `WhatsApp MCP Server` · `AI Agent 读取 WhatsApp 群聊` · `whatsapp mcp server macos` | `mcp-serve` 与 4 个只读 Tools（[MCP 契约](#mcp-stdio-server-接入与工具契约)） |
| 离线无锁读取正在运行的 WhatsApp CoreData 库 | `ChatStorage.sqlite 只读快照` · `sqlite3_backup whatsapp wal read-only` | `sqlite3_backup` + `flock` + `?mode=ro`（[六大核心架构支柱](#六大核心架构支柱)） |
| 彻底隔离私聊，仅向大模型开放 `@g.us` 群聊 | `禁止读取私聊 WhatsApp 工具` · `read-only whatsapp group exporter` | `@g.us` 物理隔离，退出码 `3`（[合规与隐私安全声明](#合规与隐私安全声明)） |
| 解析 WhatsApp `@lid` 匿名成员与 Protobuf 引用链 | `WhatsApp @lid 实名映射` · `whatsapp protobuf zmetadata reply chain` | `LID.sqlite` 跨表桥接 + Protobuf Wire 解析（[六大核心架构支柱](#六大核心架构支柱)） |
| 解决 macOS 读取 WhatsApp 数据库报错 TCC 权限不足 | `Full Disk Access WhatsApp CLI` · `whatsapp-localmind doctor` | `doctor` 诊断与 TCC 授权指引（[常见问题（FAQ）](#常见问题faq)） |

</details>

<sub>**Keywords / 关键词**: whatsapp-localmind · macOS WhatsApp CoreData · ChatStorage.sqlite · LID.sqlite · ContactsV2.sqlite · sqlite3_backup WAL snapshot · `@g.us` group-only isolation · Protobuf `ZMETADATA` · MCP Stdio Server · zero-dependency Python CLI · local-first privacy · WhatsApp 群聊提取 · WhatsApp MCP 服务器 · 离线只读防私聊泄露</sub>

---

## Architecture & Ecosystem · qilai (`qilaidav.com`)

This open-source project is engineered and maintained by **[qilai · qilaidav](https://qilaidav.com)** — an independent systems engineering studio focused on **Deterministic Systems Engineering & High-Signal Technical Diagnostics**.

- **Related System / Pillar**: [Telegram Channel Ops & Persona Engine (OASH)](https://qilaidav.com/oash/) · [English Hub](https://qilaidav.com/en/oash/)
- **Sister Repository (`*-localmind`)**: [`wechat-localmind`](https://github.com/qilaidev/wechat-localmind)
- **Studio Website**: [https://qilaidav.com](https://qilaidav.com) ([EN](https://qilaidav.com/en/))
- **Technical Notes & Field Reports**: [https://qilaidav.com/notes/](https://qilaidav.com/notes/)
- **Direct Engineering Contact**: [Telegram @BD8888](https://t.me/BD8888) · [Public Channel @AIKB8](https://t.me/AIKB8) · `hello@qilaidav.com`
