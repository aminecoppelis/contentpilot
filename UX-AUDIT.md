# Audit UX/UI — plateforme de contenu social

Date : 6 novembre 2026. Plan validé par l’utilisateur le même jour ; réalisation progressive suivie dans `UX-CHANGELOG.md`.

## Périmètre et limites

Revue des routes, templates, styles, scripts, intégrations et tests existants, complétée par les captures de la conversation. Il s’agit d’un audit du code et des parcours décrits, pas d’une recette visuelle en navigateur. Les contrastes, débordements, interactions tactiles et erreurs console devront être mesurés lors de chaque lot. Aucune conformité WCAG AA n’est affirmée à ce stade.

Aucun code applicatif n’est modifié dans cette étape. Les changements déjà présents dans le workspace sont conservés ; ils ne constituent pas une refonte validée par ce document.

## Écrans recensés

| Écran / route | Rôle actuel |
| --- | --- |
| Connexion, inscription, activation (`/app/login`, `/register`, `/activate`) | Accès et activation du compte. |
| Accueil (`/app/dashboard`) | Compteurs, publications futures, éléments à vérifier, exécutions automatiques et graphiques. |
| Stratégies (`/app/strategies`) | Liste filtrable ; création et suivi des stratégies. |
| Nouvelle stratégie (`/app/strategies/new`) | Compte, objectifs, durée, instructions et génération IA. |
| Fiche stratégie (`/app/strategies?strategy_id=…`) | Synthèse, actions, posts associés et calendrier intégré. |
| Posts (`/app/posts`) | Liste des sujets et contenus ; origine, validation et publication. |
| Nouveau contenu (`/app/posts/new`) | Brief de génération : sujet, formats, audience, objectifs et médias. |
| Consultation (`/app/posts/view`) | Écriture, médias, aperçu et préparation de la publication. |
| Édition et variantes (`/app/posts/edit`, `/posts/ideas-page`) | Modification et génération de variantes ; parcours secondaires à rationaliser. |
| Historique (`/app/history`) | Historique des idées et statuts, distinct de la liste des sujets. |
| Publications (`/app/published`) | Envois programmés, publiés, en attente, annulés et en échec. |
| Calendrier de stratégie | Scheduler commun aux actions et aux publications. `/app/publication-calendar` redirige vers la stratégie. |
| Médias d’un post (`/app/posts/idea-media` et section médias) | Import local, génération IA, recherche Pixabay, sélection et suppression. |
| Comptes connectés (`/app/networks`) | Connexion Buffer, comptes partagés, quotas et gestion des connexions. |
| Mon compte (`/app/account`) | Profil, langue/fuseau et macaron de marque. |
| Workspace (`/app/workspace`) | Membres, invitations et gestion de l’espace actif. |
| Administration (`/app/admin/*`, configuration Meta) | Utilisateurs, configuration, diagnostics et configuration technique, selon les droits. |
| Erreurs et dialogues transverses | Accès refusé, ressources absentes, confirmations, publication et connexion. |

Pas de page d’analyses sociales transverse ni de bibliothèque médias globale identifiée. Les fonctionnalités médias actuelles sont liées aux posts. Les appels de profil/Meta existants ne démontrent pas la présence d’un historique complet de portée, engagement ou abonnés.

## Stack et Syncfusion existants

- Backend : Python, FastAPI, Jinja2, asyncpg/PostgreSQL. Frontend : JavaScript natif ; pas de framework React/Angular/Vue ou Blazor identifié.
- Syncfusion **Essential JS 2, distribution JavaScript globale, 35.1.37**, chargée par CDN dans `templates/base.html`. Thème `bootstrap5.3`, licence enregistrée depuis la configuration. Aucune mise à jour proposée.
- Composants réellement initialisés : **Grid**, **Schedule**, **Stepper**, **Chart** et **AccumulationChart**. Sidebar, menus, dialogues, formulaires et skeletons restent principalement personnalisés ou natifs.
- Grids : filtrage, tri, recherche, pagination, colonnes et préférences en base. Scheduler : dates localisées et déplacement contrôlé. Charts : historique des publications et répartition des envois.
- Charte de référence : tokens de `static/css/ui-kit.css`, bleu de marque `#3b82f6`, typographie `--ui-font`, logos et icônes actuels. Certains styles anciens de pages contiennent encore des couleurs et dimensions concurrentes.

## Constats et priorités

