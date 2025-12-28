const chatListEl = document.getElementById("chat-list");
const messagesEl = document.getElementById("messages");
const footerHintEl = document.getElementById("footer-hint");

const serverPill = document.getElementById("server-pill");
const toolsPill = document.getElementById("tools-pill");
const openaiPill = document.getElementById("openai-pill");

const newChatBtn = document.getElementById("new-chat");
const attachBtn = document.getElementById("attach-btn");
const runPipelineBtn = document.getElementById("run-pipeline");
const fileInput = document.getElementById("file-input");
const inputEl = document.getElementById("message-input");
const sendBtn = document.getElementById("send-btn");
const chatTitleEl = document.getElementById("chat-title");
const scrollBtn = document.getElementById("scroll-btn");
const uploadLabelEl = document.getElementById("upload-label");
const logoutBtn = document.getElementById("logout-btn");

let activeSessionId = null;
let latestUploadPath = null;

let pipelinePendingIdx = null;
let pipelineInChatCardId = null;

let isStreaming = false;
let isSending = false;
let isPipelineRunning = false;
let openaiConfigured = true;
let pipelineStatus = null;

function uid() {
  return Math.random().toString(36).slice(2);
}

async function apiFetch(url, options) {
  const res = await fetch(url, options);
  if (res.status === 401) {
    window.location.href = "/";
    return null;
  }
  return res;
}

