import unittest
from datetime import datetime

from models.schedule import (
    ScheduleData, ProjectInfo, Activity, Relationship, Resource,
    ResourceAssignment,
    ActivityType, ActivityStatus, RelationshipType,
)
from agent.risk_analysis import (
    analyze_risks, compare_schedules, RiskReport,
)


def _act(aid, duration=5, total_float=10, status=ActivityStatus.NOT_STARTED,
         atype=ActivityType.TASK, wbs_id="W1",
         start_date=None, finish_date=None,
         baseline_finish=None):
    return Activity(
        activity_id=aid, name=f"Task {aid}", duration=duration,
        total_float=total_float, status=status, activity_type=atype,
        wbs_id=wbs_id, start_date=start_date, finish_date=finish_date,
        baseline_finish=baseline_finish,
    )


def _rel(pred, succ):
    return Relationship(predecessor_id=pred, successor_id=succ)


class TestRiskAnalysisBasic(unittest.TestCase):
    def test_empty_schedule(self):
        s = ScheduleData()
        report = analyze_risks(s)
        self.assertEqual(report.total_activities, 0)
        self.assertEqual(report.risk_level, "LOW")

    def test_all_complete(self):
        s = ScheduleData()
        s.activities = [_act("1", status=ActivityStatus.COMPLETED)]
        report = analyze_risks(s)
        self.assertEqual(report.incomplete_activities, 0)

    def test_report_fields(self):
        s = ScheduleData()
        s.project = ProjectInfo(name="Test")
        s.activities = [_act("1", total_float=0), _act("2", total_float=5)]
        s.relationships = [_rel("1", "2")]
        report = analyze_risks(s)
        self.assertEqual(report.total_activities, 2)
        self.assertEqual(report.incomplete_activities, 2)
        self.assertGreater(len(report.float_distribution), 0)


class TestCriticalAndNearCritical(unittest.TestCase):
    def test_critical_count(self):
        s = ScheduleData()
        s.activities = [
            _act("1", total_float=0),
            _act("2", total_float=0),
            _act("3", total_float=20),
        ]
        report = analyze_risks(s)
        self.assertEqual(report.critical_count, 2)

    def test_near_critical_count(self):
        s = ScheduleData()
        s.activities = [
            _act("1", total_float=0),
            _act("2", total_float=5),
            _act("3", total_float=8),
            _act("4", total_float=15),
        ]
        report = analyze_risks(s)
        self.assertEqual(report.near_critical_count, 2)  # 5 and 8

    def test_custom_threshold(self):
        s = ScheduleData()
        s.activities = [
            _act("1", total_float=5),
            _act("2", total_float=15),
            _act("3", total_float=25),
        ]
        report = analyze_risks(s, near_critical_threshold=20)
        self.assertEqual(report.near_critical_count, 2)  # 5 and 15


class TestNegativeFloat(unittest.TestCase):
    def test_negative_float_count(self):
        s = ScheduleData()
        s.activities = [
            _act("1", total_float=-10),
            _act("2", total_float=-5),
            _act("3", total_float=0),
            _act("4", total_float=20),
        ]
        report = analyze_risks(s)
        self.assertEqual(report.negative_float_count, 2)

    def test_negative_float_is_high_risk(self):
        s = ScheduleData()
        s.activities = [_act("1", total_float=-50, duration=20)]
        report = analyze_risks(s)
        self.assertEqual(report.risk_level, "HIGH")

    def test_negative_float_in_top_risks(self):
        s = ScheduleData()
        s.activities = [
            _act("1", total_float=-30, duration=10),
            _act("2", total_float=0, duration=5),
            _act("3", total_float=20, duration=5),
        ]
        report = analyze_risks(s)
        top = report.top_risks[0]
        self.assertEqual(top.activity_id, "1")
        self.assertEqual(top.risk_category, "negative_float")


class TestFloatDistribution(unittest.TestCase):
    def test_buckets_created(self):
        s = ScheduleData()
        s.activities = [
            _act("1", total_float=-5),
            _act("2", total_float=0),
            _act("3", total_float=5),
            _act("4", total_float=30),
            _act("5", total_float=60),
            _act("6", total_float=200),
        ]
        report = analyze_risks(s)
        self.assertEqual(len(report.float_distribution), 7)

        # Check that all activities are accounted for
        total_in_buckets = sum(b.count for b in report.float_distribution)
        self.assertEqual(total_in_buckets, 6)

    def test_bucket_percentages_sum(self):
        s = ScheduleData()
        s.activities = [_act(str(i), total_float=i * 10 - 20) for i in range(10)]
        report = analyze_risks(s)
        total_pct = sum(b.percentage for b in report.float_distribution)
        self.assertAlmostEqual(total_pct, 100.0, places=0)


