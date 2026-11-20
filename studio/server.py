"""Clipsart web server. Run with:  python -m studio.server

Public pages:  /  /login  /signup          The app:  /app  (signed-in users only)
Everything under /api, /media and /oauth needs a session, except /api/auth/* and /api/public."""
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import shutil
import threading
import time
from pathlib import Path
from urllib.parse import quote, urlparse

import sqlalchemy as sa
import uvicorn
from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

from . import admin as admins
from . import account, load
from . import (accounts, ai, alerts, auth, cloud_sync, config, creators, ctx, db, jobs, live, media, notion, posting,
               profiles, render, safe, transcribe, usage)

from . import tools as _tools  # noqa: E402


def _quiet(fn):
    try:
        fn()
    except Exception as e:  # noqa: BLE001 - said again, in plain words, when a video needs it
        print(f"  {e}", flush=True)


app = FastAPI(title="Clipsart", docs_url=None, redoc_url=None, openapi_url=None)
WEB = config.ROOT / "web"
OPEN = ("/api/auth/", "/pub/", "/api/public", "/auth/google/", "/auth/verify", "/brand/", "/assets/", "/healthz", "/favicon.ico", "/robots.txt", "/sitemap.xml", "/manifest.json", "/sw.js")
PAGES = {"/": "landing.html", "/login": "auth.html", "/signup": "auth.html", "/reset": "reset.html",
         "/privacy": "legal.html", "/terms": "legal.html", "/acceptable-use": "legal.html"}
VIDEO_TYPES = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".ts", ".flv"}
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; "
       "frame-src https://player.twitch.tv https://www.youtube-nocookie.com https://player.kick.com; "
       "frame-ancestors 'none'; base-uri 'self'; form-action 'self' https://accounts.google.com")


BOOT = f"{int(time.time()) % 100000:x}"     # part of every sync token, so pages reload their data after a restart


@app.on_event("startup")
async def _more_threads():
    import anyio.to_thread
    anyio.to_thread.current_default_thread_limiter().total_tokens = int(config.env("CLIPSART_REQUEST_THREADS", "64"))


@app.on_event("startup")
def _startup():
    db.init()
    for f in (config.TMP_DIR / "uploads").glob("*"):      # uploads cut short by a restart
        try:
            f.unlink()
        except OSError:
            pass
    render.install_fonts()
    if _tools.missing():
        print("\n  " + _tools.HELP + "\n", flush=True)
    if not transcribe.REMOTE and config.env("CLIPSART_FETCH_MODEL", "1") != "0":     # the speech model: fetched now, in the background, if it was never downloaded
        from . import fetch_model
        threading.Thread(target=lambda: _quiet(fetch_model.ensure), daemon=True).start()
    jobs.start()
    live.start()
    posting.start()
    from . import updates
    updates.start()                  # looks for a newer Clipsart every minute, in the background


# ================================================================ the gate: who is asking, and are they allowed
class Gate:
    """Runs before every request: finds the signed-in user, blocks what needs sign-in, blocks cross-site form
    posts, caps upload size and adds security headers."""

    def __init__(self, app):
        self.inner = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.inner(scope, receive, send)
        req = Request(scope)
        path, method = scope["path"], scope["method"]

        async def deny(status, msg, redirect=None):
            no_keep = {"Cache-Control": "private, no-store"}      # never kept by a browser or CDN
            resp = RedirectResponse(redirect, 303, headers=no_keep) if redirect else JSONResponse({"detail": msg}, status, headers=no_keep)
            await resp(scope, receive, send)

        if method not in ("GET", "HEAD", "OPTIONS"):
            if not _from_here(req):
                return await deny(403, "Cross-site requests are not allowed.")
            # Only the upload may be big. Everything else is a small form, and is cut off at 256 KB whatever its
            # headers claim, so nobody can fill the server's memory by posting junk (signed in or not).
            piece = method == "PUT" and path.startswith("/api/upload/")
            music = method == "POST" and path.endswith("/music") and path.startswith("/api/jobs/")
            overlay = method == "POST" and path.endswith("/overlay") and path.startswith("/api/jobs/")
            thumb = method == "POST" and path.endswith("/thumbnail/save") and path.startswith("/api/jobs/")
            cap = (((min(config.MAX_UPLOAD_MB, config.UPLOAD_PART_MB) if piece else config.MAX_UPLOAD_MB) + 8) * 1024 * 1024
                   if path == "/api/upload" or piece else 13 * 1024 * 1024 if thumb else 9 * 1024 * 1024 if overlay else 33 * 1024 * 1024 if music else 256 * 1024)
            try:
                if int(req.headers.get("content-length") or 0) > cap:
                    message = "Music uploads are limited to 25 MB." if music else "Thumbnails are limited to 12 MB." if thumb else "Images are limited to 8 MB." if overlay else f"That file is too big. The limit is {config.MAX_UPLOAD_MB} MB." if path == "/api/upload" else "That request is too large."
                    return await deny(413, message)
            except ValueError:
                return await deny(400, "Bad request.")
            seen, inner_receive = 0, receive

            async def receive():
                nonlocal seen
                m = await inner_receive()
                if m["type"] == "http.request":
                    seen += len(m.get("body", b""))
                    if seen > cap:
                        raise HTTPException(413, "That request is too large.")
                return m

        is_open = path in PAGES or any(path.startswith(p) for p in OPEN)
        admin_area = path == "/admin" or path.startswith(("/admin/", "/api/admin/"))
        if config.ACCOUNTS:
            cookie = auth.session_token(req.cookies)
            user = auth._sess.get(auth._h(cookie)) if cookie and not admin_area else None      # remembered: no database, no thread hop
            user = user[1] if user and time.time() - user[0] < auth.SESS_FOR else (
                await run_in_threadpool(auth.user_for, cookie, admin_area) if cookie else None)
        else:
            # No sign-in: whoever opens the page is the owner. Because nothing else stands in the way, the page
            # must have been asked for by its real address (a number, "localhost", or the address in settings),
            # so another website cannot reach it through a made-up name that points at this machine.
            if not _own_address(req.headers.get("host", "")):
                return await deny(403, "Open Clipsart by its own address.")
            if path == "/" or path == "/reset" or path.startswith("/auth/"):
                return await deny(303, "", redirect="/app")
            if path.startswith("/api/auth/") and path != "/api/auth/me":
                return await deny(404, "Not Found")
            user = auth._local or await run_in_threadpool(auth.local_user)
        if admin_area:
            # The admin area does not exist for anyone else: same "not found" whether signed out or a normal user.
            if not user or not user.is_admin:
                return await deny(404, "Not Found")
            if method not in ("GET", "HEAD"):
                # changes must come from our own pages: the browser has to say so, and it has to match
                if not _from_here(req, must_say=True):
                    return await deny(403, "Cross-site requests are not allowed.")
        if not user and not is_open:
            if path == "/app" or path.startswith("/app/"):
                return await deny(401, "", redirect="/login")
            return await deny(401, "Please sign in.")
        if user and path in ("/login", "/signup"):
            return await deny(303, "", redirect="/app")
        scope.setdefault("state", {})["user"] = user
        if user and path in ("/api/upload", "/api/upload/start") and method == "POST":
            # decided before a single byte of the file is accepted: verified, has a free slot, has disk space
            def allowed():
                with ctx.as_user(user.id):
                    _need_verified(); _job_slots(); _quota()                     # noqa: E702
            try:
                await run_in_threadpool(allowed)
            except HTTPException as e:
                return await deny(e.status_code, e.detail)
        if user and path.startswith("/api/") and not auth.seen_recently(user.id):
            await run_in_threadpool(auth.touch, user.id)

        unchanged = False

        async def send_with_headers(message):
            nonlocal unchanged
            if unchanged:                       # the browser's copy is current: send no body at all
                if message["type"] == "http.response.body" and not message.get("more_body"):
                    await send({"type": "http.response.body", "body": b""})
                return
            if message["type"] == "http.response.start":
                h = message.setdefault("headers", [])
                if method == "GET" and message.get("status") == 200:
                    tag = next((v.decode("latin-1") for k, v in h if k.lower() == b"etag"), "")
                    have = req.headers.get("if-none-match", "")
                    if tag and have and tag.removeprefix("W/") in [x.strip().removeprefix("W/") for x in have.split(",")]:
                        unchanged = True
                        message["status"] = 304
                        h[:] = [(k, v) for k, v in h if k.lower() not in (b"content-length", b"content-type", b"content-encoding")]
                h += [(b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"DENY"),
                      (b"referrer-policy", b"strict-origin-when-cross-origin"), (b"content-security-policy", CSP.encode()),
                      (b"permissions-policy", b"camera=(), microphone=(), geolocation=()")]
                if config.HTTPS:
                    h.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                if path.startswith("/api/"):
                    h.append((b"cache-control", b"no-store"))
                elif message.get("status", 200) >= 300 and not any(k.lower() == b"cache-control" for k, _ in h):
                    # redirects and errors are never kept by a CDN: a "not found" for a clip that is still being
                    # made, or a sign-in redirect, must not be shown to anyone later
                    h.append((b"cache-control", b"private, no-store"))
                if path.startswith(("/app", "/admin", "/api/", "/auth/", "/reset", "/media/")):
                    h.append((b"x-robots-tag", b"noindex, nofollow"))
            await send(message)

        token = ctx._uid.set(user.id if user else None)
        try:
            if user and path == "/api/sync" and method == "GET":
                # By far the most common request. When nothing of this user's changed it is answered right here:
                # no worker thread, no database, no disk. Anything else falls through to the normal route.
                quick = _sync_unchanged(req.query_params.get("v", ""))
                if quick is not None:
                    return await JSONResponse(quick)(scope, receive, send_with_headers)
            await self.inner(scope, receive, send_with_headers)
        finally:
            ctx._uid.reset(token)


app.add_middleware(Gate)


class Compress:
    """gzip for text responses. Videos and images are already compressed and need byte ranges, so they pass through."""
    def __init__(self, app):
        from starlette.middleware.gzip import GZipMiddleware
        self.plain, self.gzip = app, GZipMiddleware(app, minimum_size=800, compresslevel=6)

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "") if scope["type"] == "http" else ""
        media = path.startswith(("/media/", "/api/upload")) or path.endswith((".mp4", ".jpg", ".png", ".webp", ".ico"))
        await (self.plain if scope["type"] != "http" or media else self.gzip)(scope, receive, send)


