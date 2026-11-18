"""app.py（本地服务）的测试：启动真实服务，通过 HTTP 调用。AI 接口用假函数代替，不联网。"""

import csv
import datetime as dt
import http.client
import json
import tempfile
import threading
import time
import unittest
import urllib.parse
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import app
import digest_core as core


class Clock(dt.datetime):
    @classmethod
    def now(cls):
        return cls(2027, 1, 1, 12)


class AppTestCase(unittest.TestCase):
    KEY = "sk-real-secret-key-1234"

    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="app-test-", dir=Path.cwd())
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.config = self.root / "config.json"
        self.exports = self.root / "exports"
        self.exports.mkdir()
        self.ui = self.root / "ui"
        self.ui.mkdir()
        (self.ui / "index.html").write_text("<h1>界面</h1>", encoding="utf-8")
        (self.ui / "app.js").write_text("console.log(1)", encoding="utf-8")
        (self.root / "secret.txt").write_text("不应被读到", encoding="utf-8")
        self.config.write_text(json.dumps({
            "deepseek": {"base_url": "https://test.example.invalid/v1", "api_key": self.KEY},
            "profile": "测试用户", "export_dir": "exports", "open_report": False,
            "groups": [{"id": 123, "name": "学习群", "type": "study"}],
        }, ensure_ascii=False), encoding="utf-8")
        self.calls = []
        self.ai_gate = None
        patches = (
            patch.multiple(core, ROOT=self.root, CONFIG_PATH=self.config, STATE_PATH=self.root / "state.json",
                           REPORT_DIR=self.root / "reports", RAW_DIR=self.root / "raw",
                           dt=SimpleNamespace(datetime=Clock)),
            patch.object(core, "http_post", self.fake_post),
            patch.object(core.time, "sleep"),
            patch.object(app, "UI_DIR", self.ui),
        )
        for stub in patches:
            stub.start()
            self.addCleanup(stub.stop)
        self.server, self.token, self.url = app.create_server(0)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def fake_post(self, url, payload, headers, timeout):
        if self.ai_gate is not None:
            self.ai_gate.wait(5)
        self.calls.append(payload)
        content = payload["messages"][-1]["content"]
        ids = [l.split(" ", 1)[0] for l in content.splitlines() if l.startswith("M") and l.split(" ", 1)[0][1:].isdigit()]
        data = {"items": [{"title": "标题", "summary": "摘要", "category": "学习资料", "importance": 4,
                           "source_ids": ids[:1]}] if ids else [], "glossary": [], "overview": "概览"}
        return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(data, ensure_ascii=False)}}]}

    def write_export(self, gid, name, rows):
        with (self.exports / f"群_{gid}_{name}.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(("时间", "发送者", "内容"))
            writer.writerows(rows)

    def request(self, method, path, body=None, token=True, host=None, headers=None, raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        hdrs = {"Host": host or f"127.0.0.1:{self.port}"}
        if token:
            hdrs["X-Token"] = self.token if token is True else token
        if body is not None:
            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
            hdrs["Content-Type"] = "application/json"
        hdrs.update(headers or {})
        conn.request(method, path, body=raw, headers=hdrs)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        try:
            data = json.loads(data.decode("utf-8"))
        except ValueError:
            data = data.decode("utf-8", "replace")
        return resp.status, data, dict(resp.getheaders())

    def api(self, method, path, body=None, expect=200, **kw):
        status, data, _ = self.request(method, path, body, **kw)
        self.assertEqual(status, expect, data)
        return data


class Security(AppTestCase):
    def test_binds_localhost_and_url_carries_token(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.assertTrue(self.url.startswith(f"http://127.0.0.1:{self.port}/?token="))
        self.assertIn(self.token, self.url)

    def test_api_requires_correct_token(self):
        self.assertEqual(self.request("GET", "/api/status", token=False)[0], 403)
        self.assertEqual(self.request("GET", "/api/status", token="wrong")[0], 403)
        self.assertEqual(self.request("GET", "/api/status")[0], 200)

    def test_rejects_foreign_host_and_origin(self):
        """防 DNS 重绑定和其他网站冒充本页面。"""
        self.assertEqual(self.request("GET", "/api/status", host="evil.example:80")[0], 403)
        self.assertEqual(self.request("GET", "/", token=False, host=f"evil.example:{self.port}")[0], 403)
        self.assertEqual(self.request("POST", "/api/plan", {}, headers={"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.request("GET", "/api/status", host=f"localhost:{self.port}")[0], 200)

    def test_security_headers_on_every_response(self):
        for path, token in (("/", False), ("/api/status", True), ("/api/nope", True)):
            _, _, headers = self.request("GET", path, token=token)
            self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
            self.assertEqual(headers["Referrer-Policy"], "no-referrer")
            self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

    def test_static_files_cannot_escape_ui_dir(self):
        self.assertEqual(self.request("GET", "/app.js", token=False)[0], 200)
        for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/..%2fsecret.txt", "/../config.json"):
            status, body, _ = self.request("GET", path, token=False)
            self.assertEqual(status, 404, path)
            self.assertNotIn("不应被读到", str(body))

    def test_api_key_is_never_returned(self):
        for path in ("/api/config", "/api/status"):
            self.assertNotIn(self.KEY, json.dumps(self.api("GET", path), ensure_ascii=False))
        self.assertEqual(self.api("GET", "/api/config")["config"]["deepseek"]["api_key"], "••••1234")

    def test_body_limits(self):
        status, _, _ = self.request("POST", "/api/plan", raw=b"x", headers={"Content-Length": str(app.MAX_JSON_BYTES + 1)})
        self.assertEqual(status, 413)
        self.assertEqual(self.request("POST", "/api/plan", raw=b"[1]")[0], 400)
        self.assertEqual(self.request("POST", "/api/plan", raw=b"{bad")[0], 400)


class ConfigEndpoints(AppTestCase):
    def test_put_config_keeps_masked_key(self):
        view = self.api("GET", "/api/config")
        cfg = view["config"]
        cfg["profile"] = "新的个人情况"
        self.api("PUT", "/api/config", cfg)
        saved = json.loads(self.config.read_text(encoding="utf-8"))
        self.assertEqual(saved["deepseek"]["api_key"], self.KEY)
        self.assertEqual(saved["profile"], "新的个人情况")
        cfg["deepseek"]["api_key"] = "sk-brand-new-key-9999"
        self.api("PUT", "/api/config", cfg)
        self.assertEqual(json.loads(self.config.read_text(encoding="utf-8"))["deepseek"]["api_key"], "sk-brand-new-key-9999")

    def test_invalid_config_is_rejected_and_not_saved(self):
        before = self.config.read_bytes()
        cfg = self.api("GET", "/api/config")["config"]
        cfg["groups"][0]["type"] = "不存在"
        self.assertIn("未定义", self.api("PUT", "/api/config", cfg, expect=400)["error"])
        self.assertEqual(self.config.read_bytes(), before)
        issues = self.api("POST", "/api/config/validate", cfg)["issues"]
        self.assertTrue(any(i["level"] == "error" for i in issues))

    def test_status_and_test_connection(self):
        status = self.api("GET", "/api/status")
        self.assertEqual((status["version"], status["config_exists"], status["running_job"]), (app.VERSION, True, None))
        self.assertTrue(self.api("POST", "/api/test-connection")["ok"])


class FourOperations(AppTestCase):
    """主页四项高频操作对应的接口。"""

    def saved(self):
        return json.loads(self.config.read_text(encoding="utf-8"))

    def test_groups(self):
        view = self.api("POST", "/api/groups", {"group_id": "456", "name": "技术群", "type": "opensource"})
        self.assertEqual(len(view["config"]["groups"]), 2)
        self.api("PATCH", "/api/groups/456", {"type": "study"})
        self.assertEqual(self.saved()["groups"][1]["type"], "study")
        self.api("DELETE", "/api/groups/456")
        self.assertEqual([g["id"] for g in self.saved()["groups"]], [123])
        self.assertIn("已经添加过", self.api("POST", "/api/groups", {"group_id": "123", "name": "x", "type": "study"},
                                         expect=400)["error"])
        self.api("PATCH", "/api/groups/123", {"type": "nope"}, expect=400)

    def test_focus_and_categories(self):
        view = self.api("PUT", "/api/focus", {"profile": "大二学生", "explain_level": "brief"})
        self.assertEqual((view["config"]["profile"], view["explain_level"]), ("大二学生", "brief"))
        self.api("PUT", "/api/focus", {}, expect=400)
        name = urllib.parse.quote("时间/地点", safe="")
        view = self.api("PUT", f"/api/topics/study/categories/{name}", {"description": "考场安排"})
        self.assertEqual(view["topics"]["study"]["categories"]["时间/地点"], "考场安排")
        self.api("DELETE", f"/api/topics/study/categories/{urllib.parse.quote('竞赛与加分')}")
        self.assertNotIn("竞赛与加分", self.saved()["topics"]["study"]["categories"])


class SourcesPlanRun(AppTestCase):
    def setUp(self):
        super().setUp()
        self.write_export(123, "学习群", [("2027-01-01 11:00", "甲", "明天考高数")])

    def wait(self, job_id, until=("done", "failed", "cancelled")):
        for _ in range(200):
            job = self.api("GET", f"/api/jobs/{job_id}")
            if job["status"] in until:
                return job
            time.sleep(0.05)
        self.fail("任务没有结束")

    def test_sources_and_plan(self):
        sources = self.api("GET", "/api/sources")["sources"]
        self.assertEqual(sources[0]["status"], "ok")
        estimate = self.api("POST", "/api/plan", {"selection": ["group:123"], "window": {"mode": "hours", "hours": 24}})
        self.assertEqual(estimate["sources"][0]["pending"], 1)
        self.assertFalse(self.calls)

    def test_run_job_to_report(self):
        job_id = self.api("POST", "/api/run", {"window": {"mode": "preset", "name": "daily"}}, expect=202)["job_id"]
        job = self.wait(job_id)
        self.assertEqual(job["status"], "done", job)
        self.assertEqual(job["progress"]["total_batches"], 1)
        self.assertTrue(any(e["stage"] == "batch" for e in job["events"]))
        later = self.api("GET", f"/api/jobs/{job_id}?since={job['next_event']}")
        self.assertEqual(later["events"], [])
        reports = self.api("GET", "/api/reports")["reports"]
        self.assertEqual(len(reports), 1)
        report = self.api("GET", "/api/reports/" + urllib.parse.quote(reports[0]["name"]))
        self.assertIn("明天考高数", report["markdown"])
        self.api("GET", "/api/reports/" + urllib.parse.quote("../config.json"), expect=404)

    def test_one_job_at_a_time_and_cancel(self):
        self.ai_gate = threading.Event()
        job_id = self.api("POST", "/api/run", {}, expect=202)["job_id"]
        self.assertEqual(self.api("POST", "/api/run", {}, expect=409)["error"][:4], "已有任务")
        self.assertEqual(self.api("GET", "/api/status")["running_job"], job_id)
        self.api("POST", f"/api/jobs/{job_id}/cancel")
        self.ai_gate.set()
        self.assertIn(self.wait(job_id)["status"], ("cancelled", "done"))
        self.api("GET", "/api/jobs/unknown", expect=404)

    def test_failed_job_reports_error(self):
        cfg = json.loads(self.config.read_text(encoding="utf-8"))
        cfg["deepseek"] = {"api_key": "sk-xxx"}  # 官方接口但没有 Key
        self.config.write_text(json.dumps(cfg), encoding="utf-8")
        job = self.wait(self.api("POST", "/api/run", {}, expect=202)["job_id"])
        self.assertEqual(job["status"], "failed")
        self.assertIn("API Key", job["error"])


class Import(AppTestCase):
    def upload(self, filename, content, query="", expect=200):
        return self.api("POST", "/api/import" + query, raw=content.encode("utf-8"), expect=expect,
                        headers={"X-Filename": urllib.parse.quote(filename), "Content-Type": "application/octet-stream"})

    def test_import_named_export(self):
        result = self.upload("群_456_技术群.csv", "时间,发送者,内容\n")
        self.assertEqual(result["saved"], "群_456_技术群.csv")
        self.assertTrue((self.exports / "群_456_技术群.csv").exists())
        self.assertIn("group:456", [s["key"] for s in result["sources"]])

    def test_import_other_names_needs_group(self):
        self.assertEqual(self.upload("聊天记录.txt", "x", expect=400)["field"], "group_id")
        result = self.upload("聊天记录.txt", "x", "?group_id=789&name=" + urllib.parse.quote("班级群"))
        self.assertEqual(result["saved"], "群_789_班级群.txt")

    def test_import_rejects_bad_files_and_traversal(self):
        self.upload("群_1_x.exe", "x", expect=400)
        self.upload("群_1_x.csv", "", expect=400)
        result = self.upload("../../群_1_逃逸.csv", "x")
        self.assertEqual(result["saved"], "群_1_逃逸.csv")
        self.assertTrue((self.exports / "群_1_逃逸.csv").exists())
        self.assertFalse((self.root.parent / "群_1_逃逸.csv").exists())
        self.assertEqual([p.name for p in self.exports.iterdir() if p.name.endswith(".part")], [])


if __name__ == "__main__":
    unittest.main()
