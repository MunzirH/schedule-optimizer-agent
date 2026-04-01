import unittest
from datetime import datetime

from models.schedule import (
    ScheduleData, ProjectInfo, Activity, Relationship, Resource,
    ResourceAssignment, Calendar,
    ActivityType, ActivityStatus, RelationshipType, ConstraintType,
)
from agent.dcma_assessment import run_dcma_assessment


def _make_activity(aid, duration=5, status=ActivityStatus.NOT_STARTED,
                   atype=ActivityType.TASK, total_float=10,
                   constraint=ConstraintType.NONE,
                   baseline_finish=None, finish_date=None,
                   actual_start=None, actual_finish=None):
    return Activity(
        activity_id=aid, name=f"Task {aid}", duration=duration,
        status=status, activity_type=atype, total_float=total_float,
        constraint_type=constraint, baseline_finish=baseline_finish,
        finish_date=finish_date, actual_start=actual_start,
        actual_finish=actual_finish,
    )


def _make_relationship(pred, succ, rtype=RelationshipType.FS, lag=0.0):
    return Relationship(
        predecessor_id=pred, successor_id=succ,
        relationship_type=rtype, lag_days=lag,
    )


class TestDcmaCleanSchedule(unittest.TestCase):
    """A well-built schedule should pass all checks."""

    def setUp(self):
        s = ScheduleData()
        s.project = ProjectInfo(name="Clean", data_date=datetime(2026, 6, 1))

        s.activities = [
            _make_activity("1", total_float=0, baseline_finish=datetime(2026, 3, 1),
                           status=ActivityStatus.COMPLETED, actual_finish=datetime(2026, 3, 1)),
            _make_activity("2", total_float=0, baseline_finish=datetime(2026, 5, 1),
                           status=ActivityStatus.COMPLETED, actual_finish=datetime(2026, 5, 1)),
            _make_activity("3", total_float=0),
            _make_activity("4", total_float=5),
            _make_activity("5", total_float=0, atype=ActivityType.MILESTONE, duration=0),
        ]
        s.relationships = [
            _make_relationship("1", "2"),
            _make_relationship("2", "3"),
            _make_relationship("3", "4"),
            _make_relationship("4", "5"),
        ]
        s.resources = [Resource(resource_id="R1", name="Eng")]
        s.resource_assignments = [
            ResourceAssignment(activity_id="1", resource_id="R1"),
            ResourceAssignment(activity_id="2", resource_id="R1"),
            ResourceAssignment(activity_id="3", resource_id="R1"),
            ResourceAssignment(activity_id="4", resource_id="R1"),
        ]

        self.report = run_dcma_assessment(s)

    def test_all_checks_run(self):
        self.assertEqual(len(self.report.checks), 14)

    def test_high_score(self):
        # A clean schedule should pass most checks
        self.assertGreaterEqual(self.report.score_pct, 70)

    def test_no_leads(self):
        check = self.report.checks[3]  # Check 4: Leads
        self.assertTrue(check.passed)

    def test_no_lags(self):
        check = self.report.checks[4]  # Check 5: Lags
        self.assertTrue(check.passed)

    def test_relationship_types(self):
        check = self.report.checks[5]  # Check 6: FS%
        self.assertTrue(check.passed)
        self.assertEqual(check.metric_value, 100.0)

    def test_no_negative_float(self):
        check = self.report.checks[8]  # Check 9: Negative float
        self.assertTrue(check.passed)


class TestDcmaMissingLogic(unittest.TestCase):
    def test_missing_predecessors_fails(self):
        s = ScheduleData()
        s.project = ProjectInfo(name="Bad")
        # 10 tasks, none have predecessors
        s.activities = [_make_activity(str(i)) for i in range(10)]
        s.relationships = []

        report = run_dcma_assessment(s)
        check = report.checks[0]  # Check 1
        self.assertFalse(check.passed)
        self.assertEqual(check.metric_value, 100.0)

    def test_missing_successors_fails(self):
        s = ScheduleData()
        s.project = ProjectInfo(name="Bad")
        s.activities = [_make_activity(str(i)) for i in range(10)]
        s.relationships = []

        report = run_dcma_assessment(s)
        check = report.checks[1]  # Check 2
        self.assertFalse(check.passed)


class TestDcmaLeadsAndLags(unittest.TestCase):
    def test_leads_fail(self):
        s = ScheduleData()
        s.project = ProjectInfo(name="Leads")
        s.activities = [_make_activity("1"), _make_activity("2")]
        s.relationships = [_make_relationship("1", "2", lag=-3)]

        report = run_dcma_assessment(s)
        check = report.checks[3]  # Check 4: Leads
        self.assertFalse(check.passed)

    def test_excessive_lags_fail(self):
        s = ScheduleData()
        s.project = ProjectInfo(name="Lags")
        s.activities = [_make_activity(str(i)) for i in range(10)]
        # All relationships have lag
        s.relationships = [_make_relationship(str(i), str(i + 1), lag=5) for i in range(9)]

        report = run_dcma_assessment(s)
        check = report.checks[4]  # Check 5: Lags
        self.assertFalse(check.passed)


