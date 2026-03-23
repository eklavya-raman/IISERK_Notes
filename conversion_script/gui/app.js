const dom = {
  workspaceRoot: document.getElementById("workspace-root"),
  tabButtons: document.querySelectorAll(".tab-btn"),
  tabConverter: document.getElementById("tab-converter"),
  tabPublisher: document.getElementById("tab-publisher"),

  convertMode: document.getElementById("convert-mode"),
  convertSection: document.getElementById("convert-section"),
  convertTitle: document.getElementById("convert-title"),
  convertImageBase: document.getElementById("convert-image-base"),
  texFilter: document.getElementById("tex-filter"),
  htmlFilter: document.getElementById("html-filter"),
  texList: document.getElementById("tex-file-list"),
  htmlList: document.getElementById("html-file-list"),

  statTexTotal: document.getElementById("stat-tex-total"),
  statTexLinked: document.getElementById("stat-tex-linked"),
  statHtmlTotal: document.getElementById("stat-html-total"),

  publishRemoteUrl: document.getElementById("publish-remote-url"),
  publishRemoteName: document.getElementById("publish-remote-name"),
  publishTargetBranch: document.getElementById("publish-target-branch"),
  publishBranch: document.getElementById("publish-branch"),
  publishHtmlDir: document.getElementById("publish-html-dir"),

  btnRefresh: document.getElementById("btn-refresh"),
  btnSelectAll: document.getElementById("btn-tex-select-all"),
  btnSelectLinked: document.getElementById("btn-tex-select-linked"),
  btnClearTex: document.getElementById("btn-tex-clear"),
  btnLink: document.getElementById("btn-link"),
  btnConvert: document.getElementById("btn-convert"),
  btnPublish: document.getElementById("btn-publish"),
  btnCopyLog: document.getElementById("btn-copy-log"),
  btnClearLog: document.getElementById("btn-clear-log"),
  btnStopApp: document.getElementById("btn-stop-app"),

  runStatus: document.getElementById("run-status"),
  log: document.getElementById("output-log"),
};

const PREFS_KEY = "notes-manager-gui-prefs";

const state = {
  data: null,
  busy: false,
  publisherInitialized: false,
  selectedTexPaths: new Set(),
  selectedHtmlPath: "",
  prefs: {
    convertMode: "selected",
    convertSection: "",
    convertTitle: "",
    convertImageBase: "",
    publishRemoteUrl: "",
    publishRemoteName: "",
    publishTargetBranch: "",
    publishBranch: "",
    publishHtmlDir: "",
  },
};

const actionButtons = [
  dom.btnRefresh,
  dom.btnSelectAll,
  dom.btnSelectLinked,
  dom.btnClearTex,
  dom.btnLink,
  dom.btnConvert,
  dom.btnPublish,
];

function nowStamp() {
  return new Date().toLocaleTimeString();
}

function logLine(text) {
  dom.log.textContent += `[${nowStamp()}] ${text}\n`;
  dom.log.scrollTop = dom.log.scrollHeight;
}

function logBlock(text) {
  if (!text) {
    return;
  }
  dom.log.textContent += `${text}\n`;
  dom.log.scrollTop = dom.log.scrollHeight;
}

function setRunStatus(text, kind = "info") {
  dom.runStatus.textContent = `Status: ${text}`;
  dom.runStatus.classList.remove("status-ok", "status-error");

  if (kind === "ok") {
    dom.runStatus.classList.add("status-ok");
  } else if (kind === "error") {
    dom.runStatus.classList.add("status-error");
  }
}

function loadPrefs() {
  try {
    const raw = window.localStorage.getItem(PREFS_KEY);
    if (!raw) {
      return;
    }

    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") {
      return;
    }

    state.prefs = {
      ...state.prefs,
      ...parsed,
    };
  } catch (_error) {
    // Ignore malformed local prefs
  }
}

