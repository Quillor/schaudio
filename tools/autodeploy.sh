#!/bin/bash
# Publish watcher: whenever a new chapter manifest appears, sync app/books to
# R2 (incremental). Covers workers of any code age; replaces the old Vercel
# per-chapter deploys entirely.
cd /Users/timrosenberg/claude/schaudio
log() { .venv-tts/bin/python -c "import sys; sys.path.insert(0,'tools'); import claim; claim.log('claude-autodeploy', '$1')"; }
last=$(find app/books -name 'sam-ch*.json' | wc -l)
while :; do
  sleep 120
  now=$(find app/books -name 'sam-ch*.json' | wc -l)
  if [ "$now" -gt "$last" ]; then
    if .venv-tts/bin/python tools/publish_r2.py books >/dev/null 2>&1; then
      log "R2 publish OK (manifests $last -> $now)"
      last=$now
    else
      log "R2 publish FAILED, retrying next tick"
    fi
  fi
done
