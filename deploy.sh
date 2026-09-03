#!/usr/bin/env bash
#
# Post Generator — mise en production derrière Apache 2.4
#
# Installe et configure : Apache (reverse proxy HTTPS), le service systemd
# de l'application, et éventuellement le certificat Let's Encrypt.
#
# Usage :
#   sudo ./deploy.sh --domain exemple.com
#   sudo ./deploy.sh --domain exemple.com --email admin@exemple.com   # + certificat
#   sudo ./deploy.sh --domain exemple.com --no-ssl                    # HTTP seul (test)
#
set -Eeuo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOMAIN=""
EMAIL=""
WITH_SSL=1
APP_PORT="${APP_PORT:-8000}"
SERVICE_USER="${SERVICE_USER:-${SUDO_USER:-$(id -un)}}"

RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'
BLUE=$'\033[0;34m'; BOLD=$'\033[1m'; NC=$'\033[0m'
info() { echo "${BLUE}==>${NC} $*"; }
ok()   { echo "${GREEN}  ✓${NC} $*"; }
warn() { echo "${YELLOW}  !${NC} $*"; }
die()  { echo "${RED}  ✗ $*${NC}" >&2; exit 1; }
step() { echo; echo "${BOLD}$*${NC}"; }

trap 'die "Échec ligne $LINENO."' ERR

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain) DOMAIN="$2"; shift 2 ;;
    --email)  EMAIL="$2"; shift 2 ;;
    --no-ssl) WITH_SSL=0; shift ;;
    --port)   APP_PORT="$2"; shift 2 ;;
    --user)   SERVICE_USER="$2"; shift 2 ;;
    -h|--help) sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "Option inconnue : $1" ;;
  esac
done

[[ $EUID -eq 0 ]] || die "Ce script doit être lancé avec sudo."
[[ -n "$DOMAIN" ]] || die "Domaine requis : sudo ./deploy.sh --domain exemple.com"
[[ -d "$APP_DIR/venv" ]] || die "venv absent — lance d'abord ./install.sh"

cd "$APP_DIR"

echo "${BOLD}"
echo "  Post Generator — mise en production"
echo "  domaine     : $DOMAIN"
echo "  application : $APP_DIR (port $APP_PORT, utilisateur $SERVICE_USER)"
echo "  HTTPS       : $([[ $WITH_SSL -eq 1 ]] && echo oui || echo non)"
echo "${NC}"

# ---------------------------------------------------------------------------
step "1. Apache et modules"
# ---------------------------------------------------------------------------
if ! command -v apache2 >/dev/null 2>&1; then
  info "Installation d'Apache…"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq -o DPkg::Lock::Timeout=120
  apt-get install -y -qq -o DPkg::Lock::Timeout=120 apache2
fi
ok "Apache présent ($(apache2 -v | head -1 | cut -d: -f2 | xargs))"

info "Activation des modules requis…"
a2enmod proxy proxy_http headers rewrite remoteip >/dev/null 2>&1 || true
[[ $WITH_SSL -eq 1 ]] && a2enmod ssl >/dev/null 2>&1 || true
ok "proxy, proxy_http, headers, rewrite, remoteip$([[ $WITH_SSL -eq 1 ]] && echo ', ssl')"

# ---------------------------------------------------------------------------
step "2. Service systemd de l'application"
# ---------------------------------------------------------------------------
UNIT=/etc/systemd/system/post-generator.service
sed -e "s#/home/ubuntu/post_generator#$APP_DIR#g" \
    -e "s#^User=.*#User=$SERVICE_USER#" \
    -e "s#^Group=.*#Group=$SERVICE_USER#" \
    -e "s#--port 8000#--port $APP_PORT#" \
    deploy/systemd/post-generator.service > "$UNIT"
ok "Unité écrite : $UNIT"

systemctl daemon-reload
systemctl enable post-generator >/dev/null 2>&1
systemctl restart post-generator
sleep 3
if systemctl is-active --quiet post-generator; then
  ok "Service démarré"
else
  echo
  journalctl -u post-generator -n 25 --no-pager | sed 's/^/    /'
  die "Le service n'a pas démarré (voir ci-dessus)."
fi

# ---------------------------------------------------------------------------
step "3. VirtualHost Apache"
# ---------------------------------------------------------------------------
VHOST=/etc/apache2/sites-available/post-generator.conf

if [[ $WITH_SSL -eq 1 ]]; then
  sed -e "s/exemple\.com/$DOMAIN/g" \
      -e "s#/home/ubuntu/post_generator#$APP_DIR#g" \
      -e "s#127.0.0.1:8000#127.0.0.1:$APP_PORT#g" \
      deploy/apache2/post-generator.conf > "$VHOST"
else
  # Variante HTTP seule : pas de TLS, pas de redirection, pas de cookie Secure
  cat > "$VHOST" <<VHEOF
# Post Generator — HTTP seul (test/interne). Ne pas utiliser en production.
<VirtualHost *:80>
    ServerName $DOMAIN
    ErrorLog  \${APACHE_LOG_DIR}/post-generator-error.log
    CustomLog \${APACHE_LOG_DIR}/post-generator-access.log combined

    RemoteIPHeader X-Forwarded-For
    RequestHeader set X-Real-IP         %{REMOTE_ADDR}s
    RequestHeader set X-Forwarded-Proto "http"

    Alias /static/ $APP_DIR/static/
    <Directory $APP_DIR/static/>
        Require all granted
        Options -Indexes
    </Directory>
    ProxyPass /static/ !

    ProxyPreserveHost On
    ProxyRequests Off
    ProxyTimeout 600
    Timeout 600
    ProxyPass        / http://127.0.0.1:$APP_PORT/ retry=0 timeout=600
    ProxyPassReverse / http://127.0.0.1:$APP_PORT/
    <Proxy http://127.0.0.1:$APP_PORT/*>
        Require all granted
    </Proxy>
    LimitRequestBody 67108864
