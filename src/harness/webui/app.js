"use strict";

const STORAGE_KEY = "harness.dashboard.tasks.v1";
const MODE_KEY = "harness.dashboard.llm_mode";
const LLM_MODE_DEFAULT = "mock";
const POLL_MS = 2000;

const STATUS_LABEL = {
  pending: "PENDING",
  running: "RUNNING",
  paused: "PAUSED",
  completed: "COMPLETED",
  failed: "FAILED",
  unreachable: "任务不可达",
};

const $ = (id) => document.getElementById(id);

let tasks = {};
let taskIds = [];
let selectedId = null;
let currentTab = "form";
let toastTimer = null;

function loadState() {
  let arr = [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) arr = JSON.parse(raw);
  } catch (err) {
    arr = [];
  }
  for (const payload of arr) {
    if (!payload || !payload.id || tasks[payload.id]) continue;
    taskIds.push(payload.id);
    tasks[payload.id] = {
      payload,
      status: "pending",
      iterations: 0,
      error: null,
      feedback: null,
      logs: [],
      messages: [],
    };
  }
  if (taskIds.length > 0 && !selectedId) selectedId = taskIds[0];
}

function saveState() {
  const arr = taskIds.map((id) => tasks[id] && tasks[id].payload).filter(Boolean);
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(arr));
  } catch (err) {
    /* ignore storage quota errors */
  }
}

async function fetchJson(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) {
    let detail = "HTTP " + res.status;
    try {
      const body = await res.json();
      if (body && body.detail) detail = body.detail;
    } catch (err) {
      /* keep default detail */
    }
    const error = new Error(detail);
    error.status = res.status;
    throw error;
  }
  return res.json();
}

async function pollTask(id) {
  const snap = await fetchJson("/api/tasks/" + encodeURIComponent(id));
  let logs = [];
  try {
    const res = await fetchJson("/api/tasks/" + encodeURIComponent(id) + "/logs");
    logs = res.logs || [];
  } catch (err) {
    /* logs are best-effort */
  }
  const task = tasks[id];
  task.status = snap.status || "pending";
  task.iterations = snap.iterations || 0;
  task.error = snap.error || null;
  task.feedback = snap.feedback || null;
  task.logs = logs;
}

async function probeConnection() {
  try {
    await fetch("/api/health");
    return true;
  } catch (err) {
    return false;
  }
}

async function pollOnce() {
  let connOk = await probeConnection();
  for (const id of taskIds) {
    try {
      await pollTask(id);
    } catch (err) {
      if (err.status === 404) {
        tasks[id].status = "unreachable";
      } else if (!err.status) {
        connOk = false;
      }
    }
  }
  const sel = tasks[selectedId];
  if (sel) {
    try {
      const res = await fetchJson(
        "/api/tasks/" + encodeURIComponent(selectedId) + "/messages"
      );
      sel.messages = res.messages || [];
    } catch (err) {
      if (!err.status) connOk = false;
    }
  }
  setConnection(connOk);
  renderTaskList();
  if (selectedId) renderDetail();
}

function setConnection(ok) {
  const status = $("conn-status");
  status.classList.remove("conn-mid", "conn-on", "conn-off");
  status.classList.add(ok ? "conn-on" : "conn-off");
  $("conn-label").textContent = ok ? "已连接" : "连接中断";
  status.title = ok ? "API 可达" : "API 不可达，正在自动重试…";
}

function renderTaskList() {
  const list = $("task-list");
  list.innerHTML = "";
  $("task-list-empty").classList.toggle("hidden", taskIds.length > 0);
  for (const id of taskIds) {
    const task = tasks[id];
    if (!task) continue;
    const li = document.createElement("li");
    li.className = "task-item" + (id === selectedId ? " active" : "");

    const head = document.createElement("div");
    head.className = "task-item-head";
    const name = document.createElement("span");
    name.className = "task-item-id";
    name.textContent = id;
    const badge = document.createElement("span");
    badge.className = "badge badge-" + task.status;
    badge.textContent = STATUS_LABEL[task.status] || task.status;
    head.appendChild(name);
    head.appendChild(badge);

    const prompt = document.createElement("div");
    prompt.className = "task-item-prompt";
    const promptText = (task.payload && task.payload.prompt) || "";
    prompt.textContent = promptText ? promptText.slice(0, 80) : "（无提示词）";

    li.appendChild(head);
    li.appendChild(prompt);
    li.addEventListener("click", () => selectTask(id));
    list.appendChild(li);
  }
}

