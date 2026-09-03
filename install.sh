#!/usr/bin/env bash
#
# Post Generator — Installation complète
#
# Installe Python + venv + dépendances, PostgreSQL (avec pgcrypto), crée la
# base et l'utilisateur, applique la migration, prépare les répertoires de
# médias et de logs, génère un .env et crée le compte administrateur initial.
#
# Usage :
#   sudo ./install.sh                 # installation complète (recommandé)
#   ./install.sh --no-system          # saute apt (Python/PostgreSQL déjà présents)
#   ./install.sh --db-only            # ne fait que base + migration
#   ./install.sh --reset-db           # SUPPRIME la base puis réinstalle (destructif)
#
set -Eeuo pipefail

# ---------------------------------------------------------------------------
# Configuration (surchargeable par variables d'environnement)
# ---------------------------------------------------------------------------
APP_NAME="post_generator"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${VENV_DIR:-$APP_DIR/venv}"

DB_NAME="${DB_NAME:-post_generator}"
DB_USER="${DB_USER:-post_generator}"
DB_PASSWORD="${DB_PASSWORD:-}"          # généré si vide
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"

MEDIA_DIR="${MEDIA_DIR:-/var/lib/post_generator/media}"
LOG_DIR="${LOG_DIR:-/var/log/post_generator}"

ADMIN_EMAIL="${ADMIN_EMAIL:-admin@example.com}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"    # généré si vide

SKIP_SYSTEM=0
DB_ONLY=0
RESET_DB=0
PYTHON_BIN="${PYTHON_BIN:-python3}"   # réévalué à l'étape 2 si disponible

# ---------------------------------------------------------------------------
# Utilitaires d'affichage
# ---------------------------------------------------------------------------
RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'
BLUE=$'\033[0;34m'; BOLD=$'\033[1m'; NC=$'\033[0m'

info()  { echo "${BLUE}==>${NC} $*"; }
ok()    { echo "${GREEN}  ✓${NC} $*"; }
warn()  { echo "${YELLOW}  !${NC} $*"; }
die()   { echo "${RED}  ✗ $*${NC}" >&2; exit 1; }
step()  { echo; echo "${BOLD}$*${NC}"; }

trap 'die "Échec à la ligne $LINENO. Installation interrompue."' ERR

for arg in "$@"; do
  case "$arg" in
    --no-system) SKIP_SYSTEM=1 ;;
    --db-only)   DB_ONLY=1; SKIP_SYSTEM=1 ;;
    --reset-db)  RESET_DB=1 ;;
    -h|--help)
      sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) die "Option inconnue : $arg" ;;
  esac
done

cd "$APP_DIR"

echo "${BOLD}"
echo "  Post Generator — installation"
echo "  répertoire : $APP_DIR"
echo "${NC}"

# ---------------------------------------------------------------------------
# 0. Détection de l'OS et des privilèges
# ---------------------------------------------------------------------------
step "0. Vérification de l'environnement"

if [[ -f /etc/os-release ]]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  OS_ID="${ID:-inconnu}"
else
  OS_ID="inconnu"
fi
ok "Système détecté : $OS_ID"

if [[ $EUID -eq 0 ]]; then
  SUDO=""
  RUN_USER="${SUDO_USER:-root}"
else
  if command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
  else
    SUDO=""
    [[ $SKIP_SYSTEM -eq 0 ]] && die "Ni root ni sudo : relance avec --no-system ou en root."
  fi
  RUN_USER="$(id -un)"
fi
ok "Utilisateur applicatif : $RUN_USER"

# Préfixe de commande pour agir en tant qu'utilisateur postgres.
# En root, `$SUDO` est vide : `$SUDO -u postgres` produirait la commande `-u`,
# d'où l'utilisation d'un tableau construit explicitement.
if [[ $EUID -eq 0 ]]; then
  if command -v runuser >/dev/null 2>&1; then
    AS_POSTGRES=(runuser -u postgres --)
  else
    AS_POSTGRES=(su postgres -c)     # variante à chaîne unique, gérée plus bas
    AS_POSTGRES_STRING=1
  fi
