import unittest
from pathlib import Path

from parsers.xml_parser import XMLParser
from parsers.base import ParseError
from models.schedule import RelationshipType, ActivityType, ActivityStatus

DATA_DIR = Path(__file__).parent.parent / "data"


class TestXMLParserDetection(unittest.TestCase):
    def setUp(self):
        self.parser = XMLParser()

    def test_can_parse_msp_xml(self):
        self.assertTrue(self.parser.can_parse(str(DATA_DIR / "sample_schedule.xml")))

    def test_cannot_parse_csv(self):
        self.assertFalse(self.parser.can_parse(str(DATA_DIR / "sample_schedule.csv")))


class TestMSPXMLParsing(unittest.TestCase):
    def setUp(self):
        self.parser = XMLParser()
        self.schedule = self.parser.parse(str(DATA_DIR / "sample_schedule.xml"))

    def test_source_format(self):
        self.assertEqual(self.schedule.project.source_format, "msp_xml")

    def test_project_dates(self):
        self.assertIsNotNone(self.schedule.project.start_date)
        self.assertIsNotNone(self.schedule.project.finish_date)

    def test_activity_count(self):
        # 5 tasks (UID 0 is project summary, skipped)
        self.assertEqual(len(self.schedule.activities), 5)

    def test_completed_activity(self):
        demo = self.schedule.get_activity("1")
        self.assertIsNotNone(demo)
        self.assertEqual(demo.status, ActivityStatus.COMPLETED)
        self.assertEqual(demo.percent_complete, 100)

    def test_in_progress_activity(self):
        elec = self.schedule.get_activity("2")
        self.assertIsNotNone(elec)
        self.assertEqual(elec.status, ActivityStatus.IN_PROGRESS)
        self.assertEqual(elec.percent_complete, 50)

    def test_duration_conversion(self):
        # PT40H0M0S = 40 hours = 5 days
        demo = self.schedule.get_activity("1")
        self.assertEqual(demo.duration, 5.0)

    def test_milestone(self):
        complete = self.schedule.get_activity("5")
        self.assertIsNotNone(complete)
        self.assertEqual(complete.activity_type, ActivityType.MILESTONE)
        self.assertEqual(complete.duration, 0.0)

    def test_relationships(self):
        # Task 2 ← Task 1, Task 3 ← Task 1, Task 4 ← Task 2+3, Task 5 ← Task 4
        self.assertEqual(len(self.schedule.relationships), 5)

    def test_relationship_types(self):
        for rel in self.schedule.relationships:
            self.assertEqual(rel.relationship_type, RelationshipType.FS)

    def test_multiple_predecessors(self):
        preds = self.schedule.get_predecessors("4")
        self.assertEqual(len(preds), 2)
        pred_ids = {p.predecessor_id for p in preds}
        self.assertEqual(pred_ids, {"2", "3"})

    def test_resources(self):
        self.assertEqual(len(self.schedule.resources), 2)
        names = {r.name for r in self.schedule.resources}
        self.assertIn("Electrician", names)

    def test_assignments(self):
        self.assertEqual(len(self.schedule.resource_assignments), 2)


class TestXMLEdgeCases(unittest.TestCase):
    def test_file_not_found(self):
        parser = XMLParser()
        with self.assertRaises(ParseError):
            parser.parse("/nonexistent.xml")

    def test_invalid_xml(self):
        import tempfile, os
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False)
        f.write("this is not xml at all")
        f.close()
        try:
            parser = XMLParser()
            with self.assertRaises(ParseError):
                parser.parse(f.name)
        finally:
            os.unlink(f.name)


if __name__ == "__main__":
    unittest.main()
