# JARVIS — Voice AI Assistant

**Type:** Local Voice AI | **Platform:** Windows 11
**Status:** ~90% Complete, actively maintained (Apr 17, 2026)

---

## What It Is

A real-life JARVIS — always-on voice assistant running locally. British male voice (Ryan Neural), animated orb UI, deep OS integration. Speaks Malayalam for Kerala-related requests.

---

## Tech Stack

| Layer | Tech |
|-------|------|
| Backend | Python 3.x + FastAPI (Uvicorn, port 8000) |
| Frontend | React 18.2 + Vite (dev port 5173) |
| LLM | Groq API — llama-3.3-70b-versatile (primary) |
| LLM Fallbacks | llama-3.1-8b → Gemini → OpenRouter |
| TTS | Edge TTS (en-GB-RyanNeural, +25% speed) |
| STT | Browser Web Speech API |
| Browser Control | Chrome DevTools Protocol (CDP) via Microsoft Edge |
| Email/Calendar | Google Gmail + Calendar API (OAuth2) |
| Search | DuckDuckGo + BeautifulSoup scraping |

---

## Architecture

```
User speaks → Edge Web Speech API → WebSocket → server.py
  → auto_learn() + detect_malayalam()
  → detect_direct_screen_request() (bypass LLM if possible)
  → call_llm() with <<ACTION:>> tag system
  → execute_action() — parse and run tool commands
  → Edge TTS → MP3 → base64 → WebSocket → browser plays audio
  → screen_display events → floating card UI (email, calendar, maps)
```

---

## Features

### Voice I/O
- Always-on listening via Web Speech API
- Edge TTS with Malayalam support (auto-detects Kerala keywords)
- Wake: **Ctrl+Alt+Space** from anywhere (global hotkey)
- Auto-sleep after 5 min silence

### Content Tools (<<ACTION:>> Tags)
| Tag | Function |
|-----|----------|
| `<<SEARCH:query>>` | DuckDuckGo web search |
| `<<BROWSE:url>>` | Fetch & read webpage (BeautifulSoup) |
| `<<PLAY_YOUTUBE:query>>` | YouTube search + autoplay via CDP |
| `<<YOUTUBE_CONTROL:cmd>>` | pause / play / mute / seek / volume |
| `<<OPEN_URL:url>>` | Open URL in Edge |
| `<<OPEN_APP:name>>` | Launch Windows application |
| `<<RUN:cmd>>` | Execute shell command |
| `<<READ_FILE:path>>` | Read file contents |
| `<<WRITE_FILE:path>>` | Write to file |
| `<<LIST_DIR:path>>` | List directory |
| `<<FIND_FILES:pattern>>` | Search filesystem |

### Google Integration (OAuth2)
| Tag | Function |
|-----|----------|
| `<<GMAIL_CHECK>>` | List unread inbox |
| `<<GMAIL_READ:id>>` | Read specific email |
| `<<GMAIL_SEARCH:query>>` | Search mail |
| `<<GMAIL_DRAFT:json>>` | Stage reply (voice confirmation gate) |
| `<<CALENDAR_CHECK>>` | Show upcoming events |
| `<<CALENDAR_ADD:json>>` | Create calendar event |

### Memory & Learning
| Tag | Function |
|-----|----------|
| `<<REMEMBER:fact>>` | Save to memory.json |
| `<<REMIND:query>>` | Recall from memory |
| `<<HISTORY:query>>` | Search past conversations |

### Smart Features
- **Startup briefing** — world + AI news on every boot
- **Malayalam mode** — auto-detects Kerala/Malayalam keywords, responds in Malayalam
- **Relative date labels** — RFC2822 → "TODAY 9:23 AM"
- **Session mail cache** — matches sender names without extra LLM calls
- **Topic memory** — "Show it on screen" remembers last context
- **Fallback chain** — 70b → 8b → Gemini when rate-limited
- **Token optimization** — 900→420 system prompt tokens, 12-message conversation window

---

## Project Structure

