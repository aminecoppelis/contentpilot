#!/usr/bin/env bash
#
# Déploiement de Post Generator derrière un reverse proxy existant.
# À lancer SUR LA VM, après ./install.sh.
#
# Usage :
#   sudo ./deploy/setup.sh --proxy-ip 192.168.1.10 --url https://post.example.com
#
set -Eeuo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

PROXY_IP=""; PUBLIC_URL=""; APP_USER="${SUDO_USER:-$(id -un)}"; PORT=8000
GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; RED=$'\033[0;31m'; BOLD=$'\033[1m'; NC=$'\033[0m'
ok(){ echo "${GREEN}  ✓${NC} $*"; }; warn(){ echo "${YELLOW}  !${NC} $*"; }
die(){ echo "${RED}  ✗ $*${NC}" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --proxy-ip) PROXY_IP="$2"; shift 2 ;;
    --url)      PUBLIC_URL="$2"; shift 2 ;;
    --user)     APP_USER="$2"; shift 2 ;;
    --port)     PORT="$2"; shift 2 ;;
    -h|--help)  sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "Option inconnue : $1" ;;
  esac
done

[[ -n "$PROXY_IP" ]]   || die "--proxy-ip est obligatoire (IP du serveur nginx frontal)"
[[ -n "$PUBLIC_URL" ]] || die "--url est obligatoire (ex: https://post.example.com)"
[[ $EUID -eq 0 ]]      || die "À lancer avec sudo."

# --- Contrôle de cohérence de --proxy-ip -------------------------------------
# C'est le réglage le plus souvent mal renseigné, et son effet est invisible
# jusqu'au jour où plusieurs personnes se connectent en même temps.
VM_IPS="$(hostname -I)"
if [[ " $VM_IPS " == *" $PROXY_IP "* ]]; then
  warn "--proxy-ip ($PROXY_IP) est une IP de CETTE VM, pas celle du serveur nginx."
  warn "  uvicorn ignorerait alors X-Forwarded-For : toutes les connexions"
  warn "  paraîtraient venir de la même adresse et le verrouillage"
  warn "  anti-brute-force bloquerait tous les comptes d'un coup."
  warn "  Sur le serveur nginx, la bonne valeur s'obtient avec :"
  warn "      ip route get ${VM_IPS%% *}     # -> la valeur après 'src'"
  echo
  read -r -p "  Continuer malgré tout ? [o/N] " CONT
  [[ "$CONT" =~ ^[oOyY]$ ]] || die "Interrompu. Relance avec l'IP du serveur nginx."
fi

echo "${BOLD}Déploiement Post Generator${NC}"
echo "  Répertoire   : $APP_DIR"
echo "  Utilisateur  : $APP_USER"
echo "  Proxy amont  : $PROXY_IP"
echo "  URL publique : $PUBLIC_URL"
echo

# --- .env : URL publique + cookie sécurisé -------------------------------
python3 - "$PUBLIC_URL" <<'PY'
import re, sys
url = sys.argv[1].rstrip('/')
env = open('.env').read()
def setkv(content, key, value):
    if re.search(rf'^{key}=', content, re.M):
        return re.sub(rf'^{key}=.*$', f'{key}={value}', content, flags=re.M)
    return content + f'\n{key}={value}\n'
env = setkv(env, 'APP_BASE_URL', url)
env = setkv(env, 'MEDIA_PUBLIC_BASE_URL', url + '/public-media')
env = setkv(env, 'MEDIA_STORAGE_DIR', 'public-media')
env = setkv(env, 'APP_TIMEZONE', 'Europe/Paris')
env = setkv(env, 'TRUST_PROXY_HEADERS', 'true')
env = setkv(env, 'SESSION_COOKIE_SECURE', 'true' if url.startswith('https') else 'false')
open('.env','w').write(env)
PY
# Le script tourne en root : sans cela, .env réécrit appartiendrait à root
# et le service (lancé en $APP_USER) ne pourrait plus le lire.
chown "$APP_USER":"$APP_USER" .env 2>/dev/null || true
chmod 600 .env
ok "APP_BASE_URL = $PUBLIC_URL  (callbacks OAuth + liens publics)"
ok "MEDIA_PUBLIC_BASE_URL = $PUBLIC_URL/public-media"
ok "SESSION_COOKIE_SECURE aligné sur le schéma de l'URL"

