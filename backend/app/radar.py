"""Radar: messy text or a photo -> clean deadline draft.
Uses Groq (Llama text + vision models, Whisper for voice) when GROQ_API_KEY is set; otherwise (or on any failure) a rule-based fallback."""
import json, os, re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import httpx

SYSTEM = """You are Radar, an assistant for high-school students. Read the input (it may be in any language, may be messy, and may come from a photo of a worksheet or a voice transcript). Extract ONE assignment or deadline. Return only valid JSON, no extra text, with these keys:
{"title": short clear assignment name in the same language as the input, max 60 characters,
 "subject": subject name or null,
 "due_date": ISO 8601 date and time with the student's timezone offset, or null,
 "due_text_original": the exact words in the input that gave the due date, or null,
 "confidence": number from 0 to 1,
 "needs_clarification": true if the due date or title is missing or ambiguous}
Rules: Today is {today} and the student's timezone is {tz}. Resolve relative dates such as 'Friday', 'next week' or 'tomorrow' from today. If no time is given, use 23:59 local time. If there is more than one deadline, pick the soonest and set needs_clarification to true. Never invent a date. If you cannot find a due date, set due_date to null."""

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MON = "jan feb mar apr may jun jul aug sep oct nov dec".split()


def fallback(text: str, tz: str = "UTC", now: datetime | None = None) -> dict:
    try:
        zone = ZoneInfo(tz)
    except Exception:
        zone = timezone.utc
    now = now or datetime.now(zone)
    low, d = text.lower(), None
    if "tomorrow" in low:
        d = now + timedelta(days=1)
    elif re.search(r"\b(today|tonight)\b", low):
        d = now
    else:
        for i, n in enumerate(DAYS):
            if re.search(rf"\b{n}\b", low):
                d = now + timedelta(days=(i - now.weekday()) % 7 or 7)
                break
    if d is None:
        m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", low)
        day, mon = (int(m[1]), MON.index(m[2]) + 1) if m else (None, None)
        if not m:
            m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+(\d{1,2})\b", low)
            if m:
                day, mon = int(m[2]), MON.index(m[1]) + 1
        if m:
            try:
                d = datetime(now.year, mon, day, tzinfo=zone)
                if d < now:
                    d = d.replace(year=now.year + 1)
            except ValueError:
                d = None
    h, mi = 23, 59
    t = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", low)
    if t:
        h, mi = int(t[1]) % 12 + (12 if t[3] == "pm" else 0), int(t[2] or 0)
    if d:
        d = d.replace(hour=h, minute=mi, second=0, microsecond=0)
    title = re.split(r"\b(?:due|by|before|submit|deadline|tomorrow|today|tonight|" + "|".join(DAYS) + r")\b", text, flags=re.I)[0]
    title = re.sub(r"\s+(on|for|at|this|next|until|till|is)\s*$", "", title.strip(), flags=re.I)
    title = re.sub(r"^(my|the|our)\s+", "", title.strip(), flags=re.I).strip(" .,:-") or text.strip()
    title = (title[:1].upper() + title[1:])[:60]
    return {"title": title, "subject": None, "due_date": d.isoformat() if d else None,
            "due_text_original": None, "confidence": 0.6 if d else 0.2,
            "needs_clarification": d is None or not title}


GROQ = "https://api.groq.com/openai/v1"
# Model names are env-configurable because Groq retires models from time to time.
def _model(kind):
    return os.getenv({"text": "GROQ_TEXT_MODEL", "vision": "GROQ_VISION_MODEL", "stt": "GROQ_STT_MODEL"}[kind],
                     {"text": "llama-3.3-70b-versatile", "vision": "meta-llama/llama-4-scout-17b-16e-instruct", "stt": "whisper-large-v3-turbo"}[kind])


def _groq(text, image_b64, media_type, tz):
    prompt = text or "Extract the assignment and deadline from this image."
    if image_b64:
        content = [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:{media_type or 'image/jpeg'};base64,{image_b64}"}}]
    else:
        content = prompt
    body = {"model": _model("vision" if image_b64 else "text"), "temperature": 0, "max_tokens": 400,
            "messages": [{"role": "system", "content": SYSTEM.replace("{today}", datetime.now(timezone.utc).isoformat()).replace("{tz}", tz)},
                         {"role": "user", "content": content}]}
    if not image_b64:
        body["response_format"] = {"type": "json_object"}
    r = httpx.post(f"{GROQ}/chat/completions", headers={"Authorization": "Bearer " + os.environ["GROQ_API_KEY"]}, json=body, timeout=30)
    r.raise_for_status()
    out = json.loads(re.search(r"\{.*\}", r.json()["choices"][0]["message"]["content"], re.S).group(0))
    out.setdefault("needs_clarification", out.get("due_date") is None)
    return out


def transcribe(audio: bytes, media_type: str | None) -> str:
    mt = (media_type or "audio/webm").split(";")[0]
    ext = {"audio/webm": "webm", "audio/mp4": "m4a", "audio/ogg": "ogg", "audio/wav": "wav", "audio/mpeg": "mp3"}.get(mt, "webm")
    r = httpx.post(f"{GROQ}/audio/transcriptions", headers={"Authorization": "Bearer " + os.environ["GROQ_API_KEY"]},
                   data={"model": _model("stt"), "response_format": "json"}, files={"file": (f"voice.{ext}", audio, mt)}, timeout=60)
    r.raise_for_status()
    return r.json()["text"].strip()


def parse(text: str | None, image_b64: str | None, media_type: str | None, tz: str = "UTC") -> dict:
    if os.getenv("GROQ_API_KEY"):
        try:
            return _groq(text, image_b64, media_type, tz)
        except Exception:
            pass
    return fallback(text or "", tz)
