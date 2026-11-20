# UX changelog

## 20 novembre 2026 — Page d'accueil publique

- La racine `/` affiche désormais une vraie page d'accueil publique : présentation de la création sociale, illustration du parcours, fonctionnalités, organisation, réseaux, FAQ et inscription/contact.
- Entrée Accueil et retour du logo vers la racine ; navigation et contenus dans les sept langues. Les routes applicatives `/app/*` restent accessibles depuis Connexion.
- Même charte Inter/Actifpilot, mode clair et mode sombre, aperçu illustratif sur grand écran et disposition adaptée au mobile. Pas de témoignages ou résultats chiffrés inventés.
- Vérifications : 108 tests Python réussis ; accueil contrôlé en navigateur local sur ordinateur en clair/sombre et sur mobile, sans débordement dans les vues testées.

## 20 novembre 2026 — Charte Actifpilot et pages de présentation complètes

- Référence consultée en navigateur : actifpilot.com, pages Offres, Fonctionnement, Sécurité, Tarifs et Contact. Reprise de la police Inter, des logos publics, des dimensions typographiques, de la palette, des cartes arrondies et du pied de page. Les contenus présentent la création de contenus sociaux, et non les services QHSE du site de référence.
- Deux thèmes : fond clair et textes foncés en clair ; bleu nuit et textes blancs uniquement en sombre. Choix conservé entre les pages ; mode clair par défaut sans préférence enregistrée.
- Pages enrichies dans les sept langues : fonctionnalités détaillées, workflow, comparaison, organisation par entreprise, confidentialité, présentation des besoins tarifaires, FAQ et appels à l'action. Aucun prix, témoignage ou engagement d'hébergement/certification repris sans validation pour ce produit.
- Contact : champs nom, email, entreprise, téléphone, sujet et message ; préparation dans la messagerie de l'utilisateur, avec indication explicite de ce fonctionnement et sans faux message de livraison.
- Menu responsive avec ouverture/fermeture et Échap, bascule de thème et footer partagé sur les pages publiques et juridiques. Liens sur le domaine courant.
- Vérifications : 107 tests Python réussis ; rendu Playwright local en clair/sombre sur ordinateur, contact mobile et fonctionnement arabe RTL sans débordement sur les vues contrôlées. Aucun accès à la DB, worker, envoi SMTP ou publication réelle pendant la recette visuelle.

## 19 novembre 2026 — Menu public multilingue

- Menu commun : Offres, Comment ça fonctionne, Sécurité & RGPD, Tarifs, Contact, sélecteur des sept langues, Connexion et Inscription.
- Présent sur la connexion, l'inscription, les documents juridiques et les cinq nouvelles pages publiques. Liens relatifs au domaine courant, conservation de la langue et de la destination de connexion, présentation responsive et arabe RTL.
- Contenus de présentation traduits ; la page Tarifs dirige vers le contact, sans montant ni formule commerciale inventés. La page Sécurité renvoie vers les textes juridiques sans annoncer de certification ou conformité non vérifiée.
- Tests des 35 combinaisons rubrique/langue et des deux formulaires d'authentification dans les sept langues. Aucun accès DB ou envoi externe nécessaire.

## 19 novembre 2026 — Confidentialité et conditions d'utilisation

- Mention « En continuant, vous acceptez… » avec liens réels actifpilot.com sur les pages de connexion et d'inscription, en français et en anglais.
- Pages publiques `/privacy` et `/terms` (également sous `/app`) avec sélecteur FR/EN, styles responsive et contact email cliquable. Texte français des CGU repris de la pièce jointe, politique française reprise du message et traductions anglaises ajoutées ; date du 9 mars 2026 conservée.
- Tests de disponibilité sans authentification ni accès DB, langue et liens, présence des dernières sections et échappement HTML. Cette intégration publie les textes fournis ; elle ne modifie pas les traitements de données ni les mécanismes de consentement du produit.

## 18 novembre 2026 — Réglages de création réutilisables

- Dans la création d'un contenu : enregistrer les informations entreprise, site, solution, tags, consignes et activation du macaron ; réutiliser explicitement ces réglages ou activer le préremplissage des prochains contenus.
- Persistance en base par utilisateur et workspace actif (`016_creation_brand_profiles.sql`), commune aux sessions et appareils. Le logo et la position du macaron continuent d'être lus depuis Mon compte.
- Préremplissage au rendu initial, sans chargement tardif écrasant la saisie ; réutilisation manuelle confirmée si les champs ont été modifiés ; erreurs de sauvegarde sans perte des saisies. Aucun contenu ni publication créé par l'enregistrement du profil.
- Libellés dans les sept langues. Vérifications : 100 tests Python réussis ; test DOM d'enregistrement/réutilisation/échec et parcours Accordion dans les sept langues. Migration à appliquer au prochain démarrage (ou manuellement si les migrations automatiques sont désactivées).

## 18 novembre 2026 — Audit global de l'application

- Ajout de `AUDIT-APPLICATION-2026-11-18.md` : existant, dix constats priorisés avec sources dans le code, améliorations UX, huit propositions fonctionnelles et plan de livraison.
- Vérification locale : 97 tests Python réussis et reproduction isolée d'un calcul de faux statut publié après une exception sans message.
- Aucun code applicatif ni donnée modifié pour cet audit ; aucune publication, connexion externe ou recette de la VM de production effectuée. Les contrôles d'exploitation et la recette visuelle restent explicitement à réaliser.

