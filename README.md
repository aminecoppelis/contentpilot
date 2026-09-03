# Post Generator — Portage Python (FastAPI) + HTML/CSS/JS

Portage du workflow n8n `Post Generator V0 - Unified Calendar Worker V90`
(925 nœuds) vers une architecture Python classique.

## Fidélité au comportement original

Ce portage vise une fidélité maximale sur les parties les plus critiques :

| Module | Fidélité | Détail |
|---|---|---|
| Authentification (login/register/session/verrouillage) | **Verbatim** | SQL exact porté depuis les nœuds originaux (`sql/auth/*.sql`) |
| Worker planifié (claim/save/finalize) | **Verbatim** | SQL exact porté (`sql/worker/*.sql`), y compris la requête de réclamation atomique `FOR UPDATE SKIP LOCKED` |
| Prompts des agents IA | **Verbatim** | `app/services/prompts.py`, aucune reformulation |
| Crons (1min / 15min / 6h) | **Identique** | Mêmes expressions cron (`app/worker/scheduler.py`) |
| Publication (dispatch + normalisation CTA) | **Fidèle** | Logique de dédoublonnage de CTA/titre/hashtags portée depuis le nœud original |
| Endpoints Meta/Buffer/Serper | **Fidèle** | Mêmes endpoints, mêmes formats de payload |
| Pages HTML | **Reconstruites** | Le HTML original était généré par du JS inline dans n8n ; templates Jinja2 propres reconstruits (même structure fonctionnelle, design neuf) |
| Validation cron (seuil de rappel) | **Approximatif** | Seuil non documenté dans l'original, valeur par défaut assumée (`REMINDER_THRESHOLD_HOURS`) |
| Génération média (image/vidéo) | **Squelette** | Pipeline structuré, contrat exact du fournisseur IA à confirmer/brancher |

Voir la documentation complète (Cahier technique + Addendum) fournie séparément
pour la traçabilité détaillée de chaque choix.

## Installation et démarrage

Deux scripts couvrent tout le cycle de vie.

### 1. Installation

```bash
sudo ./install.sh
```

Le script enchaîne :
1. Installation des paquets système (Python 3.10+, PostgreSQL, libpq, build-essential)
   — détecte Debian/Ubuntu, Fedora/RHEL, Arch
2. Démarrage et activation du service PostgreSQL
3. Création du venv + installation des dépendances Python
4. Création des répertoires de médias (`/var/lib/post_generator/media`) et de
   logs (`/var/log/post_generator`), avec les droits sur l'utilisateur courant
5. Création du rôle et de la base PostgreSQL, activation de **pgcrypto**
   (indispensable : bcrypt, hachage des jetons, chiffrement Serper)
6. Application de la migration (protection anti-écrasement si la base contient
   déjà des tables)
7. Génération du `.env` avec une `TOKEN_ENCRYPTION_KEY` aléatoire (permissions 600)
8. Création du compte administrateur initial + son workspace personnel
9. Vérification que les dépendances s'importent et que le code compile

Les mots de passe (base et admin) sont **générés aléatoirement** et affichés
une seule fois en fin d'installation.

Options : `--no-system` (Python/PostgreSQL déjà installés), `--db-only`
(base et migration uniquement), `--help`.

Variables surchargeables : `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`,
`DB_PORT`, `MEDIA_DIR`, `LOG_DIR`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `VENV_DIR`,
`PYTHON_BIN`, `APT_LOCK_TIMEOUT`.

### Prérequis

- **Python 3.10 minimum** — Ubuntu 22.04 (3.10) et 24.04 (3.12) conviennent
  tels quels. Si plusieurs versions sont installées, le script choisit
  automatiquement la plus récente ; pour forcer :
  `PYTHON_BIN=python3.12 sudo -E ./install.sh`
- **PostgreSQL 12 minimum** (pour `FOR UPDATE SKIP LOCKED` et `gen_random_uuid()`)

### Cas particuliers gérés

- **Verrou dpkg** : sur une machine fraîchement démarrée, `unattended-upgrades`
  tient le verrou apt. Le script attend sa libération (jusqu'à 300 s, réglable
  via `APT_LOCK_TIMEOUT`) au lieu d'échouer, et réessaie une fois.
