"""Verify final roster reconciliation."""
import json
from collections import Counter

with open('backend/data/ministers.json', 'r', encoding='utf-8') as f:
    runtime = json.load(f)
with open('backend/data/ministers_review.json', 'r', encoding='utf-8') as f:
    review = json.load(f)

print('Runtime ministers:', len(runtime))
print('Review entries:', len(review))
print()

rnames = set(m['name'] for m in runtime)
vnames = set(m['name'] for m in review)
print('Common:', len(rnames & vnames))
print('Runtime only:', len(rnames - vnames))
print('Review only:', len(vnames - rnames))
print()

print('Faction distribution:')
factions = Counter(m['faction'] for m in runtime)
for f, c in sorted(factions.items(), key=lambda x: -x[1]):
    flag = 'OK' if c >= 5 else '*** LOW (<5) ***'
    print('  {}: {} {}'.format(f, c, flag))

print()
dups = [n for n, c in Counter([m['name'] for m in runtime]).items() if c > 1]
print('Duplicate names:', dups if dups else 'NONE')

# Field check
required = ['name', 'faction', 'personality_tags', 'abilities', 'status', 'loyalty', 'entry_year', 'entry_month', 'historical_note']
issues = []
for m in runtime:
    missing = [f for f in required if f not in m]
    has_position = 'position' in m or 'positions' in m
    if missing or not has_position:
        issues.append('{}: missing={}, has_position={}'.format(m.get('name', '?'), missing, has_position))
print()
print('Field issues:', issues if issues else 'NONE')

print()
print('Sample new ministers (first 5 from review additions):')
review_lookup = {m['name']: m for m in review}
added = sorted(rnames - (rnames & set(vnames)))
for name in added[:5]:
    m = next((m for m in runtime if m['name'] == name), None)
    if m:
        print('  {} | faction={} | position={} | loyalty={} | entry={}/{}'.format(
            m['name'], m['faction'], m.get('position','?'),
            m['loyalty'], m['entry_year'], m['entry_month']))
        print('    tags={} | abilities={}'.format(m['personality_tags'], m['abilities']))
