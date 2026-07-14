const elements = {
  // Screens
  homeScreen: document.getElementById("homeScreen"),
  viewerScreen: document.getElementById("viewerScreen"),
  splashScreen: document.getElementById("splashScreen"),

  // Home Form
  form: document.getElementById("connectForm"),
  sessionId: document.getElementById("sessionId"),
  pairingCode: document.getElementById("pairingCode"),
  connectButton: document.getElementById("connectButton"),
  connectError: document.getElementById("connectError"),
  copyHostId: document.getElementById("copyHostId"),
  copyHostPassword: document.getElementById("copyHostPassword"),

  // Toolbar
  requestControlButton: document.getElementById("requestControlButton"),
  releaseControlButton: document.getElementById("releaseControlButton"),
  disconnectButton: document.getElementById("disconnectButton"),
  chatButton: document.getElementById("chatButton"),
  fileButton: document.getElementById("fileButton"),
  clipboardButton: document.getElementById("clipboardButton"),
  settingsButton: document.getElementById("settingsButton"),
  badge: document.getElementById("connectionBadge"),
  statusText: document.getElementById("statusText"),
  hostStatusDot: document.getElementById("hostStatusDot"),
  hostConnectionStatus: document.getElementById("hostConnectionStatus"),

  // Canvas
  stage: document.getElementById("screenStage"),
  canvas: document.getElementById("screenCanvas"),

  // Modals
  chatOverlay: document.getElementById("chatOverlay"),
  chatForm: document.getElementById("chatForm"),
  chatInput: document.getElementById("chatInput"),
  chatLog: document.getElementById("chatLog"),
  closeChat: document.getElementById("closeChat"),

  fileOverlay: document.getElementById("fileOverlay"),
  fileInput: document.getElementById("fileInput"),
  sendFileButton: document.getElementById("sendFileButton"),
  closeFile: document.getElementById("closeFile"),

  clipboardOverlay: document.getElementById("clipboardOverlay"),
  clipboardText: document.getElementById("clipboardText"),
  sendClipboardButton: document.getElementById("sendClipboardButton"),
  closeClipboard: document.getElementById("closeClipboard"),

  settingsOverlay: document.getElementById("settingsOverlay"),
  qualityPreset: document.getElementById("qualityPreset"),
  applyQualityButton: document.getElementById("applyQualityButton"),
  closeSettings: document.getElementById("closeSettings")
};

const state = {
  ws: null,
  connected: false,
  controlAllowed: false,
  controlPending: false,
  latestImage: null,
  imageRect: { x: 0, y: 0, width: 0, height: 0 },
  frameCount: 0,
  lastPointerMove: 0,
  serverUrl: "",
};

// Splash screen logic
setTimeout(() => {
  if (elements.splashScreen) elements.splashScreen.classList.add("hidden");
}, 2500);

const ctx = elements.canvas.getContext("2d", { alpha: false });

// --- Connect / Disconnect ---
function validateForm() {
  if (elements.sessionId.value.trim() && elements.pairingCode.value.trim()) {
    elements.connectButton.classList.add("active");
    elements.connectButton.disabled = false;
  } else {
    elements.connectButton.classList.remove("active");
    elements.connectButton.disabled = true;
  }
}
elements.sessionId.addEventListener("input", validateForm);
elements.pairingCode.addEventListener("input", validateForm);
validateForm(); // Initial state

elements.form.addEventListener("submit", (event) => {
  event.preventDefault();
  void connect();
});

elements.copyHostId.addEventListener("click", () => copyCredential("fakeId", "Session ID copied"));
elements.copyHostPassword.addEventListener("click", () => copyCredential("fakePass", "Password copied"));

elements.disconnectButton.addEventListener("click", () => disconnect());

// --- Toolbar Listeners ---
elements.requestControlButton.addEventListener("click", () => {
  if (!state.connected || state.controlAllowed || state.controlPending) return;
  state.controlPending = true;
  setStatus("Waiting for host approval...");
  renderConnectionState();
  send({ type: "control:request" });
});

elements.releaseControlButton.addEventListener("click", () => {
  state.controlAllowed = false;
  state.controlPending = false;
  send({ type: "control:revoke" });
  renderConnectionState();
});

// Modals toggles
const toggleModal = (modal, show) => {
  if (show) modal.classList.remove("hidden");
  else modal.classList.add("hidden");
};

