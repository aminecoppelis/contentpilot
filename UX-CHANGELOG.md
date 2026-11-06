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
