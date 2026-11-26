"""The PDF of a processing report (workflow_report.py): a summary, the programs and versions, the methods text when
there is one, the steps in order with what each takes, and each protocol's parameters, outputs and last run.

Written with reportlab, imported only here so that the API starts without it (the report then says it is missing).
"""
from io import BytesIO
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape

DATA_NOTE = ("Every figure in this report (parameters, sizes, dates, versions) is read from the project's records. "
             "The workflow file next to it holds the same protocols with the same parameters: import it in "
             "ScipionWeb (Workflows, Import) or in Scipion to run them again, with the plugins listed below "
             "installed.")
METHODS_NOTE = ("Written by the AI assistant from the figures of this report; check it before using it.")


class ReportUnavailable(RuntimeError):
    """The PDF cannot be written here (the library for it is not installed)."""


def _text(value: Any) -> str:
    return escape(str(value if value is not None else ""))


def _when(value: Optional[str]) -> str:
    return str(value or "")[:16].replace("T", " ")


def _md5WithoutSecurityFlag(pdfdoc) -> None:
    """reportlab asks md5 for usedforsecurity=False, which some Pythons (3.8 built against some OpenSSLs) refuse:
    there it is asked without it (it only names the document, it protects nothing)."""
    import hashlib

    try:
        pdfdoc.md5(usedforsecurity=False)
    except TypeError:
        pdfdoc.md5 = lambda *args, usedforsecurity=True, **kwargs: hashlib.md5(*args, **kwargs)


def render(report: Dict[str, Any], methods: Optional[str] = None, version: str = "") -> bytes:
    try:
        from reportlab.pdfbase import pdfdoc

        _md5WithoutSecurityFlag(pdfdoc)
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
        )
    except ImportError:
        raise ReportUnavailable("The server cannot write PDFs: its administrator has to install reportlab "
                                "(pip install reportlab), or update ScipionWeb")

    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9.5, leading=12.5)
    small = ParagraphStyle("small", parent=body, fontSize=8.5, leading=10.5, textColor=colors.HexColor("#444b57"))
    cell = ParagraphStyle("cell", parent=body, fontSize=8.5, leading=10.5)
    h1 = ParagraphStyle("h1", parent=styles["Title"], fontSize=17, leading=21, alignment=0, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12.5, leading=15, spaceBefore=10, spaceAfter=4,
                        textColor=colors.HexColor("#333d49"))
    h3 = ParagraphStyle("h3", parent=styles["Heading3"], fontSize=10.5, leading=13, spaceBefore=8, spaceAfter=3)
    grid = TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9ced6")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f5")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ])

    def table(rows: List[List[Any]], widths: List[float]) -> Table:
        data = [[Paragraph(_text(value).replace("\n", "<br/>"), cell) for value in row] for row in rows]
        built = Table(data, colWidths=widths, repeatRows=1)
        built.setStyle(grid)
        return built

    width = A4[0] - 36 * mm
    story: List[Any] = []
    title = "Processing report: %s" % report["project"]
    if report.get("upTo"):
        title += " (up to protocol #%s)" % report["upTo"]
    story.append(Paragraph(_text(title), h1))
    story.append(Paragraph(_text("Generated %s by ScipionWeb%s from project %s." % (
        _when(report.get("generatedAt")), " " + version if version else "", report["projectId"])), small))
    if report.get("description"):
        story.append(Spacer(1, 4))
        story.append(Paragraph(_text(report["description"]), body))
    story.append(Spacer(1, 6))
    story.append(Paragraph(_text(DATA_NOTE), small))

    story.append(Paragraph("Programs", h2))
    programs = sorted((report.get("programs") or {}).items())
    if programs:
        story.append(table([["Plugin package", "Version"]] + [[name, version_ or "?"] for name, version_ in programs],
                           [width * 0.6, width * 0.4]))
    else:
        story.append(Paragraph("The plugins of these protocols could not be read.", body))

    if methods:
        story.append(Paragraph("Methods", h2))
        story.append(Paragraph(_text(METHODS_NOTE), small))
        story.append(Spacer(1, 3))
        for paragraph in [part.strip() for part in methods.split("\n\n") if part.strip()]:
            story.append(Paragraph(_text(paragraph).replace("\n", " "), body))
            story.append(Spacer(1, 4))

    story.append(Paragraph("Workflow", h2))
    steps = [["#", "Protocol", "Takes", "Status"]]
    for protocol in report["protocols"]:
        takes = ", ".join("#%s %s" % (item["protocolId"], item["output"]) for item in protocol["inputs"]) or "-"
        steps.append([protocol["protocolId"], "%s\n%s" % (protocol["label"], protocol["protocol"]), takes,
                      protocol["status"]])
    story.append(table(steps, [width * 0.07, width * 0.43, width * 0.35, width * 0.15]))

    story.append(Paragraph("Protocols", h2))
    for protocol in report["protocols"]:
        block: List[Any] = [Paragraph(_text("#%s %s" % (protocol["protocolId"], protocol["label"])), h3)]
        facts = "%s (%s)" % (protocol["protocol"], protocol["className"])
        if protocol.get("package"):
            facts += ", %s %s" % (protocol["package"], protocol.get("version") or "")
        facts += ". Status: %s." % protocol["status"]
        run = protocol.get("run")
        if run:
            where = ", ".join(part for part in (
                run.get("host") and "on %s" % run["host"], run.get("queue") and "queue %s" % run["queue"],
                run.get("gpus") and "%s GPU" % run["gpus"], run.get("threads") and "%s threads" % run["threads"],
                run.get("mpi") and "%s MPI" % run["mpi"]) if part)
            facts += " Last run %s to %s%s." % (_when(run.get("started")), _when(run.get("ended")) or "?",
                                                 ", " + where if where else "")
        block.append(Paragraph(_text(facts), small))
        if protocol["inputs"]:
            block.append(Paragraph(_text("Inputs: " + "; ".join(
                "%s from #%s %s" % (item["input"], item["protocolId"], item["output"])
                for item in protocol["inputs"])), small))
        block.append(Spacer(1, 3))
        story.append(KeepTogether(block))
        if protocol["params"]:
            story.append(table([["Section", "Parameter", "Value"]] + [
                [item["section"], item["label"], item["value"]] for item in protocol["params"]],
                [width * 0.2, width * 0.45, width * 0.35]))
        if protocol["outputs"]:
            story.append(Spacer(1, 3))
            story.append(table([["Output", "Type", "Items"]] + [
                [item["name"], item["type"], "" if item["size"] is None else item["size"]]
                for item in protocol["outputs"]], [width * 0.4, width * 0.4, width * 0.2]))

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#6b7280"))
        canvas.drawString(18 * mm, 10 * mm, "%s - page %d" % (title[:90], document.page))
        canvas.restoreState()

    buffer = BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                                 bottomMargin=16 * mm, title=title, author="ScipionWeb")
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
