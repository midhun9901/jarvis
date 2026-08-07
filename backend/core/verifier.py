import re


def sanitize_unverified_action_reply(user_text: str, reply: str) -> str:
    """Stop the LLM from claiming tool actions that did not actually happen."""
    lowered_user = (user_text or "").lower()
    lowered_reply = (reply or "").lower()
    action_domain = re.search(
        r"\b(mail|mails|male|males|main|mains|email|emails|gmail|gmails|mailbox|university|college|fau|file|folder|calendar|screen|open|show|display|save|remember|note|send|forward)\b",
        lowered_user,
    )
    fake_claim = re.search(
        r"\b(i found|i see|i opened|opened|showing|on your screen|i saved|saved|noted|remembered|i sent|sent|forwarded|pulled up)\b",
        lowered_reply,
    )
    if action_domain and fake_claim and "<<" not in reply:
        return (
            "I will not pretend I did that, sir. I did not run a real tool for this request. "
            "Please say the exact action, like 'show my mailbox on screen' or 'open number 1'."
        )
    return reply