- **Réinstallation** : la migration n'est pas réappliquée si la base contient
  déjà des tables, aucun second administrateur n'est créé, et le `.env`
  existant est sauvegardé avant modification.

```bash
ADMIN_EMAIL=moi@exemple.com DB_NAME=pg_prod sudo -E ./install.sh
```

### 2. Démarrage

```bash
./start.sh                  # développement, rechargement automatique
./start.sh --prod           # production
./start.sh --daemon         # arrière-plan
./start.sh --stop           # arrêt
./start.sh --status         # état
./start.sh --port 9000 --host 0.0.0.0
./start.sh --no-worker      # API seule, sans worker ni crons
```

Avant de lancer, `start.sh` vérifie : venv et `.env` présents, port libre,
aucune instance déjà active, **connexion PostgreSQL effective**, schéma migré,
extension pgcrypto active, répertoire médias inscriptible, et avertit si
`OPENROUTER_API_KEY` est vide.

#### Note importante sur le mode production

Le worker et les crons tournent via APScheduler **dans le process applicatif**.
Avec plusieurs workers uvicorn, le scheduler démarrerait dans chacun d'eux :
le cron s'exécuterait N fois par minute. Le verrouillage SQL
(`FOR UPDATE SKIP LOCKED`) empêche qu'une même tâche soit traitée deux fois,
mais la charge serait inutilement multipliée.

`--prod` lance donc **un seul worker uvicorn** par défaut. Pour scaler
correctement, séparer les deux rôles :

```bash
./start.sh --prod --no-worker --workers 4   # API scalable, sans scheduler
./start.sh --no-worker=0 --daemon           # un process dédié au scheduler
```

### Alternative Docker

```bash
cp .env.example .env
docker compose up --build
```

## Structure du projet

```
app/
  main.py              # Point d'entrée FastAPI, montage des routeurs, scheduler
  config.py            # Configuration d'infrastructure (.env uniquement)
  database.py           # Pool asyncpg + chargeur de requêtes SQL (sql/*.sql)
  security.py            # bcrypt, hash session, anti-bot, redirections sûres
  dependencies/auth.py     # Résolution de session (factorisée, cf. §10.2 Cahier technique)
  routers/                  # Un routeur par domaine (auth, posts, media, publish,
                             # networks, strategies, workspace, admin)
  services/
    prompts.py               # Prompts IA VERBATIM
    ai.py                     # Client OpenRouter
    meta.py, buffer.py, serper.py   # Clients API tierces
    mailer.py                 # Emails transactionnels
    crypto.py                  # Chiffrement des jetons OAuth
    settings_service.py         # Configuration MÉTIER lue en base (pas en .env)
  worker/
    calendar_worker.py          # Cycle du Worker planifié (algorithme exact)
    validation_cron.py           # Cron rappels (15 min)
    instagram_token_cron.py       # Cron rafraîchissement jetons (6h)
    scheduler.py                   # Ordonnancement APScheduler (cron exacts)
sql/
  auth/*.sql              # Requêtes SQL verbatim (login, register, session...)
  worker/*.sql              # Requêtes SQL verbatim (claim, save, finalize, maintenance)
templates/                   # Pages HTML (Jinja2)
static/                       # CSS/JS
migrations/001_init.sql         # DDL complet
```

## Ce qui reste à finaliser avant mise en production

1. **Génération de médias (image/vidéo)** : le contrat exact de l'API du
   fournisseur IA (probablement Grok Imagine via OpenRouter) doit être
   confirmé et branché dans `app/routers/media.py` — actuellement un
   squelette fonctionnel avec endpoints génériques.
2. **File de jobs asynchrone** pour la vidéo et la publication différée
   (recommandation Addendum §8) — actuellement traité en direct/synchrone
   pour rester simple, à migrer vers Celery/BullMQ-équivalent pour la charge
   de production.
3. **Design des pages HTML** : reconstruit proprement mais pas pixel-perfect
   par rapport à l'original (dont le HTML exact n'était pas extrait dans la
   documentation) — à ajuster selon la charte graphique réelle si besoin.
4. **Seuil du cron de rappel** (`REMINDER_THRESHOLD_HOURS`) à valider avec
   le produit — non documenté dans le workflow source.
