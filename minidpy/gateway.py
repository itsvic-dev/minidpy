import aiohttp
import asyncio
import json

_GATEWAY_URL = "wss://gateway.discord.gg/?v=10&encoding=json"


class Gateway:
    def __init__(
        self, session: aiohttp.ClientSession, token: str, *, intents=1 << 0 | 1 << 9
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

    async def connect(self):
        self._ws = await self._session.ws_connect(_GATEWAY_URL)
        self._read_task = asyncio.create_task(self._read_task_impl())

    async def reconnect(self):
        print("GATEWAY: reconnecting...")
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
                data = json.loads(msg.data)
                print(f"GATEWAY: recv op={data['op']} t={data['t']}")
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
                                print("Uncaught exception:", error)
                else:
                    func = getattr(self, f"_op_{data['op']}", None)

                if func:
                    try:
                        await func(data["d"])
                    except Exception as error:
                        print("Uncaught exception:", error)
                else:
                    print(
                        f"GATEWAY: unknown opcode or event: op={data['op']} t={data['t']}"
                    )
            else:
                raise Exception("uhhh")

    async def _op_10(self, data):
        """
        Opcode 10: HELLO
        """

        async def heartbeat():
            while not self._ws.closed:
                if self._missed_heartbeat:
                    print("GATEWAY: missed heartbeat")
                    asyncio.create_task(self.reconnect())
                    raise asyncio.CancelledError()
                await self.send_opcode(1, None)
                self._missed_heartbeat = True
                await asyncio.sleep(data["heartbeat_interval"] / 1000)
            print("GATEWAY: WS closed in heartbeat task")
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
        print(f"GATEWAY: send op={opcode}")
        await self._ws.send_json({"op": opcode, "d": data})
