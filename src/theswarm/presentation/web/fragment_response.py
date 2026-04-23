"""Fragment-or-page response helper.

Fragments are HTMX partials. When rendered in response to a direct
browser navigation (no HX-Request header) they must be wrapped in the
dark-theme base shell; when rendered in response to an HTMX swap they
must be returned as-is so HTMX can splice them into the target element.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import HTMLResponse


def render_fragment_or_page(
    request: Request,
    fragment_template: str,
    context: dict,
    *,
    page_title: str = "",
) -> HTMLResponse:
    """Return ``fragment_template`` either bare or wrapped in base.html.

    Detection is done via the ``HX-Request`` header that HTMX sends on every
    XHR. Absent header → full browser visit → wrap in ``_fragment_page.html``.
    """
    templates = request.app.state.templates
    is_htmx = request.headers.get("hx-request", "").lower() == "true"

    if is_htmx:
        return templates.TemplateResponse(fragment_template, context)

    wrapper_ctx = {
        **context,
        "fragment": fragment_template,
        "page_title": page_title,
    }
    return templates.TemplateResponse("_fragment_page.html", wrapper_ctx)
