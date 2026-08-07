const MAIL_URL = "https://faumail.fau.de/?_task=mail&_mbox=INBOX";
const MAIL_HOST_PREFIX = "https://faumail.fau.de/";

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "run-agent-command") {
    return false;
  }

  runAgentCommand(message.command || "")
    .then((result) => sendResponse({ ok: true, ...result }))
    .catch((error) =>
      sendResponse({
        ok: false,
        status: "error",
        text: error instanceof Error ? error.message : String(error),
      }),
    );

  return true;
});

async function runAgentCommand(rawCommand) {
  const command = normalizeCommand(rawCommand);
  if (!command) {
    return {
      status: "idle",
      text: "Type a command like 'check my mails' or 'login and check mails'.",
    };
  }

  const intent = parseIntent(command);
  if (!intent) {
    return {
      status: "unsupported",
      text: "This version supports mail-focused commands like 'check my mails', 'mail from Matthew', 'summarize inbox', 'open inbox', and 'open unread'.",
    };
  }

  const tab = await ensureMailTab();
  await waitForTabReady(tab.id);

  let state = await askContent(tab.id, { type: "detect-state" });
  if (state?.state === "login") {
    if (!intent.allowLogin) {
      return {
        status: "login_required",
        text: "FAUmail is at the login page. Use 'login and check mails' or sign in manually first.",
      };
    }

    const credentials = await loadCredentials();
    if (!credentials.username || !credentials.password) {
      return {
        status: "missing_credentials",
        text: "Open the extension options and save your FAUmail username and password first.",
      };
    }

    const loginResult = await askContent(tab.id, {
      type: "submit-login",
      credentials,
    });

    if (!loginResult?.ok) {
      return {
        status: "login_failed",
        text: loginResult?.text || "Login form was found, but automatic sign-in failed.",
      };
    }

    await waitForTabReady(tab.id, 15000);
    state = await pollForInboxState(tab.id, 12, 1200);
  }

  if (state?.state !== "inbox") {
    return {
      status: "waiting",
      text: "FAUmail opened, but I could not confirm the inbox view yet. If SSO, MFA, or CAPTCHA appears, complete it and run the command again.",
    };
  }

  if (intent.action === "open_inbox") {
    return {
      status: "done",
      text: "FAUmail inbox is open.",
    };
  }

  if (intent.action === "open_unread") {
    const openResult = await askContent(tab.id, { type: "open-first-unread" });
    if (openResult?.ok) {
      return {
        status: "done",
        text: "Opened the first unread email in FAUmail.",
      };
    }
    return {
      status: "done",
      text: openResult?.text || "No unread email was found to open.",
    };
  }

  const inbox = await askContent(tab.id, { type: "collect-inbox" });
  if (intent.action === "find_sender") {
    return findSenderInInbox(inbox, intent.senderQuery);
  }
  const summary = summarizeInbox(inbox);
  return {
    status: "done",
    text: summary.text,
    details: summary,
  };
}

function normalizeCommand(value) {
  return String(value || "").trim().toLowerCase();
}

function parseIntent(command) {
  if (!command) {
    return null;
  }

  const senderMatch = command.match(/\bfrom\s+(.+)$/);
  if (senderMatch?.[1]) {
    return {
      action: "find_sender",
      allowLogin: true,
      senderQuery: senderMatch[1].trim(),
    };
  }

  const wantsMail = /(mail|mails|inbox|email|emails|messages)/.test(command);
  const wantsSummary = /(check|summari[sz]e|show|read|review)/.test(command);
  const wantsOpenUnread = /(open).*(unread|latest|first)/.test(command);
  const wantsOpenInbox = /open.*(mail|mails|inbox)/.test(command);
  const allowLogin = /(login|log in|sign in|check)/.test(command);

  if (wantsOpenUnread) {
    return { action: "open_unread", allowLogin: true };
  }

  if (wantsOpenInbox) {
    return { action: "open_inbox", allowLogin };
  }

  if (wantsMail && wantsSummary) {
    return { action: "check_mail", allowLogin: true };
  }

  if (wantsMail) {
    return { action: "check_mail", allowLogin };
  }

  return null;
}

