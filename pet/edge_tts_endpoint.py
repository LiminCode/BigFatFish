# -*- coding: utf-8 -*-
"""edge-tts 的合成端点：握手被拒时换到另一个端点。

2026-10-10 起，微软的旧端点
``wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1`` 对合成
请求一律握手 403（音色列表仍正常），edge-tts 7.2.8（当时的最新版）还指着它——上游
issue rany2/edge-tts#490。同一份请求发到新端点
``wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1`` 能成功，输出格式相同。

这里不改库的默认值，只在**握手真的被拒**时换：

- 上游发了修复版、默认端点恢复之后，这段代码不会被触发，不用回头来删；
- 服务端要是哪天反过来（新的不通、旧的恢复），同样的逻辑会换回去。

端点是 edge-tts 模块级的一个变量（``edge_tts.communicate.WSS_URL``），换了之后本进程
后续的合成都用它，不必每次再撞一回已知不通的那个。

``edge_tts`` 只在函数里导入：调用方（合成线程）本来就已经导入了它，而本模块被别处
import 时不该把它拉进来（见 ``voice_chime_service`` 关于导入成本的说明）。
"""

from __future__ import annotations

import logging
import threading
from urllib.parse import urlparse

logger = logging.getLogger("big-fat-fish")

ALTERNATE_URL_TEMPLATE = (
    "wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1"
    "?Ocp-Apim-Subscription-Key={token}"
)
_REJECTED_STATUSES = (401, 403)

_lock = threading.Lock()
_library_url: str | None = None      # 库自己的端点；第一次换端点时记下


def is_rejected(exc: BaseException) -> bool:
    """这个失败是不是「握手被服务端拒绝」。

    只看异常上的 HTTP 状态码（aiohttp 的 ``WSServerHandshakeError.status``），不去匹配
    错误文字。超时、5xx、参数错误都不算——那些换端点没有用。"""
    return getattr(exc, "status", None) in _REJECTED_STATUSES


def switch() -> bool:
    """换到另一个端点；返回是否真的换了（库不可用或无处可换时为 False）。"""
    global _library_url
    try:
        import edge_tts.communicate as communicate
        from edge_tts.constants import TRUSTED_CLIENT_TOKEN
    except Exception:  # noqa: BLE001 - 库的内部结构变了：不换，交给调用方按原错误处理
        return False
    alternate = ALTERNATE_URL_TEMPLATE.format(token=TRUSTED_CLIENT_TOKEN)
    with _lock:
        current = getattr(communicate, "WSS_URL", None)
        if not isinstance(current, str):
            return False
        if _library_url is None:
            _library_url = current
        target = _library_url if current == alternate else alternate
        if target == current:
            return False
        communicate.WSS_URL = target
    logger.warning("语音合成端点 %s 拒绝了握手，改用 %s",
                   urlparse(current).hostname, urlparse(target).hostname)
    return True


def reset() -> None:
    """恢复库自己的端点并忘掉记录（测试用）。"""
    global _library_url
    with _lock:
        if _library_url is not None:
            try:
                import edge_tts.communicate as communicate

                communicate.WSS_URL = _library_url
            except Exception:  # noqa: BLE001
                pass
        _library_url = None
