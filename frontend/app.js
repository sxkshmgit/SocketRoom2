// SocketRoom frontend.
//
// HTTP (fetch) is used for logging in and loading data: history, users,
// conversations. One WebSocket per tab carries live messages both ways.

// ---------- Page elements ----------

const authView = document.getElementById("auth-view");
const chatView = document.getElementById("chat-view");
const loginForm = document.getElementById("login-form");
const registerForm = document.getElementById("register-form");
const authError = document.getElementById("auth-error");
const currentUsername = document.getElementById("current-username");
const connectionStatus = document.getElementById("connection-status");
const chatTitle = document.getElementById("chat-title");
const chatIcon = document.getElementById("chat-icon");
const sidebarToggle = document.getElementById("sidebar-toggle");
const generalButton = document.getElementById("general-button");
const generalUnread = document.getElementById("general-unread");
const conversationList = document.getElementById("conversation-list");
const conversationEmpty = document.getElementById("conversation-empty");
const userList = document.getElementById("user-list");
const userEmpty = document.getElementById("user-empty");
const messageList = document.getElementById("message-list");
const historyError = document.getElementById("history-error");
const historyRetry = document.getElementById("history-retry");
const chatError = document.getElementById("chat-error");
const messageForm = document.getElementById("message-form");
const messageInput = document.getElementById("message-input");
const sendButton = document.getElementById("send-button");

// ---------- State ----------

const TOKEN_KEY = "socketroom_token";
const RECONNECT_DELAY_MS = 2000;
const SESSION_EXPIRED = "Your session has expired. Please log in again.";

// The open chat is either General or one private conversation.
// Its `id` is "general" or the conversation's ID.
const GENERAL = { id: "general", name: "General" };

let token = sessionStorage.getItem(TOKEN_KEY);
let currentUser = null;   // { id, username }
let socket = null;        // the open WebSocket, or null
let reconnectTimer = null;
let activeChat = GENERAL;
let users = [];           // everyone registered
let conversations = [];   // my conversations, newest activity first
const unread = new Set(); // IDs of chats with unseen messages

function privateChat(conversation) {
    return { id: conversation.id, name: conversation.other_username, conversation };
}

// ---------- HTTP ----------

// Calls the API and returns { ok, status, data }. status is 0 if the server
// could not be reached.
async function api(path, { method = "GET", body } = {}) {
    const headers = {};
    if (token) {
        headers["Authorization"] = `Bearer ${token}`;
    }
    if (body !== undefined) {
        headers["Content-Type"] = "application/json";
    }
    try {
        const response = await fetch(path, {
            method,
            headers,
            body: body === undefined ? undefined : JSON.stringify(body),
        });
        const data = await response.json().catch(() => null);
        return { ok: response.ok, status: response.status, data };
    } catch (error) {
        return { ok: false, status: 0, data: null };
    }
}

// Turns a failed API result into a message for the user. FastAPI puts the
// reason in `detail`: a string, or a list of validation errors.
function errorText(result) {
    if (result.status === 0) {
        return "Could not reach the server. Please try again.";
    }
    const detail = result.data && result.data.detail;
    if (typeof detail === "string") {
        return detail;
    }
    if (Array.isArray(detail)) {
        return detail
            .map((item) => `${item.loc.at(-1)}: ${item.msg.replace(/^Value error, /, "")}`)
            .join(". ");
    }
    return "Something went wrong. Please try again.";
}

// ---------- Logging in and out ----------

function showView(name) {
    authView.hidden = name !== "auth";
    chatView.hidden = name !== "chat";
}

function showForm(name) {
    loginForm.hidden = name !== "login";
    registerForm.hidden = name !== "register";
    showAuthError("");
}

function showAuthError(message) {
    authError.textContent = message;
    authError.hidden = !message;
}

async function logIn(username, password) {
    const result = await api("/auth/login", {
        method: "POST",
        body: { username, password },
    });
    if (!result.ok) {
        showAuthError(errorText(result));
        return;
    }
    token = result.data.access_token;
    sessionStorage.setItem(TOKEN_KEY, token);
    loginForm.reset();
    registerForm.reset();
    await enterChat();
}

async function enterChat() {
    const result = await api("/auth/me");
    if (!result.ok) {
        logOut(result.status === 401 ? "" : errorText(result));
        return;
    }
    currentUser = result.data;
    currentUsername.textContent = currentUser.username;
    showView("chat");
    showChatHeader();
    renderSidebar();
    // History and the sidebar are loaded once the WebSocket says auth_ok.
    connect();
}

function logOut(message = "") {
    clearTimeout(reconnectTimer);
    closeSocket();
    token = null;
    sessionStorage.removeItem(TOKEN_KEY);
    currentUser = null;
    users = [];
    conversations = [];
    unread.clear();
    activeChat = GENERAL;
    messageList.replaceChildren();
    renderSidebar();
    setStatus("Disconnected", "disconnected");
    showForm("login");
    showView("auth");
    showAuthError(message);
}

// ---------- WebSocket ----------

function setStatus(text, state) {
    connectionStatus.textContent = text;
    connectionStatus.className = `status-pill status-pill--${state}`;
}