app.add_middleware(Compress)


# Cloudflare's published address ranges (cloudflare.com/ips). CLIPSART_CDN_RANGES replaces them if they ever change.
_CDN_RANGES = None


def _from_cdn(addr: str) -> bool:
    global _CDN_RANGES
    import ipaddress
    if _CDN_RANGES is None:
        ranges = config.env("CLIPSART_CDN_RANGES") or (
            "173.245.48.0/20 103.21.244.0/22 103.22.200.0/22 103.31.4.0/22 141.101.64.0/18 108.162.192.0/18 "
            "190.93.240.0/20 188.114.96.0/20 197.234.240.0/22 198.41.128.0/17 162.158.0.0/15 104.16.0.0/13 "
            "104.24.0.0/14 172.64.0.0/13 131.0.72.0/22 2400:cb00::/32 2606:4700::/32 2803:f800::/32 2405:b500::/32 "
            "2405:8100::/32 2a06:98c0::/29 2c0f:f248::/32")
        _CDN_RANGES = [ipaddress.ip_network(r) for r in ranges.replace(",", " ").split()]
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return any(ip in n for n in _CDN_RANGES)


def _ip(request: Request) -> str:
    """The visitor's address, used for rate limits. The connection's own address, or the one the proxy in front
    reports (CLIPSART_TRUST_PROXY). If that connection comes from the CDN, the CDN's header names the real visitor
    (CLIPSART_CLIENT_IP_HEADER). The header is believed only when the CDN really sent the request, so nobody can
    pick their own address by sending it themselves.

    The proxy adds the address it saw at the END of X-Forwarded-For. Everything before that was written by the
    visitor, so only the last entry is believed."""
    fwd = request.headers.get("x-forwarded-for", "")
    peer = (fwd.split(",")[-1].strip() if fwd and config.env("CLIPSART_TRUST_PROXY") else "") or (request.client.host if request.client else "")
    named = config.env("CLIPSART_CLIENT_IP_HEADER")
    if named and request.headers.get(named) and _from_cdn(peer):
        return request.headers[named].split(",")[0].strip()[:64]
    return peer


def _from_here(req, must_say=False) -> bool:
    """Did this change come from Clipsart's own page, and not from another website?

    The browser's own answer is trusted first: it marks every request "same-origin" or not, and a web page cannot
    fake that mark. Comparing the page's address with the address the request arrived at is only the fallback,
    because that comparison goes wrong when something in between rewrites either of them (a proxy, an antivirus
    web shield, a browser extension), which made every save fail with "Cross-site requests are not allowed"."""
    if (req.headers.get("sec-fetch-site") or "").lower() == "same-origin":
        return True
    host = (req.headers.get("host") or "").lower()
    public_netloc = urlparse(config.PUBLIC_URL).netloc.lower()
    origin = (req.headers.get("origin") or "").rstrip("/").lower()
    if origin:
        origin_netloc = urlparse(origin).netloc.lower()
        return origin_netloc == host or origin_netloc == public_netloc or origin == config.PUBLIC_URL.lower()
    referer = (req.headers.get("referer") or "").rstrip("/").lower()
    if referer:
        referer_netloc = urlparse(referer).netloc.lower()
        return referer_netloc == host or referer_netloc == public_netloc or referer.startswith(config.PUBLIC_URL.lower())
    return not must_say


def _own_address(host: str) -> bool:
    """Is this the address Clipsart is really reached by? A number (127.0.0.1, 192.168.1.20), "localhost", or the
    host in CLIPSART_PUBLIC_URL."""
    import ipaddress
    name = host.strip().lower()
    name = name[1:name.index("]")] if name.startswith("[") and "]" in name else name.rsplit(":", 1)[0] if ":" in name else name
    if name in ("localhost", urlparse(config.PUBLIC_URL).hostname or "") or name.endswith(".localhost"):
        return True
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return False


def _me(request: Request):
    return request.state.user


def _admin(request: Request):
    """The signed-in admin, read from the database for this very request. Anyone else gets "not found"."""
    u = getattr(request.state, "user", None)
    if not u or not u.is_admin or u.disabled:
        raise HTTPException(404)
    return u


def _need_verified():
    if not auth.is_verified(ctx.uid()):
        raise HTTPException(403, "Confirm your email first. We sent you a link when you signed up; you can send a new one from the banner at the top.")


# ================================================================ pages
def _page(name, shared=False):
    """A page. The browser keeps its copy and asks each time whether it has changed; when it has not, the answer
    is a few bytes ("not modified") instead of the whole page again. Signed-in pages are never kept by anything
    in between (a proxy or CDN), only by the person's own browser."""
    return FileResponse(WEB / name, headers={"Cache-Control": ("public" if shared else "private") + ", no-cache"})


_LANDING: dict = {}


@app.get("/")
def landing():
    f = WEB / "landing.html"
    m = f.stat().st_mtime
    if _LANDING.get("m") != m:
        html = f.read_text(encoding="utf-8").replace("{{SITE}}", config.PUBLIC_URL)
        _LANDING.update(m=m, html=html, etag='"' + hashlib.md5(html.encode()).hexdigest() + '"')
    # fresh for five minutes; after that a CDN or browser may show its copy while it quietly fetches the new one
    return HTMLResponse(_LANDING["html"], headers={"Cache-Control": "public, max-age=300, stale-while-revalidate=86400",
                                                   "ETag": _LANDING["etag"]})


@app.get("/robots.txt")
def robots():
    return Response("User-agent: *\nAllow: /\nDisallow: /app\nDisallow: /api/\nDisallow: /auth/\nDisallow: /reset\nDisallow: /media/\n"
                    f"\nSitemap: {config.PUBLIC_URL}/sitemap.xml\n", media_type="text/plain",
                    headers={"Cache-Control": "public, max-age=86400"})


