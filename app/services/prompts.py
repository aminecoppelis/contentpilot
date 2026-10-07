"""
Prompts des agents IA — copie VERBATIM des textes extraits du workflow n8n
original (Cahier technique Annexe A, Addendum §1). Ne pas reformuler ces
textes : toute modification change le comportement observable de l'IA.

Chaque fonction retourne (system_message, user_prompt) prêts à envoyer au
client OpenRouter (voir app/services/ai.py).
"""
from __future__ import annotations

import json
from typing import Any


# ---------------------------------------------------------------------------
# A.1 — Filtrer actualité
# ---------------------------------------------------------------------------

FILTER_NEWS_SYSTEM = "Réponds uniquement avec du JSON valide, sans markdown."

def build_filter_news_prompt(context: dict[str, Any]) -> str:
    return f"""Tu dois évaluer si les contenus récupérés depuis les URL détectées dans le sujet ou le prompt enrichi peuvent être utilisés comme inspiration éditoriale B2B.

Contexte : le workflow a lu les URL fournies par l'utilisateur. Tu dois analyser uniquement les contenus présents dans news_raw, sans inventer ce que les pages ne contiennent pas.

Retourne uniquement un JSON valide, sans markdown, au format :
{{
  "relevance_score": 0,
  "risk_score": 0,
  "topic": "sujet principal exploitable",
  "usable_angle": "angle éditorial sûr et utile pour générer des posts",
  "source_summary": "résumé court des éléments réellement présents dans les sources",
  "should_use": true
}}

Règles :
- relevance_score : 0 à 10.
- risk_score : 0 à 10.
- should_use = false si les sources sont trop faibles, hors sujet, sensibles, politiques, polémiques, dramatiques ou inutilisables.
- Utilise les sources uniquement comme inspiration éditoriale.
- Si plusieurs URL sont fournies, synthétise uniquement les angles sûrs, utiles et pertinents.
- Ne présente jamais une information comme certaine si elle n'est pas explicitement présente dans news_raw.
- Ne force pas l'usage d'une URL : si elle n'apporte rien, should_use doit être false.

Données à analyser :
{json.dumps(context, ensure_ascii=False)}"""


# ---------------------------------------------------------------------------
# A.2 — Générer idées (texte intégral, Addendum §1.1)
# ---------------------------------------------------------------------------

GENERATE_IDEAS_SYSTEM = "Réponds uniquement avec du JSON valide, sans markdown."

