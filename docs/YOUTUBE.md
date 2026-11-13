# Publication YouTube dans Coppelis

## Configuration serveur

Renseigner sur l'API et les workers :

```dotenv
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=https://socialnetwork.coppelis.com/app/networks/youtube/callback
TOKEN_ENCRYPTION_KEY=
YOUTUBE_CHUNK_BYTES=8388608
MEDIA_VIDEO_UPLOAD_MAX_BYTES=2147483648
```

Les deux dernières valeurs sont facultatives : blocs de 8 Mio et import vidéo limité à 2 Gio par défaut. Les blocs sont alignés sur 256 Kio, plafonnés à 32 Mio. L'import depuis le PC écrit la vidéo progressivement sur disque. Ajuster aussi la limite du reverse proxy (`client_max_body_size` sous Nginx), les délais d'import et l'espace disque disponible.

`TOKEN_ENCRYPTION_KEY` est une clé Fernet stable, identique pour tous les processus. Conserver la clé existante si elle est déjà configurée : la changer sans migration rend les anciens jetons illisibles. Pour une première configuration, générer une clé avec `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`, puis la conserver dans le gestionnaire de secrets du déploiement. Ne pas la committer. YouTube refuse de se connecter sans clé explicite.

Si des comptes existants utilisaient le repli de développement sans `TOKEN_ENCRYPTION_KEY`, leurs jetons doivent être réenregistrés avec la clé explicite avant de basculer ce réglage. Ne pas remplacer une clé de production ou activer une nouvelle clé sur ces comptes sans préparer cette transition.

Le secret OAuth et les jetons ne sont jamais envoyés aux composants frontend. Access token et refresh token sont stockés ensemble dans l'enveloppe Fernet `app_social_accounts.token_ciphertext`. La session d'upload reprenable est également chiffrée. Les données visibles de progression ne contiennent que le statut, les octets confirmés et le résultat vidéo.

Redémarrer l'application : la migration additive `015_youtube.sql` est appliquée par le mécanisme existant si `AUTO_MIGRATE=true`. Sinon, appliquer ce fichier avec le processus SQL habituel avant de démarrer cette version. Aucun changement de schéma n'a été appliqué à la production pendant le développement. Garder le scheduler actif (`DISABLE_SCHEDULER=false`) sur au moins une instance. Le worker partagé traite un envoi à la fois, avec réveil chaque minute. API et worker doivent voir le même stockage `MEDIA_STORAGE_DIR`, persistant entre les redémarrages.

## Google Cloud Console

1. Sur le projet du client OAuth existant, activer **YouTube Data API v3**.
2. Dans le client OAuth de type **Application Web**, autoriser exactement `https://socialnetwork.coppelis.com/app/networks/youtube/callback`. Pour le développement, ajouter une URI distincte et la mettre dans `GOOGLE_REDIRECT_URI` de cet environnement.
3. Configurer l'écran de consentement Google Auth Platform : nom Coppelis, domaine, contacts et politique de confidentialité. Ajouter les comptes de test si l'application est en mode test ; effectuer la vérification Google requise avant ouverture aux clients.
4. Déclarer les scopes `https://www.googleapis.com/auth/youtube.upload` et `https://www.googleapis.com/auth/youtube.readonly`. Le premier sert à `videos.insert`. La lecture additionnelle permet de récupérer et vérifier la chaîne par `channels.list(mine=true)` ; aucune permission de suppression de vidéos n'est demandée.
5. Vérifier les quotas et les éventuelles exigences de conformité affichées pour ce projet. L'application affiche la visibilité renvoyée par Google dans le résultat enregistré ; elle ne contourne aucune restriction du projet.

