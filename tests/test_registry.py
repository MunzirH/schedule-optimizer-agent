import unittest
from pathlib import Path

from parsers.registry import ParserRegistry, create_default_registry
from parsers.base import ParseError

DATA_DIR = Path(__file__).parent.parent / "data"


class TestParserRegistry(unittest.TestCase):
    def setUp(self):
        self.registry = create_default_registry()

    def test_supported_formats(self):
        formats = self.registry.supported_formats
        self.assertIn("CSV/TSV Schedule", formats)
        self.assertIn("Primavera P6 XER", formats)
        self.assertIn("XML Schedule (P6 PMXML / MS Project)", formats)

    def test_routes_csv(self):
        parser = self.registry.get_parser("test.csv")
        self.assertEqual(parser.format_name, "CSV/TSV Schedule")

    def test_routes_xer(self):
        parser = self.registry.get_parser("project.xer")
        self.assertEqual(parser.format_name, "Primavera P6 XER")

    def test_routes_xml(self):
        parser = self.registry.get_parser("project.xml")
        self.assertEqual(parser.format_name, "XML Schedule (P6 PMXML / MS Project)")

    def test_unknown_format_raises(self):
        with self.assertRaises(ParseError) as ctx:
            self.registry.get_parser("file.docx")
        self.assertIn("No parser found", str(ctx.exception))

    def test_parse_csv_end_to_end(self):
        schedule = self.registry.parse(str(DATA_DIR / "sample_schedule.csv"))
        self.assertEqual(len(schedule.activities), 3)

    def test_parse_xer_end_to_end(self):
        schedule = self.registry.parse(str(DATA_DIR / "sample_schedule.xer"))
        self.assertEqual(len(schedule.activities), 9)

    def test_parse_xml_end_to_end(self):
        schedule = self.registry.parse(str(DATA_DIR / "sample_schedule.xml"))
        self.assertGreater(len(schedule.activities), 0)

    def test_all_parsers_produce_same_model(self):
        """Every parser produces a ScheduleData with activities and relationships."""
        for file_name in ["sample_schedule.csv", "sample_schedule.xer", "sample_schedule.xml"]:
            schedule = self.registry.parse(str(DATA_DIR / file_name))
            self.assertGreater(len(schedule.activities), 0, f"{file_name} produced no activities")
            self.assertGreater(len(schedule.relationships), 0, f"{file_name} produced no relationships")
            self.assertIsNotNone(schedule.project.source_format, f"{file_name} missing source_format")

            # Every activity has an ID and name
            for a in schedule.activities:
                self.assertTrue(a.activity_id, f"Activity missing ID in {file_name}")
                self.assertTrue(a.name, f"Activity missing name in {file_name}")
                self.assertGreaterEqual(a.duration, 0, f"Negative duration in {file_name}")


if __name__ == "__main__":
    unittest.main()
