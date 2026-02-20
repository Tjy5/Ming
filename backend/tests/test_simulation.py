"""
Automated Game Simulation — runs multiple strategies from 1627/8 to 1644/3,
logs every turn, and prints a comprehensive balance report.

Usage:
    cd backend && python -m tests.test_simulation
"""
from __future__ import annotations

import sys
import os
import copy
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.game import (
    GameState, StructuredDecree, create_initial_state, clamp_state,
)
from models.enums import (
    DecreeType, RegionControl, RegionThreat, PersonnelAction, MinisterStatus,
    MemorialStatus,
)
from engine.core import (
    process_decree, check_preconditions, validate_target,
    inject_script_events, check_game_end,
)
from engine.tables import DECREE_PRECONDITIONS


# ── Strategy Definitions ────────────────────────────────

def _can_issue(state: GameState, decree: StructuredDecree) -> bool:
    if check_preconditions(state, decree) is not None:
        return False
    if validate_target(decree, state) is not None:
        return False
    return True


def strategy_do_nothing(state: GameState, turn: int) -> StructuredDecree | None:
    """Never issue decrees — pure passive drift."""
    return None


def strategy_tax_and_military(state: GameState, turn: int) -> StructuredDecree | None:
    """Alternate between taxing and recruiting troops. Relief when treasury allows."""
    if turn % 3 == 0:
        d = StructuredDecree(type=DecreeType.TAX_INCREASE)
        if _can_issue(state, d):
            return d
    if turn % 3 == 1:
        d = StructuredDecree(type=DecreeType.RECRUIT_TROOPS)
        if _can_issue(state, d):
            return d
    # fallback: relief for worst region
    worst = min(state.regions, key=lambda r: r.stability)
    d = StructuredDecree(type=DecreeType.DISASTER_RELIEF, target=worst.name)
    if _can_issue(state, d):
        return d
    return None


def strategy_relief_focused(state: GameState, turn: int) -> StructuredDecree | None:
    """Prioritize disaster relief for the worst region, tax when needed."""
    worst = min(state.regions, key=lambda r: r.stability)
    d = StructuredDecree(type=DecreeType.DISASTER_RELIEF, target=worst.name)
    if _can_issue(state, d):
        return d
    # need money
    d = StructuredDecree(type=DecreeType.TAX_INCREASE)
    if _can_issue(state, d):
        return d
    return None


def strategy_balanced(state: GameState, turn: int) -> StructuredDecree | None:
    """Adaptive strategy: address the most urgent problem each turn."""
    # 1. critical region → relief
    critical_regions = [r for r in state.regions if r.stability < 25]
    if critical_regions:
        target = min(critical_regions, key=lambda r: r.stability)
        d = StructuredDecree(type=DecreeType.DISASTER_RELIEF, target=target.name)
        if _can_issue(state, d):
            return d

    # 2. low military → recruit
    if state.military_morale < 35 or state.military_supply < 30:
        d = StructuredDecree(type=DecreeType.RECRUIT_TROOPS)
        if _can_issue(state, d):
            return d

    # 3. low treasury → tax
    if state.treasury < 40:
        d = StructuredDecree(type=DecreeType.TAX_INCREASE)
        if _can_issue(state, d):
            return d

    # 4. low prestige → diplomacy
    if state.court_prestige < 40:
        d = StructuredDecree(type=DecreeType.DIPLOMACY, target="蒙古")
        if _can_issue(state, d):
            return d

    # 5. civil morale low → tax decrease
    if state.civil_morale < 30:
        d = StructuredDecree(type=DecreeType.TAX_DECREASE)
        if _can_issue(state, d):
            return d

    # 6. default: relief for worst region or wait
    worst = min(state.regions, key=lambda r: r.stability)
    if worst.stability < 50:
        d = StructuredDecree(type=DecreeType.DISASTER_RELIEF, target=worst.name)
        if _can_issue(state, d):
            return d

    return None


def strategy_harsh_rule(state: GameState, turn: int) -> StructuredDecree | None:
    """Heavy-handed: harsh punishment + tax increase cycle."""
    if turn % 2 == 0:
        d = StructuredDecree(type=DecreeType.HARSH_PUNISHMENT)
        if _can_issue(state, d):
            return d
    d = StructuredDecree(type=DecreeType.TAX_INCREASE)
    if _can_issue(state, d):
        return d
    d = StructuredDecree(type=DecreeType.RECRUIT_TROOPS)
    if _can_issue(state, d):
        return d
    return None


