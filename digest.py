"""
QQ 群聊 AI 筛选器
- 读取用户自行导出的群聊记录文件（CSV / TXT，格式见 README）
- 只取上次运行之后的新消息，用 DeepSeek 按你的个人需求筛选，输出 Markdown 报告

用法:
  python digest.py                 处理 config.json 里所有群（默认从上次运行开始，首次 24 小时）
  python digest.py --hours 48      只看最近 48 小时
  python digest.py --dry-run       只筛出原文，不调用 AI（不花钱）
  python digest.py --group 123456789         只处理一个群
  python digest.py --file chat.txt --type study   处理手动复制的聊天记录

筛选偏好（群类型、分类、解释风格、个人画像）都在 config.json 里设置。
"""

import argparse
import csv
import io
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state.json"
REPORT_DIR = ROOT / "reports"
RAW_DIR = ROOT / "raw"

CHUNK_CHARS = 40000  # 每次发给 AI 的最大字符数
UNKNOWN_LIMIT = 20000  # 识别不出格式的文件超过这个字数时，需要 --all 才处理（防止误花钱）


# ---------------------------------------------------------------- 工具函数

def load_json(path, default=None):
    if not path.exists():
        return default
    text = path.read_text(encoding="utf-8-sig")  # 兼容记事本保存的带 BOM 的 UTF-8
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        line = text.splitlines()[e.lineno - 1] if e.lineno <= len(text.splitlines()) else ""
        sys.exit(f"[错误] {path.name} 第 {e.lineno} 行第 {e.colno} 列格式有误：{e.msg}\n"
                 f"  该行内容：{line.strip()}\n"
                 f"  常见原因：最后一项后面多了逗号、两项之间漏了逗号、用了中文引号或中文逗号、路径里的 \\ 没写成 \\\\ 或 /")


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def http_post(url, payload, headers=None, timeout=120):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------- 读取导出文件

_TS = r"\d{4}[-/]\d{1,2}[-/]\d{1,2} \d{1,2}:\d{2}(?::\d{2})?"
# 格式 A（单行）：[2026-11-17 14:03:00] 昵称: 内容    —— 冒号可以是中文"："
TS_LINE = re.compile(rf"^\[({_TS})\] ([^:：]*)[:：] ?(.*)$")
# 格式 B（标题行 + 内容行，经典版 QQ 消息管理器等）：
#   2026-11-17 14:03:00 昵称(123456)
#   内容……
TS_HEAD = re.compile(rf"^({_TS}) (.+?)\s*$")
CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# CSV 表头别名（不区分大小写）
CSV_COLS = {
    "time": ("时间", "日期", "time", "date", "datetime", "timestamp", "发送时间"),
    "who": ("发送者", "发送人", "昵称", "sender", "name", "nickname", "from", "user"),
    "text": ("内容", "消息", "消息内容", "content", "message", "text", "msg"),
}
# 整条消息只有这些标记时视为无用（图片、语音、空消息等）
NOISE = re.compile(r"^(\s*\[(无文本内容|图片|视频|语音|表情|文件|消息类型\d+|回复消息|动画表情)\]\s*)+$")


def parse_ts(s):
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            return dt.datetime.strptime(s, fmt).timestamp()
        except ValueError:
            continue
        except (OSError, OverflowError):  # 1970 年之类的损坏时间戳
            return 0.0
    return None


def load_messages(path):
    """读取导出文件 → [(时间戳, 发送者, 内容)]；无法识别格式（手动复制的文本）返回 None"""
    path = Path(path)
    raw = CTRL.sub("", path.read_text(encoding="utf-8-sig", errors="ignore"))
    msgs = []
    if path.suffix.lower() == ".csv":
        rows = csv.reader(io.StringIO(raw))
        header = [h.strip().lower() for h in next(rows, [])]

        def col(key):
            for name in CSV_COLS[key]:
                if name.lower() in header:
                    return header.index(name.lower())
            return None
        it, iw, ic = col("time"), col("who"), col("text")
        if it is None or ic is None:
            sys.exit(f"[错误] 无法识别 CSV 的表头：{header}\n"
                     f"  需要包含时间列（如 {'/'.join(CSV_COLS['time'][:4])}）和内容列（如 {'/'.join(CSV_COLS['text'][:4])}），"
                     f"发送者列（如 {'/'.join(CSV_COLS['who'][:4])}）可选。")
        for r in rows:
            if len(r) <= max(it, ic):
                continue
            ts = parse_ts(r[it])
            if ts is not None:
                who = r[iw].strip() if iw is not None and iw < len(r) else ""
                msgs.append((ts, who or "成员", r[ic]))
        return msgs
    lines = raw.splitlines()
    # 整个文件只用一种格式解析，避免把正文里以日期开头的句子误当成新消息
    pat = TS_LINE if any(TS_LINE.match(l) for l in lines[:2000]) else TS_HEAD
    for line in lines:
        m = pat.match(line)
        if m and parse_ts(m.group(1)) is not None:
            text = m.group(3) if pat is TS_LINE else ""
            who = m.group(2).strip()
            if pat is TS_HEAD:  # 去掉经典格式里昵称后面的 (QQ号) / <邮箱>
                who = re.sub(r"\s*[(（<][^()（）<>]*[)）>]$", "", who) or who
            msgs.append((parse_ts(m.group(1)), who, text))
            continue
        if msgs:  # 多行消息的后续行
            ts, who, text = msgs[-1]
            msgs[-1] = (ts, who, (text + "\n" + line) if text else line)
    return msgs or None