elif command -v sudo >/dev/null 2>&1; then
  AS_POSTGRES=(sudo -u postgres)
else
  AS_POSTGRES=()                     # déjà l'utilisateur postgres, ou accès direct
fi

# Exécute une commande psql en tant que postgres, quelle que soit la méthode
run_as_postgres() {
  # On se place dans /tmp : l'utilisateur postgres n'a pas le droit de lire
  # le répertoire du projet, ce qui provoquerait un avertissement
  # « could not change directory » à chaque appel.
  if [[ "${AS_POSTGRES_STRING:-0}" == "1" ]]; then
    local joined
    printf -v joined '%q ' "$@"
    ( cd /tmp && su postgres -c "$joined" )
  elif [[ ${#AS_POSTGRES[@]} -gt 0 ]]; then
    ( cd /tmp && "${AS_POSTGRES[@]}" "$@" )
  else
    ( cd /tmp && "$@" )
  fi
}

gen_secret() {
  if command -v openssl >/dev/null 2>&1; then openssl rand -hex 24
  else head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n'; fi
}

# ---------------------------------------------------------------------------
# 1. Paquets système
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Attente du verrou dpkg/apt
#
# Ubuntu lance `unattended-upgrades` au démarrage : ce processus détient le
# verrou dpkg et fait échouer tout apt-get lancé en parallèle. On attend
# qu'il se libère plutôt que d'échouer (comportement par défaut : 300 s).
# ---------------------------------------------------------------------------
APT_LOCK_TIMEOUT="${APT_LOCK_TIMEOUT:-300}"

apt_locked() {
  # fuser renvoie 0 si au moins un verrou est tenu
  $SUDO fuser /var/lib/dpkg/lock-frontend \
              /var/lib/dpkg/lock \
              /var/lib/apt/lists/lock \
              /var/cache/apt/archives/lock >/dev/null 2>&1
}

wait_for_apt() {
  apt_locked || return 0

  local holder waited=0
  holder="$(pgrep -a 'unattended-upgr|apt-get|aptitude|dpkg|apt$' 2>/dev/null | head -1 || true)"
  warn "Le gestionnaire de paquets est occupé :"
  [[ -n "$holder" ]] && warn "  $holder"
  info "Attente de la libération du verrou (max ${APT_LOCK_TIMEOUT}s)…"

  while apt_locked; do
    if (( waited >= APT_LOCK_TIMEOUT )); then
      echo
      die "Verrou dpkg toujours tenu après ${APT_LOCK_TIMEOUT}s.
     Attends la fin des mises à jour automatiques puis relance :
       while pgrep -x unattended-upgr >/dev/null; do sleep 5; done && sudo ./install.sh
     Ou augmente le délai :
       APT_LOCK_TIMEOUT=900 sudo -E ./install.sh
     Ou saute cette étape si Python et PostgreSQL sont déjà installés :
       sudo ./install.sh --no-system"
    fi
    printf '\r  ${YELLOW}!${NC} en attente… %ds/%ds' "$waited" "$APT_LOCK_TIMEOUT"
    sleep 5
    waited=$((waited + 5))
  done
  printf '\r%*s\r' 60 ''   # efface la ligne de progression
  ok "Verrou libéré après ${waited}s"
}

if [[ $SKIP_SYSTEM -eq 0 ]]; then
  step "1. Installation des paquets système"
  case "$OS_ID" in
    ubuntu|debian|linuxmint|pop)
      export DEBIAN_FRONTEND=noninteractive
      command -v fuser >/dev/null 2>&1 || $SUDO apt-get install -y -qq psmisc 2>/dev/null || true

      wait_for_apt
      info "Mise à jour de la liste des paquets…"
      # -o DPkg::Lock::Timeout : apt attend lui-même si le verrou réapparaît
      $SUDO apt-get update -qq -o DPkg::Lock::Timeout=120 || {
        warn "apt-get update a échoué — nouvelle tentative dans 15s…"
        sleep 15; wait_for_apt
        $SUDO apt-get update -qq -o DPkg::Lock::Timeout=120
      }

      wait_for_apt
      info "Installation de Python, PostgreSQL et des outils de build…"
      $SUDO apt-get install -y -qq -o DPkg::Lock::Timeout=120 \
        python3 python3-venv python3-dev python3-pip \
        postgresql postgresql-contrib libpq-dev \
        build-essential curl ca-certificates openssl || {
        warn "Installation interrompue — nouvelle tentative dans 15s…"
        sleep 15; wait_for_apt
        $SUDO apt-get install -y -qq -o DPkg::Lock::Timeout=120 \
          python3 python3-venv python3-dev python3-pip \
          postgresql postgresql-contrib libpq-dev \
          build-essential curl ca-certificates openssl
      }
      ok "Paquets installés"
      ;;
    fedora|rhel|centos|rocky|almalinux)
      info "Installation via dnf…"
      $SUDO dnf install -y -q python3 python3-devel python3-pip \
        postgresql-server postgresql-contrib libpq-devel gcc openssl curl
      if [[ ! -d /var/lib/pgsql/data/base ]]; then
        $SUDO postgresql-setup --initdb || true
      fi
      ok "Paquets installés"
      ;;
    arch|manjaro)
      $SUDO pacman -Sy --noconfirm python python-pip postgresql base-devel openssl curl
      ok "Paquets installés"
      ;;
    *)
      warn "Distribution non reconnue ($OS_ID) — installe manuellement :"
      warn "  python3 (>=3.11), python3-venv, postgresql (>=14), libpq-dev"
      warn "Puis relance avec --no-system"
      ;;
  esac

  info "Démarrage du service PostgreSQL…"
  if command -v systemctl >/dev/null 2>&1; then
    $SUDO systemctl enable postgresql >/dev/null 2>&1 || true
    $SUDO systemctl start postgresql  >/dev/null 2>&1 || warn "systemctl start a échoué"
  elif command -v service >/dev/null 2>&1; then
    $SUDO service postgresql start >/dev/null 2>&1 || warn "service start a échoué"
  fi
  ok "PostgreSQL actif"
