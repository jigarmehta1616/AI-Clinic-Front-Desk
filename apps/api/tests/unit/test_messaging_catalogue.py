"""NFR-9 catalogue completeness, WhatsApp limits, BR-9 templates, webhook signature, payload shapes."""

import hashlib
import hmac
import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from clinicdesk.integrations.whatsapp import LIMITS, build_payload, option_ids, text_of, verify_signature
from clinicdesk.modules.messaging.templates import (
    LANGS,
    META_TEMPLATES,
    TEMPLATE_BODY,
    T,
    fmt_date,
    fmt_time,
    t,
    template_ref,
)

IST = ZoneInfo("Asia/Kolkata")
BUTTON_KEYS = [k for k in T if k.startswith("btn_")]
ROW_KEYS = [k for k in T if k.startswith("row_")]
LIST_BUTTON_KEYS = ["menu_button", "days_button", "times_button", "patients_button"]


def test_every_key_in_every_language_with_same_placeholders():
    for key, by_lang in T.items():
        assert set(by_lang) == set(LANGS), key
        fields = {lang: set(re.findall(r"{(\w+)}", text)) for lang, text in by_lang.items()}
        assert len({frozenset(v) for v in fields.values()}) == 1, (key, fields)


@pytest.mark.parametrize("lang", LANGS)
def test_whatsapp_length_limits(lang):
    for k in BUTTON_KEYS:
        assert len(T[k][lang]) <= LIMITS["button_title"], (k, lang)
    for k in ROW_KEYS:
        assert len(T[k][lang]) <= LIMITS["row_title"], (k, lang)
    for k in LIST_BUTTON_KEYS:
        assert len(T[k][lang]) <= LIMITS["list_button"], (k, lang)
    for k, by_lang in T.items():
        assert len(by_lang[lang]) <= LIMITS["body"], (k, lang)


def test_emergency_text_never_claims_services_were_contacted():
    """FR-8.3 / AC-8: advise calling 108/112; only claim that clinic staff were alerted."""
    for lang in LANGS:
        text = T["emergency"][lang]
        assert "108" in text and "112" in text and "{clinic_phone}" in text
    assert not re.search(
        r"(we|have) (called|contacted|informed) (an )?(ambulance|108|112|emergency)", T["emergency"]["en"], re.I
    )


def test_meta_templates_exist_in_catalogue():
    for name, params in META_TEMPLATES.items():
        body_key = TEMPLATE_BODY.get(name, name)
        assert body_key in T, name
        assert set(params) <= set(re.findall(r"{(\w+)}", T[body_key]["en"])), name
    ref = template_ref("token_alert", "gu", token=7, ahead=3)
    assert ref == {"name": "token_alert", "language": "gu", "params": ["7", "3"]}


def test_formatting():
    at = datetime(2026, 11, 24, 4, 45, tzinfo=UTC)  # Tue 10:15 IST
    assert fmt_date(at, IST, "en") == "Tue 24 Nov" and fmt_date(at, IST, "gu") == "મંગળ 24/11"
    assert fmt_time(at, IST) == "10:15 AM"
    assert t("pick_slot", "hi", date="x") == "x को खाली समय:"


def test_signature_verification():
    body = b'{"entry":[]}'
    good = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert verify_signature(body, good, "secret")
    assert not verify_signature(body + b" ", good, "secret")
    assert not verify_signature(body, good, "")  # no secret configured → reject everything
    assert not verify_signature(body, None, "secret")


def test_payload_shapes_and_clipping():
    btn = build_payload(
        "+919800000001",
        {
            "type": "buttons",
            "text": "Q?",
            "buttons": [
                {"id": "a", "title": "x" * 40},
                {"id": "b", "title": "B"},
                {"id": "c", "title": "C"},
                {"id": "d", "title": "D"},
            ],
        },
        None,
    )
    assert btn["to"] == "919800000001" and option_ids(btn) == ["a", "b", "c"]
    assert len(btn["interactive"]["action"]["buttons"][0]["reply"]["title"]) == 20
    lst = build_payload(
        "+91",
        {"type": "list", "text": "Pick", "button": "Times", "rows": [{"id": f"r{i}", "title": "t"} for i in range(12)]},
        None,
    )
    assert len(option_ids(lst)) == 10 and text_of(lst) == "Pick"
    tpl = build_payload(
        "+91", None, {**template_ref("noshow_rebook", "hi", clinic="Smile"), "quick_replies": ["rebook:1"]}
    )
    assert tpl["template"]["language"]["code"] == "hi"
    assert tpl["template"]["components"][0]["parameters"] == [{"type": "text", "text": "Smile"}]
    assert tpl["template"]["components"][1]["parameters"] == [{"type": "payload", "payload": "rebook:1"}]
