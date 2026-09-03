"""Validation statique de la migration : simule les contrôles de PostgreSQL."""
import re, sys

sql = open('migrations/001_init.sql').read()
# retirer les commentaires pour l'analyse
clean = re.sub(r'--[^\n]*', '', sql)

errors, warnings = [], []

# 1. Tables + colonnes, dans l'ordre de création
tables = {}          # nom -> set(colonnes)
order = []
for m in re.finditer(r'CREATE TABLE (?:IF NOT EXISTS )?public\.(\w+)\s*\((.*?)\n\);', clean, re.S):
    name, body = m.group(1), m.group(2)
    if name in tables:
        errors.append(f"Table déclarée deux fois : {name}")
    cols = []
    depth = 0; current = ""
    for ch in body:
        if ch == '(': depth += 1
        if ch == ')': depth -= 1
        if ch == ',' and depth == 0:
            cols.append(current); current = ""
        else:
            current += ch
    cols.append(current)
    colnames = set()
    for c in cols:
        c = c.strip()
        mm = re.match(r'^(\w+)\s+\S', c)
        if mm and mm.group(1).upper() not in ('PRIMARY','UNIQUE','CONSTRAINT','FOREIGN','CHECK','EXCLUDE'):
            colnames.add(mm.group(1))
    tables[name] = colnames
    order.append(name)

pos = {n: i for i, n in enumerate(order)}

# 2. Clés étrangères : cible existante, créée avant, colonne existante
for m in re.finditer(r'CREATE TABLE (?:IF NOT EXISTS )?public\.(\w+)\s*\((.*?)\n\);', clean, re.S):
    name, body = m.group(1), m.group(2)
    for fk in re.finditer(r'REFERENCES public\.(\w+)\s*\((\w+)\)', body):
        target, tcol = fk.group(1), fk.group(2)
        if target not in tables:
            errors.append(f"{name}: référence une table inexistante ({target})")
        elif pos[target] > pos[name] and target != name:
            errors.append(f"{name}: référence {target} créée PLUS LOIN (ordre invalide)")
        elif tcol not in tables[target]:
            errors.append(f"{name}: référence {target}.{tcol} — colonne inconnue")

# 3. ALTER TABLE ADD CONSTRAINT
for m in re.finditer(r'ALTER TABLE public\.(\w+) ADD CONSTRAINT (\w+)\s+FOREIGN KEY \((\w+)\) REFERENCES public\.(\w+)\((\w+)\)', clean):
    t, cst, col, target, tcol = m.groups()
    if t not in tables: errors.append(f"ALTER sur table inconnue : {t}")
    elif col not in tables[t]: errors.append(f"ALTER {t}: colonne {col} inconnue")
    if target not in tables: errors.append(f"ALTER {t}: cible {target} inconnue")
    elif tcol not in tables[target]: errors.append(f"ALTER {t}: {target}.{tcol} inconnue")

# 4. Index : table + colonnes existantes, nom unique
index_names = set()
for m in re.finditer(r'CREATE INDEX(?: IF NOT EXISTS)?\s+(\w+)?\s*ON public\.(\w+)\s*\(([^)]*)\)([^;]*);', clean):
    iname, table, cols, rest = m.groups()
    if iname:
        if iname in index_names: errors.append(f"Index en double : {iname}")
        index_names.add(iname)
    if table not in tables:
        errors.append(f"Index {iname or ''}: table inconnue {table}")
        continue
    for col in re.findall(r'\b(\w+)\b', cols):
        if col.upper() in ('DESC','ASC','NULLS','LAST','FIRST'): continue
        if col not in tables[table]:
            errors.append(f"Index {iname or ''} sur {table}: colonne inconnue '{col}'")
    # clause WHERE de l'index partiel
    for col in re.findall(r'\b(\w+)\b', rest.replace('WHERE','')):
        if col.upper() in ('IS','NULL','NOT','AND','OR','IN','TRUE','FALSE'): continue
        if col.isdigit() or col.startswith("'"): continue
        if col not in tables[table] and not col.isupper():
            warnings.append(f"Index {iname or ''} sur {table}: '{col}' dans WHERE non reconnu")

# 5. Équilibre des parenthèses et des dollar-quotes
if clean.count('(') != clean.count(')'):
    errors.append(f"Parenthèses déséquilibrées : {clean.count('(')} vs {clean.count(')')}")
if sql.count('$$') % 2 != 0:
    errors.append("Blocs $$ déséquilibrés")

print(f"Tables      : {len(tables)}")
print(f"Index nommés: {len(index_names)}")
print()
if errors:
    print("ERREURS :")
    for e in errors: print("  ✗", e)
else:
    print("✓ Aucune erreur : ordre des tables, clés étrangères, colonnes et index cohérents")
if warnings:
    print("\nAvertissements :")
    for w in warnings[:8]: print("  !", w)
sys.exit(1 if errors else 0)
