#!/usr/bin/env bash
#
# Post Generator — Démarrage du serveur
#
# Usage :
#   ./start.sh                  # démarrage en développement (rechargement auto)
#   ./start.sh --prod           # production (multi-workers, sans rechargement)
#   ./start.sh --port 9000      # port personnalisé
#   ./start.sh --host 0.0.0.0   # écoute sur toutes les interfaces
#   ./start.sh --daemon         # arrière-plan (logs dans le fichier de log)
#   ./start.sh --stop           # arrête une instance lancée en --daemon
#   ./start.sh --status         # état de l'instance
#   ./start.sh --no-worker      # démarre l'API SANS le worker ni les crons
#
set -Eeuo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${VENV_DIR:-$APP_DIR/venv}"
PID_FILE="$APP_DIR/tmp/post_generator.pid"
LOG_FILE="${LOG_FILE:-${LOG_DIR:-$APP_DIR/tmp}/post_generator.log}"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
MODE="dev"
DAEMON=0
WORKERS="${WORKERS:-4}"

RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'
BLUE=$'\033[0;34m'; BOLD=$'\033[1m'; NC=$'\033[0m'
info() { echo "${BLUE}==>${NC} $*"; }
ok()   { echo "${GREEN}  ✓${NC} $*"; }
warn() { echo "${YELLOW}  !${NC} $*"; }
die()  { echo "${RED}  ✗ $*${NC}" >&2; exit 1; }

cd "$APP_DIR"

# ---------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --prod)       MODE="prod"; shift ;;
    --dev)        MODE="dev"; shift ;;
    --port)       PORT="$2"; shift 2 ;;
    --host)       HOST="$2"; shift 2 ;;
    --workers)    WORKERS="$2"; shift 2 ;;
    --daemon|-d)  DAEMON=1; shift ;;
    --no-worker)  export DISABLE_SCHEDULER=1; shift ;;
    --stop)
      if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        PID="$(cat "$PID_FILE")"
        info "Arrêt du processus $PID…"
        kill -TERM "$PID"
        for _ in $(seq 1 20); do
          kill -0 "$PID" 2>/dev/null || break
          sleep 0.5
        done
        if kill -0 "$PID" 2>/dev/null; then
          warn "Arrêt propre échoué — SIGKILL"
          kill -KILL "$PID" 2>/dev/null || true
        fi
        rm -f "$PID_FILE"
        ok "Serveur arrêté"
      else
        warn "Aucune instance en cours (pas de PID valide)"
        rm -f "$PID_FILE"
      fi
      exit 0 ;;
    --status)
      if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "${GREEN}En cours${NC} — PID $(cat "$PID_FILE")"
        echo "Logs : $LOG_FILE"
      else
        echo "${YELLOW}Arrêté${NC}"
      fi
      exit 0 ;;
    -h|--help)
      sed -n '2,17p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) die "Option inconnue : $1 (voir --help)" ;;
  esac
done

echo "${BOLD}"
echo "  Post Generator"
echo "${NC}"

# ---------------------------------------------------------------------------
# Contrôles avant démarrage
# ---------------------------------------------------------------------------
info "Contrôles avant démarrage…"

[[ -d "$VENV_DIR" ]] || die "venv introuvable. Lance d'abord : ./install.sh"
[[ -f "$VENV_DIR/bin/uvicorn" ]] || die "uvicorn absent du venv. Relance : ./install.sh"
[[ -f .env ]] || die ".env introuvable. Lance d'abord : ./install.sh"

# Instance déjà lancée ?
if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  die "Une instance tourne déjà (PID $(cat "$PID_FILE")). Utilise --stop ou --status."
fi

# Port déjà occupé ?
if command -v ss >/dev/null 2>&1; then
  if ss -ltn 2>/dev/null | grep -q ":$PORT "; then
    die "Le port $PORT est déjà utilisé. Essaie : ./start.sh --port 8001"
  fi
elif command -v lsof >/dev/null 2>&1; then
  if lsof -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    die "Le port $PORT est déjà utilisé. Essaie : ./start.sh --port 8001"
  fi
fi
ok "Port $PORT disponible"

# Connexion à la base
DB_URL="$(grep -E '^DATABASE_URL=' .env | head -1 | cut -d= -f2-)"
[[ -n "$DB_URL" ]] || die "DATABASE_URL absent de .env"

"$VENV_DIR/bin/python" - "$DB_URL" <<'PYEOF' || die "Connexion à PostgreSQL impossible — vérifie que le service tourne et que DATABASE_URL est correct."
import asyncio, sys
import asyncpg

