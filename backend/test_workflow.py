"""
test_workflow.py: Dry-run test for the multi-agent workflow.
Executes the full pipeline in terminal: User Input → Lead → Workers → Critic → Synthesizer.

Usage:
    python test_workflow.py
    python test_workflow.py --domain legal_squad --goal "Draft an NDA agreement"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from loguru import logger

# Configure loguru for clean terminal output
logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | <cyan>{message}</cyan>")


async def run_dry_test(domain: str, goal: str):
    """Execute a full workflow end-to-end in the terminal."""

    from config_loader import config_loader
    from memory import memx
    from orchestrator import WorkflowOrchestrator
    from router import model_router
    from schemas import DomainType
    from taskbox import TaskBox

    print("\n" + "=" * 70)
    print("  🧪 AI Agency Platform — Dry Run Test")
    print("=" * 70)
    print(f"  Domain: {domain}")
    print(f"  Goal:   {goal}")
    print("=" * 70 + "\n")

    # ── Initialize services ──
    print("📦 Initializing services...")
    taskbox = TaskBox()
    await taskbox.initialize()
    print("  ✅ SQLite Taskbox initialized (WAL mode)")

    redis_ok = await memx.connect()
    print(f"  {'✅' if redis_ok else '⚠️'} Redis memX {'connected' if redis_ok else '(fallback mode)'}")

    proxy_ok = await model_router.check_proxy()
    print(f"  {'✅' if proxy_ok else '⚠️'} Antigravity Proxy {'connected' if proxy_ok else 'NOT reachable'}")

    ollama_ok = await model_router.check_ollama()
    print(f"  {'✅' if ollama_ok else '⚠️'} Ollama {'connected' if ollama_ok else 'not running (optional fallback)'}")

    if not proxy_ok and not ollama_ok:
        print("\n❌ No LLM backend available! Please start one:")
        print("   Proxy:  antigravity-claude-proxy start   (recommended)")
        print("   Ollama: ollama serve && ollama pull gemma4:e2b")
        await taskbox.close()
        return

    if proxy_ok:
        print("  🚀 Using Antigravity Proxy as LLM backend")
    else:
        print("  🏠 Using Ollama as LLM backend")

    # List available models
    models = await model_router.list_local_models()
    print(f"  📋 Available models: {models[:6]}")

    # Load configs
    config_loader.load_user_preferences()
    user_prefs = config_loader.get_user_preferences()
    print(f"  📄 User preferences loaded ({len(user_prefs)} sections)")

    domain_config = config_loader.load_domain_config(DomainType(domain))
    print(f"  🏗️ Domain: {domain} ({len(domain_config.team_roles)} agents)")
    print(f"  📋 Workflow: {' → '.join(domain_config.workflow)}")

    # ── Run workflow ──
    print("\n" + "-" * 70)
    print("  🚀 Starting Workflow")
    print("-" * 70 + "\n")

    event_count = 0

    async def terminal_event_handler(event: dict):
        nonlocal event_count
        event_count += 1
        etype = event.get("type", "status")
        agent = event.get("agent", "System")
        message = event.get("message", "")

        # Color-code by event type
        icons = {
            "status": "📡",
            "task_complete": "✅",
            "review": "🔍",
            "final_output": "🎯",
            "workflow_complete": "🏁",
            "error": "❌",
        }
        icon = icons.get(etype, "📌")

        print(f"  {icon} [{agent:>20}] {message}")

        # Show preview for task completions
        if event.get("preview"):
            preview = event["preview"][:150].replace("\n", " ")
            print(f"     └─ Preview: {preview}...")

        # Show verdict for reviews
        if event.get("verdict"):
            verdict = event["verdict"]
            score = event.get("score", "N/A")
            print(f"     └─ Verdict: {verdict} (score: {score})")

        # Show final output
        if etype == "final_output" and event.get("content"):
            print(f"\n{'═' * 70}")
            print("  🎯 FINAL OUTPUT")
            print(f"{'═' * 70}")
            print(event["content"][:2000])
            print(f"{'═' * 70}\n")

    orchestrator = WorkflowOrchestrator("test_session", DomainType(domain), taskbox)
    orchestrator.on_event(terminal_event_handler)

    result = await orchestrator.run(goal, user_prefs)

    # ── Summary ──
    print("\n" + "-" * 70)
    print("  📊 Run Summary")
    print("-" * 70)
    print(f"  Status:         {result.get('status', 'unknown')}")
    print(f"  Total Tasks:    {result.get('task_count', 0)}")
    print(f"  Approved Tasks: {result.get('approved_count', 0)}")
    print(f"  Total Events:   {event_count}")

    # Show DB state
    all_tasks = await taskbox.get_tasks_by_session("test_session")
    summary = await taskbox.get_session_summary("test_session")
    print(f"  DB Summary:     {json.dumps(summary)}")

    # Show audit log count
    audit = await taskbox.get_audit_log("test_session")
    print(f"  Audit Entries:  {len(audit)}")

    print("-" * 70)
    print("  ✅ Dry run complete!")
    print("-" * 70 + "\n")

    # Cleanup
    await taskbox.close()
    await memx.disconnect()


def main():
    parser = argparse.ArgumentParser(description="AI Agency Platform — Dry Run Test")
    parser.add_argument("--domain", default="youtube_creator", choices=["youtube_creator", "legal_squad"],
                        help="Domain to test (default: youtube_creator)")
    parser.add_argument("--goal", default="Create a 10-minute tech review video about the latest AI coding tools for developers",
                        help="User goal to execute")
    args = parser.parse_args()

    asyncio.run(run_dry_test(args.domain, args.goal))


if __name__ == "__main__":
    main()
