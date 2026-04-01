"""
DCMA 14-Point Schedule Assessment Engine.

Implements the Defense Contract Management Agency's 14-point schedule
quality assessment, widely adopted across construction, aerospace,
and infrastructure industries.

Each check returns a DcmaCheckResult with:
  - pass/fail status (based on DCMA thresholds)
  - the metric value
  - the threshold
  - list of flagged activities for drill-down

Reference thresholds from DCMA-EA PAM 200.1.
"""

from dataclasses import dataclass, field
from models.schedule import (
    ScheduleData, Activity, Relationship,
    ActivityType, ActivityStatus, RelationshipType,
)


@dataclass
class DcmaCheckResult:
    """Result of a single DCMA check."""
    check_number: int
    name: str
    description: str
    passed: bool
    metric_value: float           # the computed metric (e.g. 3.2%)
    threshold: float              # the DCMA threshold (e.g. 5.0%)
    threshold_direction: str      # "max" = must be below, "min" = must be above
    unit: str = "%"               # display unit
    flagged_ids: list[str] = field(default_factory=list)
    detail: str = ""

    @property
    def grade(self) -> str:
        return "PASS" if self.passed else "FAIL"


@dataclass
class DcmaReport:
    """Complete DCMA 14-point assessment report."""
    checks: list[DcmaCheckResult] = field(default_factory=list)
    total_activities: int = 0
    incomplete_activities: int = 0

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for c in self.checks if not c.passed)

    @property
    def score_pct(self) -> float:
        if not self.checks:
            return 0.0
        return (self.passed_count / len(self.checks)) * 100

    @property
    def grade(self) -> str:
        pct = self.score_pct
        if pct >= 85:
            return "A"
        elif pct >= 70:
            return "B"
        elif pct >= 50:
            return "C"
        else:
            return "F"


def _get_incomplete_tasks(schedule: ScheduleData) -> list[Activity]:
    """Get non-completed task activities (excludes milestones, LOE, summaries)."""
    return [
        a for a in schedule.activities
        if a.status != ActivityStatus.COMPLETED
        and a.activity_type == ActivityType.TASK
    ]


def _get_all_tasks(schedule: ScheduleData) -> list[Activity]:
    """Get all task activities (excludes LOE, summaries)."""
    return [
        a for a in schedule.activities
        if a.activity_type in (ActivityType.TASK, ActivityType.MILESTONE)
    ]


def run_dcma_assessment(schedule: ScheduleData) -> DcmaReport:
    """
    Run the full DCMA 14-point assessment on a schedule.

    Returns a DcmaReport with all 14 check results.
    """
    report = DcmaReport()
    report.total_activities = len(schedule.activities)

    incomplete = _get_incomplete_tasks(schedule)
    report.incomplete_activities = len(incomplete)

    all_tasks = _get_all_tasks(schedule)

    report.checks = [
        check_1_missing_predecessors(schedule, incomplete),
        check_2_missing_successors(schedule, incomplete),
        check_3_missing_logic(schedule, incomplete),
        check_4_leads(schedule),
        check_5_lags(schedule),
        check_6_relationship_types(schedule),
        check_7_hard_constraints(schedule, incomplete),
        check_8_high_float(schedule, incomplete),
        check_9_negative_float(schedule, incomplete),
        check_10_high_duration(schedule, incomplete),
        check_11_invalid_dates(schedule),
        check_12_resources(schedule, incomplete),
        check_13_missed_tasks(schedule, all_tasks),
        check_14_critical_path_test(schedule),
    ]

    return report


# ── Check 1: Missing Predecessors ────────────────────────────────────

def check_1_missing_predecessors(schedule: ScheduleData, incomplete: list[Activity]) -> DcmaCheckResult:
    """
    Activities without predecessors (open-ended start).
    DCMA threshold: <= 5% of incomplete tasks.
    """
    if not incomplete:
        return DcmaCheckResult(1, "Missing Predecessors", "Incomplete tasks with no predecessors",
                               True, 0.0, 5.0, "max")

    successor_ids = {r.successor_id for r in schedule.relationships}
    flagged = [a for a in incomplete if a.activity_id not in successor_ids]

    pct = (len(flagged) / len(incomplete)) * 100 if incomplete else 0

    return DcmaCheckResult(
        check_number=1,
        name="Missing Predecessors",
        description="Incomplete tasks with no predecessors",
        passed=pct <= 5.0,
        metric_value=round(pct, 1),
        threshold=5.0,
        threshold_direction="max",
        flagged_ids=[a.activity_id for a in flagged],
        detail=f"{len(flagged)} of {len(incomplete)} incomplete tasks have no predecessors",
    )


