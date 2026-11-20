# ADR-0006 Constrained assistant: LLM for NLU only
Status: accepted
**Decision** LLM returns a validated structured object (intent + entities + language). A LangGraph state machine and deterministic tools perform every action; replies come from a reviewed multilingual template catalogue. Safety and STOP handling run before the LLM. Button-only mode is a complete fallback.
**Why** BR-10 patient safety, NFR-1 latency, NFR-12 cost, testability, WhatsApp template rules.
