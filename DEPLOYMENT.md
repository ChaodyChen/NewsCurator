# NewsCurator Deployment Guide

## Remote Deployment on Anthropic Cloud (CCR)

### Prerequisites
- GitHub repository: https://github.com/ChaodyChen/NewsCurator
- Claude Code scheduled trigger ID: `trig_01Qf7UAouay2enJ4okAXEiqJ`
- Google Drive service account credentials

### Environment Variables Required

The remote agent needs these variables set in the CCR environment:

```bash
# NewsAPI
NEWSAPI_KEY=***REDACTED_NEWSAPI_KEY_2***

# Google Drive
GOOGLE_APPLICATION_CREDENTIALS=***REDACTED_GCP_PROJECT***.json
GOOGLE_DRIVE_FOLDER_ID=***REDACTED_GDRIVE_FOLDER_ID***

# LINE Messaging
LINE_CHANNEL_ACCESS_TOKEN=***REDACTED_LINE_TOKEN***
LINE_CHANNEL_SECRET=***REDACTED_LINE_SECRET***
LINE_GROUP_ID=***REDACTED_LINE_GROUP_ID***

# Email Fallback
SMTP_USER=Chaody@gmail.com
SMTP_PASSWORD=***REDACTED_GMAIL_APP_PASSWORD***
FALLBACK_RECIPIENT_EMAIL=Chaody@gmail.com
```

### How to Configure

**Option A: Via Anthropic Cloud Settings (Recommended)**

1. Go to https://claude.ai/code/scheduled (or Settings → Scheduled Agents)
2. Find trigger: "NewsCurator - Daily Operations (6am Taipei)"
3. Edit trigger and locate environment/secrets configuration section
4. Paste the environment variables above
5. Save changes

**Option B: Manual Export to CCR**

If UI doesn't show environment settings, Anthropic may need to:
1. Mount a `.env.production` file in the CCR session
2. Or set environment variables via system configuration

Contact Anthropic support with trigger ID: `trig_01Qf7UAouay2enJ4okAXEiqJ`

### Daily Schedule

**Every day at 7:45 AM Taipei time (UTC+8)**

| Day | Operation | Details |
|-----|-----------|---------|
| Monday | **Delivery** | Load selections → verify links → send top 5 via LINE |
| Tue-Sat | **Fetch** | NewsAPI → URL verify → save candidates to Drive |
| Sunday | **Fetch** | Prep candidates for Monday curation |

### Local Testing (Before Deployment)

```bash
# Setup
cp .env.example .env.local
# Edit .env.local with your credentials

# Test fetch pipeline
python -c "from src.fetch_candidates import fetch_and_save; fetch_and_save()"

# Test delivery pipeline
python -c "from src.delivery import deliver_news; deliver_news()"

# Run full test suite
pytest tests/ -v
```

### Git Workflow

The CCR agent automatically:
1. Clones https://github.com/ChaodyChen/NewsCurator
2. Installs dependencies from `requirements.txt`
3. Executes fetch/delivery based on day of week
4. Commits results to `master` branch
5. Pushes changes to origin

**Important**: Ensure your GitHub token has push access.

### Monitoring

Check trigger execution:
- View logs in Claude Code UI (Scheduled tab)
- Monitor Google Drive folder for new `candidates-*.csv` files
- Verify LINE group receives weekly message on Monday 7:45am

### Troubleshooting

**"Missing required config" error**
- One or more environment variables not set in CCR
- Check DEPLOYMENT.md above for complete list
- Verify each variable in CCR settings

**"FileNotFoundError: Google credentials"**
- `***REDACTED_GCP_PROJECT***.json` not in CCR working directory
- Contact Anthropic to mount file in CCR session

**"LINE delivery failed" but email works**
- LINE API may be rate limited or token expired
- Email fallback should deliver content
- Check LINE channel access token validity

**Google Drive upload fails**
- Service account may not have permission to folder
- Verify `GOOGLE_DRIVE_FOLDER_ID` is shared with service account
- Check Drive API is enabled in Google Cloud project

### Credentials Rotation

To update any credentials:
1. Generate new credentials in their respective services
2. Update values in CCR environment settings (not in GitHub)
3. Test with manual trigger run
4. If successful, system automatically uses new credentials next execution

### Support

For CCR-specific issues (environment variables, file mounting):
- Contact Anthropic with trigger ID: `trig_01Qf7UAouay2enJ4okAXEiqJ`
- Provide error logs from Claude Code UI

For application issues:
- Check GitHub issues: https://github.com/ChaodyChen/NewsCurator/issues
- Review logs in `tests.log` for detailed error trace