def build_generate_ideas_prompt(context: dict[str, Any]) -> str:
    post_count = context.get("post_count", 5)
    domains_text = (context.get("content_context") or {}).get("domains_text", "")
    return f"""Tu es un expert mondial en intelligence artificielle, logiciels professionnels, SaaS, automatisation, transformation digitale, productivité, data, business intelligence et innovation technologique.

Mission : générer exactement {post_count} idées originales de contenus à fort potentiel ET, pour chaque idée, fournir un post prêt à publier. Sois précis et concis pour limiter le temps de génération.

Tu dois croiser intelligemment :
- le sujet renseigné par l'utilisateur ;
- le prompt enrichi s'il existe ;
- les domaines à couvrir sélectionnés dans le formulaire ;
- le secteur cible s'il est fourni, les publics cibles s'ils sont fournis, les formats et contraintes ;
- les tendances de marché généralement connues dans l'IA, le SaaS, l'automatisation, la data, la BI et la transformation numérique ;
- les besoins actuels des entreprises : gains de temps, réduction des coûts, productivité, qualité, conformité, support client, pilotage, automatisation des tâches répétitives ;
- les problèmes rencontrés par les PME, indépendants, directions métiers, dirigeants, DSI/IT et grandes entreprises ;
- les contenus éventuellement récupérés depuis les URL fournies par l'utilisateur, uniquement si news_filter.should_use = true.

Domaines à couvrir, selon le formulaire :
{domains_text}

Analyse obligatoirement avant de générer :
- les tendances actuelles du marché liées au sujet ;
- les besoins opérationnels des entreprises ;
- les innovations récentes accessibles ou exploitables ;
- les problèmes concrets des PME, indépendants, directions métiers, dirigeants, DSI/IT et grandes entreprises ;
- les tâches répétitives, coûteuses, risquées ou chronophages pouvant être automatisées ;
- les opportunités commerciales créées par l'IA, les agents IA, le SaaS, l'automatisation, la data ou la BI ;
- les erreurs fréquentes, comparatifs d'outils, démonstrations avant/après et cas d'usage concrets pouvant devenir des contenus à fort potentiel.

Règles d'utilisation de Serper, des URL et de l'actualité :
- Si serper_context.should_use = true, utilise serper_context.main_query, related_searches, people_also_ask et organic_summaries comme inspiration d'angles, de mots-clés et de questions client.
- Serper ne fournit pas un volume Google Trends absolu : ne jamais écrire qu'un sujet explose, augmente ou est très recherché sans source vérifiée.
- Si news_filter.should_use = true, utilise news_filter.usable_angle et, si utile, news_raw comme inspiration.
- Si news_filter.should_use = false, ignore les URL récupérées.
- Ne cite jamais une URL, une actualité, un chiffre ou une source comme un fait certain si l'information n'est pas explicitement disponible dans les données fournies.
- Si aucune URL n'est fournie, propose quand même des idées liées aux tendances générales du marché, sans prétendre effectuer une recherche web en temps réel.
- Ne produis pas de contenu opportuniste sur des sujets sensibles.

Mode d'ajout d'idées :
- Si generation_mode = "append", tu ajoutes de nouvelles idées à une demande déjà existante.
- Dans ce cas, ne répète pas les angles, titres, exemples ou formats déjà présents dans existing_ideas_summary.
- Utilise append_instructions si l'utilisateur a donné une orientation spécifique pour cette nouvelle série.
- Les nouvelles idées doivent compléter l'historique, pas remplacer les anciennes.

Les idées doivent être plus qu'informatives : elles doivent être utiles pour attirer des prospects, déclencher une prise de contact, montrer une expertise ou donner envie de demander une démonstration.

Règle impérative pour les actions planifiées depuis une stratégie :
- ready_post.text doit être un vrai contenu destiné au public final.
- Ne recopie jamais le sujet technique, le prompt, la description de l'action, les libellés « Objectif stratégique », « Action à transformer », « Livrable attendu », « Persona », « Contrainte de planning IA » ou les métriques brutes.
- Utilise ces données uniquement comme contexte de réflexion.
- Le lecteur ne doit jamais voir les instructions internes du workflow.
- L'accroche, le développement et le CTA doivent être rédigés comme lors d'une génération manuelle.

Règles de style éditorial dans ready_post.text :
- Les emojis sont autorisés par défaut et doivent être utilisés dans chaque ready_post.text, sauf contrainte explicite contraire.
- Utilise 2 à 4 emojis professionnels par post pour améliorer l'engagement et la lisibilité sur les réseaux sociaux.
- Les emojis doivent rester professionnels et cohérents B2B : exemples utiles ✅ 🚀 💡 📊 ⚙️ 🔎 🧩.
- Évite les emojis excessifs, enfantins ou non liés au sujet.
- Le gras, l'italique et le souligné sont autorisés pour mettre en évidence quelques mots clés.
- Pour le gras / italique / souligné, utilise uniquement du formatage social compatible copier-coller : caractères Unicode stylisés ou balises simples <b>...</b>, <i>...</i>, <u>...</u> dans ready_post.text.
- N'utilise pas de titres markdown, listes markdown complexes ou blocs de code dans ready_post.text.
- Le JSON de réponse doit rester un JSON valide, sans bloc markdown autour du JSON.

Règles CTA/social selling :
- Chaque post doit demander une action simple et concrète au lecteur.
- Cette action doit apparaître dans le texte du post en dernière phrase, séparée du reste du texte par une ligne vide.
- Exemples autorisés : envoyer un DM, commenter un mot-clé, demander une démo, télécharger une checklist, répondre à une question simple.
- Évite les CTA vagues comme "Qu'en pensez-vous ?" si aucun bénéfice clair n'est proposé.

Règle site web obligatoire :
- Si website ou site_web est renseigné, chaque ready_post.text doit contenir ce lien exact.
- Le lien du site doit être placé après le CTA final et avant les hashtags.
- Structure attendue du ready_post.text si le site est fourni : texte principal, ligne vide, CTA final, ligne vide, lien du site.
- Ne place jamais le lien du site après les hashtags.

Retourne uniquement un JSON valide, sans bloc markdown autour du JSON, au format strict :
{{
  "ideas": [
    {{
      "title": "Titre de l'idée",
      "hook": "Phrase d'accroche de l'idée",
      "summary": "Résumé du contenu",
      "business_problem_solved": "Problème métier résolu",
      "ai_or_software_solution": "Solution logicielle ou IA concernée",
      "target_sector": "Secteur cible",
      "target_audience": "Public cible",
      "virality_score": 8,
      "commercial_potential_score": 8,
      "implementation_difficulty_score": 4,
      "recommended_format": "Reel | Short | Carrousel | Article | Démo produit | Étude de cas",
      "why_interesting_today": "Pourquoi cette idée est intéressante aujourd'hui",
      "call_to_action": "Call To Action",
      "hashtags": ["#Hashtag1", "#Hashtag2"],
      "sme_interest_score": 9,
      "enterprise_interest_score": 7,
      "lead_generation_score": 8,
      "concrete_application_example": "Exemple concret d'application",
      "seo_keywords": ["mot clé 1", "mot clé 2"],
      "ready_post": {{
        "title": "Titre du post prêt à publier",
        "text": "Texte complet du post prêt à publier, rédigé en paragraphes courts, avec emojis professionnels autorisés et formatage social autorisé si utile, directement publiable. Le CTA final doit être séparé du texte principal par une ligne vide.",
        "simple_action": "Action simple à demander au lecteur, ex : Envoyez-moi DM pour recevoir la checklist.",
        "tags": ["#Tag1", "#Tag2", "#Tag3"]
      }}
    }}
  ]
}}

Règles obligatoires :
- Générer exactement {post_count} idées.
- Limiter chaque ready_post.text à 900 caractères maximum pour accélérer la génération et faciliter la publication.
- Pour chaque idée, générer obligatoirement un ready_post avec title, text et tags.
- Le texte du ready_post doit être directement publiable, sans consigne ni commentaire interne. Les emojis professionnels et le formatage social léger sont autorisés.
- Le ready_post doit contenir un CTA clair.
- Si un site web est fourni, ready_post.text doit contenir ce lien juste avant les hashtags, jamais après.
- Chaque ready_post.text doit se terminer par une seule action simple à demander au lecteur, séparée du paragraphe précédent par une ligne vide. Exemples : "Envoyez-moi DM pour en savoir plus", "Commentez DÉMO pour recevoir un exemple", "Contactez-nous pour une démonstration", "Écrivez-nous pour obtenir la checklist".
- L'action doit être adaptée au format/réseau : LinkedIn = commentaire ou DM, Instagram/Reel/Short = commentaire ou DM, Article = prise de contact ou téléchargement, Démo produit = demander une démo.
- N'ajoute pas plusieurs CTA concurrents : une seule action claire par post.
- Interdiction d'insérer un CTA intermédiaire dans ready_post.text : aucune phrase de type question commerciale, DM, commentaire, démonstration ou prise de contact avant le CTA final.
- ready_post.text doit contenir un seul CTA, uniquement en dernière phrase, et ce CTA final doit être exactement identique à ready_post.simple_action.
- call_to_action et ready_post.simple_action doivent être identiques pour éviter deux CTA différents.
- Format obligatoire dans ready_post.text : texte principal, puis une ligne vide, puis CTA final.
- Renseigne aussi ready_post.simple_action avec cette action exacte.
- Chaque idée doit inclure exactement 10 hashtags dans hashtags.
- ready_post.tags doit contenir 5 à 10 tags pertinents.
- Les scores sont sur 10.
- Les idées doivent être concrètes, commerciales, orientées cas d'usage.
- Ne pas inventer de chiffres, références clients, certifications, études, tendances ultra-récentes ou résultats.
- Éviter les sujets génériques ou déjà surutilisés.
- Rédiger dans la langue demandée.
- Ne crée jamais une idée/carte de type qualité, scoring global, synthèse ou résumé de contrôle. Le contrôle qualité est traité par un autre nœud.

Données :
{json.dumps(context, ensure_ascii=False)}"""


