"""
pdf_report.py - turns already-gathered report data (services/reports.py) into PDF bytes with reportlab.

This file only lays things out; it never decides what belongs in a report, what a person may see, or whether a
value is real - see services/reports.py for that. Colors match static/css/tokens.css so a downloaded report reads
like the rest of Nephron, not a generic template.
"""
import io

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

NAVY = colors.HexColor("#0C0D35")
MUTED = colors.HexColor("#56608A")
BORDER = colors.HexColor("#E7E9F7")
SURFACE_SOFT = colors.HexColor("#F6F7FC")
INDIGO = colors.HexColor("#302B91")
GREEN_TEXT = colors.HexColor("#06775F")
RED_TEXT = colors.HexColor("#B3203F")

_styles = getSampleStyleSheet()
TITLE = ParagraphStyle("NephronTitle", parent=_styles["Title"], textColor=INDIGO, fontSize=20, spaceAfter=2)
SUBTITLE = ParagraphStyle("NephronSubtitle", parent=_styles["Normal"], textColor=MUTED, fontSize=10, spaceAfter=0)
H2 = ParagraphStyle("NephronH2", parent=_styles["Heading2"], textColor=NAVY, fontSize=13, spaceBefore=10, spaceAfter=4)
BODY = ParagraphStyle("NephronBody", parent=_styles["Normal"], textColor=NAVY, fontSize=10, leading=14)
MUTED_BODY = ParagraphStyle("NephronMutedBody", parent=_styles["Normal"], textColor=MUTED, fontSize=9, leading=13)
BIG_NUMBER = ParagraphStyle("NephronBigNumber", parent=_styles["Normal"], textColor=NAVY, fontSize=26, leading=28)
DISCLAIMER = ParagraphStyle("NephronDisclaimer", parent=_styles["Normal"], textColor=MUTED, fontSize=8, leading=11, alignment=TA_CENTER)


def _escape(text):
    """
    Every piece of dynamic text in this module passes through this before reaching a Paragraph. Two reasons:
    1. Paragraph markup is a small XML dialect - an unescaped '&', '<' or '>' in real data (a clinical review note
       is free text a professional typed, the one place in a report that is not a controlled vocabulary) would
       break rendering, not just look wrong.
    2. The standard PDF fonts this module uses have no glyph at all for U+00B2 (as in 1.73m\u00b2, an eGFR unit) - it
       would otherwise render as a silent gap. <super> is real markup reportlab understands, so the substitution
       must run AFTER escaping, never before (or its own '<' and '>' would be escaped right back to text).
    A plain (non-Paragraph) Table cell never parses markup at all - passed a raw string, reportlab shows it
    literally, tags and all - so a value only needs this when it is going into a Paragraph.
    """
    text = str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return text.replace("\u00b2", "<super rise=4 size=6>2</super>")


def _classification_color(classification):
    return RED_TEXT if classification == "high" else GREEN_TEXT


def _rule():
    return HRFlowable(width="100%", thickness=0.75, color=BORDER, spaceBefore=4, spaceAfter=4)


def _header(patient_name, patient_email, generated_at_text):
    return [
        Paragraph("Nephron Screening Report", TITLE),
        Paragraph(f"{_escape(patient_name)} &middot; {_escape(patient_email)}", SUBTITLE),
        Spacer(1, 2 * mm),
        Paragraph(f"Generated {_escape(generated_at_text)}", MUTED_BODY),
        Spacer(1, 3 * mm),
        _rule(),
    ]


def _disclaimer_footer(disclaimer_text):
    return [Spacer(1, 6 * mm), _rule(), Spacer(1, 2 * mm), Paragraph(_escape(disclaimer_text), DISCLAIMER)]


def _cell(text, style=BODY):
    """A table cell that gets the same escaping and superscript treatment as a Paragraph, instead of the plain,
    literal text a raw string would render as."""
    return Paragraph(_escape(text), style)


def _answers_table(answers):
    """answers: the same (title, rows) pairs screening_contract.describe_inputs()/lab_contract.describe_lab_values()
    return - one small table per named group, so a group never splits awkwardly across a page (KeepTogether)."""
    label_style = ParagraphStyle("NephronAnswerLabel", parent=BODY, textColor=MUTED)
    value_style = ParagraphStyle("NephronAnswerValue", parent=BODY, textColor=NAVY)
    blocks = []
    for title, rows in answers:
        table = Table([[_cell(label, label_style), _cell(text, value_style)] for label, text in rows], colWidths=[70 * mm, 90 * mm],
                      style=TableStyle([
                          ("FONTSIZE", (0, 0), (-1, -1), 9),
                          ("LINEBELOW", (0, 0), (-1, -2), 0.4, BORDER),
                          ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                      ]))
        blocks.append(KeepTogether([Paragraph(_escape(title), H2), table]))
    return blocks


