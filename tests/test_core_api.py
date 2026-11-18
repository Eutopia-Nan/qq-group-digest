"""digest_core 新增接口的测试（GUI 阶段 1）。不联网：AI 接口用假函数代替。"""

import csv
import datetime as dt
import io
import json
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import digest_core as core


class Clock(dt.datetime):
    current = dt.datetime(2027, 1, 1, 12)

    @classmethod
    def now(cls):
        return cls.current


class CoreTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="core-test-", dir=Path.cwd())
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.config = self.root / "config.json"
        self.exports = self.root / "exports"
        self.exports.mkdir()
        self.calls = []
        self.write_config({
            "deepseek": {"base_url": "https://test.example.invalid/v1", "api_key": "secret-test-key"},
            "profile": "测试用户",
            "export_dir": "exports",
            "groups": [{"id": 123, "name": "学习群", "type": "study"}],
            "open_report": False,
        })
        Clock.current = dt.datetime(2027, 1, 1, 12)
        patches = (
            patch.multiple(core, ROOT=self.root, CONFIG_PATH=self.config, STATE_PATH=self.root / "state.json",
                           REPORT_DIR=self.root / "reports", RAW_DIR=self.root / "raw",
                           dt=SimpleNamespace(datetime=Clock)),
            patch.object(core, "http_post", self.fake_post),
            patch.object(core.time, "sleep"),
        )
        for stub in patches:
            stub.start()
            self.addCleanup(stub.stop)

    def write_config(self, cfg):
        self.config.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    def read_config(self):
        return json.loads(self.config.read_text(encoding="utf-8"))

    def write_export(self, gid, name, rows):
        path = self.exports / f"群_{gid}_{name}.csv"
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(("时间", "发送者", "内容"))
            writer.writerows(rows)
        return path

    def fake_post(self, url, payload, headers, timeout):
        self.calls.append((url, payload, headers))
        content = payload["messages"][-1]["content"]
        ids = [line.split(" ", 1)[0] for line in content.splitlines()
               if line.startswith("M") and line.split(" ", 1)[0][1:].isdigit()]
        data = {"items": [{"title": "标题", "summary": "摘要", "category": "学习资料", "importance": 4,
                           "source_ids": ids[:1]}] if ids else [],
                "glossary": [], "overview": "概览"}
        return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(data, ensure_ascii=False)}}]}


