"""
qq-group-digest 图形界面的本地服务（GUI 阶段 2a）

    python app.py                 启动并自动打开浏览器
    python app.py --no-browser    只启动，打印网址
    python app.py --port 8790     固定端口（默认由系统分配空闲端口，避免冲突）

安全设计（见 docs/gui-plan.md 第 5 节）：
1. 只监听 127.0.0.1，默认端口由系统分配
2. 启动时生成随机 token，通过网址传给页面；所有 /api/ 请求必须带 X-Token 头；同时校验 Host 头
3. 所有响应带 CSP（只允许本服务自己的脚本/样式，禁止内联脚本）和 Referrer-Policy: no-referrer
4. 文件读写只限配置的目录
5. 日志和错误里不出现 API Key
"""

import argparse
import hmac
import json
import mimetypes
import re
import secrets
import sys
import threading
import time
import traceback
import urllib.parse
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import digest_core as core
from digest_core import DigestError

VERSION = "2.0.0-dev"
UI_DIR = Path(__file__).resolve().parent / "ui"
MAX_JSON_BYTES = 1024 * 1024
MAX_IMPORT_BYTES = 512 * 1024 * 1024
MAX_JOB_EVENTS = 500
DRAIN_LIMIT = 16 * 1024 * 1024
MASK = "••••"

SECURITY_HEADERS = {
    "Content-Security-Policy": ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                                "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; "
                                "form-action 'none'; frame-ancestors 'none'"),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Cache-Control": "no-store",
}

PLACEHOLDER_PAGE = """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>qq-group-digest</title>
<body><h1>qq-group-digest 本地服务已启动</h1><p>界面（ui/ 目录）还在开发中。接口可用，见 docs/gui-plan.md 第 5 节。</p></body></html>"""


class HttpError(Exception):
    def __init__(self, status, message, field=None):
        super().__init__(message)
        self.status, self.message, self.field = status, message, field


# ---------------------------------------------------------------- API Key 打码

def mask_key(key):
    if not isinstance(key, str) or not key.strip() or key.strip().startswith("sk-xxx"):
        return ""
    key = key.strip()
    return MASK + key[-4:] if len(key) > 8 else MASK


def masked_config(cfg):
    out = json.loads(json.dumps(cfg))
    ds = out.get("deepseek")
    if isinstance(ds, dict) and "api_key" in ds:
        ds["api_key"] = mask_key(ds["api_key"])
    return out


def restore_key(submitted, current):
    """界面提交回来的 Key 如果还是打码值（或空），就保留原来的 Key。"""
    ds = submitted.get("deepseek")
    if not isinstance(ds, dict):
        return submitted
    old = current.get("deepseek", {}).get("api_key", "") if isinstance(current.get("deepseek"), dict) else ""
    new = ds.get("api_key")
    if isinstance(new, str) and (new.startswith(MASK) or (not new.strip() and old)):
        if old:
            ds["api_key"] = old
        else:
            ds.pop("api_key", None)
    return submitted


def config_view(cfg):
    """GET /api/config 返回的内容：打码后的配置 + 界面需要的派生信息。"""
    view = {"config": masked_config(cfg), "issues": core.validate_config(cfg)}
    try:
        view["topics"] = core.get_topics(cfg)
    except DigestError:
        view["topics"] = core.DEFAULT_TOPICS
    try:
        view["explain_level"] = core.explain_level(cfg)
    except DigestError:
        view["explain_level"] = "custom"
    presets = cfg.get("presets", {}) if isinstance(cfg.get("presets"), dict) else {}
    view["presets"] = {name: {**core.DEFAULT_PRESETS.get(name, {}), **(value if isinstance(value, dict) else {})}
                       for name, value in {**core.DEFAULT_PRESETS, **presets}.items()}
    return view


def load_cfg():
    return core.load_json(core.CONFIG_PATH, {})


# ---------------------------------------------------------------- 后台任务

class Job:
    def __init__(self, job_id, request):
        self.id = job_id
        self.request = request
        self.status = "running"
        self.events = []
        self.dropped = 0
        self.result = None
        self.error = None
        self.started = time.time()
        self.finished = None
        self.cancel = threading.Event()
        self.total_batches = 0
        self.batches_started = 0
        self.current = None
        self.lock = threading.Lock()

    def add_event(self, event):
        with self.lock:
            if event.get("stage") == "batch":
                self.batches_started += 1
                self.current = event.get("source_key")
            self.events.append({**event, "time": time.time()})
            if len(self.events) > MAX_JOB_EVENTS:
                self.dropped += len(self.events) - MAX_JOB_EVENTS
                del self.events[:len(self.events) - MAX_JOB_EVENTS]

    def snapshot(self, since=0):
        with self.lock:
            first = self.dropped
            events = self.events[max(0, since - first):]
            return {"id": self.id, "status": self.status, "error": self.error, "result": self.result,
                    "started": self.started, "finished": self.finished,
                    "progress": {"batches_started": self.batches_started, "total_batches": self.total_batches,
                                 "current_source": self.current},
                    "events": events, "next_event": first + len(self.events)}


