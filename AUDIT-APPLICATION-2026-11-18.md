# Audit de Coppelis — 18 novembre 2026

## Décision recommandée

Consolider la fiabilité des publications et clarifier le parcours avant d'ajouter d'autres réseaux. Ensuite, développer une médiathèque commune à l'entreprise, une validation collaborative et un profil de marque réutilisable. Les analyses sociales réelles viennent après, une fois leurs sources et permissions vérifiées.

Cet audit complète `UX-AUDIT.md` du 6 novembre ; ses constats ne sont pas tous encore actuels. Les améliorations déjà réalisées ne sont pas reproposées comme des nouveautés.

## Méthode et limites

- Revue des routes, services, workers, migrations, templates, scripts et tests du dépôt courant.
- Exécution locale de `venv/Scripts/python.exe -m pytest -q` : **97 tests réussis**, 34 sous-tests supplémentaires ; un avertissement de dépréciation Starlette/AnyIO.
- Reproduction locale, sans réseau ni base, d'un calcul incorrect du statut publié après une exception sans message.
- Aucun envoi réel, connexion OAuth réelle, appel IA payant, démarrage du scheduler, modification de données ou scan de la VM de production.
- Pas de recette visuelle en navigateur, de test d'accessibilité instrumenté, de mesure de charge ni de pentest. Les constats du code sont séparés des risques à confirmer en environnement.
- Aucune lecture de secrets nécessaire à cette revue ; aucune valeur confidentielle dans ce rapport.

Le passage des tests actuels ne garantit donc pas l'absence des défauts ci-dessous. La reproduction du statut erroné montre notamment une lacune de couverture.

## Ce qui est déjà disponible et à conserver

| Domaine | Fonctionnalités constatées |
| --- | --- |
| Organisation | Workspaces, membres, invitations, sélection de l'entreprise active et accès aux comptes sociaux selon le workspace. |
| Production de contenus | Brief IA, domaines/audiences/formats, variantes, modification du texte, sauvegarde et états de validation. |
| Stratégie | Génération de stratégies, actions et contenus associés, calendrier intégré distinguant actions et publications. |
| Médias | Import PC, génération image/vidéo, Pixabay, sélection explicite du média et macaron configurable. |
| Publication | Destinations Meta et Buffer, connexion YouTube, programmation locale et historique des envois. Les capacités varient selon le fournisseur. |
| YouTube | OAuth lié à la session et au workspace, jetons chiffrés, refresh, révocation, vidéo/Short, upload reprenable et progression confirmée. Le classement Short reste décidé par YouTube. |
| Interface | Grids, préférences de tableaux en base, Scheduler, graphiques de publications, Accordion, Toolbar/Stepper et sept langues. |
| Fiabilité existante | Migrations au démarrage, verrous de certains jobs, tests de sélection des médias et de reprise YouTube. |

Le dashboard mesure l'activité de publication de Coppelis. Ses compteurs ne constituent pas une mesure de portée, d'engagement ou de conversion sur les réseaux.

## Corrections prioritaires, avec preuves

P0 : corriger en premier, car l'information métier peut être fausse. P1 : traiter avant élargissement important de l'usage. P2 : amélioration à planifier selon la volumétrie et les retours utilisateurs.

### A01 — P0 — Une publication immédiate peut être marquée publiée après une erreur

**Constat confirmé par reproduction locale.** Dans `app/routers/publish.py`, une exception de l'envoi immédiat devient `{"error": str(exc)}`. `outcome_error()` dans `app/services/publishing.py:267` traite une chaîne vide comme une absence d'erreur. Le statut est alors calculé à `published`.

Reproduction inoffensive : `outcome_error({"error": str(ValueError())})` renvoie `None`. C'est une preuve du chemin de calcul, pas la preuve qu'une publication réelle a rencontré ce cas en production.

Le même normalisateur ne valide pas à lui seul un code HTTP d'échec ou une confirmation fournisseur absente. Certaines branches vérifient déjà ces éléments ; Facebook et les réponses atypiques doivent être couverts explicitement. Le worker a une protection contre les exceptions vides et une vérification supplémentaire pour YouTube ; le parcours immédiat reste différent.