## 17 novembre 2026 — Formats YouTube dans la création

- Ajout de « YouTube · Vidéo » et « YouTube · Short » dans les formats de création et de modification d'un sujet. Le libellé Vidéo suit la langue de l'interface ; les valeurs enregistrées restent stables.
- Les sélections YouTube sont transmises à la génération avec les autres formats. Le nom YouTube est également reconnu dans les listes de comptes des stratégies.
- Vérifications : test DOM avec le véritable Accordion Syncfusion dans les sept langues et avec repli sans SDK ; sélection des deux formats et contrôle du payload. Seize tests Python ciblés réussis. Aucun appel réel de génération ou de publication.

## 13 novembre 2026 — Publication YouTube

- Ajout de YouTube dans Mes réseaux et dans la fenêtre de publication partagée, avec choix Vidéo/Short, titre, description, tags, visibilité et public enfant. Libellés dans les sept langues.
- OAuth Google avec state lié à la session, à l'utilisateur et à l'entreprise ; jetons chiffrés et renouvelés côté serveur, révocation depuis le menu du compte. Les connexions YouTube ne peuvent pas être partagées entre entreprises.
- Upload resumable par blocs, reprise sur les octets confirmés par Google et sauvegarde chiffrée de la session. Réutilisation du worker et de l'historique existants pour les envois immédiats et programmés. Aucun statut publié sans identifiant confirmé par YouTube.
- Import vidéo en flux vers le disque, limité à 2 Gio par défaut. Migration additive `015_youtube.sql`, configuration et première publication documentées dans `docs/YOUTUBE.md`.
- Vérification automatisée : tests Python et DOM locaux, avec réponses fournisseur contrôlées. Aucune autorisation Google ni publication réelle effectuée ; la recette réelle et l'application de la migration au déploiement restent explicites dans la documentation.

## 12 novembre 2026 — Double génération du même média

- Cause identifiée dans le code : la route synchrone créait une image `pending/running` sans verrou de worker. Le worker pouvait la réclamer pendant l'appel au fournisseur et produire une deuxième image sous le même identifiant, avec écrasement du fichier et des URL.
- La génération depuis l'éditeur réserve désormais le média en `processing/running`, hors de la file du worker. Le worker ne reprend une ligne `running` que si son verrou explicite a expiré ; un verrou absent ne vaut plus expiration.
- Vérifications : 13 tests Python réussis, dont la réservation pendant l'appel fournisseur, la persistance du premier résultat et les conditions de reprise du worker. Aucun appel réel de génération ou de publication. Les tests ne prouvent pas quel résultat a été écrasé en production et ne restaurent pas un fichier déjà remplacé.

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

## 9 novembre 2026 — Correction : action de publication sur un contenu déjà publié

- Bouton « Publier ou programmer » masqué pour un contenu déjà publié, sans retirer cette action aux autres contenus du même sujet.
- La fiche consulte les publications réussies du contenu dans le workspace, même si son statut de validation est encore « approved ». Badge, étape initiale et actions affichées restent ainsi cohérents avec l’envoi réel.
- Garde côté interface empêchant l’ouverture de la modale pour ce contenu ; aucune modification de l’API de publication.
- Vérifications : huit tests Python ciblés réussis, dont le décalage entre statut de validation et publication ; test DOM de l’éditeur dans les sept langues avec ouverture de modale bloquée et aucun appel API.

## 10 novembre 2026 — Connexion Instagram réactivée

- Carte « Connecter Instagram » visible directement dans Mes réseaux, retirée des connecteurs indisponibles et reliée à la route OAuth Instagram existante.
- Retrait de l’état désactivé et du libellé « bientôt disponible » pour Instagram. Les traductions existantes sont conservées.
- Aucun changement aux identifiants, autorisations, paramètres Meta ou callbacks OAuth ; aucune connexion externe n’a été déclenchée pendant la vérification.

## 12 novembre 2026 — Visibilité des comptes Instagram avant sélection d’un média

- Correction d’un cas identifié dans le sélecteur de publication : un compte Instagram connecté disparaissait lorsqu’aucun média n’était sélectionné.
- Le compte reste désormais visible, avec une option désactivée et la raison « Aucun média n’est sélectionné ». Les types compatibles deviennent sélectionnables avec l’image ou la vidéo choisie.
- La sélection d’un média reste obligatoire pour Instagram. Les filtres d’accès au workspace, les comptes inactifs et les anciens connecteurs non pris en charge ne sont pas modifiés.
- Test DOM des six cas Instagram direct/Buffer × sans média/image/vidéo, avec lecture de comptes simulée et aucune publication.


## 12 novembre 2026 - Aperçu du média choisi

- L'aperçu utilise uniquement le média choisi et la même source que la galerie.
- Les anciennes réponses de galerie ne remplacent plus une nouvelle sélection. Les choix successifs sont enregistrés dans leur ordre.
- Tests : scénarios DOM de chargement retardé, clics successifs et erreur ; régression Instagram ; huit tests Python réussis. Aucun appel réel de publication.