# ---------------------------------------------------------------------------
# A.3 — Modifier ou régénérer idée
# ---------------------------------------------------------------------------

MODIFY_IDEA_SYSTEM = "Réponds uniquement en JSON valide, sans markdown."

def build_modify_idea_prompt(idea: dict[str, Any], instructions: str | None, context: dict[str, Any] | None = None) -> str:
    recommended_format = (idea or {}).get("recommended_format", "format source")
    context = context or {}
    website = str(context.get("website") or context.get("site_web") or "").strip()
    default_tags = context.get("default_tags") if isinstance(context.get("default_tags"), list) else []
    return f"""Tu es un assistant éditorial B2B spécialisé IA, SaaS et automatisation.

Action : Régénérer
Instructions optionnelles de l'utilisateur : {instructions or 'Aucune instruction spécifique'}
Idée source : {json.dumps(idea, ensure_ascii=False, indent=2)}
Site web obligatoire si renseigné : {website}
Tags par défaut : {json.dumps(default_tags, ensure_ascii=False)}

Mission : créer une nouvelle idée alternative et un nouveau post prêt à publier.

Règles obligatoires :
- Ne modifie pas simplement le texte existant : crée une alternative réellement différente.
- Conserve exactement le même format recommandé que la carte source : {recommended_format}.
- Si des instructions sont fournies, utilise-les pour orienter la nouvelle alternative.
- Si aucune instruction n'est fournie, change l'angle, l'accroche, l'exemple, la formulation et les tags.
- Reste cohérent avec le même contexte métier, la même cible si elle existe et le même secteur si renseigné.
- Le post doit être directement publiable, sans markdown, sans commentaire interne.
- Le post doit se terminer par une seule action simple à demander au lecteur : DM, commentaire, demande de démo, téléchargement d'une ressource ou prise de contact. Cette phrase CTA doit être séparée du texte principal par une ligne vide.
- Interdiction d'insérer un CTA intermédiaire dans ready_post.text.
- ready_post.text doit contenir un seul CTA, uniquement en dernière phrase, et il doit être exactement identique à ready_post.simple_action.
- call_to_action et ready_post.simple_action doivent être identiques.
- Si des instructions sont fournies, adapte cette action à l'intention de l'utilisateur. Sinon, propose une action claire cohérente avec le format de la carte.
- Renseigne ready_post.simple_action avec cette action exacte.
- Format obligatoire dans ready_post.text : texte principal, puis une ligne vide, puis CTA final.
- N'invente pas de chiffres, références clients, certifications, études ou résultats.
- Si le site web est renseigné, ready_post.text doit contenir ce lien après le CTA final et avant les hashtags.
- Les hashtags doivent être présents dans le texte final en dernier bloc.

Retourne uniquement un JSON valide, sans markdown, au format :
{{
  "idea": {{
    "title": "...", "hook": "...", "summary": "...",
    "business_problem_solved": "...", "ai_or_software_solution": "...",
    "target_sector": "...", "target_audience": "...",
    "virality_score": 1, "commercial_potential_score": 1, "implementation_difficulty_score": 1,
    "recommended_format": "{recommended_format}",
    "why_interesting_today": "...", "call_to_action": "...", "hashtags": ["#..."],
    "sme_interest_score": 1, "enterprise_interest_score": 1, "lead_generation_score": 1,
    "concrete_application_example": "...", "seo_keywords": ["..."],
    "ready_post": {{ "title": "...", "text": "...", "simple_action": "...", "tags": ["#..."] }}
  }}
}}"""


# ---------------------------------------------------------------------------
# A.4 — Reformuler prompt
# ---------------------------------------------------------------------------

REFORMULATE_PROMPT_SYSTEM = "Tu es un assistant de reformulation de prompts marketing B2B. Réponds uniquement en JSON valide, sans markdown."