function savePrefs() {
  state.prefs = {
    convertMode: dom.convertMode.value,
    convertSection: dom.convertSection.value,
    convertTitle: dom.convertTitle.value,
    convertImageBase: dom.convertImageBase.value,
    publishRemoteUrl: dom.publishRemoteUrl.value,
    publishRemoteName: dom.publishRemoteName.value,
    publishTargetBranch: dom.publishTargetBranch.value,
    publishBranch: dom.publishBranch.value,
    publishHtmlDir: dom.publishHtmlDir.value,
  };

  try {
    window.localStorage.setItem(PREFS_KEY, JSON.stringify(state.prefs));
  } catch (_error) {
    // Ignore storage errors
  }
}

function applyPrefs() {
  dom.convertMode.value = state.prefs.convertMode || "selected";
  dom.convertTitle.value = state.prefs.convertTitle || "";
  dom.convertImageBase.value = state.prefs.convertImageBase || "";

  if (state.prefs.publishRemoteUrl) {
    dom.publishRemoteUrl.value = state.prefs.publishRemoteUrl;
  }
  if (state.prefs.publishRemoteName) {
    dom.publishRemoteName.value = state.prefs.publishRemoteName;
  }
  if (state.prefs.publishTargetBranch) {
    dom.publishTargetBranch.value = state.prefs.publishTargetBranch;
  }
  if (state.prefs.publishBranch) {
    dom.publishBranch.value = state.prefs.publishBranch;
  }
  if (state.prefs.publishHtmlDir) {
    dom.publishHtmlDir.value = state.prefs.publishHtmlDir;
  }
}

function setBusy(busy) {
  state.busy = busy;
  actionButtons.forEach((button) => {
    button.disabled = busy;
  });
}

function switchTab(target) {
  const converterActive = target === "converter";
  dom.tabConverter.hidden = !converterActive;
  dom.tabPublisher.hidden = converterActive;
  dom.tabConverter.classList.toggle("active", converterActive);
  dom.tabPublisher.classList.toggle("active", !converterActive);

  dom.tabButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === target);
  });
}

function fillSectionOptions(options) {
  const selectedBefore = dom.convertSection.value || state.prefs.convertSection || "";
  dom.convertSection.innerHTML = "";

  const empty = document.createElement("option");
  empty.value = "";
  empty.textContent = "(no override)";
  dom.convertSection.appendChild(empty);

  options.forEach((optionData) => {
    const option = document.createElement("option");
    option.value = optionData.value;
    option.textContent = optionData.label;
    dom.convertSection.appendChild(option);
  });

  if ([...dom.convertSection.options].some((option) => option.value === selectedBefore)) {
    dom.convertSection.value = selectedBefore;
  }
}

function renderTexFiles(files) {
  dom.texList.innerHTML = "";

  const query = (dom.texFilter.value || "").trim().toLowerCase();
  const filtered = files.filter((fileData) => {
    if (!query) {
      return true;
    }

    const haystack = `${fileData.displayPath} ${fileData.linkedHtmlDisplayPath || ""}`.toLowerCase();
    return haystack.includes(query);
  });

  if (!filtered.length) {
    const empty = document.createElement("div");
    empty.className = "muted";
    empty.textContent = files.length
      ? "No TeX files match the filter."
      : "No TeX files found in tex_files/white.";
    dom.texList.appendChild(empty);
    return;
  }

  filtered.forEach((fileData, index) => {
    const item = document.createElement("label");
    item.className = "list-item";
    item.htmlFor = `tex-check-${index}`;

    const firstLine = document.createElement("div");
    firstLine.className = "list-line";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.id = `tex-check-${index}`;
    checkbox.className = "tex-check";
    checkbox.dataset.path = fileData.path;
    checkbox.dataset.linked = fileData.linkedHtmlPath ? "true" : "false";
    checkbox.checked = state.selectedTexPaths.has(fileData.path);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) {
        state.selectedTexPaths.add(fileData.path);
      } else {
        state.selectedTexPaths.delete(fileData.path);
      }
    });

    const title = document.createElement("span");
    title.textContent = fileData.displayPath;

    firstLine.append(checkbox, title);

    if (fileData.linkedHtmlDisplayPath) {
      const badge = document.createElement("span");
      badge.className = "list-badge";
      badge.textContent = "Mapped";
      firstLine.appendChild(badge);
    }

    item.appendChild(firstLine);

    if (fileData.linkedHtmlDisplayPath) {
      const linked = document.createElement("div");
      linked.className = "muted";
      linked.textContent = `Linked HTML: ${fileData.linkedHtmlDisplayPath}`;
      item.appendChild(linked);
    }

    dom.texList.appendChild(item);
  });
}