def strategy_diplomacy_focus(state: GameState, turn: int) -> StructuredDecree | None:
    """Diplomacy-heavy: try to manage external threats while relieving."""
    targets = ["蒙古", "后金", "朝鲜"]
    d = StructuredDecree(type=DecreeType.DIPLOMACY, target=targets[turn % 3])
    if _can_issue(state, d):
        return d
    # fallback: relief
    worst = min(state.regions, key=lambda r: r.stability)
    d = StructuredDecree(type=DecreeType.DISASTER_RELIEF, target=worst.name)
    if _can_issue(state, d):
        return d
    d = StructuredDecree(type=DecreeType.TAX_INCREASE)
    if _can_issue(state, d):
        return d
    return None


STRATEGIES = {
    "无为而治（从不下令）":   strategy_do_nothing,
    "穷兵黩武（加税+征兵）":  strategy_tax_and_military,
    "以民为本（优先赈灾）":   strategy_relief_focused,
    "均衡施政（自适应）":     strategy_balanced,
    "严刑峻法（酷吏路线）":   strategy_harsh_rule,
    "合纵连横（外交优先）":   strategy_diplomacy_focus,
}


# ── Simulation Engine ───────────────────────────────────

class TurnLog:
    __slots__ = (
        "year", "month", "decree_type", "triggered_events",
        "treasury", "population", "military_supply",
        "civil_morale", "military_morale", "court_prestige",
        "region_stabilities", "faction_risks", "faction_satisfactions",
        "game_over", "blocked_decree", "memorials_pending",
        "regions_fallen", "regions_unstable",
    )

    def __init__(self):
        for s in self.__slots__:
            setattr(self, s, None)


def simulate(strategy_fn, strategy_name: str) -> dict:
    state = create_initial_state()

    # resolve the opening blocking event immediately (pick first choice)
    _auto_resolve_blocking(state)

    logs: list[TurnLog] = []
    max_turns = 250  # safety cap
    turn = 0

    while turn < max_turns:
        log = TurnLog()
        log.year = state.time.year
        log.month = state.time.month

        # check game end before decree
        game_over = check_game_end(state)
        if game_over:
            log.game_over = game_over
            _snapshot(log, state)
            logs.append(log)
            break

        # pick decree
        decree = strategy_fn(state, turn)
        log.decree_type = decree.type.value if decree else "wait"
        log.blocked_decree = False

        if decree and not _can_issue(state, decree):
            decree = None
            log.blocked_decree = True

        # process
        delta, attr, triggered, game_over, reactions, summary = process_decree(
            state, decree=decree,
        )
        log.triggered_events = triggered

        # auto-resolve any blocking script events (always pick first choice)
        _auto_resolve_blocking(state)

        _snapshot(log, state)
        log.game_over = game_over

        # pending memorials count
        log.memorials_pending = sum(
            1 for m in state.memorials
            if m.status in {MemorialStatus.PENDING, MemorialStatus.DEFERRED}
        )

        logs.append(log)

        if game_over:
            break

        turn += 1

    return _build_report(strategy_name, logs, state)


def _auto_resolve_blocking(state: GameState) -> None:
    """Resolve all blocking script events by picking the first choice and applying state_effects."""
    while True:
        blocking = [e for e in state.active_events if e.is_blocking and e.is_scripted]
        if not blocking:
            break
        evt = blocking[0]
        # apply first choice effects
        if evt.choices:
            choice = evt.choices[0]
            # apply state_effects
            for path, value in choice.state_effects.items():
                _apply_state_effect(state, path, value)
            # apply loyalty_effects
            for item in choice.loyalty_effects:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    name, delta = item
                    for m in state.ministers:
                        if m.name == name:
                            m.loyalty = max(0, min(100, m.loyalty + delta))
                            break
        # remove from active + mark resolved
        state.active_events = [e for e in state.active_events if e is not evt]
        if evt.script_id:
            state.resolved_script_ids.add(evt.script_id)
        clamp_state(state)


def _apply_state_effect(state: GameState, path: str, value) -> None:
    parts = path.split(".")
    if parts[0] == "global" and len(parts) == 2:
        field = parts[1]
        if hasattr(state, field):
            setattr(state, field, getattr(state, field) + value)
    elif parts[0] == "region" and len(parts) == 3:
        rname, field = parts[1], parts[2]
        for r in state.regions:
            if r.name == rname and hasattr(r, field):
                setattr(r, field, getattr(r, field) + value)
                break
    elif parts[0] == "faction" and len(parts) == 3:
        fname, field = parts[1], parts[2]
        for f in state.factions:
            if f.name == fname and hasattr(f, field):
                setattr(f, field, getattr(f, field) + value)
                break


