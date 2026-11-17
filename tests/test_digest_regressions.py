import csv
import datetime as dt
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import digest


class Clock(dt.datetime):
    current = dt.datetime(2027, 1, 1, 12)

    @classmethod
    def now(cls):
        return cls.current


class DigestRegressions(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="digest-test-", dir=Path.cwd())
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.state = self.root / "state.json"
        self.reports = self.root / "reports"
        self.raw = self.root / "raw"
        self.config = self.root / "config.json"
        self.calls = []
        self.reply = None
        self.config.write_text(json.dumps({
            "open_report": False,
            "deepseek": {"base_url": "https://test.example.invalid/v1", "api_key": "test-only"},
        }), encoding="utf-8")
        Clock.current = dt.datetime(2027, 1, 1, 12)
        patches = (
            patch.multiple(digest, ROOT=self.root, CONFIG_PATH=self.config, STATE_PATH=self.state,
                           REPORT_DIR=self.reports, RAW_DIR=self.raw, dt=SimpleNamespace(datetime=Clock)),
            patch.object(digest, "http_post", self.fake_post),
            patch.object(digest.time, "sleep"),
        )
        for stub in patches:
            stub.start()
            self.addCleanup(stub.stop)

    def fake_post(self, url, payload, headers, timeout):
        self.calls.append((url, payload, headers))
        if isinstance(self.reply, Exception):
            raise self.reply
        if self.reply is not None:
            return self.reply
        ids = [line.split(" ", 1)[0] for line in payload["messages"][1]["content"].splitlines()
               if line.startswith("M") and line.split(" ", 1)[0][1:].isdigit()]
        content = {"items": [{"title": "通知", "summary": "没有新消息的同学也须签到", "category": "学习资料",
                              "importance": 4, "source_ids": ids, "sender": "虚构发言人", "quote": "虚构原文"}],
                   "glossary": [], "overview": "概览"}
        return self.response(content)

    @staticmethod
    def response(content, finish="stop"):
        return {"choices": [{"finish_reason": finish, "message": {"content": json.dumps(content)}}]}

    def write_csv(self, name, rows, encoding="utf-8", delimiter=","):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding=encoding, newline="") as stream:
            writer = csv.writer(stream, delimiter=delimiter)
            writer.writerow(("时间", "发送者", "内容"))
            writer.writerows(rows)
        return path

    def invoke(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", ["digest.py", *map(str, args)]), redirect_stdout(out), redirect_stderr(err):
            try:
                result = digest.main()
            except SystemExit as e:
                result = e.code
        return result, out.getvalue(), err.getvalue()

    def test_late_import_and_distinct_paths(self):
        first = ("2027-01-01 10:00", "甲", "FIRST")
        late = ("2027-01-01 11:00", "甲", "LATE")
        new = ("2027-01-01 12:30", "甲", "NEW")
        source = self.write_csv("a/chat.csv", [first])
        self.assertEqual(self.invoke("--file", source)[0], 0)
        Clock.current = dt.datetime(2027, 1, 1, 13)
        self.write_csv("a/chat.csv", [first, late, new])
        self.assertEqual(self.invoke("--file", source)[0], 0)
        request = self.calls[-1][1]["messages"][1]["content"]
        self.assertIn("LATE", request)
        self.assertIn("NEW", request)
        self.assertNotIn("FIRST", request)
        self.assertEqual(self.invoke("--file", source)[0], 0)
        self.assertEqual(len(self.calls), 2)
        other = self.write_csv("b/chat.csv", [first])
        self.assertEqual(self.invoke("--file", other)[0], 0)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(len(list(self.reports.glob("*.md"))), 3)

    def test_report_write_failure_leaves_progress_retryable(self):
        source = self.write_csv("chat.csv", [("2027-01-01 11:00", "甲", "test")])
        original = digest.atomic_write

        def fail_report(path, text):
            if path.suffix == ".md":
                raise PermissionError("mock write failure")
            return original(path, text)

        with patch.object(digest, "atomic_write", fail_report):
            self.assertEqual(self.invoke("--file", source)[0], 1)
        self.assertFalse(self.state.exists())
        self.assertEqual(self.invoke("--file", source)[0], 0)
        self.assertEqual(len(self.calls), 2)

    def test_legacy_state_migrates_and_replays_recent_records(self):
        self.state.write_text(json.dumps({"123": Clock.current.timestamp(), "file:chat": Clock.current.timestamp()}),
                              encoding="utf-8")
        config = json.loads(self.config.read_text(encoding="utf-8"))
        config.update(groups=[{"id": 123, "name": "高数: 周考", "type": "study"}], export_dir="exports")
        self.config.write_text(json.dumps(config), encoding="utf-8")
        self.write_csv("exports/群_123_考试.csv", [("2027-01-01 11:00", "甲", "NEW")])
        self.assertEqual(self.invoke()[0], 0)
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(state["version"], 2)
        self.assertTrue(state["sources"]["group:123"]["seen"])

    def test_invalid_or_truncated_model_result_never_advances(self):
        source = self.write_csv("chat.csv", [("2027-01-01 11:00", "甲", "test")])
        for answer, status in (([], "stop"), ({"items": [], "glossary": [], "overview": []}, "stop"),
                               ({"items": [], "glossary": [], "overview": ""}, "length")):
            with self.subTest(status=status, answer=answer):
                self.reply = self.response(answer, status)
                code, _, err = self.invoke("--file", source)
                self.assertEqual(code, 1)
                self.assertIn("第 1 批", err)
                self.assertFalse(self.state.exists())
                self.assertFalse(list(self.reports.glob("*.md")))

    def test_report_uses_actual_source_and_keeps_normal_summary(self):
        path = self.write_csv("chat.csv", [("2027-01-01 11:00", "甲", "原句 https://example.invalid/")])
        self.assertEqual(self.invoke("--file", path)[0], 0)
        report = next(self.reports.glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("没有新消息的同学也须签到", report)
        self.assertIn("甲: 「原句 https://example.invalid/」", report)
        self.assertNotIn("虚构", report)
        self.assertFalse(self.raw.exists())

    def test_credential_stays_with_provider_and_bad_request_is_not_retried(self):
        path = self.write_csv("chat.csv", [("2027-01-01 11:00", "甲", "test")])
        self.reply = urllib.error.HTTPError("https://test.example.invalid", 400, "mock", {}, io.BytesIO(b"unsupported format"))
        with patch.dict(os.environ, DEEPSEEK_API_KEY="dummy-official-key"):
            code, _, err = self.invoke("--file", path)
        self.assertEqual(code, 1)
        self.assertIn("deepseek.json_mode", err)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][2]["Authorization"], "Bearer test-only")

    def test_cross_year_window_encoding_and_presets(self):
        source = self.write_csv("chat.csv", [("2026-12-31 12:00:00", "甲", "BOUNDARY"),
                                             ("2026-12-31 11:59:59", "甲", "OUT"),
                                             ("2027-01-01 12:00:01", "甲", "FUTURE")], encoding="gbk", delimiter=";")
        dirty = self.invoke("--file", source, "--preset", "daily", "--dry-run")
        self.assertEqual(dirty[0], 1)
        self.assertIn("无法解码", dirty[2])
        self.assertEqual(self.invoke("--file", source, "--preset", "daily", "--dry-run", "--encoding", "gb18030")[0], 0)
        contents = next(self.raw.glob("*.txt")).read_text(encoding="utf-8")
        self.assertIn("BOUNDARY", contents)
        self.assertNotIn("OUT", contents)
        self.assertNotIn("FUTURE", contents)

    def test_unrecognized_text_requires_explicit_all(self):
        path = self.root / "chat.txt"
        path.write_text("没有时间的旧记录", encoding="utf-8")
        code, _, err = self.invoke("--file", path, "--hours", 24)
        self.assertEqual(code, 1)
        self.assertIn("--all", err)
        self.assertFalse(self.calls)
        self.assertEqual(self.invoke("--file", path, "--preset", "daily", "--all")[0], 0)

    def test_oversized_message_chunks_keep_identity(self):
        path = self.write_csv("chat.csv", [("2027-01-01 11:00", "甲", "测" * 45000)])
        self.assertEqual(self.invoke("--file", path, "--type", "study")[0], 0)
        self.assertEqual(len(self.calls), 2)
        for _, payload, _ in self.calls:
            user = payload["messages"][1]["content"]
            self.assertLessEqual(len(user), digest.CHUNK_CHARS)
            self.assertIn("M1 [2027-01-01 11:00:00] 甲: ", user)

    def test_failed_group_keeps_other_groups_report_and_checkpoint(self):
        cfg = json.loads(self.config.read_text(encoding="utf-8"))
        cfg.update(groups=[{"id": 123, "name": "第一组", "type": "study"},
                           {"id": 456, "name": "第二组", "type": "study"}], export_dir="exports")
        self.config.write_text(json.dumps(cfg), encoding="utf-8")
        for gid in (123, 456):
            self.write_csv(f"exports/群_{gid}_高数.csv", [("2027-01-01 11:00", "甲", f"作业 {gid}")])

        def fail_second(url, payload, headers, timeout):
            if "群名：第二组" in payload["messages"][1]["content"]:
                raise urllib.error.HTTPError(url, 400, "mock", {}, io.BytesIO(b"bad request"))
            return self.fake_post(url, payload, headers, timeout)

        with patch.object(digest, "http_post", fail_second):
            self.assertEqual(self.invoke()[0], 1)
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(list(state["sources"]), ["group:123"])
        report = next(self.reports.glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("未生成快报的来源", report)
        self.assertEqual(self.invoke()[0], 0)
        self.assertEqual(len(self.calls), 2)
        self.assertIn("群名：第二组", self.calls[-1][1]["messages"][1]["content"])

    def test_empty_and_nonstandard_export_inputs(self):
        for filename in ("blank.txt", "blank.csv"):
            path = self.root / filename
            path.write_bytes(b"\n  \n")
            code, out, _ = self.invoke("--file", path, "--hours", 24, "--dry-run")
            self.assertEqual(code, 0)
            self.assertIn("窗口内 0 条", out)
        path = self.write_csv("wide.csv", [("2027-01-01T12:00:00+08:00", "甲", "x" * 131073)], encoding="utf-16", delimiter="\t")
        code, out, _ = self.invoke("--file", path, "--all", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("窗口内 1 条", out)

    def test_classic_multiline_dates_are_not_senders_and_newest_file_wins(self):
        folder = self.root
        first = folder / "群_123_旧.txt"
        second = folder / "群_123_新.txt"
        first.touch()
        second.write_text("2027-01-01 11:00:00 张三(123456)\n考试时间如下\n"
                          "2027-01-01 11:00 高数考试开考\n携带学生证", encoding="utf-8")
        modified = second.stat().st_mtime
        os.utime(first, (modified - 120, modified - 120))
        self.assertEqual(digest.find_export(folder, 123), second)
        code, out, _ = self.invoke("--file", second, "--hours", 24, "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("窗口内 1 条", out)
        raw = next(self.raw.glob("*.txt")).read_text(encoding="utf-8")
        self.assertIn("2027-01-01 11:00 高数考试开考\n携带学生证", raw)


if __name__ == "__main__":
    unittest.main()
