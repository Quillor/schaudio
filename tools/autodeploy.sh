#!/bin/bash
# Publish every finished chapter within minutes, regardless of which worker
# finished it. Deploys are already chapter-triggered inside overnight.py; this
# is the safety net for chapters completed by workers that do not deploy
# (agent2's legacy processes). A deploy ships the whole books tree, so one
# deploy publishes everything finished up to that moment.
cd /Users/timrosenberg/claude/schaudio
last=$(find app/books -name 'sam-ch*.json' | wc -l)
while :; do
  sleep 180
  now=$(find app/books -name 'sam-ch*.json' | wc -l)
  if [ "$now" -gt "$last" ]; then
    if npx --no-install vercel deploy --prod --yes >/dev/null 2>&1; then
      .venv-tts/bin/python -c "import sys; sys.path.insert(0,'tools'); import claim; claim.log('claude-autodeploy','deploy OK (manifests $last -> $now)')"
      last=$now
    else
      .venv-tts/bin/python -c "import sys; sys.path.insert(0,'tools'); import claim; claim.log('claude-autodeploy','deploy FAILED, will retry next tick')"
    fi
  fi
done
