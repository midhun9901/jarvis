# J.A.R.V.I.S.
_Just A Rather Very Intelligent System_
_Last updated: 2026-04-14_

---

## What is this

A real-life JARVIS voice AI assistant running locally on Windows 11.
- Always-on mic, British male voice (Ryan Neural), glowing orb UI
- Wake from anywhere with **Ctrl+Alt+Space**
- Auto-sleeps after 5 minutes of silence
- Speaks Malayalam for Kerala/Malayalam requests
- Learns preferences automatically
- Brain: Groq API (free tier) — `llama-3.3-70b-versatile`
- Frontend: React/Vite (port 5173)
- Backend: Python FastAPI (port 8000)
- Opens in **Microsoft Edge** (switched from Chrome)

---

## How to start

```powershell
.\start_jarvis.bat
```

Edge opens automatically. Backend on port 8000, frontend on port 5173.

### If port 8000 is already in use
```powershell
Get-Process -Name python,pythonw | Stop-Process -Force
```

---

## File structure

```
C:\PROJECTS\jarvis\
├── server.py                  # Python backend — ALL logic lives here
├── hotkey.py                  # Global hotkey (Ctrl+Alt+Space = wake/focus)
├── plugins/
│   ├── gmail_agent.py         # Gmail read/search/send via Google API
│   └── calendar_agent.py      # Google Calendar read/add via Google API
├── requirements.txt
├── .env                       # API keys — DO NOT COMMIT
├── credentials.json           # Google OAuth app credentials
├── token.json                 # Google OAuth token (auto-generated, do not delete)
├── memory.json                # Persistent user facts/preferences
├── conversation_index.json    # Index of all past conversations
├── conversations/             # Past conversations as markdown files
├── logs/                      # server.log, server_err.log, frontend.log
├── start_jarvis.bat           # Launch everything
├── JARVIS.md                  # This file
└── frontend/
    ├── src/App.jsx            # Main React app — voice, orb, WebSocket, screen panels
    ├── src/components/Orb.jsx
    └── src/App.css
```

---

## Current .env

```
GROK_API_KEY=<your Groq key>
GROK_MODEL=llama-3.3-70b-versatile

GEMINI_API_KEY=<your Gemini key>
GEMINI_MODEL=gemini-2.0-flash

OPENROUTER_API_KEY=
OPENROUTER_MODEL=

TTS_VOICE=en-GB-RyanNeural
TTS_RATE=+25%
OBSIDIAN_VAULT=C:/Users/Asus/Documents/Obsidian

LLM_MAX_TOKENS=2048
LLM_TEMPERATURE=0.7
MAX_TOOL_STEPS=3
MALAYALAM_VOICE=ml-IN-MidhunNeural

GOOGLE_MAPS_API_KEY=     ← optional, improves map embeds
```

---

## Architecture

```
User speaks
  → Edge Web Speech API
  → WebSocket (ws://localhost:8000/ws)
  → server.py
      → auto_learn() — silently extract preference signals
      → detect_direct_screen_request() — bypass LLM for screen commands
      → detect_direct_youtube_request/control() — bypass LLM for YouTube
      → detect Malayalam → switch voice + inject language instruction
      → execute_action() — parse <<ACTION:>> tags, run tool
      → call_llm() → Groq primary → fallback chain → Gemini
  → Edge TTS → MP3 → base64 → WebSocket → Edge plays audio
  → screen_display events → floating card panel in UI
```

### LLM fallback chain (in order)
1. `llama-3.3-70b-versatile` (primary, 100K tokens/day)
2. `llama-3.1-8b-instant`
3. `meta-llama/llama-4-scout-17b-16e-instruct`
4. `gemma2-9b-it`
5. `mistral-saba-24b`
6. `qwen-qwq-32b`
7. `gemini-2.0-flash` (final fallback)

All Groq models are free tier with separate daily quotas. Resets at midnight UTC.

---

## Tools JARVIS has

### Standard tools
| Tag | What it does |
|-----|-------------|
| `<<SEARCH: query>>` | DuckDuckGo web search |
| `<<BROWSE: url>>` | Fetch and read a webpage |
| `<<OPEN_URL: url>>` | Open URL in browser |
| `<<OPEN_APP: name>>` | Launch any Windows app |
| `<<PLAY_YOUTUBE: query>>` | Search YouTube and open best result |
| `<<YOUTUBE_CONTROL: action>>` | Pause/play/mute/fullscreen/seek YouTube |
| `<<RUN: command>>` | Run any shell command |
| `<<READ_FILE: path>>` | Read any file |
| `<<LIST_DIR: path>>` | List folder contents |
| `<<FIND_FILES: pattern in path>>` | Search files |
| `<<WRITE_FILE: {json}>>` | Create/edit any file |
| `<<BUILD: {json}>>` | Build full project on Desktop |
| `<<REMEMBER: fact>>` | Save to memory.json permanently |
| `<<REMIND: text>>` | Save a reminder |
| `<<HISTORY: query>>` | Search past conversations |
| `<<OBSIDIAN: query>>` | Search Obsidian vault notes |

### Gmail tools
| Tag | What it does |
|-----|-------------|
| `<<GMAIL_CHECK>>` | List unread inbox (with relative date labels) |
| `<<GMAIL_READ: mail_id>>` | Read full mail body |
| `<<GMAIL_SEARCH: query>>` | Search Gmail |
| `<<GMAIL_DRAFT: mail_id:body>>` | Stage a reply (asks for voice confirmation) |

