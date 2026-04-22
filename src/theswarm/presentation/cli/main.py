"""Unified CLI entry point: theswarm [command].

This is the single entry point for TheSwarm. All commands route through here.
Default (no command) starts the full server with Mattermost, GitHub, and web dashboard.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="theswarm",
        description="TheSwarm: Autonomous AI dev team",
    )
    sub = parser.add_subparsers(dest="command")

    # serve (default when no command given)
    serve_p = sub.add_parser("serve", help="Start the full server (web + Mattermost + GitHub)")
    serve_p.add_argument("--host", default="0.0.0.0", help="Bind host")
    serve_p.add_argument("--port", type=int, default=8091, help="Bind port")
    serve_p.add_argument("--db", default="", help="SQLite database path")

    # run-cycle (legacy --cycle / --dev-only / --techlead-only)
    rc_p = sub.add_parser("run-cycle", help="Run an agent cycle from CLI")
    rc_p.add_argument("--dev-only", action="store_true", help="Run only the Dev agent")
    rc_p.add_argument("--techlead-only", action="store_true", help="Run only the TechLead agent")
    rc_p.add_argument("--autonomous", "-a", action="store_true",
                       help="Run cycles in a loop until all stories are resolved")
    rc_p.add_argument("--max-cycles", type=int, default=10,
                       help="Max cycles in autonomous mode (default: 10)")

    # dashboard (TUI)
    sub.add_parser("dashboard", help="Open the terminal dashboard")

    # cycle (v2 — run cycle for a registered project)
    cycle_p = sub.add_parser("cycle", help="Run a development cycle for a registered project")
    cycle_p.add_argument("--project", required=True, help="Project ID")
    cycle_p.add_argument("--triggered-by", default="cli", help="Trigger source")
    cycle_p.add_argument("--autonomous", "-a", action="store_true",
                          help="Run cycles until all stories are resolved")
    cycle_p.add_argument("--max-cycles", type=int, default=10,
                          help="Max cycles in autonomous mode (default: 10)")

    # projects
    proj_p = sub.add_parser("projects", help="Manage projects")
    proj_sub = proj_p.add_subparsers(dest="projects_command")

    proj_sub.add_parser("list", help="List all projects")

    add_p = proj_sub.add_parser("add", help="Register a new project")
    add_p.add_argument("project_id", help="Project slug")
    add_p.add_argument("repo", help="Repository (owner/repo)")
    add_p.add_argument("--framework", default="auto", help="Framework")
    add_p.add_argument("--ticket-source", default="github", help="Ticket source")

    rm_p = proj_sub.add_parser("remove", help="Remove a project")
    rm_p.add_argument("project_id", help="Project slug to remove")

    # schedule
    sched_p = sub.add_parser("schedule", help="Manage schedules")
    sched_sub = sched_p.add_subparsers(dest="schedule_command")

    sched_set = sched_sub.add_parser("set", help="Set a cron schedule")
    sched_set.add_argument("project_id", help="Project slug")
    sched_set.add_argument("cron", help="Cron expression (5 fields)")

    sched_disable = sched_sub.add_parser("disable", help="Disable a schedule")
    sched_disable.add_argument("project_id", help="Project slug")

    sched_delete = sched_sub.add_parser("delete", help="Delete a schedule")
    sched_delete.add_argument("project_id", help="Project slug")

    sched_sub.add_parser("list", help="List enabled schedules")

    # agents-doc
    agents_doc_p = sub.add_parser("agents-doc", help="Generate AGENTS.md from agent introspection")
    agents_doc_p.add_argument("-o", "--output", default="", help="Write to file instead of stdout")

    # record-demos
    rd_p = sub.add_parser("record-demos", help="Record Playwright demo videos for all features")
    rd_p.add_argument("--output-dir", default="",
                       help="Output directory (default: ~/.swarm-data/artifacts/feature-demos)")
    rd_p.add_argument("--headed", action="store_true", help="Run browser in headed mode")

    # dev-seed
    seed_p = sub.add_parser(
        "dev-seed", help="Populate the local DB with synthetic demo data (for dashboard dev)"
    )
    seed_p.add_argument("--count", type=int, default=3, help="Number of demo reports to insert")
    seed_p.add_argument("--reset", action="store_true", help="Delete existing seed rows first")
    seed_p.add_argument("--db", default="", help="SQLite database path")

    # seed-self
    ss_p = sub.add_parser(
        "seed-self",
        help="Register TheSwarm as a project and seed one demo per sprint (idempotent)",
    )
    ss_p.add_argument("--db", default="", help="SQLite database path")
    ss_p.add_argument(
        "--video-dir", default="",
        help="Directory holding sprint-*.webm files (default: repo docs/demos)",
    )
    ss_p.add_argument(
        "--artifacts-dir", default="",
        help="Artifact base dir (default: ~/.swarm-data/artifacts)",
    )

    # artifact-gc
    gc_p = sub.add_parser(
        "artifact-gc",
        help="Delete on-disk artifact directories with no matching report row",
    )
    gc_p.add_argument(
        "--artifact-dir", default="",
        help="Artifact base dir (default: ~/.swarm-data/artifacts)",
    )
    gc_p.add_argument("--db", default="", help="SQLite database path")
    gc_p.add_argument(
        "--apply", action="store_true",
        help="Actually delete (default: dry-run)",
    )

    # status
    sub.add_parser("status", help="Show system status")

    # validate
    sub.add_parser("validate", help="Validate startup configuration")

    return parser


async def _init_db(db_path: str = "") -> "aiosqlite.Connection":
    import os
    from theswarm.infrastructure.persistence.sqlite_repos import init_db

    if not db_path:
        data_dir = os.path.expanduser("~/.swarm-data")
        os.makedirs(data_dir, exist_ok=True)
        db_path = os.path.join(data_dir, "theswarm.db")

    return await init_db(db_path)


async def cmd_serve(args: argparse.Namespace) -> None:
    """Start the full TheSwarm server: web dashboard + Mattermost + GitHub."""
    from theswarm.presentation.web.server import start_server
    await start_server(host=args.host, port=args.port, db_path=args.db)


async def cmd_run_cycle(args: argparse.Namespace) -> None:
    """Run a legacy agent cycle (full, dev-only, techlead-only, or autonomous)."""
    from theswarm.config import CycleConfig
    from theswarm.cycle import run_autonomous, run_daily_cycle, run_dev_only, run_techlead_only

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    config = CycleConfig.from_env()

    if not config.is_real_mode:
        print("Running in STUB mode (no SWARM_GITHUB_REPO set)")
        print("Set SWARM_GITHUB_REPO=owner/repo to run for real.\n")

    if args.dev_only:
        if not config.is_real_mode:
            print("ERROR: --dev-only requires SWARM_GITHUB_REPO")
            sys.exit(1)
        print(f"Mode: DEV ONLY — repo: {config.github_repo}")
        result = await run_dev_only(config)
        print(f"\nDone. Total cost: ${result['cost_usd']:.2f}")
    elif args.techlead_only:
        if not config.is_real_mode:
            print("ERROR: --techlead-only requires SWARM_GITHUB_REPO")
            sys.exit(1)
        print(f"Mode: TECHLEAD ONLY — repo: {config.github_repo}")
        result = await run_techlead_only(config)
        print(f"\nDone. Total cost: ${result['cost_usd']:.2f}")
    elif args.autonomous:
        if not config.is_real_mode:
            print("ERROR: --autonomous requires SWARM_GITHUB_REPO")
            sys.exit(1)
        print(f"Mode: AUTONOMOUS — repo: {config.github_repo}")
        result = await run_autonomous(config, max_cycles=args.max_cycles)
        print(f"\nDone. Cycles: {result['cycles_run']}, "
              f"Total cost: ${result['total_cost_usd']:.2f}, "
              f"Project done: {result['project_done']}")
    else:
        if not config.is_real_mode:
            print("ERROR: run-cycle requires SWARM_GITHUB_REPO")
            sys.exit(1)
        print(f"Mode: DAILY CYCLE — repo: {config.github_repo}")
        result = await run_daily_cycle(config)
        print(f"\nDone. Total cost: ${result['cost_usd']:.2f}")


async def cmd_dashboard(args: argparse.Namespace) -> None:
    from theswarm.application.events.bus import EventBus
    from theswarm.application.queries.get_dashboard import GetDashboardQuery
    from theswarm.application.queries.list_projects import ListProjectsQuery
    from theswarm.infrastructure.persistence.sqlite_repos import (
        SQLiteCycleRepository,
        SQLiteProjectRepository,
    )
    from theswarm.presentation.tui.app import SwarmApp

    conn = await _init_db()
    project_repo = SQLiteProjectRepository(conn)
    cycle_repo = SQLiteCycleRepository(conn)
    bus = EventBus()

    dashboard = await GetDashboardQuery(project_repo, cycle_repo).execute()
    projects = await ListProjectsQuery(project_repo).execute()

    app = SwarmApp(event_bus=bus, dashboard=dashboard, projects=projects)
    await app.run_async()


async def cmd_cycle(args: argparse.Namespace) -> None:
    from theswarm.application.commands.run_cycle import RunCycleCommand, RunCycleHandler
    from theswarm.application.events.bus import EventBus
    from theswarm.infrastructure.persistence.sqlite_repos import (
        SQLiteCycleRepository,
        SQLiteProjectRepository,
    )

    conn = await _init_db()
    project_repo = SQLiteProjectRepository(conn)
    cycle_repo = SQLiteCycleRepository(conn)
    bus = EventBus()

    handler = RunCycleHandler(project_repo, cycle_repo, bus)
    try:
        cycle_id = await handler.handle(
            RunCycleCommand(project_id=args.project, triggered_by=args.triggered_by),
        )
        print(f"Cycle started: {cycle_id}")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


async def cmd_projects(args: argparse.Namespace) -> None:
    from theswarm.application.commands.create_project import (
        CreateProjectCommand,
        CreateProjectHandler,
    )
    from theswarm.application.commands.delete_project import (
        DeleteProjectCommand,
        DeleteProjectHandler,
    )
    from theswarm.application.queries.list_projects import ListProjectsQuery
    from theswarm.application.services.role_assignment_service import (
        RoleAssignmentService,
    )
    from theswarm.infrastructure.agents.role_assignment_repo import (
        SQLiteRoleAssignmentRepository,
    )
    from theswarm.infrastructure.persistence.sqlite_repos import SQLiteProjectRepository

    conn = await _init_db()
    project_repo = SQLiteProjectRepository(conn)

    if args.projects_command == "list" or args.projects_command is None:
        projects = await ListProjectsQuery(project_repo).execute()
        if not projects:
            print("No projects registered.")
            return
        for p in projects:
            print(f"  {p.id:<20} {p.repo:<30} {p.framework:<10} {p.ticket_source}")

    elif args.projects_command == "add":
        role_repo = SQLiteRoleAssignmentRepository(conn)
        role_service = RoleAssignmentService(role_repo)
        handler = CreateProjectHandler(project_repo, role_service=role_service)
        try:
            project = await handler.handle(
                CreateProjectCommand(
                    project_id=args.project_id,
                    repo=args.repo,
                    framework=args.framework,
                    ticket_source=args.ticket_source,
                ),
            )
            print(f"Added project: {project.id} ({project.repo})")
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.projects_command == "remove":
        handler = DeleteProjectHandler(project_repo)
        try:
            await handler.handle(DeleteProjectCommand(project_id=args.project_id))
            print(f"Removed project: {args.project_id}")
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)


async def cmd_schedule(args: argparse.Namespace) -> None:
    from theswarm.application.commands.manage_schedule import (
        DeleteScheduleCommand,
        DeleteScheduleHandler,
        DisableScheduleCommand,
        DisableScheduleHandler,
        SetScheduleCommand,
        SetScheduleHandler,
    )
    from theswarm.application.queries.get_schedule import (
        ListEnabledSchedulesQuery,
    )
    from theswarm.infrastructure.persistence.sqlite_repos import (
        SQLiteProjectRepository,
        SQLiteScheduleRepository,
    )

    conn = await _init_db()
    project_repo = SQLiteProjectRepository(conn)
    schedule_repo = SQLiteScheduleRepository(conn)

    if args.schedule_command == "set":
        handler = SetScheduleHandler(project_repo, schedule_repo)
        try:
            schedule = await handler.handle(
                SetScheduleCommand(project_id=args.project_id, cron=args.cron),
            )
            print(f"Schedule set: {args.project_id} -> {schedule.cron}")
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.schedule_command == "disable":
        handler = DisableScheduleHandler(schedule_repo)
        try:
            await handler.handle(DisableScheduleCommand(project_id=args.project_id))
            print(f"Schedule disabled: {args.project_id}")
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.schedule_command == "delete":
        handler = DeleteScheduleHandler(schedule_repo)
        try:
            await handler.handle(DeleteScheduleCommand(project_id=args.project_id))
            print(f"Schedule deleted: {args.project_id}")
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.schedule_command == "list" or args.schedule_command is None:
        query = ListEnabledSchedulesQuery(schedule_repo)
        schedules = await query.execute()
        if not schedules:
            print("No enabled schedules.")
            return
        for s in schedules:
            print(f"  {s.project_id:<20} {s.cron:<20} last_run={s.last_run or 'never'}")


async def cmd_validate(args: argparse.Namespace) -> None:
    from theswarm.application.services.startup_validator import StartupValidator

    validator = StartupValidator()
    result = validator.validate(require_api_keys=True)

    if result.warnings:
        for w in result.warnings:
            print(f"  WARNING: {w}")
    if result.errors:
        for e in result.errors:
            print(f"  ERROR: {e}")
        sys.exit(1)
    else:
        print("Validation passed.")


async def cmd_agents_doc(args: argparse.Namespace) -> None:
    """Generate AGENTS.md from agent module introspection."""
    from theswarm.tools.agents_md import generate_agents_md

    content = generate_agents_md()
    if args.output:
        with open(args.output, "w") as f:
            f.write(content)
        print(f"Wrote AGENTS.md to {args.output}")
    else:
        print(content)


async def cmd_record_demos(args: argparse.Namespace) -> None:
    """Record Playwright demo videos for all platform features."""
    import os
    import shutil
    import subprocess
    import tempfile

    output_dir = args.output_dir
    if not output_dir:
        output_dir = os.path.join(os.path.expanduser("~"), ".swarm-data", "artifacts", "feature-demos")
    os.makedirs(output_dir, exist_ok=True)

    # Run E2E tests with video recording into a temp dir
    with tempfile.TemporaryDirectory() as tmp:
        video_dir = os.path.join(tmp, "videos")
        cmd = [
            sys.executable, "-m", "pytest",
            "tests/e2e/test_features_e2e.py",
            "-v", "--video=on",
            f"--video-dir={video_dir}",
        ]
        if args.headed:
            cmd.append("--headed")

        print(f"Recording demos → {output_dir}")
        print(f"Running: {' '.join(cmd)}\n")

        result = subprocess.run(cmd, cwd=os.getcwd())

        if result.returncode != 0:
            print(f"\nTests exited with code {result.returncode} (videos may still be usable)")

        # Copy .webm files to output dir
        if os.path.isdir(video_dir):
            videos = [f for f in os.listdir(video_dir) if f.endswith(".webm")]
            for v in sorted(videos):
                src = os.path.join(video_dir, v)
                dst = os.path.join(output_dir, v)
                shutil.copy2(src, dst)
                print(f"  Saved: {dst}")
            print(f"\n{len(videos)} video(s) saved to {output_dir}")
        else:
            # Playwright may nest videos under test-results/
            found = 0
            for root, _dirs, files in os.walk(tmp):
                for f in files:
                    if f.endswith(".webm"):
                        src = os.path.join(root, f)
                        dst = os.path.join(output_dir, f)
                        shutil.copy2(src, dst)
                        print(f"  Saved: {dst}")
                        found += 1
            if found:
                print(f"\n{found} video(s) saved to {output_dir}")
            else:
                print("\nNo video files found. Ensure playwright is installed: uv run playwright install")

    print(f"\nView demos at: http://localhost:8091/features/")


async def cmd_dev_seed(args: argparse.Namespace) -> None:
    """Populate the local DB with synthetic demo reports."""
    from theswarm.application.services.dev_seed import seed_dev_data
    from theswarm.infrastructure.persistence.sqlite_repos import SQLiteProjectRepository

    conn = await _init_db(args.db)
    project_repo = SQLiteProjectRepository(conn)

    result = await seed_dev_data(
        conn, project_repo, count=args.count, reset=args.reset,
    )
    if result.project_created:
        print("Created seed project: dev-seed-demo")
    if result.reports_deleted:
        print(f"Deleted {result.reports_deleted} existing seed rows")
    print(f"Inserted {result.reports_inserted} demo reports")
    print("Open http://localhost:8091/demos/ after `theswarm serve`")


async def cmd_seed_self(args: argparse.Namespace) -> None:
    """Register TheSwarm project and seed one DemoReport per sprint (idempotent)."""
    import os
    from pathlib import Path

    from theswarm.application.services.self_seed import seed_self
    from theswarm.infrastructure.persistence.sqlite_repos import (
        SQLiteProjectRepository,
    )
    from theswarm.infrastructure.recording.report_repo import SQLiteReportRepository

    conn = await _init_db(args.db)
    project_repo = SQLiteProjectRepository(conn)
    report_repo = SQLiteReportRepository(conn)

    if args.video_dir:
        video_source_dir: Path | None = Path(args.video_dir).expanduser()
    else:
        # In-container default: docs/ lives at /app/docs; in-repo default: ./docs/demos.
        container_dir = Path("/app/docs/demos")
        repo_dir = Path(__file__).resolve().parents[4] / "docs" / "demos"
        video_source_dir = container_dir if container_dir.is_dir() else repo_dir

    if args.artifacts_dir:
        artifacts_base_dir: Path | None = Path(args.artifacts_dir).expanduser()
    else:
        artifacts_base_dir = Path(
            os.path.expanduser("~/.swarm-data/artifacts"),
        )
    artifacts_base_dir.mkdir(parents=True, exist_ok=True)

    result = await seed_self(
        project_repo,
        report_repo,
        video_source_dir=video_source_dir,
        artifacts_base_dir=artifacts_base_dir,
    )

    if result.project_created:
        print("Created project: theswarm")
    elif result.project_updated:
        print("Updated project: theswarm")
    else:
        print("Project theswarm already up to date")

    print(f"Reports saved: {len(result.reports_saved)}")
    for rid in result.reports_saved:
        print(f"  - {rid}")

    if result.videos_attached:
        print(f"Videos attached: {len(result.videos_attached)}")
        for v in result.videos_attached:
            print(f"  - {v}")
    else:
        print("No sprint videos found (expected sprint-*.webm in video-dir)")


async def cmd_artifact_gc(args: argparse.Namespace) -> None:
    """Remove on-disk artifact dirs that no longer match any report row."""
    import os

    from theswarm.application.services.artifact_gc import gc_artifacts

    artifact_dir = args.artifact_dir or os.path.join(
        os.path.expanduser("~"), ".swarm-data", "artifacts",
    )
    conn = await _init_db(args.db)

    result = await gc_artifacts(conn, artifact_dir, dry_run=not args.apply)

    mode = "DELETED" if result.deleted else "DRY-RUN"
    print(f"[{mode}] Artifact GC — base: {artifact_dir}")
    print(f"  Scanned dirs:      {result.scanned_dirs}")
    print(f"  Live cycle IDs:    {result.live_cycle_ids}")
    print(f"  Orphaned dirs:     {len(result.orphaned_dirs)}")
    print(f"  Bytes reclaimed:   {result.bytes_reclaimed:,}")
    for name in result.orphaned_dirs:
        print(f"    - {name}")
    if not result.deleted and result.orphaned_dirs:
        print("\nRun again with --apply to actually delete.")


async def cmd_status(args: argparse.Namespace) -> None:
    from theswarm.application.queries.get_dashboard import GetDashboardQuery
    from theswarm.infrastructure.persistence.sqlite_repos import (
        SQLiteCycleRepository,
        SQLiteProjectRepository,
    )

    conn = await _init_db()
    project_repo = SQLiteProjectRepository(conn)
    cycle_repo = SQLiteCycleRepository(conn)

    dashboard = await GetDashboardQuery(project_repo, cycle_repo).execute()
    print(f"Projects:      {len(dashboard.projects)}")
    print(f"Active cycles: {len(dashboard.active_cycles)}")
    print(f"Cost today:    ${dashboard.total_cost_today:.2f}")


def main(argv: list[str] | None = None) -> None:
    parser = create_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    cmd_map = {
        "serve": cmd_serve,
        "run-cycle": cmd_run_cycle,
        "dashboard": cmd_dashboard,
        "cycle": cmd_cycle,
        "projects": cmd_projects,
        "schedule": cmd_schedule,
        "agents-doc": cmd_agents_doc,
        "record-demos": cmd_record_demos,
        "validate": cmd_validate,
        "status": cmd_status,
        "dev-seed": cmd_dev_seed,
        "seed-self": cmd_seed_self,
        "artifact-gc": cmd_artifact_gc,
    }

    handler = cmd_map.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    asyncio.run(handler(args))


if __name__ == "__main__":
    main()
