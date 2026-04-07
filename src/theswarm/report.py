"""Zero-click HTML report generator.

Generates a self-contained HTML report from a cycle result dict. The report
shows each PR as a card with status, diff summary, and approve/comment actions.
Also generates weekly summaries from cycle history.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)


def generate_cycle_report(result: dict, base_url: str = "") -> str:
    """Generate an HTML report from a cycle result dict.

    Args:
        result: The dict returned by run_daily_cycle().
        base_url: External URL prefix for action endpoints (e.g. https://bots.jrec.fr/swarm).

    Returns:
        Self-contained HTML string.
    """
    date = result.get("date", datetime.now().strftime("%Y-%m-%d"))
    cost = result.get("cost_usd", 0.0)
    prs = result.get("prs", [])
    reviews = result.get("reviews", [])
    demo_report = result.get("demo_report") or {}
    daily_report = result.get("daily_report", "")
    tokens = result.get("tokens", 0)

    # Build review lookup: pr_number -> review
    review_map: dict[int, dict] = {}
    for r in reviews:
        review_map[r.get("pr_number", 0)] = r

    # Quality gates from demo report
    gates = demo_report.get("quality_gates", {})
    metrics = demo_report.get("metrics", {})
    overall = demo_report.get("overall_status", "unknown")

    pr_cards = _render_pr_cards(prs, review_map, base_url, date)
    quality_section = _render_quality_gates(gates, metrics, overall)
    cost_section = _render_cost_summary(cost, tokens, len(prs), reviews)

    return _REPORT_TEMPLATE.format(
        date=date,
        overall_status=overall,
        overall_color=_status_color(overall),
        cost_usd=f"{cost:.2f}",
        pr_count=len(prs),
        merged_count=sum(1 for r in reviews if r.get("decision") == "APPROVE"),
        pr_cards=pr_cards,
        quality_section=quality_section,
        cost_section=cost_section,
        daily_report=_escape(daily_report) if daily_report else "<em>No PO report generated.</em>",
    )


def generate_weekly_summary(entries: list[dict]) -> str:
    """Generate a weekly summary HTML from cycle history entries.

    Args:
        entries: List of cycle history dicts (from cycle-history.jsonl), most recent first.

    Returns:
        Self-contained HTML string.
    """
    if not entries:
        return _WEEKLY_EMPTY

    now = datetime.now(timezone.utc)
    week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
    week_end = now.strftime("%Y-%m-%d")

    total_cost = sum(e.get("cost_usd", 0) for e in entries)
    total_prs = sum(e.get("prs_opened", 0) for e in entries)
    total_merged = sum(e.get("prs_merged", 0) for e in entries)
    total_tokens = sum(e.get("tokens", 0) for e in entries)
    cycle_count = len(entries)

    statuses = [e.get("demo_status", "unknown") for e in entries]
    green_count = statuses.count("green")
    yellow_count = statuses.count("yellow")
    red_count = statuses.count("red")

    rows = ""
    for e in entries:
        status = e.get("demo_status", "unknown")
        rows += (
            f"<tr>"
            f"<td>{_escape(e.get('date', ''))}</td>"
            f"<td>{_escape(e.get('repo', ''))}</td>"
            f"<td><span class='badge' style='background:{_status_color(status)}'>{status}</span></td>"
            f"<td>{e.get('prs_opened', 0)}</td>"
            f"<td>{e.get('prs_merged', 0)}</td>"
            f"<td>${e.get('cost_usd', 0):.2f}</td>"
            f"</tr>\n"
        )

    return _WEEKLY_TEMPLATE.format(
        week_start=week_start,
        week_end=week_end,
        cycle_count=cycle_count,
        total_cost=f"{total_cost:.2f}",
        total_prs=total_prs,
        total_merged=total_merged,
        total_tokens=f"{total_tokens:,}",
        green_count=green_count,
        yellow_count=yellow_count,
        red_count=red_count,
        rows=rows,
        avg_cost=f"{total_cost / cycle_count:.2f}" if cycle_count else "0.00",
    )


# ── Internal helpers ─────────────────────────────────────────────────


def _escape(text: str) -> str:
    """HTML-escape a string."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("\n", "<br>")
    )


