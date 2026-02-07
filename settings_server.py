"""
设置服务 - 基于 FastAPI 的 Web 设置界面
"""
import os
from pathlib import Path
from typing import Optional
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import sounddevice as sd

from config_manager import get_config, get_history_manager

app = FastAPI(title="语音输入设置")

# 模板目录
TEMPLATE_DIR = Path(__file__).parent / "templates"


class MicrophoneConfig(BaseModel):
    """麦克风配置"""
    device_id: Optional[int] = None
    device_name: str = "自动（跟随系统）"


class ASRConfig(BaseModel):
    """ASR 配置"""
    api_key: Optional[str] = None
    model: Optional[str] = None


class LLMConfig(BaseModel):
    """LLM 配置"""
    api_key: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    correction_enabled: Optional[bool] = None
    correction_prompt: Optional[str] = None
    context_correction_enabled: Optional[bool] = None
    context_window_size: Optional[int] = None
    context_history_ttl: Optional[int] = None
    context_correction_prompt: Optional[str] = None


class ContextHistoryUpdate(BaseModel):
    """历史消息更新"""
    text: str


class ConfigUpdate(BaseModel):
    """配置更新请求"""
    microphone: Optional[MicrophoneConfig] = None
    asr: Optional[ASRConfig] = None
    llm: Optional[LLMConfig] = None


@app.get("/settings", response_class=HTMLResponse)
async def settings_page():
    """返回设置页面 HTML"""
    html_path = TEMPLATE_DIR / "settings.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "<h1>设置页面未找到</h1>"


@app.get("/api/config")
async def get_config_api():
    """获取当前配置"""
    config = get_config()

    # API Key 部分隐藏
    api_key = config.asr_api_key
    if api_key and len(api_key) > 8:
        masked_key = api_key[:4] + "*" * (len(api_key) - 8) + api_key[-4:]
    else:
        masked_key = ""

    # LLM API Key 部分隐藏
    llm_api_key = config.llm_api_key
    if llm_api_key and len(llm_api_key) > 8:
        masked_llm_key = llm_api_key[:4] + "*" * (len(llm_api_key) - 8) + llm_api_key[-4:]
    else:
        masked_llm_key = ""

    return {
        "microphone": {
            "device_id": config.microphone_device_id,
            "device_name": config.microphone_device_name
        },
        "asr": {
            "api_key": masked_key,
            "api_key_set": bool(api_key),
            "model": config.asr_model
        },
        "llm": {
            "api_key": masked_llm_key,
            "api_key_set": bool(llm_api_key),
            "provider": config.llm_provider,
            "model": config.llm_model,
            "correction_enabled": config.llm_correction_enabled,
            "correction_prompt": config.llm_correction_prompt,
            "context_correction_enabled": config.context_correction_enabled,
            "context_window_size": config.context_window_size,
            "context_history_ttl": config.context_history_ttl,
            "context_correction_prompt": config.context_correction_prompt
        },
        "context_history": get_history_manager().get_recent(config.context_window_size)
    }


@app.post("/api/config")
async def save_config_api(data: ConfigUpdate):
    """保存配置"""
    config = get_config()

    if data.microphone:
        config.set_microphone(
            device_id=data.microphone.device_id,
            device_name=data.microphone.device_name
        )

    if data.asr:
        if data.asr.api_key is not None:
            config.asr_api_key = data.asr.api_key
        if data.asr.model is not None:
            config.asr_model = data.asr.model

    if data.llm:
        if data.llm.api_key is not None:
            config.llm_api_key = data.llm.api_key
        if data.llm.provider is not None:
            config.llm_provider = data.llm.provider
        if data.llm.model is not None:
            config.llm_model = data.llm.model
        if data.llm.correction_enabled is not None:
            config.llm_correction_enabled = data.llm.correction_enabled
        if data.llm.correction_prompt is not None:
            config.llm_correction_prompt = data.llm.correction_prompt
        if data.llm.context_correction_enabled is not None:
            config.context_correction_enabled = data.llm.context_correction_enabled
        if data.llm.context_window_size is not None:
            config.context_window_size = data.llm.context_window_size
        if data.llm.context_history_ttl is not None:
            config.context_history_ttl = data.llm.context_history_ttl
        if data.llm.context_correction_prompt is not None:
            config.context_correction_prompt = data.llm.context_correction_prompt

    return {"status": "ok"}


@app.post("/api/llm/test")
async def test_llm_api():
    """测试 LLM API 连接"""
    config = get_config()

    api_key = config.get_effective_llm_api_key()
    if not api_key:
        return {"success": False, "message": "未设置 API Key"}

    # 根据 provider 获取 base_url
    provider = config.llm_provider
    if provider == "deepseek":
        base_url = "https://api.deepseek.com"
    else:
        base_url = "https://api.deepseek.com"

    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=api_key,
            base_url=base_url
        )

        # 发送简单测试请求
        completion = client.chat.completions.create(
            model=config.llm_model,
            messages=[{"role": "user", "content": "你好"}],
            max_tokens=10
        )

        response_text = completion.choices[0].message.content
        return {"success": True, "message": f"模型响应: {response_text}"}

    except Exception as e:
        return {"success": False, "message": str(e)}


@app.get("/api/context-history")
async def get_context_history():
    """获取历史消息列表（只返回窗口范围内的消息）"""
    config = get_config()
    history_mgr = get_history_manager()
    recent = history_mgr.get_recent(config.context_window_size)
    return {"history": recent}


@app.put("/api/context-history/{timestamp:path}")
async def update_context_history(timestamp: str, data: ContextHistoryUpdate):
    """编辑指定历史消息（使用 timestamp 作为标识）"""
    history_mgr = get_history_manager()
    history_mgr.update(timestamp, data.text)
    return {"status": "ok"}


@app.delete("/api/context-history/{timestamp:path}")
async def delete_context_history_item(timestamp: str):
    """删除指定历史消息（使用 timestamp 作为标识）"""
    history_mgr = get_history_manager()
    history_mgr.delete(timestamp)
    return {"status": "ok"}


@app.delete("/api/context-history")
async def clear_context_history():
    """清空历史消息"""
    history_mgr = get_history_manager()
    history_mgr.clear()
    return {"status": "ok"}


@app.get("/api/usage-stats")
async def get_usage_stats(page: int = 0, page_size: int = 20):
    """获取使用统计和分页历史消息"""
    history_mgr = get_history_manager()
    return history_mgr.get_page(page, page_size)


@app.get("/api/microphones")
async def get_microphones():
    """获取麦克风列表"""
    devices = []

    # 添加「自动」选项
    devices.append({
        "id": None,
        "name": "自动（跟随系统）"
    })

    # 获取输入设备列表
    try:
        all_devices = sd.query_devices()
        for i, device in enumerate(all_devices):
            if device['max_input_channels'] > 0:
                devices.append({
                    "id": i,
                    "name": device['name']
                })
    except Exception:
        pass

    return devices


def run_server(host: str = "127.0.0.1", port: int = 18321):
    """运行设置服务"""
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    run_server()