# ── Check 2: Missing Successors ──────────────────────────────────────

def check_2_missing_successors(schedule: ScheduleData, incomplete: list[Activity]) -> DcmaCheckResult:
    """
    Activities without successors (open-ended finish).
    DCMA threshold: <= 5% of incomplete tasks.
    """
    if not incomplete:
        return DcmaCheckResult(2, "Missing Successors", "Incomplete tasks with no successors",
                               True, 0.0, 5.0, "max")

    predecessor_ids = {r.predecessor_id for r in schedule.relationships}
    flagged = [a for a in incomplete if a.activity_id not in predecessor_ids]

    pct = (len(flagged) / len(incomplete)) * 100 if incomplete else 0

    return DcmaCheckResult(
        check_number=2,
        name="Missing Successors",
        description="Incomplete tasks with no successors",
        passed=pct <= 5.0,
        metric_value=round(pct, 1),
        threshold=5.0,
        threshold_direction="max",
        flagged_ids=[a.activity_id for a in flagged],
        detail=f"{len(flagged)} of {len(incomplete)} incomplete tasks have no successors",
    )


# ── Check 3: Missing Logic (no pred OR no succ) ─────────────────────

def check_3_missing_logic(schedule: ScheduleData, incomplete: list[Activity]) -> DcmaCheckResult:
    """
    Activities missing either predecessors or successors.
    DCMA threshold: <= 5% of incomplete tasks.
    """
    if not incomplete:
        return DcmaCheckResult(3, "Missing Logic", "Incomplete tasks missing predecessors or successors",
                               True, 0.0, 5.0, "max")

    successor_ids = {r.successor_id for r in schedule.relationships}
    predecessor_ids = {r.predecessor_id for r in schedule.relationships}

    flagged = [
        a for a in incomplete
        if a.activity_id not in successor_ids or a.activity_id not in predecessor_ids
    ]

    pct = (len(flagged) / len(incomplete)) * 100 if incomplete else 0

    return DcmaCheckResult(
        check_number=3,
        name="Missing Logic",
        description="Incomplete tasks missing predecessors or successors",
        passed=pct <= 5.0,
        metric_value=round(pct, 1),
        threshold=5.0,
        threshold_direction="max",
        flagged_ids=[a.activity_id for a in flagged],
        detail=f"{len(flagged)} of {len(incomplete)} incomplete tasks have incomplete logic",
    )


# ── Check 4: Leads (Negative Lag) ───────────────────────────────────

def check_4_leads(schedule: ScheduleData) -> DcmaCheckResult:
    """
    Relationships with negative lag (leads).
    DCMA threshold: 0% — no leads allowed.
    """
    total_rels = len(schedule.relationships)
    if total_rels == 0:
        return DcmaCheckResult(4, "Leads", "Relationships with negative lag (leads)",
                               True, 0.0, 0.0, "max")

    flagged = [r for r in schedule.relationships if r.lag_days < 0]
    pct = (len(flagged) / total_rels) * 100

    return DcmaCheckResult(
        check_number=4,
        name="Leads",
        description="Relationships with negative lag (leads)",
        passed=len(flagged) == 0,
        metric_value=round(pct, 1),
        threshold=0.0,
        threshold_direction="max",
        flagged_ids=[f"{r.predecessor_id}->{r.successor_id}" for r in flagged],
        detail=f"{len(flagged)} of {total_rels} relationships have negative lag",
    )


# ── Check 5: Lags ───────────────────────────────────────────────────

def check_5_lags(schedule: ScheduleData) -> DcmaCheckResult:
    """
    Relationships with positive lag.
    DCMA threshold: <= 5% of relationships.
    """
    total_rels = len(schedule.relationships)
    if total_rels == 0:
        return DcmaCheckResult(5, "Lags", "Relationships with positive lag",
                               True, 0.0, 5.0, "max")

    flagged = [r for r in schedule.relationships if r.lag_days > 0]
    pct = (len(flagged) / total_rels) * 100

    return DcmaCheckResult(
        check_number=5,
        name="Lags",
        description="Relationships with positive lag",
        passed=pct <= 5.0,
        metric_value=round(pct, 1),
        threshold=5.0,
        threshold_direction="max",
        flagged_ids=[f"{r.predecessor_id}->{r.successor_id}" for r in flagged],
        detail=f"{len(flagged)} of {total_rels} relationships have positive lag",
    )


# ── Check 6: Relationship Types ──────────────────────────────────────