**Correction :** résultat de publication commun distinguant accepté, en traitement, confirmé et échec ; message de secours non vide ; validation de la confirmation adaptée à chaque fournisseur. Un code HTTP ou un JSON sans erreur explicite ne doit pas suffire à déclarer un succès.

**Acceptation :** exceptions vides, erreur HTTP, JSON vide, réponse incomplète et succès fournisseur passent les tests de toutes les branches, sans faux publié.

### A02 — P1 — Reprise et protection contre les doublons inégales selon les réseaux

**Constat du code.** Les envois immédiats hors YouTube s'effectuent dans la requête HTTP (`app/routers/publish.py`). Le worker ne reprend les lignes `processing` devenues anciennes que pour YouTube (`app/worker/publication_cron.py:55`). L'index anti-doublon actif de `migrations/015_youtube.sql` est également spécifique à YouTube.

Une réponse réseau perdue ou un arrêt entre l'envoi distant et l'enregistrement local peut laisser un état ambigu. Relancer aveuglément peut dupliquer un contenu ; l'absence d'idempotence uniforme ne prouve pas que tous les fournisseurs vont effectivement le dupliquer.

**Correction :** utiliser la même file durable pour les publications immédiates et programmées ; identifiant d'opération stable, confirmation distante persistée et traitement explicite des états inconnus. Ne pas réessayer automatiquement une opération dont le succès distant est incertain.

**Acceptation :** redémarrage, double clic et réponse perdue ne produisent pas un second envoi automatique ; l'utilisateur voit « vérification nécessaire » si le résultat distant n'est pas déterminable.

### A03 — P1 — Suppression d'historique et annulation doivent être deux actions distinctes

**Constat du code.** `/published/delete-bulk` supprime directement des lignes de `post_publications` sans filtre sur leur statut (`app/routers/listing.py:280`). Une suppression locale ne révoque pas une requête déjà partie chez un fournisseur. La suppression d'un sujet possède un traitement d'annulation plus riche dans `app/routers/posts.py:679`.

**Correction :** « Annuler la programmation » pour un envoi futur, action contrôlée pour un traitement en cours, puis « Archiver l'historique » pour une trace terminée. Expliquer séparément la suppression sur un réseau social. Prévoir un nettoyage des données de test limité à un workspace, avec aperçu du périmètre.

**Acceptation :** aucune action ne promet d'annuler un appel externe déjà engagé ; une ligne en cours n'est pas effacée silencieusement avec son suivi.

### A04 — P1 — Téléchargements d'URL à encadrer côté serveur

**Risque identifié dans le code, exploitation non testée.** L'import média authentifié accepte des URL HTTP(S), puis `_image_bytes()` télécharge avec suivi des redirections (`app/routers/media.py:183,592`). Aucun filtrage des destinations réseau privées ou locales n'est visible dans ce chemin. Les téléchargements distants ne présentent pas tous les mêmes bornes que l'import de fichiers PC.

**Correction :** service de téléchargement partagé, validation des destinations IPv4/IPv6 et de chaque redirection, restrictions réseau sortantes, limites de taille réellement lues, délais et validation du contenu. Conserver un chemin distinct pour les images base64 autorisées. Recommandations issues du [guide SSRF OWASP](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html).

**Acceptation :** tests locaux contrôlés refusant les destinations interdites et les réponses trop volumineuses, sans requête vers le réseau interne de production.

### A05 — P1 — Les gros médias ne sont pas traités en flux partout

**Constat du code.** L'import vidéo et l'upload YouTube travaillent par blocs, mais `_load_bytes()` lit intégralement le fichier pour certains proxys (`app/routers/media_proxy.py:65`). Plusieurs accès simultanés à de grandes vidéos peuvent donc consommer beaucoup de mémoire. Les médias sont également servis via des montages statiques publics (`app/main.py`) et des proxys sans authentification pour les fournisseurs.

