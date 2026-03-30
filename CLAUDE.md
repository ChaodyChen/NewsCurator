# NewsCurator — Claude Code Instructions

## Architecture Overview

```
Anthropic Cloud (CCR) — Automated
├── Trigger ID: trig_01Qf7UAouay2enJ4okAXEiqJ
├── Schedule: Daily 7:45 AM Taipei time (UTC+8)
├── Monday → git pull → deliver_news (send top 5 via LINE) → git push
└── Tue–Sun → fetch_candidates (NewsAPI → data/) → git push

PythonAnywhere — Manual Curation UI
├── URL: https://chaody.pythonanywhere.com/curate
├── Serves Flask curation form (Fri–Sun)
├── git pull → reads candidates CSV from data/
└── Saves selections CSV to data/ → git push (manual)

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