@app.get("/sitemap.xml")
def sitemap():
    day = time.strftime("%Y-%m-%d")
    pages = [("/", "1.0", "weekly"), ("/signup", "0.8", "monthly"), ("/login", "0.4", "monthly"), ("/terms", "0.3", "yearly"),
             ("/privacy", "0.3", "yearly"), ("/acceptable-use", "0.2", "yearly")]
    body = "".join(f"<url><loc>{config.PUBLIC_URL}{u}</loc><lastmod>{day}</lastmod><changefreq>{c}</changefreq>"
                   f"<priority>{p}</priority></url>" for u, p, c in pages)
    return Response('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    + body + "</urlset>", media_type="application/xml", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/login")
@app.get("/signup")
def auth_page():
    return _page("auth.html", shared=True)


@app.get("/reset")
def reset_page():
    return _page("reset.html", shared=True)


LEGAL = {
    "privacy": ("Privacy Policy", "How Clipsart collects, uses and protects your data, including Google user data, cookies and your privacy rights."),
    "terms": ("Terms of Service", "The terms for using Clipsart, the AI clipping tool for streams and videos: accounts, availability and liability."),
    "acceptable-use": ("Acceptable Use Policy", "What you may and may not do with Clipsart, the AI stream clipping tool."),
}


@app.get("/privacy")
@app.get("/terms")
@app.get("/acceptable-use")
def legal_page(request: Request):
    """Public, so Google's app review (and anyone) can read them. Business name, law and contact come from settings."""
    import html as _h
    page = request.url.path.strip("/")
    title, desc = LEGAL[page]
    contact = config.CONTACT_EMAIL
    who = (f'<a href="mailto:{_h.escape(contact)}">{_h.escape(contact)}</a>' if contact
           else "the contact details on our website")
    name = _h.escape(config.LEGAL_NAME or "Clipsart")
    law = (f"the laws of {_h.escape(config.LEGAL_COUNTRY)}" if config.LEGAL_COUNTRY
           else "the laws of the country where Clipsart's operator is established")
    out = (_LEGAL_HTML or (WEB / "legal.html").read_text(encoding="utf-8"))
    for k, v in {"{{CONTACT}}": who, "{{PAGE}}": page, "{{PAGE_PATH}}": page, "{{SITE}}": _h.escape(config.PUBLIC_URL),
                 "{{NAME}}": name, "{{LAW}}": law, "{{TITLE}}": title, "{{DESC}}": desc}.items():
        out = out.replace(k, v)
    return HTMLResponse(out, headers={"Cache-Control": "public, max-age=3600"})


_LEGAL_HTML = ""


@app.get("/app")
@app.get("/app/{rest:path}")
def app_page(rest: str = ""):
    """Every app address (/app/videos, /app/creators/<id>/setup ...) is the same page; it shows the right view."""
    return _page("index.html")


@app.get("/admin")
@app.get("/admin/{rest:path}")
def admin_page(request: Request, rest: str = ""):
    _admin(request)
    return _page("admin.html")


@app.get("/healthz")
def healthz():
    with db.engine.connect() as c:
        c.execute(sa.text("select 1"))
    return {"ok": True}


@app.get("/brand/{name}")
def brand(name: str):
    if not re.fullmatch(r"[\w\-]+\.(svg|png|ico|webp|jpg|mp4)", name) or not (WEB / "brand" / name).is_file():
        raise HTTPException(404)
    return FileResponse(WEB / "brand" / name, headers={"Cache-Control": "public, max-age=604800, stale-while-revalidate=86400"})


@app.get("/assets/{name}")
def asset(name: str):
    if not re.fullmatch(r"[\w\-]+\.js", name) or not (WEB / name).is_file():
        raise HTTPException(404)
    return FileResponse(WEB / name, media_type="text/javascript", headers={"Cache-Control": "public, max-age=86400, stale-while-revalidate=604800"})


@app.get("/favicon.ico")
def favicon():
    return RedirectResponse("/brand/favicon.svg", 308)


@app.get("/manifest.json")
def manifest():
    f = WEB / "manifest.json"
    if not f.is_file():
        raise HTTPException(404)
    return FileResponse(f, media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    f = WEB / "sw.js"
    if not f.is_file():
        raise HTTPException(404)
    return FileResponse(f, media_type="application/javascript", headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


# ================================================================ sign up, sign in, sign out
@app.get("/api/public")
def public_config():
    from . import mailer
    return {"google": auth.google_ready(), "mail": mailer.ready(), "verify_email": config.VERIFY_EMAIL}


def _signed_in(request: Request, user, first: bool, redirect=None):
    token = auth.start_session(user.id, _ip(request), request.headers.get("user-agent", ""))
    resp = RedirectResponse(redirect, 303) if redirect else JSONResponse({"user": auth.public(user)})
    is_secure = config.HTTPS or (request.url.scheme == "https") or (request.headers.get("x-forwarded-proto", "").lower() == "https")
    resp.set_cookie(**auth.cookie_args(token, secure=is_secure))
    return resp


@app.post("/api/auth/signup")
def signup(request: Request, body: dict = Body(...)):
    try:
        auth.throttle("signup:" + _ip(request), 8, 3600)
        user, first = auth.signup(str(body.get("email", "")), str(body.get("password", "")), str(body.get("name", "")))
    except auth.AuthError as e:
        raise HTTPException(400, str(e))
    if not auth.is_verified(user.id):
        auth.send_verify(user)
    return _signed_in(request, user, first)


@app.post("/api/auth/resend-verification")
def resend_verification(request: Request):
    u = _me(request)
    if not u:
        raise HTTPException(401, "Please sign in.")
    if auth.is_verified(u.id):
        return {"verified": True}
    try:
        auth.throttle("verify:" + u.id, 3, 900)
    except auth.AuthError:
        raise HTTPException(429, "We've sent a few already. Check your spam folder, or try again in 15 minutes.")
    from . import mailer
    return {"sent": auth.send_verify(u), "mail_ready": mailer.ready()}


@app.get("/auth/verify")
def verify_email(request: Request, t: str = ""):
    try:
        auth.verify_link(t)
    except auth.AuthError as e:
        return RedirectResponse("/app?verify_error=" + quote(str(e)), status_code=303)
    return RedirectResponse("/app?verified=1", status_code=303)


@app.post("/api/auth/forgot")
def forgot_password(request: Request, body: dict = Body(...)):
    email = str(body.get("email", "")).strip().lower()
    try:
        auth.throttle("forgot-ip:" + _ip(request), 10, 3600)
        auth.throttle("forgot:" + email, 3, 3600)
    except auth.AuthError as e:
        raise HTTPException(429, str(e))
    auth.forgot(email)
    return {"ok": True}   # the same answer whether or not the account exists


@app.post("/api/auth/reset")
def reset_password(request: Request, body: dict = Body(...)):
    try:
        auth.throttle("reset-ip:" + _ip(request), 20, 3600)
        user = auth.reset_password(str(body.get("token", "")), str(body.get("password", "")))
    except auth.AuthError as e:
        raise HTTPException(400, str(e))
    return _signed_in(request, user, False)


@app.post("/api/auth/login")
def login(request: Request, body: dict = Body(...)):
    email = str(body.get("email", ""))
    try:
        auth.throttle("login-ip:" + _ip(request), 30, 600)
        auth.throttle(f"login:{email.strip().lower()[:254]}:{_ip(request)}", 8, 600)
        auth.throttle("login:" + email.strip().lower()[:254], 60, 600)
        user = auth.login(email, str(body.get("password", "")))
    except auth.AuthError as e:
        raise HTTPException(400, str(e))
    return _signed_in(request, user, False)


@app.post("/api/auth/logout")
def logout(request: Request):
    auth.end_session(auth.session_token(request.cookies))
    resp = JSONResponse({"ok": True})
    is_secure = config.HTTPS or (request.url.scheme == "https") or (request.headers.get("x-forwarded-proto", "").lower() == "https")
    resp.delete_cookie(auth.COOKIE, path="/", httponly=True, samesite="lax", secure=is_secure)
    return resp


@app.get("/api/auth/me")
def me(request: Request):
    return {"user": auth.public(_me(request)) if _me(request) else None}


@app.post("/api/auth/password")
def change_password(request: Request, body: dict = Body(...)):
    if not _me(request):
        raise HTTPException(401, "Please sign in.")
    try:
        auth.throttle("pw:" + _me(request).id, 6, 600)
        auth.change_password(_me(request).id, str(body.get("current", "")), str(body.get("new", "")),
                             keep_token=auth.session_token(request.cookies))
    except auth.AuthError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.get("/auth/google/start")
def google_start(next: str = "/app"):
    if not auth.google_ready():
        raise HTTPException(404)
    url, state = auth.google_url(next)
    resp = RedirectResponse(url)
    # the sign-in can only be finished by the browser that started it
    resp.set_cookie("g_state", state, max_age=900, httponly=True, samesite="lax", secure=config.HTTPS, path="/auth/google")
    return resp


@app.get("/auth/google/callback")
def google_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error or not code or not state or not hmac.compare_digest(request.cookies.get("g_state", ""), state):
        return RedirectResponse("/login?error=google", 303)
    try:
        auth.throttle("google:" + _ip(request), 30, 600)
        user, first, nxt = auth.google_finish(code, state)
    except auth.AuthError:
        return RedirectResponse("/login?error=google", 303)
    return _signed_in(request, user, first, redirect=nxt)


# ================================================================ app status
@app.get("/api/status")
def status(request: Request):
    from . import notices
    from . import updates
    me_ = _me(request)
    return {"user": auth.public(me_), "update": updates.latest() if me_.is_admin else None, "accounts": config.ACCOUNTS, "disk_full": load.disk_full(), "no_ffmpeg": bool(_tools.missing()), "links": {"repo": config.REPO_URL, "follow": config.FOLLOW_URL}, "ai": usage.brief(), "unread": notices.unread(),
            "tour": not accounts.settings()["tour_done"],
            "youtube": accounts.youtube_ready(), "connect": {p: accounts.can_connect(p) for p in accounts.CORE_PLATFORMS}, "max_upload_mb": config.MAX_UPLOAD_MB, "upload_part_mb": config.UPLOAD_PART_MB, "max_batch": config.MAX_ACTIVE_JOBS_PER_USER,
            "styles": {k: v["label"] for k, v in render.STYLES.items()}, "layouts": render.LAYOUTS}


# ================================================================ videos
def _job_or_404(jid: str):
    job = jobs.get(jid) if re.fullmatch(r"[\w\-]{8,60}", jid) else None
    if not job:
        raise HTTPException(404, "No such video")
    return job


def _job_slots():
    from . import tools
    if tools.missing():
        raise HTTPException(503, tools.HELP)
    if jobs.busy_count() >= config.MAX_ACTIVE_JOBS_PER_USER:
        raise HTTPException(429, f"You already have {config.MAX_ACTIVE_JOBS_PER_USER} videos in progress. Wait for one to finish.")


_create_lock = threading.Lock()      # "do I have a free slot?" and "take it" happen together, so bursts cannot slip past the limit
_lookups = threading.BoundedSemaphore(8)   # link and channel previews running at once, whole server
_disk: dict = {}


def _quota():
    """Each account has a fixed amount of disk space. Measured at most once a minute."""
    if load.disk_full():
        from . import storage
        raise HTTPException(507, storage.full_message())
    uid = ctx.uid()
    got = _disk.get(uid)
    if not got or time.time() - got[0] > 60:
        total = 0
        for root, _dirs, files in os.walk(config.user_dir(uid)):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        got = _disk[uid] = (time.time(), total)
    if got[1] > config.MAX_USER_GB * 1e9:
        raise HTTPException(507, "Your storage is full. Delete some older videos to make room.")


def _throttle(key, limit, window, msg="Too many requests at once. Wait a moment."):
    try:
        auth.throttle(key, limit, window)
    except auth.AuthError:
        raise HTTPException(429, msg)


def _lookup(fn, *a):
    """Run a preview lookup, unless the server is already doing as many as it should."""
    if not _lookups.acquire(blocking=False):
        raise HTTPException(429, "Lots of people are looking things up right now. Try again in a few seconds.")
    try:
        return fn(*a)
    finally:
        _lookups.release()


def _creator_rows():
    out = []
    for c in creators.all_creators():
        if profiles.needs_refresh(c):
            profiles.refresh(c["id"])
        s = live.active_for(c["id"])
        out.append({**c, "live_job": s.job["id"] if s else None, "log": creators.read_log(c["id"], 30)})
    return out


def _sync_token() -> str:
    return f"{BOOT}.{ctx.version()}.{jobs.queue_epoch() if jobs.busy_count() else 0}"


def _sync_unchanged(v: str):
    """{"v": token} if the page is up to date and this user's creators are already in memory, else None."""
    mine = creators._mem.get(ctx.uid())
    if mine is None or not v or v != _sync_token():
        return None
    for c in list(mine.values()):                      # still keep live status fresh while the page is open
        if profiles.needs_refresh(c):
            profiles.refresh(c["id"])
    return {"v": v}


@app.get("/api/sync")
def sync(v: str = ""):
    """What the page asks every couple of seconds. It sends the token it got last time; when nothing of this
    user's has changed, the answer is just that token: no files read, nothing built."""
    token = _sync_token()
    if v == token:
        return _sync_unchanged(v) or {"v": token}
    from . import notices
    return {"v": token, "jobs": [jobs.public(j) for j in jobs.list_jobs()], "creators": _creator_rows(),
            "accounts": accounts.list_accounts(), "ai": usage.brief(), "unread": notices.unread()}


@app.get("/api/jobs")
def list_jobs():
    return [jobs.public(j) for j in jobs.list_jobs()]


@app.get("/api/jobs/{jid}")
def get_job(jid: str):
    return jobs.public(_job_or_404(jid))


@app.get("/api/preview")
def link_preview(request: Request, url: str = ""):
    url = url.strip()[:500]
    if not media.site_allowed(url):
        raise HTTPException(400, "Paste a full link to a YouTube, Twitch or Kick video.")
    try:
        auth.throttle(f"preview:{_me(request).id}", 12, 60)
    except auth.AuthError:
        raise HTTPException(429, "Too many links at once. Wait a moment.")
    try:
        return _lookup(media.preview, url)
    except media.YouTubeBlocked as e:
        raise HTTPException(503, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, "Couldn't open that video. Check the link is public and complete.")


@app.post("/api/jobs")
def create_from_link(body: dict = Body(...)):
    _need_verified()
    _quota()
    _throttle("newjob:" + ctx.uid(), 30, 600)
    url = str(body.get("url", "")).strip()[:500]
    if not media.site_allowed(url):
        raise HTTPException(400, "Paste a full link to a YouTube, Twitch or Kick video.")
    try:
        media.check_youtube(url)          # YouTube is refusing us right now: say so, rather than queue a job that fails
    except media.YouTubeBlocked as e:
        raise HTTPException(503, str(e))
    creator = str(body.get("creator") or "") or None
    if creator and not creators.get(creator):
        raise HTTPException(404, "No such creator")
    try:
        with _create_lock:
            _job_slots()
            job = jobs.create({"type": "url", "url": url, "name": url}, body.get("options") or {}, creator=creator)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e) if isinstance(e, ValueError) else "Those options aren't valid.")
    seen = media._PREVIEWS.get(url)  # already looked up while the user was typing: show it straight away
    if seen:
        job.update(title=seen["title"], uploader=seen["uploader"], duration=seen["duration"])
        if media.save_thumb(jobs.job_dir(job["id"]), url=url):
            job["thumb"] = True
        jobs.save(job)
    return jobs.public(job)


@app.post("/api/upload")
def create_from_file(file: UploadFile = File(...), options: str = Form("{}"), creator: str = Form("")):
    _need_verified()
    _job_slots()
    name = re.sub(r"[^\w.\- ]", "_", Path(file.filename or "video.mp4").name)[:120]
    ext = Path(name).suffix.lower()
    if ext not in VIDEO_TYPES:
        raise HTTPException(400, "Upload a video file (mp4, mov, mkv or webm).")
    if creator and not creators.get(creator):
        raise HTTPException(404, "No such creator")
    try:
        opts = json.loads(options)
        opts = opts if isinstance(opts, dict) else {}
    except ValueError:
        opts = {}
    updir = config.TMP_DIR / "uploads"
    updir.mkdir(exist_ok=True)
    tmp = updir / f"{os.urandom(8).hex()}{ext}"
    limit, size = config.MAX_UPLOAD_MB * 1024 * 1024, 0
    try:
        with tmp.open("wb") as f:
            while chunk := file.file.read(4 * 1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"That file is too big. The limit is {config.MAX_UPLOAD_MB} MB.")
                f.write(chunk)
        try:
            with _create_lock:
                _job_slots()
                job = jobs.create({"type": "file", "path": str(tmp), "name": name}, opts, enqueue=False, creator=creator or None)
        except (ValueError, TypeError):
            raise HTTPException(400, "Those options aren't valid.")
        _disk.pop(ctx.uid(), None)
        dest = jobs.job_dir(job["id"]) / ("source" + ext)
        shutil.move(str(tmp), dest)
    finally:
        tmp.unlink(missing_ok=True)
    job["source"]["path"] = str(dest)
    jobs.enqueue(job)
    return jobs.public(job)


# ---------------------------------------------------------------- big files, sent in pieces
# The page cuts a large file into pieces, sends each one, and asks for them to be joined. Each piece is small enough
# for anything standing in front of the app. Nothing is trusted from the page: the sizes are fixed when the upload
# starts, every piece must be exactly its size, and only the account that started an upload can add to it.
_UP_ID = re.compile(r"[0-9a-f]{24}")
_up_lock = threading.Lock()


def _up_root() -> Path:
    d = config.TMP_DIR / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _up_sweep():
    """Forget uploads that were started and never finished (after six hours)."""
    for d in _up_root().glob("up-*"):
        try:
            if d.is_dir() and time.time() - d.stat().st_mtime > 6 * 3600:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def _up_get(upid: str) -> dict:
    """The upload, only if it belongs to whoever is asking."""
    if not _UP_ID.fullmatch(upid or ""):
        raise HTTPException(404, "No such upload")
    try:
        meta = json.loads((_up_root() / f"up-{upid}" / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HTTPException(404, "This upload has expired. Start it again.")
    if meta.get("user") != ctx.uid():
        raise HTTPException(404, "No such upload")
    return meta


@app.post("/api/upload/start")
def upload_start(body: dict = Body(...)):
    _need_verified()
    _job_slots()
    _quota()
    _throttle("upstart:" + ctx.uid(), 30, 600)
    name = re.sub(r"[^\w.\- ]", "_", Path(str(body.get("name") or "video.mp4")).name)[:120]
    ext = Path(name).suffix.lower()
    if ext not in VIDEO_TYPES:
        raise HTTPException(400, "Upload a video file (mp4, mov, mkv or webm).")
    size = body.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise HTTPException(400, "Bad file size.")
    if size > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"That file is too big. The limit is {config.MAX_UPLOAD_MB} MB.")
    if _disk.get(ctx.uid(), (0, 0))[1] + size > config.MAX_USER_GB * 1e9:
        raise HTTPException(507, "There isn't room for this file in your storage. Delete some older videos to make room.")
    creator = str(body.get("creator") or "")
    if creator and not creators.get(creator):
        raise HTTPException(404, "No such creator")
    opts = body.get("options") if isinstance(body.get("options"), dict) else {}
    try:
        jobs.clean_options(opts)                 # refused now rather than after the whole file has been sent
    except (ValueError, TypeError):
        raise HTTPException(400, "Those options aren't valid.")
    _up_sweep()
    mine = 0
    for d in _up_root().glob("up-*"):
        try:
            mine += json.loads((d / "meta.json").read_text(encoding="utf-8")).get("user") == ctx.uid()
        except (OSError, ValueError):
            pass
    if mine >= config.MAX_ACTIVE_JOBS_PER_USER:
        raise HTTPException(429, f"You already have {mine} uploads in progress. Let one finish first.")
    part = config.UPLOAD_PART_MB * 1024 * 1024
    upid = os.urandom(12).hex()
    d = _up_root() / f"up-{upid}"
    d.mkdir()
    meta = {"user": ctx.uid(), "name": name, "ext": ext, "size": size, "part": part, "parts": -(-size // part),
            "options": opts, "creator": creator, "t": time.time()}
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return {"id": upid, "part": part, "parts": meta["parts"]}


@app.put("/api/upload/{upid}/{n}")
async def upload_part(request: Request, upid: str, n: int):
    meta = await run_in_threadpool(_up_get, upid)
    if not 0 <= n < meta["parts"]:
        raise HTTPException(400, "No such piece.")
    want = meta["part"] if n < meta["parts"] - 1 else meta["size"] - meta["part"] * (meta["parts"] - 1)
    d = _up_root() / f"up-{upid}"
    tmp = d / f"{n:05d}.{os.urandom(4).hex()}.tmp"
    got = 0
    try:
        with tmp.open("wb") as f:
            async for chunk in request.stream():
                got += len(chunk)
                if got > want:
                    raise HTTPException(400, "That piece is the wrong size.")
                await run_in_threadpool(f.write, chunk)
        if got != want:
            raise HTTPException(400, "That piece is the wrong size.")
        tmp.replace(d / f"{n:05d}.part")           # sending a piece again simply replaces it
    finally:
        tmp.unlink(missing_ok=True)
    return {"ok": True, "n": n}


@app.post("/api/upload/{upid}/finish")
def upload_finish(upid: str):
    meta = _up_get(upid)
    _need_verified()
    d = _up_root() / f"up-{upid}"
    with _up_lock:                                    # two "finish" calls for one upload make one video, not two
        if not (d / "meta.json").is_file():
            raise HTTPException(404, "This upload has expired. Start it again.")
        parts = [d / f"{i:05d}.part" for i in range(meta["parts"])]
        missing = [i for i, p in enumerate(parts) if not p.is_file()]
        if missing:
            raise HTTPException(409, f"Piece {missing[0] + 1} of {meta['parts']} has not arrived yet.")
        if sum(p.stat().st_size for p in parts) != meta["size"]:
            raise HTTPException(400, "The pieces do not add up to the file.")
        try:
            with _create_lock:
                _job_slots()
                job = jobs.create({"type": "file", "path": "", "name": meta["name"]}, meta["options"], enqueue=False,
                                  creator=meta["creator"] or None)
        except (ValueError, TypeError):
            raise HTTPException(400, "Those options aren't valid.")
        dest = jobs.job_dir(job["id"]) / ("source" + meta["ext"])
        try:
            with dest.open("wb") as out:
                for p in parts:
                    with p.open("rb") as src:
                        shutil.copyfileobj(src, out, 4 * 1024 * 1024)
        except OSError:
            jobs.delete(job["id"])
            raise HTTPException(507, "There wasn't room to save this file. Delete some older videos and try again.")
        shutil.rmtree(d, ignore_errors=True)
    _disk.pop(ctx.uid(), None)
    job["source"]["path"] = str(dest)
    jobs.enqueue(job)
    return jobs.public(job)


@app.delete("/api/upload/{upid}")
def upload_cancel(upid: str):
    _up_get(upid)
    shutil.rmtree(_up_root() / f"up-{upid}", ignore_errors=True)
    return {"ok": True}


@app.post("/api/jobs/{jid}/clips/{cid}/render")
def rerender(jid: str, cid: str, body: dict = Body(...)):
    job = _job_or_404(jid)
    clip = next((c for c in job["clips"] if c["id"] == cid), None)
    if not clip:
        raise HTTPException(404, "No such clip")
    if job["status"] in ("queued", "running") or clip.get("status") in ("queued", "rendering"):
        raise HTTPException(409, "This clip is still being made. Try again when it has finished.")
    _throttle("render:" + ctx.uid(), 20, 600, "That's a lot of re-makes in a short time. Wait a few minutes.")
    try:
        jobs.request_render(jid, cid, body)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))
    return jobs.public(job)


@app.post("/api/jobs/{jid}/clips/{cid}/preview")
async def clip_preview(jid: str, cid: str, body: dict = Body(...)):
    job = _job_or_404(jid)
    clip = next((c for c in job["clips"] if c["id"] == cid), None)
    if not clip:
        raise HTTPException(404, "No such clip")
    if job.get("status") in ("queued", "running") or clip.get("status") in ("queued", "rendering"):
        raise HTTPException(409, "Wait for this clip to finish before previewing edits.")
    _throttle("preview:" + ctx.uid(), 6, 60, "Preview renders are busy. Wait a minute and try again.")
    try:
        file = await run_in_threadpool(jobs.render_preview, job, clip, body)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"Could not make the preview: {safe.friendly(e, 250)}") from e
    return {"file": f"/media/{jid}/{file}", "width": 540, "height": 960}