5. **Tests automatisés** — non fournis dans cette livraison initiale (voir
   Addendum §10 pour la stratégie de tests recommandée).
6. **Génération de scénario vidéo dédié** (agent IA "Générer scénario vidéo")
   dont le prompt exact n'a pas été extrait du workflow source.

## Journal des corrections (2e passe d'extraction)

Une ré-analyse ciblée du fichier source a permis de corriger plusieurs
inexactitudes de la première livraison — **par le passé, ce portage
contenait des approximations sur les points suivants, désormais corrigés
avec les valeurs exactes extraites des nœuds originaux** :

| Point corrigé | Avant (approximation) | Après (exact, extrait du workflow) |
|---|---|---|
| API Buffer | Endpoint REST simple supposé | **API GraphQL réelle** (`mutation CreatePost`), échappement manuel des chaînes (`escGraphql`), assemblé dans `app/services/buffer.py` |
| Facebook — publication photo | `{message, url}` sur `/photos` | `{url, caption, published:true}` — **le champ est `caption`, pas `message`** |
| Facebook — publication vidéo | Confondu avec le flux Reel | Endpoint natif distinct `/videos` avec `{file_url, description}` |
| Version Graph API par défaut | `v19.0` (supposition) | **`v25.0`**, confirmée par le nœud "Instagram - Lire identité canonique" |
| Identité canonique Instagram | Non implémentée | `GET https://graph.instagram.com/{version}/me?fields=user_id,username` ajoutée (`meta.get_instagram_canonical_identity`) |
| Génération d'image IA | Endpoint générique supposé | **Deux endpoints réels selon le modèle** : `x-ai/grok-imagine-image-quality` → `POST /v1/images` (payload `resolution`, `aspect_ratio`, `input_references`) ; sinon `POST /v1/chat/completions` avec `modalities:['image','text']` |
| Génération vidéo IA | Squelette non implémenté | **Payload exact** : `POST /v1/videos`, modèle `x-ai/grok-imagine-video`, `temperature:0.4` fixe, `resolution:'480p'/'720p'`, `frame_images`, `generate_audio` — cycle create → poll (`polling_url`) → download (`video_content_download_url`) |
| Cron de rappel (validation) | Seuil de 24h inventé | **Algorithme réel complet** : table dédiée `app_post_validation_email_reminders`, pattern de bail (`lease_until`/`lease_token`, 20 min), **intervalle exact de 2 heures** entre rappels réussis, auto-résolution dès que l'idée n'est plus à valider |
| Email de rappel de validation | Template générique | **HTML verbatim** reproduit caractère pour caractère (badge de rappel, bloc sujet/idée, mention "toutes les 2 heures") |
| Page de connexion (HTML/CSS/JS) | Reconstruction avec design neuf | **Port pixel-perfect** : design tokens exacts (`--accent:#4f46e5`, `--accent2:#06b6d4`, dégradé radial, cartes arrondies 28px), y compris le **compte à rebours de verrouillage côté client** (JS exact) |

Ces corrections montrent que la quasi-totalité du comportement métier —
y compris les détails d'intégration tierce les plus fins — est bien
présente dans le fichier JSON du workflow et extractible avec une lecture
suffisamment approfondie. Les points ci-dessous restent, eux, de vraies
zones grises **non résolubles par l'extraction** (informations absentes du
fichier lui-même, ex. secrets de credentials, ou comportement dépendant de
l'état runtime de n8n non sérialisé) :

- Le **modèle LLM texte exact** utilisé par les agents (`lmChatOpenRouter`)
  n'est pas visible dans l'export JSON — il dépend soit d'un réglage par
  défaut du credential (non exporté), soit d'un champ non repris par
  l'export. `OPENROUTER_MODEL` reste donc configurable, pas figé.
- Le HTML complet de **chaque** page (dashboard, liste de posts, éditeur,
  stratégies...) n'a pas été extrait exhaustivement — seule la page de
  connexion a été portée pixel-perfect à titre de preuve de méthode ; les
  autres pages gardent un design cohérent (mêmes tokens CSS) mais une
  structure HTML reconstruite plutôt que verbatim.