def format_messages(msgs):
    lines = []
    for ts, who, text in msgs:
        text = text.strip()
        if not text or NOISE.match(text):
            continue
        lines.append(f"[{dt.datetime.fromtimestamp(ts):%Y-%m-%d %H:%M}] {who}: {text}")
    return "\n".join(lines)


def default_export_dir():
    home = Path(os.environ.get("USERPROFILE", Path.home()))
    for d in (home / "Desktop", home / "OneDrive" / "Desktop", home / "OneDrive" / "桌面"):
        if (d / "QQ聊天记录导出").is_dir():
            return d / "QQ聊天记录导出"
    return home / "Desktop" / "QQ聊天记录导出"


def find_export(export_dir, gid):
    """按群号找最新的导出文件，优先 CSV（带发言人昵称）"""
    files = list(export_dir.glob(f"群_{gid}_*.csv")) + list(export_dir.glob(f"群_{gid}_*.txt"))
    if not files:
        return None
    newest = max(f.stat().st_mtime for f in files)
    fresh = [f for f in files if newest - f.stat().st_mtime < 600]  # 同一批导出的
    return sorted(fresh, key=lambda f: f.suffix.lower() != ".csv")[0]


# ---------------------------------------------------------------- DeepSeek

# 默认群类型。用户可在 config.json 的 "topics" 里覆盖或新增，无需改代码
DEFAULT_TOPICS = {
    "study": {
        "label": "学习群",
        "focus": "对提高成绩有帮助的信息",
        "categories": {
            "考试与作业通知": "考试时间/范围、作业截止、老师重点划分、课程调整",
            "提分方法与经验": "学长学姐经验、复习方法、答题技巧、避坑提醒",
            "学习资料": "真题、课件、笔记、网课、题库链接或文件",
            "竞赛与加分": "竞赛、保研/综测加分、证书、科研机会",
        },
    },
    "opensource": {
        "label": "技术/开源社区群",
        "focus": "对用户有用、有利益的信息",
        "categories": {
            "赚钱机会": "线上做题、AI 数据标注/评测、专家招募、众包、悬赏、兼职、可变现的项目。写清报酬、门槛、截止时间、链接/联系方式",
            "AI新动态": "新模型/新产品发布、行业方向、重要论文或趋势",
            "模型讨论": "群友对各个大模型的使用体验、对比、价格、优缺点评价。概括大家的观点，注意分歧",
            "开源知识": "开源项目推荐、工具、如何参与开源、实用技术技巧",
            "与我相关": "根据用户画像，适合用户的实习、竞赛、学习路线、免费资源等",
        },
    },
}

DEFAULT_EXPLAIN = "用户是零基础，用通俗大白话 + 生活类比解释清楚（2-4 句）"


def get_topics(cfg):
    return cfg.get("topics") or DEFAULT_TOPICS


