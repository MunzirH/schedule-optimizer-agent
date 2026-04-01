"""
Schedule Risk Analysis Engine.

Goes beyond DCMA pass/fail checks to provide actionable risk intelligence:
  - Near-critical path identification (float < threshold)
  - Float distribution analysis (histogram buckets)
  - Negative float drill-down by WBS area
  - Schedule health metrics (BEI, CPLI, SPI)
  - Top risk activities ranked by impact
  - Resource overallocation detection
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict

from models.schedule import (
    ScheduleData, Activity, Relationship,
    ActivityType, ActivityStatus, RelationshipType,
)


# ── Data classes ─────────────────────────────────────────────────────

@dataclass
class RiskActivity:
    """An activity flagged as a risk, with context."""
    activity_id: str
    name: str
    duration: float
    total_float: float
    risk_category: str          # "critical", "near_critical", "negative_float", "high_duration"
    risk_score: float           # 0-100, higher = worse
    wbs_id: str = ""
    start_date: str = ""
    finish_date: str = ""


@dataclass
class FloatBucket:
    """One bucket in the float distribution histogram."""
    label: str
    min_float: float
    max_float: float
    count: int
    percentage: float
    activity_ids: list[str] = field(default_factory=list)


@dataclass
class WBSRiskSummary:
    """Risk summary for a single WBS area."""
    wbs_id: str
    wbs_name: str
    total_activities: int
    critical_count: int
    near_critical_count: int
    negative_float_count: int
    avg_float: float
    min_float: float
    risk_score: float           # aggregate risk score for this WBS


@dataclass
class ScheduleComparison:
    """Comparison between two schedule versions."""
    added_activities: list[str] = field(default_factory=list)
    removed_activities: list[str] = field(default_factory=list)
    duration_changes: list[dict] = field(default_factory=list)
    float_changes: list[dict] = field(default_factory=list)
    status_changes: list[dict] = field(default_factory=list)
    critical_path_changes: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


@dataclass
class RiskReport:
    """Complete risk analysis report."""
    # Summary metrics
    total_activities: int = 0
    incomplete_activities: int = 0
    critical_count: int = 0
    near_critical_count: int = 0
    negative_float_count: int = 0
    avg_float: float = 0.0

    # Schedule performance indices
    cpli: float = 1.0           # Critical Path Length Index
    bei: float = 1.0            # Baseline Execution Index

    # Detailed analysis
    float_distribution: list[FloatBucket] = field(default_factory=list)
    top_risks: list[RiskActivity] = field(default_factory=list)
    wbs_risks: list[WBSRiskSummary] = field(default_factory=list)
    resource_conflicts: list[dict] = field(default_factory=list)

    @property
    def risk_level(self) -> str:
        """Overall risk level based on metrics."""
        if self.negative_float_count > 0 or self.bei < 0.85:
            return "HIGH"
        elif self.near_critical_count > self.incomplete_activities * 0.2 or self.bei < 0.95:
            return "MEDIUM"
        else:
            return "LOW"


# ── Core Analysis Functions ──────────────────────────────────────────

def analyze_risks(schedule: ScheduleData, near_critical_threshold: float = 10.0) -> RiskReport:
    """
    Run comprehensive risk analysis on a schedule.

    Args:
        schedule: Parsed schedule data
        near_critical_threshold: Float threshold for near-critical (default 10 days)

    Returns:
        RiskReport with all risk metrics and drill-downs
    """
    report = RiskReport()

    incomplete = [
        a for a in schedule.activities
        if a.status != ActivityStatus.COMPLETED
        and a.activity_type in (ActivityType.TASK, ActivityType.MILESTONE)
    ]

    report.total_activities = len(schedule.activities)
    report.incomplete_activities = len(incomplete)

    # Always compute performance indices (they look at completed work too)
    report.bei = _compute_bei(schedule)
    report.cpli = _compute_cpli(schedule)

    if not incomplete:
        return report

    # ── Float analysis ───────────────────────────────────────────
    floats = [a.total_float for a in incomplete if a.total_float is not None]

    if floats:
        report.avg_float = sum(floats) / len(floats)

    report.critical_count = len([
        a for a in incomplete
        if a.total_float is not None and abs(a.total_float) < 0.01
    ])

    report.near_critical_count = len([
        a for a in incomplete
        if a.total_float is not None
        and 0 < a.total_float <= near_critical_threshold
    ])

    report.negative_float_count = len([
        a for a in incomplete
        if a.total_float is not None and a.total_float < 0
    ])

    # ── Float distribution ───────────────────────────────────────
    report.float_distribution = _compute_float_distribution(incomplete)

    # ── Top risks ────────────────────────────────────────────────
    report.top_risks = _identify_top_risks(incomplete, near_critical_threshold)

    # ── WBS risk breakdown ───────────────────────────────────────
    report.wbs_risks = _analyze_wbs_risks(incomplete, schedule.wbs, near_critical_threshold)

    # ── Resource conflicts ───────────────────────────────────────
    report.resource_conflicts = _detect_resource_conflicts(schedule)

    return report


def _compute_float_distribution(incomplete: list[Activity]) -> list[FloatBucket]:
    """Compute float distribution histogram."""
    buckets_def = [
        ("Negative (< 0)", -999999, -0.01),
        ("Critical (0)", -0.01, 0.01),
        ("Near-critical (1-10)", 0.01, 10),
        ("Low float (11-20)", 10, 20),
        ("Moderate (21-44)", 20, 44),
        ("High (45-100)", 44, 100),
        ("Very high (100+)", 100, 999999),
    ]

    activities_with_float = [a for a in incomplete if a.total_float is not None]
    total = len(activities_with_float)

    buckets = []
    for label, min_f, max_f in buckets_def:
        matching = [
            a for a in activities_with_float
            if min_f < a.total_float <= max_f
            or (label == "Critical (0)" and abs(a.total_float) < 0.01)
        ]
        count = len(matching)
        pct = (count / total * 100) if total > 0 else 0

        buckets.append(FloatBucket(
            label=label,
            min_float=min_f,
            max_float=max_f,
            count=count,
            percentage=round(pct, 1),
            activity_ids=[a.activity_id for a in matching[:20]],
        ))

    return buckets


def _identify_top_risks(incomplete: list[Activity], threshold: float) -> list[RiskActivity]:
    """Identify and rank the top risk activities."""
    risks = []

    for a in incomplete:
        if a.total_float is None:
            continue

        risk_score = 0
        category = ""

        if a.total_float < 0:
            # Negative float — severity increases with magnitude and duration
            risk_score = min(100, abs(a.total_float) * 2 + a.duration * 0.5)
            category = "negative_float"
        elif abs(a.total_float) < 0.01:
            # Critical — risk based on duration (longer critical = more risk)
            risk_score = min(80, 40 + a.duration * 0.5)
            category = "critical"
        elif a.total_float <= threshold:
            # Near-critical
            risk_score = min(60, 20 + (threshold - a.total_float) * 3)
            category = "near_critical"
        elif a.duration > 44:
            # High duration (could absorb delays but hard to manage)
            risk_score = min(40, a.duration * 0.1)
            category = "high_duration"
        else:
            continue

        risks.append(RiskActivity(
            activity_id=a.activity_id,
            name=a.name,
            duration=a.duration,
            total_float=a.total_float,
            risk_category=category,
            risk_score=round(risk_score, 1),
            wbs_id=a.wbs_id or "",
            start_date=a.start_date.strftime("%Y-%m-%d") if a.start_date else "",
            finish_date=a.finish_date.strftime("%Y-%m-%d") if a.finish_date else "",
        ))

    # Sort by risk score descending
    risks.sort(key=lambda r: r.risk_score, reverse=True)
    return risks[:50]  # top 50


def _analyze_wbs_risks(
    incomplete: list[Activity],
    wbs_nodes: list,
    threshold: float,
) -> list[WBSRiskSummary]:
    """Break down risk metrics by WBS area."""
    wbs_map = defaultdict(list)

    for a in incomplete:
        wbs_id = a.wbs_id or "Unassigned"
        wbs_map[wbs_id].append(a)

    # Build name lookup
    wbs_names = {w.wbs_id: w.name for w in wbs_nodes}

    summaries = []
    for wbs_id, activities in wbs_map.items():
        floats = [a.total_float for a in activities if a.total_float is not None]

        critical = len([a for a in activities if a.total_float is not None and abs(a.total_float) < 0.01])
        near_crit = len([a for a in activities if a.total_float is not None and 0 < a.total_float <= threshold])
        neg_float = len([a for a in activities if a.total_float is not None and a.total_float < 0])

        avg_f = sum(floats) / len(floats) if floats else 0
        min_f = min(floats) if floats else 0

        # Risk score: weighted combination of negative float count and critical density
        total = len(activities)
        risk_score = 0
        if total > 0:
            neg_pct = neg_float / total
            crit_pct = (critical + near_crit) / total
            risk_score = (neg_pct * 60 + crit_pct * 30 + (1 if min_f < -20 else 0) * 10)
            risk_score = round(min(100, risk_score * 100), 1)

        summaries.append(WBSRiskSummary(
            wbs_id=wbs_id,
            wbs_name=wbs_names.get(wbs_id, wbs_id),
            total_activities=total,
            critical_count=critical,
            near_critical_count=near_crit,
            negative_float_count=neg_float,
            avg_float=round(avg_f, 1),
            min_float=round(min_f, 1),
            risk_score=risk_score,
        ))

    # Sort by risk score descending
    summaries.sort(key=lambda s: s.risk_score, reverse=True)
    return summaries


def _compute_bei(schedule: ScheduleData) -> float:
    """
    Baseline Execution Index.

    BEI = tasks completed on or before baseline finish / tasks that should be complete by now.
    Target: >= 0.95. Below 0.95 indicates schedule slippage.
    """
    data_date = schedule.project.data_date
    if not data_date:
        return 1.0

    should_be_done = [
        a for a in schedule.activities
        if a.baseline_finish is not None
        and a.baseline_finish <= data_date
        and a.activity_type in (ActivityType.TASK, ActivityType.MILESTONE)
    ]

    if not should_be_done:
        return 1.0

    completed_on_time = [
        a for a in should_be_done
        if a.status == ActivityStatus.COMPLETED
    ]

    return round(len(completed_on_time) / len(should_be_done), 3)


def _compute_cpli(schedule: ScheduleData) -> float:
    """
    Critical Path Length Index.

    CPLI = (critical path length + total float) / critical path length.
    Target: >= 1.0. Below 0.95 indicates the project likely cannot finish on time.

    Simplified: uses project dates and overall float.
    """
    if not schedule.project.start_date or not schedule.project.finish_date:
        return 1.0

    data_date = schedule.project.data_date or schedule.project.start_date

    # Critical path length = working days from data date to planned finish
    cp_length = (schedule.project.finish_date - data_date).days
    if cp_length <= 0:
        return 0.0

    # Total float = sum of float on critical/near-critical activities
    critical = [
        a for a in schedule.activities
        if a.total_float is not None
        and abs(a.total_float) < 0.01
        and a.status != ActivityStatus.COMPLETED
    ]

    # If we have negative float on the critical path, CPLI < 1
    min_float = 0
    neg_floats = [
        a.total_float for a in schedule.activities
        if a.total_float is not None and a.total_float < 0
    ]
    if neg_floats:
        min_float = min(neg_floats)

    cpli = (cp_length + min_float) / cp_length
    return round(max(0, cpli), 3)


def _detect_resource_conflicts(schedule: ScheduleData) -> list[dict]:
    """
    Detect resources assigned to overlapping activities.
    Returns top conflicts.
    """
    if not schedule.resource_assignments:
        return []

    # Build resource → activities map
    res_activities = defaultdict(list)
    for assignment in schedule.resource_assignments:
        activity = schedule.get_activity(assignment.activity_id)
        if activity and activity.start_date and activity.finish_date:
            if activity.status != ActivityStatus.COMPLETED:
                res_activities[assignment.resource_id].append(activity)

    # Find resource name lookup
    res_names = {r.resource_id: r.name for r in schedule.resources}

    conflicts = []
    for res_id, activities in res_activities.items():
        if len(activities) < 2:
            continue

        # Sort by start date
        sorted_acts = sorted(activities, key=lambda a: a.start_date)

        for i in range(len(sorted_acts)):
            for j in range(i + 1, min(i + 5, len(sorted_acts))):  # check nearby pairs
                a1 = sorted_acts[i]
                a2 = sorted_acts[j]

                # Check overlap
                if a1.start_date <= a2.finish_date and a2.start_date <= a1.finish_date:
                    overlap_start = max(a1.start_date, a2.start_date)
                    overlap_end = min(a1.finish_date, a2.finish_date)
                    overlap_days = (overlap_end - overlap_start).days

                    if overlap_days > 0:
                        conflicts.append({
                            "resource": res_names.get(res_id, res_id),
                            "activity_1": f"{a1.activity_id}: {a1.name[:40]}",
                            "activity_2": f"{a2.activity_id}: {a2.name[:40]}",
                            "overlap_days": overlap_days,
                        })

    # Sort by overlap days and return top 20
    conflicts.sort(key=lambda c: c["overlap_days"], reverse=True)
    return conflicts[:20]


# ── Schedule Comparison ──────────────────────────────────────────────

def compare_schedules(current: ScheduleData, previous: ScheduleData) -> ScheduleComparison:
    """
    Compare two schedule versions (e.g. this month vs last month).

    Returns changes in activities, durations, float, status, and critical path.
    """
    comp = ScheduleComparison()

    curr_ids = current.activity_ids()
    prev_ids = previous.activity_ids()

    comp.added_activities = sorted(curr_ids - prev_ids)
    comp.removed_activities = sorted(prev_ids - curr_ids)

    # Compare common activities
    common_ids = curr_ids & prev_ids

    for aid in common_ids:
        curr_act = current.get_activity(aid)
        prev_act = previous.get_activity(aid)

        if not curr_act or not prev_act:
            continue

        # Duration changes
        if curr_act.duration != prev_act.duration:
            comp.duration_changes.append({
                "activity_id": aid,
                "name": curr_act.name,
                "previous": prev_act.duration,
                "current": curr_act.duration,
                "delta": round(curr_act.duration - prev_act.duration, 1),
            })

        # Float changes
        if (curr_act.total_float is not None and prev_act.total_float is not None
                and curr_act.total_float != prev_act.total_float):
            comp.float_changes.append({
                "activity_id": aid,
                "name": curr_act.name,
                "previous": prev_act.total_float,
                "current": curr_act.total_float,
                "delta": round(curr_act.total_float - prev_act.total_float, 1),
            })

        # Status changes
        if curr_act.status != prev_act.status:
            comp.status_changes.append({
                "activity_id": aid,
                "name": curr_act.name,
                "previous": prev_act.status.value,
                "current": curr_act.status.value,
            })

        # Critical path changes
        curr_critical = curr_act.total_float is not None and abs(curr_act.total_float) < 0.01
        prev_critical = prev_act.total_float is not None and abs(prev_act.total_float) < 0.01

        if curr_critical != prev_critical:
            comp.critical_path_changes.append({
                "activity_id": aid,
                "name": curr_act.name,
                "was_critical": prev_critical,
                "now_critical": curr_critical,
            })

    # Sort float changes by delta (biggest losses first)
    comp.float_changes.sort(key=lambda x: x["delta"])
    comp.duration_changes.sort(key=lambda x: abs(x["delta"]), reverse=True)

    # Summary
    comp.summary = {
        "added": len(comp.added_activities),
        "removed": len(comp.removed_activities),
        "duration_changes": len(comp.duration_changes),
        "float_changes": len(comp.float_changes),
        "status_changes": len(comp.status_changes),
        "new_critical": len([c for c in comp.critical_path_changes if c["now_critical"]]),
        "removed_from_critical": len([c for c in comp.critical_path_changes if not c["now_critical"]]),
    }

    return comp


# ── Report Printer ───────────────────────────────────────────────────

def print_risk_report(report: RiskReport):
    """Print a formatted risk analysis report."""

    print(f"\n{'=' * 70}")
    print(f"  SCHEDULE RISK ANALYSIS")
    print(f"{'=' * 70}")
    print(f"  Risk Level:            {report.risk_level}")
    print(f"  Total Activities:      {report.total_activities}")
    print(f"  Incomplete Tasks:      {report.incomplete_activities}")
    print(f"  Critical:              {report.critical_count}")
    print(f"  Near-Critical (<10d):  {report.near_critical_count}")
    print(f"  Negative Float:        {report.negative_float_count}")
    print(f"  Average Float:         {report.avg_float:.1f} days")

    # Performance indices
    print(f"\n--- Performance Indices ---")
    bei_status = "OK" if report.bei >= 0.95 else ("WATCH" if report.bei >= 0.85 else "AT RISK")
    cpli_status = "OK" if report.cpli >= 1.0 else ("WATCH" if report.cpli >= 0.95 else "AT RISK")
    print(f"  BEI  (Baseline Execution):   {report.bei:.3f}  [{bei_status}]  (target >= 0.95)")
    print(f"  CPLI (Critical Path Length):  {report.cpli:.3f}  [{cpli_status}]  (target >= 1.00)")

    # Float distribution
    print(f"\n--- Float Distribution ---")
    for bucket in report.float_distribution:
        bar_len = int(bucket.percentage / 2)
        bar = "#" * bar_len
        print(f"  {bucket.label:<22} {bucket.count:>6}  ({bucket.percentage:>5.1f}%)  {bar}")

    # Top risks
    if report.top_risks:
        print(f"\n--- Top 20 Risk Activities ---")
        print(f"  {'ID':<10} {'Name':<32} {'Dur':>5} {'Float':>7} {'Score':>6} {'Category'}")
        print(f"  {'─' * 10} {'─' * 32} {'─' * 5} {'─' * 7} {'─' * 6} {'─' * 15}")
        for r in report.top_risks[:20]:
            name = r.name[:30] + ".." if len(r.name) > 32 else r.name
            print(
                f"  {r.activity_id:<10} {name:<32} {r.duration:>5.0f} {r.total_float:>7.0f} "
                f"{r.risk_score:>6.1f} {r.risk_category}"
            )

    # WBS risk breakdown
    if report.wbs_risks:
        top_wbs = [w for w in report.wbs_risks if w.risk_score > 0][:15]
        if top_wbs:
            print(f"\n--- Top Risk Areas (by WBS) ---")
            print(f"  {'WBS':<35} {'Acts':>5} {'Crit':>5} {'Near':>5} {'Neg':>5} {'Score':>6}")
            print(f"  {'─' * 35} {'─' * 5} {'─' * 5} {'─' * 5} {'─' * 5} {'─' * 6}")
            for w in top_wbs:
                name = w.wbs_name[:33] + ".." if len(w.wbs_name) > 35 else w.wbs_name
                print(
                    f"  {name:<35} {w.total_activities:>5} {w.critical_count:>5} "
                    f"{w.near_critical_count:>5} {w.negative_float_count:>5} {w.risk_score:>6.1f}"
                )

    # Resource conflicts
    if report.resource_conflicts:
        print(f"\n--- Resource Conflicts (Top 10) ---")
        for c in report.resource_conflicts[:10]:
            print(f"  {c['resource']}: {c['overlap_days']}d overlap")
            print(f"    {c['activity_1']}")
            print(f"    {c['activity_2']}")

    print(f"\n{'=' * 70}\n")


def print_comparison_report(comp: ScheduleComparison):
    """Print a formatted schedule comparison report."""

    print(f"\n{'=' * 70}")
    print(f"  SCHEDULE UPDATE COMPARISON")
    print(f"{'=' * 70}")

    s = comp.summary
    print(f"  Activities Added:          {s['added']}")
    print(f"  Activities Removed:        {s['removed']}")
    print(f"  Duration Changes:          {s['duration_changes']}")
    print(f"  Float Changes:             {s['float_changes']}")
    print(f"  Status Changes:            {s['status_changes']}")
    print(f"  New Critical Activities:   {s['new_critical']}")
    print(f"  Removed from Critical:     {s['removed_from_critical']}")

    if comp.float_changes:
        print(f"\n--- Biggest Float Losses ---")
        for c in comp.float_changes[:15]:
            name = c["name"][:35]
            print(f"  {c['activity_id']:<10} {name:<35} {c['previous']:>6.0f} -> {c['current']:>6.0f} ({c['delta']:>+.0f}d)")

    if comp.critical_path_changes:
        new_crit = [c for c in comp.critical_path_changes if c["now_critical"]]
        if new_crit:
            print(f"\n--- Newly Critical Activities ---")
            for c in new_crit[:15]:
                print(f"  {c['activity_id']:<10} {c['name'][:50]}")

    if comp.duration_changes:
        print(f"\n--- Biggest Duration Changes ---")
        for c in comp.duration_changes[:15]:
            name = c["name"][:35]
            print(f"  {c['activity_id']:<10} {name:<35} {c['previous']:>6.0f} -> {c['current']:>6.0f} ({c['delta']:>+.0f}d)")

    print(f"\n{'=' * 70}\n")
