import base64
import asyncio
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import asynccontextmanager

# Force UTF-8 output on Windows so Malayalam/Unicode text doesn't crash the console
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
os.environ.setdefault("PYTHONUNBUFFERED", "1")

def safe_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        safe = " ".join(str(a).encode("ascii", errors="replace").decode("ascii") for a in args)
        print(safe, **{k: v for k, v in kwargs.items() if k != "end"})
from collections import Counter
from pathlib import Path
from urllib.parse import quote_plus

import edge_tts
import httpx
import websockets
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from duckduckgo_search import DDGS
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI

from core.memory_consolidator import memory_consolidator_loop
from core.self_improvement_agent import run_self_improvement_agent, self_improvement_agent_loop
from core.verifier import sanitize_unverified_action_reply
from core.voice_normalizer import extract_wake_command, is_stop_listening_command, normalize_voice_text
from tools.mail_triage import (
    mail_category as _mail_category,
    mail_list_highlights as _mail_list_highlights,
    mail_priority as _mail_priority,
    relative_date_label as _relative_date_label,
    smart_mail_triage as _smart_mail_triage,
    smart_single_mail_summary as _smart_single_mail_summary,
)

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent if APP_DIR.name == "backend" else APP_DIR
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_DIR = PROJECT_ROOT / "config"
RUNTIME_DIR = PROJECT_ROOT / "runtime"
FRONTEND_DIR = PROJECT_ROOT / "frontend"

env_file = CONFIG_DIR / ".env"
load_dotenv(env_file if env_file.exists() else PROJECT_ROOT / ".env")

app = FastAPI(title="J.A.R.V.I.S.")
app.add_middleware(CORSMiddleware,
                   allow_origins=["http://localhost:5173", "http://127.0.0.1:5173",
                                  "http://localhost:8000", "http://127.0.0.1:8000"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

GROK_API_KEY    = os.getenv("GROK_API_KEY")
GROK_MODEL      = os.getenv("GROK_MODEL", "llama-3.3-70b-versatile")
DEEPSEEK_API_KEY    = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL      = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
DEEPSEEK_PRO_MODEL  = os.getenv("DEEPSEEK_PRO_MODEL", "deepseek-v4-pro")
DEEPSEEK_BASE_URL   = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY", "")
OPENAI_API_KEY      = os.getenv("OPENAI_API_KEY", "")
OPENROUTER_API_KEY  = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL    = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-r1:free")
VOICE               = os.getenv("TTS_VOICE", "en-GB-RyanNeural")
TTS_RATE            = os.getenv("TTS_RATE", "+25%")
LLM_MAX_TOKENS      = int(os.getenv("LLM_MAX_TOKENS", "500"))
LLM_TEMPERATURE     = float(os.getenv("LLM_TEMPERATURE", "0.3"))
MAX_TOOL_STEPS      = int(os.getenv("MAX_TOOL_STEPS", "3"))
STT_MODEL           = os.getenv("STT_MODEL", "whisper-large-v3-turbo")
DAILY_TOKEN_LIMIT   = int(os.getenv("DAILY_TOKEN_LIMIT", os.getenv("GROQ_DAILY_TOKEN_LIMIT", "100000")))
MAX_CONTEXT_MESSAGES = int(os.getenv("MAX_CONTEXT_MESSAGES", "4"))
TOOL_RESULT_HISTORY_CHARS = int(os.getenv("TOOL_RESULT_HISTORY_CHARS", "350"))
PROMPT_MEMORY_FACTS = int(os.getenv("PROMPT_MEMORY_FACTS", "3"))
PROMPT_MEMORY_PREFS = int(os.getenv("PROMPT_MEMORY_PREFS", "3"))
PROMPT_WIKI_CHARS = int(os.getenv("PROMPT_WIKI_CHARS", "500"))
OBSIDIAN_VAULT      = Path(os.getenv("OBSIDIAN_VAULT", str(Path.home() / "Documents" / "Obsidian")))
SECOND_BRAIN_WIKI_DIR = Path(os.getenv("SECOND_BRAIN_WIKI_DIR", "")).expanduser() if os.getenv("SECOND_BRAIN_WIKI_DIR") else None
MEMORY_FILE         = DATA_DIR / "memory.json"
WIKI_DIR            = DATA_DIR / "wiki"
SUMMARIES_FILE      = DATA_DIR / "project_summaries.json"
CONVERSATIONS_DIR   = DATA_DIR / "conversations"
CONVERSATION_INDEX_FILE = DATA_DIR / "conversation_index.json"
MEMORY_STATE_FILE   = DATA_DIR / "memory_state.json"
JARVIS_LESSONS_FILE = DATA_DIR / "jarvis_lessons.json"
SELF_IMPROVEMENT_STATE_FILE = DATA_DIR / "self_improvement_state.json"
IMPROVEMENT_REPORTS_DIR = DATA_DIR / "improvement_reports"
FRONTEND_DIST_DIR   = FRONTEND_DIR / "dist"
FRONTEND_ASSETS_DIR = FRONTEND_DIST_DIR / "assets"
DATA_DIR.mkdir(exist_ok=True)
RUNTIME_DIR.mkdir(exist_ok=True)
CONVERSATIONS_DIR.mkdir(exist_ok=True)

MEMORY_RETRIEVAL_LIMIT = int(os.getenv("MEMORY_RETRIEVAL_LIMIT", "2"))
MEMORY_RETRIEVAL_CHAR_BUDGET = int(os.getenv("MEMORY_RETRIEVAL_CHAR_BUDGET", "900"))
MEMORY_CONSOLIDATOR_ENABLED = os.getenv("MEMORY_CONSOLIDATOR_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
MEMORY_CONSOLIDATOR_INTERVAL_HOURS = float(os.getenv("MEMORY_CONSOLIDATOR_INTERVAL_HOURS", "5"))
MEMORY_CONSOLIDATOR_MAX_SESSIONS = int(os.getenv("MEMORY_CONSOLIDATOR_MAX_SESSIONS", "12"))
MEMORY_CONSOLIDATOR_SESSION_AGE_MINUTES = int(os.getenv("MEMORY_CONSOLIDATOR_SESSION_AGE_MINUTES", "10"))
SELF_IMPROVEMENT_AGENT_ENABLED = os.getenv("SELF_IMPROVEMENT_AGENT_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
SELF_IMPROVEMENT_INTERVAL_HOURS = float(os.getenv("SELF_IMPROVEMENT_INTERVAL_HOURS", "12"))
SELF_IMPROVEMENT_MAX_SESSIONS = int(os.getenv("SELF_IMPROVEMENT_MAX_SESSIONS", "6"))
SELF_IMPROVEMENT_SESSION_AGE_MINUTES = int(os.getenv("SELF_IMPROVEMENT_SESSION_AGE_MINUTES", "30"))
SELF_IMPROVEMENT_LESSON_LIMIT = int(os.getenv("SELF_IMPROVEMENT_LESSON_LIMIT", "5"))
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")

# Proactivity — Jarvis volunteers calendar/mail alerts without being asked
PROACTIVE_AGENT_ENABLED = os.getenv("PROACTIVE_AGENT_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
PROACTIVE_INTERVAL_SECONDS = int(os.getenv("PROACTIVE_INTERVAL_SECONDS", "120"))
PROACTIVE_EVENT_LEAD_MIN = int(os.getenv("PROACTIVE_EVENT_LEAD_MIN", "15"))
PROACTIVE_COOLDOWN_SECONDS = int(os.getenv("PROACTIVE_COOLDOWN_SECONDS", "300"))
PROACTIVE_QUIET_START = int(os.getenv("PROACTIVE_QUIET_START", "23"))  # 23:00
PROACTIVE_QUIET_END = int(os.getenv("PROACTIVE_QUIET_END", "8"))       # 08:00
PROACTIVE_MAIL_ALERTS = os.getenv("PROACTIVE_MAIL_ALERTS", "true").lower() in {"1", "true", "yes", "on"}

PROJECT_ROOTS = [
    Path("C:/PROJECTS"),
    Path.home() / "Desktop",
]

MODEL_PROFILES: dict[str, dict] = {}


def _register_model_profile(key: str, label: str, api_client, model: str) -> None:
    if api_client and model:
        MODEL_PROFILES[key] = {"label": label, "client": api_client, "model": model}


groq_client = OpenAI(api_key=GROK_API_KEY, base_url="https://api.groq.com/openai/v1") if GROK_API_KEY else None
if groq_client:
    _register_model_profile("groq", "Groq", groq_client, GROK_MODEL)
    print(f"  Brain option: Groq ({GROK_MODEL})")

deepseek_client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL) if DEEPSEEK_API_KEY else None
if deepseek_client:
    _register_model_profile("deepseek", "DeepSeek", deepseek_client, DEEPSEEK_MODEL)
    _register_model_profile("deepseek-pro", "DeepSeek Pro", deepseek_client, DEEPSEEK_PRO_MODEL)
    print(f"  Brain option: DeepSeek ({DEEPSEEK_MODEL})")
    print(f"  Brain option: DeepSeek Pro ({DEEPSEEK_PRO_MODEL})")

# Gemini — used only as final fallback when all Groq models are exhausted
gemini_client = None
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
if GEMINI_API_KEY:
    gemini_client = OpenAI(
        api_key=GEMINI_API_KEY,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
    )
    _register_model_profile("gemini", "Gemini", gemini_client, GEMINI_MODEL)
    print(f"  Fallback: Gemini ({GEMINI_MODEL})")

# OpenAI — used as fallback after Groq + Gemini are exhausted
openai_client = None
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
if OPENAI_API_KEY:
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
    _register_model_profile("openai", "OpenAI", openai_client, OPENAI_MODEL)
    print(f"  Fallback: OpenAI ({OPENAI_MODEL})")

# OpenRouter — used as fallback after Groq + Gemini are exhausted
openrouter_client = None
if OPENROUTER_API_KEY:
    openrouter_client = OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
        default_headers={"HTTP-Referer": "http://localhost:5173", "X-Title": "JARVIS"}
    )
    _register_model_profile("openrouter", "OpenRouter", openrouter_client, OPENROUTER_MODEL)
    print(f"  Fallback: OpenRouter ({OPENROUTER_MODEL})")

if not MODEL_PROFILES:
    raise RuntimeError("No chat model API key found. Set DEEPSEEK_API_KEY, GROK_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, or OPENROUTER_API_KEY.")


def _normalize_model_choice(choice: str) -> str | None:
    t = re.sub(r"[^a-z0-9]+", " ", (choice or "").lower()).strip()
    if not t:
        return None
    if "deepseek" in t or "deep seek" in t:
        return "deepseek-pro" if re.search(r"\b(pro|reason|thinking|smart)\b", t) else "deepseek"
    if "groq" in t or "grok" in t or "llama" in t or "allama" in t or "alama" in t:
        return "groq"
    if "ollama" in t or "olama" in t:
        return "ollama"
    if "gemini" in t or "google" in t:
        return "gemini"
    if "openrouter" in t or "router" in t:
        return "openrouter"
    if "openai" in t or "gpt" in t:
        return "openai"
    return None


def _set_active_model(provider_key: str) -> str:
    global ACTIVE_PROVIDER, ACTIVE_MODEL, client
    if provider_key not in MODEL_PROFILES:
        available = ", ".join(profile["label"] for profile in MODEL_PROFILES.values())
        raise ValueError(f"{provider_key} is not configured. Available brains: {available}.")
    profile = MODEL_PROFILES[provider_key]
    ACTIVE_PROVIDER = provider_key
    ACTIVE_MODEL = profile["model"]
    client = profile["client"]
    _token_stats["active_model"] = ACTIVE_MODEL
    return f"Switched brain to {profile['label']} using {ACTIVE_MODEL}, sir."


def detect_model_switch_request(text: str) -> str | None:
    lowered = (text or "").lower().strip()
    if not re.search(r"\b(switch|change|use|set|select|make)\b", lowered):
        return None
    if not re.search(r"\b(brain|model|llm|ai|deep\s*seek|deepseek|groq|grok|llama|allama|alama|ollama|olama|gemini|openai|gpt|openrouter)\b", lowered):
        return None
    return _normalize_model_choice(lowered) or "__unknown__"


preferred_provider = _normalize_model_choice(os.getenv("JARVIS_LLM_PROVIDER", os.getenv("LLM_PROVIDER", "")))
if not preferred_provider:
    preferred_provider = "deepseek" if "deepseek" in MODEL_PROFILES else next(iter(MODEL_PROFILES))
if preferred_provider not in MODEL_PROFILES:
    preferred_provider = next(iter(MODEL_PROFILES))

ACTIVE_PROVIDER = preferred_provider
ACTIVE_MODEL = MODEL_PROFILES[ACTIVE_PROVIDER]["model"]
client = MODEL_PROFILES[ACTIVE_PROVIDER]["client"]
print(f"  Brain: {MODEL_PROFILES[ACTIVE_PROVIDER]['label']} ({ACTIVE_MODEL})")

active_connections: set[WebSocket] = set()
memory_consolidator_task: asyncio.Task | None = None
self_improvement_agent_task: asyncio.Task | None = None
proactive_agent_task: asyncio.Task | None = None
_last_user_activity: float = 0.0   # epoch seconds — suppress proactivity mid-conversation
MALAYALAM_VOICE = os.getenv("MALAYALAM_VOICE", "ml-IN-MidhunNeural")
MALAYALAM_KEYWORDS = frozenset({
    "kerala", "keralam", "malayalam", "malayali", "keralite",
    "kochi", "kozhikode", "thiruvananthapuram", "trivandrum", "thrissur",
    "kannur", "palakkad", "wayanad", "malappuram", "alappuzha",
    "kollam", "kasaragod", "pathanamthitta", "ernakulam", "calicut",
})

if FRONTEND_ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_ASSETS_DIR)), name="assets")

MEMORY_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "can", "could", "did", "do", "for",
    "from", "get", "got", "had", "has", "have", "hello", "help", "hey", "how", "i", "if", "in",
    "into", "is", "it", "its", "just", "latest", "let", "like", "make", "me", "my", "need", "now",
    "of", "on", "open", "or", "our", "please", "project", "projects", "search", "show", "sir", "so",
    "tell", "that", "the", "their", "them", "then", "there", "these", "they", "this", "to", "up",
    "use", "want", "was", "we", "what", "when", "where", "which", "who", "why", "with", "would",
    "yeah", "yes", "you", "your",
}


# ── Memory ─────────────────────────────────────────────────────────────────────

# ── Conversation logger ────────────────────────────────────────────────────────

conversation_store_initialized = False


def now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def load_conversation_index() -> dict:
    if CONVERSATION_INDEX_FILE.exists():
        try:
            data = json.loads(CONVERSATION_INDEX_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "sessions" in data:
                return data
        except Exception:
            pass
    return {"sessions": {}}


def save_conversation_index(index: dict):
    CONVERSATION_INDEX_FILE.write_text(json.dumps(index, indent=2), encoding="utf-8")


def trim_text(text: str, limit: int = 140) -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    return text if len(text) <= limit else text[: limit - 3] + "..."


def extract_memory_keywords(text: str, limit: int = 8) -> list[str]:
    tokens = re.findall(r"[a-z0-9]{3,}", (text or "").lower())
    counts = Counter(token for token in tokens if token not in MEMORY_STOPWORDS)
    return [token for token, _ in counts.most_common(limit)]


def summarize_session_messages(messages: list[dict]) -> tuple[str, list[str], str]:
    if not messages:
        return "Conversation just started.", [], ""

    user_messages = [trim_text(m["content"], 120) for m in messages if m["role"] == "user" and m["content"].strip()]
    assistant_messages = [trim_text(m["content"], 120) for m in messages if m["role"] == "jarvis" and m["content"].strip()]
    summary_bits = []
    if user_messages:
        summary_bits.append(f"User asked about {user_messages[0].lower()}")
    if len(user_messages) > 1:
        summary_bits.append(f"Later asked about {user_messages[-1].lower()}")
    elif assistant_messages:
        summary_bits.append(f"Jarvis replied with {assistant_messages[-1].lower()}")

    summary = ". ".join(summary_bits).strip() or "General Jarvis conversation."
    keywords = extract_memory_keywords(" ".join(user_messages))
    preview_source = user_messages[-1] if user_messages else trim_text(messages[-1]["content"], 120)
    return trim_text(summary, 220), keywords, preview_source


def render_markdown_message(message: dict) -> str:
    role_label = "User" if message["role"] == "user" else "Jarvis"
    body = (message["content"] or "").strip() or "(empty)"
    return f"### {role_label} · {message['time']}\n{body}\n"


def write_session_markdown(session: dict):
    summary, keywords, preview = summarize_session_messages(session["messages"])
    path: Path = session["path"]
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "---",
        f"session_id: {session['id']}",
        f"started_at: {session['started_at']}",
        f"updated_at: {session['updated_at']}",
        f"message_count: {len(session['messages'])}",
        f"keywords: {', '.join(keywords)}",
        f"summary: {summary}",
        "---",
        "",
        f"# Conversation {session['started_at'].replace('T', ' ')}",
        "",
        "## Summary",
        summary,
        "",
        "## Preview",
        preview or "No preview yet.",
        "",
        "## Messages",
        "",
    ]
    for message in session["messages"]:
        lines.append(render_markdown_message(message))

    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")

    index = load_conversation_index()
    index["sessions"][session["id"]] = {
        "id": session["id"],
        "path": str(path),
        "date": session["date"],
        "started_at": session["started_at"],
        "updated_at": session["updated_at"],
        "message_count": len(session["messages"]),
        "summary": summary,
        "preview": preview,
        "keywords": keywords,
    }
    save_conversation_index(index)


def create_conversation_session() -> dict:
    migrate_legacy_json_conversations()
    started = datetime.datetime.now()
    date = started.strftime("%Y-%m-%d")
    session_id = f"{date}-{started.strftime('%H%M%S')}-{uuid.uuid4().hex[:6]}"
    day_dir = CONVERSATIONS_DIR / date
    path = day_dir / f"session-{started.strftime('%H%M%S')}-{uuid.uuid4().hex[:4]}.md"
    session = {
        "id": session_id,
        "date": date,
        "started_at": started.isoformat(timespec="seconds"),
        "updated_at": started.isoformat(timespec="seconds"),
        "path": path,
        "messages": [],
    }
    write_session_markdown(session)
    return session


def migrate_legacy_json_conversations():
    global conversation_store_initialized
    if conversation_store_initialized:
        return

    index = load_conversation_index()
    changed = False

    for legacy_file in sorted(CONVERSATIONS_DIR.glob("*.json")):
        legacy_id = f"legacy-{legacy_file.stem}"
        if legacy_id in index["sessions"]:
            continue
        try:
            messages = json.loads(legacy_file.read_text(encoding="utf-8"))
            if not isinstance(messages, list):
                continue
        except Exception:
            continue

        session = {
            "id": legacy_id,
            "date": legacy_file.stem,
            "started_at": f"{legacy_file.stem}T00:00:00",
            "updated_at": f"{legacy_file.stem}T23:59:59",
            "path": CONVERSATIONS_DIR / legacy_file.stem / "legacy-import.md",
            "messages": [
                {
                    "time": str(msg.get("time", "00:00:00")),
                    "role": "jarvis" if str(msg.get("role", "")).lower() == "jarvis" else "user",
                    "content": str(msg.get("content", "")),
                }
                for msg in messages
            ],
        }
        write_session_markdown(session)
        changed = True

    if changed:
        save_conversation_index(load_conversation_index())
    conversation_store_initialized = True


