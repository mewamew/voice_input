#!/bin/bash

# 语音输入启动脚本

# 获取脚本所在目录
DIR="$(cd "$(dirname "$0")" && pwd)"

# 杀掉旧进程
pkill -f "voice_input_app.py" 2>/dev/null && echo "已停止旧进程"

# 激活虚拟环境并后台运行
source "$DIR/.venv/bin/activate"
nohup python "$DIR/voice_input_app.py" > /dev/null 2>&1 &

echo "语音输入已启动"