def _snapshot(log: TurnLog, state: GameState) -> None:
    log.treasury = state.treasury
    log.population = state.population
    log.military_supply = state.military_supply
    log.civil_morale = state.civil_morale
    log.military_morale = state.military_morale
    log.court_prestige = state.court_prestige
    log.region_stabilities = {r.name: r.stability for r in state.regions}
    log.faction_risks = {f.name: f.rebellion_risk for f in state.factions}
    log.faction_satisfactions = {f.name: f.satisfaction for f in state.factions}
    log.regions_fallen = sum(1 for r in state.regions if r.control == RegionControl.FALLEN)
    log.regions_unstable = sum(1 for r in state.regions if r.control == RegionControl.UNSTABLE)


def _build_report(name: str, logs: list[TurnLog], final_state: GameState) -> dict:
    first = logs[0] if logs else None
    last = logs[-1] if logs else None
    total_turns = len(logs)

    # count decree types
    decree_counts: dict[str, int] = {}
    blocked_count = 0
    for l in logs:
        decree_counts[l.decree_type] = decree_counts.get(l.decree_type, 0) + 1
        if l.blocked_decree:
            blocked_count += 1

    # all triggered events
    all_events: list[str] = []
    for l in logs:
        if l.triggered_events:
            all_events.extend(l.triggered_events)

    event_counts: dict[str, int] = {}
    for e in all_events:
        event_counts[e] = event_counts.get(e, 0) + 1

    # find when key thresholds were crossed
    treasury_zero_turn = None
    prestige_zero_turn = None
    first_fallen_turn = None
    for i, l in enumerate(logs):
        if treasury_zero_turn is None and l.treasury == 0:
            treasury_zero_turn = (l.year, l.month)
        if prestige_zero_turn is None and l.court_prestige == 0:
            prestige_zero_turn = (l.year, l.month)
        if first_fallen_turn is None and l.regions_fallen and l.regions_fallen > 0:
            first_fallen_turn = (l.year, l.month)

    # resource trends (sample every 12 turns)
    trend_points = []
    for i in range(0, len(logs), 6):
        l = logs[i]
        trend_points.append({
            "year": l.year, "month": l.month,
            "treasury": l.treasury, "population": l.population,
            "military_supply": l.military_supply,
            "civil_morale": l.civil_morale, "military_morale": l.military_morale,
            "court_prestige": l.court_prestige,
        })
    # always include last
    if logs and (not trend_points or trend_points[-1]["year"] != last.year or trend_points[-1]["month"] != last.month):
        trend_points.append({
            "year": last.year, "month": last.month,
            "treasury": last.treasury, "population": last.population,
            "military_supply": last.military_supply,
            "civil_morale": last.civil_morale, "military_morale": last.military_morale,
            "court_prestige": last.court_prestige,
        })

    # region stability at end
    region_final = {}
    if last:
        region_final = last.region_stabilities or {}

    # faction data at end
    faction_final_risk = last.faction_risks if last else {}
    faction_final_sat = last.faction_satisfactions if last else {}

    # game result
    result = "unknown"
    result_msg = ""
    end_time = ""
    if last and last.game_over:
        result = last.game_over.get("result", "unknown")
        result_msg = last.game_over.get("message", "")
        end_time = f"{last.year}/{last.month}"

    return {
        "name": name,
        "total_turns": total_turns,
        "result": result,
        "result_msg": result_msg,
        "end_time": end_time,
        "decree_counts": decree_counts,
        "blocked_count": blocked_count,
        "event_counts": event_counts,
        "treasury_zero": treasury_zero_turn,
        "prestige_zero": prestige_zero_turn,
        "first_fallen": first_fallen_turn,
        "trends": trend_points,
        "region_final": region_final,
        "faction_final_risk": faction_final_risk,
        "faction_final_sat": faction_final_sat,
        "final_memorials_pending": last.memorials_pending if last else 0,
    }


# ── Report Printer ──────────────────────────────────────

