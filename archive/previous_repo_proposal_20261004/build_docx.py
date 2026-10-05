import os
import re
import shutil
import zipfile
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "template")

HEAD = """<?xml version='1.0' encoding='UTF-8' standalone='yes'?>
<w:document xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas" xmlns:mo="http://schemas.microsoft.com/office/mac/office/2008/main" xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" xmlns:mv="urn:schemas-microsoft-com:mac:vml" xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:w10="urn:schemas.microsoft-com:office:word" xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup" xmlns:wpi="http://schemas.microsoft.com/office/word/2010/wordprocessingInk" xmlns:wne="http://schemas.microsoft.com/office/word/2006/wordml" xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" mc:Ignorable="w14 wp14"><w:body>"""

SECT = ('<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1247" '
        'w:header="720" w:footer="720" w:gutter="0"/><w:cols w:space="720"/>'
        '<w:docGrid w:linePitch="360"/></w:sectPr>')

USABLE = 9859


def rpr(bold=False, italic=False, sz=None, mono=False, lang="en-US"):
    parts = []
    if mono:
        parts.append('<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:eastAsia="SimSun"/>')
    if bold:
        parts.append("<w:b/>")
    if italic:
        parts.append("<w:i/>")
    if sz:
        parts.append(f'<w:sz w:val="{sz}"/><w:szCs w:val="{sz}"/>')
    parts.append(f'<w:lang w:val="{lang}" w:eastAsia="zh-CN"/>')
    return "<w:rPr>" + "".join(parts) + "</w:rPr>" if parts else ""


def runs(text, **kw):
    out = []
    for i, chunk in enumerate(text.split("~~")):
        if i:
            out.append(f'<w:r>{rpr(**kw)}<w:br/></w:r>')
        out.append(f'<w:r>{rpr(**kw)}<w:t xml:space="preserve">{escape(chunk)}</w:t></w:r>')
    return "".join(out)


def para(text, ppr, **kw):
    return f"<w:p><w:pPr>{ppr}</w:pPr>{runs(text, **kw)}</w:p>"


