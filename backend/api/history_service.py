from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable
from threading import RLock

from engine.tables import REGION_NAMES, region_target_members
from models.game import GameState, HistoryEntry, history_category_of
from models.world import EntityId, RegionEntity


HISTORY_QUERY_CACHE_MAX_ENTRIES = 64
_HistoryQueryKey = tuple[str, int | None, int | None, str | None, str | None]
_history_query_cache: OrderedDict[_HistoryQueryKey, tuple[HistoryEntry, ...]] = OrderedDict()
_history_query_cache_lock = RLock()


def _append_unique(result: list[str], values: Iterable[str]) -> None:
    for value in values:
        if value in REGION_NAMES and value not in result:
            result.append(value)


def _region_name(state: GameState, entity_id: EntityId | None) -> str | None:
    if entity_id is None:
        return None
    entity = state.entity_registry.get(entity_id)
    if not isinstance(entity, RegionEntity):
        return None
    name = entity.legacy_name or entity.display_name
    return name if name in REGION_NAMES else None


def history_provinces(
    state: GameState,
    *,
    structured_target: str | None = None,
    target_region_id: EntityId | None = None,
    target_entity_ids: Iterable[EntityId] = (),
    settlement_deltas: Iterable[object] = (),
) -> list[str]:
    result: list[str] = []
    _append_unique(result, region_target_members(structured_target))
    target_name = _region_name(state, target_region_id)
    if target_name is not None:
        _append_unique(result, (target_name,))
    for entity_id in target_entity_ids:
        name = _region_name(state, entity_id)
        if name is not None:
            _append_unique(result, (name,))
    for delta in settlement_deltas:
        if getattr(delta, "target_scope", None) != "region":
            continue
        name = _region_name(state, getattr(delta, "target_id", None))
        if name is not None:
            _append_unique(result, (name,))
    return result


def next_history_sequence(state: GameState) -> int:
    return max((entry.sequence for entry in state.history_log), default=-1) + 1


def append_history_entry(
    state: GameState,
    *,
    decree_type: object,
    decree_desc: str = "",
    delta: dict | None = None,
    narrative: str = "",
    structured_target: str | None = None,
    target_region_id: EntityId | None = None,
    target_entity_ids: Iterable[EntityId] = (),
    settlement_deltas: Iterable[object] = (),
) -> HistoryEntry:
    raw_type = getattr(decree_type, "value", decree_type)
    entry = HistoryEntry(
        sequence=next_history_sequence(state),
        year=state.time.year,
        month=state.time.month,
        decree_type=str(raw_type),
        category=history_category_of(raw_type),
        provinces=history_provinces(
            state,
            structured_target=structured_target,
            target_region_id=target_region_id,
            target_entity_ids=target_entity_ids,
            settlement_deltas=settlement_deltas,
        ),
        decree_desc=decree_desc,
        delta=delta or {},
        narrative=narrative,
    )
    state.history_log.append(entry)
    return entry


def filter_history_entries(
    entries: Iterable[HistoryEntry],
    *,
    year: int | None = None,
    month: int | None = None,
    category: str | None = None,
    province: str | None = None,
) -> list[HistoryEntry]:
    ordered = sorted(
        enumerate(entries),
        key=lambda item: (
            item[1].year,
            item[1].month,
            item[1].sequence,
            item[0],
        ),
    )
    return [
        entry
        for _index, entry in ordered
        if (year is None or entry.year == year)
        and (month is None or entry.month == month)
        and (category is None or entry.category == category)
        and (province is None or province in entry.provinces)
    ]


def clear_history_query_cache() -> None:
    with _history_query_cache_lock:
        _history_query_cache.clear()


def filter_history_entries_cached(
    entries: Iterable[HistoryEntry],
    *,
    version_key: object,
    year: int | None = None,
    month: int | None = None,
    category: str | None = None,
    province: str | None = None,
) -> list[HistoryEntry]:
    """Cache immutable-version query results without weakening head isolation."""

    key: _HistoryQueryKey = (
        str(version_key),
        year,
        month,
        category,
        province,
    )
    with _history_query_cache_lock:
        cached = _history_query_cache.get(key)
        if cached is not None:
            _history_query_cache.move_to_end(key)
            return list(cached)

    filtered = tuple(filter_history_entries(
        entries,
        year=year,
        month=month,
        category=category,
        province=province,
    ))
    with _history_query_cache_lock:
        _history_query_cache[key] = filtered
        _history_query_cache.move_to_end(key)
        while len(_history_query_cache) > HISTORY_QUERY_CACHE_MAX_ENTRIES:
            _history_query_cache.popitem(last=False)
    return list(filtered)