class FourOperations(CoreTestCase):
    """GUI 主页上的四项高频操作。"""

    def assert_unchanged_after(self, error_fn):
        before = self.config.read_bytes()
        with self.assertRaises(core.DigestError):
            error_fn()
        self.assertEqual(self.config.read_bytes(), before, "出错时不能改动 config.json")

    # 1. 修改指定群聊
    def test_add_and_remove_group(self):
        cfg = core.add_group(None, "456", " 技术群 ", "opensource")
        self.assertIn({"id": 456, "name": "技术群", "type": "opensource"}, cfg["groups"])
        self.assertEqual(self.read_config()["groups"], cfg["groups"])
        cfg = core.remove_group(None, 123)
        self.assertEqual([g["id"] for g in cfg["groups"]], [456])

    def test_add_group_rejects_bad_input_without_touching_file(self):
        self.assert_unchanged_after(lambda: core.add_group(None, "12a", "x", "study"))
        self.assert_unchanged_after(lambda: core.add_group(None, "123", "重复", "study"))
        self.assert_unchanged_after(lambda: core.add_group(None, "789", "   ", "study"))
        self.assert_unchanged_after(lambda: core.add_group(None, "789", "x", "不存在的类型"))
        self.assert_unchanged_after(lambda: core.remove_group(None, "999"))

    def test_first_run_without_config_file(self):
        self.config.unlink()
        cfg = core.add_group(None, 1, "第一个群", "study")
        self.assertEqual(cfg["groups"], [{"id": 1, "name": "第一个群", "type": "study"}])
        self.assertTrue(self.config.exists())

    # 2. 修改 type
    def test_set_group_type(self):
        core.set_group_type(None, "123", "opensource")
        self.assertEqual(self.read_config()["groups"][0]["type"], "opensource")
        self.assert_unchanged_after(lambda: core.set_group_type(None, "123", "nope"))
        self.assert_unchanged_after(lambda: core.set_group_type(None, "999", "study"))

    # 3. 修改聚焦的信息
    def test_set_profile(self):
        core.set_profile(None, "  大二计算机学生  ")
        self.assertEqual(self.read_config()["profile"], "大二计算机学生")

    def test_categories_for_builtin_type_are_really_removed(self):
        """修复：删除内置类型的分类后，不能被内置默认值悄悄加回来。"""
        core.remove_category(None, "study", "竞赛与加分")
        cfg = self.read_config()
        self.assertNotIn("竞赛与加分", cfg["topics"]["study"]["categories"])
        self.assertIn("学习资料", cfg["topics"]["study"]["categories"])
        prompt = core.build_system_prompt(core.load_config(), "study")
        self.assertNotIn("竞赛与加分", prompt)
        self.assertIn("学习资料", prompt)

    def test_set_category_and_new_type(self):
        core.set_category(None, "study", "学习资料", "只要真题")
        core.set_category(None, "class", "班级通知", "班会、收费、填表")
        topics = core.get_topics(core.load_config())
        self.assertEqual(topics["study"]["categories"]["学习资料"], "只要真题")
        self.assertEqual(topics["class"]["categories"], {"班级通知": "班会、收费、填表"})
        core.add_group(None, "456", "班级群", "class")
        self.assert_unchanged_after(lambda: core.set_category(None, "study", "其他有用", "x"))
        self.assert_unchanged_after(lambda: core.set_category(None, "study", "  ", "x"))
        self.assert_unchanged_after(lambda: core.remove_category(None, "study", "没有这个分类"))
        self.assert_unchanged_after(lambda: core.remove_category(None, "没有这个类型", "x"))

    def test_explain_level(self):
        self.assertEqual(core.explain_level(core.load_config()), "detailed")
        core.set_explain_level(None, "off")
        cfg = core.load_config()
        self.assertEqual(core.explain_level(cfg), "off")
        self.assertIn("glossary 返回空数组", core.build_system_prompt(cfg, "study"))
        core.set_explain_level(None, "brief")
        self.assertEqual(core.explain_level(core.load_config()), "brief")
        self.assert_unchanged_after(lambda: core.set_explain_level(None, "loud"))

    # 4. 回溯时间
    def test_set_preset_hours(self):
        core.set_preset_hours(None, "weekly", "72")
        self.assertEqual(self.read_config()["presets"]["weekly"], {"hours": 72})
        window = core.resolve_window(core.load_config(), preset="weekly")
        self.assertEqual((window.hours, window.title), (72, "今周快报"))
        self.assert_unchanged_after(lambda: core.set_preset_hours(None, "weekly", 0))
        self.assert_unchanged_after(lambda: core.set_preset_hours(None, "weekly", "abc"))
        self.assert_unchanged_after(lambda: core.set_preset_hours(None, "monthly", 24))


class ConfigValidation(CoreTestCase):
    def test_errors_and_warnings(self):
        issues = core.validate_config({"groups": [{"id": 1, "name": "x", "type": "nope"}], "open_report": "yes"})
        errors = {i["field"] for i in issues if i["level"] == "error"}
        self.assertEqual(errors, {"groups", "open_report"})
        warnings = {i["field"] for i in core.validate_config({}) if i["level"] == "warning"}
        self.assertEqual(warnings, {"deepseek", "profile", "groups"})

    def test_save_refuses_errors(self):
        before = self.config.read_bytes()
        with self.assertRaises(core.DigestError):
            core.save_config({"presets": {"daily": {"hours": -1}}})
        self.assertEqual(self.config.read_bytes(), before)
        core.save_config({"profile": "ok"})
        self.assertEqual(self.read_config(), {"profile": "ok"})


class Sources(CoreTestCase):
    def test_scan_marks_status_and_finds_unconfigured(self):
        cfg = core.load_config()
        cfg["groups"].append({"id": 456, "name": "坏类型", "type": "nope"})
        cfg["groups"].append({"id": 789, "name": "没导出", "type": "study"})
        self.write_export(123, "学习群", [])
        self.write_export(456, "坏类型", [])
        self.write_export(999, "新发现的群", [])
        by_key = {s["key"]: s for s in core.scan_sources(cfg)}
        self.assertEqual(by_key["group:123"]["status"], "ok")
        self.assertEqual(by_key["group:456"]["status"], "bad_type")
        self.assertEqual(by_key["group:789"]["status"], "missing")
        self.assertEqual((by_key["group:999"]["status"], by_key["group:999"]["name"], by_key["group:999"]["configured"]),
                         ("unconfigured", "新发现的群", False))