def extract_history_snippet(path: Path, query: str, limit: int = 320) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""

    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("---")]
    query_lower = query.lower().strip()
    keywords = extract_memory_keywords(query, limit=6)
    snippets = []

    for i, line in enumerate(lines):
        lower = line.lower()
        if (query_lower and query_lower in lower) or any(keyword in lower for keyword in keywords):
            start = max(0, i - 1)
            end = min(len(lines), i + 2)
            snippets.append(" ".join(lines[start:end]))
            if len(snippets) >= 2:
                break

    if not snippets:
        snippets = [" ".join(lines[8:16])] if len(lines) > 8 else [" ".join(lines[:8])]

    combined = " | ".join(trim_text(snippet, limit) for snippet in snippets if snippet)
    return trim_text(combined, limit)


def retrieve_relevant_history(query: str, limit: int = MEMORY_RETRIEVAL_LIMIT,
                              char_budget: int = MEMORY_RETRIEVAL_CHAR_BUDGET,
                              exclude_session_id: str | None = None) -> list[str]:
    query = (query or "").strip()
    if not query:
        return []

    migrate_legacy_json_conversations()
    index = load_conversation_index()
    query_lower = query.lower()
    keywords = extract_memory_keywords(query, limit=6)
    if not keywords and len(query_lower) < 5:
        return []
    scored_entries = []

    for entry in index.get("sessions", {}).values():
        if exclude_session_id and entry.get("id") == exclude_session_id:
            continue
        haystack = " ".join([
            str(entry.get("summary", "")),
            str(entry.get("preview", "")),
            " ".join(entry.get("keywords", [])),
        ]).lower()
        score = 0
        if query_lower in haystack:
            score += 120
        for keyword in keywords:
            if keyword in entry.get("keywords", []):
                score += 30
            if keyword in haystack:
                score += 12
        if score <= 0:
            try:
                file_text = Path(entry["path"]).read_text(encoding="utf-8", errors="ignore")[:3000].lower()
            except Exception:
                file_text = ""
            if query_lower and query_lower in file_text:
                score += 80
            else:
                score += sum(10 for keyword in keywords if keyword in file_text)
        if score <= 0:
            continue
        scored_entries.append((score, entry))

    scored_entries.sort(key=lambda item: (item[0], item[1].get("updated_at", "")), reverse=True)

    results = []
    used = 0
    for _, entry in scored_entries[: max(limit * 3, limit)]:
        path = Path(entry["path"])
        snippet = extract_history_snippet(path, query)
        if not snippet:
            continue
        block = f"[{entry.get('date', 'unknown')}] {entry.get('summary', '')}\n{snippet}"
        if used + len(block) > char_budget and results:
            break
        results.append(trim_text(block, 420))
        used += len(block)
        if len(results) >= limit:
            break
    return results


def log_message(role: str, content: str, session: dict | None = None):
    """Append a message to the active markdown conversation log."""
    if session is None:
        return
    session["messages"].append({
        "time": datetime.datetime.now().strftime("%H:%M:%S"),
        "role": role,
        "content": content,
    })
    session["updated_at"] = now_iso()
    write_session_markdown(session)


def search_history(query: str) -> str:
    """Search all past conversations from markdown memory without spending API tokens."""
    try:
        results = retrieve_relevant_history(query, limit=5, char_budget=1800)
    except Exception as e:
        return f"History search failed: {e}"
    return "\n\n".join(results) if results else f"Nothing found in history for '{query}'"


def load_recent_thread(exclude_session_id: str | None = None,
                       max_msgs: int = 4, max_age_hours: int = 3) -> list[dict]:
    """Return the tail of the most recent prior conversation so Jarvis can pick up
    where it left off. Returns [] if the last chat is stale or unreadable."""
    try:
        index = load_conversation_index()
        sessions = [
            e for e in index.get("sessions", {}).values()
            if e.get("id") != exclude_session_id and int(e.get("message_count", 0) or 0) > 0
        ]
        if not sessions:
            return []
        sessions.sort(key=lambda e: e.get("updated_at", ""), reverse=True)
        latest = sessions[0]
        try:
            updated = datetime.datetime.fromisoformat(latest.get("updated_at", ""))
            if (datetime.datetime.now() - updated).total_seconds() > max_age_hours * 3600:
                return []
        except Exception:
            return []
        text = Path(latest["path"]).read_text(encoding="utf-8", errors="ignore")
        msgs = []
        for m in re.finditer(r"^### (User|Jarvis) · .*?\n(.*?)(?=^### |\Z)", text, flags=re.M | re.S):
            role = "user" if m.group(1) == "User" else "assistant"
            body = m.group(2).strip()
            if body and not body.startswith("[BRIEFING]") and body != "(empty)":
                msgs.append({"role": role, "content": trim_text(body, 300)})
        return msgs[-max_msgs:]
    except Exception:
        return []


# ── Memory ─────────────────────────────────────────────────────────────────────

def load_memory() -> dict:
    if MEMORY_FILE.exists():
        try:
            return json.loads(MEMORY_FILE.read_text())
        except Exception:
            pass
    return {"facts": [], "preferences": [], "reminders": []}

def save_memory(mem: dict):
    MEMORY_FILE.write_text(json.dumps(mem, indent=2))


def load_jarvis_lessons() -> dict:
    if JARVIS_LESSONS_FILE.exists():
        try:
            data = json.loads(JARVIS_LESSONS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {"reply_rules": [], "tool_rules": [], "voice_rules": []}

# Patterns that signal learnable preferences/facts in natural speech
# NOTE: keep these tight — only genuine preferences, not passing statements
_LEARN_PATTERNS = [
    re.compile(r"\bi\s+(prefer|like|love|enjoy|hate|dislike)\s+(?!to\s+ask|asking|knowing|wondering)(.{5,80})", re.I),
    re.compile(r"\bmy\s+(favorite|preferred|usual|default)\s+\w+\s+is\s+(.{3,60})", re.I),
    re.compile(r"\b(?:call\s+me|my\s+name\s+is)\s+(\w[\w\s]{1,30})", re.I),
    re.compile(r"\bi\s+(work|study|code|build)\s+(on|in|at|with|as)\s+(.{3,60})", re.I),
    re.compile(r"\balways\s+(use|open|play|start|run)\s+(.{3,60})", re.I),
    re.compile(r"\bnever\s+(use|open|play|start|run)\s+(.{3,60})", re.I),
    re.compile(r"\bdon't\s+(?:ever\s+)?(use|do|play|open|show)\s+(.{3,60})", re.I),
    re.compile(r"\bi\s+(?:go\s+to|study\s+at|work\s+at)\s+(.{3,60})", re.I),
]

# Phrases that look like preferences but aren't — filter these out
_LEARN_BLOCKLIST = re.compile(
    r"^(i'm\s+(saying|asking|working|trying|wondering|thinking|looking|checking|going)|"
    r"i\s+am\s+(asking|saying|working|trying|wondering|thinking|looking|checking))",
    re.I
)

def auto_learn(text: str) -> None:
    """Extract preference signals from user speech and save them automatically."""
    # Skip short or question-like inputs — not preference signals
    if len(text) < 12 or text.strip().endswith("?"):
        return
    if _LEARN_BLOCKLIST.search(text.strip()):
        return
    mem = load_memory()
    existing = set(mem["facts"] + mem["preferences"])
    changed = False
    for pat in _LEARN_PATTERNS:
        for match in pat.finditer(text):
            fact = match.group(0).strip().rstrip(".,!?")
            if len(fact) > 12 and fact.lower() not in {e.lower() for e in existing}:
                mem["preferences"].append(fact)
                existing.add(fact.lower())
                changed = True
                safe_print(f"[Auto-learned] {fact}")
    if changed:
        save_memory(mem)


# ── Project scanner ────────────────────────────────────────────────────────────

def detect_tech(children: list) -> str:
    tags = []
    if "package.json" in children:   tags.append("Node/JS")
    if "requirements.txt" in children or any(f.endswith('.py') for f in children): tags.append("Python")
    if "pom.xml" in children:         tags.append("Java")
    if "Cargo.toml" in children:      tags.append("Rust")
    if "go.mod" in children:          tags.append("Go")
    if any(f.endswith('.html') for f in children): tags.append("HTML")
    if ".git" in children:            tags.append("git")
    return ", ".join(tags) if tags else "misc"


def get_project_mtime(path: Path) -> float:
    """Latest modification time among key files in a project."""
    key_files = ['README.md', 'package.json', 'requirements.txt', 'main.py', 'server.py', 'index.js']
    times = [path.stat().st_mtime]
    for f in key_files:
        fp = path / f
        if fp.exists():
            times.append(fp.stat().st_mtime)
    return max(times)


def build_project_summary(path: Path, children: list) -> str:
    """Build a 2-3 line summary of a project by reading key files (done once, then cached)."""
    tech = detect_tech(children)
    parts = [f"Tech: {tech}", f"Files: {', '.join(sorted(children)[:15])}"]

    for key_file in ['README.md', 'CLAUDE.md', 'package.json']:
        fp = path / key_file
        if fp.exists():
            try:
                content = fp.read_text(encoding="utf-8", errors="ignore")
                if key_file == 'package.json':
                    pkg = json.loads(content)
                    desc = pkg.get("description", "")
                    if desc:
                        parts.append(f"Description: {desc}")
                else:
                    first_lines = "\n".join(content.splitlines()[:5]).strip()
                    if first_lines:
                        parts.append(f"{key_file}: {first_lines}")
                break
            except Exception:
                pass
    return " | ".join(parts)


def load_summaries() -> dict:
    if SUMMARIES_FILE.exists():
        try:
            return json.loads(SUMMARIES_FILE.read_text())
        except Exception:
            pass
    return {}


def get_project_list() -> str:
    """Return a COMPACT project list for the system prompt. Uses cache — no file reading per request."""
    summaries = load_summaries()
    updated = False
    lines = []

    for root in PROJECT_ROOTS:
        if not root.exists():
            continue
        try:
            for item in sorted(root.iterdir()):
                if not item.is_dir() or item.name.startswith('.'):
                    continue
                if item.name in ('node_modules', '__pycache__', 'venv', '.git', 'logs'):
                    continue
                try:
                    children = [f.name for f in item.iterdir() if not f.name.startswith('.')]
                except Exception:
                    children = []

                key = str(item)
                mtime = get_project_mtime(item)

                # Regenerate summary only if project changed or not cached
                if key not in summaries or summaries[key].get("mtime", 0) < mtime:
                    summary = build_project_summary(item, children)
                    summaries[key] = {"mtime": mtime, "summary": summary}
                    updated = True

                lines.append(f"• {item.name} ({item}) — {summaries[key]['summary']}")
        except Exception:
            pass

    if updated:
        SUMMARIES_FILE.write_text(json.dumps(summaries, indent=2))

    return "\n".join(lines) if lines else "No projects found."


# ── System prompt ──────────────────────────────────────────────────────────────

_wiki_pages_cache: list[tuple[str, str]] | None = None
_wiki_cache_ts: float = 0.0
_WIKI_CACHE_TTL = 300  # seconds — pick up ingest.py wiki updates without a restart


def _wiki_source_dirs() -> list[Path]:
    dirs = [WIKI_DIR]
    if SECOND_BRAIN_WIKI_DIR and SECOND_BRAIN_WIKI_DIR.exists():
        dirs.append(SECOND_BRAIN_WIKI_DIR)
    return dirs


def load_wiki_pages() -> list[tuple[str, str]]:
    """Read curated wiki pages (cached with TTL). Raw/inbox notes stay out of prompt memory."""
    global _wiki_pages_cache, _wiki_cache_ts
    if _wiki_pages_cache is not None and time.time() - _wiki_cache_ts < _WIKI_CACHE_TTL:
        return _wiki_pages_cache

    pages: list[tuple[str, str]] = []
    seen: set[Path] = set()
    for wiki_dir in _wiki_source_dirs():
        if not wiki_dir.exists():
            continue
        for md_file in sorted(wiki_dir.rglob("*.md")):
            lower_parts = {part.lower() for part in md_file.parts}
            if {"raw", "inbox"} & lower_parts:
                continue
            try:
                resolved = md_file.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                title = md_file.relative_to(wiki_dir).as_posix()
                text = md_file.read_text(encoding="utf-8", errors="replace").strip()
                if text:
                    pages.append((title, text))
            except Exception:
                pass

    _wiki_pages_cache = pages
    _wiki_cache_ts = time.time()
    return pages


def load_wiki_context(query: str = "") -> str:
    """Return a compact, query-relevant slice of curated wiki context."""
    pages = load_wiki_pages()
    if not pages:
        return ""
    user_words = {w for w in re.findall(r"[a-z0-9][a-z0-9_-]{3,}", query.lower())}
    scored: list[tuple[int, str, str]] = []
    for title, text in pages:
        haystack = f"{title}\n{text}".lower()
        page_words = set(re.findall(r"[a-z0-9][a-z0-9_-]{3,}", haystack))
        score = len(user_words & page_words)
        if score:
            scored.append((score, title, text))

    if not scored and re.search(r"\b(projects?|wiki|second\s*brain|jarvis|kerala|vase|spray|portfolio)\b", query.lower()):
        scored = [(1, title, text) for title, text in pages if title in {"index.md", "home.md", "projects.md"}]
    if not scored:
        return ""
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)

    parts = []
    budget = PROMPT_WIKI_CHARS
    for _, title, text in scored[:4]:
        chunk = f"[{title}]\n{text}"
        if len(chunk) > max(200, budget):
            chunk = chunk[:max(200, budget)].rstrip()
        parts.append(chunk)
        budget -= len(chunk)
        if budget <= 0:
            break
    return "\n\n---\n\n".join(parts)[:PROMPT_WIKI_CHARS]


def reload_wiki():
    global _wiki_pages_cache
    _wiki_pages_cache = None

_PERSONALITY = (
    "You are J.A.R.V.I.S.: Tony Stark's AI majordomo — unflappable, razor-sharp, quietly loyal.\n"
    "VOICE INTERFACE: You are a voice assistant. You HEAR the user through a microphone (speech-to-text) "
    "and reply OUT LOUD (text-to-speech). You can hear them right now. Never claim you can only read text "
    "or that you cannot hear.\n"
    "ADDRESS: Always address the user as \"sir\" — never \"dude\", \"bro\", \"man\", or by first name, "
    "regardless of any note or memory suggesting otherwise.\n"
    "TONE: Refined British butler. Dry, understated wit. Anticipate the next need and say it. Confident, "
    "never servile; gently push back when he's about to do something unwise. Spoken aloud, so: no markdown, "
    "no lists, no emoji.\n"
    "LENGTH: Default 1-3 crisp sentences. Go longer only when the task truly needs it (briefings, "
    "explanations he asked to unpack). Never pad.\n"
)

# Memory lines about how to address the user — filtered out so the persona's
# fixed "sir" always wins (prevents the dude/bro/sir contradiction war).
_ADDRESS_MEMORY_RE = re.compile(
    r"\b(dude|bro)\b|\bcall me\b|\brefer to (me|the user|user)\b|"
    r"address(ed)?\s+(me|the user|him|as)\b|\bas \"?(sir|dude|bro)\"?",
    re.I,
)

_RULES = """RULES:
- Greetings/small talk → direct reply, NO tools.
- Only use a tool when explicitly requested.
- News/facts/current events → <<SEARCH:>> always, never from memory.
- "FAU/college/university" mail may be fau.de or fau.edu. "screen" = JARVIS display.
- After tool result → 1-3 sentences, never read raw output verbatim.
- <<REMEMBER:>> whenever you learn a preference, fact, or correction.\n"""

_TOOL_HEADER = "TOOLS available for this request:\n"

_RULES += "IMPORTANT: Never claim you saved, noted, or remembered something unless the REMEMBER tool actually ran.\n"
_RULES += "IMPORTANT: When summarising mail/calendar results, only report data that was actually returned by the tool. Never invent, guess, or fabricate sender names, subjects, or content. If fewer mails loaded than expected, say so — do not fill gaps with made-up data.\n"
_RULES += "LANGUAGE: Always respond in English only. Never respond in any other language, regardless of what language the user speaks or writes in.\n"

_WEB_TOOLS = """<<SEARCH: q>> current facts/news
<<BROWSE: url>> read webpage
<<OPEN_URL: url>> open browser URL\n"""

_APP_TOOLS = "<<OPEN_APP: name>> launch app\n"
_MEMORY_TOOLS = "<<REMEMBER: fact>> save preference/fact\n<<HISTORY: q>> search past chats\n"

_MEDIA_TOOLS = "<<PLAY_YOUTUBE: q>>  open YouTube\n<<YOUTUBE_CONTROL: action>>  pause/resume/mute/seek\n"

_FILE_TOOLS = """<<RUN: cmd>>  shell command
<<READ_FILE: path>>  read file
<<LIST_DIR: path>>  list folder
<<FIND_FILES: pattern in path>>
<<WRITE_FILE: {"path":"...","content":"..."}>>
<<BUILD: {"project_name":"...","files":[...]}>>
<<REMIND: text>>  set reminder\n"""

_GMAIL_TOOLS = """<<GMAIL_CHECK>>  unread inbox
<<GMAIL_READ: id>>  full mail body
<<GMAIL_SEARCH: q>>  search Gmail
<<GMAIL_DRAFT: id:body>>  stage reply (confirm before sending)
<<GMAIL_SCREEN>>  inbox on screen
<<GMAIL_SEARCH_SCREEN: q>>  search+screen
<<PITCH_MAIL: id>>  one mail on screen\n"""

_CALENDAR_TOOLS = """<<CALENDAR_CHECK>>  upcoming events
<<CALENDAR_DATE: today/tomorrow/YYYY-MM-DD>>
<<CALENDAR_ADD: title|YYYY-MM-DD|HH:MM|mins|location>>
<<CALENDAR_SCREEN>>  week on screen
<<CALENDAR_TODAY>>  today on screen
<<CALENDAR_TOMORROW>>  tomorrow on screen\n"""

_MISC_TOOLS = "<<MAPS: origin|dest>>  directions on screen\n<<CLOSE_SCREEN>>  dismiss screen\n<<OBSIDIAN: q>>  search notes\n"

_VISION_TOOLS = "<<SEE_SCREEN: question>>  look at the user's actual screen and answer\n"
_DEVICE_TOOLS = "<<CONTROL: action>>  volume up/down/mute, play/pause, next/previous, lock, sleep\n"

