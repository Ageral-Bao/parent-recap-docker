"""The setup page's HTTP shell: the one-time code, the safeguards, idle shutdown, and routing each
call to the phase that answers it.

Safeguards, since anything that can reach the port can reach the page:
  - it listens on 127.0.0.1 only, on a free port, unless SETUP_BIND names another address: a
    container sets 0.0.0.0 so the browser on the machine running it can reach the page, and then
    the page's own address is whatever Host the request came in on (SETUP_PORT pins the port)
  - the address carries a one-time random code as its first path segment, and every request must
    have it; the page's own links are relative, so they carry it too. The one exception is the
    browser's own ask for /favicon.ico, answered with nothing, since a refusal is a console error
  - a request whose Host or Origin isn't the page's own address is refused, which stops other
    sites and DNS rebinding; an answer must also come from the page's own script, as JSON. Bound
    to another address, the Origin must match the Host the request came in on: another site's
    page sends its own Origin, so it is refused just the same, without having to know in advance
    which address the family reaches the container on
  - it serves only the files in `page/`, by name, and they load nothing from the internet
  - it stops after 30 minutes without a request
It logs nothing about requests, since their address carries the code.
"""
from __future__ import annotations

import argparse
import hmac
import json
import math
import os
import re
import socketserver
import threading
from collections.abc import Iterable, Mapping, Set
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from secrets import token_urlsafe
from typing import Any, TypeVar

from .. import setup_connect, setup_report, setup_save
from ..system import desktop, profile, secrets
from .context import Action, Context, Page, Phase, Timeouts
from .phases import PHASES

PAGE_DIR = Path(__file__).parent.parent / "page"
FILES = {  # what the page is made of, by the path under its address
    "": ("index.html", "text/html; charset=utf-8"),
    "page.js": ("page.js", "text/javascript; charset=utf-8"),
    "page.css": ("page.css", "text/css; charset=utf-8"),
    "text.json": ("text.json", "application/json; charset=utf-8"),
    "myclub-tilaa.webp": ("myclub-tilaa.webp", "image/webp"),  # where MyClub's link is
}
FAVICON = "/favicon.ico"  # which the browser asks for at the root, outside the code, on every load
STATE = "api/state"  # the page's state, which every phase adds its part to
ALIVE = "api/alive"  # what the page asks every few seconds to see its program is still there
MAX_BODY = 64 * 1024
HEADERS = {
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; "
                               "img-src 'self'; connect-src 'self'; frame-src 'self'; "
                               "base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer",  # the address carries the code
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
}
T = TypeVar("T")


def register(steps) -> None:
    p = steps.add_parser("page", help="Open the setup page in the browser, served from this Mac "
                         "until 30 minutes without use")
    p.add_argument("--bind", default=None,
                   help="The address to listen on (default: SETUP_BIND, else 127.0.0.1; a "
                        "container sets 0.0.0.0 so the browser on the machine running it reaches "
                        "the page)")
    p.add_argument("--port", type=int, default=None,
                   help="The port to listen on (default: SETUP_PORT, else a free one)")
    p.set_defaults(func=cmd_page)


def cmd_page(args: argparse.Namespace) -> int:
    config = Path(os.path.expanduser(os.path.expandvars(args.config or "~/.family/config.yaml")))
    return serve(SetupServer(Context(config, timeouts=_timeouts()),
                             bind=args.bind, port=args.port))


def _timeouts() -> Timeouts:
    """The page's idle shutdown, 30 minutes unless SETUP_IDLE_MINUTES says otherwise, and none at
    all at 0: reached over the network, the family goes away and comes back, so a container keeps
    it as long as it runs."""
    minutes = os.environ.get("SETUP_IDLE_MINUTES", "").strip()
    if not minutes:
        return Timeouts()
    try:
        idle = float(minutes) * 60
    except ValueError:
        return Timeouts()
    return Timeouts(idle=idle if idle > 0 else math.inf)


def serve(server: SetupServer) -> int:
    """Opens `server`'s page in the browser and serves it until it stops, saying so in the window
    the page runs from."""
    address = server.reachable_url
    out: dict[str, Any] = {"result": "opened", "url": address}
    if not desktop.open_url(address):
        out = {"result": "not-opened", "url": address, "port": server.port,
               "next": f"The browser didn't open. Open this address in it: {address}"}
    if not secrets.reachable():  # the page says so too
        out["warning"] = setup_report.KEYCHAIN_WARNING
    print(json.dumps(out, ensure_ascii=False), flush=True)
    try:
        server.serve_until_idle()
    except KeyboardInterrupt:
        server.stop()
    print(closed_line(server.context.chosen_language() or "en"), flush=True)
    return 0


def closed_line(language: str) -> str:
    """What the window the page runs from says once it stops, however it stopped, in the language
    picked on it: Terminal on a Mac, the PowerShell window the install line was pasted into on
    Windows."""
    return profile.current().closed_lines[language]


