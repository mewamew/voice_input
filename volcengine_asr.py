"""
火山引擎（豆包）流式语音识别客户端

基于 WebSocket 双向流式识别，支持边录音边出文字。
协议参考：火山引擎语音识别 BigModel API
"""
import asyncio
import gzip
import json
import struct
import threading
import time
import uuid
from typing import Callable, Optional

import websockets


# 协议常量
PROTOCOL_VERSION = 0b0001
HEADER_SIZE = 0b0001  # 4 bytes

# Message types
CLIENT_FULL_REQUEST = 0b0001
CLIENT_AUDIO_ONLY = 0b0010
SERVER_FULL_RESPONSE = 0b1001
SERVER_ACK = 0b1011
SERVER_ERROR = 0b1111

# Message type specific flags
MSG_NO_SEQUENCE = 0b0000
MSG_POS_SEQUENCE = 0b0001
MSG_NEG_SEQUENCE = 0b0010
MSG_NEG_WITH_SEQUENCE = 0b0011

# Serialization
MSG_JSON = 0b0001

# Compression
MSG_NO_COMPRESSION = 0b0000
MSG_GZIP = 0b0001

# WebSocket 地址
WS_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"


def _build_header(message_type: int, flags: int, serialization: int, compression: int) -> bytes:
    """构建 4 字节协议头"""
    header = bytearray(4)
    header[0] = (PROTOCOL_VERSION << 4) | HEADER_SIZE
    header[1] = (message_type << 4) | flags
    header[2] = (serialization << 4) | compression
    header[3] = 0x00  # reserved
    return bytes(header)


def _build_request(payload: dict, seq: int) -> bytes:
    """构建完整请求（header + seq + payload size + payload）"""
    payload_bytes = json.dumps(payload).encode("utf-8")
    compressed = gzip.compress(payload_bytes)
    header = _build_header(CLIENT_FULL_REQUEST, MSG_POS_SEQUENCE, MSG_JSON, MSG_GZIP)
    return header + struct.pack(">i", seq) + struct.pack(">I", len(compressed)) + compressed


def _build_audio_frame(audio_bytes: bytes, seq: int, is_last: bool = False) -> bytes:
    """构建音频帧（header + seq + payload size + compressed audio）"""
    if is_last:
        flags = MSG_NEG_WITH_SEQUENCE
        seq = -seq
    else:
        flags = MSG_POS_SEQUENCE
    header = _build_header(CLIENT_AUDIO_ONLY, flags, MSG_JSON, MSG_GZIP)
    compressed = gzip.compress(audio_bytes)
    return header + struct.pack(">i", seq) + struct.pack(">I", len(compressed)) + compressed


def _parse_response(data: bytes) -> dict:
    """解析服务端响应"""
    if len(data) < 4:
        return {"type": "error", "text": "响应数据太短"}

    header = data[0:4]
    msg_type = (header[1] >> 4) & 0x0F
    flags = header[1] & 0x0F
    serialization = (header[2] >> 4) & 0x0F
    compression = header[2] & 0x0F

    # header_size 字段决定 payload 起始位置
    header_word_size = data[0] & 0x0F  # 以 4 字节为单位
    payload = data[header_word_size * 4:]

    is_final = False
    # 解析 flags 中的 seq 和 last 标记
    if flags & 0x01:  # 有 sequence
        payload = payload[4:]  # 跳过 seq (4 bytes)
    if flags & 0x02:  # negative / last
        is_final = True

    if msg_type == SERVER_FULL_RESPONSE:
        payload_size = struct.unpack(">I", payload[:4])[0]
        payload_bytes = payload[4:4 + payload_size]

        if compression == MSG_GZIP:
            payload_bytes = gzip.decompress(payload_bytes)

        if serialization == MSG_JSON:
            msg = json.loads(payload_bytes)
            # 2.0 格式: {"result": {"text": "..."}}
            result = msg.get("result", {})
            if isinstance(result, dict):
                text = result.get("text", "")
            else:
                # 兼容旧格式: {"result": [{"text": "..."}]}
                text_parts = [item.get("text", "") for item in result]
                text = "".join(text_parts)

            return {
                "type": "result",
                "text": text,
                "is_final": is_final
            }

    elif msg_type == SERVER_ACK:
        return {"type": "ack"}

    elif msg_type == SERVER_ERROR:
        code = struct.unpack(">i", payload[:4])[0]
        err_payload_size = struct.unpack(">I", payload[4:8])[0]
        payload_bytes = payload[8:8 + err_payload_size]
        if compression == MSG_GZIP:
            payload_bytes = gzip.decompress(payload_bytes)
        error_info = json.loads(payload_bytes) if serialization == MSG_JSON else {}
        return {"type": "error", "text": str(error_info)}

    return {"type": "unknown"}