class TestWBSRisks(unittest.TestCase):
    def test_wbs_grouping(self):
        s = ScheduleData()
        s.activities = [
            _act("1", wbs_id="W1", total_float=-10),
            _act("2", wbs_id="W1", total_float=0),
            _act("3", wbs_id="W2", total_float=50),
        ]
        report = analyze_risks(s)
        self.assertGreater(len(report.wbs_risks), 0)

        # W1 should have higher risk than W2
        w1 = next(w for w in report.wbs_risks if w.wbs_id == "W1")
        w2 = next(w for w in report.wbs_risks if w.wbs_id == "W2")
        self.assertGreater(w1.risk_score, w2.risk_score)


class TestPerformanceIndices(unittest.TestCase):
    def test_bei_all_on_time(self):
        s = ScheduleData()
        s.project = ProjectInfo(data_date=datetime(2026, 6, 1))
        s.activities = [
            _act("1", status=ActivityStatus.COMPLETED,
                 baseline_finish=datetime(2026, 3, 1)),
            _act("2", status=ActivityStatus.COMPLETED,
                 baseline_finish=datetime(2026, 5, 1)),
        ]
        report = analyze_risks(s)
        self.assertEqual(report.bei, 1.0)

    def test_bei_all_late(self):
        s = ScheduleData()
        s.project = ProjectInfo(data_date=datetime(2026, 6, 1))
        s.activities = [
            _act("1", status=ActivityStatus.NOT_STARTED,
                 baseline_finish=datetime(2026, 3, 1)),
            _act("2", status=ActivityStatus.NOT_STARTED,
                 baseline_finish=datetime(2026, 5, 1)),
        ]
        report = analyze_risks(s)
        self.assertEqual(report.bei, 0.0)

    def test_bei_partial(self):
        s = ScheduleData()
        s.project = ProjectInfo(data_date=datetime(2026, 6, 1))
        s.activities = [
            _act("1", status=ActivityStatus.COMPLETED,
                 baseline_finish=datetime(2026, 3, 1)),
            _act("2", status=ActivityStatus.NOT_STARTED,
                 baseline_finish=datetime(2026, 5, 1)),
        ]
        report = analyze_risks(s)
        self.assertEqual(report.bei, 0.5)

    def test_cpli_healthy(self):
        s = ScheduleData()
        s.project = ProjectInfo(
            data_date=datetime(2026, 1, 1),
            start_date=datetime(2026, 1, 1),
            finish_date=datetime(2026, 12, 31),
        )
        s.activities = [_act("1", total_float=0)]
        report = analyze_risks(s)
        self.assertGreaterEqual(report.cpli, 0.95)

    def test_cpli_with_negative_float(self):
        s = ScheduleData()
        s.project = ProjectInfo(
            data_date=datetime(2026, 1, 1),
            start_date=datetime(2026, 1, 1),
            finish_date=datetime(2026, 12, 31),
        )
        s.activities = [_act("1", total_float=-50)]
        report = analyze_risks(s)
        self.assertLess(report.cpli, 1.0)


class TestResourceConflicts(unittest.TestCase):
    def test_overlapping_assignments(self):
        s = ScheduleData()
        s.activities = [
            _act("1", start_date=datetime(2026, 1, 1), finish_date=datetime(2026, 1, 15)),
            _act("2", start_date=datetime(2026, 1, 10), finish_date=datetime(2026, 1, 25)),
        ]
        s.resources = [Resource(resource_id="R1", name="Crew A")]
        s.resource_assignments = [
            ResourceAssignment(activity_id="1", resource_id="R1"),
            ResourceAssignment(activity_id="2", resource_id="R1"),
        ]
        report = analyze_risks(s)
        self.assertGreater(len(report.resource_conflicts), 0)
        self.assertEqual(report.resource_conflicts[0]["resource"], "Crew A")

    def test_no_overlap_no_conflict(self):
        s = ScheduleData()
        s.activities = [
            _act("1", start_date=datetime(2026, 1, 1), finish_date=datetime(2026, 1, 10)),
            _act("2", start_date=datetime(2026, 1, 15), finish_date=datetime(2026, 1, 25)),
        ]
        s.resources = [Resource(resource_id="R1", name="Crew A")]
        s.resource_assignments = [
            ResourceAssignment(activity_id="1", resource_id="R1"),
            ResourceAssignment(activity_id="2", resource_id="R1"),
        ]
        report = analyze_risks(s)
        self.assertEqual(len(report.resource_conflicts), 0)


