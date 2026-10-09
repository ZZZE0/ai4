# CodeBuddy 配置 MCP 服务器经验总结

> 初版 2026-09-24（以 `jztan/pdf-mcp` 为例），2026-09-28 补充「工具数量治理」。
> 场景：在 CodeBuddy IDE 中接入 MCP 服务器，并治理其工具规模，仅对当前项目生效。
> 结论：**配置层面 —— 配置文件路径与顶层键名必须精确匹配客户端；规模层面 —— 工具数量必须主动收敛。**

---

## 一、最终可用的配置

### 1.1 位置与安装

配置写在**工作区根目录**的 `.mcp.json`，顶层键为 `mcpServers`。

```bash
# uv 安装（一次性，Linux）
python3 -m pip install --user -U uv     # 落地在 ~/.local/bin/uv（与 uvx 同目录）
```

### 1.2 pdf-mcp：直连

```json
{
	"mcpServers": {
		"pdf-mcp": {
			"type": "stdio",
			"command": "/home/demo/.local/bin/uvx",
			"args": ["pdf-mcp"],
			"disabled": false,
			"timeout": 180000
		}
	}
}
```

### 1.3 docx-mcp-server：经 stdio 过滤代理

该服务器有 219 个工具，且服务端与客户端均不支持裁剪，故串一层代理：

```json
"docx-mcp-server": {
  "type": "stdio",
  "command": "/home/demo/.local/bin/uv",
  "args": [
    "run",
    "--script",
    "/home/demo/桌面/人工智能项目/mcp_filters/docx_tool_filter.py"
  ],
  "env": {
    "PATH": "/home/demo/.local/bin:/usr/local/bin:/usr/bin:/bin"
  },
  "disabled": false,
  "timeout": 180000
}
```

与 pdf-mcp 的两点差异：用 `uv` 而非 `uvx`（PEP 723 脚本需 `uv run --script`）；参数多一层脚本路径。
另外多了一个 `env.PATH`：代理内部要用 `uvx` 拉起上游，而 GUI 客户端的 PATH 快照未必包含 `~/.local/bin`。

> 方案原理见第六章，完整操作见 `../mcp_filters/使用文档.md`。

---

## 二、核心教训

### 教训 1：各客户端的「配置文件路径 + 顶层键名」互不通用

| 客户端 | 配置文件 | 顶层键 |
|---|---|---|
| **CodeBuddy（项目级）** | `<工作区>/.mcp.json` | **`mcpServers`** |
| CodeBuddy（用户级，VS Code 原生通道） | `%APPDATA%\Code\User\mcp.json`（Linux 为 `~/.config/Code/User/mcp.json`） | `servers` |
| VS Code | `.vscode/mcp.json` | `servers` |
| Claude Code | `<项目根>/.mcp.json` | `mcpServers` |
| Claude Desktop | `claude_desktop_config.json` | `mcpServers` |
| Codex CLI | `~/.codex/config.toml` | `[mcp_servers.xxx]` |
| Kiro | `.kiro/settings/mcp.json` | `mcpServers` |

踩坑过程：先按 VS Code 风格写成 `servers`、放进 `.codebuddy/mcp.json`，路径和键名两处都错。**不要靠记忆或类比，去看客户端的实际实现**（方法见教训 6）。

---

### 教训 2：报错 `Cannot convert undefined or null to object` 基本等于「键名写错了」

该错误的字面含义是「对 undefined/null 取键」。顶层键写成 `servers` 时，客户端执行 `Object.entries(config.mcpServers)`，而 `mcpServers` 为 undefined，随即抛错。

**结论**：看到它，第一反应应是「**客户端期望的字段名与我的不一致**」，而不是「文件坏了」。

---

### 教训 3：项目级 MCP 服务器有「审批门」，默认不会自动连接

出于安全考虑，来自项目配置的服务器受以下约束：

- 来源为 `project` 时初始状态是 `pendingApproval`，**未批准不会建立连接**，工具列表也加载不出来
- 审批结果基于配置指纹（`sha256(项目路径 + 服务器名 + type/command/args/cwd/env/url/headers)`）计算
- **工作区未受信任**时状态直接是 `workspace-untrusted`

改完配置后除了重启，还要在 MCP 面板**手动点「批准」**；反复失败则检查工作区信任状态（`Ctrl+Shift+P` → `Workspaces: Manage Workspace Trust`）。

> 这是设计特性而非 bug：防止「克隆别人的仓库，一打开就自动执行里面藏的恶意命令」。

---

### 教训 4：GUI 应用有独立的 PATH 快照，改完环境变量必须重启

