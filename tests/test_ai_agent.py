import unittest
from datetime import datetime

from models.schedule import (
    ScheduleData, ProjectInfo, Activity, Relationship, Resource,
    ResourceAssignment, ActivityType, ActivityStatus, RelationshipType,
)
from agent.dcma_assessment import run_dcma_assessment
from agent.risk_analysis import analyze_risks
from agent.ai_agent import ScheduleAgent, AgentConfig, _build_summary
from agent.tools import ScheduleTools, dispatch_tool
from optimization.critical_path import compute_cpm, find_driving_path, what_if_delay, find_missing_logic


def _act(aid, dur=5, fl=10, status=ActivityStatus.NOT_STARTED,
         atype=ActivityType.TASK, wbs="W1",
         start=None, finish=None, bl_finish=None):
    return Activity(
        activity_id=aid, name="Task " + aid, duration=dur,
        total_float=fl, status=status, activity_type=atype,
        wbs_id=wbs, start_date=start, finish_date=finish,
        baseline_finish=bl_finish)

def _rel(p, s, rtype=RelationshipType.FS, lag=0):
    return Relationship(predecessor_id=p, successor_id=s,
                        relationship_type=rtype, lag_days=lag)

def _make_schedule():
    s = ScheduleData()
    s.project = ProjectInfo(name="Test Bridge", source_format="xer",
                            source_file="test.xer",
                            data_date=datetime(2026, 6, 1),
                            start_date=datetime(2026, 1, 1),
                            finish_date=datetime(2026, 12, 31))
    s.activities = [
        _act("1", dur=5, fl=0, status=ActivityStatus.COMPLETED,
             start=datetime(2026, 1, 1), finish=datetime(2026, 1, 5)),
        _act("2", dur=20, fl=0, status=ActivityStatus.IN_PROGRESS,
             start=datetime(2026, 1, 6), finish=datetime(2026, 2, 1)),
        _act("3", dur=30, fl=-5,
             start=datetime(2026, 2, 2), finish=datetime(2026, 3, 15)),
        _act("4", dur=10, fl=15,
             start=datetime(2026, 3, 16), finish=datetime(2026, 3, 30)),
        _act("5", dur=0, fl=0, atype=ActivityType.MILESTONE),
    ]
    s.relationships = [_rel("1", "2"), _rel("2", "3"), _rel("3", "4"), _rel("4", "5")]
    s.resources = [Resource(resource_id="R1", name="Crew A")]
    s.resource_assignments = [
        ResourceAssignment(activity_id="1", resource_id="R1"),
        ResourceAssignment(activity_id="2", resource_id="R1"),
    ]
    return s


# ── CPM Engine Tests ─────────────────────────────────────────────────

class TestCPMEngine(unittest.TestCase):
    def test_basic_cpm(self):
        s = _make_schedule()
        result = compute_cpm(s)
        self.assertFalse(result.has_cycles)
        self.assertGreater(result.total_duration, 0)
        self.assertGreater(len(result.critical_path), 0)

    def test_critical_path_identified(self):
        s = ScheduleData()
        s.activities = [_act("A", dur=5), _act("B", dur=10), _act("C", dur=3)]
        s.relationships = [_rel("A", "B"), _rel("A", "C")]
        result = compute_cpm(s)
        self.assertIn("B", result.critical_path)  # longer path
        self.assertEqual(result.total_duration, 15)  # 5 + 10

    def test_float_computation(self):
        s = ScheduleData()
        s.activities = [_act("A", dur=5), _act("B", dur=10), _act("C", dur=3)]
        s.relationships = [_rel("A", "B"), _rel("A", "C")]
        result = compute_cpm(s)
        # C should have float (shorter path)
        self.assertGreater(result.task_details["C"]["total_float"], 0)
        # A and B should be critical
        self.assertTrue(result.task_details["A"]["is_critical"])
        self.assertTrue(result.task_details["B"]["is_critical"])

    def test_cycle_detection(self):
        s = ScheduleData()
        s.activities = [_act("A"), _act("B")]
        s.relationships = [_rel("A", "B"), _rel("B", "A")]
        result = compute_cpm(s)
        self.assertTrue(result.has_cycles)

    def test_lag_handling(self):
        s = ScheduleData()
        s.activities = [_act("A", dur=5), _act("B", dur=5)]
        s.relationships = [_rel("A", "B", lag=3)]
        result = compute_cpm(s)
        self.assertEqual(result.total_duration, 13)  # 5 + 3 lag + 5

    def test_empty_schedule(self):
        s = ScheduleData()
        result = compute_cpm(s)
        self.assertEqual(result.total_duration, 0)


