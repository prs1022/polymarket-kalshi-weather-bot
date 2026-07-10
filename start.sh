#!/bin/bash
#===================================
# Trading Bot 后端启动脚本
# 用法:
#   ./start.sh          # 前台运行(可看日志)
#   ./start.sh start    # 后台运行
#   ./start.sh stop     # 停止
#   ./start.sh restart  # 重启
#   ./start.sh status   # 查看状态
#   ./start.sh logs     # 查看日志
#===================================

APP_NAME="trading-bot"
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$APP_DIR/.run/$APP_NAME.pid"
LOG_DIR="$APP_DIR/.run/logs"
LOG_FILE="$LOG_DIR/app.log"
PORT="${PORT:-8000}"

# Python 路径(自动检测: conda > venv > system)
# 优先用有 uvicorn 的环境
if command -v python3 &>/dev/null && python3 -c "import uvicorn" 2>/dev/null; then
    # 当前环境已有 uvicorn (conda/system)
    PYTHON_CMD="python3"
elif [ -f "$APP_DIR/venv/bin/python" ] && "$APP_DIR/venv/bin/python" -c "import uvicorn" 2>/dev/null; then
    PYTHON_CMD="$APP_DIR/venv/bin/python"
elif [ -f "$APP_DIR/.venv/bin/python" ] && "$APP_DIR/.venv/bin/python" -c "import uvicorn" 2>/dev/null; then
    PYTHON_CMD="$APP_DIR/.venv/bin/python"
else
    PYTHON_CMD="python3"
fi

mkdir -p "$LOG_DIR"
mkdir -p "$APP_DIR/.run"

# 获取 PID
get_pid() {
    if [ -f "$PID_FILE" ]; then
        local pid
        pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            echo "$pid"
            return 0
        else
            rm -f "$PID_FILE"
        fi
    fi
    return 1
}

# 打印 Python 环境
show_python() {
    echo "Using Python: $($PYTHON_CMD --version 2>&1) at $(which $PYTHON_CMD)"
}

# 前台运行
run_foreground() {
    show_python
    echo "Starting $APP_NAME (foreground) on port $PORT..."
    echo "Press Ctrl+C to stop."
    echo "Logs: $LOG_FILE"
    echo "============================================"
    $PYTHON_CMD run.py 2>&1 | tee "$LOG_FILE"
}

# 后台运行
run_background() {
    local pid
    if pid=$(get_pid); then
        echo "$APP_NAME is already running (PID: $pid)"
        exit 1
    fi

    show_python
    echo "Starting $APP_NAME (background) on port $PORT......"

    nohup $PYTHON_CMD run.py > "$LOG_FILE" 2>&1 &
    local new_pid=$!
    echo "$new_pid" > "$PID_FILE"

    sleep 2
    if kill -0 "$new_pid" 2>/dev/null; then
        echo "  PID: $new_pid"
        echo "  Log: $LOG_FILE"
        echo "  Port: $PORT"
        echo ""
        echo "  Use './start.sh logs' to view logs"
        echo "  Use './start.sh stop' to stop"
    else
        echo "  Failed to start! Check log: $LOG_FILE"
        rm -f "$PID_FILE"
        exit 1
    fi
}

# 停止
stop_app() {
    local pid
    if pid=$(get_pid); then
        echo "Stopping $APP_NAME (PID: $pid)..."
        kill "$pid"
        sleep 3
        if kill -0 "$pid" 2>/dev/null; then
            echo "  Force killing..."
            kill -9 "$pid"
        fi
        rm -f "$PID_FILE"
        echo "  Stopped."
    else
        echo "$APP_NAME is not running."
    fi
}

# 重启
restart_app() {
    stop_app
    sleep 1
    run_background
}

# 查看状态
show_status() {
    local pid
    if pid=$(get_pid); then
        echo "$APP_NAME is running (PID: $pid, Port: $PORT)"
    else
        echo "$APP_NAME is not running."
    fi
}

# 查看日志
show_logs() {
    if [ -f "$LOG_FILE" ]; then
        tail -f "$LOG_FILE"
    else
        echo "No log file found: $LOG_FILE"
    fi
}

# 主逻辑
case "${1:-run}" in
    run|foreground)
        run_foreground
        ;;
    start|background)
        run_background
        ;;
    stop)
        stop_app
        ;;
    restart)
        restart_app
        ;;
    status)
        show_status
        ;;
    logs)
        show_logs
        ;;
    *)
        echo "Usage: $0 {run|start|stop|restart|status|logs}"
        echo ""
        echo "  run (default) - 前台运行, 日志同时输出到终端和文件"
        echo "  start        - 后台运行, 关闭终端不影响"
        echo "  stop         - 停止后台进程"
        echo "  restart      - 重启"
        echo "  status       - 查看运行状态"
        echo "  logs         - 实时查看日志(tail -f)"
        exit 1
        ;;
esac
