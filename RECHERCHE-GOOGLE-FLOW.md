# Recherche : Google Flow et API de génération d’images

Vérification : 12 novembre 2026. Recherche documentaire uniquement, sans modification de l’application, création de compte ni génération facturée.

## Conclusion à transmettre

Google Flow permet de générer et modifier des images dans son interface web. Toutefois, aucune API publique Flow avec documentation développeur, authentification et contrat d’intégration n’a été identifiée dans les sources officielles consultées. Cela ne démontre pas l’absence d’offres privées ou futures.

Pour intégrer officiellement la génération d’images Google à notre plateforme, la voie documentée est **l’API Gemini**, avec les modèles d’images de la famille **Nano Banana**. Il faut distinguer cette API du produit Flow et de ses quotas d’utilisation dans le navigateur.

Sources : [Flow — création d’images](https://support.google.com/flow/answer/16729550?hl=fr), [Flow — premiers pas](https://support.google.com/flow/answer/16353333?hl=fr), [API Gemini — génération d’images](https://ai.google.dev/gemini-api/docs/image-generation).

## Comparaison

| Point | Google Flow | API Gemini pour les images |
| --- | --- | --- |
| Usage documenté | Création et retouche dans des projets via l’interface web. | Appels programmatiques depuis une application. |
| Intégration au site | API publique Flow non identifiée au cours de la recherche. | Documentation et SDK officiels disponibles. |
| Images de référence | Possibles dans les parcours Flow documentés. | Génération et modification à partir de texte et d’images. |
| Gratuité | Quotas d’images dépendant du modèle et du forfait. | Pas de Free Tier indiqué pour les modèles d’images comparés ci-dessous. |
| Facturation | Conditions propres au produit Flow. | Usage API facturé suivant le modèle et les entrées/sorties. |

Les possibilités de l’API Gemini sont documentées dans le [guide officiel de génération d’images](https://ai.google.dev/gemini-api/docs/image-generation) ; sa facturation est décrite dans la [grille tarifaire officielle](https://ai.google.dev/gemini-api/docs/pricing).

## Gratuité dans Flow : ce que cela signifie

La page d’aide consultée indique que la génération et l’agrandissement des images Flow ne consomment actuellement pas les crédits mensuels Google Flow/IA, mais utilisent des limites quotidiennes par modèle. Elle affiche notamment, sans forfait Google AI :

- Nano Banana Pro : jusqu’à 20 générations par jour.
- Nano Banana 2.1 et Nano Banana 2 Lite : jusqu’à 400 générations par jour, quota combiné.

Ce sont des plafonds d’utilisation du produit, avec des limites de rythme supplémentaires possibles ; ce n’est pas une promesse d’accès API gratuit. Ne pas construire un budget d’automatisation en supposant que ces quotas sont transférables à l’API Gemini.

Source : [limites quotidiennes des images Flow](https://support.google.com/flow/answer/16729550?hl=fr). Disponibilité et conditions d’accès : [premiers pas avec Flow](https://support.google.com/flow/answer/16353333?hl=fr).

## Coûts API indicatifs

La grille officielle consultée affiche les montants suivants pour la **sortie image en mode Standard** :

| Modèle API | Image 1K | Image 2K | Image 4K |
| --- | ---: | ---: | ---: |
| `gemini-nano-banana-2.1` | 0,0336 USD | 0,0504 USD | 0,113 USD |
| `gemini-3.1-flash-image` — Nano Banana 2 | 0,067 USD | 0,101 USD | 0,151 USD |

Exemple de calcul : 1 000 sorties 1K avec Nano Banana 2.1 représentent **33,60 USD pour les seules images de sortie**. Il faut ajouter les entrées, les autres sorties facturables éventuelles, les outils optionnels, les nouvelles tentatives et les taxes applicables. Ce n’est donc pas un devis global de génération.

Ces modèles n’ont pas de génération gratuite indiquée dans la colonne Free Tier de la grille consultée. Les tarifs et identifiants doivent être revérifiés au moment du développement et avant de fixer un prix commercial.

Source : [tarification Gemini, sections Nano Banana 2.1 et Gemini 3.1 Flash Image](https://ai.google.dev/gemini-api/docs/pricing).

## Attention aux anciens articles sur Imagen

Les articles historiques qui recommandent Imagen ne suffisent pas pour choisir une intégration actuelle. La page officielle Imagen de l’API Gemini consultée indique que ces modèles y sont arrêtés et renvoie vers Nano Banana. Cette observation concerne l’API Gemini ; elle ne permet pas de conclure au statut de toutes les offres Google Cloud portant le nom Imagen.

Source : [documentation Imagen dans l’API Gemini](https://ai.google.dev/gemini-api/docs/imagen).

## Recommandation pour notre application

1. Utiliser Flow manuellement pour comparer les rendus et préparer les prompts, si le compte y a accès.
2. Pour l’automatisation, comparer l’API Gemini officielle à l’accès aux modèles Google éventuellement disponible dans notre catalogue OpenRouter. La disponibilité et les tarifs OpenRouter doivent être vérifiés séparément ; ils ne sont pas établis par la tarification Google ci-dessus.
3. Tester un petit ensemble de prompts réels : illustration de post, visuel avec texte français et retouche avec image de référence. Mesurer qualité, délai, coût effectif et taux d’échec avant de choisir.
4. En cas de choix de l’API directe, conserver la clé côté serveur et réutiliser notre pipeline de téléchargement, stockage et sélection des médias. Cela demande une adaptation du fournisseur ; les appels Google ne se substituent pas automatiquement aux payloads OpenRouter existants.
5. Ne pas utiliser les appels internes repérés dans le navigateur de Flow comme contrat d’API de production : ils ne constituent pas une interface publique documentée dans la recherche effectuée.

Cette recommandation est une proposition d’architecture, pas un comparatif de qualité mesuré. Aucun test de génération n’a été réalisé ni facturé pour cette recherche.