@app.post("/api/jobs/{jid}/clips/{cid}/thumbnail/frame")
async def thumbnail_frame(jid: str, cid: str, body: dict = Body(...)):
    """Extract a still frame from this user's finished clip for the thumbnail editor."""
    job = _job_or_404(jid)
    clip = next((c for c in job["clips"] if c["id"] == cid), None)
    if not clip or clip.get("status") != "done":
        raise HTTPException(404, "No finished clip to make a thumbnail from.")
    try:
        seconds = float(body.get("seconds", 0))
    except (TypeError, ValueError):
        raise HTTPException(400, "Choose a valid time in the clip.")
    duration = max(0.0, float(clip.get("end", 0)) - float(clip.get("start", 0)))
    if not math.isfinite(seconds) or seconds < 0 or seconds >= duration:
        raise HTTPException(400, "Choose a time inside this clip.")
    clips_dir = Path(job["dir"]) / "clips"
    source = clips_dir / Path(str(clip.get("file") or "")).name
    if not source.is_file():
        raise HTTPException(404, "The finished clip file is missing.")
    token = secrets.token_hex(8)
    draft = f"{cid}.thumb-draft-{token}.jpg"
    temp = clips_dir / f".{draft}.part.jpg"
    try:
        await run_in_threadpool(media.run, ["ffmpeg", "-y", "-v", "error", "-ss", f"{seconds:.3f}", "-i", str(source),
                                             "-frames:v", "1", "-vf", "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280",
                                             "-q:v", "3", str(temp)], timeout=45)
        from PIL import Image
        with Image.open(temp) as im:
            im.verify()
        os.replace(temp, clips_dir / draft)
        old = Path(str(clip.get("thumbnail_draft") or "")).name
        before = dict(clip)
        clip["thumbnail_draft"] = draft
        try:
            jobs.save(job)
        except Exception:
            clip.clear()
            clip.update(before)
            (clips_dir / draft).unlink(missing_ok=True)
            raise
        if old.startswith(f"{cid}.thumb-draft-") and old != draft:
            (clips_dir / old).unlink(missing_ok=True)
        return {"file": f"/media/{jid}/{draft}", "width": 720, "height": 1280}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Could not capture that frame: {safe.friendly(e, 200)}") from e
    finally:
        temp.unlink(missing_ok=True)