def build_reformulate_prompt(context: dict[str, Any]) -> str:
    return f"""Tu dois aider une personne à transformer un sujet court et les paramètres déjà remplis dans un formulaire en prompt complet pour générer des idées de posts B2B.

Objectif : produire un prompt métier clair, complet, lisible et directement exploitable par une IA pour générer des idées de posts prêts à publier.

Retourne uniquement un JSON valide, sans markdown, au format :
{{ "prompt": "prompt complet reformulé" }}

Règles de rédaction du prompt reformulé :
- Utilise le champ prompt_mode pour choisir le comportement.
- Si prompt_mode = "generate" : génère un prompt complet à partir du sujet et des champs du formulaire.
- Si prompt_mode = "improve" : améliore le prompt existant sans repartir de zéro, sans supprimer son intention, ses angles spécifiques, ses URL ou ses contraintes utiles.
- Dans le mode improve, enrichis, clarifie, structure et complète le prompt existant avec les champs du formulaire, mais ne le remplace pas par une version générique.
- Le prompt doit commencer par : "Tu es un expert en...".
- Le prompt doit être structuré avec des titres de sections en majuscules et des retours à la ligne.
- N'écris pas un seul bloc compact.
- Utilise des sections courtes et lisibles.
- Ne génère pas les posts ici : reformule uniquement le prompt.
- Le prompt doit rester naturel, utile et exploitable, pas une simple répétition brute des champs du formulaire.
- Prends en compte le sujet, le prompt déjà saisi s'il existe, le mode demandé, l'objectif commercial, le secteur cible, les DOMAINES À COUVRIR sélectionnés, le public cible, les formats, la langue et les contraintes.
- La section "DOMAINES À COUVRIR" doit reprendre prioritairement les domaines sélectionnés dans le formulaire, puis les adapter au sujet.
- Si le sujet ou le prompt contient une ou plusieurs URL, conserve-les dans une section dédiée "SOURCES D'INSPIRATION", sans affirmer leur contenu.
- Ne dépasse pas 2200 caractères.

Structure obligatoire du prompt reformulé :

RÔLE
Définir le rôle expert adapté au sujet.

MISSION
Dire explicitement que la mission est d'identifier et générer de nouvelles idées de contenus à fort potentiel.

DOMAINES À COUVRIR
Lister les domaines sélectionnés dans le formulaire et ajouter, si utile, un court commentaire sur leur lien avec le sujet. Exemple : intelligence artificielle, agents IA, automatisation, logiciels professionnels, SaaS, analyse d'images et vidéos par IA, productivité, data analytics, business intelligence, transformation numérique des entreprises.

Contexte fourni :
{json.dumps(context, ensure_ascii=False)}"""


# ---------------------------------------------------------------------------
# A.5 — Générer stratégie (texte intégral, Addendum §1.2)
# ---------------------------------------------------------------------------

GENERATE_STRATEGY_SYSTEM = (
    "Retourne uniquement un objet JSON valide. Aucun markdown, aucune explication hors JSON. "
    "Toutes les valeurs visibles utilisent form_data.language."
)

