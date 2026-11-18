(() => {
  const $ = id => document.getElementById(id);
  const request = window.demoRequest;
  const formats = { daily: "最近 24 小时", weekly: "最近 7 天" };
  let config;
  let sources = [];
  let selection = new Set();
  let topic = "study";
  let windowChoice = "daily";
  let currentPlan;
  let estimateVersion = 0;
  let activeJob;
  let pollTimer;
  let activeReport;
  let reportVersion = 0;

  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  }

  function button(text, action, className = "text-button") {
    const element = node("button", text, className);
    element.type = "button";
    element.addEventListener("click", action);
    return element;
  }

  function message(target, content = "", error = false) {
    target.textContent = content;
    target.hidden = !content;
    target.classList.toggle("error", error);
  }

  async function perform(target, action) {
    try { await action(); }
    catch (error) { message(target, error.message, true); }
  }

  function topicOptions(select, selected) {
    select.replaceChildren(...Object.entries(config.topics).map(([key, entry]) => new Option(entry.label, key)));
    select.value = selected;
  }

  async function loadSources() {
    sources = await request("GET", "/api/sources");
    const available = new Set(sources.filter(source => source.configured && source.status === "ok").map(source => source.key));
    selection = new Set([...selection].filter(key => available.has(key)));
    renderSources();
    await estimate();
  }

  function renderSources() {
    const current = sources.filter(source => source.configured);
    const discovered = sources.filter(source => !source.configured);
    $("groups").replaceChildren(...current.map(sourceRow));
    if (!current.length) $("groups").append(node("p", "添加一个群聊来源后即可开始。", "field-message"));
    $("discovered-list").replaceChildren(...discovered.map(sourceRow));
    $("discovered").hidden = !discovered.length;
    renderSelection();
  }

  function renderSelection() {
    const count = sources.filter(source => source.configured && source.status === "ok").length;
    $("selection-count").textContent = `已选 ${selection.size} 个群 · ${count} 个可用来源`;
  }

  function sourceRow(source) {
    const row = node("div", undefined, "source-row");
    const details = node("span", undefined, "source-details");
    const fileName = source.file?.split(/[\\/]/).at(-1);
    details.append(node("strong", source.name), node("small", fileName || "还没有导出文件"));
    const status = node("p", undefined, "field-message row-message");
    status.setAttribute("role", "status");
    status.hidden = true;

    if (source.configured) {
      const label = node("label", undefined, "source-label");
      const check = node("input");
      check.type = "checkbox";
      check.checked = selection.has(source.key);
      check.disabled = source.status !== "ok";
      check.setAttribute("aria-label", `选择${source.name}`);
      check.addEventListener("change", () => {
        if (check.checked) selection.add(source.key);
        else selection.delete(source.key);
        renderSelection();
        estimate();
      });
      label.append(check, details);
      const select = node("select");
      select.setAttribute("aria-label", `${source.name}的群类型`);
      topicOptions(select, source.type);
      select.addEventListener("change", () => perform(status, async () => {
        const previous = source.type;
        try { await request("PATCH", `/api/groups/${source.group_id}`, { type: select.value }); }
        catch (error) { select.value = previous; throw error; }
        source.type = select.value;
        topic = select.value;
        renderFocus();
        message(status, "已保存。");
        await estimate();
      }));
      const remove = button("移除", () => perform(status, async () => {
        await request("DELETE", `/api/groups/${source.group_id}`);
        await loadSources();
        message($("source-message"), `已移除「${source.name}」。`);
      }));
      remove.setAttribute("aria-label", `移除${source.name}`);
      row.append(label, select, remove);
    } else {
      const add = button("＋ 添加", () => perform(status, async () => {
        await request("POST", "/api/groups", { id: source.group_id, name: source.name, type: topic });
        selection.add(source.key);
        await loadSources();
        message($("source-message"), `已添加「${source.name}」。`);
      }), "button");
      add.setAttribute("aria-label", `添加${source.name}`);
      row.append(details, add);
    }
    row.append(status);
    return row;
  }

  function setCategoryForm(open) {
    $("category-form").hidden = !open;
    $("show-category").setAttribute("aria-expanded", String(open));
    if (open) $("category-name").focus();
    else $("category-form").reset();
  }

  function categoryPath(name) {
    return `/api/topics/${encodeURIComponent(topic)}/categories/${encodeURIComponent(name)}`;
  }

  function renderFocus() {
    topicOptions($("topic"), topic);
    const categories = Object.entries(config.topics[topic]?.categories || {});
    $("categories").replaceChildren(...categories.map(([name, description]) => {
      const chip = node("span", name, "chip");
      chip.title = description;
      const remove = button("×", () => perform($("category-message"), async () => {
        config = await request("DELETE", categoryPath(name));
        renderFocus();
        $("show-category").focus();
        message($("category-message"), `已删除「${name}」。`);
      }), "");
      remove.setAttribute("aria-label", `删除分类 ${name}`);
      chip.append(remove);
      return chip;
    }));
    if (!categories.length) $("categories").append(node("p", "暂未添加分类。", "field-message"));
    for (const item of $("explain").querySelectorAll("button")) {
      item.setAttribute("aria-pressed", String(item.dataset.level === config.explain_level));
    }
  }

  function readWindow() {
    if (windowChoice === "custom") {
      const value = $("window-value").valueAsNumber;
      return { mode: "hours", hours: value * ($("window-unit").value === "days" ? 24 : 1) };
    }
    if (windowChoice === "since_last") return { mode: "since_last" };
    return { mode: "preset", name: windowChoice };
  }

  function renderWindow() {
    $("custom-window").hidden = windowChoice !== "custom";
    for (const control of $("windows").querySelectorAll("button")) {
      const name = control.dataset.window;
      control.setAttribute("aria-pressed", String(name === windowChoice));
      if (formats[name]) control.textContent = formats[name];
    }
  }

  function setRunEnabled() {
    $("run").disabled = Boolean(activeJob) || !(currentPlan?.total_batches > 0);
  }

  async function estimate() {
    const version = ++estimateVersion;
    currentPlan = undefined;
    setRunEnabled();
    message($("window-message"));
    message($("estimate-message"));
    for (const name of ["messages", "batches", "tokens"]) $(`estimate-${name}`).textContent = "—";
    try {
      const plan = await request("POST", "/api/plan", { selection: [...selection], window: readWindow() });
      if (version !== estimateVersion) return;
      currentPlan = plan;
      $("estimate-messages").textContent = plan.sources.reduce((total, row) => total + row.pending, 0).toLocaleString("zh-CN");
      $("estimate-batches").textContent = plan.total_batches.toLocaleString("zh-CN");
      $("estimate-tokens").textContent = plan.est_tokens.toLocaleString("zh-CN");
    } catch (error) {
      if (version !== estimateVersion) return;
      const target = error.field === "window" ? $("window-message") : $("estimate-message");
      message(target, error.message, error.field !== "selection");
    }
    setRunEnabled();
  }

  async function importFiles(files) {
    message($("source-message"));
    let added = 0;
    const errors = [];
    for (const file of files) {
      try { await request("POST", "/api/import", { name: file.name, size: file.size }); added++; }
      catch (error) { errors.push(error.message); }
    }
    await loadSources();
    message($("source-message"), [added ? `已模拟导入 ${added} 个文件。` : "", ...new Set(errors)].filter(Boolean).join(" "), Boolean(errors.length));
  }

  function showJob(job) {
    $("job").hidden = false;
    $("job-status").textContent = job.message;
    $("progress").max = job.total_batches || 1;
    $("progress").value = job.batch || 0;
    $("cancel").hidden = job.status !== "running";
    $("job-report").hidden = !job.report_path;
    if (job.status === "running") return;
    clearTimeout(pollTimer);
    activeJob = undefined;
    if (job.report_path) activeReport = job.report_path;
    setRunEnabled();
    if (location.hash === "#reports") perform($("global-message"), loadReports);
  }

  async function poll() {
    const id = activeJob;
    if (!id) return;
    try {
      const job = await request("GET", `/api/jobs/${id}`);
      if (id !== activeJob) return;
      showJob(job);
      if (activeJob) pollTimer = setTimeout(poll, 1000);
    } catch (error) {
      showJob({ status: "failed", message: error.message });
    }
  }

  function appendInline(parent, text) {
    const pattern = /\*\*([^*]+)\*\*|\[([^\]]+)\]\(([^)]+)\)|<(https?:\/\/[^>\s]+)>|\*([^*]+)\*/g;
    let offset = 0;
    for (const match of text.matchAll(pattern)) {
      parent.append(text.slice(offset, match.index));
      if (match[1]) parent.append(node("strong", match[1]));
      else if (match[5]) parent.append(node("em", match[5]));
      else {
        const href = match[3] || match[4];
        if (/^https?:\/\/[^\s]+$/i.test(href)) {
          try {
            const link = node("a", match[2] || href);
            link.href = new URL(href).href;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            parent.append(link);
          } catch { parent.append(match[0]); }
        } else parent.append(match[0]);
      }
      offset = match.index + match[0].length;
    }
    parent.append(text.slice(offset));
  }

  function markdown(content) {
    const fragment = document.createDocumentFragment();
    let list;
    for (const line of content.split(/\r?\n/)) {
      const bullet = /^[-*] (.+)$/.exec(line);
      if (bullet) {
        if (!list) { list = node("ul"); fragment.append(list); }
        const item = node("li");
        appendInline(item, bullet[1]);
        list.append(item);
        continue;
      }
      list = undefined;
      if (!line.trim()) continue;
      if (/^\s*---\s*$/.test(line)) { fragment.append(node("hr")); continue; }
      const heading = /^(#{1,6}) (.+)$/.exec(line);
      const quote = /^>\s?(.*)$/.exec(line);
      const element = node(heading ? `h${heading[1].length}` : quote ? "blockquote" : "p");
      appendInline(element, heading?.[2] ?? quote?.[1] ?? line);
      fragment.append(element);
    }
    return fragment;
  }

  async function showReport(path) {
    activeReport = path;
    const version = ++reportVersion;
    for (const item of $("report-list").querySelectorAll("button")) {
      item.setAttribute("aria-current", String(item.dataset.path === path));
    }
    const name = path.split(/[\\/]/).at(-1);
    const report = await request("GET", `/api/reports/${encodeURIComponent(name)}`);
    if (version === reportVersion) $("report-content").replaceChildren(markdown(report.markdown));
  }

  async function loadReports() {
    const reports = await request("GET", "/api/reports");
    $("report-list").replaceChildren(...reports.map(report => {
      const item = button(report.title, () => perform($("global-message"), () => showReport(report.path)), "history-button");
      const date = new Date(report.created * 1000).toLocaleString("zh-CN", { dateStyle: "medium", timeStyle: "short" });
      item.append(node("small", date));
      item.dataset.path = report.path;
      return item;
    }));
    const report = reports.find(entry => entry.path === activeReport) || reports[0];
    if (report) await showReport(report.path);
    else $("report-content").replaceChildren(node("p", "还没有生成快报。"));
  }

  function navigate() {
    const showReports = location.hash === "#reports";
    $("home-view").hidden = showReports;
    $("reports-view").hidden = !showReports;
    $(showReports ? "reports-link" : "home-link").setAttribute("aria-current", "page");
    $(showReports ? "home-link" : "reports-link").removeAttribute("aria-current");
    message($("global-message"));
    if (showReports) perform($("global-message"), loadReports);
  }

  function bindControls() {
    window.addEventListener("hashchange", navigate);
    $("import-input").addEventListener("change", event => {
      perform($("source-message"), () => importFiles([...event.target.files]));
      event.target.value = "";
    });
    const drop = $("import-zone");
    drop.addEventListener("dragover", event => { event.preventDefault(); drop.classList.add("dragging"); });
    drop.addEventListener("dragleave", () => drop.classList.remove("dragging"));
    drop.addEventListener("drop", event => {
      event.preventDefault();
      drop.classList.remove("dragging");
      perform($("source-message"), () => importFiles([...event.dataTransfer.files]));
    });
    $("profile").addEventListener("change", () => perform($("profile-message"), async () => {
      const updated = await request("PUT", "/api/focus", { profile: $("profile").value });
      config.profile = updated.profile;
      $("profile").value = updated.profile;
      message($("profile-message"), "已保存。");
    }));
    $("topic").addEventListener("change", event => {
      topic = event.target.value;
      message($("category-message"));
      setCategoryForm(false);
      renderFocus();
    });
    $("show-category").addEventListener("click", () => setCategoryForm(true));
    $("hide-category").addEventListener("click", () => { setCategoryForm(false); $("show-category").focus(); });
    $("category-form").addEventListener("submit", event => {
      event.preventDefault();
      perform($("category-message"), async () => {
        const name = $("category-name").value.trim();
        if (!name) throw new Error("请输入分类名。");
        config = await request("PUT", categoryPath(name), { description: $("category-description").value });
        setCategoryForm(false);
        renderFocus();
        $("show-category").focus();
        message($("category-message"), `已保存「${name}」。`);
      });
    });
    $("explain").addEventListener("click", event => {
      const level = event.target.dataset.level;
      if (!level) return;
      perform($("explain-message"), async () => {
        const updated = await request("PUT", "/api/focus", { explain_level: level });
        config.explain_level = updated.explain_level;
        renderFocus();
        message($("explain-message"), "已保存。");
      });
    });
    $("windows").addEventListener("click", event => {
      if (!event.target.dataset.window) return;
      windowChoice = event.target.dataset.window;
      renderWindow();
      estimate();
      if (windowChoice === "custom") $("window-value").focus();
    });
    $("custom-window").addEventListener("submit", event => event.preventDefault());
    $("custom-window").addEventListener("input", estimate);
    $("save-default").addEventListener("click", () => perform($("window-message"), async () => {
      await request("PUT", "/api/config", { selection: [...selection], window: readWindow() });
      message($("window-message"), "已保存本次群聊选择和时间范围为默认。");
    }));
    $("run").addEventListener("click", () => perform($("estimate-message"), async () => {
      if (!currentPlan || activeJob) return;
      $("run").disabled = true;
      try {
        const { job_id } = await request("POST", "/api/run", { selection: currentPlan.selection, window: currentPlan.window });
        activeJob = job_id;
        await poll();
      } finally { setRunEnabled(); }
    }));
    $("cancel").addEventListener("click", () => perform($("estimate-message"), async () => {
      if (!activeJob) return;
      showJob(await request("POST", `/api/jobs/${activeJob}/cancel`));
    }));
  }

  perform($("global-message"), async () => {
    config = await request("GET", "/api/config");
    topic = Object.hasOwn(config.topics, topic) ? topic : Object.keys(config.topics)[0];
    selection = new Set(config.selection);
    windowChoice = config.window.name || (config.window.mode === "hours" ? "custom" : config.window.mode);
    if (windowChoice === "custom") $("window-value").value = config.window.hours;
    $("profile").value = config.profile;
    renderFocus();
    renderWindow();
    bindControls();
    await loadSources();
    navigate();
  });
})();
