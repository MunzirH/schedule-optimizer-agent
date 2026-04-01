"""
CPM (Critical Path Method) Engine.

Operates on ScheduleData to compute:
  - Forward pass (early start / early finish)
  - Backward pass (late start / late finish)
  - Total float and free float
  - Critical path
  - Driving path to any activity
  - What-if scenario analysis
"""

import networkx as nx
from dataclasses import dataclass, field

from models.schedule import (
    ScheduleData, Activity, Relationship,
    ActivityType, ActivityStatus, RelationshipType,
)


class CPMError(Exception):
    pass


@dataclass
class CPMResult:
    """Result of a CPM computation."""
    critical_path: list[str] = field(default_factory=list)
    total_duration: float = 0.0
    task_details: dict = field(default_factory=dict)
    has_cycles: bool = False
    cycle_nodes: list[str] = field(default_factory=list)


@dataclass
class DrivingPathResult:
    """Result of tracing the driving path to an activity."""
    target_id: str = ""
    driving_path: list[str] = field(default_factory=list)
    driving_relationships: list[dict] = field(default_factory=list)
    total_duration: float = 0.0
    bottleneck_id: str = ""
    bottleneck_name: str = ""


@dataclass
class WhatIfResult:
    """Result of a what-if scenario."""
    scenario: str = ""
    original_duration: float = 0.0
    new_duration: float = 0.0
    delta: float = 0.0
    original_critical_path: list[str] = field(default_factory=list)
    new_critical_path: list[str] = field(default_factory=list)
    affected_activities: list[dict] = field(default_factory=list)


def build_network(schedule: ScheduleData) -> nx.DiGraph:
    """Build a NetworkX DiGraph from ScheduleData."""
    G = nx.DiGraph()

    for a in schedule.activities:
        if a.activity_type in (ActivityType.SUMMARY, ActivityType.WBS_SUMMARY):
            continue
        G.add_node(
            a.activity_id,
            duration=a.duration,
            name=a.name,
            status=a.status.value,
            activity_type=a.activity_type.value,
            wbs_id=a.wbs_id or "",
            original_float=a.total_float,
        )

    valid_ids = set(G.nodes)
    for r in schedule.relationships:
        if r.predecessor_id in valid_ids and r.successor_id in valid_ids:
            G.add_edge(
                r.predecessor_id,
                r.successor_id,
                rel_type=r.relationship_type.name,
                lag=r.lag_days,
            )

    return G


def compute_cpm(schedule: ScheduleData) -> CPMResult:
    """
    Run full CPM computation on a schedule.

    Builds the network, detects cycles, adds virtual start/end,
    runs forward and backward pass, computes float, identifies critical path.
    """
    G = build_network(schedule)
    result = CPMResult()

    if len(G.nodes) == 0:
        return result

    # Check for cycles
    if not nx.is_directed_acyclic_graph(G):
        result.has_cycles = True
        try:
            cycle = nx.find_cycle(G)
            result.cycle_nodes = list(set(n for edge in cycle for n in edge[:2]))
        except nx.NetworkXNoCycle:
            pass
        return result

    # Add virtual START and END
    G = G.copy()
    G.add_node("__START__", duration=0, name="Virtual Start")
    G.add_node("__END__", duration=0, name="Virtual End")

    for node in list(G.nodes):
        if node in ("__START__", "__END__"):
            continue
        if len(list(G.predecessors(node))) == 0:
            G.add_edge("__START__", node, rel_type="FS", lag=0)
        if len(list(G.successors(node))) == 0:
            G.add_edge(node, "__END__", rel_type="FS", lag=0)

    topo = list(nx.topological_sort(G))

    # Forward pass
    es = {}
    ef = {}
    for node in topo:
        dur = G.nodes[node].get("duration", 0)
        preds = list(G.predecessors(node))
        if not preds:
            es[node] = 0
        else:
            es[node] = max(ef[p] + G.edges[p, node].get("lag", 0) for p in preds)
        ef[node] = es[node] + dur

    result.total_duration = ef["__END__"]

    # Backward pass
    ls = {}
    lf = {}
    for node in reversed(topo):
        dur = G.nodes[node].get("duration", 0)
        succs = list(G.successors(node))
        if not succs:
            lf[node] = result.total_duration
        else:
            lf[node] = min(ls[s] - G.edges[node, s].get("lag", 0) for s in succs)
        ls[node] = lf[node] - dur

    # Build task details
    for node in G.nodes:
        if node in ("__START__", "__END__"):
            continue
        total_float = round(ls[node] - es[node], 2)

        # Free float = min(ES of successors + lag) - EF of this
        succs = list(G.successors(node))
        if succs:
            free_float = round(
                min(es[s] + G.edges[node, s].get("lag", 0) for s in succs if s != "__END__")
                - ef[node], 2
            ) if any(s != "__END__" for s in succs) else total_float
        else:
            free_float = total_float

        result.task_details[node] = {
            "earliest_start": round(es[node], 2),
            "earliest_finish": round(ef[node], 2),
            "latest_start": round(ls[node], 2),
            "latest_finish": round(lf[node], 2),
            "total_float": total_float,
            "free_float": free_float,
            "is_critical": abs(total_float) < 0.01,
            "name": G.nodes[node].get("name", node),
            "duration": G.nodes[node].get("duration", 0),
        }

    # Trace critical path
    current = "__END__"
    path = []
    while current != "__START__":
        preds = list(G.predecessors(current))
        if not preds:
            break
        critical_preds = [
            p for p in preds
            if p == "__START__" or abs(ls.get(p, 0) - es.get(p, 0)) < 0.01
        ]
        if critical_preds:
            current = max(critical_preds, key=lambda p: ef.get(p, 0))
        else:
            current = max(preds, key=lambda p: ef.get(p, 0))
        if current != "__START__":
            path.insert(0, current)

    result.critical_path = path
    return result


