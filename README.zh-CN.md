# qq-group-digest

[English](README.md) | **简体中文**

> 用 AI 从 QQ 群聊记录里筛出对你有用的信息，自动生成每日/每周快报。

![License](https://img.shields.io/badge/license-MIT-blue)
![Version](https://img.shields.io/badge/version-1.0.0-green)
![Python](https://img.shields.io/badge/python-3.8%2B-3776AB)

![demo](docs/demo.svg)

## 目录
- [功能特性](#功能特性)
- [快速开始](#快速开始)
- [使用方法](#使用方法)
- [配置](#配置)
- [项目结构](#项目结构)
- [常见问题](#常见问题)
- [贡献](#贡献)
- [许可证](#许可证)

## 功能特性
- 🎯 **筛选偏好由你决定**：关注哪些群、每个群筛哪些分类、你的身份和需求，都写在配置文件里，不用改代码
- 📚 **开箱即用的两套分类**：学习群（考试通知、提分方法、学习资料、竞赛加分）和技术群（赚钱机会、AI 新动态、模型讨论、开源知识）
- ✅ **判断你能不能参加**：遇到兼职、招募、竞赛这类机会，会根据你的情况判断你是否符合门槛
- 💡 **术语解释**：每条信息可以附上通俗解释，报告末尾还有术语小词典。风格可以自定义，也可以关掉
- 📅 **每日 / 每周快报**：双击就能运行，每条信息都标注日期
- 💰 **省钱**：只处理指定时间范围内的消息，自动过滤图片、表情等空消息。一天的群聊处理一次通常只要几分钱
- 🔌 **兼容多种 AI 和格式**：DeepSeek 或任何 OpenAI 兼容接口（包括本地的 Ollama）；支持 CSV、TXT、经典版 QQ 消息管理器等多种导出格式
- 📦 **零依赖**：只用 Python 标准库

## 快速开始

### 环境要求
- Python >= 3.8（安装时务必勾选 **"Add python.exe to PATH"**）
- 一个 [DeepSeek API Key](https://platform.deepseek.com)：注册后需要先充值几块钱，在 **API keys** 页面创建 Key，它只显示一次，记得马上复制
- 导出好的群聊记录（见[第 2 步](#第-2-步导出群聊记录)）

### 安装
**方式一（推荐新手）**：在本页面点绿色的 **Code** 按钮 → **Download ZIP**，解压到一个好找的位置，比如 `D:\qq-group-digest`。

**方式二**：用 git
```bash
git clone https://github.com/Eutopia-Nan/qq-group-digest.git
cd qq-group-digest
```

无需安装任何依赖。

## 使用方法

### 第 1 步：填写配置
1. 在项目文件夹里复制 `config.example.json`，把副本**重命名为 `config.json`**
   > Windows 默认隐藏文件扩展名，改名时容易变成 `config.json.json`。建议先在资源管理器顶部点 **查看 → 显示 → 文件扩展名** 把它打开。
2. 用记事本或 VS Code 打开 `config.json`，至少改这三处：

| 要改的地方 | 怎么填 |
|---|---|
| `"api_key": "sk-xxx（...）"` | 把引号里的**整段内容**换成你的 Key |
| `"profile": "【必填】..."` | 换成你自己的情况，越具体筛得越准 |
| `"groups"` | `id` 填群号，`name` 填群名（随意写），`type` 填 `study` 或 `opensource` |

**群号在哪看**：QQ 群聊 → 右上角"群聊设置"，群名称下面那串数字就是群号。导出的文件名里也有。

**编辑时注意**（写错了程序会提示第几行出错）：
- 只改**引号里面**的内容，引号本身要保留
- 用英文标点：英文双引号 `"`、英文逗号 `,`、英文冒号 `:`
- 列表中每两项之间要有逗号，**最后一项后面不能有逗号**
- 内容里不要再出现英文双引号，需要的话用「」代替
- 写路径时，`\` 要写成 `\\` 或 `/`，例如 `"D:/QQ导出"`

### 第 2 步：导出群聊记录
本项目**只处理已经导出的文件**，不负责获取聊天记录。推荐用第三方工具 [qq-chat-exporter](https://github.com/Yosooiiii/qq-chat-exporter)（作者 Yosooiiii，MIT 许可，与本项目无关）把群聊导出为 **CSV**，CSV 里带发言人昵称。

- 默认导出到 `桌面\QQ聊天记录导出\`，文件名形如 `群_<群号>_<群名>.csv`，本工具会按群号自动找到最新的文件，**不用改名**
- 导出位置不在桌面的话，在 `config.json` 的 `export_dir` 填上那个文件夹的路径
- 其他工具导出的文件也可以用，见[支持的聊天记录格式](#支持的聊天记录格式)

> 请仅导出你本人账号、你有权查看的聊天记录，并遵守相关法律法规和平台协议。

### 第 3 步：试运行（不花钱）
在项目文件夹的地址栏输入 `cmd` 回车，然后运行：
```bash
python digest.py --dry-run
```
它会显示每个群找到多少条消息，但不调用 AI。

### 第 4 步：生成报告
双击：
- `1_今日快报_24小时.bat`：最近 24 小时，报告存到 `reports\今日快报\`
- `2_今周快报_一周.bat`：最近 7 天，报告存到 `reports\今周快报\`

报告是 `.md` 文件，运行完会自动打开。用记事本就能看，用 VS Code、Typora 或 Obsidian 打开排版更好。

### 日常使用
**每次都要先重新导出，再运行**，因为本工具不会自己去 QQ 里拿新消息：

1. 用导出工具重新导出（覆盖旧文件即可）
2. 双击 `.bat` 生成报告
3. 看完报告后删除导出的文件，因为它是明文

### 命令行参数
```bash
python digest.py --preset daily      # 今日快报（同双击 1）
python digest.py --preset weekly     # 今周快报（同双击 2）
python digest.py                     # 只处理上次（不带参数）运行之后的新消息
python digest.py --hours 72          # 最近 3 天
python digest.py --dry-run           # 只统计、不调用 AI（不花钱）
python digest.py --group 123456789   # 只处理一个群
python digest.py --file 文件.txt --type study   # 处理任意一个聊天记录文件
python digest.py --all               # 处理全部历史记录（很费钱，慎用）
```

## 配置
所有设置都在 `config.json` 里：

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `deepseek.api_key` | AI 接口的 Key（也可以用环境变量 `DEEPSEEK_API_KEY`） | 无，必填 |
| `deepseek.base_url` | AI 接口地址，任何 OpenAI 兼容接口都可以 | `https://api.deepseek.com` |
| `deepseek.model` | 模型名 | `deepseek-chat` |
| `profile` | **最重要**。你的身份、能力和需求，AI 靠它判断什么对你有用 | 无，必填 |
| `explain_style` | 术语解释的风格。留空 `""` 就不解释 | 零基础，大白话 + 生活类比 |
| `topics` | 群类型，以及每类群的关注点和分类（见下文） | `study`、`opensource` |
| `groups` | 要筛选的群：`id` 群号、`name` 群名、`type` 群类型 | 无，必填 |
| `export_dir` | 导出文件所在的文件夹 | `桌面\QQ聊天记录导出` |
| `report_dir` | 不用预设时报告的保存位置 | `reports` |
| `presets` | 预设的时间范围（`hours`）、标题和保存位置 | `daily` 24 小时、`weekly` 168 小时 |
| `open_report` | 运行完是否自动打开报告 | `true` |

### 自定义群类型
在 `topics` **原有的大括号里面**加一项，和 `study`、`opensource` 并列（前一项末尾要补逗号）：
```json
"topics": {
  "study": { ...原有内容，不要删... },
  "opensource": { ...原有内容，不要删... },
  "job": {
    "label": "求职交流群",
    "focus": "招聘、内推和求职经验",
    "categories": {
      "内推机会": "公司、岗位、要求、截止时间、内推码或联系方式",
      "面经": "面试题目、流程、薪资信息"
    }
  }
},
```
然后把对应群的 `type` 写成 `"job"`。

- `label`：群的描述
- `focus`：这类群里你最关心什么
- `categories`：分类名 → 这个分类收集什么
- 不需要写"其他有用"分类，程序会自动补上
- 正在使用的类型不要删；类型不存在时，程序会在调用 AI 之前就报错，不会白花钱

### 换成其他 AI
修改 `base_url` 和 `model` 即可。例如用本地的 Ollama：`"base_url": "http://localhost:11434/v1"`，`"model": "qwen2.5"`，`api_key` 可以不填。数据不出本机，隐私更好。

### 支持的聊天记录格式
| 格式 | 示例 |
|---|---|
| CSV（推荐） | 表头包含时间列（`时间`/`日期`/`time`/`date`）和内容列（`内容`/`消息`/`content`/`message`），发送者列（`发送者`/`昵称`/`sender`/`name`）可选 |
| 单行 TXT | `[2026-11-17 14:03:00] 张三: 内容`（冒号中英文都可以，秒可以省略） |
| 经典版 QQ 消息管理器 TXT | 一行 `2026-11-17 14:03:00 张三(123456)`，下一行是内容 |
| 其他纯文本 | 识别不出时间，只能整份处理。超过 2 万字时需要加 `--all` 确认，防止误花钱 |

## 项目结构
```
├── digest.py                 # 主程序
├── config.example.json       # 配置模板（复制为 config.json 后填写）
├── 1_今日快报_24小时.bat      # 双击生成今日快报
├── 2_今周快报_一周.bat        # 双击生成今周快报
├── docs/                     # 文档图片
├── reports/                  # 生成的报告（运行后出现，不上传）
├── raw/                      # 每次交给 AI 的原文（运行后出现，不上传）
└── state.json                # 记录上次运行时间（运行后出现，不上传）
```

## 常见问题
| 看到的提示 | 原因和解决方法 |
|---|---|
| `'python' 不是内部或外部命令` / 弹出微软商店 | Python 没装好或没加入 PATH。重新运行 Python 安装程序，选 Modify 并勾选 "Add python.exe to PATH" |
| `config.json 第 X 行格式有误` | 按提示检查那一行，常见是多了或漏了逗号、用了中文引号 |
| `没找到导出文件` | 还没导出；或者导出位置不在桌面，需要设置 `export_dir`；或者群号填错了 |
| `可能需要先重新导出` | 导出文件里没有这段时间的消息，先重新导出 |
| `401` / `402` | API Key 填错了 / 账户余额不足 |
| 报告里写"没有筛出有用信息" | 有新消息，但 AI 判断都是闲聊。可以把 `profile` 和 `categories` 写得更具体 |
| `所有群都没有新消息，未生成报告` | 时间范围内没有消息。换成 `--hours 72` 试试，或者先重新导出 |

**已知限制**
- 消息很多时会分批交给 AI，不同批次之间可能出现重复条目
- `.bat` 只适用于 Windows；macOS/Linux 用 `python3 digest.py --preset daily`
- AI 可能看漏或理解错，考试时间、截止日期等重要信息请以原消息为准

**隐私**：时间范围内的聊天内容会发送给你配置的 AI 服务商。`config.json`、`reports/`、`raw/` 已写入 `.gitignore`，不会被上传。

## 贡献
欢迎提交 Issue 和 PR！请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

1. Fork 本仓库
2. 新建分支 `git checkout -b feature/xxx`
3. 提交 `git commit -m 'Add xxx'`
4. 推送 `git push origin feature/xxx`
5. 发起 Pull Request

## 许可证
[MIT](LICENSE) © Eutopia

本项目在 AI 辅助下开发。
