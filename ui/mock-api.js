/* In-browser stand-in for the routes defined in docs/gui-plan.md §5. */
window.demoRequest = (() => {
  const day = 86400000;
  const now = Date.now();
  const settings = {
    profile: "大二，关注高数作业和暑期实习。",
    explain_level: "brief",
    topics: {
      study: { label: "学习群", categories: { "考试与作业通知": "考试和作业期限", "学习资料": "课件和复习资料", "竞赛与加分": "报名与加分安排" } },
      opensource: { label: "技术群", categories: { "AI新动态": "模型和工具更新", "开源知识": "开源项目和教程", "赚钱机会": "实习和兼职" } },
    },
    presets: { daily: { hours: 24 }, weekly: { hours: 168 } },
    selection: ["group:102938", "group:204875"],
    window: { mode: "preset", name: "daily" },
  };
  const source = (group_id, name, type, file, configured, count) => ({
    key: `group:${group_id}`, group_id, name, type, file,
    file_mtime: file ? now / 1000 : null, configured,
    status: configured ? (file ? "ok" : "missing") : "unconfigured", count,
  });
  const sources = [
    source("102938", "高数学习群", "study", "群_102938_高数学习群.csv", true, 48),
    source("204875", "开源与 AI 交流", "opensource", "群_204875_开源与AI交流.txt", true, 75),
    source("368250", "竞赛报名群", "study", null, true, 0),
    source("489012", "计算机二班", null, "群_489012_计算机二班.csv", false, 30),
  ];
  const examples = {
    study: "### 考试与作业通知\n\n高数作业周五晚上八点截止。\n\n> 原文 · 小林：这次高数作业周五晚上八点交。\n\n- 复习范围见 [课程资料](https://example.com/study)。",
    opensource: "### AI新动态\n\n群里分享了一个用于整理学习笔记的开源工具。\n\n> 原文 · 小周：工具支持把笔记导出为 Markdown。",
  };
  const reports = [];
  const jobs = new Map();
  const copy = value => JSON.parse(JSON.stringify(value));
  const fail = (message, field) => { throw Object.assign(new Error(message), { field }); };

  function addReport(title, rows, created, partial = false) {
    const date = new Date(created).toLocaleDateString("zh-CN");
    const sections = rows.map(row => `## ${row.name}\n\n${examples[row.type] || "本次暂无分类示例。"}`);
    const markdown = [`# ${title} · ${date}`, partial ? "本次任务已取消，以下是已完成的部分。" : "群聊摘录和关键消息。", ...sections].join("\n\n---\n\n");
    const path = `快报_${created}_${reports.length + 1}.md`;
    reports.unshift({ path, title, created: created / 1000, size: new Blob([markdown]).size, markdown });
    return path;
  }

  addReport("本周快报", sources.slice(0, 2), now - 3 * day);
  addReport("今日快报", sources.slice(0, 1), now - day);

  const storageKey = "qq-group-digest-ui-demo-v1";
  try {
    const stored = JSON.parse(localStorage.getItem(storageKey));
    if (stored?.settings && Array.isArray(stored.sources) && Array.isArray(stored.reports)) {
      Object.assign(settings, stored.settings);
      sources.splice(0, sources.length, ...stored.sources);
      reports.splice(0, reports.length, ...stored.reports);
    }
  } catch { /* The demo also runs in browsers that disable file URL storage. */ }

  function persist() {
    try { localStorage.setItem(storageKey, JSON.stringify({ settings, sources, reports })); }
    catch { /* Keep the current session usable when browser storage is unavailable. */ }
  }

  function estimate({ selection, window }) {
    let hours;
    switch (window.mode) {
      case "preset": hours = settings.presets[window.name]?.hours; break;
      case "hours": hours = window.hours; break;
      case "since_last": hours = 12; break;
      case "all": hours = 336; break;
      default: fail("请选择时间范围。", "window");
    }
    if (!Number.isFinite(hours) || hours <= 0 || hours > 8760) fail("请输入 1 年以内的正数时长。", "window");
    const picked = sources.filter(row => selection.includes(row.key) && row.configured && row.status === "ok");
    if (!picked.length) fail("请至少选择一个有导出文件的群。", "selection");
    const planned = picked.map(row => {
      const pending = Math.max(1, Math.round(row.count * Math.min(hours, 336) / 24));
      return { key: row.key, name: row.name, in_window: pending + 2, pending, chars: pending * 124, batches: Math.ceil(pending / 85), warnings: [] };
    });
    return { selection: [...selection], window: copy(window), sources: planned,
      total_batches: planned.reduce((total, row) => total + row.batches, 0),
      est_tokens: Math.round(planned.reduce((total, row) => total + row.chars, 0) * 0.65) };
  }

  function readJob(job) {
    if (job.status === "running") {
      job.batch = Math.min(job.total_batches, Math.floor((Date.now() - job.started) / 1700));
      if (job.batch === job.total_batches) {
        job.status = "done";
        job.report_path = addReport("群聊快报", job.rows, Date.now());
        job.message = "快报已生成。";
        persist();
      } else {
        job.message = `正在整理第 ${job.batch + 1} / ${job.total_batches} 批`;
      }
    }
    return { id: job.id, status: job.status, batch: job.batch, total_batches: job.total_batches,
      message: job.message, report_path: job.report_path };
  }

  return async function request(method, path, data) {
    if (path === "/api/status" && method === "GET") {
      return { version: "2.0-demo", configured: true, running: [...jobs.values()].some(job => job.status === "running") };
    }
    if (path === "/api/config") {
      if (method === "PUT") {
        estimate(data);
        settings.selection = [...data.selection];
        settings.window = copy(data.window);
        persist();
      }
      return copy(settings);
    }
    if (path === "/api/sources" && method === "GET") return copy(sources);
    if (path === "/api/import" && method === "POST") {
      const match = /^(?:群_(\d+)_)?(.+)\.(csv|txt)$/i.exec(data.name);
      if (!match) fail("请选择 CSV 或 TXT 文件。", "file");
      const groupId = match[1] || String(500000 + sources.length);
      const existing = sources.find(row => row.group_id === groupId);
      if (existing) Object.assign(existing, { file: data.name, file_mtime: Date.now() / 1000, count: 30,
        status: existing.configured ? "ok" : "unconfigured" });
      else sources.push(source(groupId, match[2], null, data.name, false, 30));
      persist();
      return { name: data.name, key: `group:${groupId}` };
    }
    const groups = /^\/api\/groups(?:\/([^/]+))?$/.exec(path);
    if (groups) {
      const row = sources.find(item => item.group_id === (groups[1] || data?.id));
      if (!row) fail("找不到该群聊。", "group");
      if (method !== "DELETE" && !Object.hasOwn(settings.topics, data.type)) fail("请选择已有群类型。", "type");
      if (method === "DELETE") {
        row.configured = false;
        row.type = null;
        row.status = "unconfigured";
        settings.selection = settings.selection.filter(key => key !== row.key);
        if (!row.file) sources.splice(sources.indexOf(row), 1);
      } else {
        row.configured = true;
        row.type = data.type;
        row.status = row.file ? "ok" : "missing";
      }
      persist();
      return copy(settings);
    }
    if (path === "/api/focus" && method === "PUT") {
      if (data.profile !== undefined) {
        if (typeof data.profile !== "string" || data.profile.length > 1000) fail("个人情况最多填写 1000 字。", "profile");
        settings.profile = data.profile.trim();
      }
      if (data.explain_level !== undefined) {
        if (!["detailed", "brief", "off"].includes(data.explain_level)) fail("请选择解释程度。", "explain_level");
        settings.explain_level = data.explain_level;
      }
      persist();
      return copy(settings);
    }
    const categories = /^\/api\/topics\/([^/]+)\/categories\/([^/]+)$/.exec(path);
    if (categories) {
      const topic = decodeURIComponent(categories[1]);
      const name = decodeURIComponent(categories[2]).trim();
      const list = settings.topics[topic]?.categories;
      if (!list || !name || name.length > 30 || name === "其他有用") fail("请输入有效的分类名。", "name");
      if (method === "DELETE") {
        if (!Object.hasOwn(list, name)) fail("找不到该分类。", "name");
        delete list[name];
      } else {
        const description = data.description?.trim();
        if (!description || description.length > 160) fail("请输入 1 到 160 字的筛选说明。", "description");
        Object.defineProperty(list, name, { value: description, writable: true, enumerable: true, configurable: true });
      }
      persist();
      return copy(settings);
    }
    if (path === "/api/plan" && method === "POST") return estimate(data);
    if (path === "/api/run" && method === "POST") {
      if ([...jobs.values()].some(job => job.status === "running")) fail("已经有一份快报正在生成。", "job");
      const plan = estimate(data);
      const id = String(jobs.size + 1);
      const rows = sources.filter(row => plan.sources.some(item => item.key === row.key));
      jobs.set(id, { id, rows, started: Date.now(), status: "running", total_batches: plan.total_batches, batch: 0, report_path: null });
      return { job_id: id };
    }
    const task = /^\/api\/jobs\/([^/]+)(\/cancel)?$/.exec(path);
    if (task) {
      const job = jobs.get(task[1]);
      if (!job) fail("找不到生成任务。", "job");
      readJob(job);
      if (task[2] && method === "POST" && job.status === "running") {
        job.status = "cancelled";
        job.message = "任务已取消。";
        if (job.batch) {
          job.report_path = addReport("部分群聊快报", job.rows.slice(0, 1), Date.now(), true);
          persist();
        }
      }
      return readJob(job);
    }
    if (path === "/api/reports" && method === "GET") return reports.map(({ markdown, ...info }) => ({ ...info }));
    if (path.startsWith("/api/reports/") && method === "GET") {
      const pathName = decodeURIComponent(path.slice("/api/reports/".length));
      const report = reports.find(entry => entry.path === pathName);
      if (!report) fail("找不到这份快报。", "report");
      return { markdown: report.markdown };
    }
    fail("演示接口没有这个操作。");
  };
})();
