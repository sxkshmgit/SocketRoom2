const TOKEN_KEY = "socketroom_token";
const USERNAME_PATTERN = /^[A-Za-z0-9_.-]+$/;
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
const historyError = document.getElementById("history-error");
const historyErrorText = document.getElementById("history-error-text");
const historyRetry = document.getElementById("history-retry");
const chatTitle = document.getElementById("chat-title");
const chatIcon = document.getElementById("chat-icon");
const sidebarToggle = document.getElementById("sidebar-toggle");
const generalButton = document.getElementById("general-button");
const generalUnread = document.getElementById("general-unread");
const conversationList = document.getElementById("conversation-list");
const conversationEmpty = document.getElementById("conversation-empty");
const userList = document.getElementById("user-list");
const userEmpty = document.getElementById("user-empty");

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
const HISTORY_RETRY_BASE_MS = 1000;
const HISTORY_MAX_RETRIES = 3;

let historyGeneration = 0;
let historyRetryTimer = null;
let historyRequestSocket = null;

// The chat shown in the message list: General, or one private conversation.
// General and private messages are numbered separately, so the message list
// and seenMessageIds only ever hold one chat at a time.
const GENERAL_CHAT = { type: "general" };
let activeChat = GENERAL_CHAT;
let generalHasUnread = false;
const conversations = new Map(); // conversation ID -> conversation (+ unread flag)
let allUsers = [];
let sidebarLoaded = false;
let sidebarGeneration = 0;

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
                return `${field}: ${String(item.msg).replace(/^Value error, /, "")}`;
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

function showHistoryError(message, canRetry) {
    historyErrorText.textContent = message;
    historyRetry.hidden = !canRetry;
    historyError.hidden = false;
}

function clearHistoryError() {
    historyErrorText.textContent = "";
    historyRetry.hidden = true;
    historyError.hidden = true;
}

function cancelHistoryLoad() {
    historyGeneration += 1;
    historyRequestSocket = null;
    clearTimeout(historyRetryTimer);
    historyRetryTimer = null;
    clearHistoryError();
}

function isRetryableHistoryFailure(result) {
    return result.status === 0 || result.status >= 500;
}

function historyPath() {
    if (activeChat.type === "private") {
        return `/conversations/${activeChat.conversationId}/messages?limit=100`;
    }
    return "/messages?limit=100";
}

async function loadHistory(attempt = 0) {
    const ws = socket;
    if (!ws || historyRequestSocket === ws) {
        return;
    }

    const generation = ++historyGeneration;
    historyRequestSocket = ws;
    clearTimeout(historyRetryTimer);
    historyRetryTimer = null;

    if (attempt === 0) {
        clearHistoryError();
    }

    const result = await apiRequest(historyPath(), { token: currentToken });

    // Only clear the marker if no newer load (e.g. after a chat switch) owns it.
    if (historyRequestSocket === ws && generation === historyGeneration) {
        historyRequestSocket = null;
    }

    if (ws !== socket || generation !== historyGeneration) {
        return;
    }

    if (result.ok) {
        clearHistoryError();
        if (Array.isArray(result.data)) {
            result.data.forEach((message) => insertMessage(message));
        }
        return;
    }

    if (result.status === 401) {
        handleAuthFailure();
        return;
    }

    if (isRetryableHistoryFailure(result) && attempt < HISTORY_MAX_RETRIES) {
        const delay = HISTORY_RETRY_BASE_MS * 2 ** attempt;

        showHistoryError(
            `Could not load message history. Retrying in ${Math.ceil(delay / 1000)}s...`,
            false
        );

        historyRetryTimer = setTimeout(() => {
            historyRetryTimer = null;
            if (ws === socket && generation === historyGeneration) {
                loadHistory(attempt + 1);
            }
        }, delay);

        return;
    }

    showHistoryError("Could not load message history.", true);
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
        loadSidebar();
    } else if (frame.type === "message") {
        if (activeChat.type === "general") {
            insertMessage(frame.data);
        } else if (frame.data && frame.data.sender_id !== currentUserId) {
            generalHasUnread = true;
            renderSidebar();
        }
    } else if (frame.type === "private_message") {
        handlePrivateMessage(frame.data);
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
        cancelHistoryLoad();
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
    cancelHistoryLoad();
    setStatus("Disconnected");

    activeChat = GENERAL_CHAT;
    generalHasUnread = false;
    conversations.clear();
    allUsers = [];
    sidebarLoaded = false;
    sidebarGeneration += 1;
    updateChatHeader();
    renderSidebar();
    setSidebarOpen(false);
}

