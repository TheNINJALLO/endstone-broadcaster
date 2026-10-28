"""HTTP compatibility for older Bedrock signaling routes.

The upstream JAR and SDP messages stay unchanged. The JVM's HTTP proxy sends
ordinary requests through this loopback listener; HTTPS still goes directly.
Only a confirmed older backend's rejected status-query parameters are removed.
"""

import http.client
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

MAX_BODY = 4 * 1024 * 1024
HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "proxy-connection",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


def _headers(headers):
    omitted = HOP_HEADERS | {
        name.strip().lower()
        for name in headers.get("Connection", "").split(",")
        if name.strip()
    }
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in omitted and key.lower() != "content-length"
    }


def _legacy_status(body):
    try:
        status = json.loads(body)
        protocol = status.get("protocol")
        return (
            isinstance(status.get("name"), str)
            and isinstance(status.get("version"), str)
            and isinstance(protocol, int)
            and not isinstance(protocol, bool)
            and 0 < protocol < 2225
        )
    except (ValueError, AttributeError, UnicodeError):
        return False


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, backend, logger):
        self.backend = backend
        self.logger = logger
        self.legacy = False
        self.legacy_lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(128)
        super().__init__(("127.0.0.1", 0), _Handler)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, *args):
        # Never log SDP offers, identity assertions, or complete request URLs.
        pass

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def _handle(self):
        self.close_connection = True
        if not self.server.slots.acquire(blocking=False):
            self.send_error(503)
            return
        try:
            if self.headers.get("Transfer-Encoding"):
                self.send_error(400, "A Content-Length is required")
                return
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= MAX_BODY:
                self.send_error(413)
                return
            body = self.rfile.read(length)
            if len(body) != length:
                self.send_error(400)
                return
            url = urlsplit(self.path)
            if url.scheme:
                if (
                    url.scheme != "http"
                    or url.username
                    or url.password
                    or not url.hostname
                ):
                    self.send_error(400)
                    return
                host, port = url.hostname, url.port or 80
            else:
                host, port = self.server.backend
            if host in ("127.0.0.1", "localhost") and port == self.server.server_port:
                self.send_error(400)
                return
            path = url.path or "/"
            query = url.query
            is_status_query = (
                self.command == "GET"
                and path == "/v1/join"
                and bool(query)
                and (host.casefold(), port) == self.server.backend
            )
            target = path + ("?" + query if query else "")
            if is_status_query and self.server.legacy:
                target = path
            response = self._forward(host, port, target, body)
            if is_status_query and response[0] == 404 and target != path:
                bare = self._forward(host, port, path, body)
                if 200 <= bare[0] < 300 and _legacy_status(bare[2]):
                    with self.server.legacy_lock:
                        if not self.server.legacy:
                            self.server.legacy = True
                            self.server.logger.info(
                                "Enabled compatibility for the backend's older NetherNet status route"
                            )
                    response = bare
            code, headers, response_body = response
            self.send_response(code)
            for key, value in _headers(headers).items():
                if key.lower() not in ("server", "date"):
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(response_body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(response_body)
        except (OSError, http.client.HTTPException, ValueError) as error:
            self.server.logger.warning(f"HTTP signaling forwarding failed: {error}")
            try:
                self.send_error(502)
            except OSError:
                pass
        finally:
            self.server.slots.release()

    def _forward(self, host, port, target, body):
        connection = http.client.HTTPConnection(host, port, timeout=10)
        try:
            headers = _headers(self.headers)
            headers["Connection"] = "close"
            connection.request(self.command, target, body=body, headers=headers)
            response = connection.getresponse()
            payload = response.read(MAX_BODY + 1)
            if len(payload) > MAX_BODY:
                raise ValueError("HTTP signaling response exceeds the size limit")
            return response.status, response.headers, payload
        finally:
            connection.close()


class SignalingHTTPProxy:
    def __init__(self, host, port, logger):
        self.server = _Server((host.casefold().strip("[]"), port), logger)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.1},
            name="broadcaster-http-compat",
            daemon=True,
        )
        self.thread.start()

    def java_options(self):
        return [
            "-Dhttp.proxyHost=127.0.0.1",
            f"-Dhttp.proxyPort={self.server.server_port}",
            "-Dhttp.nonProxyHosts=",
        ]

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