function renderDetail() {
  const task = tasks[selectedId];
  const content = $("detail-content");
  const empty = $("detail-empty");
  if (!task) {
    content.classList.add("hidden");
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");
  content.classList.remove("hidden");

  $("detail-title").textContent = selectedId;
  const statusBadge = $("detail-status");
  statusBadge.className = "badge badge-" + task.status;
  statusBadge.textContent = STATUS_LABEL[task.status] || task.status;

  $("meta-id").textContent = selectedId;
  $("meta-prompt").textContent = task.payload.prompt || "";
  $("meta-eval").textContent = task.payload.eval_command || "—";
  $("meta-iterations").textContent =
    String(task.iterations) + " / " + String(task.payload.max_iterations || "?");
  $("meta-timeout").textContent = String(task.payload.timeout || "?") + " s";
  $("meta-llm-mode").textContent =
    task.payload.llm_mode === "real"
      ? "真实 LLM"
      : task.payload.llm_mode === "mock"
      ? "离线 Mock"
      : "—";

  $("meta-error").classList.toggle("hidden", !task.error);
  $("meta-error").textContent = task.error ? "错误：" + task.error : "";
  $("meta-feedback").classList.toggle("hidden", !task.feedback);
  $("meta-feedback").textContent = task.feedback ? "反馈：" + task.feedback : "";

  renderHitl(task);
  renderInterrupt(task);
  renderLogs(task.logs || []);
  renderConversation(task);
}

function renderHitl(task) {
  $("hitl-actions").classList.toggle("hidden", task.status !== "paused");
}

function renderInterrupt(task) {
  $("interrupt-wrap").classList.toggle("hidden", task.status !== "running");
}

function renderLogs(logs) {
  const area = $("log-area");
  const text = logs.join("\n");
  const switched = area.getAttribute("data-task-id") !== selectedId;
  if (!switched && text === area.getAttribute("data-rendered")) return;
  area.setAttribute("data-task-id", selectedId);
  area.setAttribute("data-rendered", text);
  const stick =
    switched ||
    area.scrollHeight - area.scrollTop - area.clientHeight < 24;
  area.textContent = text;
  if (stick) area.scrollTop = area.scrollHeight;
}

function renderConversation(task) {
  const box = $("conversation");
  const messages = task.messages || [];
  box.innerHTML = "";
  if (messages.length === 0) {
    const hint = document.createElement("div");
    hint.className = "empty-hint";
    hint.textContent = "暂无消息。任务运行中输入内容并发送，可向 Agent 注入指令。";
    box.appendChild(hint);
    return;
  }
  for (const message of messages) {
    const row = document.createElement("div");
    const role = message.role === "user" ? "msg-user" : "msg-agent";
    row.className = "msg " + role;
    const meta = document.createElement("div");
    meta.className = "msg-role";
    meta.textContent = message.role === "user" ? "用户" : "Agent";
    const content = document.createElement("div");
    content.className = "msg-content";
    content.textContent = message.content || "";
    row.appendChild(meta);
    row.appendChild(content);
    box.appendChild(row);
  }
  box.scrollTop = box.scrollHeight;
}

function selectTask(id) {
  selectedId = id;
  renderTaskList();
  renderDetail();
}

function addTask(payload, id) {
  const taskId = id || payload.id;
  if (tasks[taskId]) return;
  taskIds.unshift(taskId);
  tasks[taskId] = {
    payload,
    status: "pending",
    iterations: 0,
    error: null,
    feedback: null,
    logs: [],
    messages: [],
  };
  selectedId = taskId;
  saveState();
  renderTaskList();
  renderDetail();
}

/* ---------- new task modal ---------- */

function openModal() {
  $("form-error").classList.add("hidden");
  if (currentTab === "yaml") syncFormToYaml();
  $("modal-backdrop").classList.remove("hidden");
  $("field-id").focus();
}

function closeModal() {
  $("modal-backdrop").classList.add("hidden");
}

function setTab(tab) {
  currentTab = tab;
  $("tab-form").classList.toggle("tab-active", tab === "form");
  $("tab-yaml").classList.toggle("tab-active", tab === "yaml");
  $("form-fields").classList.toggle("hidden", tab !== "form");
  $("yaml-fields").classList.toggle("hidden", tab !== "yaml");
  if (tab === "yaml") syncFormToYaml();
}

function readForm() {
  const task = {
    id: $("field-id").value.trim(),
    prompt: $("field-prompt").value.trim(),
  };
  const evalCommand = $("field-eval").value.trim();
  if (evalCommand) task.eval_command = evalCommand;
  const iterations = parseInt($("field-iterations").value, 10);
  const timeout = parseFloat($("field-timeout").value);
  if (!isNaN(iterations) && iterations >= 1) task.max_iterations = iterations;
  if (!isNaN(timeout) && timeout > 0) task.timeout = timeout;
  return task;
}

function yamlQuote(value) {
  const needsQuote =
    value === "" ||
    /^[\s#"'\-?:,\[\]{}&*!|>%@`]/.test(value) ||
    /[\s:]$/.test(value) ||
    /^[0-9-]/.test(value);
  return needsQuote ? JSON.stringify(value) : value;
}

function objectToYaml(task) {
  const lines = [];
  if (task.id) lines.push("id: " + yamlQuote(String(task.id)));
  if (task.prompt) lines.push("prompt: " + yamlQuote(String(task.prompt)));
  if (task.eval_command) {
    lines.push("eval_command: " + yamlQuote(String(task.eval_command)));
  }
  if (typeof task.max_iterations === "number") {
    lines.push("max_iterations: " + task.max_iterations);
  }
  if (typeof task.timeout === "number") {
    lines.push("timeout: " + task.timeout);
  }
  return lines.join("\n");
}

function syncFormToYaml() {
  $("yaml-input").value = objectToYaml(readForm());
}

function yamlToObject(text) {
  const task = {};
  const lines = text.split(/\r?\n/);
  for (const line of lines) {
    if (/^\s/.test(line)) {
      throw new Error("不支持的 YAML：暂不支持缩进嵌套，请使用扁平键值");
    }
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const match = trimmed.match(/^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$/);
    if (!match) throw new Error("无法解析 YAML 行：" + line);
    const key = match[1];
    const raw = match[2].trim();
    let value;
    if (raw === "" || raw === "null" || raw === "~") {
      value = null;
    } else if (raw.startsWith('"') && raw.endsWith('"')) {
      try {
        value = JSON.parse(raw);
      } catch (err) {
        value = raw.slice(1, -1);
      }
    } else if (raw.startsWith("'") && raw.endsWith("'")) {
      value = raw.slice(1, -1).replace(/''/g, "'");
    } else if (raw === "true") {
      value = true;
    } else if (raw === "false") {
      value = false;
    } else if (/^-?\d+$/.test(raw)) {
      value = parseInt(raw, 10);
    } else if (/^-?\d+\.\d+$/.test(raw)) {
      value = parseFloat(raw);
    } else if (/^[{[\-]/.test(raw)) {
      throw new Error("不支持的 YAML 值：" + raw);
    } else {
      value = raw;
    }
    task[key] = value;
  }
  return task;
}

function showFormError(message) {
  const box = $("form-error");
  box.textContent = message;
  box.classList.remove("hidden");
}

/* ---------- API Key modal ---------- */

function openApiKeyModal() {
  $("cred-error").classList.add("hidden");
  $("cred-status").classList.add("hidden");
  $("cred-value").value = "";
  $("api-key-modal").classList.remove("hidden");
  refreshCredStatus();
}

function closeApiKeyModal() {
  $("api-key-modal").classList.add("hidden");
}

function credUrl(service, key) {
  return (
    "/api/credential/" +
    encodeURIComponent(service) +
    "/" +
    encodeURIComponent(key)
  );
}

function showCredError(message) {
  const box = $("cred-error");
  box.textContent = message;
  box.classList.remove("hidden");
}

async function refreshCredStatus() {
  const status = $("cred-status");
  const service = $("cred-service").value.trim();
  const key = $("cred-key").value.trim();
  status.textContent = "查询中…";
  status.className = "callout";
  status.classList.remove("hidden");
  try {
    const res = await fetchJson(credUrl(service, key));
    if (res.configured) {
      status.textContent = "已配置（key 已保存，不会回显明文）";
      status.classList.add("callout-ok");
    } else {
      status.textContent = "未配置";
      status.classList.add("callout-warn");
    }
  } catch (err) {
    status.textContent = "查询失败：" + err.message;
    status.classList.add("callout-error");
  }
}

async function saveCredential() {
  $("cred-error").classList.add("hidden");
  const service = $("cred-service").value.trim();
  const key = $("cred-key").value.trim();
  const value = $("cred-value").value;
  if (!service || !key) {
    showCredError("Service 与 Key 不能为空");
    return;
  }
  if (!value) {
    showCredError("请输入 key 值");
    return;
  }
  const saveBtn = $("cred-save");
  saveBtn.disabled = true;
  try {
    await fetchJson(credUrl(service, key), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value }),
    });
    $("cred-value").value = "";
    showToast("API Key 已保存");
    await refreshCredStatus();
  } catch (err) {
    showCredError("保存失败：" + err.message);
  } finally {
    saveBtn.disabled = false;
  }
}

async function clearCredential() {
  $("cred-error").classList.add("hidden");
  const service = $("cred-service").value.trim();
  const key = $("cred-key").value.trim();
  if (!service || !key) {
    showCredError("Service 与 Key 不能为空");
    return;
  }
  try {
    await fetchJson(credUrl(service, key), { method: "DELETE" });
    $("cred-value").value = "";
    showToast("API Key 已清除");
    await refreshCredStatus();
  } catch (err) {
    showCredError("清除失败：" + err.message);
  }
}

/* ---------- LLM mode ---------- */

const LLM_MODE_LABEL = { mock: "离线 Mock", real: "真实 LLM" };

function getLlmMode() {
  const saved = localStorage.getItem(MODE_KEY);
  return saved === "real" ? "real" : LLM_MODE_DEFAULT;
}

function persistLlmMode(mode) {
  try {
    localStorage.setItem(MODE_KEY, mode);
  } catch (err) {
    /* ignore storage quota errors */
  }
}

function setLlmMode(mode) {
  persistLlmMode(mode);
  $("llm-mode-select").value = mode;
  $("llm-mode").title =
    "LLM 模式：" + LLM_MODE_LABEL[mode] + "（任务运行时生效）";
}

function initLlmMode() {
  const mode = getLlmMode();
  $("llm-mode-select").value = mode;
  $("llm-mode").title =
    "LLM 模式：" + LLM_MODE_LABEL[mode] + "（任务运行时生效）";
}

async function credentialConfigured(service, key) {
  try {
    const res = await fetchJson(credUrl(service, key));
    return !!res.configured;
  } catch (err) {
    return false;
  }
}

async function onLlmModeChange() {
  const mode = $("llm-mode-select").value;
  setLlmMode(mode);
  if (mode === "real") {
    const configured = await credentialConfigured("harness", "openai");
    if (!configured) {
      showToast(
        "真实 LLM 需要 API Key：请打开「API Key」保存，并在服务端 config 设置 llm.credential_ref + base_url"
      );
      openApiKeyModal();
    } else {
      showToast("真实 LLM：该任务提交后将以真实 LLM 运行（任务运行时生效）");
    }
  } else {
    showToast("离线 Mock：该任务提交后将以 MockLLM 运行（演示循环）");
  }
}

/* ---------- conversation ---------- */

async function sendMessage() {
  const box = $("message-input");
  const content = box.value.trim();
  if (!content) return;
  if (!selectedId) {
    showToast("请先选择任务");
    return;
  }
  try {
    await fetchJson(
      "/api/tasks/" + encodeURIComponent(selectedId) + "/message",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      }
    );
    const task = tasks[selectedId];
    task.messages = task.messages || [];
    task.messages.push({ role: "user", content });
    box.value = "";
    renderConversation(task);
  } catch (err) {
    showToast("发送失败：" + err.message);
  }
}

