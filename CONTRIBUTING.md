# 贡献指南 / Contributing

感谢你愿意参与！/ Thanks for your interest in contributing!

## 提 Issue / Reporting issues
- **Bug**：请附上运行的命令、完整的报错信息、Python 版本和导出工具名称。
  Include the command you ran, the full error output, your Python version and the export tool you used.
- **不支持的聊天记录格式 / Unsupported export format**：请附上**脱敏后**的几行样例（把昵称、群号、内容换成假的）。
  Attach a few **anonymized** sample lines (replace names, IDs and content).
- **请勿**在 Issue 里贴出 API Key、真实聊天记录或群号。
  **Never** post API keys, real chat logs or group IDs in issues.

## 提 PR / Pull requests
1. 保持**零依赖**：只用 Python 标准库。
   Keep it **dependency-free**: standard library only.
2. 兼容 Python 3.8+。
   Stay compatible with Python 3.8+.
3. 改动用户可见的行为时，请同步更新 `README.md` 和 `README.zh-CN.md`。
   If you change user-facing behavior, update both `README.md` and `README.zh-CN.md`.
4. 新增配置项时，同步更新 `config.example.json`，并确保旧的配置文件仍能使用。
   When adding config options, update `config.example.json` and keep old configs working.
5. 提交前至少跑一次 `python digest.py --dry-run` 和 `python -m py_compile digest.py`。
   Before submitting, run `python digest.py --dry-run` and `python -m py_compile digest.py`.

## 想法 / Ideas
欢迎以下方向的贡献 / Contributions especially welcome for:
- 支持更多聊天记录导出格式（微信、Telegram 等） / More export formats (WeChat, Telegram, …)
- 合并分批处理时产生的重复条目 / Deduplicating items across batches
- macOS / Linux 启动脚本 / Launcher scripts for macOS / Linux
