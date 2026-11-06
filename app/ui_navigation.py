"""Presentation-only navigation. Never creates routes or changes business actions."""


def breadcrumb_items(request, translate):
    path = request.url.path.rstrip("/")
    home = {"text": translate("nav.home"), "url": "/app/dashboard"}
    sections = {
        "/app/posts": ("nav.subjects", "/app/posts"),
        "/app/strategies": ("nav.strategies", "/app/strategies"),
        "/app/networks": ("nav.networks", "/app/networks"),
        "/app/published": ("nav.published", "/app/published"),
        "/app/history": ("nav.subjects", "/app/posts"),
        "/app/account": ("nav.account", "/app/account"),
        "/app/workspace": ("nav.workspace", "/app/workspace"),
        "/app/admin": ("nav.admin", "/app/admin/settings"),
    }
    if path == "/app/dashboard":
        return [{**home, "url": ""}]
    parent = next((prefix for prefix in sections if path == prefix or path.startswith(prefix + "/")), None)
    if not parent:
        return []
    key, url = sections[parent]
    items = [home, {"text": translate(key), "url": url}]
    child = {
        "/app/posts/new": "js.shell.create",
        "/app/posts/view": "js.shell.post",
        "/app/posts/edit": "js.shell.edit",
        "/app/posts/ideas-page": "js.shell.variants",
        "/app/strategies/new": "strat.new",
        "/app/networks/meta/config": "js.shell.settings",
        "/app/admin/users": "js.shell.users",
        "/app/admin/workspaces/setup": "nav.workspace",
    }.get(path)
    if path == "/app/strategies" and request.query_params.get("strategy_id"):
        child = "js.shell.strategy"
    if path == "/app/history":
        child = "js.shell.history"
    if child:
        items.append({"text": translate(child), "url": ""})
    else:
        items[-1]["url"] = ""
    return items