function onFileChosen(event) {
  const file = event.target.files[0];
  event.target.value = "";
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    const box = $("message-input");
    box.value = String(reader.result || "");
    box.focus();
    showToast("已读取文件：" + file.name);
  };
  reader.onerror = () => showToast("文件读取失败：" + file.name);
  reader.readAsText(file);
}

/* ---------- HITL / interrupt ---------- */

async function hitl(decision) {
  if (!selectedId) return;
  const actions = $("hitl-actions");
  actions.classList.add("hidden");
  try {
    await fetchJson("/api/hitl/" + encodeURIComponent(selectedId) + "/" + decision, {
      method: "POST",
    });
    await pollOnce();
  } catch (err) {
    showToast("操作失败：" + err.message);
    renderDetail();
  }
}

async function interruptTask() {
  if (!selectedId) return;
  try {
    await fetchJson(
      "/api/tasks/" + encodeURIComponent(selectedId) + "/interrupt",
      { method: "POST" }
    );
    showToast("已请求中断任务");
    await pollOnce();
  } catch (err) {
    showToast("中断失败：" + err.message);
  }
}

/* ---------- toast ---------- */

function showToast(message) {
  const toast = $("toast");
  toast.textContent = message;
  toast.classList.add("toast-show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("toast-show"), 3000);
}

/* ---------- wire up ---------- */

$("new-task-btn").addEventListener("click", openModal);
$("modal-close").addEventListener("click", closeModal);
$("form-cancel").addEventListener("click", closeModal);
$("modal-backdrop").addEventListener("click", (event) => {
  if (event.target === $("modal-backdrop")) closeModal();
});
$("api-key-btn").addEventListener("click", openApiKeyModal);
$("llm-mode-select").addEventListener("change", onLlmModeChange);
$("api-key-close").addEventListener("click", closeApiKeyModal);
$("cred-cancel").addEventListener("click", closeApiKeyModal);
$("api-key-modal").addEventListener("click", (event) => {
  if (event.target === $("api-key-modal")) closeApiKeyModal();
});
$("cred-form").addEventListener("submit", (event) => {
  event.preventDefault();
  saveCredential();
});
$("cred-clear").addEventListener("click", clearCredential);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeModal();
    closeApiKeyModal();
  }
});

