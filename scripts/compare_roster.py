"""Compare ministers.json with ministers_review.json and produce an audit report."""
import json
from collections import Counter

with open('backend/data/ministers.json', 'r', encoding='utf-8') as f:
    runtime = json.load(f)
with open('backend/data/ministers_review.json', 'r', encoding='utf-8') as f:
    review = json.load(f)

runtime_names = set(m['name'] for m in runtime)
review_names = set(m['name'] for m in review)

print(f'Runtime ministers: {len(runtime)}')
print(f'Review entries:    {len(review)}')
print(f'Common (in both):  {len(runtime_names & review_names)}')
print(f'In review only:    {len(review_names - runtime_names)}')
print(f'In runtime only:   {len(runtime_names - review_names)}')
print()

# --- Missing from runtime (in review but not in runtime) ---
print('=' * 60)
print('Ministers in review but NOT in runtime (potential additions):')
print('=' * 60)
review_lookup = {m['name']: m for m in review}
missing = sorted(review_names - runtime_names)
for n in missing:
    bp = review_lookup[n].get('base_profile', {})
    faction = bp.get('faction', '?')
    position = bp.get('position', '?')
    print(f'  {n} | faction: {faction} | position: {position}')

# --- In runtime but NOT in review ---
print()
print('=' * 60)
print('Ministers in runtime but NOT in review (stale review entries):')
print('=' * 60)
runtime_lookup = {m['name']: m for m in runtime}
stale = sorted(runtime_names - review_names)
for n in stale:
    m = runtime_lookup[n]
    print(f'  {n} | faction: {m.get("faction","?")} | position: {m.get("position","?")}')

# --- Faction distribution in runtime ---
print()
print('=' * 60)
print('Runtime faction distribution:')
print('=' * 60)
factions = Counter(m['faction'] for m in runtime)
for f, c in factions.most_common():
    print(f'  {f}: {c}')

# --- Faction distribution in review ---
print()
print('=' * 60)
print('Review faction distribution (for missing ministers):')
print('=' * 60)
missing_factions = Counter(
    review_lookup[n].get('base_profile', {}).get('faction', '?')
    for n in missing
)
for f, c in missing_factions.most_common():
    print(f'  {f}: {c}')

# --- Field validation for runtime ---
print()
print('=' * 60)
print('Runtime field validation:')
print('=' * 60)
required = ['name', 'faction', 'personality_tags', 'abilities', 'status', 'loyalty', 'entry_year', 'entry_month', 'historical_note']
issues = []
for m in runtime:
    missing_fields = [f for f in required if f not in m]
    has_position = 'position' in m or 'positions' in m
    if missing_fields or not has_position:
        issues.append(f'  {m["name"]}: missing={missing_fields}, has_position={has_position}')
if issues:
    for i in issues:
        print(i)
else:
    print('  All runtime ministers have required fields.')

runtime_names_list = [m['name'] for m in runtime]
duplicates = [n for n, c in Counter(runtime_names_list).items() if c > 1]
if duplicates:
    print(f'  DUPLICATE names: {duplicates}')
else:
    print('  No duplicate names found.')
