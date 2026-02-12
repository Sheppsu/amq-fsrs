import aiohttp
import logging
import json
import socketio as sio
import asyncio
import time


_log = logging.getLogger(__name__)
SESSION_LIFETIME = 60 * 60 * 2


class URL:
    SIGNIN = "https://animemusicquiz.com/signIn"
    SOCKET_TOKEN = "https://animemusicquiz.com/socketToken"
    SOCKET = "https://socket.animemusicquiz.com"
    MASTER_LIST = "https://animemusicquiz.com/libraryMasterList"


class EmitCallback:
    def __init__(self):
        self.result = None
        self.evt = asyncio.Event()

    async def wait_finished(self, timeout=5):
        await asyncio.wait_for(self.evt.wait(), timeout)
        return self.result

    def __call__(self, result):
        self.result = result
        self.evt.set()


def get_session_cookie_jar():
    try:
        with open("session.json", "r") as f:
            session_info = json.load(f)
        if session_info.get("last_updated") + SESSION_LIFETIME < time.time():
            return

        cookie_jar = aiohttp.CookieJar()
        cookie_jar.load("session_cookies")

        _log.info("Using previous session cookies")
        return cookie_jar
    except FileNotFoundError:
        return


class AMQClient:
    def __init__(self, username: str, trainer):
        self.username: str = username
        cookie_jar = get_session_cookie_jar()
        self.session: aiohttp.ClientSession = aiohttp.ClientSession(cookie_jar=cookie_jar)
        self.logged_in: bool = cookie_jar is not None
        self.socket: sio.AsyncClient | None = None
        self.unresolved_results = {}

        self.trainer = trainer

    async def login(self, password: str):
        if self.logged_in:
            return True

        data = {
            "username": self.username,
            "password": password,
            "stayLoggedIn": True
        }
        resp = await self.session.post(URL.SIGNIN, data=data)
        if resp.status == 200:
            self.logged_in = True
            _log.info("Login success")

            self.session.cookie_jar.save("session_cookies")
            with open("session.json", "w") as f:
                json.dump({"last_updated": time.time()}, f)

            return True

        _log.info("Login failed: %s" % (await resp.text()))
        return False

    async def _get_socket_info(self):
        resp = await self.session.get(URL.SOCKET_TOKEN)
        if resp.status == 200:
            data = json.loads(await resp.text())
            return data["token"], data["port"]

        _log.info("Failed to retrieve socket token: %s" % (await resp.text()))

    async def connect(self):
        if not self.logged_in:
            raise RuntimeError("Must login first")
        if self.socket is not None:
            raise RuntimeError("Already connected")

        socket_info = await self._get_socket_info()
        if socket_info is None:
            return False
        _log.info("Socket token retrieved")
        socket_token, socket_port = socket_info

        self.socket = sio.AsyncClient()

        @self.socket.on("command")
        async def on_command(data):
            result = self.unresolved_results.get(data["command"])
            if result is not None:
                result(data["data"])
                self.unresolved_results.pop(data["command"])
                return

            await self._handle_extra_messages(data["command"], data["data"])

        @self.socket.event
        async def connect():
            _log.info("Socket is connected")
            # set invisible
            await self.socket.emit("command", {
                "type": "social",
                "command": "change social status",
                "data": {
                    "socialStatus": 4
                }
            })
            _log.info("Requesting master list and anime list...")
            await asyncio.sleep(1)
            await self.socket.emit("command", {
                "type": "library",
                "command": "get current master list id"
            })
            await self.socket.emit("command", {
                "type": "library",
                "command": "get anime status list"
            })

        @self.socket.event
        def connect_error(data):
            _log.warning("Connection failed: %s" % data)

        @self.socket.event
        def disconnect(reason):
            _log.warning("Disconnected: %s" % reason)

        await self.socket.connect(URL.SOCKET + ":" + socket_port + "/?token=" + socket_token)

        return True

    async def close(self):
        await self.session.close()
        self.logged_in = False
        if self.socket is not None:
            await self.socket.disconnect()
            self.socket = None

    async def _handle_extra_messages(self, command: str, data: dict):
        if command == "get current master list id":
            _log.info("Received master list")
            master_list_id = data["masterListId"]
            resp = await self.session.get(URL.MASTER_LIST, params={"masterId": master_list_id})
            self.trainer.set_master_list(json.loads(await resp.text()))
        elif command == "get anime status list":
            _log.info("Received anime list")
            self.trainer.set_my_list(data["animeListMap"])

    async def video_host_change(self, host: str):
        if self.socket is None:
            raise RuntimeError("Socket not connected")

        await self.socket.emit("command", {
            "command": "video host change",
            "data": {"host": host},
            "type": "settings"
        })

    async def get_song_info(self, ann_song_id: int):
        if self.socket is None:
            raise RuntimeError("Socket not connected")

        result = EmitCallback()
        self.unresolved_results["get song extended info"] = result
        await self.socket.emit("command", {
            "command": "get song extended info",
            "data": {
                "annSongId": ann_song_id,
                "includeFileNames": True
            },
            "type": "library"
        })

        return await result.wait_finished()