| Impact | Constat vérifiable | Amélioration proposée |
| --- | --- | --- |
| Fort | « Posts », sujets, idées, variantes et envois se superposent ; `/published` contient aussi les envois futurs et échoués. | Stabiliser le vocabulaire : contenu → variantes → validation → envoi. Présenter les états de publication séparément de la validation. |
| Fort | Une date d’exécution crée un contenu ; une date de publication l’envoie. Le même calendrier porte ces deux événements. | Conserver des types explicites, filtres et légendes ; rendre l’effet d’un déplacement visible avant confirmation. |
| Fort | Le dashboard a récemment mélangé passé/futur et erreurs de stratégie avec publications. La correction existe, mais ses destinations doivent rester cohérentes. | Prioriser publications futures et problèmes identifiés. Vérifier que le clic d’un compteur retrouve exactement son périmètre, notamment les envois programmés en retard. |
| Fort | `ui-kit.css`, styles de pages, styles inline, règles globales et nombreux `!important` se superposent ; limites de largeur contradictoires constatées. | Consolider les conteneurs et adapter les composants Syncfusion aux tokens existants, sans recoloration ni changement de typographie. |
| Fort | Formulaire de génération long ; préférences avancées visibles dès le début. Éditeur avec variantes, validations, médias et nombreux dialogues. | Brief minimal puis options avancées repliables ; un objectif par étape ; conserver sauvegarde, aperçu et actions de publication explicites. |
| Fort | Aperçus sociaux avec compteurs illustratifs codés en dur (likes/commentaires). | Retirer ces chiffres ou signaler explicitement la simulation ; ne jamais les présenter comme des mesures réelles. |
| Moyen | Deux recherches visibles dans les listes Posts/Stratégies : formulaire de page et Search du Grid. | Une recherche visible avec un périmètre clair ; migrer les préférences sans laisser de recherche cachée active. |
| Moyen | Certains boutons font 28–32 px, des textes 9–11 px ; navigation dense sur mobile. | Agrandir les cibles tactiles, hiérarchiser les colonnes et tester zoom, clavier et RTL. Mesurer les contrastes des textes secondaires et des boutons. |
| Moyen | Des labels de formulaires ne sont pas reliés explicitement aux champs ; les dialogues n’ont pas tous le même traitement du focus. | Associer labels/erreurs/champs ; harmoniser focus initial, Échap et retour au déclencheur, via Dialog lorsque pertinent. |
| Moyen | La topbar propose le workspace, pas une recherche globale ni un sélecteur de profil social. La cloche affiche un état vide statique. | Action Créer persistante ; distinguer workspace et compte social. Ne pas simuler un système de notifications inexistant. |
| Moyen | En mode Grid, certaines listes chargent toutes les lignes avant pagination côté navigateur. | Mesurer la volumétrie ; prévoir pagination distante puis virtualisation si adaptée aux hauteurs de lignes et aux actions. Ce lot touche les contrats de données et doit être validé. |
| Faible | Retours de page présents, mais pas de fil d’Ariane homogène ; états vides et rayons variables. | Breadcrumb et composants partagés pour titres, états vides, badges et feedback. |

Le thème actuel déclare `color-scheme: light`. Un mode sombre complet n’est pas inclus dans le premier lot : il nécessiterait une validation spécifique de la charte.

## Architecture proposée

Navigation : **Tableau de bord · Création de contenu · Stratégies · Calendrier · Analyses · Médias · Comptes connectés · Paramètres**, avec administration conditionnée aux droits. Les sections Analyses et Médias ne deviennent accessibles que lorsqu’un véritable écran fonctionnel existe.

La topbar distingue le workspace du compte social, accueille une action principale persistante « Créer un post » et un Breadcrumb. La recherche globale sera ajoutée après définition de son périmètre et des autorisations, sans réutiliser abusivement une recherche locale.

Le Calendrier demande une décision : la demande antérieure imposait son intégration dans la stratégie, alors que la nouvelle mission demande une entrée principale. Par défaut, conserver le Scheduler intégré ; une entrée globale regroupant les stratégies ne sera créée qu’après validation.

Parcours cible : **brief minimal → génération et variantes → édition avec aperçu → vérification du compte et du média → publier maintenant ou programmer → confirmation et statut réel**. Les changements d’écran ne doivent jamais déclencher un envoi.

## Plan de réalisation à valider

