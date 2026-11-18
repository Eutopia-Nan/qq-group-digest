"""
QQ 群聊 AI 筛选器（命令行）
- 读取用户自行导出的群聊记录文件（CSV / TXT，格式见 README）
- 增量处理尚未出现在快报中的消息，用 DeepSeek 按你的需求筛选，输出 Markdown 报告

用法:
  python digest.py                 处理 config.json 里所有群（默认从上次运行开始，首次 24 小时）
  python digest.py --hours 48      只看最近 48 小时
  python digest.py --dry-run       只筛出原文，不调用 AI（不花钱）
  python digest.py --group 123456789         只处理一个群
  python digest.py --file chat.txt --type study   处理手动复制的聊天记录

筛选偏好（群类型、分类、解释风格、个人画像）都在 config.json 里设置。
具体逻辑在 digest_core.py，本文件只负责解析参数和打印。
"""

import argparse
import os
import sys

import digest_core as core
from digest_core import DigestError


def hours_argument(value):
    try:
        return core.positive_hours(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def print_event(event):
    print(event["message"], file=sys.stderr if event["level"] == "error" else sys.stdout)


def open_report(cfg, path):
    if os.name == "nt" and cfg.get("open_report", True):
        try:
            os.startfile(path)
        except OSError:
            print("[提醒] 无法自动打开报告，请从上面的路径手动打开。")


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="QQ 群聊 AI 筛选器")
    time_opts = ap.add_mutually_exclusive_group()
    time_opts.add_argument("--hours", type=hours_argument, help="只看最近 N 小时（增量首次默认 24 小时）")
    time_opts.add_argument("--all", action="store_true", help="处理全部历史，也允许没有时间的纯文本")
    ap.add_argument("--dry-run", action="store_true", help="只筛出原文存到 raw/，不调用 AI")
    source_opts = ap.add_mutually_exclusive_group()
    source_opts.add_argument("--group", help="只处理某一个群（群号）")
    source_opts.add_argument("--file", help="处理指定文件（如手动复制的聊天记录 txt）")
    ap.add_argument("--type", default="opensource", help="--file 模式下的群类型（config.json 的 topics 里定义的名字）")
    ap.add_argument("--encoding", help="输入文件编码（默认识别 UTF-8 和带 BOM 的 UTF-16，可指定 gb18030）")
    ap.add_argument("--preset", help="使用 config.json 里 presets 定义的预设，如 daily（24小时→今日快报）、weekly（一周→今周快报）")
    args = ap.parse_args()

    try:
        cfg = core.load_config(required=not (args.dry_run and args.file))
        window = core.resolve_window(cfg, preset=args.preset, hours=args.hours, all_=args.all, emit=print_event)
        selection = [f"group:{args.group}"] if args.group else None
        jobs = core.collect_jobs(cfg, selection=selection, file=args.file, file_type=args.type, emit=print_event)
        core.check_job_types(cfg, jobs)
        settings = None if args.dry_run else core.api_settings(cfg)
        outcome = core.run_digest(cfg, jobs, window, settings, dry_run=args.dry_run,
                                  encoding=args.encoding, emit=print_event)
        if outcome["report_path"]:
            open_report(cfg, outcome["report_path"])
        return int(bool(outcome["failures"]))
    except (DigestError, OSError) as e:
        print(f"[错误] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