```
jarvis/
├── server.py                  # ALL backend logic (2479 lines)
│                              #   - FastAPI app + WebSocket handler
│                              #   - LLM call with action parsing
│                              #   - Tool execution (search, browse, file I/O)
│                              #   - YouTube CDP control
│                              #   - Malayalam detection
│                              #   - Auto-learn from dialogue
│                              #   - Conversation persistence
├── hotkey.py                  # Global Ctrl+Alt+Space listener → POST /wake
├── ingest.py                  # Wiki ingestion script (LLM-driven updates)
├── start_jarvis.bat           # Launcher (backend + frontend + hotkey + Edge)
│
├── plugins/
│   ├── gmail_agent.py         # Gmail read/search/send (Google OAuth)
│   └── calendar_agent.py      # Calendar read/add (Google OAuth)
│
├── wiki/                      # System prompt knowledge base
│   ├── me.md                  # User identity/background
│   ├── projects.md            # Active projects list
│   ├── preferences.md         # Voice/automation preferences
│   ├── capabilities.md        # Tool documentation
│   └── fau.md                 # FAU university context
│
├── conversations/             # Past chats stored as markdown by date
├── conversation_index.json    # Searchable index of all sessions
├── memory.json                # Persistent facts/preferences (learned)
├── project_summaries.json     # Cached project summaries
│
├── frontend/
│   ├── src/
│   │   ├── App.jsx            # Main UI: voice button, orb, WebSocket, panels
│   │   ├── components/Orb.jsx # Canvas-based animated orb visualization
│   │   └── App.css
│   ├── package.json           # React + Vite
│   └── dist/                  # Built output (served at /assets)
│
├── .env                       # API keys (Groq, Gemini, OpenRouter, TTS config)
├── credentials.json           # Google OAuth app credentials
├── token.json                 # Google OAuth token (auto-generated)
└── logs/                      # server.log, server_err.log, frontend.log
```

---

## API Endpoints

| Route | Method | Purpose |
|-------|--------|---------|
| `/` | GET | Serve frontend `index.html` |
| `/assets/*` | GET | Serve built Vite JS/CSS |
| `/health` | GET | Liveness check |
| `/stats` | GET | Token usage (model, prompt/completion counts) |
| `/wake` | POST | Trigger wake-up (from hotkey.py) |
| `/ws` | WebSocket | Main conversation handler |

### WebSocket Message Types
| Type | Direction | Content |
|------|-----------|---------|
| `transcript` | Client→Server | User speech text |
| `response` | Server→Client | LLM reply text |
| `status` | Server→Client | "Searching...", "Speaking..." |
| `audio` | Server→Client | Base64 MP3 TTS audio |
| `screen_display` | Server→Client | Floating card data (email/calendar/maps) |
| `extension_result` | Client→Server | Chrome extension command result |

---

## Config Files

| File | Purpose |
|------|---------|
| `.env` | API keys, TTS voice/speed, LLM max tokens, temp, vault path |
| `credentials.json` | Google OAuth app ID/secret (from Cloud Console) |
| `token.json` | Google OAuth token (auto-saved on first auth) |
| `memory.json` | Facts/preferences learned from dialogue |
| `wiki/*.md` | System prompt knowledge base |
| `start_jarvis.bat` | Launch script |

---

## How to Run

```bash
# Option 1: Batch launcher
.\start_jarvis.bat

# Option 2: Manual
python server.py          # Backend on :8000
cd frontend && npm run dev # Frontend on :5173 (dev mode)
python hotkey.py          # Global hotkey listener
```

---

## Known Limitations

- Groq free tier: 100K tokens/day on main model (resets midnight UTC)
- All fallback quotas can exhaust with heavy use
- YouTube autoplay needs Edge to allow it
- No proactive calendar reminders
- No multi-device sync
- Monolithic `server.py` (2479 lines — all logic in one file)

---

## Recent Changes (Apr 14-17, 2026)

- Switched from Chrome to Microsoft Edge
- Added relative date labels on emails
- Session mail sender cache
- Topic memory for "show it on screen"
- Token efficiency: 900→420 system prompt tokens
- Conversation window capped at 12 messages
