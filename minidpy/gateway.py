import aiohttp
import asyncio
import json
import zlib
import logging

logger = logging.getLogger(__name__)

_GATEWAY_URL = "wss://gateway.discord.gg/?v=10&encoding=json"
_ZLIB_SUFFIX = b"\x00\x00\xff\xff"  # Z_SYNC_FLUSH


class Gateway:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        token: str,
        *,
        intents=1 << 0 | 1 << 9,
        use_zlib_stream=True,
    ):
        self._seq = -1
        self._token = token
        self._session = session
        self._heartbeat_task = None
        self._read_task = None
        self.intents = intents

        self._event_listeners: dict[str, list[callable]] = {}
        self._session_id = None
        self._resume_url = None
        self._missed_heartbeat = False
        self._use_zlib_stream = use_zlib_stream
        if self._use_zlib_stream:
            self._decompressobj = zlib.decompressobj()
            self._buffer = bytearray()

    async def connect(self):
        self._ws = await self._session.ws_connect(
            _GATEWAY_URL + ("&compress=zlib-stream" if self._use_zlib_stream else "")
        )
        self._read_task = asyncio.create_task(self._read_task_impl())

    async def reconnect(self):
        logger.info("reconnecting...")
        self._heartbeat_task.cancel()
        self._read_task.cancel()
        await self._ws.close()
        self._missed_heartbeat = False

        self._ws = await self._session.ws_connect(self._resume_url)
        self._read_task = asyncio.create_task(self._read_task_impl())

    def on(self, event: str, function: callable):
        if event not in self._event_listeners:
            self._event_listeners[event] = []
        self._event_listeners[event].append(function)

    async def _read_task_impl(self):
        async for msg in self._ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                await self._handle_ws_message(msg.data)
            elif msg.type == aiohttp.WSMsgType.BINARY and self._use_zlib_stream:
                self._buffer.extend(msg.data)

                if len(msg.data) < 4 or msg.data[-4:] != _ZLIB_SUFFIX:
                    continue

                msg = self._decompressobj.decompress(self._buffer)
                self._buffer = bytearray()
                await self._handle_ws_message(msg.decode())
            else:
                logger.debug("received unknown msg type, ignoring")
        if self._ws.closed:
            logger.debug(f"closed in read task, code {self._ws.close_code}")
            asyncio.create_task(self.reconnect())

    async def _handle_ws_message(self, message: str):
        data = json.loads(message)
        logger.debug(f"recv op={data['op']} t={data['t']}")
        if "s" in data:
            self._seq = data["s"]
        func = None
        if data["t"] is not None:
            func = getattr(self, f"_event_{data['t']}", None)
            if data["t"] in self._event_listeners:
                for function in self._event_listeners[data["t"]]:
                    try:
                        await function(data["d"])
                    except Exception as error:
                        logger.error(f"Uncaught exception: {error}")
        else:
            func = getattr(self, f"_op_{data['op']}", None)

        if func:
            try:
                await func(data["d"])
            except Exception as error:
                logger.error(f"Uncaught exception in library code: {error}")
        else:
            logger.debug(f"unknown opcode or event: op={data['op']} t={data['t']}")

    async def _op_10(self, data):
        """
        Opcode 10: HELLO
        """

        async def heartbeat():
            while not self._ws.closed:
                if self._missed_heartbeat:
                    logger.debug("missed heartbeat")
                    asyncio.create_task(self.reconnect())
                    raise asyncio.CancelledError()
                await self.send_opcode(1, None)
                self._missed_heartbeat = True
                await asyncio.sleep(data["heartbeat_interval"] / 1000)
            logger.debug("WS closed in heartbeat task")
            asyncio.create_task(self.reconnect())

        self._heartbeat_task = asyncio.create_task(heartbeat(), name="GatewayHeartbeat")
        if self._session_id is None:
            await self._send_identify()
        else:
            await self._send_resume()

    async def _op_11(self, _):
        """
        Opcode 11: HEARTBEAT ACK
        """
        self._missed_heartbeat = False

    async def _op_7(self, _):
        """
        Opcode 7: RECONNECT
        """
        asyncio.create_task(self.reconnect())

    async def _op_9(self, can_resume):
        """
        Opcode 9: INVALID SESSION
        """
        if not can_resume:
            self._session_id = None
            self._resume_url = _GATEWAY_URL
        asyncio.create_task(self.reconnect())

    async def _send_identify(self):
        """
        Opcode 2: IDENTIFY
        """

        await self.send_opcode(
            2,
            {
                "token": self._token,
                "properties": {
                    "os": "linux",
                    "browser": "minidpy",
                    "device": "minidpy",
                },
                "presence": {"status": "offline"},
                "intents": self.intents,
            },
        )

    async def _send_resume(self):
        """
        Opcode 6: RESUME
        """

        await self.send_opcode(
            6,
            {
                "token": self._token,
                "session_id": self._session_id,
                "seq": self._seq,
            },
        )

    async def _event_READY(self, data):
        self._resume_url = data["resume_gateway_url"]
        self._session_id = data["session_id"]

    async def send_opcode(self, opcode: int, data: any):
        if self._ws.closed:
            raise Exception("WS is closed")
        logger.debug(f"send op={opcode}")
        await self._ws.send_json({"op": opcode, "d": data})