def check_6_relationship_types(schedule: ScheduleData) -> DcmaCheckResult:
    """
    Percentage of Finish-to-Start relationships.
    DCMA threshold: >= 90% should be FS.
    """
    total_rels = len(schedule.relationships)
    if total_rels == 0:
        return DcmaCheckResult(6, "Relationship Types", "Percentage of finish-to-start relationships",
                               True, 100.0, 90.0, "min")

    fs_count = sum(1 for r in schedule.relationships if r.relationship_type == RelationshipType.FS)
    pct = (fs_count / total_rels) * 100

    non_fs = [r for r in schedule.relationships if r.relationship_type != RelationshipType.FS]

    return DcmaCheckResult(
        check_number=6,
        name="Relationship Types",
        description="Percentage of finish-to-start relationships",
        passed=pct >= 90.0,
        metric_value=round(pct, 1),
        threshold=90.0,
        threshold_direction="min",
        flagged_ids=[f"{r.predecessor_id}->{r.successor_id} ({r.relationship_type.name})" for r in non_fs[:50]],
        detail=f"{fs_count} of {total_rels} relationships are finish-to-start",
    )


# ── Check 7: Hard Constraints ───────────────────────────────────────

def check_7_hard_constraints(schedule: ScheduleData, incomplete: list[Activity]) -> DcmaCheckResult:
    """
    Activities with hard constraints (MSO, MFO, SNET, SNLT, FNET, FNLT).
    DCMA threshold: <= 5% of incomplete tasks.
    """
    from models.schedule import ConstraintType

    hard_types = {
        ConstraintType.MSO, ConstraintType.MFO,
        ConstraintType.SNET, ConstraintType.SNLT,
        ConstraintType.FNET, ConstraintType.FNLT,
    }

    if not incomplete:
        return DcmaCheckResult(7, "Hard Constraints", "Incomplete tasks with hard constraints",
                               True, 0.0, 5.0, "max")

    flagged = [a for a in incomplete if a.constraint_type in hard_types]
    pct = (len(flagged) / len(incomplete)) * 100

    return DcmaCheckResult(
        check_number=7,
        name="Hard Constraints",
        description="Incomplete tasks with hard constraints",
        passed=pct <= 5.0,
        metric_value=round(pct, 1),
        threshold=5.0,
        threshold_direction="max",
        flagged_ids=[a.activity_id for a in flagged],
        detail=f"{len(flagged)} of {len(incomplete)} incomplete tasks have hard constraints",
    )


# ── Check 8: High Float ─────────────────────────────────────────────

def check_8_high_float(schedule: ScheduleData, incomplete: list[Activity]) -> DcmaCheckResult:
    """
    Activities with total float > 44 working days.
    DCMA threshold: <= 5% of incomplete tasks.
    """
    if not incomplete:
        return DcmaCheckResult(8, "High Float", "Incomplete tasks with total float > 44 days",
                               True, 0.0, 5.0, "max")

    flagged = [
        a for a in incomplete
        if a.total_float is not None and a.total_float > 44
    ]
    pct = (len(flagged) / len(incomplete)) * 100

    return DcmaCheckResult(
        check_number=8,
        name="High Float",
        description="Incomplete tasks with total float > 44 days",
        passed=pct <= 5.0,
        metric_value=round(pct, 1),
        threshold=5.0,
        threshold_direction="max",
        flagged_ids=[a.activity_id for a in flagged],
        detail=f"{len(flagged)} of {len(incomplete)} incomplete tasks have float > 44 days",
    )


# ── Check 9: Negative Float ─────────────────────────────────────────

def check_9_negative_float(schedule: ScheduleData, incomplete: list[Activity]) -> DcmaCheckResult:
    """
    Activities with negative total float.
    DCMA threshold: 0 — no negative float.
    """
    if not incomplete:
        return DcmaCheckResult(9, "Negative Float", "Incomplete tasks with negative total float",
                               True, 0.0, 0.0, "max")

    flagged = [
        a for a in incomplete
        if a.total_float is not None and a.total_float < 0
    ]
    pct = (len(flagged) / len(incomplete)) * 100

    return DcmaCheckResult(
        check_number=9,
        name="Negative Float",
        description="Incomplete tasks with negative total float",
        passed=len(flagged) == 0,
        metric_value=round(pct, 1),
        threshold=0.0,
        threshold_direction="max",
        flagged_ids=[f"{a.activity_id} (float: {a.total_float:.0f}d)" for a in flagged],
        detail=f"{len(flagged)} of {len(incomplete)} incomplete tasks have negative float",
    )


# ── Check 10: High Duration ─────────────────────────────────────────

