# UX changelog

## 6 novembre 2026 — Étape 1 : audit, en attente de validation

- Ajout de `UX-AUDIT.md` : inventaire des écrans, stack Syncfusion, constats ergonomiques, priorités et plan par lots.
- Distinction entre statistiques de publication disponibles et analyses sociales nécessitant des sources complémentaires.
- Identification de la décision sur le calendrier global, à concilier avec la vue intégrée demandée précédemment.
- Aucun changement applicatif, de charte, de route, de schéma de données ou d’intégration effectué dans cette étape.
- Aucun composant Syncfusion ajouté ou mis à jour ; version constatée : EJ2 JavaScript 35.1.37.
- Vérifications à venir : recette visuelle en navigateur, contrastes mesurés, responsive, clavier/RTL et contrats des intégrations, après validation des lots.

Les modifications déjà présentes avant cet audit sont conservées et ne sont pas attribuées à cette étape.

## 6 novembre 2026 — Lot 1 : socle de navigation

Plan validé par l’utilisateur (« ok go »). Le calendrier reste intégré aux stratégies, conformément à la préférence antérieure ; aucune nouvelle route de calendrier global n’est créée.

- Ajout d’un fil d’Ariane partagé, calculé uniquement depuis les routes existantes, avec **Syncfusion Breadcrumb EJ2 35.1.37** et repli HTML si le SDK n’est pas disponible.
- Ajout de l’action persistante « Créer un post » et d’un lien clavier « Aller au contenu ».
- Regroupement du comportement de la sidebar dans `app-shell.js` : état desktop conservé, menu mobile, focus contenu dans le tiroir, Échap, retour du focus et contenu arrière inactif.
- Styles de shell fondés sur les tokens existants ; aucune modification des couleurs de marque, police, logo ou icônes de marque.
- Traductions des nouveaux libellés dans les sept langues. Aucun appel Buffer, IA ou endpoint métier ajouté ou changé.
- La sidebar existante est conservée pour cette première migration ; son éventuel remplacement par Sidebar EJ2 sera traité séparément pour ne pas cumuler deux moteurs de mise en page.

Fichiers principaux : `app/ui_navigation.py`, `app/templating.py`, `templates/base.html`, `templates/partials/breadcrumbs.html`, `static/css/app-shell.css`, `static/js/app-shell.js`, traductions et tests dédiés.

Vérifications : 26 tests Python ciblés réussis ; rendu du shell dans les sept langues ; test DOM avec le vrai Breadcrumb Syncfusion, repli sans SDK, clavier, focus et transitions desktop/mobile. Ces tests ne remplacent pas une recette visuelle dans un navigateur réel ; cette vérification reste à effectuer avant publication.

Suite du plan : Dashboard Layout, puis formulaire de création simplifié. Aucun écran Analyses ou Médias vide n’a été ajouté au menu.

### Correction du lot 1 — action principale unique

- Retrait du bouton « Nouveau post » dans l’en-tête du Dashboard : il doublonnait l’action permanente « Créer un post » de la topbar. Le raccourci secondaire vers les stratégies est conservé.

## 6 novembre 2026 — Lot 2 : Dashboard orienté publication

- Mise en page des quatre panneaux avec **Syncfusion Dashboard Layout EJ2 35.1.37**, tout en conservant les Charts et AccumulationChart existants.
- Ordre initial : publications à venir et éléments à vérifier, puis graphiques. Les exécutions automatiques restent dans une section distincte et repliable.
- Mode « Personnaliser » explicite : déplacement limité aux poignées, alternatives par boutons fléchés et réinitialisation. Le tableau de bord reste verrouillé hors de ce mode ; les données ne sont jamais modifiées par ces actions.
- Ordre mémorisé localement dans le navigateur, avec une clé distincte par utilisateur et workspace ; ce réglage de présentation ne prétend pas être synchronisé entre appareils.
- Conservation des nœuds DOM et de leurs écouteurs : liens de publication, sélecteur de période et panneaux détaillés restent actifs après déplacement.
- Réadaptation des graphiques lors du déplacement, du changement de largeur et du repli de la sidebar. Présentation empilée sur mobile ; grille HTML utilisable sans SDK.
- Ce lot intègre les corrections du Dashboard préparées auparavant : exclusion des dates passées des événements à venir, séparation des retards/échecs et retrait des alertes de stratégie de la carte des publications réussies.
- Aucun KPI de portée, engagement ou abonnés inventé ; les statistiques reposent sur les envois stockés dans le workspace.

Fichiers principaux : `templates/posts/dashboard.html`, `templates/posts/_dashboard_attention.html`, `static/js/dashboard-layout.js`, `static/js/dashboard.js`, `static/css/dashboard.css`, `app/services/dashboard_metrics.py`, route Dashboard, contexte de templates, traductions et tests dédiés.

Vérifications : 26 tests Python ciblés réussis ; rendu des quatre panneaux dans les sept langues, sans doublon de création ; tests DOM avec les vrais composants Syncfusion pour les graphiques et Dashboard Layout, déplacement clavier, réinitialisation, états vides et conservation des événements. Les scénarios SQL passé/futur ont été validés sur des fixtures PostgreSQL sans modifier les données stockées. Recette visuelle en navigateur réel toujours à effectuer avant publication.

Suite : simplification du formulaire de création et regroupement des réglages avancés, sans changer les paramètres envoyés à la génération.

## 6 novembre 2026 — Lot 3a : formulaire de création guidé