else
  step "1. Paquets système — ignoré (--no-system)"
fi

# ---------------------------------------------------------------------------
# 2. Vérification de la version de Python
# ---------------------------------------------------------------------------
if [[ $DB_ONLY -eq 0 ]]; then
  step "2. Vérification de Python"
  command -v python3 >/dev/null 2>&1 || die "python3 introuvable."

  # Minimum réel du code : 3.10 (unions X | Y, pas de TaskGroup ni except*).
  # Ubuntu 22.04 fournit 3.10, Ubuntu 24.04 fournit 3.12 — les deux conviennent.
  PYTHON_BIN="${PYTHON_BIN:-python3}"

  # Si une version plus récente est déjà installée, on la préfère.
  for candidate in python3.13 python3.12 python3.11; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PYTHON_BIN="$candidate"
      break
    fi
  done

  PY_VER="$("$PYTHON_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
  PY_OK="$("$PYTHON_BIN" -c 'import sys; print(1 if sys.version_info >= (3,10) else 0)')"

  if [[ "$PY_OK" != "1" ]]; then
    die "Python 3.10+ requis (détecté : $PY_VER avec $PYTHON_BIN).
     Sur Ubuntu ancien, installe une version récente :
       sudo add-apt-repository -y ppa:deadsnakes/ppa
       sudo apt-get update && sudo apt-get install -y python3.12 python3.12-venv
       PYTHON_BIN=python3.12 sudo -E ./install.sh"
  fi

  # Le module venv doit être présent (paquet séparé sur Debian/Ubuntu)
  if ! "$PYTHON_BIN" -c 'import venv' 2>/dev/null; then
    warn "Module venv absent pour $PYTHON_BIN — installation…"
    $SUDO apt-get install -y -qq -o DPkg::Lock::Timeout=120 "${PYTHON_BIN}-venv" 2>/dev/null \
      || die "Impossible d'installer ${PYTHON_BIN}-venv. Installe-le manuellement."
  fi

  ok "Python $PY_VER ($PYTHON_BIN)"