def _status_color(status: str) -> str:
    return {
        "green": "#00cc88",
        "yellow": "#ffaa00",
        "red": "#ff4466",
        "pass": "#00cc88",
        "fail": "#ff4466",
    }.get(status, "#8888a0")


def _render_pr_cards(prs: list[dict], review_map: dict, base_url: str, date: str) -> str:
    if not prs:
        return '<div class="card"><p style="color:var(--dim)">No PRs opened this cycle.</p></div>'

    cards = ""
    for pr in prs:
        number = pr.get("number", "?")
        url = pr.get("url", "#")
        title = pr.get("title", f"PR #{number}")
        review = review_map.get(number, {})
        decision = review.get("decision", "PENDING")
        summary = review.get("summary", "")
        issues = review.get("issues", [])

        decision_color = {
            "APPROVE": "#00cc88",
            "REQUEST_CHANGES": "#ffaa00",
            "PENDING": "#8888a0",
        }.get(decision, "#8888a0")

        issues_html = ""
        if issues:
            issues_html = "<ul class='issues'>"
            for issue in issues[:5]:
                desc = _escape(issue.get("description", "")[:120])
                issues_html += f"<li>{desc}</li>"
            issues_html += "</ul>"

        # Action form (approve / comment)
        action_html = ""
        if base_url and decision != "APPROVE":
            action_html = f"""
            <div class="actions">
              <form method="POST" action="{base_url}/reports/{date}/approve/{number}" style="display:inline">
                <button type="submit" class="btn btn-approve">Approve &amp; Merge</button>
              </form>
              <form method="POST" action="{base_url}/reports/{date}/comment/{number}" style="display:inline">
                <input type="text" name="comment" placeholder="Leave a comment..." class="comment-input">
                <button type="submit" class="btn btn-comment">Comment</button>
              </form>
            </div>"""

        cards += f"""
        <div class="card pr-card">
          <div class="pr-header">
            <a href="{_escape(url)}" target="_blank" class="pr-link">#{number}</a>
            <span class="pr-title">{_escape(title)}</span>
            <span class="badge" style="background:{decision_color}">{decision}</span>
          </div>
          {f'<p class="review-summary">{_escape(summary)}</p>' if summary else ''}
          {issues_html}
          {action_html}
        </div>"""

    return cards


def _render_quality_gates(gates: dict, metrics: dict, overall: str) -> str:
    if not gates:
        return '<p style="color:var(--dim)">No quality gate data available.</p>'

    rows = ""
    for name, gate in gates.items():
        status = gate.get("status", "unknown")
        color = _status_color(status)
        detail = ""
        if "total" in gate:
            detail = f"{gate.get('passed', 0)}/{gate['total']} passed"
        elif "percent" in gate:
            detail = f"{gate['percent']}%"
        elif "semgrep_high" in gate:
            detail = f"{gate['semgrep_high']} high findings"
        label = name.replace("_", " ").title()
        rows += f"<tr><td>{label}</td><td>{detail}</td><td><span class='badge' style='background:{color}'>{status}</span></td></tr>\n"

    return f"""
    <table class="quality-table">
      <thead><tr><th>Gate</th><th>Detail</th><th>Status</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>"""


def _render_cost_summary(cost: float, tokens: int, pr_count: int, reviews: list) -> str:
    merged = sum(1 for r in reviews if r.get("decision") == "APPROVE")
    cost_per_pr = cost / pr_count if pr_count else 0
    return f"""
    <div class="cost-grid">
      <div class="cost-item">
        <div class="cost-label">Total Cost</div>
        <div class="cost-value">${cost:.2f}</div>
      </div>
      <div class="cost-item">
        <div class="cost-label">Tokens</div>
        <div class="cost-value">{tokens:,}</div>
      </div>
      <div class="cost-item">
        <div class="cost-label">PRs Opened</div>
        <div class="cost-value">{pr_count}</div>
      </div>
      <div class="cost-item">
        <div class="cost-label">PRs Merged</div>
        <div class="cost-value">{merged}</div>
      </div>
      <div class="cost-item">
        <div class="cost-label">Cost/PR</div>
        <div class="cost-value">${cost_per_pr:.2f}</div>
      </div>
    </div>"""


