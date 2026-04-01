import unittest
import tempfile
import os

from parsers.csv_parser import CSVScheduleParser
from parsers.base import ParseError
from models.schedule import RelationshipType, ActivityType, ActivityStatus


class CSVParserTestBase(unittest.TestCase):
    def setUp(self):
        self.parser = CSVScheduleParser()
        self.files = []

    def tearDown(self):
        for f in self.files:
            os.unlink(f)

    def _make(self, content):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
        f.write(content)
        f.close()
        self.files.append(f.name)
        return f.name


class TestCSVBasicParsing(CSVParserTestBase):
    def test_standard_columns(self):
        path = self._make(
            "task_id,task_name,start_date,end_date,duration,predecessors,resource\n"
            "T1,Design,1/1/2026,1/5/2026,5,,Engineer A\n"
            "T2,Review,1/6/2026,1/8/2026,3,T1,Engineer B\n"
            "T3,Build,1/6/2026,1/12/2026,7,T1,Engineer C\n"
        )
        schedule = self.parser.parse(path)
        self.assertEqual(len(schedule.activities), 3)
        self.assertEqual(len(schedule.relationships), 2)
        self.assertEqual(len(schedule.resources), 3)
        self.assertEqual(schedule.project.source_format, "csv")

    def test_activity_fields(self):
        path = self._make(
            "task_id,task_name,start_date,end_date,duration,predecessors,resource\n"
            "T1,Design,1/1/2026,1/5/2026,5,,Eng\n"
        )
        schedule = self.parser.parse(path)
        a = schedule.activities[0]
        self.assertEqual(a.activity_id, "T1")
        self.assertEqual(a.name, "Design")
        self.assertEqual(a.duration, 5.0)
        self.assertIsNotNone(a.start_date)
        self.assertIsNotNone(a.finish_date)


class TestCSVFlexibleColumns(CSVParserTestBase):
    def test_alternate_column_names(self):
        path = self._make(
            "Activity ID,Activity Name,Start,Finish,Original Duration,Predecessor,Assigned To\n"
            "A100,Excavation,2026-03-01,2026-03-10,10,,Crew 1\n"
            "A110,Foundation,2026-03-11,2026-03-20,10,A100,Crew 2\n"
        )
        schedule = self.parser.parse(path)
        self.assertEqual(len(schedule.activities), 2)
        self.assertEqual(schedule.activities[0].name, "Excavation")
        self.assertEqual(schedule.activities[1].name, "Foundation")

    def test_extra_columns_ignored(self):
        path = self._make(
            "task_id,task_name,duration,predecessors,resource,cost,notes\n"
            "T1,Design,5,,Eng,50000,Important task\n"
        )
        schedule = self.parser.parse(path)
        self.assertEqual(len(schedule.activities), 1)

    def test_missing_required_columns_raises(self):
        path = self._make(
            "name,cost\n"
            "Design,50000\n"
        )
        with self.assertRaises(ParseError) as ctx:
            self.parser.parse(path)
        self.assertIn("Cannot find required columns", str(ctx.exception))

    def test_tab_delimited(self):
        path = self._make(
            "task_id\ttask_name\tduration\tpredecessors\tresource\n"
            "T1\tDesign\t5\t\tEng\n"
        )
        schedule = self.parser.parse(path)
        self.assertEqual(len(schedule.activities), 1)