class TestDrivingPath(unittest.TestCase):
    def test_basic_driving_path(self):
        s = _make_schedule()
        result = find_driving_path(s, "4")
        self.assertIn("4", result.driving_path)
        self.assertGreater(len(result.driving_path), 1)

    def test_bottleneck_identified(self):
        s = _make_schedule()
        result = find_driving_path(s, "5")
        self.assertTrue(result.bottleneck_id)

    def test_nonexistent_activity(self):
        s = _make_schedule()
        result = find_driving_path(s, "NONEXISTENT")
        self.assertEqual(len(result.driving_path), 0)


class TestWhatIf(unittest.TestCase):
    def test_delay_impact(self):
        s = ScheduleData()
        s.activities = [_act("A", dur=5), _act("B", dur=10)]
        s.relationships = [_rel("A", "B")]
        result = what_if_delay(s, "A", 5)
        self.assertEqual(result.delta, 5)  # critical activity, full impact

    def test_non_critical_delay(self):
        s = ScheduleData()
        s.activities = [_act("A", dur=5), _act("B", dur=10), _act("C", dur=3)]
        s.relationships = [_rel("A", "B"), _rel("A", "C")]
        result = what_if_delay(s, "C", 2)
        self.assertEqual(result.delta, 0)  # C has float, no project impact


class TestMissingLogic(unittest.TestCase):
    def test_detects_open_ends(self):
        s = ScheduleData()
        s.activities = [_act("A"), _act("B"), _act("C")]
        s.relationships = [_rel("A", "B")]  # C has no links
        result = find_missing_logic(s)
        dangling_ids = [d["id"] for d in result["dangling"]]
        self.assertIn("C", dangling_ids)

    def test_clean_schedule(self):
        s = ScheduleData()
        s.activities = [_act("A"), _act("B")]
        s.relationships = [_rel("A", "B")]
        result = find_missing_logic(s)
        self.assertEqual(result["summary"]["dangling"], 0)


# ── Tool Tests ───────────────────────────────────────────────────────

class TestScheduleTools(unittest.TestCase):
    def setUp(self):
        self.schedule = _make_schedule()
        self.tools = ScheduleTools(self.schedule)

    def test_get_activity(self):
        r = self.tools.get_activity("1")
        self.assertEqual(r["name"], "Task 1")
        self.assertEqual(r["duration"], 5)

    def test_get_activity_not_found(self):
        r = self.tools.get_activity("NOPE")
        self.assertIn("error", r)

    def test_find_activities_by_status(self):
        r = self.tools.find_activities(status="completed")
        self.assertEqual(r["total_matches"], 1)

    def test_find_activities_by_float(self):
        r = self.tools.find_activities(max_float=0)
        self.assertGreater(r["total_matches"], 0)

    def test_find_activities_by_name(self):
        r = self.tools.find_activities(name_contains="Task 3")
        self.assertEqual(r["total_matches"], 1)

    def test_predecessors_chain(self):
        r = self.tools.get_predecessors_chain("4", depth=3)
        self.assertGreater(len(r["predecessors"]), 0)

    def test_successors_chain(self):
        r = self.tools.get_successors_chain("1", depth=3)
        self.assertGreater(len(r["successors"]), 0)

    def test_critical_path(self):
        r = self.tools.compute_critical_path()
        self.assertIn("critical_path", r)

    def test_driving_path(self):
        r = self.tools.get_driving_path("4")
        self.assertIn("driving_path", r)

    def test_simulate_delay(self):
        r = self.tools.simulate_delay("2", 5)
        self.assertIn("project_impact", r)

    def test_logic_health(self):
        r = self.tools.check_logic_health()
        self.assertIn("summary", r)

    def test_wbs_summary(self):
        r = self.tools.get_wbs_summary()
        self.assertIn("wbs_areas", r)

    def test_resource_loading(self):
        r = self.tools.get_resource_loading()
        self.assertIn("resources", r)

    def test_recommendations(self):
        r = self.tools.get_recommendations()
        self.assertIn("recommendations", r)

    def test_dispatch_tool(self):
        r = dispatch_tool(self.tools, "get_activity", activity_id="1")
        self.assertEqual(r["name"], "Task 1")

    def test_dispatch_unknown_tool(self):
        r = dispatch_tool(self.tools, "nonexistent_tool")
        self.assertIn("error", r)