def build(content_path, out_path, lang, title, subject, pages):
    lines = [l.rstrip("\n") for l in open(content_path, encoding="utf-8")]
    body = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        tag, _, val = line.partition("|")
        if tag == "TBLW":
            widths = [int(x) for x in val.split(",")]
            fs = 16
            rows = []
            i += 1
            while i < len(lines) and lines[i].startswith("TR|"):
                rows.append([c for c in lines[i][3:].split("||")])
                i += 1
            body.append(table(rows, widths, fs, lang))
            continue
        if tag == "TR":
            widths = [USABLE // 4] * 4
            rows = []
            while i < len(lines) and lines[i].startswith("TR|"):
                rows.append([c for c in lines[i][3:].split("||")])
                i += 1
            body.append(table(rows, widths, 16, lang))
            continue
        if tag == "PRE":
            pre = []
            while i < len(lines) and lines[i].startswith("PRE|"):
                pre.append(lines[i][4:])
                i += 1
            for pline in pre:
                body.append(para(pline if pline.strip() else " ",
                                 '<w:spacing w:after="0" w:line="200" w:lineRule="auto"/>',
                                 sz=16, mono=True, lang=lang))
            continue
        common = {"en-US": "en-US", "ru": "ru-RU", "zh": "en-US"}[lang] if False else lang
        if tag == "PAGE":
            body.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
        elif tag == "T":
            body.append(para(val, '<w:spacing w:after="40"/><w:jc w:val="center"/>',
                             bold=True, sz=40, lang=common))
        elif tag == "S":
            body.append(para(val, '<w:spacing w:after="40"/><w:jc w:val="center"/>',
                             bold=True, sz=26, lang=common))
        elif tag == "I":
            body.append(para(val, '<w:spacing w:after="320"/><w:jc w:val="center"/>',
                             italic=True, sz=21, lang=common))
        elif tag == "H1":
            body.append(para(val, '<w:keepNext/><w:spacing w:before="200" w:after="120"/>',
                             bold=True, sz=27, lang=common))
        elif tag == "H2":
            body.append(para(val, '<w:keepNext/><w:spacing w:before="120" w:after="100"/>',
                             bold=True, sz=23, lang=common))
        elif tag == "P":
            body.append(para(val, '<w:spacing w:after="120"/><w:jc w:val="both"/>', lang=common))
        elif tag == "B":
            if "||" in val:
                lead, rest = val.split("||", 1)
            else:
                m = re.search(r"\s\|\s*", val)
                if m:
                    lead, rest = val[:m.start()], val[m.end():]
                else:
                    lead, rest = None, val
            if lead is not None and not lead.endswith(" ") and not (lang == "zh-CN" and lead.endswith("。")):
                lead += " "
            if lead is None:
                body.append(para(rest,
                                 '<w:pStyle w:val="ListBullet"/><w:spacing w:after="60"/><w:jc w:val="both"/>',
                                 lang=common))
            else:
                ppr = '<w:pStyle w:val="ListBullet"/><w:spacing w:after="60"/><w:jc w:val="both"/>'
                body.append("<w:p><w:pPr>" + ppr + "</w:pPr>"
                            + runs(lead, bold=True, lang=common)
                            + runs(rest, lang=common) + "</w:p>")
        else:
            raise SystemExit(f"unknown tag {tag!r} in {content_path}: {line[:80]}")
        i += 1

    doc = HEAD + "".join(body) + SECT + "</w:body></w:document>"
    work = out_path + ".work"
    if shutil.os.path.exists(work):
        shutil.rmtree(work)
    shutil.copytree(SRC, work)
    with open(work + "/word/document.xml", "w", encoding="utf-8") as f:
        f.write(doc)
    core = open(work + "/docProps/core.xml", encoding="utf-8").read()
    core = re.sub(r"<dc:title>.*?</dc:title>", f"<dc:title>{escape(title)}</dc:title>", core, flags=re.S)
    core = re.sub(r"<dc:subject>.*?</dc:subject>", f"<dc:subject>{escape(subject)}</dc:subject>", core, flags=re.S)
    core = re.sub(r"<dc:language>.*?</dc:language>", "", core)
    if "</cp:coreProperties>" in core and "<dc:language>" not in core:
        core = core.replace("</cp:coreProperties>", f"<dc:language>{lang}</dc:language></cp:coreProperties>")
    with open(work + "/docProps/core.xml", "w", encoding="utf-8") as f:
        f.write(core)
    plain = re.sub(r"<[^>]+>", "", doc)
    words = len(re.findall(r"[A-Za-z0-9\u0400-\u04ff]+", plain)) + len(re.findall(r"[\u4e00-\u9fff]", plain))
    app = open(work + "/docProps/app.xml", encoding="utf-8").read()
    for tag, val in (("Words", words), ("Characters", len(plain)),
                     ("Paragraphs", doc.count("<w:p>")), ("Lines", max(1, words // 12))):
        app = re.sub(rf"<{tag}>\d*</{tag}>", f"<{tag}>{val}</{tag}>", app)
    app = re.sub(r"<Pages>\d*</Pages>", f"<Pages>{pages}</Pages>", app)
    with open(work + "/docProps/app.xml", "w", encoding="utf-8") as f:
        f.write(app)
    if zipfile.is_zipfile(out_path):
        os_remove(out_path)
    zf = zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED)
    for root, _, files in shutil.os.walk(work):
        for fn in files:
            full = shutil.os.path.join(root, fn)
            rel = shutil.os.path.relpath(full, work)
            zf.write(full, rel)
    zf.close()
    shutil.rmtree(work)
    return len(doc)


def os_remove(path):
    import os
    os.remove(path)


def table(rows, widths, fs, lang):
    ncols = max(len(r) for r in rows)
    if len(widths) != ncols:
        widths = [USABLE // ncols] * ncols
    grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)
    out = ['<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:type="auto" w:w="0"/>'
           '<w:tblLayout w:type="fixed"/><w:tblLook w:firstColumn="1" w:firstRow="1" '
           'w:lastColumn="0" w:lastRow="0" w:noHBand="0" w:noVBand="1" w:val="04A0"/></w:tblPr>'
           f'<w:tblGrid>{grid}</w:tblGrid>']
    for ri, row in enumerate(rows):
        row = row + [""] * (ncols - len(row))
        out.append("<w:tr>")
        for ci, cell in enumerate(row):
            shd = '<w:shd w:val="clear" w:fill="D9D9D9"/>' if ri == 0 else ""
            out.append(f'<w:tc><w:tcPr><w:tcW w:type="dxa" w:w="{widths[ci]}"/>{shd}'
                       '<w:vAlign w:val="top"/></w:tcPr>')
            out.append(para(cell, '<w:spacing w:before="40" w:after="40" w:line="240" w:lineRule="auto"/>',
                            bold=(ri == 0 or ci == 0), sz=fs, lang=lang))
            out.append("</w:tc>")
        out.append("</w:tr>")
    out.append("</w:tbl>")
    out.append('<w:p><w:pPr><w:spacing w:after="80"/></w:pPr><w:r><w:rPr><w:sz w:val="8"/></w:rPr>'
               '<w:t xml:space="preserve"> </w:t></w:r></w:p>')
    return "".join(out)


if __name__ == "__main__":
    jobs = [
        ("content_en.txt", "SmartMed_Ambient_EHR_Copilot_EN.docx", "en-US",
         "SmartMed Ambient EHR Copilot - Project Proposal and Algorithm Design",
         "8th Global Campus AI Algorithm Elite Competition, Digital Economy AI Agent Track", 13),
        ("content_ru.txt", "SmartMed_Ambient_EHR_Copilot_RU.docx", "ru-RU",
         "SmartMed Ambient EHR Copilot - \u043f\u0440\u043e\u0435\u043a\u0442\u043d\u0430\u044f \u0437\u0430\u043f\u0438\u0441\u043a\u0430 \u0438 \u0430\u043b\u0433\u043e\u0440\u0438\u0442\u043c\u0438\u0447\u0435\u0441\u043a\u0438\u0439 \u0434\u0438\u0437\u0430\u0439\u043d",
         "8-\u0439 \u0433\u043b\u043e\u0431\u0430\u043b\u044c\u043d\u044b\u0439 \u043a\u0430\u043c\u043f\u0443\u0441\u043d\u044b\u0439 \u043a\u043e\u043d\u043a\u0443\u0440\u0441 \u0418\u0418-\u0430\u043b\u0433\u043e\u0440\u0438\u0442\u043c\u043e\u0432, \u0442\u0440\u0435\u043a \u0418\u0418-\u0430\u0433\u0435\u043d\u0442\u044b \u0432 \u0446\u0438\u0444\u0440\u043e\u0432\u043e\u0439 \u044d\u043a\u043e\u043d\u043e\u043c\u0438\u043a\u0435", 16),
        ("content_zh.txt", "SmartMed_Ambient_EHR_Copilot_ZH.docx", "zh-CN",
         "SmartMed \u73af\u5883\u611f\u77e5\u7535\u5b50\u75c5\u5386\u667a\u80fd\u4f53 - \u9879\u76ee\u65b9\u6848\u4e0e\u7b97\u6cd5\u8bbe\u8ba1",
         "\u7b2c\u516b\u5c4a\u5168\u7403\u6821\u56ed\u4eba\u5de5\u667a\u80fd\u7b97\u6cd5\u7cbe\u82f1\u5927\u8d5b \u6570\u5b57\u7ecf\u6d4eAI\u667a\u80fd\u4f53\u8d5b\u9053", 9),
    ]
    base = HERE + "/"
    for src, out, lang, title, subject, pages in jobs:
        n = build(base + src, base + out, lang, title, subject, pages)
        print(out, "xml bytes:", n)