async function ensureMailTab() {
  const tabs = await chrome.tabs.query({});
  const existing = tabs.find((tab) => (tab.url || "").startsWith(MAIL_HOST_PREFIX));
  if (existing?.id) {
    await chrome.tabs.update(existing.id, { active: true, url: MAIL_URL });
    if (existing.windowId) {
      await chrome.windows.update(existing.windowId, { focused: true });
    }
    return existing;
  }

  return chrome.tabs.create({ url: MAIL_URL, active: true });
}

async function waitForTabReady(tabId, timeoutMs = 12000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const tab = await chrome.tabs.get(tabId);
    if (tab.status === "complete") {
      return;
    }
    await delay(250);
  }
}

async function pollForInboxState(tabId, attempts, delayMs) {
  for (let i = 0; i < attempts; i += 1) {
    const state = await askContent(tabId, { type: "detect-state" });
    if (state?.state === "inbox") {
      return state;
    }
    await delay(delayMs);
  }
  return { state: "unknown" };
}

async function askContent(tabId, payload) {
  try {
    return await chrome.tabs.sendMessage(tabId, payload);
  } catch (_error) {
    return null;
  }
}

async function loadCredentials() {
  const data = await chrome.storage.local.get(["username", "password"]);
  return {
    username: data.username || "",
    password: data.password || "",
  };
}

function summarizeInbox(inbox) {
  const messages = Array.isArray(inbox?.messages) ? inbox.messages : [];
  const unread = messages.filter((message) => message.unread);
  const visibleCount = messages.length;
  const unreadCount = unread.length;

  if (!visibleCount) {
    return {
      visibleCount: 0,
      unreadCount: 0,
      text: "Inbox opened, but no visible messages were detected yet.",
    };
  }

  const samples = (unread.length ? unread : messages).slice(0, 5);
  const sampleText = samples
    .map((message, index) => `${index + 1}. ${compact(message.from)} - ${compact(message.subject)}`)
    .join("\n");

  const firstLine =
    unreadCount > 0
      ? `You have ${unreadCount} unread message${unreadCount === 1 ? "" : "s"} in the visible inbox list.`
      : "There are no unread messages in the visible inbox list.";

  return {
    visibleCount,
    unreadCount,
    samples,
    text: `${firstLine}\n${sampleText}`,
  };
}

function findSenderInInbox(inbox, senderQuery) {
  const messages = Array.isArray(inbox?.messages) ? inbox.messages : [];
  const normalizedQuery = compact(senderQuery).toLowerCase();

  if (!messages.length) {
    return {
      status: "done",
      text: "Inbox opened, but no visible messages were detected yet.",
    };
  }

  const matches = messages.filter((message) => {
    const from = compact(message.from).toLowerCase();
    const subject = compact(message.subject).toLowerCase();
    return from.includes(normalizedQuery) || subject.includes(normalizedQuery);
  });

  if (!matches.length) {
    return {
      status: "done",
      text: `I could not find any visible inbox messages from ${compact(senderQuery)}.`,
    };
  }

  const sampleText = matches
    .slice(0, 5)
    .map((message, index) => `${index + 1}. ${compact(message.from)} - ${compact(message.subject)}`)
    .join("\n");

  return {
    status: "done",
    text: `I found ${matches.length} visible message${matches.length === 1 ? "" : "s"} from ${compact(senderQuery)}.\n${sampleText}`,
    details: {
      senderQuery,
      matchCount: matches.length,
      matches: matches.slice(0, 5),
    },
  };
}

function compact(value) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) {
    return "(no text)";
  }
  return text.length > 90 ? `${text.slice(0, 87)}...` : text;
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
