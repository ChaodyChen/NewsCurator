# Semiconductor News Curator

Automated news curation system for semiconductor industry updates. Fetches daily news, enables manual ranking, and delivers curated top 5 stories to LINE every Monday at 8am.

**Status:** Phase 1 Implementation (MVP)

---

## Quick Start

### 1. Setup Environment

```bash
# Clone/navigate to project
cd NewsCurator

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Credentials

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Then edit `.env` with:
- **NEWSAPI_KEY**: Get from https://newsapi.org
- **LINE_CHANNEL_ACCESS_TOKEN**: Get from LINE Developers Console
- **LINE_CHANNEL_SECRET**: Get from LINE Developers Console
- **LINE_GROUP_ID**: Your LINE group ID
- **GOOGLE_APPLICATION_CREDENTIALS**: Path to Google service account JSON
- **GOOGLE_DRIVE_FOLDER_ID**: Your Google Drive folder for storing CSVs
- **FALLBACK_RECIPIENT_EMAIL**: Your email for error alerts
- **SMTP_USER** & **SMTP_PASSWORD**: Email account for fallback alerts

### 3. Run Tests

```bash
# Run all tests with coverage
pytest

# Run specific test file
pytest tests/test_fetch_candidates.py

# Run with verbose output
pytest -v

# Run only unit tests
pytest -m unit
```

### 4. Run Application

```bash
# Start web server for curation form
python src/app.py
# Opens at http://localhost:5000

# Schedule daily fetch (requires Cloud Scheduler or similar)
python src/fetch_candidates.py --schedule

# Schedule Monday delivery (requires Cloud Scheduler or similar)
python src/delivery.py --schedule
```

---

## Project Structure

```
.
├── src/
│   ├── __init__.py
│   ├── config.py                 # Configuration management
│   ├── fetch_candidates.py       # Daily news fetch pipeline
│   ├── curation_form.py          # Curation logic
│   ├── delivery.py               # LINE/email delivery
│   └── app.py                    # Flask web application
├── tests/
│   ├── __init__.py
│   ├── test_fetch_candidates.py
│   ├── test_curation_form.py
│   ├── test_delivery.py
│   └── test_app.py
├── config/                        # Configuration templates
├── .env.example                  # Environment variable template
├── requirements.txt              # Python dependencies
├── pytest.ini                    # Pytest configuration
└── README.md                     # This file
```

---

## Architecture Overview

### Data Flow

```
┌──────────────────────────────────────────────┐
│  DAILY FETCH (Mon-Fri 6am via remote trigger)│
├──────────────────────────────────────────────┤
│  1. Fetch from NewsAPI (keywords + sources)  │
│  2. Verify URL (HEAD request, 5sec timeout)  │
│  3. Filter by timestamp (<48h old)           │
│  4. Deduplicate by URL                       │
│  5. Save to CSV on Google Drive              │
└──────────────────────────────────────────────┘
              ↓
┌──────────────────────────────────────────────┐
│  WEEKLY CURATION (You, Thu/Fri evening)      │
├──────────────────────────────────────────────┤
│  1. Visit http://localhost:5000/curate       │
│  2. Review 15-20 candidate stories           │
│  3. Rank top 6-7 (or mark "skip")            │
│  4. Submit (saves to selections CSV)         │
└──────────────────────────────────────────────┘
              ↓
