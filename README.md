# Cadence 🚀

> **Inbox-Aware Job Search Assistant for Students and New Grads** hunting software engineering internships and entry-level roles.

Cadence connects seamlessly to your Gmail (read-only), detects Online Assessments (OAs) and interview invitations using a fast two-stage classifier (rules + LLM), manages reminder loops over Telegram with DST-resilient scheduling, polls monitored employer career boards (Greenhouse, Lever, Ashby), performs dense semantic matching with pgvector, and automates recruiter outreach nudges.

---

## 🏗️ System Architecture

```mermaid
flowchart TD
    subgraph Ingestion ["1. Multi-Source Ingestion"]
        GM["Gmail API (read-only)"] -->|history.list sync| GP["Gmail Poller (every 4 min)"]
        ATS["Career Boards (Greenhouse, Lever, Ashby)"] -->|HTTP polling & diffing| JP["Job Poller (every 5 min)"]
        RES["Candidate Resume (PDF/DOCX)"] -->|FastAPI In-Memory Parser| EXT["LLM Resume Profile Extractor"]
    end

    subgraph Intelligence ["2. Two-Stage Classifier & Semantic Matching"]
        GP --> S1["Stage 1: Regex & Domain Filter (<1ms)"]
        S1 -->|Candidate Signals| S2["Stage 2: Structured LLM Classifier"]
        S2 -->|OA / Interview Events| DB_EVT["Events Table"]
        S2 -->|Application Confirmation| AT["Application Tracker"]
        
        EXT --> EMB["Dense Vector Embeddings"]
        JP --> EMB
        EMB --> DB_VEC[("PostgreSQL + pgvector")]
        DB_VEC --> MATCHER["Job Matcher (Cosine Similarity >= 0.40)"]
    end

    subgraph ApplicationOutreach ["3. Cold Outreach & Sent Verification"]
        AT --> SENT["Gmail Sent Search (to:@domain, 60d)"]
        SENT -->|Prior Outreach Exists| SILENT["Log cold_email_detected (Silent)"]
        SENT -->|No Outreach Found| DRAFT["LLM Cold Email Drafter + LinkedIn Deep-Links"]
    end

    subgraph Dispatcher ["4. DST-Safe Reminders & Telegram Bot"]
        DB_EVT --> REM["Reminder Scheduler (10:00 & 19:00 User Time)"]
        REM --> TICK["Tick Worker (SELECT FOR UPDATE SKIP LOCKED)"]
        TICK --> BOT["Telegram Bot Dispatcher"]
        MATCHER --> BOT
        DRAFT --> BOT
        BOT -->|Interactive Alerts & Action Buttons| USER(("Candidate (Telegram)"))
        USER -->|/matches, /applications, /lead, Recur, Dismiss| BOT
    end
```

---

## 💡 Key Design Decisions & Engineering Highlights

### 1. Privacy-Minimal Storage by Design
- **Zero Raw Email/Resume Persistence**: Cadence requests strictly the `gmail.readonly` OAuth scope. Email bodies, subjects, and uploaded resume PDFs are processed strictly in-memory and are **never saved to disk, logged, or stored in the database**.
- **Fernet Symmetric Encryption**: OAuth refresh tokens are encrypted at rest using AES-128-CBC + HMAC-SHA256 authenticated Fernet keys.
- **GDPR-Compliant Full Data Deletion**: Candidates can wipe their account, all database records, and automatically revoke Google OAuth permissions instantly with `/delete_my_data`.

### 2. Two-Stage Classification Pipeline
- **Stage 1 (Rules Filter)**: Evaluates sender domains (HackerRank, CodeSignal, HireVue, Greenhouse, Lever, etc.) and keyword patterns in `<1ms`, eliminating 90%+ of inbox noise before invoking an LLM.
- **Stage 2 (Structured LLM Classifier)**: Extracts structured JSON with candidate platform, company name, role title, and ISO deadline with schema validation and model fallback across `gemini-3.5-flash`, `gemini-3.8-flash`, and `claude-3-5-haiku`.
- **Benchmark Accuracy**: Evaluated on hand-labeled email fixtures with **100% precision, recall, and F1-score across all 5 classes** (`oa`, `interview`, `application_confirmation`, `rejection`, `other`).

### 3. DST-Safe Pure Scheduling Math
- **Local Time Wall-Clock Anchors**: Reminders fire at candidate-friendly morning (10:00) and evening (19:00) slots.
- **ZoneInfo Conversions**: Calculates next fire timestamps using native Python `zoneinfo` objects, completely eliminating DST spring-forward (23-hour days) and fall-back (25-hour days) clock drift bugs.
- **Distributed Idempotency**: The reminder tick worker queries due notifications using `SELECT FOR UPDATE SKIP LOCKED`, preventing race conditions across worker replicas.

