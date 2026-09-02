# JARVIS — Local Voice Assistant for Windows

A daily-use voice system I built to connect conversational models with tools on
my own computer. It combines streaming voice interaction, screen perception,
web and OS actions, Gmail and Calendar integrations, and persistent memory in a
single local application.

Press `Ctrl+Alt+Space`, speak, and the system can answer, show structured results
in the React interface, or execute an allowed action through the Python backend.

## What this project demonstrates

JARVIS is more than a chat interface. The engineering work is in coordinating
several components with different latency, state, and safety requirements:

- a WebSocket conversation loop between a React/Vite client and FastAPI;
- speech capture, transcription, model routing, tool execution, and neural TTS;
- a small, inspectable action protocol for browser, file, search, vision, email,
  calendar, media, and OS tools;
- persistent conversation and preference memory;
- scheduled memory-consolidation, self-review, and proactive-notification jobs;
- provider switching and fallbacks when a model is unavailable or rate-limited.

It is a personal Windows system that I actively use, not a hosted multi-user
service.

## System loop

```text
voice input
    ↓
React interface ── WebSocket ── FastAPI backend
                                      ↓
                                model router
                                      ↓
                             parsed tool action
                                      ↓
          web · screen · files · OS · Gmail · Calendar · YouTube
                                      ↓
                         structured UI + spoken response
```

## Selected engineering decisions

### Inspectable tool protocol

Tools are exposed through a compact `<<ACTION: …>>` protocol. The backend parses
the requested action, routes it to a specific implementation, and returns the
result to the conversation loop. The format is intentionally simple enough to
inspect while debugging a failed action.

### Local-first state

Conversation history, learned preferences, and runtime state remain on the
machine. A scheduled three-stage memory process—Extractor, Judge, Writer—turns
older conversations into a smaller set of durable facts while rejecting noisy
or private candidates.

### Bounded self-review

A background process reviews repeated failure patterns and stores short lessons
for later prompts. It can recommend a code change, but it does not silently
modify the application.

### Confirmation at sensitive boundaries

Gmail integration can read and search mail, but replies are staged as drafts and
pass through a spoken confirmation gate. Screen captures are used for the
current request and are not stored.

## Capabilities

| Area | Implemented capability |
|---|---|
| Voice | Always-on listening, global wake shortcut, neural TTS, English and Malayalam responses |
| Web | DuckDuckGo search, page reading, and URL opening |
| Google | Gmail read/search/draft and Calendar read/add through OAuth2 |
| Browser and media | YouTube search/playback and controls through Chrome DevTools Protocol |
| Windows | App launching, media controls, volume, lock, and configured shell/file actions |
| Vision | On-demand description of the current screen |
| Memory | Facts, preferences, conversation history, and scheduled consolidation |
| Proactivity | Calendar and important-mail notifications with quiet hours and cooldowns |

## Architecture

```text
                 React + Vite voice UI
         Web Speech capture · orb · result panels
                          │
                       WebSocket
                          │
             FastAPI backend (backend/server.py)
                          │
       ┌──────────┬───────┼──────────┬───────────────┐
       ▼          ▼       ▼          ▼               ▼
  model router  actions  Google   memory store   background jobs
  + fallbacks   + tools  OAuth2   + history      + notifications
```

**Core stack:** Python · FastAPI · WebSockets · React 18 · Vite · Edge TTS ·
Chrome DevTools Protocol · Gmail/Calendar APIs.

## Repository guide

| Path | Responsibility |
|---|---|
| [`backend/server.py`](backend/server.py) | FastAPI app, WebSocket loop, model routing, action parsing, and tool execution |
| [`backend/core/`](backend/core/) | Voice normalization, memory consolidation, verification, and self-review |
| [`backend/plugins/`](backend/plugins/) | Gmail and Calendar integrations |
| [`backend/tools/`](backend/tools/) | Focused tool implementations such as mail triage |
| [`frontend/src/`](frontend/src/) | Voice interface, animated orb, connection state, and result panels |
| [`extensions/chrome/fau-mail-agent/`](extensions/chrome/fau-mail-agent/) | Browser extension for FAU mail workflows |
| [`config/.env.example`](config/.env.example) | Non-secret configuration template |
| [`docs/PROJECT_OVERVIEW.md`](docs/PROJECT_OVERVIEW.md) | Detailed feature and configuration reference |

## Run it on Windows

Prerequisites: Python 3, Node.js/npm, and your own model-provider credentials.
Google OAuth credentials are only required for Gmail and Calendar features.

```bat
git clone https://github.com/midhun9901/jarvis.git
cd jarvis
setup.bat
```

The setup script creates the Python environment, installs backend and frontend
dependencies, copies `config/.env.example` to `config/.env`, and opens the local
configuration file. After adding the providers you intend to use:

```bat
start_jarvis.bat
```

The launcher starts the backend on port 8000, the Vite interface on port 5173,
and the global hotkey listener, then opens the interface as a standalone browser
window.

## Security and privacy boundaries

- API keys and OAuth credentials are loaded from ignored local files; no secrets
  are stored in this repository.
- Gmail replies are drafted before confirmation rather than sent immediately.
- Screen images are handled for the active request and are not persisted.
- Background self-review can write prompt lessons, not arbitrary code changes.
- This is a trusted, single-user local tool. Shell and filesystem actions should
  not be exposed to an untrusted network or shared deployment.

## Current limitations

- Windows-specific launcher, global hotkey, and OS integrations.
- Browser media control depends on a local Chromium debugging connection.
- Cloud model, speech, search, and Google integrations still depend on their
  respective services and quotas.
- The backend remains intentionally direct and readable, but several concerns
  still meet in one large server module and would benefit from further isolation.

## Status

Active personal project. The design goal is practical daily utility: fast voice
interaction, visible tool behavior, persistent context, and explicit boundaries
around sensitive actions.