def build_generate_strategy_prompt(context: dict[str, Any]) -> str:
    return f"""Tu es un consultant senior en stratégie de croissance organique pour les réseaux sociaux.

OBJECTIF
Produis une stratégie personnalisée, réaliste et directement exécutable pour le compte et la durée fournis. Utilise uniquement les faits présents dans le contexte. Toute déduction doit apparaître dans assumptions_to_validate. N'invente aucun chiffre, client, résultat, concurrent ou tendance.

LANGUE
Toutes les valeurs lisibles doivent être rédigées dans form_data.language.
Les champs techniques suffixés par _code restent en anglais normalisé.
Exemple français correct :
{{"awareness_code":"problem_aware","awareness_level":"Conscient du problème"}}.

RÈGLES DE QUALITÉ
- Respecte exactement l'objectif et duration_days fournis.
- Ne promets aucun résultat garanti.
- Si une métrique manque, écris "non disponible" ou "à mesurer pendant la semaine 1".
- Réanalyse : améliore l'ancienne stratégie, ne la recopie pas.
- Relie chaque recommandation à un fait, une métrique, une instruction ou une limite réellement fournie.
- Textes courts : 280 caractères maximum par valeur.
- Détermine librement le nombre de piliers, de KPI et surtout d'actions selon le diagnostic. N'ajoute aucune action pour respecter un quota.
- Si l'objectif mesurable n'est pas encore atteint, actions ne peut jamais être un tableau vide. Une stratégie sans action est alors invalide.
- Pour une cible d'abonnés supérieure au niveau actuel, construis le programme concret nécessaire pour réduire cet écart. N'ajoute une phase profil, contenu, preuve, variation, conversion ou mesure que si elle est justifiée par le diagnostic.
- Zéro action n'est acceptable que si l'objectif est déjà atteint ; indique alors explicitement la preuve dans observed_facts et success_conditions.
- Chaque action doit être spécifique : preuve ou raison, tâche concrète, format, angle, livrable, CTA si utile, KPI et échéance.
- requires_post_generation=true uniquement si l'action doit créer un contenu éditorial publiable (post, Reel, vidéo, image, série de contenus ou variation éditoriale).
- requires_post_generation=false pour les actions opérationnelles sans post : profil/bio, lien, CTA de profil, landing page, offre, formulaire, configuration, mesure/KPI, reporting, audit, checklist interne ou autre tâche manuelle.
- Une action avec requires_post_generation=false reste planifiable dans le calendrier mais ne doit jamais créer de sujet.
- Ne crée pas d'action vague comme publier régulièrement ou améliorer l'engagement sans préciser comment.

RÈGLE OBLIGATOIRE BIO / PROFIL
- Avant toute action concernant la bio, la description, la promesse ou le profil, examine network_snapshot.profile du COMPTE SÉLECTIONNÉ.
- biography_available=true signifie que le texte actuel du profil a réellement été récupéré (il peut être vide). biography_available=false signifie que tu ne peux pas conclure qu'une réécriture est nécessaire.
- N'ajoute jamais une action profil/bio par habitude ou simplement parce qu'elle est un quick win classique.
- Si biography_available=false, n'ajoute aucune action de réécriture de bio/profil : la nécessité ne peut pas être vérifiée à partir du compte.
- Si biography_available=true, compare la bio actuelle à l'objectif, à l'offre, à l'audience et au CTA attendu. Si elle est déjà suffisamment claire et cohérente, n'ajoute aucune action profil/bio et remplace-la par une action réellement utile.
- Si une modification est nécessaire, l'action doit avoir category="profil", requires_post_generation=false et profile_update.change_needed=true.
- profile_update.current_text doit reprendre le texte actuel réellement disponible, sans l'inventer. Une chaîne vide est autorisée si la bio récupérée est réellement vide.
- profile_update.reason doit expliquer le défaut concret observé.
- profile_update.proposed_text doit contenir la NOUVELLE BIO / DESCRIPTION FINALE complète, prête à copier-coller et adaptée au réseau du compte.
- La description de l'action doit inclure explicitement « Bio proposée : » suivi du texte final proposé.
- Le deliverable doit contenir le texte final proposé afin qu'il soit visible directement dans la tâche/calendrier.

MEDIA_PREFILL
Chaque action doit contenir media_prefill avec uniquement les valeurs acceptées :
- media_type : "image" ou "video"
- image_styles : 0 à 2 valeurs parmi
  "photo_realiste","illustration_b2b","mockup_saas","infographie","isometrique","flat_design","3d","cover_linkedin","visuel_reel","avatar","objet_anime"
- video_styles : 0 à 2 valeurs parmi
  "demo_produit","video_explicative","avant_apres","storytelling_court","motion_design","video_realiste","avatar","objet_anime"
- aspect_ratio : "1:1","4:5","9:16" ou "16:9"
- instructions : consigne directement exploitable par le générateur
- video_scenario_text : scénario court seulement si media_type = "video", sinon ""

CLASSIFICATIONS
- feasibility_code, confidence_code : "low","medium","high"
- awareness_code : "unaware","problem_aware","solution_aware","product_aware","ready_to_buy"
- decision_stage_code : "discovery","consideration","conversion","retention"
- pace : "aggressive","balanced","conservative"
Les champs lisibles associés doivent être rédigés dans la langue utilisateur.

RÉPONSE
Retourne uniquement un JSON valide, sans markdown ni commentaire, selon ce schéma :

{{
  "strategy":{{
    "title":"","executive_summary":"",
    "objective":{{"goal":"","target":"","duration_days":0,"feasibility_code":"medium","feasibility":"","conditions":[]}},
    "account_overview":{{"account_type":"","what_it_does":"","promoted_offer":"","target_audience":"","positioning":"","content_style":"","credibility_signals":[],"data_limits":[]}},
    "profile_analysis":{{"summary":"","strengths":[{{"title":"","evidence":"","impact":""}}],"weaknesses":[{{"title":"","evidence":"","impact":""}}],"improvement_axes":[{{"title":"","why":"","expected_effect":""}}]}},
    "diagnostic":{{"profile_maturity":0,"positioning_clarity":0,"content_consistency":0,"audience_fit":0,"conversion_readiness":0,"growth_potential":0}},
    "observed_facts":[], "assumptions_to_validate":[],
    "positioning":{{"promise":"","proof_to_build":"","differentiation":"","tone":""}},
    "audience_strategy":{{"primary":"","secondary":"","pain_points":[],"content_expectations":[]}},
    "target_analysis":{{"primary_target":"","secondary_targets":[],"persona":"","segment":"","awareness_code":"problem_aware","awareness_level":"","decision_stage_code":"discovery","decision_stage":"","pain_points":[],"desired_outcomes":[],"objections":[],"triggers":[],"content_angles":[],"targeting_reason":"","confidence_code":"medium","confidence":"","excluded_targets":[]}},
    "content_pillars":[{{"name":"","purpose":"","formats":[],"frequency":"","examples":[],"evidence":""}}],
    "cadence":{{"weekly_frequency":"","recommended_days":[],"engagement_routine":"","production_process":""}},
    "kpis":[{{"name":"","baseline":"","target":"","formula":"","source":""}}],
    "expert_marketing_review":{{"user_request_interpretation":"","expert_reframe":"","feasibility_code":"medium","feasibility":"","main_leverage":"","reason":"","risk":"","next_best_action":""}},
    "objective_timeline":{{"max_days":0,"estimated_days_to_target":0,"confidence":"medium","reason":"","pace":"balanced"}},
    "adaptive_control":{{"tracking_metric":"","baseline_value":null,"target_value":null,"checkpoints":[{{"offset_ratio":0.33,"expected_progress_ratio":0.3,"if_behind":"","if_on_track":""}}],"corrective_playbook":[]}},
    "resources_needed":[], "do_not_do":[], "success_conditions":[]
  }},
  "actions":[
    {{
      "title":"","description":"","category":"content","priority":"high","due_day":1,
      "evidence":"","format":"","angle":"","cta":"","deliverable":"",
      "requires_post_generation":true,
      "profile_update":{{"change_needed":false,"current_text":"","reason":"","proposed_text":""}},
      "kpi":{{"name":"","target":"","baseline":"","reason":""}},
      "calendar_slot":{{"recommended_offset_days":1,"recommended_hour":11,"spacing_group":"education","reason":""}},
      "media_prefill":{{"media_type":"image","image_styles":["illustration_b2b"],"video_styles":[],"aspect_ratio":"4:5","instructions":"","video_scenario_text":""}}
    }}
  ]
}}

PLANIFICATION INTELLIGENTE OBLIGATOIRE :
- Ne donne jamais le même calendar_slot.recommended_offset_days à plusieurs actions lorsque la durée permet de les séparer.
- Répartis les actions sur l'horizon réaliste, sans tout concentrer au début.
- Ordre logique : 1. quick_win (profil, cadrage) ; 2. proof/education (preuve, pédagogie) ; 3. conversion (CTA, offre, leads) ; 4. measurement (KPI, analyse).
- Les actions high peuvent commencer plus tôt, mais elles ne doivent pas toutes être programmées le même jour.
- spacing_group uniquement parmi : quick_win, proof, education, conversion, measurement.
- La mesure et l'analyse doivent arriver après suffisamment d'exécution, généralement dans les 20 derniers pour cent de l'horizon.

QUALITÉ DES ACTIONS OBLIGATOIRE :
- Ne crée jamais une action autonome de type routine d'interaction (commenter, liker, suivre, réponses génériques).
- Chaque action doit produire un résultat concret et vérifiable.
- Le nombre d'actions est entièrement libre : conserve seulement les étapes nécessaires.
- Ne complète jamais la liste pour atteindre un minimum et ne la tronque jamais pour respecter un maximum arbitraire.

Contraintes finales :
- 3 éléments maximum dans strengths, weaknesses et improvement_axes.
- 4 éléments maximum dans les autres tableaux.
- Tous les scores diagnostic sont des entiers de 0 à 10.
- due_day et calendar_slot.recommended_offset_days restent entre 1 et la durée demandée.
- recommended_hour reste entre 7 et 21.
- JSON strictement parsable.

CONTEXTE COMPACT :
{json.dumps(context, ensure_ascii=False)}"""


