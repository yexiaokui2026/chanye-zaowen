import argparse
import html
import json
import re
from collections import Counter
from urllib.parse import urlparse
from datetime import datetime, timedelta
from pathlib import Path

CATEGORY_ORDER = ["热点资讯", "国际资讯", "国内资讯", "企业动态", "宏观政策"]
MINIMUM_COUNTS = dict(zip(CATEGORY_ORDER, (3, 3, 4, 6, 3)))
CARD_RE = re.compile(
    r'\s*<section style="display:block;width:auto;margin:0 0 18px 0;padding:18px 20px 20px;'
    r'background:#f8fafd;border:1px solid #e7ecf3;border-radius:4px;box-shadow:0 10px 24px '
    r'rgba\(15,39,72,0\.08\);text-align:left!important;text-indent:0!important;box-sizing:border-box;">'
    r'.*?</section>',
    re.S,
)
DATE_RE = re.compile(r'20\d{2}\.\d{2}\.\d{2}&nbsp;&nbsp;星期[一二三四五六日天]')
URL_RE = re.compile(r'https?://', re.I)
WEEKDAYS = "一二三四五六日"


def esc(value):
    return html.escape(str(value or "").strip(), quote=True)


def markdown_cell(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def parse_publish_date(value):
    value = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    raise ValueError("publish_date 必须是 YYYY-MM-DD、YYYY.MM.DD 或 YYYY/MM/DD")


def parse_news_time(value):
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(value or '').strip()):
        return datetime.strptime(str(value).strip(), '%Y-%m-%d')
    value = str(value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    raise ValueError(f"无法解析新闻发布时间：{value}")


def computed_time_check(published_at, publish_date):
    dt = parse_news_time(published_at)
    target = (publish_date - timedelta(days=1)).date()
    supplement = target - timedelta(days=1)
    if dt.date() == target:
        return "目标新闻日"
    if dt.date() == supplement and dt.hour >= 18:
        return "前一日18点后补充"
    return "超出默认窗口，需复核"


def validate_item(category, item):
    required = ["title", "summary", "source", "published_at", "url"]
    missing = [key for key in required if not str(item.get(key, "")).strip()]
    if missing:
        raise ValueError(f"{category} 有新闻缺少字段：{', '.join(missing)}")
    if not re.match(r'^https?://', str(item["url"]).strip(), re.I):
        raise ValueError(f"{category}《{item['title']}》原链接不是 http(s) 地址")
    if URL_RE.search(str(item["summary"])):
        raise ValueError(f"{category}《{item['title']}》摘要中含网址；网址只能进入核查表")
    parse_news_time(item["published_at"])


def validate_selection(items_by_category):
    if not isinstance(items_by_category, dict):
        raise ValueError('Input must contain an items object')
    seen_urls = set()
    seen_titles = set()
    for category, minimum in MINIMUM_COUNTS.items():
        items = items_by_category.get(category)
        if not isinstance(items, list) or len(items) < minimum:
            actual = len(items) if isinstance(items, list) else 0
            raise ValueError(f'{category}: {actual} items; minimum is {minimum}; no upper limit')
        for item in items:
            validate_item(category, item)
            url = str(item['url']).strip()
            host = (urlparse(url).hostname or '').lower()
            if not host:
                raise ValueError('Source URL must have a hostname')
            title = str(item['title']).strip()
            if url in seen_urls or title in seen_titles:
                raise ValueError(f'Duplicate story: {title}')
            seen_urls.add(url)
            seen_titles.add(title)
            if category == CATEGORY_ORDER[-1]:
                official_host = host.endswith('.gov.cn')
                reviewed_official = item.get('official_source') is True and str(item.get('note') or '').strip()
                if not official_host and not reviewed_official:
                    raise ValueError(f'Macro story needs a verified official website: {title}')


def source_distribution(items_by_category):
    hosts = Counter()
    for items in items_by_category.values():
        for item in items:
            host = (urlparse(item['url']).hostname or '').lower()
            hosts[host.removeprefix('www.')] += 1
    return hosts


def render_source_audit(items_by_category):
    hosts = source_distribution(items_by_category)
    total = sum(hosts.values())
    aggregators = sum(count for host, count in hosts.items()
                      if host in ('cls.cn', 'chinastarmarket.cn')
                      or host.endswith(('.cls.cn', '.chinastarmarket.cn')))
    lines = ['', '## 来源分布自检', '', '以下为承载域名统计，不等于独立原始发布者数量；转载关系须逐条人工核对。', '']
    lines.extend(f'- {host}: {count}条' for host, count in hosts.most_common())
    lines.append(f'财联社/科创板日报承载：{aggregators}/{total}条。')
    if total and aggregators * 2 > total:
        lines.append('来源集中预警：多数链接仍依赖财联社/科创板日报；交付前继续核源并说明保留转引的原因。')
    return '\n'.join(lines) + '\n'


def render_card(item):
    title = esc(item["title"])
    summary = esc(item["summary"])
    source = esc(item["source"])
    return f'''\n\t\t\t\t\t<section style="display:block;width:auto;margin:0 0 18px 0;padding:18px 20px 20px;background:#f8fafd;border:1px solid #e7ecf3;border-radius:4px;box-shadow:0 10px 24px rgba(15,39,72,0.08);text-align:left!important;text-indent:0!important;box-sizing:border-box;">
\t\t\t\t\t\t<p style="display: block; margin: 0px 0px 10px; padding: 0px; color: #062a56; font-size: 16px; line-height: 1.45; letter-spacing: 0.4px; text-indent: 0px !important;text-align:left !important;" align="left !important">
\t\t\t\t\t\t\t<span style="font-size: 16px;"><strong>{title}</strong></span>
\t\t\t\t\t\t</p>
\t\t\t\t\t\t<p style="display: block; margin: 0px; padding: 0px; color: #283447; font-size: 15px; line-height: 1.8; font-weight: 400; letter-spacing: 1.8px; word-break: break-word; overflow-wrap: anywhere; text-indent: 0px !important;text-align:justify;" align="justify">
\t\t\t\t\t\t\t{summary}【{source}】
\t\t\t\t\t\t</p>
\t\t\t\t\t</section>'''


def replace_category_cards(template, category_index, items):
    marker = f"<strong>{category_index:02d}</strong>"
    start = template.find(marker)
    if start < 0:
        raise ValueError(f"母版缺少栏目编号 {category_index:02d}")
    if category_index < len(CATEGORY_ORDER):
        next_marker = f"<strong>{category_index + 1:02d}</strong>"
        end = template.find(next_marker, start + len(marker))
    else:
        end = template.find("产业朝闻&nbsp;&nbsp;企业发展智慧之选", start + len(marker))
    if end < 0:
        raise ValueError(f"无法确定栏目 {category_index:02d} 的结束位置")
    segment = template[start:end]
    matches = list(CARD_RE.finditer(segment))
    if not matches:
        raise ValueError(f"母版栏目 {category_index:02d} 中未找到新闻卡片")
    cards = "".join(render_card(item) for item in items)
    segment = segment[:matches[0].start()] + cards + segment[matches[-1].end():]
    return template[:start] + segment + template[end:]


def render_html(template, data, publish_date):
    validate_selection(data.get('items') or data.get('selected'))
    items_by_category = data.get("items") or data.get("selected")
    date_text = publish_date.strftime("%Y.%m.%d")
    weekday = WEEKDAYS[publish_date.weekday()]
    output, count = DATE_RE.subn(f"{date_text}&nbsp;&nbsp;星期{weekday}", template, count=1)
    if count != 1:
        raise ValueError("母版头图日期占位未找到或不唯一")
    for index, category in enumerate(CATEGORY_ORDER, start=1):
        output = replace_category_cards(output, index, items_by_category[category])
    if "auth_key" in output or "bexp.135editor.com" in output or "file:" in output:
        raise ValueError("输出仍含临时图片地址或本地路径")
    image_urls = re.findall(r'<img\b[^>]*\bsrc="(https?://[^"]+)"', output, re.I)
    if len(image_urls) != 2 or not all("mmbiz.qpic.cn" in url for url in image_urls):
        raise ValueError("母版必须且只能包含城市图与尾图两条微信素材地址")
    return output, items_by_category


def render_links_table(items_by_category, publish_date):
    rows = [
        "# 产业朝闻原链接核查表",
        "",
        f"发布日期：{publish_date.strftime('%Y-%m-%d')}  ",
        f"主目标新闻日：{(publish_date - timedelta(days=1)).strftime('%Y-%m-%d')}",
        "",
        "|序号|栏目|标题|发布时间|来源|原链接|时间核查|核查备注|",
        "|---:|---|---|---|---|---|---|---|",
    ]
    number = 1
    for category in CATEGORY_ORDER:
        for item in items_by_category[category]:
            time_check = str(item.get("time_check") or computed_time_check(item["published_at"], publish_date))
            note = str(item.get("note") or "原链接可访问；标题、时间与摘要待交付前复核")
            rows.append(
                f"|{number}|{markdown_cell(category)}|{markdown_cell(item['title'])}|"
                f"{markdown_cell(item['published_at'])}|{markdown_cell(item['source'])}|"
                f"{markdown_cell(item['url'])}|{markdown_cell(time_check)}|{markdown_cell(note)}|"
            )
            number += 1
    rows.extend(["", f"共 {number - 1} 条入选新闻。"])
    return "\n".join(rows) + "\n"


def main():
    parser = argparse.ArgumentParser(description="使用产业朝闻固定母版生成135排版HTML和原链接核查表")
    parser.add_argument("--input", required=True, help="最终入选新闻 JSON")
    parser.add_argument("--out-dir", required=True, help="输出目录")
    parser.add_argument("--template", help="可选母版路径；默认使用 Skill assets/135-wechat-template.html")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    template_path = Path(args.template) if args.template else script_dir.parent / "assets" / "135-wechat-template.html"
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    publish_date = parse_publish_date(data.get("publish_date") or data.get("date"))
    template = template_path.read_text(encoding="utf-8")
    output_html, items_by_category = render_html(template, data, publish_date)
    links_md = render_links_table(items_by_category, publish_date)

    links_md += render_source_audit(items_by_category)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = publish_date.strftime("%Y-%m-%d")
    html_path = out_dir / f"产业朝闻_{stamp}_公众号排版.html"
    links_path = out_dir / f"产业朝闻_{stamp}_原链接核查表.md"
    code_path = out_dir / f'产业朝闻_{stamp}_HTML代码.txt'
    html_path.write_text(output_html, encoding="utf-8")
    code_path.write_text(output_html, encoding='utf-8')
    links_path.write_text(links_md, encoding="utf-8")
    assert html_path.read_bytes() == code_path.read_bytes()
    print(json.dumps({'html': str(html_path), 'code': str(code_path), 'links': str(links_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
