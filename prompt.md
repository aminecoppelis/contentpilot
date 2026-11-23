# Développer la prospection Facebook dans ContentPilot

Tu travailles dans le dépôt ContentPilot. Développe un module de prospection Facebook inspiré du parcours de Novalya, avec une interface propre à ContentPilot et une extension Chrome Manifest V3. Le périmètre couvre les profils Facebook personnels et supplémentaires, les groupes Facebook et les publications Facebook.

## Résultat attendu

L’utilisateur se connecte à Facebook dans Chrome, associe le profil actif à ContentPilot après avoir vérifié son nom et sa photo, sélectionne une source de prospects, prépare son message et lance la campagne depuis ContentPilot. L’extension exécute les actions dans la session Facebook ouverte. Le destinataire voit le profil Facebook de l’utilisateur comme expéditeur. ContentPilot affiche la progression et les résultats.

## Parcours à développer

1. Ajouter une section **Prospection Facebook** dans ContentPilot. Prévoir un bouton **Connecter mon profil Facebook**. L’extension détecte le profil actif et présente son nom et sa photo pour confirmation. Afficher l’état de la connexion et demander une nouvelle confirmation si le profil actif change. Garder les identifiants et cookies Facebook dans le navigateur.
2. Permettre d’ajouter un lien vers un groupe ou une publication Facebook. Pour un groupe, parcourir progressivement les lots de membres affichés dans le navigateur après le lancement. Pour une publication, partir des profils visibles dans la liste des réactions. Dédupliquer les profils par identifiant stable ou URL normalisée. Indiquer quand la liste visible est épuisée ou quand le parcours s’interrompt. Prévoir un filtre facultatif par mot-clé sur les informations affichées et un plafond de destinataires choisi par l’utilisateur.
3. Permettre de rédiger et de prévisualiser un message avec un champ de personnalisation pour le prénom. Afficher la source, le profil expéditeur, le message et le plafond avant confirmation. Le bouton **Lancer la campagne** démarre l’exécution dans l’onglet Facebook. L’extension utilise les commandes de messagerie accessibles au profil actif. Si le profil ne peut pas recevoir de message, indiquer le motif lorsqu’il est visible et passer au suivant.
4. Afficher les compteurs **En attente**, **Envoyés**, **Ignorés** et **À vérifier**, ainsi que le détail par prospect. Marquer un message comme envoyé après confirmation observable dans l’interface. Si le navigateur se ferme ou si le résultat d’un envoi est incertain, enregistrer l’état et éviter tout renvoi automatique du même message. Prévoir des commandes de pause, reprise et arrêt. Suspendre la campagne si Facebook affiche une vérification, une restriction ou une demande de reconnexion.

## Mise en œuvre

- Lis les instructions du dépôt et inspecte les routes, modèles, migrations, écrans de connexion et mécanismes d’authentification existants. Réutilise les conventions du projet. Ajoute le parcours de prospection et préserve le parcours de connexion des Pages utilisé pour la publication.
- Place l’extension dans un dossier dédié. Utilise un manifeste Manifest V3, un service worker pour la coordination et des scripts de contenu pour l’interaction avec l’onglet. Limite les permissions aux fonctionnalités et domaines concernés. Valide l’origine et le contenu des messages échangés entre ContentPilot et l’extension.
- Conserve les campagnes, leurs prospects et leurs résultats dans ContentPilot. Contrôle l’accès par utilisateur ou espace de travail selon les conventions du dépôt. Empêche deux exécutions concurrentes de traiter la même campagne. Utilise des états persistants pour permettre une reprise fiable malgré la suspension du service worker ou la fermeture de Chrome.
- Isole la logique qui dépend de l’interface Facebook pour faciliter les corrections quand la page change. Utilise les éléments affichés et les actions disponibles dans l’onglet. Si une action est inaccessible, rends cet état visible à l’utilisateur.

## Livrables et validation

- Une extension chargeable via **Charger l’extension non empaquetée**, le module intégré à ContentPilot et les migrations nécessaires.
- Des instructions courtes pour lancer ContentPilot, installer l’extension localement et essayer le parcours complet.
- Des tests sur pages de simulation pour vérifier le chargement progressif des profils, la déduplication, la confirmation du bon profil, le suivi d’envoi, la reprise et les cas d’interruption. Utilise Playwright si c’est adapté aux tests du dépôt. Les tests automatisés doivent utiliser des profils et messages fictifs.
- Présente à la fin les fichiers modifiés, les commandes de vérification exécutées et les étapes du parcours Facebook qui restent à valider avec un compte de test autorisé.
