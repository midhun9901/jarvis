import datetime
import email.utils
import re


def relative_date_label(raw_date: str) -> str:
    """Convert raw RFC2822 email date to a short local label."""
    try:
        parsed = email.utils.parsedate_to_datetime(raw_date)
        local = parsed.astimezone()
        today = datetime.date.today()
        diff = (local.date() - today).days
        t = local.strftime("%#I:%M %p")
        if diff == 0:
            return f"TODAY {t}"
        if diff == 1:
            return f"TOMORROW {t}"
        if diff == -1:
            return f"YESTERDAY {t}"
        if 2 <= diff <= 6:
            return f"{local.strftime('%A')} {t}"
        return local.strftime("%b %d, %Y ") + t
    except Exception:
        return raw_date


def mail_text(mail: dict) -> str:
    return " ".join([
        mail.get("sender", ""),
        mail.get("subject", ""),
        mail.get("snippet", ""),
    ]).lower()


def mail_category(mail: dict) -> str:
    text = mail_text(mail)
    sender = (mail.get("sender") or "").lower()
    if any(token in text for token in ("fau", "university", "college", "faumail", "course", "registration", "exam", "student")):
        return "university"
    if any(token in sender for token in ("linkedin", "indeed", "stepstone", "xing")) or any(token in text for token in ("job alert", "job application", "recruiter", "hiring")):
        return "job"
    if any(token in text for token in ("invoice", "payment", "bill", "bank", "receipt", "tax", "rent", "splitwise")):
        return "finance"
    if any(token in text for token in ("meeting", "appointment", "interview", "schedule", "calendar", "invite")):
        return "meeting"
    if any(token in sender for token in ("no-reply", "noreply", "spotify", "uber eats", "datacamp")) or any(token in text for token in ("offer", "discount", "premium", "sale", "newsletter", "unsubscribe", "promo")):
        return "promotion"
    return "other"


def mail_priority(mail: dict) -> tuple[int, str]:
    text = mail_text(mail)
    category = mail_category(mail)
    score = 0
    reason = "normal priority"
    if mail.get("unread"):
        score += 1
    if category in ("university", "meeting", "finance"):
        score += 3
        reason = category
    elif category == "job":
        score += 1
        reason = "job update"
    elif category == "promotion":
        score -= 3
        reason = "promotion/noise"
    if re.search(r"\b(urgent|important|deadline|due|action required|respond|reply|final reminder|expires|tomorrow|today)\b", text):
        score += 4
        reason = "needs attention"
    return score, reason


def smart_single_mail_summary(mail: dict) -> str:
    label = relative_date_label(mail.get("date", ""))
    sender = re.sub(r"<[^>]+>", "", mail.get("sender", "")).replace('"', "").strip() or "Unknown sender"
    subject = mail.get("subject") or "(no subject)"
    category = mail_category(mail)
    score, reason = mail_priority(mail)
    if score >= 7:
        priority = "high priority"
    elif score >= 3:
        priority = "worth checking"
    elif category == "promotion":
        priority = "low priority, likely promotional"
    else:
        priority = "not urgent"
    return f"Yes. Latest match is from {sender}, received {label}. Summary: {subject}. Category: {category}. Priority: {priority} ({reason})."


def mail_list_highlights(mails: list[dict], limit: int = 5) -> str:
    if not mails:
        return "I do not have a mail list in context right now, sir."
    lines = []
    for i, mail in enumerate(mails[:limit], start=1):
        sender = re.sub(r"<[^>]+>", "", mail.get("sender", "")).strip() or "Unknown sender"
        subject = mail.get("subject") or "(no subject)"
        category = mail_category(mail)
        _, reason = mail_priority(mail)
        lines.append(f"{i}. {sender}: {subject} ({category}, {reason})")
    remaining = len(mails) - min(len(mails), limit)
    tail = f" {remaining} more are on screen." if remaining > 0 else ""
    return "Here are the real mail highlights: " + " ".join(lines) + tail


def important_mail_briefing(mails: list[dict], limit: int = 4) -> str:
    if not mails:
        return "I do not see any relevant inbox mail right now, sir. I filtered out promotions, social updates, and obvious automated offers."
    lines = []
    for mail in mails[:limit]:
        sender = re.sub(r"<[^>]+>", "", mail.get("sender", "")).replace('"', "").strip() or "Unknown sender"
        subject = mail.get("subject") or "(no subject)"
        lines.append(f"{sender} - {subject}")
    remaining = len(mails) - min(len(mails), limit)
    tail = f" I found {remaining} more relevant message{'s' if remaining != 1 else ''}." if remaining > 0 else ""
    return "Relevant mail only: " + " ".join(lines) + tail


def smart_mail_triage(mails: list[dict], *, total_unread: int | None = None) -> str:
    if not mails:
        return "I do not see any inbox mail to triage right now, sir."

    buckets: dict[str, list[dict]] = {}
    scored = []
    for mail in mails:
        category = mail_category(mail)
        buckets.setdefault(category, []).append(mail)
        score, reason = mail_priority(mail)
        scored.append((score, reason, mail))
    scored.sort(key=lambda item: (item[0], item[2].get("timestamp", 0)), reverse=True)

    unread_count = total_unread if total_unread is not None else sum(1 for mail in mails if mail.get("unread"))
    parts = [f"I found {unread_count} unread message{'s' if unread_count != 1 else ''}."]
    category_order = ["university", "meeting", "finance", "job", "other", "promotion"]
    summaries = []
    for category in category_order:
        count = len(buckets.get(category, []))
        if count:
            label = "promotions/noise" if category == "promotion" else category
            summaries.append(f"{count} {label}")
    if summaries:
        parts.append("Breakdown: " + ", ".join(summaries) + ".")

    actionable = [(score, reason, mail) for score, reason, mail in scored if score >= 3 and mail_category(mail) != "promotion"]
    if actionable:
        lines = []
        for score, reason, mail in actionable[:3]:
            sender = re.sub(r"<[^>]+>", "", mail.get("sender", "")).replace('"', "").strip() or "Unknown sender"
            subject = mail.get("subject") or "(no subject)"
            category = mail_category(mail)
            lines.append(f"{sender}: {subject} ({category}, {reason})")
        parts.append(f"{len(actionable)} seem to need attention. " + " ".join(lines))
    else:
        parts.append("Nothing looks urgent from the inbox metadata.")

    noise_count = len(buckets.get("promotion", []))
    if noise_count:
        parts.append(f"I skipped {noise_count} promotional or automated message{'s' if noise_count != 1 else ''}.")
    return " ".join(parts)
