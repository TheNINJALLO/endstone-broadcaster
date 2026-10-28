import http.client
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock

import pytest

from endstone_broadcaster.signaling import MAX_BODY, SignalingHTTPProxy


@contextmanager
def backend(
    *, modern=False, protocol=2193, missing=False, invalid=False, refused=False
):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.command, self.path, b"", self.headers))
            query = "?" in self.path
            if self.path == "/notification":
                code, body = 200, b"notification endpoint"
            elif refused and query:
                code, body = 403, b"denied"
            elif missing or (query and not modern):
                code, body = 404, b"Not Found"
            else:
                code = 200
                body = (
                    b"<html>not NetherNet</html>"
                    if invalid
                    else json.dumps(
                        {
                            "name": "Test Server",
                            "protocol": protocol,
                            "version": "1.26.52",
                            "level": "World",
                            "players": 0,
                            "maxPlayers": 10,
                            "gameType": 0,
                        }
                    ).encode()
                )
            self.reply(code, body)

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            requests.append((self.command, self.path, body, self.headers))
            self.reply(200, b"v=0\r\na=identity:signed-answer\r\n")

        def reply(self, code, body):
            self.send_response(code)
            self.send_header(
                "Content-Type",
                "application/sdp" if self.command == "POST" else "application/json",
            )
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    try:
        yield server, requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request(proxy, server, path, method="GET", body=None):
    connection = http.client.HTTPConnection(
        "127.0.0.1", proxy.server.server_port, timeout=3
    )
    try:
        connection.request(
            method,
            f"http://127.0.0.1:{server.server_port}{path}",
            body=body,
            headers={"Content-Type": "application/sdp", "Accept": "application/sdp"},
        )
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def test_legacy_query_falls_back_and_signed_join_stays_identical():
    logger = Mock()
    with backend() as (server, requests):
        proxy = SignalingHTTPProxy("127.0.0.1", server.server_port, logger)
        try:
            assert (
                request(
                    proxy,
                    server,
                    "/v1/join?version=1.26.60&protocol=2225&platform=-1&id=42",
                )[0]
                == 200
            )
            assert requests[0][1].endswith("&id=42")
            assert requests[1][1] == "/v1/join"
            assert proxy.server.legacy is True
            assert request(proxy, server, "/v1/join?id=43")[0] == 200
            assert requests[-1][1] == "/v1/join"
            offer = b"v=0\r\na=identity:signed-client-token\r\na=candidate:abc\r\n"
            assert request(proxy, server, "/v1/join/42", "POST", offer) == (
                200,
                b"v=0\r\na=identity:signed-answer\r\n",
            )
            method, path, recorded, headers = requests[-1]
            assert (method, path, recorded) == ("POST", "/v1/join/42", offer)
            assert headers["Content-Type"] == "application/sdp"
            assert headers["Host"] == f"127.0.0.1:{server.server_port}"
            logger.info.assert_called_once()
        finally:
            proxy.stop()
        assert not proxy.thread.is_alive()


def test_modern_queries_are_forwarded_unchanged():
    with backend(modern=True, protocol=2225) as (server, requests):
        proxy = SignalingHTTPProxy("127.0.0.1", server.server_port, Mock())
        try:
            path = "/v1/join?version=1.26.60&protocol=2225&platform=-1&id=42"
            assert request(proxy, server, path)[0] == 200
            assert [item[1] for item in requests] == [path]
            assert proxy.server.legacy is False
        finally:
            proxy.stop()


@pytest.mark.parametrize(
    "settings,expected_requests",
    [
        ({"missing": True}, 2),
        ({"invalid": True}, 2),
        ({"protocol": 2225}, 2),
        ({"refused": True}, 1),
    ],
)
def test_does_not_mask_missing_routes_invalid_status_or_modern_refusals(
    settings, expected_requests
):
    with backend(**settings) as (server, requests):
        proxy = SignalingHTTPProxy("127.0.0.1", server.server_port, Mock())
        try:
            expected_code = 403 if settings.get("refused") else 404
            assert request(proxy, server, "/v1/join?id=42")[0] == expected_code
            assert len(requests) == expected_requests
            assert proxy.server.legacy is False
        finally:
            proxy.stop()


def test_fallback_is_scoped_to_the_configured_backend_and_other_http_still_works():
    with backend() as (server, requests):
        proxy = SignalingHTTPProxy("different.invalid", server.server_port, Mock())
        try:
            assert request(proxy, server, "/v1/join?id=42")[0] == 404
            assert len(requests) == 1
            assert request(proxy, server, "/notification") == (
                200,
                b"notification endpoint",
            )
            assert proxy.server.legacy is False
        finally:
            proxy.stop()


def test_simultaneous_legacy_requests_all_recover():
    with backend() as (server, _):
        proxy = SignalingHTTPProxy("127.0.0.1", server.server_port, Mock())
        try:
            results = []
            threads = [
                threading.Thread(
                    target=lambda: results.append(
                        request(proxy, server, "/v1/join?id=42")[0]
                    )
                )
                for _ in range(4)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=4)
                assert not thread.is_alive()
            assert results == [200] * 4
        finally:
            proxy.stop()


def test_limits_request_size_without_forwarding():
    with backend() as (server, requests):
        proxy = SignalingHTTPProxy("127.0.0.1", server.server_port, Mock())
        connection = http.client.HTTPConnection(
            "127.0.0.1", proxy.server.server_port, timeout=3
        )
        try:
            connection.putrequest(
                "POST", f"http://127.0.0.1:{server.server_port}/v1/join/42"
            )
            connection.putheader("Content-Length", str(MAX_BODY + 1))
            connection.endheaders()
            response = connection.getresponse()
            assert response.status == 413
            response.read()
            assert requests == []
        finally:
            connection.close()
            proxy.stop()
