# Cadence 🛫

> Inbox-aware job-search assistant for students and new grads hunting internships and entry-level engineering roles.

Cadence connects to your Gmail (read-only), detects Online Assessments (OAs) and interview invitations using a fast two-stage filter (rules + LLM), manages reminders over Telegram with interactive recurrence, polls company career boards, and automates cold-email nudges.

---

## Architecture Overview

```mermaid
flowchart TD
    subgraph Ingestion & Polling
        GM[Gmail API - read-only] -->|history.list sync| GP[Gmail Poller]
        ATS[ATS Job Boards\nGreenhouse, Lever, Ashby] -->|career board fetch| JP[Job Board Poller]
    end

    subgraph Intelligence
        GP --> S1[Stage 1: Rule-based Keyword/Domain Filter]
        S1 -->|Candidate Emails| S2[Stage 2: LLM Classifier & Extraction]
        S2 --> DB[(PostgreSQL + pgvector)]
        JP --> DB
    end

    subgraph Reminders & Notifications
        TW[Tick Worker\nSELECT FOR UPDATE SKIP LOCKED] -->|evaluate next_fire_at| BOT[Telegram Bot]
        BOT -->|Recur / Dismiss callbacks| DB
        BOT -->|Alerts & Nudges| User((User))
    end
```

---

## Core Features

- **Privacy-Minimal:** Read-only Gmail scope; email bodies and subjects are processed in memory and never persisted to the database or logged.
- **Smart OA / Interview Reminders:** Interactive Telegram inline buttons (`[🔁 Recur] [✖ Dismiss]`) that fire at 10:00 & 19:00 user local time with DST resilience.
- **Career Board Polling:** High-frequency diffing on Greenhouse, Lever, and Ashby boards with pgvector similarity matching against resume profiles.
- **Application Outreach Nudges:** Detects confirmation emails and nudges users with tailored cold-email drafts and LinkedIn recruiter search links.

---

## Quickstart

### 1. Prerequisites
- Python 3.12+
- Docker & Docker Compose
- Telegram Bot Token ([@BotFather](https://t.me/BotFather))
- Google Cloud Console OAuth 2.0 Client Credentials
- Anthropic API Key

### 2. Environment Setup
```bash
cp .env.example .env
# Fill in your database URL, Fernet encryption key, Telegram bot token, and API keys
```

Generate a Fernet secret key:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 3. Local Development with Docker Compose
```bash
docker compose up --build
```

### 4. Running Migrations
```bash
alembic upgrade head
```

### 5. Running Tests & Quality Checks
```bash
pytest
ruff check .
mypy src tests
```