function renderHtmlFiles(files) {
  dom.htmlList.innerHTML = "";

  const query = (dom.htmlFilter.value || "").trim().toLowerCase();
  const filtered = files.filter((fileData) => {
    if (!query) {
      return true;
    }
    return fileData.displayPath.toLowerCase().includes(query);
  });

  if (!filtered.length) {
    const empty = document.createElement("div");
    empty.className = "muted";
    empty.textContent = files.length ? "No HTML files match the filter." : "No HTML files found in html/.";
    dom.htmlList.appendChild(empty);
    return;
  }

  filtered.forEach((fileData, index) => {
    const item = document.createElement("label");
    item.className = "list-item";
    item.htmlFor = `html-radio-${index}`;

    const line = document.createElement("div");
    line.className = "list-line";

    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "html-target";
    radio.id = `html-radio-${index}`;
    radio.className = "html-radio";
    radio.dataset.path = fileData.path;
    radio.checked = state.selectedHtmlPath === fileData.path;
    radio.addEventListener("change", () => {
      if (radio.checked) {
        state.selectedHtmlPath = fileData.path;
      }
    });

    const text = document.createElement("span");
    text.textContent = fileData.displayPath;

    line.append(radio, text);
    item.appendChild(line);
    dom.htmlList.appendChild(item);
  });
}

function fillPublishDefaults(defaults) {
  if (!dom.publishRemoteUrl.value.trim()) {
    dom.publishRemoteUrl.value = defaults.remoteUrl;
  }
  if (!dom.publishRemoteName.value.trim()) {
    dom.publishRemoteName.value = defaults.remoteName;
  }
  if (!dom.publishTargetBranch.value.trim()) {
    dom.publishTargetBranch.value = defaults.targetBranch;
  }
  if (!dom.publishBranch.value.trim()) {
    dom.publishBranch.value = defaults.publishBranch;
  }
  if (!dom.publishHtmlDir.value.trim()) {
    dom.publishHtmlDir.value = defaults.htmlDir;
  }

  state.publisherInitialized = true;
}

function renderStats() {
  const texFiles = state.data?.texFiles || [];
  const htmlFiles = state.data?.htmlFiles || [];
  const linkedTexCount = texFiles.filter((fileData) => Boolean(fileData.linkedHtmlPath)).length;

  dom.statTexTotal.textContent = `${texFiles.length}`;
  dom.statTexLinked.textContent = `${linkedTexCount}`;
  dom.statHtmlTotal.textContent = `${htmlFiles.length}`;
}

function renderState() {
  if (!state.data) {
    return;
  }

  dom.workspaceRoot.textContent = state.data.workspaceRoot;
  fillSectionOptions(state.data.sectionOptions || []);
  renderTexFiles(state.data.texFiles || []);
  renderHtmlFiles(state.data.htmlFiles || []);
  fillPublishDefaults(state.data.publishDefaults || {});
  renderStats();
  savePrefs();
}

function getCheckedTexPaths() {
  return [...document.querySelectorAll(".tex-check:checked")].map((node) => node.dataset.path);
}

function getSelectedHtmlPath() {
  const selected = document.querySelector(".html-radio:checked");
  return selected ? selected.dataset.path : "";
}

function buildTexDisplayMap() {
  const items = state.data?.texFiles || [];
  return new Map(items.map((item) => [item.path, item.displayPath]));
}

function resolveConversionTargets(mode, checked) {
  if (mode === "selected") {
    return [...checked];
  }

  const texFiles = state.data?.texFiles || [];
  if (mode === "all") {
    return texFiles.map((item) => item.path);
  }

  if (mode === "linked") {
    return texFiles.filter((item) => Boolean(item.linkedHtmlPath)).map((item) => item.path);
  }

  return [];
}

