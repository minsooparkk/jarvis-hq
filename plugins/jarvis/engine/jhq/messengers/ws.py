"""웹소켓 한 겹(websocket-client 패키지). Slack Socket Mode 와 Discord 게이트웨이가 쓴다.

websocket-client 를 고른 이유: 순수 파이썬이고 의존이 없으며, 동기(스레드) 방식이라 jarvisd(스레드로 도는 데몬)와
맞는다. discord.py·slack_sdk 의 비동기 틀을 데몬에 들이지 않고, 두 메신저를 같은 모양으로 시험할 수 있다(가짜 연결 주입).
Slack·Discord 를 고른 설치에만 엔진 venv 에 받는다(텔레그램은 표준 라이브러리만).
"""

import struct


class Closed(ConnectionError):
    """상대가 연결을 닫음. code: 닫힘 코드(모르면 None)."""

    def __init__(self, code=None, reason=""):
        super().__init__(f"웹소켓 닫힘 {code} {reason}".strip())
        self.code = code


class Conn:
    """recv() → 글 하나 또는 None(시간 초과·제어 프레임). 닫히면 Closed."""

    def __init__(self, url, timeout=5):
        import websocket
        self.wsmod = websocket
        self.ws = websocket.create_connection(url, timeout=timeout, enable_multithread=True)

    def recv(self):
        w = self.wsmod
        try:
            op, frame = self.ws.recv_data_frame(True)
        except w.WebSocketTimeoutException:
            return None
        except (w.WebSocketConnectionClosedException, OSError) as e:
            raise Closed(None, str(e)) from None
        if op == w.ABNF.OPCODE_CLOSE:
            data = frame.data or b""
            raise Closed(struct.unpack("!H", data[:2])[0] if len(data) >= 2 else None)
        if op == w.ABNF.OPCODE_PING:
            self.ws.pong(frame.data)
            return None
        if op in (w.ABNF.OPCODE_TEXT, w.ABNF.OPCODE_BINARY):
            return frame.data.decode("utf-8", errors="replace") if isinstance(frame.data, bytes) else frame.data
        return None

    def send(self, text):
        try:
            self.ws.send(text)
        except (self.wsmod.WebSocketException, OSError) as e:
            raise Closed(None, str(e)) from None

    def close(self, code=1000):
        try:
            self.ws.close(status=code)
        except Exception:  # noqa: BLE001
            pass


def connect(url, timeout=5):
    return Conn(url, timeout)
