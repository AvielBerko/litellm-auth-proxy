#!/usr/bin/env python3
"""Tiny local reverse proxy that adds `Authorization: Bearer <key>` to every
request and forwards it to a LiteLLM server.

Point OpenWhispr's Self-Hosted URL at this proxy (e.g. http://127.0.0.1:8787/v1)
and it will forward to UPSTREAM (e.g. https://litellm.example.com/v1/...).

Config via env vars or flags:
  --upstream                 override the LITELLM_URL constant below
  LITELLM_API_KEY / --key    the key to inject
  --host / --port            where to listen (default 127.0.0.1:8787)
  LITELLM_MODEL / --model    optional: force the multipart `model` field
                             (e.g. qwen3-asr) if OpenWhispr sends another name

Stdlib only, Python 3.8+.
"""
import argparse
import http.client
import os
import re
import ssl
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

# Base URL of your LiteLLM server (without /v1). Edit this.
LITELLM_URL = "https://your-litellm-host:4000"

HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
}


def rewrite_model(body: bytes, content_type: str, model: str) -> bytes:
    """Replace the `model` field value in a multipart/form-data body."""
    m = re.search(r'boundary="?([^";]+)"?', content_type or "")
    if not m:
        return body
    boundary = m.group(1).encode()
    pattern = re.compile(
        rb'(--' + re.escape(boundary) +
        rb'\r\nContent-Disposition: form-data; name="model"\r\n(?:[^\r\n]+\r\n)*\r\n)'
        rb'(.*?)(\r\n--' + re.escape(boundary) + rb')',
        re.DOTALL | re.IGNORECASE,
    )
    return pattern.sub(lambda mm: mm.group(1) + model.encode() + mm.group(3), body, count=1)


def make_handler(upstream, key, model, verbose):
    up = urlsplit(upstream.rstrip("/"))
    base_path = up.path  # e.g. "" or "/litellm"
    is_https = up.scheme == "https"
    ctx = ssl.create_default_context() if is_https else None

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _proxy(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None

            ctype = self.headers.get("Content-Type", "")
            if body and model and "multipart/form-data" in ctype:
                body = rewrite_model(body, ctype, model)

            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
            headers.pop("Authorization", None)
            headers.pop("authorization", None)
            headers["Authorization"] = f"Bearer {key}"
            headers["Host"] = up.netloc
            if body is not None:
                headers["Content-Length"] = str(len(body))

            path = base_path + self.path
            conn_cls = http.client.HTTPSConnection if is_https else http.client.HTTPConnection
            kwargs = {"context": ctx} if is_https else {}
            conn = conn_cls(up.hostname, up.port, timeout=300, **kwargs)
            try:
                conn.request(self.command, path, body=body, headers=headers)
                resp = conn.getresponse()
                data = resp.read()
            except Exception as e:  # upstream unreachable etc.
                msg = f'{{"error": "proxy upstream error: {e}"}}'.encode()
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(msg)))
                self.end_headers()
                self.wfile.write(msg)
                return
            finally:
                conn.close()

            if verbose:
                sys.stderr.write(f"  -> {self.command} {up.scheme}://{up.netloc}{path} = {resp.status}\n")
                if resp.status >= 400:
                    sys.stderr.write(f"     {data[:500]!r}\n")

            self.send_response(resp.status, resp.reason)
            for k, v in resp.getheaders():
                if k.lower() not in HOP_BY_HOP:
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = _proxy

        def do_OPTIONS(self):  # permissive CORS preflight, in case it's needed
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "*")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.send_header("Content-Length", "0")
            self.end_headers()

    return Handler


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--upstream", default=LITELLM_URL)
    p.add_argument("--key", default=os.environ.get("LITELLM_API_KEY"))
    p.add_argument("--model", default=os.environ.get("LITELLM_MODEL"))
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("-q", "--quiet", action="store_true")
    a = p.parse_args()
    if not a.key:
        p.error("need --key or LITELLM_API_KEY")

    handler = make_handler(a.upstream, a.key, a.model, not a.quiet)
    if a.quiet:
        handler.log_message = lambda *args: None
    srv = ThreadingHTTPServer((a.host, a.port), handler)
    print(f"Proxy listening on http://{a.host}:{a.port} -> {a.upstream}"
          + (f" (forcing model={a.model})" if a.model else ""), file=sys.stderr)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