def _factors_table(factors):
    style = ParagraphStyle("NephronFactor", parent=BODY, textColor=NAVY, fontSize=9)
    return Table([[_cell(f, style)] for f in factors], colWidths=[160 * mm],
                style=TableStyle([("BOTTOMPADDING", (0, 0), (-1, -1), 2), ("TOPPADDING", (0, 0), (-1, -1), 2)]))


def _reviews_block(reviews):
    if not reviews:
        return []
    rows = []
    for review in reviews:
        meta = _escape(review["professional_name"]) + (f" &middot; {_escape(review['profession_title'])}" if review.get("profession_title") else "") \
            + f" &middot; {review['date']:%b} {review['date'].day}, {review['date'].year}"
        rows.append(Paragraph(f"<b>{meta}</b><br/>{_escape(review['note'])}", BODY))
        rows.append(Spacer(1, 2 * mm))
    return [Paragraph("Notes from your professional", H2), *rows]


def build_assessment_report(data):
    """
    data: {patient_name, patient_email, generated_at_text, record: {date_text, type, probability_text,
    classification, classification_text, threshold_text, what_this_means}, answers, factors_up, factors_down,
    reviews (possibly empty), disclaimer}
    Returns PDF bytes.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=18 * mm, bottomMargin=18 * mm, leftMargin=20 * mm, rightMargin=20 * mm,
                            title="Nephron Screening Report")
    record = data["record"]
    story = _header(data["patient_name"], data["patient_email"], data["generated_at_text"])
    story += [
        Paragraph(f"{_escape(record['date_text'])} &middot; {_escape(record['type'])}", H2),
        Table([[Paragraph(f"<b>{_escape(record['probability_text'])}</b>", BIG_NUMBER),
              Paragraph(f"<font color='{_classification_color(record['classification']).hexval()}'><b>{_escape(record['classification_text'])}</b></font>"
                       f"<br/>{_escape(record['what_this_means'])}<br/>{_escape(record['threshold_text'])}", BODY)]],
             colWidths=[45 * mm, 115 * mm], style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")])),
        Spacer(1, 3 * mm),
    ]
    if data["factors_up"] or data["factors_down"]:
        story.append(Paragraph("What raised your estimate", H2))
        story.append(_factors_table(data["factors_up"]))
        story.append(Paragraph("What lowered your estimate", H2))
        story.append(_factors_table(data["factors_down"]))
    story += _reviews_block(data["reviews"])
    story.append(Paragraph("Your answers", H2))
    story += _answers_table(data["answers"])
    story += _disclaimer_footer(data["disclaimer"])
    doc.build(story)
    return buf.getvalue()


def build_history_report(data):
    """
    data: {patient_name, patient_email, generated_at_text, rows: [{date_text, type, probability_text,
    classification, classification_text}], reviews_by_assessment: {assessment_id: [...]} (possibly empty), disclaimer}
    Returns PDF bytes.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=18 * mm, bottomMargin=18 * mm, leftMargin=20 * mm, rightMargin=20 * mm,
                            title="Nephron Assessment History")
    story = _header(data["patient_name"], data["patient_email"], data["generated_at_text"])
    story.append(Paragraph("Assessment history", H2))
    header_style = ParagraphStyle("NephronTableHeader", parent=BODY, textColor=NAVY, fontName="Helvetica-Bold")
    plain_style = ParagraphStyle("NephronTableCell", parent=BODY, textColor=NAVY)
    table_rows = [[_cell("Date", header_style), _cell("Type", header_style), _cell("Predicted risk", header_style), _cell("Classification", header_style)]]
    for row in data["rows"]:
        color = _classification_color(row["classification"])
        table_rows.append([_cell(row["date_text"], plain_style), _cell(row["type"], plain_style), _cell(row["probability_text"], plain_style),
                          Paragraph(f"<font color='{color.hexval()}'>{_escape(row['classification_text'])}</font>", BODY)])
    story.append(Table(table_rows, colWidths=[35 * mm, 40 * mm, 35 * mm, 50 * mm],
                       style=TableStyle([("BACKGROUND", (0, 0), (-1, 0), SURFACE_SOFT), ("FONTSIZE", (0, 0), (-1, -1), 9),
                                        ("GRID", (0, 0), (-1, -1), 0.4, BORDER), ("TOPPADDING", (0, 0), (-1, -1), 4),
                                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4)])))
    if data["reviews_by_assessment"]:
        story.append(PageBreak())
        story.append(Paragraph("Notes from your professional", H2))
        for row in data["rows"]:
            reviews = data["reviews_by_assessment"].get(row["assessment_id"], [])
            if not reviews:
                continue
            story.append(Paragraph(f"<b>{_escape(row['date_text'])} &middot; {_escape(row['type'])}</b>", BODY))
            story += _reviews_block(reviews)[1:]        # skip the repeated "Notes from your professional" heading
            story.append(Spacer(1, 3 * mm))
    story += _disclaimer_footer(data["disclaimer"])
    doc.build(story)
    return buf.getvalue()