# Keyword sets for conditional tool injection
_WEB_KW      = {"search", "browse", "web", "website", "internet", "online", "latest", "today", "news", "current", "recent", "look up", "google"}
_VISION_KW   = {"screen", "looking at", "see this", "what do you see", "on my display", "look at"}
_DEVICE_KW   = {"volume", "louder", "quieter", "mute", "unmute", "lock", "sleep", "hibernate", "pause", "play", "next track", "previous track", "brightness"}
_APP_KW      = {"open", "launch", "start", "app", "application", "program"}
_MEMORY_KW   = {"remember", "recall", "history", "before", "previously", "i told you", "you said", "forget"}
_MEDIA_KW    = {"youtube", "play", "video", "music", "song", "watch", "pause", "resume", "mute", "fullscreen", "seek"}
_FILE_KW     = {"file", "folder", "run", "execute", "read", "write", "create", "list", "find", "build", "script", "remind", "reminder"}
_GMAIL_KW    = {"mail", "mails", "email", "emails", "gmail", "gmails", "mailbox", "inbox", "message", "sender", "fau", "college", "draft", "reply", "unread", "males", "mains"}
_CALENDAR_KW = {"calendar", "schedule", "event", "meeting", "appointment"}
_MISC_KW     = {"map", "direction", "route", "note", "obsidian", "close", "screen", "dismiss"}

# Project list cache — refresh every 5 minutes, not every message
_project_list_cache: dict = {"text": "", "ts": 0.0}
_PROJECT_LIST_TTL = 300  # seconds

def get_project_list_cached() -> str:
    now = time.time()
    if now - _project_list_cache["ts"] < _PROJECT_LIST_TTL and _project_list_cache["text"]:
        return _project_list_cache["text"]
    text = get_project_list()
    _project_list_cache["text"] = text
    _project_list_cache["ts"] = now
    return text


_HISTORY_TRIGGERS = {"remember", "recall", "last time", "did i", "did we", "history", "before", "previously", "you said", "i told you"}
_PROJECT_TRIGGERS = {"project", "projects", "code", "build", "kerala", "vase", "yolo", "flutter", "agent", "visuali", "webpage", "openvc"}

def build_system_prompt(current_user_text: str = "", session_id: str | None = None) -> str:
    mem = load_memory()
    lessons = load_jarvis_lessons()
    now = datetime.datetime.now().strftime("%A, %B %d %Y — %I:%M %p")
    user_lower = current_user_text.lower()

    # Projects list — only inject when user is explicitly asking about projects/code
    projects_block = ""
    if current_user_text and any(kw in user_lower for kw in _PROJECT_TRIGGERS):
        projects_block = f"\nProjects: {get_project_list_cached()}"

    # Relevant history — only retrieve when user is asking about past conversations
    history_block = ""
    if any(kw in user_lower for kw in _HISTORY_TRIGGERS):
        relevant_history = retrieve_relevant_history(
            current_user_text,
            limit=MEMORY_RETRIEVAL_LIMIT,
            char_budget=MEMORY_RETRIEVAL_CHAR_BUDGET,
            exclude_session_id=session_id,
        )
        if relevant_history:
            history_block = "\nRelevant memory from past conversations:\n"
            for item in relevant_history:
                history_block += f"  - {item}\n"

    # Keep memory useful but small; long memories are expensive every turn.
    memory_block = ""
    # Most recent N — new facts/preferences must surface, not the oldest ones.
    # Drop address-term instructions: the persona owns how to address the user,
    # so a stray "call me bro" memory can never override the fixed "sir".
    clean_facts = [f for f in mem["facts"] if not _ADDRESS_MEMORY_RE.search(f)]
    clean_prefs = [p for p in mem["preferences"] if not _ADDRESS_MEMORY_RE.search(p)]
    # Identity (the user's name) must always surface, even if it's an old fact;
    # fill the remaining slots with the most recent facts.
    identity = [f for f in clean_facts if re.search(r"\bname\b", f, re.I)]
    other_facts = [f for f in clean_facts if f not in identity]
    facts = (identity[-1:] + other_facts[-PROMPT_MEMORY_FACTS:]) if identity else other_facts[-PROMPT_MEMORY_FACTS:]
    prefs = clean_prefs[-PROMPT_MEMORY_PREFS:]
    if facts or prefs:
        memory_block = "\nUser: " + "; ".join(facts + prefs) + "\n"
    if mem["reminders"]:
        memory_block += "Reminders: " + "; ".join(mem["reminders"][-3:]) + "\n"

    lessons_block = ""
    learned_rules = []
    for key in ("reply_rules", "tool_rules", "voice_rules"):
        values = lessons.get(key, [])
        if isinstance(values, list):
            learned_rules.extend(str(value) for value in values[-1:])
    if learned_rules:
        lessons_block = "\nLearned Jarvis fixes: " + "; ".join(learned_rules[:3]) + "\n"

    # Wiki — only inject the pages that match this request.
    wiki_block = ""
    if current_user_text:
        wiki_context = load_wiki_context(current_user_text)
        if wiki_context:
            wiki_block = f"\nContext: {wiki_context}\n"

    # Conditional tool injection — only include groups relevant to this request
    tools = ""
    if any(kw in user_lower for kw in _WEB_KW):
        tools += _WEB_TOOLS
    if any(kw in user_lower for kw in _APP_KW):
        tools += _APP_TOOLS
    if any(kw in user_lower for kw in _MEMORY_KW):
        tools += _MEMORY_TOOLS
    if not current_user_text or any(kw in user_lower for kw in _MEDIA_KW):
        tools += _MEDIA_TOOLS
    if not current_user_text or any(kw in user_lower for kw in _FILE_KW):
        tools += _FILE_TOOLS
    if any(kw in user_lower for kw in _GMAIL_KW):
        tools += _GMAIL_TOOLS
    if any(kw in user_lower for kw in _CALENDAR_KW):
        tools += _CALENDAR_TOOLS
    if any(kw in user_lower for kw in _MISC_KW):
        tools += _MISC_TOOLS
    if any(kw in user_lower for kw in _VISION_KW):
        tools += _VISION_TOOLS
    if any(kw in user_lower for kw in _DEVICE_KW):
        tools += _DEVICE_TOOLS
    if tools:
        tools = _TOOL_HEADER + tools

    return (
        f"You are J.A.R.V.I.S. — Tony Stark's assistant. Sharp, British, brief.\n"
        f"Now: {now} | Brain: {ACTIVE_MODEL}\n"
        f"{memory_block}{history_block}{lessons_block}{wiki_block}{projects_block}\n"
        + _PERSONALITY + tools + _RULES
    )


# ── Tools ──────────────────────────────────────────────────────────────────────

YOUTUBE_URL_HINTS = (
    "youtube.com/watch",
    "youtube.com/shorts/",
    "youtube.com/live/",
    "youtu.be/",
)
GENERIC_YOUTUBE_QUERY_WORDS = {
    "latest", "new", "newest", "recent", "episode", "video", "videos", "song", "songs",
    "music", "trailer", "clip", "clips", "official", "full", "watch", "play", "open",
    "youtube", "you", "tube", "on", "the", "a", "an",
}
AUTOMATION_BROWSER_PORT = int(os.getenv("AUTOMATION_BROWSER_PORT", "9222"))
AUTOMATION_BROWSER_DIR = RUNTIME_DIR / "chrome-automation"
AUTOMATION_BROWSER_BASE = f"http://127.0.0.1:{AUTOMATION_BROWSER_PORT}"
AUTOMATION_BROWSER_VERSION = f"{AUTOMATION_BROWSER_BASE}/json/version"
AUTOMATION_BROWSER_TARGETS = f"{AUTOMATION_BROWSER_BASE}/json/list"
YOUTUBE_CONTROL_SHORT_WORDS = {"pause", "resume", "continue", "stop", "mute", "unmute", "fullscreen"}


def web_search_results(query: str, max_results: int = 5) -> list[dict]:
    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=max_results))


def is_youtube_url(url: str) -> bool:
    url = (url or "").lower()
    return any(hint in url for hint in YOUTUBE_URL_HINTS)