def build_system_prompt(cfg, gtype):
    topics = get_topics(cfg)
    if gtype not in topics:
        sys.exit(f"[错误] 群类型 {gtype!r} 未定义。config.json 的 topics 里可用的有：{', '.join(topics)}")
    t = topics[gtype]
    cats = dict(t.get("categories") or {})
    cats.setdefault("其他有用", "确实有价值但不属于以上分类的")
    cat_lines = "\n".join(f'- "{k}"：{v}' for k, v in cats.items())
    explain = cfg.get("explain_style", DEFAULT_EXPLAIN)
    if explain:
        explain_rule = (f"3. explain 字段：{explain}。仅在这条信息涉及专业术语或概念时填写，否则留空字符串。\n"
                        f"4. glossary：聊天中出现的、用户可能看不懂的重要术语（最多 8 个），按同样的风格解释。")
    else:
        explain_rule = "3. explain 字段留空字符串。\n4. glossary 返回空数组。"
    return f"""你是一个帮用户筛选群聊消息的助手。这个群是「{t.get('label', gtype)}」。从群聊记录中只挑出{t.get('focus', '对用户有用的信息')}，忽略闲聊、表情、刷屏、无意义争论。

关注的分类（category 只能取以下之一）：
{cat_lines}

用户画像：{cfg.get('profile', '（未填写）')}

要求：
1. 只保留真正有用的信息，宁缺毋滥。同一件事的多条消息合并成一条。结合用户画像判断什么对用户有用。
2. importance 取 1-5，5 = 必须马上看/有截止时间/与用户利益直接相关。
{explain_rule}
5. quote 摘录最关键的原话（不超过 80 字），links 收集相关链接。
6. 如果是机会类信息（兼职、招募、竞赛、实习等），在 eligibility 字段根据用户画像判断用户能否参与及原因；其他信息留空。
7. 不要编造聊天中没有的信息。

只输出 JSON，格式如下：
{{
  "items": [
    {{
      "category": "分类名",
      "importance": 1-5,
      "title": "一句话标题",
      "summary": "具体内容摘要（报酬/时间/要求等关键信息）",
      "eligibility": "机会类信息填写：用户能否参与及原因，其余留空",
      "explain": "解释，可为空",
      "quote": "关键原话",
      "sender": "发送人",
      "time": "消息日期时间，照抄聊天记录里的格式 YYYY-MM-DD HH:MM；多条消息合并时写最早~最晚",
      "links": ["..."]
    }}
  ],
  "glossary": [{{"term": "术语", "explain": "解释"}}],
  "overview": "这段时间群里整体在聊什么，2-3 句"
}}"""


def parse_ai_json(content):
    """容错解析：兼容 ```json 代码块包裹、前后多余文字等不规范回复"""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")
        if start != -1 and end > start:
            return json.loads(content[start:end + 1])
        raise


def call_deepseek(cfg, system, user):
    ds = cfg.get("deepseek", {})
    base = ds.get("base_url", "https://api.deepseek.com").rstrip("/")
    key = os.environ.get("DEEPSEEK_API_KEY") or ds.get("api_key", "")
    if not key or key.startswith("sk-xxx"):
        if "deepseek.com" in base:
            sys.exit("[错误] 未设置 API Key：请在 config.json 的 deepseek.api_key 填写，或设置环境变量 DEEPSEEK_API_KEY")
        key = "none"  # 本地模型（如 Ollama）不需要 Key
    payload = {
        "model": ds.get("model", "deepseek-chat"),
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_object"},
        "temperature": 0.3,
    }
    url = base + "/chat/completions"
    for attempt in range(3):
        try:
            r = http_post(url, payload, {"Authorization": f"Bearer {key}"}, timeout=300)
            data = parse_ai_json(r["choices"][0]["message"]["content"])
            return data if isinstance(data, dict) else {}
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")
            if e.code == 401:
                sys.exit(f"[错误] AI 接口返回 401：API Key 错误，请检查 config.json。{body[:200]}")
            if e.code == 402:
                sys.exit(f"[错误] AI 接口返回 402：账户余额不足，请先充值。{body[:200]}")
            print(f"  AI 接口出错 {e.code}，重试中... {body[:200]}")
        except urllib.error.URLError as e:
            print(f"  连不上 AI 接口 {url}：{e.reason}，重试中...")
        except Exception as e:
            print(f"  AI 返回结果解析失败：{e}，重试中...")
        time.sleep(3 * (attempt + 1))
    sys.exit("[错误] AI 接口连续 3 次失败，请检查网络、base_url 和 model 设置。")


def chunk_text(text, size=CHUNK_CHARS):
    lines, chunks, cur, n = text.split("\n"), [], [], 0
    for line in lines:
        if n + len(line) > size and cur:
            chunks.append("\n".join(cur))
            cur, n = [], 0
        cur.append(line)
        n += len(line) + 1
    if cur:
        chunks.append("\n".join(cur))
    return chunks