function snapshotSelections() {
  state.selectedTexPaths = new Set(getCheckedTexPaths());
  const selectedHtml = getSelectedHtmlPath();
  if (selectedHtml) {
    state.selectedHtmlPath = selectedHtml;
  }
}

async function apiGet(path) {
  const response = await fetch(path, { method: "GET" });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `Request failed (${response.status})`);
  }
  return data;
}

async function apiPost(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload || {}),
  });

  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `Request failed (${response.status})`);
  }
  return data;
}

async function refreshState() {
  snapshotSelections();
  const result = await apiGet("/api/state");
  if (!result || !result.ok) {
    const message = result && result.error ? result.error : "Failed to load GUI state.";
    throw new Error(message);
  }

  state.data = result;
  renderState();
}

async function withBusy(action) {
  if (state.busy) {
    return;
  }

  setBusy(true);
  try {
    await action();
  } finally {
    setBusy(false);
  }
}

function writeCommandResult(result, label) {
  const status = result.ok ? "OK" : "ERROR";
  logLine(`${label} [${status}]: ${result.summary}`);
  setRunStatus(`${label} - ${result.summary}`, result.ok ? "ok" : "error");
  if (result.log) {
    logBlock(result.log);
  }
}

async function onLink() {
  const checked = getCheckedTexPaths();
  const htmlPath = getSelectedHtmlPath();

  if (checked.length !== 1) {
    alert("Please check exactly one TeX file to create/update a link.");
    return;
  }

  if (!htmlPath) {
    alert("Please choose one HTML target file.");
    return;
  }

  await withBusy(async () => {
    logLine("Running link update...");
    setRunStatus("Running link update...");
    const result = await apiPost("/api/link", {
      texPath: checked[0],
      htmlPath,
    });

    writeCommandResult(result, "Link");
    await refreshState();
  });
}

async function onConvert() {
  const mode = dom.convertMode.value;
  const checked = getCheckedTexPaths();

  const targets = resolveConversionTargets(mode, checked);

  if (!targets.length) {
    if (mode === "selected") {
      alert("Select at least one TeX file for selected mode.");
    } else if (mode === "linked") {
      alert("No mapped TeX files found. Create links first or switch mode.");
    } else {
      alert("No TeX files found to convert.");
    }
    return;
  }

  await withBusy(async () => {
    logLine(`Starting conversion (${mode}) for ${targets.length} file(s)...`);
    setRunStatus(`Starting conversion (${mode}) for ${targets.length} file(s)...`);
    savePrefs();

    const texDisplayMap = buildTexDisplayMap();
    let successCount = 0;
    let failCount = 0;

    for (let index = 0; index < targets.length; index += 1) {
      const texPath = targets[index];
      const displayPath = texDisplayMap.get(texPath) || texPath;
      const prefix = `[${index + 1}/${targets.length}]`;

      logLine(`${prefix} Converting ${displayPath}`);
      setRunStatus(`Converting ${index + 1}/${targets.length}: ${displayPath}`);

      try {
        const result = await apiPost("/api/convert", {
          mode: "selected",
          texPaths: [texPath],
          customTitle: dom.convertTitle.value,
          section: dom.convertSection.value,
          imageBaseUrl: dom.convertImageBase.value,
        });

        if (result.ok) {
          successCount += 1;
        } else {
          failCount += 1;
        }

        writeCommandResult(result, `Convert ${prefix}`);
      } catch (error) {
        failCount += 1;
        const message = `Convert ${prefix} [ERROR]: ${error.message}`;
        logLine(message);
        setRunStatus(message, "error");
      }
    }

    const summary = failCount === 0
      ? `Conversion finished: ${successCount}/${targets.length} file(s) succeeded.`
      : `Conversion finished: ${successCount}/${targets.length} succeeded, ${failCount} failed.`;

    logLine(summary);
    setRunStatus(summary, failCount === 0 ? "ok" : "error");

    await refreshState();
  });
}

async function onPublish() {
  await withBusy(async () => {
    logLine("Starting publish task...");
    setRunStatus("Starting publish task...");
    savePrefs();

    const result = await apiPost("/api/publish", {
      remoteUrl: dom.publishRemoteUrl.value,
      remoteName: dom.publishRemoteName.value,
      targetBranch: dom.publishTargetBranch.value,
      publishBranch: dom.publishBranch.value,
      htmlDir: dom.publishHtmlDir.value,
    });

    writeCommandResult(result, "Publish");
    await refreshState();
  });
}