### 4. Career Board Polling & pgvector Semantic Matching
- **Multi-ATS Public API Connectors**: Native adapters for **Greenhouse**, **Lever**, and **Ashby** scraping over 40+ curated top technology, fintech, robotics, and autonomy companies.
- **Cosine Similarity Ranking**: Embeds candidate resume profiles (skills, target roles, project themes) and open job listings into dense 768-dimensional vectors with `pgvector` HNSW indexes and hard filters (grad year, location).
- **Deduplicated Alerts**: Tracks delivered matches via `job_alerts` table to ensure candidates never receive duplicate alerts for the same opening.

### 5. Sent Folder Outreach Verification & Recruiter Deep-Links
- **Outreach Detection**: When an `application_confirmation` email is detected, Cadence searches the user's Gmail Sent folder (`to:{domain} newer_than:60d`) for prior notes.
- **Smart Branching**: If prior outreach is detected, Cadence remains silent; if no outreach is found, Cadence sends a Telegram nudge with instant LinkedIn University Recruiter search links, Hiring Manager search links, and an LLM-drafted personalized cold email.

---

## 🛠️ Tech Stack

- **Backend & API**: Python 3.12+, FastAPI, Uvicorn, Pydantic v2 & Pydantic-Settings
- **Database & Vectors**: PostgreSQL 16, pgvector, SQLAlchemy 2.0 (asyncpg), Alembic
- **Messaging & Bot**: python-telegram-bot v21+ (Async HTTP)
- **AI / LLM & Embeddings**: Google Gemini (`google-genai` SDK), Anthropic Claude (`anthropic`)
- **Testing & Quality**: pytest, pytest-asyncio, ruff (linter & formatter), mypy (strict typing)

---

## 🚀 Local Development Setup

### 1. Prerequisites
- Python 3.12+
- Docker & Docker Compose (or local PostgreSQL with pgvector)
- Google Cloud Console Project (with Gmail API enabled and OAuth credentials)
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- Google Gemini API Key (or Anthropic API Key)

### 2. Clone & Environment Configuration
```bash
git clone https://github.com/Insight14/Cadence.git
cd Cadence

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Configure environment variables
cp .env.example .env
```

Generate a 32-byte urlsafe Fernet encryption key:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Update `.env` with your credentials:
```ini
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/jobpilot
DATABASE_SYNC_URL=postgresql://postgres:postgres@localhost:5432/jobpilot
FERNET_KEY=your_generated_fernet_key_here
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback
GEMINI_API_KEY=your_gemini_api_key
LLM_MODEL=gemini-3.5-flash
```

### 3. Start Database & Run Migrations
```bash
# Start PostgreSQL with pgvector extension
docker compose up -d db

# Apply database migrations
alembic upgrade head

# Seed monitored companies catalog (40+ top employers)
python scripts/seed_companies.py
```

### 4. Start the Application
You can run the FastAPI server and background workers locally:

```bash
# Terminal 1: FastAPI Web Server & Onboarding UI
uvicorn jobpilot.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2: Worker Loops (Gmail poller, Job board poller, Reminder ticks)
python -m jobpilot.worker
```

Open `http://localhost:8000` in your browser to connect Gmail, upload your resume, and link your Telegram account.

---

## 🤖 Telegram Bot Commands

| Command | Description |
| :--- | :--- |
| `/start` | Launch bot, view linked account status, and see command overview |
| `/link <token_or_email>` | Link Telegram chat to your Cadence account |
| `/matches` | View top open job matches ranked by resume similarity |
| `/applications` | Track all active applications, applied dates, and outreach status |
| `/lead <job_url>` | Manually track a job lead from Discord, LinkedIn, or Instagram |
| `/threshold <score>` | Customize minimum affinity score threshold (e.g. `/threshold 0.50`) |
| `/stats` | View personal summary of tracked apps, active reminders, and alerts |
| `/mute <company>` | Mute match alerts for a specific employer |
| `/unmute <company>` | Unmute match alerts for an employer |
| `/timezone <IANA>` | Update local timezone (e.g. `/timezone America/Chicago`) |
| `/pause` | Temporarily pause all reminder notifications |
| `/resume` | Resume reminder notifications |
| `/delete_my_data` | Permanently delete all user records and revoke Google OAuth tokens |

---

## 🧪 Testing & Evaluation

### Run Unit Tests
```bash
pytest
```
*Cadence includes 100 comprehensive unit tests with zero external network calls.*

### Run Code Quality & Type Checks
```bash
ruff check .
ruff format --check .
mypy src tests
```

### Run Two-Stage Classifier Evaluation Harness
```bash
python tests/eval/run_eval.py
```

### View Live Operational Metrics
```bash
python scripts/metrics.py
```

---

## 📄 License
MIT License. Built for students & new grads.
