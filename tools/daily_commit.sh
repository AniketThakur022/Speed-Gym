#!/bin/bash
# Daily checkpoint: commit all changes in the Speed Gym repo and push to origin.
# Installed as LaunchAgent com.speedgym.daily-commit (daily 03:00, runs on wake if missed).
set -u
REPO="/Users/harshahirrao/Speed gym"
LOG="$HOME/Library/Logs/speedgym-daily-commit.log"
cd "$REPO" || exit 1
exec >> "$LOG" 2>&1
echo "=== $(date '+%Y-%m-%d %H:%M:%S') daily checkpoint ==="

# Don't fight a live git operation from a working session
if [ -f .git/index.lock ]; then
  echo "index.lock present — another git operation in progress; skipping this run"
  exit 0
fi

git add -A
if git diff --cached --quiet; then
  echo "nothing to commit"
else
  git -c user.name="Speed Gym" -c user.email="thakuraniketsingh022@gmail.com" \
    commit -m "auto: daily checkpoint $(date '+%Y-%m-%d %H:%M')

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" && echo "committed"
fi

if GIT_TERMINAL_PROMPT=0 git push origin main; then
  echo "pushed"
else
  echo "PUSH FAILED — GitHub auth missing? Run: brew install gh && gh auth login"
fi
