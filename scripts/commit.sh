#!/usr/bin/env bash
# Commit data/ and public/ and push. Jobs share one concurrency group, so they
# never run at the same time; the rebase only covers a manual push in between.
set -euo pipefail
message="${1:-Update}"

git config user.name "transit-pulse-bot"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add data public

if git diff --cached --quiet; then
  echo "Nothing to commit."
  exit 0
fi

git commit -q -m "$message"
for attempt in 1 2 3; do
  if git push -q; then
    echo "Pushed on attempt $attempt."
    exit 0
  fi
  # During a rebase "theirs" is this job's commit: keep its generated files.
  git pull -q --rebase -X theirs
done
echo "Push failed after 3 attempts." >&2
exit 1
