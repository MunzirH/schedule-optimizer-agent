"""
Schedule AI Agent with Tool Calling.

The agent reasons about the schedule by calling tool functions
to query, compute, and analyze data on demand — instead of
relying on a static text dump.
"""

import json
import os
from dataclasses import dataclass

from models.schedule import ScheduleData, ActivityStatus
from agent.dcma_assessment import DcmaReport
from agent.risk_analysis import RiskReport
from agent.tools import ScheduleTools, TOOL_DESCRIPTIONS


SYSTEM_PROMPT = (
    "You are an expert construction schedule analyst with 20+ years of CPM "
    "scheduling, DCMA 14-point assessments, and project controls experience.\n\n"
    "You have FULL ACCESS to a parsed construction schedule through tool functions. "
    "You can query any activity, trace logic chains, compute the critical path, "
    "run what-if scenarios, and generate recommendations.\n\n"
    "IMPORTANT RULES:\n"
    "1. Use the tools to look up specific data before answering\n"
    "2. Reference specific activity IDs, durations, and float values\n"
    "3. Give actionable recommendations grounded in the data\n"
    "4. When asked about delays, use get_driving_path to trace the cause\n"
    "5. When asked about risks, use get_recommendations and find_activities\n"
    "6. When asked what-if questions, use simulate_delay\n"
    "7. Do NOT invent data — if you need it, call a tool\n"
    "8. When asked what file you are analyzing, reference the project name and source file\n\n"
    "Available tools:\n"
)


@dataclass
class AgentConfig:
    provider: str = "gemini"
    gemini_api_key: str = ""
    claude_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    claude_model: str = "claude-sonnet-4-6"
    max_context_activities: int = 500
    max_tool_rounds: int = 3


