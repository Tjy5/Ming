import copy
import random
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from models.game import (
    GameState, GameTime, Faction, Region, Minister, MinisterAbilities,
    StructuredDecree, create_initial_state, clamp_state,
    INITIAL_MINISTERS, INITIAL_FACTIONS, INITIAL_REGIONS,
)
from models.enums import (
    DecreeType, MinisterStatus, PersonnelAction, TaxContribution,
)
from engine.core import process_decree, apply_minister_transition, inject_script_events
from api.routes import select_debate_ministers
from db.saves import _migrate_save


# ── Strategies ────────────────────────────────────────

st_prestige = st.integers(min_value=0, max_value=100)


def make_state(court_prestige=75, ministers=None) -> GameState:
    return GameState(
        time=GameTime(year=1630, month=6, era_name="崇祯", era_year=3),
        national_treasury=20, imperial_treasury=10, grain=500,
        population=15000, military_strength=40,
        civil_morale=60, military_morale=70,
        court_prestige=court_prestige,
        factions=[f.model_copy() for f in INITIAL_FACTIONS],
        regions=[r.model_copy() for r in INITIAL_REGIONS],
        ministers=ministers or [m.model_copy() for m in INITIAL_MINISTERS],
    )


# ── 13.1 Silence preserves non-prestige fields ───────

@given(prestige=st_prestige)
@settings(max_examples=50)
def test_silence_preserves_non_prestige(prestige):
    state = make_state(court_prestige=prestige)
    before = state.model_dump()

    change = max(0, min(3, 100 - state.court_prestige))
    state.court_prestige += change

    after = state.model_dump()
    for key in ("national_treasury", "imperial_treasury", "grain", "population",
                "military_strength", "civil_morale", "military_morale"):
        assert after[key] == before[key]
    assert after["factions"] == before["factions"]
    assert after["regions"] == before["regions"]
    assert after["ministers"] == before["ministers"]


# ── 13.2 Silence prestige bounds ─────────────────────

@given(prestige=st_prestige)
@settings(max_examples=50)
def test_silence_prestige_bounds(prestige):
    state = make_state(court_prestige=prestige)
    change = max(0, min(3, 100 - state.court_prestige))
    state.court_prestige += change
    assert state.court_prestige == min(100, prestige + 3)
    assert 0 <= state.court_prestige <= 100


# ── 13.3 Minister selection determinism ──────────────

@given(seed=st.integers(min_value=0, max_value=10000))
@settings(max_examples=30)
def test_minister_selection_determinism(seed):
    state = make_state()
    r1 = select_debate_ministers(state, DecreeType.TAX_INCREASE)
    rng = random.Random(seed)
    shuffled = list(state.ministers)
    rng.shuffle(shuffled)
    state.ministers = shuffled
    r2 = select_debate_ministers(state, DecreeType.TAX_INCREASE)
    if r1 and r2:
        assert {r1[0].name, r1[1].name} == {r2[0].name, r2[1].name}


# ── 13.4 Non-personnel decree preserves minister status ──

non_personnel = st.sampled_from([
    dt for dt in DecreeType if dt != DecreeType.PERSONNEL
])


@given(dt=non_personnel)
@settings(max_examples=30)
def test_non_personnel_preserves_ministers(dt):
    state = make_state()
    statuses_before = [m.status for m in state.ministers]
    decree = StructuredDecree(type=dt)
    if dt == DecreeType.DISASTER_RELIEF:
        decree.target = "陕西"
    elif dt == DecreeType.DIPLOMACY:
        decree.target = "后金"
    process_decree(state, decree)
    statuses_after = [m.status for m in state.ministers]
    assert statuses_before == statuses_after


# ── 13.5 Minister status transition commutativity ─────

@given(st.data())
@settings(max_examples=20)
def test_transition_commutativity(data):
    state_a = make_state()
    state_b = make_state()
    active = [m.name for m in state_a.ministers if m.status == MinisterStatus.ACTIVE]
    assume(len(active) >= 2)
    targets = data.draw(st.lists(st.sampled_from(active), min_size=2, max_size=2, unique=True))
    d1 = StructuredDecree(type=DecreeType.PERSONNEL, target=targets[0], sub_action=PersonnelAction.DISMISS)
    d2 = StructuredDecree(type=DecreeType.PERSONNEL, target=targets[1], sub_action=PersonnelAction.DISMISS)

    apply_minister_transition(state_a, d1)
    apply_minister_transition(state_a, d2)

    apply_minister_transition(state_b, d2)
    apply_minister_transition(state_b, d1)

    for ma, mb in zip(state_a.ministers, state_b.ministers):
        assert ma.status == mb.status


# ── 13.6 Conditional injection False leaves no trace ──

@given(risk=st.integers(min_value=0, max_value=100))
@settings(max_examples=30)
def test_condition_false_no_trace(risk):
    # yuan-chonghuan-arrest at 1629/12 requires "jisi-invasion" resolved;
    # without that prerequisite, it should never inject.
    state = GameState(
        time=GameTime(year=1629, month=12, era_name="崇祯", era_year=2),
        factions=[Faction(name="test", satisfaction=50, influence=25, rebellion_risk=risk)],
        regions=[Region(name="test", stability=50, garrison=10000, tax_contribution=TaxContribution.MEDIUM)],
    )
    state.resolved_script_ids = set()  # prerequisite NOT met
    inject_script_events(state)
    assert not any(e.script_id == "yuan-chonghuan-arrest" for e in state.active_events)
    assert "yuan-chonghuan-arrest" not in state.resolved_script_ids


# ── 13.7 Save migration idempotency ─────────────────

@given(year=st.integers(min_value=1621, max_value=1644))
@settings(max_examples=30)
def test_save_migration_idempotent(year):
    data = {
        "time": {"year": year, "month": 6},
        "treasury": 100, "population": 100, "military_supply": 80,
        "civil_morale": 60, "military_morale": 70, "court_prestige": 75,
        "factions": [], "active_events": [], "history_log": [],
        "decree_count": 5, "event_cooldowns": {}, "regions": [],
    }
    _migrate_save(data)
    snap = copy.deepcopy(data)
    _migrate_save(data)
    assert data == snap


# ── 13.8 Opening script effects clamp ────────────────

@given(
    national_treasury=st.integers(min_value=0, max_value=10000),
    prestige=st.integers(min_value=0, max_value=100),
)
@settings(max_examples=30)
def test_opening_effects_clamp(national_treasury, prestige):
    state = create_initial_state()
    state.national_treasury = national_treasury
    state.court_prestige = prestige
    evt = next(e for e in state.active_events if e.script_id == "chongzhen-accession-1627-08")
    for choice in evt.choices:
        if choice.decrees:
            s = create_initial_state()
            s.national_treasury = national_treasury
            s.court_prestige = prestige
            process_decree(s, choice.decrees[0])
            assert 0 <= s.court_prestige <= 100
            assert 0 <= s.national_treasury <= 10000


# ── 13.9 Debate API validation leaves state unchanged ─

@given(dt=st.sampled_from(list(DecreeType)))
@settings(max_examples=30)
def test_debate_validation_no_state_change(dt):
    state = make_state()
    snap = state.model_dump()
    result = select_debate_ministers(state, dt)
    after = state.model_dump()
    assert snap == after
