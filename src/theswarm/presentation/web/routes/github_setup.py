"""GitHub App creation via the manifest flow — two clicks, zero copy-paste.

The owner clicks "Create the app" (a form auto-submitted to GitHub with the
manifest JSON); GitHub creates the App under their account and redirects
back with a one-time code; the callback exchanges it for the credentials
(app id, private key, client id/secret, webhook secret) and stores them in
the Fernet vault. The credentials travel GitHub → this server directly;
they never transit through a human or a chat.

Both routes live behind the auth wall (/setup is not in the public list).
"""

from __future__ import annotations

import json
import logging

import httpx
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from theswarm.tools import github_app

log = logging.getLogger(__name__)

router = APIRouter(prefix="/setup", tags=["setup"])

DEFAULT_APP_NAME = "theswarm-jrec"


def external_base(request: Request) -> str:
    """Public URL of this instance, reverse-proxy aware."""
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host") or request.headers.get(
        "host", request.url.netloc,
    )
    base = request.app.state.base_path
    return f"{proto}://{host.split(',')[0].strip()}{base}"


def build_manifest(request: Request, name: str) -> dict:
    ext = external_base(request)
    return {
        "name": name,
        "url": ext,
        "public": False,
        "redirect_url": f"{ext}/setup/github-app/callback",
        "callback_urls": [f"{ext}/auth/github/callback"],
        "hook_attributes": {
            "url": f"{ext}/webhooks/github",
            "active": False,  # webhook-triggered cycles are a later étape
        },
        "default_permissions": {
            "contents": "write",        # branches, commits, pushes
            "issues": "write",          # the composer creates issues
            "pull_requests": "write",   # the Dev agent opens PRs
            "checks": "write",          # QA verdict as a real check (later)
            "metadata": "read",
        },
        "default_events": [],
    }


@router.get("/github-app", response_class=HTMLResponse)
async def github_app_setup(request: Request) -> HTMLResponse:
    templates = request.app.state.templates
    creds = await github_app.load_credentials()
    manifest = build_manifest(request, DEFAULT_APP_NAME)
    return templates.TemplateResponse("github_app_setup.html", {
        "creds": creds,
        "manifest_json": json.dumps(manifest),
        "default_name": DEFAULT_APP_NAME,
        "created": request.query_params.get("created") == "1",
    })


@router.get("/github-app/callback")
async def github_app_callback(request: Request, code: str = ""):
    base = request.app.state.base_path
    if not code:
        return RedirectResponse(f"{base}/setup/github-app", status_code=303)

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            f"{github_app.GITHUB_API}/app-manifest/{code}/conversions",
            headers={"Accept": "application/vnd.github+json"},
        )
    if resp.status_code != 201:
        log.error("Manifest conversion failed: %s %s",
                  resp.status_code, resp.text[:200])
        templates = request.app.state.templates
        return templates.TemplateResponse("github_app_setup.html", {
            "creds": None,
            "manifest_json": json.dumps(
                build_manifest(request, DEFAULT_APP_NAME),
            ),
            "default_name": DEFAULT_APP_NAME,
            "created": False,
            "error": (
                "GitHub refused the one-time code (it expires after one "
                "hour and burns on first use). Start over below."
            ),
        }, status_code=502)

    payload = resp.json()
    creds = github_app.GitHubAppCredentials(
        app_id=str(payload["id"]),
        private_key_pem=payload["pem"],
        client_id=payload["client_id"],
        client_secret=payload["client_secret"],
        webhook_secret=payload.get("webhook_secret") or "",
        slug=payload.get("slug", ""),
        html_url=payload.get("html_url", ""),
    )
    await github_app.store_credentials(creds)
    log.info("GitHub App '%s' (id %s) connected", creds.slug, creds.app_id)
    return RedirectResponse(
        f"{base}/setup/github-app?created=1", status_code=303,
    )


# ── Plain OAuth App (Sign in with GitHub without the manifest flow) ────
#
# GitHub has no API to mint an OAuth client, so the owner creates the OAuth
# App once on GitHub (three fields, shown on the page) and pastes the client
# id + secret here; they go straight into the Fernet vault.


def _oauth_page(request: Request, saved: bool = False, error: str = "") -> HTMLResponse:
    templates = request.app.state.templates
    ext = external_base(request)
    return templates.TemplateResponse("github_oauth_setup.html", {
        "homepage_url": ext,
        "callback_url": f"{ext}/auth/github/callback",
        "saved": saved,
        "error": error,
    })


@router.get("/github-oauth", response_class=HTMLResponse)
async def github_oauth_setup(request: Request) -> HTMLResponse:
    page = _oauth_page(request, saved=request.query_params.get("saved") == "1")
    return page


@router.post("/github-oauth")
async def github_oauth_save(
    request: Request,
    client_id: str = Form(default=""),
    client_secret: str = Form(default=""),
):
    base = request.app.state.base_path
    if not client_id.strip() or not client_secret.strip():
        return _oauth_page(request, error="Both the client ID and the client secret are needed.")
    await github_app.store_oauth_client(client_id, client_secret)
    log.info("GitHub OAuth client saved (client id %s…)", client_id.strip()[:6])
    return RedirectResponse(f"{base}/setup/github-oauth?saved=1", status_code=303)
