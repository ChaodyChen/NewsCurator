# NewsCurator — Claude Code Instructions

## Architecture Overview

```
Anthropic Cloud (CCR) — Automated Fetch
├── Trigger ID: trig_01Qf7UAouay2enJ4okAXEiqJ
├── Schedule: Daily 7:45 AM Taipei time (UTC+8)
└── Every day → fetch_candidates (NewsAPI → data/) → git push

PythonAnywhere — Curation UI + Delivery
├── URL: https://chaody.pythonanywhere.com/curate
├── Serves Flask curation form (Fri–Sun)
├── git pull → reads candidates CSV from data/
├── Saves selections CSV to data/ → auto git push
├── POST /api/deliver → Monday 8am delivery via LINE
└── Scheduled Task: curl -X POST .../api/deliver (Mon 00:00 UTC = 8am Taipei)

GitHub (data/) — Shared Storage
├── data/candidates-YYYY-MM-DD.csv (written by CCR, read by PythonAnywhere)
└── data/selections-YYYY-MM-DD.csv (written by PythonAnywhere, read by CCR)
```

## Deploy Configuration (configured by /setup-deploy)
- Platform: PythonAnywhere
- Production URL: https://chaody.pythonanywhere.com
- Deploy workflow: manual git pull in PythonAnywhere bash console
- Deploy status command: HTTP health check
- Merge method: squash
- Project type: web app
- Post-deploy health check: https://chaody.pythonanywhere.com/api/health

### Custom deploy hooks
- Pre-merge: none
- Deploy trigger: git pull in PythonAnywhere bash console
- Deploy status: poll https://chaody.pythonanywhere.com/api/health
- Health check: https://chaody.pythonanywhere.com/api/health