class TestScheduleComparison(unittest.TestCase):
    def setUp(self):
        self.prev = ScheduleData()
        self.prev.activities = [
            _act("1", duration=5, total_float=10),
            _act("2", duration=10, total_float=0),
            _act("3", duration=3, total_float=20, status=ActivityStatus.NOT_STARTED),
        ]
        self.prev.relationships = [_rel("1", "2"), _rel("2", "3")]

    def test_added_activities(self):
        curr = ScheduleData()
        curr.activities = self.prev.activities + [_act("4")]
        curr.relationships = self.prev.relationships
        comp = compare_schedules(curr, self.prev)
        self.assertIn("4", comp.added_activities)

    def test_removed_activities(self):
        curr = ScheduleData()
        curr.activities = self.prev.activities[:2]  # remove "3"
        curr.relationships = self.prev.relationships
        comp = compare_schedules(curr, self.prev)
        self.assertIn("3", comp.removed_activities)

    def test_duration_change(self):
        curr = ScheduleData()
        curr.activities = [
            _act("1", duration=8, total_float=10),  # changed from 5 to 8
            _act("2", duration=10, total_float=0),
            _act("3", duration=3, total_float=20),
        ]
        curr.relationships = self.prev.relationships
        comp = compare_schedules(curr, self.prev)
        self.assertGreater(len(comp.duration_changes), 0)
        change = comp.duration_changes[0]
        self.assertEqual(change["activity_id"], "1")
        self.assertEqual(change["delta"], 3.0)

    def test_float_change(self):
        curr = ScheduleData()
        curr.activities = [
            _act("1", duration=5, total_float=3),  # float dropped from 10 to 3
            _act("2", duration=10, total_float=0),
            _act("3", duration=3, total_float=20),
        ]
        curr.relationships = self.prev.relationships
        comp = compare_schedules(curr, self.prev)
        self.assertGreater(len(comp.float_changes), 0)

    def test_status_change(self):
        curr = ScheduleData()
        curr.activities = [
            _act("1", duration=5, total_float=10),
            _act("2", duration=10, total_float=0),
            _act("3", duration=3, total_float=20, status=ActivityStatus.COMPLETED),
        ]
        curr.relationships = self.prev.relationships
        comp = compare_schedules(curr, self.prev)
        self.assertGreater(len(comp.status_changes), 0)
        self.assertEqual(comp.status_changes[0]["current"], "Completed")

    def test_critical_path_change(self):
        curr = ScheduleData()
        curr.activities = [
            _act("1", duration=5, total_float=0),  # became critical (was 10)
            _act("2", duration=10, total_float=0),
            _act("3", duration=3, total_float=20),
        ]
        curr.relationships = self.prev.relationships
        comp = compare_schedules(curr, self.prev)
        self.assertGreater(len(comp.critical_path_changes), 0)

    def test_summary(self):
        curr = ScheduleData()
        curr.activities = self.prev.activities + [_act("4")]
        curr.relationships = self.prev.relationships
        comp = compare_schedules(curr, self.prev)
        self.assertIn("added", comp.summary)
        self.assertEqual(comp.summary["added"], 1)


class TestRiskLevel(unittest.TestCase):
    def test_high_risk(self):
        s = ScheduleData()
        s.activities = [_act("1", total_float=-10)]
        report = analyze_risks(s)
        self.assertEqual(report.risk_level, "HIGH")

    def test_medium_risk(self):
        s = ScheduleData()
        s.project = ProjectInfo(data_date=datetime(2026, 6, 1))
        # Many near-critical, no negative float
        s.activities = [_act(str(i), total_float=5) for i in range(10)]
        report = analyze_risks(s)
        self.assertEqual(report.risk_level, "MEDIUM")

    def test_low_risk(self):
        s = ScheduleData()
        s.project = ProjectInfo(data_date=datetime(2026, 6, 1))
        s.activities = [
            _act("1", total_float=30, status=ActivityStatus.COMPLETED,
                 baseline_finish=datetime(2026, 3, 1)),
            _act("2", total_float=30, status=ActivityStatus.COMPLETED,
                 baseline_finish=datetime(2026, 4, 1)),
        ]
        report = analyze_risks(s)
        self.assertEqual(report.risk_level, "LOW")


class TestWithRealXER(unittest.TestCase):
    def test_xer_risk_analysis(self):
        from pathlib import Path
        from parsers.registry import create_default_registry

        xer_path = Path(__file__).parent.parent / "data" / "sample_schedule.xer"
        if not xer_path.exists():
            self.skipTest("sample_schedule.xer not found")

        registry = create_default_registry()
        schedule = registry.parse(str(xer_path))
        report = analyze_risks(schedule)

        self.assertGreater(report.total_activities, 0)
        self.assertGreater(len(report.float_distribution), 0)
        self.assertIn(report.risk_level, ("LOW", "MEDIUM", "HIGH"))


if __name__ == "__main__":
    unittest.main()
