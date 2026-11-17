"""Normalize uploads before storing; originals and EXIF never become public."""

import io
import warnings

from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener
from pypdf import PdfReader

register_heif_opener(thumbnails=False)
Image.MAX_IMAGE_PIXELS = 100_000_000
MAX_UPLOAD = 256 * 1024 * 1024


def normalize_upload(upload, kind):
    if upload.size > MAX_UPLOAD:
        raise ValueError(
            "No pudimos procesar este archivo. Intenta otra foto de la misma propiedad."
        )
    upload.seek(0)
    if kind == "plan" and upload.read(5) == b"%PDF-":
        upload.seek(0)
        if upload.size > 20 * 1024 * 1024:
            raise ValueError("El plano PDF debe pesar menos de 20 MB.")
        try:
            pdf = PdfReader(upload)
            if pdf.is_encrypted or not 1 <= len(pdf.pages) <= 50:
                raise ValueError("Usa un PDF sin contraseña y con hasta 50 páginas.")
        except Exception as exc:
            raise ValueError("No pudimos leer este plano PDF.") from exc
        upload.seek(0)
        return ContentFile(upload.read()), "application/pdf", "pdf"
    upload.seek(0)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(upload) as source:
                source.seek(0)
                source.draft("RGB", (2400, 2400))
                image = ImageOps.exif_transpose(source)
                image.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
                if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
                    rgba = image.convert("RGBA")
                    white = Image.new("RGB", rgba.size, "white")
                    white.paste(rgba, mask=rgba.getchannel("A"))
                    image = white
                else:
                    image = image.convert("RGB")
                image.info.clear()
                for quality in (85, 75, 65):
                    output = io.BytesIO()
                    image.save(output, format="WEBP", quality=quality, method=4, exif=b"", xmp=b"")
                    if output.tell() <= 800_000:
                        break
                while output.tell() > 800_000 and max(image.size) > 1000:
                    image.thumbnail(
                        (int(image.width * 0.8), int(image.height * 0.8)), Image.Resampling.LANCZOS
                    )
                    output = io.BytesIO()
                    image.save(output, format="WEBP", quality=65, method=4, exif=b"", xmp=b"")
                return ContentFile(output.getvalue()), "image/webp", "webp"
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValueError(
            "No pudimos leer esta imagen. Prueba otra foto; las demás se conservaron."
        ) from exc
