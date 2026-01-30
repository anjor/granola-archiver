# Quick Start Guide

Get the Granola archiver up and running in 5 minutes.

## Prerequisites

- Python 3.13+
- Granola API credentials (in `~/.granola/credentials.json`)
- Git and GitHub account

## Step 1: Install

```bash
cd /Users/anjor/repos/anjor/granola-archiver

# Install dependencies
pip install -e .

# Install granola-py-client
pip install -e /Users/anjor/repos/anjor/granola-py-client
```

## Step 2: Create Archive Repository

```bash
# Create a new GitHub repo for archives
gh repo create granola-transcripts --private

# Clone it locally
git clone https://github.com/yourusername/granola-transcripts.git ~/granola-transcripts

# Initialize
cd ~/granola-transcripts
echo "# Granola Meeting Transcripts" > README.md
git add README.md
git commit -m "Initial commit"
git push origin main
```

## Step 3: Configure

```bash
cd /Users/anjor/repos/anjor/granola-archiver

# Edit config.yaml and update the repo_path
nano config.yaml
```

Change this line:
```yaml
archive:
  repo_path: /Users/yourusername/granola-transcripts  # Update this!
```

## Step 4: Test Run

```bash
# Dry run to see what would be archived
python -m archiver --dry-run

# Archive documents for real
python -m archiver
```

You should see output like:

```
┏━━━━━━━━━━━━━━━━━━┳━━━━━━━┓
┃ Metric           ┃ Count ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━━┩
│ Total Documents  │ 5     │
│ Archived         │ 5     │
│ Failed           │ 0     │
│ Skipped          │ 0     │
└──────────────────┴───────┘
```

Check your archive repo:

```bash
cd ~/granola-transcripts
ls -R
```

You should see files organized like:
```
2026/01/2026-01-30-meeting-title.md
```

## Step 5: Set Up Automation (Optional)

```bash
cd /Users/anjor/repos/anjor/granola-archiver
./scripts/setup_launchd.sh
```

The archiver will now run automatically every 30 minutes.

## Verify It's Working

```bash
# Check launchd job is loaded
launchctl list | grep granola

# View logs
tail -f /tmp/granola-archiver.log
```

## Troubleshooting

### "granola-client not found"
```bash
pip install -e /Users/anjor/repos/anjor/granola-py-client
```

### "Repository path does not exist"
Update `config.yaml` with the correct path to your archive repository.

### "Authentication failed"
Ensure `~/.granola/credentials.json` exists with valid credentials.

### View detailed logs
```bash
tail -f /tmp/granola-archiver.log
```

## Next Steps

- Customize `config.yaml` to filter specific workspaces
- Set minimum meeting duration to skip short meetings
- Adjust logging level and location
- Browse the archived transcripts in your archive repo

For more details, see [README.md](README.md).