class TestCSVPredecessorParsing(CSVParserTestBase):
    def test_simple_predecessors(self):
        path = self._make(
            "task_id,task_name,duration,predecessors,resource\n"
            "T1,A,5,,Eng\n"
            "T2,B,3,T1,Eng\n"
        )
        schedule = self.parser.parse(path)
        self.assertEqual(len(schedule.relationships), 1)
        rel = schedule.relationships[0]
        self.assertEqual(rel.predecessor_id, "T1")
        self.assertEqual(rel.successor_id, "T2")
        self.assertEqual(rel.relationship_type, RelationshipType.FS)
        self.assertEqual(rel.lag_days, 0.0)

    def test_multiple_predecessors(self):
        path = self._make(
            "task_id,task_name,duration,predecessors,resource\n"
            "T1,A,5,,Eng\n"
            "T2,B,3,,Eng\n"
            "T3,C,4,\"T1,T2\",Eng\n"
        )
        schedule = self.parser.parse(path)
        self.assertEqual(len(schedule.relationships), 2)

    def test_typed_predecessors(self):
        path = self._make(
            "task_id,task_name,duration,predecessors,resource\n"
            "T1,A,5,,Eng\n"
            "T2,B,3,T1SS,Eng\n"
        )
        schedule = self.parser.parse(path)
        rel = schedule.relationships[0]
        self.assertEqual(rel.relationship_type, RelationshipType.SS)

    def test_predecessors_with_lag(self):
        path = self._make(
            "task_id,task_name,duration,predecessors,resource\n"
            "T1,A,5,,Eng\n"
            "T2,B,3,T1FS+3,Eng\n"
        )
        schedule = self.parser.parse(path)
        rel = schedule.relationships[0]
        self.assertEqual(rel.lag_days, 3.0)

    def test_predecessors_with_lead(self):
        path = self._make(
            "task_id,task_name,duration,predecessors,resource\n"
            "T1,A,5,,Eng\n"
            "T2,B,3,T1FS-2,Eng\n"
        )
        schedule = self.parser.parse(path)
        rel = schedule.relationships[0]
        self.assertEqual(rel.lag_days, -2.0)


class TestCSVStatusInference(CSVParserTestBase):
    def test_completed_by_percent(self):
        path = self._make(
            "task_id,task_name,duration,predecessors,percent_complete\n"
            "T1,A,5,,100\n"
        )
        schedule = self.parser.parse(path)
        self.assertEqual(schedule.activities[0].status, ActivityStatus.COMPLETED)

    def test_in_progress_by_percent(self):
        path = self._make(
            "task_id,task_name,duration,predecessors,percent_complete\n"
            "T1,A,5,,50\n"
        )
        schedule = self.parser.parse(path)
        self.assertEqual(schedule.activities[0].status, ActivityStatus.IN_PROGRESS)

    def test_not_started_default(self):
        path = self._make(
            "task_id,task_name,duration,predecessors,resource\n"
            "T1,A,5,,Eng\n"
        )
        schedule = self.parser.parse(path)
        self.assertEqual(schedule.activities[0].status, ActivityStatus.NOT_STARTED)

    def test_milestone_detection(self):
        path = self._make(
            "task_id,task_name,duration,predecessors,resource\n"
            "T1,Project Complete,0,,\n"
        )
        schedule = self.parser.parse(path)
        self.assertEqual(schedule.activities[0].activity_type, ActivityType.MILESTONE)


class TestCSVEdgeCases(CSVParserTestBase):
    def test_empty_file_raises(self):
        path = self._make("")
        with self.assertRaises(ParseError):
            self.parser.parse(path)

    def test_file_not_found_raises(self):
        with self.assertRaises(ParseError):
            self.parser.parse("/nonexistent/file.csv")

    def test_invalid_duration_raises(self):
        path = self._make(
            "task_id,task_name,duration,predecessors\n"
            "T1,A,not_a_number,\n"
        )
        with self.assertRaises(ParseError):
            self.parser.parse(path)

    def test_project_dates_inferred(self):
        path = self._make(
            "task_id,task_name,start_date,end_date,duration,predecessors,resource\n"
            "T1,A,2026-01-01,2026-01-05,5,,Eng\n"
            "T2,B,2026-01-10,2026-01-20,10,T1,Eng\n"
        )
        schedule = self.parser.parse(path)
        self.assertIsNotNone(schedule.project.start_date)
        self.assertIsNotNone(schedule.project.finish_date)
        self.assertLess(schedule.project.start_date, schedule.project.finish_date)


if __name__ == "__main__":
    unittest.main()
