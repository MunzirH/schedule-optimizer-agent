"""
Interactive chat interface for the Schedule AI Agent.

Usage:
    from agent.chat import run_chat
    run_chat(schedule, dcma_report, risk_report, provider="gemini")
"""

from agent.ai_agent import ScheduleAgent, AgentConfig


def run_chat(schedule, dcma_report=None, risk_report=None, provider="gemini"):
    """Run interactive chat session."""

    config = AgentConfig(provider=provider)
    agent = ScheduleAgent(config)
    agent.load_schedule(schedule, dcma_report, risk_report)

    status = agent.get_api_status()

    print(f"\n{'=' * 60}")
    print(f"  SCHEDULE AI AGENT")
    print(f"{'=' * 60}")
    print(f"  Provider:  {status['provider']}")
    print(f"  API Key:   {'configured' if status.get(f'{provider}_configured') else 'NOT SET'}")
    print(f"  Schedule:  {'loaded' if status['schedule_loaded'] else 'not loaded'}")
    print(f"")

    if not status.get(f"{provider}_configured"):
        if provider == "gemini":
            print("  To use the AI agent, set your Gemini API key:")
            print("    Windows:  set GEMINI_API_KEY=your-key-here")
            print("    Linux:    export GEMINI_API_KEY=your-key-here")
            print("    Free key: https://aistudio.google.com/apikey")
        else:
            print("  To use the AI agent, set your Claude API key:")
            print("    Windows:  set ANTHROPIC_API_KEY=your-key-here")
            print("    Linux:    export ANTHROPIC_API_KEY=your-key-here")
            print("    Get key:  https://console.anthropic.com/")
        print()

    print("  Ask questions about your schedule. Type 'quit' to exit.")
    print("  Example questions:")
    print("    - What are the top 5 risks on this project?")
    print("    - Why do we have so much negative float?")
    print("    - Summarize the DCMA results for the owner's meeting")
    print("    - Which WBS areas need immediate attention?")
    print("    - What should we do about the resource conflicts?")
    print(f"{'=' * 60}\n")

    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nChat ended.")
            break

        if not question:
            continue

        if question.lower() in ("quit", "exit", "q", "bye"):
            print("\nChat ended. Good luck with the project!")
            break

        print("\nThinking...\n")
        response = agent.ask(question)
        print(f"Agent: {response}\n")