Voir `.env.example`. Rappel architectural important : les clés Meta/Buffer/
Serper ne sont **pas** dans `.env` — elles sont gérées dynamiquement via
`/app/admin/settings` et stockées dans `app_integration_settings` /
`app_social_accounts`, exactement comme dans le workflow original.## État du portage des pages — TERMINÉ

Toutes les pages du workflow original sont portées.

| Page | État | Détail |
|---|---|---|
| Login / Register / Activate | **Pixel-perfect** | Design tokens exacts, compte à rebours de verrouillage JS |
| Topbar partagée | **Verbatim** | `topbar.css` + `topbar.js` : sélecteur de workspace avec recherche, modale de création, menu utilisateur, nav mobile |
| Composants partagés | **Verbatim** | `pgToast`/`pgFlash`, compteur de caractères des textarea (limites exactes par champ), filtres multi-statuts, scroll infini |
| Account | **Fidèle** | 2 panneaux repliables ; le changement d'email désactive le compte + révoque les sessions |
| Workspace | **Fidèle** | 8 actions réelles, table `workspace_invitations`, protection du dernier workspace |
| Admin Users | **Fidèle** | Modale d'édition, pagination, garde anti-double-soumission |
| Paramétrage admin (Serper) | **Fidèle** | Table `app_external_api_settings`, clé chiffrée pgcrypto |
| Configuration Meta admin | **Fidèle** | Formulaire unique 2 providers, validations strictes, "Enregistrer et tester" |
| Dashboard | **Fidèle** | KPI, prochaines actions, bouton "Nettoyer et relancer" |
| Sujets (liste) | **Fidèle** | Liste les `post_requests` avec agrégats idées/approuvées/médias |
| Nouveau sujet (formulaire) | **Fidèle** | Multi-select personnalisés, suggestions Serper, reformulation IA, overlay |
| Modifier un sujet | **Fidèle** | Multi-select avec champs cachés, tous les paramètres éditables |
| **Consultation / édition d'un post** | **Fidèle** | CSS verbatim (42 756 car.) ; éditeur avec mise en forme Unicode (gras/italique/souligné), autosave, régénération IA, validation/refus, carrousel de médias + lightbox, génération image/vidéo, modale de publication multi-comptes, "générer plus d'idées" |
| Idées de post (Historique) | **Fidèle** | Filtre multi-statuts, scroll infini, cellules personne/publication |
| Posts publiés | **Fidèle** | Sélection groupée, modale d'erreur, suppression en masse |
| Mes réseaux | **Fidèle** | Menu kebab 5 actions, modale Buffer (nom/clé/channel), partage, états de jeton |
| Stratégies | **Fidèle** | Table avec progression, modale de création, génération d'instruction IA, reprogrammation de créneau |
| Page d'erreur / 404 | **Verbatim** | Style et markup exacts |

**Couverture des endpoints : 70/70** — tous les webhooks du workflow original
ont une route équivalente, y compris les proxys de médias
(`/posts/media-image.jpg`, `/posts/media-image-buffer.jpg`,
`/posts/media-video.mp4`, `/posts/media-inline`,
`/posts/video-content-grok-imagine[.mp4]`), la pagination
(`/posts/list-page`, `/networks/list-page`, `/admin/users/list-page`),
la sélection de Pages Facebook, le test des identifiants Meta et la
migration multi-workspace.

### Note sur les proxys de médias

Ces routes sont volontairement **non authentifiées** : Meta et Buffer viennent
chercher le fichier depuis leurs propres serveurs, sans cookie de session.
La protection repose sur l'imprévisibilité de l'UUID du média, exactement
comme dans le workflow d'origine. Le répertoire de stockage local est
`MEDIA_DIR` (`app/routers/media_proxy.py`) — à monter sur un volume
persistant, ou à remplacer par un bucket S3 en production (Addendum §8).




## Audit qualité (syntaxe / règles / fonctionnel / performance / logique)

Un audit systématique a été mené après le portage. Résultats et corrections :

### Syntaxe — OK
`python -m compileall` passe sur tous les fichiers, tous les templates Jinja2
se parsent, les parenthèses de tous les fichiers SQL sont équilibrées, et
chaque fichier SQL / template référencé dans le code existe réellement.

