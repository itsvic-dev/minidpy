import aiohttp
import asyncio
import json


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

    async def connect(self):
        self._ws = await self._session.ws_connect(
            "wss://gateway.discord.gg/?v=10&encoding=json"
        )
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
                            await function(data["d"])
                else:
                    func = getattr(self, f"_op_{data['op']}", None)

                if func:
                    await func(data["d"])
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
                await self.send_opcode(1, None)
                await asyncio.sleep(data["heartbeat_interval"])

        self._heartbeat_task = asyncio.create_task(heartbeat(), name="GatewayHeartbeat")
        await self._send_identify()

    async def _op_11(self, _):
        """
        Opcode 11: HEARTBEAT ACK
        """
        pass

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

    async def send_opcode(self, opcode: int, data: any):
        if self._ws.closed:
            raise Exception("WS is closed")
        print(f"GATEWAY: send op={opcode}")
        await self._ws.send_json({"op": opcode, "d": data})
