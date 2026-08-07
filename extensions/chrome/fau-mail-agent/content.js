const LOGIN_USER_SELECTORS = [
  "#rcmloginuser",
  "input[name='_user']",
  "input[type='email']",
  "input[type='text']",
];

const LOGIN_PASSWORD_SELECTORS = [
  "#rcmloginpwd",
  "input[name='_pass']",
  "input[type='password']",
];

const LOGIN_SUBMIT_SELECTORS = [
  "#rcmloginsubmit",
  "button[type='submit']",
  "input[type='submit']",
];

const MAIL_ROW_SELECTORS = [
  "#messagelist tbody tr",
  "table#messagelist tbody tr",
  "table.records-table tbody tr",
];

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  Promise.resolve(handleMessage(message))
    .then((result) => sendResponse(result))
    .catch((error) =>
      sendResponse({
        ok: false,
        text: error instanceof Error ? error.message : String(error),
      }),
    );

  return true;
});

async function handleMessage(message) {
  switch (message?.type) {
    case "detect-state":
      return detectState();
    case "submit-login":
      return submitLogin(message.credentials || {});
    case "collect-inbox":
      return collectInbox();
    case "open-first-unread":
      return openFirstUnread();
    default:
      return { ok: false, text: "Unknown action." };
  }
}

function detectState() {
  if (findFirst(LOGIN_PASSWORD_SELECTORS)) {
    return { state: "login" };
  }

  if (isInboxPage()) {
    return { state: "inbox" };
  }

  return { state: "unknown" };
}

function submitLogin(credentials) {
  const userInput = findFirst(LOGIN_USER_SELECTORS);
  const passInput = findFirst(LOGIN_PASSWORD_SELECTORS);
  const submitButton = findFirst(LOGIN_SUBMIT_SELECTORS);

  if (!userInput || !passInput || !submitButton) {
    return {
      ok: false,
      text: "Roundcube login form was not detected on this page.",
    };
  }

  if (!credentials.username || !credentials.password) {
    return {
      ok: false,
      text: "Missing saved credentials.",
    };
  }

  fillInput(userInput, credentials.username);
  fillInput(passInput, credentials.password);
  submitButton.click();

  return {
    ok: true,
    text: "Submitted FAUmail login form.",
  };
}

function collectInbox() {
  const rows = findMailRows();
  const messages = rows.map(extractMessage).filter(Boolean);

  return {
    ok: true,
    state: "inbox",
    url: window.location.href,
    messageCount: messages.length,
    messages,
  };
}

function openFirstUnread() {
  const rows = findMailRows();
  const unreadRow = rows.find((row) => isUnreadRow(row)) || rows[0];
  if (!unreadRow) {
    return {
      ok: false,
      text: "No visible messages found in the inbox list.",
    };
  }

  const clickable = unreadRow.querySelector("a") || unreadRow;
  clickable.click();
  return {
    ok: true,
    text: "Opened a message from the inbox list.",
  };
}

function isInboxPage() {
  if (window.location.search.includes("_task=mail")) {
    return true;
  }
  return findMailRows().length > 0;
}

function findMailRows() {
  for (const selector of MAIL_ROW_SELECTORS) {
    const rows = Array.from(document.querySelectorAll(selector)).filter((row) => row.children.length > 0);
    if (rows.length) {
      return rows;
    }
  }
  return [];
}

function extractMessage(row) {
  const from = readCellText(row, [
    ".from",
    "td.from",
    ".sender",
    ".col-from",
  ]);
  const subject = readCellText(row, [
    ".subject",
    "td.subject",
    ".col-subject",
  ]);
  const date = readCellText(row, [
    ".date",
    "td.date",
    ".col-date",
  ]);

  if (!from && !subject) {
    return null;
  }

  return {
    unread: isUnreadRow(row),
    from,
    subject,
    date,
  };
}

function isUnreadRow(row) {
  const className = (row.className || "").toLowerCase();
  return className.includes("unread") || className.includes("recent") || row.getAttribute("aria-selected") === "false";
}

function readCellText(root, selectors) {
  for (const selector of selectors) {
    const element = root.querySelector(selector);
    const text = normalizeText(element?.textContent || "");
    if (text) {
      return text;
    }
  }
  return "";
}

function findFirst(selectors) {
  for (const selector of selectors) {
    const element = document.querySelector(selector);
    if (element) {
      return element;
    }
  }
  return null;
}

function fillInput(input, value) {
  input.focus();
  input.value = value;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

function normalizeText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}
