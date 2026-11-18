# FAQ: Customization

**English** | [简体中文](faq.zh-CN.md)

Make all of these changes in **`config.json`** in the project root. Open it with Notepad or VS Code. After editing, do a dry run to check for errors. It doesn't call the AI and costs nothing:

```bash
python digest.py --preset daily --dry-run
```

> When editing, only change what's inside the quotes. Use straight ASCII punctuation (`"` `,` `:`), don't put a comma after the last item in a list, and write paths with `/` or `\\`. If something is wrong, the program tells you the line number.

- [Q1: How do I change which groups are processed?](#q1-how-do-i-change-which-groups-are-processed)
- [Q2: How do I change a group's type?](#q2-how-do-i-change-a-groups-type)
- [Q3: How do I change what information to focus on?](#q3-how-do-i-change-what-information-to-focus-on)
- [Q4: How do I change how far back to look?](#q4-how-do-i-change-how-far-back-to-look)

---

## Q1: How do I change which groups are processed?

Edit `groups`:

```json
"groups": [
  { "id": 123456789, "name": "My study group", "type": "study" },
  { "id": 987654321, "name": "My tech group", "type": "opensource" }
],
```

| Goal | How |
|---|---|
| Add a group | Add a line in the same format, and put a comma at the end of the line before it. `id` is the group number, which also appears in the export file name `群_<groupId>_<name>.csv`. `name` is any label you like. |
| Stop processing a group | Delete its line, and make sure the new last line has no trailing comma |
| Process one group just this time | Leave the config alone and run `python digest.py --preset daily --group 123456789` |
| Process a file that isn't in the list | `python digest.py --file "path/to/file" --type study --hours 24` |

A newly added group needs its chats exported first. Otherwise you'll see "export file not found".

## Q2: How do I change a group's type?

Change the `"type"` of the group in `groups`. It decides which set of categories the AI uses for that group.

- `type` must be a name that **already exists** in `topics`. The defaults are `study` (study groups) and `opensource` (tech / open-source groups).
- To switch to another existing type, change the value, e.g. from `"type": "study"` to `"type": "opensource"`.
- To use a new type, create it in `topics` first (see [Q3](#q3-how-do-i-change-what-information-to-focus-on)), then set the group's `type` to the new name.
- An unknown type is reported **before** any AI call, so it costs nothing.

## Q3: How do I change what information to focus on?

Three fields work together:

**① `profile`: who you are and what you want (the most important one)**
```json
"profile": "Second-year CS student, knows Python, looking for a summer internship and online gigs, preparing for the calculus final."
```
The more specific, the better. The AI uses this to decide what's useful to you and whether you qualify for an opportunity.

**② `topics`: the categories for each group type**
```json
"study": {
  "label": "学习群",
  "focus": "对提高成绩有帮助的信息",
  "categories": {
    "考试与作业通知": "考试时间/范围、作业截止、老师重点划分、课程调整",
    "学习资料": "真题、课件、笔记、网课、题库链接或文件"
  }
}
```
- `label` describes this kind of group, `focus` says what you care about most, and `categories` maps each category name to what it should collect.
- To add a category, add a `"name": "what to collect"` line to `categories`. To remove one, delete its line.
- To create a new type, copy the whole `study` block, give it a new name (e.g. `"class"`), and put it next to the existing types, separated by a comma.
- You don't need an "other useful" category. The program adds it automatically.
- The prompts and reports are in Chinese, so writing categories in Chinese gives the most consistent results.

**③ `explain_style`: whether to explain jargon**
```json
"explain_style": "用户是零基础，用通俗大白话 + 生活类比解释清楚（2-4 句）"
```
- For shorter explanations, use something like `"用户有一定基础，一句话简要说明"` ("the user has some background; one short sentence").
- To turn explanations off, set it to `""`. The glossary at the end of the report goes away too.

## Q4: How do I change how far back to look?

| Goal | How |
|---|---|
| Permanently change the daily / weekly window | `hours` in `presets` (in hours) |
| Look at the last N hours just this time | `python digest.py --hours 72` (3 days), `--hours 720` (30 days) |
| Only messages since the last run | `python digest.py` (no time option). Already processed messages are skipped. |
| The whole history in the export file | `python digest.py --all` (can be expensive with many messages) |

```json
"presets": {
  "daily":  { "hours": 24,  "title": "今日快报", "report_dir": "reports/今日快报" },
  "weekly": { "hours": 168, "title": "今周快报", "report_dir": "reports/今周快报" }
}
```

- To add a preset, for example `"monthly": { "hours": 720, "title": "本月快报", "report_dir": "reports/本月快报" }`, then run `python digest.py --preset monthly`.
- **You can't look back further than the export file goes.** For the last 7 days, re-export first so the file covers those 7 days.
- Runs with `--hours` or `--preset` don't change the "since the last run" checkpoint.