elements.chatButton.addEventListener("click", () => toggleModal(elements.chatOverlay, true));
elements.closeChat.addEventListener("click", () => toggleModal(elements.chatOverlay, false));

elements.fileButton.addEventListener("click", () => toggleModal(elements.fileOverlay, true));
elements.closeFile.addEventListener("click", () => toggleModal(elements.fileOverlay, false));

elements.clipboardButton.addEventListener("click", async () => {
  // Try to use Clipboard API, if failed fallback to Modal
  if (!state.controlAllowed) return;
  try {
    const text = await navigator.clipboard.readText();
    send({ type: "clipboard:text", text });
    setStatus("Clipboard text sent to host");
  } catch (err) {
    toggleModal(elements.clipboardOverlay, true);
  }
});
elements.closeClipboard.addEventListener("click", () => toggleModal(elements.clipboardOverlay, false));
elements.sendClipboardButton.addEventListener("click", () => {
  const text = elements.clipboardText.value;
  send({ type: "clipboard:text", text });
  setStatus("Clipboard text sent to host");
  toggleModal(elements.clipboardOverlay, false);
});

elements.settingsButton.addEventListener("click", () => toggleModal(elements.settingsOverlay, true));
elements.closeSettings.addEventListener("click", () => toggleModal(elements.settingsOverlay, false));

// --- Actions ---
elements.chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = elements.chatInput.value.trim();
  if (text && state.connected) {
    send({ type: "chat:message", text });
    addChatMessage("self", text);
    elements.chatInput.value = "";
  }
});

function addChatMessage(sender, text) {
  const div = document.createElement("div");
  div.className = `chat-msg ${sender}`;
  div.textContent = text;
  elements.chatLog.appendChild(div);
  elements.chatLog.scrollTop = elements.chatLog.scrollHeight;
}

elements.sendFileButton.addEventListener("click", () => {
  if (!state.controlAllowed) {
    setStatus("Control must be approved to send files.");
    return;
  }
  const file = elements.fileInput.files[0];
  if (!file) return;

  const reader = new FileReader();
  reader.onload = (e) => {
    // Correctly split data URL to just get the base64 part
    const base64 = e.target.result.split(',')[1];
    send({
      type: "file:send",
      name: file.name,
      data: base64
    });
    setStatus(`Sent file: ${file.name}`);
    toggleModal(elements.fileOverlay, false);
    elements.fileInput.value = "";
  };
  reader.readAsDataURL(file);
});

elements.applyQualityButton.addEventListener("click", () => {
  const preset = elements.qualityPreset.value;
  let fps = 12, quality = 75;
  if (preset === "sharp") { fps = 10; quality = 95; }
  else if (preset === "fast") { fps = 15; quality = 30; }

  if (state.connected) {
    send({ type: "settings:update", fps, quality });
    setStatus(`Requested stream settings: ${preset}`);
  }
  toggleModal(elements.settingsOverlay, false);
});

// --- Mouse and Canvas Event Listeners ---
elements.canvas.addEventListener("contextmenu", (event) => event.preventDefault());
elements.canvas.addEventListener("pointerdown", (event) => {
  elements.canvas.focus();
  sendMouse("down", event);
});
elements.canvas.addEventListener("pointerup", (event) => sendMouse("up", event));
elements.canvas.addEventListener("pointermove", (event) => {
  const now = performance.now();
  if (now - state.lastPointerMove < 30) return;
  state.lastPointerMove = now;
  sendMouse("move", event);
});
elements.canvas.addEventListener(
  "wheel",
  (event) => {
    if (!state.controlAllowed) return;
    event.preventDefault();
    // Use deltaY raw values divided by a factor to make scroll smooth.
    // Positive deltaY means scroll down, Negative means scroll up.
    send({
      type: "input:mouse",
      action: "wheel",
      delta_x: Math.round(event.deltaX / 50),
      delta_y: Math.round(event.deltaY / 50),
    });
  },
  { passive: false }
);

window.addEventListener("keydown", (event) => sendKey("down", event));
window.addEventListener("keyup", (event) => sendKey("up", event));
window.addEventListener("resize", resizeCanvas);

