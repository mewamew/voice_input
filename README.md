# Voice Input - macOS 语音输入工具

一款 macOS 状态栏语音输入应用，按下快捷键即可录音，自动识别并输入文字到任意应用程序。

## 功能特点

- **快捷键触发**：默认使用右 Command 键，按下开始录音，再按停止并识别
- **状态栏常驻**：隐藏 Dock 图标，仅显示状态栏图标
- **语音识别**：使用阿里云 DashScope ASR 服务
- **智能纠错**：可选的 LLM 纠错功能，自动修正识别错误
- **上下文纠错**：根据历史对话上下文纠正专有名词、人名等
- **Web 设置界面**：可视化配置，无需编辑配置文件

## 系统要求

- macOS 10.15+
- Python 3.9+

## 安装

### 1. 克隆项目

```bash
git clone https://github.com/mewamew/voice_input.git
cd voice_input
```

### 2. 创建虚拟环境并安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. 授予系统权限

应用需要以下权限才能正常工作：

1. **麦克风权限** - 录制语音
2. **辅助功能权限** - 模拟键盘输入文字
3. **输入监控权限** - 监听快捷键

首次运行时，系统会弹出权限请求。也可以手动在 **系统设置 → 隐私与安全性** 中授予。

## 配置

### API Key 配置

应用需要配置阿里云 DashScope API Key 进行语音识别。

**方式一：通过设置界面配置（推荐）**

启动应用后，点击状态栏图标 → 设置，在网页中配置 API Key。

**方式二：通过环境变量配置**

```bash
export DASHSCOPE_API_KEY="your-api-key"
```

### 获取 API Key

1. 访问 [阿里云 DashScope 控制台](https://dashscope.console.aliyun.com/)
2. 开通服务并创建 API Key

### 可选：LLM 纠错

如需启用 LLM 纠错功能，还需配置 DeepSeek API Key：

1. 访问 [DeepSeek 开放平台](https://platform.deepseek.com/)
2. 注册并创建 API Key
3. 在设置界面中配置

## 运行

### 使用启动脚本（推荐）

```bash
./start.sh
```

### 手动运行

```bash
source .venv/bin/activate
python voice_input_app.py
```

## 使用方法

### 基本操作

1. **开始录音**：按下快捷键（默认右 Command）
2. **停止录音**：再次按下快捷键
3. **文字输入**：识别完成后自动输入到当前光标位置

### 修正识别错误

当识别结果有误时：

1. 手动修改识别结果
2. 复制修改后的文本
3. 快速双击录音快捷键（间隔 < 0.4 秒）
4. 系统会用剪贴板内容更新最新历史记录

这样可以确保上下文纠错功能使用正确的历史记录。

### 设置界面

点击状态栏图标 → 设置，或直接访问 http://127.0.0.1:18321/settings

可配置项：

| 设置项 | 说明 |
|--------|------|
| 麦克风 | 选择音频输入设备 |
| ASR API Key | 阿里云 DashScope API Key |
| ASR 模型 | 语音识别模型（推荐 qwen3-asr-flash） |
| LLM API Key | DeepSeek API Key（可选） |
| 语音纠错 | 使用 LLM 纠正识别错误 |
| 上下文纠错 | 根据历史对话纠正专有名词等 |
| 历史消息数量 | 上下文纠错参考的历史条数（1-10） |
| 历史有效期 | 超过有效期的历史不参与纠错（5-60 分钟） |

## 配置文件

配置文件存储在 `~/.voice_input/config.json`，历史记录存储在 `~/.voice_input/history/` 目录。

## 项目结构

```
voice_input/
├── voice_input_app.py    # 主程序
├── audio_recorder.py     # 音频录制模块
├── keyboard_listener.py  # 键盘监听模块
├── text_inputter.py      # 文字输入模块
├── config_manager.py     # 配置管理模块
├── settings_server.py    # 设置服务（FastAPI）
├── templates/
│   └── settings.html     # 设置页面
├── microphone.png        # 录音中图标
├── microphone.slash.png  # 空闲状态图标
├── start.sh              # 启动脚本
└── requirements.txt      # Python 依赖
```

## 开机自启动

可以将启动脚本添加到登录项：

1. 打开 **系统设置 → 通用 → 登录项**
2. 点击 + 号添加 `start.sh`

或者创建 launchd 服务实现自启动。

## 常见问题

### Q: 快捷键没有反应？

检查是否授予了「输入监控」权限。在 **系统设置 → 隐私与安全性 → 输入监控** 中添加终端或 Python。

### Q: 文字无法输入？

检查是否授予了「辅助功能」权限。在 **系统设置 → 隐私与安全性 → 辅助功能** 中添加终端或 Python。

### Q: 识别结果不准确？

1. 确保麦克风正常工作
2. 尝试启用 LLM 纠错功能
3. 启用上下文纠错，让系统学习你常用的专有名词

## 许可证

MIT License
