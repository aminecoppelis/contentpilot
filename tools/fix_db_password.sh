#!/usr/bin/env bash
#
# Resynchronise le mot de passe PostgreSQL entre .env et le rôle de la base.
#
# Symptôme corrigé :
#   password authentication failed for user "post_generator"
#
# Cause habituelle : install.sh relancé régénère un mot de passe aléatoire
# et l'écrit dans .env, mais une restauration ultérieure d'un ancien .env
# (par exemple via update.sh) remet l'ancienne valeur, désormais obsolète.
#
# Ce script relit le mot de passe présent dans .env et l'applique au rôle,
# plutôt que d'en générer un nouveau : la configuration reste inchangée.
#
#   sudo bash tools/fix_db_password.sh
#
set -Eeuo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; YELLOW=$'\033[0;33m'; NC=$'\033[0m'
ok(){ echo "${GREEN}  ✓${NC} $*"; }; warn(){ echo "${YELLOW}  !${NC} $*"; }
die(){ echo "${RED}  ✗ $*${NC}" >&2; exit 1; }

[[ -f .env ]] || die ".env introuvable."
DB_URL="$(grep -E '^DATABASE_URL=' .env | head -1 | cut -d= -f2- | tr -d '"')"
[[ -n "$DB_URL" ]] || die "DATABASE_URL absent de .env"

# postgresql://user:password@host:port/dbname
DB_USER="$(sed -E 's#^[^:]+://([^:]+):.*#\1#'      <<<"$DB_URL")"
DB_PASS="$(sed -E 's#^[^:]+://[^:]+:([^@]+)@.*#\1#' <<<"$DB_URL")"
DB_HOST="$(sed -E 's#.*@([^:/]+).*#\1#'             <<<"$DB_URL")"
DB_PORT="$(sed -E 's#.*@[^:]+:([0-9]+)/.*#\1#'      <<<"$DB_URL")"
DB_NAME="$(sed -E 's#.*/([^/?]+)(\?.*)?$#\1#'       <<<"$DB_URL")"

echo "Configuration lue dans .env :"
echo "  rôle : $DB_USER"
echo "  base : $DB_NAME sur $DB_HOST:$DB_PORT"
echo

if [[ $EUID -eq 0 ]] && command -v runuser >/dev/null 2>&1; then
  AS_PG=(runuser -u postgres --)
elif command -v sudo >/dev/null 2>&1; then
  AS_PG=(sudo -u postgres)
else
  die "Droits insuffisants : relance avec sudo."
fi

( cd /tmp && "${AS_PG[@]}" psql -v ON_ERROR_STOP=1 -tAc \
    "ALTER ROLE \"$DB_USER\" WITH LOGIN PASSWORD '$DB_PASS'" postgres >/dev/null ) \
  || die "Impossible de modifier le rôle $DB_USER."
ok "Mot de passe du rôle aligné sur celui de .env"

export PGPASSWORD="$DB_PASS"
if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -tAc "SELECT 1" >/dev/null 2>&1; then
  ok "Connexion vérifiée avec les identifiants de .env"
else
  die "La connexion échoue encore — vérifie DATABASE_URL et pg_hba.conf."
fi
unset PGPASSWORD

if systemctl is-active --quiet post-generator 2>/dev/null; then
  systemctl restart post-generator
  ok "Service redémarré"
fi
echo
echo "  Contrôle : journalctl -u post-generator -n 20 --no-pager | grep -i worker"
