(() => {
  "use strict";

  const $ = id => document.getElementById(id);
  const enc = encodeURIComponent;
  const SVG_NS = "http://www.w3.org/2000/svg";
  const VIEWS = { "#home": "home", "#focus": "focus", "#reports": "reports" };
  const MAX_HOURS = 100000;

  const state = {
    token: undefined,
    config: undefined,          // GET /api/config 的视图
    view: undefined,            // 当前页面：home / focus / reports
    sources: [],
    selection: new Set(),
    newTypes: new Map(),        // 新发现的群：勾选前在行内选的类型
    lastType: undefined,
    windowChoice: "since_last", // since_last / all / custom / preset:<名字>
    windowError: "",
    plan: undefined,
    planError: "",
    estimating: false,
    estimateVersion: 0,
    estimateTimer: undefined,
    savingDefaults: false,
    job: { id: undefined, cursor: 0, starting: false, cancelling: false, message: "", timer: undefined },
    pendingImports: [],
    reports: [],
    activeReportId: undefined,
    pendingReportPath: undefined,
    reportVersion: 0,
    reportMarkdown: "",
    currentType: undefined,
    drag: null,
  };

  // ---------------------------------------------------------------- 本机服务

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
    if (!state.token) throw new Error("请用启动窗口显示的本机网址打开页面。");
    const headers = { "X-Token": state.token };
    let body;
    if (file) {
      headers["Content-Type"] = "application/octet-stream";
      headers["X-Filename"] = enc(file.name);
      body = file;
    } else if (data !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(data);
    }
    let response;
    try { response = await fetch(path, { method, headers, body, cache: "no-store", redirect: "error" }); }
    catch { throw new Error("连不上本机服务，请确认程序还开着。"); }
    const result = await response.json().catch(() => null);
    if (response.status === 401 || response.status === 403) throw new Error("本机访问授权失效了，请重新打开程序。");
    if (!response.ok) throw Object.assign(new Error(result?.error || `本机服务出错了（${response.status}）。`), {
      status: response.status, field: result?.field,
    });
    if (!result) throw new Error("本机服务返回了看不懂的数据。");
    return result;
  }

  // ---------------------------------------------------------------- 小工具

  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  }

  function icon(name, className = "icon") {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("class", className);
    svg.setAttribute("aria-hidden", "true");
    const use = document.createElementNS(SVG_NS, "use");
    use.setAttribute("href", `#i-${name}`);
    svg.append(use);
    return svg;
  }

  function button(text, action, className = "btn") {
    const element = node("button", text, className);
    element.type = "button";
    if (action) element.addEventListener("click", action);
    return element;
  }

  function iconButton(name, label, action, className = "btn btn-ghost btn-sm btn-icon") {
    const element = button("", action, className);
    element.append(icon(name));
    element.setAttribute("aria-label", label);
    element.title = label;
    return element;
  }

  function setHidden(element, hidden) { element.hidden = hidden; }

  function inlineMessage(target, text = "", kind = "") {
    target.textContent = text;
    target.hidden = !text;
    target.classList.toggle("error", kind === "error");
  }

  const num = value => Number(value).toLocaleString("zh-CN");
  const validHours = hours => Number.isFinite(hours) && hours > 0 && hours <= MAX_HOURS;

  function fmtTime(seconds) {
    if (!seconds) return "";
    const date = new Date(seconds * 1000);
    const now = new Date();
    const time = `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
    const dayStart = value => new Date(value.getFullYear(), value.getMonth(), value.getDate()).getTime();
    const days = Math.round((dayStart(now) - dayStart(date)) / 864e5);
    if (days === 0) return `今天 ${time}`;
    if (days === 1) return `昨天 ${time}`;
    const md = `${date.getMonth() + 1}月${date.getDate()}日`;
    return date.getFullYear() === now.getFullYear() ? `${md} ${time}` : `${date.getFullYear()}年${md} ${time}`;
  }

  function shortPeriod(period) {
    if (!period) return "";
    const year = String(new Date().getFullYear());
    return period.replace(/(\d{4})-(\d{2})-(\d{2}) (\d{2}:\d{2}):\d{2}/g,
      (_, y, m, d, t) => `${y === year ? "" : `${y}-`}${m}-${d} ${t}`);
  }

  function hoursLabel(hours) {
    const value = Number(hours);
    if (!(value > 0)) return "";
    const days = value / 24;
    return days > 1 && Number.isInteger(days) ? `${days} 天` : `${value} 小时`;
  }

  const topics = () => state.config?.topics || {};
  const topicLabel = key => topics()[key]?.label || key;
  const groupsUsing = key => (state.config?.config?.groups || []).filter(group => group.type === key);
  const catPath = (topicKey, name) => `/api/topics/${enc(topicKey)}/categories/${enc(name)}`;
  const hasIssue = field => (state.config?.issues || []).some(issue => issue.field === field);

  const supportsFieldSizing = typeof CSS !== "undefined" && CSS.supports?.("field-sizing", "content");
  function autoResize(textarea) {
    if (supportsFieldSizing) return;
    textarea.style.height = "auto";
    if (textarea.scrollHeight) textarea.style.height = `${textarea.scrollHeight}px`;
  }

  // ---------------------------------------------------------------- Toast

  const toasts = new Map();
  let toastSeq = 0;
  const TOAST_ICONS = { success: "check", error: "error", info: "info" };

  function toast(text, { type = "info", key = `toast-${++toastSeq}`, action, duration } = {}) {
    let entry = toasts.get(key);
    if (!entry) {
      entry = { el: node("div"), timer: undefined };
      toasts.set(key, entry);
      $("toasts").append(entry.el);
      while (toasts.size > 4) toasts.values().next().value.close();
    }
    clearTimeout(entry.timer);
    const { el } = entry;
    const close = () => {
      clearTimeout(entry.timer);
      el.remove();
      if (toasts.get(key) === entry) toasts.delete(key);
    };
    entry.close = close;
    el.className = `toast is-${type}`;
    el.setAttribute("role", type === "error" ? "alert" : "status");
    const parts = [type === "loading" ? node("span", undefined, "spinner") : icon(TOAST_ICONS[type] || "info"),
      node("span", text, "toast-text")];
    if (action) parts.push(button(action.label, () => { close(); action.run(); }, ""));
    if (type === "error") parts.push(iconButton("x", "关闭提示", close, "toast-close"));
    el.replaceChildren(...parts);
    const ms = duration ?? (type === "loading" ? 0 : type === "error" ? 7000 : action ? 6000 : 2600);
    if (ms) entry.timer = setTimeout(close, ms);
    return entry;
  }

  /* 统一的异步操作反馈：超过 250ms 才显示 loading，成功和失败都用 toast。
     失败时返回 undefined（错误已经提示过），调用方据此回滚界面。 */
  let taskSeq = 0;
  async function task(fn, { loading, success, key = `task-${++taskSeq}` } = {}) {
    let shown = false;
    const timer = loading ? setTimeout(() => { shown = true; toast(loading, { type: "loading", key }); }, 250) : undefined;
    try {
      const result = await fn();
      clearTimeout(timer);
      const done = typeof success === "function" ? success(result) : success;
      if (done) toast(typeof done === "string" ? done : done.text, { type: "success", key, action: done.action });
      else if (shown) toasts.get(key)?.close();
      return result ?? true;
    } catch (error) {
      clearTimeout(timer);
      toast(error.message || "出错了。", { type: "error", key });
      return undefined;
    }
  }

  function fatal(text) {
    $("fatal").textContent = text;
    $("fatal").hidden = !text;
  }

  // ---------------------------------------------------------------- 外观（白 / 米黄 / 黑）

  const THEMES = [
    { id: "light", name: "白", icon: "sun" },
    { id: "sepia", name: "米黄", icon: "paper" },
    { id: "dark", name: "黑", icon: "moon" },
  ];
  const systemDark = window.matchMedia?.("(prefers-color-scheme: dark)");

  function currentTheme() {
    const saved = document.documentElement.dataset.theme;
    return THEMES.some(theme => theme.id === saved) ? saved : (systemDark?.matches ? "dark" : "light");
  }

  function applyTheme(id) {
    if (THEMES.some(theme => theme.id === id)) document.documentElement.dataset.theme = id;
    else delete document.documentElement.dataset.theme;  // 没选过：跟随系统
    const index = THEMES.findIndex(theme => theme.id === currentTheme());
    const now = THEMES[index];
    const next = THEMES[(index + 1) % THEMES.length];
    const control = $("toggle-theme");
    control.querySelector("use").setAttribute("href", `#i-${now.icon}`);
    control.setAttribute("aria-label", `外观：${now.name}。点一下换成${next.name}`);
    control.title = `外观：${now.name}（点一下换成${next.name}）`;
  }

  async function cycleTheme() {
    const before = document.documentElement.dataset.theme;
    const index = THEMES.findIndex(theme => theme.id === currentTheme());
    const next = THEMES[(index + 1) % THEMES.length];
    applyTheme(next.id);  // 先切换，保存失败再换回来
    const view = await task(() => request("PUT", "/api/theme", { theme: next.id }), {
      key: "theme", success: `外观：${next.name}`,
    });
    if (view) applyConfig(view);
    else applyTheme(before);
  }

  // ---------------------------------------------------------------- 配置和待办

  const TODO_TEXT = { deepseek: "没填 API Key", profile: "没填个人情况", groups: "还没添加群" };
  const TODO_ACTIONS = {
    deepseek: { label: "去设置", run: () => openSettings("api-key") },
    profile: { label: "去填写", run: () => goFocus("profile") },
    groups: { label: "去添加", run: goAddGroup },
  };

  function applyConfig(view) {
    state.config = view;
    renderIssues();
  }

  function renderIssues() {
    const issues = state.config?.issues || [];
    const warnings = issues.filter(issue => issue.level === "warning");
    const errors = issues.filter(issue => issue.level === "error");
    $("todo-list").replaceChildren(...warnings.map(issue => {
      const item = node("li", undefined, "todo");
      const known = TODO_TEXT[issue.field] && /还没|没有填写|没填/.test(issue.message);
      item.append(node("span", known ? TODO_TEXT[issue.field] : issue.message));
      const action = known && TODO_ACTIONS[issue.field];
      if (action) item.append(button(`${action.label} →`, action.run, "link-btn"));
      return item;
    }));
    $("todos").hidden = !warnings.length;
    $("settings-dot").hidden = !hasIssue("deepseek");
    $("focus-dot").hidden = !warnings.some(issue => issue.field === "profile");
    fatal(errors.length ? `config.json 有问题，先修好再继续：${errors.map(issue => issue.message).join("；")}` : "");
    renderRun();
  }

  // ---------------------------------------------------------------- 页面切换

  function currentView() { return VIEWS[location.hash] || "home"; }

  function navigate() {
    const view = currentView();
    if (view === state.view) return;
    state.view = view;
    for (const name of ["home", "focus", "reports"]) {
      setHidden($(`view-${name}`), name !== view);
      const link = $(`nav-${name}`);
      if (name === view) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    }
    if (view === "focus") renderFocus();
    if (view === "reports") task(loadReports, { key: "reports" });
  }

  function go(hash) {
    if (location.hash !== hash) location.hash = hash;
    navigate();
  }

  function goFocus(fieldId, typeKey) {
    if (typeKey) state.currentType = typeKey;
    go("#focus");
    if (typeKey) renderFocus();
    if (fieldId) $(fieldId).focus();
  }

  function goAddGroup() {
    go("#home");
    const first = $("source-list").querySelector("input[type=checkbox]:not(:checked)");
    (first || $("import-input")).focus();
  }

  // ---------------------------------------------------------------- 1 选择群

  async function loadSources(initialSelection) {
    const { sources } = await request("GET", "/api/sources");
    state.sources = sources;
    const configured = new Set(sources.filter(source => source.configured).map(source => source.key));
    const wanted = initialSelection === null ? configured : (initialSelection ?? state.selection);
    state.selection = new Set([...wanted].filter(key => configured.has(key)));
    renderSources();
    estimate();
  }

  function defaultNewType() {
    const keys = Object.keys(topics());
    return keys.includes(state.lastType) ? state.lastType : keys[0];
  }

  function renderSources() {
    $("source-list").replaceChildren(...state.sources.map(sourceRow));
    $("sources-empty").hidden = state.sources.length > 0;
    $("empty-export-dir").textContent = state.config.paths?.export_dir || "设置里的导出目录";
    renderSelectionCount();
  }

  function renderSelectionCount() {
    const configured = state.sources.filter(source => source.configured).length;
    const found = state.sources.length - configured;
    $("selection-count").textContent = state.sources.length
      ? `已选 ${state.selection.size} / ${configured}${found ? ` · 新发现 ${found}` : ""}` : "";
  }

  function sourceRow(source) {
    const row = node("li", undefined, "source-row");
    row.dataset.key = source.key;
    const id = `source-${source.group_id}`;
    const check = node("input");
    check.type = "checkbox";
    check.id = id;
    check.checked = source.configured && state.selection.has(source.key);

    const label = node("label", undefined, "source-main");
    label.htmlFor = id;
    const name = node("span", undefined, "source-name");
    const title = node("span", source.name);
    title.title = source.name;
    name.append(title);
    const fileName = source.file?.split(/[\\/]/).at(-1);
    let detail;
    if (!source.configured) {
      name.append(node("span", "新发现", "badge"));
      detail = `${fileName} · ${fmtTime(source.file_mtime)} · 勾选就会添加`;
    } else if (source.status === "bad_type") {
      name.append(node("span", "类型失效", "badge badge-warn"));
      detail = "原来的类型被删了，在右边重新选一个";
    } else if (!source.file) {
      name.append(node("span", "没有导出文件", "badge badge-warn"));
      detail = `导出成 群_${source.group_id}_群名.csv 后点 ⟳ 重新扫描`;
      row.classList.add("is-off");
    } else {
      detail = `${fileName} · ${fmtTime(source.file_mtime)}`;
    }
    const file = node("span", detail, "source-file");
    file.title = source.file || detail;
    label.append(name, file);

    const select = typeSelect(source);
    check.addEventListener("change", () => toggleSource(source, check, row, select));
    row.append(check, label, select, source.configured ? groupMenu(source) : node("span"));
    return row;
  }

  function typeSelect(source) {
    const select = node("select", undefined, "input select type-select");
    select.setAttribute("aria-label", `「${source.name}」的群类型`);
    const all = topics();
    for (const [key, topic] of Object.entries(all)) select.append(new Option(topic.label || key, key));
    const current = source.configured ? source.type : (state.newTypes.get(source.key) || defaultNewType());
    if (!Object.hasOwn(all, current)) {
      const missing = new Option("（类型已失效）", current);
      missing.disabled = true;
      select.prepend(missing);
    }
    select.append(new Option("管理类型…", "__manage"));
    select.value = current;
    let previous = current;
    select.addEventListener("change", async () => {
      if (select.value === "__manage") {
        select.value = previous;
        goFocus(undefined, Object.hasOwn(topics(), previous) ? previous : undefined);
        return;
      }
      const next = select.value;
      state.lastType = next;
      if (!source.configured) {
        state.newTypes.set(source.key, next);
        previous = next;
        return;
      }
      select.disabled = true;
      const view = await task(() => request("PATCH", `/api/groups/${enc(source.group_id)}`, { type: next }), {
        loading: "正在保存…", key: `type-${source.key}`,
        success: `「${source.name}」改成了${topicLabel(next)}`,
      });
      select.disabled = false;
      if (!view) { select.value = previous; return; }
      previous = next;
      applyConfig(view);
      const wasBroken = source.status === "bad_type";
      source.type = next;
      if (wasBroken) {
        source.status = source.file ? "ok" : "missing";
        renderSources();
      }
      estimate();
    });
    return select;
  }

  async function toggleSource(source, check, row, select) {
    if (source.configured) {
      if (check.checked) state.selection.add(source.key);
      else state.selection.delete(source.key);
      renderSelectionCount();
      estimate();
      return;
    }
    if (!check.checked) return;
    const type = Object.hasOwn(topics(), select.value) ? select.value : defaultNewType();
    row.classList.add("is-busy");
    const view = await task(() => request("POST", "/api/groups", { group_id: source.group_id, name: source.name, type }), {
      loading: `正在添加「${source.name}」…`, success: `已添加「${source.name}」`,
    });
    if (!view) {
      check.checked = false;
      row.classList.remove("is-busy");
      return;
    }
    applyConfig(view);
    state.selection.add(source.key);
    await task(() => loadSources(), { key: "sources" });
  }

  function groupMenu(source) {
    const menu = node("details", undefined, "menu");
    const summary = node("summary");
    summary.setAttribute("aria-label", `「${source.name}」的更多操作`);
    summary.title = "更多操作";
    summary.append(icon("more"));
    const pop = node("div", undefined, "menu-pop");
    const remove = button("", () => { menu.open = false; removeGroup(source); }, "danger");
    remove.append(icon("trash"), document.createTextNode("从列表移除"));
    pop.append(remove);
    menu.append(summary, pop);
    return menu;
  }

  async function removeGroup(source) {
    const wasSelected = state.selection.has(source.key);
    const view = await task(() => request("DELETE", `/api/groups/${enc(source.group_id)}`), {
      loading: "正在移除…",
      success: { text: `已移除「${source.name}」`, action: { label: "撤销", run: () => restoreGroup(source, wasSelected) } },
    });
    if (!view) return;
    applyConfig(view);
    state.selection.delete(source.key);
    await task(() => loadSources(), { key: "sources" });
  }

  async function restoreGroup(source, wasSelected) {
    const view = await task(() => request("POST", "/api/groups", {
      group_id: source.group_id, name: source.name, type: source.type,
    }), { success: `已恢复「${source.name}」` });
    if (!view) return;
    applyConfig(view);
    if (wasSelected) state.selection.add(source.key);
    await task(() => loadSources(), { key: "sources" });
  }

  // ---------------------------------------------------------------- 导入

  function showNextImport() {
    const form = $("import-group");
    form.hidden = !state.pendingImports.length;
    if (!state.pendingImports.length) return;
    const file = state.pendingImports[0];
    form.reset();
    $("import-group-name").value = file.name.replace(/\.[^.]+$/, "").slice(0, 60);
    $("import-prompt").textContent = `「${file.name}」的文件名里没有群号，填一下它是哪个群：`;
    $("import-group-id").focus();
  }

  async function uploadFile(file, params = new URLSearchParams()) {
    const query = new URLSearchParams(params);
    const upload = () => {
      const search = query.toString();
      return request("POST", search ? `/api/import?${search}` : "/api/import", undefined, file);
    };
    try { return await upload(); }
    catch (error) {
      if (error.status !== 409 || error.field !== "overwrite") throw error;
      if (!window.confirm(error.message)) return null;
      query.set("overwrite", "1");
      return upload();
    }
  }

  async function importFiles(files) {
    if (!files.length) return;
    let added = 0;
    let skipped = 0;
    const errors = [];
    const progress = toast(`正在导入 ${files.length} 个文件…`, { type: "loading", key: "import" });
    for (const file of files) {
      if (!/\.(csv|txt)$/i.test(file.name) || !file.size) {
        errors.push(`「${file.name}」不是有内容的 CSV / TXT`);
        continue;
      }
      if (!/^群_\d+_.*\.(csv|txt)$/i.test(file.name)) {
        state.pendingImports.push(file);
        continue;
      }
      try {
        if (await uploadFile(file)) added++;
        else skipped++;
      } catch (error) {
        if (error.field === "group_id") state.pendingImports.push(file);
        else errors.push(error.message);
      }
    }
    progress.close();
    if (added) await task(() => loadSources(), { key: "sources" });
    const summary = [added && `导入了 ${added} 个文件`, skipped && `保留了 ${skipped} 个同名的原文件`].filter(Boolean).join("，");
    if (errors.length) toast([summary, ...new Set(errors)].filter(Boolean).join("；"), { type: "error", key: "import" });
    else if (summary) toast(summary, { type: "success", key: "import" });
    showNextImport();
  }

  // ---------------------------------------------------------------- 2 时间范围

  function windowOptions() {
    const presets = state.config.presets || {};
    const options = [{ id: "since_last", label: "上次之后" }];
    for (const [name, preset] of Object.entries(presets)) {
      const builtin = name === "daily" || name === "weekly";
      options.push({ id: `preset:${name}`, label: (builtin && hoursLabel(preset?.hours)) || preset?.title || name });
    }
    options.push({ id: "all", label: "全部" }, { id: "custom", label: "自定义" });
    return options;
  }

  function buildWindowButtons() {
    const options = windowOptions();
    if (!options.some(option => option.id === state.windowChoice)) state.windowChoice = "since_last";
    $("windows").replaceChildren(...options.map(option => {
      const control = button(option.label, () => chooseWindow(option.id), "");
      control.dataset.window = option.id;
      return control;
    }));
    renderWindow();
  }

  function chooseWindow(id) {
    state.windowChoice = id;
    renderWindow();
    estimate();
    if (id === "custom") $("window-value").focus();
  }

  function readWindow() {
    const choice = state.windowChoice;
    if (choice === "custom") {
      const value = $("window-value").valueAsNumber;
      return { mode: "hours", hours: value * ($("window-unit").value === "days" ? 24 : 1) };
    }
    if (choice === "since_last" || choice === "all") return { mode: choice };
    return { mode: "preset", name: choice.slice("preset:".length) };
  }

  function restoreWindow(window) {
    if (!window) return;
    if (window.mode === "all" || window.mode === "since_last") state.windowChoice = window.mode;
    else if (window.mode === "hours" && validHours(window.hours)) {
      state.windowChoice = "custom";
      const days = window.hours / 24;
      $("window-value").value = Number.isInteger(days) && days > 1 ? days : window.hours;
      $("window-unit").value = Number.isInteger(days) && days > 1 ? "days" : "hours";
    } else if (window.mode === "preset" && Object.hasOwn(state.config.presets ?? {}, window.name)) {
      state.windowChoice = `preset:${window.name}`;
    } else toast("保存的默认时间范围已经不能用了，先用「上次之后」。");
  }

  function windowHint() {
    const choice = state.windowChoice;
    if (choice === "since_last") return "从上次生成之后开始，第一次是最近 24 小时";
    if (choice === "all") return "导出文件里的全部消息，消息多时很费 Token";
    if (choice === "custom") {
      const { hours } = readWindow();
      return validHours(hours) ? `最近 ${hoursLabel(hours)}` : "";
    }
    const name = choice.slice("preset:".length);
    const preset = state.config.presets?.[name] || {};
    return [preset.title, hoursLabel(preset.hours) && `最近 ${hoursLabel(preset.hours)}`].filter(Boolean).join(" · ");
  }

  function renderWindow() {
    for (const control of $("windows").querySelectorAll("button")) {
      control.setAttribute("aria-pressed", String(control.dataset.window === state.windowChoice));
    }
    $("custom-window").hidden = state.windowChoice !== "custom";
    $("window-hint").textContent = windowHint();
    inlineMessage($("window-error"), state.windowError, "error");
    $("save-default").disabled = state.savingDefaults || !canSaveDefaults();
  }

  function canSaveDefaults() {
    const window = readWindow();
    return Boolean(state.config?.defaults) && (window.mode !== "hours" || validHours(window.hours));
  }

  async function saveDefaults() {
    if (state.savingDefaults || !canSaveDefaults()) return;
    const configured = state.sources.filter(source => source.configured);
    const allSelected = configured.length > 0 && configured.every(source => state.selection.has(source.key));
    state.savingDefaults = true;
    renderWindow();
    const view = await task(() => request("PUT", "/api/defaults", {
      selection: allSelected ? null : [...state.selection], window: readWindow(),
    }), { loading: "正在保存…", success: "已设为默认，下次打开会自动选好" });
    state.savingDefaults = false;
    if (view) applyConfig(view);
    renderWindow();
  }

  // ---------------------------------------------------------------- 3 预估与生成

  const selectedWithFile = () => state.sources.filter(source => source.configured && source.file && state.selection.has(source.key));

  function estimate() {
    clearTimeout(state.estimateTimer);
    state.estimateVersion++;
    state.plan = undefined;
    state.estimating = true;
    renderEstimate();
    state.estimateTimer = setTimeout(runEstimate, 150);
  }

  async function runEstimate() {
    const version = ++state.estimateVersion;
    state.plan = undefined;
    state.planError = "";
    state.windowError = "";
    const window = readWindow();
    if (window.mode === "hours" && !validHours(window.hours)) {
      state.windowError = "填一个大于 0、不超过 100000 小时的时长。";
      state.estimating = false;
      renderWindow();
      renderEstimate();
      return;
    }
    if (!selectedWithFile().length) {
      state.estimating = false;
      renderWindow();
      renderEstimate();
      return;
    }
    try {
      const plan = await request("POST", "/api/plan", { selection: [...state.selection], window });
      if (version !== state.estimateVersion) return;
      state.plan = plan;
    } catch (error) {
      if (version !== state.estimateVersion) return;
      if (error.field === "window") state.windowError = error.message;
      else state.planError = error.message;
    }
    state.estimating = false;
    renderWindow();
    renderEstimate();
  }

  function renderEstimate() {
    const plan = state.plan;
    const pending = plan ? plan.sources.reduce((total, row) => total + row.pending, 0) : undefined;
    $("estimate-messages").textContent = plan ? num(pending) : "—";
    $("estimate-batches").textContent = plan ? num(plan.total_batches) : "—";
    $("estimate-tokens").textContent = plan ? num(plan.est_tokens) : "—";
    renderNotices();
    renderRun();
  }

  function renderNotices() {
    const groups = [];
    for (const source of state.sources) {
      if (source.configured && !source.file && state.selection.has(source.key)) {
        groups.push({ name: source.name, items: [{ level: "info", code: "missing", message: "还没有导出文件，这次会跳过" }] });
      }
    }
    for (const row of state.plan?.sources || []) {
      const items = [];
      if (row.error) items.push({ level: "error", code: "error", message: row.error });
      const notices = row.notices || (row.warnings || []).map(text => ({ level: "warn", code: "other", message: text, detail: "" }));
      for (const notice of notices) {
        items.push({ ...notice, level: notice.code === "bad_lines" ? "info" : notice.level === "error" ? "error" : "warn" });
      }
      if (items.length) groups.push({ name: row.name, items });
    }
    const count = groups.reduce((total, group) => total + group.items.length, 0);
    $("notices").hidden = !count;
    $("notice-count").textContent = count;
    $("notice-list").replaceChildren(...groups.map(group => {
      const block = node("div", undefined, "notice-group");
      const title = node("h4", group.name);
      title.title = group.name;
      block.append(title, ...group.items.map(noticeItem));
      return block;
    }));
  }

  function noticeItem(item) {
    const element = node("div", undefined, `notice is-${item.level}`);
    element.append(icon(item.level === "error" ? "error" : item.level === "info" ? "info" : "warn"));
    const body = node("div");
    body.append(node("p", item.message));
    if (item.detail) {
      const details = node("details");
      details.append(node("summary", "详情"), node("p", item.detail));
      body.append(details);
    }
    const actions = [];
    if (item.code === "stale_export" || item.code === "missing") {
      actions.push(button("重新扫描", refreshSources, "link-btn"));
    }
    if (item.code === "stale_export" && state.windowChoice !== "all") {
      actions.push(button("改成全部历史", () => chooseWindow("all"), "link-btn"));
    }
    if (actions.length) {
      const row = node("div", undefined, "notice-actions");
      row.append(...actions);
      body.append(row);
    }
    element.append(body);
    return element;
  }

  function runBlocker() {
    if (state.job.id) return { text: "正在生成，完成后才能再开始" };
    if (state.job.starting) return { text: "正在开始…" };
    if (hasIssue("deepseek")) return { text: "还没填 API Key", action: { label: "去设置", run: () => openSettings("api-key") } };
    if (state.windowError) return { text: "时间范围不对，先改一下" };
    if (!state.selection.size) return { text: "先在左边勾选至少一个群" };
    if (!selectedWithFile().length) return { text: "勾选的群都还没有导出文件" };
    if (state.estimating || (!state.plan && !state.planError)) return { text: "正在估算…" };
    if (state.planError) return { text: state.planError };
    if (state.plan.total_batches === 0) return { text: "待处理消息为 0，换个时间范围试试" };
    return null;
  }

  function renderRun() {
    if (!state.config) return;
    const blocker = runBlocker();
    $("run").disabled = Boolean(blocker);
    const reason = $("run-reason");
    reason.classList.toggle("is-blocking", Boolean(blocker));
    if (!blocker) {
      reason.textContent = "也可以按 Ctrl + Enter";
      return;
    }
    reason.replaceChildren(document.createTextNode(blocker.action ? `${blocker.text} · ` : blocker.text));
    if (blocker.action) reason.append(button(blocker.action.label, blocker.action.run, "link-btn"));
  }

  async function startRun() {
    const blocker = runBlocker();
    if (blocker) {
      if (!state.job.id) toast(`现在还不能生成：${blocker.text}`);
      return;
    }
    state.job.starting = true;
    renderRun();
    try {
      const { job_id: id } = await request("POST", "/api/run", { selection: state.plan.selection, window: state.plan.window });
      Object.assign(state.job, { id, cursor: 0, message: "", cancelling: false });
      $("job-report").hidden = true;
      await poll();
    } catch (error) {
      toast(error.message, { type: "error" });
    } finally {
      state.job.starting = false;
      renderRun();
    }
  }

  async function poll() {
    const id = state.job.id;
    if (!id) return;
    try {
      const job = await request("GET", `/api/jobs/${enc(id)}?since=${state.job.cursor}`);
      if (id !== state.job.id) return;
      toasts.get("poll")?.close();
      showJob(job);
      if (state.job.id) state.job.timer = setTimeout(poll, 1000);
    } catch (error) {
      toast(error.message, { type: "error", key: "poll" });
      if (state.job.id === id) state.job.timer = setTimeout(poll, 2000);
    }
  }

  function jobStatusText(job) {
    const { batches_started: started = 0, total_batches: total = 0 } = job.progress || {};
    const reportPath = job.result?.report_path;
    if (job.status === "running") {
      if (state.job.cancelling) return "正在取消，等这一批请求结束…";
      return total && started ? `正在分析第 ${started} / ${total} 批` : state.job.message || "正在准备消息…";
    }
    if (job.status === "cancelled") return reportPath ? "已取消，做完的部分已保存" : "已取消";
    if (job.status === "failed") return job.error || "生成失败";
    if (job.result?.failures?.length && reportPath) return "快报生成了，但有的群没处理成功，详情见快报";
    return reportPath ? "快报生成好了" : state.job.message || "这段时间没有新消息，没生成快报";
  }

  function renderJobPanels(job) {
    const running = job?.status === "running";
    const { batches_started: started = 0, total_batches: total = 0 } = job?.progress || {};
    const text = job ? jobStatusText(job) : "";
    const ratio = !job ? 0 : job.status !== "running" ? 1 : total ? Math.min(started, total) / total : 0;
    for (const [panel, status, bar, visible] of [
      [$("job"), $("job-status"), $("job-bar"), Boolean(job)],
      [$("report-job"), $("report-job-status"), $("report-job-bar"), running],
    ]) {
      panel.hidden = !visible;
      status.textContent = text;
      bar.classList.toggle("is-indeterminate", running && !total);
      bar.firstElementChild.style.width = running && !total ? "" : `${Math.round(ratio * 100)}%`;
    }
    for (const control of document.querySelectorAll("[data-cancel-job]")) {
      control.hidden = !running;
      control.disabled = state.job.cancelling;
    }
    $("nav-running").hidden = !running;
  }

  function showJob(job) {
    state.job.cursor = job.next_event ?? state.job.cursor;
    const last = job.events?.at(-1)?.message?.trim();
    if (last) state.job.message = last;
    renderJobPanels(job);
    if (job.status === "running") return;

    clearTimeout(state.job.timer);
    state.job.id = undefined;
    state.job.cancelling = false;
    renderJobPanels(job);
    const reportPath = job.result?.report_path;
    $("job-report").hidden = !reportPath;
    if (reportPath) state.pendingReportPath = reportPath;
    const text = jobStatusText(job);
    if (job.status === "failed") toast(text, { type: "error", key: "job" });
    else if (reportPath) {
      toast(text, { type: "success", key: "job", action: { label: "查看", run: () => { state.pendingReportPath = reportPath; openReports(); } } });
    } else toast(text, { key: "job" });
    estimate();
    if (state.view === "reports") task(loadReports, { key: "reports" });
  }

  function openReports() {
    if (state.view === "reports") task(loadReports, { key: "reports" });
    else go("#reports");
  }

  async function cancelJob() {
    const id = state.job.id;
    if (!id || state.job.cancelling) return;
    for (const control of document.querySelectorAll("[data-cancel-job]")) control.disabled = true;
    const ok = await task(() => request("POST", `/api/jobs/${enc(id)}/cancel`), { loading: "正在取消…" });
    if (ok && state.job.id === id) {
      state.job.cancelling = true;
      for (const status of [$("job-status"), $("report-job-status")]) status.textContent = "正在取消，等这一批请求结束…";
    } else {
      for (const control of document.querySelectorAll("[data-cancel-job]")) control.disabled = false;
    }
  }

  async function refreshSources() {
    await task(() => loadSources(), { loading: "正在扫描导出目录…", success: "已重新扫描", key: "sources" });
  }

  // ---------------------------------------------------------------- 关注点

  function renderFocus() {
    const view = state.config;
    if (document.activeElement !== $("profile")) $("profile").value = view.config.profile || "";
    for (const control of $("explain").querySelectorAll("button")) {
      control.setAttribute("aria-pressed", String(control.dataset.level === view.explain_level));
    }
    $("explain-hint").textContent = view.explain_level === "custom" ? "现在用的是 config.json 里自己写的说法" : "";
    const keys = Object.keys(topics());
    if (!keys.includes(state.currentType)) state.currentType = keys[0];
    renderTypeList();
    renderTypeDetail();
  }

  function renderTypeList() {
    $("type-list").replaceChildren(...Object.entries(topics()).map(([key, topic]) => {
      const item = node("li");
      const control = button("", () => selectType(key), "type-item");
      control.dataset.type = key;
      control.setAttribute("aria-current", String(key === state.currentType));
      control.append(node("span", topic.label || key), node("small", `${groupsUsing(key).length} 个群`));
      item.append(control);
      return item;
    }));
  }

  function selectType(key) {
    state.currentType = key;
    renderTypeList();
    renderTypeDetail();
    $("type-list").querySelector(`[data-type="${CSS.escape(key)}"]`)?.focus();
  }

  function renderTypeDetail() {
    const key = state.currentType;
    const topic = topics()[key];
    $("type-detail").hidden = !topic;
    if (!topic) return;
    const label = $("type-label");
    label.value = label.dataset.saved = topic.label || key;
    const focus = $("type-focus");
    focus.value = focus.dataset.saved = topic.focus || "";
    $("type-focus-echo").textContent = topic.focus || "对你有用的信息";
    const users = groupsUsing(key);
    $("type-users").replaceChildren(...(users.length
      ? users.map(group => node("span", group.name, "chip"))
      : [node("span", "还没有群在用。在主页给群选这个类型就行。", "hint")]));
    renderCategories();
  }

  function categoryRows() {
    return [...$("category-list").querySelectorAll(".cat-row:not(.is-fixed):not(.is-draft)")];
  }

  function renderCategories(focusAfter) {
    const topicKey = state.currentType;
    const entries = Object.entries(topics()[topicKey]?.categories || {});
    $("cat-count").textContent = entries.length;
    const fixed = node("li", undefined, "cat-row is-fixed");
    const fixedBody = node("div", undefined, "cat-body");
    fixedBody.append(node("span", "其他有用", "cat-name"), node("span", "不属于上面任何一类、但确实有用的，程序会自动放这里", "cat-desc"));
    fixed.append(node("span"), fixedBody, node("span"));
    $("category-list").replaceChildren(...entries.map(([name, description]) => categoryRow(topicKey, name, description)), fixed);
    for (const area of $("category-list").querySelectorAll("textarea")) autoResize(area);
    if (focusAfter) {
      const row = categoryRows().find(item => item.dataset.name === focusAfter.name);
      row?.querySelector(focusAfter.selector)?.focus();
    }
  }

  function bindInline(input, commit, { multiline = false } = {}) {
    input.dataset.saved = input.value;
    input.addEventListener("keydown", event => {
      if (event.isComposing || event.keyCode === 229) return;
      if (event.key === "Enter" && !(multiline && event.shiftKey)) {
        event.preventDefault();
        input.blur();
      } else if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        input.value = input.dataset.saved;
        if (multiline) autoResize(input);
        input.blur();
      }
    });
    input.addEventListener("blur", () => {
      const value = input.value.trim();
      if (value === input.dataset.saved) {
        input.value = input.dataset.saved;
        return;
      }
      commit(value);
    });
    if (multiline) input.addEventListener("input", () => autoResize(input));
  }

  function categoryRow(topicKey, name, description, draft = false) {
    const row = node("li", undefined, `cat-row${draft ? " is-draft" : ""}`);
    row.dataset.name = name;
    const handle = iconButton("grip", `调整「${name}」的顺序（Alt + ↑ / ↓）`, undefined, "handle");
    handle.title = "拖动排序";
    if (draft) handle.hidden = true;
    const body = node("div", undefined, "cat-body");
    const nameInput = node("input", undefined, "inline-input cat-name");
    nameInput.value = name;
    nameInput.maxLength = 30;
    nameInput.placeholder = "分类名";
    nameInput.setAttribute("aria-label", "分类名");
    const descInput = node("textarea", undefined, "inline-input cat-desc");
    descInput.rows = 1;
    descInput.value = description;
    descInput.maxLength = 300;
    descInput.placeholder = "写清楚要挑哪些消息，比如：考试时间、作业截止";
    descInput.setAttribute("aria-label", draft ? "新分类的说明" : `「${name}」的说明`);
    body.append(nameInput, descInput);
    const remove = iconButton("x", draft ? "放弃新分类" : `删除分类「${name}」`, () => deleteCategory(topicKey, row), "btn btn-ghost btn-sm btn-icon remove");
    row.append(handle, body, remove);

    if (draft) {
      // 新分类：在名字里按回车直接跳到说明（失焦时会先把分类建好）
      nameInput.addEventListener("keydown", event => {
        if (event.key !== "Enter" || event.isComposing || event.keyCode === 229) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        if (nameInput.value.trim()) descInput.focus();
      });
    }
    bindInline(nameInput, value => commitCategoryName(topicKey, row, nameInput, value));
    bindInline(descInput, value => commitCategoryDescription(topicKey, row, descInput, value), { multiline: true });

    if (draft) {
      row.addEventListener("focusout", event => {
        if (!row.contains(event.relatedTarget) && !nameInput.value.trim() && !descInput.value.trim()) row.remove();
      });
      return row;
    }
    row.addEventListener("keydown", event => {
      if (!event.altKey || (event.key !== "ArrowUp" && event.key !== "ArrowDown")) return;
      event.preventDefault();
      // 还有没保存的改名时先不挪，免得改名和排序两个请求互相打架
      const editing = document.activeElement;
      if (editing?.dataset?.saved !== undefined && editing.value.trim() !== editing.dataset.saved) {
        toast("先按回车保存修改，再调整顺序");
        return;
      }
      const rows = categoryRows();
      const from = rows.indexOf(row);
      const to = from + (event.key === "ArrowUp" ? -1 : 1);
      if (from < 0 || to < 0 || to >= rows.length) return;
      const active = document.activeElement;
      if (to < from) rows[to].before(row);
      else rows[to].after(row);
      active?.focus();
      moveCategory(topicKey, row.dataset.name, to);
    });
    handle.addEventListener("pointerdown", () => { row.draggable = true; });
    handle.addEventListener("pointerup", () => { row.draggable = false; });
    row.addEventListener("dragstart", event => {
      state.drag = { row, topicKey };
      row.classList.add("is-dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", row.dataset.name);
    });
    row.addEventListener("dragend", () => {
      row.draggable = false;
      row.classList.remove("is-dragging");
      clearDropMarks();
      state.drag = null;
    });
    return row;
  }

  function clearDropMarks() {
    for (const row of $("category-list").querySelectorAll(".drop-before, .drop-after")) row.classList.remove("drop-before", "drop-after");
  }

  function dropTarget(event) {
    if (!state.drag) return null;
    const row = event.target.closest?.(".cat-row:not(.is-fixed):not(.is-draft)");
    if (!row || row === state.drag.row) return null;
    const rect = row.getBoundingClientRect();
    return { row, before: event.clientY < rect.top + rect.height / 2 };
  }

  async function commitCategoryName(topicKey, row, input, value) {
    const draft = row.classList.contains("is-draft");
    if (!value) {
      if (draft) return;
      input.value = input.dataset.saved;
      toast("分类名不能为空", { type: "error" });
      return;
    }
    const existing = topics()[topicKey]?.categories || {};
    if (Object.hasOwn(existing, value) && value !== row.dataset.name) {
      toast(`已经有分类「${value}」了`, { type: "error" });
      if (!draft) input.value = input.dataset.saved;
      return;
    }
    if (draft) return createCategory(topicKey, row, value);
    const old = row.dataset.name;
    const view = await task(() => request("PATCH", catPath(topicKey, old), { name: value }), {
      key: "category", success: `已改名为「${value}」`,
    });
    if (!view) { input.value = input.dataset.saved; return; }
    applyConfig(view);
    row.dataset.name = value;
    input.dataset.saved = value;
    row.querySelector(".cat-desc").setAttribute("aria-label", `「${value}」的说明`);
    row.querySelector(".remove").setAttribute("aria-label", `删除分类「${value}」`);
  }

  async function commitCategoryDescription(topicKey, row, input, value) {
    if (row.classList.contains("is-draft")) return;
    const view = await task(() => request("PATCH", catPath(topicKey, row.dataset.name), { description: value }), {
      key: "category", success: "说明已保存",
    });
    if (!view) { input.value = input.dataset.saved; autoResize(input); return; }
    applyConfig(view);
    input.value = input.dataset.saved = value;
  }

  async function createCategory(topicKey, row, name) {
    const descInput = row.querySelector(".cat-desc");
    const sent = descInput.value.trim();
    const view = await task(() => request("PUT", catPath(topicKey, name), { description: sent }), {
      key: "category", success: `已添加「${name}」`,
    });
    if (!view) return;
    // 请求期间用户可能已经在说明里继续打字：重新渲染后把这些字带过去，失焦时再保存
    const keepFocus = document.activeElement === descInput;
    const typed = descInput.value;
    applyConfig(view);
    if (state.currentType !== topicKey) return;
    renderCategories();
    renderTypeList();
    const created = categoryRows().find(item => item.dataset.name === name)?.querySelector(".cat-desc");
    if (!created) return;
    if (typed.trim() !== sent) {
      created.value = typed;
      autoResize(created);
    }
    if (keepFocus) {
      created.focus();
      created.setSelectionRange(created.value.length, created.value.length);
    }
  }

  function addCategory() {
    const existing = $("category-list").querySelector(".cat-row.is-draft");
    if (existing) { existing.querySelector(".cat-name").focus(); return; }
    const row = categoryRow(state.currentType, "", "", true);
    $("category-list").querySelector(".is-fixed").before(row);
    row.querySelector(".cat-name").focus();
  }

  async function deleteCategory(topicKey, row) {
    if (row.classList.contains("is-draft")) {
      row.remove();
      $("add-category").focus();
      return;
    }
    const name = row.dataset.name;
    const index = categoryRows().indexOf(row);
    const description = topics()[topicKey]?.categories?.[name] ?? "";
    const view = await task(() => request("DELETE", catPath(topicKey, name)), {
      key: "category",
      success: { text: `已删除「${name}」`, action: { label: "撤销", run: () => restoreCategory(topicKey, name, description, index) } },
    });
    if (!view) return;
    applyConfig(view);
    if (state.currentType !== topicKey) return;
    renderCategories();
    const next = categoryRows()[Math.min(index, categoryRows().length - 1)];
    (next?.querySelector(".handle") || $("add-category")).focus();
  }

  async function restoreCategory(topicKey, name, description, index) {
    const view = await task(async () => {
      await request("PUT", catPath(topicKey, name), { description });
      return request("PATCH", catPath(topicKey, name), { order: index });
    }, { key: "category", success: `已恢复「${name}」` });
    if (!view) return;
    applyConfig(view);
    if (state.currentType === topicKey) renderCategories();
  }

  async function moveCategory(topicKey, name, order) {
    const view = await task(() => request("PATCH", catPath(topicKey, name), { order }), { key: "category-order", success: "顺序已更新" });
    if (view) applyConfig(view);
    else if (state.currentType === topicKey) renderCategories();
  }

  async function commitTypeLabel(value) {
    const key = state.currentType;
    const input = $("type-label");
    if (!value) {
      input.value = input.dataset.saved;
      toast("类型名不能为空", { type: "error" });
      return;
    }
    const view = await task(() => request("PATCH", `/api/topics/${enc(key)}`, { label: value }), {
      key: "type", success: `改名为「${value}」`,
    });
    if (!view) { input.value = input.dataset.saved; return; }
    applyConfig(view);
    input.dataset.saved = value;
    renderTypeList();
    renderSources();
  }

  async function commitTypeFocus(value) {
    const key = state.currentType;
    const input = $("type-focus");
    if (!value) {
      input.value = input.dataset.saved;
      toast("关注方向不能为空", { type: "error" });
      return;
    }
    const view = await task(() => request("PATCH", `/api/topics/${enc(key)}`, { focus: value }), {
      key: "type", success: "关注方向已保存",
    });
    if (!view) { input.value = input.dataset.saved; return; }
    applyConfig(view);
    input.dataset.saved = value;
    $("type-focus-echo").textContent = value;
  }

  async function deleteType() {
    const key = state.currentType;
    const topic = topics()[key];
    if (!topic) return;
    const label = topic.label || key;
    const users = groupsUsing(key);
    if (users.length) {
      toast(`还有 ${users.length} 个群在用「${label}」：${users.map(group => group.name).join("、")}。先在主页把它们改成别的类型。`, {
        type: "error", key: "type", action: { label: "去主页", run: () => go("#home") },
      });
      return;
    }
    if (Object.keys(topics()).length <= 1) {
      toast("至少要留一个群类型", { type: "error", key: "type" });
      return;
    }
    const count = Object.keys(topic.categories || {}).length;
    if (!window.confirm(`删除「${label}」？${count ? `它的 ${count} 个分类也会一起删掉。` : ""}`)) return;
    const view = await task(() => request("DELETE", `/api/topics/${enc(key)}`), {
      key: "type", loading: "正在删除…", success: `已删除「${label}」`,
    });
    if (!view) return;
    applyConfig(view);
    state.currentType = Object.keys(view.topics)[0];
    renderFocus();
    renderSources();
    $("type-list").querySelector('[aria-current="true"]')?.focus();
  }

  function setNewTypeForm(open) {
    $("new-type-form").hidden = !open;
    $("add-type").hidden = open;
    if (open) $("new-type-label").focus();
    else $("new-type-form").reset();
  }

  async function createType(event) {
    event.preventDefault();
    const label = $("new-type-label").value.trim();
    if (!label) return;
    const view = await task(() => request("POST", "/api/topics", { label }), {
      key: "type", loading: "正在新建…", success: `已新建「${label}」，写一下关注方向和分类吧`,
    });
    if (!view) return;
    applyConfig(view);
    state.currentType = view.key;
    setNewTypeForm(false);
    renderFocus();
    renderSources();
    $("type-focus").focus();
    $("type-focus").select();
  }

  async function saveProfile() {
    const status = $("profile-status");
    status.className = "save-status";
    status.textContent = "保存中…";
    const view = await task(() => request("PUT", "/api/focus", { profile: $("profile").value }), { key: "profile" });
    if (!view) {
      status.className = "save-status error";
      status.textContent = "没保存上";
      return;
    }
    applyConfig(view);
    if (document.activeElement !== $("profile")) $("profile").value = view.config.profile || "";
    status.className = "save-status ok";
    status.textContent = "已保存 ✓";
  }

  async function setExplain(level) {
    const names = { detailed: "详细", brief: "简短", off: "不要" };
    const view = await task(() => request("PUT", "/api/focus", { explain_level: level }), {
      key: "explain", success: `术语解释：${names[level]}`,
    });
    if (!view) return;
    applyConfig(view);
    renderFocus();
  }

  // ---------------------------------------------------------------- 快报

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

  function renderReportList() {
    const list = $("report-list");
    list.replaceChildren(...state.reports.map(report => {
      const item = node("li");
      const control = button("", () => task(() => showReport(report.id), { key: "reports" }), "report-item");
      control.dataset.reportId = report.id;
      control.setAttribute("aria-current", String(report.id === state.activeReportId));
      control.append(node("span", report.title, "report-item-title"));
      if (report.groups?.length) {
        const groups = node("span", report.groups.join("、"), "report-item-sub");
        groups.title = report.groups.join("、");
        control.append(groups);
      }
      if (report.period) control.append(node("span", shortPeriod(report.period), "report-item-sub"));
      control.append(node("span", `${fmtTime(report.created)} 生成`, "report-item-time"));
      item.append(control);
      return item;
    }));
    if (!state.reports.length) list.append(node("li", "还没有快报。", "empty"));
  }

  async function loadReports() {
    const { reports } = await request("GET", "/api/reports");
    state.reports = reports;
    const target = (state.pendingReportPath && reports.find(entry => entry.path === state.pendingReportPath)) ||
      reports.find(entry => entry.id === state.activeReportId) || reports[0];
    state.pendingReportPath = undefined;
    state.activeReportId = target?.id;
    renderReportList();
    if (target) await showReport(target.id);
    else {
      $("reader-head").hidden = true;
      const empty = node("div", undefined, "empty");
      empty.append(node("h3", "这里会显示生成好的快报"), node("p", "回到主页选好群和时间范围，点「生成快报」就行。"));
      const back = button("去主页", () => go("#home"), "btn btn-sm");
      empty.append(back);
      $("report-content").replaceChildren(empty);
    }
  }

  async function showReport(id) {
    state.activeReportId = id;
    const version = ++state.reportVersion;
    for (const item of $("report-list").querySelectorAll(".report-item")) {
      item.setAttribute("aria-current", String(item.dataset.reportId === id));
    }
    const report = await request("GET", `/api/reports/${enc(id)}`);
    if (version !== state.reportVersion) return;
    const meta = state.reports.find(entry => entry.id === id);
    state.reportMarkdown = report.markdown;
    $("reader-head").hidden = false;
    $("reader-title").textContent = report.title || meta?.title || report.name;
    $("reader-meta").textContent = [
      shortPeriod(meta?.period), meta?.groups?.length ? `${meta.groups.length} 个群` : "", meta ? `${fmtTime(meta.created)} 生成` : "",
    ].filter(Boolean).join(" · ");
    $("report-content").replaceChildren(markdown(report.markdown.replace(/^\uFEFF?# [^\n]*\n?/, "")));
  }

  async function copyReport() {
    const text = state.reportMarkdown;
    if (!text) return;
    await task(async () => {
      try { await navigator.clipboard.writeText(text); }
      catch {
        const area = node("textarea");
        area.value = text;
        area.className = "sr-only";
        document.body.append(area);
        area.select();
        const ok = document.execCommand("copy");
        area.remove();
        if (!ok) throw new Error("没能复制，请直接打开报告文件。");
      }
    }, { key: "copy", success: "已复制快报原文（Markdown）" });
  }

  async function revealFolder(id) {
    await task(() => request("POST", "/api/reports/open-folder", id ? { id } : {}), {
      key: "folder", loading: "正在打开文件夹…", success: "已打开报告文件夹",
    });
  }

  // ---------------------------------------------------------------- 设置抽屉

  function setKeyVisible(visible) {
    const input = $("api-key");
    const toggle = $("toggle-key");
    input.type = visible ? "text" : "password";
    toggle.setAttribute("aria-pressed", String(visible));
    toggle.setAttribute("aria-label", visible ? "隐藏 API Key" : "显示 API Key");
    toggle.querySelector("use").setAttribute("href", visible ? "#i-eye-off" : "#i-eye");
  }

  function renderPathHints() {
    const current = state.config.config;
    const paths = state.config.paths || {};
    const hint = (inputId, hintId, saved, effective, fallback) => {
      const value = $(inputId).value.trim();
      $(hintId).textContent = !value ? `留空时用 ${fallback || "默认目录"}`
        : value === saved && effective ? `实际位置：${effective}` : "保存后生效";
    };
    hint("export-dir", "export-dir-hint", current.export_dir || "", paths.export_dir, paths.default_export_dir);
    hint("report-dir", "report-dir-hint", current.report_dir || "", paths.report_dir, paths.default_report_dir);
  }

  function setTestResult(text = "", kind = "") {
    const target = $("test-result");
    target.className = `inline-status${kind && kind !== "loading" ? ` ${kind}` : ""}`;
    const lead = kind === "loading" ? node("span", undefined, "spinner") : kind === "ok" ? icon("check") : kind === "error" ? icon("error") : null;
    target.replaceChildren(...(lead ? [lead] : []), ...(text ? [node("span", text)] : []));
  }

  function openSettings(focusId, firstRun = false) {
    const current = state.config.config;
    $("setup-note").hidden = !firstRun;
    $("settings-title").textContent = firstRun ? "首次设置" : "设置";
    $("api-url").value = current.deepseek?.base_url || "https://api.deepseek.com";
    $("api-model").value = current.deepseek?.model || "deepseek-flash";
    $("api-key").value = "";
    const masked = current.deepseek?.api_key;
    $("api-key").placeholder = masked ? "留空就不改" : "粘贴你的 API Key";
    $("api-key-hint").textContent = masked
      ? `已保存（${masked}）。换了接口地址要重新填。`
      : "还没保存过。用本机模型（比如 Ollama）可以不填。";
    setKeyVisible(false);
    $("export-dir").value = current.export_dir || "";
    $("report-dir").value = current.report_dir || "";
    $("daily-hours").value = state.config.presets?.daily?.hours ?? 24;
    $("weekly-hours").value = state.config.presets?.weekly?.hours ?? 168;
    $("save-raw").checked = current.save_raw === true;
    renderPathHints();
    setTestResult();
    inlineMessage($("settings-error"));
    const dialog = $("settings");
    if (!dialog.open) dialog.showModal();
    dialog.append($("toasts"));  // 模态框在最上层，toast 放进去才看得见
    ($(focusId) || $("api-url")).focus();
  }

  function closeSettings() {
    if ($("settings").open) $("settings").close();
  }

  async function settingsConfig() {
    // 整体替换配置需要带上完整的当前内容，包括界面不编辑的字段。
    const { config: { selection: _selection, window: _window, ...latest } } = await request("GET", "/api/config");
    const hours = { daily: $("daily-hours").valueAsNumber, weekly: $("weekly-hours").valueAsNumber };
    if (Object.values(hours).some(value => !(value > 0 && value <= MAX_HOURS))) {
      throw new Error("快报小时数要大于 0、不超过 100000。");
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

  async function saveSettings(event) {
    event.preventDefault();
    if (!$("settings-form").reportValidity()) return;
    const submit = $("save-settings");
    submit.disabled = true;
    inlineMessage($("settings-error"));
    try {
      const view = await request("PUT", "/api/config", await settingsConfig());
      applyConfig(view);
      closeSettings();
      toast("设置已保存", { type: "success", key: "settings" });
      buildWindowButtons();
      estimate();
      await task(() => loadSources(), { key: "sources" });
      if (state.view === "reports") await task(loadReports, { key: "reports" });
    } catch (error) {
      inlineMessage($("settings-error"), error.message, "error");
    } finally {
      submit.disabled = false;
    }
  }

  async function testConnection() {
    if (!$("settings-form").reportValidity()) return;
    const control = $("test-connection");
    control.disabled = true;
    setTestResult("正在连接…", "loading");
    try {
      const result = await request("POST", "/api/test-connection", await settingsConfig());
      setTestResult(result.message, result.ok ? "ok" : "error");
    } catch (error) {
      setTestResult(error.message, "error");
    } finally {
      control.disabled = false;
    }
  }

  // ---------------------------------------------------------------- 事件绑定

  function bindControls() {
    window.addEventListener("hashchange", navigate);

    // 顶栏与设置
    $("open-settings").addEventListener("click", () => openSettings());
    $("toggle-theme").addEventListener("click", cycleTheme);
    systemDark?.addEventListener?.("change", () => applyTheme(document.documentElement.dataset.theme));
    $("close-settings").addEventListener("click", closeSettings);
    $("cancel-settings").addEventListener("click", closeSettings);
    $("settings").addEventListener("click", event => { if (event.target === $("settings")) closeSettings(); });
    $("settings").addEventListener("close", () => {
      $("api-key").value = "";
      setKeyVisible(false);
      document.body.append($("toasts"));
    });
    $("settings-form").addEventListener("submit", saveSettings);
    $("test-connection").addEventListener("click", testConnection);
    $("toggle-key").addEventListener("click", () => setKeyVisible($("api-key").type === "password"));
    for (const id of ["export-dir", "report-dir"]) $(id).addEventListener("input", renderPathHints);

    // 1 选择群
    $("refresh-sources").addEventListener("click", refreshSources);
    $("import-input").addEventListener("change", event => {
      importFiles([...event.target.files]);
      event.target.value = "";
    });
    $("dropzone-pick").addEventListener("click", () => $("import-input").click());
    $("empty-change-dir").addEventListener("click", () => openSettings("export-dir"));
    $("cancel-import").addEventListener("click", () => {
      state.pendingImports.shift();
      toast("跳过了这个文件");
      showNextImport();
    });
    $("import-group").addEventListener("submit", async event => {
      event.preventDefault();
      const file = state.pendingImports[0];
      if (!file) return;
      const query = new URLSearchParams({ group_id: $("import-group-id").value.trim(), name: $("import-group-name").value.trim() });
      const submit = event.submitter;
      submit.disabled = true;
      const result = await task(() => uploadFile(file, query), {
        loading: "正在导入…", key: "import",
        success: value => (value && value !== true ? `已导入「${value.saved}」` : "保留了同名的原文件"),
      });
      submit.disabled = false;
      if (!result) return;
      state.pendingImports.shift();
      if (result !== true) await task(() => loadSources(), { key: "sources" });
      showNextImport();
    });

    // 整个窗口都能拖入文件
    let dragDepth = 0;
    const hasFiles = event => [...(event.dataTransfer?.types || [])].includes("Files");
    window.addEventListener("dragenter", event => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      dragDepth++;
      $("drop-overlay").hidden = false;
    });
    window.addEventListener("dragover", event => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
    });
    window.addEventListener("dragleave", event => {
      if (!hasFiles(event)) return;
      dragDepth = Math.max(0, dragDepth - 1);
      if (!dragDepth) $("drop-overlay").hidden = true;
    });
    window.addEventListener("drop", event => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      dragDepth = 0;
      $("drop-overlay").hidden = true;
      if ($("settings").open) return;
      go("#home");
      importFiles([...event.dataTransfer.files]);
    });

    // 2 时间范围
    $("custom-window").addEventListener("input", () => { renderWindow(); estimate(); });
    $("save-default").addEventListener("click", saveDefaults);

    // 3 生成
    $("run").addEventListener("click", startRun);
    for (const control of document.querySelectorAll("[data-cancel-job]")) control.addEventListener("click", cancelJob);

    // 关注点
    $("profile").addEventListener("input", () => {
      $("profile-status").className = "save-status";
      $("profile-status").textContent = "有改动，离开输入框会保存";
    });
    $("profile").addEventListener("change", saveProfile);
    $("explain").addEventListener("click", event => {
      const level = event.target.closest("button")?.dataset.level;
      if (level && level !== state.config.explain_level) setExplain(level);
    });
    bindInline($("type-label"), commitTypeLabel);
    bindInline($("type-focus"), commitTypeFocus);
    $("delete-type").addEventListener("click", deleteType);
    $("add-type").addEventListener("click", () => setNewTypeForm(true));
    $("cancel-new-type").addEventListener("click", () => { setNewTypeForm(false); $("add-type").focus(); });
    $("new-type-form").addEventListener("submit", createType);
    $("new-type-label").addEventListener("keydown", event => {
      if (event.key === "Escape") { event.preventDefault(); setNewTypeForm(false); $("add-type").focus(); }
    });
    $("add-category").addEventListener("click", addCategory);

    // 分类拖拽排序
    const list = $("category-list");
    list.addEventListener("dragover", event => {
      const target = dropTarget(event);
      clearDropMarks();
      if (!target) return;
      event.preventDefault();
      target.row.classList.add(target.before ? "drop-before" : "drop-after");
    });
    list.addEventListener("drop", event => {
      const target = dropTarget(event);
      clearDropMarks();
      if (!target) return;
      event.preventDefault();
      const { row, topicKey } = state.drag;
      if (target.before) target.row.before(row);
      else target.row.after(row);
      moveCategory(topicKey, row.dataset.name, categoryRows().indexOf(row));
    });

    // 快报
    for (const control of document.querySelectorAll("[data-open-folder]")) control.addEventListener("click", () => revealFolder());
    $("copy-report").addEventListener("click", copyReport);
    $("reveal-report").addEventListener("click", () => revealFolder(state.activeReportId));

    // 键盘：Ctrl+Enter 生成；Esc 关闭菜单（抽屉由 dialog 自己处理 Esc）
    document.addEventListener("keydown", event => {
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && state.view === "home" && !$("settings").open) {
        event.preventDefault();
        startRun();
      }
      if (event.key === "Escape") {
        for (const menu of document.querySelectorAll("details.menu[open]")) {
          menu.open = false;
          menu.querySelector("summary").focus();
        }
      }
    });
    document.addEventListener("click", event => {
      for (const menu of document.querySelectorAll("details.menu[open]")) {
        if (!menu.contains(event.target)) menu.open = false;
      }
    });
  }

  // ---------------------------------------------------------------- 启动

  async function init() {
    state.token = loadToken();
    applyTheme();
    const status = await request("GET", "/api/status");
    applyConfig(await request("GET", "/api/config"));
    applyTheme(state.config.config.ui_theme);
    restoreWindow(state.config.defaults?.window);
    buildWindowButtons();
    bindControls();
    state.job.id = status.running_job || undefined;
    await loadSources(state.config.defaults?.selection ?? null);
    navigate();
    if (state.job.id) poll();
    if (!status.config_exists) openSettings(undefined, true);
  }

  init().catch(error => fatal(error.message));
})();
