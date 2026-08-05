"""Convert review-only ministers to runtime format and reconcile both files."""
import json
import random
import copy
from collections import Counter

random.seed(42)

with open('backend/data/ministers.json', 'r', encoding='utf-8') as f:
    runtime_ministers = json.load(f)

with open('backend/data/ministers_review.json', 'r', encoding='utf-8') as f:
    review_entries = json.load(f)

# ============================================================
# Helper: characterize position type
# ============================================================
MILITARY_POSITIONS = {'总兵', '副总兵', '参将', '副将', '千总', '指挥使', '守备', '游击',
                       '宣府总兵', '锦衣卫指挥使', '北镇抚司', '保国公', '英国公世子',
                       '新城侯', '中军都督', '宣大总督', '总兵官'}
CIVIL_POSITIONS = {'尚书', '侍郎', '御史', '翰林', '知府', '知县', '知州', '教谕',
                    '主事', '主簿', '郎中', '员外郎', '给事中', '太常寺', '光禄寺',
                    '翰林编修', '翰林修撰', '翰林侍读', '大学士', '文渊阁大学士',
                    '东阁大学士', '武英殿大学士', '吏部尚书', '礼部尚书', '户部尚书',
                    '刑部尚书', '工部尚书', '吏部侍郎', '礼部侍郎', '户部侍郎',
                    '刑部侍郎', '工部侍郎', '都御史', '左都御史', '右都御史',
                    '副都御史', '佥都御史', '监察御史', '顺天府尹', '河南巡抚',
                    '陕西参政', '湖广佥事', '大名知府', '南阳知府', '太常少卿',
                    '光禄少卿', '户部主事', '礼部主事', '工部主事', '刑部主事',
                    '太仆寺卿', '翰林学士', '进士'}

MILITARY_TAGS = ['勇猛', '果敢', '善战', '刚烈', '善谋', '忠君', '果断']
CIVIL_TAGS = ['博学', '翰林', '清廉', '务实', '刚直', '谨慎', '善谋', '忠君']

FACTION_BONUS_TAGS = {
    '东林党': ['刚直', '清廉'],
    '阉党残余': ['圆滑', '贪权'],
    '勋贵集团': ['忠诚', '保守'],
    '辽东边将': ['勇猛', '果敢'],
    '中原剿匪系': ['果断', '刚烈'],
    '温体仁派': ['圆滑', '善谋'],
    '周延儒派': ['谨慎', '圆滑'],
    '中立派': ['务实', '谨慎'],
}

FACTION_LOYALTY = {
    '东林党': (65, 85),
    '阉党残余': (10, 35),
    '勋贵集团': (55, 75),
    '辽东边将': (45, 65),
    '中原剿匪系': (40, 60),
    '温体仁派': (30, 55),
    '周延儒派': (30, 55),
    '中立派': (45, 70),
}


def is_military_position(pos):
    """Check if a position is primarily military."""
    if not pos:
        return False
    for mp in MILITARY_POSITIONS:
        if mp in pos:
            return True
    return False


def generate_abilities(pos, faction):
    """Generate balanced abilities based on position type."""
    pos_str = pos or ''
    if is_military_position(pos_str):
        military = random.randint(55, 85)
        civil = random.randint(25, 55)
        diplomacy = random.randint(20, 50)
    elif any(kw in pos_str for kw in ['大学士', '尚书', '侍郎', '翰林']):
        civil = random.randint(70, 92)
        military = random.randint(3, 25)
        diplomacy = random.randint(40, 70)
    elif any(kw in pos_str for kw in ['巡抚', '总督', '参政', '佥事']):
        civil = random.randint(50, 70)
        military = random.randint(35, 60)
        diplomacy = random.randint(40, 60)
    else:
        civil = random.randint(45, 75)
        military = random.randint(10, 40)
        diplomacy = random.randint(30, 60)
    return {'civil': civil, 'military': military, 'diplomacy': diplomacy}


def generate_personality_tags(base_tags, faction):
    """Generate 2-4 unique personality tags."""
    bonus = FACTION_BONUS_TAGS.get(faction, [])
    pool = base_tags + bonus
    seen = set()
    tags = []
    for tag in pool:
        if tag not in seen:
            tags.append(tag)
            seen.add(tag)
            if len(tags) >= 4:
                break
    # Ensure at least 2 tags
    while len(tags) < 2:
        extra = [t for t in base_tags if t not in seen]
        if not extra:
            extra = ['务实']
        tags.append(extra[0])
        seen.add(extra[0])
    return tags[:4]


def determine_entry(historical_note):
    """Determine entry_year/entry_month from historical note hints."""
    note = historical_note or ''
    # Default: 崇祯元年八月 (1627/8)
    year = 1627
    month = 8

    # Try to detect timeline hints
    if any(kw in note for kw in ['崇祯末', '崇祯后期', '甲申']):
        year = random.choice([1640, 1642, 1643])
        month = random.randint(1, 12)
    elif any(kw in note for kw in ['崇祯中', '崇祯中期']):
        year = random.choice([1635, 1637, 1639])
        month = random.randint(1, 12)
    elif any(kw in note for kw in ['南明', '弘光', '隆武', '永历']):
        year = 1644
        month = random.randint(3, 12)
    elif any(kw in note for kw in ['天启', '天启朝']):
        year = 1627
        month = 8
    elif any(kw in note for kw in ['早期', '早年']):
        year = 1627
        month = random.randint(1, 12)
    else:
        # Randomize slightly to avoid all entering same month
        year = random.choice([1627, 1628, 1629])
        month = random.randint(1, 12)
    return year, month