def analyze(cfg, group_name, gtype, text):
    system = build_system_prompt(cfg, gtype)
    chunks = chunk_text(text)
    result = {"items": [], "glossary": [], "overview": []}
    for i, chunk in enumerate(chunks, 1):
        print(f"  AI 分析中 ({i}/{len(chunks)})，{len(chunk)} 字...")
        r = call_deepseek(cfg, system, f"群名：{group_name}\n\n聊天记录：\n{chunk}")
        items = r.get("items")
        result["items"] += [x for x in items if isinstance(x, dict)] if isinstance(items, list) else []
        gloss = r.get("glossary")
        result["glossary"] += [x for x in gloss if isinstance(x, dict)] if isinstance(gloss, list) else []
        if r.get("overview"):
            result["overview"].append(r["overview"])
    # 术语去重
    seen, gl = set(), []
    for g in result["glossary"]:
        if g.get("term") and g["term"] not in seen:
            seen.add(g["term"])
            gl.append(g)
    result["glossary"] = gl
    return result


# ---------------------------------------------------------------- 报告

def importance(it):
    """把 AI 给的重要度转成 0-5 的整数，兼容 "4"、4.0、"高" 等写法"""
    v = it.get("importance", 0)
    try:
        return max(0, min(5, int(float(v))))
    except (TypeError, ValueError):
        return {"极高": 5, "高": 4, "中": 3, "低": 2}.get(str(v).strip(), 0)


def render(group_name, gtype, result, msg_count, period):
    out = [f"## {group_name}", f"*{period}，共 {msg_count} 条消息*", ""]
    if result["overview"]:
        out += ["> " + " ".join(result["overview"]), ""]
    items = sorted(result["items"], key=lambda x: -importance(x))
    if not items:
        out += ["没有筛出有用信息。", ""]
    cats = []
    for it in items:
        if it.get("category") not in cats:
            cats.append(it.get("category"))
    for cat in cats:
        out += [f"### {cat or '其他'}", ""]
        for it in [x for x in items if x.get("category") == cat]:
            stars = "★" * importance(it)
            out.append(f"#### {stars} {it.get('title', '')}")
            out.append(f"{it.get('summary', '')}")
            if it.get("eligibility"):
                out.append(f"- **我能参加吗**：{it['eligibility']}")
            if it.get("explain"):
                out.append(f"- **解释**：{it['explain']}")
            if it.get("quote"):
                out.append(f"- 原话（{it.get('sender', '')}）：「{it['quote']}」")
            for link in it.get("links") or []:
                out.append(f"- 链接：{link}")
            if it.get("time"):
                out.append(f"- 📅 {it['time']}")
            out.append("")
    if result["glossary"]:
        out += ["### 术语小词典", ""]
        out += [f"- **{g['term']}**：{g.get('explain', '')}" for g in result["glossary"] if g.get("term")]
        out.append("")
    return "\n".join(out)




# ---------------------------------------------------------------- 主流程