`uv` 安装后会修改**用户 PATH**（Windows 由 winget 写入；Linux 下落在 `~/.local/bin`，未必在 GUI 的 PATH 里），但已启动的 IDE 用的是**启动那一刻**的环境快照，新装的命令行工具找不到。

**正确做法（二选一）**：配置里直接写**可执行文件的绝对路径**（本次采用，最稳）；或完全重启 IDE（不是关窗口）后再用简写命令。

**注意坑**：Windows 绝对路径含反斜杠，JSON 里必须写成**双反斜杠** `\\`；Linux 用正斜杠，路径含中文或空格也无需转义，直接写即可。

---

### 教训 5：首次启动会下载依赖，`timeout` 必须放大

pdf-mcp 首次启动要下载约 65 MB Python 依赖 + 约 130 MB 嵌入模型，耗时可能数分钟；客户端默认超时常见 60 秒，会直接判定失败。

做法：配置里显式写 `"timeout": 180000`，并**先在终端预热一次**把下载走完：

```bash
uvx pdf-mcp --help        # Linux 下需确保 ~/.local/bin 在 PATH 中
```

---

### 教训 6：排错要读源码/日志，不要靠猜

本次能定位根因，靠的是直接读客户端扩展的源码。注意压缩后的 `index.js` 单行极长，**要截取命中点附近的窗口，不要直接 grep 整行**：

```bash
# 1. 找到扩展目录
ls -d ~/.vscode/extensions/*coding-copilot*

# 2. 截取报错字符串附近的片段（-o 只输出命中窗口，避免整行刷屏）
grep -o '.\{700\}MCP setting.\{700\}' ~/.vscode/extensions/*coding-copilot*/out/extension/index.js | head -1
```

从中读出两条决定性事实：

```js
const rn = path.join(workspacePath, ".mcp.json")                    // 事实 A：配置路径 = 工作区根/.mcp.json
for (const [name, cfg] of Object.entries(dn.mcpServers)) { ... }    // 事实 B：直接取 mcpServers，无兜底
```

`Object.entries(dn.mcpServers)` 就是报错的直接来源，看到它就知道该改键名。

> 排错优先级：**官方文档 → 客户端源码 → 日志文件 → 社区文章**。只看社区文章会一直按 `servers` 写，永远修不好。

---

### 教训 7：`uvx` 是全局工具，不绑定任何项目

| 用法 | 环境位置 | 作用范围 |
|---|---|---|
| `uvx pdf-mcp` | 全局共享缓存 | 所有项目、所有目录通用 |
| `uv tool install pdf-mcp` | 全局工具目录 | 所有项目、所有目录通用 |
| `uv init` + `pyproject.toml` | 项目目录下的 `.venv` | 仅当前项目 |

`uvx` 的隔离环境放在**全局缓存**而非项目文件夹，所以换项目、换目录都复用同一份缓存，无需重装。真正的「项目绑定」只体现在 **MCP 配置文件放在哪**。

迁移到新机器只需两步：装 uv → 复制同一段 JSON。

---

### 教训 8：工具数量是必须治理的配置项

`docx-mcp-server` 注册了 **219 个工具**，它们会在**每一轮请求**中全部进入上下文，粗估占用 **2~3 万 token**。代价分两层：

- **直接成本**：token 消耗与费用
- **间接成本（更隐蔽）**：候选过多会稀释模型注意力，导致挑错工具、或该调用时反而不调用

**判断标准**：某个服务器里超过一半的工具是你三个月内没用过的，就该收敛。

---

### 教训 9：禁用工具分三层尝试，从便宜到贵

| 层次 | 手段 | 成本 | 本例结果 |
|---|---|---|---|
| 第 1 层 | 服务端自带开关（环境变量 / 启动参数 / 配置文件） | 最低 | ❌ 完全没有 |
| 第 2 层 | 客户端工具级过滤字段（如 `disabledTools`） | 低 | ❌ 被静默忽略 |
| 第 3 层 | 自建 stdio 过滤代理 | 中 | ✅ 可行且通用 |

**第 2 层必须实测，不能看文档**：往配置里写 `disabledTools` 并放几个明确的探针工具（本例选了 `scrub_pii`、`xpath_query`、`insert_pie_chart`），重载后看它们是否从工具列表消失。本例中依然存在，说明客户端只是忽略未知字段。

> ⚠️ 「不报错也不生效」是最阴险的失败模式 —— 只看日志会以为配置成功，实际是空转。

---

### 教训 10：服务端有没有裁剪能力，读源码 30 秒就能确认

直接看服务端入口文件（GitHub 仓库或本地 `site-packages` 均可），搜三个特征：