# ---------------------------------------------------------------------------
# A.6 — Réessayer programme stratégie
# ---------------------------------------------------------------------------

RETRY_STRATEGY_SYSTEM = (
    "Retourne uniquement un objet JSON valide. Aucun markdown. "
    "Le nombre d'actions est libre mais zéro action est interdit si l'objectif reste non atteint."
)

def build_retry_strategy_prompt(strategy_context: dict, first_output: str, retry_reason: str) -> str:
    return f"""Tu corriges une première analyse de stratégie qui n'a pas fourni de programme d'actions exploitable alors que l'objectif reste à atteindre.

RÈGLE ABSOLUE
- Retourne un JSON strictement valide.
- Le tableau actions doit contenir uniquement les actions réellement nécessaires pour atteindre l'objectif.
- Aucun minimum et aucun maximum arbitraire. Ne crée aucune action de remplissage.
- Ne crée aucune routine autonome de commentaires, likes, follows ou réponses génériques.
- Chaque action doit correspondre directement à un diagnostic, une faiblesse, une opportunité ou une dépendance.
- Chaque action doit produire un livrable concret et vérifiable.
- requires_post_generation=true uniquement si l'action doit créer un contenu éditorial publiable.
- requires_post_generation=false pour les actions opérationnelles sans post.
- Toute action bio/profil doit être vérifiée contre strategy_context.network_snapshot.profile : ne la conserve que si biography_available=true et si le texte actuel montre réellement un écart avec l'objectif.
- Si biography_available=false, ne conclus pas qu'une réécriture est nécessaire.
- Une action bio/profil conservée doit contenir profile_update.change_needed=true, current_text, reason et proposed_text.
- Répartis les dates dans un ordre logique sur duration_days.
- Si une cible d'abonnés est supérieure au niveau actuel, actions ne peut pas être vide.

FORMAT DE SORTIE
{{
  "strategy":{{
    "title":"","executive_summary":"",
    "objective":{{"goal":"","target":"","duration_days":0,"feasibility_code":"medium","feasibility":"","conditions":[]}},
    "account_overview":{{"promoted_offer":"","target_audience":"","positioning":""}},
    "profile_analysis":{{"summary":"","strengths":[],"weaknesses":[],"improvement_axes":[]}},
    "observed_facts":[], "assumptions_to_validate":[],
    "positioning":{{"promise":"","proof_to_build":"","differentiation":"","tone":""}},
    "content_pillars":[], "kpis":[],
    "expert_marketing_review":{{"next_best_action":"","reason":"","risk":"","main_leverage":""}},
    "success_conditions":[]
  }},
  "actions":[
    {{
      "title":"","description":"","category":"contenu","priority":"high","due_day":1,
      "evidence":"","format":"","angle":"","cta":"","deliverable":"",
      "requires_post_generation":true,
      "profile_update":{{"change_needed":false,"current_text":"","reason":"","proposed_text":""}},
      "kpi":{{"name":"","target":"","baseline":"","reason":""}},
      "calendar_slot":{{"recommended_offset_days":1,"recommended_hour":11,"spacing_group":"proof","reason":""}},
      "media_prefill":{{"media_type":"image","image_styles":["illustration_b2b"],"video_styles":[],"aspect_ratio":"4:5","instructions":"","video_scenario_text":""}}
    }}
  ]
}}

CONTEXTE DE LA STRATÉGIE :
{json.dumps(strategy_context, ensure_ascii=False)}

PREMIÈRE RÉPONSE À CORRIGER :
{first_output}

RAISON DE LA SECONDE PASSE :
{retry_reason}"""


# ---------------------------------------------------------------------------
# A.8 — Worker : Générer post (agent du cron minute)
# ---------------------------------------------------------------------------

WORKER_GENERATE_SYSTEM = "Réponds uniquement avec un JSON valide, sans markdown ni commentaire."