| Lot / commit prévu | Contenu | Syncfusion prioritaire | Vérifications |
| --- | --- | --- | --- |
| 0 — `docs: audit UX et plan` | Présent audit, vocabulaire et décisions. | Inventaire seulement. | Validation utilisateur. |
| 1 — `ui: socle de navigation et thème` | Tokens existants, conteneurs, topbar, CTA, navigation mobile et Breadcrumb. Migration progressive des contrôles. | Sidebar, Toolbar, Breadcrumb ; Menu si nécessaire. | Logo/polices/couleurs inchangés ; rôles, workspace, clavier, RTL et mobile. |
| 2 — `ui: dashboard orienté publication` | Prochaines publications, anomalies identifiées, résumé réel et états vides utiles ; graphiques secondaires. | Dashboard Layout, Charts ; Sparklines uniquement avec historique disponible. | Dates passées/futures, fuseaux, données vides, clics cohérents. Réorganisation des panneaux via un mode explicite, sans gêner les liens. |
| 3 — `ui: création guidée et aperçu` | Formulaire simplifié, paramètres avancés, variantes et aperçu adaptés à la largeur ; actions finales hiérarchisées. | Stepper existant, Accordion, MultiSelect, Uploader, Dialog. | Sauvegarde et payloads identiques, erreurs récupérables, aucun envoi automatique. |
| 4 — `ui: calendrier et comptes` | Scheduler lisible, types distincts, connexion/reconnexion explicite et compte sélectionné visible. | Schedule, DateTimePicker, Tooltip, Message. | Drag & drop, éléments non modifiables, concurrence, Buffer et droits. Création rapide seulement après validation du parcours. |
| 5 — `ui: listes et bibliothèque` | Recherche unique, filtres visibles, préférences conservées, médias réutilisables selon périmètre validé. | Grid, Chips, Uploader, Dialog. | Filtres/sélections/export/données sensibles ; performances avant migration distante. |
| 6 — `ui: analyses réelles` | Mesures sociales, variations, top contenus, horaires et recommandations, après validation des sources. | Charts, HeatMap, Grid et exports utiles. | Provenance, fraîcheur, périodes comparables, métriques indisponibles jamais remplacées par des chiffres inventés. |

Rich Text Editor et Image Editor ne seront ajoutés qu’en cas de besoin validé : remplacer l’éditeur actuel peut modifier la sérialisation et la fidélité du texte envoyé. Kanban, AI AssistView et Smart Paste restent optionnels ; leur utilité et leur disponibilité dans la version conservée doivent être confirmées avant engagement.

## Recette et gestion des changements

Un commit limité par lot, sans embarquer les modifications préexistantes non liées. Si un lot révèle un changement métier nécessaire, le séparer et demander validation avant de l’appliquer.

À chaque page : validation Python/Jinja, tests ciblés des interactions et des contrats, contrôles console et réseau en navigateur, captures desktop/tablette/mobile, parcours clavier/RTL et vérification visuelle de la charte. Pas de commande frontend de build à inventer : l’application actuelle utilise des assets JavaScript/CSS sans bundler identifié.

Scénarios critiques : texte non sauvegardé, génération échouée, upload interrompu, compte expiré, changement de workspace, annulation de publication, replanification en conflit, fuseaux/DST, données vides et panne du CDN. Les appels Buffer/IA ne sont pas déclenchés pour une simple recette visuelle.

## Décisions demandées

1. Valider le plan et commencer par le socle, puis Dashboard et Création.
2. Calendrier : conserver uniquement la vue intégrée ou autoriser une vue éditoriale globale en complément ?
3. Analyses : quelles données réelles et autorisations sont disponibles pour portée, engagement et abonnés ? À défaut, garder les statistiques de publication actuelles et reporter les recommandations d’horaires.

## Références techniques

- Code : `templates/base.html`, `app/templating.py`, `static/css/ui-kit.css`, `static/js/syncfusion-grid.js`, `static/js/publication-calendar.js`, `static/js/post-flow.js`, `app/services/dashboard_metrics.py`, routes et templates des pages recensées.
- [Dashboard Layout JavaScript global — documentation officielle](https://ej2.syncfusion.com/javascript/documentation/dashboard-layout/es5-getting-started).
- [Virtualisation du Grid — documentation officielle et limites de hauteur de ligne](https://ej2.syncfusion.com/javascript/documentation/grid/scrolling/virtual-scrolling).

Les exemples de documentation devront être adaptés à **35.1.37**, sans recopier leurs versions CDN éventuelles ni modifier la licence du projet.