```bash
grep -nE "import os|os\.environ|os\.getenv" server.py   # ① 是否读环境变量
grep -nE "argparse|sys\.argv"               server.py   # ② 是否解析启动参数
grep -nE "list_tools"                       server.py   # ③ 是否过滤 tools/list
```

本例 `docx_mcp/server.py` 三项全空，且所有工具都是 `@mcp.tool()` 裸装饰器**无条件注册** —— 据此可立即判定「服务端裁剪不可行」，无需再试。

---

## 三、排查清单（Checklist）

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 报 `Cannot convert undefined or null to object` | 顶层键名写错 | 改为 `mcpServers` |
| MCP 面板里根本不出现该服务器 | 配置文件路径不对 | 项目级放 `<工作区根>/.mcp.json` |
| 一直显示 `pendingApproval` | 项目级审批未通过 | 在 MCP 面板点「批准」 |
| 显示 `workspace-untrusted` | 工作区未受信任 | 信任该工作区 |
| 报 command not found / 连不上 | IDE 的 PATH 是旧快照 | 用绝对路径，或完全重启 IDE |
| 首次连接超时失败 | 首次下载依赖耗时 | 放大 `timeout`；先终端预热 |
| 改了配置没反应 | 没重载 | `Ctrl+Shift+P` → `Reload Window` |
| 重载后工具数量没变 | 客户端缓存了工具列表 | **完全退出客户端再启动**，不只是 Reload |
| `disabledTools` 写了但没生效 | 客户端不支持该字段（静默忽略） | 改用过滤代理（见第六章） |
| 单个服务器的工具数超过 100 | 未做规模治理 | 加过滤代理收敛白名单 |

---

## 四、本次环境存档

| 项目 | 值 |
|---|---|
| 系统 | Ubuntu 20.04（内核 5.15） |
| Python（系统） | 3.8.10 —— 过老，不用于 MCP 环境 |
| Python（uv 托管） | 3.12.15，位于 `~/.local/share/uv/python/` |
| uv 版本 | 0.12.22 |
| uv 安装方式 | `python3 -m pip install --user -U uv` |
| uv / uvx 路径 | `/home/demo/.local/bin/uv`、`/home/demo/.local/bin/uvx` |
| jupyter 环境 | `/home/demo/.venvs/mcpjup`（JupyterLab 4.6.4 + collaboration） |
| 用户数据目录名（常量） | `.codebuddy`（用户级与工作区级同名） |

### 4.1 缓存位置与清理

| 缓存 | 位置 | 清理命令 |
|---|---|---|
| uv 缓存 | `~/.local/share/uv/cache` | `uv cache prune` / `uv cache clean` |
| pdf-mcp 缓存 | `~/.cache/pdf-mcp` | MCP 工具 `pdf_cache_clear` |

> uv 官方警告：**不要手动删缓存目录里的文件**，只用 `uv cache prune` / `uv cache clean`。

### 4.2 迁移记录：Windows → Linux（2026-10-02）

从 Windows 的「卫星智能体项目」整份拷贝过来的 `.mcp.json` 在 Linux 上完全加载不了，
根因是**每个 `command` 都是 Windows 专用**：

| 原配置 | 问题 | 迁移后 |
|---|---|---|
| `C:\...\uvx.exe` | 绝对路径不存在 | `/home/demo/.local/bin/uvx` |
| `C:\...\uv.exe` | 同上 | `/home/demo/.local/bin/uv` |
| `cmd /c ...exe` | Linux 没有 `cmd` | 改为 `uvx <包名>` |
| `D:\nodejs\npx.cmd` | 无该盘符、也无 node | 该服务器（firecrawl）直接移除 |
| conda env 中的 `jupyter-mcp-server.exe` | Linux 上没有 conda | `uvx jupyter-mcp-server start` |

迁移中额外发现的兼容性问题：

- **`paper-search-mcp` 必须钉 `mcp<2`**（与 docx 同因，否则 `ModuleNotFoundError`）；`excel-mcp-server` 实测无需钉。
- **jupyter 环境变量改名**：`JUPYTER_URL`/`JUPYTER_TOKEN` → `CODE_SANDBOX_URL`/`CODE_SANDBOX_TOKEN`，启动变为 `start` 子命令（见 `jupyter.md`）。
- **先预热再连接**：终端逐个跑 `uvx <包> --help`，避免客户端按默认超时判定失败。

---

## 五、可复用的通用结论

