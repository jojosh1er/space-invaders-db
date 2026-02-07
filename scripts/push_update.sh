#!/bin/bash
# 🚀 push_update.sh - Commit & push les changements
#
# Usage:
#   bash scripts/push_update.sh                    # Commit avec message auto
#   bash scripts/push_update.sh "mon message"      # Commit avec message custom

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

cd "$REPO_DIR"

# Vérifier s'il y a des changements
if git diff --quiet data/ 2>/dev/null; then
    echo "✅ Aucun changement détecté dans data/"
    exit 0
fi

# Message de commit
if [ -n "$1" ]; then
    MSG="$1"
else
    # Générer un message automatique
    DATE=$(date +"%Y-%m-%d %H:%M")
    
    # Compter les changements
    ADDED=$(git diff --numstat data/invaders_master.json 2>/dev/null | awk '{print $1}' || echo "?")
    REMOVED=$(git diff --numstat data/invaders_master.json 2>/dev/null | awk '{print $2}' || echo "?")
    
    # Lire les stats depuis metadata
    if command -v python3 &> /dev/null; then
        TOTAL=$(python3 -c "import json; d=json.load(open('data/metadata.json')); print(d.get('total_invaders','?'))" 2>/dev/null || echo "?")
        MSG="🔄 Update ${DATE} - ${TOTAL} invaders (+${ADDED}/-${REMOVED} lignes)"
    else
        MSG="🔄 Update ${DATE} (+${ADDED}/-${REMOVED} lignes)"
    fi
fi

echo "📝 Commit: $MSG"
echo ""

# Ajouter et commit
git add data/
git status --short data/

echo ""
git commit -m "$MSG"

# Push
echo ""
echo "🚀 Push..."
git push

echo ""
echo "✅ Terminé !"