LOOPBACK = ("127.0.0.1", "localhost", "::1")


def _code() -> str:
    """The code the page's address carries, which is the only way in: random per start unless
    SETUP_CODE pins it. A container restarts often, and its page's address is what the family keeps
    as a bookmark, so pinning it, in .env, saves copying a new one out of the log every time."""
    given = os.environ.get("SETUP_CODE", "").strip()
    if given and re.fullmatch(r"[A-Za-z0-9_-]{16,}", given):
        return given
    return token_urlsafe(32)


def _bind_address(bind: str | None, port: int | None) -> tuple[str, int]:
    """Where to listen: what the command asked for, else SETUP_BIND and SETUP_PORT, else
    127.0.0.1 on a free port."""
    host = (bind or os.environ.get("SETUP_BIND") or "").strip() or "127.0.0.1"
    if port is None:
        try:
            port = int(os.environ.get("SETUP_PORT") or 0)
        except ValueError:
            port = 0
    return host, port


def _lan_ip() -> str:
    """This machine's address on the interface its default route leaves by, which is the one a
    browser on the same network reaches it through. No packet is sent: the kernel only picks the
    address."""
    import socket
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("10.255.255.255", 1))
            return str(probe.getsockname()[0])
        finally:
            probe.close()
    except OSError:
        return "127.0.0.1"


class SetupServer:
    """The setup page's server for `context`'s config, listening from when it's made, answering
    the calls of each of `phases`, through `listener` on `bind`'s free port: 127.0.0.1 unless
    another address is asked for, as a container does so the machine running it reaches the page."""

    def __init__(self, context: Context, phases: Iterable[type[Phase]] = PHASES,
                 listener: type[ThreadingHTTPServer] | None = None,
                 bind: str | None = None, port: int | None = None) -> None:
        self.context = context
        self.phases = [phase(context) for phase in phases]
        reserved = {*FILES, STATE}
        self.actions: dict[str, Action] = _routes(reserved, (p.routes() for p in self.phases))
        self.pages: dict[str, Page] = _routes(reserved, (p.pages() for p in self.phases))
        self.code = _code()
        bind_host, bind_port = _bind_address(bind, port)
        self._httpd = (listener or _HTTPServer)((bind_host, bind_port), _Handler)
        self._httpd.setup = self  # type: ignore[attr-defined]
        host, port = self._httpd.server_address[:2]
        self.address = (str(host), int(port))
        self.port = int(port)
        # Bound to another address, the page is reached under whatever Host the request came in
        # on, which can't be known here: the checks compare each request's Origin with its own
        # Host instead of with a fixed address.
        self.wildcard = str(host) not in LOOPBACK
        self.host = "" if self.wildcard else f"{host}:{port}"
        self.origin = "" if self.wildcard else f"http://{self.host}"
        self.url = f"{self.origin}/{self.code}/"
        # What to open, or to print when nothing opens: SETUP_PUBLIC_URL when whatever runs this
        # knows how the family reaches it (a container's mapped port), else this machine's
        # address on its network.
        base = os.environ.get("SETUP_PUBLIC_URL", "").strip().rstrip("/")
        if not base:
            base = self.origin or f"http://{_lan_ip()}:{port}"
        self.reachable_url = f"{base}/{self.code}/"
        self.last_request = context.clock()
        self._serving = False
        self._state = threading.Lock()

    def serve_until_idle(self) -> None:
        """Serves until `stop`, or until the idle timeout passes without a request."""
        context = self.context
        with self._state:
            if context.stopped.is_set():
                return
            self._serving = True
        thread = threading.Thread(target=self._httpd.serve_forever,
                                  args=(context.timeouts.poll,), daemon=True)
        thread.start()
        try:
            while not context.stopped.wait(context.timeouts.poll):
                if context.clock() - self.last_request >= context.timeouts.idle:
                    break
        finally:
            self._httpd.shutdown()
            self._httpd.server_close()
            thread.join()

    def stop(self) -> None:
        with self._state:
            self.context.stopped.set()  # also ends Claude's sign-in
            if not self._serving:
                self._httpd.server_close()
        for phase in self.phases:
            phase.stop()
        self.context.chat.join()

    def state(self) -> dict[str, Any]:
        for phase in self.phases:
            phase.opening()
        progress = self.context.progress()
        out: dict[str, Any] = {"progress": progress}
        for phase in self.phases:
            out |= phase.state(progress)
        return out


def _routes(reserved: Set[str], tables: Iterable[Mapping[str, T]]) -> dict[str, T]:
    """The phases' routes as one table, refusing a path two phases, or a phase and the shell,
    both answer."""
    routes: dict[str, T] = {}
    for table in tables:
        for path, route in table.items():
            if path in routes or path in reserved:
                raise ValueError(f"{path} is answered twice")
            routes[path] = route
    return routes


