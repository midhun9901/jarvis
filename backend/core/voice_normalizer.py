import re


_VOICE_NORMALIZATIONS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\bg[\s-]?males?\b", re.I), "gmails"),
    (re.compile(r"\bg[\s-]?mails?\b", re.I), "gmails"),
    (re.compile(r"\bmail\s*box\b", re.I), "mailbox"),
    (re.compile(r"\b(?:males|mains)\b", re.I), "mails"),
    (re.compile(r"\b(?:male|main|meal)\b", re.I), "mail"),
    (re.compile(r"\bthat\s+mails?\b", re.I), "that mail"),
    (re.compile(r"\bopen\s+number\s+one\b", re.I), "open number 1"),
    (re.compile(r"\bopen\s+number\s+two\b", re.I), "open number 2"),
    (re.compile(r"\bopen\s+number\s+three\b", re.I), "open number 3"),
    (re.compile(r"\ballama\b", re.I), "llama"),
    (re.compile(r"\balama\b", re.I), "llama"),
    (re.compile(r"\bolama\b", re.I), "ollama"),
    (re.compile(r"\bdeep\s+seek\b", re.I), "deepseek"),
    (re.compile(r"\byou\s+tube\b", re.I), "youtube"),
    (re.compile(r"\bschreen\b", re.I), "screen"),
    (re.compile(r"\bskreen\b", re.I), "screen"),
)


# NOTE: "service" was removed — it woke Jarvis on any sentence containing the word
WAKE_WORD_RE = re.compile(r"\b(jarvis|jervis|jar vess|jarves)\b", re.I)
STOP_LISTENING_RE = re.compile(
    r"^\s*(stop|stop listening|go to sleep|sleep|stand by|standby|pause listening)\s*[.!?]?\s*$",
    re.I,
)


def normalize_voice_text(text: str) -> str:
    """Normalize common STT slips before routing, without changing display text."""
    if not text:
        return text
    normalized = re.sub(r"\s+", " ", text).strip()
    lowered = normalized.lower()
    context_is_mail = bool(re.search(
        r"\b(gmail|gmails|email|emails|mailbox|inbox|unread|message|messages|screen|university|college|fau|from|open|show|display|read|check|see)\b",
        lowered,
    ))
    for pattern, replacement in _VOICE_NORMALIZATIONS:
        if replacement in {"mail", "mails", "gmails", "mailbox"} and not context_is_mail:
            continue
        normalized = pattern.sub(replacement, normalized)
    return normalized


def extract_wake_command(text: str) -> str | None:
    """Return command after wake word, empty string for wake only, None for no wake."""
    match = WAKE_WORD_RE.search(text or "")
    if not match:
        return None
    return (text[match.end():] or "").strip(" .,:;!?")


def is_stop_listening_command(text: str) -> bool:
    return bool(STOP_LISTENING_RE.match(text or ""))
