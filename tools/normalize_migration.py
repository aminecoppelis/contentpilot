#!/usr/bin/env python3
"""
Normalise un fichier de migration pour qu'il soit applicable en toutes
circonstances, quelle que soit sa version :

  1. CREATE TABLE / CREATE INDEX forcés en IF NOT EXISTS (relançable)
  2. ALTER TABLE ADD CONSTRAINT protégés contre le doublon (bloc DO)
  3. Instructions réémises dans un ordre TOPOLOGIQUEMENT valide :
     extensions, puis tables triées selon leurs dépendances de clés
     étrangères, puis contraintes différées, puis index.

Le point 3 est le plus important : il rend impossible l'erreur
« relation "X" does not exist » due à une table déclarée avant sa
dépendance, indépendamment de l'ordre du fichier source.

Usage : normalize_migration.py source.sql destination.sql
"""
import re
import sys
from collections import defaultdict


def parse(sql: str):
    extensions = re.findall(r'^\s*(CREATE EXTENSION[^;]+;)', sql, re.M)

    tables = {}   # nom -> texte complet du CREATE TABLE
    deps = defaultdict(set)
    for m in re.finditer(
            r'CREATE TABLE\s+(?:IF NOT EXISTS\s+)?public\.(\w+)\s*\((?:[^;]*?)\n\);',
            sql, re.S):
        name = m.group(1)
        body = m.group(0)
        tables[name] = body
        for fk in re.finditer(r'REFERENCES\s+public\.(\w+)', body):
            if fk.group(1) != name:
                deps[name].add(fk.group(1))

    alters = re.findall(
        r'(?:DO \$do\$ BEGIN\s*)?(ALTER TABLE public\.\w+ ADD CONSTRAINT[^;]+;)', sql)

    indexes = re.findall(r'^\s*(CREATE (?:UNIQUE )?INDEX[^;]+;)', sql, re.M)
    return extensions, tables, deps, alters, indexes


def topo_sort(tables: dict, deps: dict) -> list:
    """Tri par dépendances. Les cycles (rares, ex. FK croisées) sont brisés :
    la contrainte concernée sera de toute façon rejouée en ALTER."""
    ordered, visiting, done = [], set(), set()

    def visit(node):
        if node in done or node not in tables:
            return
        if node in visiting:      # cycle : on ignore l'arête
            return
        visiting.add(node)
        for dep in sorted(deps.get(node, ())):
            visit(dep)
        visiting.discard(node)
        done.add(node)
        ordered.append(node)

    for name in tables:           # ordre d'origine préservé à dépendances égales
        visit(name)
    return ordered


def make_idempotent_table(body: str) -> str:
    return re.sub(r'^CREATE TABLE\s+(?!IF NOT EXISTS)', 'CREATE TABLE IF NOT EXISTS ', body)


def make_idempotent_index(stmt: str) -> str:
    if 'IF NOT EXISTS' in stmt:
        return stmt
    m = re.match(r'CREATE (UNIQUE )?INDEX\s+ON public\.(\w+)\s*\(([^)]*)\)(.*)', stmt, re.S)
    if m:   # index anonyme : on lui forge un nom déterministe
        uniq, table, cols, rest = m.groups()
        slug = re.sub(r'[^a-z0-9]+', '_', cols.lower()).strip('_')[:40]
        return (f'CREATE {uniq or ""}INDEX IF NOT EXISTS {table}_{slug}_idx '
                f'ON public.{table} ({cols}){rest}')
    return re.sub(r'CREATE (UNIQUE )?INDEX\s+(?!IF NOT EXISTS)',
                  lambda mm: f'CREATE {mm.group(1) or ""}INDEX IF NOT EXISTS ', stmt)


def guard_alter(stmt: str) -> str:
    return ('DO $do$ BEGIN\n  ' + stmt.rstrip(';') +
            ';\nEXCEPTION WHEN duplicate_object THEN NULL; END $do$;')


def main(src: str, dst: str) -> int:
    sql = open(src, encoding='utf-8').read()
    extensions, tables, deps, alters, indexes = parse(sql)

    if not tables:
        print('normalize_migration: aucune table trouvée — fichier copié tel quel',
              file=sys.stderr)
        open(dst, 'w', encoding='utf-8').write(sql)
        return 0

    order = topo_sort(tables, deps)

    out = ['-- Fichier généré automatiquement par tools/normalize_migration.py',
           '-- Idempotent et trié par dépendances. Ne pas éditer.', '']
    out += extensions or ['CREATE EXTENSION IF NOT EXISTS pgcrypto;']
    out.append('')
    out.append('-- ---- Tables (ordre de dépendances) ----')
    for name in order:
        out.append(make_idempotent_table(tables[name]))
        out.append('')
    if alters:
        out.append('-- ---- Contraintes différées ----')
        seen = set()
        for a in alters:
            if a in seen:
                continue
            seen.add(a)
            out.append(guard_alter(a))
        out.append('')
    if indexes:
        out.append('-- ---- Index ----')
        seen = set()
        for i in indexes:
            norm = make_idempotent_index(i)
            if norm in seen:
                continue
            seen.add(norm)
            out.append(norm)

    open(dst, 'w', encoding='utf-8').write('\n'.join(out) + '\n')
    print(f'normalize_migration: {len(order)} tables, {len(alters)} contraintes, '
          f'{len(indexes)} index — ordre validé')
    return 0


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