class VolcengineStreamingASR:
    """火山引擎流式语音识别客户端"""

    # 音频分块大小（200ms @ 16kHz 16bit mono = 6400 bytes）
    CHUNK_DURATION_MS = 200
    CHUNK_SIZE = int(16000 * 2 * CHUNK_DURATION_MS / 1000)  # 6400 bytes
    # 最多缓存 12 秒音频，防止网络异常导致内存持续增长
    MAX_BUFFER_SIZE = CHUNK_SIZE * 60
    # stop() 等待服务端最终结果的时限
    STOP_WAIT_TIMEOUT_SECONDS = 12
    # 超时后主动关闭 WebSocket 的补充等待时长
    FORCE_CLOSE_WAIT_SECONDS = 2

    def __init__(
        self,
        app_key: str,
        access_key: str,
        on_partial_result: Optional[Callable[[str], None]] = None,
        on_final_result: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        self.app_key = app_key
        self.access_key = access_key
        self.on_partial_result = on_partial_result
        self.on_final_result = on_final_result
        self.on_error = on_error

        self._request_id = str(uuid.uuid4())
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ws = None
        self._connected = asyncio.Event()
        self._stopped = False
        self._audio_buffer = bytearray()
        self._buffer_lock = threading.Lock()
        self._final_text = ""
        self._done_event = threading.Event()
        self._seq = 1  # 协议序号
        self._overflow_notified = False
        self._stop_lock = threading.Lock()

    def start(self):
        """启动 WebSocket 连接（在独立线程中运行 asyncio 事件循环）"""
        self._stopped = False
        self._done_event.clear()
        self._final_text = ""
        self._seq = 1
        self._request_id = str(uuid.uuid4())
        self._overflow_notified = False
        with self._buffer_lock:
            self._audio_buffer.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self):
        """运行 asyncio 事件循环"""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._session())
        except Exception as e:
            if self.on_error:
                self.on_error(f"WebSocket 会话异常: {e}")
        finally:
            self._done_event.set()
            self._loop.close()

    async def _session(self):
        """WebSocket 会话"""
        headers = {
            "X-Api-App-Key": self.app_key,
            "X-Api-Access-Key": self.access_key,
            "X-Api-Resource-Id": "volc.bigasr.sauc.duration",
            "X-Api-Request-Id": self._request_id,
        }

        connect_kwargs = {"additional_headers": headers}
        # websockets>=15 默认读取系统代理；这里优先禁用代理，避免缺少 python-socks 时直接失败
        try:
            connect_ctx = websockets.connect(WS_URL, proxy=None, **connect_kwargs)
        except TypeError:
            connect_ctx = websockets.connect(WS_URL, **connect_kwargs)

        try:
            async with connect_ctx as ws:
                self._ws = ws
                self._connected.set()

                # 发送初始化请求
                init_payload = {
                    "user": {
                        "uid": "voice_input_user"
                    },
                    "audio": {
                        "format": "pcm",
                        "codec": "pcm",
                        "rate": 16000,
                        "bits": 16,
                        "channel": 1
                    },
                    "request": {
                        "model_name": "bigmodel",
                        "enable_punc": True,
                        "enable_itn": True,
                        "result_type": "single"
                    }
                }

                await ws.send(_build_request(init_payload, self._seq))
                self._seq += 1

                # 等待初始化响应
                init_resp = await ws.recv()
                if isinstance(init_resp, str):
                    init_resp = init_resp.encode("utf-8")
                init_result = _parse_response(init_resp)
                if init_result["type"] == "error":
                    if self.on_error:
                        self.on_error(init_result.get("text", "初始化失败"))
                    self._stopped = True
                    return

                # 启动音频发送协程和接收协程
                send_task = asyncio.create_task(self._send_audio_loop())
                recv_task = asyncio.create_task(self._recv_loop())

                # 等待两个任务完成
                await asyncio.gather(send_task, recv_task)

        except websockets.exceptions.ConnectionClosed as e:
            if not self._stopped:
                self._emit_error(f"WebSocket 连接关闭: {e}")
            self._stopped = True
        except Exception as e:
            self._emit_error(f"WebSocket 连接失败: {e}")
            self._stopped = True
        finally:
            self._ws = None

    async def _send_audio_loop(self):
        """音频发送循环：从缓冲区取数据，按 200ms 分块发送"""
        while not self._stopped:
            if self._ws and self._is_ws_closed():
                self._stopped = True
                break

            chunk = None
            with self._buffer_lock:
                if len(self._audio_buffer) >= self.CHUNK_SIZE:
                    chunk = bytes(self._audio_buffer[:self.CHUNK_SIZE])
                    del self._audio_buffer[:self.CHUNK_SIZE]

            if chunk and self._ws:
                try:
                    await self._ws.send(_build_audio_frame(chunk, self._seq, is_last=False))
                    self._seq += 1
                except Exception as e:
                    if not self._stopped:
                        self._emit_error(f"发送音频失败: {e}")
                    self._stopped = True
                    break
            else:
                await asyncio.sleep(0.05)

        # 发送剩余缓冲区数据
        while self._ws:
            if self._is_ws_closed():
                break
            chunk = None
            with self._buffer_lock:
                if len(self._audio_buffer) == 0:
                    break
                chunk = bytes(self._audio_buffer[:self.CHUNK_SIZE])
                del self._audio_buffer[:self.CHUNK_SIZE]
            try:
                await self._ws.send(_build_audio_frame(chunk, self._seq, is_last=False))
                self._seq += 1
            except Exception:
                break

        # 发送结束标记
        if self._ws and not self._is_ws_closed():
            try:
                await self._ws.send(_build_audio_frame(b"", self._seq, is_last=True))
            except Exception:
                pass

    async def _recv_loop(self):
        """接收服务端响应"""
        stopped_since = None
        while self._ws:
            try:
                data = await asyncio.wait_for(self._ws.recv(), timeout=1.0)
                if isinstance(data, str):
                    data = data.encode("utf-8")

                result = _parse_response(data)
                stopped_since = None

                if result["type"] == "result":
                    text = result["text"]
                    if result["is_final"]:
                        self._final_text = text
                        if self.on_final_result:
                            self.on_final_result(text)
                        self._stopped = True
                        return  # 收到最终结果，退出接收循环
                    else:
                        if self.on_partial_result:
                            self.on_partial_result(text)

                elif result["type"] == "error":
                    self._emit_error(result.get("text", "未知错误"))
                    self._stopped = True
                    return

                elif result["type"] == "ack":
                    pass  # 确认消息，忽略

            except asyncio.TimeoutError:
                if self._stopped:
                    if stopped_since is None:
                        stopped_since = time.time()
                    elif time.time() - stopped_since >= self.STOP_WAIT_TIMEOUT_SECONDS:
                        self._stopped = True
                        return
                continue
            except websockets.exceptions.ConnectionClosed:
                self._stopped = True
                return
            except Exception as e:
                if not self._stopped:
                    self._emit_error(f"接收响应异常: {e}")
                self._stopped = True
                return

    def feed_audio(self, pcm_bytes: bytes):
        """喂入 PCM 音频数据（线程安全）"""
        if self._stopped or not pcm_bytes:
            return
        overflow_happened = False
        with self._buffer_lock:
            self._audio_buffer.extend(pcm_bytes)
            if len(self._audio_buffer) > self.MAX_BUFFER_SIZE:
                overflow = len(self._audio_buffer) - self.MAX_BUFFER_SIZE
                del self._audio_buffer[:overflow]
                if not self._overflow_notified:
                    self._overflow_notified = True
                    overflow_happened = True

        if overflow_happened:
            print("Warning: ASR audio buffer overflow, dropped old audio chunks.")

    def stop(self) -> str:
        """停止流式识别，等待最终结果

        Returns:
            最终识别文本
        """
        with self._stop_lock:
            self._stopped = True
            thread = self._thread

        if not thread:
            return self._final_text

        # 第一阶段：等待服务端返回 final
        if self._done_event.wait(timeout=self.STOP_WAIT_TIMEOUT_SECONDS):
            return self._final_text

        # 第二阶段：超时则主动关闭连接，确保后台线程退出
        ws = self._ws
        if ws and self._loop and not self._loop.is_closed():
            try:
                future = asyncio.run_coroutine_threadsafe(ws.close(), self._loop)
                future.result(timeout=self.FORCE_CLOSE_WAIT_SECONDS)
            except Exception:
                pass

        self._done_event.wait(timeout=self.FORCE_CLOSE_WAIT_SECONDS)
        return self._final_text

    def get_final_text(self) -> str:
        """获取最终识别文本"""
        return self._final_text

    def _emit_error(self, msg: str):
        """安全触发错误回调"""
        if self.on_error:
            try:
                self.on_error(msg)
            except Exception:
                pass

    def _is_ws_closed(self) -> bool:
        """兼容不同 websockets 版本判断连接是否关闭"""
        ws = self._ws
        if ws is None:
            return True

        closed_attr = getattr(ws, "closed", None)
        if isinstance(closed_attr, bool):
            return closed_attr

        state = getattr(ws, "state", None)
        if state is None:
            return False

        try:
            return str(state).upper().endswith("CLOSED")
        except Exception:
            return False
