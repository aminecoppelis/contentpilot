"""
Configuration centralisée (variables d'environnement uniquement).

Rappel architectural (voir Cahier technique §1 / Addendum §9) :
- Ici : uniquement la configuration d'INFRASTRUCTURE (jamais modifiable sans
  redéploiement : DB, cookies, SMTP serveur, clé OpenRouter).
- La configuration MÉTIER (App ID Meta, clé Serper, clé Buffer par
  utilisateur...) vit en base dans `app_integration_settings` /
  `app_social_accounts`, lue à l'exécution par app/services/settings.py,
  JAMAIS ici. Ne pas mélanger les deux catégories.
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Infrastructure
    database_url: str
    app_base_url: str = "https://socialnetwork.coppelis.com"
    app_timezone: str = "Europe/Paris"
    # Par défaut les médias restent DANS le projet : <project>/public-media/.
    # MEDIA_STORAGE_DIR peut rester relatif ; il sera résolu depuis PROJECT_ROOT,
    # et non depuis le répertoire courant du process.
    media_storage_dir: str = "public-media"
    media_public_base_url: str = "https://socialnetwork.coppelis.com/public-media"
    trust_proxy_headers: bool = True
    env: str = "development"
    log_level: str = "info"

    # Session (voir Cahier technique §3.5 / §4.1)
    session_cookie_name: str = "pg_session"
    session_cookie_secure: bool = False
    session_ttl_hours: int = 720

    # SMTP
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "Post Generator <support@coppelis.com>"
    smtp_use_tls: bool = False
    smtp_start_tls: bool = False
    smtp_timeout: int = 15

    @property
    def media_storage_path(self) -> Path:
        """Chemin absolu du stockage média, ancré sur la racine du projet."""
        configured = Path((self.media_storage_dir or "public-media").strip())
        if configured.is_absolute():
            return configured.resolve()
        return (PROJECT_ROOT / configured).resolve()

    @property
    def smtp_enabled(self) -> bool:
        """SMTP considéré actif seulement si un hôte est renseigné.
        Laisser SMTP_HOST vide désactive proprement l'envoi d'emails :
        l'application fonctionne, les liens d'activation sont journalisés."""
        return bool((self.smtp_host or "").strip())

    # OpenRouter (agents IA — voir Cahier technique §9)
    openrouter_api_key: str = ""
    openrouter_model: str = "openai/gpt-4o-mini"
    # Stratégie : paramètres identiques au nœud OpenRouter n8n validé en production.
    openrouter_strategy_model: str = "openai/gpt-4.1-mini"
    openrouter_strategy_max_tokens: int = 2200
    openrouter_strategy_temperature: float = 0.3
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # Garde-fous des sorties JSON structurées. Le second/3e essai augmente
    # automatiquement le budget si OpenRouter coupe la réponse.
    openrouter_max_output_tokens: int = 12000
    openrouter_json_attempts: int = 3

    # Worker planifié (Cahier technique §8)
    worker_lock_minutes: int = 15
    worker_max_attempts: int = 3
    disable_scheduler: bool = False  # --no-worker : API seule, sans cron

    # Applique les migrations manquantes au démarrage (recommandé).
    # Les migrations étant idempotentes et transactionnelles, l'opération est
    # sans risque ; passer à false pour piloter le schéma manuellement.
    auto_migrate: bool = True

    # Chiffrement des jetons OAuth (Addendum §11)
    token_encryption_key: str = ""


@lru_cache
def get_settings() -> Settings:
    """
    Charge la configuration. Les erreurs de lecture du .env sont converties
    en message explicite : un PermissionError brut au milieu d'une trace
    pydantic n'indique pas la cause réelle (fichier créé par root alors que
    le service tourne sous un autre utilisateur).
    """
    import os
    import pwd

    try:
        return Settings()
    except PermissionError as exc:
        path = os.path.abspath(".env")
        try:
            owner = pwd.getpwuid(os.stat(path).st_uid).pw_name
            mode = oct(os.stat(path).st_mode & 0o777)
        except Exception:  # noqa: BLE001
            owner, mode = "inconnu", "inconnu"
        current = pwd.getpwuid(os.getuid()).pw_name
        raise RuntimeError(
            f"Impossible de lire {path} : {exc}\n"
            f"  Fichier appartenant à '{owner}' (mode {mode}), "
            f"processus lancé par '{current}'.\n"
            f"  Correction : sudo chown {current}:{current} {path}"
        ) from exc
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Fichier .env introuvable. Lance d'abord : ./install.sh"
        ) from exc