class PlanAndRun(CoreTestCase):
    def setUp(self):
        super().setUp()
        self.write_export(123, "学习群", [("2027-01-01 11:00", "甲", "明天考高数"),
                                          ("2027-01-01 11:30", "乙", "[图片]"),
                                          ("2026-12-01 11:00", "丙", "很久以前")])

    def test_plan_counts_without_side_effects(self):
        result = core.plan(core.load_config(), None, {"mode": "hours", "hours": 24})
        source = result["sources"][0]
        self.assertEqual((source["in_window"], source["pending"], source["batches"]), (2, 1, 1))
        self.assertEqual(result["total_batches"], 1)
        self.assertGreater(result["est_tokens"], 0)
        self.assertFalse(self.calls, "plan 不能调用 AI")
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["config.json", "exports"])

    def test_plan_rejects_bad_window(self):
        cfg = core.load_config()
        for spec in ({"mode": "hours", "hours": 0}, {"mode": "preset"}, {"mode": "weird"}):
            with self.assertRaises(core.DigestError):
                core.plan(cfg, None, spec)

    def test_run_writes_report_and_reports_progress(self):
        cfg = core.load_config()
        events = []
        outcome = core.run(cfg, core.plan(cfg, ["group:123"], {"mode": "since_last"}), events.append)
        self.assertTrue(Path(outcome["report_path"]).exists())
        self.assertEqual(outcome["sources"][0]["status"], "ok")
        batch = [e for e in events if e["stage"] == "batch"]
        self.assertEqual((batch[0]["batch"], batch[0]["total_batches"], batch[0]["source_key"]), (1, 1, "group:123"))
        self.assertTrue((self.root / "state.json").exists())

    def test_cancel_keeps_partial_report_but_not_progress(self):
        self.write_export(456, "技术群", [("2027-01-01 11:00", "丁", "新模型发布")])
        cfg = core.load_config()
        cfg["groups"].append({"id": 456, "name": "技术群", "type": "opensource"})
        cancel = threading.Event()

        def cancel_after_first(event):
            if event["stage"] == "batch":
                cancel.set()
        outcome = core.run(cfg, core.plan(cfg), cancel_after_first, cancel)
        self.assertTrue(outcome["cancelled"])
        self.assertEqual([s["status"] for s in outcome["sources"]], ["ok", "cancelled"])
        self.assertEqual(len(self.calls), 1)
        self.assertIn("已取消", Path(outcome["report_path"]).read_text(encoding="utf-8"))
        self.assertFalse((self.root / "state.json").exists(), "取消时不能推进进度")


class Reports(CoreTestCase):
    def test_list_and_read_only_inside_report_dirs(self):
        cfg = core.load_config()
        folder = self.root / "reports" / "今日快报"
        folder.mkdir(parents=True)
        (folder / "今日快报_a.md").write_text("# 今日快报 2027-01-01\n内容", encoding="utf-8")
        reports = core.list_reports(cfg)
        self.assertEqual([r["title"] for r in reports], ["今日快报 2027-01-01"])
        self.assertIn("内容", core.read_report(cfg, reports[0]["path"]))
        secret = self.root / "secret.md"
        secret.write_text("x", encoding="utf-8")
        for path in (secret, folder / ".." / ".." / "secret.md", self.config):
            with self.assertRaises(core.DigestError):
                core.read_report(cfg, path)


class Connection(CoreTestCase):
    def test_ok_and_failures_never_leak_key(self):
        cfg = core.load_config()
        self.assertTrue(core.test_connection(cfg)["ok"])
        payload = self.calls[-1][1]
        self.assertNotIn("response_format", payload)

        def unauthorized(url, payload, headers, timeout):
            raise urllib.error.HTTPError(url, 401, "x", {}, io.BytesIO(b"bad key secret-test-key"))
        with patch.object(core, "http_post", unauthorized):
            result = core.test_connection(cfg)
        self.assertFalse(result["ok"])
        self.assertIn("401", result["message"])
        self.assertNotIn("secret-test-key", result["message"])

        def offline(url, payload, headers, timeout):
            raise urllib.error.URLError("no route")
        with patch.object(core, "http_post", offline):
            self.assertIn("无法连接", core.test_connection(cfg)["message"])

    def test_missing_key_for_official_endpoint(self):
        result = core.test_connection({"deepseek": {"api_key": "sk-xxx（占位）"}})
        self.assertFalse(result["ok"])
        self.assertIn("API Key", result["message"])
        self.assertFalse(self.calls)


