# qq-group-digest

**English** | [简体中文](README.zh-CN.md)

> Use AI to pick out what actually matters to you from QQ group chats, and get a daily or weekly digest.

![License](https://img.shields.io/badge/license-MIT-blue)
![Version](https://img.shields.io/badge/version-1.0.0-green)
![Python](https://img.shields.io/badge/python-3.8%2B-3776AB)

![demo](docs/demo.svg)

## Table of Contents
- [Features](#features)
- [Quick Start](#quick-start)
- [Usage](#usage)
- [Configuration](#configuration)
- [Project Structure](#project-structure)
- [FAQ](#faq)
- [Contributing](#contributing)
- [License](#license)

## Features
- 🎯 **You decide what to collect**: which groups to read, which categories to sort messages into, and who you are and what you need. All of it lives in a config file, so you never touch the code.
- 📚 **Two category sets out of the box**: study groups (exam notices, study tips, materials, competitions) and tech groups (paid gigs, AI news, model discussions, open-source tips).
- ✅ **"Can I join?" check**: for gigs, recruitments and competitions, it judges whether you meet the requirements based on your profile.
- 💡 **Plain-language explanations**: each item can carry an explanation of the jargon in it, and the report ends with a glossary. You can change the style or turn it off.
- 📅 **Daily and weekly digests**: double-click to run. Every item is dated.
- 💰 **Cheap**: it only processes messages inside the time window you choose and drops images, stickers and empty messages. A day of chat usually costs a few cents of a yuan.
- 🔌 **Works with many models and formats**: DeepSeek or any OpenAI-compatible API, including a local Ollama. Reads CSV, TXT and the classic QQ Message Manager export.
- 📦 **Zero dependencies**: Python standard library only.

> The prompts and reports are in Chinese, since the tool is built for Chinese-language QQ groups.

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
This project only processes chats that have **already been exported**. It does not fetch messages itself. We recommend the third-party tool [qq-chat-exporter](https://github.com/Yosooiiii/qq-chat-exporter) (by Yosooiiii, MIT, not affiliated with this project). Export as **CSV**, which includes sender nicknames.

- Exports go to `Desktop\QQ聊天记录导出\` by default, with file names like `群_<groupId>_<name>.csv`. The tool picks the newest file for each group by its ID.
- If you export somewhere else, set `export_dir`.
- Other formats work too. See [Supported formats](#supported-formats).

> Only export chats from your own account that you are entitled to view, and follow applicable laws and platform terms.

### Step 3: Dry run (free)
```bash
python digest.py --dry-run
```
It shows how many messages it found for each group, without calling the AI.

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
python digest.py                     # only messages since the last plain run
python digest.py --hours 72          # last 3 days
python digest.py --dry-run           # count only, no AI call
python digest.py --group 123456789   # one group only
python digest.py --file chat.txt --type study   # any chat file
python digest.py --all               # whole history (can be expensive)
```

## Configuration
All settings live in `config.json`.

| Key | Description | Default |
|------|------|--------|
| `deepseek.api_key` | API key. The `DEEPSEEK_API_KEY` env var also works. | none, required |
| `deepseek.base_url` | Any OpenAI-compatible endpoint | `https://api.deepseek.com` |
| `deepseek.model` | Model name | `deepseek-chat` |
| `profile` | **Most important.** Who you are and what you need | none, required |
| `explain_style` | How to explain jargon. Set to `""` to turn explanations off. | beginner-friendly |
| `topics` | Group types, with what to focus on and the categories for each | `study`, `opensource` |
| `groups` | Groups to process: `id`, `name`, `type` | none, required |
| `export_dir` | Folder that holds the exported files | `Desktop/QQ聊天记录导出` |
| `report_dir` | Where reports go when no preset is used | `reports` |
| `presets` | Named time windows (`hours`), titles and output folders | `daily` 24h, `weekly` 168h |
| `open_report` | Open the report automatically when done | `true` |

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
Change `base_url` and `model`. For a local Ollama, use `"base_url": "http://localhost:11434/v1"` and `"model": "qwen2.5"`. No key is needed, and your data stays on your machine.

### Supported formats
| Format | Example |
|---|---|
| CSV (recommended) | Needs a time column (`时间`/`time`/`date`) and a content column (`内容`/`content`/`message`). A sender column (`发送者`/`sender`/`name`) is optional. |
| One-line TXT | `[2026-11-17 14:03:00] Alice: text`. Chinese or English colon; seconds are optional. |
| Classic QQ Message Manager TXT | A line `2026-11-17 14:03:00 Alice(123456)`, with the content on the next line |
| Other plain text | No timestamps, so the whole file is processed. Files over 20,000 characters need `--all` to confirm, so you don't overspend by accident. |

## Project Structure
```
├── digest.py                 # main program
├── config.example.json       # config template (copy to config.json)
├── 1_今日快报_24小时.bat      # daily digest launcher (Windows)
├── 2_今周快报_一周.bat        # weekly digest launcher (Windows)
├── docs/                     # images for docs
├── reports/                  # generated reports (git-ignored)
├── raw/                      # text sent to the AI on each run (git-ignored)
└── state.json                # last-run timestamps (git-ignored)
```

## FAQ
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

**Privacy**: messages inside the time window are sent to the AI provider you configure. `config.json`, `reports/` and `raw/` are git-ignored.

## Contributing
Issues and PRs are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) first.

1. Fork this repo
2. Create a branch: `git checkout -b feature/xxx`
3. Commit: `git commit -m 'Add xxx'`
4. Push: `git push origin feature/xxx`
5. Open a Pull Request

## License
[MIT](LICENSE) © Eutopia

Built with AI assistance.
