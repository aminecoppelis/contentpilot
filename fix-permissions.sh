#!/usr/bin/env bash
# Répare les droits et les fins de ligne de tous les scripts du projet.
# À lancer si un script répond « commande introuvable » ou « Permission denied ».
#   bash fix-permissions.sh
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "Normalisation des fins de ligne (CRLF -> LF)…"
find . -maxdepth 3 \( -name '*.sh' -o -name '*.py' -o -name '*.sql' \) \
  -not -path './venv/*' -exec sed -i 's/\r$//' {} + 2>/dev/null || true

echo "Attribution du bit exécutable…"
chmod +x ./*.sh ./deploy/*.sh ./tools/*.py 2>/dev/null || true

USER_NAME="${SUDO_USER:-$(id -un)}"
if [[ $EUID -eq 0 && "$USER_NAME" != root ]]; then
  chown -R "$USER_NAME":"$USER_NAME" "$DIR"
  echo "Propriété attribuée à $USER_NAME"
fi
[[ -f .env ]] && chmod 600 .env

echo
echo "Scripts disponibles :"
for f in install.sh start.sh update.sh mail.sh deploy/setup.sh; do
  [[ -f "$f" ]] && printf "  %-22s %s\n" "$f" "$([[ -x "$f" ]] && echo exécutable || echo 'NON exécutable')"
done
echo
echo "Terminé."