</VirtualHost>
VHEOF
fi
ok "VirtualHost écrit : $VHOST"

a2ensite post-generator >/dev/null 2>&1 || true
# Le site par défaut capterait les requêtes si le ServerName ne correspond pas
a2dissite 000-default >/dev/null 2>&1 || true

info "Vérification de la configuration Apache…"
if apache2ctl configtest 2>&1 | grep -qi "syntax ok"; then
  ok "Configuration valide"
else
  apache2ctl configtest 2>&1 | sed 's/^/    /'
  die "Configuration Apache invalide."
fi

# ---------------------------------------------------------------------------
step "4. Certificat TLS"
# ---------------------------------------------------------------------------
if [[ $WITH_SSL -eq 0 ]]; then
  warn "HTTPS désactivé (--no-ssl) — à réserver aux tests internes"
elif [[ -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]]; then
  ok "Certificat déjà présent pour $DOMAIN"
  systemctl reload apache2
elif [[ -n "$EMAIL" ]]; then
  command -v certbot >/dev/null 2>&1 || {
    info "Installation de certbot…"
    apt-get install -y -qq -o DPkg::Lock::Timeout=120 certbot python3-certbot-apache
  }
  info "Obtention du certificat Let's Encrypt…"
  # Le vhost 443 référence un certificat inexistant : on désactive le temps
  # de l'émission, sinon Apache refuse de recharger.
  a2dissite post-generator >/dev/null 2>&1 || true
  systemctl reload apache2
  if certbot certonly --apache -d "$DOMAIN" --email "$EMAIL" \
       --agree-tos --non-interactive; then
    a2ensite post-generator >/dev/null 2>&1
    systemctl reload apache2
    ok "Certificat obtenu et vhost réactivé"
  else
    a2ensite post-generator >/dev/null 2>&1 || true
    warn "Échec de certbot — vérifie que $DOMAIN pointe bien vers cette machine"
    warn "et que les ports 80/443 sont ouverts, puis relance :"
    warn "  sudo certbot --apache -d $DOMAIN"
  fi
else
  warn "Aucun certificat pour $DOMAIN et --email non fourni."
  warn "Le vhost HTTPS restera inactif tant qu'il n'y a pas de certificat :"
  warn "  sudo certbot --apache -d $DOMAIN"
fi

systemctl restart apache2
ok "Apache rechargé"

# ---------------------------------------------------------------------------
step "5. Mise à jour du .env"
# ---------------------------------------------------------------------------
SCHEME=$([[ $WITH_SSL -eq 1 ]] && echo https || echo http)
python3 - "$APP_DIR/.env" "$SCHEME://$DOMAIN" "$([[ $WITH_SSL -eq 1 ]] && echo true || echo false)" <<'PYENV'
import re, sys
path, base_url, secure = sys.argv[1], sys.argv[2], sys.argv[3]
content = open(path, encoding='utf-8').read()

def upsert(text, key, value):
    if re.search(rf'^{key}=', text, re.M):
        return re.sub(rf'^{key}=.*$', f'{key}={value}', text, flags=re.M)
    return text.rstrip('\n') + f'\n{key}={value}\n'

content = upsert(content, 'APP_BASE_URL', base_url)
content = upsert(content, 'SESSION_COOKIE_SECURE', secure)
content = upsert(content, 'ENV', 'production')
open(path, 'w', encoding='utf-8').write(content)
print(f"  APP_BASE_URL={base_url}")
print(f"  SESSION_COOKIE_SECURE={secure}")
PYENV
ok ".env mis à jour"

systemctl restart post-generator
sleep 2
systemctl is-active --quiet post-generator && ok "Application redémarrée" \
  || die "Redémarrage échoué : journalctl -u post-generator -n 30"

# ---------------------------------------------------------------------------
step "6. Vérification"
# ---------------------------------------------------------------------------
sleep 1
HEALTH="$(curl -sk -o /dev/null -w '%{http_code}' "$SCHEME://$DOMAIN/health" --max-time 10 || echo 000)"
if [[ "$HEALTH" == "200" ]]; then
  ok "Application accessible : $SCHEME://$DOMAIN/health répond 200"
else
  warn "Le point de santé renvoie $HEALTH"
  warn "  Diagnostic : curl -v $SCHEME://$DOMAIN/health"
  warn "  Logs app    : journalctl -u post-generator -n 40"
  warn "  Logs Apache : tail -n 40 /var/log/apache2/post-generator-error.log"
fi

echo
echo "${GREEN}${BOLD}  Déploiement terminé.${NC}"
echo
echo "  Application : ${BOLD}$SCHEME://$DOMAIN/app/login${NC}"
echo
echo "  ${BOLD}Commandes utiles${NC}"
echo "    systemctl status post-generator"
echo "    journalctl -u post-generator -f"
echo "    systemctl restart post-generator"
echo "    tail -f /var/log/apache2/post-generator-error.log"
echo
echo "  ${BOLD}À faire dans la console Meta${NC}"
echo "    URI de redirection OAuth à déclarer à l'identique :"
echo "      $SCHEME://$DOMAIN/app/networks/facebook/callback"
echo "      $SCHEME://$DOMAIN/app/networks/instagram/callback"
echo "    Puis renseigner la même URL publique dans l'écran"
echo "    d'administration « Configuration Meta »."
echo