class JobManager:
    """同一时间只允许一个任务。"""

    def __init__(self):
        self.jobs = {}
        self.lock = threading.Lock()

    def running(self):
        with self.lock:
            return next((job for job in self.jobs.values() if job.status == "running"), None)

    def start(self, request):
        with self.lock:
            if any(job.status == "running" for job in self.jobs.values()):
                raise HttpError(409, "已有任务正在运行，请等它结束或先取消。")
            job = Job(uuid.uuid4().hex[:12], request)
            self.jobs[job.id] = job
        threading.Thread(target=self._work, args=(job,), daemon=True).start()
        return job

    def get(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
        if job is None:
            raise HttpError(404, "没有这个任务。")
        return job

    @staticmethod
    def _work(job):
        try:
            cfg = core.load_config()
            estimate = core.plan(cfg, job.request.get("selection"), job.request.get("window"))
            job.total_batches = estimate["total_batches"]
            outcome = core.run(cfg, estimate, job.add_event, job.cancel)
            job.result = outcome
            job.status = "cancelled" if outcome["cancelled"] else ("failed" if outcome["failures"] and not outcome["report_path"] else "done")
            if job.status == "failed":
                job.error = "；".join(f"{name}：{err}" for name, err in outcome["failures"])
        except DigestError as e:
            job.status, job.error = "failed", str(e)
        except Exception:  # 不把内部细节（可能含路径）暴露给界面，只记到控制台
            traceback.print_exc()
            job.status, job.error = "failed", "发生了意外错误，请查看启动窗口里的报错信息。"
        finally:
            job.finished = time.time()


# ---------------------------------------------------------------- 请求处理

def make_handler(token, port, jobs):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    allowed_origins = {f"http://{host}" for host in allowed_hosts}

    class Handler(BaseHTTPRequestHandler):
        server_version = "qq-group-digest"
        sys_version = ""
        timeout = 60  # 客户端卡住时不让线程一直等

        def log_message(self, fmt, *args):
            # 默认日志会打印带 token 的网址，这里只记录方法和不含查询参数的路径。
            path = urllib.parse.urlsplit(self.path).path
            sys.stderr.write(f"[{self.log_date_time_string()}] {self.command} {path} {args[1] if len(args) > 1 else ''}\n")

        # ---------- 响应 ----------
        def send(self, status, body, content_type="application/json; charset=utf-8"):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            elif isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for name, value in SECURITY_HEADERS.items():
                self.send_header(name, value)
            if getattr(self, "_close_header", False):
                self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def drain(self):
            """出错时请求体可能还没读。小的读掉丢弃；太大的直接关闭连接。
            否则 Windows 会重置连接，浏览器只能看到"网络错误"，看不到我们的中文提示。"""
            if self._consumed:
                return
            self._consumed = True
            value = self.headers.get("Content-Length") or "0"
            length = int(value) if value.isdigit() else 0
            if 0 < length <= DRAIN_LIMIT:
                try:
                    while length:
                        chunk = self.rfile.read(min(length, 65536))
                        if not chunk:
                            break
                        length -= len(chunk)
                except OSError:
                    self.close_connection = True
            elif length:
                self.close_connection = True

        def fail(self, status, message, field=None):
            self.drain()
            if self.close_connection:
                self._close_header = True
            body = {"error": message}
            if field:
                body["field"] = field
            self.send(status, body)

        # ---------- 校验 ----------
        def check_host(self):
            if self.headers.get("Host", "") not in allowed_hosts:
                raise HttpError(403, "请求来源无效。")

        def check_api(self):
            supplied = self.headers.get("X-Token", "")
            if not hmac.compare_digest(supplied.encode(), token.encode()):
                raise HttpError(403, "缺少或错误的访问令牌。请从启动窗口里打印的网址打开。")
            origin = self.headers.get("Origin")
            if origin is not None and origin not in allowed_origins:
                raise HttpError(403, "请求来源无效。")

        def content_length(self):
            value = self.headers.get("Content-Length") or "0"
            if not value.isdigit():
                raise HttpError(400, "请求头 Content-Length 无效。")
            return int(value)

        def json_body(self):
            length = self.content_length()
            if length > MAX_JSON_BYTES:
                self._consumed, self.close_connection = True, True
                raise HttpError(413, "请求内容太大。")
            self._consumed = True
            if not length:
                return {}
            try:
                data = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise HttpError(400, "请求内容不是有效的 JSON。") from None
            if not isinstance(data, dict):
                raise HttpError(400, "请求内容必须是 JSON 对象。")
            return data

        # ---------- 分发 ----------
        def do_GET(self):
            self.dispatch("GET")

        def do_HEAD(self):
            self.dispatch("GET")

        def do_POST(self):
            self.dispatch("POST")

        def do_PUT(self):
            self.dispatch("PUT")

        def do_PATCH(self):
            self.dispatch("PATCH")

        def do_DELETE(self):
            self.dispatch("DELETE")

        def dispatch(self, method):
            self._consumed = False
            self._close_header = False
            try:
                self.check_host()
                url = urllib.parse.urlsplit(self.path)
                path = urllib.parse.unquote(url.path)
                # 先按 / 拆分再逐段解码，分类名里含有编码后的 / 也不会被拆错
                segments = [urllib.parse.unquote(p) for p in url.path.split("/") if p]
                if not path.startswith("/api/"):
                    if method != "GET":
                        raise HttpError(405, "不支持这个操作。")
                    return self.static(path)
                self.check_api()
                query = urllib.parse.parse_qs(url.query)
                status, body = self.route(method, segments, query)
                self.send(status, body)
            except HttpError as e:
                self.fail(e.status, e.message, e.field)
            except DigestError as e:
                self.fail(400, str(e))
            except Exception:
                traceback.print_exc()
                self.fail(500, "发生了意外错误，请查看启动窗口里的报错信息。")

        def static(self, path):
            if path in ("", "/"):
                path = "/index.html"
            target = (UI_DIR / path.lstrip("/")).resolve()
            if path == "/index.html" and not target.exists():
                return self.send(200, PLACEHOLDER_PAGE, "text/html; charset=utf-8")
            if UI_DIR.resolve() not in target.parents or not target.is_file():
                raise HttpError(404, "没有这个页面。")
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
                content_type += "; charset=utf-8"
            self.send(200, target.read_bytes(), content_type)

        # ---------- 接口 ----------
        def route(self, method, segments, query):
            parts = segments[1:]  # 去掉 "api"
            head = parts[0] if parts else ""

            if method == "GET" and parts == ["status"]:
                cfg = load_cfg()
                issues = core.validate_config(cfg)
                running = jobs.running()
                return 200, {"version": VERSION, "config_exists": core.CONFIG_PATH.exists(),
                             "ready": not issues, "issues": issues,
                             "running_job": running.id if running else None}

            if head == "config":
                if method == "GET" and len(parts) == 1:
                    return 200, config_view(load_cfg())
                if method == "PUT" and len(parts) == 1:
                    cfg = restore_key(self.json_body(), load_cfg())
                    core.save_config(cfg)
                    return 200, config_view(cfg)
                if method == "POST" and parts == ["config", "validate"]:
                    cfg = restore_key(self.json_body(), load_cfg())
                    return 200, {"issues": core.validate_config(cfg)}

            if method == "POST" and parts == ["test-connection"]:
                body = self.json_body()
                cfg = restore_key(body, load_cfg()) if body else load_cfg()
                return 200, core.test_connection(cfg)

            # 四项高频操作
            if head == "groups":
                if method == "POST" and len(parts) == 1:
                    body = self.json_body()
                    return 200, config_view(core.add_group(None, body.get("group_id", ""), body.get("name", ""),
                                                           body.get("type", "")))
                if len(parts) == 2 and method == "DELETE":
                    return 200, config_view(core.remove_group(None, parts[1]))
                if len(parts) == 2 and method == "PATCH":
                    return 200, config_view(core.set_group_type(None, parts[1], self.json_body().get("type", "")))
            if method == "PUT" and parts == ["focus"]:
                body = self.json_body()
                if "profile" not in body and "explain_level" not in body:
                    raise HttpError(400, "请提供 profile 或 explain_level。")
                cfg = None
                if "profile" in body:
                    cfg = core.set_profile(None, body["profile"])
                if "explain_level" in body:
                    cfg = core.set_explain_level(None, body["explain_level"])
                return 200, config_view(cfg)
            if head == "topics" and len(parts) == 4 and parts[2] == "categories":
                gtype, name = parts[1], parts[3]
                if method == "PUT":
                    return 200, config_view(core.set_category(None, gtype, name, self.json_body().get("description", "")))
                if method == "DELETE":
                    return 200, config_view(core.remove_category(None, gtype, name))

            if method == "GET" and parts == ["sources"]:
                return 200, {"sources": core.scan_sources(load_cfg())}

            if method == "POST" and parts == ["plan"]:
                body = self.json_body()
                return 200, core.plan(core.load_config(), body.get("selection"), body.get("window"))

            if method == "POST" and parts == ["run"]:
                body = self.json_body()
                job = jobs.start({"selection": body.get("selection"), "window": body.get("window")})
                return 202, {"job_id": job.id}
            if head == "jobs" and len(parts) >= 2:
                job = jobs.get(parts[1])
                if method == "GET" and len(parts) == 2:
                    since = query.get("since", ["0"])[0]
                    return 200, job.snapshot(int(since) if since.isdigit() else 0)
                if method == "POST" and len(parts) == 3 and parts[2] == "cancel":
                    job.cancel.set()
                    return 200, {"ok": True}

            if method == "GET" and head == "reports":
                cfg = load_cfg()
                reports = core.list_reports(cfg)
                if len(parts) == 1:
                    return 200, {"reports": reports}
                if len(parts) == 2:
                    match = next((r for r in reports if r["name"] == parts[1]), None)
                    if match is None:
                        raise HttpError(404, "没有这份快报。")
                    return 200, {"name": match["name"], "title": match["title"],
                                 "markdown": core.read_report(cfg, match["path"])}

            if method == "POST" and parts == ["import"]:
                return 200, self.import_file(query)

            raise HttpError(404, "没有这个接口。")

        def import_file(self, query):
            """拖入导出文件：请求体是文件内容，文件名放在 X-Filename 头（URL 编码）。

            文件名形如 群_<群号>_<群名>.csv/.txt 时原样保存；否则需要在网址里带 group_id（和可选的 name），
            会保存为 群_<group_id>_<name>.<扩展名>，这样扫描时能按群号找到。
            """
            raw_name = urllib.parse.unquote(self.headers.get("X-Filename", "")).replace("\\", "/").split("/")[-1]
            suffix = Path(raw_name).suffix.lower()
            if suffix not in (".csv", ".txt"):
                raise HttpError(400, "只支持 .csv 或 .txt 格式的聊天记录。")
            if core.EXPORT_NAME.match(raw_name):
                filename = core.filename_label(Path(raw_name).stem) + suffix
            else:
                gid = query.get("group_id", [""])[0]
                if not re.fullmatch(r"[0-9]+", gid):
                    raise HttpError(400, "这个文件名里没有群号，请先选择它属于哪个群。", "group_id")
                name = query.get("name", [Path(raw_name).stem])[0]
                filename = f"群_{gid}_{core.filename_label(name)}{suffix}"
            length = self.content_length()
            if length <= 0:
                raise HttpError(400, "文件是空的。")
            if length > MAX_IMPORT_BYTES:
                raise HttpError(413, f"文件太大（上限 {MAX_IMPORT_BYTES // 1024 // 1024} MB）。")
            cfg = load_cfg()
            export_dir = core.path_from_root(core.text_setting(cfg, "export_dir", "") or core.default_export_dir())
            export_dir.mkdir(parents=True, exist_ok=True)
            target = export_dir / filename
            temp = export_dir / f".{filename}.{uuid.uuid4().hex[:8]}.part"
            self._consumed = True
            try:
                with temp.open("wb") as stream:
                    remaining = length
                    while remaining:
                        chunk = self.rfile.read(min(remaining, 1024 * 1024))
                        if not chunk:
                            raise HttpError(400, "上传中断了，请重试。")
                        stream.write(chunk)
                        remaining -= len(chunk)
                temp.replace(target)
            finally:
                temp.unlink(missing_ok=True)
            return {"saved": filename, "sources": core.scan_sources(cfg)}

    return Handler


# ---------------------------------------------------------------- 启动

def create_server(port=0):
    """创建服务（不启动）。返回 (server, token, url)。"""
    token = secrets.token_urlsafe(24)
    server = ThreadingHTTPServer(("127.0.0.1", port), BaseHTTPRequestHandler)
    actual = server.server_address[1]
    server.RequestHandlerClass = make_handler(token, actual, JobManager())
    server.daemon_threads = True
    return server, token, f"http://127.0.0.1:{actual}/?token={token}"


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="qq-group-digest 图形界面")
    ap.add_argument("--port", type=int, default=0, help="监听端口，默认由系统分配空闲端口")
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = ap.parse_args()
    try:
        server, _, url = create_server(args.port)
    except OSError as e:
        print(f"[错误] 无法启动本地服务：{e}", file=sys.stderr)
        return 1
    print("qq-group-digest 已启动。请在浏览器中打开（这个网址只对本机有效，不要分享给别人）：")
    print(url)
    print("关闭这个窗口即可退出。")
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, (url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
