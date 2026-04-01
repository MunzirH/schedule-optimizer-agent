"""
Unified schedule data model.

Every parser (CSV, XER, XML, MSP, PDF) must produce a ScheduleData object.
All downstream analysis (DCMA 14-point, critical path, risk, AI agent)
operates exclusively on this model — never on raw file data.
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Optional


# ── Enums ──────────────────────────────────────────────────────────────────

class RelationshipType(Enum):
    """Dependency relationship between two activities."""
    FS = "Finish-to-Start"
    SS = "Start-to-Start"
    FF = "Finish-to-Finish"
    SF = "Start-to-Finish"


class ConstraintType(Enum):
    """Schedule constraint applied to an activity."""
    NONE = "None"
    ASAP = "As Soon As Possible"
    ALAP = "As Late As Possible"
    SNET = "Start No Earlier Than"
    SNLT = "Start No Later Than"
    FNET = "Finish No Earlier Than"
    FNLT = "Finish No Later Than"
    MSO = "Must Start On"
    MFO = "Must Finish On"


class ActivityType(Enum):
    """Type of schedule activity."""
    TASK = "Task"
    MILESTONE = "Milestone"
    LOE = "Level of Effort"          # summary / hammock
    SUMMARY = "Summary"
    WBS_SUMMARY = "WBS Summary"


class ActivityStatus(Enum):
    """Current status of an activity."""
    NOT_STARTED = "Not Started"
    IN_PROGRESS = "In Progress"
    COMPLETED = "Completed"


# ── Core data classes ──────────────────────────────────────────────────────

@dataclass
class Calendar:
    """Work calendar defining working days and holidays."""
    calendar_id: str
    name: str
    is_default: bool = False
    work_days: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])  # Mon-Fri
    holidays: list[date] = field(default_factory=list)
    hours_per_day: float = 8.0


@dataclass
class Resource:
    """A resource (person, crew, equipment) that can be assigned to activities."""
    resource_id: str
    name: str
    resource_type: str = "Labor"  # Labor, Material, Equipment
    max_units: float = 1.0        # availability (1.0 = 100%)
    cost_per_hour: float = 0.0


@dataclass
class ResourceAssignment:
    """Assignment of a resource to an activity."""
    activity_id: str
    resource_id: str
    planned_units: float = 0.0     # planned hours/quantity
    actual_units: float = 0.0      # actual hours/quantity
    planned_cost: float = 0.0
    actual_cost: float = 0.0


@dataclass
class Relationship:
    """Dependency link between two activities."""
    predecessor_id: str
    successor_id: str
    relationship_type: RelationshipType = RelationshipType.FS
    lag_days: float = 0.0          # positive = lag, negative = lead


@dataclass
class WBSNode:
    """Work Breakdown Structure node."""
    wbs_id: str
    name: str
    parent_id: Optional[str] = None
    level: int = 0


@dataclass
class Activity:
    """
    A single schedule activity — the fundamental unit of work.

    This is intentionally flat and serializable. Complex derived values
    (float, early/late dates) are computed by the analysis engine,
    not stored here.
    """
    activity_id: str
    name: str
    duration: float                            # original/remaining duration in days

    # Dates
    start_date: Optional[datetime] = None      # planned/early start
    finish_date: Optional[datetime] = None     # planned/early finish
    actual_start: Optional[datetime] = None
    actual_finish: Optional[datetime] = None
    baseline_start: Optional[datetime] = None
    baseline_finish: Optional[datetime] = None

    # Classification
    activity_type: ActivityType = ActivityType.TASK
    status: ActivityStatus = ActivityStatus.NOT_STARTED
    percent_complete: float = 0.0

    # Hierarchy
    wbs_id: Optional[str] = None
    calendar_id: Optional[str] = None

    # Constraints
    constraint_type: ConstraintType = ConstraintType.NONE
    constraint_date: Optional[datetime] = None

    # Float (populated by analysis, not parsers)
    total_float: Optional[float] = None
    free_float: Optional[float] = None

    # Original duration (before progress)
    original_duration: Optional[float] = None


@dataclass
class ProjectInfo:
    """Top-level project metadata."""
    project_id: str = ""
    name: str = ""
    data_date: Optional[datetime] = None       # status date / as-of date
    start_date: Optional[datetime] = None
    finish_date: Optional[datetime] = None
    source_format: str = ""                    # "csv", "xer", "xml", "mpp", "pdf"
    source_file: str = ""


@dataclass
class ScheduleData:
    """
    The unified schedule container.

    This is the ONLY object that crosses the boundary between
    parsers and the analysis engine. Every parser returns one of these.
    """
    project: ProjectInfo = field(default_factory=ProjectInfo)
    activities: list[Activity] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    calendars: list[Calendar] = field(default_factory=list)
    resources: list[Resource] = field(default_factory=list)
    resource_assignments: list[ResourceAssignment] = field(default_factory=list)
    wbs: list[WBSNode] = field(default_factory=list)

    # ── Convenience accessors ──────────────────────────────────────────

    def get_activity(self, activity_id: str) -> Optional[Activity]:
        """Look up an activity by ID."""
        for a in self.activities:
            if a.activity_id == activity_id:
                return a
        return None

    def get_predecessors(self, activity_id: str) -> list[Relationship]:
        """Get all relationships where this activity is the successor."""
        return [r for r in self.relationships if r.successor_id == activity_id]

    def get_successors(self, activity_id: str) -> list[Relationship]:
        """Get all relationships where this activity is the predecessor."""
        return [r for r in self.relationships if r.predecessor_id == activity_id]

    def activity_ids(self) -> set[str]:
        """Set of all activity IDs."""
        return {a.activity_id for a in self.activities}

    def summary(self) -> dict:
        """Quick summary stats for the schedule."""
        statuses = {}
        for a in self.activities:
            statuses[a.status.value] = statuses.get(a.status.value, 0) + 1

        rel_types = {}
        for r in self.relationships:
            key = r.relationship_type.value
            rel_types[key] = rel_types.get(key, 0) + 1

        return {
            "project_name": self.project.name,
            "source_format": self.project.source_format,
            "total_activities": len(self.activities),
            "total_relationships": len(self.relationships),
            "total_resources": len(self.resources),
            "total_calendars": len(self.calendars),
            "wbs_nodes": len(self.wbs),
            "activity_statuses": statuses,
            "relationship_types": rel_types,
            "data_date": self.project.data_date.isoformat() if self.project.data_date else None,
        }