# --- Service systemd -----------------------------------------------------
sed -e "s#/home/ubuntu/post_generator#$APP_DIR#g" \
    -e "s#^User=.*#User=$APP_USER#" \
    -e "s#^Group=.*#Group=$APP_USER#" \
    -e "s#--forwarded-allow-ips=[0-9.]*#--forwarded-allow-ips=$PROXY_IP#" \
    -e "s#--port 8000#--port $PORT#" \
    deploy/post-generator.service > /etc/systemd/system/post-generator.service
ok "Service installé : /etc/systemd/system/post-generator.service"

# Contrôle : l'utilisateur du service peut-il réellement lire .env et écrire
# dans les répertoires de travail ? Un échec ici évite un démarrage raté.
if ! sudo -u "$APP_USER" test -r "$APP_DIR/.env"; then
  chown -R "$APP_USER":"$APP_USER" "$APP_DIR" 2>/dev/null || true
  sudo -u "$APP_USER" test -r "$APP_DIR/.env" \
    || die ".env illisible par $APP_USER. Corrige : chown $APP_USER $APP_DIR/.env"
  ok "Propriété des fichiers corrigée pour $APP_USER"
fi
for d in "$APP_DIR/public-media" /var/log/post_generator; do
  [[ -d "$d" ]] && chown -R "$APP_USER":"$APP_USER" "$d" 2>/dev/null || true
done
ok "Répertoires médias et logs accessibles à $APP_USER"

systemctl daemon-reload
systemctl enable post-generator >/dev/null 2>&1
systemctl restart post-generator
sleep 3
if systemctl is-active --quiet post-generator; then
  ok "Service démarré"
else
  echo; journalctl -u post-generator -n 25 --no-pager; die "Le service n'a pas démarré."
fi

# --- Pare-feu : n'ouvrir le port qu'au proxy -----------------------------
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow from "$PROXY_IP" to any port "$PORT" proto tcp >/dev/null
  ok "ufw : port $PORT ouvert uniquement depuis $PROXY_IP"
else
  warn "ufw inactif — pense à restreindre l'accès au port $PORT au seul $PROXY_IP"
fi

# --- Vérification --------------------------------------------------------
sleep 1
if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
  ok "L'application répond sur le port $PORT"
else
  warn "Pas de réponse sur /health — voir : journalctl -u post-generator -f"
fi

VM_IP="$(hostname -I | awk '{print $1}')"
PORT_FINAL="$PORT"
DOMAIN="$(echo "$PUBLIC_URL" | sed -E 's#^https?://##; s#/.*$##')"

echo
echo "${BOLD}Sur le serveur nginx frontal :${NC}"
echo "  Le bloc ci-dessous est complet, sans upstream — proxy_pass direct."
echo
cat <<NGINXCONF
server {
    listen 80;
    server_name ${DOMAIN};
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl;
    server_name ${DOMAIN};

    ssl_certificate     /etc/nginx/ssl/coppelis2025.pem;
    ssl_certificate_key /etc/nginx/ssl/wildcard-coppelis-2025.key;

    client_max_body_size 100M;

    location / {
        proxy_pass http://${VM_IP}:${PORT_FINAL};

        proxy_http_version 1.1;
        proxy_set_header Connection "";

        proxy_set_header Host              \$host;
        proxy_set_header X-Real-IP         \$remote_addr;
        proxy_set_header X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        # Le defaut de 60 s couperait en pleine generation IA
        proxy_connect_timeout 30s;
        proxy_send_timeout    300s;
        proxy_read_timeout    300s;

        proxy_buffering off;
    }
}
NGINXCONF
echo
echo "  Puis :  sudo nginx -t && sudo systemctl reload nginx"
echo
echo "${BOLD}Dans l'app Meta, declarer les URI de redirection :${NC}"
echo "  ${PUBLIC_URL}/app/networks/facebook/callback"
echo "  ${PUBLIC_URL}/app/networks/instagram/callback"
echo
echo "${BOLD}Verification de bout en bout :${NC}"
echo "  Sur la VM       :  curl -s http://127.0.0.1:${PORT_FINAL}/health"
echo "  Depuis nginx    :  curl -s --max-time 5 http://${VM_IP}:${PORT_FINAL}/health"
echo "  Depuis Internet :  curl -I ${PUBLIC_URL}/health"
echo
echo "  Logs : journalctl -u post-generator -f"
