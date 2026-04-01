import unittest
from models.schedule import (
    ScheduleData, ProjectInfo, Activity, Relationship, Resource,
    RelationshipType, ActivityType, ActivityStatus,
)


class TestScheduleData(unittest.TestCase):
    def _make_schedule(self):
        s = ScheduleData()
        s.project = ProjectInfo(name="Test Project", source_format="csv")
        s.activities = [
            Activity(activity_id="T1", name="Design", duration=5),
            Activity(activity_id="T2", name="Build", duration=10),
            Activity(activity_id="T3", name="Test", duration=3),
        ]
        s.relationships = [
            Relationship(predecessor_id="T1", successor_id="T2"),
            Relationship(predecessor_id="T2", successor_id="T3"),
        ]
        return s

    def test_activity_ids(self):
        s = self._make_schedule()
        self.assertEqual(s.activity_ids(), {"T1", "T2", "T3"})

    def test_get_activity(self):
        s = self._make_schedule()
        self.assertEqual(s.get_activity("T2").name, "Build")
        self.assertIsNone(s.get_activity("T99"))

    def test_get_predecessors(self):
        s = self._make_schedule()
        preds = s.get_predecessors("T2")
        self.assertEqual(len(preds), 1)
        self.assertEqual(preds[0].predecessor_id, "T1")

    def test_get_successors(self):
        s = self._make_schedule()
        succs = s.get_successors("T1")
        self.assertEqual(len(succs), 1)
        self.assertEqual(succs[0].successor_id, "T2")

    def test_summary(self):
        s = self._make_schedule()
        summary = s.summary()
        self.assertEqual(summary["total_activities"], 3)
        self.assertEqual(summary["total_relationships"], 2)
        self.assertEqual(summary["project_name"], "Test Project")

    def test_relationship_types(self):
        self.assertEqual(RelationshipType.FS.value, "Finish-to-Start")
        self.assertEqual(RelationshipType.SS.name, "SS")

    def test_activity_defaults(self):
        a = Activity(activity_id="X", name="Test", duration=5)
        self.assertEqual(a.activity_type, ActivityType.TASK)
        self.assertEqual(a.status, ActivityStatus.NOT_STARTED)
        self.assertEqual(a.percent_complete, 0.0)
        self.assertIsNone(a.total_float)


if __name__ == "__main__":
    unittest.main()
