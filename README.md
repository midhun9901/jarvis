# JARVIS

Local voice AI assistant with a Python backend, React voice UI, persistent memory, Gmail/Calendar helpers, and browser automation tools.

## Start

```powershell
.\start_jarvis.bat
```

The launcher starts:

- Backend: `backend/server.py` on port `8000`
- Frontend: `frontend/` on port `5173`
- Hotkey listener: `backend/hotkey.py`
- App window: Chrome preferred, Edge fallback

## Wake / Sleep

- `Ctrl+Alt+Space`: wake or focus Jarvis
- Click the orb: activate or wake
- Auto-sleep after 5 minutes of silence

## Main Folders

```text
backend/             Python backend, hotkey, ingest script, integrations
backend/plugins/     Gmail and Calendar API helpers
config/              .env, Google OAuth credentials, OAuth token
data/                Memory, conversations, wiki, project summaries, raw ingest files
docs/                Project overview and deeper notes
extensions/chrome/   Chrome extension projects
frontend/            React/Vite voice UI
logs/                Runtime logs
runtime/             Runtime browser profiles and generated caches
venv/                Python virtual environment
```

## Config

Put runtime keys in `config/.env`.

```env
JARVIS_LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_PRO_MODEL=deepseek-v4-pro
GROK_API_KEY=
GROK_MODEL=llama-3.3-70b-versatile
TTS_VOICE=en-GB-RyanNeural
TTS_RATE=+25%
MALAYALAM_VOICE=ml-IN-MidhunNeural
OBSIDIAN_VAULT=C:/PROJECTS/2nd_brain
SECOND_BRAIN_WIKI_DIR=C:/PROJECTS/2nd_brain/wiki
LLM_MAX_TOKENS=2048
LLM_TEMPERATURE=0.7
MAX_TOOL_STEPS=2
MAX_CONTEXT_MESSAGES=4
TOOL_RESULT_HISTORY_CHARS=350
PROMPT_MEMORY_FACTS=3
PROMPT_MEMORY_PREFS=3
PROMPT_WIKI_CHARS=500
MEMORY_CONSOLIDATOR_ENABLED=true
MEMORY_CONSOLIDATOR_INTERVAL_HOURS=5
MEMORY_CONSOLIDATOR_MAX_SESSIONS=12
MEMORY_CONSOLIDATOR_SESSION_AGE_MINUTES=10
SELF_IMPROVEMENT_AGENT_ENABLED=true
SELF_IMPROVEMENT_INTERVAL_HOURS=12
SELF_IMPROVEMENT_MAX_SESSIONS=6
SELF_IMPROVEMENT_SESSION_AGE_MINUTES=30
SELF_IMPROVEMENT_LESSON_LIMIT=5
DAILY_TOKEN_LIMIT=100000
```

`JARVIS_LLM_PROVIDER` controls the default chat brain. Use `deepseek`, `deepseek-pro`, `groq`, `gemini`, `openai`, or `openrouter` when the matching API key is configured.

The `MAX_CONTEXT_MESSAGES`, `TOOL_RESULT_HISTORY_CHARS`, and `PROMPT_*` settings keep Jarvis token-efficient without disabling memory or tools.

`OBSIDIAN_VAULT` points Jarvis note search at your second-brain vault. `SECOND_BRAIN_WIKI_DIR` points automatic context at curated second-brain pages. Keep automatic context aimed at `wiki/`, not `raw/` or `inbox/`, so Jarvis uses maintained summaries instead of private scratch notes or source dumps.

The memory consolidator is a background AI Memory Agent. Every `MEMORY_CONSOLIDATOR_INTERVAL_HOURS`, it reads older conversation logs and runs three stages: Extractor finds possible memories, Judge rejects junk/private/temporary items, and Writer saves clean durable facts/preferences/corrections to `data/memory.json`. It tracks processed sessions in `data/memory_state.json`, so it does not rescan everything every time.

The self-improvement agent studies older Jarvis conversations for repeated failure patterns. It classifies issues like hallucination, wrong tool, missed tool, voice mishear, tone, verbosity, memory, mail, calendar, model switching, and wake-word problems. It saves only tiny behavior lessons to `data/jarvis_lessons.json`, injects at most one recent lesson per category into future prompts, and writes implementation recommendations to `data/improvement_reports/`. It does not automatically rewrite code; code changes should still be reviewed and applied deliberately.

You can also run it manually at the end of a conversation by saying "deploy the self correction agent" or "run the self improvement agent." Manual runs process only the latest/current conversation, so they are much cheaper than the scheduled batch job.

Google OAuth files live in `config/`:

- `config/credentials.json`: Google Cloud OAuth client
- `config/token.json`: generated OAuth token

## Voice

The browser captures microphone audio and sends it to `backend/server.py`, which transcribes through Groq Whisper. Jarvis then responds through Edge TTS audio.

You can switch chat brains by voice:

- "Switch to DeepSeek"
- "Use DeepSeek Pro"
- "Switch brain to Groq"
- "What model are you running?"

## Tools

| Tag | Action |
|-----|--------|
| `<<SEARCH: q>>` | DuckDuckGo search |
| `<<BROWSE: url>>` | Fetch webpage |
| `<<OPEN_URL: url>>` | Open URL |
| `<<OPEN_APP: name>>` | Launch app |
| `<<PLAY_YOUTUBE: q>>` | Find and open a YouTube video |
| `<<YOUTUBE_CONTROL: act>>` | YouTube playback control |
| `<<RUN: cmd>>` | Shell command |
| `<<READ_FILE: path>>` | Read file |
| `<<WRITE_FILE: {json}>>` | Create or edit file |
| `<<REMEMBER: fact>>` | Save to `data/memory.json` |
| `<<HISTORY: q>>` | Search `data/conversations/` |
| `<<OBSIDIAN: q>>` | Search Obsidian vault |
| `<<SEE_SCREEN: q>>` | Look at the actual desktop and answer (vision) |
| `<<CONTROL: action>>` | System volume / media / lock / sleep |

## Vision

Ask "what's on my screen?", "what am I looking at?", or "read my screen" and Jarvis
captures the primary monitor and describes it through a vision-capable brain
(Gemini if `GEMINI_API_KEY` is set, otherwise OpenAI). Screenshots are sent to the
model for that one request and never stored.

## Device control

Spoken commands like "turn up the volume", "mute", "next track", "lock my computer",
or "go to sleep" drive system media keys and Windows power commands.

## Proactivity

A background agent volunteers timely alerts without being asked — an upcoming
calendar event, or a newly-arrived important email. It respects quiet hours, a
cooldown between interjections, and stays silent while you're mid-conversation.
Tunable in `config/.env`:

```env
PROACTIVE_AGENT_ENABLED=true
PROACTIVE_INTERVAL_SECONDS=120
PROACTIVE_EVENT_LEAD_MIN=15
PROACTIVE_COOLDOWN_SECONDS=300
PROACTIVE_QUIET_START=23
PROACTIVE_QUIET_END=8
PROACTIVE_MAIL_ALERTS=true
```

## Continuity

On reconnect, Jarvis seeds the tail of your most recent conversation (if it was
within the last few hours) so follow-ups like "what were we just discussing?" work.
Complex requests ("write…", "debug…", "explain…") automatically escalate to the
strongest configured brain and get more tool steps.

## Notes

- Token usage shown in the UI is local tracking since the Jarvis server started.
- Gmail/Calendar use `config/credentials.json` and `config/token.json`.
- The typed command bar is a fallback when voice input is inconvenient.
