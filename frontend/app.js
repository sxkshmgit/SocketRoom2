const TOKEN_KEY = "socketroom_token";

const authView = document.getElementById("auth-view");
const chatView = document.getElementById("chat-view");
const loginForm = document.getElementById("login-form");
const registerForm = document.getElementById("register-form");
const authError = document.getElementById("auth-error");
const currentUsername = document.getElementById("current-username");
const messageList = document.getElementById("message-list");
const messageForm = document.getElementById("message-form");
const messageInput = document.getElementById("message-input");
const sendButton = document.getElementById("send-button");
const connectionStatus = document.getElementById("connection-status");
const chatError = document.getElementById("chat-error");

let currentToken = null;
let currentUserId = null;

const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30000;
const POLICY_VIOLATION_CODE = 1008;

let socket = null;
let authenticated = false;
let reconnectAttempts = 0;
let reconnectTimer = null;
const seenMessageIds = new Set();

function showView(name) {
    authView.hidden = name !== "auth";
    chatView.hidden = name !== "chat";
}

function showForm(name) {
    loginForm.hidden = name !== "login";
    registerForm.hidden = name !== "register";
    clearError();
}

function showError(message) {
    authError.textContent = message;
    authError.hidden = false;
}

function clearError() {
    authError.textContent = "";
    authError.hidden = true;
}

function loadStoredToken() {
    try {
        return sessionStorage.getItem(TOKEN_KEY);
    } catch (error) {
        return null;
    }
}

function saveToken(token) {
    currentToken = token;
    try {
        sessionStorage.setItem(TOKEN_KEY, token);
    } catch (error) {
        // Token stays in memory only if storage is unavailable.
    }
}

function clearToken() {
    currentToken = null;
    try {
        sessionStorage.removeItem(TOKEN_KEY);
    } catch (error) {
        // Nothing to clear if storage is unavailable.
    }
}

async function apiRequest(path, { method = "GET", body, token } = {}) {
    const headers = {};
    if (body !== undefined) {
        headers["Content-Type"] = "application/json";
    }
    if (token) {
        headers["Authorization"] = `Bearer ${token}`;
    }

    let response;
    try {
        response = await fetch(path, {
            method,
            headers,
            body: body !== undefined ? JSON.stringify(body) : undefined,
        });
    } catch (error) {
        return { ok: false, status: 0, data: null };
    }

    let data = null;
    try {
        data = await response.json();
    } catch (error) {
        data = null;
    }
    return { ok: response.ok, status: response.status, data };
}

function validationMessage(data) {
    if (data && Array.isArray(data.detail)) {
        return data.detail
            .map((item) => {
                const field = Array.isArray(item.loc) ? item.loc[item.loc.length - 1] : "input";
                return `${field}: ${item.msg}`;
            })
            .join(". ");
    }
    return "Some of the information you entered is invalid.";
}

function describeError(result) {
    if (result.status === 0) {
        return "Could not reach the server. Please try again.";
    }
    if (result.status === 401) {
        return "Invalid username or password.";
    }
    if (result.status === 409) {
        return "That username is already taken.";
    }
    if (result.status === 422) {
        return validationMessage(result.data);
    }
    return "Something went wrong. Please try again.";
}

async function login(username, password) {
    const result = await apiRequest("/auth/login", {
        method: "POST",
        body: { username, password },
    });
    if (!result.ok) {
        showError(describeError(result));
        return false;
    }
    saveToken(result.data.access_token);
    return true;
}

async function enterChat() {
    const result = await apiRequest("/auth/me", { token: currentToken });

    if (!result.ok) {
        if (result.status === 401) {
            clearToken();
        }
        showForm("login");
        showView("auth");
        if (result.status !== 401) {
            showError(describeError(result));
        }
        return;
    }

    currentUsername.textContent = result.data.username;
    currentUserId = result.data.id;
    showView("chat");
    startChat();
}

function setStatus(text, state = "disconnected") {
    connectionStatus.textContent = text;
    connectionStatus.className = `status-pill status-pill--${state}`;
}

function setSendingEnabled(enabled) {
    messageInput.disabled = !enabled;
    sendButton.disabled = !enabled;
}

function showChatError(message) {
    chatError.textContent = message;
    chatError.hidden = false;
}

function clearChatError() {
    chatError.textContent = "";
    chatError.hidden = true;
}

function buildSocketUrl() {
    const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${scheme}//${window.location.host}/ws`;
}

function parseTimestamp(value) {
    if (typeof value !== "string") {
        return null;
    }
    let text = value.replace(/(\.\d{3})\d+/, "$1");
    if (!/(Z|[+-]\d{2}:?\d{2})$/i.test(text)) {
        text += "Z";
    }
    const date = new Date(text);
    return Number.isNaN(date.getTime()) ? null : date;
}

function formatTimestamp(value) {
    const date = parseTimestamp(value);
    return date ? date.toLocaleString() : "";
}

function buildMessageElement(message) {
    const isOwn = currentUserId !== null && message.sender_id === currentUserId;

    const item = document.createElement("li");
    item.className = `message ${isOwn ? "message--own" : "message--other"}`;
    item.dataset.messageId = String(message.id);

    const meta = document.createElement("div");
    meta.className = "message__meta";
    const sender = document.createElement("strong");
    sender.className = "message__sender";
    sender.textContent = message.sender_username;
    const time = document.createElement("time");
    time.className = "message__time";
    time.textContent = formatTimestamp(message.created_at);
    meta.append(sender, " ", time);

    const bubble = document.createElement("p");
    bubble.className = "message__bubble";
    bubble.textContent = message.content;

    item.append(meta, bubble);
    return item;
}