def clean_youtube_query(query: str) -> str:
    cleaned = query.strip()
    cleaned = re.sub(r'(?i)\b(jarvis|please|can you|could you|would you)\b', ' ', cleaned)
    cleaned = re.sub(r'(?i)\b(open|play|watch|find|search(?: for)?|launch|start)\b', ' ', cleaned)
    cleaned = re.sub(r'(?i)\b(on|in|from|at)\b', ' ', cleaned)
    cleaned = re.sub(r'(?i)\b(you\s*tube|youtube|youtue|youtu)\b', ' ', cleaned)
    cleaned = re.sub(r'(?i)\bvideo\b', ' ', cleaned)
    cleaned = re.sub(r'(?i)\band\b', ' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip(" .?!,")
    return cleaned or query.strip()


def extract_youtube_query_keywords(query: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", query.lower())
    keywords = [word for word in words if word not in GENERIC_YOUTUBE_QUERY_WORDS and len(word) > 1]
    return keywords[:6]


def build_youtube_search_text(query: str) -> str:
    keywords = extract_youtube_query_keywords(query)
    if not keywords:
        return query
    if any(word in query.lower() for word in ("latest", "new", "newest", "recent")):
        return f"{' '.join(keywords)} official latest"
    return f"{query} official"


def find_youtube_video_url(query: str) -> str | None:
    candidates = [
        f"site:youtube.com/watch {query}",
        f"site:youtu.be {query}",
        f"YouTube {query}",
    ]
    for candidate in candidates:
        try:
            results = web_search_results(candidate, max_results=8)
        except Exception:
            continue
        for result in results:
            url = result.get("href", "")
            if is_youtube_url(url):
                return url
    return None


def launch_automation_browser(start_url: str = "about:blank") -> None:
    AUTOMATION_BROWSER_DIR.mkdir(exist_ok=True)
    args = [
        "chrome",
        f"--remote-debugging-port={AUTOMATION_BROWSER_PORT}",
        f"--user-data-dir={AUTOMATION_BROWSER_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        start_url,
    ]
    creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    subprocess.Popen(args, creationflags=creationflags)


async def browser_is_ready() -> bool:
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            resp = await client.get(AUTOMATION_BROWSER_VERSION)
        return resp.is_success
    except Exception:
        return False


async def ensure_automation_browser() -> None:
    if await browser_is_ready():
        return
    launch_automation_browser()
    for _ in range(24):
        if await browser_is_ready():
            return
        await asyncio.sleep(0.25)
    raise RuntimeError("Chrome automation browser did not start in time.")


async def get_automation_targets() -> list[dict]:
    await ensure_automation_browser()
    async with httpx.AsyncClient(timeout=2.0) as client:
        resp = await client.get(AUTOMATION_BROWSER_TARGETS)
        resp.raise_for_status()
    targets = resp.json()
    return [
        target for target in targets
        if target.get("type") == "page" and not str(target.get("url", "")).startswith("devtools://")
    ]


async def get_best_automation_target(prefer_youtube: bool = False) -> dict:
    targets = await get_automation_targets()
    youtube_targets = [
        target for target in targets
        if is_youtube_url(str(target.get("url", ""))) or "youtube.com" in str(target.get("url", "")).lower()
    ]
    if prefer_youtube and youtube_targets:
        return youtube_targets[-1]
    if targets:
        return targets[-1]
    launch_automation_browser()
    await asyncio.sleep(0.8)
    targets = await get_automation_targets()
    if targets:
        return targets[-1]
    raise RuntimeError("No browser page target available for automation.")


async def send_cdp_command(target: dict, method: str, params: dict | None = None) -> dict:
    ws_url = target.get("webSocketDebuggerUrl")
    if not ws_url:
        raise RuntimeError("Chrome target is missing a debugger websocket.")

    message_id = int(datetime.datetime.now().timestamp() * 1000)
    payload = {"id": message_id, "method": method, "params": params or {}}

    async with websockets.connect(ws_url, open_timeout=4, close_timeout=4) as websocket:
        await websocket.send(json.dumps(payload))
        while True:
            raw = await websocket.recv()
            response = json.loads(raw)
            if response.get("id") != message_id:
                continue
            if response.get("error"):
                message = response["error"].get("message", "Unknown CDP error")
                raise RuntimeError(message)
            return response.get("result", {})


async def evaluate_target(target: dict, expression: str) -> dict | str | None:
    result = await send_cdp_command(
        target,
        "Runtime.evaluate",
        {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        },
    )
    return result.get("result", {}).get("value")


async def focus_target(target: dict) -> None:
    await send_cdp_command(target, "Page.bringToFront")


async def navigate_target(target: dict, url: str) -> None:
    await send_cdp_command(target, "Page.navigate", {"url": url})
    await focus_target(target)


async def get_active_youtube_target() -> dict | None:
    try:
        targets = await get_automation_targets()
    except Exception:
        return None
    youtube_targets = [
        target for target in targets
        if is_youtube_url(str(target.get("url", ""))) or "youtube.com" in str(target.get("url", "")).lower()
    ]
    return youtube_targets[-1] if youtube_targets else None


def with_youtube_autoplay(url: str) -> str:
    if not url:
        return url
    separator = "&" if "?" in url else "?"
    if "autoplay=" in url:
        return url
    return f"{url}{separator}autoplay=1"


async def get_best_youtube_result_url(target: dict, query: str, attempts: int = 10, delay: float = 0.45) -> str | None:
    query_text = query.lower()
    keywords = extract_youtube_query_keywords(query)
    expression = f"""(() => {{
const query = {json.dumps(query_text)};
const keywords = {json.dumps(keywords)};
const normalize = (value) => (value || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
const containers = Array.from(document.querySelectorAll('ytd-video-renderer, ytd-rich-item-renderer, ytd-grid-video-renderer'));
const scored = containers.map((container) => {{
  const titleEl = container.querySelector('a#video-title, h3 a, a#thumbnail[href*="/watch"]');
  const channelEl = container.querySelector('ytd-channel-name a, #channel-name a, ytd-channel-name');
  const badgeEls = Array.from(container.querySelectorAll('ytd-badge-supported-renderer, #badges, .badge')).map((el) => el.textContent || '');
  const metaEls = Array.from(container.querySelectorAll('#metadata-line span, #metadata span')).map((el) => el.textContent || '');
  const href = titleEl?.href || titleEl?.getAttribute?.('href') || '';
  const title = normalize(titleEl?.textContent || '');
  const channel = normalize(channelEl?.textContent || '');
  const badges = normalize(badgeEls.join(' '));
  const meta = normalize(metaEls.join(' '));
  if (!href || !href.includes('/watch')) return null;

  let score = 0;
  if (title.includes(query)) score += 60;
  if (channel.includes(query)) score += 90;

  for (const keyword of keywords) {{
    if (title.includes(keyword)) score += 14;
    if (channel.includes(keyword)) score += 28;
    if (badges.includes(keyword)) score += 6;
  }}

  if (badges.includes('verified')) score += 6;
  if (title.includes('official')) score += 8;
  if (channel.includes('official')) score += 10;
  if (meta.includes('live') || title.includes('live')) score -= 25;
  if (href.includes('/shorts/')) score -= 20;
  if (channel.includes('topic')) score -= 8;
  if (channel.includes('fan') || channel.includes('clips') || channel.includes('edit')) score -= 14;

  return {{ score, href, title, channel }};
}}).filter(Boolean).sort((a, b) => b.score - a.score);

if (!scored.length) {{
  return {{ ok:false, reason:'no-results', title:document.title, url:location.href }};
}}

const best = scored[0];
return {{ ok:true, href:best.href, score:best.score, channel:best.channel }};
}})()"""
    for _ in range(attempts):
        result = await evaluate_target(target, expression)
        if isinstance(result, dict) and result.get("ok"):
            href = str(result.get("href", "")).strip()
            if href:
                return href
        await asyncio.sleep(delay)
    return None


async def ensure_current_video_playing(target: dict, attempts: int = 12, delay: float = 0.4) -> bool:
    expression = """(() => {
const video = document.querySelector('video');
if (!video) return {ok:false, reason:'no-video', title:document.title};
const playButton = document.querySelector('.ytp-large-play-button, .ytp-play-button');
if (video.paused && playButton) playButton.click();
return Promise.resolve(video.play?.()).then(() => ({
  ok:true,
  paused:video.paused,
  currentTime:video.currentTime,
  title:document.title
})).catch(err => ({
  ok:false,
  reason:String(err),
  title:document.title
}));
})()"""
    for _ in range(attempts):
        result = await evaluate_target(target, expression)
        if isinstance(result, dict) and result.get("ok"):
            return True
        await asyncio.sleep(delay)
    return False


def normalize_youtube_control(raw: str) -> str | None:
    text = raw.lower().strip()
    if "unmute" in text:
        return "unmute"
    if "mute" in text:
        return "mute"
    if any(word in text for word in ("resume", "continue", "unpause")):
        return "resume"
    if "pause" in text or "stop" in text:
        return "pause"
    if re.search(r"\bplay\b", text):
        return "play"
    if "captions" in text or "caption" in text or "subtitles" in text or "subtitle" in text:
        return "captions"
    if "theater" in text or "cinema mode" in text:
        return "theater"
    if "fullscreen" in text or "full screen" in text:
        return "fullscreen"
    if "volume up" in text or "louder" in text or "increase volume" in text:
        return "volume_up"
    if "volume down" in text or "quieter" in text or "decrease volume" in text:
        return "volume_down"
    if "rewind" in text or "seek back" in text or "skip back" in text or "back 10" in text:
        return "seek_back"
    if "seek forward" in text or "skip ahead" in text or "skip forward" in text or "forward 10" in text:
        return "seek_forward"
    if "next video" in text or text == "next":
        return "next"
    if "previous video" in text or text == "previous":
        return "previous"
    return None


def youtube_control_script(action: str) -> str:
    script_body = {
        "play": """
const video = document.querySelector('video');
if (!video) return {ok:false, error:'No active YouTube video found.'};
return Promise.resolve(video.play?.()).then(() => ({
  ok:true, action:'play', title:document.title, paused:video.paused, muted:video.muted
})).catch(err => ({ok:false, error:String(err), title:document.title}));
""",
        "resume": """
const video = document.querySelector('video');
if (!video) return {ok:false, error:'No active YouTube video found.'};
return Promise.resolve(video.play?.()).then(() => ({
  ok:true, action:'resume', title:document.title, paused:video.paused, muted:video.muted
})).catch(err => ({ok:false, error:String(err), title:document.title}));
""",
        "pause": """
const video = document.querySelector('video');
if (!video) return {ok:false, error:'No active YouTube video found.'};
video.pause();
return {ok:true, action:'pause', title:document.title, paused:video.paused, muted:video.muted};
""",
        "mute": """
const video = document.querySelector('video');
if (!video) return {ok:false, error:'No active YouTube video found.'};
video.muted = true;
return {ok:true, action:'mute', title:document.title, paused:video.paused, muted:video.muted};
""",
        "unmute": """
const video = document.querySelector('video');
if (!video) return {ok:false, error:'No active YouTube video found.'};
video.muted = false;
return {ok:true, action:'unmute', title:document.title, paused:video.paused, muted:video.muted};
""",
        "seek_forward": """
const video = document.querySelector('video');
if (!video) return {ok:false, error:'No active YouTube video found.'};
video.currentTime = Math.min(video.duration || Number.MAX_SAFE_INTEGER, video.currentTime + 10);
return {ok:true, action:'seek_forward', title:document.title, currentTime:video.currentTime};
""",
        "seek_back": """
const video = document.querySelector('video');
if (!video) return {ok:false, error:'No active YouTube video found.'};
video.currentTime = Math.max(0, video.currentTime - 10);
return {ok:true, action:'seek_back', title:document.title, currentTime:video.currentTime};
""",
        "volume_up": """
const video = document.querySelector('video');
if (!video) return {ok:false, error:'No active YouTube video found.'};
video.volume = Math.min(1, video.volume + 0.1);
video.muted = false;
return {ok:true, action:'volume_up', title:document.title, volume:video.volume};
""",
        "volume_down": """
const video = document.querySelector('video');
if (!video) return {ok:false, error:'No active YouTube video found.'};
video.volume = Math.max(0, video.volume - 0.1);
return {ok:true, action:'volume_down', title:document.title, volume:video.volume};
""",
        "captions": """
const button = document.querySelector('.ytp-subtitles-button');
if (!button) return {ok:false, error:'Caption control not found on this page.'};
button.click();
return {ok:true, action:'captions', title:document.title};
""",
        "theater": """
const button = document.querySelector('.ytp-size-button');
if (!button) return {ok:false, error:'Theater mode control not found on this page.'};
button.click();
return {ok:true, action:'theater', title:document.title};
""",
        "fullscreen": """
const button = document.querySelector('.ytp-fullscreen-button');
if (!button) return {ok:false, error:'Fullscreen control not found on this page.'};
button.click();
return {ok:true, action:'fullscreen', title:document.title};
""",
        "next": """
const button = document.querySelector('.ytp-next-button');
if (!button) return {ok:false, error:'Next video button is not available.'};
button.click();
return {ok:true, action:'next', title:document.title};
""",
        "previous": """
const button = document.querySelector('.ytp-prev-button');
if (!button) return {ok:false, error:'Previous video button is not available.'};
button.click();
return {ok:true, action:'previous', title:document.title};
""",
    }.get(action)

    if not script_body:
        raise RuntimeError(f"Unsupported YouTube control action: {action}")

    return f"(() => {{ {script_body} }})()"


async def play_youtube(query: str) -> str:
    cleaned_query = clean_youtube_query(query)
    target = await get_best_automation_target(prefer_youtube=True)

    # Use a web search to find a direct video URL first, then keep it in the
    # automation browser so later pause/play/mute commands target the same tab.
    video_url = find_youtube_video_url(cleaned_query)
    if video_url:
        await navigate_target(target, with_youtube_autoplay(video_url))
        await asyncio.sleep(1.2)
        await ensure_current_video_playing(target)
        return f"Opening and playing the best YouTube result for '{cleaned_query}'."

    # Fall back to YouTube search results, pick the best visible video, then play it.
    search_text = build_youtube_search_text(cleaned_query)
    search_url = f"https://www.youtube.com/results?search_query={quote_plus(search_text)}"
    await navigate_target(target, search_url)
    best_url = await get_best_youtube_result_url(target, cleaned_query)
    if best_url:
        await navigate_target(target, with_youtube_autoplay(best_url))
        await asyncio.sleep(1.2)
        await ensure_current_video_playing(target)
        return f"Opening and playing the best YouTube result for '{cleaned_query}'."
    return f"Opened YouTube search results for '{cleaned_query}', but I could not select a video automatically."


async def youtube_control(action_raw: str) -> str:
    action = normalize_youtube_control(action_raw)
    if not action:
        return f"I couldn't map '{action_raw}' to a YouTube control."

    target = await get_active_youtube_target()
    if not target:
        return "No active YouTube tab is open in the automation browser."

    await focus_target(target)
    await asyncio.sleep(0.15)
    result = await evaluate_target(target, youtube_control_script(action))
    if isinstance(result, dict):
        if result.get("ok"):
            return f"YouTube {action.replace('_', ' ')} applied."
        return result.get("error", f"YouTube {action.replace('_', ' ')} failed.")
    return f"YouTube {action.replace('_', ' ')} applied."


def detect_direct_youtube_request(text: str) -> str | None:
    lowered = text.lower()
    if not any(term in lowered for term in ("youtube", "you tube", "youtue", "youtu")):
        return None
    if not any(word in lowered for word in ("play", "watch", "open", "find", "search")):
        return None
    return clean_youtube_query(text)


async def detect_direct_youtube_control(text: str) -> str | None:
    action = normalize_youtube_control(text)
    if not action:
        return None

    lowered = text.lower()
    if any(term in lowered for term in ("youtube", "you tube", "youtue", "youtu", "video", "episode", "song", "music")):
        return action

    words = re.findall(r"[a-zA-Z]+", lowered)
    if action in YOUTUBE_CONTROL_SHORT_WORDS and len(words) <= 3 and await get_active_youtube_target():
        return action

    return None


# Remembers what topic was last discussed so "show it on screen" resolves correctly
_last_topic: str = "inbox"   # "calendar" | "inbox" | "college"


def detect_direct_screen_request(text: str) -> str | None:
    """
    Detect commands to pitch content to the screen.
    Returns an action key: 'inbox', 'college', 'close', 'calendar_today',
    'calendar_tomorrow', 'calendar', or 'sender:<name>'
    Handles mangled speech: pitch/pit/beat/which/put + screen/skreen/scream etc.
    """
    global _last_topic
    t = text.lower().strip()

    # Fuzzy match for "screen"
    has_screen = bool(re.search(r"\b(screen|scream|skreen|stream|the scr|to scr)\b", t))
    # Fuzzy match for pitch verbs
    has_pitch  = bool(re.search(r"\b(pitch|pit\b|put|show|display|see|view|open|beam|beat\b|bit\b|which\b|bring|push|send)\b", t))
    # Mail-related words
    has_mail   = bool(re.search(r"\b(mail|mails|male|males|main|mains|email|emails|gmail|gmails|mailbox|inbox|messages?)\b", t))
    # Calendar words
    has_cal    = bool(re.search(r"\b(calendar|schedule|events?|agenda|appointments?)\b", t))
    # Close/dismiss
    has_close  = bool(re.search(r"\b(close|clear|dismiss|remove|hide|take.?off|shut|exit)\b", t))
    # Map/directions — always let LLM handle (needs origin+destination)
    has_map    = bool(re.search(r"\b(direction|directions|route|navigate|map|maps|way to|how to get)\b", t))
    # Vague pronoun — "show it on screen"
    vague      = bool(re.search(r"\b(it|this|that|them)\b", t))

    # Close screen
    if has_close and (has_screen or has_cal or has_mail):
        return "close"

    # Maps — never intercept, let LLM parse origin|destination
    if has_map:
        return None

    # Calendar — requires BOTH screen AND a pitch verb to bypass LLM
    if has_cal:
        _last_topic = "calendar"
        if has_screen and has_pitch:
            if re.search(r"\b(tomorrow|tmr)\b", t):
                return "calendar_tomorrow"
            if re.search(r"\b(today|now)\b", t):
                return "calendar_today"
            return "calendar"
        # "check my calendar" / "what's on my schedule" → let LLM speak it
        return None

    # "show it/this/that on screen" → replay last topic
    if has_screen and vague and not has_mail:
        return _last_topic

    if has_pitch and has_mail and vague:
        return "mail_context"

    # Everything else needs screen + (pitch verb or mail word)
    if not (has_screen and (has_pitch or has_mail)):
        return None

    # "show [unknown thing] on screen" with no mail keyword → let LLM handle
    if not has_mail:
        return None

    # Mail on screen
    _last_topic = "inbox"

    # "college" / "university" / "fau" → search fau.edu
    if re.search(r"\b(college|university|fau|uni\b|school)\b", t):
        _last_topic = "college"
        return "college"

    # "from [name]" → cache lookup
    sender_match = re.search(r"\bfrom\s+([a-z][a-z ]{1,30}?)(?:\s+on|\s+to|\s*$)", t)
    if sender_match:
        return f"sender:{sender_match.group(1).strip()}"

    return "inbox"


def detect_direct_fau_mail_request(text: str) -> str | None:
    lowered = text.lower().strip()
    if not any(term in lowered for term in ("mail", "mails", "male", "males", "main", "mains", "email", "emails", "gmail", "gmails", "mailbox", "inbox", "college")):
        return None

    sender_match = re.search(r"\bfrom\s+([a-z0-9@._ -]{2,80})", lowered)
    if sender_match:
        sender = sender_match.group(1).strip(" .?!,")
        if sender:
            return f"mail from {sender}"

    if "unread" in lowered or "latest" in lowered:
        return "open unread"
    if any(term in lowered for term in ("open", "show")) and "inbox" in lowered:
        return "open inbox"
    if any(term in lowered for term in ("summarize", "summary", "check", "read", "review", "show")):
        return "check my mails"

    if any(term in lowered for term in ("college", "fau", "faumail", "fau mail")):
        return "check my mails"

    return None


def search_web(query: str) -> str:
    try:
        results = web_search_results(query, max_results=5)
        if not results:
            return "No results."
        snippets = []
        for r in results:
            snippets.append(f"• {r['title'][:80]} — {r['body'][:150]}\n  {r['href']}")
        return "\n".join(snippets)
    except Exception as e:
        return f"Search failed: {e}"


async def browse_url_content(url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            resp = await c.get(url, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        lines = [l for l in soup.get_text("\n", strip=True).splitlines() if l.strip()]
        return "\n".join(lines[:50])
    except Exception as e:
        return f"Browse failed: {e}"


def open_url(url: str) -> str:
    url = url.strip()
    # Only plain http(s) URLs — the string is interpolated into a shell command
    if not re.match(r'^https?://[^\s"\'<>|&^]+$', url):
        return f"Refused to open suspicious URL: {url[:80]}"
    try:
        subprocess.Popen(f'start chrome --new-tab "{url}"', shell=True)
        return f"Opened {url} in browser."
    except Exception as e:
        return f"Failed to open URL: {e}"


# ── Vision (screen perception) ──────────────────────────────────────────────────

def capture_screen_png() -> bytes:
    """Grab the primary monitor as PNG bytes."""
    import mss
    import mss.tools
    with mss.mss() as sct:
        monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
        shot = sct.grab(monitor)
        return mss.tools.to_png(shot.rgb, shot.size)


def analyze_image_png(image_png: bytes, query: str) -> str:
    """Send a screenshot to a vision-capable brain and return a spoken description."""
    vision_client = gemini_client or openai_client
    vision_model = GEMINI_MODEL if gemini_client else OPENAI_MODEL
    if not vision_client:
        return ("I don't have eyes configured, sir. Add a Gemini or OpenAI key "
                "so I can look at your screen.")
    data_uri = "data:image/png;base64," + base64.b64encode(image_png).decode()
    messages = [
        {"role": "system", "content":
            "You are J.A.R.V.I.S. looking at the user's screen. Describe what is relevant to "
            "their question in 1-3 spoken sentences. No markdown. If they asked a specific "
            "question about the screen, answer it directly."},
        {"role": "user", "content": [
            {"type": "text", "text": query or "What's on my screen right now?"},
            {"type": "image_url", "image_url": {"url": data_uri}},
        ]},
    ]
    resp = vision_client.chat.completions.create(
        model=vision_model, messages=messages, max_tokens=400, temperature=0.4,
    )
    _track_usage(vision_model, resp.usage)
    return resp.choices[0].message.content or "I couldn't make sense of the screen, sir."


async def see_screen(query: str = "") -> str:
    """Capture the screen and describe it. Blocking work runs in the executor."""
    loop = asyncio.get_event_loop()
    try:
        png = await loop.run_in_executor(None, capture_screen_png)
    except Exception as e:
        return f"I couldn't capture the screen, sir: {e}"
    try:
        return await loop.run_in_executor(None, lambda: analyze_image_png(png, query))
    except Exception as e:
        return f"I captured the screen but couldn't interpret it, sir: {e}"


def detect_direct_screen_vision_request(text: str) -> str | None:
    """Detect 'what's on my screen / what am I looking at' — reading the desktop,
    distinct from the 'show X on screen' display feature."""
    t = text.lower().strip()
    if re.search(r"\bwhat am i looking at\b", t):
        return text
    if re.search(r"\bwhat do you see\b", t):
        return text
    if re.search(r"\b(look at|read|describe|analy[sz]e|check)\s+(my|the|this)\s+screen\b", t):
        return text
    if re.search(r"\bcan you see\s+(my|the|this)\s+screen\b", t):
        return text
    # "what's on my screen" but not "show/put/pitch ... on screen"
    if re.search(r"\bwhat(?:'s| is| are)?\b.*\bon (my|the) screen\b", t) and \
            not re.search(r"\b(show|put|pitch|display|bring|send|push|open)\b", t):
        return text
    return None


APP_MAP = {
    "chrome": "chrome", "browser": "chrome", "google": "chrome",
    "vscode": "code",   "vs code": "code",   "code": "code",
    "notepad": "notepad", "notepad++": "notepad++",
    "explorer": "explorer", "file explorer": "explorer",
    "spotify": "spotify", "discord": "discord", "slack": "slack",
    "terminal": "wt",   "powershell": "powershell", "cmd": "cmd",
    "calculator": "calc", "paint": "mspaint",
    "word": "winword",  "excel": "excel", "powerpoint": "powerpnt",
    "task manager": "taskmgr",
}

def open_app(name: str) -> str:
    try:
        cmd = APP_MAP.get(name.lower().strip(), name.strip())
        subprocess.Popen(cmd, shell=True)
        return f"Opened {name}."
    except Exception as e:
        return f"Couldn't open {name}: {e}"


# ── Device control (volume / media / power) ─────────────────────────────────────

def _press_media_key(key, times: int = 1) -> None:
    from pynput.keyboard import Controller
    kb = Controller()
    for _ in range(times):
        kb.press(key)
        kb.release(key)


def control_device(action_raw: str) -> str:
    """System-wide media/volume/power control via OS media keys."""
    t = (action_raw or "").lower().strip()
    try:
        from pynput.keyboard import Key
        if re.search(r"\b(volume up|louder|turn it up|raise|increase)\b", t) or t == "volume_up":
            _press_media_key(Key.media_volume_up, 4)
            return "Volume up, sir."
        if re.search(r"\b(volume down|quieter|turn it down|lower|decrease)\b", t) or t == "volume_down":
            _press_media_key(Key.media_volume_down, 4)
            return "Volume down, sir."
        if re.search(r"\bunmute\b", t):
            _press_media_key(Key.media_volume_mute)
            return "Unmuted, sir."
        if re.search(r"\b(mute|silence)\b", t):
            _press_media_key(Key.media_volume_mute)
            return "Muted, sir."
        if re.search(r"\b(next|skip)\b", t):
            _press_media_key(Key.media_next)
            return "Next track, sir."
        if re.search(r"\b(previous|back|prev)\b", t):
            _press_media_key(Key.media_previous)
            return "Previous track, sir."
        if re.search(r"\b(pause|play|resume)\b", t):
            _press_media_key(Key.media_play_pause)
            return "Done, sir."
        if re.search(r"\block\b", t):
            subprocess.Popen("rundll32.exe user32.dll,LockWorkStation", shell=True)
            return "Locking the workstation, sir."
        if re.search(r"\b(sleep|suspend|hibernate|power down)\b", t):
            subprocess.Popen("rundll32.exe powrprof.dll,SetSuspendState 0,1,0", shell=True)
            return "Putting the machine to sleep, sir."
        return f"I'm not sure how to '{action_raw}', sir."
    except Exception as e:
        return f"Device control failed, sir: {e}"


def run_command(cmd: str) -> str:
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=30,
            cwd="C:/PROJECTS"
        )
        out = (result.stdout or "").strip()
        err = (result.stderr or "").strip()
        if out and err:
            return f"Output:\n{out}\nErrors:\n{err}"
        return out or err or "(no output)"
    except subprocess.TimeoutExpired:
        return "Command timed out after 30 seconds."
    except Exception as e:
        return f"Command failed: {e}"


def read_file(path: str) -> str:
    try:
        p = Path(path.strip())
        if not p.exists():
            return f"File not found: {path}"
        content = p.read_text(encoding="utf-8", errors="ignore")
        if len(content) > 4000:
            return content[:4000] + "\n...[truncated — file too large]"
        return content
    except Exception as e:
        return f"Read failed: {e}"


def list_dir(path: str) -> str:
    try:
        p = Path(path.strip())
        if not p.exists():
            return f"Path not found: {path}"
        items = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        lines = []
        for item in items:
            if item.name.startswith('.'):
                continue
            size = f"  {item.stat().st_size:,} bytes" if item.is_file() else "/"
            lines.append(f"{'📁' if item.is_dir() else '📄'} {item.name}{size}")
        return "\n".join(lines) if lines else "Empty directory."
    except Exception as e:
        return f"List failed: {e}"


def find_files(query: str) -> str:
    """Find files matching a name pattern in a directory."""
    parts = re.split(r'\s+in\s+', query, flags=re.I, maxsplit=1)
    pattern = parts[0].strip()
    search_root = Path(parts[1].strip()) if len(parts) > 1 else Path("C:/PROJECTS")

    try:
        matches = []
        for p in search_root.rglob(f"*{pattern}*"):
            if any(skip in str(p) for skip in ['node_modules', '.git', '__pycache__', 'venv']):
                continue
            matches.append(str(p))
            if len(matches) >= 20:
                break
        if not matches:
            return f"No files matching '{pattern}' found in {search_root}."
        return "\n".join(matches)
    except Exception as e:
        return f"Search failed: {e}"


def write_file(raw: str) -> str:
    try:
        data = json.loads(raw)
        path = Path(data["path"])
        content = data["content"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Written: {path}"
    except Exception as e:
        return f"Write failed: {e}"


def build_project(raw: str) -> str:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return f"Build failed — bad JSON: {e}"
    name = data.get("project_name", "jarvis-project")
    files = data.get("files", [])
    path = Path.home() / "Desktop" / name
    path.mkdir(parents=True, exist_ok=True)
    created = []
    for f in files:
        fname = f.get("filename", "")
        if fname:
            fp = path / fname
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(f.get("content", ""), encoding="utf-8")
            created.append(fname)
    return f"Project '{name}' on Desktop. Files: {', '.join(created)}"


def remember(fact: str) -> str:
    mem = load_memory()
    existing = {e.lower() for e in mem["facts"] + mem["preferences"]}
    if fact.lower().strip() in existing:
        return f"Already noted: {fact}"
    if "prefer" in fact.lower():
        mem["preferences"].append(fact)
    else:
        mem["facts"].append(fact)
    save_memory(mem)
    return f"Saved: {fact}"


def search_obsidian(query: str) -> str:
    """Search Obsidian vault notes for a query."""
    if not OBSIDIAN_VAULT.exists():
        return f"Obsidian vault not found at {OBSIDIAN_VAULT}. Set OBSIDIAN_VAULT in .env"
    query_lower = query.lower()
    include_raw = bool(re.search(r"\b(raw|source|sources|inbox|scratch|uncurated)\b", query_lower))
    results = []
    try:
        md_files = sorted(OBSIDIAN_VAULT.rglob("*.md"), key=lambda path: (0 if "wiki" in {part.lower() for part in path.parts} else 1, str(path)))
        for md_file in md_files:
            parts = {part.lower() for part in md_file.parts}
            if {".obsidian", ".trash"} & parts:
                continue
            if not include_raw and {"raw", "inbox"} & parts:
                continue
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
                if query_lower in content.lower() or query_lower in md_file.stem.lower():
                    # Return matching note with context
                    lines = content.splitlines()
                    preview = "\n".join(lines[:30])
                    rel = md_file.relative_to(OBSIDIAN_VAULT).as_posix()
                    results.append(f"--- {rel} ---\n{preview}")
                    if len(results) >= 4:
                        break
            except Exception:
                continue
    except Exception as e:
        return f"Obsidian search failed: {e}"
    return "\n\n".join(results) if results else f"No Obsidian notes found matching '{query}'"


def add_reminder(text: str) -> str:
    mem = load_memory()
    ts = datetime.datetime.now().strftime("%b %d %H:%M")
    mem["reminders"].append(f"[{ts}] {text}")
    save_memory(mem)
    return f"Reminder set: {text}"


def direct_access_capability_answer(text: str) -> str | None:
    """Answer access-permission questions without performing the access."""
    lowered = text.lower().strip()
    asks_capability = re.search(r"\b(can|could|are you able to|do you have access to|can you access)\b", lowered)
    mentions_private_source = re.search(r"\b(files?|folders?|laptop|computer|pc|mail|mails|emails?|gmail|gmails|calendar)\b", lowered)
    actual_command = re.match(r"\s*(open|show|display|read|list|search|find|check|get)\b", lowered)
    if asks_capability and mentions_private_source and not actual_command:
        return (
            "Yes, sir. I can access local project files in this workspace and your connected Gmail/Calendar, "
            "but I will not open, read, search, or display anything unless you explicitly ask me to."
        )
    return None


def is_self_correction_request(text: str) -> bool:
    lowered = text.lower().strip()
    return bool(re.search(
        r"\b(deploy|run|launch|start|trigger|activate)\b.*\b(self[-\s]?(correction|improvement)|improvement agent|correction agent|learn from this conversation|analy[sz]e this conversation)\b",
        lowered,
    ))


async def direct_self_correction_answer(text: str, session: dict) -> str | None:
    """Run Jarvis's self-improvement agent on command for the current/recent conversation."""
    if not is_self_correction_request(text):
        return None

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: run_self_improvement_agent(
            conversation_index_file=CONVERSATION_INDEX_FILE,
            lessons_file=JARVIS_LESSONS_FILE,
            state_file=SELF_IMPROVEMENT_STATE_FILE,
            report_dir=IMPROVEMENT_REPORTS_DIR,
            call_llm=call_llm,
            max_sessions=1,
            min_session_age_minutes=0,
            lesson_limit=SELF_IMPROVEMENT_LESSON_LIMIT,
        ),
    )
    if result.get("processed", 0) <= 0:
        return "I ran the self-correction agent, sir, but this conversation is still too small to learn anything useful from."
    added = result.get("lessons_added", 0)
    failures = result.get("failures", 0)
    report = result.get("report")
    if added:
        return f"Self-correction complete, sir. I reviewed this conversation, found {failures} issue pattern{'s' if failures != 1 else ''}, and added {added} behavior fix{'es' if added != 1 else ''}. Report saved at {report}."
    return f"Self-correction complete, sir. I reviewed this conversation and wrote a report, but did not add new prompt rules. Report saved at {report}."


def direct_nonenglish_fragment_answer(text: str) -> str | None:
    """Avoid inventing actions for casual non-English fragments."""
    stripped = text.strip()
    lowered = stripped.lower()
    if any("\u0D00" <= ch <= "\u0D7F" for ch in stripped):
        return None
    if re.search(r"\b(translate|what does|meaning|in english|save|remember|note)\b", lowered):
        return None
    if re.search(r"[äöüßæøåáéíóúýðþñç]", lowered) and not re.search(
        r"\b(open|show|display|read|search|find|check|mail|email|gmail|file|folder|calendar|youtube)\b",
        lowered,
    ):
        return "I heard that as a non-English phrase, sir. I will not save or act on it unless you ask me to translate or remember it."
    return None


# ── Action parser ──────────────────────────────────────────────────────────────

# ── Mail + Calendar session cache ──────────────────────────────────────────────
# Keyed by lowercase sender name fragments → {id, sender, subject, date, snippet}
# Reset each session. Single-user system — module-level is fine.
_mail_cache: dict[str, dict] = {}   # "mathias" → mail dict
_last_mail_context: dict | None = None
_last_mail_list: list[dict] = []
_last_mail_list_label: str = "mail"
_pending_gmail_send: dict | None = None


def _cache_mails(mails: list[dict]):
    """Store mails in session cache keyed by sender name tokens."""
    global _mail_cache, _last_mail_context, _last_mail_list, _last_topic
    if mails:
        _last_mail_context = mails[0]
        _last_mail_list = mails[:]
        _last_topic = "inbox"
    for m in mails:
        sender = m.get("sender", "")
        # Extract name part before < e.g. "Mathias Zinnen <m@fau.de>" → "mathias zinnen"
        name = re.sub(r"<[^>]+>", "", sender).strip().lower()
        for token in name.split():
            if len(token) > 2:
                _mail_cache[token] = m
        # Also key by full sender string tokens
        for token in re.findall(r"[a-z0-9]{3,}", sender.lower()):
            _mail_cache[token] = m


def _format_mails(mails: list[dict]) -> str:
    lines = []
    for i, m in enumerate(mails):
        label = _relative_date_label(m.get("date", ""))
        lines.append(
            f"{i+1}. [ID:{m['id']}] [{label}] From: {m['sender']} | {m['subject']} | {m['snippet'][:80]}"
        )
    return "\n".join(lines)


def _lookup_cached_mail(text: str) -> dict | None:
    """Find a mail in session cache from a natural-language sender reference."""
    tokens = re.findall(r"[a-z]{3,}", text.lower())
    for token in tokens:
        if token in _mail_cache:
            return _mail_cache[token]
    return None


def _mail_one_line(mail: dict, *, include_body_hint: bool = False) -> str:
    label = _relative_date_label(mail.get("date", ""))
    sender = mail.get("sender", "Unknown sender")
    subject = mail.get("subject") or "(no subject)"
    snippet = (mail.get("snippet") or "").strip()
    base = f"The most recent mail I found is from {sender}, received {label}, about {subject}."
    if include_body_hint and snippet:
        return f"{base} Preview: {snippet[:160]}"
    return base


def _mail_by_number(text: str) -> dict | None:
    lowered = text.lower()
    match = re.search(r"\b(?:number|mail|message)?\s*(\d{1,2})\b", lowered)
    if match:
        index = int(match.group(1))
    else:
        ordinals = {
            "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
            "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
        }
        index = next((value for word, value in ordinals.items() if re.search(rf"\b{word}\b", lowered)), 0)
    if 1 <= index <= len(_last_mail_list):
        return _last_mail_list[index - 1]
    return None


def _extract_mail_sender_query(text: str) -> str | None:
    lowered = text.lower().strip()
    if re.search(r"\b(fau|college|university)\b", lowered):
        return "fau"
    match = re.search(r"\bfrom\s+([a-z0-9@._' -]{2,80})", lowered)
    if match:
        return match.group(1).strip(" .?!,")
    match = re.search(r"\b(?:mail|mails|email|emails|message|messages)\s+from\s+([a-z0-9@._' -]{2,80})", lowered)
    if match:
        return match.group(1).strip(" .?!,")
    return None


def _gmail_sender_query(sender: str) -> str:
    sender = sender.strip()
    lowered = sender.lower()
    if lowered == "fau":
        return "{from:fau.de from:fau.edu fau.de fau.edu fau}"
    if "@" in sender or "." in sender:
        return f"from:{sender}"
    if " " in sender:
        return f'from:"{sender}"'
    return f"from:{sender}"


async def direct_gmail_answer(text: str) -> str | None:
    """Answer common mail questions without spending LLM tokens."""
    global _last_mail_context, _last_mail_list_label
    lowered = text.lower().strip()
    if re.search(r"\b(calendar|schedule|agenda|events?|appointments?)\b", lowered):
        return None
    if re.search(r"\b(screen|skreen|scream|on screen)\b", lowered):
        return None
    mailish = re.search(r"\b(mail|mails|male|males|main|mains|email|emails|gmail|gmails|mailbox|inbox|message|messages|meal)\b", lowered)
    ackish = re.fullmatch(r"(yes|yeah|yep|yup|mm[\s-]*hmm|mhm|sure|ok|okay|read them|summari[sz]e them|highlights?|\.)", lowered)
    numbered_mail = _mail_by_number(lowered)
    sender_query = _extract_mail_sender_query(lowered)
    if not mailish and not ackish and not numbered_mail and not sender_query:
        return None

    wants_date = re.search(r"\b(date|when|received|receive|time)\b", lowered)
    wants_latest = re.search(r"\b(last|latest|recent|newest|most recent)\b", lowered)
    wants_any = re.search(r"\b(any|have|has|got|found|find|check)\b", lowered)
    wants_recent = re.search(r"\b(recent|latest|newest|last)\b", lowered)
    wants_unread = re.search(r"\bunread\b", lowered)
    wants_all = re.search(r"\b(all|everything|full inbox|mailbox)\b", lowered)
    wants_briefing = re.search(r"\b(read|summari[sz]e|brief|important|relevant|main things?|highlights?|tell me)\b", lowered)
    wants_highlights = ackish or re.search(r"\b(highlights?|summari[sz]e|recite|read them|overview)\b", lowered)
    wants_full_number = numbered_mail and re.search(r"\b(read|open|show|display|full|number|message|mail)\b", lowered)

    try:
        from plugins.gmail_agent import get_mail_by_id, get_recent_mails, get_unread_mails, search_mails

        if lowered == "." and _last_mail_list:
            return "The mail list is still on screen, sir. Say 'read highlights' or 'open number 1' and I will use the real messages."

        if wants_highlights and _last_mail_list:
            return _mail_list_highlights(_last_mail_list)

        if wants_full_number and numbered_mail:
            _last_mail_context = numbered_mail
            full = get_mail_by_id(numbered_mail["id"])
            snippet = (full.get("body") or "").strip()[:900]
            return (
                f"Mail {(_last_mail_list.index(numbered_mail) + 1)} is from {full.get('sender', 'Unknown sender')}, "
                f"received {_relative_date_label(full.get('date', ''))}, subject {full.get('subject') or '(no subject)'}. "
                f"{snippet}"
            )

        if wants_date and not sender_query:
            mail = _lookup_cached_mail(lowered) or _last_mail_context
            if not mail:
                return "I do not have a mail in context yet, sir. Ask me for the latest mail first."
            return (
                f"That mail was received {_relative_date_label(mail.get('date', ''))}. "
                f"It was from {mail.get('sender', 'Unknown sender')} about {mail.get('subject') or '(no subject)'}."
            )

        if sender_query:
            query = _gmail_sender_query(sender_query)
            mails = search_mails(query, max_results=10)
            if not mails and sender_query == "fau":
                mails = search_mails("fau", max_results=10)
            if not mails:
                return f"I found no mails from {sender_query}, sir."
            _cache_mails(mails)
            if wants_date:
                return (
                    f"The latest mail from {sender_query} was received "
                    f"{_relative_date_label(mails[0].get('date', ''))}."
                )
            if wants_any and not wants_latest:
                return f"Yes, I found {len(mails)} mail{'s' if len(mails) != 1 else ''} from {sender_query}. {_smart_single_mail_summary(mails[0])}"
            return _smart_single_mail_summary(mails[0])

        if wants_latest or re.fullmatch(r"(last|latest)\s+(mail|meal|email)", lowered):
            mails = get_unread_mails(max_results=10) if wants_unread else get_recent_mails(max_results=10)
            if not mails:
                return "I found no mail in that view, sir."
            _cache_mails(mails)
            _last_mail_list_label = "unread inbox" if wants_unread else "recent inbox"
            return _smart_single_mail_summary(mails[0])

        if wants_briefing and mailish and not wants_recent and not wants_all and not wants_unread:
            unread = get_unread_mails(max_results=20)
            recent = get_recent_mails(max_results=20)
            seen = set()
            mails = []
            for mail in unread + recent:
                if mail["id"] not in seen:
                    seen.add(mail["id"])
                    mails.append(mail)
            _cache_mails(mails)
            _last_mail_list_label = "relevant inbox"
            return _smart_mail_triage(mails, total_unread=len(unread))

        if wants_any and mailish:
            mails = get_unread_mails(max_results=10) if wants_unread else get_recent_mails(max_results=10)
            if not mails:
                return "I found no mail in that view, sir."
            _cache_mails(mails)
            _last_mail_list_label = "unread inbox" if wants_unread else "recent inbox"
            return f"I found {len(mails)} {_last_mail_list_label} messages. {_smart_single_mail_summary(mails[0])}"

    except Exception as e:
        return f"Gmail error: {e}"

    return None


# ── Gmail plugin ───────────────────────────────────────────────────────────────

async def gmail_check(_: str = "") -> str:
    try:
        from plugins.gmail_agent import get_unread_mails
        mails = get_unread_mails(max_results=10)
        if not mails:
            return "No unread messages in your inbox."
        _cache_mails(mails)
        return f"{len(mails)} unread messages:\n" + _format_mails(mails)
    except Exception as e:
        return f"Gmail error: {e}"


async def gmail_read(mail_id: str) -> str:
    try:
        from plugins.gmail_agent import get_mail_by_id
        mail = get_mail_by_id(mail_id.strip())
        label = _relative_date_label(mail.get("date", ""))
        return (
            f"From: {mail['sender']}\n"
            f"Subject: {mail['subject']}\n"
            f"Date: {label}\n\n"
            f"{mail['body']}"
        )
    except Exception as e:
        return f"Gmail error: {e}"


async def gmail_search(query: str) -> str:
    try:
        from plugins.gmail_agent import search_mails
        mails = search_mails(query.strip(), max_results=10)
        if not mails:
            return f"No messages found for: {query}"
        _cache_mails(mails)
        return _format_mails(mails)
    except Exception as e:
        return f"Gmail error: {e}"


async def gmail_draft(arg: str) -> str:
    """Store a pending reply draft and return a confirmation prompt.
    arg format: 'mail_id:body' — split on first colon."""
    global _pending_gmail_send
    parts = arg.split(":", 1)
    if len(parts) != 2:
        return "Invalid GMAIL_DRAFT format. Expected GMAIL_DRAFT:mail_id:body"
    mail_id, body = parts[0].strip(), parts[1].strip()
    try:
        from plugins.gmail_agent import get_mail_by_id
        mail = get_mail_by_id(mail_id)
        _pending_gmail_send = {
            "mail_id": mail_id,
            "body":    body,
            "to":      mail["sender"],
            "subject": mail["subject"],
        }
        preview = body[:120] + ("..." if len(body) > 120 else "")
        return (
            f"Draft ready. Replying to {mail['sender']} "
            f"re: '{mail['subject']}'. "
            f"Message: {preview}. "
            f"Say yes to send or no to cancel."
        )
    except Exception as e:
        return f"Gmail error preparing draft: {e}"


# ── Calendar text functions (LLM-callable, return spoken text) ────────────────

async def calendar_check(_: str = "") -> str:
    """Return next 7 days of events as spoken text."""
    try:
        from plugins.calendar_agent import get_events
        events = get_events(days_ahead=7)
        if not events:
            return "Your calendar is clear for the next week, sir."
        lines = []
        for e in events:
            t = f" at {e['time_start']}" if e['time_start'] else ""
            lines.append(f"[{e['label']}]{t} — {e['title']}")
        return "Upcoming events:\n" + "\n".join(lines)
    except Exception as ex:
        return f"Calendar error: {ex}"


async def calendar_check_date(date_str: str) -> str:
    """Return events on a specific date. date_str: YYYY-MM-DD or 'today'/'tomorrow'."""
    try:
        from plugins.calendar_agent import get_events_on_date
        ds = date_str.strip().lower()
        if ds in ("today", "now"):
            target = datetime.date.today()
        elif ds == "tomorrow":
            target = datetime.date.today() + datetime.timedelta(days=1)
        else:
            target = datetime.date.fromisoformat(ds)
        events = get_events_on_date(target)
        if not events:
            return f"Nothing on the calendar for {target.strftime('%B %d')}, sir."
        lines = []
        for e in events:
            t = f" at {e['time_start']}" if e['time_start'] else ""
            lines.append(f"{t} — {e['title']}{' @ ' + e['location'] if e['location'] else ''}")
        label = "today" if target == datetime.date.today() else target.strftime("%B %d")
        return f"Events for {label}:\n" + "\n".join(lines)
    except Exception as ex:
        return f"Calendar error: {ex}"


async def calendar_add(arg: str) -> str:
    """Add an event. arg format: title|YYYY-MM-DD|HH:MM|duration_min|location"""
    try:
        from plugins.calendar_agent import create_event
        parts = [p.strip() for p in arg.split("|")]
        title    = parts[0] if len(parts) > 0 else "New Event"
        date_str = parts[1] if len(parts) > 1 else datetime.date.today().isoformat()
        time_str = parts[2] if len(parts) > 2 else ""
        duration = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 60
        location = parts[4] if len(parts) > 4 else ""
        ev = create_event(title, date_str, time_str, duration, location)
        t = f" at {ev['time_start']}" if ev['time_start'] else ""
        return f"Done, sir. '{title}' added for {ev['label']}{t}."
    except Exception as ex:
        return f"Calendar error: {ex}"


async def direct_calendar_answer(text: str) -> str | None:
    """Answer calendar read/check requests before Gmail routing can misread them."""
    lowered = text.lower().strip()
    if not re.search(r"\b(calendar|schedule|agenda|events?|appointments?)\b", lowered):
        return None
    # Creation intent ("schedule a meeting", "add an event tomorrow") must reach
    # the LLM so it can emit <<CALENDAR_ADD>> — never intercept it as a read.
    if re.search(r"\b(add|create|book|new|set\s*up|put|make)\b", lowered) or \
            re.search(r"\bschedule\s+(a|an|the|my)\b", lowered):
        return None
    if re.search(r"\b(can|could|able|access)\b", lowered) and not re.search(r"\b(read|check|show|display|what|anything|events?|appointments?)\b", lowered):
        return (
            "Yes, sir. I can access your connected calendar, but I will not read or display it "
            "unless you explicitly ask me to."
        )
    if not re.search(r"\b(read|check|show|display|what|anything|events?|appointments?|tomorrow|today|schedule|agenda)\b", lowered):
        return None
    if re.search(r"\b(tomorrow|tmr)\b", lowered):
        return await calendar_check_date("tomorrow")
    if re.search(r"\b(today|now)\b", lowered):
        return await calendar_check_date("today")
    return await calendar_check("")


async def direct_mail_calendar_answer(text: str) -> str | None:
    lowered = text.lower().strip()
    has_mail = re.search(r"\b(mail|mails|email|emails|gmail|gmails|mailbox|inbox)\b", lowered)
    has_calendar = re.search(r"\b(calendar|schedule|agenda|meetings?|events?|appointments?|tomorrow|today)\b", lowered)
    if not (has_mail and has_calendar):
        return None
    try:
        from plugins.gmail_agent import get_recent_mails, get_unread_mails
        unread = get_unread_mails(max_results=20)
        recent = get_recent_mails(max_results=20)
        seen = set()
        mails = []
        for mail in unread + recent:
            if mail["id"] not in seen:
                seen.add(mail["id"])
                mails.append(mail)
        _cache_mails(mails)
        global _last_mail_list_label
        _last_mail_list_label = "relevant inbox"
        mail_part = _smart_mail_triage(mails, total_unread=len(unread))
    except Exception as exc:
        mail_part = f"Mail error: {exc}"
    if re.search(r"\b(tomorrow|tmr)\b", lowered):
        cal_part = await calendar_check_date("tomorrow")
    elif re.search(r"\b(today|now)\b", lowered):
        cal_part = await calendar_check_date("today")
    else:
        cal_part = await calendar_check("")
    return f"{mail_part} Calendar: {cal_part}"


def _is_gmail_confirmation(text: str) -> bool:
    t = text.lower().strip()
    # Cancellation wins: "no, don't send it" must never count as a confirmation
    if _is_gmail_cancellation(t):
        return False
    return bool(re.search(r"\b(yes|yeah|yep|yup|sure|confirm|okay|ok|send it|send|go ahead|do it)\b", t))


def _is_gmail_cancellation(text: str) -> bool:
    t = text.lower().strip()
    return bool(re.search(r"\b(no|nope|cancel|don'?t send|do not send|stop|abort|never\s?mind|discard)\b", t))


# ── Screen display actions (need WebSocket to push content to frontend) ────────

async def maps_directions(arg: str, ws: WebSocket) -> str:
    """Show route on screen. arg format: 'origin|destination'"""
    parts = arg.split("|", 1)
    if len(parts) != 2:
        return "Maps format error. Use: MAPS: origin|destination"
    origin, destination = parts[0].strip(), parts[1].strip()
    origin_enc   = quote_plus(origin)
    dest_enc     = quote_plus(destination)

    if GOOGLE_MAPS_API_KEY:
        embed_url = (
            f"https://www.google.com/maps/embed/v1/directions"
            f"?key={GOOGLE_MAPS_API_KEY}"
            f"&origin={origin_enc}&destination={dest_enc}&mode=driving"
        )
    else:
        embed_url = f"https://maps.google.com/maps?saddr={origin_enc}&daddr={dest_enc}&output=embed"

    maps_url = f"https://www.google.com/maps/dir/{origin_enc}/{dest_enc}/"

    await ws.send_json({
        "type": "screen_display",
        "content_type": "map",
        "data": {
            "origin": origin,
            "destination": destination,
            "embed_url": embed_url,
            "maps_url": maps_url,
        },
    })
    return f"Directions from {origin} to {destination} are now on your screen."


async def pitch_mail(mail_id: str, ws: WebSocket) -> str:
    """Display a full mail on screen. mail_id can be an actual ID or a sender name."""
    try:
        from plugins.gmail_agent import get_mail_by_id
        # Try cache lookup first (handles "pitch the one from Mathias" style)
        cached = _lookup_cached_mail(mail_id)
        real_id = cached["id"] if cached else mail_id.strip()
        mail = get_mail_by_id(real_id)
        label = _relative_date_label(mail.get("date", ""))
        await ws.send_json({
            "type": "screen_display",
            "content_type": "email",
            "data": {
                "id":      mail["id"],
                "sender":  mail["sender"],
                "subject": mail["subject"],
                "date":    label,
                "body":    mail["body"],
            },
        })
        return f"Mail from {mail['sender']} is now on your screen."
    except Exception as e:
        return f"Could not display mail: {e}"


async def display_mails_screen(mails: list[dict], ws: WebSocket, label: str = "mail") -> str:
    global _last_mail_list_label
    if not mails:
        return f"No {label} messages to display."
    _last_mail_list_label = label
    _cache_mails(mails)
    for m in mails:
        m["date_label"] = _relative_date_label(m.get("date", ""))
    await ws.send_json({
        "type": "screen_display",
        "content_type": "mails_list",
        "data": {"mails": mails, "query": label},
    })
    return f"{len(mails)} {label} messages are now on your screen."


async def gmail_screen(_: str, ws: WebSocket) -> str:
    """Show relevant inbox on screen with relative date labels."""
    try:
        from plugins.gmail_agent import get_recent_mails, get_unread_mails
        unread = get_unread_mails(max_results=20)
        recent = get_recent_mails(max_results=20)
        seen = set()
        mails = []
        for mail in unread + recent:
            if mail["id"] not in seen:
                seen.add(mail["id"])
                mails.append(mail)
        mails.sort(key=lambda mail: (_mail_priority(mail)[0], mail.get("timestamp", 0)), reverse=True)
        mails = [mail for mail in mails if _mail_category(mail) != "promotion"][:10]
        if not mails:
            return "No relevant inbox messages to display after filtering promotions and obvious automated mail."
        return await display_mails_screen(mails, ws, "relevant inbox")
    except Exception as e:
        return f"Gmail error: {e}"


async def gmail_search_screen(query: str, ws: WebSocket) -> str:
    """Search Gmail and show results on screen with relative date labels."""
    try:
        from plugins.gmail_agent import search_mails
        mails = search_mails(query.strip(), max_results=10)
        if not mails:
            return f"No messages found for: {query}"
        await display_mails_screen(mails, ws, "search result")
        return f"Found {len(mails)} messages. Showing on screen."
    except Exception as e:
        return f"Gmail error: {e}"


async def close_screen(_: str, ws: WebSocket) -> str:
    await ws.send_json({"type": "screen_display", "content_type": "close"})
    return "Screen cleared, sir."


# ── Calendar screen actions ────────────────────────────────────────────────────

async def calendar_screen(arg: str, ws: WebSocket) -> str:
    """Show upcoming calendar events on screen."""
    try:
        from plugins.calendar_agent import get_events
        days = 7
        if arg.strip().isdigit():
            days = int(arg.strip())
        events = get_events(days_ahead=days)
        if not events:
            return "No upcoming events in the next week."
        await ws.send_json({
            "type": "screen_display",
            "content_type": "calendar",
            "data": {"events": events},
        })
        return f"{len(events)} upcoming events are now on your screen."
    except Exception as e:
        return f"Calendar error: {e}"


async def calendar_today_screen(_: str, ws: WebSocket) -> str:
    """Show today's events on screen."""
    try:
        from plugins.calendar_agent import get_events_on_date
        events = get_events_on_date(datetime.date.today())
        await ws.send_json({
            "type": "screen_display",
            "content_type": "calendar",
            "data": {"events": events, "label": "TODAY"},
        })
        n = len(events)
        return f"You have {n} event{'s' if n != 1 else ''} today." if n else "Nothing on the calendar today, sir."
    except Exception as e:
        return f"Calendar error: {e}"


async def calendar_tomorrow_screen(_: str, ws: WebSocket) -> str:
    """Show tomorrow's events on screen."""
    try:
        from plugins.calendar_agent import get_events_on_date
        tomorrow = datetime.date.today() + datetime.timedelta(days=1)
        events = get_events_on_date(tomorrow)
        await ws.send_json({
            "type": "screen_display",
            "content_type": "calendar",
            "data": {"events": events, "label": "TOMORROW"},
        })
        n = len(events)
        return f"You have {n} event{'s' if n != 1 else ''} tomorrow." if n else "Nothing scheduled for tomorrow, sir."
    except Exception as e:
        return f"Calendar error: {e}"


SCREEN_ACTIONS = [
    (re.compile(r'<<MAPS:\s*(.+?)>>',               re.I|re.S), "Getting directions",   maps_directions),
    (re.compile(r'<<PITCH_MAIL:\s*(.+?)>>',          re.I|re.S), "Displaying mail",      pitch_mail),
    (re.compile(r'<<GMAIL_SCREEN(\s*)>>',            re.I),      "Showing inbox",        gmail_screen),
    (re.compile(r'<<GMAIL_SEARCH_SCREEN:\s*(.+?)>>', re.I|re.S), "Showing mail search",  gmail_search_screen),
    (re.compile(r'<<CALENDAR_SCREEN(\s*)>>',         re.I),      "Showing calendar",     calendar_screen),
    (re.compile(r'<<CALENDAR_TODAY(\s*)>>',          re.I),      "Checking today",       calendar_today_screen),
    (re.compile(r'<<CALENDAR_TOMORROW(\s*)>>',       re.I),      "Checking tomorrow",    calendar_tomorrow_screen),
    (re.compile(r'<<CLOSE_SCREEN(\s*)>>',            re.I),      "Closing screen",       close_screen),
]


ACTIONS = [
    (re.compile(r'<<SEARCH:\s*(.+?)>>',           re.I|re.S), "Searching",      lambda m: search_web(m)),
    (re.compile(r'<<BROWSE:\s*(.+?)>>',            re.I|re.S), "Browsing",       lambda m: browse_url_content(m)),
    (re.compile(r'<<OPEN_URL:\s*(.+?)>>',          re.I|re.S), "Opening URL",    lambda m: open_url(m)),
    (re.compile(r'<<OPEN_APP:\s*(.+?)>>',          re.I|re.S), "Opening app",    lambda m: open_app(m)),
    (re.compile(r'<<PLAY_YOUTUBE:\s*(.+?)>>',      re.I|re.S), "Opening YouTube",lambda m: play_youtube(m)),
    (re.compile(r'<<YOUTUBE_CONTROL:\s*(.+?)>>',   re.I|re.S), "Controlling YouTube", lambda m: youtube_control(m)),
    (re.compile(r'<<RUN:\s*(.+?)>>',               re.I|re.S), "Running command",lambda m: run_command(m)),
    (re.compile(r'<<READ_FILE:\s*(.+?)>>',         re.I|re.S), "Reading file",   lambda m: read_file(m)),
    (re.compile(r'<<LIST_DIR:\s*(.+?)>>',          re.I|re.S), "Listing folder", lambda m: list_dir(m)),
    (re.compile(r'<<FIND_FILES:\s*(.+?)>>',        re.I|re.S), "Searching files",lambda m: find_files(m)),
    (re.compile(r'<<WRITE_FILE:\s*(\{.+?\})>>',   re.I|re.S), "Writing file",   lambda m: write_file(m)),
    (re.compile(r'<<BUILD:\s*(\{.+?\})>>',         re.I|re.S), "Building",       lambda m: build_project(m)),
    (re.compile(r'<<REMEMBER:\s*(.+?)>>',          re.I|re.S), "Remembering",    lambda m: remember(m)),
    (re.compile(r'<<REMIND:\s*(.+?)>>',            re.I|re.S), "Reminder",       lambda m: add_reminder(m)),
    (re.compile(r'<<OBSIDIAN:\s*(.+?)>>',          re.I|re.S), "Reading notes",  lambda m: search_obsidian(m)),
    (re.compile(r'<<HISTORY:\s*(.+?)>>',           re.I|re.S), "Searching history", lambda m: search_history(m)),
    (re.compile(r'<<SEE_SCREEN:?\s*(.*?)>>',       re.I|re.S), "Looking at screen", lambda m: see_screen(m)),
    (re.compile(r'<<CONTROL:\s*(.+?)>>',           re.I|re.S), "Controlling device", lambda m: control_device(m)),
    # Gmail plugin
    (re.compile(r'<<GMAIL_CHECK(\s*)>>',           re.I),      "Checking Gmail", lambda m: gmail_check()),
    (re.compile(r'<<GMAIL_READ:\s*(.+?)>>',        re.I|re.S), "Reading mail",   lambda m: gmail_read(m)),
    (re.compile(r'<<GMAIL_SEARCH:\s*(.+?)>>',      re.I|re.S), "Searching Gmail",lambda m: gmail_search(m)),
    (re.compile(r'<<GMAIL_DRAFT:\s*(.+?)>>',       re.I|re.S), "Preparing reply",lambda m: gmail_draft(m)),
    # Calendar plugin
    (re.compile(r'<<CALENDAR_CHECK(\s*)>>',        re.I),      "Checking calendar", lambda m: calendar_check()),
    (re.compile(r'<<CALENDAR_DATE:\s*(.+?)>>',     re.I|re.S), "Checking date",     lambda m: calendar_check_date(m)),
    (re.compile(r'<<CALENDAR_ADD:\s*(.+?)>>',      re.I|re.S), "Adding event",      lambda m: calendar_add(m)),
]


async def execute_action(text: str, ws: WebSocket):
    # Screen actions — always async, always receive (arg, ws)
    for pattern, label, handler in SCREEN_ACTIONS:
        match = pattern.search(text)
        if not match:
            continue
        await ws.send_json({"type": "status", "message": f"{label}..."})
        arg = (match.group(1) or "").strip() if match.lastindex else ""
        result = await handler(arg, ws)
        clean = pattern.sub("", text).strip()
        return True, str(result), clean

    # Regular actions
    for pattern, label, handler in ACTIONS:
        match = pattern.search(text)
        if not match:
            continue
        await ws.send_json({"type": "status", "message": f"{label}..."})
        result = handler(match.group(1).strip())
        if hasattr(result, "__await__"):
            result = await result
        clean = pattern.sub("", text).strip()
        return True, str(result), clean
    return False, "", text


# ── TTS ────────────────────────────────────────────────────────────────────────

TAG_RE = re.compile(r'<<[^>]+>>', re.S)  # strip any leftover <<...>> tags

def clean_for_speech(text: str) -> str:
    """Remove tool tags and markdown symbols before sending to TTS."""
    text = TAG_RE.sub("", text)                          # remove <<ACTION: ...>> tags
    text = re.sub(r'\*+', '', text)                          # strip all asterisks
    text = re.sub(r'`{1,3}[^`]*`{1,3}', '', text)       # `inline code` / ```blocks```
    text = re.sub(r'#+', '', text)                              # strip all hash symbols
    text = re.sub(r'^[-*•]\s+', '', text, flags=re.MULTILINE)   # bullet points
    text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)   # numbered lists
    text = re.sub(r'_{1,2}([^_]+)_{1,2}', r'\1', text)  # _italic_ / __bold__
    text = re.sub(r'[-—_]{3,}', '', text)                # --- horizontal rules
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text) # [link text](url)
    text = re.sub(r'\s+', ' ', text)                     # collapse whitespace
    return text.strip()

async def tts(text: str, voice: str | None = None) -> bytes:
    text = clean_for_speech(text)
    if not text:
        text = "Done, sir."
    for v in [voice or VOICE, VOICE]:  # try requested voice, fall back to default
        try:
            communicate = edge_tts.Communicate(text, v, rate=TTS_RATE)
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                tmp = f.name
            await communicate.save(tmp)
            data = Path(tmp).read_bytes()
            os.unlink(tmp)
            if data:
                return data
        except Exception:
            if v == VOICE:
                raise  # default voice also failed — give up
    raise RuntimeError("TTS produced no audio")


# ── LLM call with automatic Groq fallback ────────────────────────────────────

# Groq is also used for speech-to-text when configured.


def _audio_suffix(mime: str) -> str:
    mime = (mime or "").lower()
    if "mp4" in mime:
        return ".mp4"
    if "mpeg" in mime or "mp3" in mime:
        return ".mp3"
    if "wav" in mime:
        return ".wav"
    if "ogg" in mime:
        return ".ogg"
    return ".webm"


def transcribe_audio_b64(audio_b64: str, mime: str = "audio/webm") -> str:
    """Transcribe browser-recorded mic audio through Groq's OpenAI-compatible API."""
    if not groq_client:
        raise RuntimeError("GROK_API_KEY is required for voice transcription.")
    if not audio_b64:
        return ""

    audio_bytes = base64.b64decode(audio_b64)
    if len(audio_bytes) < 1200:
        return ""

    tmp = None
    try:
        with tempfile.NamedTemporaryFile(suffix=_audio_suffix(mime), delete=False) as f:
            tmp = f.name
            f.write(audio_bytes)

        with open(tmp, "rb") as audio_file:
            result = groq_client.audio.transcriptions.create(
                file=audio_file,
                model=STT_MODEL,
                response_format="text",
            )

        if isinstance(result, str):
            return result.strip()
        return str(getattr(result, "text", "") or "").strip()
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass

# Fallback chain: tried in order when primary returns a recoverable error
GROQ_FALLBACK_CHAIN = [
    "llama-3.1-8b-instant",                      # Fallback1
    "meta-llama/llama-4-scout-17b-16e-instruct",  # Fallback2
    "meta-llama/llama-4-maverick-17b-128e-instruct", # Fallback3
    "gemma2-9b-it",                               # Fallback4 — kept for future re-activation
    "llama3-8b-8192",                             # Fallback5 — separate smaller quota
]

def _is_recoverable(err: str) -> bool:
    """True for errors where trying the next model makes sense."""
    e = err.lower()
    return any(k in e for k in [
        "429", "500", "quota", "rate", "decommissioned",
        "model_not_found", "not supported", "deprecated",
        "internal server error",
    ])


# ── Token usage tracking ───────────────────────────────────────────────────────
_token_stats: dict = {"active_model": ACTIVE_MODEL, "models": {}, "date": datetime.date.today().isoformat()}


def _maybe_reset_token_stats() -> None:
    """Reset counters at midnight so DAILY_TOKEN_LIMIT really means daily."""
    today = datetime.date.today().isoformat()
    if _token_stats.get("date") != today:
        _token_stats["date"] = today
        _token_stats["models"] = {}


def get_token_summary() -> dict:
    _maybe_reset_token_stats()
    total_prompt     = sum(v["prompt"]     for v in _token_stats["models"].values())
    total_completion = sum(v["completion"] for v in _token_stats["models"].values())
    total = total_prompt + total_completion
    return {
        "active_model":       _token_stats["active_model"],
        "prompt_tokens":      total_prompt,
        "completion_tokens":  total_completion,
        "total_tokens":       total,
        "daily_limit":        DAILY_TOKEN_LIMIT,
        "remaining_tokens":   max(DAILY_TOKEN_LIMIT - total, 0),
        "models":             _token_stats["models"],
    }


def format_token_status() -> str:
    stats = get_token_summary()
    total = stats["total_tokens"]
    limit = stats["daily_limit"]
    remaining = stats["remaining_tokens"]
    if total == 0:
        return (
            f"I have not tracked any chat-completion tokens since this Jarvis server started. "
            f"The local dashboard limit is {limit:,}, so locally it shows {remaining:,} remaining. "
            "I cannot read Groq's account-wide remaining quota from here."
        )
    return (
        f"Since this Jarvis server started, I have tracked {total:,} chat-completion tokens: "
        f"{stats['prompt_tokens']:,} in and {stats['completion_tokens']:,} out. "
        f"Against the local dashboard limit of {limit:,}, that leaves {remaining:,}. "
        "This is local tracking, not Groq's account-wide quota page."
    )

def _track_usage(model: str, usage) -> None:
    _maybe_reset_token_stats()
    _token_stats["active_model"] = model
    if model not in _token_stats["models"]:
        _token_stats["models"][model] = {"prompt": 0, "completion": 0, "calls": 0}
    if usage:
        _token_stats["models"][model]["prompt"]     += getattr(usage, "prompt_tokens",     0) or 0
        _token_stats["models"][model]["completion"] += getattr(usage, "completion_tokens", 0) or 0
    _token_stats["models"][model]["calls"] += 1


# Preference order for "deep" reasoning turns — first available wins
_DEEP_PROVIDER_ORDER = ["deepseek-pro", "openai", "gemini", "deepseek", "groq"]


def _deep_provider_key() -> str:
    for key in _DEEP_PROVIDER_ORDER:
        if key in MODEL_PROFILES:
            return key
    return ACTIVE_PROVIDER


def call_llm(messages: list, deep: bool = False, max_tokens: int | None = None) -> str:
    # 0. Deep turns escalate to the strongest configured brain for this one call
    if deep:
        deep_key = _deep_provider_key()
        if deep_key != ACTIVE_PROVIDER:
            try:
                dp = MODEL_PROFILES[deep_key]
                resp = dp["client"].chat.completions.create(
                    model=dp["model"],
                    messages=messages,
                    max_tokens=max_tokens or max(LLM_MAX_TOKENS, 1024),
                    temperature=LLM_TEMPERATURE,
                )
                _track_usage(dp["model"], resp.usage)
                return resp.choices[0].message.content or ""
            except Exception as e:
                if not _is_recoverable(str(e)):
                    raise
                print(f"Deep model failed ({deep_key}): {e}")

    # 1. Try primary model
    try:
        active_profile = MODEL_PROFILES[ACTIVE_PROVIDER]
        resp = active_profile["client"].chat.completions.create(
            model=active_profile["model"],
            messages=messages,
            max_tokens=max_tokens or LLM_MAX_TOKENS,
            temperature=LLM_TEMPERATURE,
        )
        _track_usage(active_profile["model"], resp.usage)
        return resp.choices[0].message.content or ""
    except Exception as e:
        if not _is_recoverable(str(e)):
            raise
        print(f"Primary model failed ({ACTIVE_MODEL}): {e}")

    # 2. Try other configured provider profiles before provider-specific fallbacks
    for provider_key, profile in MODEL_PROFILES.items():
        if provider_key == ACTIVE_PROVIDER:
            continue
        try:
            print(f"  Trying {profile['label']} fallback: {profile['model']}")
            resp = profile["client"].chat.completions.create(
                model=profile["model"],
                messages=messages,
                max_tokens=LLM_MAX_TOKENS,
                temperature=LLM_TEMPERATURE,
            )
            _track_usage(profile["model"], resp.usage)
            return resp.choices[0].message.content or ""
        except Exception as pe:
            if not _is_recoverable(str(pe)):
                raise
            print(f"  {profile['label']} fallback failed ({profile['model']}): {pe}")
            continue

    # 3. Try Groq fallback chain
    if not groq_client:
        raise RuntimeError("No fallback chat models are available right now.")

    for fallback in GROQ_FALLBACK_CHAIN:
        try:
            print(f"  Trying Groq fallback: {fallback}")
            resp = groq_client.chat.completions.create(
                model=fallback,
                messages=messages,
                max_tokens=LLM_MAX_TOKENS,
                temperature=LLM_TEMPERATURE,
            )
            _track_usage(fallback, resp.usage)
            return resp.choices[0].message.content or ""
        except Exception as fe:
            if not _is_recoverable(str(fe)):
                raise
            print(f"  Groq fallback failed ({fallback}): {fe}")
            continue

    # 3. Final fallback: Gemini
    if gemini_client:
        print(f"  All Groq models exhausted — falling back to Gemini ({GEMINI_MODEL})")
        try:
            resp = gemini_client.chat.completions.create(
                model=GEMINI_MODEL,
                messages=messages,
                max_tokens=LLM_MAX_TOKENS,
                temperature=LLM_TEMPERATURE,
            )
            _track_usage(GEMINI_MODEL, resp.usage)
            return resp.choices[0].message.content or ""
        except Exception as ge:
            print(f"  Gemini failed: {str(ge)[:120]}")
            # Fall through to OpenRouter

    # 4. Final fallback: OpenRouter (try multiple free models)
    if openrouter_client:
        openrouter_models = [
            OPENROUTER_MODEL,
            "google/gemma-3-27b-it:free",
            "mistralai/mistral-7b-instruct:free",
            "microsoft/phi-3-mini-128k-instruct:free",
        ]
        for or_model in openrouter_models:
            try:
                print(f"  Trying OpenRouter: {or_model}")
                resp = openrouter_client.chat.completions.create(
                    model=or_model,
                    messages=messages,
                    max_tokens=LLM_MAX_TOKENS,
                    temperature=LLM_TEMPERATURE,
                )
                _track_usage(or_model, resp.usage)
                return resp.choices[0].message.content or ""
            except Exception as oe:
                print(f"  OpenRouter {or_model} failed: {str(oe)[:200]}")
                continue

    raise RuntimeError(
        "I'm afraid all my neural pathways are saturated, sir. "
        "No models are available right now — please check your API keys or try again shortly."
    )


# ── HTTP ───────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "online", "provider": ACTIVE_PROVIDER, "model": ACTIVE_MODEL}


@app.get("/stats")
async def get_stats():
    return get_token_summary()


@app.get("/")
async def root():
    index_file = FRONTEND_DIST_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"status": "online", "provider": ACTIVE_PROVIDER, "model": ACTIVE_MODEL}