**Correction :** réponses fichier ou streaming avec support des requêtes partielles, limites de ressources, séparation entre aperçu privé et accès fournisseur. Évaluer des URL signées expirables compatibles avec la durée de récupération des réseaux. Une URL à UUID difficile à deviner ne fournit pas à elle seule une politique de confidentialité par entreprise.

**Acceptation :** lecture et récupération fournisseur d'une grande vidéo avec mémoire bornée ; utilisateur non autorisé refusé sur l'aperçu privé ; envoi fournisseur toujours fonctionnel.

### A06 — P1 — Durcissement de session et gestion des clés à terminer

**Constats du code, configuration de la VM non vérifiée.** La session est HttpOnly et SameSite=Lax (`app/routers/auth.py:114`). Le flag Secure est configurable et désactivé par défaut ; cela ne prouve pas qu'il est désactivé en production. Aucune protection CSRF générale par jeton ou contrôle Origin n'a été trouvée pour les formulaires de mutation. Le state OAuth YouTube est, lui, protégé séparément.

`app/services/crypto.py` conserve un repli de dérivation de clé depuis la connexion DB lorsque la clé explicite manque. YouTube exige déjà une clé explicite. Il faut une règle de production homogène et une procédure de rotation tenant compte des jetons existants.

**Correction :** garde-fous de démarrage en production, Secure activé, protection CSRF des mutations et procédure de rotation/révocation des secrets. Ne pas changer une clé existante sans migration. SameSite reste une couche utile, sans remplacer les autres protections dans la plupart des déploiements : [guide CSRF OWASP](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).

**Acceptation :** mutations inter-origines refusées, formulaires légitimes et callbacks OAuth fonctionnels, jetons anciens toujours lisibles pendant une rotation préparée.

### A07 — P1 — Les capacités des plateformes sont définies à plusieurs endroits

**Constat du code.** Formats dans `static/js/form.js` et `app/routers/posts.py`, types et médias dans `static/js/consultation.js`, validation dans `app/routers/publish.py`. L'ajout récent de YouTube à la création après son ajout à la publication illustre le risque de décalage.

**Correction :** référentiel unique des capacités par plateforme et fournisseur : formats, média requis, contraintes, programmation et champs particuliers. Générer les options UI depuis ce référentiel, tout en conservant les validations serveur.

**Acceptation :** une nouvelle capacité apparaît de manière cohérente en création, modification, génération et publication ; aucune option affichée comme disponible ne dépend seulement d'une liste JS divergente.

### A08 — P2 — Pagination côté navigateur à préparer pour la croissance

**Constat du code, lenteur non mesurée.** Avec Syncfusion activé, plusieurs listes passent une limite SQL à `None` : `app/routers/posts.py:353`, `app/routers/networks.py:145`, `app/routers/listing.py:257`, `app/routers/strategies.py:415`. La pagination visuelle n'empêche donc pas le chargement initial de toutes les lignes correspondantes.

**Correction :** mesurer puis introduire pagination, tri et filtres distants, en conservant les préférences existantes. Ne pas fixer un seuil de migration sans mesure.

**Acceptation :** tests avec 1 000 puis 10 000 éléments synthétiques ; temps et taille de réponse mesurés, requêtes bornées et filtres appliqués avant pagination.

### A09 — P2 — Internationalisation et cohérence de l'interface incomplètes

**Constat du code.** Le dialogue Pixabay contient encore des textes français en dur dans `templates/posts/_view_modals.html:336` et suivantes. Le flux de publication comporte de nombreux dialogues personnalisés ; les traitements du focus et du clavier doivent être testés, sans affirmer ici qu'ils échouent tous.

Le code frontend et les routes restent volumineux : 1 240 lignes pour `consultation.js`, 2 371 pour `ui-kit.css`, 1 542 pour `strategies.py` et 1 189 pour `posts.py` au moment de la revue. Ces tailles ne sont pas un défaut en soi ; elles augmentent le coût d'une modification transversale quand les règles sont aussi dupliquées.

