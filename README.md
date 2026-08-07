# JARVIS — a local voice AI assistant

An always-on, voice-driven AI assistant that runs on my own machine. Talk to it, and it searches the web, reads and drafts email, manages my calendar, controls the browser and OS, looks at my screen, remembers what matters across sessions, and even studies its own past mistakes to get better. Python backend, React voice UI, pluggable LLM "brains."

> Wake with `Ctrl+Alt+Space` → speak → it acts. British neural voice, an animated orb, and it switches to Malayalam when I ask about anything Kerala-related.

---

## Why it's interesting

Most "assistant" projects wrap a chat model. This one is a small **agent system** with a few parts I'm proud of:

- **🧠 Persistent memory with a background agent.** A memory-consolidator runs on a schedule, reads older conversations, and in three stages — *Extractor → Judge → Writer* — pulls out durable facts/preferences while rejecting junk and anything private, then saves them for future prompts.
- **🔁 Self-improvement agent.** It reviews past conversations for repeated failure patterns (hallucination, wrong tool, mishears, verbosity…), writes itself tiny behavioural "lessons," and injects the most relevant one into future prompts. It recommends code fixes but never applies them silently.
- **📣 Proactive agent.** Volunteers timely nudges without being asked — an upcoming calendar event, a newly-arrived important email — while respecting quiet hours and staying silent mid-conversation.
- **👁 Screen vision.** "What's on my screen?" captures the monitor and answers through a vision model. Screenshots are used for that one request and never stored.
- **🔌 Pluggable brains, switchable by voice.** "Switch to DeepSeek", "use the Pro model" — DeepSeek / Groq / Gemini / OpenAI / OpenRouter behind one interface, with a fallback chain when a provider is rate-limited.

## What it can do

| Area | Capability |
|------|------------|
| **Voice I/O** | Always-on listening, neural TTS, global wake hotkey, auto-sleep, English + Malayalam |
| **Web** | DuckDuckGo search, fetch & read pages, open URLs |
| **Google** | Gmail read/search/**draft** (with a spoken confirmation gate) + Calendar read/add, via OAuth2 |
| **Browser/OS** | YouTube search & playback control via Chrome DevTools Protocol, launch apps, shell commands, volume/media/lock |
| **Files** | Read / write / search the filesystem by voice |
| **Vision** | Describe the current screen on request |
| **Memory** | Remember facts, recall them, search past conversations |

Tools are exposed to the model through a lightweight `<<ACTION: …>>` tag protocol that the backend parses and executes.

## Architecture

```
                 ┌──────────────── React + Vite voice UI (orb, panels) ───────────────┐
   mic audio ──▶ │  Web Speech capture  ──ws──▶                          ◀──ws── audio │
                 └───────────────────────────────┬───────────────────────────────────┘
                                                 ▼
                            FastAPI backend  (backend/server.py)
                                                 │
        ┌───────────────┬────────────────────────┼───────────────┬───────────────────┐
        ▼               ▼                         ▼               ▼                   ▼
   LLM router      <<ACTION>>              Gmail / Calendar   memory +           background agents
 (DeepSeek/Groq/   tool executor           (OAuth2)          conversation      (consolidator,
  Gemini/…)        (search, browse,                          store             self-improvement,
                    files, YouTube CDP,                                         proactive)
                    vision, OS control)
```

**Stack:** Python · FastAPI + WebSockets · React 18 + Vite · Groq Whisper (STT) · Edge TTS · Chrome DevTools Protocol · Google Gmail/Calendar APIs.

## Running it

You supply your own API keys and Google OAuth app; there are **no secrets in this repo**.

```bash
# 1. copy the template and fill in your keys
cp config/.env.example config/.env
# 2. add your Google OAuth files to config/  (credentials.json, token.json)
# 3. launch backend + frontend + hotkey listener
./start_jarvis.bat
```

Full configuration reference (LLM providers, TTS, memory/self-improvement/proactivity tuning) is in [`docs/PROJECT_OVERVIEW.md`](docs/PROJECT_OVERVIEW.md).

## Notes

A personal project I built and use daily on Windows. The design goal was a genuinely *useful* assistant — memory, agency, and real integrations — not a demo. It's deliberately hackable: one readable backend, a small tool protocol, and config-driven behaviour.
