#!/usr/bin/env bash
# Lance un cycle cible sur theswarm, en local, comme le fait le bouton Play.
# Usage: run-targeted.sh <numero_issue>
# Voir scripts/local_cycle/README.md. Journaux et espace de travail vont dans
# tmp/local-cycle/ (ignore par git).
set -euo pipefail

ISSUE="${1:?usage: run-targeted.sh <numero_issue>}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

set -a
# shellcheck disable=SC1091
ENV_FILE="${SWARM_ENV_FILE:-$ROOT/.env}"
[ -f "$ENV_FILE" ] && source "$ENV_FILE"
set +a

# No PATH workaround on purpose. This Mac has 3.11.6 ahead of 3.12.0 and
# theswarm declares >=3.12; fix A makes `find_system_python` skip the 3.11
# on its own. Leaving PATH alone is what exercises it for real.

export SWARM_GITHUB_REPO="jrechet/theswarm"
export SWARM_TEAM_ID="local"
export SWARM_WORKSPACE_DIR="$ROOT/tmp/local-cycle/workspace"
mkdir -p "$SWARM_WORKSPACE_DIR"

if ! claude -p 'ok' --model sonnet >/dev/null 2>&1; then
  echo "CLI Claude indisponible — le cycle echouerait au premier appel." >&2
  exit 1
fi

LOG="$ROOT/tmp/local-cycle/targeted-${ISSUE}-$(date -u +%Y%m%dT%H%M%SZ).log"
echo "Issue cible  : #$ISSUE"
echo "Depot        : $SWARM_GITHUB_REPO (SELF_REPO — le TechLead approuve sans merger)"
echo "Journal      : $LOG"
echo

PYTHONPATH="$ROOT/src" .venv/bin/python scripts/local_cycle/targeted_cycle.py "$ISSUE" 2>&1 | tee "$LOG"
