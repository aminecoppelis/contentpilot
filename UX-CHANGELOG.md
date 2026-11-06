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
