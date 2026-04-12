"""CLI entry point: theswarm [command]."""

from __future__ import annotations

import argparse
import asyncio
import sys


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="theswarm",
        description="TheSwarm: Autonomous AI dev team",
    )
    sub = parser.add_subparsers(dest="command")

    # serve
    serve_p = sub.add_parser("serve", help="Start the web dashboard")
    serve_p.add_argument("--host", default="0.0.0.0", help="Bind host")
    serve_p.add_argument("--port", type=int, default=8091, help="Bind port")
    serve_p.add_argument("--db", default="", help="SQLite database path")

    # dashboard (TUI)
    sub.add_parser("dashboard", help="Open the terminal dashboard")

    # cycle
    cycle_p = sub.add_parser("cycle", help="Run a development cycle")
    cycle_p.add_argument("--project", required=True, help="Project ID")
    cycle_p.add_argument("--triggered-by", default="cli", help="Trigger source")

    # projects
    proj_p = sub.add_parser("projects", help="Manage projects")
    proj_sub = proj_p.add_subparsers(dest="projects_command")

    list_p = proj_sub.add_parser("list", help="List all projects")

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

    # status
    status_p = sub.add_parser("status", help="Show system status")

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
    import uvicorn
    from theswarm.application.events.bus import EventBus
    from theswarm.infrastructure.persistence.sqlite_repos import (
        SQLiteCycleRepository,
        SQLiteProjectRepository,
    )
    from theswarm.presentation.web.app import create_web_app

    conn = await _init_db(args.db)
    project_repo = SQLiteProjectRepository(conn)
    cycle_repo = SQLiteCycleRepository(conn)
    bus = EventBus()

    app = create_web_app(project_repo, cycle_repo, bus)
    config = uvicorn.Config(app, host=args.host, port=args.port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


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
        handler = CreateProjectHandler(project_repo)
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
            print(f"Schedule set: {args.project_id} → {schedule.cron}")
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
        "dashboard": cmd_dashboard,
        "cycle": cmd_cycle,
        "projects": cmd_projects,
        "schedule": cmd_schedule,
        "validate": cmd_validate,
        "status": cmd_status,
    }

    handler = cmd_map.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    asyncio.run(handler(args))


if __name__ == "__main__":
    main()
