"""
发布版（exe）入口：启动本地服务，用 pywebview 打开一个桌面窗口。

- 窗口用的是系统自带的 WebView2（Windows 10/11 一般已安装）
- 没有 pywebview 或 WebView2 时，改用默认浏览器打开，并弹出提示框（里面有网址）；点"确定"即退出
- 源码版也可以直接运行：python desktop.py（需要 pip install pywebview，不装也能用浏览器模式）
"""

import os
import sys
import threading
import traceback
import webbrowser

import app

TITLE = "QQ群聊整理"


def message_box(text, error=False):
    """Windows 上用系统提示框（不依赖控制台，exe 没有黑窗口也能看到）；其他系统打印出来。"""
    if os.name == "nt":
        import ctypes
        flags = 0x10 if error else 0x40  # MB_ICONERROR / MB_ICONINFORMATION
        ctypes.windll.user32.MessageBoxW(None, text, TITLE, flags)
    else:
        print(text, file=sys.stderr if error else sys.stdout)


def webview2_ready():
    """pywebview 能否用 WebView2 打开窗口。

    pywebview 在 Windows 上找不到 WebView2 时会悄悄退回到旧的 IE 内核（mshtml），
    界面在 IE 内核里无法运行。它在导入 winforms 模块时就决定了用哪个内核，所以先导入再检查。
    """
    if os.name != "nt":
        return True
    try:
        from webview.platforms import winforms
    except Exception:
        return False
    return getattr(winforms, "renderer", None) == "edgechromium"


def open_window(url):
    """在桌面窗口里打开界面，阻塞到窗口关闭。窗口打不开时返回 False。"""
    try:
        import webview
    except ImportError:
        return False
    if not webview2_ready():
        return False
    try:
        webview.create_window(TITLE, url, width=1200, height=820, min_size=(900, 600))
        webview.start(gui="edgechromium" if os.name == "nt" else None)
        return True
    except Exception:
        return False


def browser_fallback(url):
    """没有独立窗口时：用默认浏览器打开，提示框关闭前服务一直运行。"""
    try:
        opened = webbrowser.open(url)
    except Exception:
        opened = False
    copy_tip = "（在这个提示框上按 Ctrl+C 可以复制全部文字。这个网址只在本机有效，不要分享给别人。）"
    if opened:
        message_box("已在浏览器中打开 QQ群聊整理。\n\n"
                    f"如果没有看到，请把下面的网址复制到浏览器地址栏：\n{url}\n{copy_tip}\n\n"
                    "使用期间请不要关闭这个提示框；用完点\"确定\"即可退出。\n"
                    "（这台电脑没有可用的 WebView2，所以没有打开独立窗口。）")
    else:
        message_box("没能自动打开浏览器。\n\n"
                    f"请把下面的网址复制到浏览器地址栏：\n{url}\n{copy_tip}\n\n"
                    "使用期间请不要关闭这个提示框；用完点\"确定\"即可退出。")


def main():
    # 没有控制台的 exe 里 stdout/stderr 可能是 None，写日志会出错：改为丢弃
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    try:
        server, _, url = app.create_server()
    except OSError as e:
        message_box(f"无法启动本地服务：{e}", error=True)
        return 1
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        if not open_window(url):
            browser_fallback(url)
    except Exception:
        message_box("程序出错了：\n\n" + traceback.format_exc(limit=3), error=True)
        return 1
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
