#!/usr/bin/env python3
import json
import base64
import hashlib
import hmac
import os
import secrets
import time
import re
import threading
from http import cookies
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
USERS_KEY = "mira_blend_qc_users_v1"
ENTRIES_KEY = "mira_blend_qc_entries_v1"
RATIO_NOTICES_KEY = "mira_blend_qc_ratio_notices_v1"
NON_SHIP_RESULTS_KEY = "mira_blend_qc_non_ship_results_v1"
CORRECTION_INDICATORS_KEY = "mira_blend_qc_correction_indicators_v1"
GREEN_BEANS_KEY = "mira_blend_qc_green_beans_v1"
SINGLE_ORIGIN_SCHEDULES_KEY = "mira_blend_qc_single_origin_schedules_v1"
BLEND_CATALOG_KEY = "mira_blend_qc_catalog_v1"
PRODUCT_CATALOG_KEY = "mira_product_qc_catalog_v1"
SESSION_COOKIE = "mira_session"
SESSION_TTL_SECONDS = 60 * 60 * 6
SESSION_SECRET = (
    os.environ.get("MIRA_SESSION_SECRET")
    or (hmac.new(SUPABASE_KEY.encode(), b"mira-session-signing-v1", hashlib.sha256).hexdigest() if SUPABASE_KEY else "")
    or os.environ.get("SECRET_KEY")
    or secrets.token_hex(32)
)
PRIMARY_ADMIN_USER_ID = os.environ.get("MIRA_PRIMARY_ADMIN_USER_ID", "eomms0110").strip().lower()
SESSIONS = {}
REVOKED_SESSIONS = {}
LOGIN_ATTEMPTS = {}
SIGNUP_ATTEMPTS = {}
STORE_LOCK = threading.RLock()
MACHINE_DATA_KEY = "mira_customer_machine_data_v1"
PUBLIC_FILES = {name: ROOT / "production_ai" / name for name in (
    "mira_archive.html", "mira_archive_sw.js", "mira_archive_manifest.json",
    "mira_archive_icon.svg", "mira_archive_icon_192.png", "mira_archive_icon_512.png")}


class StoreError(Exception):
    pass


class AuthError(Exception):
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


def write_store_key(key, value):
    if STORE_PROVIDER == "supabase":
        write_supabase_store({key: value})
        return
    with STORE_LOCK:
        store = read_store()
        store[key] = value
        write_store(store)


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


def today_text():
    return time.strftime("%Y-%m-%d", time.localtime())


def normalize_user_id(value):
    return str(value or "").strip().lower()


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), salt.encode("utf-8"), 150000)
    return salt, digest.hex()


def verify_password(user, password):
    if user.get("passwordHash") and user.get("passwordSalt"):
        _, digest = password_hash(password, user.get("passwordSalt"))
        return hmac.compare_digest(digest, str(user.get("passwordHash")))
    legacy = user.get("password")
    return bool(legacy) and hmac.compare_digest(str(legacy), str(password))


def hash_user_password(user, password):
    salt, digest = password_hash(password)
    clean = dict(user)
    clean.pop("password", None)
    clean["passwordSalt"] = salt
    clean["passwordHash"] = digest
    return clean


def sanitize_user(user):
    clean = dict(user or {})
    clean.pop("password", None)
    clean.pop("passwordSalt", None)
    clean.pop("passwordHash", None)
    if user:
        clean["permissions"] = normalize_permissions(user)
    return clean


def is_primary_admin(user):
    return normalize_user_id(user.get("userId")) == PRIMARY_ADMIN_USER_ID


def normalize_role(role):
    if role == "admin":
        return "admin"
    if role in ("editor", "cupper"):
        return "cupper"
    if role == "roaster":
        return "roaster"
    if role == "green_manager":
        return "green_manager"
    if role == "account_manager":
        return "account_manager"
    return "viewer"