def find_driving_path(schedule: ScheduleData, target_id: str) -> DrivingPathResult:
    """
    Trace the driving (longest) path to a specific activity.
    Shows exactly what chain of activities is determining this activity's dates.
    """
    G = build_network(schedule)
    result = DrivingPathResult(target_id=target_id)

    if target_id not in G.nodes:
        return result

    # Walk backwards from target, always following the driving predecessor
    G_with_virtual = G.copy()
    G_with_virtual.add_node("__START__", duration=0)
    for node in list(G_with_virtual.nodes):
        if node == "__START__":
            continue
        if len(list(G_with_virtual.predecessors(node))) == 0:
            G_with_virtual.add_edge("__START__", node, rel_type="FS", lag=0)

    if not nx.is_directed_acyclic_graph(G_with_virtual):
        return result

    # Forward pass to get ES/EF
    topo = list(nx.topological_sort(G_with_virtual))
    es = {}
    ef = {}
    for node in topo:
        dur = G_with_virtual.nodes[node].get("duration", 0)
        preds = list(G_with_virtual.predecessors(node))
        if not preds:
            es[node] = 0
        else:
            es[node] = max(ef[p] + G_with_virtual.edges[p, node].get("lag", 0) for p in preds)
        ef[node] = es[node] + dur

    # Trace back from target
    path = [target_id]
    current = target_id
    total_dur = G.nodes[target_id].get("duration", 0)

    while True:
        preds = list(G_with_virtual.predecessors(current))
        preds = [p for p in preds if p != "__START__"]
        if not preds:
            break

        # The driving predecessor is the one with the latest EF
        driver = max(preds, key=lambda p: ef.get(p, 0) + G_with_virtual.edges[p, current].get("lag", 0))
        path.insert(0, driver)

        rel_data = G_with_virtual.edges[driver, current]
        result.driving_relationships.append({
            "from": driver,
            "to": current,
            "type": rel_data.get("rel_type", "FS"),
            "lag": rel_data.get("lag", 0),
        })

        total_dur += G_with_virtual.nodes[driver].get("duration", 0)
        current = driver

    result.driving_path = path
    result.total_duration = total_dur

    # Identify bottleneck (longest activity on the driving path)
    if path:
        bottleneck = max(path, key=lambda n: G.nodes[n].get("duration", 0) if n in G.nodes else 0)
        result.bottleneck_id = bottleneck
        result.bottleneck_name = G.nodes[bottleneck].get("name", bottleneck) if bottleneck in G.nodes else bottleneck

    return result