@app.post("/api/jobs/{jid}/clips/{cid}/thumbnail/save")
async def thumbnail_save(jid: str, cid: str, file: UploadFile = File(...), title: str = Form(""), style: str = Form("bold")):
    """Normalize a browser-edited/uploaded thumbnail and atomically make it the clip cover."""
    job = _job_or_404(jid)
    clip = next((c for c in job["clips"] if c["id"] == cid), None)
    if not clip or clip.get("status") != "done":
        raise HTTPException(404, "No finished clip to update.")
    ext = Path(file.filename or "thumbnail.jpg").suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        raise HTTPException(400, "Choose a JPEG, PNG, or WebP thumbnail.")
    if style not in ("bold", "clean", "neon"):
        raise HTTPException(400, "Choose a valid thumbnail text style.")
    clips_dir = Path(job["dir"]) / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(8)
    temp = clips_dir / f".{cid}.thumb-{token}.part.jpg"
    final = clips_dir / f"{cid}.thumb-{token}.jpg"
    try:
        size = 0
        payload = bytearray()
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > 12 * 1024 * 1024:
                raise HTTPException(413, "Thumbnails are limited to 12 MB.")
            payload.extend(chunk)
        if not payload:
            raise HTTPException(400, "Choose an image first.")
        from PIL import Image, ImageOps
        import io
        try:
            with Image.open(io.BytesIO(payload)) as probe:
                if probe.format not in ("JPEG", "PNG", "WEBP") or probe.width < 1 or probe.height < 1 or probe.width * probe.height > 20_000_000:
                    raise HTTPException(400, "Thumbnail must be a valid image up to 20 megapixels.")
                probe.verify()
            with Image.open(io.BytesIO(payload)) as image:
                image = ImageOps.exif_transpose(image).convert("RGB")
                image = ImageOps.fit(image, (720, 1280), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
                image.save(temp, "JPEG", quality=92, optimize=True)
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, "That file is not a readable image.") from e
        os.replace(temp, final)
        old_cover = Path(str(clip.get("cover") or "")).name
        old_draft = Path(str(clip.get("thumbnail_draft") or "")).name
        before = dict(clip)
        clip.update(cover=final.name, thumbnail_custom=True, thumbnail_draft=None,
                    thumbnail_text=str(title).strip()[:80], thumbnail_style=style)
        try:
            jobs.save(job)
        except Exception:
            clip.clear()
            clip.update(before)
            raise
        if old_cover.startswith(f"{cid}.thumb-"):
            (clips_dir / old_cover).unlink(missing_ok=True)
        if old_draft.startswith(f"{cid}.thumb-draft-"):
            (clips_dir / old_draft).unlink(missing_ok=True)
        return {"ok": True, "file": final.name}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        temp.unlink(missing_ok=True)
        final.unlink(missing_ok=True)
        raise HTTPException(500, f"Could not save the thumbnail: {safe.friendly(e, 200)}") from e
    finally:
        temp.unlink(missing_ok=True)
        await file.close()


@app.post("/api/jobs/{jid}/clips/{cid}/thumbnail/reset")
def thumbnail_reset(jid: str, cid: str):
    """Restore the latest generated cover and remove this clip's custom thumbnail."""
    job = _job_or_404(jid)
    clip = next((c for c in job["clips"] if c["id"] == cid), None)
    if not clip or clip.get("status") != "done":
        raise HTTPException(404, "No finished clip to update.")
    clips_dir = Path(job["dir"]) / "clips"
    generated = Path(str(clip.get("generated_cover") or "")).name
    if not generated:
        generated = Path(str(clip.get("file") or "")).stem + ".jpg"
    if not (clips_dir / generated).is_file():
        raise HTTPException(404, "The generated thumbnail is not available to restore.")
    old = Path(str(clip.get("cover") or "")).name
    draft = Path(str(clip.get("thumbnail_draft") or "")).name
    before = dict(clip)
    clip.update(cover=generated, thumbnail_custom=False, thumbnail_draft=None)
    try:
        jobs.save(job)
    except Exception:
        clip.clear()
        clip.update(before)
        raise
    for name in (old, draft):
        if name.startswith(f"{cid}.thumb-"):
            (clips_dir / name).unlink(missing_ok=True)
    return {"ok": True, "file": generated}


@app.post("/api/jobs/{jid}/clips/{cid}/music")
async def clip_music_upload(jid: str, cid: str, file: UploadFile = File(...), attribution: str = Form(""),
                             license_url: str = Form(""), rights_confirmed: str = Form("")):
    """Store a user-provided audio track for this clip. We do not fetch tracks from streaming services."""
    job = _job_or_404(jid)
    clip = next((c for c in job["clips"] if c["id"] == cid), None)
    if not clip:
        raise HTTPException(404, "No such clip")
    if clip.get("status") in ("queued", "rendering") or job.get("status") in ("queued", "running"):
        raise HTTPException(409, "Wait for this clip to finish before adding music.")
    if rights_confirmed != "yes":
        raise HTTPException(400, "Confirm that you have permission to reuse this track in your video.")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"):
        raise HTTPException(400, "Choose an MP3, WAV, M4A, AAC, OGG, or FLAC audio file.")
    attribution = str(attribution).strip()[:500]
    license_url = str(license_url).strip()[:500]
    if license_url:
        parsed = urlparse(license_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise HTTPException(400, "The source or license must be an HTTP or HTTPS link.")
    clips_dir = Path(job["dir"]) / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(8)
    temp = clips_dir / f".{cid}.{token}.part"
    final = clips_dir / f"{cid}.music-{token}{ext}"
    size = 0
    try:
        with temp.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > 25 * 1024 * 1024:
                    raise HTTPException(413, "Music files are limited to 25 MB.")
                out.write(chunk)
        if not size:
            raise HTTPException(400, "Choose an audio file first.")
        info = json.loads(media.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(temp)], timeout=30))
        audio = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)
        duration = float((audio or {}).get("duration") or info.get("format", {}).get("duration") or 0)
        if not audio or not 0 < duration <= 3600:
            raise HTTPException(400, "Choose an audio file up to 60 minutes long.")
        os.replace(temp, final)
        clip.update(music_file=final.name, music_name=Path(file.filename or "Music track").name[:120],
                    music_attribution=attribution, music_license_url=license_url, music_enabled=True,
                    music_volume=clip.get("music_volume", 0.25), source_volume=clip.get("source_volume", 1.0))
        jobs.save(job)
        return {"ok": True, "name": clip["music_name"], "duration": round(duration, 1), "attribution": attribution,
                "license_url": license_url}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Could not read that audio file: {safe.friendly(e, 200)}") from e
    finally:
        temp.unlink(missing_ok=True)
        await file.close()


@app.post("/api/jobs/{jid}/clips/{cid}/overlay")
async def clip_overlay_upload(jid: str, cid: str, file: UploadFile = File(...)):
    """Store a user-provided image overlay for one owned clip."""
    job = _job_or_404(jid)
    clip = next((c for c in job["clips"] if c["id"] == cid), None)
    if not clip:
        raise HTTPException(404, "No such clip")
    if clip.get("status") in ("queued", "rendering") or job.get("status") in ("queued", "running"):
        raise HTTPException(409, "Wait for this clip to finish before adding an image.")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(400, "Choose a PNG, JPEG, or WebP image.")
    d = Path(job["dir"]) / "clips"
    d.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(8)
    temp, final = d / f".{cid}.{token}.part", d / f"{cid}.overlay-{token}{ext}"
    try:
        size = 0
        with temp.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > 8 * 1024 * 1024:
                    raise HTTPException(413, "Images are limited to 8 MB.")
                out.write(chunk)
        if not size:
            raise HTTPException(400, "Choose an image first.")
        from PIL import Image
        with Image.open(temp) as im:
            if im.format not in ("PNG", "JPEG", "WEBP") or im.width < 1 or im.height < 1 or im.width * im.height > 24_000_000:
                raise HTTPException(400, "Choose a valid image no larger than 24 megapixels.")
            im.verify()
        os.replace(temp, final)
        previous = Path(str(clip.get("overlay_file") or "")).name
        clip.update(overlay_file=final.name, overlay_name=Path(file.filename or "Overlay image").name[:120],
                    overlay_scale=clip.get("overlay_scale", 0.24), overlay_x=clip.get("overlay_x", 0.78),
                    overlay_y=clip.get("overlay_y", 0.82))
        jobs.save(job)
        if previous.startswith(f"{cid}.overlay-"):
            (d / previous).unlink(missing_ok=True)
        return {"ok": True, "name": clip["overlay_name"]}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Could not read that image: {safe.friendly(e, 200)}") from e
    finally:
        temp.unlink(missing_ok=True)
        await file.close()


