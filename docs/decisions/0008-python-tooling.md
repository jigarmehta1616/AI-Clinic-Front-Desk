# ADR-0008 Python tooling
Status: accepted
Python 3.12+ target (CI 3.12; dev machine 3.14). `pyproject.toml` + pip, ruff (lint+format), mypy (strict on `core`, `policy` modules), pytest + pytest-asyncio. Docker image `python:3.12-slim`. `uv` may replace pip later without code impact.
