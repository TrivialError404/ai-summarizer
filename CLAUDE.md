# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI-powered summarizer that fetches content from various sources, generates summaries via a local **Ollama** LLM, and delivers them (currently via email). Sources currently: **IMAP emails** and **heise.de articles**.

## Project Goals

Periodically summarize content from various sources in the background using a local LLM.

- **Extensible sources** — currently emails + heise.de; planned: more news (politics, business), job postings, etc. New sources always follow the same pipeline: scrape data → convert to Markdown → manually analyze Markdown → define LLM prompt → generate summary → store/send
- **Flexible output** — currently email (sender = recipient); both the delivery channel and sender may change in the future
- **Automation** — Docker-based cronjob on a VM/server. A config controls what gets summarized and how it gets delivered
- **Configurator** — planned: controls which sources, which prompts, which output format
- **Robust deployment** — making Docker run on a fresh VM (planned for later)

## Running

```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium  # needed for heise.de auth

# Run the main pipeline
python main.py

# Debug individual sources (run from project root)
python scripts/debug_email.py
python scripts/debug_heise.py
python scripts/debug_llm.py
```

**Docker** (from `deploy/`):
```bash
docker compose -f deploy/docker-compose.yml up
```

## Environment Variables

Copy `.env.example` to `.env`. Key variables:
- `IMAP_USER` / `IMAP_PASSWORD` — email credentials (App Password required, reused for SMTP)
- `OLLAMA_HOST` / `OLLAMA_MODEL` — Ollama endpoint and model (default: `llama3.2`)
- `HEISE_USERNAME` / `HEISE_PASSWORD` — heise.de login for authenticated scraping

## Architecture

```
main.py                              # orchestration, prompt templates, pipeline logic
├── sources/                         # source-specific logic (one subpackage per source)
│   ├── email/
│   │   └── email_postprocessing.py  # md_postprocess_remove_reply
│   └── heise/
│       ├── heise_scraper.py         # RSS + archive scraping, content extraction, md_postprocess_remove_section_noise
│       └── heise_auth.py            # Playwright-based login for heise.de
├── lib/                             # generic, reusable modules
│   ├── email/
│   │   ├── providers.py             # shared IMAP/SMTP provider registry (single source of truth)
│   │   ├── email_fetcher.py         # IMAP client
│   │   └── email_sender.py          # SMTP client
│   ├── llm_ollama.py                # Ollama /api/generate wrapper
│   ├── html_to_markdown.py          # generic HTML→Markdown conversion (no source-specific logic)
│   └── utils.py                     # JSON I/O, date formatting
├── scripts/                         # debug/development scripts
├── deploy/                          # Dockerfile, docker-compose.yml, entrypoint.sh
└── tests/                           # (planned)
```

**Pipeline pattern** (same for every source):
```
source (scrape/fetch) → html_to_markdown → source-specific md postprocessing → llm_ollama → output
```

- **`sources/`** — source-specific logic: scraping, authentication, Markdown postprocessing. Each source may import from `lib/` but never from other sources.
- **`lib/`** — generic modules with no project-specific logic. Designed to be reusable across projects. Provider registry in `lib/email/providers.py` is the single source of truth for IMAP+SMTP config.
- **`scripts/`** — standalone debug scripts. Run from project root.

## Key Design Decisions

- All LLM prompts and output are in **German** (2-sentence summaries for emails, 3-sentence for articles)
- Locale is set to `de_DE.UTF-8` for German date formatting
- Raw and processed data are saved to `temp/{email,heise}/` as JSON + human-readable `.txt`
- Email provider is auto-detected from the domain in `IMAP_USER` — custom SMTP host/port can override
- Heise authentication uses Playwright to handle JS-heavy login, then transfers cookies to `requests.Session`