@app.post("/wake")
async def wake():
    dead = set()
    for ws in active_connections:
        try:
            await ws.send_json({"type": "wake"})
        except Exception:
            dead.add(ws)
    active_connections.difference_update(dead)
    return JSONResponse({"woken": len(active_connections)})


async def start_memory_consolidator():
    """Start the background Memory Agent."""
    global memory_consolidator_task
    if not MEMORY_CONSOLIDATOR_ENABLED:
        safe_print("[memory agent] disabled")
        return
    if memory_consolidator_task and not memory_consolidator_task.done():
        return
    interval_seconds = int(MEMORY_CONSOLIDATOR_INTERVAL_HOURS * 60 * 60)
    memory_consolidator_task = asyncio.create_task(
        memory_consolidator_loop(
            conversation_index_file=CONVERSATION_INDEX_FILE,
            memory_file=MEMORY_FILE,
            state_file=MEMORY_STATE_FILE,
            call_llm=call_llm,
            interval_seconds=interval_seconds,
            max_sessions=MEMORY_CONSOLIDATOR_MAX_SESSIONS,
            min_session_age_minutes=MEMORY_CONSOLIDATOR_SESSION_AGE_MINUTES,
            initial_delay_seconds=60,
            logger=safe_print,
        )
    )
    safe_print(
        "[memory agent] enabled "
        f"interval={MEMORY_CONSOLIDATOR_INTERVAL_HOURS}h "
        f"max_sessions={MEMORY_CONSOLIDATOR_MAX_SESSIONS}"
    )