$("tab-form").addEventListener("click", () => setTab("form"));
$("tab-yaml").addEventListener("click", () => setTab("yaml"));

$("task-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("form-error").classList.add("hidden");
  let task;
  try {
    task =
      currentTab === "yaml"
        ? yamlToObject($("yaml-input").value)
        : readForm();
  } catch (err) {
    showFormError(err.message);
    return;
  }
  if (!task.id || !task.prompt) {
    showFormError("必须填写任务 ID 与 Prompt");
    return;
  }
  task.llm_mode = getLlmMode();
  const submitBtn = $("form-submit");
  submitBtn.disabled = true;
  try {
    const res = await fetchJson("/api/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(task),
    });
    addTask(task, res.task_id);
    closeModal();
    await pollOnce();
  } catch (err) {
    showFormError("提交失败：" + err.message);
  } finally {
    submitBtn.disabled = false;
  }
});

$("hitl-approve").addEventListener("click", () => hitl("approve"));
$("hitl-reject").addEventListener("click", () => hitl("reject"));
$("interrupt-btn").addEventListener("click", interruptTask);

$("upload-button").addEventListener("click", () => $("file-input").click());
$("file-input").addEventListener("change", onFileChosen);
$("send-button").addEventListener("click", sendMessage);
$("message-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    sendMessage();
  }
});

loadState();
initLlmMode();
renderTaskList();
renderDetail();
pollOnce();
setInterval(pollOnce, POLL_MS);