// --- WebSocket Logic ---
async function connect() {
  disconnect();
  setConnectError("");

  const sessionId = elements.sessionId.value.trim();
  const pairingCode = elements.pairingCode.value.trim();

  let ws;
  try {
    let baseUrl = state.serverUrl;
    if (!baseUrl && window.pywebview?.api) {
      baseUrl = String(await window.pywebview.api.get_server_url()).trim().replace(/\/+$/, "");
    }

    let wsUrl = "";
    if (/^wss?:\/\//i.test(baseUrl)) {
      wsUrl = `${baseUrl}/ws/viewer`;
    } else if (/^https?:$/i.test(window.location.protocol) && window.location.host) {
      const scheme = window.location.protocol === "https:" ? "wss" : "ws";
      wsUrl = `${scheme}://${window.location.host}/ws/viewer`;
    } else {
      throw new Error("Server configuration is missing");
    }
    ws = new WebSocket(wsUrl);
  } catch (error) {
    setConnectError(error?.message || "Unable to start the connection.");
    elements.connectButton.disabled = false;
    elements.connectButton.textContent = "Join Session";
    return;
  }

  elements.connectButton.disabled = true;
  elements.connectButton.textContent = "Connecting...";
  state.ws = ws;

  ws.addEventListener("open", () => {
    send({
      type: "viewer:hello",
      session_id: sessionId,
      pairing_code: pairingCode,
    });
  });

  ws.addEventListener("message", (event) => {
    const data = parseMessage(event.data);
    handleMessage(data);
  });

  ws.addEventListener("close", () => {
    if (state.ws !== ws) return;
    state.connected = false;
    state.controlAllowed = false;
    state.controlPending = false;
    state.ws = null;
    renderConnectionState();
    setStatus("Disconnected");
    if (!elements.connectError.textContent) setConnectError("Session disconnected.");
    switchScreen("home");
  });

  ws.addEventListener("error", () => {
    if (state.ws !== ws) return;
    setStatus("Connection failed");
    setConnectError("Could not reach the secure relay server.");
    elements.connectButton.disabled = false;
    elements.connectButton.textContent = "Join Session";
  });
}

function disconnect() {
  if (state.ws) state.ws.close();
  state.ws = null;
  state.connected = false;
  state.controlAllowed = false;
  state.controlPending = false;
  renderConnectionState();
  switchScreen("home");
  elements.connectButton.disabled = false;
  elements.connectButton.textContent = "Join Session";
}

function switchScreen(screen) {
  if (screen === "viewer") {
    elements.homeScreen.classList.add("hidden");
    elements.viewerScreen.classList.remove("hidden");
    resizeCanvas();
  } else {
    elements.homeScreen.classList.remove("hidden");
    elements.viewerScreen.classList.add("hidden");
  }
}

function handleMessage(data) {
  switch (data.type) {
    case "viewer:registered":
      state.connected = true;
      state.controlPending = Boolean(data.pending);
      setStatus("Connected securely to Host");
      renderConnectionState();
      switchScreen("viewer");
      break;
    case "session:state":
      state.connected = Boolean(data.connected);
      state.controlPending = Boolean(data.pending);
      renderConnectionState();
      break;
    case "host:frame":
      receiveFrame(data);
      break;
    case "host:status":
      setStatus(data.detail || "Host status updated");
      break;
    case "control:state":
      state.controlAllowed = Boolean(data.allowed);
      state.controlPending = Boolean(data.pending);
      setStatus(data.reason || (state.controlAllowed ? "Control approved by host" : "Control denied"));
      renderConnectionState();
      break;
    case "chat:message":
      if (data.text) {
        addChatMessage("other", data.text);
        if (elements.chatOverlay.classList.contains("hidden")) {
            setStatus("💬 New message received!");
            toggleModal(elements.chatOverlay, true);
        }
      }
      break;
    case "server:error":
      setStatus(data.detail || "Server error");
      setConnectError(data.detail || "Server rejected the connection.");
      renderConnectionState();
      break;
  }
}

function receiveFrame(data) {
  const image = new Image();
  image.onload = () => {
    state.latestImage = image;
    state.frameCount += 1;
    elements.stage.classList.add("has-frame");
    drawFrame();
  };
  image.src = `data:image/jpeg;base64,${data.image}`;
}

function resizeCanvas() {
  const rect = elements.stage.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  // Make the canvas pixel size match its bounding rect exactly
  elements.canvas.width = rect.width;
  elements.canvas.height = rect.height;
  drawFrame();
}

