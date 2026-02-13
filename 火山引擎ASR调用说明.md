# 火山引擎（豆包）流式语音识别 API 调用说明

## 服务信息

| 项目 | 值 |
|------|-----|
| 服务名称 | 豆包流式语音识别模型 2.0 |
| WebSocket 地址 | `wss://openspeech.bytedance.com/api/v3/sauc/bigmodel` |
| Resource ID | `volc.bigasr.sauc.duration`（按时长计费） |
| 协议 | WebSocket 双向流式，自定义二进制协议 |

## 控制台配置

### 前置条件

1. 注册火山引擎账号，进入 [豆包语音控制台](https://console.volcengine.com/speech/app)
2. 创建应用，在**接入能力**中勾选「豆包流式语音识别模型2.0 小时版」
3. 购买时长包（服务中心 → 豆包流式语音识别模型2.0 → 购买）
4. 获取应用凭证：

| 控制台字段 | 用途 | 对应 Header |
|-----------|------|-------------|
| APP ID | 应用标识 | `X-Api-App-Key` |
| Access Token | 访问令牌 | `X-Api-Access-Key` |
| Secret Key | 不需要使用 | — |

## 认证方式

WebSocket 连接时通过 HTTP Header 传递认证信息：

```
X-Api-App-Key: {APP ID}
X-Api-Access-Key: {Access Token}
X-Api-Resource-Id: volc.bigasr.sauc.duration
X-Api-Request-Id: {UUID}
```

## 二进制协议

### 协议头（4 字节）

```
Byte 0: [协议版本 4bit=0001] [头大小 4bit=0001]  → 0x11
Byte 1: [消息类型 4bit]       [标志位 4bit]
Byte 2: [序列化方式 4bit]     [压缩方式 4bit]
Byte 3: 保留 0x00
```

消息类型：
- `0001` — 客户端完整请求（初始化）
- `0010` — 客户端纯音频请求
- `1001` — 服务端完整响应
- `1111` — 服务端错误响应

标志位：
- `0001` (POS_SEQUENCE) — 正序号，非最后一包
- `0011` (NEG_WITH_SEQUENCE) — 负序号，最后一包

序列化方式：
- `0001` — JSON

压缩方式：
- `0001` — GZIP

### 消息格式

```
[协议头 4B] [seq 4B, signed int, big-endian] [payload_size 4B, unsigned int] [payload]
```

- `seq`：序列号，从 1 开始递增。最后一包时取负值（`-seq`）
- `payload`：JSON 序列化后经 GZIP 压缩的数据（包括音频数据也需要 GZIP 压缩）

## 调用流程

### 1. 建立 WebSocket 连接

```python
import aiohttp
import uuid

headers = {
    "X-Api-Resource-Id": "volc.bigasr.sauc.duration",
    "X-Api-Request-Id": str(uuid.uuid4()),
    "X-Api-Access-Key": "{Access Token}",
    "X-Api-App-Key": "{APP ID}",
}

session = aiohttp.ClientSession()
ws = await session.ws_connect(
    "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel",
    headers=headers
)
```

### 2. 发送初始化请求（seq=1）

```python
payload = {
    "user": {"uid": "your_user_id"},
    "audio": {
        "format": "pcm",     # 必须是 "pcm"，不能用 "raw"
        "codec": "pcm",
        "rate": 16000,        # 采样率 16kHz
        "bits": 16,           # 16bit
        "channel": 1          # 单声道
    },
    "request": {
        "model_name": "bigmodel",
        "enable_punc": True,  # 启用标点
        "enable_itn": True,   # 启用数字/日期格式化
        "result_type": "single"
    }
}
```

构建消息：`协议头 + seq(4B) + payload_size(4B) + gzip(json(payload))`

发送后等待服务端返回初始化响应（包含空 text 的 result）。

### 3. 流式发送音频

将 PCM 音频按 200ms 分块（16kHz × 16bit × 1ch × 0.2s = 6400 bytes），逐包发送：

```python
# 非最后一包：flags=POS_SEQUENCE, seq 为正数
# 最后一包：  flags=NEG_WITH_SEQUENCE, seq 取负值

# 音频数据同样需要 GZIP 压缩
compressed_audio = gzip.compress(pcm_bytes)
msg = header + struct.pack(">i", seq) + struct.pack(">I", len(compressed_audio)) + compressed_audio
```

### 4. 接收识别结果

服务端返回的响应格式：

```json
{
    "audio_info": {"duration": 200},
    "result": {
        "text": "识别的文字",
        "additions": {"log_id": "..."}
    }
}
```

响应解析要点：
- 通过 `header_size`（Byte 0 低 4 位）× 4 定位 payload 起始位置
- 标志位 `& 0x01` 表示有 seq 字段（4B），需跳过
- 标志位 `& 0x02` 表示最后一包（`is_final`）
- payload 先读 4B `payload_size`，再读对应长度数据，GZIP 解压后 JSON 解析
- `result` 字段为 dict，识别文本在 `result.text` 中

### 5. 关闭连接

发送最后一包（空音频 + `is_last=True`）后，服务端会返回最终结果（`is_final=True`），之后连接自动关闭。

## 常见错误

| HTTP 状态码 | 错误信息 | 原因 |
|------------|---------|------|
| 401 | `load grant: requested grant not found` | APP ID 或 Access Token 错误 |
| 403 | `requested resource not granted` | 应用未勾选对应服务能力，或未购买资源包 |
| 400 | `resourceId xxx is not allowed` | Resource ID 不正确 |
| 400 | `unsupported format raw` | 音频 format 必须填 `"pcm"` 而非 `"raw"` |

## 注意事项

- Access Token 中 `I`（大写 i）和 `l`（小写 L）容易混淆，建议直接从控制台复制
- 音频格式必须填 `"pcm"`，不能填 `"raw"`（服务端不支持）
- 所有数据（包括音频）都需要 GZIP 压缩
- seq 序号从 1 开始，每发一包递增，最后一包取负值
- 使用 `aiohttp` 或 `websockets` 库均可建立 WebSocket 连接
