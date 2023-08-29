import aiohttp
import asyncio


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

        if not self._is_bot:
            self._session.headers[
                "User-Agent"
            ] = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36"

    async def _request(self, method: str, endpoint: str, data: any):
        resp = await self._session.request(
            method, f"{_BASE_URL}/v{self._version}{endpoint}", json=data
        )
        data = await resp.json()
        if "retry_after" in data:
            await asyncio.sleep(data["retry_after"])
            return self._request(method, endpoint, data)
        if "code" in data and "message" in data:
            raise RESTError(data["code"], data["message"])
        return data

    async def get(self, endpoint: str):
        return await self._request("GET", endpoint, None)

    async def post(self, endpoint: str, data: any):
        return await self._request("POST", endpoint, data)


class RESTError(Exception):
    def __init__(self, code: int, message: str):
        super(f"Error {code}: {message}")
        self.code = code
        self.message = message