**Correction :** extraire les textes restants, recette sept langues dont RTL, vérifier focus/Échap/retour au déclencheur et découper progressivement par responsabilité pendant les changements fonctionnels.

### A10 — P1 à confirmer en exploitation — Supervision et restauration

Les migrations et `/health` existent. Cela ne démontre pas que la VM supervise la file, les traitements bloqués, l'espace disque, les sauvegardes ou la restauration. Aucun accès à son infrastructure n'a été réalisé et l'absence de ces dispositifs n'est pas affirmée.

**À vérifier :** dernière exécution du worker, âge du plus ancien job, erreurs par fournisseur, occupation du stockage, sauvegarde cohérente DB + fichiers + clés, restauration sur un environnement isolé. Une sauvegarde PostgreSQL ne remplace pas celle des fichiers médias : [documentation PostgreSQL](https://www.postgresql.org/docs/current/backup.html).

## Améliorations UX à réaliser sur le parcours actuel

1. **Distinguer contenu et envoi.** Un contenu peut avoir plusieurs destinations et plusieurs résultats. Afficher le statut par compte, la date, le média figé et le lien confirmé ; ne pas résumer un succès partiel à un unique badge vert.
2. **Clarifier les deux dates.** « Créer automatiquement le contenu le… » et « Envoyer sur le réseau le… », avec légende dans le calendrier intégré aux stratégies. Pas de nouveau calendrier autonome dans le menu.
3. **Récapitulatif avant envoi.** Entreprise, chaîne/compte, format, miniature ou vidéo choisie, texte, visibilité et fuseau. Afficher les contraintes précises avant le clic final.
4. **Erreurs avec suite possible.** Reconnecter le compte, choisir un autre média, attendre un quota ou vérifier un envoi incertain. Proposer une relance seulement si elle peut être effectuée sans doublon.
5. **Nommer l'historique selon son contenu.** « Publications » ou « Suivi des envois » est plus clair que « Posts publiés » pour une page contenant aussi programmations et échecs. Les labels doivent changer dans toutes les langues.
6. **Rendre l'aide contextuelle.** Afficher pourquoi une destination est indisponible et comment la rendre disponible. La connexion Instagram sans média sélectionné possède déjà un début de ce comportement ; l'étendre uniformément.

## Fonctionnalités nouvelles à forte valeur

Les éléments ci-dessous sont des propositions produit déduites des parcours et du code, pas des demandes utilisateurs validées ni une étude de marché. L'effort est relatif : S = changement ciblé ; M = plusieurs écrans/services ; L = nouvelle persistance et intégrations ou orchestration.

| Rang | Fonctionnalité | Bénéfice concret | Extension de l'existant et limites | Effort |
| --- | --- | --- | --- | --- |
| 1 | Médiathèque par entreprise | Réutiliser une photo/vidéo sans la générer à nouveau ; retrouver ce qui a été utilisé. | Étendre les médias aujourd'hui attachés aux idées : recherche, dossiers/tags, favoris, références d'usage et conservation. Respecter les droits de l'entreprise et éviter la suppression d'un fichier référencé. | M/L |
| 2 | Validation collaborative assignée | Un rédacteur prépare, un responsable commente et valide la version destinée à partir. | Les états de validation existent déjà ; ajouter relecteur assigné, commentaires, rôles explicites et validation liée à une version. Une modification après validation doit rouvrir la validation. | M/L |
| 3 | Profil de marque par entreprise | Éviter de ressaisir entreprise, audience, ton, offres et liens ; rendre les contenus plus cohérents. | Réutiliser les champs actuels du brief et le macaron. Ajouter éléments approuvés, expressions à éviter et références, avec aperçu des informations envoyées à l'IA. | M |
| 4 | Notifications utiles | Savoir qu'un envoi a échoué ou qu'une validation attend une action. | La cloche de `templates/base.html:191` affiche actuellement un état vide statique. Alimenter un vrai fil, avec liens vers les objets et préférences ; commencer par les événements critiques. | M |
| 5 | Déclinaison d'un contenu par réseau | Transformer un sujet en variantes adaptées, sans recopier manuellement texte et médias. | Les variantes existent ; ajouter une relation explicite entre versions par destination et leurs contraintes. Montrer les différences, ne pas réutiliser silencieusement une légende incompatible. | M |
| 6 | Suivi des consommations IA | Comprendre les générations qui consomment le budget et fixer un plafond par entreprise. | Des réponses IA exposent `usage` dans `app/services/ai.py`, mais aucun registre financier complet n'a été identifié. Journaliser les consommations disponibles ; indiquer « coût indisponible » si le fournisseur ne le fournit pas. | M/L |
| 7 | Analyses sociales réelles et rapport client | Identifier les contenus utiles et préparer un bilan périodique. | Commencer par un réseau et un petit jeu de métriques vérifiées. Ajouter collecte, historique, date de fraîcheur et export. Les API, permissions et métriques disponibles doivent être vérifiées avant engagement. Ne pas présenter les scores IA comme des performances mesurées. | L |
| 8 | Modèles réutilisables de campagne | Reprendre une structure éditoriale qui fonctionne sans recommencer un brief complet. | Dupliquer brief/structure et paramètres, en demandant explicitement de nouvelles dates et de nouveaux envois ; jamais recopier des publications actives automatiquement. | M |

## Plan de livraison recommandé

| Lot | Contenu | Critère de sortie |
| --- | --- | --- |
| 1 — Confiance dans l'envoi | A01, A02, A03 ; tests immédiat/programmé, erreurs et réponses perdues. | Aucun faux publié ; état incertain explicite ; annulation distincte de l'effacement d'historique. |
| 2 — Production et sécurité | A04, A05, A06 et vérification A10. | Téléchargements bornés, politique d'accès aux médias, protection des mutations et restauration démontrée. |
| 3 — Parcours cohérent | A07 et récapitulatif avant envoi ; internationalisation prioritaire. | Même capacité proposée à toutes les étapes et compréhension des deux dates. |
| 4 — Usage quotidien en équipe | Médiathèque + profil de marque, puis validation assignée et notifications. | Un testeur peut réutiliser un média et faire valider une version sans assistance. |
| 5 — Pilotage | Consommations IA, analyses d'un premier réseau et rapport client ; pagination distante selon mesures. | Métriques traçables, coûts jamais inventés et listes mesurées sous charge. |

Ne pas estimer un calendrier ferme avant un découpage technique et la confirmation du nombre d'utilisateurs, des volumes médias et des droits de publication attendus. Éviter d'ajouter maintenant plusieurs nouveaux réseaux, un éditeur vidéo complet ou une publication autonome sans contrôle : ces ajouts augmenteraient les surfaces à fiabiliser avant de résoudre les problèmes de confiance existants.

## Recette réelle à prévoir après les corrections

- Entreprise A/B : comptes, médias, jobs, préférences, historique et liens refusés hors périmètre autorisé.
- Même contenu envoyé vers deux comptes : succès partiel lisible et relance limitée à la cible concernée.
- Choix de média, génération simultanée, rafraîchissement et copie enregistrée pour l'envoi cohérents.
- Exception vide, timeout avant/après acceptation distante, fermeture de page et redémarrage du worker.
- Annulation future, traitement déjà engagé et archivage d'un envoi terminé.
- Programmation autour d'un changement d'heure et affichage du fuseau sur confirmation et historique.
- Google révoqué, accès expiré, upload YouTube interrompu et traitement vidéo encore en cours après réception.
- Clavier, focus des dialogues, zoom 200 %, mobile et interface arabe RTL.
- Listes volumineuses, lecture vidéo simultanée et espace disque insuffisant.
- Restauration isolée de la DB, des fichiers et des clés avant toute suppression de sauvegarde.

## Mesure du bénéfice

Suivre le temps entre brief et programmation, les abandons par étape, les erreurs par fournisseur, les états bloqués, les doublons confirmés, le taux de réutilisation des médias et le temps de validation. Mesurer d'abord une référence sur l'usage réel, puis fixer les objectifs ; aucun gain chiffré n'est garanti par cet audit.