def role_permissions(role):
    normalized = normalize_role(role)
    if normalized == "admin":
        return ["cupping", "roasting", "correction", "green", "espresso", "visit", "machine_data", "product_qc"]
    if normalized == "cupper":
        return ["cupping"]
    if normalized == "roaster":
        return ["roasting", "correction"]
    if normalized == "green_manager":
        return ["green"]
    if normalized == "account_manager":
        return ["espresso", "visit", "machine_data"]
    return []


def normalize_permissions(user):
    allowed = {"cupping", "roasting", "correction", "green", "espresso", "visit", "product_qc", "machine_data"}
    permissions = set(role_permissions(user.get("role")))
    permissions.update(value for value in user.get("permissions", []) if value in allowed)
    return sorted(permissions)


def has_permission(user, permission):
    return is_primary_admin(user) or permission in normalize_permissions(user)


def has_any_operational_permission(user):
    return is_primary_admin(user) or bool(normalize_permissions(user))


def can_write_store_key(user, key):
    if is_primary_admin(user):
        return True
    if key == USERS_KEY or key == BLEND_CATALOG_KEY:
        return False
    if key in (GREEN_BEANS_KEY, RATIO_NOTICES_KEY, SINGLE_ORIGIN_SCHEDULES_KEY):
        return has_permission(user, "green")
    if key == CORRECTION_INDICATORS_KEY:
        return has_permission(user, "correction")
    if key == NON_SHIP_RESULTS_KEY:
        return has_any_operational_permission(user)
    if key == PRODUCT_CATALOG_KEY:
        return has_permission(user, "product_qc")
    if key == MACHINE_DATA_KEY:
        return has_permission(user, "machine_data")
    if key == ENTRIES_KEY:
        return any(has_permission(user, permission) for permission in ("cupping", "roasting", "espresso", "visit"))
    return False


def can_read_store_key(user, key):
    if key in (ENTRIES_KEY, BLEND_CATALOG_KEY, RATIO_NOTICES_KEY, SINGLE_ORIGIN_SCHEDULES_KEY):
        return True
    return can_write_store_key(user, key)


def entry_permission(entry):
    return {"roasting": "roasting", "espresso": "espresso", "visit": "visit",
            "correction": "correction"}.get(entry.get("entryType"), "cupping")


def visible_entries(user, entries):
    return [item for item in entries if item.get("entryType") not in ("visit", "correction")
            or has_permission(user, entry_permission(item))]


def validate_store_value(key, value):
    if key in (BLEND_CATALOG_KEY, PRODUCT_CATALOG_KEY):
        if not isinstance(value, dict):
            raise ValueError("목록 형식이 올바르지 않습니다.")
    elif not isinstance(value, list) or len(value) > 50000:
        raise ValueError("저장 데이터는 목록이어야 합니다.")
    if key not in (BLEND_CATALOG_KEY, PRODUCT_CATALOG_KEY) and any(not isinstance(item, dict) for item in value):
        raise ValueError("기록 형식이 올바르지 않습니다.")
    if key == ENTRIES_KEY:
        for item in value:
            if not isinstance(item.get("id"), str) or not item["id"]:
                raise ValueError("기록 ID가 필요합니다.")
            if not isinstance(item.get("entryType", ""), str):
                raise ValueError("잘못된 기록 종류입니다.")
    def check(item, field="", depth=0):
        if depth > 20:
            raise ValueError("데이터 구조가 너무 깊습니다.")
        if isinstance(item, dict):
            for name, child in item.items():
                check(child, name, depth + 1)
        elif isinstance(item, list):
            for child in item:
                check(child, field, depth + 1)
        elif isinstance(item, str):
            if len(item) > 20000 or re.search(r"<\s*/?\s*[a-zA-Z][^>]*>", item):
                raise ValueError("허용되지 않는 입력입니다.")
            if field == "id" and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", item):
                raise ValueError("잘못된 기록 ID입니다.")
            if field == "entryType" and item not in ("", "cupping", "roasting", "espresso", "visit", "correction"):
                raise ValueError("잘못된 기록 종류입니다.")
    check(value)