class TestDcmaRelationshipTypes(unittest.TestCase):
    def test_too_many_non_fs_fails(self):
        s = ScheduleData()
        s.project = ProjectInfo(name="SS Heavy")
        s.activities = [_make_activity(str(i)) for i in range(10)]
        # 50% FS, 50% SS — should fail (threshold is 90%)
        s.relationships = (
            [_make_relationship(str(i), str(i + 1), rtype=RelationshipType.FS) for i in range(0, 5)] +
            [_make_relationship(str(i), str(i + 1), rtype=RelationshipType.SS) for i in range(5, 9)]
        )

        report = run_dcma_assessment(s)
        check = report.checks[5]  # Check 6
        self.assertFalse(check.passed)


class TestDcmaConstraints(unittest.TestCase):
    def test_hard_constraints_fail(self):
        s = ScheduleData()
        s.project = ProjectInfo(name="Constrained")
        # All 10 tasks have MSO constraints — should fail
        s.activities = [_make_activity(str(i), constraint=ConstraintType.MSO) for i in range(10)]
        s.relationships = [_make_relationship(str(i), str(i + 1)) for i in range(9)]

        report = run_dcma_assessment(s)
        check = report.checks[6]  # Check 7
        self.assertFalse(check.passed)


class TestDcmaFloat(unittest.TestCase):
    def test_high_float_fails(self):
        s = ScheduleData()
        s.project = ProjectInfo(name="Floaty")
        # All tasks have float > 44
        s.activities = [_make_activity(str(i), total_float=100) for i in range(10)]
        s.relationships = [_make_relationship(str(i), str(i + 1)) for i in range(9)]

        report = run_dcma_assessment(s)
        check = report.checks[7]  # Check 8
        self.assertFalse(check.passed)

    def test_negative_float_fails(self):
        s = ScheduleData()
        s.project = ProjectInfo(name="Negative")
        s.activities = [_make_activity(str(i), total_float=-5) for i in range(5)]
        s.relationships = [_make_relationship(str(i), str(i + 1)) for i in range(4)]

        report = run_dcma_assessment(s)
        check = report.checks[8]  # Check 9
        self.assertFalse(check.passed)


class TestDcmaHighDuration(unittest.TestCase):
    def test_long_activities_fail(self):
        s = ScheduleData()
        s.project = ProjectInfo(name="Long")
        s.activities = [_make_activity(str(i), duration=90) for i in range(10)]
        s.relationships = [_make_relationship(str(i), str(i + 1)) for i in range(9)]

        report = run_dcma_assessment(s)
        check = report.checks[9]  # Check 10
        self.assertFalse(check.passed)


class TestDcmaResources(unittest.TestCase):
    def test_no_resources_fails(self):
        s = ScheduleData()
        s.project = ProjectInfo(name="No Resources")
        s.activities = [_make_activity(str(i)) for i in range(10)]
        s.relationships = [_make_relationship(str(i), str(i + 1)) for i in range(9)]
        s.resource_assignments = []

        report = run_dcma_assessment(s)
        check = report.checks[11]  # Check 12
        self.assertFalse(check.passed)


class TestDcmaMissedTasks(unittest.TestCase):
    def test_missed_tasks_fail(self):
        s = ScheduleData()
        s.project = ProjectInfo(name="Behind", data_date=datetime(2026, 6, 1))
        s.activities = [
            # Should be done (baseline finish before data date) but isn't
            _make_activity("1", baseline_finish=datetime(2026, 3, 1), status=ActivityStatus.NOT_STARTED),
            _make_activity("2", baseline_finish=datetime(2026, 4, 1), status=ActivityStatus.NOT_STARTED),
            _make_activity("3", baseline_finish=datetime(2026, 5, 1), status=ActivityStatus.NOT_STARTED),
        ]
        s.relationships = [_make_relationship("1", "2"), _make_relationship("2", "3")]

        report = run_dcma_assessment(s)
        check = report.checks[12]  # Check 13
        self.assertFalse(check.passed)
        self.assertEqual(check.metric_value, 100.0)


class TestDcmaCriticalPath(unittest.TestCase):
    def test_no_critical_path_fails(self):
        s = ScheduleData()
        s.project = ProjectInfo(name="No CP")
        # All activities have high float — no critical path
        s.activities = [_make_activity(str(i), total_float=100) for i in range(10)]
        s.relationships = [_make_relationship(str(i), str(i + 1)) for i in range(9)]

        report = run_dcma_assessment(s)
        check = report.checks[13]  # Check 14
        self.assertFalse(check.passed)


class TestDcmaReportSummary(unittest.TestCase):
    def test_grade_calculation(self):
        s = ScheduleData()
        s.project = ProjectInfo(name="Test")
        s.activities = [_make_activity("1", total_float=0)]
        s.relationships = []

        report = run_dcma_assessment(s)
        self.assertIn(report.grade, ("A", "B", "C", "F"))
        self.assertGreater(report.score_pct, 0)


class TestDcmaWithRealXER(unittest.TestCase):
    """Test against the sample XER file to ensure integration works."""

    def test_xer_assessment(self):
        from pathlib import Path
        from parsers.registry import create_default_registry

        xer_path = Path(__file__).parent.parent / "data" / "sample_schedule.xer"
        if not xer_path.exists():
            self.skipTest("sample_schedule.xer not found")

        registry = create_default_registry()
        schedule = registry.parse(str(xer_path))
        report = run_dcma_assessment(schedule)

        self.assertEqual(len(report.checks), 14)
        self.assertGreater(report.total_activities, 0)
        # The sample XER is well-built, should score reasonably
        self.assertGreaterEqual(report.passed_count, 5)


if __name__ == "__main__":
    unittest.main()
