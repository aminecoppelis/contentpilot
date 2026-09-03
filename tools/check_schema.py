#!/usr/bin/env python3
"""
Vérifie que toutes les colonnes référencées par le code existent bien
dans le schéma déclaré par les migrations.

Analyse :
  - les fichiers sql/**/*.sql
  - les requêtes SQL écrites en dur dans app/**/*.py

et compare aux colonnes déclarées dans migrations/*.sql (CREATE TABLE +
ALTER TABLE ADD COLUMN).

C'est ce contrôle qui aurait évité l'erreur
  UndefinedColumnError: column u.activated_at does not exist
détectée seulement à l'exécution.

Usage : python3 tools/check_schema.py    (code de sortie 1 si anomalie)
"""
from __future__ import annotations

import ast
import glob
import os
import re
import sys

SQL_KEYWORDS = {
    'SET', 'WHERE', 'ON', 'USING', 'VALUES', 'SELECT', 'AS', 'LEFT', 'RIGHT',
    'INNER', 'OUTER', 'JOIN', 'RETURNING', 'GROUP', 'ORDER', 'LIMIT', 'AND',
    'OR', 'NOT', 'NULL', 'LATERAL', 'WITH', 'FROM', 'INTO', 'UPDATE', 'DO',
}
# Colonnes système PostgreSQL, jamais déclarées par l'application
PG_INTERNAL = {
    'attname', 'attnum', 'attrelid', 'conkey', 'conname', 'conrelid', 'contype',
    'oid', 'relname', 'relnamespace', 'nspname', 'indexrelid', 'indrelid',
    'tableoid', 'xmin', 'ctid',
}


def schema_columns() -> dict[str, set[str]]:
    tables: dict[str, set[str]] = {}
    # Les fichiers sql/**/migration.sql du projet créent aussi des colonnes
    # (motif « auto-réparant » repris du workflow) : ils font partie du schéma.
    sources = sorted(glob.glob('migrations/*.sql')) + sorted(glob.glob('sql/**/migration*.sql', recursive=True))
    for path in sources:
        sql = open(path, encoding='utf-8').read()
        # Un commentaire en fin de ligne casserait le découpage des colonnes
        sql = re.sub(r'--[^\n]*', '', sql)
        for m in re.finditer(
                r'CREATE TABLE (?:IF NOT EXISTS )?public\.(\w+)\s*\((.*?)\n\);', sql, re.S):
            name, body = m.group(1), m.group(2)
            cols, depth, cur = set(), 0, ''
            for ch in body:
                if ch == '(':
                    depth += 1
                if ch == ')':
                    depth -= 1
                if ch == ',' and depth == 0:
                    cols.add(cur)
                    cur = ''
                else:
                    cur += ch
            cols.add(cur)
            for c in cols:
                mm = re.match(r'^\s*(\w+)\s+\S', c)
                if mm and mm.group(1).upper() not in (
                        'PRIMARY', 'UNIQUE', 'CONSTRAINT', 'FOREIGN', 'CHECK'):
                    tables.setdefault(name, set()).add(mm.group(1))
        for m in re.finditer(
                r'ALTER TABLE (?:public\.)?(\w+)\s+ADD COLUMN (?:IF NOT EXISTS )?(\w+)', sql):
            tables.setdefault(m.group(1), set()).add(m.group(2))
        # colonnes ajoutées via une chaîne exécutée dynamiquement
        for m in re.finditer(r"ADD COLUMN (?:IF NOT EXISTS )?(\w+)\s+\w", sql):
            for t in tables:
                pass  # rattaché plus bas si le nom de table est identifiable
    return tables


def aliases(query: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in re.finditer(
            r'\b(?:FROM|JOIN|UPDATE|INTO)\s+public\.(\w+)\s+(?:AS\s+)?(\w+)\b', query, re.I):
        table, alias = m.group(1), m.group(2)
        if alias.upper() in SQL_KEYWORDS:
            continue
        out[alias] = table
    return out


def scan(query: str, source: str, tables: dict[str, set[str]], found: set) -> None:
    q = re.sub(r'--[^\n]*', '', query)
    # CTE : leurs noms ne sont pas des tables réelles
    cte = set(re.findall(r'(\w+)\s+AS\s+(?:MATERIALIZED\s+)?\(', q, re.I))

    for alias, table in aliases(q).items():
        if table not in tables or alias in cte:
            continue
        for m in re.finditer(rf'\b{re.escape(alias)}\.(\w+)\b', q):
            col = m.group(1)
            if col in PG_INTERNAL or col in tables[table]:
                continue
            # Une colonne définie par un CTE plus haut n'est pas une erreur
            if re.search(rf'\bAS\s+{re.escape(col)}\b', q, re.I):
                continue
            found.add((source, table, col))

    for m in re.finditer(r'INSERT INTO public\.(\w+)\s*\(([^)]*)\)', q, re.S):
        table = m.group(1)
        if table not in tables:
            continue
        for col in re.findall(r'\w+', m.group(2)):
            if col not in tables[table]:
                found.add((source, table, col))


def main() -> int:
    tables = schema_columns()
    if not tables:
        print('Aucune table trouvée dans migrations/ — vérification impossible.')
        return 2

    found: set = set()

    for path in sorted(glob.glob('sql/**/*.sql', recursive=True)):
        scan(open(path, encoding='utf-8').read(), path, tables, found)

    for root, _, files in os.walk('app'):
        if '__pycache__' in root:
            continue
        for f in sorted(files):
            if not f.endswith('.py'):
                continue
            path = os.path.join(root, f)
            tree = ast.parse(open(path, encoding='utf-8').read(), filename=path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                        and 'public.' in node.value:
                    scan(node.value, path, tables, found)

    print(f'Schéma : {len(tables)} tables, '
          f'{sum(len(c) for c in tables.values())} colonnes déclarées')
    if found:
        print('\nCOLONNES RÉFÉRENCÉES MAIS ABSENTES DU SCHÉMA :')
        for source, table, col in sorted(found, key=lambda x: (x[1], x[2])):
            print(f'  {table}.{col:26} <- {source}')
        print(f'\n{len(found)} anomalie(s). Ajoute les colonnes dans une migration.')
        return 1
    print('\nOK — toutes les colonnes référencées existent dans le schéma.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
