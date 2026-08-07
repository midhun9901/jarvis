"""
plugins/calendar_agent.py — Google Calendar integration for JARVIS

Uses the same credentials.json / token.json as gmail_agent.py.
Scopes are additive — on first run after adding this, a new OAuth
flow will open in the browser to grant calendar access.
"""

import datetime

from googleapiclient.discovery import build

from plugins.gmail_agent import get_credentials


def _get_service():
    """Calendar service using the shared Google credentials from gmail_agent."""
    return build("calendar", "v3", credentials=get_credentials())


def _relative_label(dt: datetime.datetime) -> str:
    today = datetime.date.today()
    d = dt.date() if hasattr(dt, "date") else dt
    diff = (d - today).days
    if diff == 0:   return "TODAY"
    if diff == 1:   return "TOMORROW"
    if diff == -1:  return "YESTERDAY"
    if 2 <= diff <= 6: return dt.strftime("%A")  # "Wednesday"
    return dt.strftime("%b %d")


def _parse_event(e: dict) -> dict:
    start = e.get("start", {})
    end   = e.get("end",   {})

    def _parse_dt(d):
        if "dateTime" in d:
            return datetime.datetime.fromisoformat(d["dateTime"])
        if "date" in d:
            return datetime.datetime.combine(
                datetime.date.fromisoformat(d["date"]),
                datetime.time()
            )
        return None

    start_dt = _parse_dt(start)
    end_dt   = _parse_dt(end)
    all_day  = "date" in start and "dateTime" not in start

    label  = _relative_label(start_dt) if start_dt else ""
    time_s = "" if all_day else (start_dt.strftime("%#I:%M %p") if start_dt else "")
    time_e = "" if all_day else (end_dt.strftime("%#I:%M %p")   if end_dt   else "")

    return {
        "id":          e.get("id", ""),
        "title":       e.get("summary", "(no title)"),
        "location":    e.get("location", ""),
        "description": (e.get("description") or "")[:300],
        "link":        e.get("hangoutLink") or e.get("htmlLink", ""),
        "all_day":     all_day,
        "start_dt":    start_dt.isoformat() if start_dt else "",
        "end_dt":      end_dt.isoformat()   if end_dt   else "",
        "label":       label,
        "time_start":  time_s,
        "time_end":    time_e,
        "calendar":    e.get("organizer", {}).get("displayName", ""),
    }


def get_events(days_ahead: int = 7, max_results: int = 20) -> list[dict]:
    """Return events from now to now+days_ahead."""
    service = _get_service()
    now = datetime.datetime.now(datetime.timezone.utc)
    end = now + datetime.timedelta(days=days_ahead)
    resp = service.events().list(
        calendarId="primary",
        timeMin=now.isoformat(),
        timeMax=end.isoformat(),
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    return [_parse_event(e) for e in resp.get("items", [])]


def get_events_on_date(target: datetime.date) -> list[dict]:
    """Return all events on a specific date."""
    service = _get_service()
    # Local-day boundaries, timezone-aware — naive + "Z" shifted the window to UTC
    start = datetime.datetime.combine(target, datetime.time.min).astimezone().isoformat()
    end   = datetime.datetime.combine(target, datetime.time.max).astimezone().isoformat()
    resp = service.events().list(
        calendarId="primary",
        timeMin=start,
        timeMax=end,
        maxResults=20,
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    return [_parse_event(e) for e in resp.get("items", [])]


def create_event(title: str, date_str: str, time_str: str = "",
                 duration_min: int = 60, location: str = "", description: str = "") -> dict:
    """Create a calendar event. date_str: YYYY-MM-DD, time_str: HH:MM (24h)."""
    service = _get_service()
    if time_str:
        # Interpret the requested time in the machine's local timezone, not a hardcoded one
        start_dt = datetime.datetime.fromisoformat(f"{date_str}T{time_str}:00").astimezone()
        end_dt   = start_dt + datetime.timedelta(minutes=duration_min)
        body = {
            "summary": title,
            "location": location,
            "description": description,
            "start": {"dateTime": start_dt.isoformat()},
            "end":   {"dateTime": end_dt.isoformat()},
        }
    else:
        body = {
            "summary":  title,
            "location": location,
            "description": description,
            "start": {"date": date_str},
            "end":   {"date": date_str},
        }
    created = service.events().insert(calendarId="primary", body=body).execute()
    return _parse_event(created)


def delete_event(event_id: str) -> str:
    service = _get_service()
    service.events().delete(calendarId="primary", eventId=event_id).execute()
    return f"Event {event_id} deleted."