def what_if_delay(schedule: ScheduleData, activity_id: str, delay_days: float) -> WhatIfResult:
    """
    Simulate: what happens if this activity's duration increases by delay_days?
    Returns impact on project duration and critical path.
    """
    result = WhatIfResult()
    result.scenario = "Delay " + activity_id + " by " + str(delay_days) + " days"

    # Compute original
    original = compute_cpm(schedule)
    result.original_duration = original.total_duration
    result.original_critical_path = original.critical_path

    # Create modified schedule
    from copy import deepcopy
    modified = deepcopy(schedule)
    act = modified.get_activity(activity_id)
    if not act:
        result.new_duration = original.total_duration
        result.delta = 0
        return result

    act.duration += delay_days

    # Compute modified
    new_cpm = compute_cpm(modified)
    result.new_duration = new_cpm.total_duration
    result.new_critical_path = new_cpm.critical_path
    result.delta = new_cpm.total_duration - original.total_duration

    # Find affected activities (float changed)
    for aid, new_detail in new_cpm.task_details.items():
        if aid in original.task_details:
            old_float = original.task_details[aid]["total_float"]
            new_float = new_detail["total_float"]
            if abs(old_float - new_float) > 0.01:
                result.affected_activities.append({
                    "activity_id": aid,
                    "name": new_detail["name"],
                    "old_float": old_float,
                    "new_float": new_float,
                    "float_change": round(new_float - old_float, 2),
                })

    result.affected_activities.sort(key=lambda x: x["float_change"])
    return result


def find_missing_logic(schedule: ScheduleData) -> dict:
    """
    Detect logic issues and suggest fixes.

    Returns:
      - open_starts: activities with no predecessors
      - open_ends: activities with no successors
      - dangling: activities with neither
      - suggestions: potential relationships based on WBS proximity
    """
    successor_ids = {r.successor_id for r in schedule.relationships}
    predecessor_ids = {r.predecessor_id for r in schedule.relationships}

    tasks = [
        a for a in schedule.activities
        if a.activity_type in (ActivityType.TASK, ActivityType.MILESTONE)
        and a.status != ActivityStatus.COMPLETED
    ]

    open_starts = [a for a in tasks if a.activity_id not in successor_ids]
    open_ends = [a for a in tasks if a.activity_id not in predecessor_ids]
    dangling = [a for a in tasks
                if a.activity_id not in successor_ids
                and a.activity_id not in predecessor_ids]

    # Suggest relationships based on WBS grouping and dates
    suggestions = []
    wbs_groups = {}
    for a in tasks:
        wbs = a.wbs_id or "none"
        if wbs not in wbs_groups:
            wbs_groups[wbs] = []
        wbs_groups[wbs].append(a)

    for wbs_id, acts in wbs_groups.items():
        if len(acts) < 2:
            continue
        # Sort by start date
        dated = [a for a in acts if a.start_date]
        if len(dated) < 2:
            continue
        dated.sort(key=lambda a: a.start_date)

        for i in range(len(dated) - 1):
            a1 = dated[i]
            a2 = dated[i + 1]
            # If a2 starts after a1 and they're not already linked
            already_linked = any(
                r.predecessor_id == a1.activity_id and r.successor_id == a2.activity_id
                for r in schedule.relationships
            )
            if not already_linked and a1.activity_id in [x.activity_id for x in open_ends]:
                suggestions.append({
                    "from": a1.activity_id,
                    "from_name": a1.name,
                    "to": a2.activity_id,
                    "to_name": a2.name,
                    "wbs": wbs_id,
                    "type": "FS",
                    "reason": "Sequential dates within same WBS, open end",
                })

    return {
        "open_starts": [{"id": a.activity_id, "name": a.name, "wbs": a.wbs_id} for a in open_starts],
        "open_ends": [{"id": a.activity_id, "name": a.name, "wbs": a.wbs_id} for a in open_ends],
        "dangling": [{"id": a.activity_id, "name": a.name, "wbs": a.wbs_id} for a in dangling],
        "suggestions": suggestions[:50],
        "summary": {
            "open_starts": len(open_starts),
            "open_ends": len(open_ends),
            "dangling": len(dangling),
            "suggestions": min(len(suggestions), 50),
        },
    }