async def start_self_improvement_agent():
    """Start the background Jarvis self-improvement agent."""
    global self_improvement_agent_task
    if not SELF_IMPROVEMENT_AGENT_ENABLED:
        safe_print("[self-improvement agent] disabled")
        return
    if self_improvement_agent_task and not self_improvement_agent_task.done():
        return
    interval_seconds = int(SELF_IMPROVEMENT_INTERVAL_HOURS * 60 * 60)
    self_improvement_agent_task = asyncio.create_task(
        self_improvement_agent_loop(
            conversation_index_file=CONVERSATION_INDEX_FILE,
            lessons_file=JARVIS_LESSONS_FILE,
            state_file=SELF_IMPROVEMENT_STATE_FILE,
            report_dir=IMPROVEMENT_REPORTS_DIR,
            call_llm=call_llm,
            interval_seconds=interval_seconds,
            max_sessions=SELF_IMPROVEMENT_MAX_SESSIONS,
            min_session_age_minutes=SELF_IMPROVEMENT_SESSION_AGE_MINUTES,
            lesson_limit=SELF_IMPROVEMENT_LESSON_LIMIT,
            initial_delay_seconds=180,
            logger=safe_print,
        )
    )
    safe_print(
        "[self-improvement agent] enabled "
        f"interval={SELF_IMPROVEMENT_INTERVAL_HOURS}h "
        f"max_sessions={SELF_IMPROVEMENT_MAX_SESSIONS}"
    )