def check_10_high_duration(schedule: ScheduleData, incomplete: list[Activity]) -> DcmaCheckResult:
    """
    Activities with duration > 44 working days (2 months).
    DCMA threshold: <= 5% of incomplete tasks.
    """
    if not incomplete:
        return DcmaCheckResult(10, "High Duration", "Incomplete tasks with duration > 44 days",
                               True, 0.0, 5.0, "max")

    flagged = [a for a in incomplete if a.duration > 44]
    pct = (len(flagged) / len(incomplete)) * 100

    return DcmaCheckResult(
        check_number=10,
        name="High Duration",
        description="Incomplete tasks with duration > 44 days",
        passed=pct <= 5.0,
        metric_value=round(pct, 1),
        threshold=5.0,
        threshold_direction="max",
        flagged_ids=[f"{a.activity_id} ({a.duration:.0f}d)" for a in flagged],
        detail=f"{len(flagged)} of {len(incomplete)} incomplete tasks exceed 44 days duration",
    )


# ── Check 11: Invalid Dates ─────────────────────────────────────────

def check_11_invalid_dates(schedule: ScheduleData) -> DcmaCheckResult:
    """
    Activities with invalid date logic:
    - Actual dates in the future (past data date)
    - Forecast dates in the past (before data date)
    DCMA threshold: 0 — no invalid dates.
    """
    data_date = schedule.project.data_date
    flagged = []

    if data_date:
        for a in schedule.activities:
            # Actual start in the future
            if a.actual_start and a.actual_start > data_date and a.status == ActivityStatus.NOT_STARTED:
                flagged.append(a)
            # Actual finish in the future
            elif a.actual_finish and a.actual_finish > data_date:
                flagged.append(a)
            # Forecast/planned dates in the past for not-started activities
            elif (a.status == ActivityStatus.NOT_STARTED
                  and a.finish_date and a.finish_date < data_date):
                flagged.append(a)

    total = len(schedule.activities)
    pct = (len(flagged) / total) * 100 if total else 0

    return DcmaCheckResult(
        check_number=11,
        name="Invalid Dates",
        description="Activities with date anomalies relative to data date",
        passed=len(flagged) == 0,
        metric_value=round(pct, 1),
        threshold=0.0,
        threshold_direction="max",
        flagged_ids=[a.activity_id for a in flagged],
        detail=f"{len(flagged)} activities have invalid dates relative to data date",
    )


# ── Check 12: Resources ─────────────────────────────────────────────

def check_12_resources(schedule: ScheduleData, incomplete: list[Activity]) -> DcmaCheckResult:
    """
    Activities without resource assignments (excluding milestones).
    DCMA threshold: all non-milestone activities should be resource-loaded.
    """
    if not incomplete:
        return DcmaCheckResult(12, "Resources", "Incomplete tasks without resource assignments",
                               True, 0.0, 5.0, "max")

    assigned_ids = {a.activity_id for a in schedule.resource_assignments}
    non_milestones = [a for a in incomplete if a.activity_type != ActivityType.MILESTONE]

    if not non_milestones:
        return DcmaCheckResult(12, "Resources", "Incomplete tasks without resource assignments",
                               True, 0.0, 5.0, "max")

    flagged = [a for a in non_milestones if a.activity_id not in assigned_ids]
    pct = (len(flagged) / len(non_milestones)) * 100

    return DcmaCheckResult(
        check_number=12,
        name="Resources",
        description="Incomplete tasks without resource assignments",
        passed=pct <= 5.0,
        metric_value=round(pct, 1),
        threshold=5.0,
        threshold_direction="max",
        flagged_ids=[a.activity_id for a in flagged[:100]],
        detail=f"{len(flagged)} of {len(non_milestones)} incomplete tasks have no resource assignment",
    )


# ── Check 13: Missed Tasks ──────────────────────────────────────────

def check_13_missed_tasks(schedule: ScheduleData, all_tasks: list[Activity]) -> DcmaCheckResult:
    """
    Tasks that should be complete by now (baseline finish <= data date)
    but are not. DCMA threshold: <= 5%.
    """
    data_date = schedule.project.data_date

    if not data_date or not all_tasks:
        return DcmaCheckResult(
            13, "Missed Tasks",
            "Tasks past baseline finish but not complete",
            True, 0.0, 5.0, "max",
            detail="No data date available — cannot evaluate missed tasks",
        )

    baselined = [a for a in all_tasks if a.baseline_finish is not None]
    if not baselined:
        return DcmaCheckResult(
            13, "Missed Tasks",
            "Tasks past baseline finish but not complete",
            True, 0.0, 5.0, "max",
            detail="No baseline dates found — cannot evaluate missed tasks",
        )

    should_be_done = [a for a in baselined if a.baseline_finish <= data_date]
    if not should_be_done:
        return DcmaCheckResult(13, "Missed Tasks", "Tasks past baseline finish but not complete",
                               True, 0.0, 5.0, "max", detail="No tasks due before data date")

    flagged = [a for a in should_be_done if a.status != ActivityStatus.COMPLETED]
    pct = (len(flagged) / len(should_be_done)) * 100

    return DcmaCheckResult(
        check_number=13,
        name="Missed Tasks",
        description="Tasks past baseline finish but not complete",
        passed=pct <= 5.0,
        metric_value=round(pct, 1),
        threshold=5.0,
        threshold_direction="max",
        flagged_ids=[a.activity_id for a in flagged[:100]],
        detail=f"{len(flagged)} of {len(should_be_done)} tasks due by data date are not complete",
    )