class ScheduleAgent:
    def __init__(self, config=None):
        self.config = config or AgentConfig()
        self._tools = None
        self._summary = ""
        self._history = []
        self._loaded = False

        if not self.config.gemini_api_key:
            self.config.gemini_api_key = os.environ.get("GEMINI_API_KEY", "")
        if not self.config.claude_api_key:
            self.config.claude_api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    def load_schedule(self, schedule, dcma_report=None, risk_report=None):
        """Load schedule and create tool interface."""
        self._tools = ScheduleTools(schedule)
        self._summary = _build_summary(schedule, dcma_report, risk_report)
        self._history = []
        self._loaded = True

    def ask(self, question):
        """Ask a question. The agent will call tools as needed."""
        if not self._loaded:
            raise RuntimeError("No schedule loaded.")

        self._history.append({"role": "user", "content": question})

        # Build the prompt with summary + tool descriptions + question
        enriched = self._enrich_question(question)

        if self.config.provider == "gemini":
            resp = _call_gemini(enriched, self._summary, self._history, self.config)
        elif self.config.provider == "claude":
            resp = _call_claude(enriched, self._summary, self._history, self.config)
        else:
            raise RuntimeError("Unknown provider: " + self.config.provider)

        # Check if agent wants to call a tool
        tool_result = self._try_tool_call(resp)
        if tool_result:
            # Feed tool result back and get final answer
            follow_up = resp + "\n\nTool Result:\n" + json.dumps(tool_result, indent=2, default=str)
            self._history.append({"role": "assistant", "content": follow_up})
            self._history.append({"role": "user", "content": "Based on the tool result above, provide your analysis."})

            if self.config.provider == "gemini":
                resp = _call_gemini("Analyze the tool result and answer the original question.",
                                    self._summary, self._history, self.config)
            else:
                resp = _call_claude("Analyze the tool result and answer the original question.",
                                    self._summary, self._history, self.config)

        self._history.append({"role": "assistant", "content": resp})
        return resp

    def run_tool(self, tool_name, **kwargs):
        """Directly run a tool and return results (for CLI use)."""
        if not self._tools:
            return {"error": "No schedule loaded"}
        from agent.tools import dispatch_tool
        return dispatch_tool(self._tools, tool_name, **kwargs)

    def get_api_status(self):
        return {
            "provider": self.config.provider,
            "gemini_configured": bool(self.config.gemini_api_key),
            "claude_configured": bool(self.config.claude_api_key),
            "schedule_loaded": self._loaded,
        }

    def _enrich_question(self, question):
        """Pre-process question: auto-call relevant tools based on keywords."""
        q_lower = question.lower()
        extra_context = []

        # Auto-call tools based on question patterns
        if any(w in q_lower for w in ["critical path", "cp ", "longest path"]):
            result = self._tools.compute_critical_path()
            extra_context.append("Critical Path Data:\n" + json.dumps(result, indent=2, default=str))

        if any(w in q_lower for w in ["recommend", "suggestion", "improve", "fix", "should we"]):
            result = self._tools.get_recommendations()
            extra_context.append("Recommendations:\n" + json.dumps(result, indent=2, default=str))

        if any(w in q_lower for w in ["missing logic", "open end", "open start", "no predecessor", "no successor"]):
            result = self._tools.check_logic_health()
            extra_context.append("Logic Health:\n" + json.dumps(result, indent=2, default=str))

        if any(w in q_lower for w in ["resource", "crew", "overalloc", "assigned"]):
            result = self._tools.get_resource_loading()
            extra_context.append("Resource Loading:\n" + json.dumps(result, indent=2, default=str))

        if any(w in q_lower for w in ["wbs", "area", "zone", "section", "phase"]):
            result = self._tools.get_wbs_summary()
            extra_context.append("WBS Summary:\n" + json.dumps(result, indent=2, default=str))

        if any(w in q_lower for w in ["negative float", "behind schedule", "delayed", "late"]):
            result = self._tools.find_activities(max_float=-0.01, limit=20)
            extra_context.append("Negative Float Activities:\n" + json.dumps(result, indent=2, default=str))

        if any(w in q_lower for w in ["what if", "what happens", "delay", "slip", "impact"]):
            # Try to extract activity ID and delay from question
            pass  # handled by tool call parsing below

        # Look for activity ID references in the question
        for a in self._tools.schedule.activities:
            if a.activity_id in question:
                result = self._tools.get_activity(a.activity_id)
                extra_context.append("Activity " + a.activity_id + " Details:\n" + json.dumps(result, indent=2, default=str))
                # Also get driving path
                dp = self._tools.get_driving_path(a.activity_id)
                if dp.get("driving_path"):
                    extra_context.append("Driving Path to " + a.activity_id + ":\n" + json.dumps(dp, indent=2, default=str))
                break

        if extra_context:
            return question + "\n\n--- AUTO-RETRIEVED DATA ---\n" + "\n\n".join(extra_context)
        return question

    def _try_tool_call(self, response):
        """Check if the AI response contains a tool call request."""
        if "TOOL_CALL:" not in response:
            return None

        try:
            # Extract tool call from response
            idx = response.index("TOOL_CALL:")
            call_str = response[idx + 10:].strip()
            # Try to parse as tool_name(args)
            if "(" in call_str:
                tool_name = call_str[:call_str.index("(")].strip()
                args_str = call_str[call_str.index("(") + 1:call_str.rindex(")")]
                # Simple arg parsing
                kwargs = {}
                if args_str.strip():
                    for part in args_str.split(","):
                        if "=" in part:
                            k, v = part.split("=", 1)
                            k = k.strip().strip('"').strip("'")
                            v = v.strip().strip('"').strip("'")
                            try:
                                v = float(v)
                            except ValueError:
                                pass
                            kwargs[k] = v
                from agent.tools import dispatch_tool
                return dispatch_tool(self._tools, tool_name, **kwargs)
        except Exception:
            pass
        return None


# ── Summary Builder ──────────────────────────────────────────────────

