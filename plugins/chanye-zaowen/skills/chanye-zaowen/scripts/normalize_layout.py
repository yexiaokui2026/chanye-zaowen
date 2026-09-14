"""Apply the article's mobile typography without rewriting editorial content."""

import argparse
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path

TITLE_STYLE = (
    "display:block;margin:0 0 10px;padding:0;color:#062a56;"
    "font-size:16px;line-height:1.45;letter-spacing:0;"
    "word-break:normal;overflow-wrap:anywhere;white-space:normal;"
    "text-indent:0!important;text-align:justify!important;"
    "text-align-last:left!important;text-justify:inter-ideograph;"
    "text-wrap:wrap;box-sizing:border-box;"
)
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
             "link", "meta", "param", "source", "track", "wbr"}


def overlay_style(style, declarations):
    # Only replace named declarations; retain unrelated template styling.
    names = {part.split(":", 1)[0].strip().lower()
             for part in declarations.split(";") if ":" in part}
    kept = [part.strip() for part in style.split(";")
            if ":" in part and part.split(":", 1)[0].strip().lower() not in names]
    return ";".join(kept + [declarations.rstrip(";")]) + ";"


def replace_attribute(raw, name, value):
    pattern = re.compile(r"\s" + re.escape(name) + r"\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+)", re.I)
    attr = f' {name}="{html.escape(value, quote=True)}"'
    if pattern.search(raw):
        return pattern.sub(lambda _: attr, raw, count=1)
    end = raw.rfind("/>") if raw.endswith("/>") else raw.rfind(">")
    return raw[:end] + attr + raw[end:]


class LayoutParser(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.offsets = [0]
        for line in source.splitlines(keepends=True):
            self.offsets.append(self.offsets[-1] + len(line))
        self.stack = []
        self.edits = []
        self.title_count = 0

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        style = attr.get("style") or ""
        compact = re.sub(r"\s+", "", style).lower()
        parent = self.stack[-1] if self.stack else {}
        card = tag == "section" and ("background:#f8fafd" in compact)
        title = tag == "p" and ("cz-news-title" in (attr.get("class") or "").split()
                                or parent.get("card") and not parent.get("paragraph_seen"))
        if tag == "p" and parent.get("card"):
            parent["paragraph_seen"] = True
        inside_title = title or parent.get("inside_title", False)
        raw = self.get_starttag_text()
        updated = raw
        if title:
            self.title_count += 1
            updated = replace_attribute(updated, "style", TITLE_STYLE)
            updated = replace_attribute(updated, "align", "justify")
            classes = (attr.get("class") or "").split()
            classes = [c for c in classes if c != "cz-news-title-last-line-right"]
            if "cz-news-title" not in classes:
                classes.append("cz-news-title")
            updated = replace_attribute(updated, "class", " ".join(classes))
        elif inside_title and tag in {"span", "strong", "b", "em"}:
            updated = replace_attribute(updated, "style", overlay_style(style,
                "letter-spacing:0;white-space:normal;word-break:normal;"
                "overflow-wrap:anywhere;text-align:inherit;text-align-last:inherit"))
        elif tag == "img":
            updated = replace_attribute(updated, "style", overlay_style(style,
                "display:block;width:100%;max-width:100%!important;height:auto;"
                "box-sizing:border-box"))
        if updated != raw:
            line, column = self.getpos()
            start = self.offsets[line - 1] + column
            self.edits.append((start, start + len(raw), updated))
        if tag not in VOID_TAGS:
            self.stack.append({"tag": tag, "card": card, "inside_title": inside_title})

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                del self.stack[index:]
                break


def normalize_layout(source):
    parser = LayoutParser(source)
    parser.feed(source)
    parser.close()
    if not parser.title_count:
        raise ValueError("No article news titles found; original HTML was not changed")
    output = source
    for start, end, value in reversed(parser.edits):
        output = output[:start] + value + output[end:]
    return output


def preview_document(fragment, title):
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(title)}</title>'
            '<style>html{margin:0}body{margin:0;background:#edf0f4;padding:24px 0;'
            'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",Arial,sans-serif;}'
            'main{box-sizing:border-box;width:100%;max-width:390px;margin:0 auto;'
            'padding:16px 16px 32px;background:#fff;}'
            '@media(max-width:430px){body{padding:0}main{max-width:none}}'
            '</style></head><body><main>' + fragment + '</main></body></html>')


def main():
    parser = argparse.ArgumentParser(description="Optimize supplied article HTML only")
    parser.add_argument("--input", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    source = Path(args.input).read_text(encoding="utf-8-sig")
    optimized = normalize_layout(source)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    outputs = {"article.html": optimized, "article-code.txt": optimized,
               "mobile-preview.html": preview_document(optimized, "产业朝闻 · 排版优化预览"),
               "original-preview.html": preview_document(source, "产业朝闻 · 原版对照")}
    for name, content in outputs.items():
        path = out_dir / name
        path.write_text(content, encoding="utf-8")
        paths[name] = str(path)
    print(json.dumps(paths, ensure_ascii=False))


if __name__ == "__main__":
    main()