fi

# ---------------------------------------------------------------------------
# 3. Environnement virtuel + dépendances
# ---------------------------------------------------------------------------
if [[ $DB_ONLY -eq 0 ]]; then
  step "3. Environnement virtuel et dépendances Python"
  if [[ ! -d "$VENV_DIR" ]]; then
    info "Création du venv dans $VENV_DIR (${PYTHON_BIN:-python3})…"
    "${PYTHON_BIN:-python3}" -m venv "$VENV_DIR"
    ok "venv créé"
  else
    ok "venv déjà présent"
  fi

  info "Mise à jour de pip…"
  "$VENV_DIR/bin/pip" install --quiet --upgrade pip setuptools wheel

  info "Installation des dépendances (requirements.txt)…"
  "$VENV_DIR/bin/pip" install --quiet -r requirements.txt
  ok "$( "$VENV_DIR/bin/pip" list --format=freeze | wc -l ) paquets installés"
fi

# ---------------------------------------------------------------------------
# 4. Répertoires et permissions
# ---------------------------------------------------------------------------
step "4. Répertoires et permissions"

create_dir() {
  local dir="$1" desc="$2"
  if [[ ! -d "$dir" ]]; then
    $SUDO mkdir -p "$dir" || die "Impossible de créer $dir"
  fi
  $SUDO chown -R "$RUN_USER":"$RUN_USER" "$dir" 2>/dev/null || \
    warn "chown impossible sur $dir (droits insuffisants)"
  $SUDO chmod 750 "$dir" 2>/dev/null || true
  ok "$desc : $dir"
}

create_dir "$MEDIA_DIR" "Médias générés"
create_dir "$LOG_DIR"   "Logs applicatifs"

# Répertoires locaux du projet
mkdir -p "$APP_DIR/tmp"
chmod 750 "$APP_DIR/tmp"
ok "Fichiers temporaires : $APP_DIR/tmp"

# ---------------------------------------------------------------------------
# 5. Base de données
# ---------------------------------------------------------------------------
step "5. Base de données PostgreSQL"

if [[ -z "$DB_PASSWORD" ]]; then
  DB_PASSWORD="$(gen_secret)"
  GENERATED_DB_PWD=1
else
  GENERATED_DB_PWD=0
fi

psql_admin() {
  run_as_postgres psql -v ON_ERROR_STOP=1 -tAc "$1" postgres
}

if [[ $RESET_DB -eq 1 ]]; then
  warn "--reset-db : suppression de la base $DB_NAME (données définitivement perdues)"
  read -r -p "  Confirmer en tapant le nom de la base ($DB_NAME) : " CONFIRM
  [[ "$CONFIRM" == "$DB_NAME" ]] || die "Confirmation incorrecte — rien n'a été supprimé."
  run_as_postgres psql -v ON_ERROR_STOP=1 -tAc \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$DB_NAME' AND pid <> pg_backend_pid()" postgres >/dev/null 2>&1 || true
  run_as_postgres psql -v ON_ERROR_STOP=1 -tAc "DROP DATABASE IF EXISTS $DB_NAME" postgres >/dev/null
  ok "Base supprimée"
fi

info "Création du rôle et de la base…"
if [[ "$(psql_admin "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" || true)" == "1" ]]; then
  psql_admin "ALTER ROLE $DB_USER WITH LOGIN PASSWORD '$DB_PASSWORD'" >/dev/null
  ok "Rôle $DB_USER existant — mot de passe mis à jour"