// ---------- Private chats and sidebar ----------

function isActiveConversation(conversationId) {
    return activeChat.type === "private" && activeChat.conversationId === conversationId;
}

function updateChatHeader() {
    const isPrivate = activeChat.type === "private";
    chatIcon.textContent = isPrivate ? "@" : "#";
    chatTitle.textContent = isPrivate ? activeChat.otherUsername : "General";
    messageInput.placeholder = isPrivate
        ? `Message @${activeChat.otherUsername}`
        : "Message #General";
}

function setSidebarOpen(open) {
    chatView.classList.toggle("chat--sidebar-open", open);
    sidebarToggle.setAttribute("aria-expanded", String(open));
    sidebarToggle.setAttribute("aria-label", open ? "Hide chats" : "Show chats");
}

function openChat(chat) {
    const sameChat =
        chat.type === activeChat.type &&
        (chat.type === "general" || chat.conversationId === activeChat.conversationId);
    setSidebarOpen(false);
    if (sameChat) {
        return;
    }

    activeChat = chat;
    if (chat.type === "general") {
        generalHasUnread = false;
    } else {
        const conversation = conversations.get(chat.conversationId);
        if (conversation) {
            conversation.unread = false;
        }
    }

    cancelHistoryLoad();
    messageList.replaceChildren();
    seenMessageIds.clear();
    clearChatError();
    updateChatHeader();
    renderSidebar();

    if (socket && authenticated) {
        loadHistory();
        messageInput.focus();
    }
}

function openPrivateChat(conversation) {
    openChat({
        type: "private",
        conversationId: conversation.id,
        otherUsername: conversation.other_username,
    });
}

function handlePrivateMessage(message) {
    if (!message || typeof message.conversation_id !== "number") {
        return;
    }

    if (isActiveConversation(message.conversation_id)) {
        insertMessage(message);
    }

    const conversation = conversations.get(message.conversation_id);
    if (!conversation) {
        // Someone started a new conversation with us: refresh the list.
        loadSidebar();
        return;
    }

    conversation.last_message_at = message.created_at;
    if (!isActiveConversation(message.conversation_id) && message.sender_id !== currentUserId) {
        conversation.unread = true;
    }
    renderSidebar();
}

async function startConversation(userId) {
    clearChatError();
    const token = currentToken;
    const result = await apiRequest("/conversations", {
        method: "POST",
        body: { user_id: userId },
        token,
    });
    if (token !== currentToken) {
        return; // Logged out while the request was in flight.
    }

    if (!result.ok) {
        if (result.status === 401) {
            handleAuthFailure();
        } else if (result.status === 0) {
            showChatError("Could not reach the server. Please try again.");
        } else {
            showChatError("Could not start the conversation.");
        }
        return;
    }

    let conversation = conversations.get(result.data.id);
    if (!conversation) {
        conversation = { ...result.data, unread: false };
        conversations.set(conversation.id, conversation);
    }
    openPrivateChat(conversation);
}

async function loadSidebar() {
    const generation = ++sidebarGeneration;
    const token = currentToken;
    const [usersResult, conversationsResult] = await Promise.all([
        apiRequest("/users", { token }),
        apiRequest("/conversations", { token }),
    ]);
    if (generation !== sidebarGeneration) {
        return; // A newer load started, or the user logged out.
    }

    if (usersResult.status === 401 || conversationsResult.status === 401) {
        handleAuthFailure();
        return;
    }
    if (!usersResult.ok || !conversationsResult.ok) {
        showChatError("Could not load your conversations.");
        return;
    }

    const fresh = new Map();
    for (const item of conversationsResult.data) {
        const old = conversations.get(item.id);
        // After a reconnect, anything that changed while we were away is unread.
        const changed = !old || old.last_message_at !== item.last_message_at;
        const unread =
            Boolean(old && old.unread) ||
            (sidebarLoaded && changed && !isActiveConversation(item.id));
        fresh.set(item.id, { ...item, unread });
    }
    // Keep conversations opened here that have no messages yet; the server
    // only lists conversations with at least one message.
    for (const [id, old] of conversations) {
        if (!fresh.has(id) && old.last_message_at === null) {
            fresh.set(id, old);
        }
    }

    conversations.clear();
    fresh.forEach((conversation, id) => conversations.set(id, conversation));
    allUsers = usersResult.data;
    sidebarLoaded = true;
    renderSidebar();
}

