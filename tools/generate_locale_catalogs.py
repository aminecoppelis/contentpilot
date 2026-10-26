"""Generate additional UI locale catalogs from the canonical French catalog.

This one-off maintenance helper preserves interpolation placeholders and HTML
tags while translating values through the public Google Translate endpoint.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "translations" / "fr.json"
TARGETS = {"es": "es", "it": "it", "de": "de", "ru": "ru"}
TOKEN_RE = re.compile(r"(\{[^{}]+\}|<[^<>]+>|https?://\S+)")


def protect(value: str) -> tuple[str, list[str]]:
    tokens: list[str] = []

    def repl(match: re.Match[str]) -> str:
        tokens.append(match.group(0))
        return f"ZXQPH{len(tokens) - 1}QXZ"

    return TOKEN_RE.sub(repl, value), tokens


def restore(value: str, tokens: list[str]) -> str:
    for index, token in enumerate(tokens):
        marker = f"ZXQPH{index}QXZ"
        value = re.sub(re.escape(marker), lambda _match, t=token: t, value, flags=re.I)
    return value


def translate(value: str, target: str) -> str:
    if not value.strip():
        return value
    protected, tokens = protect(value)
    query = urllib.parse.urlencode(
        {"client": "gtx", "sl": "fr", "tl": target, "dt": "t", "q": protected}
    )
    url = f"https://translate.googleapis.com/translate_a/single?{query}"
    last_error: Exception | None = None
    for attempt in range(5):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "ContentPilot-i18n/1.0"})
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            result = "".join(part[0] for part in payload[0] if part and part[0])
            return restore(result, tokens)
        except Exception as exc:  # noqa: BLE001 - retry transient remote failures
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Translation failed for {target}: {value[:80]!r}") from last_error


def translate_batch(values: list[str], target: str) -> list[str]:
    separator = "ZXQSEPZXQ"
    joined = f"\n{separator}\n".join(values)
    result = translate(joined, target)
    parts = re.split(r"\s*ZXQSEPZXQ\s*", result, flags=re.I)
    if len(parts) != len(values):
        return [translate(value, target) for value in values]
    return parts


def env_value(name: str) -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def translate_object_with_ai(values: dict[str, str], locale: str) -> dict[str, str]:
    language_names = {"de": "German", "ru": "Russian"}
    payload = {
        "model": env_value("OPENROUTER_MODEL") or "openai/gpt-4o-mini",
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    f"Translate every JSON value into {language_names[locale]}. "
                    "Return one valid JSON object with exactly the same keys. Preserve all "
                    "placeholders such as {name}, URLs, HTML tags, punctuation and product names."
                ),
            },
            {"role": "user", "content": json.dumps(values, ensure_ascii=False)},
        ],
    }
    base = env_value("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1"
    request = urllib.request.Request(
        f"{base.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {env_value('OPENROUTER_API_KEY')}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        result = json.loads(response.read().decode("utf-8"))
    translated = json.loads(result["choices"][0]["message"]["content"])
    if set(translated) != set(values):
        raise ValueError("The AI translation response changed catalog keys")
    return {key: str(translated[key]) for key in values}


def main() -> None:
    source: dict[str, str] = json.loads(SOURCE.read_text(encoding="utf-8"))
    for locale, target in TARGETS.items():
        destination = ROOT / "translations" / f"{locale}.json"
        existing: dict[str, str] = {}
        if destination.exists():
            existing = json.loads(destination.read_text(encoding="utf-8"))
        translated: dict[str, str] = {
            key: existing[key] for key in source if existing.get(key)
        }
        pending = [(key, str(value)) for key, value in source.items() if key not in translated]
        for offset in range(0, len(pending), 80):
            batch = pending[offset : offset + 80]
            if locale in {"de", "ru"}:
                translated.update(translate_object_with_ai(dict(batch), locale))
            else:
                results = translate_batch([value for _key, value in batch], target)
                translated.update({key: value for (key, _source), value in zip(batch, results)})
            checkpoint = {key: translated[key] for key in source if key in translated}
            destination.write_text(
                json.dumps(checkpoint, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"{locale}: {len(translated)}/{len(source)}", flush=True)
        translated = {key: translated[key] for key in source}
        destination.write_text(
            json.dumps(translated, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"{locale}: complete ({len(translated)} keys)", flush=True)


if __name__ == "__main__":
    main()
