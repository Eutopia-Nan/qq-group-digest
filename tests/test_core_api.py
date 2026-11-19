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



class TopicManagement(CoreTestCase):
    """关注点页：群类型的新建、改名、删除，以及分类的改名、改说明、排序。"""

    def assert_unchanged_after(self, error_fn, error=core.DigestError):
        before = self.config.read_bytes()
        with self.assertRaises(error):
            error_fn()
        self.assertEqual(self.config.read_bytes(), before, "出错时不能改动 config.json")

    def categories(self, gtype="study"):
        return list(core.get_topics(core.load_config())[gtype]["categories"].items())

    def test_rename_category_keeps_position_and_description(self):
        before = self.categories()
        core.update_category(None, "study", "学习资料", new_name="资料")
        after = self.categories()
        self.assertEqual(after[2], ("资料", before[2][1]))
        self.assertEqual([k for k, _ in after[:2]], [k for k, _ in before[:2]])

    def test_change_description_and_order(self):
        core.update_category(None, "study", "竞赛与加分", description="  只要竞赛  ", order=0)
        self.assertEqual(self.categories()[0], ("竞赛与加分", "只要竞赛"))
        core.update_category(None, "study", "竞赛与加分", order=99)
        self.assertEqual(self.categories()[-1][0], "竞赛与加分")
        prompt = core.build_system_prompt(core.load_config(), "study")
        self.assertLess(prompt.index("考试与作业通知"), prompt.index("竞赛与加分"))

    def test_update_category_rejects_bad_input_without_touching_file(self):
        self.assert_unchanged_after(lambda: core.update_category(None, "study", "学习资料"))
        self.assert_unchanged_after(lambda: core.update_category(None, "study", "没有", description="x"))
        self.assert_unchanged_after(lambda: core.update_category(None, "study", "学习资料", new_name="  "))
        self.assert_unchanged_after(lambda: core.update_category(None, "study", "学习资料", new_name="其他有用"))
        self.assert_unchanged_after(lambda: core.update_category(None, "study", "学习资料", order=-1))
        self.assert_unchanged_after(lambda: core.update_category(None, "study", "学习资料", order=True))
        self.assert_unchanged_after(lambda: core.update_category(None, "study", "学习资料", description=3))
        self.assert_unchanged_after(lambda: core.update_category(None, "study", "学习资料", new_name="竞赛与加分"),
                                    core.ConflictError)

    def test_add_topic_generates_keys(self):
        cfg, key = core.add_topic(None, "求职群", "实习和校招信息")
        self.assertEqual(key, "custom_1")
        self.assertEqual(cfg["topics"]["custom_1"], {"label": "求职群", "focus": "实习和校招信息", "categories": {}})
        _, key = core.add_topic(None, "Jobs")
        self.assertEqual(key, "jobs")
        self.assertEqual(core.get_topics(core.load_config())["jobs"]["focus"], core.NEW_TOPIC_FOCUS)
        _, key = core.add_topic(None, "另一个", key="mine")
        self.assertEqual(key, "mine")
        core.add_group(None, "456", "求职交流", "custom_1")

    def test_add_topic_rejects_bad_input_without_touching_file(self):
        self.assert_unchanged_after(lambda: core.add_topic(None, "  "))
        self.assert_unchanged_after(lambda: core.add_topic(None, "x" * 31))
        self.assert_unchanged_after(lambda: core.add_topic(None, "新类型", focus=""))
        self.assert_unchanged_after(lambda: core.add_topic(None, "新类型", key="带空格 的键"))
        self.assert_unchanged_after(lambda: core.add_topic(None, "学习群"), core.ConflictError)
        self.assert_unchanged_after(lambda: core.add_topic(None, "新类型", key="study"), core.ConflictError)

    def test_update_topic(self):
        core.update_topic(None, "study", label="期末冲刺群", focus="考试相关")
        topic = core.get_topics(core.load_config())["study"]
        self.assertEqual((topic["label"], topic["focus"]), ("期末冲刺群", "考试相关"))
        self.assertIn("考试与作业通知", topic["categories"], "改名时不能丢掉内置分类")
        self.assertIn("「期末冲刺群」", core.build_system_prompt(core.load_config(), "study"))
        core.update_topic(None, "study", label="期末冲刺群")  # 和自己同名不算冲突
        self.assert_unchanged_after(lambda: core.update_topic(None, "study"))
        self.assert_unchanged_after(lambda: core.update_topic(None, "study", focus=" "))
        self.assert_unchanged_after(lambda: core.update_topic(None, "nope", label="x"))
        self.assert_unchanged_after(lambda: core.update_topic(None, "study", label="技术/开源社区群"),
                                    core.ConflictError)

    def test_remove_topic_in_use_is_conflict(self):
        self.assert_unchanged_after(lambda: core.remove_topic(None, "study"), core.ConflictError)
        with self.assertRaisesRegex(core.ConflictError, "学习群"):
            core.remove_topic(None, "study")
        self.assert_unchanged_after(lambda: core.remove_topic(None, "nope"))

    def test_remove_builtin_topic_stays_removed(self):
        core.remove_topic(None, "opensource")
        self.assertEqual(self.read_config()["topics"]["opensource"], {"removed": True})
        cfg = core.load_config()
        self.assertNotIn("opensource", core.get_topics(cfg))
        self.assertFalse([i for i in core.validate_config(cfg) if i["level"] == "error"])
        self.assert_unchanged_after(lambda: core.add_group(None, "456", "x", "opensource"))
        self.assert_unchanged_after(lambda: core.update_topic(None, "opensource", label="x"))
        # 自动生成的键不会复用已删除的内置键
        _, key = core.add_topic(None, "opensource")
        self.assertEqual(key, "custom_1")

    def test_remove_custom_topic_and_keep_last_one(self):
        _, key = core.add_topic(None, "求职群")
        core.remove_topic(None, key)
        self.assertNotIn(key, self.read_config()["topics"])
        core.remove_topic(None, "opensource")
        core.remove_group(None, "123")
        self.assert_unchanged_after(lambda: core.remove_topic(None, "study"))

    def test_removed_builtin_topic_can_be_recreated_by_set_category(self):
        core.remove_topic(None, "opensource")
        core.set_category(None, "opensource", "新分类", "说明")
        topic = core.get_topics(core.load_config())["opensource"]
        self.assertEqual(topic["categories"], {"新分类": "说明"})
        self.assertEqual(topic["label"], "技术/开源社区群")

    def test_writes_keep_other_fields_and_chinese(self):
        cfg = self.read_config()
        cfg["my_note"] = "自己写的字段"
        self.write_config(cfg)
        core.add_topic(None, "求职群")
        text = self.config.read_text(encoding="utf-8")
        self.assertIn("求职群", text)
        self.assertIn("自己写的字段", text)


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

    def test_plan_gives_structured_notices(self):
        cfg = core.load_config()
        result = core.plan(cfg, None, {"mode": "hours", "hours": 0.25})
        notice = result["sources"][0]["notices"][0]
        self.assertEqual((notice["level"], notice["code"]), ("warn", "stale_export"))
        self.assertIn("2027-01-01 11:30", notice["detail"])
        self.assertEqual(len(result["sources"][0]["warnings"]), 1, "原来的 warnings 字符串保持不变")
        with (self.exports / "群_123_学习群.csv").open("a", encoding="utf-8", newline="") as stream:
            stream.write("坏时间,甲,内容\n")
        notices = core.plan(cfg, None, {"mode": "hours", "hours": 24})["sources"][0]["notices"]
        bad = next(n for n in notices if n["code"] == "bad_lines")
        self.assertIn("跳过了 1 处", bad["message"])
        self.assertIn("第 5 行", bad["detail"])

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
        self.assertEqual((reports[0]["groups"], reports[0]["period"]), ([], ""))
        (folder / "今日快报_b.md").write_text(
            "# 今日快报 2027-01-02\n\n## 学习群\n*2027-01-01 08:00:00 ~ 2027-01-02 08:00:00，共 3 条消息*\n\n"
            "### 学习资料\n\n---\n\n## 技术群\n*2027-01-01 08:00:00 ~ 2027-01-02 08:00:00，共 1 条消息*\n\n"
            "---\n\n## 未生成快报的来源\n\n- 坏群：出错了", encoding="utf-8")
        entry = next(r for r in core.list_reports(cfg) if r["name"] == "今日快报_b.md")
        self.assertEqual(entry["groups"], ["学习群", "技术群"])
        self.assertEqual(entry["period"], "2027-01-01 08:00:00 ~ 2027-01-02 08:00:00")
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

    def test_cancel_during_last_request_keeps_result_without_progress(self):
        """Codex 联调：只有一批时，在模型返回前取消 → 保留返回的结果，但不推进进度。"""
        self.write_export(123, "学习群", [("2027-01-01 11:00", "甲", "明天考高数")])
        cfg = core.load_config()
        cancel = threading.Event()
        real_post = self.fake_post

        def cancel_while_waiting(*args, **kwargs):
            cancel.set()  # 用户在请求进行中点了取消
            return real_post(*args, **kwargs)
        with patch.object(core, "http_post", cancel_while_waiting):
            outcome = core.run(cfg, core.plan(cfg), None, cancel)
        self.assertTrue(outcome["cancelled"])
        self.assertEqual((outcome["sources"][0]["status"], outcome["sources"][0]["items"]), ("ok", 1))
        report = Path(outcome["report_path"]).read_text(encoding="utf-8")
        self.assertIn("#### ★★★★ 标题", report)
        self.assertIn("处理进度没有推进", report)
        self.assertFalse((self.root / "state.json").exists(), "取消时不能推进进度")