async def main(dsn):
    try:
        conn = await asyncio.wait_for(asyncpg.connect(dsn), timeout=8)
    except Exception as exc:
        print(f"    {exc}", file=sys.stderr)
        return 1
    try:
        tables = await conn.fetchval(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
        if tables < 5:
            print(f"    Base accessible mais seulement {tables} table(s) : migration manquante ?",
                  file=sys.stderr)
            return 1
        has_pgcrypto = await conn.fetchval(
            "SELECT count(*) FROM pg_extension WHERE extname='pgcrypto'")
        if not has_pgcrypto:
            print("    Extension pgcrypto absente (requise pour bcrypt).", file=sys.stderr)
            return 1
    finally:
        await conn.close()
    return 0

sys.exit(asyncio.run(main(sys.argv[1])))
PYEOF
ok "Base de données accessible (schéma et pgcrypto présents)"

# Clé OpenRouter renseignée ?
if ! grep -qE '^OPENROUTER_API_KEY=.+' .env; then
  warn "OPENROUTER_API_KEY vide dans .env — toute génération IA échouera"
fi

# Serveur SMTP : test réel du dialogue (connexion + chiffrement + auth).
# Non bloquant : l'application fonctionne sans email.
SMTP_H="$(grep -E '^SMTP_HOST=' .env | head -1 | cut -d= -f2- | tr -d '"' )"
if [[ -z "$SMTP_H" ]]; then
  warn "SMTP_HOST vide — emails désactivés (activation de compte, invitations, alertes)"
else
  SMTP_RESULT="$("$VENV_DIR/bin/python" - <<'PYSMTP' 2>&1
import os, smtplib, ssl, sys
def env(key, default=""):
    for line in open(".env", encoding="utf-8"):
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"')
    return default

host = env("SMTP_HOST"); port = int(env("SMTP_PORT", "25") or 25)
user = env("SMTP_USER"); pwd = env("SMTP_PASSWORD")
use_tls = env("SMTP_USE_TLS", "false").lower() == "true" or port == 465
start_tls = env("SMTP_START_TLS", "false").lower() == "true" or port in (587, 2587)
mode = "SSL implicite" if use_tls else ("STARTTLS" if start_tls else "clair")
try:
    if use_tls:
        srv = smtplib.SMTP_SSL(host, port, timeout=8, context=ssl.create_default_context())
    else:
        srv = smtplib.SMTP(host, port, timeout=8)
        if start_tls:
            srv.starttls(context=ssl.create_default_context())
    with srv:
        srv.ehlo()
        if user and pwd:
            srv.login(user, pwd)
            print(f"OK|{mode}, authentification réussie")
        else:
            print(f"OK|{mode}, sans authentification")
except Exception as exc:
    print(f"KO|{mode}|{type(exc).__name__}: {exc}")
    sys.exit(1)
PYSMTP
)" || true
  if [[ "$SMTP_RESULT" == OK\|* ]]; then
    ok "SMTP opérationnel (${SMTP_RESULT#OK|})"
  else
    warn "SMTP inutilisable : ${SMTP_RESULT#KO|}"
    warn "  Port 465 -> SSL implicite | port 587 -> STARTTLS (détection automatique)"
    warn "  Capteur local sans configuration : ./mail.sh"
    warn "  Les emails échoueront, mais l'application fonctionnera normalement."
  fi
fi

mkdir -p "$(dirname "$LOG_FILE")" "$APP_DIR/tmp"

# ---------------------------------------------------------------------------
# Construction de la commande
# ---------------------------------------------------------------------------
if [[ "$MODE" == "prod" ]]; then
  # ATTENTION : avec plusieurs workers uvicorn, le scheduler APScheduler
  # démarrerait dans CHAQUE worker — le cron tournerait N fois par minute.
  # Le verrouillage SQL (FOR UPDATE SKIP LOCKED) empêche le double traitement
  # d'une même tâche, mais pour éviter la charge inutile on lance un seul
  # worker porteur du scheduler, sauf si --no-worker est passé.
  if [[ "${DISABLE_SCHEDULER:-0}" == "1" ]]; then
    CMD=("$VENV_DIR/bin/uvicorn" app.main:app --host "$HOST" --port "$PORT"
         --workers "$WORKERS" --log-level info --no-access-log)
    RUN_DESC="production, $WORKERS workers, SANS scheduler"
  else
    CMD=("$VENV_DIR/bin/uvicorn" app.main:app --host "$HOST" --port "$PORT"
         --workers 1 --log-level info)
    RUN_DESC="production, 1 worker (scheduler actif)"
    warn "Mode prod avec scheduler : 1 seul worker uvicorn."
    warn "Pour scaler : lance l'API avec --no-worker --workers $WORKERS,"
    warn "et un process séparé dédié au scheduler."
  fi
else
  CMD=("$VENV_DIR/bin/uvicorn" app.main:app --host "$HOST" --port "$PORT"
       --reload --reload-dir app --reload-dir templates --log-level debug)
  RUN_DESC="développement, rechargement automatique"
fi

[[ "${DISABLE_SCHEDULER:-0}" == "1" ]] && warn "Worker et crons DÉSACTIVÉS (--no-worker)"

echo
info "Mode : $RUN_DESC"
echo "    URL       : ${BOLD}http://${HOST}:${PORT}${NC}"
echo "    Connexion : http://${HOST}:${PORT}/app/login"
echo "    Santé     : http://${HOST}:${PORT}/health"
echo

# ---------------------------------------------------------------------------
# Lancement
# ---------------------------------------------------------------------------
if [[ $DAEMON -eq 1 ]]; then
  info "Démarrage en arrière-plan…"
  nohup "${CMD[@]}" >>"$LOG_FILE" 2>&1 &
  APP_PID=$!
  echo "$APP_PID" > "$PID_FILE"
  sleep 3
  if kill -0 "$APP_PID" 2>/dev/null; then
    ok "Serveur démarré — PID $APP_PID"
    echo "    Logs   : tail -f $LOG_FILE"
    echo "    Arrêt  : ./start.sh --stop"
  else
    rm -f "$PID_FILE"
    echo
    echo "${RED}Le serveur s'est arrêté immédiatement. Dernières lignes du log :${NC}"
    tail -n 25 "$LOG_FILE" 2>/dev/null || true
    exit 1
  fi
else
  echo "${YELLOW}  Ctrl+C pour arrêter${NC}"
  echo
  echo "$$" > "$PID_FILE"
  trap 'rm -f "$PID_FILE"; echo; info "Serveur arrêté."; exit 0' INT TERM
  exec "${CMD[@]}"
fi
