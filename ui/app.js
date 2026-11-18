(() => {
  const $ = id => document.getElementById(id);
  let token;
  let config;
  let sources = [];
  let selection = new Set();
  let topic = "study";
  let windowChoice = "since_last";
  let savedPreset;
  let savingDefaults = false;
  let currentPlan;
  let estimateVersion = 0;
  let activeJob;
  let starting = false;
  let pollTimer;
  let jobCursor = 0;
  let cancelling = false;
  let jobMessage = "";
  let pendingImports = [];
  let activeReportId;
  let pendingReportPath;
  let reportVersion = 0;

  function loadToken() {
    const url = new URL(location.href);
    const key = "qq-group-digest-token";
    const supplied = url.searchParams.get("token");
    try {
      if (supplied) sessionStorage.setItem(key, supplied);
      return supplied || sessionStorage.getItem(key);
    } catch { return supplied; }
    finally {
      if (supplied) {
        url.searchParams.delete("token");
        history.replaceState(null, "", url);
      }
    }
  }

  async function request(method, path, data, file) {
    if (!token) throw new Error("请用启动窗口显示的本机网址打开页面。");
    const headers = { "X-Token": token };
    let body;
    if (file) {
      headers["Content-Type"] = "application/octet-stream";
      headers["X-Filename"] = encodeURIComponent(file.name);
      body = file;
    } else if (data !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(data);
    }
    let response;
    try { response = await fetch(path, { method, headers, body, cache: "no-store", redirect: "error" }); }
    catch { throw new Error("无法连接本机服务，请确认启动窗口仍在运行。"); }
    const result = await response.json().catch(() => null);
    if (response.status === 401 || response.status === 403) throw new Error("本机访问授权已失效，请重新打开启动窗口显示的网址。");
    if (!response.ok) throw Object.assign(new Error(result?.error || `本机服务返回错误（${response.status}）。`), {
      status: response.status, field: result?.field,
    });
    if (!result) throw new Error("本机服务返回了无法识别的数据。");
    return result;
  }

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

  async function loadSources(initialSelection) {
    ({ sources } = await request("GET", "/api/sources"));
    const configured = new Set(sources.filter(source => source.configured).map(source => source.key));
    const wanted = initialSelection === null ? configured : (initialSelection ?? selection);
    selection = new Set([...wanted].filter(key => configured.has(key)));
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
        const next = select.value;
        select.disabled = true;
        try { config = await request("PATCH", `/api/groups/${encodeURIComponent(source.group_id)}`, { type: next }); }
        catch (error) { select.value = previous; throw error; }
        finally { select.disabled = false; }
        source.type = next;
        topic = next;
        renderFocus();
        message(status, "已保存。");
        await estimate();
      }));
      const remove = button("移除", () => perform(status, async () => {
        config = await request("DELETE", `/api/groups/${encodeURIComponent(source.group_id)}`);
        await loadSources();
        message($("source-message"), `已移除「${source.name}」。`);
      }));
      remove.setAttribute("aria-label", `移除${source.name}`);
      row.append(label, select, remove);
    } else {
      const add = button("＋ 添加", () => perform(status, async () => {
        config = await request("POST", "/api/groups", { group_id: source.group_id, name: source.name, type: topic });
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
    if (windowChoice === "since_last" || windowChoice === "all") return { mode: windowChoice };
    return { mode: "preset", name: windowChoice === "saved-preset" ? savedPreset : windowChoice };
  }

  function restoreWindow(window) {
    if (window?.mode === "all" || window?.mode === "since_last") windowChoice = window.mode;
    else if (window?.mode === "hours" && validHours(window.hours)) {
      windowChoice = "custom";
      $("window-value").value = window.hours;
      $("window-unit").value = "hours";
    } else if (window?.mode === "preset" && Object.hasOwn(config.presets ?? {}, window.name)) {
      if (window.name === "daily" || window.name === "weekly") windowChoice = window.name;
      else {
        savedPreset = window.name;
        windowChoice = "saved-preset";
      }
    } else if (window) {
      message($("defaults-message"), "保存的时间范围已不可用，暂用「上次之后」。");
    }
  }

  function renderWindow() {
    $("custom-window").hidden = windowChoice !== "custom";
    for (const control of $("windows").querySelectorAll("button")) {
      const name = control.dataset.window;
      control.setAttribute("aria-pressed", String(name === windowChoice));
      if (name === "saved-preset") {
        control.hidden = !savedPreset;
        if (savedPreset) control.textContent = config.presets[savedPreset]?.title || savedPreset;
      }
      const hours = (name === "daily" || name === "weekly") && config.presets?.[name]?.hours;
      if (Number(hours) > 0) {
        const days = Number(hours) / 24;
        control.textContent = days > 1 && Number.isInteger(days) ? `最近 ${days} 天` : `最近 ${hours} 小时`;
      }
    }
  }

  function validHours(hours) {
    return Number.isFinite(hours) && hours > 0 && hours <= 100000;
  }

  function canSaveDefaults() {
    const window = readWindow();
    return Boolean(config.defaults) && (window.mode !== "hours" || validHours(window.hours));
  }

  function setRunEnabled() {
    $("run").disabled = starting || Boolean(activeJob) || !(currentPlan?.total_batches > 0);
  }

  async function estimate() {
    const version = ++estimateVersion;
    currentPlan = undefined;
    setRunEnabled();
    $("save-default").disabled = savingDefaults || !canSaveDefaults();
    message($("window-message"));
    message($("estimate-message"));
    for (const name of ["messages", "batches", "tokens"]) $(`estimate-${name}`).textContent = "—";
    const window = readWindow();
    if (window.mode === "hours" && !validHours(window.hours)) {
      message($("window-message"), "请输入大于 0 且不超过 100000 小时的时长。", true);
      return;
    }
    if (!sources.some(source => source.file && selection.has(source.key))) {
      message($("estimate-message"), "请至少选择一个有导出文件的群。");
      return;
    }
    try {
      const plan = await request("POST", "/api/plan", { selection: [...selection], window });
      if (version !== estimateVersion) return;
      currentPlan = plan;
      $("estimate-messages").textContent = plan.sources.reduce((total, row) => total + row.pending, 0).toLocaleString("zh-CN");
      $("estimate-batches").textContent = plan.total_batches.toLocaleString("zh-CN");
      $("estimate-tokens").textContent = plan.est_tokens.toLocaleString("zh-CN");
      const warnings = plan.sources.flatMap(row => [row.error, ...(row.warnings || [])].filter(Boolean).map(note => `${row.name}：${note}`));
      if (warnings.length) message($("estimate-message"), warnings.join("；"), plan.sources.some(row => row.error));
    } catch (error) {
      if (version !== estimateVersion) return;
      const target = error.field === "window" ? $("window-message") : $("estimate-message");
      message(target, error.message, error.field !== "selection");
    }
    setRunEnabled();
  }

  function showNextImport() {
    $("import-group").hidden = !pendingImports.length;
    if (!pendingImports.length) return;
    const file = pendingImports[0];
    $("import-group").reset();
    $("import-group-name").value = file.name.replace(/\.[^.]+$/, "").slice(0, 60);
    message($("source-message"), `请为「${file.name}」填写群号。`);
    $("import-group-id").focus();
  }

  async function uploadFile(file, params = new URLSearchParams()) {
    const query = new URLSearchParams(params);
    const upload = () => request("POST", `/api/import${query.size ? `?${query}` : ""}`, undefined, file);
    try { return await upload(); }
    catch (error) {
      if (error.status !== 409 || error.field !== "overwrite") throw error;
      if (!window.confirm(error.message)) return null;
      query.set("overwrite", "1");
      return upload();
    }
  }

  async function importFiles(files) {
    let added = 0;
    let skipped = 0;
    const errors = [];
    for (const file of files) {
      if (!/\.(csv|txt)$/i.test(file.name) || !file.size) {
        errors.push(`「${file.name}」须为非空的 CSV 或 TXT。`);
        continue;
      }
      if (!/^群_\d+_.*\.(csv|txt)$/i.test(file.name)) {
        pendingImports.push(file);
        continue;
      }
      try {
        if (await uploadFile(file)) added++;
        else skipped++;
      }
      catch (error) {
        if (error.field === "group_id") pendingImports.push(file);
        else errors.push(error.message);
      }
    }
    if (added) await loadSources();
    const summary = [added && `已导入 ${added} 个文件。`, skipped && `已保留 ${skipped} 个同名原文件。`, ...new Set(errors)];
    message($("source-message"), summary.filter(Boolean).join(" "), Boolean(errors.length));
    showNextImport();
  }

  function showJob(job) {
    $("job").hidden = false;
    jobCursor = job.next_event ?? jobCursor;
    const { batches_started: started = 0, total_batches: total = 0 } = job.progress || {};
    const reportPath = job.result?.report_path;
    const last = job.events?.at(-1)?.message?.trim();
    if (last) jobMessage = last;
    if (job.status === "running") {
      $("job-status").textContent = cancelling ? "正在取消，等待当前请求结束…" :
        (total && started ? `已开始 ${started} / ${total} 批` : jobMessage || "正在准备消息…");
    } else if (job.status === "cancelled") $("job-status").textContent = reportPath ? "已取消，部分结果已保存。" : "任务已取消。";
    else if (job.status === "failed") $("job-status").textContent = job.error || "生成失败。";
    else if (job.result?.failures?.length && reportPath) $("job-status").textContent = "快报已生成，部分群处理失败，详情见快报。";
    else $("job-status").textContent = reportPath ? "快报已生成。" : jobMessage || "没有生成新快报。";
    $("progress").max = total || 1;
    if (total) $("progress").value = job.status === "done" ? total : Math.min(started, total);
    else $("progress").removeAttribute("value");
    $("cancel").hidden = job.status !== "running";
    $("cancel").disabled = cancelling;
    $("job-report").hidden = !reportPath;
    if (job.status === "running") return;
    clearTimeout(pollTimer);
    activeJob = undefined;
    cancelling = false;
    if (reportPath) pendingReportPath = reportPath;
    setRunEnabled();
    if (location.hash === "#reports") perform($("global-message"), loadReports);
  }

  async function poll() {
    const id = activeJob;
    if (!id) return;
    try {
      const job = await request("GET", `/api/jobs/${encodeURIComponent(id)}?since=${jobCursor}`);
      if (id !== activeJob) return;
      message($("estimate-message"));
      showJob(job);
      if (activeJob) pollTimer = setTimeout(poll, 1000);
    } catch (error) {
      message($("estimate-message"), error.message, true);
      if (activeJob === id) pollTimer = setTimeout(poll, 2000);
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

  async function showReport(id) {
    activeReportId = id;
    const version = ++reportVersion;
    for (const item of $("report-list").querySelectorAll("button")) {
      item.setAttribute("aria-current", String(item.dataset.reportId === id));
    }
    const report = await request("GET", `/api/reports/${encodeURIComponent(id)}`);
    if (version === reportVersion) $("report-content").replaceChildren(markdown(report.markdown));
  }

  async function loadReports() {
    const { reports } = await request("GET", "/api/reports");
    $("report-list").replaceChildren(...reports.map(report => {
      const item = button(report.title, () => perform($("global-message"), () => showReport(report.id)), "history-button");
      const date = new Date(report.created * 1000).toLocaleString("zh-CN", { dateStyle: "medium", timeStyle: "short" });
      item.append(node("small", date));
      item.dataset.reportId = report.id;
      return item;
    }));
    const report = (pendingReportPath && reports.find(entry => entry.path === pendingReportPath)) ||
      reports.find(entry => entry.id === activeReportId) || reports[0];
    pendingReportPath = undefined;
    if (report) await showReport(report.id);
    else $("report-content").replaceChildren(node("p", "还没有生成快报。"));
  }

  function editSettings(firstRun = false) {
    const current = config.config;
    $("setup-note").hidden = !firstRun;
    $("settings-title").textContent = firstRun ? "首次设置" : "设置";
    $("api-url").value = current.deepseek?.base_url || "https://api.deepseek.com";
    $("api-model").value = current.deepseek?.model || "deepseek-flash";
    $("api-key").value = "";
    $("export-dir").value = current.export_dir || "";
    $("report-dir").value = current.report_dir || "";
    $("daily-hours").value = config.presets?.daily?.hours ?? 24;
    $("weekly-hours").value = config.presets?.weekly?.hours ?? 168;
    $("save-raw").checked = current.save_raw === true;
    message($("settings-message"));
    $("settings").showModal();
  }

  async function settingsConfig() {
    // Config replacement requires the complete current document, including fields the UI doesn't edit.
    const { config: { selection: _selection, window: _window, ...latest } } = await request("GET", "/api/config");
    const hours = { daily: $("daily-hours").valueAsNumber, weekly: $("weekly-hours").valueAsNumber };
    if (Object.values(hours).some(value => !(value > 0 && value <= 100000))) {
      throw new Error("快报小时数应大于 0 且不超过 100000。");
    }
    const key = $("api-key").value.trim();
    const baseUrl = $("api-url").value.trim();
    const { api_key: oldKey, ...provider } = latest.deepseek || {};
    const savedUrl = provider.base_url || "https://api.deepseek.com";
    const keepKey = baseUrl.replace(/\/+$/, "") === savedUrl.replace(/\/+$/, "");
    const apiKey = key || (keepKey ? oldKey : undefined);
    return { ...latest, profile: latest.profile ?? "", groups: latest.groups ?? [], deepseek: {
      ...provider, base_url: baseUrl, model: $("api-model").value.trim(),
      ...(apiKey !== undefined ? { api_key: apiKey } : {}),
    }, export_dir: $("export-dir").value.trim(), report_dir: $("report-dir").value.trim(),
    save_raw: $("save-raw").checked, presets: {
      ...latest.presets, daily: { ...latest.presets?.daily, hours: hours.daily },
      weekly: { ...latest.presets?.weekly, hours: hours.weekly },
    } };
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
    $("open-settings").addEventListener("click", () => editSettings());
    $("close-settings").addEventListener("click", () => $("settings").close());
    $("settings-form").addEventListener("submit", event => {
      event.preventDefault();
      const submission = event.submitter;
      submission.disabled = true;
      perform($("settings-message"), async () => {
        try {
          config = await request("PUT", "/api/config", await settingsConfig());
          $("settings-form").reset();
          $("settings").close();
          renderWindow();
          renderFocus();
          await loadSources();
          if (location.hash === "#reports") await loadReports();
          else message($("source-message"), "设置已保存。可在此导入并添加群聊。");
        } finally { submission.disabled = false; }
      });
    });
    $("test-connection").addEventListener("click", () => {
      if (!$("settings-form").reportValidity()) return;
      $("test-connection").disabled = true;
      message($("settings-message"), "正在测试连接…");
      perform($("settings-message"), async () => {
        try {
          const result = await request("POST", "/api/test-connection", await settingsConfig());
          message($("settings-message"), result.message, !result.ok);
        } finally { $("test-connection").disabled = false; }
      });
    });
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
    $("cancel-import").addEventListener("click", () => {
      pendingImports.shift();
      message($("source-message"), "已跳过该文件。");
      showNextImport();
    });
    $("import-group").addEventListener("submit", event => {
      event.preventDefault();
      const file = pendingImports[0];
      if (!file) return;
      const query = new URLSearchParams({ group_id: $("import-group-id").value.trim(), name: $("import-group-name").value.trim() });
      const submit = event.submitter;
      submit.disabled = true;
      perform($("source-message"), async () => {
        try {
          const result = await uploadFile(file, query);
          pendingImports.shift();
          if (result) await loadSources();
          message($("source-message"), result ? `已导入「${result.saved}」。` : "已保留同名原文件。");
          showNextImport();
        } finally { submit.disabled = false; }
      });
    });
    $("profile").addEventListener("change", () => perform($("profile-message"), async () => {
      const updated = await request("PUT", "/api/focus", { profile: $("profile").value });
      config = updated;
      $("profile").value = updated.config.profile || "";
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
        config = updated;
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
    $("save-default").addEventListener("click", () => perform($("defaults-message"), async () => {
      if (savingDefaults || !canSaveDefaults()) return;
      const payload = { selection: [...selection], window: readWindow() };
      savingDefaults = true;
      $("save-default").disabled = true;
      message($("defaults-message"), "正在保存…");
      try {
        const view = await request("PUT", "/api/defaults", payload);
        config.defaults = view.defaults;
        message($("defaults-message"), "已保存，下次打开界面时会恢复这次选择。");
      } finally {
        savingDefaults = false;
        $("save-default").disabled = !canSaveDefaults();
      }
    }));
    $("run").addEventListener("click", () => perform($("estimate-message"), async () => {
      if (!currentPlan || activeJob || starting) return;
      starting = true;
      setRunEnabled();
      try {
        const { job_id } = await request("POST", "/api/run", { selection: currentPlan.selection, window: currentPlan.window });
        activeJob = job_id;
        jobCursor = 0;
        jobMessage = "";
        await poll();
      } finally { starting = false; setRunEnabled(); }
    }));
    $("cancel").addEventListener("click", () => perform($("estimate-message"), async () => {
      if (!activeJob || cancelling) return;
      const id = activeJob;
      $("cancel").disabled = true;
      try {
        await request("POST", `/api/jobs/${encodeURIComponent(id)}/cancel`);
        if (activeJob === id) {
          cancelling = true;
          $("job-status").textContent = "正在取消，等待当前请求结束…";
        }
      } finally { $("cancel").disabled = cancelling; }
    }));
  }

  perform($("global-message"), async () => {
    token = loadToken();
    const status = await request("GET", "/api/status");
    config = await request("GET", "/api/config");
    restoreWindow(config.defaults?.window);
    if (!config.defaults) message($("defaults-message"), "当前本机服务尚未提供保存默认的接口。");
    const defaultsWarnings = config.issues?.filter(issue => issue.field === "ui_defaults" && issue.level === "warning");
    if (defaultsWarnings?.length) message($("defaults-message"), defaultsWarnings.map(issue => issue.message).join(" "));
    topic = Object.hasOwn(config.topics, topic) ? topic : Object.keys(config.topics)[0];
    $("profile").value = config.config.profile || "";
    activeJob = status.running_job || undefined;
    renderFocus();
    renderWindow();
    bindControls();
    await loadSources(config.defaults?.selection ?? null);
    navigate();
    if (activeJob) await poll();
    if (!status.config_exists) editSettings(true);
  });
})();
