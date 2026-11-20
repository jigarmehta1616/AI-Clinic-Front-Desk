---
name: ai-agent-engineering
description: LangGraph assistant, structured NLU, tools, language handling, prompts and safety guardrails. Use when changing anything in modules/assistant or integrations/llm.
---
# AI agent engineering
**Purpose** A constrained, safe, cheap assistant — the LLM understands, code acts.
**When to use** Intents, prompts, tools, language detection, safety, LLM provider changes.
**Required context** `docs/architecture/ai-agent-design.md`, ADR-0006.

## Engineering rules
- LLM output is a validated Pydantic object (intent, entities, language, confidence). It never writes SQL, never chooses tenant/patient ids, never free-writes medical text.
- Fixed order: STOP & button payloads → emergency/medical lexicon → consent gate → NLU → state machine → tools → template reply.
- Tools validate args, inject tenant from context, call module services. Add a tool only with an FR id.
- Redact before every provider call: phones, names, ages → placeholders; no full history (DP-7).
- Timeout 2 s, temperature 0, smallest adequate model; any failure → button menu.
- Replies come from the template catalogue; every template exists in gu, hi and en.
- Trace each turn to Langfuse with cost (NFR-11/12).

## Validation checklist
- [ ] Fixture cases in gu/hi/en/mixed for new intents
- [ ] Emergency and medical cases still escalate (AC-8)
- [ ] Flow works with LLM disabled (button mode)
- [ ] Redaction test covers new fields