class _HTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer without its look-up of this Mac's host name when it binds, which
    can take several seconds on some Macs and networks while the family waits for the page."""

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name, self.server_port = str(host), int(port)


class _Handler(BaseHTTPRequestHandler):
    server_version = "ParentRecap"
    sys_version = ""

    def log_message(self, format: str, *args: Any) -> None:
        pass  # a request's address carries the code

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def _handle(self, method: str) -> None:
        setup: SetupServer = self.server.setup  # type: ignore[attr-defined]
        # Read all of what was sent before any answer: answering and closing while the body is
        # still coming in resets the connection, and the sender never sees the answer.
        body = self._read_body()
        if (method == "GET" and self.path.partition("?")[0] == FAVICON
                and (setup.wildcard or self.headers.get("Host") == setup.host)):
            return self._send(HTTPStatus.NO_CONTENT, b"", "text/plain; charset=utf-8")
        path = self._own_path(setup, method)
        if path is None:
            return self._send(HTTPStatus.FORBIDDEN, b"Forbidden\n", "text/plain; charset=utf-8")
        if method == "GET" and path == "/" + ALIVE:  # not use: an open tab doesn't keep it running
            return self._send(HTTPStatus.NO_CONTENT, b"", "text/plain; charset=utf-8")
        setup.last_request = setup.context.clock()
        if not path:  # the address without its final slash, which the page's links need
            return self._send(HTTPStatus.MOVED_PERMANENTLY, b"", "text/plain; charset=utf-8",
                              Location=setup.url)
        path = path[1:]
        if method == "GET" and path in FILES:
            name, kind = FILES[path]
            return self._send(HTTPStatus.OK, (PAGE_DIR / name).read_bytes(), kind)
        if method == "GET" and path == STATE:
            return self._json(HTTPStatus.OK, setup.state())
        if method == "GET" and path in setup.pages and (served := setup.pages[path]()) is not None:
            page, kind, headers = served
            return self._send(HTTPStatus.OK, page, kind, **headers)
        if method == "POST" and path in setup.actions:
            raw = _json_body(body)
            if raw is _NOT_JSON:
                return self._json(HTTPStatus.BAD_REQUEST, setup_save.outcome(
                    "invalid-answers", "The answers aren't JSON.", errors=["not JSON"]))
            try:
                reply = setup.actions[path](raw)
            except setup_connect.Malformed as e:  # the same refusal from every call
                reply = HTTPStatus.BAD_REQUEST, e.answer
            self._json(*reply)
            if setup.context.closing:  # setup is done, and the page has been told
                setup.stop()
            return None
        return self._send(HTTPStatus.NOT_FOUND, b"Not found\n", "text/plain; charset=utf-8")

    def _own_path(self, setup: SetupServer, method: str) -> str | None:
        """The path after the code, from its slash (empty without one), or None if the request
        isn't the page's own: the wrong Host or Origin, or without the code."""
        origin = self.headers.get("Origin")
        checkable = origin is not None or method != "GET"
        if setup.wildcard:
            # Bound to another address, this request's Host is the page's own address only if
            # its Origin agrees: a page on another site sends that site's Origin, and is refused.
            host = self.headers.get("Host") or ""
            if not host or (checkable and origin != f"http://{host}"):
                return None
        else:
            if self.headers.get("Host") != setup.host:
                return None
            if checkable and origin != setup.origin:
                return None
        if method == "POST" and self.headers.get_content_type() != "application/json":
            return None
        _, _, rest = self.path.partition("?")[0].partition("/")
        code, slash, path = rest.partition("/")
        if not hmac.compare_digest(code.encode(), setup.code.encode()):
            return None
        return slash + path

    def _read_body(self) -> bytes | None:
        """The request's body, read to its end; None if it has no length that can be read, or is
        longer than MAX_BODY, whose rest is read and dropped."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if length < 0:
            return None
        body = self.rfile.read(min(length, MAX_BODY))
        remaining = length - len(body)
        while remaining > 0:
            chunk = self.rfile.read(min(remaining, MAX_BODY))
            if not chunk:
                break
            remaining -= len(chunk)
        return body if length <= MAX_BODY else None

    def _json(self, status: HTTPStatus, out: dict[str, Any]) -> None:
        self._send(status, json.dumps(out, ensure_ascii=False).encode(),
                   "application/json; charset=utf-8")

    def _send(self, status: HTTPStatus, body: bytes, kind: str, **headers: str) -> None:
        self.send_response(status)
        for name, value in {**HEADERS, **headers, "Content-Type": kind,
                            "Content-Length": str(len(body))}.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)


_NOT_JSON = object()


def _json_body(body: bytes | None) -> Any:
    if not body:
        return _NOT_JSON
    try:
        return json.loads(body)
    except ValueError:
        return _NOT_JSON