# ── HTML Templates ───────────────────────────────────────────────────

_REPORT_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TheSwarm Report — {date}</title>
<style>
  :root {{
    --bg: #0a0a0f;
    --surface: #12121a;
    --border: #1e1e2e;
    --text: #e0e0e6;
    --dim: #8888a0;
    --accent: #00ccff;
    --green: #00cc88;
    --red: #ff4466;
    --yellow: #ffaa00;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
    background: var(--bg);
    color: var(--text);
    padding: 2rem;
    line-height: 1.6;
    max-width: 900px;
    margin: 0 auto;
  }}
  h1 {{ color: var(--accent); font-size: 1.4rem; margin-bottom: 0.5rem; }}
  h2 {{ color: var(--text); font-size: 1.1rem; margin: 1.5rem 0 0.8rem; }}
  .subtitle {{ color: var(--dim); font-size: 0.9rem; margin-bottom: 1.5rem; }}
  .card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1.2rem;
    margin-bottom: 1rem;
  }}
  .badge {{
    display: inline-block;
    padding: 0.15rem 0.5rem;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--bg);
  }}
  .pr-header {{
    display: flex;
    align-items: center;
    gap: 0.8rem;
    flex-wrap: wrap;
  }}
  .pr-link {{
    color: var(--accent);
    text-decoration: none;
    font-weight: 700;
    font-size: 1.1rem;
  }}
  .pr-link:hover {{ text-decoration: underline; }}
  .pr-title {{ color: var(--text); font-weight: 500; }}
  .review-summary {{ color: var(--dim); font-size: 0.85rem; margin-top: 0.5rem; }}
  .issues {{ color: var(--dim); font-size: 0.8rem; margin: 0.5rem 0 0 1.2rem; }}
  .issues li {{ margin-bottom: 0.2rem; }}
  .actions {{ margin-top: 0.8rem; display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }}
  .btn {{
    padding: 0.4rem 0.8rem;
    border: none;
    border-radius: 4px;
    font-family: inherit;
    font-size: 0.8rem;
    font-weight: 600;
    cursor: pointer;
  }}
  .btn-approve {{ background: var(--green); color: var(--bg); }}
  .btn-approve:hover {{ opacity: 0.9; }}
  .btn-comment {{ background: var(--border); color: var(--text); }}
  .btn-comment:hover {{ background: var(--dim); color: var(--bg); }}
  .comment-input {{
    padding: 0.4rem 0.6rem;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    color: var(--text);
    font-family: inherit;
    font-size: 0.8rem;
    width: 250px;
  }}
  .comment-input:focus {{ outline: 1px solid var(--accent); border-color: var(--accent); }}
  .quality-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.85rem;
  }}
  .quality-table th {{
    text-align: left;
    color: var(--dim);
    padding: 0.4rem 0.8rem;
    border-bottom: 1px solid var(--border);
    text-transform: uppercase;
    font-size: 0.75rem;
    letter-spacing: 0.05em;
  }}
  .quality-table td {{ padding: 0.4rem 0.8rem; border-bottom: 1px solid var(--border); }}
  .cost-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
    gap: 1rem;
  }}
  .cost-item {{ text-align: center; }}
  .cost-label {{ color: var(--dim); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }}
  .cost-value {{ color: var(--green); font-size: 1.3rem; font-weight: 700; margin-top: 0.3rem; }}
  .report-body {{ color: var(--dim); font-size: 0.85rem; }}
  @media (max-width: 600px) {{
    body {{ padding: 1rem; }}
    .comment-input {{ width: 100%; }}
  }}
</style>
</head>
<body>
<h1>TheSwarm Report</h1>
<div class="subtitle">{date} &mdash; <span class="badge" style="background:{overall_color}">{overall_status}</span> &mdash; ${cost_usd} &mdash; {pr_count} PRs ({merged_count} merged)</div>