@app.delete("/api/jobs/{jid}")
def delete_job(jid: str):
    job = _job_or_404(jid)
    if job["status"] in ("queued", "running", "live") or jid in live.SESSIONS:
        raise HTTPException(409, "This is still being worked on. Stop it or wait for it to finish first.")
    jobs.delete(jid)
    return {"ok": True}


def _pairs(v, limit=300) -> list:
    """[[video id, clip id], ...] from the page, checked."""
    out = []
    for x in (v if isinstance(v, list) else [])[:limit]:
        if isinstance(x, (list, tuple)) and len(x) == 2 and all(isinstance(y, str) and re.fullmatch(r"[\w\-]{1,60}", y) for y in x):
            out.append((x[0], x[1]))
    return out


@app.delete("/api/jobs/{jid}/clips/{cid}")
def delete_clip(jid: str, cid: str):
    _job_or_404(jid)
    try:
        if not account.delete_clip(jid, cid):
            raise HTTPException(404, "No such clip")
    except account.Busy as e:
        raise HTTPException(409, str(e))
    return {"ok": True}


@app.post("/api/bulk/delete")
def bulk_delete(body: dict = Body(...)):
    _throttle("bulkdel:" + ctx.uid(), 30, 600)
    vids = [x for x in (body.get("videos") if isinstance(body.get("videos"), list) else [])[:300]
            if isinstance(x, str) and re.fullmatch(r"[\w\-]{8,60}", x)]
    return account.delete_many(vids, _pairs(body.get("clips")))


@app.get("/api/clips.zip")
def clips_zip(ids: str = ""):
    """Many clips as one download. `ids` is video.clip pairs separated by commas."""
    _throttle("zip:" + ctx.uid(), 12, 600, "Give it a moment: you just downloaded several groups of clips.")
    pairs = _pairs([p.split(".", 1) for p in ids.split(",") if "." in p][:300])
    try:
        f = account.zip_clips(pairs)
    except ValueError as e:
        raise HTTPException(400, str(e))
    from starlette.background import BackgroundTask
    return FileResponse(f, filename=f"Clipsart-clips-{len(pairs)}.zip", media_type="application/zip",
                        headers={"Cache-Control": "private, no-store"}, background=BackgroundTask(lambda: f.unlink(missing_ok=True)))


@app.delete("/api/creators/{cid}")
def delete_creator(cid: str):
    _throttle("cdel:" + ctx.uid(), 30, 600)
    try:
        r = account.delete_creator(cid)
    except account.Busy as e:
        raise HTTPException(409, str(e))
    if not r.get("ok"):
        raise HTTPException(404, "No such creator")
    return r


@app.post("/api/account/delete")
def delete_my_account(request: Request, body: dict = Body(...)):
    """Deletes the signed-in account and everything in it. The page asks for the email to be typed, so it cannot
    happen by a stray click or a request the person did not mean to make."""
    me_ = _me(request)
    if str(body.get("confirm") or "").strip().lower() != me_.email.lower():
        raise HTTPException(400, "Type your email address exactly to confirm.")
    try:
        account.delete_account(me_.id)
    except account.Busy as e:
        raise HTTPException(409, str(e))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.cookie_args("x")["key"], path="/")
    return resp


@app.get("/media/{jid}/{name}")
def media_file(jid: str, name: str, download: int = 0):
    if not re.fullmatch(r"[\w\-.]+\.(mp4|jpg|mp3|wav|m4a|aac|ogg|flac)", name):
        raise HTTPException(404)
    clips_dir = (Path(_job_or_404(jid)["dir"]) / "clips").resolve()
    f = (clips_dir / name).resolve()
    if not f.is_file() or not f.is_relative_to(clips_dir):
        raise HTTPException(404)
    return FileResponse(f, filename=name if download else None, headers={"Cache-Control": "private, max-age=300"})


# ================================================================ creators and live recording
def _channel_ok(body: dict):
    links = [str(body.get("channel") or "").strip()]
    chs = body.get("channels")
    if chs is not None and not isinstance(chs, dict):
        raise HTTPException(400, "Bad channel list.")
    for plat, url in (chs or {}).items():
        url = str(url or "").strip()
        if url and creators.platform_key(url) != plat:
            raise HTTPException(400, f"That link isn't a {plat.title()} channel.")
        links.append(url)
    for ch in links:
        if ch and not media.site_allowed(live.normalize(ch)):
            raise HTTPException(400, "Channel links must be from YouTube, Twitch or Kick.")


@app.get("/api/admin/email-preview")
def email_preview(request: Request, kind: str = "verify"):
    """What account emails look like, for admins."""
    from . import mailer
    _admin(request)
    if kind == "reset":
        page = mailer.preview("Reset your password", "Someone asked to reset the password for this Clipsart account. If that was you, choose a new one below.",
                              "Choose a new password", config.PUBLIC_URL + "/reset?t=example",
                              "The link works for one hour. If you didn't ask for this, ignore this email and your password stays the same.")
    else:
        page = mailer.preview()
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})


@app.post("/api/admin/test-email")
def test_email(request: Request):
    """Send the confirm-email template to the admin, to check the email service works."""
    from . import mailer
    me_ = _admin(request)
    if not mailer.ready():
        raise HTTPException(400, "No email service is set up yet. Add the CLIPSART_SMTP settings to .env first.")
    mailer.send(me_.email, "Clipsart test email", "Your emails are working",
                "This is a test from your Clipsart server. Account emails like this one will now reach people.",
                "Open Clipsart", config.PUBLIC_URL + "/app", "You can ignore this message.")
    return {"sent_to": me_.email}


@app.post("/api/feedback")
def send_feedback(request: Request, body: dict = Body(...)):
    from . import feedback, mailer
    u = _me(request)
    try:
        auth.throttle("feedback:" + u.id, 10, 3600)
        kind = str(body.get("kind", ""))
        message = str(body.get("message", ""))
        page = str(body.get("page", ""))[:200]
        context = str(body.get("context", ""))[:1000]
        report = feedback.submit(u.id, kind, message, page, context)
        report["email_queued"] = mailer.send_feedback(
            kind if kind in feedback.KINDS else "other", message.strip(), u.email, page, context)
        return report
    except auth.AuthError:
        raise HTTPException(429, "You've sent a lot of messages in the last hour. Try again a bit later.")
    except feedback.Refused as e:
        raise HTTPException(400, str(e))


@app.get("/api/admin/feedback")
def admin_feedback(request: Request, status: str = ""):
    from . import feedback
    _admin(request)
    return feedback.listing(status)


@app.post("/api/admin/feedback/{fid}")
def admin_feedback_status(request: Request, fid: int, body: dict = Body(...)):
    from . import feedback
    _admin(request)
    try:
        feedback.set_status(fid, str(body.get("status", "")))
    except feedback.Refused as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.get("/api/notifications")
def notifications_list():
    from . import notices
    return notices.mine()


@app.post("/api/notifications/read")
def notifications_read():
    from . import notices
    notices.read_all()
    return {"ok": True}


@app.get("/api/me/photo")
def my_photo(request: Request):
    u = _me(request)
    got = auth.photo(u.id) if u else None
    if not got:
        raise HTTPException(404)
    return FileResponse(got[0], media_type=got[1], headers={"Cache-Control": "private, max-age=86400"})


@app.get("/api/channel-preview")
def channel_preview(request: Request, url: str = ""):
    url = url.strip()[:300]
    if not url or not media.site_allowed(live.normalize(url)):
        raise HTTPException(400, "Paste a YouTube, Twitch or Kick channel link.")
    try:
        auth.throttle(f"chanprev:{_me(request).id}", 12, 60)
    except auth.AuthError:
        raise HTTPException(429, "Too many lookups at once. Wait a moment.")
    try:
        return _lookup(profiles.preview, url)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, "Couldn't open that channel. Check the link.")


@app.get("/api/creators/{cid}/avatar")
def creator_avatar(cid: str, p: str = ""):
    c = creators.get(cid)
    if not c:
        raise HTTPException(404)
    key = p if p in creators.PLATFORMS else creators.platform_key(c["channel"])
    prof = (c.get("profiles") or {}).get(key) or {}
    f = creators.root(cid) / f"avatar-{key}.img"
    if not f.is_file() or prof.get("pic") not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(404)
    return FileResponse(f, media_type=prof["pic"], headers={"Cache-Control": "private, max-age=86400"})


@app.get("/api/creators")
def list_creators():
    return _creator_rows()


@app.post("/api/creators")
def new_creator(body: dict = Body(...)):
    _channel_ok(body)
    if len(creators.all_creators()) >= config.MAX_CREATORS:
        raise HTTPException(400, f"This server allows {config.MAX_CREATORS} creators per account.")
    try:
        c = creators.create(body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if c.get("channels"):
        profiles.refresh(c["id"], force=True)
    return c


@app.put("/api/creators/{cid}")
def edit_creator(cid: str, body: dict = Body(...)):
    _throttle("cedit:" + ctx.uid(), 60, 600)
    _channel_ok(body)
    try:
        c = creators.update(cid, body)
    except KeyError:
        raise HTTPException(404, "No such creator")
    except ValueError as e:
        raise HTTPException(400, str(e))
    s = live.active_for(cid)
    if s:
        s.settings = c  # new settings apply to the running recording straight away
    if "channels" in body or "channel" in body:
        profiles.refresh(cid, force=True)
    if body.get("auto_watch") and c.get("auto_watch") and not s:
        live.check_now(cid)    # if they are live right now, recording starts within seconds
    return c


@app.post("/api/creators/{cid}/live")
def go_live(cid: str, body: dict = Body(default={})):
    _need_verified()
    try:
        c = creators.get(cid)
    except ValueError:
        c = None
    if not c:
        raise HTTPException(404, "No such creator")
    # the stream the user is watching, else where they are live right now, else the channel chosen in Setup
    on_air = [p["channel"] for k, p in (c.get("profiles") or {}).items() if p.get("live") and c["channels"].get(k) == p.get("channel")]
    asked = str((body or {}).get("channel") or "")
    url = asked if asked in c["channels"].values() else c["channel"] if c["channel"] in on_air or not on_air else on_air[0]
    try:
        return jobs.public(live.start_session(c, url))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/live/{jid}/stop")
def stop_live(jid: str):
    s = live.mine(jid)
    if not s:
        raise HTTPException(404, "This recording has already ended")
    s.stop()
    return {"ok": True}


@app.post("/api/live/{jid}/clip")
def clip_now(jid: str, body: dict = Body(...)):
    s = live.mine(jid)
    if not s or s.ended:
        raise HTTPException(404, "This recording has already ended")
    _throttle("clipnow:" + ctx.uid(), 6, 60, "Give it a moment: your last clips are still being made.")
    if len(s.manual) >= 3:
        raise HTTPException(429, "Give it a moment: your last clips are still being made.")
    try:
        s.clip_last(max(5, min(180, float(body.get("seconds", 30)))))
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


# ================================================================ AI usage
@app.get("/api/usage")
def ai_usage():
    return usage.summary({c["id"]: c["name"] for c in creators.all_creators()})


# ---------------------------------------------------------------- the AI key and model, set from the dashboard
# Only the owner (or an admin, when accounts are on) reaches these. The key is never sent back to the page.
def _ai_error(e, candidate_key=None) -> str:
    msg = safe.friendly(e, 300)
    for k in (ai.key(), candidate_key):
        if k and isinstance(k, str) and k.strip():
            msg = msg.replace(k, "<key>")
    return msg


@app.get("/api/ai")
def ai_get(request: Request):
    _admin(request)
    return ai.public()


@app.put("/api/ai")
def ai_put(request: Request, body: dict = Body(...)):
    _admin(request)
    k = body.get("key")
    try:
        out = ai.save(body.get("provider"), body.get("models"), body.get("base_url") or "",
                      None if k is None or (isinstance(k, str) and not k.strip() and not body.get("remove_key")) else str(k))
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))
    usage.forget_all()
    ctx.bump()
    return out


