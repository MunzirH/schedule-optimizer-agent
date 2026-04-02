"""
Schedule Optimizer Agent — Web API

FastAPI backend serving:
  - POST /api/upload          → upload schedule file, get full analysis
  - GET  /api/status          → server health check
  - POST /api/chat            → ask AI agent a question
  - POST /api/tool            → directly call an agent tool
  - POST /api/compare         → compare two schedule files
"""

import os
import json
import tempfile
import traceback
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

from parsers.registry import create_default_registry
from agent.dcma_assessment import run_dcma_assessment
from agent.risk_analysis import analyze_risks, compare_schedules
from agent.ai_agent import ScheduleAgent, AgentConfig
from agent.tools import ScheduleTools, dispatch_tool, TOOL_DESCRIPTIONS
from models.schedule import ActivityStatus, ActivityType


app = FastAPI(
    title="Schedule Optimizer Agent",
    description="AI-powered construction schedule analyzer",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state for current session
_session = {
    "schedule": None,
    "dcma_report": None,
    "risk_report": None,
    "agent": None,
    "tools": None,
    "filename": None,
}


# ── Models ───────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    question: str
    provider: Optional[str] = "gemini"

class ToolRequest(BaseModel):
    tool_name: str
    kwargs: Optional[dict] = {}


# ── Endpoints ────────────────────────────────────────────────────────

@app.get("/api/status")
def status():
    return {
        "status": "running",
        "schedule_loaded": _session["schedule"] is not None,
        "filename": _session["filename"],
        "tools_available": list(TOOL_DESCRIPTIONS.keys()),
    }


@app.post("/api/upload")
async def upload_schedule(file: UploadFile = File(...)):
    """Upload a schedule file and run full analysis."""
    if not file.filename:
        raise HTTPException(400, "No file provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in (".csv", ".tsv", ".xer", ".xml"):
        raise HTTPException(400, "Unsupported format: " + ext + ". Use .csv, .xer, or .xml")

    # Save to temp file
    try:
        content = await file.read()
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
        tmp.write(content)
        tmp.close()
    except Exception as e:
        raise HTTPException(500, "Failed to save file: " + str(e))

    # Parse
    try:
        registry = create_default_registry()
        schedule = registry.parse(tmp.name)
    except Exception as e:
        os.unlink(tmp.name)
        raise HTTPException(400, "Parse error: " + str(e))

    # Analyze
    try:
        dcma_report = run_dcma_assessment(schedule)
        risk_report = analyze_risks(schedule)
    except Exception as e:
        os.unlink(tmp.name)
        raise HTTPException(500, "Analysis error: " + str(e))

    # Store in session
    _session["schedule"] = schedule
    _session["dcma_report"] = dcma_report
    _session["risk_report"] = risk_report
    _session["tools"] = ScheduleTools(schedule)
    _session["filename"] = file.filename

    # Set up agent
    agent = ScheduleAgent(AgentConfig())
    agent.load_schedule(schedule, dcma_report, risk_report)
    _session["agent"] = agent

    os.unlink(tmp.name)

    # Build response
    return _build_analysis_response(schedule, dcma_report, risk_report, file.filename)


@app.post("/api/chat")
def chat(req: ChatRequest):
    """Ask the AI agent a question about the loaded schedule."""
    if not _session["agent"]:
        raise HTTPException(400, "No schedule loaded. Upload a file first.")

    try:
        response = _session["agent"].ask(req.question)
        return {"response": response}
    except Exception as e:
        return {"response": "Error: " + str(e)}


@app.post("/api/tool")
def call_tool(req: ToolRequest):
    """Directly call an agent tool."""
    if not _session["tools"]:
        raise HTTPException(400, "No schedule loaded.")

    result = dispatch_tool(_session["tools"], req.tool_name, **req.kwargs)
    return {"tool": req.tool_name, "result": result}


@app.post("/api/compare")
async def compare(
    current: UploadFile = File(...),
    previous: UploadFile = File(...),
):
    """Compare two schedule files."""
    registry = create_default_registry()
    files = []

    try:
        for f in [current, previous]:
            content = await f.read()
            ext = Path(f.filename).suffix.lower()
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
            tmp.write(content)
            tmp.close()
            files.append(tmp.name)

        sched_current = registry.parse(files[0])
        sched_previous = registry.parse(files[1])

        comp = compare_schedules(sched_current, sched_previous)

        return {
            "summary": comp.summary,
            "duration_changes": comp.duration_changes[:50],
            "float_changes": comp.float_changes[:50],
            "status_changes": comp.status_changes[:50],
            "critical_path_changes": comp.critical_path_changes[:50],
            "added": len(comp.added_activities),
            "removed": len(comp.removed_activities),
        }
    except Exception as e:
        raise HTTPException(400, "Comparison error: " + str(e))
    finally:
        for f in files:
            os.unlink(f)


# ── Response Builder ─────────────────────────────────────────────────

def _build_analysis_response(schedule, dcma, risk, filename):
    """Build the JSON response for the frontend."""

    # Project overview
    project = {
        "name": schedule.project.name,
        "filename": filename,
        "source_format": schedule.project.source_format,
        "data_date": schedule.project.data_date.isoformat() if schedule.project.data_date else None,
        "start_date": schedule.project.start_date.isoformat() if schedule.project.start_date else None,
        "finish_date": schedule.project.finish_date.isoformat() if schedule.project.finish_date else None,
        "total_activities": len(schedule.activities),
        "total_relationships": len(schedule.relationships),
        "total_resources": len(schedule.resources),
        "completed": len([a for a in schedule.activities if a.status == ActivityStatus.COMPLETED]),
        "in_progress": len([a for a in schedule.activities if a.status == ActivityStatus.IN_PROGRESS]),
        "not_started": len([a for a in schedule.activities if a.status == ActivityStatus.NOT_STARTED]),
    }

    # DCMA checks
    dcma_checks = []
    for c in dcma.checks:
        dcma_checks.append({
            "number": c.check_number,
            "name": c.name,
            "passed": c.passed,
            "value": c.metric_value,
            "threshold": c.threshold,
            "direction": c.threshold_direction,
            "unit": c.unit,
            "detail": c.detail,
            "flagged_count": len(c.flagged_ids),
            "flagged_sample": c.flagged_ids[:10],
        })

    dcma_summary = {
        "passed": dcma.passed_count,
        "failed": dcma.failed_count,
        "total": len(dcma.checks),
        "score": round(dcma.score_pct, 1),
        "grade": dcma.grade,
        "checks": dcma_checks,
    }

    # Risk analysis
    risk_data = {
        "level": risk.risk_level,
        "critical_count": risk.critical_count,
        "near_critical_count": risk.near_critical_count,
        "negative_float_count": risk.negative_float_count,
        "avg_float": round(risk.avg_float, 1),
        "bei": round(risk.bei, 3),
        "cpli": round(risk.cpli, 3),
        "float_distribution": [
            {"label": b.label, "count": b.count, "percentage": b.percentage}
            for b in risk.float_distribution
        ],
        "top_risks": [
            {
                "id": r.activity_id, "name": r.name, "duration": r.duration,
                "float": r.total_float, "score": r.risk_score, "category": r.risk_category,
            }
            for r in risk.top_risks[:20]
        ],
        "wbs_risks": [
            {
                "wbs_id": w.wbs_id, "name": w.wbs_name, "total": w.total_activities,
                "critical": w.critical_count, "near_critical": w.near_critical_count,
                "negative_float": w.negative_float_count, "score": w.risk_score,
            }
            for w in risk.wbs_risks if w.risk_score > 0
        ][:15],
    }

    # Activities for Gantt (prioritized, limited)
    prioritized = sorted(
        schedule.activities,
        key=lambda a: (
            0 if (a.total_float is not None and a.total_float < 0) else
            1 if (a.total_float is not None and abs(a.total_float) < 0.01) else
            2 if a.status == ActivityStatus.IN_PROGRESS else 3
        ),
    )

    activities = []
    for a in prioritized[:500]:
        activities.append({
            "id": a.activity_id,
            "name": a.name,
            "duration": a.duration,
            "start": a.start_date.isoformat() if a.start_date else None,
            "finish": a.finish_date.isoformat() if a.finish_date else None,
            "status": a.status.value,
            "float": a.total_float,
            "wbs": a.wbs_id,
            "is_critical": a.total_float is not None and abs(a.total_float) < 0.01,
            "is_milestone": a.activity_type == ActivityType.MILESTONE,
            "percent_complete": a.percent_complete,
        })

    return {
        "project": project,
        "dcma": dcma_summary,
        "risk": risk_data,
        "activities": activities,
    }


# ── Serve Frontend ───────────────────────────────────────────────────

frontend_dir = Path(__file__).parent / "frontend" / "dist"
if frontend_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(frontend_dir / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        file_path = frontend_dir / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(frontend_dir / "index.html"))