### Règles métier — 1 écart corrigé
- **`requires_post_generation` n'était pas appliqué à la planification.** Toutes
  les actions étaient envoyées au calendrier avec `generation_required: true`,
  ce qui aurait fait générer des posts pour des tâches manuelles (bio, audit,
  mesure) — exactement ce que le Cahier technique §7.7 interdit. Corrigé :
  la catégorie et le `media_prefill` sont désormais évalués avant insertion.

### Fonctionnel — 3 bugs corrigés
- **Jointure cassée dans `/history`** : `LIMIT 0` dans une sous-requête rendait
  la colonne « Publié par » toujours vide. Remplacée par un `LATERAL` correct.
- **`published_by` inexistant en base** alors que deux pages l'affichaient ;
  colonne ajoutée (+ `published_at`, `error_message`) et désormais renseignée
  à la publication.
- **`/published` affichait le créateur comme publieur** (même alias SQL utilisé
  deux fois). Corrigé avec une jointure distincte.
- Le callback OAuth Facebook connectait toutes les Pages d'office ; il crée
  maintenant des *candidats* et laisse l'utilisateur choisir, comme l'original.
  Le `state` OAuth consommé est supprimé (rejeu impossible).

### Logique / intégrité — transactions ajoutées
Aucune écriture multi-tables n'était transactionnelle. Un échec en cours de lot
laissait des données incohérentes (idées sans version courante, stratégie sans
actions, deux versions `is_current` simultanées). Transactions ajoutées sur :
génération d'idées, `generate-more`, édition/régénération IA, création de
stratégie, planification au calendrier, publication, callbacks OAuth.

### Performance — 3 axes corrigés
- **N+1 supprimés** : les comptes sociaux sont préchargés en une requête avant
  la boucle de publication ; les actions de stratégie et les entrées de
  calendrier sont insérées via `executemany` au lieu d'un aller-retour par ligne.
- **Connexion PG plus retenue pendant les appels réseau** : un appel Meta/Buffer
  peut durer 2 minutes ; la connexion était auparavant conservée pendant tout
  l'appel, ce qui aurait épuisé le pool sous charge. Les appels tiers se font
  désormais hors `pool.acquire()`.
- **14 index ajoutés** : toutes les listes filtrent par `workspace_id` et trient
  par date sans index ; les lookups par jeton haché (session, activation,
  invitation, `state` OAuth) faisaient des scans séquentiels. Un index partiel
  couvre aussi la requête de réclamation du Worker.

### Limite persistante
**Rien de tout cela n'a été exécuté** (ni réseau ni PostgreSQL dans
l'environnement de portage). Cet audit est statique : il détecte les erreurs de
structure, de schéma et de logique, mais pas les erreurs d'exécution. Le premier
`docker compose up` reste l'étape de vérification décisive.


## Audit des déclarations de variables

Aucun linter n'étant disponible dans l'environnement de portage, un
vérificateur AST dédié a été écrit pour détecter les noms non définis
(le cas typique que `compileall` ne voit pas : le code compile, mais lève
un `NameError` seulement quand la ligne est atteinte).

**1 bug réel trouvé et corrigé :**
- `app/routers/networks.py` — `decrypt_token` était utilisé dans
  `/networks/quota` sans être importé. La route aurait levé un `NameError`
  au premier appel sur un compte Buffer. Import ajouté.

**Vérifications complémentaires, toutes au vert :**

| Contrôle | Résultat |
|---|---|
| Noms Python non définis | 1 corrigé ; les 10 restants sont des faux positifs (paramètres de fonctions imbriquées, non suivis par le vérificateur) |
| Syntaxe JS (`node --check`) sur les 10 fichiers statiques | OK |
| Syntaxe des scripts inline des templates (Jinja neutralisé) | OK — 0 erreur |
| Fonctions appelées depuis `onclick`/`onsubmit` mais non définies | aucune |
| Variables Jinja2 utilisées mais non fournies par la route | aucune |
| Placeholders SQL inline `$N` vs arguments passés | cohérent partout |
| Placeholders des fichiers `sql/*.sql` vs arguments passés | cohérent partout |
| Colonnes lues dans les résultats vs colonnes des `SELECT` | cohérent |


## Organisation des feuilles de style

L'ordre de chargement dans `base.html` est significatif :

