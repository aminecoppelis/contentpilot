#!/usr/bin/env bash
#
# Mise à jour de Post Generator depuis une archive.
#
# Préserve .env et venv/, applique les nouvelles dépendances, corrige les
# droits et redémarre le service. Les migrations manquantes sont appliquées
# automatiquement par l'application au démarrage.
#
# Usage :
#   sudo ./update.sh /chemin/vers/post_generator_python_port.zip
#
set -Eeuo pipefail

ARCHIVE="${1:-}"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_USER="${SUDO_USER:-$(id -un)}"

GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; RED=$'\033[0;31m'; BOLD=$'\033[1m'; NC=$'\033[0m'
ok(){ echo "${GREEN}  ✓${NC} $*"; }; warn(){ echo "${YELLOW}  !${NC} $*"; }
die(){ echo "${RED}  ✗ $*${NC}" >&2; exit 1; }

[[ -n "$ARCHIVE" ]] || die "Usage : sudo ./update.sh /chemin/vers/archive.zip"
[[ -f "$ARCHIVE" ]] || die "Archive introuvable : $ARCHIVE"
command -v unzip >/dev/null || die "unzip absent : sudo apt-get install -y unzip"

echo "${BOLD}Mise à jour de Post Generator${NC}"
echo "  Projet  : $APP_DIR"
echo "  Archive : $ARCHIVE"
echo

# 1. Sauvegardes
BACKUP="/tmp/pg-backup-$(date +%Y%m%d%H%M%S)"
mkdir -p "$BACKUP"
[[ -f "$APP_DIR/.env" ]] && cp "$APP_DIR/.env" "$BACKUP/.env" && ok "Sauvegarde de .env dans $BACKUP"
[[ -f "$APP_DIR/.env" ]] || warn ".env absent — il sera à recréer"

# 2. Arrêt du service
if systemctl is-active --quiet post-generator 2>/dev/null; then
  systemctl stop post-generator
  ok "Service arrêté"
fi

# 3. Extraction
TMP="$(mktemp -d)"
unzip -q -o "$ARCHIVE" -d "$TMP"
SRC="$TMP/post_generator"
[[ -d "$SRC" ]] || SRC="$TMP"
[[ -f "$SRC/app/main.py" ]] || die "Archive invalide : app/main.py introuvable"

# Le venv et le .env ne doivent jamais être écrasés
rsync -a --exclude='venv/' --exclude='.env' --exclude='tmp/' "$SRC/" "$APP_DIR/" \
  || cp -r "$SRC/." "$APP_DIR/"
ok "Fichiers du projet mis à jour"

# 4. Restauration de la configuration
[[ -f "$BACKUP/.env" ]] && cp "$BACKUP/.env" "$APP_DIR/.env" && ok ".env restauré"

# 5. Droits
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"
chmod 600 "$APP_DIR/.env" 2>/dev/null || true
chmod +x "$APP_DIR"/*.sh "$APP_DIR"/deploy/*.sh "$APP_DIR"/tools/*.py 2>/dev/null || true
ok "Droits attribués à $APP_USER"

# 6. Dépendances
if [[ -x "$APP_DIR/venv/bin/pip" ]]; then
  sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt" \
    && ok "Dépendances à jour"
else
  warn "venv absent — lance ./install.sh"
fi

# 7. Redémarrage
if [[ -f /etc/systemd/system/post-generator.service ]]; then
  systemctl daemon-reload
  systemctl start post-generator
  sleep 4
  if systemctl is-active --quiet post-generator; then
    ok "Service redémarré"
  else
    echo; journalctl -u post-generator -n 30 --no-pager
    die "Le service n'a pas redémarré."
  fi
else
  warn "Service systemd absent — lance ./deploy/setup.sh"
fi

# 8. Contrôles
echo
echo "${BOLD}Contrôles${NC}"
sleep 1
curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1 \
  && ok "L'application répond" || warn "Pas de réponse sur /health"

grep -q "_tls_mode" "$APP_DIR/app/services/mailer.py" \
  && ok "Correctif SMTP (ports 465/587) présent" || warn "Correctif SMTP absent"

[[ -f "$APP_DIR/app/migrations.py" ]] \
  && ok "Migrations automatiques au démarrage" || warn "app/migrations.py absent"

if journalctl -u post-generator -n 60 --no-pager 2>/dev/null | grep -q "Migration appliquée"; then
  ok "Migrations appliquées : $(journalctl -u post-generator -n 60 --no-pager | grep -o 'Migration appliquée : .*' | tail -1)"
fi

echo
echo "  Sauvegarde : $BACKUP"
echo "  Logs       : journalctl -u post-generator -f"
rm -rf "$TMP"
