# qq-group-digest

**English** | [简体中文](README.zh-CN.md)

> Use AI to pick out what actually matters to you from QQ group chats, and get a daily or weekly digest.

![License](https://img.shields.io/badge/license-MIT-blue)
![Version](https://img.shields.io/badge/version-1.0.0-green)
![Python](https://img.shields.io/badge/python-3.8%2B-3776AB)

![demo](docs/demo.svg)

## Table of Contents
- [Features](#features)
- [Two Ways to Get Started](#two-ways-to-get-started)
- [Quick Start](#quick-start)
- [Usage](#usage)
- [Configuration](#configuration)
- [Project Structure](#project-structure)
- [FAQ](#faq)
- [Contributing](#contributing)
- [Disclaimer](#disclaimer)
- [License](#license)

## Features
- 🎯 **You decide what to collect**: which groups to read, which categories to sort messages into, and who you are and what you need. All of it lives in a config file, so you never touch the code.
- 📚 **Two category sets out of the box**: study groups (exam notices, study tips, materials, competitions) and tech groups (paid gigs, AI news, model discussions, open-source tips).
- ✅ **"Can I join?" check**: for gigs, recruitments and competitions, it judges whether you meet the requirements based on your profile.
- 💡 **Plain-language explanations**: each item can carry an explanation of the jargon in it, and the report ends with a glossary. You can change the style or turn it off.
- 📅 **Daily and weekly digests**: double-click to run. Every item is dated.
- 💰 **Cheap**: it only processes messages inside the time window you choose and drops images, stickers and empty messages. A day of chat usually costs a few cents of a yuan.
- 🔌 **Multiple models and formats**: uses DeepSeek and compatible Chat Completions endpoints, including a local Ollama. Reads CSV, TXT and the classic QQ Message Manager export.
- 📦 **Zero dependencies**: Python standard library only.

> The prompts and reports are in Chinese, since the tool is built for Chinese-language QQ groups.

## Two Ways to Get Started

| | Best for | How |
|---|---|---|
| **Option A: Do it yourself** | You want to understand each step | Follow [Quick Start](#quick-start) and [Usage](#usage) below (about 10 minutes) |
| **Option B: Let an AI agent set it up** | You have an AI assistant that can run commands on your computer (Claude Code, Codex, Cursor, etc.) | Copy the prompt below and send it to the agent. It will ask you questions and do the setup. |

<details>
<summary><b>Option B: prompt to send to your agent</b> (click to expand)</summary>

```text
Please install and configure the open-source project qq-group-digest on this computer:
https://github.com/Eutopia-Nan/qq-group-digest

It reads QQ group chat files that I export myself, uses AI to pick out what's useful to me, and produces daily/weekly digests.
First read README.md (or README.zh-CN.md) and config.example.json in the repo, then follow the steps below.
Talk to me in my language, ask one question at a time, explain things plainly, and don't assume I can code.

[Steps]
1. Check that Python >= 3.8 is installed. If not, tell me how to install it (on Windows, tick "Add python.exe to PATH"). Don't install it silently for me.
2. Ask me which folder to put the project in, then download it or git clone it there.
3. Run the self-check: python digest.py --file examples/study.csv --type study --all --dry-run and confirm it works.
4. Copy config.example.json to config.json, then ask me about each item and fill it in:
   - AI provider: DeepSeek (needs an API key and a topped-up balance at platform.deepseek.com), another OpenAI-compatible endpoint, or a local model such as Ollama.
   - profile: ask about my role, major or year, skill level, and what I most want from these groups (exam notices, gigs, internships, tech news…). Write it up as one paragraph.
   - groups: which groups to process, and each group's ID and purpose.
   - topics: design categories for each group's purpose. Reuse the built-in study / opensource types where they fit; otherwise create a new type and confirm the categories with me.
   - explain_style: whether I want jargon explained, and in how much detail.
   - export_dir: where my exported chat files are.
   After every edit, verify that config.json is valid JSON.
5. In the export folder, check by file name (群_<groupId>_*.csv / *.txt) that every group has an export file, and tell me which are missing.
6. Run python digest.py --preset daily --dry-run and summarize the result for me in a sentence or two.
7. Tell me the daily routine: re-export the chats first, then double-click 1_今日快报_24小时.bat or 2_今周快报_一周.bat.

[Rules you must follow]
- Write the API key only into the local config.json. Never show it in full in your replies, and never commit or upload it anywhere. config.json is in .gitignore; keep it that way.
- This project only processes files that have already been exported. Do not read or decrypt QQ's databases or process memory yourself. Do not download, install or run any third-party export tool unless I explicitly agree. If I have no export files yet, just explain my options and their risks and let me decide.
- Do not open or repeat the contents of my chats. When checking export files, look only at file names, sizes and modification times.
- Real AI calls cost money. Until I explicitly agree, only run commands with --dry-run.
- Do not modify digest.py. If something fails, show me the exact error and your diagnosis first.
```

</details>

## Quick Start

### Requirements
- Python >= 3.8. On Windows, tick **"Add python.exe to PATH"** in the installer.
- A [DeepSeek API key](https://platform.deepseek.com). Top up a small balance first, then create a key under **API keys**. It is shown only once, so copy it right away.
- Exported group chat records. See [Step 2](#step-2-export-chat-records).

### Installation
```bash
git clone https://github.com/Eutopia-Nan/qq-group-digest.git
cd qq-group-digest
```
If you don't use git, click **Code → Download ZIP** and unzip it. There is nothing to install.

From the project folder, check the installation with a bundled sample. This command needs no configuration or API key.

```bash
python digest.py --file examples/study.csv --type study --all --dry-run
```

The output should show two messages in range and one selected for processing.

## Usage

### Step 1: Configure
Copy `config.example.json` to `config.json` and fill in at least these three:

| Field | What to enter |
|---|---|
| `deepseek.api_key` | Your API key. Replace the whole placeholder string. |
| `profile` | Who you are and what you need. The more specific, the better the filtering. |
| `groups` | `id` is the group number, `name` is any label you like, `type` is `study` or `opensource`. |

If `config.json` has a syntax error, the program tells you the line number. The usual causes are a trailing comma, Chinese quotation marks, or an unescaped `\` in a path. Use `/` or `\\` in paths.

### Step 2: Export chat records
This project only processes chats that have **already been exported**. It contains no code for fetching or decrypting chat data. You can use any export tool, for example the third-party [qq-chat-exporter](https://github.com/Yosooiiii/qq-chat-exporter) (by Yosooiiii, MIT, not affiliated with this project). If you use it, choose **CSV**, which includes sender nicknames. Please assess the risks of any third-party tool yourself.

- The exporter's Windows app is on its [Releases page](https://github.com/Yosooiiii/qq-chat-exporter/releases). Keep QQ running and signed in while exporting.
- Exports go to `Desktop\QQ聊天记录导出\` by default, with file names like `群_<groupId>_<name>.csv`. The tool picks the newest file for each group within a format and prefers CSV when both formats were exported around the same time.
- If you export somewhere else, set `export_dir`.
- Other formats work too. See [Supported formats](#supported-formats).

> Only export chats from your own account that you are entitled to view, and follow applicable laws and platform terms.

### Step 3: Dry run (free)
```bash
python digest.py --dry-run
```
It shows how many messages it found and saves the selected text to `raw/`. A dry run makes no AI calls and leaves progress unchanged.

### Step 4: Generate a digest
On Windows, double-click:
- `1_今日快报_24小时.bat` for the last 24 hours. Saved to `reports/今日快报/`.
- `2_今周快报_一周.bat` for the last 7 days. Saved to `reports/今周快报/`.

On any OS you can also run:
```bash
python digest.py --preset daily
python digest.py --preset weekly
```

**Re-export before every run.** The tool only reads exported files and never pulls new messages from QQ by itself.

### CLI options
```bash
python digest.py                     # unprocessed messages, starting with a 24-hour window on first run
python digest.py --hours 72          # last 3 days
python digest.py --dry-run           # save a local preview, no AI call
python digest.py --group 123456789   # one group only
python digest.py --file chat.txt --type study   # any chat file
python digest.py --file chat.csv --encoding gb18030 --dry-run   # GBK/GB18030 export
python digest.py --all               # whole history (can be expensive)
```

## Configuration
All settings live in `config.json`.

| Key | Description | Default |
|------|------|--------|
| `deepseek.api_key` | Key for the configured endpoint. The official DeepSeek endpoint also accepts `DEEPSEEK_API_KEY`. | usually required for cloud services |
| `deepseek.base_url` | Any OpenAI-compatible endpoint | `https://api.deepseek.com` |
| `deepseek.model` | Model name. Update older configs that use `deepseek-chat` or `deepseek-reasoner`. | `deepseek-flash` |
| `deepseek.json_mode` | Request JSON mode from the endpoint. Response validation still runs if disabled. | `true` |
| `deepseek.chunk_chars` | Character limit per batch in the user prompt. Lower it for smaller-context models. | `40000` |
| `deepseek.max_tokens` | Maximum output tokens per batch | `4096` |
| `profile` | Who you are and what you need | none |
| `explain_style` | How to explain jargon. Set to `""` to turn explanations off. | beginner-friendly |
| `topics` | Group types, with what to focus on and the categories for each | `study`, `opensource` |
| `groups` | Groups to process: `id`, `name`, `type` | none, required |
| `export_dir` | Folder that holds the exported files | `Desktop/QQ聊天记录导出` |
| `report_dir` | Where reports go when no preset is used | `reports` |
| `presets` | Named time windows (`hours`), titles and output folders | `daily` 24h, `weekly` 168h |
| `open_report` | Open the report automatically when done | `true` |
| `save_raw` | Keep a plaintext copy during normal runs. A dry run always saves a preview. | `false` |
| `ui_defaults` | Groups and time range the GUI pre-selects, written by its "save as default" button. The command line ignores it. | all groups, since last run |

Built-in topics and presets accept field-level overrides. **Your categories are the full list**: whatever you put in `categories` is used as-is, and the built-in categories are no longer merged back in, so deleting a line really deletes that category. If you omit `categories`, the built-in ones are used. `{}` leaves only the automatic "其他有用" (other useful) category.

> ⚠️ Upgrading from an older version: older versions merged your categories with the built-in ones. If you only listed the categories you added, the built-in ones won't appear any more after upgrading. Copy the ones you want to keep from `config.example.json`. A custom preset needs a positive `hours` value unless you provide `--hours` or `--all` on the command line.

The first successful incremental run after upgrading converts `state.json` to track individual messages. It may include some recent messages again because the old format only saved run times. `--hours`, the daily and weekly presets, and `--all` leave incremental progress unchanged.

### Custom group types
Add an entry next to the existing ones in `topics`:
```json
"job": {
  "label": "求职交流群",
  "focus": "招聘、内推和求职经验",
  "categories": {
    "内推机会": "公司、岗位、要求、截止时间、内推码或联系方式",
    "面经": "面试题目、流程、薪资信息"
  }
}
```
Then set a group's `type` to `"job"`. A catch-all "其他有用" (other useful) category is added automatically. Unknown types are caught before any paid API call.

### Other models
Set `base_url`, `model` and `api_key` for the service you are using. For local Ollama, use `"base_url": "http://localhost:11434/v1"`, a model you have downloaded, and an empty key. If your endpoint does not support `response_format`, set `"json_mode": false` under `deepseek`.

### Supported formats
| Format | Example |
|---|---|
| CSV (recommended) | Needs a time column (`时间`/`time`/`date`) and a content column (`内容`/`content`/`message`). A sender column (`发送者`/`sender`/`name`) is optional. |
| One-line TXT | `[2026-11-17 14:03:00] Alice: text`. Chinese or English colon; seconds are optional. |
| Classic QQ Message Manager TXT | A line `2026-11-17 14:03:00 Alice(123456)`, with the content on the next line |
| Other plain text | Use `--all` to confirm processing the entire file when timestamps cannot be detected. |

CSV supports comma, semicolon and Tab delimiters. Timestamps can be local date-times, ISO 8601 with an offset, or 10/13-digit Unix timestamps. The tool detects UTF-8 and UTF-16 with a BOM. For GBK exports, pass `--encoding gb18030`.

## Project Structure
```
├── digest.py                 # command-line entry (argument parsing, progress output)
├── digest_core.py            # core logic: reading, filtering, AI calls, reports
├── config.example.json       # config template (copy to config.json)
├── 1_今日快报_24小时.bat      # daily digest launcher (Windows)
├── 2_今周快报_一周.bat        # weekly digest launcher (Windows)
├── docs/                     # docs, FAQ and images
├── tests/                    # automated tests
├── reports/                  # generated reports (git-ignored)
├── raw/                      # dry-run previews and optional plaintext copies (git-ignored)
└── state.json                # incremental progress (git-ignored)
```

## FAQ
> Want to change which groups are processed, a group's type, what to focus on, or how far back to look? See the [customization FAQ](docs/faq.md).

Messages you may see while running, and how to fix them:

| Message | Cause and fix |
|---|---|
| `'python' is not recognized` | Python isn't on PATH. Re-run the installer, choose Modify, and tick "Add python.exe to PATH". |
| `config.json 第 X 行格式有误` | JSON syntax error on that line |
| `没找到导出文件` (export not found) | Not exported yet, wrong `export_dir`, or wrong group ID |
| `401` / `402` | Wrong API key / insufficient balance |
| `没有筛出有用信息` (nothing useful found) | There were messages, but the AI judged them all as chatter. Make `profile` and `categories` more specific. |

**Known limitations**
- Large inputs are split into batches, so an item can appear twice when it spans batches.
- The AI can miss or misread things. Check exam dates and deadlines against the original messages.

The selected chat content, sender names and your profile are sent to the configured AI provider. Git ignores `config.json`, `state.json`, `reports/` and `raw/` by default. Check custom output folders before sharing the repository.

## Contributing
Issues and PRs are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) first.

1. Fork this repo
2. Create a branch: `git checkout -b feature/xxx`
3. Commit: `git commit -m 'Add xxx'`
4. Push: `git push origin feature/xxx`
5. Open a Pull Request

## Disclaimer
- This is an independent open-source project. It is not affiliated with, authorized by, or endorsed by Tencent. "QQ" is a trademark of Tencent and is used here only to describe what the tool works with.
- This project only analyzes chat export files that users produce themselves. It contains no code for fetching, cracking or decrypting QQ data, and does not connect to any QQ protocol.
- Third-party tools mentioned here are maintained by their own authors. This project is not responsible for their functionality, security or compliance.
- Only process chats you are entitled to view, and follow applicable laws and platform terms. You are solely responsible for how you use this project.

## License
[MIT](LICENSE) © Eutopia

Built with AI assistance.