| Fichier | Rôle | Portée |
|---|---|---|
| `layout.css` | **Base obligatoire** : `:root` (toutes les variables), `body`, `.topbar`, `.nav`, `.wrap`/`.app`, `.header`, `.card`, `table`, `.badge`, `.btn`, `.notice`, champs de formulaire | Toutes les pages internes |
| `app.css` | Pages d'authentification uniquement (`.auth-shell`, `.authCard`, `.field`, `.hpField`) — ces pages n'étendent pas `base.html` et sont autonomes | login / register / activate |
| `topbar.css` | Sélecteur de workspace, menu utilisateur, nav mobile (port verbatim de `pgWorkspaceSelectorStyles`) | Toutes les pages internes |
| `toast.css`, `tables.css` | Composants partagés | Toutes |
| `consultation.css`, `networks.css`, `strategies.css`, `form.css`, `published.css` | Spécifiques à une page, chargées via `{% block extra_style %}` | Page concernée |

**Règle à respecter** : ne jamais redéfinir dans `app.css` une règle de
structure (`.topbar`, `.card`, `table`, `.btn`…). Chargé après `layout.css`,
il l'écraserait sur toutes les pages internes.

**Toutes les variables CSS doivent être déclarées dans le `:root` de
`layout.css`**, y compris les alias (`--primary`/`--accent`,
`--primary2`/`--accent2`). Une variable non déclarée rend la propriété
invalide en silence : c'est ce qui avait transformé les boutons en blocs
blancs sans bordure.

Un contrôle rapide des variables orphelines :

```bash
grep -rhoP 'var\(--[\w-]+' static/css templates | sort -u
```


## Emails en développement

`install.sh` n'installe **pas** de serveur mail : en production on utilise un
fournisseur externe (SendGrid, Brevo, Gmail…), et un Postfix local enverrait
des messages classés en spam. Trois options sont proposées à la place.

### a) Capteur local — recommandé en développement

```bash
./mail.sh
```

Serveur SMTP minimal écrivant les emails sur disque au lieu de les envoyer.
**Aucune dépendance** (stdlib Python uniquement), aucun Docker.

Pour chaque message reçu : un `.eml`, un `.html`, une ligne dans `index.log`,
et un affichage console avec **le lien d'activation ou d'invitation extrait
automatiquement** — c'est le plus pratique pour créer un compte sans mail réel.

```
  [1] Active ton compte Post Generator
      destinataire : ubuntu@example.com
      lien         : http://localhost:8000/app/activate?token=abc123
      fichier      : 20260825-131420-001-active-ton-compte.html
```

Puis dans `.env` : `SMTP_HOST=127.0.0.1` et `SMTP_PORT=1025`.

### b) Fournisseur externe

```
SMTP_HOST=smtp.sendgrid.net
SMTP_PORT=587
SMTP_USER=apikey
SMTP_PASSWORD=SG.xxxx
SMTP_START_TLS=true
```

### c) Emails désactivés (défaut)

`SMTP_HOST` vide. L'application fonctionne normalement ; les liens
d'activation sont écrits dans les logs du serveur. Aucun envoi n'est tenté et
aucune action utilisateur n'échoue à cause du mail.


## Outils de vérification (`tools/`)

À lancer après toute modification du schéma ou des requêtes :

```bash
python3 tools/check_schema.py        # colonnes référencées vs schéma déclaré
python3 tools/validate_migration.py  # ordre des tables, FK, index
python3 tools/normalize_migration.py src.sql dst.sql   # rend une migration applicable
```

`check_schema.py` analyse les fichiers `sql/**/*.sql` **et** les requêtes
écrites en dur dans `app/**/*.py`, puis les compare aux colonnes déclarées
dans `migrations/`. C'est ce contrôle qui détecte en amont les erreurs du type
`UndefinedColumnError: column u.activated_at does not exist`, qui ne se
manifestaient jusque-là qu'à l'exécution de la route concernée.

### Migrations

| Fichier | Contenu |
|---|---|
| `001_init.sql` | Schéma complet (24 tables, 27 index) |
| `002_missing_columns.sql` | Colonnes découvertes après coup, additives et idempotentes |

`install.sh` applique `001` puis toutes les migrations `0NN_` suivantes dans
l'ordre, chacune dans sa propre transaction. Sur une base existante, seules
les migrations additives ont un effet.


