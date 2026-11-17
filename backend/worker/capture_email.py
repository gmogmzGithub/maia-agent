"""Resend's HTTPS transport and escaped HTML shared with the Django fallback."""

import base64
from dataclasses import dataclass
from html import escape

import httpx
from django.conf import settings


@dataclass(frozen=True)
class MailResult:
    status: str
    error: str = ""
    provider_id: str = ""


def email_html(row):
    paragraphs = "".join(
        f'<p style="margin:0 0 18px;line-height:1.6">{escape(part).replace(chr(10), "<br>")}</p>'
        for part in row.body.split("\n\n")
    )
    link = row.attachment.get("review_url", "") or next(
        (
            line.strip()
            for line in row.body.splitlines()
            if line.strip().startswith(settings.PUBLIC_BASE_URL + "/propietarios#")
        ),
        "",
    )
    label = (
        "Revisar mi propiedad y el acuerdo"
        if row.attachment
        else ("Verificar mi email" if "#verify=" in link else "Recuperar mi acceso")
    )
    cta = (
        f'<p style="margin:28px 0"><a style="background:#193b2a;color:white;padding:14px 22px;'
        f'border-radius:8px;text-decoration:none;display:inline-block" href="{escape(link, quote=True)}">'
        f"{label}</a></p>"
        if link
        else ""
    )
    return (
        '<!doctype html><html lang="es"><meta charset="utf-8"><body style="margin:0;background:#f6f7f3;'
        'font-family:Arial,sans-serif;color:#23352c"><main style="max-width:600px;margin:24px auto;'
        'padding:32px;background:white;border-radius:12px"><p style="font-size:24px;font-weight:bold;'
        'color:#193b2a">maia.</p>'
        f'<h1 style="font-size:22px;line-height:1.3">{escape(row.subject)}</h1>{cta}{paragraphs}'
        "</main></body></html>"
    )


def send_resend(row, pdf=None, client=None):
    payload = {
        "from": settings.DEFAULT_FROM_EMAIL,
        "to": [row.recipient],
        "subject": row.subject,
        "text": row.body,
        "html": email_html(row),
        "tags": [{"name": "capture_delivery", "value": str(row.pk)}],
    }
    if pdf is not None:
        payload["attachments"] = [
            {
                "filename": "acuerdo-exclusividad.pdf",
                "content": base64.b64encode(pdf).decode("ascii"),
            }
        ]
    try:
        with (
            httpx.Client(timeout=httpx.Timeout(15, connect=5), follow_redirects=False)
            if client is None
            else client as http
        ):
            response = http.post(
                "https://api.resend.com/emails",
                json=payload,
                headers={
                    "Authorization": "Bearer " + settings.RESEND_API_KEY,
                    "Idempotency-Key": f"capture-mail/{row.pk}/{row.attempts}",
                },
            )
        if response.status_code in {400, 401, 403, 404, 413, 422, 429}:
            return MailResult("failed", f"resend_http_{response.status_code}")
        if not 200 <= response.status_code < 300:
            return MailResult("uncertain", "resend_result_unknown")
        value = response.json()
        provider_id = value.get("id") if isinstance(value, dict) else None
        if not isinstance(provider_id, str) or not 1 <= len(provider_id) <= 128:
            return MailResult("uncertain", "resend_receipt_missing")
        return MailResult("sent", provider_id=provider_id)
    except httpx.ConnectError:
        return MailResult("failed", "connection_failed")
    except Exception:
        # Never expose response bodies, request headers, tokens or message contents.
        return MailResult("uncertain", "resend_result_unknown")