def merge_authorized_entries(user, previous, incoming):
    if is_primary_admin(user):
        return incoming
    old = {item["id"]: item for item in previous}
    new = {item["id"]: item for item in incoming}
    if len(new) != len(incoming):
        raise ValueError("중복 기록 ID입니다.")
    for identity, item in new.items():
        before = old.get(identity)
        if before == item:
            continue
        if before and before.get("entryType") == "roasting" and not has_permission(user, "roasting"):
            derived = {"verdict", "updatedAt", "issueLocked"}
            if {k: v for k, v in before.items() if k not in derived} == {k: v for k, v in item.items() if k not in derived}:
                # Verdicts are derived by the UI from authorized cupping/espresso records.
                new[identity] = before
                continue
        if not has_permission(user, entry_permission(item)) or (before and not has_permission(user, entry_permission(before))):
            raise AuthError("다른 페이지의 기록을 수정할 수 없습니다.")
    for identity, item in old.items():
        if identity not in new and item in visible_entries(user, [item]) and not has_permission(user, entry_permission(item)):
            raise AuthError("다른 페이지의 기록을 삭제할 수 없습니다.")
    hidden = [item for item in previous if item not in visible_entries(user, [item])]
    return list(new.values()) + [item for item in hidden if item["id"] not in new]


def read_users_from_store():
    store = read_store()
    users = store.get(USERS_KEY)
    return users if isinstance(users, list) else []


def write_users_to_store(users):
    write_store_key(USERS_KEY, users)


def find_user(users, user_id):
    normalized = normalize_user_id(user_id)
    return next((user for user in users if normalize_user_id(user.get("userId")) == normalized), None)