## Migrations appliquées automatiquement au démarrage

L'application applique elle-même les migrations manquantes au lancement
(`app/migrations.py`, activé par `AUTO_MIGRATE=true`, valeur par défaut).

Une table `schema_migrations` mémorise les fichiers déjà appliqués avec
l'empreinte SHA-256 de leur contenu :

- un fichier inconnu est exécuté dans une transaction unique (échec = base
  inchangée) puis enregistré ;
- un fichier déjà appliqué est ignoré ;
- un fichier déjà appliqué mais **modifié depuis** est signalé dans les logs
  et **non rejoué**, pour ne jamais écraser de données en silence. Pour
  changer le schéma, ajouter un nouveau fichier `0NN_*.sql`.

Conséquence pratique : **plus besoin de relancer `install.sh` après une mise
à jour du code**. Un simple `./start.sh` suffit — les colonnes ajoutées entre
deux versions sont créées avant que la moindre requête soit servie.

Pour piloter le schéma manuellement : `AUTO_MIGRATE=false` dans `.env`.


## Mise en production derrière Apache 2.4

```bash
sudo ./deploy.sh --domain exemple.com --email admin@exemple.com
```

Le script installe Apache et ses modules, crée le service systemd, écrit le
VirtualHost, obtient le certificat Let's Encrypt, met à jour le `.env`, puis
vérifie que `/health` répond. Options : `--no-ssl` (HTTP seul, tests),
`--port`, `--user`.

### Points de configuration spécifiques à cette application

| Réglage | Pourquoi |
|---|---|
| `ProxyTimeout 600` / `Timeout 600` | Une génération d'idées ou de média par IA dépasse souvent 2 minutes. Le défaut Apache (60 s) coupe la requête et renvoie 504 alors que la génération aboutit côté serveur. |
| `RemoteIPHeader` + `X-Real-IP` | L'anti-brute-force verrouille par couple (email, IP). Sans ces en-têtes, toutes les tentatives seraient comptées sur `127.0.0.1` : un seul utilisateur bloquerait tout le monde. |
| `Alias /static/` + `ProxyPass /static/ !` | CSS et JS servis directement par Apache, sans passer par uvicorn. |
| `LimitRequestBody 64 Mo` | Import d'images et scénarios vidéo. |
| `--proxy-headers --forwarded-allow-ips 127.0.0.1` | uvicorn n'accepte les en-têtes de transfert que depuis Apache. |
| `--workers 1` | Le scheduler (worker de génération, crons) tourne dans le process. Avec N workers, les crons s'exécuteraient N fois par minute. |

### Après le déploiement

`deploy.sh` renseigne automatiquement `APP_BASE_URL`, `SESSION_COOKIE_SECURE`
et `ENV=production` dans le `.env`.

Reste à faire manuellement dans la console Meta — les URI doivent être
déclarées **à l'identique** :

```
https://exemple.com/app/networks/facebook/callback
https://exemple.com/app/networks/instagram/callback
```

puis la même URL publique dans l'écran d'administration « Configuration Meta ».

### Exploitation

```bash
systemctl status post-generator
journalctl -u post-generator -f
systemctl restart post-generator
tail -f /var/log/apache2/post-generator-error.log
```

### Scaler l'API

Le scheduler doit rester unique. Déclarer deux services :

- `post-generator-api` : `--workers 4` avec `DISABLE_SCHEDULER=1`
- `post-generator-worker` : `--workers 1`, scheduler actif

Le verrouillage SQL (`FOR UPDATE SKIP LOCKED`) garantit de toute façon
qu'aucune tâche n'est traitée deux fois.


## Mise en production derrière un reverse proxy existant

### Faut-il installer Apache sur la VM ?

**Non**, si un nginx (ou Apache) frontal pointe déjà vers l'IP de la VM.
Deux reverse proxies en cascade n'apportent rien et compliquent la
transmission de l'IP réelle du client. La topologie correcte est :

```
Internet  →  nginx frontal (TLS)  →  VM Ubuntu:8000 (uvicorn)
```

La VM n'a besoin que d'uvicorn, lancé comme service systemd.

### Sur la VM

```bash
sudo ./deploy/setup.sh --proxy-ip 192.168.1.10 --url https://post.example.com
```

