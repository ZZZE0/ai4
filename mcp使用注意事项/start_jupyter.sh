#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# 为 jupyter-mcp-server 启停本地 JupyterLab 服务
#
#   用法：  ./start_jupyter.sh [start|stop|status] [工作目录]
#
#   示例：  ./start_jupyter.sh start                # 用默认目录启动（后台）
#           ./start_jupyter.sh start ~/notebooks    # 指定 notebook 根目录
#           ./start_jupyter.sh status
#           ./start_jupyter.sh stop
#
#   说明:
#     - 环境   : /home/demo/.venvs/mcpjup  (Python 3.12 + JupyterLab 4.6 + collaboration)
#     - 地址   : http://127.0.0.1:8889   token: mcpjup
#     - MCP 侧 : 见项目根目录 .mcp.json 中的 "jupyter" 条目
#                (CODE_SANDBOX_URL / CODE_SANDBOX_TOKEN 必须与下面一致)
#     - 日志   : /tmp/mcpjup-jupyter.log
# ---------------------------------------------------------------------------
set -euo pipefail

VENV="/home/demo/.venvs/mcpjup"
HOST="127.0.0.1"
PORT="8889"
TOKEN="mcpjup"
DEFAULT_WORKDIR="/home/demo/桌面/人工智能项目"
PIDFILE="/tmp/mcpjup-jupyter.pid"
LOGFILE="/tmp/mcpjup-jupyter.log"

ACTION="${1:-start}"
WORKDIR="${2:-$DEFAULT_WORKDIR}"

is_running() {
    [ -f "$PIDFILE" ] || return 1
    kill -0 "$(cat "$PIDFILE")" 2>/dev/null
}

case "$ACTION" in
    stop)
        if is_running; then
            pid="$(cat "$PIDFILE")"
            kill "$pid"
            for _ in $(seq 1 20); do
                kill -0 "$pid" 2>/dev/null || break
                sleep 0.5
            done
            kill -9 "$pid" 2>/dev/null || true
            rm -f "$PIDFILE"
            echo "已停止 JupyterLab (PID $pid)"
        else
            rm -f "$PIDFILE"
            echo "JupyterLab 未在运行"
        fi
        ;;

    status)
        if is_running; then
            pid="$(cat "$PIDFILE")"
            echo "运行中  PID=$pid"
            echo "地址    http://$HOST:$PORT/lab?token=$TOKEN"
            curl -sS --max-time 5 "http://$HOST:$PORT/api/status?token=$TOKEN" \
                 && echo || echo "(API 尚未就绪)"
        else
            echo "未运行"
            exit 1
        fi
        ;;

    start)
        if is_running; then
            echo "已在运行 (PID $(cat "$PIDFILE"))，地址 http://$HOST:$PORT/lab?token=$TOKEN"
            exit 0
        fi
        if [ ! -x "$VENV/bin/jupyter" ]; then
            echo "错误：找不到 $VENV/bin/jupyter（环境未创建？）" >&2
            exit 1
        fi
        mkdir -p "$WORKDIR"

        # collaboration(ydoc) 是新版 jupyter-mcp-server 的硬依赖，先确认可用
        "$VENV/bin/python" -c "import jupyter_server_ydoc" 2>/dev/null || {
            echo "错误：jupyter_server_ydoc 缺失，请执行：" >&2
            echo "  $VENV/bin/pip install jupyter-collaboration" >&2
            exit 1
        }

        echo "启动 JupyterLab ..."
        echo "  工作目录 : $WORKDIR"
        echo "  日志     : $LOGFILE"

        nohup "$VENV/bin/jupyter" lab \
            --no-browser \
            --ip="$HOST" \
            --port="$PORT" \
            --ServerApp.token="$TOKEN" \
            --ServerApp.password="" \
            --ServerApp.root_dir="$WORKDIR" \
            --ServerApp.allow_origin="*" \
            --ServerApp.disable_check_xsrf=True \
            --MappingKernelManager.default_kernel_name=mcpjup \
            --KernelSpecManager.ensure_native_kernel=False \
            >>"$LOGFILE" 2>&1 &
        echo $! >"$PIDFILE"

        for _ in $(seq 1 60); do
            if curl -sS --max-time 3 "http://$HOST:$PORT/api/status?token=$TOKEN" >/dev/null 2>&1; then
                echo "就绪 PID=$(cat "$PIDFILE")"
                echo "浏览器打开 : http://$HOST:$PORT/lab?token=$TOKEN"
                exit 0
            fi
            sleep 1
        done

        echo "启动超时，请检查 $LOGFILE" >&2
        tail -20 "$LOGFILE" >&2 || true
        exit 1
        ;;

    *)
        echo "用法: $0 [start|stop|status] [工作目录]" >&2
        exit 2
        ;;
esac
