"""Recover a rejected transport paragraph directly from its source notices.

This is formatting of selected evidence, not a replacement for factual validation.
No street, route number or event detail is hard-coded.
"""
import re

from report_rules import transport_link_problems


META_LINE = re.compile(
    r"^[.\s]*(?:деталі\b|тут\b|схеми перекриття\b|розклад руху\b|"
    r"електротранспорту на сайті\b|інформує департамент\b|"
    r"усі інші маршрути\b|зміни у русі транспорту\s*$)", re.I)


def clean_transport_notice(post):
    from groq_report import clean_source_text
    lines = []
    for original in post.get("text", "").splitlines():
        # Link nodes can leave the terminating full stop on a separate line.
        if original.strip().startswith(".") and lines and lines[-1][-1] not in ".!?:;":
            lines[-1] += "."
        line = clean_source_text(original).strip()
        if not re.search(r"[А-Яа-яІіЇїЄєҐґ]", line) or META_LINE.search(line):
            continue
        # An official notice can contain an elliptical cause-only paragraph.
        # Make it a closure statement, without connecting it to another notice.
        if (re.match(r"Через тимчасове перекриття\b", line, re.I)
            and not re.search(r"курсу\w*|змінен\w*|здійсню\w*|руха\w*|перенес\w*", line, re.I)):
            line = re.sub(r"^Через тимчасове перекриття\b", "Тимчасово перекрито", line, flags=re.I)
            line = re.sub(r"\bпроїзної частини\b", "проїзну частину", line, flags=re.I)
        if re.match(r"(?:Сьогодні у .+|Тимчасово) діють зміни у русі громадського транспорту$", line, re.I):
            line += ":"
        lines.append(line)
    text = re.sub(r"\s+([.,;:])", r"\1", " ".join(lines))
    text = re.sub(r"([.!?])\s*\1+", r"\1", text).strip(" .:;—-")
    return text + "." if text else ""


def recover_transport_section(report, posts):
    if not posts or not transport_link_problems(report, posts):
        return report
    notices = []
    for post in sorted(posts, key=lambda p: p.get("published_at", p.get("published_local", ""))):
        if post.get("category_hint") != "1.2":
            continue
        text = clean_transport_notice(post)
        if text and text not in notices:
            notices.append(text)
    if not notices:
        # Keep the invalid draft invalid rather than deleting its facts.
        return report
    body = " Окремо: ".join(notices)
    rebuilt, count = re.subn(r"(?ms)^1\.2\.\s+.*?(?=^1\.3\.)",
                            lambda _: "1.2. " + body + "\n", report)
    if count != 1 or transport_link_problems(rebuilt, posts):
        return report
    print("Source-based transport recovery applied: section 1.2")
    return rebuilt