function setSendingEnabled(enabled) {
    messageInput.disabled = !enabled;
    sendButton.disabled = !enabled;
}

// Closes the socket on purpose. Setting `socket` to null first tells the
// close handler below not to reconnect.
function closeSocket() {
    const ws = socket;
    socket = null;
    if (ws) {
        ws.close();
    }
}

function connect() {
    closeSocket();
    setStatus("Connecting...", "connecting");
    setSendingEnabled(false);

    const scheme = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${scheme}//${location.host}/ws`);
    socket = ws;

    // Step 1: the first frame we send must be our token.
    ws.addEventListener("open", () => {
        ws.send(JSON.stringify({ type: "auth", data: { token } }));
    });

    // Step 2: everything the server sends arrives here.
    ws.addEventListener("message", (event) => {
        if (ws === socket) {
            handleFrame(JSON.parse(event.data));
        }
    });

    ws.addEventListener("close", (event) => {
        if (ws !== socket) {
            return; // We closed it ourselves (log out, or a new connection).
        }
        socket = null;
        setSendingEnabled(false);
        // 1008: the token was rejected or has expired.
        if (event.code === 1008) {
            logOut(SESSION_EXPIRED);
            return;
        }
        // Anything else (server restart, network drop): try again shortly.
        setStatus("Disconnected. Reconnecting...", "disconnected");
        reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS);
    });
}

function handleFrame(frame) {
    if (frame.type === "auth_ok") {
        setStatus("Connected", "connected");
        setSendingEnabled(true);
        clearChatError();
        messageInput.focus();
        // (Re)load everything, in case we missed messages while disconnected.
        loadHistory();
        loadSidebar();
    } else if (frame.type === "message") {
        receiveMessage(GENERAL.id, frame.data);
    } else if (frame.type === "private_message") {
        receiveMessage(frame.data.conversation_id, frame.data);
    } else if (frame.type === "error") {
        showChatError(frame.content);
    }
}

function receiveMessage(chatId, message) {
    if (chatId === activeChat.id) {
        appendMessage(message);
    } else if (message.sender_id !== currentUser.id) {
        unread.add(chatId);
    }

    if (chatId !== GENERAL.id) {
        const conversation = conversations.find((c) => c.id === chatId);
        if (!conversation) {
            loadSidebar(); // Someone started a new conversation with us.
            return;
        }
        // Newest activity first: move this conversation to the top.
        conversations = [conversation, ...conversations.filter((c) => c !== conversation)];
    }
    renderSidebar();
}

function sendMessage(content) {
    const frame =
        activeChat.id === GENERAL.id
            ? { type: "message", content }
            : { type: "private_message", conversation_id: activeChat.id, content };
    socket.send(JSON.stringify(frame));
}

// ---------- Messages ----------

function showChatError(message) {
    chatError.textContent = message;
    chatError.hidden = false;
}

function clearChatError() {
    chatError.hidden = true;
}

function formatTime(value) {
    // The server sends UTC times without a time zone, sometimes with
    // microseconds. Keep up to milliseconds and mark them as UTC ("Z").
    return new Date(value.slice(0, 23) + "Z").toLocaleString();
}

function buildMessageElement(message) {
    const isOwn = message.sender_id === currentUser.id;

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
    time.textContent = formatTime(message.created_at);
    meta.append(sender, " ", time);

    // textContent (never innerHTML) so messages can't inject HTML.
    const bubble = document.createElement("p");
    bubble.className = "message__bubble";
    bubble.textContent = message.content;

    item.append(meta, bubble);
    return item;
}

function isShown(message) {
    return messageList.querySelector(`[data-message-id="${message.id}"]`) !== null;
}

function appendMessage(message) {
    if (isShown(message)) {
        return;
    }
    const nearBottom =
        messageList.scrollHeight - messageList.scrollTop - messageList.clientHeight < 40;
    messageList.append(buildMessageElement(message));
    if (nearBottom) {
        messageList.scrollTop = messageList.scrollHeight;
    }
}

async function loadHistory() {
    const chat = activeChat;
    messageList.replaceChildren();
    historyError.hidden = true;

    const path =
        chat.id === GENERAL.id
            ? "/messages?limit=100"
            : `/conversations/${chat.id}/messages?limit=100`;
    const result = await api(path);

    if (chat !== activeChat) {
        return; // The user switched chats while this was loading.
    }
    if (result.status === 401) {
        logOut(SESSION_EXPIRED);
        return;
    }
    if (!result.ok) {
        historyError.hidden = false;
        return;
    }
    // Live messages may have arrived while we were loading; they are newer,
    // so put the history in front of them and skip any duplicates.
    const older = result.data.filter((message) => !isShown(message));
    messageList.prepend(...older.map(buildMessageElement));
    messageList.scrollTop = messageList.scrollHeight;
}

// ---------- Chats and sidebar ----------

function showChatHeader() {
    const isGeneral = activeChat.id === GENERAL.id;
    chatIcon.textContent = isGeneral ? "#" : "@";
    chatTitle.textContent = activeChat.name;
    messageInput.placeholder = isGeneral ? "Message #General" : `Message @${activeChat.name}`;
}