class ReviewRegressions(CoreTestCase):
    """Codex 审查阶段 1 时复现的 4 个问题。"""

    def test_cancel_keeps_batches_already_paid_for(self):
        """P1：单群分两批，第一批返回后取消 → 报告保留第一批，进度不推进。"""
        with (self.exports / "群_123_学习群.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(("时间", "发送者", "内容"))
            writer.writerow(("2027-01-01 11:00", "甲", "测" * 45000))
        cfg = core.load_config()
        cancel = threading.Event()
        outcome = core.run(cfg, core.plan(cfg), lambda e: cancel.set() if e["stage"] == "batch" else None, cancel)
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(outcome["cancelled"])
        self.assertEqual((outcome["sources"][0]["status"], outcome["sources"][0]["items"]), ("partial", 1))
        report = Path(outcome["report_path"]).read_text(encoding="utf-8")
        self.assertIn("#### ★★★★ 标题", report)
        self.assertIn("只分析了部分消息", report)
        self.assertFalse((self.root / "state.json").exists())

    def test_huge_lookback_rejected_on_save(self):
        """P2：超大回溯值不能写进配置。"""
        before = self.config.read_bytes()
        for hours in (1e308, core.MAX_HOURS + 1):
            with self.assertRaises(core.DigestError):
                core.set_preset_hours(None, "daily", hours)
        self.assertEqual(self.config.read_bytes(), before)
        with self.assertRaises(core.DigestError):
            core.plan(core.load_config(), None, {"mode": "hours", "hours": 1e308})
        cfg = core.load_config()
        cfg["presets"] = {"daily": {"hours": 1e308}}
        self.assertTrue(any(i["field"] == "presets" for i in core.validate_config(cfg)))
        core.set_preset_hours(None, "daily", core.MAX_HOURS)

    def test_wrong_argument_types_raise_digest_error(self):
        """P2：非法类型统一抛 DigestError，且不改写 config.json。"""
        before = self.config.read_bytes()
        bad_calls = (
            lambda: core.add_group(None, 456, 42, "study"),
            lambda: core.add_group(None, 456, "x", None),
            lambda: core.add_group(None, 4.5, "x", "study"),
            lambda: core.add_group(None, True, "x", "study"),
            lambda: core.set_group_type(None, 123, []),
            lambda: core.set_group_type(None, [123], "study"),
            lambda: core.set_profile(None, None),
            lambda: core.set_category(None, "study", 1, "x"),
            lambda: core.set_category(None, {}, "x", "x"),
            lambda: core.set_category(None, "study", "x", None),
            lambda: core.remove_category(None, "study", ["x"]),
            lambda: core.set_explain_level(None, ["off"]),
            lambda: core.set_preset_hours(None, ["daily"], 24),
        )
        for call in bad_calls:
            with self.assertRaises(core.DigestError):
                call()
        self.assertEqual(self.config.read_bytes(), before)

    def test_concurrent_saves_keep_both_changes(self):
        """P2：两个修改同时读到同一份配置再保存，两项改动都要保留。"""
        original = core.load_json
        barrier = threading.Barrier(2, timeout=1)

        def slow_load(path, default=None):
            data = original(path, default)
            if path == self.config:
                try:
                    barrier.wait()  # 没有锁时两个线程会在这里会合，读到同一份旧配置
                except threading.BrokenBarrierError:
                    pass
            return data
        with patch.object(core, "load_json", slow_load):
            threads = [threading.Thread(target=core.set_profile, args=(None, "新画像")),
                       threading.Thread(target=core.set_group_type, args=(None, 123, "opensource"))]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        cfg = self.read_config()
        self.assertEqual((cfg["profile"], cfg["groups"][0]["type"]), ("新画像", "opensource"))


if __name__ == "__main__":
    unittest.main()