def build_worker_generate_prompt(
    subject: str, commercial_objective: str, target_sector: str, language: str,
    preferred_formats: list, target_audience: list, constraints: str, prompt: str,
) -> str:
    # Port strict du nœud n8n « Worker - Generate with OpenRouter ».
    return f"""Tu es un rédacteur social media B2B expérimenté. Tu dois transformer une action de stratégie en UNE idée de contenu et en UN véritable post directement publiable.

Contexte de la demande :
- Sujet : {subject}
- Objectif commercial : {commercial_objective}
- Secteur : {target_sector}
- Langue : {language}
- Formats privilégiés : {json.dumps(preferred_formats, ensure_ascii=False, separators=(",", ":"))}
- Public cible : {json.dumps(target_audience, ensure_ascii=False, separators=(",", ":"))}
- Contraintes : {constraints}
- Contexte stratégique complet : {prompt}

Règles impératives :
- Utilise le contexte stratégique pour comprendre l’angle, mais ne recopie jamais les instructions internes dans le post.
- Le texte final ne doit jamais contenir les libellés « Objectif stratégique », « Action à transformer en contenu », « Livrable attendu », « Persona » ou « Contrainte de planning IA ».
- Ne transforme pas la liste des métriques brutes en paragraphe. Utilise-les seulement pour choisir un angle crédible.
- Ne prétends pas avoir des résultats, études, clients ou chiffres qui ne sont pas fournis.
- Le post doit être naturel, concret, professionnel et adapté au format demandé.
- Le post doit contenir une seule action claire, placée en dernier paragraphe.
- ready_post.text doit mesurer entre 250 et 1 500 caractères.
- Fournis entre 5 et 10 hashtags pertinents.
- Retourne uniquement du JSON valide, sans markdown.

Format exact :
{{
  "ideas": [
    {{
      "title": "Titre éditorial de l’idée",
      "hook": "Accroche courte",
      "summary": "Résumé de l’angle",
      "business_problem_solved": "Problème métier traité",
      "ai_or_software_solution": "Solution ou approche mise en avant",
      "target_sector": "Secteur cible",
      "target_audience": "Public cible",
      "virality_score": 7,
      "commercial_potential_score": 8,
      "implementation_difficulty_score": 3,
      "recommended_format": "Format recommandé",
      "why_interesting_today": "Pourquoi cet angle est pertinent",
      "call_to_action": "Action finale exacte",
      "hashtags": ["#Hashtag1", "#Hashtag2", "#Hashtag3", "#Hashtag4", "#Hashtag5"],
      "sme_interest_score": 8,
      "enterprise_interest_score": 7,
      "lead_generation_score": 8,
      "concrete_application_example": "Exemple concret",
      "seo_keywords": ["mot clé 1", "mot clé 2"],
      "ready_post": {{
        "title": "Titre du post",
        "text": "Texte complet et directement publiable, avec le CTA comme dernier paragraphe.",
        "simple_action": "Action finale exacte",
        "tags": ["#Hashtag1", "#Hashtag2", "#Hashtag3", "#Hashtag4", "#Hashtag5"]
      }}
    }}
  ]
}}"""

# ---------------------------------------------------------------------------
# Stratégie robuste segmentée — génération en plusieurs objets JSON bornés
# ---------------------------------------------------------------------------

GENERATE_STRATEGY_PLAN_SYSTEM = (
    "Tu produis uniquement un objet JSON strictement valide, sans markdown. "
    "Tu génères le diagnostic complet et un plan d'actions compact, jamais les actions détaillées."
)