class UiDefaults(CoreTestCase):
    """界面"保存为默认"（大纲第 4.1 节）。"""

    def test_missing_field_gives_fallback(self):
        self.assertEqual(core.get_defaults(core.load_config()),
                         {"selection": None, "window": {"mode": "since_last"}})

    def test_set_and_get(self):
        core.set_defaults(None, [], {"mode": "hours", "hours": "48"})
        self.assertEqual(core.get_defaults(core.load_config()),
                         {"selection": [], "window": {"mode": "hours", "hours": 48}})
        core.set_defaults(None, None, {"mode": "all"})
        self.assertIsNone(core.get_defaults(core.load_config())["selection"])

    def test_bad_input_does_not_touch_file(self):
        before = self.config.read_bytes()
        bad = (("group:123", {"mode": "all"}), (["group:123", "group:123"], {"mode": "all"}),
               (["123"], {"mode": "all"}), (["group:999"], {"mode": "all"}),
               (None, {"mode": "preset", "name": "monthly"}), (None, {"mode": "hours", "hours": 0}),
               (None, {"mode": "hours", "hours": 1e308}), (None, "daily"), (None, None))
        for selection, window in bad:
            with self.assertRaises(core.DigestError, msg=(selection, window)):
                core.set_defaults(None, selection, window)
        self.assertEqual(self.config.read_bytes(), before)

    def test_remove_group_prunes_selection(self):
        core.add_group(None, 456, "技术群", "opensource")
        core.set_defaults(None, ["group:123", "group:456"], {"mode": "since_last"})
        core.remove_group(None, 456)
        self.assertEqual(self.read_config()["ui_defaults"]["selection"], ["group:123"])

    def test_deleted_preset_falls_back_without_rewriting(self):
        """Codex 建议：保存的预设被删除后，恢复为"上次之后"，且不改写配置。"""
        cfg = self.read_config()
        cfg["presets"] = {"month": {"hours": 720}}
        cfg["ui_defaults"] = {"selection": ["group:123", "group:777"], "window": {"mode": "preset", "name": "month"}}
        self.write_config(cfg)
        self.assertEqual(core.get_defaults(core.load_config())["window"], {"mode": "preset", "name": "month"})
        del cfg["presets"]["month"]
        self.write_config(cfg)
        before = self.config.read_bytes()
        defaults = core.get_defaults(core.load_config())
        self.assertEqual(defaults, {"selection": ["group:123"], "window": {"mode": "since_last"}})
        self.assertEqual(self.config.read_bytes(), before)
        levels = {i["level"] for i in core.validate_config(cfg) if i["field"] == "ui_defaults"}
        self.assertEqual(levels, {"warning"}, "引用已删除的群或预设只给 warning，不阻止保存")

    def test_malformed_field_is_error_but_reading_still_works(self):
        cfg = self.read_config()
        cfg["ui_defaults"] = {"selection": "all", "window": []}
        self.assertTrue(any(i["field"] == "ui_defaults" and i["level"] == "error" for i in core.validate_config(cfg)))
        self.assertEqual(core.get_defaults(cfg), {"selection": None, "window": {"mode": "since_last"}})
        cfg["ui_defaults"] = "x"
        self.assertEqual(core.get_defaults(cfg)["selection"], None)

    def test_cli_ignores_ui_defaults(self):
        self.write_export(123, "学习群", [])
        core.set_defaults(None, [], {"mode": "preset", "name": "weekly"})
        cfg = core.load_config()
        self.assertEqual([j.key for j in core.collect_jobs(cfg)], ["group:123"])
        self.assertIsNone(core.resolve_window(cfg).hours)


if __name__ == "__main__":
    unittest.main()
