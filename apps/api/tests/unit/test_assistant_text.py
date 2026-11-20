"""BR-10, FR-2.1, FR-2.6, FR-2.9, FR-8.3, AC-1/AC-8/AC-9 — deterministic understanding layer."""

from datetime import date

import pytest

from clinicdesk.modules.assistant.text import (
    classify_safety,
    clean_name,
    clinic_code,
    detect_intent,
    detect_language,
    is_start,
    is_stop,
    matches_time_of_day,
    parse_age,
    parse_date_hint,
    parse_time_of_day,
)

MON = date(2026, 11, 23)


@pytest.mark.parametrize(
    "text",
    [
        "chest pain",
        "My father has CHEST PAIN since morning",
        "he fainted",
        "can't breathe",
        "heavy bleeding",
        "seene mein dard ho raha hai",
        "सीने में दर्द",
        "सांस नहीं ले पा रहा",
        "બેભાન થઈ ગયા",
        "છાતીમાં દુખાવો થાય છે",
        "chhati ma dukhavo",
        "slurred speech and face drooping",
        "emergency",
    ],
)
def test_emergencies_detected_in_all_languages(text):
    """AC-8, FR-8.3."""
    assert classify_safety(text) == "emergency"


@pytest.mark.parametrize(
    "text",
    [
        "which medicine for tooth pain",
        "I have fever",
        "dant ma dukhavo che",
        "दांत में दर्द",
        "મને તાવ છે",
        "can you check my x-ray report",
        "physio for stroke rehab",
        "paralysis therapy",
        "after accident knee pain",
    ],
)
def test_medical_topics_go_to_staff_not_emergency(text):
    """BR-10, FR-2.6; rehab words are medical, not emergency (physio clinics)."""
    assert classify_safety(text) == "medical"


@pytest.mark.parametrize("text", ["appointment kal savare", "hi", "book for tomorrow", "what are your timings"])
def test_ordinary_messages_are_safe(text):
    assert classify_safety(text) == "none"


@pytest.mark.parametrize("text", ["STOP", "stop", " Stop. ", "unsubscribe", "બંધ", "बंद करो", "band karo"])
def test_stop_words(text):
    """FR-2.9, AC-9."""
    assert is_stop(text)


@pytest.mark.parametrize("text", ["don't stop my appointment", "stop reminders please call me", "bus stop"])
def test_stop_requires_whole_message(text):
    assert not is_stop(text)


def test_start_words():
    assert is_start("START") and is_start("ચાલુ") and not is_start("start my booking")


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("appointment kal savare", "book"),
        ("મારે એપોઇન્ટમેન્ટ જોઈએ", "book"),
        ("अपॉइंटमेंट चाहिए", "book"),
        ("cancel my appointment", "manage"),
        ("reschedule please", "manage"),
        ("token", "token"),
        ("what is the address", "info"),
        ("Hi", "greeting"),
        ("kem cho", "greeting"),
        ("talk to staff", "staff"),
        ("asdfgh", "none"),
    ],
)
def test_intents(text, intent):
    assert detect_intent(text) == intent


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("appointment kal savare", date(2026, 11, 24)),
        ("aavti kale", date(2026, 11, 24)),
        ("કાલે", date(2026, 11, 24)),
        ("कल सुबह", date(2026, 11, 24)),
        ("today", MON),
        ("aaje", MON),
        ("parso", date(2026, 11, 25)),
        ("on friday", date(2026, 11, 27)),
        ("shukravar", date(2026, 11, 27)),
        ("monday", MON),
        ("28/11", date(2026, 11, 28)),
        ("5-1", date(2027, 1, 5)),
        ("૨૮/૧૧", date(2026, 11, 28)),
        ("book appointment", None),
        ("kale" + "x", None),
    ],
)
def test_date_hints(text, expected):
    assert parse_date_hint(text, MON) == expected


@pytest.mark.parametrize(
    ("text", "tod"),
    [
        ("kal savare", "morning"),
        ("સવારે", "morning"),
        ("subah", "morning"),
        ("bapore", "afternoon"),
        ("शाम को", "evening"),
        ("sanje", "evening"),
        ("tomorrow", None),
    ],
)
def test_time_of_day(text, tod):
    assert parse_time_of_day(text) == tod


def test_time_of_day_filter():
    assert matches_time_of_day(10, "morning") and not matches_time_of_day(12, "morning")
    assert matches_time_of_day(17, "evening") and matches_time_of_day(9, None)


@pytest.mark.parametrize(
    ("text", "lang", "strong"),
    [
        ("છાતીમાં", "gu", True),
        ("नमस्ते", "hi", True),
        ("kale savare aavvu che", "gu", False),
        ("mujhe kal appointment chahiye", "hi", False),
        ("book tomorrow", "en", False),
    ],
)
def test_language_detection(text, lang, strong):
    assert detect_language(text, default="en") == (lang, strong)


def test_age_name_and_clinic_code():
    assert parse_age("64") == 64 and parse_age("૬૪ વર્ષ") == 64 and parse_age("I am 130") is None
    assert parse_age("sixty") is None
    assert clean_name("  Kantaben Patel. ") == "Kantaben Patel" and clean_name("12345") is None
    assert clinic_code("Hi #smile12 appointment") == "SMILE12" and clinic_code("hello") is None


@pytest.mark.parametrize(
    "text", ["chest pain since morning, what to do", "chest pain, please help", "I need an appointment"]
)
def test_plain_english_is_not_answered_in_clinic_default_language(text):
    """NFR-9: English sentences get English replies even when the clinic's first language is Gujarati."""
    assert detect_language(text, default="gu") == ("en", False)


def test_mixed_romanised_still_uses_default_on_tie():
    """'appointment kal savare' has one Hindi and one Gujarati cue: falls back to the clinic default."""
    assert detect_language("appointment kal savare", default="gu") == ("gu", False)
