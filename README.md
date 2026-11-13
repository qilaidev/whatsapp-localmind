# WhatsApp LocalMind (`whatsapp-localmind`)

**零依赖 macOS WhatsApp 本地群聊只读提取、结构化清洗、CLI 与 MCP Server 能力层（面向 AI Agent）**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](https://www.python.org/)
[![Zero Dependencies](https://img.shields.io/badge/Dependencies-Zero%20Runtime%20Deps-brightgreen.svg)](./pyproject.toml)
[![Platform: macOS](https://img.shields.io/badge/Platform-macOS-black.svg)](https://www.apple.com/macos/)
[![MCP Server](https://img.shields.io/badge/MCP-Stdio%20Read--Only-6E56CF.svg)](#mcp-stdio-server-接入与工具契约)
[![Agent CLI](https://img.shields.io/badge/Agent-CLI%20%26%20SKILL.md-orange.svg)](./skills/whatsapp-localmind/SKILL.md)

**简体中文** | [English](./README.en.md) | [llms.txt](./llms.txt) | [Agent Skill](./skills/whatsapp-localmind/SKILL.md) | [Security Policy](./SECURITY.md) | [Contributing](./CONTRIBUTING.md) | [Changelog](./CHANGELOG.md) | [MIT License](./LICENSE)

**WhatsApp LocalMind (`whatsapp-localmind`)** 是一个纯 Python 标准库构建的 **macOS WhatsApp 本地群聊只读数据提取与结构化清洗能力层**，同时提供 POSIX 规范的 CLI 工具与零依赖 JSON-RPC 2.0 MCP Stdio Server。它通过 `sqlite3_backup` 原子快照与 `?mode=ro` 只读协议离线读取本地 CoreData 数据库（`ChatStorage.sqlite`、`LID.sqlite`、`ContactsV2.sqlite`），在 SQL 与媒体层物理拦截一对一私聊，将群聊消息转化为高信噪比的结构化 JSON 或 Markdown 对话流供 Claude Desktop、Cursor、Antigravity 等 AI Agent 安全消费。

> **`*-localmind` 本地即时通讯只读提取能力层家族**
>
> 本仓库与姊妹仓 [`wechat-localmind`](https://github.com/qilaidev/wechat-localmind)（macOS & Windows 微信本地群聊提取能力层）同属 **`*-localmind` 本地聊天提取家族**，两仓严格遵循统一的五项架构哲学：
> **100% 离线只读快照 + 物理拦截一对一私聊 + 四级实名还原 + 单调增量游标 + CLI & MCP 双协议交付**。

---

## 定位边界：它是什么 / 不是什么

| 它是什么（What it is） | 它不是什么（What it is not） |
| :--- | :--- |
| ✅ **100% 离线只读本地数据提取层**：读取 macOS 本地 WhatsApp CoreData SQLite 容器 | ❌ **不是协议机器人或自动化外挂**：不登录 WhatsApp Web、不模拟点击、不连接远程服务器 |
| ✅ **物理级 `@g.us` 群聊隔离引擎**：在 SQL 与媒体层强制拦截一对一私聊与状态广播 | ❌ **不是消息发送工具**：绝不包含发消息、改已读回执或写回原数据库的代码 |
| ✅ **AI Agent 原生交付底座**：内置 9 个 CLI 子命令、4 个只读 MCP 工具与 `SKILL.md` | ❌ **不依赖任何第三方 pip 包**：无需安装 `protobuf`、`mcp`、`sqlite-vec` 等外部库 |

---

## 六大核心架构支柱

1. **SQLite Online Backup 原子快照与并发锁（100% 离线只读）**
   - 采用 SQLite Online Backup API（`sqlite3_backup`）与 POSIX `flock` 文件锁，在独立目录（`~/Library/Application Support/WhatsApp-LocalMind/snapshot`）生成合并 `-wal` 日志的单文件只读快照，并以 `?mode=ro` URI 模式打开，绝不触碰或锁死运行中的 WhatsApp 原库，**零封号风险、零外部网络请求**。
2. **`@g.us` 物理级私聊拦截与黑白名单隔离**
   - 在底层 SQL 查询（`src/wa_localmind/db.py`）与附件导出层（`src/wa_localmind/media.py`）双重强制校验 `ZCONTACTJID LIKE '%@g.us'`，**100% 物理拦截一对一私聊会话（`@s.whatsapp.net` / `@lid` 私聊）与状态广播**，支持黑名单（默认）与白名单双模切换。
3. **四级实名还原与 `@lid` 跨表匿名 ID 桥接**
   - 自动联合查询 `LID.sqlite`（`ZWAZACCOUNT`）、`ZWACHATSESSION`（一对一会话通讯录备注）、`ContactsV2.sqlite`、`ZWAGROUPMEMBER`、`ZWAPROFILEPUSHNAME` 与 `ZWAMESSAGE.ZPUSHNAME`，按 **通讯录备注 > 群内昵称 > PushName > 手机号后 4 位（`用户(xxxx)`）** 四级优先级还原真实身份，并自动识别本人发言（`ZISFROMME = 1` -> `我(姓名)`）。
4. **零依赖 Protobuf Wire 引用链解析与白名单 `@提及` 还原**
   - 内置纯 Python 零依赖 Protobuf Wire 解析器（`src/wa_localmind/protobuf_parser.py`）解码 `ZWAMEDIAITEM.ZMETADATA` 字节流，精准还原 **150 字父消息引用链**（`ZSTANZAID`）与群成员字典白名单 `@提及`（不误伤邮箱与订单号），自动剔除已撤回消息（`ZMESSAGETYPE = 14`）及系统安全通知。
5. **全局单调增量游标（`--after-id`）与上下文缓冲窗**
   - 基于 `ZWAMESSAGE.Z_PK` 提供全局单调递增游标 `--after-id`，每次增量拉取默认附带前 10 条历史上下文缓冲窗（`is_context_buffer: true`）；当检测到客户端重装导致游标越界时，自动降级拉取过去 24 小时记录并输出结构化预警。
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

在支持 Model Context Protocol (MCP) 的客户端（Claude Desktop、Cursor、Google Antigravity、Codex 等）中添加以下只读配置（将 `<HOME>` 替换为你的用户主目录，或直接使用 `whatsapp-localmind` 如果 `~/.local/bin` 已在 `PATH` 中）：

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
2. **`config`** — 本人身份锚点与群黑白名单配置：
   ```bash
   whatsapp-localmind config set-identity --name "张工" --phone-suffix "8888"
   whatsapp-localmind config block "120363000000000002@g.us"
   whatsapp-localmind config set-mode --mode whitelist
   whatsapp-localmind config allow "120363000000000001@g.us"
   ```
3. **`groups`**（别名 `list-groups`）— 查看可访问群聊与最新游标：
   ```bash
   whatsapp-localmind groups --format md
   whatsapp-localmind groups --keyword "供应链" --include-blocked --format json
   ```
4. **`fetch`** — 按时间窗或单调游标提取清洗后消息流：
   ```bash
   whatsapp-localmind fetch --chats ALL_ALLOWED --since 24h --format md
   whatsapp-localmind fetch --chats ALL_ALLOWED --after-id 1500 --format json | jq .
   ```
5. **`search`** — 跨群关键词检索与上下文窗口：
   ```bash
   whatsapp-localmind search --query "报价单" --since 30d --context 3 --format md
   ```
6. **`export-media`** — 按 `msg_id` 导出群内沙盒附件：
   ```bash
   whatsapp-localmind export-media --msg-ids 128498,128499 --format json
   ```
7. **`clean`** — 清理导出媒体缓存或销毁本地快照：
   ```bash
   whatsapp-localmind clean --media-only
   ```
8. **`mcp-serve`** — 启动 JSON-RPC 2.0 MCP Stdio Server。
9. **`install`** — 软链安装 CLI 到 `~/.local/bin` 并可选安装 `SKILL.md`。

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

### 1. 使用 `whatsapp-localmind` 会导致 WhatsApp 账号被封禁吗？
不会。`whatsapp-localmind` **零封号风险**。它不连接任何 WhatsApp 服务器、不登录 WhatsApp Web、不注入客户端进程，也不发送任何消息；它仅通过 macOS 本地文件系统和 SQLite Online Backup API 离线读取 `ChatStorage.sqlite` 的只读快照。

### 2. 如何确保 AI Agent 绝对不会读取我的一对一私聊记录？
系统在底层引擎与策略层实施双重物理隔离：所有 SQL 查询强制注入 `ZCONTACTJID LIKE '%@g.us'` 条件，且 `config.py` 与 `media.py` 会在执行前校验目标 JID 必须以 `@g.us` 结尾。任何传入 `@s.whatsapp.net` 或 `@lid` 私聊 JID 的请求都会立即被拦截并返回退出码 `3`（`POLICY_DENIED`）。

### 3. 运行 `doctor` 提示缺少 Full Disk Access (TCC) 权限怎么办？
打开 macOS **系统设置 -> 隐私与安全性 -> 完全磁盘访问权限（Full Disk Access）**，将你正在使用的终端应用（如 Terminal、iTerm2、Ghostty、VS Code 或 Cursor）加入允许列表并重启终端即可。

### 4. 如果客户端重装或游标 `--after-id` 越界了怎么恢复？
`fetch` 会自动检测请求游标是否大于当前数据库的 `global_latest_msg_id`。一旦检测到游标越界，工具会自动降级为拉取过去 24 小时的群聊消息，并在返回的 `meta.warnings` 中附加越界预警，方便上层 Agent 重置游标。

### 5. 应该优先使用 MCP Server 还是 CLI？
如果你在 Claude Desktop、Cursor 或 Antigravity 等原生支持 MCP 的宿主中与 AI 对话，推荐直接挂载 `whatsapp-localmind mcp-serve`；如果你在编写定时汇总脚本、Shell 管道（`jq`）或基于 `SKILL.md` 的 Agent 工作流，直接使用 `whatsapp-localmind` CLI 会更灵活。

### 6. 为什么坚持零第三方 pip 依赖？
本地隐私数据提取工具应当极度轻量、可审计且长期稳定。完全基于 Python 3.10+ 标准库实现（包括手写的 Protobuf Wire 解析器与 JSON-RPC 2.0 MCP Server），意味着没有任何供应链投毒风险，也无需维护复杂的虚拟环境即可直接运行。

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
