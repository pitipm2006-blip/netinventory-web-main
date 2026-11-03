"""Exportación de reportes (Sprint 7): CSV seguro y PDF."""
import csv
import io
from datetime import datetime

_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")


def sanitize_cell(value) -> str:
    """Evita inyección de fórmulas al abrir el CSV en Excel/Calc."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_DANGEROUS) else text


def to_csv(headers: list[str], rows: list[list]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([sanitize_cell(cell) for cell in row])
    return "\ufeff" + buffer.getvalue()  # BOM para acentos en Excel


def to_pdf(title: str, headers: list[str], rows: list[list]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = io.BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=landscape(A4), title=title)
    styles = getSampleStyleSheet()
    data = [headers] + [["" if c is None else str(c)[:40] for c in row] for row in rows]
    table = Table(data, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
            ]
        )
    )
    document.build(
        [
            Paragraph(title, styles["Title"]),
            Paragraph(f"Generado: {datetime.now():%Y-%m-%d %H:%M} · {len(rows)} registros", styles["Normal"]),
            Spacer(1, 12),
            table,
        ]
    )
    return buffer.getvalue()
