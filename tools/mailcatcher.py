#!/usr/bin/env python3
"""
Capteur d'emails local pour le développement — SANS AUCUNE DÉPENDANCE.

Implémente le minimum du protocole SMTP (RFC 5321) avec asyncio : au lieu de
relayer les messages, il les enregistre sur disque.

Pour chaque email reçu :
  - un fichier .eml complet (ouvrable dans n'importe quel client mail)
  - un fichier .html si le message contient une partie HTML
  - une ligne dans index.log : date, destinataire, sujet, lien d'action
  - un affichage console avec le lien cliquable (activation, invitation…)

Aucun Docker, aucun pip install, aucun téléchargement.

Usage :
  python3 tools/mailcatcher.py                 # 127.0.0.1:1025
  python3 tools/mailcatcher.py --port 2525
  python3 tools/mailcatcher.py --dir /var/log/post_generator/mails
"""
from __future__ import annotations

import argparse
import asyncio
import email
import email.policy
import re
from datetime import datetime
from pathlib import Path

LINK_RE = re.compile(r'https?://[^\s"\'<>]+')


class MailStore:
    def __init__(self, outdir: Path):
        self.outdir = outdir
        self.outdir.mkdir(parents=True, exist_ok=True)
        self.index = self.outdir / "index.log"
        self.count = 0

    def save(self, recipients: list[str], raw: bytes) -> None:
        self.count += 1
        try:
            msg = email.message_from_bytes(raw, policy=email.policy.default)
            subject = msg["Subject"] or "sans-sujet"
        except Exception:  # noqa: BLE001 - un mail malformé ne doit pas tuer le serveur
            msg, subject = None, "message-illisible"

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        slug = re.sub(r"[^a-z0-9]+", "-", subject.lower()).strip("-")[:50] or "mail"
        base = self.outdir / f"{stamp}-{self.count:03d}-{slug}"
        base.with_suffix(".eml").write_bytes(raw)

        html = None
        if msg is not None:
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    try:
                        html = part.get_content()
                    except Exception:  # noqa: BLE001
                        html = None
                    break
        if html:
            base.with_suffix(".html").write_text(html, encoding="utf-8")

        links = LINK_RE.findall(html or "")
        action = next((l for l in links if "/app/" in l), links[0] if links else "")

        with self.index.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} | "
                    f"{', '.join(recipients)} | {subject} | {action}\n")

        print(f"\n  [{self.count}] {subject}")
        print(f"      destinataire : {', '.join(recipients)}")
        if action:
            print(f"      lien         : {action}")
        print(f"      fichier      : {base.with_suffix('.html' if html else '.eml').name}")


class SMTPProtocol(asyncio.Protocol):
    """Implémentation minimale mais conforme du dialogue SMTP entrant."""

    def __init__(self, store: MailStore):
        self.store = store
        self.transport: asyncio.Transport | None = None
        self.buffer = b""
        self.in_data = False
        self.data = b""
        self.recipients: list[str] = []

    def connection_made(self, transport):
        self.transport = transport
        self._send("220 localhost Post Generator mailcatcher")

    def _send(self, line: str) -> None:
        if self.transport:
            self.transport.write(line.encode("utf-8", "replace") + b"\r\n")

    def data_received(self, chunk: bytes) -> None:
        self.buffer += chunk
        if self.in_data:
            self._consume_data()
        else:
            self._consume_commands()

    def _consume_data(self) -> None:
        # Fin du corps = ligne contenant uniquement un point
        marker = b"\r\n.\r\n"
        alt = b"\n.\n"
        idx = self.buffer.find(marker)
        size = len(marker)
        if idx < 0:
            idx = self.buffer.find(alt)
            size = len(alt)
        if idx < 0:
            return
        self.data += self.buffer[:idx]
        self.buffer = self.buffer[idx + size:]
        self.in_data = False
        # Dé-échappement du point initial (transparence SMTP)
        body = re.sub(rb"(?m)^\.\.", b".", self.data)
        try:
            self.store.save(self.recipients or ["(inconnu)"], body)
            self._send("250 OK message enregistre")
        except Exception as exc:  # noqa: BLE001
            print(f"      ERREUR d'enregistrement : {exc}")
            self._send("451 Erreur locale d'enregistrement")
        self.data = b""
        self.recipients = []
        self._consume_commands()

    def _consume_commands(self) -> None:
        while b"\n" in self.buffer and not self.in_data:
            line, self.buffer = self.buffer.split(b"\n", 1)
            self._handle(line.rstrip(b"\r").decode("utf-8", "replace"))
        if self.in_data and self.buffer:
            self._consume_data()

    def _handle(self, line: str) -> None:
        cmd = line.split(" ", 1)[0].upper() if line else ""
        arg = line[len(cmd):].strip()

        if cmd == "EHLO":
            self._send("250-localhost")
            self._send("250-8BITMIME")
            self._send("250 SIZE 33554432")
        elif cmd == "HELO":
            self._send("250 localhost")
        elif cmd == "MAIL":
            self.recipients = []
            self._send("250 OK")
        elif cmd == "RCPT":
            m = re.search(r"<([^>]*)>", arg)
            self.recipients.append(m.group(1) if m else arg.replace("TO:", "").strip())
            self._send("250 OK")
        elif cmd == "DATA":
            self.in_data = True
            self.data = b""
            self._send("354 Envoie le message, termine par une ligne contenant un point")
        elif cmd == "RSET":
            self.recipients, self.data, self.in_data = [], b"", False
            self._send("250 OK")
        elif cmd == "NOOP":
            self._send("250 OK")
        elif cmd == "QUIT":
            self._send("221 Au revoir")
            if self.transport:
                self.transport.close()
        elif cmd in ("STARTTLS", "AUTH"):
            # Capteur local : ni TLS ni authentification nécessaires
            self._send("502 Commande non prise en charge par le capteur local")
        elif cmd:
            self._send("250 OK")


async def serve(host: str, port: int, outdir: Path) -> None:
    store = MailStore(outdir)
    loop = asyncio.get_running_loop()
    server = await loop.create_server(lambda: SMTPProtocol(store), host, port)

    print("+--------------------------------------------------------+")
    print("|  Capteur d'emails local — Post Generator                |")
    print("+--------------------------------------------------------+")
    print(f"  Ecoute   : {host}:{port}")
    print(f"  Stockage : {outdir}")
    print(f"  Journal  : {outdir / 'index.log'}")
    print()
    print(f"  Dans .env :  SMTP_HOST={host}   SMTP_PORT={port}")
    print("  Ctrl+C pour arreter.")

    async with server:
        await server.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capteur d'emails local (aucune dependance).",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1025)
    parser.add_argument("--dir", default="./tmp/mails")
    args = parser.parse_args()

    outdir = Path(args.dir).expanduser().resolve()
    try:
        asyncio.run(serve(args.host, args.port, outdir))
    except KeyboardInterrupt:
        print("\nArret du capteur.")
    except OSError as exc:
        print(f"Impossible d'ecouter sur {args.host}:{args.port} : {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