Références officielles : [OAuth serveur et accès hors ligne](https://developers.google.com/identity/protocols/oauth2/web-server), [channels.list](https://developers.google.com/youtube/data/reference/rest/v3/channels/list), [videos.insert](https://developers.google.com/youtube/data/reference/rest/v3/videos/insert), [protocole resumable](https://developers.google.com/youtube/data/guides/using_resumable_upload_protocol).

## Première publication réelle

1. Se connecter à Coppelis et sélectionner l'entreprise concernée.
2. Ouvrir **Mes réseaux → Connecter YouTube**. Choisir le compte ou la chaîne Google voulue et accorder les deux autorisations. Le callback ne valide la connexion qu'après réception des jetons hors ligne et lecture de la chaîne. Un refus ou une absence de chaîne affiche une erreur.
3. Ouvrir un post, importer ou générer une vidéo puis la sélectionner dans la galerie.
4. Dans la fenêtre de publication, choisir la chaîne **YouTube Vidéo** ou **YouTube Short**. Un seul format peut être choisi par chaîne pour cet envoi. Renseigner le titre, la description, les tags séparés par des virgules, la visibilité et le public enfant ou non. Commencer par une vidéo privée courte pour ce premier essai.
5. Choisir publication immédiate ou date future. La programmation est locale : l'envoi commence à l'échéance, pas avant. La date est donc le début de l'envoi ; le transfert et le traitement YouTube peuvent retarder la disponibilité effective.
6. Suivre les octets confirmés par Google dans le post. Une mise en file n'est jamais une confirmation de publication. L'identifiant et le lien vidéo sont enregistrés seulement après confirmation finale de `videos.insert`. Le traitement vidéo peut ensuite continuer chez YouTube. Retrouver le lien et le statut dans **Posts publiés**.

Les Shorts utilisent le même `videos.insert`. Le format choisi décrit l'intention de publication ; YouTube décide du classement selon les caractéristiques du fichier. Choisir un fichier vertical ou carré respectant ses critères actuels. Le code ne fabrique pas de statut « Short confirmé ».

## Reprise, isolation et déconnexion

- Chaque connexion est propre au workspace. Même chaîne autorisée dans deux entreprises : deux enregistrements et deux autorisations locales distinctes. Le partage d'une connexion YouTube entre workspaces est refusé côté serveur, y compris si un ancien lien de partage existe.
- Le state OAuth est haché, valable dix minutes, consommé atomiquement et lié à l'utilisateur, au workspace actif et à la session navigateur. Changer d'entreprise pendant l'autorisation impose de recommencer.
- Le worker renouvelle les access tokens avec le refresh token, sous verrou SQL. Si Google refuse le renouvellement, la publication échoue avec une invitation à reconnecter la chaîne.
- En cas de perte réseau, la reprise interroge Google pour retrouver les octets réellement reçus. Après redémarrage, un traitement inactif depuis quinze minutes peut être repris avec sa session sauvegardée. Une session expirée échoue explicitement ; aucune nouvelle session n'est créée automatiquement, pour éviter les doublons. Vérifier YouTube Studio avant une nouvelle tentative manuelle.
- Un double clic ou une répétition HTTP ne peut pas créer deux envois actifs pour le même post et la même chaîne. Les erreurs de quota restent visibles et ne sont pas transformées en succès.
- **Mes réseaux → menu de la chaîne → Déconnecter et révoquer Google** appelle Google, retire les jetons locaux et désactive le compte. Si Google ne confirme pas la révocation, le retrait ne prétend pas avoir réussi. Une révocation Google peut affecter les autres autorisations du même compte Google pour le même client OAuth ; les reconnexions éventuelles restent propres à chaque entreprise.

## Vérification

Installer les dépendances de test avec `python -m pip install -r requirements-dev.txt`. `venv/Scripts/python.exe -m pytest -q` exécute les tests Python. `node tests/youtube_publication_dom.cjs` exerce le formulaire avec jsdom ; il nécessite les dépendances jsdom du cache de tests existant. Ces tests utilisent des réponses HTTP contrôlées, sans OAuth réel ni upload réel. Une recette avec la chaîne Google du propriétaire reste nécessaire après configuration et déploiement ; aucune connexion ou publication réelle n'a été effectuée au développement.

Résultat de livraison : 97 tests Python réussis (34 sous-tests supplémentaires), plus les tests DOM YouTube, Instagram et sélection des médias. La migration SQL est livrée pour le mécanisme de démarrage ; elle n'a pas été exécutée sur la base de production pendant cette intervention.

## Fichiers livrés

Créés :

- `app/routers/youtube.py`
- `app/services/youtube.py`
- `migrations/015_youtube.sql`
- `tests/test_youtube.py`
- `tests/youtube_publication_dom.cjs`
- `requirements-dev.txt`
- `docs/YOUTUBE.md`

Modifiés :

- `.env.example`, `app/config.py`, `app/main.py`
- `app/routers/listing.py`, `app/routers/media.py`, `app/routers/networks.py`, `app/routers/posts.py`, `app/routers/publish.py`
- `app/services/publishing.py`, `app/services/social_accounts.py`, `app/worker/publication_cron.py`
- `static/js/consultation.js`, `static/css/consultation.css`
- `templates/networks/list.html`, `templates/networks/_account_rows.html`, `templates/partials/network_badges.html`
- `templates/posts/view.html`, `templates/posts/_view_modals.html`, `templates/posts/_published_rows.html`
- `translations/fr.json`, `translations/en.json`, `translations/de.json`, `translations/es.json`, `translations/it.json`, `translations/ru.json`, `translations/ar.json`
- `tests/test_media_upload.py`, `tests/test_post_publication_status.py`, `UX-CHANGELOG.md`