# ── Proactivity engine ──────────────────────────────────────────────────────────

_proactive_state = {
    "announced_events": set(),   # calendar event ids already mentioned
    "seen_mail_ids": set(),      # mail ids known at last check (baseline)
    "baselined": False,          # have we recorded the initial mail backlog?
    "last_spoke": 0.0,           # epoch seconds of last proactive utterance
}


async def broadcast_proactive(text: str) -> None:
    """Speak an unprompted line to every connected client."""
    if not active_connections:
        return
    try:
        audio_b64 = base64.b64encode(await tts(text)).decode()
    except Exception:
        audio_b64 = None
    dead = set()
    for ws in list(active_connections):
        try:
            await ws.send_json({"type": "response", "text": text})
            if audio_b64:
                await ws.send_json({"type": "audio", "data": audio_b64})
        except Exception:
            dead.add(ws)
    active_connections.difference_update(dead)
    safe_print(f"JARVIS [proactive]: {text}")


def _in_quiet_hours() -> bool:
    hour = datetime.datetime.now().hour
    start, end = PROACTIVE_QUIET_START, PROACTIVE_QUIET_END
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end   # window wraps midnight


def _proactive_calendar_lines() -> list[str]:
    """Events starting within the lead window we haven't announced yet."""
    lines = []
    try:
        from plugins.calendar_agent import get_events
        events = get_events(days_ahead=1)
    except Exception:
        return lines
    now = datetime.datetime.now().astimezone()
    for ev in events:
        ev_id = ev.get("id", "")
        start_iso = ev.get("start_dt", "")
        if not ev_id or not start_iso or ev_id in _proactive_state["announced_events"]:
            continue
        try:
            start_dt = datetime.datetime.fromisoformat(start_iso)
            if start_dt.tzinfo is None:
                start_dt = start_dt.astimezone()
        except Exception:
            continue
        minutes = (start_dt - now).total_seconds() / 60
        if 0 < minutes <= PROACTIVE_EVENT_LEAD_MIN:
            mins = max(1, round(minutes))
            title = ev.get("title", "an event")
            loc = f" at {ev['location']}" if ev.get("location") else ""
            lines.append(f"Sir, {title}{loc} starts in {mins} minute{'s' if mins != 1 else ''}.")
            _proactive_state["announced_events"].add(ev_id)
    return lines


def _proactive_mail_lines() -> list[str]:
    """Newly-arrived high-priority mail since the last check."""
    if not PROACTIVE_MAIL_ALERTS:
        return []
    lines = []
    try:
        from plugins.gmail_agent import get_unread_mails
        mails = get_unread_mails(max_results=15)
    except Exception:
        return lines

    if not _proactive_state["baselined"]:
        # First run — learn the current backlog without announcing it
        _proactive_state["seen_mail_ids"] = {m["id"] for m in mails}
        _proactive_state["baselined"] = True
        return lines

    important = []
    for m in mails:
        if m["id"] in _proactive_state["seen_mail_ids"]:
            continue
        _proactive_state["seen_mail_ids"].add(m["id"])
        score, _ = _mail_priority(m)
        if score >= 3 and _mail_category(m) != "promotion":
            important.append(m)

    if important:
        top = important[0]
        sender = re.sub(r"<[^>]+>", "", top.get("sender", "")).strip() or "someone"
        subject = top.get("subject") or "(no subject)"
        if len(important) == 1:
            lines.append(f"Sir, a message from {sender} just arrived: {subject}.")
        else:
            lines.append(f"Sir, {len(important)} new messages worth your attention just arrived — the latest is from {sender}: {subject}.")
    return lines


async def proactive_agent_loop() -> None:
    """Background watcher that volunteers timely calendar/mail alerts."""
    await asyncio.sleep(20)   # let auth/connections settle
    loop = asyncio.get_event_loop()
    while True:
        try:
            quiet = _in_quiet_hours()
            recently_active = (time.time() - _last_user_activity) < 25
            cooled = (time.time() - _proactive_state["last_spoke"]) >= PROACTIVE_COOLDOWN_SECONDS
            if active_connections and not quiet and not recently_active and cooled:
                cal_lines = await loop.run_in_executor(None, _proactive_calendar_lines)
                mail_lines = await loop.run_in_executor(None, _proactive_mail_lines)
                lines = cal_lines + mail_lines
                if lines:
                    await broadcast_proactive(" ".join(lines[:2]))
                    _proactive_state["last_spoke"] = time.time()
            elif quiet:
                # Keep mail baseline fresh during quiet hours so morning isn't a flood
                await loop.run_in_executor(None, _proactive_mail_lines)
        except Exception as exc:
            safe_print(f"[proactive agent] failed: {exc}")
        await asyncio.sleep(max(30, PROACTIVE_INTERVAL_SECONDS))


async def start_proactive_agent():
    global proactive_agent_task
    if not PROACTIVE_AGENT_ENABLED:
        safe_print("[proactive agent] disabled")
        return
    if proactive_agent_task and not proactive_agent_task.done():
        return
    proactive_agent_task = asyncio.create_task(proactive_agent_loop())
    safe_print(
        "[proactive agent] enabled "
        f"interval={PROACTIVE_INTERVAL_SECONDS}s lead={PROACTIVE_EVENT_LEAD_MIN}m "
        f"cooldown={PROACTIVE_COOLDOWN_SECONDS}s quiet={PROACTIVE_QUIET_START}-{PROACTIVE_QUIET_END}"
    )


@asynccontextmanager
async def jarvis_lifespan(_app: FastAPI):
    await start_memory_consolidator()
    await start_self_improvement_agent()
    await start_proactive_agent()
    try:
        yield
    finally:
        if memory_consolidator_task and not memory_consolidator_task.done():
            memory_consolidator_task.cancel()
            try:
                await memory_consolidator_task
            except asyncio.CancelledError:
                pass
        if self_improvement_agent_task and not self_improvement_agent_task.done():
            self_improvement_agent_task.cancel()
            try:
                await self_improvement_agent_task
            except asyncio.CancelledError:
                pass
        if proactive_agent_task and not proactive_agent_task.done():
            proactive_agent_task.cancel()
            try:
                await proactive_agent_task
            except asyncio.CancelledError:
                pass


app.router.lifespan_context = jarvis_lifespan


# ── WebSocket ──────────────────────────────────────────────────────────────────

_MALAYALAM_INTENT_PHRASES = re.compile(
    r"\b(in malayalam|malayalam lo|malayalam il|malayalamil|"
    r"malayalam news|kerala news|keralam|"
    r"speak malayalam|reply in malayalam|respond in malayalam|"
    r"പറ|വാ|എന്ത്|എങ്ങനെ)\b",
    re.IGNORECASE
)

def detect_malayalam_request(text: str) -> bool:
    """Only switch to Malayalam when user actually wants a Malayalam response."""
    # Contains Malayalam Unicode script → definitely Malayalam
    if any("\u0D00" <= ch <= "\u0D7F" for ch in text):
        return True
    # Explicit intent phrases
    return bool(_MALAYALAM_INTENT_PHRASES.search(text))


