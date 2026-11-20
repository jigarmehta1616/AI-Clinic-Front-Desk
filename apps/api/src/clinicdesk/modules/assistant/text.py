"""Deterministic understanding of patient text in Gujarati, Hindi, English and romanised mixes. Pure.

This layer runs before (and without) any LLM:
* safety screen (BR-10, FR-2.6, FR-8.3) — emergency always wins;
* STOP / START (FR-2.9);
* intents and date / time-of-day hints good enough for "appointment kal savare" (AC-1).

Lexicons are deliberately broad: a false emergency costs one extra message and a staff alert; a missed
one can cost a life. Chronic/rehab words common in physio ("stroke", "paralysis", "accident") are routed as
medical (staff) rather than emergency so rehab bookings are not blocked.
The emergency list MUST be reviewed by a clinician before the pilot (open question Q12).
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Literal

Safety = Literal["emergency", "medical", "none"]
Intent = Literal["greeting", "book", "manage", "token", "queue", "info", "staff", "none"]
TimeOfDay = Literal["morning", "afternoon", "evening"]

_DIGITS = str.maketrans("૦૧૨૩૪૫૬૭૮૯०१२३४५६७८९", "01234567890123456789")
_GU = re.compile(r"[઀-૿]")
_HI = re.compile(r"[ऀ-ॿ]")


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(_DIGITS)).strip().lower()


def _has(t: str, phrases: tuple[str, ...]) -> bool:
    """Romanised phrases match on word boundaries; Indic-script phrases match as substrings."""
    for p in phrases:
        if p.isascii():
            if re.search(rf"(?<![a-z]){re.escape(p)}(?![a-z])", t):
                return True
        elif p in t:
            return True
    return False


# --- language ------------------------------------------------------------------------------------
_GU_HINTS = (
    "che",
    "chhe",
    "kem",
    "savare",
    "sawar",
    "kale",
    "aavti",
    "aavtikale",
    "mare",
    "tamne",
    "joie",
    "joiye",
    "bapore",
    "saanje",
    "sanje",
    "aaje",
    "nathi",
    "karvi",
    "levi",
    "parmdivas",
)
_HI_HINTS = (
    "hai",
    "hain",
    "mujhe",
    "chahiye",
    "kya",
    "nahi",
    "nahin",
    "subah",
    "shaam",
    "dopahar",
    "aaj",
    "kal",
    "parso",
    "karna",
    "lena",
    "milna",
    "mera",
    "meri",
    "kab",
)


_EN_HINTS = frozenset(
    {
        "the",
        "what",
        "please",
        "help",
        "my",
        "is",
        "are",
        "i",
        "to",
        "do",
        "need",
        "want",
        "can",
        "you",
        "when",
        "since",
        "morning",
        "evening",
        "afternoon",
        "tomorrow",
        "today",
        "and",
        "for",
        "with",
        "have",
        "has",
        "how",
        "where",
        "of",
        "pain",
        "doctor",
        "book",
        "appointment",
        "time",
        "thanks",
        "thank",
        "hello",
        "hi",
        "not",
        "will",
        "would",
    }
)


def detect_language(text: str, default: str = "en") -> tuple[str, bool]:
    """Returns (language, strong). `strong` = decided by script, so it may override a stored preference."""
    if _GU.search(text):
        return "gu", True
    if _HI.search(text):
        return "hi", True
    words = set(re.findall(r"[a-z]+", normalize(text)))
    gu, hi = len(words & set(_GU_HINTS)), len(words & set(_HI_HINTS))
    if gu > hi:
        return "gu", False
    if hi > gu:
        return "hi", False
    if gu == 0 and words & _EN_HINTS:
        return "en", False  # plain English sentence: don't fall back to the clinic's default language
    return default, False


# --- opt-out -------------------------------------------------------------------------------------
_STOP = {
    "stop",
    "stop all",
    "unsubscribe",
    "opt out",
    "optout",
    "band",
    "band karo",
    "bandh",
    "bandh karo",
    "बंद",
    "बंद करो",
    "बंद करें",
    "रोको",
    "रोकें",
    "બંધ",
    "બંધ કરો",
}
_START = {"start", "unstop", "chalu", "chalu karo", "शुरू", "चालू", "ચાલુ", "ચાલુ કરો"}


def is_stop(text: str) -> bool:
    return normalize(text).strip(" .!") in _STOP


def is_start(text: str) -> bool:
    return normalize(text).strip(" .!") in _START


# --- safety --------------------------------------------------------------------------------------
_EMERGENCY = (
    # English
    "chest pain",
    "heart attack",
    "cardiac arrest",
    "can't breathe",
    "cant breathe",
    "cannot breathe",
    "not breathing",
    "difficulty breathing",
    "trouble breathing",
    "short of breath",
    "breathless",
    "unconscious",
    "fainted",
    "collapsed",
    "not responding",
    "heavy bleeding",
    "bleeding a lot",
    "won't stop bleeding",
    "wont stop bleeding",
    "bleeding won't stop",
    "face drooping",
    "sudden weakness",
    "can't speak",
    "cannot speak",
    "slurred speech",
    "seizure",
    "fits",
    "suicide",
    "kill myself",
    "poison",
    "poisoned",
    "overdose",
    "anaphylaxis",
    "severe allergic",
    "throat swelling",
    "swelling in throat",
    "choking",
    "emergency",
    # Hindi (romanised + Devanagari)
    "seene mein dard",
    "seene me dard",
    "sine me dard",
    "chhati me dard",
    "chhati mein dard",
    "dil ka daura",
    "saans nahi",
    "saans nahin",
    "saans lene mein",
    "saans lene me",
    "sans nahi",
    "behosh",
    "bahut khoon",
    "khoon beh",
    "khoon nahi ruk",
    "zeher",
    "zahar",
    "atmahatya",
    "सीने में दर्द",
    "छाती में दर्द",
    "दिल का दौरा",
    "सांस नहीं",
    "साँस नहीं",
    "सांस लेने में",
    "साँस लेने में",
    "बेहोश",
    "बहुत खून",
    "खून बह",
    "खून नहीं रुक",
    "ज़हर",
    "जहर",
    "आत्महत्या",
    "दौरा पड़",
    # Gujarati (romanised + script)
    "chhati ma dukhavo",
    "chhati ma dukhe",
    "chhatima dukhavo",
    "shwas nathi",
    "swas nathi",
    "shwas leva ma",
    "bebhan",
    "lohi bandh nathi",
    "khub lohi",
    "jher",
    "aapghat",
    "heart attack aavyo",
    "છાતીમાં દુખાવો",
    "છાતી માં દુખાવો",
    "છાતીમાં દુખે",
    "શ્વાસ નથી",
    "શ્વાસ લેવામાં",
    "બેભાન",
    "ખૂબ લોહી",
    "લોહી બંધ નથી",
    "હાર્ટ એટેક",
    "ઝેર",
    "આપઘાત",
    "એટેક આવ્યો",
)
_MEDICAL = (
    # symptoms / clinical questions → staff, never answered (BR-10)
    "pain",
    "ache",
    "toothache",
    "dard",
    "dukhavo",
    "dukhe",
    "fever",
    "bukhar",
    "tav",
    "taav",
    "swelling",
    "swollen",
    "sojan",
    "sojo",
    "bleeding",
    "blood",
    "khoon",
    "lohi",
    "infection",
    "pus",
    "rash",
    "injury",
    "sprain",
    "fracture",
    "medicine",
    "medicines",
    "tablet",
    "tablets",
    "dawa",
    "dava",
    "davai",
    "prescription",
    "dose",
    "antibiotic",
    "painkiller",
    "stroke",
    "paralysis",
    "accident",
    "report",
    "x-ray",
    "xray",
    "mri",
    "diagnosis",
    "is it serious",
    "what should i take",
    "side effect",
    "allergy",
    "pregnant",
    "sensitivity",
    "cavity",
    "stitches",
    "दर्द",
    "बुखार",
    "सूजन",
    "खून",
    "दवा",
    "दवाई",
    "रिपोर्ट",
    "इंफेक्शन",
    "दुखाव",
    "દુખાવો",
    "દુખે",
    "તાવ",
    "સોજો",
    "લોહી",
    "દવા",
    "રિપોર્ટ",
    "ઇન્ફેક્શન",
)


def classify_safety(text: str) -> Safety:
    t = normalize(text)
    if _has(t, _EMERGENCY):
        return "emergency"
    if _has(t, _MEDICAL):
        return "medical"
    return "none"


# --- intents -------------------------------------------------------------------------------------
_INTENTS: list[tuple[Intent, tuple[str, ...]]] = [
    (
        "staff",
        (
            "talk to staff",
            "human",
            "receptionist",
            "call me",
            "staff",
            "complaint",
            "स्टाफ",
            "શિકાયત",
            "स्टाफ़",
            "સ્ટાફ",
            "शिकायत",
        ),
    ),
    (
        "manage",
        (
            "cancel",
            "reschedule",
            "change time",
            "postpone",
            "radd",
            "rad karo",
            "badalvo",
            "badalna",
            "रद्द",
            "बदल",
            "રદ",
            "બદલ",
        ),
    ),
    ("token", ("token", "walk in", "walk-in", "line", "टोकन", "ટોકન")),
    (
        "queue",
        (
            "status",
            "my turn",
            "how long",
            "kitna time",
            "kitni der",
            "maro varo",
            "mera number",
            "मेरी बारी",
            "મારો વારો",
        ),
    ),
    (
        "info",
        (
            "address",
            "location",
            "where",
            "timing",
            "timings",
            "open",
            "fees",
            "fee",
            "charges",
            "parking",
            "map",
            "kya time",
            "kitne baje",
            "pata",
            "sarnamu",
            "पता",
            "समय",
            "फीस",
            "સરનામું",
            "સમય",
            "ફી",
        ),
    ),
    (
        "book",
        (
            "appointment",
            "apointment",
            "appoinment",
            "appt",
            "book",
            "booking",
            "slot",
            "milna",
            "malvu",
            "checkup",
            "check-up",
            "check up",
            "consultation",
            "visit",
            "mulakat",
            "अपॉइंटमेंट",
            "अपॉइन्टमेंट",
            "बुक",
            "मिलना",
            "એપોઇન્ટમેન્ટ",
            "અપોઇન્ટમેન્ટ",
            "બુક",
            "મુલાકાત",
            "મળવું",
        ),
    ),
    (
        "greeting",
        (
            "hi",
            "hii",
            "hello",
            "hey",
            "namaste",
            "namaskar",
            "kem cho",
            "menu",
            "start over",
            "नमस्ते",
            "नमस्कार",
            "નમસ્તે",
            "કેમ છો",
        ),
    ),
]


def detect_intent(text: str) -> Intent:
    t = normalize(text)
    for intent, phrases in _INTENTS:
        if _has(t, phrases):
            return intent
    return "none"


# --- dates & time of day -------------------------------------------------------------------------
_DAY_WORDS: list[tuple[int, tuple[str, ...]]] = [
    (2, ("parso", "parson", "day after tomorrow", "parmdivas", "param divase", "परसों", "પરમ દિવસે", "પરમદિવસે")),
    (1, ("kal", "kale", "aavti kale", "aavtikale", "tomorrow", "tmrw", "कल", "આવતીકાલે", "કાલે")),
    (0, ("aaj", "aaje", "today", "आज", "આજે")),
]
_WEEKDAYS: list[tuple[int, tuple[str, ...]]] = [
    (0, ("monday", "somvar", "सोमवार", "સોમવાર")),
    (1, ("tuesday", "mangalvar", "मंगलवार", "મંગળવાર")),
    (2, ("wednesday", "budhvar", "बुधवार", "બુધવાર")),
    (3, ("thursday", "guruvar", "brihaspativar", "गुरुवार", "ગુરુવાર")),
    (4, ("friday", "shukravar", "शुक्रवार", "શુક્રવાર")),
    (5, ("saturday", "shanivar", "शनिवार", "શનિવાર")),
    (6, ("sunday", "ravivar", "रविवार", "રવિવાર")),
]
_TOD: list[tuple[TimeOfDay, tuple[str, ...]]] = [
    ("morning", ("morning", "savare", "sawar", "savar", "subah", "subha", "सुबह", "સવારે", "સવાર")),
    ("afternoon", ("afternoon", "bapore", "bapor", "dopahar", "dopehar", "दोपहर", "બપોરે", "બપોર")),
    ("evening", ("evening", "saanje", "sanje", "sanj", "shaam", "sham", "शाम", "સાંજે", "સાંજ")),
]


def parse_date_hint(text: str, today: date) -> date | None:
    t = normalize(text)
    m = re.search(r"(?<!\d)(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{2,4}))?(?!\d)", t)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else today.year
        year = year + 2000 if year < 100 else year
        try:
            candidate = date(year, mo, d)
        except ValueError:
            candidate = None
        if candidate is not None:
            if not m.group(3) and candidate < today:
                candidate = date(today.year + 1, mo, d)
            return candidate
    for offset, words in _DAY_WORDS:
        if _has(t, words):
            return today + timedelta(days=offset)
    for weekday, words in _WEEKDAYS:
        if _has(t, words):
            return today + timedelta(days=(weekday - today.weekday()) % 7)
    return None


def parse_time_of_day(text: str) -> TimeOfDay | None:
    t = normalize(text)
    for tod, words in _TOD:
        if _has(t, words):
            return tod
    return None


def matches_time_of_day(hour: int, tod: TimeOfDay | None) -> bool:
    if tod is None:
        return True
    return {"morning": hour < 12, "afternoon": 12 <= hour < 16, "evening": hour >= 16}[tod]


def parse_age(text: str) -> int | None:
    m = re.search(r"(?<!\d)(\d{1,3})(?!\d)", normalize(text))
    if not m:
        return None
    age = int(m.group(1))
    return age if 0 <= age <= 120 else None


def clean_name(text: str) -> str | None:
    name = re.sub(r"\s+", " ", text).strip(" .,-")
    if not (2 <= len(name) <= 80) or re.search(r"\d", name.translate(_DIGITS)):
        return None
    return name


def clinic_code(text: str) -> str | None:
    """Shared pilot number: patients reach a clinic via a wa.me link / QR containing `#CODE` (Q1)."""
    m = re.search(r"#([A-Za-z0-9]{3,12})\b", text)
    return m.group(1).upper() if m else None
