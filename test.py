from minidpy import Gateway
import asyncio
import aiohttp
import logging


async def on_ready(data):
    print("hello!! logged in as", data["user"]["username"])


async def main():
    logging.basicConfig(level=logging.DEBUG)
    with open("token.txt") as file:
        token = file.readline().strip("\n")
    gateway = Gateway(aiohttp.ClientSession(), token)

    gateway.on("READY", on_ready)

    await gateway.connect()


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