else
  psql_admin "CREATE ROLE $DB_USER WITH LOGIN PASSWORD '$DB_PASSWORD'" >/dev/null
  ok "Rôle $DB_USER créé"
fi

if [[ "$(psql_admin "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" || true)" == "1" ]]; then
  ok "Base $DB_NAME existante"
  DB_EXISTED=1
else
  psql_admin "CREATE DATABASE $DB_NAME OWNER $DB_USER" >/dev/null
  ok "Base $DB_NAME créée"
  DB_EXISTED=0
fi

info "Activation de l'extension pgcrypto (requise pour bcrypt et les jetons)…"
run_as_postgres psql -v ON_ERROR_STOP=1 -d "$DB_NAME" \
  -c "CREATE EXTENSION IF NOT EXISTS pgcrypto;" >/dev/null
# PostgreSQL 15+ : le schéma public n'est plus inscriptible par défaut
run_as_postgres psql -v ON_ERROR_STOP=1 -d "$DB_NAME" \
  -c "GRANT ALL ON SCHEMA public TO \"$DB_USER\";" >/dev/null
run_as_postgres psql -v ON_ERROR_STOP=1 -d "$DB_NAME" \
  -c "ALTER SCHEMA public OWNER TO \"$DB_USER\";" >/dev/null 2>&1 || true
ok "pgcrypto activée et droits accordés"

export PGPASSWORD="$DB_PASSWORD"
DB_URL="postgresql://$DB_USER:$DB_PASSWORD@$DB_HOST:$DB_PORT/$DB_NAME"

info "Analyse de l'état du schéma…"

# --- Inventaire des tables essentielles déjà présentes -----------------------
ESSENTIAL_TABLES=(app_users auth_sessions workspaces workspace_members
  post_requests post_ideas post_versions post_media post_publications
  app_social_accounts app_growth_strategies app_growth_strategy_action_calendar)

