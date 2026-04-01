"""
Agent Tools — queryable functions for the AI agent.

These tools give the agent the ability to dynamically query,
analyze, and reason about the schedule data instead of relying
on a static text dump.

Each tool returns a dict that gets serialized to the AI as context.
"""

from collections import Counter, defaultdict
from models.schedule import (
    ScheduleData, Activity, ActivityType, ActivityStatus, RelationshipType,
)
from optimization.critical_path import (
    compute_cpm, find_driving_path, what_if_delay, find_missing_logic,
)


class ScheduleTools:
    """
    Tool functions the AI agent can invoke to query the schedule.

    The agent describes what it wants to look up, the tool dispatcher
    calls the right function, and the result is fed back to the agent.
    """

    def __init__(self, schedule: ScheduleData):
        self.schedule = schedule
        self._cpm_cache = None

    # ── Activity Queries ─────────────────────────────────────────────

    def get_activity(self, activity_id: str) -> dict:
        """Get full details for a specific activity."""
        a = self.schedule.get_activity(activity_id)
        if not a:
            return {"error": "Activity " + activity_id + " not found"}

        preds = self.schedule.get_predecessors(activity_id)
        succs = self.schedule.get_successors(activity_id)

        return {
            "activity_id": a.activity_id,
            "name": a.name,
            "duration": a.duration,
            "original_duration": a.original_duration,
            "status": a.status.value,
            "type": a.activity_type.value,
            "total_float": a.total_float,
            "free_float": a.free_float,
            "start_date": a.start_date.strftime("%Y-%m-%d") if a.start_date else None,
            "finish_date": a.finish_date.strftime("%Y-%m-%d") if a.finish_date else None,
            "actual_start": a.actual_start.strftime("%Y-%m-%d") if a.actual_start else None,
            "actual_finish": a.actual_finish.strftime("%Y-%m-%d") if a.actual_finish else None,
            "baseline_start": a.baseline_start.strftime("%Y-%m-%d") if a.baseline_start else None,
            "baseline_finish": a.baseline_finish.strftime("%Y-%m-%d") if a.baseline_finish else None,
            "wbs_id": a.wbs_id,
            "constraint": a.constraint_type.value,
            "percent_complete": a.percent_complete,
            "predecessors": [
                {"id": r.predecessor_id, "type": r.relationship_type.name, "lag": r.lag_days}
                for r in preds
            ],
            "successors": [
                {"id": r.successor_id, "type": r.relationship_type.name, "lag": r.lag_days}
                for r in succs
            ],
        }

    def find_activities(self, name_contains: str = "", wbs_id: str = "",
                        status: str = "", min_float: float = None,
                        max_float: float = None, min_duration: float = None,
                        limit: int = 30) -> dict:
        """Search activities by name, WBS, status, float range, or duration."""
        results = []
        for a in self.schedule.activities:
            if name_contains and name_contains.lower() not in a.name.lower():
                continue
            if wbs_id and a.wbs_id != wbs_id:
                continue
            if status:
                if status.lower() == "completed" and a.status != ActivityStatus.COMPLETED:
                    continue
                if status.lower() == "in progress" and a.status != ActivityStatus.IN_PROGRESS:
                    continue
                if status.lower() == "not started" and a.status != ActivityStatus.NOT_STARTED:
                    continue
            if min_float is not None and (a.total_float is None or a.total_float < min_float):
                continue
            if max_float is not None and (a.total_float is None or a.total_float > max_float):
                continue
            if min_duration is not None and a.duration < min_duration:
                continue

            fl = a.total_float if a.total_float is not None else None
            results.append({
                "id": a.activity_id,
                "name": a.name,
                "duration": a.duration,
                "float": fl,
                "status": a.status.value,
                "wbs": a.wbs_id,
            })

        return {
            "total_matches": len(results),
            "showing": min(len(results), limit),
            "activities": results[:limit],
        }

    # ── Logic Analysis ───────────────────────────────────────────────

    def get_predecessors_chain(self, activity_id: str, depth: int = 5) -> dict:
        """Trace predecessor chain backwards up to N levels."""
        chain = []
        visited = set()
        self._trace_preds(activity_id, chain, visited, depth, 0)
        return {
            "target": activity_id,
            "chain_depth": depth,
            "predecessors": chain,
        }

    def _trace_preds(self, aid, chain, visited, max_depth, current_depth):
        if current_depth >= max_depth or aid in visited:
            return
        visited.add(aid)
        preds = self.schedule.get_predecessors(aid)
        for r in preds:
            a = self.schedule.get_activity(r.predecessor_id)
            if a:
                entry = {
                    "id": a.activity_id,
                    "name": a.name,
                    "duration": a.duration,
                    "float": a.total_float,
                    "status": a.status.value,
                    "rel_type": r.relationship_type.name,
                    "lag": r.lag_days,
                    "depth": current_depth + 1,
                }
                chain.append(entry)
                self._trace_preds(r.predecessor_id, chain, visited, max_depth, current_depth + 1)

    def get_successors_chain(self, activity_id: str, depth: int = 5) -> dict:
        """Trace successor chain forwards up to N levels."""
        chain = []
        visited = set()
        self._trace_succs(activity_id, chain, visited, depth, 0)
        return {
            "target": activity_id,
            "chain_depth": depth,
            "successors": chain,
        }

    def _trace_succs(self, aid, chain, visited, max_depth, current_depth):
        if current_depth >= max_depth or aid in visited:
            return
        visited.add(aid)
        succs = self.schedule.get_successors(aid)
        for r in succs:
            a = self.schedule.get_activity(r.successor_id)
            if a:
                entry = {
                    "id": a.activity_id,
                    "name": a.name,
                    "duration": a.duration,
                    "float": a.total_float,
                    "status": a.status.value,
                    "rel_type": r.relationship_type.name,
                    "lag": r.lag_days,
                    "depth": current_depth + 1,
                }
                chain.append(entry)
                self._trace_succs(r.successor_id, chain, visited, max_depth, current_depth + 1)

    # ── Critical Path & Driving Path ─────────────────────────────────

    def compute_critical_path(self) -> dict:
        """Compute or retrieve the critical path."""
        if not self._cpm_cache:
            self._cpm_cache = compute_cpm(self.schedule)

        r = self._cpm_cache
        if r.has_cycles:
            return {"error": "Schedule has circular dependencies", "cycle_nodes": r.cycle_nodes}

        path_details = []
        for aid in r.critical_path:
            detail = r.task_details.get(aid, {})
            path_details.append({
                "id": aid,
                "name": detail.get("name", ""),
                "duration": detail.get("duration", 0),
                "es": detail.get("earliest_start", 0),
                "ef": detail.get("earliest_finish", 0),
            })

        return {
            "critical_path": r.critical_path,
            "total_duration": r.total_duration,
            "critical_activities_count": len(r.critical_path),
            "path_details": path_details,
        }

    def get_driving_path(self, activity_id: str) -> dict:
        """Find what's driving the dates for a specific activity."""
        r = find_driving_path(self.schedule, activity_id)
        return {
            "target": r.target_id,
            "driving_path": r.driving_path,
            "path_length": len(r.driving_path),
            "total_duration": r.total_duration,
            "bottleneck": r.bottleneck_id,
            "bottleneck_name": r.bottleneck_name,
            "relationships": r.driving_relationships,
        }

    # ── What-If Scenarios ────────────────────────────────────────────

    def simulate_delay(self, activity_id: str, delay_days: float) -> dict:
        """What happens if this activity is delayed by N days?"""
        r = what_if_delay(self.schedule, activity_id, delay_days)
        return {
            "scenario": r.scenario,
            "original_duration": r.original_duration,
            "new_duration": r.new_duration,
            "project_impact": r.delta,
            "critical_path_changed": r.original_critical_path != r.new_critical_path,
            "affected_count": len(r.affected_activities),
            "most_affected": r.affected_activities[:15],
        }

    # ── Logic Health ─────────────────────────────────────────────────

    def check_logic_health(self) -> dict:
        """Detect missing logic and suggest fixes."""
        return find_missing_logic(self.schedule)

    # ── WBS Analysis ─────────────────────────────────────────────────

    def get_wbs_summary(self, wbs_id: str = "") -> dict:
        """Get summary for a specific WBS area, or all WBS areas."""
        wbs_groups = defaultdict(list)
        for a in self.schedule.activities:
            wid = a.wbs_id or "Unassigned"
            if wbs_id and wid != wbs_id:
                continue
            wbs_groups[wid].append(a)

        wbs_names = {w.wbs_id: w.name for w in self.schedule.wbs}
        summaries = []

        for wid, acts in wbs_groups.items():
            completed = len([a for a in acts if a.status == ActivityStatus.COMPLETED])
            in_progress = len([a for a in acts if a.status == ActivityStatus.IN_PROGRESS])
            not_started = len([a for a in acts if a.status == ActivityStatus.NOT_STARTED])
            floats = [a.total_float for a in acts if a.total_float is not None]
            neg = len([f for f in floats if f < 0])
            crit = len([f for f in floats if abs(f) < 0.01])

            summaries.append({
                "wbs_id": wid,
                "wbs_name": wbs_names.get(wid, wid),
                "total": len(acts),
                "completed": completed,
                "in_progress": in_progress,
                "not_started": not_started,
                "critical": crit,
                "negative_float": neg,
                "avg_float": round(sum(floats) / len(floats), 1) if floats else 0,
                "min_float": round(min(floats), 1) if floats else 0,
            })

        summaries.sort(key=lambda s: s.get("min_float", 0))
        return {"wbs_areas": summaries}

    # ── Resource Analysis ────────────────────────────────────────────

    def get_resource_loading(self, resource_name: str = "") -> dict:
        """Get resource assignments and detect overallocation."""
        res_map = {r.resource_id: r.name for r in self.schedule.resources}
        assignments = defaultdict(list)

        for ra in self.schedule.resource_assignments:
            rname = res_map.get(ra.resource_id, ra.resource_id)
            if resource_name and resource_name.lower() not in rname.lower():
                continue
            a = self.schedule.get_activity(ra.activity_id)
            if a and a.status != ActivityStatus.COMPLETED:
                assignments[rname].append({
                    "activity_id": a.activity_id,
                    "name": a.name,
                    "duration": a.duration,
                    "start": a.start_date.strftime("%Y-%m-%d") if a.start_date else None,
                    "finish": a.finish_date.strftime("%Y-%m-%d") if a.finish_date else None,
                })

        result = []
        for rname, acts in assignments.items():
            result.append({
                "resource": rname,
                "assignment_count": len(acts),
                "activities": acts[:20],
            })

        result.sort(key=lambda r: r["assignment_count"], reverse=True)
        return {"resources": result[:20]}

    # ── Schedule Recommendations ─────────────────────────────────────

    def get_recommendations(self) -> dict:
        """
        Analyze the schedule and generate improvement recommendations.
        Uses schedule data, logic health, and metrics to suggest fixes.
        """
        recs = []

        # Check logic health
        logic = find_missing_logic(self.schedule)
        if logic["summary"]["open_starts"] > 10:
            recs.append({
                "priority": "HIGH",
                "category": "Logic",
                "issue": str(logic["summary"]["open_starts"]) + " activities have no predecessors",
                "recommendation": "Add predecessor relationships to open-start activities. " +
                                  "Focus on activities with low float first.",
                "count": logic["summary"]["open_starts"],
            })

        if logic["summary"]["open_ends"] > 10:
            recs.append({
                "priority": "HIGH",
                "category": "Logic",
                "issue": str(logic["summary"]["open_ends"]) + " activities have no successors",
                "recommendation": "Add successor relationships to open-end activities to ensure " +
                                  "they influence the project finish date.",
                "count": logic["summary"]["open_ends"],
            })

        # Negative float
        neg_float_acts = [
            a for a in self.schedule.activities
            if a.total_float is not None and a.total_float < 0
            and a.status != ActivityStatus.COMPLETED
        ]
        if neg_float_acts:
            worst = min(neg_float_acts, key=lambda a: a.total_float)
            recs.append({
                "priority": "CRITICAL",
                "category": "Schedule Delay",
                "issue": str(len(neg_float_acts)) + " activities have negative float (worst: " +
                         str(int(worst.total_float)) + " days on " + worst.activity_id + ": " + worst.name + ")",
                "recommendation": "Develop a recovery plan. Consider crashing critical activities, " +
                                  "fast-tracking parallel work, or re-sequencing. Focus on the driving " +
                                  "path to the most delayed activities.",
                "count": len(neg_float_acts),
            })

        # Long duration activities
        long_acts = [
            a for a in self.schedule.activities
            if a.duration > 44 and a.activity_type == ActivityType.TASK
            and a.status != ActivityStatus.COMPLETED
        ]
        if len(long_acts) > 20:
            recs.append({
                "priority": "MEDIUM",
                "category": "Activity Detail",
                "issue": str(len(long_acts)) + " activities exceed 44 days duration",
                "recommendation": "Break long-duration activities into smaller, measurable tasks. " +
                                  "This improves progress tracking and schedule accuracy.",
                "count": len(long_acts),
            })

        # Resource loading
        res_counts = Counter(ra.resource_id for ra in self.schedule.resource_assignments)
        if res_counts:
            busiest_id, busiest_count = res_counts.most_common(1)[0]
            res_names = {r.resource_id: r.name for r in self.schedule.resources}
            if busiest_count > 100:
                recs.append({
                    "priority": "MEDIUM",
                    "category": "Resources",
                    "issue": res_names.get(busiest_id, busiest_id) + " has " + str(busiest_count) + " assignments",
                    "recommendation": "Review resource loading for overallocation. Consider adding " +
                                      "crews or redistributing work.",
                    "count": busiest_count,
                })

        # Unresourced activities
        assigned_ids = {ra.activity_id for ra in self.schedule.resource_assignments}
        unresourced = [
            a for a in self.schedule.activities
            if a.activity_id not in assigned_ids
            and a.activity_type == ActivityType.TASK
            and a.status != ActivityStatus.COMPLETED
        ]
        if len(unresourced) > len(self.schedule.activities) * 0.5:
            recs.append({
                "priority": "MEDIUM",
                "category": "Resources",
                "issue": str(len(unresourced)) + " incomplete tasks have no resource assignment",
                "recommendation": "Resource-load the schedule to enable resource leveling and " +
                                  "identify overallocations.",
                "count": len(unresourced),
            })

        # Non-FS relationships
        total_rels = len(self.schedule.relationships)
        fs_count = sum(1 for r in self.schedule.relationships if r.relationship_type == RelationshipType.FS)
        if total_rels > 0:
            fs_pct = fs_count / total_rels * 100
            if fs_pct < 90:
                recs.append({
                    "priority": "LOW",
                    "category": "Relationship Types",
                    "issue": "Only " + str(round(fs_pct)) + "% finish-to-start relationships (target: 90%+)",
                    "recommendation": "Review non-FS relationships. Replace SS/FF with FS where possible " +
                                      "to improve schedule logic clarity.",
                    "count": total_rels - fs_count,
                })

        recs.sort(key=lambda r: {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}.get(r["priority"], 4))
        return {"recommendations": recs}


# ── Tool Dispatcher ──────────────────────────────────────────────────

TOOL_DESCRIPTIONS = {
    "get_activity": "Get full details for a specific activity by ID",
    "find_activities": "Search activities by name, WBS, status, float range, or duration",
    "get_predecessors_chain": "Trace predecessor chain backwards from an activity",
    "get_successors_chain": "Trace successor chain forwards from an activity",
    "compute_critical_path": "Compute the critical path through the network",
    "get_driving_path": "Find what chain of activities is driving dates for a specific activity",
    "simulate_delay": "What-if: simulate delaying an activity and see the project impact",
    "check_logic_health": "Detect missing predecessors/successors and suggest fixes",
    "get_wbs_summary": "Get schedule metrics broken down by WBS area",
    "get_resource_loading": "Get resource assignments and detect overallocation",
    "get_recommendations": "Generate improvement recommendations based on schedule analysis",
}


def dispatch_tool(tools: ScheduleTools, tool_name: str, **kwargs) -> dict:
    """Call a tool by name with keyword arguments."""
    func = getattr(tools, tool_name, None)
    if not func:
        return {"error": "Unknown tool: " + tool_name}
    try:
        return func(**kwargs)
    except Exception as e:
        return {"error": "Tool error: " + str(e)}
