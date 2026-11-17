"""Immutable approval snapshots and deterministic PDF copies for owner review."""

from io import BytesIO
from xml.sax.saxutils import escape

from django.conf import settings
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from datalayer.capture_approval import commercial_data
from datalayer.capture_catalog import CONTRACT_TEXT, CONTRACT_VERSION, KINDS


def contract_snapshot(capture, agreement=None):
    data = commercial_data(agreement.snapshot if agreement else capture.data)
    result = {
        "kind": "capture_contract",
        "capture_id": str(capture.pk),
        "revision": capture.revision,
        "data": data,
        "reviewed_at": capture.verified_at.isoformat() if capture.verified_at else None,
        "version": agreement.version if agreement else CONTRACT_VERSION,
        "text": agreement.text if agreement else CONTRACT_TEXT,
        "issued_at": timezone.localtime(
            agreement.accepted_at if agreement else timezone.now()
        ).strftime("%d/%m/%Y %H:%M"),
        "name": data.get("name", ""),
        "title": data.get("title") or KINDS[data["kind"]][0],
        "address": ", ".join(
            str(data.get(k) or "")
            for k in (
                "private_address",
                "location_reference",
                "neighborhood",
                "municipality",
                "state",
            )
            if data.get(k)
        ),
        "operation": "Preventa"
        if data.get("is_presale")
        else ("Venta" if data.get("operation") == "sale" else "Renta"),
        "review_url": f"{settings.PUBLIC_BASE_URL.rstrip('/')}/propietarios?capture={capture.pk}",
    }
    if agreement:
        result["accepted_at"] = timezone.localtime(agreement.accepted_at).strftime("%d/%m/%Y %H:%M")
        result["expires_at"] = timezone.localtime(agreement.expires_at).strftime("%d/%m/%Y %H:%M")
        result["ended_at"] = (
            timezone.localtime(agreement.ended_at).strftime("%d/%m/%Y %H:%M")
            if agreement.ended_at
            else ""
        )
    return result


def contract_pdf(snapshot):
    """Build from the queued snapshot, not a mutable capture or current template."""
    output = BytesIO()
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="ContractTitle",
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=25,
            textColor=colors.HexColor("#193b2a"),
            spaceAfter=12,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ContractBody",
            fontName="Helvetica",
            fontSize=11,
            leading=17,
            spaceAfter=10,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ContractNotice",
            parent=styles["ContractBody"],
            fontName="Helvetica-Bold",
            textColor=colors.HexColor("#775523"),
            backColor=colors.HexColor("#fbf4df"),
            borderPadding=10,
            spaceAfter=18,
        )
    )
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=22 * mm,
        leftMargin=22 * mm,
        topMargin=22 * mm,
        bottomMargin=22 * mm,
        title="Maia - Acuerdo de exclusividad de demostración",
        author="Maia",
    )
    body = []

    def paragraph(text, style="ContractBody"):
        body.append(Paragraph(escape(str(text)).replace("\n", "<br/>"), styles[style]))

    paragraph("MAIA", "Heading2")
    paragraph("Acuerdo de exclusividad", "ContractTitle")
    paragraph(
        "DEMOSTRACIÓN - ACEPTACIÓN REGISTRADA EN LA PLATAFORMA"
        if snapshot.get("accepted_at")
        else "DEMOSTRACIÓN - COPIA PARA REVISIÓN - SIN ACEPTAR",
        "ContractNotice",
    )
    for label, key in [
        ("Propietario o representante", "name"),
        ("Inmueble", "title"),
        ("Ubicación", "address"),
        ("Operación", "operation"),
        ("Solicitud", "capture_id"),
        ("Versión del contrato", "version"),
        ("Copia emitida", "issued_at"),
    ]:
        paragraph(f"{label}: {snapshot[key]}")
    body.append(Spacer(1, 5 * mm))
    paragraph("Condiciones de la exclusividad", "Heading2")
    paragraph(snapshot["text"])
    if snapshot.get("accepted_at"):
        paragraph(
            f"Aceptación registrada: {snapshot['accepted_at']}. Vencimiento pactado: {snapshot['expires_at']}."
        )
        if snapshot.get("ended_at"):
            paragraph(
                f"Acuerdo terminado: {snapshot['ended_at']}. Esta copia conserva el historial; no acredita exclusividad vigente."
            )
    paragraph(
        "Duración: seis meses calendario desde la aceptación en la plataforma. "
        "Recibir este documento o abrir la liga no registra aceptación. "
        "La publicación requiere la aceptación del propietario y la acción posterior del equipo."
    )
    paragraph(
        "Consulta en la plataforma" if snapshot.get("accepted_at") else "Cómo continuar", "Heading2"
    )
    paragraph(
        "Esta copia conserva el contenido aceptado. Consulta el estado vigente de la solicitud en tu cuenta."
        if snapshot.get("accepted_at")
        else "Entra con tu cuenta, revisa la solicitud y el acuerdo vigente y pulsa Aceptar exclusividad."
    )
    body.append(
        Paragraph(
            f'<link href="{escape(snapshot["review_url"], {chr(34): "&quot;"})}" color="#193b2a">'
            "Abrir esta solicitud en Mis propiedades</link>",
            styles["ContractBody"],
        )
    )
    paragraph(
        "Si el equipo corrige la solicitud, revisa la nueva versión en el portal antes de aceptar."
    )

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 9)
        canvas.setFillColor(colors.HexColor("#68746c"))
        canvas.drawCentredString(
            A4[0] / 2, 12 * mm, f"Maia | Contrato dummy | Página {document.page}"
        )
        canvas.restoreState()

    doc.build(body, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
