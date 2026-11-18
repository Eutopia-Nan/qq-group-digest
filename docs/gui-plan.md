# 图形界面版开发大纲（v2.0）

> 本文是 Claude 与 Codex 协作开发的**共同依据**。修改本文（特别是第 4、5 节的接口约定）需要单独提 PR，由项目所有者确认后再按新约定开发。

## 1. 目标
把 qq-group-digest 做成**不用碰命令行和 JSON** 的本地软件：普通用户下载、解压、双击，就能完成配置、选择群、生成快报和查看快报。

**完成标准**：一个从没用过本项目的人，只看界面上的提示，10 分钟内能生成第一份快报。

## 2. 已定决策
| 决策 | 结论 | 理由 |
|---|---|---|
| 界面技术 | 本地网页：Python 标准库 `http.server` + 原生 HTML/CSS/JS | 保持零依赖、跨平台、体积小 |
| 前端框架 | **不用**（不用 React/Vue，也不用 npm 构建） | 不引入构建步骤；用户解压即用 |
| 桌面窗口 | 发布版用 **pywebview** 把网页嵌进原生窗口；没有 WebView2 时自动改用浏览器打开 | 用户看到的是独立软件窗口，不是浏览器标签页 |
| 导出聊天记录 | **不集成**任何读取或解密 QQ 数据的功能 | 法律风险；与 README 免责声明一致。改为监视导出目录、支持拖入文件 |
| 配置来源 | 仍然是 `config.json`，界面只是读写它 | 兼容命令行和老用户 |
| 命令行 | **完整保留**，行为不变 | 现有用户和测试不受影响 |
| Python 版本 | 3.8+ | 与现有版本一致 |
| 运行依赖 | 从源码运行时**零依赖**；pywebview 和 PyInstaller **只在打包时**使用 | 源码用户不用装任何东西 |
| 发布形式 | ① **exe 版**：PyInstaller **文件夹模式**（exe + 依赖文件夹，压缩成 zip），推荐给普通用户；② 源码版 | 文件夹模式比单文件 exe 更少被杀毒软件误报 |

## 2.1 四项高频操作（核心体验要求）
以下四项是用户最常做的修改，必须在**主页**上直接完成，**最多点两下**，不进设置页，也不碰 JSON：

| 操作 | 界面 | 核心函数 |
|---|---|---|
| 1. 修改指定群聊 | 群列表打勾选择；导出目录里发现未配置的群时显示"➕ 添加"；每个群可以"移除" | `add_group` / `remove_group`；本次勾选通过 `selection` 传入 |
| 2. 修改 type | 每个群旁边的下拉框，改完自动保存 | `set_group_type` |
| 3. 修改聚焦的信息 | "我的关注点"卡片：个人情况文本框；当前类型的分类标签（× 删除，＋ 添加）；解释程度三档开关（详细 / 简短 / 不要） | `set_profile` / `set_category` / `remove_category` / `set_explain_level` |
| 4. 回溯时间 | 按钮组：今天 / 本周 / 上次之后 / 自定义（N 天或 N 小时） | `plan` / `run` 的 `window` 参数 |

- **本次选择和长期配置分开**：勾选群、选时间范围只影响这一次运行；点"保存为默认"才会写入配置
- 每次修改**当场生效、当场校验**。出错就在对应控件旁边用中文提示，不弹出技术性的报错
- **验收**：对每一项，录下新用户的操作，点击次数不超过 2 次（文本输入不算），整个过程不出现 JSON 或命令行

## 3. 目标文件结构
```
digest_core.py        # 核心逻辑：无 print、无 input、无 sys.exit
digest.py             # 命令行：解析参数 → 调用核心 → 打印
app.py                # 本地服务：HTTP 接口 + 任务管理 + 安全校验
desktop.py            # 发布版入口：启动 app.py，用 pywebview 打开窗口；失败时改用浏览器
ui/index.html         # 单页界面
ui/app.js
ui/style.css
启动界面.bat          # 源码版：双击启动 app.py（用浏览器打开）
build/build_exe.py    # 打包脚本：PyInstaller 文件夹模式 → dist/qq-group-digest/ → zip
tests/                # 现有测试 + 核心/接口新测试
docs/gui-plan.md      # 本文
```