function fmtTime(iso) {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function truncate(text, maxLen = 64) {
  const cleaned = (text || "").replace(/\s+/g, " ").trim();
  if (!cleaned) return "";
  if (cleaned.length <= maxLen) return cleaned;
  return cleaned.slice(0, maxLen - 1).trim() + "…";
}

function escapeHtml(text) {
  return (text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function renderMarkdown(text) {
  if (!text) return "";
  let cleaned = text.replace(/\u2022/g, "-");
  cleaned = cleaned
    .split("\n")
    .map((line) => {
      const bulletCount = (line.match(/ - /g) || []).length;
      if (bulletCount >= 2 && !line.trim().startsWith("-") && !/^\d+\./.test(line.trim())) {
        return line.replace(/ - /g, "\n- ");
      }
      return line;
    })
    .join("\n");

  let out = escapeHtml(cleaned);
  const codeBlocks = [];

  out = out.replace(/```([\s\S]*?)```/g, (_, code) => {
    const placeholder = `@@CODEBLOCK${codeBlocks.length}@@`;
    codeBlocks.push(`<pre><code>${code}</code></pre>`);
    return `\n\n${placeholder}\n\n`;
  });

  out = out.replace(/^###\s+(.*)$/gm, "\n\n<h3>$1</h3>\n\n");
  out = out.replace(/^##\s+(.*)$/gm, "\n\n<h2>$1</h2>\n\n");
  out = out.replace(/^#\s+(.*)$/gm, "\n\n<h1>$1</h1>\n\n");
  out = out.replace(/^\s*---\s*$/gm, "\n\n<hr />\n\n");
  out = out.replace(/^\s*> (.*)$/gm, "\n\n<blockquote>$1</blockquote>\n\n");

  out = out.replace(/(?:^|\n)([-*] .+(?:\n[-*] .+)*)/g, (match, list) => {
    const items = list
      .split("\n")
      .map((line) => line.replace(/^[-*]\s+/, "").trim())
      .filter(Boolean);
    if (!items.length) return match;
    return `\n\n<ul>${items.map((item) => `<li>${item}</li>`).join("")}</ul>\n\n`;
  });

  out = out.replace(/(?:^|\n)((?:\d+\. .+(?:\n\d+\. .+)*)+)/g, (match, list) => {
    const items = list
      .split("\n")
      .map((line) => line.replace(/^\d+\.\s+/, "").trim())
      .filter(Boolean);
    if (!items.length) return match;
    return `\n\n<ol>${items.map((item) => `<li>${item}</li>`).join("")}</ol>\n\n`;
  });

  out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/\*([^*]+)\*/g, "<em>$1</em>");

  codeBlocks.forEach((block, idx) => {
    out = out.replace(`@@CODEBLOCK${idx}@@`, block);
  });

  const blocks = out
    .split(/\n{2,}/)
    .map((block) => block.trim())
    .filter(Boolean)
    .map((block) => {
      if (block.startsWith("<") && block.endsWith(">")) {
        return block;
      }
      return `<p>${block.replace(/\n/g, "<br />")}</p>`;
    });

  return blocks.join("");
}

function scrollBottom(smooth = false) {
  if (!messagesEl) return;
  messagesEl.scrollTo({
    top: messagesEl.scrollHeight,
    behavior: smooth ? "smooth" : "auto",
  });
}

function getBusyMessage() {
  if (isPipelineRunning) return "Running step...";
  if (isStreaming) return "Thinking...";
  if (isSending) return "Sending...";
  return "";
}

function updateFooterHint() {
  if (!openaiConfigured) {
    footerHintEl.textContent = "OPENAI_API_KEY is not set. Add it to your environment to chat.";
    return;
  }
  if (isPipelineRunning) {
    footerHintEl.textContent = "Running step...";
    return;
  }
  if (pipelineStatus === "blocked") {
    footerHintEl.textContent = "Pipeline waiting for approval.";
    return;
  }
  if (pipelineStatus === "stale") {
    footerHintEl.textContent = "New document uploaded. Run the pipeline to index it.";
    return;
  }
  if (pipelineStatus === "completed") {
    footerHintEl.textContent = "RAG ready. Ask questions about the document.";
    return;
  }
  if (pipelineStatus === "error") {
    footerHintEl.textContent = "Pipeline error. Check server logs.";
    return;
  }
  if (pipelineStatus === "rejected") {
    footerHintEl.textContent = "Pipeline rejected.";
    return;
  }
  footerHintEl.textContent = "";
}

function updateUiState() {
  const busy = isStreaming || isSending || isPipelineRunning;
  inputEl.disabled = busy;
  sendBtn.disabled = busy;
  attachBtn.disabled = busy;
  runPipelineBtn.disabled = busy || !latestUploadPath;

  sendBtn.textContent = "Send";
  updateFooterHint();
}

function setUploadState(path, filename) {
  latestUploadPath = path || null;
  if (filename) {
    uploadLabelEl.textContent = filename;
  } else if (path) {
    uploadLabelEl.textContent = path;
  } else {
    uploadLabelEl.textContent = "No file uploaded yet.";
  }
  updateUiState();
}

function bubble(role, text) {
  const div = document.createElement("div");
  div.className = `bubble ${role}`;
  if (role === "assistant") {
    div.innerHTML = renderMarkdown(text);
  } else {
    div.textContent = text;
  }
  messagesEl.appendChild(div);
  scrollBottom();
}

function renderPipelineCard(steps, pendingStep) {
  if (pipelineInChatCardId) {
    const old = document.getElementById(pipelineInChatCardId);
    if (old) old.remove();
  }

  pipelineInChatCardId = "pipe_" + uid();
  const card = document.createElement("div");
  card.className = "pipeline-card";
  card.id = pipelineInChatCardId;

  const header = document.createElement("div");
  header.className = "pipeline-header";

  const title = document.createElement("div");
  title.className = "pipeline-title";
  title.textContent = "Pipeline";

  const meta = document.createElement("div");
  meta.className = "pipeline-meta";
  const completed = steps.filter((s) => s.status === "completed").length;
  meta.textContent = pendingStep ? "Awaiting approval" : `${completed}/${steps.length} completed`;

  header.appendChild(title);
  header.appendChild(meta);
  card.appendChild(header);

  const list = document.createElement("div");
  list.className = "pipeline-steps";

  steps.forEach((s) => {
    const row = document.createElement("div");
    row.className = "pipeline-step";

    const name = document.createElement("div");
    name.className = "step-name";
    name.textContent = `${s.idx + 1}. ${s.title}`;

    const badge = document.createElement("div");
    badge.className = `status-chip ${statusClass(s.status)}`;
    badge.textContent = s.status;

    row.appendChild(name);
    row.appendChild(badge);
    list.appendChild(row);
  });

  card.appendChild(list);

  if (pendingStep && pendingStep.status === "pending") {
    pipelinePendingIdx = pendingStep.idx;

    const approval = document.createElement("div");
    approval.className = "approval-bar";

    const approveBtn = document.createElement("button");
    approveBtn.className = "btn-approve";
    approveBtn.textContent = "Approve and run";
    approveBtn.onclick = async () => {
      approveBtn.disabled = true;
      rejectBtn.disabled = true;
      await pipelineDecision("approve");
    };

    const rejectBtn = document.createElement("button");
    rejectBtn.className = "btn-reject";
    rejectBtn.textContent = "Reject";
    rejectBtn.onclick = async () => {
      approveBtn.disabled = true;
      rejectBtn.disabled = true;
      await pipelineDecision("reject");
    };

    approval.appendChild(rejectBtn);
    approval.appendChild(approveBtn);
    card.appendChild(approval);
  } else {
    pipelinePendingIdx = null;
  }

  messagesEl.appendChild(card);
  scrollBottom();
}

function statusClass(status) {
  if (status === "pending") return "is-pending";
  if (status === "running") return "is-running";
  if (status === "completed") return "is-completed";
  if (status === "queued") return "is-queued";
  if (status === "rejected") return "is-rejected";
  if (status === "error") return "is-error";
  return "is-queued";
}

async function fetchHealth() {
  const res = await apiFetch("/api/health");
  if (!res) return;
  const data = await res.json();

  if (data.tools_loaded > 0) {
    serverPill.className = "pill pill-good";
    serverPill.textContent = "connected";
  } else {
    serverPill.className = "pill pill-warn";
    serverPill.textContent = "connecting";
  }

  toolsPill.className = data.tools_loaded > 0 ? "pill pill-good" : "pill pill-warn";
  toolsPill.textContent = `${data.tools_loaded} loaded`;

  openaiConfigured = Boolean(data.openai_configured);
  if (openaiConfigured) {
    openaiPill.className = "pill pill-good";
    openaiPill.textContent = "ready";
  } else {
    openaiPill.className = "pill pill-bad";
    openaiPill.textContent = "missing";
  }

  updateUiState();
}

async function checkAuth() {
  const res = await apiFetch("/api/auth/session");
  if (!res) return null;
  const data = await res.json();
  if (!data.ok) {
    window.location.href = "/";
    return null;
  }
  return data.user || null;
}

async function loadChats() {
  const res = await apiFetch("/api/chats");
  if (!res) return;
  const data = await res.json();
  renderChatList(data.chats || []);
}

function renderChatList(chats) {
  chatListEl.innerHTML = "";
  chats.forEach((c) => {
    const item = document.createElement("div");
    item.className = "chat-item" + (c.session_id === activeSessionId ? " active" : "");

    const avatar = document.createElement("div");
    avatar.className = "chat-avatar";
    const initial = (c.title || "C").trim().charAt(0) || "C";
    avatar.textContent = initial.toUpperCase();

    const meta = document.createElement("div");
    meta.className = "chat-meta";

    const title = document.createElement("div");
    title.className = "chat-title";
    title.textContent = c.title || "Chat";

    const preview = document.createElement("div");
    preview.className = "chat-preview";
    const previewText = truncate(c.last_message, 80) || "No messages yet.";
    preview.textContent = previewText;

    meta.appendChild(title);
    meta.appendChild(preview);

    const time = document.createElement("div");
    time.className = "chat-time";
    time.textContent = fmtTime(c.last_message_at || c.updated_at || c.created_at || "");

    item.appendChild(avatar);
    item.appendChild(meta);
    item.appendChild(time);

    item.onclick = async () => {
      await selectChat(c.session_id);
    };

    chatListEl.appendChild(item);
  });
}

async function selectChat(sessionId) {
  activeSessionId = sessionId;
  messagesEl.innerHTML = "";
  pipelinePendingIdx = null;
  pipelineInChatCardId = null;

  const res = await apiFetch(`/api/chats/${sessionId}`);
  if (!res) return;
  const data = await res.json();

  if (data.chat && data.chat.title) {
    chatTitleEl.textContent = data.chat.title;
  } else {
    chatTitleEl.textContent = "Chat";
  }

  const msgs = data.messages || [];
  msgs.forEach((m) => bubble(m.role, m.content));

  if (data.latest_upload) {
    setUploadState(data.latest_upload.path, data.latest_upload.filename || data.latest_upload.path);
  } else {
    setUploadState(null, null);
  }

  const isStale = Boolean(data.pipeline_stale);
  pipelineStatus = isStale ? "stale" : (data.pipeline ? data.pipeline.status : null);

  if (!isStale && data.steps && data.steps.length) {
    const pending = (data.steps || []).find((s) => s.status === "pending");
    renderPipelineCard(data.steps, pending || null);
  }

  updateUiState();
  await loadChats();
}

async function createNewChat() {
  const sessionId = uid();
  const res = await apiFetch("/api/chats/new", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, title: "New Chat" }),
  });
  if (!res) return;
  pipelineStatus = null;
  await loadChats();
  await selectChat(sessionId);
}

async function uploadPdf(file) {
  if (isStreaming || isSending || isPipelineRunning) return;
  if (!activeSessionId) {
    await createNewChat();
  }
  const fd = new FormData();
  fd.append("file", file);

  const res = await apiFetch(`/api/upload?session_id=${encodeURIComponent(activeSessionId)}`, {
    method: "POST",
    body: fd,
  });
  if (!res) return;
  const data = await res.json();
  if (data.ok) {
    setUploadState(data.path, data.filename);
    bubble("system", `Uploaded: ${data.filename}`);
  } else {
    bubble("system", "Upload failed.");
  }
}

async function sendMessageWithText(text) {
  if (isStreaming || isSending || isPipelineRunning) return;
  const trimmed = text.trim();
  if (!trimmed) return;
  if (!activeSessionId) {
    await createNewChat();
  }

  isSending = true;
  updateUiState();

  bubble("user", trimmed);

  const res = await apiFetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: activeSessionId, message: trimmed }),
  });
  if (!res) return;
  const data = await res.json();

  isSending = false;
  updateUiState();

  if (data.mode === "pipeline") {
    pipelineStatus = "blocked";
    const steps = data.steps || [];
    const pending = data.first_step || steps.find((s) => s.status === "pending") || null;
    renderPipelineCard(steps, pending);
    return;
  }

  await streamAssistant();
}