def process(cfg, args, state, now, stamp, name, gtype, path, skey):
    """处理一个导出文件，返回报告段落（dry-run 时返回 None）"""
    msgs = load_messages(path)
    if msgs is None:  # 识别不出时间格式（如手动复制的文本），无法按时间过滤
        text = CTRL.sub("", Path(path).read_text(encoding="utf-8-sig", errors="ignore"))
        count, period = text.count("\n") + 1, "手动导入（未识别时间，处理整份文件）"
        if len(text) > UNKNOWN_LIMIT and not args.all and not args.dry_run:
            calls = len(chunk_text(text))
            sys.exit(f"[停止] {Path(path).name} 识别不出时间格式，无法只取最近的消息。\n"
                     f"  整份文件 {len(text)} 字，需要调用 AI 约 {calls} 次，可能比较费钱。\n"
                     f"  确认要全部处理请加 --all；或者只把需要的部分复制到一个新文件再处理。\n"
                     f"  支持的格式见 README 的「支持的聊天记录格式」。")
    else:
        if args.all:
            since = 0
        elif args.hours:
            since = now.timestamp() - args.hours * 3600
        else:
            since = state.get(skey, now.timestamp() - 24 * 3600)
        latest = max((m[0] for m in msgs), default=0)
        if latest and latest < since:
            print(f"  提醒：文件里最新的消息是 {dt.datetime.fromtimestamp(latest):%m-%d %H:%M}，"
                  f"早于本次起点，可能需要先重新导出。")
        msgs = [m for m in msgs if m[0] >= since]
        text = format_messages(msgs)
        count = len(msgs)
        useful = sum(1 for m in msgs if m[2].strip() and not NOISE.match(m[2].strip()))
        start = "全部" if since == 0 else f"{dt.datetime.fromtimestamp(since):%m-%d %H:%M}"
        period = f"{start} ~ {now:%m-%d %H:%M}"
    if msgs is None:
        useful = count
    print(f"[{name}] {period}：{count} 条消息，去掉图片/空消息后 {useful} 条，{len(text)} 字")
    (RAW_DIR / f"{stamp}_{name}.txt").write_text(text, encoding="utf-8")
    if args.dry_run:
        return None
    if not text.strip():
        return f"## {name}\n*{period}*\n\n没有新消息。\n"
    result = analyze(cfg, name, gtype, text)
    if not (args.hours or args.all):  # 只有"从上次运行开始"的模式才记录进度，周报等不会打乱它
        state[skey] = now.timestamp()
    return render(name, gtype, result, count, period)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="QQ 群聊 AI 筛选器")
    ap.add_argument("--hours", type=float, help="只看最近 N 小时（默认：从上次运行开始，首次 24 小时）")
    ap.add_argument("--all", action="store_true", help="不按时间过滤，处理全部记录（很费钱，慎用）")
    ap.add_argument("--dry-run", action="store_true", help="只筛出原文存到 raw/，不调用 AI")
    ap.add_argument("--group", help="只处理某一个群（群号）")
    ap.add_argument("--file", help="处理指定文件（如手动复制的聊天记录 txt）")
    ap.add_argument("--type", default="opensource", help="--file 模式下的群类型（config.json 的 topics 里定义的名字）")
    ap.add_argument("--preset", help="使用 config.json 里 presets 定义的预设，如 daily（24小时→今日快报）、weekly（一周→今周快报）")
    args = ap.parse_args()

    cfg = load_json(CONFIG_PATH)
    if cfg is None:
        sys.exit("[错误] 没找到 config.json，请复制 config.example.json 为 config.json 并填写")

    title = "今日快报"
    def resolve(p):
        p = Path(p)
        return p if p.is_absolute() else ROOT / p

    report_dir = resolve(cfg.get("report_dir") or REPORT_DIR)
    if args.preset:
        presets = cfg.get("presets", {})
        if args.preset not in presets:
            sys.exit(f"[错误] config.json 里没有预设 {args.preset}，可用的有：{', '.join(presets) or '无'}")
        ps = presets[args.preset]
        if not args.hours and not args.all:
            args.hours = ps.get("hours")
        title = ps.get("title", title)
        report_dir = resolve(ps.get("report_dir") or report_dir)
        print(f"预设 {args.preset}：最近 {args.hours:g} 小时 → {report_dir}")
    report_dir.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(exist_ok=True)
    now = dt.datetime.now()
    stamp = now.strftime("%Y-%m-%d_%H%M")
    state = load_json(STATE_PATH, {})

    jobs = []  # (名字, 类型, 路径, 状态键)
    if args.file:
        p = Path(args.file)
        if not p.exists():
            sys.exit(f"[错误] 文件不存在：{p}")
        jobs.append((p.stem, args.type, p, f"file:{p.stem}"))
    else:
        export_dir = resolve(cfg.get("export_dir") or default_export_dir())
        print(f"导出文件夹：{export_dir}")
        for g in cfg["groups"]:
            gid = str(g["id"])
            if args.group and args.group != gid:
                continue
            f = find_export(export_dir, gid)
            if not f:
                print(f"[{g['name']}] 没找到导出文件（群_{gid}_*.csv / .txt），请先用导出工具导出，跳过")
                continue
            print(f"[{g['name']}] 使用 {f.name}（导出于 {dt.datetime.fromtimestamp(f.stat().st_mtime):%m-%d %H:%M}）")
            jobs.append((g["name"], g["type"], f, gid))
    if not jobs:
        sys.exit("没有可处理的文件。")

    # 在调用 AI（花钱）之前先检查所有群类型都已定义
    for name, gtype, _, _ in jobs:
        if gtype not in get_topics(cfg):
            sys.exit(f"[错误] 「{name}」的群类型 {gtype!r} 未定义。"
                     f"config.json 的 topics 里现有：{', '.join(get_topics(cfg))}")

    sections = []
    for name, gtype, path, skey in jobs:
        sec = process(cfg, args, state, now, stamp, name, gtype, path, skey)
        if sec:
            sections.append(sec)

    if args.dry_run:
        print("\ndry-run 完成：筛出的原文在 raw/ 文件夹，未调用 AI。")
        return
    save_json(STATE_PATH, state)
    if all("没有新消息" in sec for sec in sections):
        print("\n这段时间所有群都没有新消息，未生成报告。")
        return
    out = report_dir / f"{title}_{stamp}.md"
    out.write_text(f"# {title} {now:%Y-%m-%d %H:%M}\n\n" + "\n---\n\n".join(sections), encoding="utf-8")
    print(f"\n完成 → {out}")
    if os.name == "nt" and cfg.get("open_report", True):
        os.startfile(out)


if __name__ == "__main__":
    main()