## 4. 核心接口约定（digest_core.py）
核心代码**不得**直接 print、input 或 sys.exit。出错时抛 `DigestError`，错误信息写成用户能看懂的中文；进度通过回调报告。

```python
load_config(path=None) -> dict                 # 读取并校验，错误信息含行号
save_config(cfg, path=None) -> None            # 先校验再原子写入，校验失败不写
validate_config(cfg) -> list[Issue]            # Issue = {field, message, level: "error"|"warning"}

# —— 四项高频操作：一个动作一个函数，每个都"读取 → 修改 → 校验 → 原子写入"，返回更新后的配置 ——
add_group(cfg_path, group_id, name, type) -> dict
remove_group(cfg_path, group_id) -> dict
set_group_type(cfg_path, group_id, type) -> dict          # type 必须已存在，否则抛 DigestError
set_profile(cfg_path, text) -> dict
set_category(cfg_path, type, name, description) -> dict   # 新增或修改分类；type 不存在时自动新建类型
remove_category(cfg_path, type, name) -> dict
set_explain_level(cfg_path, level) -> dict                # "detailed" | "brief" | "off"，对应 explain_style 的三种预设文字
set_preset_hours(cfg_path, preset, hours) -> dict

scan_sources(cfg) -> list[Source]
#   Source = {key, group_id, name, type, file, file_mtime, configured: bool, status: "ok"|"missing"|"bad_type"}
#   同时列出导出目录里存在、但 config.json 里没有配置的群（configured=False），方便界面一键添加

plan(cfg, selection, window) -> Plan           # 相当于 dry-run，不调用 AI、不写 state
#   selection = [source key, ...]
#   window    = {"mode": "since_last"} | {"mode": "hours", "hours": 24} | {"mode": "all"}
#             | {"mode": "preset", "name": "daily"}
#   Plan = {sources: [{key, name, in_window, pending, chars, batches, warnings}], total_batches, est_tokens}

run(cfg, plan, on_progress, cancel) -> RunResult
#   on_progress(event)  event = {stage, source_key, batch, total_batches, message}
#   cancel: threading.Event；被取消时已花费的结果仍然保留，不推进 state
#   RunResult = {report_path, sources: [{key, status, items, error}], failures}

test_connection(cfg) -> {ok, model, message}   # 用最小请求验证 Key、模型和余额
list_reports(cfg) -> list[{path, title, created, size}]
read_report(path) -> str                       # 只允许读取配置的报告目录内的文件
```

- 现有的 state 语义（`since_last` 增量、`seen` 去重、`--hours` 和 `--preset` 不推进进度）**保持不变**
- 费用只显示**预估 token 数和调用次数**。价格可以在配置里填 `price_per_million_tokens`（可选），**不写死价格**，因为模型价格会变