function activityTime(conversation) {
    const date = parseTimestamp(conversation.last_message_at);
    // Conversations with no messages yet were just opened: show them first.
    return date ? date.getTime() : Number.MAX_SAFE_INTEGER;
}

function buildSidebarItem({ icon, name, active = false, unread = false, onClick }) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = unread ? "sidebar__item sidebar__item--unread" : "sidebar__item";
    if (active) {
        button.setAttribute("aria-current", "true");
    }

    const iconElement = document.createElement("span");
    iconElement.className = "sidebar__icon";
    iconElement.setAttribute("aria-hidden", "true");
    iconElement.textContent = icon;

    const nameElement = document.createElement("span");
    nameElement.className = "sidebar__name";
    nameElement.textContent = name;

    button.append(iconElement, nameElement);

    if (unread) {
        const dot = document.createElement("span");
        dot.className = "sidebar__unread";
        const label = document.createElement("span");
        label.className = "visually-hidden";
        label.textContent = "unread messages";
        dot.append(label);
        button.append(dot);
    }

    button.addEventListener("click", onClick);
    item.append(button);
    return item;
}

function renderSidebar() {
    if (activeChat.type === "general") {
        generalButton.setAttribute("aria-current", "true");
    } else {
        generalButton.removeAttribute("aria-current");
    }
    generalButton.classList.toggle("sidebar__item--unread", generalHasUnread);
    generalUnread.hidden = !generalHasUnread;

    const sorted = [...conversations.values()].sort(
        (a, b) => activityTime(b) - activityTime(a)
    );
    conversationList.replaceChildren(
        ...sorted.map((conversation) =>
            buildSidebarItem({
                icon: "@",
                name: conversation.other_username,
                active: isActiveConversation(conversation.id),
                unread: conversation.unread,
                onClick: () => openPrivateChat(conversation),
            })
        )
    );
    conversationEmpty.hidden = !sidebarLoaded || sorted.length > 0;

    // "Start a chat" lists everyone we don't already have a conversation with.
    const inConversation = new Set(sorted.map((conversation) => conversation.other_user_id));
    const others = allUsers.filter(
        (user) => user.id !== currentUserId && !inConversation.has(user.id)
    );
    userList.replaceChildren(
        ...others.map((user) =>
            buildSidebarItem({
                icon: user.username.charAt(0).toUpperCase(),
                name: user.username,
                onClick: () => startConversation(user.id),
            })
        )
    );
    userEmpty.hidden = !sidebarLoaded || others.length > 0;

    const anyUnread = generalHasUnread || sorted.some((conversation) => conversation.unread);
    sidebarToggle.classList.toggle("sidebar-toggle--unread", anyUnread);
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
    const frame =
        activeChat.type === "private"
            ? { type: "private_message", conversation_id: activeChat.conversationId, content }
            : { type: "message", content };
    socket.send(JSON.stringify(frame));
    messageInput.value = "";
});

generalButton.addEventListener("click", () => {
    openChat(GENERAL_CHAT);
});

sidebarToggle.addEventListener("click", () => {
    setSidebarOpen(!chatView.classList.contains("chat--sidebar-open"));
});

document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && chatView.classList.contains("chat--sidebar-open")) {
        setSidebarOpen(false);
        sidebarToggle.focus();
    }
});

historyRetry.addEventListener("click", () => {
    if (socket && authenticated) {
        loadHistory();
    }
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

    const username = document.getElementById("register-username").value.trim();
    const password = document.getElementById("register-password").value;

    try {
        if (!USERNAME_PATTERN.test(username)) {
            showError("Username: use only letters, numbers, underscores, hyphens and periods.");
            return;
        }

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