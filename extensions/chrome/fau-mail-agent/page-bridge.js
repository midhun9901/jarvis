window.addEventListener("message", async (event) => {
  if (event.source !== window) {
    return;
  }

  const payload = event.data;
  if (!payload || payload.type !== "JARVIS_EXTENSION_COMMAND" || payload.target !== "fau-mail-agent") {
    return;
  }

  let detail;
  try {
    const response = await chrome.runtime.sendMessage({
      type: "run-agent-command",
      command: payload.command || "",
    });
    detail = {
      ok: Boolean(response?.ok),
      commandId: payload.commandId,
      text: response?.text || "No response from FAU Mail Agent.",
      status: response?.status || "done",
      details: response?.details || null,
    };
  } catch (error) {
    detail = {
      ok: false,
      commandId: payload.commandId,
      text: error instanceof Error ? error.message : String(error),
      status: "error",
      details: null,
    };
  }

  window.postMessage(
    {
      type: "JARVIS_EXTENSION_RESULT",
      source: "fau-mail-agent",
      ...detail,
    },
    "*",
  );
});