function drawFrame() {
  const rect = elements.canvas.getBoundingClientRect();
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, elements.canvas.width, elements.canvas.height);

  if (!state.latestImage) return;

  const image = state.latestImage;
  // Calculate scaled size maintaining aspect ratio
  const scale = Math.min(elements.canvas.width / image.width, elements.canvas.height / image.height);
  const width = image.width * scale;
  const height = image.height * scale;
  const x = (elements.canvas.width - width) / 2;
  const y = (elements.canvas.height - height) / 2;

  state.imageRect = { x, y, width, height };
  ctx.imageSmoothingEnabled = true;
  ctx.drawImage(image, x, y, width, height);
}

function sendMouse(action, event) {
  if (!state.controlAllowed) return;
  const point = normalizePointer(event);
  if (!point) return;
  event.preventDefault();
  send({
    type: "input:mouse",
    action,
    button: pointerButton(event.button),
    x_pct: point.x,
    y_pct: point.y,
  });
}

function sendKey(action, event) {
  if (!state.controlAllowed || isTypingTarget(event.target)) return;
  if (action === "down" && event.repeat) return;
  event.preventDefault();
  send({
    type: "input:key",
    action,
    key: event.key,
    code: event.code,
  });
}

function normalizePointer(event) {
  if (!state.latestImage) return null;
  const rect = elements.canvas.getBoundingClientRect();
  const x = event.clientX - rect.left - state.imageRect.x;
  const y = event.clientY - rect.top - state.imageRect.y;
  if (x < 0 || y < 0 || x > state.imageRect.width || y > state.imageRect.height) return null;
  return {
    x: clamp(x / state.imageRect.width),
    y: clamp(y / state.imageRect.height),
  };
}

function pointerButton(button) {
  if (button === 1) return "middle";
  if (button === 2) return "right";
  return "left";
}

function send(payload) {
  if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return;
  state.ws.send(JSON.stringify(payload));
}

function parseMessage(raw) {
  try { return JSON.parse(raw); } catch { return {}; }
}

function renderConnectionState() {
  if (state.controlAllowed) {
    elements.requestControlButton.classList.add("hidden");
    elements.releaseControlButton.classList.remove("hidden");
    elements.badge.className = "badge badge-control";
    elements.badge.textContent = "Control Active";
  } else {
    elements.requestControlButton.classList.remove("hidden");
    elements.releaseControlButton.classList.add("hidden");
    elements.requestControlButton.disabled = state.controlPending;
    elements.requestControlButton.textContent = state.controlPending ? "Waiting..." : "🖱️ Control";
    elements.badge.className = "badge badge-online";
    elements.badge.textContent = "Connected (View Only)";
  }

  elements.fileButton.disabled = !state.controlAllowed;
  elements.clipboardButton.disabled = !state.controlAllowed;
}

function setStatus(text) {
  elements.statusText.textContent = text;
}

function setConnectError(text) {
  elements.connectError.textContent = text;
}

async function copyCredential(elementId, successText) {
  const value = document.getElementById(elementId)?.textContent?.trim();
  if (!value || value === "Loading..." || value === "------") return;
  try {
    await navigator.clipboard.writeText(value);
    elements.hostConnectionStatus.textContent = successText;
  } catch (error) {
    console.error("Clipboard copy failed", error);
  }
}

function isTypingTarget(target) {
  if (!target) return false;
  const tagName = target.tagName;
  return tagName === "INPUT" || tagName === "TEXTAREA" || target.isContentEditable;
}

function clamp(value) { return Math.max(0, Math.min(1, value)); }

// --- Initial State ---
switchScreen("home");

// --- PyWebView Integration ---
async function loadHostCredentials() {
  const api = window.pywebview?.api;
  if (!api) return;

  try {
    const creds = await api.get_credentials();
    if (!creds?.id || !creds?.pass) throw new Error("Credential response is incomplete");

    document.getElementById("fakeId").textContent = creds.id;
    document.getElementById("fakePass").textContent = creds.pass;
  } catch (error) {
    console.error("Failed to load host credentials", error);
  }
}

async function loadHostStatus() {
  const api = window.pywebview?.api;
  if (!api || !elements.hostConnectionStatus || !elements.hostStatusDot) return;

  try {
    symconnectApplyHostStatus(await api.get_host_status());
  } catch (error) {
    console.error("Failed to load host status", error);
  }
}

function symconnectApplyHostStatus(status) {
  const statusState = ["connecting", "ready", "error"].includes(status?.state)
    ? status.state
    : "error";

  elements.hostConnectionStatus.textContent = status?.detail || "Connection status unavailable.";
  elements.hostStatusDot.classList.remove("dot-connecting", "dot-ready", "dot-error");
  elements.hostStatusDot.classList.add(`dot-${statusState}`);
}

