# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp<2", "anyio"]
# ///
"""docx-mcp-server 工具过滤代理

上游 docx-mcp-server 会无条件注册约 220 个工具，且服务端不提供任何开关
（server.py 中不存在 os.environ 读取，也没有 tools/list 过滤逻辑）。
本代理夹在 MCP 客户端与上游之间，只放行 ALLOW 中列出的工具，
其余在 tools/list 阶段就被隐藏，从而大幅压缩上下文开销。

由 MCP 客户端自动拉起，通常无需手动运行：
    uv run --script docx_tool_filter.py

环境变量（均可选）：
    DOCX_MCP_ALLOW    逗号分隔的白名单，覆盖内置 ALLOW。
                      设为 "all" 表示关闭过滤、全部透传。
    DOCX_MCP_DENY     逗号分隔的额外禁用项，在白名单基础上继续削减。
    DOCX_MCP_VERBOSE  设为 1 时输出放行/拦截明细到 stderr。
"""

from __future__ import annotations

import os
import sys
import traceback

import anyio
import mcp.types as types
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server import Server
from mcp.server.stdio import stdio_server

# ---------------------------------------------------------------- 上游服务器
UPSTREAM_COMMAND = "uvx"
UPSTREAM_ARGS = ["--with", "mcp<2", "docx-mcp-server"]

# ---------------------------------------------------------------- 工具白名单
# 面向「中文文档的阅读 + 编辑 + 修订批注」场景挑选。
# 需要某个被裁掉的工具时，把它的名字补进这里即可（改完重载 MCP 生效）。
ALLOW: tuple[str, ...] = (
    # --- 读取与查询 ---
    "open_document",
    "close_document",
    "get_document_info",
    "get_body_text",
    "get_paragraph",
    "get_paragraph_format",
    "get_headings",
    "get_document_outline",
    "search_text",
    "get_tables",
    "get_table",
    "get_cell_text",
    "get_images",
    "get_statistics",
    "get_word_count",
    "get_reading_time",
    # --- 导出 ---
    "export_markdown",
    "table_to_csv",
    # --- 创建与保存 ---
    "create_document",
    "save_document",
    "copy_document",
    # --- 文本编辑 ---
    "insert_text",
    "replace_text",
    "delete_text",
    "update_paragraph",
    "set_formatting",
    "apply_style_to_range",
    "set_run_font",
    # --- 段落格式 ---
    "set_paragraph_indentation",
    "set_line_spacing",
    "set_paragraph_border",
    "set_paragraph_shading",
    # --- 表格 ---
    "add_table",
    "add_table_row",
    "add_column_to_table",
    "delete_table_row",
    "modify_cell",
    "merge_cells",
    "set_column_widths",
    # --- 修订与批注 ---
    "set_track_changes",
    "get_tracked_changes",
    "accept_changes",
    "reject_changes",
    "add_comment",
    "get_comments",
    # --- 样式 ---
    "get_styles",
    "create_style",
)


# ---------------------------------------------------------------- 基础设施
def _verbose() -> bool:
    return os.environ.get("DOCX_MCP_VERBOSE", "") not in ("", "0", "false", "False")


def _log(msg: str) -> None:
    # 必须写 stderr —— stdout 要留给 JSON-RPC
    print(f"[docx-filter] {msg}", file=sys.stderr, flush=True)


def _env_list(name: str) -> list[str] | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    return [p.strip() for p in raw.split(",") if p.strip()]


def resolve_allow() -> set[str] | None:
    """计算允许暴露的工具集合；返回 None 表示关闭过滤、全部透传。"""
    override = _env_list("DOCX_MCP_ALLOW")
    if override is not None:
        if not override or [x.lower() for x in override] == ["all"]:
            return None
        allowed = set(override)
    else:
        allowed = set(ALLOW)

    allowed -= set(_env_list("DOCX_MCP_DENY") or [])
    return allowed


async def _collect_tools(session: ClientSession) -> list[types.Tool]:
    """拉取上游全部工具，处理分页。"""
    tools: list[types.Tool] = []
    cursor: str | None = None
    while True:
        page = await session.list_tools(cursor=cursor)
        tools.extend(page.tools)
        cursor = page.nextCursor
        if not cursor:
            return tools


async def _serve() -> None:
    allowed = resolve_allow()
    params = StdioServerParameters(command=UPSTREAM_COMMAND, args=UPSTREAM_ARGS)

    async with stdio_client(params) as (up_read, up_write):
        async with ClientSession(up_read, up_write) as upstream:
            await upstream.initialize()

            all_tools = await _collect_tools(upstream)
            known = {t.name for t in all_tools}

            if allowed is None:
                exposed = list(all_tools)
            else:
                exposed = [t for t in all_tools if t.name in allowed]
                unknown = sorted(allowed - known)
                if unknown:
                    _log(f"警告: 白名单中的这些工具在上游不存在 -> {unknown}")

            # 去掉 outputSchema：代理只转发上游的 content，不重放结构化输出。
            # 若保留 outputSchema，SDK 会以「声明了结构化输出却未返回」为由拒绝调用。
            exposed = [t.model_copy(update={"outputSchema": None}) for t in exposed]

            _log(
                f"上游 {len(all_tools)} 个工具 -> 放行 {len(exposed)} 个，"
                f"隐藏 {len(all_tools) - len(exposed)} 个"
            )
            if _verbose():
                _log("放行: " + ", ".join(sorted(t.name for t in exposed)))

            index = {t.name: t for t in exposed}
            server = Server("docx-mcp-filtered")

            @server.list_tools()
            async def _list_tools() -> list[types.Tool]:
                return list(index.values())

            @server.call_tool()
            async def _call_tool(name: str, arguments: dict | None):
                if name not in index:
                    return [
                        types.TextContent(
                            type="text",
                            text=(
                                f"工具 {name!r} 已被 docx-mcp 过滤代理禁用。"
                                "如需启用，请把工具名加入 docx_tool_filter.py 的 ALLOW 列表。"
                            ),
                        )
                    ]
                try:
                    result = await upstream.call_tool(name, arguments or {})
                except Exception as exc:  # noqa: BLE001
                    _log(f"调用 {name} 失败: {exc!r}")
                    return [
                        types.TextContent(type="text", text=f"上游调用失败: {exc}")
                    ]

                if result.content:
                    return result.content
                structured = getattr(result, "structuredContent", None)
                if structured is not None:
                    return structured
                return [types.TextContent(type="text", text="(上游返回了空结果)")]

            async with stdio_server() as (cl_read, cl_write):
                await server.run(
                    cl_read, cl_write, server.create_initialization_options()
                )


def main() -> None:
    try:
        anyio.run(_serve)
    except Exception:  # noqa: BLE001
        traceback.print_exc(file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
