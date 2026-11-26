"""Model yanıtını doğrulama ve Türkçe Markdown oluşturma."""

import html
import json
import re

MARKER = "<!-- pr-inceleme-botu -->"
NOTE = "Bu otomatik bir incelemedir; onay ekip liderindedir."
BADGES = {"kritik": "🔴 Kritik", "onemli": "🟠 Önemli", "oneri": "🔵 Öneri"}


class ReviewError(Exception):
    pass


def _text(value, limit=1000):
    if not isinstance(value, str):
        return ""
    value = re.sub(r"[\ud800-\udfff]", "\ufffd", value)
    return " ".join(value.split())[:limit]


def _list(value, limit):
    if isinstance(value, str):
        value = [re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", line)
                 for line in value.splitlines()]
    if not isinstance(value, list):
        return []
    return [item for entry in value if (item := _text(entry))][:limit]


def validate(raw, files):
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", raw):
        try:
            data, _ = decoder.raw_decode(raw, match.start())
        except (ValueError, RecursionError):
            continue
        if isinstance(data, dict) and _text(data.get("ozet")):
            break
    else:
        raise ReviewError("Model yanıtında özet içeren geçerli bir inceleme JSON'u bulunamadı.")

    paths = {file.path: file.added for file in files}
    findings = []
    for item in data.get("bulgular") if isinstance(data.get("bulgular"), list) else []:
        if not isinstance(item, dict):
            continue
        level = item.get("onem")
        title = _text(item.get("baslik"), 160)
        explanation = _text(item.get("aciklama"))
        if not isinstance(level, str) or level not in BADGES or not title or not explanation:
            continue
        path = item.get("dosya")
        path = path if isinstance(path, str) and path in paths else None
        line = item.get("satir")
        if type(line) is not int or path is None or line not in paths[path]:
            line = None
        findings.append({"dosya": path, "satir": line, "onem": level,
                         "baslik": title, "aciklama": explanation,
                         "oneri": _text(item.get("oneri"))})
        if len(findings) == 15:
            break

    links = []
    for item in data.get("iliski") if isinstance(data.get("iliski"), list) else []:
        if not isinstance(item, dict):
            continue
        source, target = item.get("kaynak"), item.get("hedef")
        if (isinstance(source, str) and isinstance(target, str)
                and source in paths and target in paths and source != target
                and (source, target) not in links):
            links.append((source, target))
        if len(links) == 8:
            break
    return {"ozet": _text(data["ozet"]), "akis": _list(data.get("akis"), 6),
            "bulgular": findings, "sorular": _list(data.get("sorular"), 8),
            "test_onerileri": _list(data.get("test_onerileri"), 8), "iliski": links}


# Biçimlendirme, bağlantı ve otomatik bağlantı (":") üretebilen karakterler kaçırılır;
# nokta/virgül gibi zararsız noktalama okunabilirlik için olduğu gibi kalır.
MD_SPECIAL = set("\\`*_[]()#|!~:")


def _md(value):
    value = " ".join(value.split())
    # Model ve dosya adları Markdown/HTML, bağlantı veya mention oluşturamaz.
    return "".join(
        html.escape(char) if char in "<>&" else "&#64;" if char == "@"
        else "\\" + char if char in MD_SPECIAL else char
        for char in value
    )


def _finding(item, location=True):
    path, line = item["dosya"], item["satir"]
    place = _md(path) if path and location else ""
    if place and line is not None:
        place += f", satır {line}"
    result = f"**{BADGES[item['onem']]} · {_md(item['baslik'])}**"
    if place:
        result += f" ({place})"
    result += f"\n\n{_md(item['aciklama'])}"
    if item["oneri"]:
        result += f"\n\n**Öneri** {_md(item['oneri'])}"
    return result


def _diagram(links):
    if not links:
        return []
    nodes = dict.fromkeys(path for pair in links for path in pair)
    ids = {path: f"F{index}" for index, path in enumerate(nodes, 1)}
    lines = ["", "```mermaid", "flowchart LR"]
    for path, node in ids.items():
        # Mermaid kaynak koduna yalnızca güvenli etiket karakterleri ekle.
        label = "".join(char if char.isalnum() or char in " ./_-" else " "
                        for char in path[:100]).strip()
        lines.append(f'    {node}["{label or node}"]')
    lines.extend(f"    {ids[source]} --> {ids[target]}" for source, target in links)
    return [*lines, "```"]


def render(report, skipped, include_inline=True, marker=False):
    lines = ["# PR İnceleme Raporu", "", "## Özet", "", _md(report["ozet"]),
             "", "## Değişikliğin akışı", ""]
    lines.extend([f"- {_md(item)}" for item in report["akis"]] or ["- Akış bilgisi yok."])
    lines.extend(_diagram(report["iliski"]))
    lines.extend(["", "## Bulgular", ""])
    findings = [item for item in report["bulgular"] if include_inline or item["satir"] is None]
    lines.extend(["\n\n".join(_finding(item) for item in findings)] if findings else [
        "Satır bulguları diff üzerinde yer alıyor." if report["bulgular"] else "Bulgu yok."
    ])
    for title, key in (("Sorular", "sorular"), ("Test önerileri", "test_onerileri")):
        lines.extend(["", f"## {title}", ""])
        lines.extend([f"- {_md(item)}" for item in report[key]] or ["- Yok."])
    if skipped:
        lines.extend(["", "## İncelenmeyen dosyalar", ""])
        lines.extend(f"- {_md(path)} ({reason})" for path, reason in skipped)
    if marker:
        lines.extend(["", MARKER])
    lines.extend(["", NOTE])
    if (cost := report.get("cost_usd")) is not None:
        lines.extend(["", f"_Tahmini model maliyeti · {cost:.6f} USD_"])
    return "\n".join([*lines, ""])


def inline_comments(report):
    return [{"path": item["dosya"], "line": item["satir"], "side": "RIGHT",
             "body": _finding(item, location=False)}
            for item in report["bulgular"] if item["satir"] is not None]