async function onStopApp() {
  const approved = window.confirm("Stop the local GUI backend and close this app?");
  if (!approved) {
    return;
  }

  try {
    logLine("Stopping app...");
    setRunStatus("Stopping backend...");
    await apiPost("/api/shutdown", {});
    logLine("Shutdown requested. You can close this browser tab.");
    setRunStatus("Shutdown requested.");
  } catch (error) {
    logLine(`Failed to stop app: ${error.message}`);
    setRunStatus(`Failed to stop app: ${error.message}`, "error");
  }
}

function onSelectAllTex() {
  document.querySelectorAll(".tex-check").forEach((checkbox) => {
    checkbox.checked = true;
    state.selectedTexPaths.add(checkbox.dataset.path);
  });
}

function onSelectLinkedTex() {
  document.querySelectorAll(".tex-check").forEach((checkbox) => {
    const shouldSelect = checkbox.dataset.linked === "true";
    checkbox.checked = shouldSelect;
    if (shouldSelect) {
      state.selectedTexPaths.add(checkbox.dataset.path);
    } else {
      state.selectedTexPaths.delete(checkbox.dataset.path);
    }
  });
}

function onClearTexSelection() {
  document.querySelectorAll(".tex-check").forEach((checkbox) => {
    checkbox.checked = false;
    state.selectedTexPaths.delete(checkbox.dataset.path);
  });
}

async function onCopyLog() {
  const text = dom.log.textContent || "";
  if (!text.trim()) {
    setRunStatus("Nothing to copy.");
    return;
  }

  try {
    await navigator.clipboard.writeText(text);
    setRunStatus("Output log copied to clipboard.", "ok");
  } catch (_error) {
    setRunStatus("Clipboard copy failed in this environment.", "error");
  }
}

function bindEvents() {
  dom.tabButtons.forEach((button) => {
    button.addEventListener("click", () => switchTab(button.dataset.tab));
  });

  dom.btnRefresh.addEventListener("click", () => withBusy(refreshState));
  dom.btnSelectAll.addEventListener("click", onSelectAllTex);
  dom.btnSelectLinked.addEventListener("click", onSelectLinkedTex);
  dom.btnClearTex.addEventListener("click", onClearTexSelection);
  dom.btnLink.addEventListener("click", onLink);
  dom.btnConvert.addEventListener("click", onConvert);
  dom.btnPublish.addEventListener("click", onPublish);
  dom.btnCopyLog.addEventListener("click", onCopyLog);
  dom.btnStopApp.addEventListener("click", onStopApp);
  dom.btnClearLog.addEventListener("click", () => {
    dom.log.textContent = "";
    setRunStatus("Log cleared.");
  });

  dom.texFilter.addEventListener("input", () => {
    if (!state.data) {
      return;
    }
    renderTexFiles(state.data.texFiles || []);
  });

  dom.htmlFilter.addEventListener("input", () => {
    if (!state.data) {
      return;
    }
    renderHtmlFiles(state.data.htmlFiles || []);
  });

  [
    dom.convertMode,
    dom.convertSection,
    dom.convertTitle,
    dom.convertImageBase,
    dom.publishRemoteUrl,
    dom.publishRemoteName,
    dom.publishTargetBranch,
    dom.publishBranch,
    dom.publishHtmlDir,
  ].forEach((node) => {
    node.addEventListener("change", savePrefs);
    node.addEventListener("input", savePrefs);
  });
}

async function init() {
  loadPrefs();
  bindEvents();
  switchTab("converter");
  applyPrefs();
  logLine("Loading application state...");
  setRunStatus("Loading application state...");

  try {
    await refreshState();
    logLine("Ready.");
    setRunStatus("Ready", "ok");
  } catch (error) {
    logLine(`Initialization failed: ${error.message}`);
    setRunStatus(`Initialization failed: ${error.message}`, "error");
  }
}

document.addEventListener("DOMContentLoaded", init);
