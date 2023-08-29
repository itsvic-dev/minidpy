import aiohttp


_BASE_URL = "https://discord.com/api"


class REST:
    def __init__(
        self, session: aiohttp.ClientSession, token: str, *, is_bot=True, version=10
    ):
        self._session = session
        self._token = token
        self._is_bot = is_bot
        self._version = version

        self._session.headers["Authorization"] = (
            "Bot " if is_bot else ""
        ) + self._token

    async def get(self, endpoint: str):
        resp = await self._session.get(f"{_BASE_URL}/v{self._version}{endpoint}")
        data = await resp.json()
        if "code" in data and "message" in data:
            raise RESTError(data["code"], data["message"])

    async def post(self, endpoint: str, data: any):
        resp = await self._session.post(
            f"{_BASE_URL}/v{self._version}{endpoint}", json=data
        )
        data = await resp.json()
        if "code" in data and "message" in data:
            raise RESTError(data["code"], data["message"])


class RESTError(Exception):
    def __init__(self, code: int, message: str):
        super(f"Error {code}: {message}")
        self.code = code
        self.message = message