### Screen / display tools
| Tag | What it does |
|-----|-------------|
| `<<GMAIL_SCREEN>>` | Show inbox as floating card in UI |
| `<<GMAIL_SEARCH_SCREEN: query>>` | Search Gmail + show on screen |
| `<<PITCH_MAIL: mail_id>>` | Show one specific mail on screen |
| `<<MAPS: origin\|destination>>` | Show directions on screen |
| `<<CALENDAR_SCREEN>>` | Show next 7 days of calendar on screen |
| `<<CALENDAR_TODAY>>` | Show today's events on screen |
| `<<CALENDAR_TOMORROW>>` | Show tomorrow's events on screen |
| `<<CLOSE_SCREEN>>` | Dismiss the screen panel |

### Calendar tools
| Tag | What it does |
|-----|-------------|
| `<<CALENDAR_CHECK>>` | Read upcoming events aloud (7 days) |
| `<<CALENDAR_DATE: today/tomorrow/YYYY-MM-DD>>` | Events on specific date |
| `<<CALENDAR_ADD: title\|date\|time\|mins\|location>>` | Add event to Google Calendar |

---

## Screen panel (floating card UI)

A 400px floating card appears bottom-right when JARVIS pitches content to screen.
Supports four content types:
- **map** — embedded Google Maps with route info and "Open in Maps" link
- **email** — full mail with sender/subject/date header + scrollable body
- **mails_list** — inbox or search results with relative date badges
- **calendar** — events grouped by day (TODAY, TOMORROW, Wednesday, etc.)

Voice commands that trigger it directly (bypass LLM):
- "show my calendar on screen" / "pitch calendar to screen"
- "show tomorrow's schedule on screen"
- "pitch my mails to screen" / "show inbox on screen"
- "show college mails on screen" → searches `from:fau.edu`
- "show mails from [name] on screen" → cache lookup by sender name
- "close the screen" / "exit" / "dismiss"

---

## Gmail + Calendar setup (Google OAuth)

Both use the same `credentials.json` + `token.json` OAuth flow.

### First-time setup (or after deleting token.json)
```powershell
cd c:\PROJECTS\jarvis
.\venv\Scripts\python.exe -c "from plugins.gmail_agent import _get_service; _get_service()"
```
A browser window opens → log in → click Allow. `token.json` is saved with Gmail + Calendar scopes.

### If re-authing (scope change, deleted profile, etc.)
Delete `token.json` first, then run the command above.

### credentials.json
Downloaded from Google Cloud Console → APIs & Services → Credentials → OAuth 2.0 Client ID (Desktop app).
Scopes needed: Gmail (readonly + send) + Calendar.

---

## Smart features added 2026-04-14

### Relative date labels on emails
Python converts raw RFC2822 email dates to human labels before the LLM sees them:
- `"Mon, 14 Apr 2026 09:23:11 +0200"` → `"TODAY 9:23 AM"`
- `"Tue, 15 Apr 2026 16:00:00 +0200"` → `"TOMORROW 4:00 PM"`
The LLM trusts these labels — no more date math errors.

### Session mail cache
After any Gmail check/search, sender names are indexed in memory.
"Show me the mail from Mathias on screen" → Python matches directly, no LLM guessing.

### Topic memory
JARVIS remembers the last discussed topic (calendar / inbox / college).
"Show it on screen" after talking about calendar → shows calendar, not inbox.

### Token efficiency
- System prompt trimmed from ~900 to ~420 tokens
- Conversation window capped at last 12 messages
- Wiki context capped at 1200 chars
- Result: ~50% less token burn per session, quotas last much longer

---

## Features

### Malayalam / Kerala mode
Say anything with Kerala/Malayalam keywords → JARVIS responds in Malayalam, switches to `ml-IN-MidhunNeural` voice, searches Kerala-specific news. Switches back automatically.

### Automatic preference learning
Scans every message for preference signals ("I prefer...", "I always use...", "I'm studying at...") and saves instantly to `memory.json`. Also uses `<<REMEMBER:>>` proactively mid-conversation.

### Sleep / wake
- Auto-sleeps after 5 minutes of silence
- **Ctrl+Alt+Space** from anywhere → brings Edge to front, wakes JARVIS
- Click the orb → wake

---

## Known limitations

- Groq free tier: 100K tokens/day on main model (resets midnight UTC)
- All free tier quotas can be exhausted with heavy use — wait for reset
- Google Maps embed works without API key but directions render better with one (set `GOOGLE_MAPS_API_KEY` in .env)
- Calendar OAuth requires browser window on first run

---

## User context

- Windows 11, PowerShell
- Uses Microsoft Edge (switched from Chrome 2026-04-14)
- Groq free tier + Gemini fallback
- Studies at FAU (fau.edu)
- Wants everything automated — no manual terminal steps
- Wants always-on listening like movie JARVIS

---

## User's projects (C:\PROJECTS)

| Project | Tech | Notes |
|---------|------|-------|
| jarvis | Python + React | This project |
| keralaconnect | Flutter | Mobile app |
| vase_project | Python/PyTorch | Image retrieval ML |
| vase_urn_project | Python | Vase retrieval variant |
| openvc | Python/YOLOv8 | Computer vision |
| audio visualisation kazhapp | HTML PWA | Audio visualizer |
| webpage_creation_projects | Node/React/Vite | Web projects |
| agents | misc | Various agents |

---

## Wiki — Persistent Memory Layer

```
wiki/
├── me.md           → who the user is, location, background
├── projects.md     → active projects
├── preferences.md  → voice style, automation habits, API constraints
├── capabilities.md → full tool list
└── fau.md          → FAU university context, FAUmail

raw/                → drop new source material here
raw/processed/      → ingested files moved here automatically
```

Edit wiki files directly — changes take effect on the next conversation turn (system prompt rebuilds per-request).

---

## How to continue in a new session

Paste this at the start of your new chat:

> "Read `C:\PROJECTS\jarvis\JARVIS.md` — then help me with..."
