# MCP 服务器汇总（Linux）

> 2026-10-02。统一用 `uvx`（`/home/demo/.local/bin/`），不再使用 conda。

| 服务器 | 运行命令 | 版本要求 |
|---|---|---|
| pdf-mcp | `uvx pdf-mcp` | — |
| docx-mcp-server | `uvx --with "mcp<2" docx-mcp-server` | **必须 `mcp<2`** |
| paper-search-mcp | `uvx --with "mcp<2" paper-search-mcp` | **必须 `mcp<2`** |
| excel-mcp-server | `uvx excel-mcp-server stdio` | — |
| jupyter-mcp-server | `uvx jupyter-mcp-server start` | 需外部 JupyterLab + collaboration |

**为什么要钉 `mcp<2`**：docx 与 paper-search 仍用 mcp v1 的 `FastMCP`，2.x 已改名为 `MCPServer`，
不钉会抛 `ModuleNotFoundError: No module named 'mcp.server.fastmcp'`。

原 conda 环境已弃用：`mcpjup` → `/home/demo/.venvs/mcpjup`；`excelmcp` → 直接用 `uvx`。