1. **配置 MCP 前先确认三件事**：配置文件路径、顶层键名、传输类型（stdio / http）。
2. **文档缺失时直接读客户端源码**，比反复试错快得多。
3. **GUI 里调用命令行工具一律用绝对路径**，可绕开整类环境变量问题。
4. **本地 stdio 宽松，远程 HTTP 常强制鉴权**（pdf-mcp 的 HTTP 模式必须有 `PDF_MCP_AUTH_TOKEN` 与 `[paths]` 白名单，否则拒绝启动）。
5. **改配置后必须重载/重启**，并检查审批、工作区信任之类的安全门。
6. **优先项目级配置**：能跑通的最小配置就是好配置，污染全局配置要谨慎。
7. **工具数量要主动收敛**（>50 审视，>100 裁剪）；客户端对未知字段静默忽略，是否生效必须实测。

---

## 六、工具数量治理：stdio 过滤代理

> 只沉淀**方法论**便于迁移；完整操作见 `../mcp_filters/使用文档.md`。

### 6.1 原理

当一个服务器的工具数过多、且服务端与客户端都不支持裁剪时，在两者之间插入一个薄代理：

```
客户端 ──stdio──> 过滤代理 ──stdio──> 上游 MCP 服务器
                     ↑
             只放行白名单内的工具
```

代理做两件事：**列表层**——启动时连上游取全量工具，只把白名单内的返回给客户端；**调用层**——被禁工具的调用直接拒绝、不转发（双重保险）。

### 6.2 落地要点

| 环节 | 做法 |
|---|---|
| 脚本形式 | 单文件 + **PEP 723 内联依赖**（`# /// script` 块），由 `uv run --script` 执行，**零额外安装** |
| 配置写法 | `command` 用 `uv`（Linux 下写绝对路径 `/home/demo/.local/bin/uv`），`args` 为 `["run","--script","<脚本绝对路径>"]` |
| 上游兼容 | 依赖必须钉 **`mcp<2`**：很多服务器仍用 v1 的 `FastMCP`，而 mcp 2.x 已把它改名为 `MCPServer`，不钉版本会直接崩 |
| stdout 纪律 | **日志一律走 stderr**，stdout 只留给 JSON-RPC，否则污染协议流 |
| 分页处理 | 拉取工具时要循环处理 `nextCursor`，避免上游工具多于一页时漏掉 |
| 白名单容错 | 对「上游不存在」的工具名主动报警，防止拼写错误静默失效 |
| 逃生开关 | 支持 `..._ALLOW=all` 环境变量临时关闭过滤，便于二分排查 |
| 结构化输出 | 暴露工具时**要去掉 `outputSchema`**。代理只重放上游的 `content`，若保留该字段，SDK 会以「声明了结构化输出却未返回」为由拒绝**所有**调用 |

### 6.3 验证方法（不要跳过）

**不能只看「连接成功」**，必须核对工具数量：模拟客户端发一次 `tools/list`，统计条数并抽查关键工具。

| 检查项 | 改前 | 改后 |
|---|---|---|
| 暴露工具总数 | 219 | **47** |
| `scrub_pii` / `xpath_query`（应隐藏） | 存在 | 已隐藏 |
| `get_body_text` / `save_document`（应保留） | 存在 | 保留 |

> 白名单写错时连接照样成功，只是工具悄悄少了或多了。

### 6.4 收益与代价

| 项 | 说明 |
|---|---|
| 收益 | 工具数 219 → 47（约 −79%），上下文开销同步下降 |
| 代价 | 多一层进程，冷启动约 +1~2 秒（`timeout` 设 180 秒足够） |
| 维护 | 增删工具 = 改脚本里的一个列表 + 重载客户端；换上游命令与白名单即可复用到任何 MCP 服务器 |

---

## 附：pdf-mcp 常用工具速查

| 工具 | 用途 |
|---|---|
| `pdf_info` | 页数、元数据、目录，探测扫描页 —— **建议第一步先调** |
| `pdf_search` | 关键词 + 语义混合检索，返回带页码的段落摘录 |
| `pdf_read_pages` | 精读指定页/页范围（含表格、OCR） |
| `pdf_read_all` | 小文档整份读取 |
| `pdf_render_pages` | 渲染成 PNG，供视觉模型看图表 |
| `pdf_extract_chart` | 从矢量图提取精确的 `(x, y)` 数据 |
| `pdf_corpus_warm` / `pdf_corpus_overview` / `pdf_corpus_search` | 整个文件夹的预热 / 分诊 / 跨文档检索 |
| `pdf_cache_stats` / `pdf_cache_clear` / `server_info` | 缓存与能力查询 |

典型调用顺序：`pdf_info` 规划 → `pdf_search` 定位 → 需要更多内容再用 `pdf_read_pages`。