@app.post("/api/ai/models")
def ai_models(request: Request, body: dict = Body(default={})):
    _admin(request)
    _throttle("aimodels:" + ctx.uid(), 30, 600)
    try:
        return {"models": ai.list_models(body.get("provider"), body.get("base_url"), body.get("key"))}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        reason = ai.explain(e)
        candidate = body.get("key") if isinstance(body, dict) else None
        raise HTTPException(502, f"The service did not give its list of models. {reason}" if reason else
                            "The service did not give its list of models. Check the key, or type the model yourself. " + _ai_error(e, candidate)[:160])


@app.post("/api/ai/test")
def ai_test(request: Request):
    _admin(request)
    _throttle("aitest:" + ctx.uid(), 20, 600)
    try:
        return ai.test()
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, ai.explain(e) or "The AI did not answer: " + _ai_error(e))


# ================================================================ posting, accounts, settings
@app.get("/api/overview")
def overview():
    return posting.overview()


# ================================================================ analytics
@app.get("/api/analytics")
def get_analytics():
    from . import analytics
    return analytics.summary()


@app.post("/api/analytics/refresh")
def refresh_analytics():
    from . import analytics
    return analytics.refresh()


@app.get("/api/settings")
def get_settings():
    return accounts.public_settings()


@app.put("/api/settings")
def put_settings(body: dict = Body(...)):
    try:
        accounts.save_settings(body)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))
    return accounts.public_settings()


@app.get("/api/accounts")
def list_accounts():
    return accounts.list_accounts()


@app.delete("/api/accounts/{aid}")
def remove_account(aid: str):
    accounts.remove(aid)
    return {"ok": True}


@app.post("/api/accounts/direct")
def account_connect_direct(body: dict = Body(...)):
    """Directly connects a social media account using Fast 1-Click mode or an API token."""
    platform = str(body.get("platform", "")).strip().lower()
    name = str(body.get("name", "")).strip()
    token = str(body.get("token", "")).strip() or "web"
    extra_id = str(body.get("extra_id", "")).strip()
    if platform not in accounts.ALL_PLATFORMS:
        raise HTTPException(400, f"Unsupported platform: {platform}")
    if not name:
        name = f"@{platform}_creator"
    try:
        acc = accounts.connect_direct(platform, name, token, extra_id)
        return {"ok": True, "account": acc}
    except Exception as e:
        raise HTTPException(400, str(e))


# ---------------------------------------------------------------- connecting YouTube, Instagram and TikTok
# Connect sends the browser to the platform's own sign-in page; the platform sends it back here, and the person lands
# on Settings, Connected apps, with the account added (or a message saying what went wrong).
def _back(**q):
    from urllib.parse import urlencode as _ue
    return RedirectResponse("/app/settings/apps?" + _ue(q), 303)


@app.get("/oauth/{platform}/start")
def connect_start(platform: str):
    if platform not in accounts.PLATFORM_NAMES:
        raise HTTPException(404)
    try:
        return RedirectResponse(accounts.connect_url(platform), 303)
    except ValueError as e:
        return _back(connect_error=str(e))


@app.get("/oauth/{platform}/callback")
def connect_callback(platform: str, code: str = "", state: str = "", error: str = "", error_description: str = "",
                     error_reason: str = ""):
    if platform not in accounts.PLATFORM_NAMES:
        raise HTTPException(404)
    name = accounts.PLATFORM_NAMES[platform]
    if error or not code:
        why = "you cancelled" if error in ("access_denied",) or error_reason == "user_denied" else (error_description or error or "no sign-in code came back")
        return _back(connect_error=f"{name} was not connected: {why[:160]}.")
    try:
        _throttle("connect:" + ctx.uid(), 30, 600)
        acc = accounts.connect_finish(platform, code, state)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        return _back(connect_error=f"{name} was not connected: {safe.friendly(e, 240)}")
    return _back(connected=platform, name=acc["name"])


@app.get("/pub/{token}.mp4")
def public_clip(token: str):
    """A clip for a platform to fetch while posting it: one clip, one hour, signed (see accounts.clip_link)."""
    got = accounts.read_clip_link(token)
    if not got:
        raise HTTPException(404)
    uid, job_id, name = got
    with ctx.as_user(uid):
        job = jobs.get(job_id) if re.fullmatch(r"[\w\-]{8,60}", job_id) else None
        f = Path(job["dir"]) / "clips" / name if job else None
    if not f or not f.is_file():
        raise HTTPException(404)
    return FileResponse(f, media_type="video/mp4", headers={"Cache-Control": "private, no-store"})


# ---------------------------------------------------------------- where Clipsart keeps everything (Settings, Storage)
def _on_this_computer(request: Request) -> bool:
    """Is the person sitting at the computer Clipsart runs on? Only then can a folder window be opened for them."""
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1", "localhost") and not config.env("CLIPSART_TRUST_PROXY")


@app.get("/api/storage")
def storage_get(request: Request):
    from . import storage
    _admin(request)
    return storage.info(_on_this_computer(request))


@app.post("/api/storage/open")
def storage_open(request: Request, body: dict = Body(None)):
    from . import storage
    _admin(request)
    if not _on_this_computer(request):
        raise HTTPException(400, "The folder can only be opened on the computer Clipsart runs on.")
    sub = (body or {}).get("sub", "") if isinstance(body, dict) else ""
    try:
        storage.open_folder(sub)
    except OSError as e:
        raise HTTPException(500, "Couldn't open the folder: " + safe.friendly(e, 200))
    return {"ok": True}