function symconnectBootstrap(payload) {
  const credentials = payload?.credentials;
  if (credentials?.id && credentials?.pass) {
    document.getElementById("fakeId").textContent = credentials.id;
    document.getElementById("fakePass").textContent = credentials.pass;
  }
  state.serverUrl = String(payload?.server_url || "").trim().replace(/\/+$/, "");
  symconnectApplyHostStatus(payload?.status);
}

window.symconnectBootstrap = symconnectBootstrap;
window.symconnectApplyHostStatus = symconnectApplyHostStatus;

// --- Host UI Elements ---
const hostChatToggle = document.getElementById("hostChatToggle");
const hostChatBadge = document.getElementById("hostChatBadge");
const hostChatPanel = document.getElementById("hostChatPanel");
const closeHostChat = document.getElementById("closeHostChat");
const hostChatLog = document.getElementById("hostChatLog");

const hostFileToast = document.getElementById("hostFileToast");
const hostFileName = document.getElementById("hostFileName");
const hostFileClose = document.getElementById("hostFileClose");
const hostFileOpen = document.getElementById("hostFileOpen");

let unreadHostChats = 0;

if (hostChatToggle) {
  hostChatToggle.addEventListener("click", () => {
    hostChatPanel.classList.toggle("hidden");
    if (!hostChatPanel.classList.contains("hidden")) {
      unreadHostChats = 0;
      hostChatBadge.classList.add("hidden");
      hostChatBadge.innerText = "0";
      hostChatLog.scrollTop = hostChatLog.scrollHeight;
    }
  });
}
if (closeHostChat) {
  closeHostChat.addEventListener("click", () => hostChatPanel.classList.add("hidden"));
}
if (hostFileClose) {
  hostFileClose.addEventListener("click", () => hostFileToast.classList.add("hidden"));
}
if (hostFileOpen) {
  hostFileOpen.addEventListener("click", () => {
    if (window.pywebview && window.pywebview.api) {
      window.pywebview.api.open_downloads_folder();
    }
    hostFileToast.classList.add("hidden");
  });
}

window.symconnectHostNotification = (data) => {
  if (data && data.message) {
    if (data.title === "Chat Message") {
      // Append to host chat log
      const div = document.createElement("div");
      div.className = "chat-msg other";
      
      // Parse out the sender prefix if needed, or just display raw
      let text = data.message;
      if (text.startsWith("Viewer says: ")) text = text.substring(13);
      div.textContent = text;
      
      // Remove empty state if present
      const emptyState = hostChatLog.querySelector(".empty-state");
      if (emptyState) emptyState.remove();
      
      hostChatLog.appendChild(div);
      hostChatLog.scrollTop = hostChatLog.scrollHeight;
      
      // Update badge if panel is hidden
      if (hostChatPanel && hostChatPanel.classList.contains("hidden")) {
        unreadHostChats++;
        hostChatBadge.innerText = unreadHostChats;
        hostChatBadge.classList.remove("hidden");
      }
    } else if (data.title === "File Received") {
      // Show file toast
      let filename = data.message;
      if (filename.startsWith("File saved to Downloads: ")) {
         filename = filename.substring(25);
      }
      hostFileName.innerText = filename;
      hostFileToast.classList.remove("hidden");
      
      // Auto hide after 10 seconds
      setTimeout(() => hostFileToast.classList.add("hidden"), 10000);
    } else {
      // Fallback
      alert(`${data.title || "Notification"}:\n\n${data.message}`);
    }
  }
};

let updateDownloadUrl = "";

window.symconnectShowUpdate = (data) => {
  const banner = document.getElementById("updateBanner");
  if (banner && data && data.url) {
    updateDownloadUrl = data.url;
    banner.innerText = `A new version (v${data.version}) is available! Click here to update automatically.`;
    banner.style.display = "block";
    
    banner.addEventListener("click", () => {
      banner.innerText = "Downloading update, please wait... The app will restart shortly.";
      banner.style.pointerEvents = "none";
      banner.style.background = "#eab308";
      if (window.pywebview && window.pywebview.api) {
        window.pywebview.api.trigger_app_update(updateDownloadUrl);
      }
    });
  }
};

window.addEventListener("pywebviewready", () => {
  void loadHostCredentials();
  void loadHostStatus();
});
void loadHostCredentials();
void loadHostStatus();
window.setInterval(loadHostStatus, 1000);
