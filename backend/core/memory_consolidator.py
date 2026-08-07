import asyncio
import datetime
import json
import re
from pathlib import Path
from typing import Callable


MemoryLLM = Callable[[list[dict]], str]


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


def _read_session_text(entry: dict, char_limit: int = 8000) -> str:
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


def _clean_memory_item(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip(" -•\t\r\n")
    text = text.rstrip(".")
    return text[:220]


def _memory_type(value: str) -> str:
    value = str(value or "").lower().strip()
    return "preference" if value.startswith("pref") else "fact"


def _dedupe_add(target: list[str], item: str, existing_lower: set[str]) -> bool:
    cleaned = _clean_memory_item(item)
    if len(cleaned) < 8:
        return False
    lowered = cleaned.lower()
    if lowered in existing_lower:
        return False
    target.append(cleaned)
    existing_lower.add(lowered)
    return True


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


def _heuristic_candidates(session_text: str, session_id: str) -> list[dict]:
    """Cheap fallback for explicit preferences/corrections if the LLM fails."""
    candidates: list[dict] = []
    lines = session_text.splitlines()
    for index, line in enumerate(lines):
        if not line.lower().startswith("### user"):
            continue
        user_text = lines[index + 1] if index + 1 < len(lines) else ""
        user_text = _clean_memory_item(user_text)
        lowered = user_text.lower()
        if re.search(r"\b(prefer|always|never|don't|do not|call me|my name is)\b", lowered):
            candidates.append({
                "type": "preference",
                "text": user_text,
                "reason": "explicit user preference or correction",
                "confidence": 0.65,
                "source_session": session_id,
            })
        elif re.search(r"\b(i study|i work|i live|my university|my project)\b", lowered):
            candidates.append({
                "type": "fact",
                "text": user_text,
                "reason": "explicit stable user fact",
                "confidence": 0.6,
                "source_session": session_id,
            })
    return candidates[:8]


def _llm_extract_candidates(session_text: str, session_id: str, call_llm: MemoryLLM) -> list[dict]:
    prompt = (
        "You are the Extractor Agent in Jarvis's long-term memory system.\n"
        "Read the conversation and find POSSIBLE long-term memories. Be generous here; the Judge Agent filters later.\n"
        "Candidate types: fact or preference.\n"
        "Good candidates: stable user facts, strong preferences, corrections to Jarvis behavior, project context, recurring instructions.\n"
        "Bad candidates: one-off questions, temporary mail/calendar details, raw transcript filler, jokes, secrets, API keys, passwords.\n"
        "Each candidate must be short, third-person, and useful tomorrow.\n"
        "Return JSON only: {\"candidates\":[{\"type\":\"fact|preference\",\"text\":\"user ...\",\"reason\":\"...\",\"confidence\":0.0-1.0}]}.\n\n"
        f"CONVERSATION:\n{session_text}"
    )
    data = _extract_json_object(call_llm([
        {"role": "system", "content": "You are a memory extractor. Return strict JSON only."},
        {"role": "user", "content": prompt},
    ]))
    raw_candidates = data.get("candidates", [])
    if not isinstance(raw_candidates, list):
        return []

    candidates = []
    for item in raw_candidates[:12]:
        if not isinstance(item, dict):
            continue
        text = _clean_memory_item(item.get("text", ""))
        if len(text) < 8:
            continue
        candidates.append({
            "type": _memory_type(item.get("type", "fact")),
            "text": text,
            "reason": _clean_memory_item(item.get("reason", ""))[:120],
            "confidence": float(item.get("confidence", 0.5) or 0.5),
            "source_session": session_id,
        })
    return candidates


def _llm_judge_candidates(candidates: list[dict], memory: dict, call_llm: MemoryLLM) -> list[dict]:
    if not candidates:
        return []
    existing = {
        "facts": memory.get("facts", [])[-80:],
        "preferences": memory.get("preferences", [])[-80:],
    }
    prompt = (
        "You are the Judge Agent for Jarvis's long-term memory.\n"
        "Approve only memories that are durable, useful, non-sensitive, and not already captured.\n"
        "Reject one-off requests, email/calendar contents, temporary events, model status, jokes, vague statements, secrets, API keys, passwords, and duplicates.\n"
        "If a newer candidate conflicts with old memory, approve the newer correction and mention it as a correction.\n"
        "Return JSON only: {\"approved\":[{\"type\":\"fact|preference\",\"text\":\"...\",\"reason\":\"...\"}]}.\n\n"
        f"EXISTING MEMORY:\n{json.dumps(existing, ensure_ascii=False)}\n\n"
        f"CANDIDATES:\n{json.dumps(candidates[:80], ensure_ascii=False)}"
    )
    data = _extract_json_object(call_llm([
        {"role": "system", "content": "You judge candidate memories. Return strict JSON only."},
        {"role": "user", "content": prompt},
    ]))
    approved_raw = data.get("approved", [])
    if not isinstance(approved_raw, list):
        return []

    approved = []
    for item in approved_raw[:40]:
        if not isinstance(item, dict):
            continue
        text = _clean_memory_item(item.get("text", ""))
        if len(text) < 8:
            continue
        approved.append({
            "type": _memory_type(item.get("type", "fact")),
            "text": text,
            "reason": _clean_memory_item(item.get("reason", ""))[:120],
        })
    return approved


def _llm_write_memories(approved: list[dict], memory: dict, call_llm: MemoryLLM) -> dict[str, list[str]]:
    if not approved:
        return {"facts": [], "preferences": []}
    existing = {
        "facts": memory.get("facts", [])[-80:],
        "preferences": memory.get("preferences", [])[-80:],
    }
    prompt = (
        "You are the Writer Agent for Jarvis's long-term memory.\n"
        "Rewrite approved memories into clean final notes for data/memory.json.\n"
        "Rules: third person, short, no secrets, no duplicates, no temporary details, no uncertain claims.\n"
        "If a correction supersedes old memory, write the corrected version clearly.\n"
        "Return JSON only: {\"facts\":[\"...\"],\"preferences\":[\"...\"]}.\n\n"
        f"EXISTING MEMORY:\n{json.dumps(existing, ensure_ascii=False)}\n\n"
        f"APPROVED CANDIDATES:\n{json.dumps(approved, ensure_ascii=False)}"
    )
    data = _extract_json_object(call_llm([
        {"role": "system", "content": "You write final memory notes. Return strict JSON only."},
        {"role": "user", "content": prompt},
    ]))
    facts = [_clean_memory_item(item) for item in data.get("facts", []) if isinstance(item, str)]
    preferences = [_clean_memory_item(item) for item in data.get("preferences", []) if isinstance(item, str)]
    return {"facts": facts[:20], "preferences": preferences[:20]}


def _fallback_approve_and_write(candidates: list[dict]) -> dict[str, list[str]]:
    """Use heuristic candidates directly if judge/writer calls fail."""
    facts: list[str] = []
    preferences: list[str] = []
    for candidate in candidates:
        if float(candidate.get("confidence", 0) or 0) < 0.6:
            continue
        if candidate.get("type") == "preference":
            preferences.append(candidate["text"])
        else:
            facts.append(candidate["text"])
    return {"facts": facts[:12], "preferences": preferences[:12]}


def consolidate_conversation_memory(
    *,
    conversation_index_file: Path,
    memory_file: Path,
    state_file: Path,
    call_llm: MemoryLLM,
    max_sessions: int = 12,
    min_session_age_minutes: int = 10,
) -> dict:
    """Run the multi-stage Memory Agent over unprocessed conversation sessions."""
    index = _load_json(conversation_index_file, {"sessions": {}})
    memory = _load_json(memory_file, {"facts": [], "preferences": [], "reminders": []})
    state = _load_json(state_file, {"processed_sessions": {}, "runs": []})
    memory.setdefault("facts", [])
    memory.setdefault("preferences", [])
    memory.setdefault("reminders", [])
    state.setdefault("processed_sessions", {})
    state.setdefault("runs", [])

    candidates_to_process = []
    for session_id, entry in index.get("sessions", {}).items():
        processed_updated = state["processed_sessions"].get(session_id)
        if processed_updated == entry.get("updated_at"):
            continue
        if not _session_is_old_enough(entry, min_session_age_minutes):
            continue
        if int(entry.get("message_count", 0) or 0) < 2:
            state["processed_sessions"][session_id] = entry.get("updated_at")
            continue
        candidates_to_process.append((entry.get("updated_at", ""), session_id, entry))

    candidates_to_process.sort(reverse=True)
    candidates_to_process = candidates_to_process[:max_sessions]

    processed = 0
    extracted_candidates: list[dict] = []
    for _, session_id, entry in candidates_to_process:
        session_text = _read_session_text(entry)
        if not session_text:
            state["processed_sessions"][session_id] = entry.get("updated_at")
            continue
        try:
            extracted_candidates.extend(_llm_extract_candidates(session_text, session_id, call_llm))
        except Exception:
            extracted_candidates.extend(_heuristic_candidates(session_text, session_id))
        state["processed_sessions"][session_id] = entry.get("updated_at")
        processed += 1

    try:
        approved = _llm_judge_candidates(extracted_candidates, memory, call_llm)
        final_memories = _llm_write_memories(approved, memory, call_llm)
    except Exception:
        approved = extracted_candidates
        final_memories = _fallback_approve_and_write(extracted_candidates)

    existing_lower = {str(item).lower() for item in memory["facts"] + memory["preferences"]}
    added = {"facts": 0, "preferences": 0}
    for item in final_memories.get("facts", []):
        if _dedupe_add(memory["facts"], item, existing_lower):
            added["facts"] += 1
    for item in final_memories.get("preferences", []):
        if _dedupe_add(memory["preferences"], item, existing_lower):
            added["preferences"] += 1

    run = {
        "time": datetime.datetime.now().isoformat(timespec="seconds"),
        "agent": "extractor-judge-writer",
        "processed": processed,
        "candidates": len(extracted_candidates),
        "approved": len(approved),
        "added": added,
    }
    state["runs"].append(run)
    state["runs"] = state["runs"][-100:]
    _write_json(memory_file, memory)
    _write_json(state_file, state)
    return run


async def memory_consolidator_loop(
    *,
    conversation_index_file: Path,
    memory_file: Path,
    state_file: Path,
    call_llm: MemoryLLM,
    interval_seconds: int,
    max_sessions: int,
    min_session_age_minutes: int,
    initial_delay_seconds: int = 60,
    logger=print,
) -> None:
    """Run the Memory Agent forever in the background."""
    await asyncio.sleep(max(0, initial_delay_seconds))
    while True:
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: consolidate_conversation_memory(
                    conversation_index_file=conversation_index_file,
                    memory_file=memory_file,
                    state_file=state_file,
                    call_llm=call_llm,
                    max_sessions=max_sessions,
                    min_session_age_minutes=min_session_age_minutes,
                ),
            )
            logger(
                "[memory agent] "
                f"processed={result['processed']} "
                f"candidates={result['candidates']} "
                f"approved={result['approved']} "
                f"added={result['added']}"
            )
        except Exception as exc:
            logger(f"[memory agent] failed: {exc}")
        await asyncio.sleep(max(60, interval_seconds))