count_existing_tables() {
  psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -tAc \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'" 2>/dev/null || echo 0
}
missing_essential() {
  psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -tAc "
    SELECT string_agg(t, ' ') FROM unnest(ARRAY['$(printf "%s','" "${ESSENTIAL_TABLES[@]}" | sed "s/,'$//")']) AS t
    WHERE NOT EXISTS (SELECT 1 FROM information_schema.tables
                      WHERE table_schema='public' AND table_name = t)" 2>/dev/null || echo ""
}

EXISTING="$(count_existing_tables)"
MISSING="$(missing_essential)"
ok "$EXISTING table(s) présente(s) dans le schéma public"

# --- Normalisation de la migration ------------------------------------------
# Le script ne suppose PAS que le fichier de migration soit la version
# idempotente : il en fabrique une copie normalisée dans /tmp où les
# CREATE TABLE / CREATE INDEX sont forcés en IF NOT EXISTS. Une ancienne
# version du fichier fonctionne donc aussi bien qu'une récente.
MIGRATION_SRC="migrations/001_init.sql"
[[ -f "$MIGRATION_SRC" ]] || die "Fichier de migration introuvable : $MIGRATION_SRC"

MIGRATION_RUN="$(mktemp --suffix=.sql)"

# Le normaliseur rend le fichier applicable quelle que soit sa version :
#   - CREATE TABLE / INDEX en IF NOT EXISTS (relançable après échec)
#   - ALTER ADD CONSTRAINT protégés contre le doublon
#   - tables réordonnées par TRI TOPOLOGIQUE des clés étrangères
# Ce dernier point élimine définitivement les erreurs
# « relation "X" does not exist » liées à l'ordre des déclarations.
if [[ -f tools/normalize_migration.py ]]; then
  "${PYTHON_BIN:-python3}" tools/normalize_migration.py "$MIGRATION_SRC" "$MIGRATION_RUN" \
    | sed 's/^/  /' || die "Normalisation de la migration impossible."
else
  warn "tools/normalize_migration.py absent — migration appliquée telle quelle"
  cp "$MIGRATION_SRC" "$MIGRATION_RUN"
fi

# --- Application -------------------------------------------------------------
info "Application de la migration…"
MIGRATION_LOG="$(mktemp)"
if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
        -v ON_ERROR_STOP=1 --single-transaction -q \
        -f "$MIGRATION_RUN" >"$MIGRATION_LOG" 2>&1; then
  TABLE_COUNT="$(count_existing_tables)"
  INDEX_COUNT="$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -tAc \
    "SELECT count(*) FROM pg_indexes WHERE schemaname='public'")"
  ok "Schéma à jour — $TABLE_COUNT tables, $INDEX_COUNT index"
  rm -f "$MIGRATION_LOG" "$MIGRATION_RUN"
else
  echo
  echo "${RED}  Erreur PostgreSQL :${NC}"
  grep -E 'ERROR|ERREUR|FATAL' "$MIGRATION_LOG" | head -10 | sed 's/^/    /'
  echo
  warn "Transaction annulée : la base est restée dans son état d'avant."
  warn "Journal : $MIGRATION_LOG"
  warn "SQL réellement exécuté : $MIGRATION_RUN"
  echo
  warn "Pour repartir d'une base vierge :"
  warn "  sudo ./install.sh --reset-db"
  die "Migration impossible."
fi

# --- Migrations additives ----------------------------------------------------
# Les fichiers 002+ complètent le schéma initial. Idempotents et appliqués
# dans l'ordre lexicographique, chacun dans sa propre transaction.
for extra in $(ls migrations/[0-9][0-9][0-9]_*.sql 2>/dev/null | grep -v '001_init' | sort); do
  EXTRA_LOG="$(mktemp)"
  if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
          -v ON_ERROR_STOP=1 --single-transaction -q -f "$extra" >"$EXTRA_LOG" 2>&1; then
    ok "Migration additive appliquée : $(basename "$extra")"
    rm -f "$EXTRA_LOG"
  else
    echo
    grep -E 'ERROR|ERREUR|FATAL' "$EXTRA_LOG" | head -5 | sed 's/^/    /'
    die "Échec de $(basename "$extra") — journal : $EXTRA_LOG"
  fi
done

# --- Contrôle final ----------------------------------------------------------
MISSING="$(missing_essential)"
if [[ -n "${MISSING// /}" ]]; then
  die "Tables essentielles toujours manquantes : $MISSING
     Relance avec une base vierge : sudo ./install.sh --reset-db"
fi
ok "Les ${#ESSENTIAL_TABLES[@]} tables essentielles sont présentes"

# ---------------------------------------------------------------------------
# 6. Fichier .env
# ---------------------------------------------------------------------------
step "6. Configuration (.env)"

if [[ -f .env ]]; then
  cp .env ".env.backup.$(date +%Y%m%d%H%M%S)"
  warn ".env existant sauvegardé — DATABASE_URL mis à jour, le reste conservé"
  python3 - "$DB_URL" <<'PYEOF'
import re, sys
url = sys.argv[1]
content = open('.env').read()
if re.search(r'^DATABASE_URL=', content, re.M):
    content = re.sub(r'^DATABASE_URL=.*$', f'DATABASE_URL={url}', content, flags=re.M)
else:
    content += f'\nDATABASE_URL={url}\n'
open('.env', 'w').write(content)
PYEOF
else
  TOKEN_KEY="$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' 2>/dev/null \
    || "$VENV_DIR/bin/python" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
  cat > .env <<ENVEOF
# --- Généré par install.sh le $(date -Iseconds) ---

# Infrastructure
DATABASE_URL=$DB_URL
APP_BASE_URL=http://localhost:8000
ENV=development
LOG_LEVEL=info

# Session
SESSION_COOKIE_NAME=pg_session
SESSION_COOKIE_SECURE=false
SESSION_TTL_HOURS=720

# Chiffrement des jetons OAuth (NE PAS PERDRE : les comptes connectés
# deviendraient indéchiffrables)
TOKEN_ENCRYPTION_KEY=$TOKEN_KEY

# SMTP — laisser SMTP_HOST VIDE désactive proprement les emails.
# L'application fonctionne alors normalement : les liens d'activation
# sont écrits dans les logs du serveur au lieu d'être envoyés.
# Serveur de test local :
#   docker run -d -p 1025:1025 -p 8025:8025 mailhog/mailhog
#   puis SMTP_HOST=localhost / SMTP_PORT=1025 (webmail sur :8025)
SMTP_HOST=
SMTP_PORT=1025
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM="Post Generator <no-reply@example.com>"
# Chiffrement détecté automatiquement d'après le port :
#   465 -> SSL implicite | 587 -> STARTTLS | 25/1025 -> aucun
# Ne renseigne ci-dessous que pour forcer un mode non standard.
SMTP_USE_TLS=false
SMTP_START_TLS=false

# OpenRouter — REQUIS pour toute génération IA
OPENROUTER_API_KEY=
OPENROUTER_MODEL=openai/gpt-4o-mini
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1

# Worker planifié
WORKER_LOCK_MINUTES=15
WORKER_MAX_ATTEMPTS=3
ENVEOF
  chmod 600 .env
  chown "$RUN_USER":"$RUN_USER" .env 2>/dev/null || true
  ok ".env généré (600, propriétaire $RUN_USER)"
fi

# ---------------------------------------------------------------------------
# 6bis. Serveur d'email
# ---------------------------------------------------------------------------
step "6bis. Configuration des emails"

# Aucun serveur mail n'est installé sur la machine : en production on utilise
# un fournisseur externe (SendGrid, Brevo, Gmail...), et un Postfix local
# enverrait des messages classés en spam. Pour le développement, le projet
# fournit un capteur d'emails sans aucune dépendance (tools/mailcatcher.py)
# qui enregistre les messages sur disque au lieu de les envoyer.

SMTP_CONFIGURED="$(grep -E '^SMTP_HOST=.+' .env 2>/dev/null | head -1 || true)"
if [[ -n "$SMTP_CONFIGURED" ]]; then
  ok "SMTP déjà renseigné dans .env — inchangé"
else
  ok "Emails désactivés (SMTP_HOST vide) : l'application fonctionne,"
  echo "     les liens d'activation sont écrits dans les logs du serveur."
  echo
  echo "     Trois options, au choix :"
  echo "       a) Capteur local (développement, aucune dépendance) :"
  echo "            ./mail.sh"
  echo "          puis dans .env :  SMTP_HOST=127.0.0.1  SMTP_PORT=1025"
  echo "       b) Fournisseur externe : renseigne SMTP_HOST/PORT/USER/PASSWORD"
  echo "          dans .env (SMTP_START_TLS=true pour le port 587)"
  echo "       c) Ne rien faire : les emails restent désactivés"
fi

# ---------------------------------------------------------------------------
# 7. Compte administrateur initial
# ---------------------------------------------------------------------------
step "7. Compte administrateur"

ADMIN_EXISTS="$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -tAc \
  "SELECT count(*) FROM public.app_users WHERE role='admin'" 2>/dev/null || echo 0)"

if [[ "$ADMIN_EXISTS" -gt 0 ]]; then
  ok "Un administrateur existe déjà — création ignorée"
  ADMIN_CREATED=0
else
  if [[ -z "$ADMIN_PASSWORD" ]]; then
    ADMIN_PASSWORD="$(gen_secret | cut -c1-16)Aa1!"
  fi
  psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 -q <<SQLEOF
WITH new_user AS (
  INSERT INTO public.app_users (email, first_name, last_name, full_name, password_hash, role, is_active)
  VALUES (lower('$ADMIN_EMAIL'), 'Admin', 'Système', 'Admin Système',
          crypt('$ADMIN_PASSWORD', gen_salt('bf', 10)), 'admin', true)
  RETURNING id
), ws AS (
  INSERT INTO public.workspaces (name, owner_user_id, is_personal)
  SELECT 'Espace personnel', id, true FROM new_user
  RETURNING id, owner_user_id
)
INSERT INTO public.workspace_members (workspace_id, user_id, role, status, joined_at)
SELECT ws.id, ws.owner_user_id, 'owner', 'active', now() FROM ws;
SQLEOF
  ok "Administrateur créé : $ADMIN_EMAIL"
  ADMIN_CREATED=1
fi

unset PGPASSWORD

# ---------------------------------------------------------------------------
# 8. Vérifications finales
# ---------------------------------------------------------------------------
step "8. Vérifications"

if [[ $DB_ONLY -eq 0 ]]; then
  if "$VENV_DIR/bin/python" -c "import fastapi, asyncpg, jinja2, apscheduler, httpx, bcrypt" 2>/dev/null; then
    ok "Toutes les dépendances Python s'importent"
  else
    die "Certaines dépendances ne s'importent pas — relance : $VENV_DIR/bin/pip install -r requirements.txt"
  fi

  if "$VENV_DIR/bin/python" -m compileall -q app >/dev/null 2>&1; then
    ok "Code applicatif compilé sans erreur"
  else
    warn "Des erreurs de compilation subsistent dans app/"
  fi
fi

chmod +x start.sh mail.sh deploy/setup.sh 2>/dev/null || true

# --- Propriété des fichiers ---------------------------------------------------
# Lancé avec sudo, ce script crée venv/, .env et tmp/ en tant que root, alors
# que l'application tourne sous $RUN_USER. Sans cette reprise de propriété,
# le service échoue au démarrage sur « PermissionError: '.env' ».
if [[ $EUID -eq 0 && "$RUN_USER" != "root" ]]; then
  chown -R "$RUN_USER":"$RUN_USER" "$APP_DIR" 2>/dev/null || \
    warn "Reprise de propriété partielle sur $APP_DIR"
  ok "Fichiers du projet attribués à $RUN_USER"
fi

# ---------------------------------------------------------------------------
# Résumé
# ---------------------------------------------------------------------------
echo
echo "${GREEN}${BOLD}  Installation terminée.${NC}"
echo
echo "  ${BOLD}Base de données${NC}"
echo "    URL      : postgresql://$DB_USER:***@$DB_HOST:$DB_PORT/$DB_NAME"
if [[ ${GENERATED_DB_PWD:-0} -eq 1 ]]; then
echo "    Mot de passe généré : ${YELLOW}$DB_PASSWORD${NC}"
echo "    (enregistré dans .env — aucune action requise)"
fi
echo
if [[ ${ADMIN_CREATED:-0} -eq 1 ]]; then
echo "  ${BOLD}Compte administrateur${NC}"
echo "    Email        : $ADMIN_EMAIL"
echo "    Mot de passe : ${YELLOW}$ADMIN_PASSWORD${NC}"
echo "    ${RED}Note ce mot de passe : il ne sera plus jamais affiché.${NC}"
echo
fi
echo "  ${BOLD}Répertoires${NC}"
echo "    Médias : $MEDIA_DIR"
echo "    Logs   : $LOG_DIR"
echo
echo "  ${BOLD}À faire avant de démarrer${NC}"
echo "    1. Renseigner ${YELLOW}OPENROUTER_API_KEY${NC} dans .env (sinon aucune génération IA)"
echo "    2. SMTP : laissé désactivé par défaut (SMTP_HOST vide)."
echo "       Sans SMTP, le lien d'activation d'un nouveau compte apparaît"
echo "       dans les logs du serveur. Pour un serveur de test local :"
echo "         docker run -d -p 1025:1025 -p 8025:8025 mailhog/mailhog"
echo "    3. Une fois connecté : configurer Meta et Serper dans l'interface d'admin"
echo
echo "  ${BOLD}Démarrer :${NC}  ./start.sh"
echo