def generate_loyalty(faction):
    lo, hi = FACTION_LOYALTY.get(faction, (40, 70))
    return random.randint(lo, hi)


def convert_review_to_minister(review_entry):
    """Convert a single review entry to a runtime minister dict."""
    bp = review_entry.get('base_profile', {})
    name = review_entry['name']
    faction = bp.get('faction', '中立派')
    position = bp.get('position', '未分配')
    historical_note = bp.get('historical_note', '')

    pos_str = position or ''
    if is_military_position(pos_str):
        tag_pool = MILITARY_TAGS
    else:
        tag_pool = CIVIL_TAGS

    tags = generate_personality_tags(tag_pool, faction)
    abilities = generate_abilities(pos_str, faction)
    loyalty = generate_loyalty(faction)
    entry_year, entry_month = determine_entry(historical_note)

    minister = {
        'name': name,
        'faction': faction,
        'personality_tags': tags,
        'abilities': abilities,
        'status': 'active',
        'loyalty': loyalty,
        'position': position,
        'entry_year': entry_year,
        'entry_month': entry_month,
        'historical_note': historical_note,
    }

    # Mark certain positions as eunuch
    if any(kw in pos_str for kw in ['太监', '司礼', '秉笔', '掌印']):
        minister['is_eunuch'] = True

    return minister


# ============================================================
# Task 1: Convert review-only ministers to runtime format
# ============================================================
runtime_names = set(m['name'] for m in runtime_ministers)
review_names_all = set(m['name'] for m in review_entries)

review_only = review_names_all - runtime_names
runtime_only = runtime_names - review_names_all

print(f'Review-only ministers (to add to runtime): {len(review_only)}')
print(f'Runtime-only ministers (need review entries): {len(runtime_only)}')

# Convert review-only ministers to runtime format
new_runtime_ministers = []
review_lookup = {m['name']: m for m in review_entries}

for name in sorted(review_only):
    entry = review_lookup[name]
    minister = convert_review_to_minister(entry)
    new_runtime_ministers.append(minister)

# ============================================================
# Task 2: Create new runtime roster with 100+ ministers
# ============================================================
final_roster = runtime_ministers + new_runtime_ministers

# Verify uniqueness
names_in_final = [m['name'] for m in final_roster]
dups = [n for n, c in Counter(names_in_final).items() if c > 1]
if dups:
    print(f'ERROR: Duplicate names detected: {dups}')
else:
    print(f'All {len(names_in_final)} names are unique.')

# Verify required fields
required = ['name', 'faction', 'personality_tags', 'abilities', 'status', 'loyalty', 'entry_year', 'entry_month', 'historical_note']
issues = []
for m in final_roster:
    missing = [f for f in required if f not in m]
    has_position = 'position' in m or 'positions' in m
    if missing or not has_position:
        issues.append(f'  {m["name"]}: missing={missing}, has_position={has_position}')
if issues:
    print(f'Field issues ({len(issues)}):')
    for i in issues:
        print(i)
else:
    print('All ministers have required fields and position/positions.')

# Faction distribution
factions = Counter(m['faction'] for m in final_roster)
print(f'\nFinal faction distribution ({len(final_roster)} ministers):')
for f, c in factions.most_common():
    status = 'OK' if c >= 5 else 'LOW (<5)'
    print(f'  {f}: {c} ({status})')

# Write updated runtime roster
with open('backend/data/ministers.json', 'w', encoding='utf-8') as f:
    json.dump(final_roster, f, ensure_ascii=False, indent=2)

print(f'\nWrote {len(final_roster)} ministers to backend/data/ministers.json')

# ============================================================
# Task 2.2: Add review entries for runtime-only ministers
# ============================================================
print(f'\nRuntime-only ministers to add review entries for:')
runtime_lookup = {m['name']: m for m in runtime_ministers}
new_review_entries = copy.deepcopy(review_entries)

for name in sorted(runtime_only):
    m = runtime_lookup[name]
    print(f'  {name} ({m["faction"]}, {m.get("position", "?")})')
    review_entry = {
        'name': name,
        'base_profile': {
            'faction': m.get('faction', '?'),
            'position': m.get('position', '?'),
            'historical_note': m.get('historical_note', ''),
        },
        'aliases': [],
        'birth_year': None,
        'death_year': None,
        'office_history': [m.get('position', '?')],
        'major_contributions': [],
        'related_events': [],
        'project_role_background': f'{m["faction"]}成员。{m.get("position", "")}。',
        'sources': [
            {
                'title': '项目初始大臣数据（ministers.json）',
                'url': 'backend/data/ministers.json',
                'tier': 'C_SECONDARY',
                'locator': '当前项目设定基线',
            }
        ],
        'review': {
            'status': 'draft',
            'reviewer': 'codex',
            'last_reviewed_on': '2026-04-27',
            'notes': '从运行时阵容新增至审查队列，待补全来源与履历。',
        },
    }
    new_review_entries.append(review_entry)

with open('backend/data/ministers_review.json', 'w', encoding='utf-8') as f:
    json.dump(new_review_entries, f, ensure_ascii=False, indent=2)
print(f'Wrote {len(new_review_entries)} review entries to backend/data/ministers_review.json')