async def run_startup_briefing(ws: WebSocket, conversation: list, session: dict) -> None:
    """Fetch today's world + AI news and deliver a spoken startup briefing."""
    now = datetime.datetime.now()
    greeting = "Good morning" if now.hour < 12 else "Good afternoon" if now.hour < 17 else "Good evening"

    await ws.send_json({"type": "thinking"})
    await ws.send_json({"type": "status", "message": "Fetching today's news..."})

    try:
        world_news = search_web("top world news headlines today")
        ai_news    = search_web("latest artificial intelligence AI news today")
    except Exception:
        return

    briefing_messages = [
        conversation[0],
        {
            "role": "user",
            "content": (
                f"Deliver a spoken startup briefing. "
                f"Start with '{greeting}, sir.' then state the time and date naturally. "
                f"Cover the 3-4 most important world headlines and 2-3 key AI developments — "
                f"pick only the most relevant and interesting stories. "
                f"Keep it under 90 seconds of speech. Conversational English, no bullets, no markdown. "
                f"End by saying they can ask you to elaborate on any story.\n\n"
                f"WORLD NEWS:\n{world_news[:900]}\n\nAI NEWS:\n{ai_news[:900]}"
            ),
        },
    ]

    spoken = clean_for_speech(await asyncio.get_event_loop().run_in_executor(None, call_llm, briefing_messages))
    if not spoken:
        return

    # Don't persist briefing in main conversation — it bloats every subsequent call

    log_message("jarvis", f"[BRIEFING] {spoken}", session)
    safe_print(f"JARVIS [briefing]: {spoken[:120]}...")

    await ws.send_json({"type": "response", "text": spoken})
    await ws.send_json({"type": "status", "message": "Speaking..."})
    audio = await tts(spoken)
    await ws.send_json({"type": "audio", "data": base64.b64encode(audio).decode()})


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    active_connections.add(ws)
    session = create_conversation_session()
    conversation = [{"role": "system", "content": build_system_prompt(session_id=session["id"])}]
    # Carry the tail of the last recent conversation so Jarvis isn't amnesiac
    prior_thread = load_recent_thread(exclude_session_id=session["id"])
    if prior_thread:
        conversation.extend(prior_thread)
        safe_print(f"[continuity] seeded {len(prior_thread)} prior messages")
    print("Client connected.")

    try:
        while True:
            data = await ws.receive_json()
            if data.get("type") == "extension_result":
                result_text = clean_for_speech(data.get("text", "").strip()) or "The extension finished, sir."
                conversation.append({"role": "assistant", "content": result_text})
                log_message("jarvis", result_text, session)
                await ws.send_json({"type": "response", "text": result_text})
                await ws.send_json({"type": "status", "message": "Speaking..."})
                audio = await tts(result_text)
                await ws.send_json({"type": "audio", "data": base64.b64encode(audio).decode()})
                continue

            message_type = data.get("type")
            if message_type == "audio_transcript":
                listen_mode = data.get("mode", "command")
                await ws.send_json({"type": "status", "message": "Checking wake word..." if listen_mode == "wake" else "Transcribing..."})
                try:
                    user_text = await asyncio.get_event_loop().run_in_executor(
                        None,
                        transcribe_audio_b64,
                        data.get("data", ""),
                        data.get("mime", "audio/webm"),
                    )
                except Exception as e:
                    safe_print(f"STT error: {e}")
                    await ws.send_json({"type": "stt_empty", "message": "Voice transcription failed"})
                    continue
                if not user_text:
                    await ws.send_json({"type": "stt_empty", "message": 'Waiting for "Jarvis"...' if listen_mode == "wake" else "Listening..."})
                    continue
                raw_audio_text = user_text
                user_text = normalize_voice_text(user_text)
                if user_text != raw_audio_text:
                    safe_print(f"[voice normalized] {raw_audio_text!r} -> {user_text!r}")
                if listen_mode == "wake":
                    wake_command = extract_wake_command(user_text)
                    if wake_command is None:
                        await ws.send_json({"type": "stt_empty", "message": 'Waiting for "Jarvis"...'})
                        continue
                    await ws.send_json({"type": "wake_detected", "text": user_text, "command": wake_command})
                    continue
                if is_stop_listening_command(user_text):
                    await ws.send_json({"type": "sleep_listening", "message": 'Standing by. Say "Jarvis" to wake me.'})
                    continue
                await ws.send_json({"type": "user_transcript", "text": user_text})
            elif message_type == "transcript":
                user_text = data.get("text", "").strip()
            else:
                continue

            if not user_text:
                continue

            global _last_user_activity
            _last_user_activity = time.time()   # suppress proactive interjections mid-turn

            raw_user_text = user_text
            user_text = normalize_voice_text(user_text)
            if user_text != raw_user_text:
                safe_print(f"[voice normalized] {raw_user_text!r} -> {user_text!r}")

            wake_command = extract_wake_command(user_text)
            if wake_command is not None and not wake_command:
                await ws.send_json({"type": "wake_detected", "text": user_text, "command": ""})
                continue
            if wake_command:
                user_text = wake_command

            if is_stop_listening_command(user_text):
                await ws.send_json({"type": "sleep_listening", "message": 'Standing by. Say "Jarvis" to wake me.'})
                continue

            # Startup briefing trigger sent by the frontend on first activation
            if user_text == "__startup__":
                await run_startup_briefing(ws, conversation, session)
                continue

            # Detect Kerala/Malayalam requests — switch language + TTS voice
            is_malayalam = detect_malayalam_request(user_text)

            conversation[0] = {"role": "system", "content": build_system_prompt(user_text, session["id"])}
            safe_print(f"\nUser: {user_text}")
            log_message("user", user_text, session)
            auto_learn(user_text)  # silently extract any preference signals

            if is_self_correction_request(user_text):
                await ws.send_json({"type": "status", "message": "Running self-correction agent..."})
                await ws.send_json({"type": "thinking"})
            direct_self_correction_spoken = await direct_self_correction_answer(user_text, session)
            if direct_self_correction_spoken:
                conversation.append({"role": "user", "content": user_text})
                conversation.append({"role": "assistant", "content": direct_self_correction_spoken})
                log_message("jarvis", direct_self_correction_spoken, session)
                safe_print(f"JARVIS [self-correction direct]: {direct_self_correction_spoken}")
                await ws.send_json({"type": "response", "text": direct_self_correction_spoken})
                await ws.send_json({"type": "status", "message": "Speaking..."})
                audio = await tts(direct_self_correction_spoken)
                await ws.send_json({"type": "audio", "data": base64.b64encode(audio).decode()})
                continue

            direct_access_spoken = direct_access_capability_answer(user_text)
            if direct_access_spoken:
                conversation.append({"role": "user", "content": user_text})
                conversation.append({"role": "assistant", "content": direct_access_spoken})
                log_message("jarvis", direct_access_spoken, session)
                safe_print(f"JARVIS [access direct]: {direct_access_spoken}")
                await ws.send_json({"type": "response", "text": direct_access_spoken})
                await ws.send_json({"type": "status", "message": "Speaking..."})
                audio = await tts(direct_access_spoken)
                await ws.send_json({"type": "audio", "data": base64.b64encode(audio).decode()})
                continue

            direct_language_spoken = direct_nonenglish_fragment_answer(user_text)
            if direct_language_spoken:
                conversation.append({"role": "user", "content": user_text})
                conversation.append({"role": "assistant", "content": direct_language_spoken})
                log_message("jarvis", direct_language_spoken, session)
                safe_print(f"JARVIS [language direct]: {direct_language_spoken}")
                await ws.send_json({"type": "response", "text": direct_language_spoken})
                await ws.send_json({"type": "status", "message": "Speaking..."})
                audio = await tts(direct_language_spoken)
                await ws.send_json({"type": "audio", "data": base64.b64encode(audio).decode()})
                continue

            # ── Gmail send confirmation gate ────────────────────────────────
            global _pending_gmail_send
            if _pending_gmail_send:
                if _is_gmail_confirmation(user_text):
                    await ws.send_json({"type": "status", "message": "Sending..."})
                    try:
                        from plugins.gmail_agent import send_reply as _gmail_send
                        _result = _gmail_send(_pending_gmail_send["mail_id"], _pending_gmail_send["body"])
                        spoken = f"Done, sir. {_result}"
                    except Exception as _e:
                        spoken = f"I couldn't send that, sir. {_e}"
                    finally:
                        _pending_gmail_send = None
                    conversation.append({"role": "assistant", "content": spoken})
                    log_message("jarvis", spoken, session)
                    safe_print(f"JARVIS [gmail send]: {spoken}")
                    await ws.send_json({"type": "response", "text": spoken})
                    await ws.send_json({"type": "status", "message": "Speaking..."})
                    audio = await tts(spoken)
                    await ws.send_json({"type": "audio", "data": base64.b64encode(audio).decode()})
                    continue
                elif _is_gmail_cancellation(user_text):
                    _pending_gmail_send = None
                    spoken = "Draft discarded, sir. Anything else?"
                    conversation.append({"role": "assistant", "content": spoken})
                    log_message("jarvis", spoken, session)
                    await ws.send_json({"type": "response", "text": spoken})
                    await ws.send_json({"type": "status", "message": "Speaking..."})
                    audio = await tts(spoken)
                    await ws.send_json({"type": "audio", "data": base64.b64encode(audio).decode()})
                    continue
            # ── End Gmail gate ──────────────────────────────────────────────

            direct_combo_spoken = await direct_mail_calendar_answer(user_text)
            if direct_combo_spoken:
                conversation.append({"role": "user", "content": user_text})
                conversation.append({"role": "assistant", "content": direct_combo_spoken})
                log_message("jarvis", direct_combo_spoken, session)
                safe_print(f"JARVIS [mail+calendar direct]: {direct_combo_spoken}")
                await ws.send_json({"type": "response", "text": direct_combo_spoken})
                await ws.send_json({"type": "status", "message": "Speaking..."})
                audio = await tts(direct_combo_spoken)
                await ws.send_json({"type": "audio", "data": base64.b64encode(audio).decode()})
                continue

            direct_calendar_spoken = await direct_calendar_answer(user_text)
            if direct_calendar_spoken:
                conversation.append({"role": "user", "content": user_text})
                conversation.append({"role": "assistant", "content": direct_calendar_spoken})
                log_message("jarvis", direct_calendar_spoken, session)
                safe_print(f"JARVIS [calendar direct]: {direct_calendar_spoken}")
                await ws.send_json({"type": "response", "text": direct_calendar_spoken})
                await ws.send_json({"type": "status", "message": "Speaking..."})
                audio = await tts(direct_calendar_spoken)
                await ws.send_json({"type": "audio", "data": base64.b64encode(audio).decode()})
                continue

            direct_mail_spoken = await direct_gmail_answer(user_text)
            if direct_mail_spoken:
                conversation.append({"role": "user", "content": user_text})
                conversation.append({"role": "assistant", "content": direct_mail_spoken})
                log_message("jarvis", direct_mail_spoken, session)
                safe_print(f"JARVIS [gmail direct]: {direct_mail_spoken}")
                await ws.send_json({"type": "response", "text": direct_mail_spoken})
                await ws.send_json({"type": "status", "message": "Speaking..."})
                audio = await tts(direct_mail_spoken)
                await ws.send_json({"type": "audio", "data": base64.b64encode(audio).decode()})
                continue

            conversation.append({"role": "user", "content": user_text})

            direct_vision_query = detect_direct_screen_vision_request(user_text)
            if direct_vision_query:
                await ws.send_json({"type": "status", "message": "Looking at your screen..."})
                spoken = await see_screen(direct_vision_query)
                conversation.append({"role": "assistant", "content": spoken})
                log_message("jarvis", spoken, session)
                safe_print(f"JARVIS [vision]: {spoken}")
                await ws.send_json({"type": "response", "text": spoken})
                await ws.send_json({"type": "status", "message": "Speaking..."})
                audio = await tts(spoken)
                await ws.send_json({"type": "audio", "data": base64.b64encode(audio).decode()})
                continue

            direct_screen_action = detect_direct_screen_request(user_text)
            if direct_screen_action:
                if direct_screen_action == "close":
                    await close_screen("", ws)
                    spoken = "Screen cleared, sir."
                elif direct_screen_action == "college":
                    await ws.send_json({"type": "status", "message": "Fetching FAU mails..."})
                    spoken = await gmail_search_screen("{from:fau.de from:fau.edu fau.de fau.edu fau}", ws)
                elif direct_screen_action == "mail_context":
                    if _last_mail_context:
                        await ws.send_json({"type": "status", "message": "Displaying selected mail..."})
                        spoken = await pitch_mail(_last_mail_context["id"], ws)
                    else:
                        spoken = "I do not have a real mail selected yet, sir. Ask me to check your mailbox first."
                elif direct_screen_action == "calendar_today":
                    await ws.send_json({"type": "status", "message": "Checking calendar..."})
                    spoken = await calendar_today_screen("", ws)
                elif direct_screen_action == "calendar_tomorrow":
                    await ws.send_json({"type": "status", "message": "Checking calendar..."})
                    spoken = await calendar_tomorrow_screen("", ws)
                elif direct_screen_action == "calendar":
                    await ws.send_json({"type": "status", "message": "Checking calendar..."})
                    spoken = await calendar_screen("", ws)
                elif direct_screen_action.startswith("sender:"):
                    sender_query = direct_screen_action[7:]
                    cached = _lookup_cached_mail(sender_query)
                    if cached:
                        await ws.send_json({"type": "status", "message": "Displaying mail..."})
                        spoken = await pitch_mail(cached["id"], ws)
                    else:
                        await ws.send_json({"type": "status", "message": "Searching mail..."})
                        spoken = await gmail_search_screen(sender_query, ws)
                else:  # inbox
                    await ws.send_json({"type": "status", "message": "Fetching inbox..."})
                    if re.search(r"\b(them|those|these|all of them|that list)\b", user_text.lower()) and _last_mail_list:
                        spoken = await display_mails_screen(_last_mail_list, ws, _last_mail_list_label)
                    else:
                        spoken = await gmail_screen("", ws)
                conversation.append({"role": "assistant", "content": spoken})
                log_message("jarvis", spoken, session)
                safe_print(f"JARVIS [screen]: {spoken}")
                await ws.send_json({"type": "response", "text": spoken})
                await ws.send_json({"type": "status", "message": "Speaking..."})
                audio = await tts(spoken)
                await ws.send_json({"type": "audio", "data": base64.b64encode(audio).decode()})
                continue

            direct_youtube_query = detect_direct_youtube_request(user_text)
            if direct_youtube_query:
                await ws.send_json({"type": "status", "message": "Opening YouTube..."})
                tool_result = await play_youtube(direct_youtube_query)
                spoken = f"Opening it on YouTube now, sir. I picked the best match for {direct_youtube_query}."
                conversation.append({"role": "assistant", "content": spoken})
                log_message("jarvis", spoken, session)
                safe_print(f"JARVIS: {spoken} [{tool_result}]")
                await ws.send_json({"type": "response", "text": spoken})
                await ws.send_json({"type": "status", "message": "Speaking..."})
                audio = await tts(spoken)
                await ws.send_json({"type": "audio", "data": base64.b64encode(audio).decode()})
                continue

            direct_youtube_action = await detect_direct_youtube_control(user_text)
            if direct_youtube_action:
                await ws.send_json({"type": "status", "message": "Controlling YouTube..."})
                tool_result = await youtube_control(direct_youtube_action)
                spoken = f"{tool_result}."
                conversation.append({"role": "assistant", "content": spoken})
                log_message("jarvis", spoken, session)
                safe_print(f"JARVIS: {spoken}")
                await ws.send_json({"type": "response", "text": spoken})
                await ws.send_json({"type": "status", "message": "Speaking..."})
                audio = await tts(spoken)
                await ws.send_json({"type": "audio", "data": base64.b64encode(audio).decode()})
                continue

            # Direct bypass for simple questions that should NEVER reach the LLM
            _ul = user_text.lower().strip().rstrip("?!.")
            _meta_model = re.search(r"\b(which|what)\b.{0,20}\b(model|brain|llm|ai)\b", _ul)
            _meta_token = re.search(r"\b(tokens?|token\s+usage|quota)\b", _ul)
            # "can you hear me / do you hear me / you can hear me right" and mis-hears
            _meta_hear = bool(re.search(r"\bhear (me|you)\b", _ul) or re.search(r"\b(can|do|are) you hear", _ul))
            _meta_check = re.search(
                r"^(can you hear me|hear me|do you hear me|are you there|are you online|"
                r"are you working|are you listening|hello|hi|hey|testing|test|yo|sup|"
                r"what'?s up|how are you|how'?s it going|you there|still there|"
                r"you alive|you awake|good morning|good afternoon|good evening|good night|"
                r"thanks|thank you|thanks jarvis|thank you jarvis|jarvis)"
                r"(\s+(now|jarvis|buddy|man|bro|pal|there))?\.?$", _ul
            )
            _model_switch = detect_model_switch_request(user_text)
            if _model_switch:
                if _model_switch == "__unknown__":
                    _available = ", ".join(p["label"] for p in MODEL_PROFILES.values())
                    spoken = f"Which brain would you like, sir? Available: {_available}."
                else:
                    try:
                        spoken = _set_active_model(_model_switch)
                    except ValueError as exc:
                        spoken = str(exc)
                conversation.append({"role": "assistant", "content": spoken})
                log_message("jarvis", spoken, session)
                safe_print(f"JARVIS [model switch]: {spoken}")
                await ws.send_json({"type": "response", "text": spoken})
                await ws.send_json({"type": "status", "message": "Speaking..."})
                audio = await tts(spoken)
                await ws.send_json({"type": "audio", "data": base64.b64encode(audio).decode()})
                continue
            if _meta_hear:
                spoken = "Loud and clear, sir — I hear you over the microphone."
                conversation.append({"role": "assistant", "content": spoken})
                log_message("jarvis", spoken, session)
                safe_print(f"JARVIS [meta hear]: {spoken}")
                await ws.send_json({"type": "response", "text": spoken})
                await ws.send_json({"type": "status", "message": "Speaking..."})
                audio = await tts(spoken)
                await ws.send_json({"type": "audio", "data": base64.b64encode(audio).decode()})
                continue
            if _meta_model:
                spoken = f"Running on {MODEL_PROFILES[ACTIVE_PROVIDER]['label']} using {ACTIVE_MODEL}, sir."
                conversation.append({"role": "assistant", "content": spoken})
                log_message("jarvis", spoken, session)
                safe_print(f"JARVIS [meta]: {spoken}")
                await ws.send_json({"type": "response", "text": spoken})
                await ws.send_json({"type": "status", "message": "Speaking..."})
                audio = await tts(spoken)
                await ws.send_json({"type": "audio", "data": base64.b64encode(audio).decode()})
                continue
            if _meta_token:
                spoken = format_token_status()
                conversation.append({"role": "assistant", "content": spoken})
                log_message("jarvis", spoken, session)
                safe_print(f"JARVIS [meta]: {spoken}")
                await ws.send_json({"type": "response", "text": spoken})
                await ws.send_json({"type": "status", "message": "Speaking..."})
                audio = await tts(spoken)
                await ws.send_json({"type": "audio", "data": base64.b64encode(audio).decode()})
                continue
            if _meta_check:
                spoken = "Loud and clear, sir."
                conversation.append({"role": "assistant", "content": spoken})
                log_message("jarvis", spoken, session)
                safe_print(f"JARVIS [direct]: {spoken}")
                await ws.send_json({"type": "response", "text": spoken})
                await ws.send_json({"type": "status", "message": "Speaking..."})
                audio = await tts(spoken)
                await ws.send_json({"type": "audio", "data": base64.b64encode(audio).decode()})
                continue

            # FAU mail extension disabled — extension not installed, causes 15s hang
            # direct_fau_mail_command = detect_direct_fau_mail_request(user_text)
            # if direct_fau_mail_command: ...

            await ws.send_json({"type": "thinking"})

            # Hard requests escalate to the strongest brain and get more tool steps.
            is_complex = bool(re.search(
                r"\b(write|build|create|code|debug|fix|design|plan|analy[sz]e|explain|"
                r"compare|research|summari[sz]e|draft|refactor|implement|why|how does|"
                r"step by step|walk me through)\b",
                user_text.lower(),
            )) and len(user_text) > 25
            tool_budget = max(MAX_TOOL_STEPS, 4) if is_complex else MAX_TOOL_STEPS

            try:
                spoken = ""
                for _ in range(tool_budget):
                    # Keep only the recent thread; older turns are logged on disk.
                    trimmed = [conversation[0]] + conversation[-MAX_CONTEXT_MESSAGES:]
                    reply = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: call_llm(trimmed, deep=is_complex)
                    )
                    safe_print(f"Raw: {reply[:120]}")
                    found, result, spoken = await execute_action(reply, ws)
                    if not found:
                        spoken = sanitize_unverified_action_reply(user_text, reply)
                        break
                    # Truncate tool results stored in history — large results (browse, search)
                    # stay in context for 4+ turns and are the biggest source of input token bloat
                    result_stored = result[:TOOL_RESULT_HISTORY_CHARS] + ("..." if len(result) > TOOL_RESULT_HISTORY_CHARS else "")
                    conversation.append({"role": "assistant", "content": reply})
                    conversation.append({
                        "role": "user",
                        "content": f"[Result: {result_stored}]"
                    })
                    await ws.send_json({"type": "thinking"})

                spoken = clean_for_speech(spoken) or "Done, sir."
                conversation.append({"role": "assistant", "content": spoken})
                # Prune conversation: keep system prompt + a compact recent window.
                max_kept = max(MAX_CONTEXT_MESSAGES + 2, 6)
                if len(conversation) > max_kept + 1:
                    conversation[1:] = conversation[-max_kept:]
                log_message("jarvis", spoken, session)
                safe_print(f"JARVIS: {spoken}")

                await ws.send_json({"type": "response", "text": spoken})
                await ws.send_json({"type": "status", "message": "Speaking..."})
                tts_voice = MALAYALAM_VOICE if is_malayalam else None
                audio = await tts(spoken, voice=tts_voice)
                await ws.send_json({"type": "audio", "data": base64.b64encode(audio).decode()})

            except WebSocketDisconnect:
                raise
            except Exception as e:
                import traceback; traceback.print_exc()
                err = f"I've hit a snag, sir. {e}"
                try:
                    await ws.send_json({"type": "response", "text": err})
                    audio = await tts(err)
                    await ws.send_json({"type": "audio", "data": base64.b64encode(audio).decode()})
                except Exception:
                    pass

    except WebSocketDisconnect:
        active_connections.discard(ws)
        print("Client disconnected.")


if __name__ == "__main__":
    import uvicorn

    # Auto-launch hotkey.py if not already running
    _hotkey_script = APP_DIR / "hotkey.py"
    _pythonw = PROJECT_ROOT / "venv" / "Scripts" / "pythonw.exe"
    if _hotkey_script.exists() and _pythonw.exists():
        import psutil
        _hotkey_running = any(
            "hotkey.py" in " ".join(p.cmdline())
            for p in psutil.process_iter(["cmdline"])
            if p.info["cmdline"]
        )
        if not _hotkey_running:
            subprocess.Popen(
                [str(_pythonw), str(_hotkey_script)],
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
                cwd=str(PROJECT_ROOT),
            )

    print("\n" + "=" * 55)
    print("  J.A.R.V.I.S. Online — Good to have you back, sir.")
    print("=" * 55 + "\n")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