@app.get("/api/storage/backup")
def storage_backup(request: Request):
    """Downloads a zip archive containing Clipsart's databases, settings, and account configurations."""
    import io
    import zipfile
    _admin(request)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for fname in ("ai.json", "apps.json", "posts.json", "clipsart.db"):
            fp = config.DATA_DIR / fname
            if fp.is_file():
                z.write(fp, arcname=fname)
        users_dir = config.DATA_DIR / "users"
        if users_dir.is_dir():
            for root, _dirs, files in os.walk(users_dir):
                for f in files:
                    if f.endswith((".json", ".db", ".sqlite")):
                        full_p = Path(root) / f
                        rel_p = full_p.relative_to(config.DATA_DIR)
                        z.write(full_p, arcname=str(rel_p))
    buf.seek(0)
    return Response(content=buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": "attachment; filename=clipsart-backup.zip"})


@app.post("/api/storage/pick")
def storage_pick(request: Request):
    from . import storage
    _admin(request)
    if not _on_this_computer(request):
        raise HTTPException(400, "Type the folder's path instead: a folder window can only be shown on the computer Clipsart runs on.")
    return {"path": storage.pick_folder()}


@app.put("/api/storage")
def storage_put(request: Request, body: dict = Body(...)):
    from . import storage
    _admin(request)
    try:
        if body.get("cancel"):
            storage.cancel_change()
            return storage.info(_on_this_computer(request))
        storage.change(str(body.get("path") or ""), bool(body.get("move", True)))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return storage.info(_on_this_computer(request))


@app.get("/api/apps")
def apps_get(request: Request):
    _admin(request)
    return accounts.apps_public()


@app.put("/api/apps")
def apps_put(request: Request, body: dict = Body(...)):
    _admin(request)
    try:
        return accounts.save_app(str(body.get("platform", "")), body.get("client_id"), body.get("client_secret"))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/posts")
def add_posts(body: dict = Body(...)):
    job = jobs.get(str(body.get("job")))
    clip = next((c for c in job["clips"] if c["id"] == body.get("clip")), None) if job else None
    if not clip or clip.get("status") != "done":
        raise HTTPException(404, "That clip is not ready")
    try:
        made = posting.enqueue(job, clip, [str(a) for a in body.get("accounts", [])][:20], now=bool(body.get("now")),
                               scheduled_at=body.get("scheduled_at"), timezone=body.get("timezone"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not made:
        raise HTTPException(400, "Nothing was queued. Pick at least one account this clip has not already gone to.")
    return {"queued": len(made)}


@app.post("/api/posts/{pid}/{action}")
def post_action(pid: str, action: str):
    try:
        {"cancel": posting.cancel, "retry": posting.retry}[action](pid)
    except KeyError:
        raise HTTPException(404)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


# ================================================================ Google Calendar & iCal Feed
@app.get("/api/calendar/feed.ics")
def calendar_feed(request: Request):
    """RFC 5545 iCalendar feed of the user's scheduled and posted clips for Google Calendar, Apple Calendar, Outlook."""
    from datetime import datetime, timezone
    from fastapi.responses import Response

    mine = posting._mine()
    now_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Clipsart//Content Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Clipsart Content Schedule",
        "X-WR-TIMEZONE:UTC",
    ]

    for p in mine:
        due = p.get("due_at")
        if not due:
            continue
        dt = datetime.fromtimestamp(due, timezone.utc)
        dt_str = dt.strftime("%Y%m%dT%H%M%SZ")
        dt_end = datetime.fromtimestamp(due + 900, timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        job = jobs.get(p.get("job", ""))
        clip = next((c for c in job["clips"] if c["id"] == p.get("clip")), {}) if job else {}

        platform = (p.get("platform") or "Shorts").title()
        title = clip.get("title") or job.get("meta", {}).get("name") or "Clipsart Scheduled Clip"
        title = re.sub(r"[\r\n]+", " ", str(title)).strip()
        hook = clip.get("hook") or ""
        account = p.get("account_name") or ""
        status = p.get("status") or "scheduled"

        desc = f"Hook: {hook}\\nPlatform: {platform}\\nAccount: {account}\\nStatus: {status}"

        lines.extend([
            "BEGIN:VEVENT",
            f"UID:clip-{p['id']}@clipsart",
            f"DTSTAMP:{now_utc}",
            f"DTSTART:{dt_str}",
            f"DTEND:{dt_end}",
            f"SUMMARY:[{platform}] {title}",
            f"DESCRIPTION:{desc}",
            "STATUS:CONFIRMED",
            "END:VEVENT",
        ])

    lines.append("END:VCALENDAR")
    ics_content = "\r\n".join(lines) + "\r\n"
    return Response(content=ics_content, media_type="text/calendar",
                    headers={"Content-Disposition": 'inline; filename="clipsart-schedule.ics"'})


@app.get("/api/calendar/google-url/{pid}")
def calendar_google_url(pid: str, request: Request, redirect: bool = False):
    """Generates a 1-click Google Calendar web event creation link for a scheduled clip."""
    from datetime import datetime, timezone
    from urllib.parse import quote
    from fastapi.responses import RedirectResponse

    mine = posting._mine()
    post = next((p for p in mine if p.get("id") == pid), None)
    if not post or not post.get("due_at"):
        raise HTTPException(404, "Scheduled post not found")

    due = post["due_at"]
    dt = datetime.fromtimestamp(due, timezone.utc)
    dt_start = dt.strftime("%Y%m%dT%H%M%SZ")
    dt_end = datetime.fromtimestamp(due + 900, timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    job = jobs.get(post.get("job", ""))
    clip = next((c for c in job["clips"] if c["id"] == post.get("clip")), {}) if job else {}

    platform = (post.get("platform") or "Shorts").title()
    title = clip.get("title") or (job.get("meta") or {}).get("name") or "Clipsart Scheduled Clip"
    hook = clip.get("hook") or ""
    account = post.get("account_name") or ""

    event_title = f"[{platform}] {title}"
    details = f"Hook: {hook}\nPlatform: {platform}\nAccount: {account}\nStatus: {post.get('status')}"

    url = f"https://calendar.google.com/calendar/render?action=TEMPLATE&text={quote(event_title)}&dates={dt_start}/{dt_end}&details={quote(details)}"
    if redirect or "text/html" in request.headers.get("accept", ""):
        return RedirectResponse(url, status_code=302)
    return {"url": url}


@app.post("/api/alerts/test")
def test_alert():
    if not alerts.configured():
        raise HTTPException(400, "Save a Discord webhook or Telegram details first.")
    auth_problem = None
    try:
        auth.throttle("alert:" + ctx.uid(), 10, 600)
    except auth.AuthError as e:
        auth_problem = str(e)
    if auth_problem:
        raise HTTPException(429, auth_problem)
    problems = alerts.send("Clipsart: test message. Alerts are working.")
    if problems:
        raise HTTPException(400, "; ".join(problems))
    return {"ok": True}


@app.post("/api/alerts/drop/{jid}/{cid}")
def alert_drop_clip(jid: str, cid: str):
    """Manually dispatches an MP4 clip directly into Discord and/or Telegram."""
    job = _job_or_404(jid)
    clip = next((c for c in job["clips"] if c["id"] == cid), None)
    if not clip or clip.get("status") != "done":
        raise HTTPException(404, "Clip not found or not rendered yet")
    clip_path = Path(job["dir"]) / "clips" / clip["file"]
    creator = creators.get(job.get("creator")) or dict(creators.DEFAULTS, name="clips")
    title = clip.get("title") or clip.get("hook") or "New Clip"
    caption = posting._caption(clip, creator)
    problems = alerts.send_clip_drop(clip_path, title, clip.get("hook") or "", caption)
    if problems:
        raise HTTPException(400, "; ".join(problems))
    return {"ok": True, "message": "Clip dropped to community channels!"}


@app.post("/api/integrations/notion/sync/{jid}/{cid}")
def notion_sync_clip(jid: str, cid: str):
    """Creates a card in the user's Notion Kanban database for this clip."""
    job = _job_or_404(jid)
    clip = next((c for c in job["clips"] if c["id"] == cid), None)
    if not clip:
        raise HTTPException(404, "Clip not found")
    try:
        res = notion.sync_clip(
            title=clip.get("title") or clip.get("hook") or "New Clip",
            hook=clip.get("hook") or "",
            status="Ready" if clip.get("status") == "done" else "In Progress",
            duration=float(clip.get("end", 0)) - float(clip.get("start", 0)),
            score=int(clip.get("score") or 0),
            tags=clip.get("hashtags") or [],
        )
        return {"ok": True, "notion": res}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/integrations/notion/test")
def notion_test():
    """Verifies that the Notion token and database ID are valid."""
    if not notion.configured():
        raise HTTPException(400, "Configure your Notion Token and Database ID in Settings first.")
    s = accounts.settings()
    token = s.get("notion_token", "").strip()
    db_id = s.get("notion_database_id", "").strip().replace("-", "")
    try:
        import httpx
        r = httpx.get(f"{notion.NOTION_API}/databases/{db_id}", headers=notion._headers(token), timeout=15)
        if r.status_code >= 400:
            err = r.json().get("message", f"Notion error {r.status_code}")
            raise HTTPException(400, f"Notion error: {err}")
        return {"ok": True, "title": (r.json().get("title") or [{}])[0].get("plain_text", "Notion Database")}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/cloud-sync/export/{jid}/{cid}")
def cloud_sync_export_clip(jid: str, cid: str):
    """Copies a rendered clip and its cover into the configured local cloud sync folder (Google Drive, Dropbox, etc.)."""
    if not cloud_sync.configured():
        raise HTTPException(400, "Configure your Cloud Backup Directory in Settings first.")
    job = _job_or_404(jid)
    clip = next((c for c in job["clips"] if c["id"] == cid), None)
    if not clip or clip.get("status") != "done":
        raise HTTPException(404, "Clip not found or not rendered yet")
    dest = cloud_sync.export_clip(job, clip)
    if not dest:
        raise HTTPException(400, "Could not export clip (check that the folder exists and is writable).")
    return {"ok": True, "path": dest, "message": f"Exported to {Path(dest).name}"}


@app.post("/api/cloud-sync/test")
def cloud_sync_test():
    """Verifies that the configured local cloud sync folder exists and is writable."""
    if not cloud_sync.configured():
        raise HTTPException(400, "Configure your Cloud Backup Directory in Settings first.")
    folder = cloud_sync.get_sync_dir()
    if not folder:
        raise HTTPException(400, "The specified cloud backup folder does not exist or is not accessible.")
    test_file = folder / ".clipsart_test.tmp"
    try:
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
    except Exception as e:
        raise HTTPException(400, f"Cloud folder is not writable: {e}")
    return {"ok": True, "path": str(folder), "message": f"Cloud directory is active and writable: {folder.name}"}


# ================================================================ admin (only accounts marked as admin in the database)
# The gate above already answers "not found" to everyone else; each route checks again so neither can be forgotten.
def _uid_ok(uid: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]{6,40}", uid):
        raise HTTPException(404)
    return uid


@app.get("/api/admin/overview")
def admin_overview(request: Request):
    _admin(request)
    return admins.overview()


@app.get("/api/admin/users/{uid}")
def admin_user(request: Request, uid: str):
    _admin(request)
    try:
        return admins.user_detail(_uid_ok(uid))
    except admins.Refused as e:
        raise HTTPException(e.status, str(e))


@app.post("/api/admin/users/{uid}/disabled")
def admin_disable(request: Request, uid: str, body: dict = Body(...)):
    me_ = _admin(request)
    try:
        return admins.set_disabled(me_, _uid_ok(uid), body.get("disabled"))
    except admins.Refused as e:
        raise HTTPException(e.status, str(e))


@app.post("/api/admin/users/{uid}/delete")
def admin_delete_user(request: Request, uid: str, body: dict = Body(...)):
    me_ = _admin(request)
    target = auth.get_user(_uid_ok(uid))
    if not target:
        raise HTTPException(404, "No such account")
    if target.id == me_.id:
        raise HTTPException(400, "You can't delete your own account from here.")
    if str(body.get("confirm") or "").strip().lower() != target.email.lower():
        raise HTTPException(400, "Type the account's email address exactly to confirm.")
    try:
        account.delete_account(target.id)
    except account.Busy as e:
        raise HTTPException(409, str(e))
    with db.engine.begin() as c:
        admins._log(c, me_.id, "delete", target.id, "account deleted")
    return {"ok": True}


def main():
    print(f"\n  Clipsart is running:  {config.PUBLIC_URL}\n")
    if not config.ACCOUNTS and (config.HTTPS or config.HOST not in ("127.0.0.1", "localhost", "::1")):
        print("  Sign-in is off, so anyone who can reach this address can use Clipsart and its AI key.\n"
              "  On a server other people can reach, set CLIPSART_ACCOUNTS=1 in .env.\n", flush=True)
    if config.env("CLIPSART_AUTO_RELOAD") == "1":
        # restart by itself whenever the server code changes (pages in web/ never need a restart)
        uvicorn.run("studio.server:app", host=config.HOST, port=config.PORT, log_level="warning", backlog=4096, reload=True,
                    reload_dirs=[str(config.ROOT / "studio")], reload_includes=["*.py"],
                    proxy_headers=bool(config.env("CLIPSART_TRUST_PROXY")), forwarded_allow_ips="*")
        return
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="warning", backlog=4096,
                proxy_headers=bool(config.env("CLIPSART_TRUST_PROXY")), forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