- Brief essentiel en premier : sujet, instructions, objectif, langue, nombre de contenus et formats. Les champs sont réorganisés sans modifier leurs noms, valeurs par défaut ou contraintes.
- Réglages de ciblage et de marque regroupés dans deux panneaux **Syncfusion Accordion EJ2 35.1.37**, initialement fermés. Sans SDK, les réglages restent visibles et utilisables.
- Matérialisation de tous les champs avant initialisation des contrôleurs existants : les dix domaines et les trois formats préremplis, ainsi que les paramètres facultatifs, restent transmis même lorsque les panneaux sont fermés.
- Ouverture automatique du panneau en erreur et focus sur le premier champ invalide ; associations labels/champs et descriptions d’erreur améliorées.
- Génération annoncée comme une préparation de contenus, sans publication ni programmation automatique. Skeleton de chargement sans pourcentage fictif ; saisies conservées en cas d’échec pour permettre un nouvel essai.
- Aucun changement aux routes, à la structure du payload de génération, aux options envoyées à l’IA ou au comportement du macaron.

Fichiers principaux : `templates/posts/new.html`, `static/js/creation-form.js`, `static/css/creation-form.css`, ajustements de validation dans `static/js/form.js`, traductions et tests du formulaire.

Vérifications : 27 tests Python ciblés réussis ; contrats de champs vérifiés dans les sept langues ; test DOM avec le vrai Accordion, champs fermés, valeurs par défaut, erreurs, focus, payload exact, échec de génération et repli sans SDK. Aucune requête réelle vers l’IA ou Buffer n’a été envoyée. La recette visuelle en navigateur réel reste à effectuer avant publication.

Suite du lot 3 : consultation des variantes, édition et aperçu, notamment la distinction entre les compteurs simulés de l’aperçu et les données réelles.

## 6 novembre 2026 — Lot 3b : éditeur et aperçu des contenus

- Navigation entre contenus par **Syncfusion Toolbar EJ2 35.1.37**, avec liens HTML en repli, focus clavier et prise en compte des cartes ajoutées pendant la génération.
- Les deux contenus par ligne sont conservés sur grand écran ; la navigation permet d’atteindre une carte sans changer son texte ni son étape.
- Modes Texte / Les deux / Aperçu indépendants par carte. Le choix est mémorisé par identifiant de contenu dans ce navigateur, en conservant l’ancienne préférence globale comme valeur initiale.
- Suppression des likes et commentaires fictifs dans les aperçus de l’éditeur (LinkedIn, Facebook, Instagram), remplacés par une mention explicite d’aperçu indicatif sans statistiques réelles.
- Champ de texte identifié par un label ; état de sauvegarde annoncé ; focus visible et tailles de contrôles améliorés.
- Intégration des améliorations de parcours préparées auparavant : boutons annonçant l’étape suivante, action « Publier ou programmer » hiérarchisée, sauvegarde et blocage sur texte vide ou échec conservés.
- Pas de migration vers un éditeur HTML : le texte Unicode et le contrat de publication restent inchangés. Aucun endpoint métier modifié.

Fichiers principaux : `templates/posts/view.html`, `static/js/post-editor.js`, `static/css/post-editor.css`, adaptations de présentation dans `static/js/consultation.js` et `static/js/post-flow.js`, styles du parcours, traductions et tests.

Vérifications : 29 tests Python ciblés réussis ; tests DOM du contrôleur complet et des vrais Toolbar et Stepper Syncfusion ; sept langues, navigation, apparition de nouveaux contenus, indépendance des aperçus, repli sans SDK et garde-fous de sauvegarde. Les tests de navigation n’effectuent aucun appel API et les simulations de parcours ne publient aucun post. La recette visuelle dans un navigateur réel reste à effectuer avant publication.

Suite du plan : calendrier et comptes connectés, en conservant le Scheduler dans la stratégie.

## 6 novembre 2026 — Lot 4 : calendrier et comptes connectés

- Scheduler conservé dans la stratégie. Libellés explicites « Action de stratégie » et « Envoi du post », légende et explication des événements non déplaçables.
- Portée des filtres rendue visible : ils concernent les publications ; lorsqu’ils masquent les actions, un message l’indique et une réinitialisation est disponible.
- Ajout de **Syncfusion DateTimePicker EJ2 35.1.37** dans les détails. La date reste transmise comme heure locale du compte pour la conversion serveur existante ; l’input natif reste disponible en repli.
- Focus sur le détail au clic et retour au calendrier à la fermeture. Les actualisations ne déplacent pas le focus.
- Intégration des corrections de navigation de stratégie préparées auparavant : onglets clavier/RTL, relations ARIA et restauration de l’onglet Posts par lien direct.
- Configuration Buffer visible près du nom du compte pour son workspace propriétaire, sans doublon dans le menu. Les comptes partagés ne reçoivent pas cette action ; activation, partage et suppression conservent leurs règles.
- Identifiant technique remplacé par une indication de propriété/partage ; connecteurs indisponibles regroupés dans une section secondaire. Le statut d’accès « Actif » n’est plus présenté comme la preuve d’une connexion externe valide.
- Aucun endpoint métier, flux OAuth, token, règle de publication ou autorisation modifié. Aucune nouvelle route de calendrier global.

Fichiers principaux : calendrier partiel/JS/CSS, templates et styles des comptes, navigation JS des stratégies et tests dédiés. Composants Syncfusion : Schedule existant et DateTimePicker ajouté, version inchangée.

Vérifications : 31 tests Python ciblés réussis ; vrais Scheduler et DateTimePicker dans les sept langues, navigateur UTC et compte America/New_York, conservation des révisions précises, filtres, confirmations et verrouillage des publications déjà envoyées. Tests DOM des onglets et de l’ouverture Buffer : bon compte/canal, clé non exposée, conservation d’une clé vide en édition, aucun appel API. La recette visuelle dans un navigateur réel reste à effectuer avant publication.

Suite du plan : listes et recherche cohérentes, puis périmètre de bibliothèque médias et analyses réelles selon les données disponibles.