# ── Check 14: Critical Path Test ────────────────────────────────────

def check_14_critical_path_test(schedule: ScheduleData) -> DcmaCheckResult:
    """
    Verifies the schedule has a valid critical path (total float = 0).
    The critical path should be continuous from start to finish.
    DCMA threshold: critical path must exist and be continuous.
    """
    critical = [
        a for a in schedule.activities
        if a.total_float is not None and abs(a.total_float) < 0.01
        and a.activity_type in (ActivityType.TASK, ActivityType.MILESTONE)
        and a.status != ActivityStatus.COMPLETED
    ]

    total_tasks = len([
        a for a in schedule.activities
        if a.activity_type in (ActivityType.TASK, ActivityType.MILESTONE)
    ])

    if total_tasks == 0:
        return DcmaCheckResult(14, "Critical Path Test", "Valid critical path exists",
                               False, 0.0, 0.0, "min", detail="No tasks found")

    pct = (len(critical) / total_tasks) * 100

    # A healthy schedule typically has 10-20% critical activities
    # No critical path at all = FAIL
    # Too many critical activities (>50%) suggests broken logic
    has_critical = len(critical) > 0
    reasonable = pct <= 50

    return DcmaCheckResult(
        check_number=14,
        name="Critical Path Test",
        description="Valid critical path exists",
        passed=has_critical and reasonable,
        metric_value=round(pct, 1),
        threshold=0.0,
        threshold_direction="min",
        unit="% critical",
        flagged_ids=[a.activity_id for a in critical[:50]],
        detail=f"{len(critical)} of {total_tasks} tasks are critical ({pct:.1f}%)",
    )


# ── Report Printer ───────────────────────────────────────────────────

def print_dcma_report(report: DcmaReport):
    """Print a formatted DCMA 14-point assessment report."""

    print(f"\n{'=' * 70}")
    print(f"  DCMA 14-POINT SCHEDULE ASSESSMENT")
    print(f"{'=' * 70}")
    print(f"  Total Activities:      {report.total_activities}")
    print(f"  Incomplete Tasks:      {report.incomplete_activities}")
    print(f"  Overall Score:         {report.passed_count}/{len(report.checks)} checks passed ({report.score_pct:.0f}%)")
    print(f"  Grade:                 {report.grade}")
    print(f"{'=' * 70}\n")

    print(f"  {'#':<4} {'Check':<25} {'Result':<8} {'Value':>8} {'Thresh':>8} {'Status'}")
    print(f"  {'─' * 4} {'─' * 25} {'─' * 8} {'─' * 8} {'─' * 8} {'─' * 30}")

    for c in report.checks:
        icon = "PASS" if c.passed else "FAIL"
        marker = "  " if c.passed else "! "

        if c.threshold_direction == "min":
            thresh_str = f">={c.threshold:.0f}{c.unit}"
        else:
            thresh_str = f"<={c.threshold:.0f}{c.unit}"

        print(
            f"  {c.check_number:<4} {c.name:<25} {icon:<8} "
            f"{c.metric_value:>6.1f}{c.unit:<2} {thresh_str:>8} {marker}{c.detail}"
        )

    # Summary of failures
    failures = [c for c in report.checks if not c.passed]
    if failures:
        print(f"\n{'─' * 70}")
        print(f"  FAILED CHECKS ({len(failures)}):")
        print(f"{'─' * 70}")
        for c in failures:
            print(f"\n  #{c.check_number} {c.name}")
            print(f"     {c.detail}")
            if c.flagged_ids:
                shown = c.flagged_ids[:10]
                print(f"     Flagged: {', '.join(shown)}")
                if len(c.flagged_ids) > 10:
                    print(f"     ... and {len(c.flagged_ids) - 10} more")

    print(f"\n{'=' * 70}\n")
