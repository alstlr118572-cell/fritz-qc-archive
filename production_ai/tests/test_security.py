import importlib.util
import json
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import parse_qs


spec = importlib.util.spec_from_file_location("archive", Path(__file__).parents[1] / "mira_archive_server.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


class SecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        app.STORE_PROVIDER = "local"
        app.STORE_PATH = Path(cls.temp.name) / "store.json"
        app.MiraArchiveHandler.log_message = lambda *args: None
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app.MiraArchiveHandler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:" + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.temp.cleanup()

    def setUp(self):
        self.users = [app.hash_user_password({"id": "id-" + role, "userId": name, "role": role,
                     "status": "approved", "permissions": []}, "test-password-123")
                     for role, name in [("admin", app.PRIMARY_ADMIN_USER_ID), ("cupper", "cupper"),
                                        ("account_manager", "manager"), ("viewer", "viewer")]]
        self.roast = {"id": "r1", "entryType": "roasting", "roastDate": "2026-10-20", "verdict": ""}
        self.visit = {"id": "v1", "entryType": "visit", "visitData": {"phone": "private"}}
        app.write_store({app.USERS_KEY: self.users, app.ENTRIES_KEY: [self.roast, self.visit]})
        app.LOGIN_ATTEMPTS.clear()
        app.SIGNUP_ATTEMPTS.clear()

    def request(self, method, path, value=None, cookie=None, headers=None):
        options = {"Content-Type": "application/json", **(headers or {})}
        if cookie:
            options["Cookie"] = cookie
        request = Request(self.base + path, method=method, headers=options,
                          data=json.dumps(value).encode() if value is not None else None)
        try:
            response = urlopen(request)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read()
            try:
                body = json.loads(raw)
            except ValueError:
                body = None
            return response.code, body, response.headers

    def cookie(self, role):
        user = next(user for user in self.users if user["role"] == role)
        return app.SESSION_COOKIE + "=" + app.issue_session(user)

    def test_static_allowlist_get_and_head(self):
        for path in ("/production_ai/mira_archive_server.py", "/production_ai/data/mira_archive_store.json",
                     "/operation_ai/.env", "/production_ai/docs/", "/production_ai/%2e%2e/operation_ai/.env"):
            for method in ("GET", "HEAD"):
                self.assertEqual(self.request(method, path)[0], 404)
        self.assertEqual(self.request("GET", "/production_ai/mira_archive.html")[0], 200)

    def test_read_and_write_permissions(self):
        viewer = self.cookie("viewer")
        for key in (app.MACHINE_DATA_KEY, app.GREEN_BEANS_KEY, app.CORRECTION_INDICATORS_KEY):
            self.assertEqual(self.request("GET", "/api/store/" + key, cookie=viewer)[0], 403)
        status, body, _ = self.request("GET", "/api/store/" + app.ENTRIES_KEY, cookie=viewer)
        self.assertEqual(status, 200)
        self.assertEqual(body["value"], [self.roast])
        self.assertEqual(self.request("PUT", "/api/store/" + app.MACHINE_DATA_KEY,
                                     {"value": [{"id": "m1"}]}, self.cookie("account_manager"))[0], 200)
        self.assertEqual(self.request("PUT", "/api/store/" + app.ENTRIES_KEY,
                                     {"value": []}, self.cookie("cupper"))[0], 403)

    def test_cupping_save_preserves_hidden_visit_and_roast(self):
        cup = {"id": "c1", "entryType": "cupping", "verdict": "pass"}
        derived = {**self.roast, "verdict": "pass"}
        self.assertEqual(self.request("PUT", "/api/store/" + app.ENTRIES_KEY,
                                     {"value": [derived, cup]}, self.cookie("cupper"))[0], 200)
        self.assertIn(self.visit, app.read_store()[app.ENTRIES_KEY])
        self.assertIn(self.roast, app.read_store()[app.ENTRIES_KEY])

    def test_bad_input_and_cross_origin(self):
        path = "/api/store/" + app.ENTRIES_KEY
        for value in ({"bad": True}, [{"id": '<img src=x onerror=alert(1)>'}]):
            self.assertEqual(self.request("PUT", path, {"value": value}, self.cookie("admin"))[0], 400)
        self.assertEqual(self.request("POST", "/api/auth/login", {}, headers={"Origin": "https://evil.example"})[0], 400)

    def test_cannot_change_another_page_record(self):
        changed = {**self.roast, "batch": "#999"}
        status, _, _ = self.request("PUT", "/api/store/" + app.ENTRIES_KEY,
                                   {"value": [changed]}, self.cookie("cupper"))
        self.assertEqual(status, 403)
        self.assertEqual(app.read_store()[app.ENTRIES_KEY], [self.roast, self.visit])

    def test_cookie_security_and_signature(self):
        status, _, headers = self.request("POST", "/api/auth/login", {
            "userId": "viewer", "password": "test-password-123"}, headers={"X-Forwarded-Proto": "https"})
        self.assertEqual(status, 200)
        for flag in ("HttpOnly", "Secure", "SameSite=Lax", "Max-Age=21600"):
            self.assertIn(flag, headers["Set-Cookie"])
        invalid = self.cookie("viewer") + "tampered"
        self.assertEqual(self.request("GET", "/api/store/" + app.ENTRIES_KEY, cookie=invalid)[0], 401)

    def test_login_rate_limit_and_reserved_signup(self):
        for _ in range(5):
            self.request("POST", "/api/auth/login", {"userId": "viewer", "password": "wrong"})
        self.assertEqual(self.request("POST", "/api/auth/login", {"userId": "viewer", "password": "wrong"})[0], 429)
        self.assertEqual(self.request("POST", "/api/auth/signup", {"userId": app.PRIMARY_ADMIN_USER_ID,
                         "password": "test-password-123", "name": "test", "team": "test"})[0], 400)

    def test_password_change_and_logout_revoke_session(self):
        old = self.cookie("viewer")
        status, _, headers = self.request("POST", "/api/auth/password", {
            "currentPassword": "test-password-123", "nextPassword": "new-test-password-123"}, old)
        self.assertEqual(status, 200)
        self.assertEqual(self.request("GET", "/api/store/" + app.ENTRIES_KEY, cookie=old)[0], 401)
        fresh = headers["Set-Cookie"].split(";")[0]
        self.assertEqual(self.request("POST", "/api/auth/logout", {}, fresh)[0], 200)
        self.assertEqual(self.request("GET", "/api/store/" + app.ENTRIES_KEY, cookie=fresh)[0], 401)

    def test_bootstrap_matches_permission_filtered_reads(self):
        self.assertEqual(self.request("GET", "/api/bootstrap")[0], 401)
        for role in ("admin", "cupper", "account_manager", "viewer"):
            cookie = self.cookie(role)
            status, body, _ = self.request("GET", "/api/bootstrap", cookie=cookie)
            self.assertEqual(status, 200)
            status, individual, _ = self.request("GET", "/api/store/" + app.ENTRIES_KEY, cookie=cookie)
            self.assertEqual(body["store"][app.ENTRIES_KEY], individual["value"])
            self.assertNotIn("passwordHash", json.dumps(body))
            self.assertNotIn(app.USERS_KEY, body["store"])
            if role != "admin":
                self.assertEqual(len(body["users"]), 1)
                self.assertNotIn(app.GREEN_BEANS_KEY, body["store"])
        app.write_store_key(app.MACHINE_DATA_KEY, [{"id": "m1"}])
        _, body, _ = self.request("GET", "/api/bootstrap", cookie=self.cookie("viewer"))
        self.assertNotIn(app.MACHINE_DATA_KEY, body["store"])
        _, body, _ = self.request("GET", "/api/bootstrap", cookie=self.cookie("account_manager"))
        self.assertEqual(body["store"][app.MACHINE_DATA_KEY], [{"id": "m1"}])

    def test_bootstrap_uses_two_filtered_database_reads(self):
        source = app.read_store()
        calls = []
        def database_request(path, method="GET", **kwargs):
            calls.append((path, method))
            selection = parse_qs(path.partition("?")[2])["key"][0]
            keys = selection[4:-1].split(",")
            return [{"key": key, "value": source[key]} for key in keys if key in source]
        with patch.object(app, "STORE_PROVIDER", "supabase"), patch.object(app, "supabase_request", database_request):
            status, body, _ = self.request("GET", "/api/bootstrap", cookie=self.cookie("viewer"))
        self.assertEqual(status, 200)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(method == "GET" for _, method in calls))
        self.assertIn(app.USERS_KEY, calls[0][0])
        self.assertNotIn(app.MACHINE_DATA_KEY, calls[1][0])
        self.assertEqual(body["store"][app.ENTRIES_KEY], [self.roast])

    def test_single_store_read_does_not_fetch_other_keys(self):
        calls = []
        with patch.object(app, "STORE_PROVIDER", "supabase"), patch.object(app, "supabase_request", lambda path: calls.append(path) or []):
            self.assertIsNone(app.read_store_key(app.BLEND_CATALOG_KEY))
        self.assertEqual(len(calls), 1)
        self.assertEqual(parse_qs(calls[0].partition("?")[2])["key"], ["in.(" + app.BLEND_CATALOG_KEY + ")"])


if __name__ == "__main__":
    unittest.main()