# ── Agent Tests ──────────────────────────────────────────────────────

class TestAgentSummary(unittest.TestCase):
    def test_summary_contains_project(self):
        s = _make_schedule()
        dcma = run_dcma_assessment(s)
        risk = analyze_risks(s)
        summary = _build_summary(s, dcma, risk)
        self.assertIn("Test Bridge", summary)
        self.assertIn("test.xer", summary)

    def test_summary_contains_dcma(self):
        s = _make_schedule()
        dcma = run_dcma_assessment(s)
        summary = _build_summary(s, dcma, None)
        self.assertIn("DCMA", summary)

    def test_summary_contains_risk(self):
        s = _make_schedule()
        risk = analyze_risks(s)
        summary = _build_summary(s, None, risk)
        self.assertIn("RISK", summary)


class TestAgentSetup(unittest.TestCase):
    def test_load_schedule(self):
        agent = ScheduleAgent(AgentConfig(gemini_api_key="fake"))
        agent.load_schedule(_make_schedule())
        self.assertTrue(agent.get_api_status()["schedule_loaded"])

    def test_ask_without_loading_raises(self):
        agent = ScheduleAgent()
        with self.assertRaises(RuntimeError):
            agent.ask("test")

    def test_no_api_key_returns_message(self):
        agent = ScheduleAgent(AgentConfig(provider="gemini", gemini_api_key=""))
        agent.load_schedule(_make_schedule())
        resp = agent.ask("test")
        self.assertIn("API key", resp)

    def test_run_tool_directly(self):
        agent = ScheduleAgent()
        agent.load_schedule(_make_schedule())
        r = agent.run_tool("get_activity", activity_id="1")
        self.assertEqual(r["name"], "Task 1")

    def test_unknown_provider_raises(self):
        agent = ScheduleAgent(AgentConfig(provider="openai"))
        agent.load_schedule(_make_schedule())
        with self.assertRaises(RuntimeError):
            agent.ask("test")


class TestWithSampleXER(unittest.TestCase):
    def test_full_pipeline(self):
        from pathlib import Path
        from parsers.registry import create_default_registry
        xer = Path(__file__).parent.parent / "data" / "sample_schedule.xer"
        if not xer.exists():
            self.skipTest("No XER")
        registry = create_default_registry()
        schedule = registry.parse(str(xer))
        tools = ScheduleTools(schedule)

        # Test all tools work on real data
        self.assertGreater(len(tools.get_activity("1")["name"]), 0)
        self.assertGreater(len(tools.compute_critical_path()["critical_path"]), 0)
        self.assertIn("recommendations", tools.get_recommendations())
        self.assertIn("wbs_areas", tools.get_wbs_summary())
        self.assertIn("summary", tools.check_logic_health())


if __name__ == "__main__":
    unittest.main()