function insertMessage(message) {
    if (!message || typeof message.id !== "number" || seenMessageIds.has(message.id)) {
        return;
    }
    seenMessageIds.add(message.id);

    const nearBottom =
        messageList.scrollHeight - messageList.scrollTop - messageList.clientHeight < 40;

    const item = buildMessageElement(message);
    let node = messageList.lastElementChild;
    while (node && Number(node.dataset.messageId) > message.id) {
        node = node.previousElementSibling;
    }
    if (node) {
        node.after(item);
    } else {
        messageList.prepend(item);
    }

    if (nearBottom) {
        messageList.scrollTop = messageList.scrollHeight;
    }
}

async function loadHistory() {
    const ws = socket;
    const result = await apiRequest("/messages?limit=100", { token: currentToken });
    if (ws !== socket) {
        return;
    }
    if (!result.ok) {
        if (result.status === 401) {
            handleAuthFailure();
            return;
        }
        showChatError("Could not load message history.");
        return;
    }
    if (Array.isArray(result.data)) {
        result.data.forEach((message) => insertMessage(message));
    }
}

function handleSocketMessage(raw) {
    let frame;
    try {
        frame = JSON.parse(raw);
    } catch (error) {
        return;
    }
    if (!frame || typeof frame !== "object") {
        return;
    }

    if (frame.type === "auth_ok") {
        authenticated = true;
        reconnectAttempts = 0;
        setStatus("Connected", "connected");
        setSendingEnabled(true);
        clearChatError();
        messageInput.focus();
        loadHistory();
    } else if (frame.type === "message") {
        insertMessage(frame.data);
    } else if (frame.type === "error") {
        showChatError(typeof frame.content === "string" ? frame.content : "Something went wrong.");
    }
}

function scheduleReconnect() {
    if (reconnectTimer !== null) {
        return;
    }
    const delay = Math.min(RECONNECT_BASE_MS * 2 ** reconnectAttempts, RECONNECT_MAX_MS);
    const totalDelay = Math.round(delay + Math.random() * 0.3 * delay);
    reconnectAttempts += 1;
    setStatus(`Disconnected. Reconnecting in ${Math.ceil(totalDelay / 1000)}s...`);
    reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        connectSocket();
    }, totalDelay);
}

function connectSocket() {
    if (!currentToken) {
        return;
    }
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
    authenticated = false;
    setSendingEnabled(false);
    setStatus(reconnectAttempts === 0 ? "Connecting..." : "Reconnecting...", "connecting");

    const ws = new WebSocket(buildSocketUrl());
    socket = ws;

    ws.addEventListener("open", () => {
        if (ws !== socket) {
            return;
        }
        ws.send(JSON.stringify({ type: "auth", data: { token: currentToken } }));
    });

    ws.addEventListener("message", (event) => {
        if (ws !== socket) {
            return;
        }
        handleSocketMessage(event.data);
    });

    ws.addEventListener("close", (event) => {
        if (ws !== socket) {
            return;
        }
        socket = null;
        authenticated = false;
        setSendingEnabled(false);
        if (event.code === POLICY_VIOLATION_CODE) {
            handleAuthFailure();
            return;
        }
        scheduleReconnect();
    });
}

function stopChat() {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
    reconnectAttempts = 0;
    authenticated = false;
    setSendingEnabled(false);

    const ws = socket;
    socket = null;
    if (ws) {
        ws.close();
    }

    messageList.replaceChildren();
    seenMessageIds.clear();
    clearChatError();
    setStatus("Disconnected");
}

function startChat() {
    stopChat();
    connectSocket();
}

function handleAuthFailure() {
    stopChat();
    clearToken();
    showForm("login");
    showView("auth");
    showError("Your session has expired. Please log in again.");
}

messageForm.addEventListener("submit", (event) => {
    event.preventDefault();

    const content = messageInput.value.trim();
    if (!content || !authenticated || !socket || socket.readyState !== WebSocket.OPEN) {
        return;
    }

    clearChatError();
    socket.send(JSON.stringify({ type: "message", content }));
    messageInput.value = "";
});

loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearError();

    const submitButton = loginForm.querySelector("button[type='submit']");
    submitButton.disabled = true;

    const username = document.getElementById("login-username").value;
    const password = document.getElementById("login-password").value;

    try {
        if (await login(username, password)) {
            loginForm.reset();
            await enterChat();
        }
    } finally {
        submitButton.disabled = false;
    }
});

registerForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearError();

    const submitButton = registerForm.querySelector("button[type='submit']");
    submitButton.disabled = true;

    const username = document.getElementById("register-username").value;
    const password = document.getElementById("register-password").value;

    try {
        const result = await apiRequest("/users", {
            method: "POST",
            body: { username, password },
        });

        if (!result.ok) {
            showError(describeError(result));
            return;
        }

        if (await login(username, password)) {
            registerForm.reset();
            await enterChat();
        }
    } finally {
        submitButton.disabled = false;
    }
});

document.getElementById("show-register").addEventListener("click", () => {
    showForm("register");
});

document.getElementById("show-login").addEventListener("click", () => {
    showForm("login");
});

document.getElementById("logout-button").addEventListener("click", () => {
    stopChat();
    clearToken();
    showForm("login");
    showView("auth");
});

async function init() {
    currentToken = loadStoredToken();
    if (currentToken) {
        await enterChat();
    } else {
        showForm("login");
        showView("auth");
    }
}

init();