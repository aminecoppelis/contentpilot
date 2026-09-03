import os

os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost/post_generator")
os.environ.setdefault("APP_BASE_URL", "https://socialnetwork.coppelis.com")
os.environ.setdefault("TRUST_PROXY_HEADERS", "true")

from starlette.requests import Request

from app.config import get_settings
from app.public_origin import resolve_public_origin


def _request(host: str, proto: str = "https") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "scheme": "http",
        "path": "/app/networks/meta/config",
        "raw_path": b"/app/networks/meta/config",
        "query_string": b"",
        "headers": [
            (b"host", b"127.0.0.1:8000"),
            (b"x-forwarded-host", host.encode()),
            (b"x-forwarded-proto", proto.encode()),
        ],
        "server": ("127.0.0.1", 8000),
        "client": ("127.0.0.1", 40000),
    }
    return Request(scope)


def test_https_proxy_origin_tracks_instance_domain():
    get_settings.cache_clear()
    assert resolve_public_origin(_request("socialnetwork.coppelis.com", "https")) == "https://socialnetwork.coppelis.com"


def test_internal_http_proxy_cannot_downgrade_configured_https_origin():
    get_settings.cache_clear()
    assert resolve_public_origin(_request("socialnetwork.coppelis.com", "http")) == "https://socialnetwork.coppelis.com"


def test_https_proxy_can_use_another_instance_domain_automatically():
    get_settings.cache_clear()
    assert resolve_public_origin(_request("social-alt.coppelis.com", "https")) == "https://social-alt.coppelis.com"