Le script :
1. écrit `APP_BASE_URL` dans `.env` (utilisé par les callbacks OAuth et les
   liens des emails) et aligne `SESSION_COOKIE_SECURE` sur le schéma de l'URL ;
2. installe et démarre le service systemd, avec `--forwarded-allow-ips` réglé
   sur l'IP du frontal ;
3. restreint le port 8000 au seul serveur frontal via ufw ;
4. vérifie que `/health` répond, et rappelle les URI à déclarer côté Meta.

### Sur le serveur frontal

Modèle complet dans `deploy/nginx-frontend.conf`. L'essentiel :

```nginx
upstream post_generator { server 192.168.1.50:8000; }

location / {
    proxy_pass http://post_generator;
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 300s;   # génération IA et rendu vidéo
    client_max_body_size 100M;
}
```

### Trois points à ne pas manquer

| Réglage | Pourquoi |
|---|---|
| `X-Forwarded-For` / `X-Real-IP` côté proxy **et** `--forwarded-allow-ips=<IP du frontal>` côté uvicorn | Le verrouillage anti-brute-force s'appuie sur le couple (email, IP). Mal configuré, toutes les connexions semblent venir du frontal : un seul attaquant bloquerait tous les comptes. Ne jamais mettre `*`, cela permettrait l'usurpation d'IP. |
| `APP_BASE_URL` = URL publique HTTPS | Les callbacks OAuth Meta et les liens des emails sont construits à partir de cette valeur. Une URL interne rendrait la connexion des réseaux sociaux impossible. |
| `proxy_read_timeout 300s` | Une génération IA ou un rendu vidéo dépasse largement les 60 s par défaut : sinon un 504 tombe en pleine génération. |

Déclarer enfin dans l'app Meta les URI de redirection :
`https://post.example.com/app/networks/facebook/callback` et
`.../instagram/callback`.

### Si la VM est exposée directement (sans frontal)

Un VirtualHost Apache complet est fourni dans
`deploy/optionnel/apache-post-generator.conf` — à n'utiliser que dans ce cas.


## Propriété des fichiers

`install.sh` lancé avec `sudo` crée `venv/`, `.env` et `tmp/` en tant que
**root**, alors que l'application tourne sous un utilisateur ordinaire.
Les deux scripts reprennent désormais la propriété automatiquement, mais si
le service échoue avec :

```
PermissionError: [Errno 13] Permission denied: '.env'
```

la correction tient en une ligne :

```bash
sudo chown -R ubuntu:ubuntu /home/ubuntu/post_generator
sudo systemctl restart post-generator
```

L'application détecte ce cas au démarrage et affiche désormais le
propriétaire réel du fichier, l'utilisateur du processus et la commande
exacte à exécuter, plutôt qu'une trace pydantic illisible.


## L'email d'activation n'arrive pas

Si l'application affiche « Compte créé. Vérifie ta boîte mail », c'est que le
serveur SMTP a **accepté** le message : l'envoi a réussi, la non-réception se
joue en aval.

### Débloquer immédiatement

```bash
# Générer un lien d'activation valable 24 h
venv/bin/python tools/activation.py --link utilisateur@example.com

# Ou activer le compte directement, sans email
venv/bin/python tools/activation.py --activate utilisateur@example.com

# Voir l'état de tous les comptes
venv/bin/python tools/activation.py --list
```

### Diagnostiquer l'envoi

```bash
venv/bin/python tools/activation.py --test-mail utilisateur@example.com
sudo journalctl -u post-generator | grep -i mailer | tail -20
```

### Causes fréquentes quand le SMTP accepte mais que rien n'arrive

| Cause | Vérification |
|---|---|
| **`SMTP_FROM` non autorisé** — le cas le plus fréquent chez OVH, qui accepte le message puis le supprime sans notification | `SMTP_FROM` doit être exactement une adresse du compte SMTP, par ex. `"Post Generator <contact@votredomaine.fr>"` et non `no-reply@example.com` |
| Message classé indésirable | Vérifier le dossier spam du destinataire |
| Absence de SPF/DKIM sur le domaine expéditeur | Consulter les logs de rejet du fournisseur |
| `SMTP_USER` incorrect | Chez OVH, c'est l'adresse email complète, pas un identifiant court |
