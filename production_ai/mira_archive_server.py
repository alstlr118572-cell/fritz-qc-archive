#!/usr/bin/env python3
import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
STORE_PATH = ROOT / "production_ai" / "data" / "mira_archive_store.json"
PORT = int(os.environ.get("PORT", "8765"))
STORE_PROVIDER = os.environ.get("MIRA_STORE_PROVIDER", "local").strip().lower()
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_TABLE = os.environ.get("MIRA_SUPABASE_TABLE", "mira_archive_store")


class StoreError(Exception):
    pass


def read_store():
    if STORE_PROVIDER == "supabase":
        return read_supabase_store()
    if not STORE_PATH.exists():
        return {}
    try:
        return json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_store(store):
    if STORE_PROVIDER == "supabase":
        write_supabase_store(store)
        return
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")


def supabase_headers(prefer=""):
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise StoreError("Supabase storage requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.")
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def supabase_request(path, method="GET", payload=None, prefer=""):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        f"{SUPABASE_URL}/rest/v1/{path}",
        data=body,
        method=method,
        headers=supabase_headers(prefer),
    )
    try:
        with urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise StoreError(f"Supabase HTTP {error.code}: {detail}") from error
    except URLError as error:
        raise StoreError(f"Supabase connection failed: {error}") from error


def read_supabase_store():
    rows = supabase_request(f"{SUPABASE_TABLE}?select=key,value")
    if not isinstance(rows, list):
        return {}
    return {row.get("key"): row.get("value") for row in rows if row.get("key")}


def write_supabase_store(store):
    rows = [{"key": key, "value": value} for key, value in store.items()]
    if not rows:
        return
    supabase_request(
        f"{SUPABASE_TABLE}?on_conflict=key",
        method="POST",
        payload=rows,
        prefer="resolution=merge-duplicates",
    )


def store_status():
    return {
        "provider": STORE_PROVIDER,
        "supabaseConfigured": bool(SUPABASE_URL and SUPABASE_KEY),
        "table": SUPABASE_TABLE if STORE_PROVIDER == "supabase" else "",
    }


class MiraArchiveHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        super().end_headers()

    def send_json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/ping":
            self.send_json(200, {"ok": True, "store": store_status()})
            return
        if parsed.path.startswith("/api/store/"):
            key = unquote(parsed.path.removeprefix("/api/store/"))
            try:
                store = read_store()
                self.send_json(200, {"value": store.get(key)})
            except StoreError as error:
                self.send_json(500, {"error": str(error)})
            return
        super().do_GET()

    def do_PUT(self):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/store/"):
            self.send_json(404, {"error": "not found"})
            return
        key = unquote(parsed.path.removeprefix("/api/store/"))
        length = int(self.headers.get("Content-Length", "0") or "0")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except Exception:
            self.send_json(400, {"error": "invalid json"})
            return
        try:
            store = read_store()
            store[key] = payload.get("value")
            write_store(store)
            self.send_json(200, {"ok": True})
        except StoreError as error:
            self.send_json(500, {"error": str(error)})


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), MiraArchiveHandler)
    print(f"Fritz QC Archive server: http://127.0.0.1:{PORT}/production_ai/mira_archive.html")
    print(f"Store provider: {STORE_PROVIDER}")
    print("Keep this window open while using the archive.")
    server.serve_forever()
