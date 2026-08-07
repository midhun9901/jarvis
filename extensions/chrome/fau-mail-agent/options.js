const usernameEl = document.getElementById("username");
const passwordEl = document.getElementById("password");
const statusEl = document.getElementById("status");
const saveEl = document.getElementById("save");
const clearEl = document.getElementById("clear");

restore();

saveEl.addEventListener("click", async () => {
  await chrome.storage.local.set({
    username: usernameEl.value.trim(),
    password: passwordEl.value,
  });
  setStatus("Saved credentials locally.");
});

clearEl.addEventListener("click", async () => {
  await chrome.storage.local.remove(["username", "password"]);
  usernameEl.value = "";
  passwordEl.value = "";
  setStatus("Cleared saved credentials.");
});

async function restore() {
  const data = await chrome.storage.local.get(["username", "password"]);
  usernameEl.value = data.username || "";
  passwordEl.value = data.password || "";
}

function setStatus(text) {
  statusEl.textContent = text;
}
