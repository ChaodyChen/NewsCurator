# NewsCurator — Claude Code Instructions

## Architecture Overview

```
Anthropic Cloud (CCR) — Automated
├── Trigger ID: trig_01Qf7UAouay2enJ4okAXEiqJ
├── Schedule: Daily 7:45 AM Taipei time (UTC+8)
├── Monday → deliver_news (send top 5 via LINE)
└── Tue–Sun → fetch_candidates (NewsAPI → Google Drive)

PythonAnywhere — Manual Curation UI
├── URL: https://chaody.pythonanywhere.com/curate
├── Serves Flask curation form (Fri–Sun)
├── Reads candidates CSV from Google Drive
└── Saves selections CSV to Google Drive

Google Drive — Shared Storage
├── candidates-YYYY-MM-DD.csv (written by CCR, read by PythonAnywhere)
└── selections-YYYY-MM-DD.csv (written by PythonAnywhere, read by CCR)
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