## 5. HTTP 接口约定（app.py）
所有接口都以 `/api/` 开头，返回 JSON。出错时返回 `{"error": "中文说明", "field": 可选}`。

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/status` | 版本、配置是否完整（决定是否进入向导）、当前是否有任务在运行 |
| GET / PUT | `/api/config` | 读写配置。**返回时 api_key 打码**（只显示后 4 位）；PUT 时如果 Key 字段是打码值，就保留原 Key |
| POST | `/api/groups` · DELETE `/api/groups/{id}` · PATCH `/api/groups/{id}` | 添加 / 移除群；修改类型（对应四项操作 1、2） |
| PUT | `/api/focus` | `{profile?, explain_level?}`（对应操作 3） |
| PUT · DELETE | `/api/topics/{type}/categories/{name}` | 新增或修改 / 删除分类（对应操作 3） |
| POST | `/api/config/validate` | 只校验不保存 |
| POST | `/api/test-connection` | 测试 AI 连接 |
| GET | `/api/sources` | 扫描导出目录 |
| POST | `/api/plan` | 预估 `{selection, window}` |
| POST | `/api/run` | 开始任务，返回 `{job_id}`。**同一时间只允许一个任务** |
| GET | `/api/jobs/{id}` | 任务进度，前端每秒轮询一次 |
| POST | `/api/jobs/{id}/cancel` | 取消任务 |
| GET | `/api/reports` | 历史报告列表 |
| GET | `/api/reports/{name}` | 报告原文（Markdown） |
| POST | `/api/import` | 拖入文件：复制到导出目录 |

**安全要求（必须做到）**
1. 只监听 `127.0.0.1`。端口用 0，由系统分配，启动后自动打开浏览器，从此不再有端口冲突
2. 启动时生成随机 token，通过网址传给页面；之后每个请求都必须带上 `X-Token` 请求头，否则拒绝。同时校验 `Host` 头，防止其他网站冒充本页面调用接口
3. **报告内容不可信**（来自群聊），前端渲染 Markdown 时**必须先转义 HTML**，链接只允许 `http(s)`
4. 读写文件只限配置的目录，防止通过 `../` 访问别的文件
5. 日志和错误信息里不能出现 API Key

## 6. 界面
1. **首次启动向导**（配置不完整时自动进入）：AI 服务和测试连接 → 关于你 → 选择群（来自 `/api/sources`）→ 完成并试运行
2. **主页**：完成第 2.1 节的四项高频操作；显示预估；点"生成快报"后显示进度条和取消按钮
3. **快报**：历史列表 + 阅读视图（本地渲染 Markdown）
4. **设置**：低频项（AI 服务、路径、预设、报告格式开关）；当场校验

## 7. 开发阶段与分工

| 阶段 | 内容 | 负责 | 审查 | 验收标准 |
|---|---|---|---|---|
| **0** | 确定本文 | Claude 起草 | Codex + 项目所有者 | 合并到 main |
| **1** | 拆出 `digest_core.py`，`digest.py` 改为调用核心；实现第 2.1 节的四项操作函数 | Claude | Codex | 现有 12 个测试全部通过；命令行输出和报告格式不变；四项操作函数都有测试（包括非法输入不会写坏 config.json） |
| **2a** | `app.py`：接口、任务、安全 | Claude | Codex | 接口测试覆盖第 5 节；没有 token 的请求被拒绝 |
| **2b** | 界面原型：主页（含四项操作）+ 快报页，**先接假数据** | Codex | Claude | 能和 2a 并行开发；按第 5 节的 JSON 格式写假数据；四项操作都不超过 2 次点击 |
| **3** | 接通真实接口；向导 + 设置页 | Codex | Claude | 新用户全流程不碰 JSON |
| **4** | pywebview 窗口 + PyInstaller 文件夹模式打包脚本、README 更新、v2.0.0 Release（exe 版 + 源码版） | Claude | Codex | 在一台干净的 Windows 10/11 上，解压后双击 exe 能打开窗口并生成快报；没有 WebView2 时能退回浏览器 |

## 8. 协作规则
1. **一个阶段一个分支**：`feat/gui-<阶段>-<简述>`，例如 `feat/gui-1-core`。完成后提 PR，由另一方审查，项目所有者合并
2. **同一时间同一个文件只有一方在改**。2a 和 2b 并行时，Claude 只改 `app.py`，Codex 只改 `ui/`
3. 第 4、5 节的接口是双方的约定。想改接口，先单独提 PR 改本文，不在功能 PR 里顺手改
4. 每个 PR 必须做到：`python -m unittest discover -s tests` 通过；`python -m py_compile` 通过；不新增第三方依赖；不提交 `config.json`、`state.json`、报告或真实聊天记录
5. 改了用户可见的行为，要同步更新 `README.md`、`README.zh-CN.md` 和 `docs/faq*.md`
6. 审查时只报告**能复现的问题**，要附上输入和"实际结果 vs 预期结果"

## 9. 本版不做
- 读取或解密 QQ 数据、接入 QQ 协议
- 定时自动运行（因为导出这一步仍然要手动做）
- 多用户、云端同步、账号系统
- 代码签名（以后再考虑）
