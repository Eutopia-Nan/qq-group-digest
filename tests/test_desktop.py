"""desktop.py 的启动回退逻辑（阶段 4，Codex 复现的问题）。不会真的打开窗口或浏览器。"""

import http.client
import os
import subprocess
import sys
import textwrap
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

import desktop

ROOT = Path(__file__).resolve().parent.parent

try:
    import webview  # noqa: F401
    HAS_WEBVIEW = True
except ImportError:
    HAS_WEBVIEW = False


class BrowserFallback(unittest.TestCase):
    def run_main(self, browser_opens):
        shown = []

        def fake_box(text, error=False):
            # 提示框还开着时，服务必须仍在运行
            url = urllib.parse.urlsplit(text[text.index("http://"):].split()[0])
            conn = http.client.HTTPConnection(url.hostname, url.port, timeout=5)
            conn.request("GET", "/", headers={"Host": url.netloc})
            shown.append((text, error, conn.getresponse().status))
            conn.close()
        with patch.object(desktop, "open_window", return_value=False), \
                patch.object(desktop.webbrowser, "open", return_value=browser_opens) as browser, \
                patch.object(desktop, "message_box", fake_box):
            self.assertEqual(desktop.main(), 0)
        browser.assert_called_once()
        self.assertEqual(len(shown), 1)
        return shown[0]

    def test_browser_failure_says_so_and_gives_the_address(self):
        """Codex P2：webbrowser.open() 返回 False 时，不能说"已打开"，要给出网址。"""
        text, error, status = self.run_main(browser_opens=False)
        self.assertIn("没能自动打开浏览器", text)
        self.assertNotIn("已在浏览器中打开", text)
        self.assertRegex(text, r"http://127\.0\.0\.1:\d+/\?token=\S+")
        self.assertEqual(status, 200)

    def test_browser_success_still_shows_the_address(self):
        text, error, status = self.run_main(browser_opens=True)
        self.assertIn("已在浏览器中打开", text)
        self.assertRegex(text, r"http://127\.0\.0\.1:\d+/\?token=\S+")
        self.assertEqual(status, 200)


@unittest.skipUnless(os.name == "nt" and HAS_WEBVIEW, "需要 Windows 和 pywebview（打包环境）")
class WebView2Detection(unittest.TestCase):
    def probe(self, hide_webview2):
        """在子进程里检查：pywebview 一旦导入就固定了内核，不能在本进程里反复模拟。"""
        code = textwrap.dedent(f"""
            import sys, winreg
            sys.path.insert(0, {str(ROOT)!r})
            if {hide_webview2!r}:
                original = winreg.OpenKey
                def fake(key, sub_key, *args, **kwargs):
                    if "EdgeUpdate" in sub_key:
                        raise OSError("模拟：没有安装 WebView2")
                    return original(key, sub_key, *args, **kwargs)
                winreg.OpenKey = fake
            import desktop
            from unittest.mock import patch
            with patch("webview.create_window") as create, patch("webview.start") as start:
                opened = desktop.open_window("http://127.0.0.1:1/")
            print(desktop.webview2_ready(), opened, create.called, start.called)
        """)
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.split()

    def test_missing_webview2_falls_back_instead_of_using_ie(self):
        """Codex P2：没有 WebView2 时 pywebview 会选 mshtml，这时要改用浏览器，不能开窗口。"""
        self.assertEqual(self.probe(hide_webview2=True), ["False", "False", "False", "False"])

    def test_webview2_present_opens_window(self):
        self.assertEqual(self.probe(hide_webview2=False), ["True", "True", "True", "True"])


if __name__ == "__main__":
    unittest.main()