function setSidebarOpen(open) {
    chatView.classList.toggle("chat--sidebar-open", open);
    sidebarToggle.setAttribute("aria-expanded", String(open));
}

function openChat(chat) {
    setSidebarOpen(false);
    if (chat.id === activeChat.id) {
        return;
    }
    activeChat = chat;
    unread.delete(chat.id);
    clearChatError();
    showChatHeader();
    renderSidebar();
    loadHistory();
    messageInput.focus();
}

async function startConversation(userId) {
    const result = await api("/conversations", {
        method: "POST",
        body: { user_id: userId },
    });
    if (result.status === 401) {
        logOut(SESSION_EXPIRED);
        return;
    }
    if (!result.ok) {
        showChatError(errorText(result));
        return;
    }
    const conversation = result.data;
    if (!conversations.some((c) => c.id === conversation.id)) {
        conversations.unshift(conversation);
    }
    openChat(privateChat(conversation));
}

async function loadSidebar() {
    const requestToken = token;
    const [usersResult, conversationsResult] = await Promise.all([
        api("/users"),
        api("/conversations"),
    ]);
    if (token !== requestToken) {
        return; // Logged out while loading.
    }
    if (usersResult.status === 401 || conversationsResult.status === 401) {
        logOut(SESSION_EXPIRED);
        return;
    }
    if (!usersResult.ok || !conversationsResult.ok) {
        showChatError("Could not load your conversations.");
        return;
    }
    users = usersResult.data;
    conversations = conversationsResult.data;
    // The server only lists conversations that have messages. Keep the open
    // one visible even if nothing has been sent in it yet.
    const open = activeChat.conversation;
    if (open && !conversations.some((c) => c.id === open.id)) {
        conversations.unshift(open);
    }
    renderSidebar();
}

function buildSidebarItem(icon, name, chatId, onClick) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "sidebar__item";
    button.setAttribute("aria-current", String(chatId === activeChat.id));
    button.classList.toggle("sidebar__item--unread", unread.has(chatId));

    const iconElement = document.createElement("span");
    iconElement.className = "sidebar__icon";
    iconElement.setAttribute("aria-hidden", "true");
    iconElement.textContent = icon;

    const nameElement = document.createElement("span");
    nameElement.className = "sidebar__name";
    nameElement.textContent = name;
    button.append(iconElement, nameElement);

    if (unread.has(chatId)) {
        const dot = document.createElement("span");
        dot.className = "sidebar__unread";
        const label = document.createElement("span");
        label.className = "visually-hidden"; // read by screen readers only
        label.textContent = "unread messages";
        dot.append(label);
        button.append(dot);
    }

    button.addEventListener("click", onClick);
    const item = document.createElement("li");
    item.append(button);
    return item;
}

function renderSidebar() {
    generalButton.setAttribute("aria-current", String(activeChat.id === GENERAL.id));
    generalButton.classList.toggle("sidebar__item--unread", unread.has(GENERAL.id));
    generalUnread.hidden = !unread.has(GENERAL.id);

    conversationList.replaceChildren(
        ...conversations.map((c) =>
            buildSidebarItem("@", c.other_username, c.id, () => openChat(privateChat(c)))
        )
    );
    conversationEmpty.hidden = conversations.length > 0;

    // "Start a chat" lists everyone we don't have a conversation with yet.
    const talkingTo = new Set(conversations.map((c) => c.other_user_id));
    const others = users.filter((u) => u.id !== currentUser.id && !talkingTo.has(u.id));
    userList.replaceChildren(
        ...others.map((u) =>
            buildSidebarItem(u.username[0].toUpperCase(), u.username, null, () =>
                startConversation(u.id)
            )
        )
    );
    userEmpty.hidden = others.length > 0;

    sidebarToggle.classList.toggle("sidebar-toggle--unread", unread.size > 0);
}

// ---------- Event listeners ----------

loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await logIn(
        document.getElementById("login-username").value,
        document.getElementById("login-password").value
    );
});

registerForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const username = document.getElementById("register-username").value.trim();
    const password = document.getElementById("register-password").value;
    const result = await api("/users", { method: "POST", body: { username, password } });
    if (!result.ok) {
        showAuthError(errorText(result));
        return;
    }
    await logIn(username, password);
});

document.getElementById("show-register").addEventListener("click", () => showForm("register"));
document.getElementById("show-login").addEventListener("click", () => showForm("login"));
document.getElementById("logout-button").addEventListener("click", () => logOut());

messageForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const content = messageInput.value.trim();
    if (!content || !socket || messageInput.disabled) {
        return;
    }
    clearChatError();
    sendMessage(content);
    messageInput.value = "";
});

generalButton.addEventListener("click", () => openChat(GENERAL));
historyRetry.addEventListener("click", () => loadHistory());
sidebarToggle.addEventListener("click", () => {
    setSidebarOpen(!chatView.classList.contains("chat--sidebar-open"));
});
document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
        setSidebarOpen(false);
    }
});

// ---------- Start ----------

if (token) {
    enterChat(); // Still logged in from earlier in this tab.
} else {
    showForm("login");
    showView("auth");
}
