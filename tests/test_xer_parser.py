import unittest
from pathlib import Path

from parsers.xer_parser import XERParser
from parsers.base import ParseError
from models.schedule import RelationshipType, ActivityType, ActivityStatus

DATA_DIR = Path(__file__).parent.parent / "data"


class TestXERParser(unittest.TestCase):
    def setUp(self):
        self.parser = XERParser()
        self.xer_path = str(DATA_DIR / "sample_schedule.xer")

    def test_can_parse_xer(self):
        self.assertTrue(self.parser.can_parse(self.xer_path))

    def test_cannot_parse_csv(self):
        self.assertFalse(self.parser.can_parse(str(DATA_DIR / "sample_schedule.csv")))

    def test_file_not_found(self):
        with self.assertRaises(ParseError):
            self.parser.parse("/nonexistent.xer")


class TestXERProjectInfo(unittest.TestCase):
    def setUp(self):
        self.parser = XERParser()
        self.schedule = self.parser.parse(str(DATA_DIR / "sample_schedule.xer"))

    def test_project_name(self):
        self.assertEqual(self.schedule.project.name, "Highway Bridge Rehab")

    def test_project_id(self):
        self.assertEqual(self.schedule.project.project_id, "1001")

    def test_source_format(self):
        self.assertEqual(self.schedule.project.source_format, "xer")

    def test_data_date(self):
        self.assertIsNotNone(self.schedule.project.data_date)

    def test_project_dates(self):
        self.assertIsNotNone(self.schedule.project.start_date)
        self.assertIsNotNone(self.schedule.project.finish_date)


class TestXERActivities(unittest.TestCase):
    def setUp(self):
        self.parser = XERParser()
        self.schedule = self.parser.parse(str(DATA_DIR / "sample_schedule.xer"))

    def test_activity_count(self):
        self.assertEqual(len(self.schedule.activities), 9)

    def test_completed_activity(self):
        mob = self.schedule.get_activity("1")
        self.assertIsNotNone(mob)
        self.assertEqual(mob.name, "Mobilization")
        self.assertEqual(mob.status, ActivityStatus.COMPLETED)
        self.assertEqual(mob.percent_complete, 100)
        self.assertIsNotNone(mob.actual_start)
        self.assertIsNotNone(mob.actual_finish)

    def test_active_activity(self):
        design = self.schedule.get_activity("3")
        self.assertIsNotNone(design)
        self.assertEqual(design.status, ActivityStatus.IN_PROGRESS)
        self.assertEqual(design.percent_complete, 60)

    def test_not_started_activity(self):
        review = self.schedule.get_activity("4")
        self.assertIsNotNone(review)
        self.assertEqual(review.status, ActivityStatus.NOT_STARTED)

    def test_milestone(self):
        closeout = self.schedule.get_activity("9")
        self.assertIsNotNone(closeout)
        self.assertEqual(closeout.activity_type, ActivityType.MILESTONE)
        self.assertEqual(closeout.duration, 0)

    def test_duration_conversion(self):
        # 40 hours / 8 hours per day = 5 days
        mob = self.schedule.get_activity("1")
        self.assertEqual(mob.original_duration, 5.0)

    def test_float_values(self):
        review = self.schedule.get_activity("4")
        self.assertEqual(review.total_float, 2.0)  # 16 hours / 8
        self.assertEqual(review.free_float, 1.0)   # 8 hours / 8

    def test_wbs_assigned(self):
        mob = self.schedule.get_activity("1")
        self.assertEqual(mob.wbs_id, "W2")


class TestXERRelationships(unittest.TestCase):
    def setUp(self):
        self.parser = XERParser()
        self.schedule = self.parser.parse(str(DATA_DIR / "sample_schedule.xer"))

    def test_relationship_count(self):
        self.assertEqual(len(self.schedule.relationships), 9)

    def test_relationship_type(self):
        # All relationships in our sample are FS
        for rel in self.schedule.relationships:
            self.assertEqual(rel.relationship_type, RelationshipType.FS)

    def test_relationship_structure(self):
        # Task 2 depends on Task 1
        preds = self.schedule.get_predecessors("2")
        self.assertEqual(len(preds), 1)
        self.assertEqual(preds[0].predecessor_id, "1")

    def test_multiple_predecessors(self):
        # Task 6 (Foundation) depends on Task 4 (Review) and Task 5 (Permits)
        preds = self.schedule.get_predecessors("6")
        self.assertEqual(len(preds), 2)
        pred_ids = {p.predecessor_id for p in preds}
        self.assertEqual(pred_ids, {"4", "5"})


class TestXERCalendars(unittest.TestCase):
    def setUp(self):
        self.parser = XERParser()
        self.schedule = self.parser.parse(str(DATA_DIR / "sample_schedule.xer"))

    def test_calendar_count(self):
        self.assertEqual(len(self.schedule.calendars), 1)

    def test_calendar_name(self):
        self.assertEqual(self.schedule.calendars[0].name, "Standard 5-Day")

    def test_calendar_default(self):
        self.assertTrue(self.schedule.calendars[0].is_default)


class TestXERResources(unittest.TestCase):
    def setUp(self):
        self.parser = XERParser()
        self.schedule = self.parser.parse(str(DATA_DIR / "sample_schedule.xer"))

    def test_resource_count(self):
        self.assertEqual(len(self.schedule.resources), 3)

    def test_resource_names(self):
        names = {r.name for r in self.schedule.resources}
        self.assertIn("Engineer Alpha", names)
        self.assertIn("Field Crew 1", names)

    def test_resource_assignments(self):
        self.assertEqual(len(self.schedule.resource_assignments), 7)


class TestXERWBS(unittest.TestCase):
    def setUp(self):
        self.parser = XERParser()
        self.schedule = self.parser.parse(str(DATA_DIR / "sample_schedule.xer"))

    def test_wbs_count(self):
        self.assertEqual(len(self.schedule.wbs), 3)

    def test_wbs_hierarchy(self):
        design = next(w for w in self.schedule.wbs if w.wbs_id == "W2")
        self.assertEqual(design.parent_id, "W1")


class TestXERSummary(unittest.TestCase):
    def test_summary_output(self):
        parser = XERParser()
        schedule = parser.parse(str(DATA_DIR / "sample_schedule.xer"))
        summary = schedule.summary()
        self.assertEqual(summary["total_activities"], 9)
        self.assertEqual(summary["total_relationships"], 9)
        self.assertEqual(summary["total_resources"], 3)
        self.assertIn("Finish-to-Start", summary["relationship_types"])


if __name__ == "__main__":
    unittest.main()
