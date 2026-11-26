"""Dependency-free PDF report generation for Observatory scans."""

import datetime
import textwrap


def _ascii(text):
    replacements = {
        "\u00d7": "x", "\u00f7": "/", "\u2212": "-", "\u2013": "-", "\u2014": "-",
        "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    }
    text = "".join(replacements.get(ch, ch) for ch in str(text))
    return text.encode("ascii", "replace").decode("ascii")


def _escape(text):
    return _ascii(text).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap(line, width=92):
    line = _ascii(line)
    if not line:
        return [""]
    return textwrap.wrap(line, width=width, replace_whitespace=False,
                         drop_whitespace=False) or [""]


def build_pdf(records):
    """Build a valid single- or multi-page PDF and return it as bytes."""
    records = list(records or [])
    lines = ["OBSERVATORY FORMULA REPORT", ""]
    if not records:
        lines.extend(["No saved scans.", ""])

    for index, rec in enumerate(records, 1):
        if len(records) > 1:
            lines.append(f"Scan {index} of {len(records)}")
        lines.append(f"Expression: {rec.get('expression', '')}")

        variables = rec.get("variables", {}) or {}
        if variables:
            values = ", ".join(f"{name} = {value}" for name, value in variables.items())
            lines.append(f"Variables: {values}")
        else:
            lines.append("Variables: none")

        ts = rec.get("ts")
        if ts:
            try:
                stamp = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, OSError, OverflowError):
                stamp = str(ts)
            lines.append(f"Date: {stamp}")

        if rec.get("ok"):
            lines.append(f"Status: Success")
            lines.append(f"Result: {rec.get('result', '')}")
        else:
            error = rec.get("error") or {}
            lines.append(f"Status: Error ({error.get('kind', 'unknown')})")
            lines.append(f"Error: {error.get('message', '')}")

        steps = rec.get("steps", []) or []
        computations = [step for step in steps if step.get("type") == "compute"]
        if computations:
            lines.append("Calculation steps:")
            for step in computations:
                lines.append(f"- {step.get('subexpression', '')}: {step.get('text', '')}")

        tree = rec.get("tree", "")
        if tree:
            lines.append("Expression tree:")
            for tree_line in str(tree).splitlines():
                lines.extend(_wrap(tree_line, 88))
        lines.append("")
        lines.append("-" * 92)
        lines.append("")

    wrapped = []
    for line in lines:
        wrapped.extend(_wrap(line))

    line_height = 14
    lines_per_page = 52
    pages = []
    for start in range(0, max(len(wrapped), 1), lines_per_page):
        pages.append(wrapped[start:start + lines_per_page])

    objects = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(None)  # pages object
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    page_object_ids = []
    content_object_ids = []
    for page_index, page_lines in enumerate(pages):
        content = ["BT", "/F1 10 Tf", "50 790 Td", "14 TL"]
        for line in page_lines:
            content.append(f"({ _escape(line) }) Tj")
            content.append("T*")
        content.append("ET")
        content_bytes = ("\n".join(content) + "\n").encode("ascii")

        content_object_ids.append(len(objects) + 1)
        objects.append(b"<< /Length %d >>\nstream\n" % len(content_bytes) + content_bytes + b"endstream")
        page_object_ids.append(len(objects) + 1)
        objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] "
                       b"/Resources << /Font << /F1 3 0 R >> >> "
                       b"/Contents %d 0 R >>" % content_object_ids[-1])

    objects[1] = (("<< /Type /Pages /Kids [" +
                   " ".join(f"{pid} 0 R" for pid in page_object_ids) +
                   f"] /Count {len(page_object_ids)} >>").encode("ascii"))

    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf.extend(f"{object_id} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(pdf)