<h2>Cost &amp; Metrics</h2>
<div class="card">
{cost_section}
</div>

<h2>Pull Requests</h2>
{pr_cards}

<h2>Quality Gates</h2>
<div class="card">
{quality_section}
</div>

<h2>PO Daily Report</h2>
<div class="card report-body">
{daily_report}
</div>

</body>
</html>
"""

_WEEKLY_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TheSwarm Weekly — {week_start} to {week_end}</title>
<style>
  :root {{
    --bg: #0a0a0f; --surface: #12121a; --border: #1e1e2e;
    --text: #e0e0e6; --dim: #8888a0; --accent: #00ccff;
    --green: #00cc88; --red: #ff4466; --yellow: #ffaa00;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'SF Mono', 'Fira Code', monospace;
    background: var(--bg); color: var(--text);
    padding: 2rem; line-height: 1.6; max-width: 900px; margin: 0 auto;
  }}
  h1 {{ color: var(--accent); font-size: 1.4rem; margin-bottom: 0.5rem; }}
  h2 {{ font-size: 1.1rem; margin: 1.5rem 0 0.8rem; }}
  .subtitle {{ color: var(--dim); font-size: 0.9rem; margin-bottom: 1.5rem; }}
  .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 1.2rem; margin-bottom: 1rem; }}
  .badge {{ display: inline-block; padding: 0.15rem 0.5rem; border-radius: 4px; font-size: 0.75rem; font-weight: 600; color: var(--bg); }}
  .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 1rem; text-align: center; }}
  .stat-label {{ color: var(--dim); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }}
  .stat-value {{ font-size: 1.3rem; font-weight: 700; margin-top: 0.3rem; }}
  .stat-cost {{ color: var(--green); }}
  .stat-pr {{ color: var(--accent); }}
  .stat-status {{ color: var(--yellow); }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
  th {{ text-align: left; color: var(--dim); padding: 0.4rem 0.8rem; border-bottom: 1px solid var(--border); text-transform: uppercase; font-size: 0.75rem; letter-spacing: 0.05em; }}
  td {{ padding: 0.4rem 0.8rem; border-bottom: 1px solid var(--border); }}
</style>
</head>
<body>
<h1>TheSwarm Weekly Summary</h1>
<div class="subtitle">{week_start} &mdash; {week_end} &mdash; {cycle_count} cycles</div>

<div class="card">
<div class="stats">
  <div><div class="stat-label">Total Cost</div><div class="stat-value stat-cost">${total_cost}</div></div>
  <div><div class="stat-label">Avg/Cycle</div><div class="stat-value stat-cost">${avg_cost}</div></div>
  <div><div class="stat-label">PRs Opened</div><div class="stat-value stat-pr">{total_prs}</div></div>
  <div><div class="stat-label">PRs Merged</div><div class="stat-value stat-pr">{total_merged}</div></div>
  <div><div class="stat-label">Tokens</div><div class="stat-value">{total_tokens}</div></div>
  <div><div class="stat-label">Cycles</div><div class="stat-value">{cycle_count}</div></div>
</div>
</div>

<h2>Status Distribution</h2>
<div class="card">
<div class="stats">
  <div><div class="stat-label">Green</div><div class="stat-value" style="color:var(--green)">{green_count}</div></div>
  <div><div class="stat-label">Yellow</div><div class="stat-value" style="color:var(--yellow)">{yellow_count}</div></div>
  <div><div class="stat-label">Red</div><div class="stat-value" style="color:var(--red)">{red_count}</div></div>
</div>
</div>

<h2>Cycle History</h2>
<div class="card">
<table>
<thead><tr><th>Date</th><th>Repo</th><th>Status</th><th>PRs</th><th>Merged</th><th>Cost</th></tr></thead>
<tbody>
{rows}
</tbody>
</table>
</div>

</body>
</html>
"""

_WEEKLY_EMPTY = """\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>TheSwarm Weekly</title>
<style>body{font-family:monospace;background:#0a0a0f;color:#8888a0;padding:2rem;}</style>
</head>
<body><h1>No cycle data for this week.</h1></body>
</html>
"""
