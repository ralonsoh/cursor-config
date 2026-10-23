#!/usr/bin/env python3
"""End-to-end test: real socket, fake upstream, SSE streaming intact."""

from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cursor_effort_proxy as proxy


class FakeUpstream(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    received: list[dict] = []
    received_headers: list[dict] = []

    def log_message(self, *args):  # silence
        pass

    def do_GET(self):
        if self.path.endswith("/models"):
            payload = json.dumps({"data": [{"id": "vendor/model1"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n) if n else b""
        FakeUpstream.received_headers.append(dict(self.headers.items()))
        try:
            FakeUpstream.received.append(json.loads(body))
        except Exception:
            FakeUpstream.received.append({"__raw__": body.decode("utf-8", "replace")})

        # Stream three SSE events, then a text/event-stream terminator.
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for i in range(3):
            chunk = f'data: {{"n":{i}}}\n\n'.encode()
            self.wfile.write(b"%x\r\n" % len(chunk) + chunk + b"\r\n")
            self.wfile.flush()
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()


class TestProxyEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.upstream = ThreadingHTTPServer(("127.0.0.1", 0), FakeUpstream)
        cls.upstream.daemon_threads = True
        threading.Thread(target=cls.upstream.serve_forever, daemon=True).start()

        up_host, up_port = cls.upstream.server_address[:2]
        cls.cfg = proxy.Config(
            upstream=f"http://{up_host}:{up_port}/v1",
            log=False,
            api_key="test-key",
            rules=[
                proxy.Rule(
                    match=__import__("re").compile("model-a"),
                    param="reasoning_effort",
                    value="high",
                )
            ],
        )
        proxy.Handler.cfg = cls.cfg
        proxy.Handler.api_key = cls.cfg.api_key
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), proxy.Handler)
        cls.srv.daemon_threads = True
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = "http://%s:%d" % cls.srv.server_address[:2]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.upstream.shutdown()
        cls.srv.server_close()
        cls.upstream.server_close()

    def _post(self, payload):
        import http.client

        host, port = self.srv.server_address[:2]
        conn = http.client.HTTPConnection(host, port, timeout=10)
        conn.request(
            "POST",
            "/v1/chat/completions",
            body=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, resp.getheader("Content-Type"), data

    def test_injection_reaches_upstream(self):
        FakeUpstream.received.clear()
        status, ctype, data = self._post(
            {"model": "vendor/model-a", "messages": [], "stream": True}
        )
        self.assertEqual(status, 200)
        self.assertEqual(FakeUpstream.received[0]["reasoning_effort"], "high")

    def test_sse_stream_content_preserved(self):
        FakeUpstream.received.clear()
        status, ctype, data = self._post(
            {"model": "vendor/model-a", "messages": [], "stream": True}
        )
        self.assertEqual(status, 200)
        self.assertIn("text/event-stream", ctype)
        self.assertEqual(data, b'data: {"n":0}\n\ndata: {"n":1}\n\ndata: {"n":2}\n\n')

    def test_non_matching_model_untouched(self):
        FakeUpstream.received.clear()
        status, _, _ = self._post({"model": "gpt-5.4", "messages": []})
        self.assertEqual(status, 200)
        self.assertNotIn("reasoning_effort", FakeUpstream.received[0])

    def test_get_passthrough(self):
        import http.client

        host, port = self.srv.server_address[:2]
        conn = http.client.HTTPConnection(host, port, timeout=10)
        conn.request("GET", "/v1/models")
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        self.assertEqual(resp.status, 200)
        self.assertIn(b"vendor/model1", data)

    def test_healthz(self):
        import http.client

        host, port = self.srv.server_address[:2]
        conn = http.client.HTTPConnection(host, port, timeout=10)
        conn.request("GET", "/healthz")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.read(), b"ok\n")
        conn.close()

    def _post_with_auth(self, payload, auth):
        import http.client

        host, port = self.srv.server_address[:2]
        conn = http.client.HTTPConnection(host, port, timeout=10)
        conn.request(
            "POST",
            "/v1/chat/completions",
            body=json.dumps(payload),
            headers={"Content-Type": "application/json", "Authorization": auth},
        )
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data

    def test_configured_api_key_replaces_client_header(self):
        FakeUpstream.received.clear()
        FakeUpstream.received_headers.clear()
        self._post_with_auth(
            {"model": "vendor/model-a", "messages": []}, "Bearer client-supplied"
        )
        auth = FakeUpstream.received_headers[0].get("Authorization")
        self.assertEqual(auth, "Bearer test-key")

    def test_api_key_injected_when_client_sends_none(self):
        FakeUpstream.received.clear()
        FakeUpstream.received_headers.clear()
        self._post({"model": "vendor/model-a", "messages": []})
        auth = FakeUpstream.received_headers[0].get("Authorization")
        self.assertEqual(auth, "Bearer test-key")

    def test_no_duplicate_authorization_headers(self):
        FakeUpstream.received.clear()
        FakeUpstream.received_headers.clear()
        self._post_with_auth(
            {"model": "vendor/model-a", "messages": []}, "Bearer client-supplied"
        )
        raw = dict(FakeUpstream.received_headers[0])
        self.assertNotIn("client-supplied", str(raw))


if __name__ == "__main__":
    unittest.main()