def build_generate_strategy_plan_prompt(context: dict[str, Any]) -> str:
    retry_note = ""
    if context.get("_retry_reason"):
        retry_note = (
            "\nSECONDE ANALYSE : " + str(context.get("_retry_reason"))
            + "\nCorrige le diagnostic/plan précédent sans recopier une erreur."
        )
    minimum_actions = int(context.get("minimum_action_count") or 0)
    return f"""Tu es un consultant senior en stratégie de croissance organique pour les réseaux sociaux.

MISSION
Construis le DIAGNOSTIC COMPLET et le PLAN COMPACT des actions. Les détails de chaque action seront générés ensuite par d'autres appels : ta réponse doit donc rester compacte.

RÈGLES FACTUELLES
- Utilise uniquement les faits du contexte. Toute déduction non vérifiée va dans assumptions_to_validate.
- N'invente aucun chiffre, client, résultat, concurrent ou tendance.
- Respecte form_data.language et duration_days.
- objective_already_reached=true UNIQUEMENT si les données observées prouvent explicitement que l'objectif quantifiable est déjà atteint.
- Si objective_already_reached=false, action_blueprints doit contenir au moins {minimum_actions} actions, soit au minimum 3 posts par semaine.
- Toutes les actions sont des posts publiables : category="content" et requires_post_generation=true.
- Ne propose jamais de créer un calendrier, un planning, un audit, un reporting, un profil ou une tâche manuelle.
- Ne crée aucune routine autonome de likes/commentaires/follows.
- Chaque blueprint correspond à un livrable concret et vérifiable.
- Une action profil/bio n'est autorisée que si network_snapshot.biography_available=true et si la bio réellement lue justifie une modification.
- requires_post_generation=true uniquement pour un contenu publiable.
- Répartis due_day sur l'horizon, sans concentrer toutes les actions le même jour.
- Le nombre d'actions est déterminé par le diagnostic ; il ne peut toutefois pas dépasser le nombre de jours disponibles.
- Valeurs techniques : feasibility_code/confidence_code=low|medium|high ; awareness_code=unaware|problem_aware|solution_aware|product_aware|ready_to_buy ; decision_stage_code=discovery|consideration|conversion|retention ; pace=aggressive|balanced|conservative.
- Scores diagnostic : entiers 0..10.
- Maximum 3 strengths/weaknesses/improvement_axes et 4 éléments dans les autres tableaux de stratégie.
- Chaque valeur textuelle doit rester concise (environ 280 caractères maximum).

FORMAT STRICT
{{
  "strategy":{{
    "title":"","executive_summary":"","objective_already_reached":false,
    "objective":{{"goal":"","target":"","duration_days":0,"feasibility_code":"medium","feasibility":"","conditions":[]}},
    "account_overview":{{"account_type":"","what_it_does":"","promoted_offer":"","target_audience":"","positioning":"","content_style":"","credibility_signals":[],"data_limits":[]}},
    "profile_analysis":{{"summary":"","strengths":[{{"title":"","evidence":"","impact":""}}],"weaknesses":[{{"title":"","evidence":"","impact":""}}],"improvement_axes":[{{"title":"","why":"","expected_effect":""}}]}},
    "diagnostic":{{"profile_maturity":0,"positioning_clarity":0,"content_consistency":0,"audience_fit":0,"conversion_readiness":0,"growth_potential":0}},
    "observed_facts":[],"assumptions_to_validate":[],
    "positioning":{{"promise":"","proof_to_build":"","differentiation":"","tone":""}},
    "audience_strategy":{{"primary":"","secondary":"","pain_points":[],"content_expectations":[]}},
    "target_analysis":{{"primary_target":"","secondary_targets":[],"persona":"","segment":"","awareness_code":"problem_aware","awareness_level":"","decision_stage_code":"discovery","decision_stage":"","pain_points":[],"desired_outcomes":[],"objections":[],"triggers":[],"content_angles":[],"targeting_reason":"","confidence_code":"medium","confidence":"","excluded_targets":[]}},
    "content_pillars":[{{"name":"","purpose":"","formats":[],"frequency":"","examples":[],"evidence":""}}],
    "cadence":{{"weekly_frequency":"","recommended_days":[],"engagement_routine":"","production_process":""}},
    "kpis":[{{"name":"","baseline":"","target":"","formula":"","source":""}}],
    "expert_marketing_review":{{"user_request_interpretation":"","expert_reframe":"","feasibility_code":"medium","feasibility":"","main_leverage":"","reason":"","risk":"","next_best_action":""}},
    "objective_timeline":{{"max_days":0,"estimated_days_to_target":0,"confidence":"medium","reason":"","pace":"balanced"}},
    "adaptive_control":{{"tracking_metric":"","baseline_value":null,"target_value":null,"checkpoints":[{{"offset_ratio":0.33,"expected_progress_ratio":0.3,"if_behind":"","if_on_track":""}}],"corrective_playbook":[]}},
    "resources_needed":[],"do_not_do":[],"success_conditions":[]
  }},
  "action_blueprints":[
    {{"plan_id":"a1","title":"","category":"content","priority":"high","due_day":1,"requires_post_generation":true,"reason":"","evidence":""}}
  ]
}}

CONTEXTE :
{json.dumps(context, ensure_ascii=False)}{retry_note}"""


GENERATE_STRATEGY_ACTIONS_SYSTEM = (
    "Tu produis uniquement un objet JSON strictement valide, sans markdown. "
    "Tu détailles exactement les actions demandées et conserves chaque plan_id à l'identique."
)


def build_generate_strategy_actions_prompt(*, context: dict[str, Any], strategy: dict, blueprints: list[dict]) -> str:
    compact_network = dict(context.get("network_snapshot") or {})
    compact_network.pop("recent_content", None)
    compact_context = {
        "form_data": context.get("form_data") or {},
        "network_snapshot": compact_network,
        "research_context": context.get("research_context") or {},
    }
    return f"""Tu transformes un petit lot de blueprints d'une stratégie déjà validée en actions opérationnelles complètes.

RÈGLES ABSOLUES
- Retourne EXACTEMENT {len(blueprints)} actions, dans le même ordre.
- Copie plan_id, title, category, priority, due_day et requires_post_generation de chaque blueprint sans les changer.
- Chaque description doit être concrète, directement exécutable et inclure le livrable.
- category=profil : seulement si la bio a réellement été récupérée et si une modification est justifiée ; profile_update.change_needed=true, current_text exact, reason et proposed_text final prêt à copier-coller.
- category=content : requires_post_generation=true seulement si un contenu éditorial doit être généré.
- media_type=image|video ; aspect_ratio=1:1|4:5|9:16|16:9.
- image_styles : max 2 parmi photo_realiste,illustration_b2b,mockup_saas,infographie,isometrique,flat_design,3d,cover_linkedin,visuel_reel,avatar,objet_anime.
- video_styles : max 2 parmi demo_produit,video_explicative,avant_apres,storytelling_court,motion_design,video_realiste,avatar,objet_anime.
- recommended_hour entre 7 et 21 ; spacing_group=quick_win|proof|education|conversion|measurement.
- N'invente aucun résultat ou preuve.
- JSON complet ; aucune phrase hors JSON.

FORMAT STRICT
{{"actions":[{{
  "plan_id":"a1","title":"","description":"","category":"content","priority":"high","due_day":1,
  "evidence":"","format":"","angle":"","cta":"","deliverable":"","requires_post_generation":true,
  "profile_update":{{"change_needed":false,"current_text":"","reason":"","proposed_text":""}},
  "kpi":{{"name":"","target":"","baseline":"","reason":""}},
  "calendar_slot":{{"recommended_offset_days":1,"recommended_hour":11,"spacing_group":"education","reason":""}},
  "media_prefill":{{"media_type":"image","image_styles":["illustration_b2b"],"video_styles":[],"aspect_ratio":"4:5","instructions":"","video_scenario_text":""}}
}}]}}

STRATÉGIE VALIDÉE :
{json.dumps(strategy, ensure_ascii=False)}

BLUEPRINTS DE CE LOT :
{json.dumps(blueprints, ensure_ascii=False)}

CONTEXTE FACTUEL COMPACT :
{json.dumps(compact_context, ensure_ascii=False)}"""