def issue_session(user):
    session = {
        "userId": user.get("id"),
        "version": user.get("sessionVersion", 0),
        "expiresAt": time.time() + SESSION_TTL_SECONDS,
    }
    payload = base64.urlsafe_b64encode(json.dumps(session, separators=(",", ":")).encode("utf-8")).decode("ascii").rstrip("=")
    signature = hmac.new(SESSION_SECRET.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def legacy_session_user_from_token(token):
    session = SESSIONS.get(token)
    if not session:
        return None
    if session.get("expiresAt", 0) < time.time():
        SESSIONS.pop(token, None)
        return None
    users = read_users_from_store()
    user = next((item for item in users if item.get("id") == session.get("userId")), None)
    if not user or user.get("status") != "approved":
        return None
    if session.get("version", 0) != user.get("sessionVersion", 0):
        return None
    return user


def session_user_from_token(token):
    if not token:
        return None
    if token in REVOKED_SESSIONS:
        return None
    if "." not in token:
        return legacy_session_user_from_token(token)
    payload, signature = token.rsplit(".", 1)
    if not payload.isascii() or len(token) > 4096:
        return None
    expected = hmac.new(SESSION_SECRET.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        padded = payload + ("=" * (-len(payload) % 4))
        session = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception:
        return None
    try:
        if float(session.get("expiresAt") or 0) < time.time():
            return None
    except (ValueError, TypeError):
        return None
    users = read_users_from_store()
    user = next((item for item in users if item.get("id") == session.get("userId")), None)
    if not user or user.get("status") != "approved":
        return None
    if session.get("version", 0) != user.get("sessionVersion", 0):
        return None
    return user


def apply_admin_guard(users):
    guarded = []
    for user in users:
        next_user = dict(user)
        if is_primary_admin(next_user):
            next_user["status"] = "approved"
            next_user["role"] = "admin"
            next_user["permissions"] = role_permissions("admin")
        elif normalize_role(next_user.get("role")) == "admin":
            next_user["role"] = "viewer"
            next_user["permissions"] = normalize_permissions(next_user)
        else:
            next_user["role"] = normalize_role(next_user.get("role"))
            next_user["permissions"] = normalize_permissions(next_user)
        guarded.append(next_user)
    return guarded


def merge_admin_user_updates(existing_users, incoming_users):
    by_id = {user.get("id"): user for user in existing_users if user.get("id")}
    next_users = []
    for incoming in incoming_users:
        existing = by_id.get(incoming.get("id"), {})
        merged = {**existing, **incoming}
        if incoming.get("password"):
            if not 8 <= len(str(incoming["password"])) <= 256:
                raise ValueError("비밀번호는 8자 이상이어야 합니다.")
            merged = hash_user_password(merged, incoming.get("password"))
            merged["passwordUpdatedAt"] = today_text()
        else:
            merged.pop("password", None)
            if existing.get("passwordHash"):
                merged["passwordHash"] = existing.get("passwordHash")
                merged["passwordSalt"] = existing.get("passwordSalt")
        merged["sessionVersion"] = existing.get("sessionVersion", 0) + (1 if incoming.get("password") else 0)
        next_users.append(merged)
    return apply_admin_guard(next_users)


class MiraArchiveHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        super().end_headers()

    def send_head(self):
        path = unquote(urlparse(self.path).path)
        name = path.removeprefix("/production_ai/")
        if path == "/":
            name = "mira_archive.html"
        if name not in PUBLIC_FILES or path not in ("/", "/" + name, "/production_ai/" + name):
            self.send_error(404)
            return None
        self.path = "/production_ai/" + name
        return super().send_head()

    def send_json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json_with_cookie(self, status, payload, token=None, clear_cookie=False):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if token:
            self.send_header(
                "Set-Cookie",
                f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_TTL_SECONDS}" + ("; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""),
            )
        if clear_cookie:
            self.send_header("Set-Cookie", f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_json_body(self):
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            raise ValueError("invalid origin")
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length < 0 or length > 8 * 1024 * 1024:
            raise ValueError("request too large")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            if not isinstance(value, dict):
                raise ValueError("invalid json")
            return value
        except Exception as error:
            raise ValueError("invalid json") from error

    def session_token(self):
        raw = self.headers.get("Cookie", "")
        jar = cookies.SimpleCookie()
        try:
            jar.load(raw)
        except cookies.CookieError:
            return ""
        morsel = jar.get(SESSION_COOKIE)
        return morsel.value if morsel else ""

    def current_user(self):
        return session_user_from_token(self.session_token())

    def require_user(self):
        user = self.current_user()
        if not user:
            raise AuthError("로그인이 필요합니다.")
        return user

    def require_admin(self):
        user = self.require_user()
        if not is_primary_admin(user):
            raise AuthError("관리자 권한이 필요합니다.")
        return user

    def handle_auth_get(self, path):
        try:
            if path == "/api/auth/me":
                user = self.current_user()
                self.send_json(200, {"user": sanitize_user(user) if user else None})
                return True
            if path == "/api/auth/users":
                self.require_admin()
                users = apply_admin_guard(read_users_from_store())
                self.send_json(200, {"users": [sanitize_user(user) for user in users]})
                return True
        except AuthError as error:
            self.send_json(403, {"error": str(error)})
            return True
        return False

    def handle_auth_post(self, path):
        try:
            payload = self.read_json_body()
        except ValueError:
            self.send_json(400, {"error": "invalid json"})
            return True
        try:
            if path == "/api/auth/login":
                user_id = normalize_user_id(payload.get("userId"))
                password = str(payload.get("password") or "")
                attempt_key = (self.client_address[0], user_id)
                failures, blocked_until = LOGIN_ATTEMPTS.get(attempt_key, (0, 0))
                if blocked_until > time.time():
                    self.send_json(429, {"error": "로그인 시도가 많습니다. 잠시 후 다시 시도해주세요."})
                    return True
                users = apply_admin_guard(read_users_from_store())
                user = find_user(users, user_id)
                if not user or not verify_password(user, password):
                    failures += 1
                    LOGIN_ATTEMPTS[attempt_key] = (failures, time.time() + 60 if failures >= 5 else 0)
                    self.send_json(403, {"error": "아이디 또는 비밀번호를 확인해주세요."})
                    return True
                LOGIN_ATTEMPTS.pop(attempt_key, None)
                if user.get("status") != "approved":
                    message = "아직 관리자 승인 대기 중입니다." if user.get("status") == "pending" else "승인이 거절된 사용자입니다."
                    self.send_json(403, {"error": message})
                    return True
                if not verify_password(user, password):
                    self.send_json(403, {"error": "비밀번호가 맞지 않습니다."})
                    return True
                if user.get("password") or not user.get("passwordHash"):
                    users = [hash_user_password(item, password) if item.get("id") == user.get("id") else item for item in users]
                    users = apply_admin_guard(users)
                    write_users_to_store(users)
                    user = find_user(users, user_id)
                token = issue_session(user)
                self.send_json_with_cookie(200, {"user": sanitize_user(user)}, token=token)
                return True
            if path == "/api/auth/signup":
                now = time.time()
                attempts = [stamp for stamp in SIGNUP_ATTEMPTS.get(self.client_address[0], []) if now - stamp < 3600]
                if len(attempts) >= 10:
                    self.send_json(429, {"error": "가입 요청이 많습니다. 나중에 다시 시도해주세요."})
                    return True
                SIGNUP_ATTEMPTS[self.client_address[0]] = attempts + [now]
                user_id = normalize_user_id(payload.get("userId"))
                password = str(payload.get("password") or "")
                name = str(payload.get("name") or "").strip()
                team = str(payload.get("team") or "").strip()
                if user_id == PRIMARY_ADMIN_USER_ID or not re.fullmatch(r"[a-z0-9_.-]{3,64}", user_id) or not name or len(name) > 100 or len(team) > 100:
                    self.send_json(400, {"error": "사용자 정보를 확인해주세요."})
                    return True
                if len(user_id) < 3:
                    self.send_json(400, {"error": "아이디는 3자 이상으로 입력하세요."})
                    return True
                if len(password) < 8 or len(password) > 256:
                    self.send_json(400, {"error": "비밀번호는 8자 이상 256자 이하로 입력하세요."})
                    return True
                users = apply_admin_guard(read_users_from_store())
                existing = find_user(users, user_id)
                if existing:
                    message = "이미 승인된 사용자입니다. 로그인 화면에서 로그인하세요." if existing.get("status") == "approved" else "이미 같은 아이디로 승인 대기 중입니다."
                    self.send_json(409, {"error": message})
                    return True
                user = hash_user_password({
                    "id": "user-" + secrets.token_hex(10),
                    "userId": user_id,
                    "name": name,
                    "team": team,
                    "status": "pending",
                    "role": "viewer",
                    "permissions": [],
                    "requestedAt": today_text(),
                }, password)
                write_users_to_store([user, *users])
                self.send_json(200, {"ok": True})
                return True
            if path == "/api/auth/logout":
                token = self.session_token()
                user = self.current_user()
                if user:
                    users = read_users_from_store()
                    write_users_to_store([{**item, "sessionVersion": item.get("sessionVersion", 0) + 1} if item.get("id") == user.get("id") else item for item in users])
                if token:
                    SESSIONS.pop(token, None)
                    REVOKED_SESSIONS[token] = time.time() + SESSION_TTL_SECONDS
                self.send_json_with_cookie(200, {"ok": True}, clear_cookie=True)
                return True
            if path == "/api/auth/password":
                user = self.require_user()
                users = apply_admin_guard(read_users_from_store())
                stored = next((item for item in users if item.get("id") == user.get("id")), None)
                if not stored or not verify_password(stored, payload.get("currentPassword") or ""):
                    self.send_json(403, {"error": "현재 비밀번호가 맞지 않습니다."})
                    return True
                next_password = str(payload.get("nextPassword") or "")
                if len(next_password) < 8 or len(next_password) > 256:
                    self.send_json(400, {"error": "새 비밀번호는 8자 이상 256자 이하로 입력하세요."})
                    return True
                users = [{**hash_user_password(item, next_password), "sessionVersion": item.get("sessionVersion", 0) + 1} if item.get("id") == stored.get("id") else item for item in users]
                write_users_to_store(apply_admin_guard(users))
                REVOKED_SESSIONS[self.session_token()] = time.time() + SESSION_TTL_SECONDS
                updated_user = next(item for item in users if item.get("id") == stored.get("id"))
                self.send_json_with_cookie(200, {"ok": True}, token=issue_session(updated_user))
                return True
        except (AuthError, StoreError) as error:
            self.send_json(403, {"error": str(error)})
            return True
        return False

    def handle_auth_put(self, path):
        if path != "/api/auth/users":
            return False
        try:
            self.require_admin()
            payload = self.read_json_body()
            incoming = payload.get("users")
            if not isinstance(incoming, list):
                self.send_json(400, {"error": "invalid users"})
                return True
            users = merge_admin_user_updates(read_users_from_store(), incoming)
            write_users_to_store(users)
            self.send_json(200, {"users": [sanitize_user(user) for user in users]})
        except ValueError:
            self.send_json(400, {"error": "invalid json"})
        except (AuthError, StoreError) as error:
            self.send_json(403, {"error": str(error)})
        return True

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/ping":
            self.send_json(200, {"ok": True, "store": store_status()})
            return
        if parsed.path.startswith("/api/auth/") and self.handle_auth_get(parsed.path):
            return
        if parsed.path.startswith("/api/store/"):
            key = unquote(parsed.path.removeprefix("/api/store/"))
            try:
                user = self.require_user()
                if not can_read_store_key(user, key):
                    self.send_json(403, {"error": "관리자 권한이 필요합니다."})
                    return
                store = read_store()
                value = store.get(key)
                if key == ENTRIES_KEY and isinstance(value, list):
                    value = visible_entries(user, value)
                if key == USERS_KEY and isinstance(value, list):
                    value = [sanitize_user(item) for item in apply_admin_guard(value)]
                self.send_json(200, {"value": value})
            except AuthError as error:
                self.send_json(401, {"error": str(error)})
            except StoreError as error:
                self.send_json(500, {"error": str(error)})
            return
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/auth/") and self.handle_auth_post(parsed.path):
            return
        self.send_json(404, {"error": "not found"})

    def do_PUT(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/auth/") and self.handle_auth_put(parsed.path):
            return
        if not parsed.path.startswith("/api/store/"):
            self.send_json(404, {"error": "not found"})
            return
        key = unquote(parsed.path.removeprefix("/api/store/"))
        try:
            user = self.require_user()
        except AuthError as error:
            self.send_json(401, {"error": str(error)})
            return
        if not can_write_store_key(user, key):
            self.send_json(403, {"error": "해당 저장소를 수정할 권한이 없습니다."})
            return
        try:
            payload = self.read_json_body()
        except ValueError:
            self.send_json(400, {"error": "invalid json"})
            return
        try:
            store = read_store()
            value = payload.get("value")
            validate_store_value(key, value)
            if key == ENTRIES_KEY:
                if any(not isinstance(item, dict) or not item.get("id") for item in value):
                    raise ValueError("기록 ID가 필요합니다.")
                value = merge_authorized_entries(user, store.get(key) or [], value)
            store[key] = value
            write_store_key(key, value)
            self.send_json(200, {"ok": True})
        except ValueError as error:
            self.send_json(400, {"error": str(error)})
        except AuthError as error:
            self.send_json(403, {"error": str(error)})
        except StoreError as error:
            self.send_json(500, {"error": str(error)})


if __name__ == "__main__":
    server = ThreadingHTTPServer((os.environ.get("MIRA_BIND_HOST", "0.0.0.0" if STORE_PROVIDER == "supabase" else "127.0.0.1"), PORT), MiraArchiveHandler)
    print(f"Fritz QC Archive server: http://127.0.0.1:{PORT}/production_ai/mira_archive.html")
    print(f"Store provider: {STORE_PROVIDER}")
    print("Keep this window open while using the archive.")
    server.serve_forever()
