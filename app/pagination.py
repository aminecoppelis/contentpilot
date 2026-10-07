from __future__ import annotations

from math import ceil
from urllib.parse import urlencode


def page_meta(*, page: int, page_size: int, total: int, path: str, query: dict | None = None,
              fragment: str = "", page_param: str = "page") -> dict:
    total = max(0, int(total or 0))
    total_pages = max(1, ceil(total / page_size))
    page = min(max(1, int(page or 1)), total_pages)
    start = max(1, min(page - 2, total_pages - 4))
    end = min(total_pages, start + 4)
    encoded = urlencode({k: v for k, v in (query or {}).items() if v not in (None, "")})
    return {
        "page": page, "page_size": page_size, "total": total, "total_pages": total_pages,
        "first": (page - 1) * page_size + 1 if total else 0,
        "last": min(page * page_size, total), "pages": range(start, end + 1),
        "path": path, "query_prefix": f"{encoded}&" if encoded else "",
        "fragment": f"#{fragment.lstrip('#')}" if fragment else "",
        "page_param": page_param,
    }