def _build_summary(schedule, dcma, risk):
    """Build a concise summary for the AI context."""
    parts = []

    # Project
    s = schedule.summary()
    c = len([a for a in schedule.activities if a.status == ActivityStatus.COMPLETED])
    p = len([a for a in schedule.activities if a.status == ActivityStatus.IN_PROGRESS])
    n = len([a for a in schedule.activities if a.status == ActivityStatus.NOT_STARTED])
    dd = schedule.project.data_date.strftime("%Y-%m-%d") if schedule.project.data_date else "N/A"
    st = schedule.project.start_date.strftime("%Y-%m-%d") if schedule.project.start_date else "N/A"
    fi = schedule.project.finish_date.strftime("%Y-%m-%d") if schedule.project.finish_date else "N/A"
    parts.append(
        "=== PROJECT ===\n"
        "Name: " + str(schedule.project.name) + "\n"
        "Source: " + str(schedule.project.source_file) + "\n"
        "Format: " + str(schedule.project.source_format) + "\n"
        "Data Date: " + dd + "\n"
        "Start: " + st + " | Finish: " + fi + "\n"
        "Activities: " + str(s["total_activities"]) +
        " | Rels: " + str(s["total_relationships"]) +
        " | Resources: " + str(s["total_resources"]) + "\n"
        "Done=" + str(c) + " Active=" + str(p) + " Pending=" + str(n)
    )

    # DCMA
    if dcma:
        lines = ["=== DCMA (" + str(dcma.passed_count) + "/" + str(len(dcma.checks)) + " Grade " + dcma.grade + ") ==="]
        for ch in dcma.checks:
            st_ch = "PASS" if ch.passed else "FAIL"
            lines.append("#" + str(ch.check_number) + " " + ch.name + ": " + st_ch + " " + str(ch.metric_value) + ch.unit + " " + ch.detail)
        parts.append("\n".join(lines))

    # Risk
    if risk:
        parts.append(
            "=== RISK (" + risk.risk_level + ") ===\n"
            "Critical: " + str(risk.critical_count) +
            " | Near-Crit: " + str(risk.near_critical_count) +
            " | Neg Float: " + str(risk.negative_float_count) + "\n"
            "BEI: " + str(round(risk.bei, 3)) +
            " | CPLI: " + str(round(risk.cpli, 3))
        )

    return "\n\n".join(parts)


# ── API Calls ────────────────────────────────────────────────────────

def _call_gemini(question, summary, history, config):
    import urllib.request
    import urllib.error

    key = config.gemini_api_key
    if not key:
        return ("Gemini API key not set.\n"
                "  Set: GEMINI_API_KEY=your-key\n"
                "  Free: https://aistudio.google.com/apikey")

    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           + config.gemini_model + ":generateContent?key=" + key)

    # Build tool descriptions string
    tool_desc = "\n".join("- " + k + ": " + v for k, v in TOOL_DESCRIPTIONS.items())
    system = SYSTEM_PROMPT + tool_desc

    contents = [
        {"role": "user", "parts": [{"text": system + "\n\n" + summary}]},
        {"role": "model", "parts": [{"text": "Schedule loaded. I have tool access to query all " + str(len(TOOL_DESCRIPTIONS)) + " analysis functions. Ready for questions."}]},
    ]
    for m in history[:-1]:
        role = "user" if m["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})
    contents.append({"role": "user", "parts": [{"text": question}]})

    payload = {
        "contents": contents,
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 4096},
    }

    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=90) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        candidates = result.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            if parts:
                return parts[0].get("text", "No response.")
        return "No response from Gemini."
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")[:300] if e.fp else ""
        return "Gemini error (" + str(e.code) + "): " + body
    except Exception as e:
        return "Error: " + str(e)


def _call_claude(question, summary, history, config):
    import urllib.request
    import urllib.error

    key = config.claude_api_key
    if not key:
        return ("Claude API key not set.\n"
                "  Set: ANTHROPIC_API_KEY=your-key\n"
                "  Get: https://console.anthropic.com/")

    tool_desc = "\n".join("- " + k + ": " + v for k, v in TOOL_DESCRIPTIONS.items())
    system = SYSTEM_PROMPT + tool_desc

    msgs = [
        {"role": "user", "content": "Schedule data:\n\n" + summary + "\n\nReady."},
        {"role": "assistant", "content": "Schedule loaded with tool access. Ready for questions."},
    ]
    for m in history[:-1]:
        msgs.append({"role": m["role"], "content": m["content"]})
    msgs.append({"role": "user", "content": question})

    payload = {
        "model": config.claude_model,
        "max_tokens": 4096,
        "system": system,
        "messages": msgs,
    }

    try:
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-api-key": key,
                      "anthropic-version": "2023-06-01"}, method="POST")
        with urllib.request.urlopen(req, timeout=90) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        content = result.get("content", [])
        if content:
            return content[0].get("text", "No response.")
        return "No response from Claude."
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")[:300] if e.fp else ""
        return "Claude error (" + str(e.code) + "): " + body
    except Exception as e:
        return "Error: " + str(e)