def print_report(reports: list[dict]) -> None:
    sep = "=" * 80
    thin = "-" * 80

    print(f"\n{sep}")
    print("  崇祯模拟器 — 自动化平衡性测试报告")
    print(f"{sep}\n")

    # ── Summary Table ──
    print("┌─────────────────────────┬──────┬──────────┬────────────────────────────┐")
    print("│ 策略                    │ 回合 │ 结局时间 │ 结果                       │")
    print("├─────────────────────────┼──────┼──────────┼────────────────────────────┤")
    for r in reports:
        name = r["name"][:23].ljust(23)
        turns = str(r["total_turns"]).rjust(4)
        etime = r["end_time"].ljust(8) if r["end_time"] else "未结束".ljust(8)
        res = r["result_msg"][:26].ljust(26) if r["result_msg"] else r["result"].ljust(26)
        print(f"│ {name} │ {turns} │ {etime} │ {res} │")
    print("└─────────────────────────┴──────┴──────────┴────────────────────────────┘")

    # ── Per-strategy details ──
    for r in reports:
        print(f"\n{thin}")
        print(f"  策略: {r['name']}")
        print(f"  结果: {r['result']} — {r['result_msg']}")
        print(f"  总回合: {r['total_turns']}  结束时间: {r['end_time'] or 'N/A'}")
        print(thin)

        # Decree distribution
        print("\n  政令分布:")
        for dtype, cnt in sorted(r["decree_counts"].items(), key=lambda x: -x[1]):
            label = _decree_label(dtype)
            bar = "█" * min(cnt, 50)
            print(f"    {label.ljust(12)} {str(cnt).rjust(3)}  {bar}")
        if r["blocked_count"]:
            print(f"    被阻止的政令: {r['blocked_count']}")

        # Key timestamps
        print("\n  关键时间节点:")
        if r["treasury_zero"]:
            print(f"    国库归零: {r['treasury_zero'][0]}年{r['treasury_zero'][1]}月")
        else:
            print(f"    国库归零: 未发生")
        if r["prestige_zero"]:
            print(f"    威望归零: {r['prestige_zero'][0]}年{r['prestige_zero'][1]}月")
        else:
            print(f"    威望归零: 未发生")
        if r["first_fallen"]:
            print(f"    首个区域沦陷: {r['first_fallen'][0]}年{r['first_fallen'][1]}月")
        else:
            print(f"    首个区域沦陷: 未发生")

        # Events
        if r["event_counts"]:
            print("\n  触发的连锁事件:")
            for ename, cnt in sorted(r["event_counts"].items(), key=lambda x: -x[1]):
                print(f"    {ename}: {cnt}次")

        # Resource trend
        print("\n  资源趋势 (每半年采样):")
        print(f"    {'时间'.ljust(10)} {'国库'.rjust(4)} {'人口'.rjust(4)} {'军备'.rjust(4)} {'民心'.rjust(4)} {'军心'.rjust(4)} {'威望'.rjust(4)}")
        for t in r["trends"]:
            time_str = f"{t['year']}/{t['month']}"
            print(f"    {time_str.ljust(10)} {t['treasury']:4d} {t['population']:4d} {t['military_supply']:4d} {t['civil_morale']:4d} {t['military_morale']:4d} {t['court_prestige']:4d}")

        # Final region status
        print("\n  终局区域稳定度:")
        for rname, stab in sorted(r["region_final"].items(), key=lambda x: x[1]):
            bar = "▓" * (stab // 2) if stab > 0 else "✕"
            print(f"    {rname.ljust(6)} {str(stab).rjust(3)}  {bar}")

        # Final faction status
        print("\n  终局派系状态:")
        print(f"    {'派系'.ljust(10)} {'满意'.rjust(4)} {'叛乱风险'.rjust(8)}")
        for fname in r["faction_final_risk"]:
            sat = r["faction_final_sat"].get(fname, 0)
            risk = r["faction_final_risk"].get(fname, 0)
            risk_warn = " ⚠" if risk > 60 else " ☠" if risk > 80 else ""
            print(f"    {fname.ljust(10)} {sat:4d} {risk:8d}{risk_warn}")

        if r["final_memorials_pending"]:
            print(f"\n  未处理奏疏: {r['final_memorials_pending']}")

    # ── Cross-strategy Analysis ──
    print(f"\n{sep}")
    print("  跨策略分析")
    print(sep)

    # Survival ranking
    print("\n  存活时长排名:")
    ranked = sorted(reports, key=lambda r: r["total_turns"], reverse=True)
    for i, r in enumerate(ranked, 1):
        print(f"    {i}. {r['name']} — {r['total_turns']}回合 ({r['end_time'] or '未结束'})")

    # Victory check
    victories = [r for r in reports if r["result"] == "victory"]
    if victories:
        print(f"\n  胜利策略: {', '.join(r['name'] for r in victories)}")
    else:
        print(f"\n  ⚠ 没有策略达成胜利条件")

    # Common death cause
    defeat_msgs: dict[str, int] = {}
    for r in reports:
        if r["result"] == "defeat":
            msg = r["result_msg"]
            defeat_msgs[msg] = defeat_msgs.get(msg, 0) + 1
    if defeat_msgs:
        print("\n  失败原因统计:")
        for msg, cnt in sorted(defeat_msgs.items(), key=lambda x: -x[1]):
            print(f"    {msg}: {cnt}次")

    # Balance issues
    print(f"\n{sep}")
    print("  平衡性问题诊断")
    print(sep)

    issues = []

    # 1. all strategies die too early
    avg_turns = sum(r["total_turns"] for r in reports) / len(reports)
    max_possible = (1644 - 1627) * 12  # ~204
    if avg_turns < max_possible * 0.3:
        issues.append(f"平均存活{avg_turns:.0f}回合，仅占总时间轴{avg_turns/max_possible*100:.0f}%，游戏可能过难")

    # 2. all die from same cause
    if len(defeat_msgs) == 1:
        issues.append(f"所有失败都因同一原因: {list(defeat_msgs.keys())[0]}，缺乏多样性")

    # 3. treasury always hits zero
    treasury_zero_count = sum(1 for r in reports if r["treasury_zero"] is not None)
    if treasury_zero_count == len(reports):
        avg_zero_time = sum(
            (r["treasury_zero"][0] - 1627) * 12 + r["treasury_zero"][1]
            for r in reports if r["treasury_zero"]
        ) / treasury_zero_count
        issues.append(f"所有策略都出现国库归零，平均在{avg_zero_time:.0f}个月后，经济系统可能过于严苛")

    # 4. no strategy can reach 1644
    if all(r["total_turns"] < max_possible - 10 for r in reports):
        issues.append("没有策略能存活到1644年，胜利条件可能不可达")

    # 5. passive drift too punishing
    do_nothing = next((r for r in reports if "无为" in r["name"]), None)
    balanced = next((r for r in reports if "均衡" in r["name"]), None)
    if do_nothing and balanced:
        ratio = balanced["total_turns"] / max(do_nothing["total_turns"], 1)
        if ratio < 1.5:
            issues.append(f"积极施政(均衡)仅比无为多存活{ratio:.1f}倍，主动操作的奖励不足")

    # 6. court_prestige is the binding constraint
    prestige_deaths = sum(1 for r in reports if "威严" in r.get("result_msg", ""))
    if prestige_deaths > len(reports) * 0.5:
        issues.append(f"{prestige_deaths}/{len(reports)}个策略因威望归零失败，court_prestige衰减可能过快")

    # 7. regions fall too fast
    early_fall = sum(1 for r in reports if r["first_fallen"] and (r["first_fallen"][0] - 1627) * 12 + r["first_fallen"][1] < 24)
    if early_fall > len(reports) * 0.5:
        issues.append(f"{early_fall}/{len(reports)}个策略在2年内出现区域沦陷，区域稳定度衰减可能过快")

    if issues:
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")
    else:
        print("  未发现明显平衡性问题 ✓")

    print(f"\n{sep}")
    print("  报告结束")
    print(f"{sep}\n")


def _decree_label(dtype: str) -> str:
    labels = {
        "tax_increase": "加税",
        "tax_decrease": "减税",
        "recruit_troops": "征兵",
        "disband_troops": "裁兵",
        "personnel": "任免",
        "diplomacy": "外交",
        "disaster_relief": "赈灾",
        "harsh_punishment": "严刑",
        "wait": "等待",
    }
    return labels.get(dtype, dtype)


# ── Main ────────────────────────────────────────────────

def main():
    reports = []
    for name, fn in STRATEGIES.items():
        print(f"模拟中: {name} ...", flush=True)
        report = simulate(fn, name)
        reports.append(report)
        print(f"  → {report['result']} @ {report['end_time'] or 'N/A'} ({report['total_turns']}回合)")

    print_report(reports)


if __name__ == "__main__":
    main()
