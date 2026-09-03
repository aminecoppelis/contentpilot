#!/usr/bin/env bash
#
# Lance le capteur d'emails local (développement).
# Les messages ne sont pas envoyés : ils sont enregistrés dans tmp/mails/
# avec le lien d'activation ou d'invitation extrait automatiquement.
#
# Usage :
#   ./mail.sh                 # 127.0.0.1:1025
#   ./mail.sh --port 2525
#
set -Eeuo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

PY="${PYTHON_BIN:-python3}"
[[ -x "$APP_DIR/venv/bin/python" ]] && PY="$APP_DIR/venv/bin/python"

MAIL_DIR="${MAIL_DIR:-$APP_DIR/tmp/mails}"
mkdir -p "$MAIL_DIR"

echo "Rappel : dans .env -> SMTP_HOST=127.0.0.1 et SMTP_PORT=1025"
echo "Les emails capturés sont consultables dans : $MAIL_DIR"
echo
exec "$PY" tools/mailcatcher.py --dir "$MAIL_DIR" "$@"