async function sendMessage() {
  await sendMessageWithText(inputEl.value);
  inputEl.value = "";
}

async function streamAssistant() {
  isStreaming = true;
  updateUiState();

  const thinking = document.createElement("div");
  thinking.className = "bubble assistant";
  thinking.textContent = "Thinking...";
  messagesEl.appendChild(thinking);
  scrollBottom();

  const ev = new EventSource(`/api/chat/stream?session_id=${encodeURIComponent(activeSessionId)}`);

  let buf = "";
  ev.onmessage = (e) => {
    if (e.data === "[DONE]") {
      ev.close();
      thinking.innerHTML = renderMarkdown(buf || " ");
      isStreaming = false;
      updateUiState();
      return;
    }
    if (e.data.startsWith("[ERROR]")) {
      thinking.textContent = e.data;
      ev.close();
      isStreaming = false;
      updateUiState();
      return;
    }
    buf += e.data;
    thinking.textContent = buf;
    scrollBottom();
  };

  ev.onerror = () => {
    thinking.textContent = buf || "Streaming error.";
    ev.close();
    isStreaming = false;
    updateUiState();
  };
}

async function pipelineDecision(decision) {
  if (isStreaming || isSending || isPipelineRunning) return;
  isPipelineRunning = true;
  updateUiState();

  const res = await apiFetch("/api/pipeline/decision", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: activeSessionId, decision }),
  });
  if (!res) return;
  const data = await res.json();

  isPipelineRunning = false;
  pipelineStatus = data.status || pipelineStatus;
  updateUiState();

  const steps = data.steps || [];
  const pending = data.pending || steps.find((s) => s.status === "pending") || null;
  renderPipelineCard(steps, pending);

  if (data.status === "completed") {
    bubble("system", "Pipeline completed.");
  }
  if (data.status === "rejected") {
    bubble("system", "Pipeline rejected.");
  }
  if (data.status === "error") {
    bubble("system", "Pipeline error. Check server logs.");
  }
}

newChatBtn.onclick = createNewChat;
attachBtn.onclick = () => fileInput.click();
runPipelineBtn.onclick = async () => {
  if (!latestUploadPath) return;
  await sendMessageWithText("run the pipeline");
};

fileInput.onchange = async () => {
  const f = fileInput.files[0];
  if (!f) return;
  await uploadPdf(f);
  fileInput.value = "";
};

sendBtn.onclick = sendMessage;
scrollBtn.onclick = () => scrollBottom(true);
if (logoutBtn) {
  logoutBtn.onclick = async () => {
    await apiFetch("/api/auth/logout", { method: "POST" });
    window.location.href = "/";
  };
}

inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendMessage();
});

(async function boot() {
  const user = await checkAuth();
  if (!user) return;
  await fetchHealth();
  await loadChats();

  const chatsRes = await apiFetch("/api/chats");
  if (!chatsRes) return;
  const chatsData = await chatsRes.json();
  const chats = chatsData.chats || [];
  if (chats.length === 0) {
    await createNewChat();
  } else {
    await selectChat(chats[0].session_id);
  }
  setInterval(fetchHealth, 5000);
})();