┌──────────────────────────────────────────────┐
│  MONDAY DELIVERY (8:00 AM via remote trigger)│
├──────────────────────────────────────────────┤
│  1. Load top 6-7 ranked stories              │
│  2. Verify links final time                  │
│  3. Promote reserves if links are dead       │
│  4. Format as LINE message                   │
│  5. Send to LINE group                       │
│  6. Fallback: email alert if LINE fails      │
└──────────────────────────────────────────────┘
```

### Key Decisions

- **CSV + Google Drive** (Phase 1): Simple, human-readable. Transition to database in Phase 2.
- **6-7 story ranking**: Rank 6-7 serve as automatic reserves if top 5 link dies.
- **Sequential URL verification**: 40 seconds for 20 URLs is acceptable at 6am.
- **Server-side curation form**: Reads/writes directly to Google Drive; seamless UX.
- **Email fallback**: If LINE fails, alert is sent to you (not auto-delivery to team).

---

## Phase 1 Checklist

### Week 1-2: MVP Implementation

- [ ] NewsAPI integration (fetch_candidates.py)
- [ ] URL verification (HEAD requests, timeout handling)
- [ ] Timestamp filtering and deduplication
- [ ] CSV storage on Google Drive
- [ ] Flask curation form (minimal UI)
- [ ] Curation logic (ranking, validation)
- [ ] LINE delivery module
- [ ] Email fallback integration
- [ ] Remote trigger setup (daily fetch, Monday delivery)
- [ ] End-to-end testing

### Phase 2: ML Learning (Weeks 3-4+)

After 4-8 weeks of your selections:
- [ ] Collect training data (>30 selections)
- [ ] Train scikit-learn logistic regression model
- [ ] Auto-ranking suggestions in curation form
- [ ] Transition from CSV to PostgreSQL database
- [ ] Continuous model retraining weekly

---

## Development Notes

### Test Coverage

Target: 80%+ coverage of critical paths

Critical paths (must test):
1. URL verification (404, timeout, success)
2. Reserve story promotion (when links die)
3. LINE delivery (success, failure, retry)
4. Email fallback (when LINE fails)
5. End-to-end: fetch → curate → deliver

See `tests/` for test stubs. Each function has 2-3 TODO comments with test cases.

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage report
pytest --cov=src --cov-report=html

# Run only tests with "verify" in the name
pytest -k verify

# Run with detailed output
pytest -vv
```

### Google Drive Integration

The curation form needs to read/write CSV files on Google Drive:

1. **Setup Google credentials:**
   - Create service account in Google Cloud Console
   - Download service account JSON key
   - Set `GOOGLE_APPLICATION_CREDENTIALS` to path of JSON file

2. **Share folder with service account:**
   - Create folder in Google Drive
   - Share with service account email
   - Set `GOOGLE_DRIVE_FOLDER_ID` in `.env`

3. **File structure on Drive:**
   ```
   /your-folder/
   ├── candidates-2026-03-24.csv
   ├── candidates-2026-03-31.csv
   ├── selections-2026-03-24.csv
   └── selections-2026-03-31.csv
   ```

### LINE Bot Setup

1. Create LINE bot in LINE Developers Console
2. Get Channel Access Token → set as `LINE_CHANNEL_ACCESS_TOKEN`
3. Get Group ID: Send a message in group, then query API to find group ID
4. Test with:
   ```python
   from src.delivery import send_via_line
   send_via_line("Test message", access_token, group_id)
   ```

---

## Troubleshooting

### CSV Concurrency Issues

**Problem:** You're editing candidates.csv while cron fetches new data.

**Solution:** Use timestamped filenames:
- `candidates-2026-03-24.csv` (Monday fetch)
- `candidates-2026-03-31.csv` (next Monday fetch)
- You always edit this week's file; cron writes to next week's file.

### URL Verification Timeout

**Problem:** Verify taking >40 seconds for 20 URLs.

**Solution:** Increase parallel verification in Phase 2. For now, accept 40 seconds.

### LINE API Errors

**Problem:** 401 Unauthorized from LINE API.

**Solution:** Verify `LINE_CHANNEL_ACCESS_TOKEN` is valid. Regenerate if expired.

**Problem:** 429 Rate Limited.

**Solution:** Reduce message volume or add retry backoff (already in code).

---

## TODOs (Deferred to Phase 2+)

- [ ] Database transition (CSV → PostgreSQL)
- [ ] ML model training (after 4-8 weeks of selections)
- [ ] Parallel URL verification (if volume grows)
- [ ] Multi-group LINE delivery (per-team targeting)
- [ ] Auto-source discovery (find new high-value sources)

---

## References

- **Design Doc:** [User-master-design-20260326-101729.md](./User-master-design-20260326-101729.md)
- **NewsAPI:** https://newsapi.org/docs
- **LINE Bot SDK:** https://github.com/line/line-bot-sdk-python
- **Google Drive API:** https://developers.google.com/drive/api/guides/about-sdk
- **Flask:** https://flask.palletsprojects.com/
- **Pytest:** https://docs.pytest.org/

---

## Questions?

See the design doc for detailed rationale on architecture, scope, and Phase 2 plans.
