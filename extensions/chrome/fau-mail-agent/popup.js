const commandEl = document.getElementById("command");
const resultEl = document.getElementById("result");
const runEl = document.getElementById("run");
const fillCheckEl = document.getElementById("fill-check");

fillCheckEl.addEventListener("click", () => {
  commandEl.value = "check my mails";
  commandEl.focus();
});

runEl.addEventListener("click", async () => {
  const command = commandEl.value.trim();
  if (!command) {
    render("Type a command first.");
    return;
  }

  render("Running...");
  const response = await chrome.runtime.sendMessage({
    type: "run-agent-command",
    command,
  });

  if (!response) {
    render("No response from the agent.");
    return;
  }

  render(response.text || response.status || "Done.");
});

function render(text) {
  resultEl.textContent = text;
}
