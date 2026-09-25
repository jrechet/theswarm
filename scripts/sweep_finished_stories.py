"""Close the stories whose sub-tasks are all done — the ones a merge never closed.

Since #229 the TechLead closes a story when a merge finishes it. Stories
finished before that stay open "in-progress" (on concert-tour-app on
2026-09-25: #344 and a dozen older ones). This lists them, and closes them
with --apply, through the same `techlead.finished_stories` / `close_stories`
the merge uses.

    uv run python scripts/sweep_finished_stories.py --repo jrechet/concert-tour-app
    uv run python scripts/sweep_finished_stories.py --repo jrechet/concert-tour-app --apply
"""

from __future__ import annotations

import argparse
import asyncio
import sys


async def sweep(repo: str, *, apply: bool, client=None) -> list[int]:
    """The finished stories still open; closed too when `apply`."""
    from theswarm.agents.techlead import close_stories, finished_stories

    if client is None:
        from theswarm.tools.github import GitHubClient

        client = GitHubClient(repo_name=repo)
    finished = await finished_stories(client)
    still_open = []
    for story, children in finished:
        issue = await client.get_issue(story)
        if issue is not None and issue.get("state") != "closed":
            still_open.append((story, children))
            print(f"#{story}: every sub-task done ({', '.join(f'#{n}' for n in children)})")
    if not still_open:
        print("No finished story is still open.")
        return []
    if not apply:
        print(f"\n{len(still_open)} story(ies) to close — run again with --apply.")
        return [story for story, _ in still_open]
    closed = await close_stories(client, still_open)
    print(f"\nClosed {len(closed)} story(ies): {', '.join(f'#{n}' for n in closed)}")
    return closed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--apply", action="store_true", help="close them (default: list only)")
    args = parser.parse_args()
    asyncio.run(sweep(args.repo, apply=args.apply))
    return 0


if __name__ == "__main__":
    sys.exit(main())
