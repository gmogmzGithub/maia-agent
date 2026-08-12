"""The minimal Property Document ingestion page (ADR-0010, P-045, P-051, P-052).

One server-rendered page with drag-and-drop upload. It is an ingestion utility,
not a dashboard and not a second conversational interface, and it accepts only
the bounded upload operation.

Protection is one Developer HTTP Basic credential. CORS stays disabled, so this
route is safe even while the separate Meta webhook route is exposed through the
HTTPS tunnel; the webhook authenticates with Meta's signature instead.
"""

from __future__ import annotations

import hmac
import html

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from realestate.config import get_settings
from realestate.domain.properties import AcceptedUpload, PropertyService
from realestate.domain.property_document import MAX_UPLOAD_BYTES, ValidationError

router = APIRouter(tags=["upload"])
_basic = HTTPBasic(auto_error=False)


def require_developer(
    credentials: HTTPBasicCredentials | None = Depends(_basic),
) -> str:
    settings = get_settings()
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Developer credentials required.",
        headers={"WWW-Authenticate": "Basic"},
    )
    if not settings.developer_basic_user or not settings.developer_basic_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DEVELOPER_BASIC_USER / DEVELOPER_BASIC_PASSWORD are not configured.",
        )
    if credentials is None:
        raise unauthorized
    # Compared as bytes: hmac.compare_digest raises TypeError on str inputs that
    # are not pure ASCII, which would turn a bad credential into a 500.
    user_ok = hmac.compare_digest(
        credentials.username.encode("utf-8"), settings.developer_basic_user.encode("utf-8")
    )
    password_ok = hmac.compare_digest(
        credentials.password.encode("utf-8"),
        settings.developer_basic_password.encode("utf-8"),
    )
    if not (user_ok and password_ok):
        raise unauthorized
    return credentials.username


def _page(message: str = "", errors: list[str] | None = None) -> str:
    banner = ""
    if message:
        banner = f'<p class="ok">{html.escape(message)}</p>'
    if errors:
        items = "".join(f"<li>{html.escape(error)}</li>" for error in errors)
        banner = f'<div class="bad"><p>The upload was rejected. Nothing was changed.</p><ul>{items}</ul></div>'

    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<title>Property Document upload</title>
<style>
 body {{ font: 16px/1.5 system-ui, sans-serif; max-width: 46rem; margin: 3rem auto; padding: 0 1rem; }}
 #drop {{ border: 2px dashed #999; border-radius: .5rem; padding: 3rem 1rem; text-align: center; color: #555; }}
 #drop.over {{ border-color: #222; background: #f4f4f4; color: #222; }}
 .ok {{ background: #e7f5e7; border-left: 4px solid #2b8a3e; padding: .75rem 1rem; }}
 .bad {{ background: #fdecea; border-left: 4px solid #c92a2a; padding: .75rem 1rem; }}
 .bad ul {{ margin: .5rem 0 0 1rem; }}
 small {{ color: #666; }}
</style></head>
<body>
<h1>Property Document upload</h1>
{banner}
<form id="form" method="post" action="/upload" enctype="multipart/form-data">
  <div id="drop">
    <p>Drop one <code>.md</code> Property Document here, or choose a file.</p>
    <input id="file" type="file" name="file" accept=".md,text/markdown" required>
  </div>
  <p><button type="submit">Upload</button></p>
</form>
<p><small>One UTF-8 Markdown file, maximum {MAX_UPLOAD_BYTES // 1024} KB. A valid first
upload creates the Property as Active. A valid replacement adds a version and keeps the
current status. An invalid upload changes nothing.</small></p>
<script>
 const drop = document.getElementById('drop'), file = document.getElementById('file');
 for (const type of ['dragenter', 'dragover']) {{
   drop.addEventListener(type, e => {{ e.preventDefault(); drop.classList.add('over'); }});
 }}
 for (const type of ['dragleave', 'drop']) {{
   drop.addEventListener(type, e => {{ e.preventDefault(); drop.classList.remove('over'); }});
 }}
 drop.addEventListener('drop', e => {{
   if (e.dataTransfer.files.length) {{ file.files = e.dataTransfer.files; }}
 }});
</script>
</body></html>"""


@router.get("/upload", response_class=HTMLResponse)
async def upload_page(_: str = Depends(require_developer)) -> HTMLResponse:
    return HTMLResponse(_page())


@router.post("/upload", response_class=HTMLResponse)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    developer: str = Depends(require_developer),
) -> HTMLResponse:
    content = await file.read()

    async with request.app.state.database.session_scope() as session:
        service = PropertyService(session, request.app.state.artifacts)
        try:
            accepted: AcceptedUpload = await service.accept_upload(
                filename=file.filename or "", content=content, actor_id=developer
            )
        except ValidationError as exc:
            # A rejection persists nothing and leaves any current accepted
            # version and status untouched.
            return HTMLResponse(_page(errors=exc.errors), status_code=422)

    return HTMLResponse(_page(message=accepted.summary), status_code=201)
