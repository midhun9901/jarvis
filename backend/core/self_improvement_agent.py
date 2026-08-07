import asyncio
import datetime
import json
import re
from pathlib import Path
from typing import Callable


ImprovementLLM = Callable[[list[dict]], str]

FAILURE_CATEGORIES = {
    "hallucination",
    "wrong_tool",
    "missed_tool",
    "voice_mishear",
    "tone",
    "verbosity",
    "memory",
    "mail",
    "calendar",
    "model_switch",
    "wake_word",
    "other",
}


def _load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _extract_json_object(text: str) -> dict:
    text = (text or "").strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _parse_iso(value: str) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(str(value))
    except Exception:
        return None


def _session_is_old_enough(entry: dict, min_age_minutes: int) -> bool:
    updated = _parse_iso(entry.get("updated_at", ""))
    if not updated:
        return True
    age = datetime.datetime.now() - updated
    return age.total_seconds() >= min_age_minutes * 60


def _clean(text: str, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip(" -•\t\r\n")
    return text[:limit]


def _read_session_text(entry: dict, char_limit: int = 3500) -> str:
    path = Path(entry.get("path", ""))
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    text = re.sub(r"---.*?---", "", text, count=1, flags=re.S)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[-char_limit:]


def _collect_sessions(conversation_index_file: Path, state: dict, max_sessions: int, min_age_minutes: int) -> list[tuple[str, dict, str]]:
    index = _load_json(conversation_index_file, {"sessions": {}})
    sessions: list[tuple[str, dict, str]] = []
    for session_id, entry in index.get("sessions", {}).items():
        if state.get("processed_sessions", {}).get(session_id) == entry.get("updated_at"):
            continue
        if int(entry.get("message_count", 0) or 0) < 4:
            state.setdefault("processed_sessions", {})[session_id] = entry.get("updated_at")
            continue
        if not _session_is_old_enough(entry, min_age_minutes):
            continue
        sessions.append((entry.get("updated_at", ""), entry, session_id))
    sessions.sort(reverse=True)

    selected = []
    for _, entry, session_id in sessions[:max_sessions]:
        text = _read_session_text(entry)
        if text:
            selected.append((session_id, entry, text))
    return selected


def _analyst_agent(conversation_batch: str, call_llm: ImprovementLLM) -> dict:
    prompt = (
        "You are Jarvis's Conversation Analyst Agent.\n"
        "Study recent conversations and find repeated behavior failures only.\n"
        "Focus on: hallucinated actions, wrong/missed tools, voice mishears, tone problems, verbosity, memory mistakes, mail/calendar bugs, model switching, wake-word issues.\n"
        "Classify each failure as one of: hallucination, wrong_tool, missed_tool, voice_mishear, tone, verbosity, memory, mail, calendar, model_switch, wake_word, other.\n"
        "Do not include secrets or raw private content. Use short paraphrased evidence. Prefer 3-6 high-signal failures over long lists.\n"
        "Return JSON only: "
        "{\"failures\":[{\"category\":\"...\",\"pattern\":\"...\",\"evidence\":\"short paraphrase\",\"severity\":\"low|medium|high\"}],"
        "\"good_behaviors\":[\"...\"],\"voice_mishearings\":[{\"heard\":\"...\",\"intended\":\"...\",\"context\":\"...\"}]}.\n\n"
        f"CONVERSATIONS:\n{conversation_batch}"
    )
    return _extract_json_object(call_llm([
        {"role": "system", "content": "Analyze assistant behavior. Return strict compact JSON only."},
        {"role": "user", "content": prompt},
    ]))


def _architect_agent(analysis: dict, existing_lessons: dict, call_llm: ImprovementLLM) -> dict:
    compact_existing = {
        "reply_rules": existing_lessons.get("reply_rules", [])[-5:],
        "tool_rules": existing_lessons.get("tool_rules", [])[-5:],
        "voice_rules": existing_lessons.get("voice_rules", [])[-5:],
    }
    prompt = (
        "You are Jarvis's Improvement Architect Agent.\n"
        "Turn analysis into token-light improvements.\n"
        "Behavior lessons must be short, general, non-private, and useful across future chats. Max 5 total new lessons.\n"
        "If a fix needs code, prefer a code recommendation instead of many prompt rules.\n"
        "Code recommendations must name likely files/functions and explain the change. Do not claim code was changed.\n"
        "Return JSON only: "
        "{\"lessons\":{\"reply_rules\":[\"...\"],\"tool_rules\":[\"...\"],\"voice_rules\":[\"...\"]},"
        "\"code_recommendations\":[{\"title\":\"...\",\"why\":\"...\",\"suggestion\":\"...\",\"files\":[\"...\"]}]}.\n\n"
        f"EXISTING LESSONS:\n{json.dumps(compact_existing, ensure_ascii=False)}\n\n"
        f"ANALYSIS:\n{json.dumps(analysis, ensure_ascii=False)[:7000]}"
    )
    return _extract_json_object(call_llm([
        {"role": "system", "content": "Design safe token-light assistant improvements. Return strict compact JSON only."},
        {"role": "user", "content": prompt},
    ]))


def _merge_lessons(existing: dict, new_lessons: dict, lesson_limit: int) -> dict:
    merged = {
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "reply_rules": list(existing.get("reply_rules", [])),
        "tool_rules": list(existing.get("tool_rules", [])),
        "voice_rules": list(existing.get("voice_rules", [])),
    }
    for key in ("reply_rules", "tool_rules", "voice_rules"):
        seen = {str(item).lower() for item in merged[key]}
        values = new_lessons.get(key, [])
        for item in values if isinstance(values, list) else []:
            cleaned = _clean(item, 130)
            if len(cleaned) < 8 or cleaned.lower() in seen:
                continue
            merged[key].append(cleaned)
            seen.add(cleaned.lower())
        merged[key] = merged[key][-lesson_limit:]
    return merged


def _write_report(report_dir: Path, analysis: dict, architecture: dict, sessions: list[tuple[str, dict, str]]) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = report_dir / f"self-improvement-{timestamp}.md"
    session_lines = [
        f"- {session_id}: {entry.get('summary', 'No summary')}"
        for session_id, entry, _ in sessions
    ]
    failures = analysis.get("failures", []) if isinstance(analysis.get("failures", []), list) else []
    recs = architecture.get("code_recommendations", []) if isinstance(architecture.get("code_recommendations", []), list) else []
    lessons = architecture.get("lessons", {}) if isinstance(architecture.get("lessons", {}), dict) else {}

    lines = [
        "# Jarvis Self-Improvement Report",
        "",
        f"Generated: {datetime.datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Sessions Reviewed",
        *session_lines,
        "",
        "## Failure Patterns",
    ]
    if failures:
        for item in failures:
            if isinstance(item, dict):
                category = item.get("category", "other")
                if category not in FAILURE_CATEGORIES:
                    category = "other"
                lines.append(
                    f"- {item.get('severity', 'medium')} [{category}]: "
                    f"{_clean(item.get('pattern', ''))} Evidence: {_clean(item.get('evidence', ''), 180)}"
                )
    else:
        lines.append("- No clear failure patterns found.")

    lines.extend(["", "## Behavior Lessons Added"])
    for key in ("reply_rules", "tool_rules", "voice_rules"):
        values = lessons.get(key, []) if isinstance(lessons.get(key, []), list) else []
        if values:
            lines.append(f"{key}:")
            for value in values:
                lines.append(f"- {_clean(value, 140)}")

    lines.extend(["", "## Code Recommendations"])
    if recs:
        for rec in recs:
            if not isinstance(rec, dict):
                continue
            files = ", ".join(rec.get("files", [])) if isinstance(rec.get("files", []), list) else ""
            lines.append(
                f"- {_clean(rec.get('title', 'Recommendation'), 120)}: "
                f"{_clean(rec.get('suggestion', ''), 360)} Files: {files}"
            )
    else:
        lines.append("- No code changes recommended.")

    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return path


def run_self_improvement_agent(
    *,
    conversation_index_file: Path,
    lessons_file: Path,
    state_file: Path,
    report_dir: Path,
    call_llm: ImprovementLLM,
    max_sessions: int = 6,
    min_session_age_minutes: int = 30,
    lesson_limit: int = 5,
) -> dict:
    """Analyze Jarvis conversations and update safe, compact behavior lessons."""
    state = _load_json(state_file, {"processed_sessions": {}, "runs": []})
    state.setdefault("processed_sessions", {})
    state.setdefault("runs", [])
    lessons = _load_json(lessons_file, {"reply_rules": [], "tool_rules": [], "voice_rules": []})

    sessions = _collect_sessions(conversation_index_file, state, max_sessions, min_session_age_minutes)
    if not sessions:
        run = {
            "time": datetime.datetime.now().isoformat(timespec="seconds"),
            "processed": 0,
            "lessons_added": 0,
            "report": None,
        }
        state["runs"].append(run)
        state["runs"] = state["runs"][-100:]
        _write_json(state_file, state)
        return run

    batch_parts = []
    for session_id, entry, text in sessions:
        batch_parts.append(f"SESSION {session_id}\nSUMMARY: {entry.get('summary', '')}\n{text}")
    conversation_batch = "\n\n---\n\n".join(batch_parts)[:12000]

    analysis = _analyst_agent(conversation_batch, call_llm)
    architecture = _architect_agent(analysis, lessons, call_llm)
    new_lessons = architecture.get("lessons", {}) if isinstance(architecture.get("lessons", {}), dict) else {}
    merged_lessons = _merge_lessons(lessons, new_lessons, lesson_limit)

    old_count = sum(len(lessons.get(key, [])) for key in ("reply_rules", "tool_rules", "voice_rules"))
    new_count = sum(len(merged_lessons.get(key, [])) for key in ("reply_rules", "tool_rules", "voice_rules"))
    report_path = _write_report(report_dir, analysis, architecture, sessions)

    for session_id, entry, _ in sessions:
        state["processed_sessions"][session_id] = entry.get("updated_at")

    _write_json(lessons_file, merged_lessons)
    run = {
        "time": datetime.datetime.now().isoformat(timespec="seconds"),
        "agent": "classified-analyst-architect-reporter",
        "processed": len(sessions),
        "lessons_added": max(0, new_count - old_count),
        "failures": len(analysis.get("failures", [])) if isinstance(analysis.get("failures", []), list) else 0,
        "report": str(report_path),
    }
    state["runs"].append(run)
    state["runs"] = state["runs"][-100:]
    _write_json(state_file, state)
    return run


async def self_improvement_agent_loop(
    *,
    conversation_index_file: Path,
    lessons_file: Path,
    state_file: Path,
    report_dir: Path,
    call_llm: ImprovementLLM,
    interval_seconds: int,
    max_sessions: int,
    min_session_age_minutes: int,
    lesson_limit: int,
    initial_delay_seconds: int = 180,
    logger=print,
) -> None:
    """Run Jarvis's self-improvement agent forever in the background."""
    await asyncio.sleep(max(0, initial_delay_seconds))
    while True:
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: run_self_improvement_agent(
                    conversation_index_file=conversation_index_file,
                    lessons_file=lessons_file,
                    state_file=state_file,
                    report_dir=report_dir,
                    call_llm=call_llm,
                    max_sessions=max_sessions,
                    min_session_age_minutes=min_session_age_minutes,
                    lesson_limit=lesson_limit,
                ),
            )
            logger(
                "[self-improvement agent] "
                f"processed={result['processed']} "
                f"failures={result.get('failures', 0)} "
                f"lessons_added={result['lessons_added']} "
                f"report={result['report']}"
            )
        except Exception as exc:
            logger(f"[self-improvement agent] failed: {exc}")
        await asyncio.sleep(max(60, interval_seconds))
