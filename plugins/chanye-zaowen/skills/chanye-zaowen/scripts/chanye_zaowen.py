import argparse
import csv
import hashlib
import html
import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

CATEGORY_ORDER = ["热点资讯", "国际资讯", "国内资讯", "企业动态", "宏观政策"]
CATEGORY_EN = {
    "热点资讯": "HOT NEWS",
    "国际资讯": "INTERNATIONAL NEWS",
    "国内资讯": "DOMESTIC NEWS",
    "企业动态": "COMPANY NEWS",
    "宏观政策": "MACRO POLICIES",
}
# A company may be the actual publisher when the item is from its official newsroom.
# The source label is validated against the URL and editorial notes, not a name blacklist.
MEDIA_HINTS = [
    "央视新闻", "央视财经", "新华社", "人民日报", "经济日报", "中国新闻网", "中新经纬", "中国证券报",
    "上海证券报", "证券时报", "第一财经", "界面新闻", "每日经济新闻", "科创板日报", "财联社",
    "新京报", "新京报贝壳财经", "湖北日报", "安徽日报", "深圳发布", "浙江国资", "每经网",
]
POLICY_WORDS = ["印发", "发布", "出台", "实施", "征求意见", "方案", "意见", "措施", "规划", "标准", "法规", "条例", "行动计划", "通知", "指导意见"]
INDUSTRY_WORDS = [
    "产业", "经济", "制造", "工业", "能源", "电力", "石油", "天然气", "算力", "芯片", "半导体", "机器人",
    "数据", "低空", "物流", "贸易", "关税", "出口", "进口", "供应链", "矿产", "光伏", "汽车", "电池",
    "医药", "创新药", "AI", "人工智能", "云", "模型", "消费", "服务贸易", "金融", "房地产", "专利",
]
LOW_VALUE_WORDS = ["农业合作分委会", "普通座谈", "会见", "慰问", "灾害", "地震", "伤亡", "风口研报", "午间新闻精选", "收评", "指数", "涨停", "跌停"]

@dataclass
class NewsItem:
    pool: str
    id: str
    time: str
    title: str
    content: str
    link: str
    source_label: str
    source_evidence: str
    category_guess: str
    score: int
    reasons: list


def sign(params):
    query = "&".join(f"{k}={params[k]}" for k in sorted(params))
    return hashlib.md5(hashlib.sha1(query.encode()).hexdigest().encode()).hexdigest()


def get_json(url, referer):
    last_error = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": referer})
            with urllib.request.urlopen(req, timeout=45) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise last_error


def fetch_cls_page(last_time):
    params = {
        "app": "CailianpressWeb", "last_time": str(last_time), "os": "web",
        "refresh_type": "1", "rn": "50", "sv": "8.7.9",
    }
    params["sign"] = sign(params)
    url = "https://www.cls.cn/v1/roll/get_roll_list?" + urllib.parse.urlencode(params)
    data = get_json(url, "https://www.cls.cn/telegraph")
    if data.get("errno") != 0:
        raise RuntimeError(f"CLS API failed: {data}")
    return data.get("data", {}).get("roll_data", [])


def fetch_kcb_page(last_time):
    params = {
        "app": "stib", "category": "stib", "channel": "100", "last_time": str(last_time),
        "os": "stibWeb", "refresh_type": "1", "rn": "20", "sv": "1.4.3",
    }
    params["sign"] = sign(params)
    url = "https://www.chinastarmarket.cn/v1/roll/get_roll_list?" + urllib.parse.urlencode(params)
    data = get_json(url, "https://www.chinastarmarket.cn/telegraph")
    if data.get("errno") != 0:
        raise RuntimeError(f"KCB API failed: {data}")
    return data.get("data", {}).get("roll_data", [])


def fetch_window(fetch_page, start, end, pool):
    last_time = int(end.timestamp())
    seen = {}
    while True:
        page = fetch_page(last_time)
        if not page:
            break
        oldest = None
        for raw in page:
            ts = int(raw.get("ctime") or raw.get("time") or 0)
            if not ts:
                continue
            dt = datetime.fromtimestamp(ts)
            oldest = dt if oldest is None or dt < oldest else oldest
            if start <= dt <= end:
                nid = str(raw.get("id") or raw.get("cailianpress_id") or raw.get("title") or ts)
                title = clean(raw.get("title") or raw.get("brief") or "")
                content = clean(raw.get("content") or raw.get("brief") or raw.get("content_text") or title)
                link = f"https://www.cls.cn/detail/{nid}" if pool == "财联社" else f"https://www.chinastarmarket.cn/detail/{nid}"
                seen[nid] = normalize_item(pool, nid, dt, title, content, link)
        if oldest is None or oldest < start:
            break
        last_time = int(oldest.timestamp()) - 1
        time.sleep(0.55)
    return sorted(seen.values(), key=lambda x: x.time, reverse=True)


def fetch_wscn(start, end, limit=50):
    items = []
    cursor = ""
    while True:
        url = "https://api-one.wallstcn.com/apiv1/content/lives?channel=global-channel&limit=50"
        if cursor:
            url += "&cursor=" + urllib.parse.quote(str(cursor))
        data = get_json(url, "https://wallstreetcn.com/live")
        arr = data.get("data", {}).get("items", [])
        if not arr:
            break
        oldest = None
        for raw in arr:
            ts = int(raw.get("display_time") or raw.get("created_at") or 0)
            if ts > 10_000_000_000:
                ts = ts // 1000
            if not ts:
                continue
            dt = datetime.fromtimestamp(ts)
            oldest = dt if oldest is None or dt < oldest else oldest
            if start <= dt <= end:
                nid = str(raw.get("id") or raw.get("uri") or ts)
                content = clean(raw.get("content_text") or raw.get("title") or "")
                title = clean(raw.get("title") or first_sentence(content))
                link = raw.get("uri") or f"https://wallstreetcn.com/livenews/{nid}"
                items.append(normalize_item("华尔街见闻", nid, dt, title, content, link))
        cursor = data.get("data", {}).get("next_cursor")
        if oldest is None or oldest < start or not cursor:
            break
        time.sleep(0.55)
    dedup = {i.id: i for i in items}
    return sorted(dedup.values(), key=lambda x: x.time, reverse=True)


def clean(s):
    s = html.unescape(str(s or ""))
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def first_sentence(s):
    m = re.split(r"(?<=[。！？])", s.strip(), maxsplit=1)
    return m[0][:60] if m else s[:60]


def extract_source(text, pool):
    text = clean(text)
    for pattern in [r"[（(]([^（）()]{2,20})[）)]\s*$", r"据[“\"]?([^，。、“\"]{2,20})[”\"]?(?:消息|报道|获悉|公众号消息)"]:
        m = re.search(pattern, text)
        if m:
            src = m.group(1).strip()
            src = src.replace("记者", "").strip()
            if src:
                if src.startswith(pool) or "记者" in src:
                    return pool, m.group(0)
                return src, m.group(0)
    for hint in MEDIA_HINTS:
        if hint in text:
            return hint, hint
    return pool, "默认使用承载平台；未识别到更具体媒体来源"


def guess_category(title, content):
    text = title + " " + content
    if any(w in text for w in POLICY_WORDS) and re.search(r"国家|国务院|工信部|商务部|发改委|财政部|市场监管|税务总局|知识产权局|数据局|人民政府|市委|省政府", text):
        return "宏观政策"
    if re.search(r"美国|加拿大|日本|韩国|越南|伊朗|阿曼|欧盟|英国|德国|法国|俄罗斯|印度|瑞典|巴西|全球|国际", text):
        return "国际资讯"
    if re.search(r"公司|集团|发布|收购|订单|产能|财报|营收|投资|合作|上市|IPO|配售|节点|模型|产品|开服", text) and not any(w in text for w in POLICY_WORDS):
        return "企业动态"
    return "国内资讯"


def score_item(title, content, pool):
    text = title + " " + content
    score = 0
    reasons = []
    hits = [w for w in INDUSTRY_WORDS if w in text]
    if hits:
        score += min(10, len(set(hits)) * 2); reasons.append("产业经济相关")
    if pool == "科创板日报":
        score += 4; reasons.append("科创板日报信号")
    if re.search(r"万亿|千亿|百亿|亿美元|%|同比|增长|首次|首款|全球|国家级|国务院|两部门|三部门", text):
        score += 4; reasons.append("含关键数字/首发/国家级信号")
    if re.search(r"英伟达|苹果|华为|腾讯|阿里|亚马逊|微软|特斯拉|DeepSeek|宇树|宁德时代|丰田", text):
        score += 3; reasons.append("高关注企业")
    if any(w in text for w in LOW_VALUE_WORDS):
        score -= 5; reasons.append("低价值或偏离产业")
    if re.search(r"股价|涨停|跌停|A股|港股", text) and not re.search(r"财报|订单|产能|投资|产业", text):
        score -= 4; reasons.append("偏股票交易")
    return score, reasons


def normalize_item(pool, nid, dt, title, content, link):
    if not title:
        title = first_sentence(content)
    src, evidence = extract_source(content, pool)
    category = guess_category(title, content)
    score, reasons = score_item(title, content, pool)
    return NewsItem(pool, nid, dt.strftime("%Y-%m-%d %H:%M:%S"), title, content, link, src, evidence, category, score, reasons)


def is_policy(item):
    return item.category_guess == "宏观政策" or any(w in item.title + item.content for w in POLICY_WORDS)


def compress(content, max_chars=170):
    text = clean(content)
    text = re.sub(r"^财联社\d+月\d+日电[，,]?", "", text)
    text = re.sub(r"^《科创板日报》\d+日讯[，,]?", "", text)
    text = re.sub(r"[（(][^（）()]{2,20}[）)]\s*$", "", text).strip()
    if len(text) <= max_chars:
        return text
    parts = re.split(r"(?<=[。！？])", text)
    out = ""
    for p in parts:
        if len(out) + len(p) <= max_chars:
            out += p
    return out.strip() or text[:max_chars].rstrip("，,；;：:") + "。"


def quality_issues(selected):
    issues = []
    forbidden_terms = ["午间新闻精选", "风口研报", "科创板收评", "创业板指", "收盘", "涨停", "跌停", "沪深两市成交额", "商品期货", "主力合约", "盯盘", "出席开幕式并致辞", "视频通话", "交换意见", "抢险救援", "灾害", "外交部回应", "毒气展"]
    for cat, items in selected.items():
        for item in items:
            text = item.title + " " + item.content
            hit = [w for w in forbidden_terms if w in text]
            if hit:
                issues.append(f"{cat}《{item.title}》命中禁止/低价值词：{'、'.join(hit)}")
            if not item.link:
                issues.append(f"{cat}《{item.title}》缺少来源链接")
            if cat == "宏观政策":
                if not is_policy(item):
                    issues.append(f"宏观政策《{item.title}》不是明确政策/方案/意见/措施/规划/标准类")
                if item.source_label == "财联社":
                    issues.append(f"宏观政策《{item.title}》只有财联社来源，未核到官方/权威来源")
            if cat == "国内资讯" and is_policy(item):
                issues.append(f"国内资讯《{item.title}》实际是政策类，应进入宏观政策或排除")
            if cat == "热点资讯" and is_policy(item):
                issues.append(f"热点资讯《{item.title}》是政策类，不能放热点")
    return issues


def write_outputs(out_dir, start, end, pools, selected):
    out_dir.mkdir(parents=True, exist_ok=True)
    all_items = [i for arr in pools.values() for i in arr]
    meta = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "window_start": start.strftime("%Y-%m-%d %H:%M:%S"),
        "window_end": end.strftime("%Y-%m-%d %H:%M:%S"),
        "pool_counts": {k: len(v) for k, v in pools.items()},
        "pool_newest_oldest": {k: {"newest": v[0].time if v else "", "oldest": v[-1].time if v else ""} for k, v in pools.items()},
    }
    (out_dir / "抓取报告.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "完整新闻池.json").write_text(json.dumps([asdict(i) for i in all_items], ensure_ascii=False, indent=2), encoding="utf-8")
    with (out_dir / "候选评分表.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["pool", "time", "category_guess", "score", "title", "source_label", "link", "reasons"])
        for i in sorted(all_items, key=lambda x: x.score, reverse=True):
            w.writerow([i.pool, i.time, i.category_guess, i.score, i.title, i.source_label, i.link, ";".join(i.reasons)])
    issues = quality_issues(selected)
    if issues:
        fail = ["# 自检失败报告", "", "本次结果未生成正式稿，因为命中以下质量问题：", ""]
        fail.extend([f"- {issue}" for issue in issues])
        fail.extend(["", "已保留抓取报告、完整新闻池、候选评分表和来源核查表，供继续修正规则使用。"] )
        (out_dir / "自检失败报告.md").write_text("\n".join(fail)+"\n", encoding="utf-8")
    else:
        md = ["# 产业朝闻正式稿", "", f"时间窗口：{meta['window_start']} 至 {meta['window_end']}", ""]
        for cat in CATEGORY_ORDER:
            items = selected.get(cat, [])
            if not items:
                continue
            md.append(f"## {cat}  {CATEGORY_EN[cat]}")
            md.append("")
            for i in items:
                md.append(f"**{i.title}**")
                md.append(compress(i.content) + f"【{i.source_label}】{i.link}")
                md.append("")
        (out_dir / "正式稿.md").write_text("\n".join(md).strip()+"\n", encoding="utf-8")
    check = ["# 来源核查表", "", f"时间窗口：{meta['window_start']} 至 {meta['window_end']}", "", "|分类|标题|发布时间|正文来源|新闻池|来源链接|入选理由|", "|---|---|---:|---|---|---|---|"]
    for cat in CATEGORY_ORDER:
        for i in selected.get(cat, []):
            check.append(f"|{cat}|{i.title}|{i.time}|【{i.source_label}】|{i.pool}|{i.link}|{'；'.join(i.reasons)}|")
    (out_dir / "来源核查表.md").write_text("\n".join(check)+"\n", encoding="utf-8")


def blocked_item(item):
    text = item.title + " " + item.content
    if not item.link or not item.title or not item.content:
        return "缺少标题/正文/链接"
    if any(w in text for w in ["午间新闻精选", "风口研报", "科创板收评", "创业板指", "收盘", "涨停", "跌停", "沪深两市成交额", "商品期货", "主力合约", "盯盘"]):
        return "市场播报/研报/合集，不进正式稿"
    if any(w in text for w in ["农业合作分委会", "出席开幕式并致辞", "视频通话", "交换意见"]):
        return "低价值农业会议，不进正式稿"
    if re.search(r"股价|A股|港股", text) and not re.search(r"财报|订单|产能|投资|产业|产品|合作", text):
        return "偏股票交易"
    if not any(w in text for w in INDUSTRY_WORDS):
        return "产业经济相关性不足"
    return ""

def title_key(title):
    title = re.sub(r"^【|】$", "", title)
    return re.sub(r"[\W_]+", "", title)[:26]

def select_items(items):
    buckets = {c: [] for c in CATEGORY_ORDER}
    used = set()
    clean_items = [i for i in items if not blocked_item(i)]

    def add(cat, item, limit):
        key = title_key(item.title)
        if key in used or len(buckets[cat]) >= limit:
            return False
        buckets[cat].append(item)
        used.add(key)
        return True

    macro_pool = [i for i in clean_items if is_policy(i) and i.source_label != "财联社" and re.search(r"国家|国务院|工信部|商务部|发改委|财政部|市场监管|税务总局|知识产权局|数据局|人民政府|省委|市委|两部门|三部门", i.title + i.content)]
    for i in sorted(macro_pool, key=lambda x: x.score, reverse=True):
        add("宏观政策", i, 3)

    ai_company_count = 0
    company_pool = [i for i in clean_items if i.category_guess == "企业动态" and not is_policy(i)]
    for i in sorted(company_pool, key=lambda x: x.score, reverse=True):
        is_ai = "AI" in i.title + i.content or "人工智能" in i.title + i.content
        if is_ai and ai_company_count >= 2:
            continue
        if add("企业动态", i, 5) and is_ai:
            ai_company_count += 1

    domestic_pool = [i for i in clean_items if i.category_guess == "国内资讯" and not is_policy(i)]
    domestic_pool += [i for i in clean_items if i.category_guess == "企业动态" and re.search(r"行业|产业|规模|数据|市场|项目|突破", i.title + i.content) and not is_policy(i)]
    for i in sorted(domestic_pool, key=lambda x: x.score, reverse=True):
        add("国内资讯", i, 3)

    intl_re = r"美国|加拿大|日本|韩国|越南|伊朗|阿曼|欧盟|英国|德国|法国|俄罗斯|印度|瑞典|巴西|阿根廷|全球|国际"
    intl_pool = [i for i in clean_items if re.search(intl_re, i.title + i.content) and re.search(r"能源|石油|天然气|电力|贸易|关税|出口|进口|供应链|芯片|半导体|数据中心|投资|产量|销量|融资|债券|利率|通胀|制裁|航运|物流|矿产|汽车", i.title + i.content) and not is_policy(i)]
    for i in sorted(intl_pool, key=lambda x: x.score, reverse=True):
        add("国际资讯", i, 3)

    hot_pool = [i for i in clean_items if not is_policy(i) and title_key(i.title) not in used and i.score >= 9]
    for i in sorted(hot_pool, key=lambda x: x.score, reverse=True):
        add("热点资讯", i, 3)

    return buckets


def main():
    ap = argparse.ArgumentParser(description="产业朝闻执行器：抓取完整新闻池并生成正式稿、来源核查表和过程证据")
    ap.add_argument("--start", required=True, help="YYYY-MM-DD HH:MM")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD HH:MM")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--include-wscn", action="store_true")
    args = ap.parse_args()
    start = datetime.strptime(args.start, "%Y-%m-%d %H:%M")
    end = datetime.strptime(args.end, "%Y-%m-%d %H:%M")
    pools = {
        "财联社": fetch_window(fetch_cls_page, start, end, "财联社"),
        "科创板日报": fetch_window(fetch_kcb_page, start, end, "科创板日报"),
    }
    if args.include_wscn:
        pools["华尔街见闻"] = fetch_wscn(start, end)
    items = [i for arr in pools.values() for i in arr]
    selected = select_items(items)
    write_outputs(Path(args.out_dir), start, end, pools, selected)
    print(json.dumps({"out_dir": args.out_dir, "counts": {k: len(v) for k, v in pools.items()}}, ensure_ascii=False))

if __name__ == "__main__":
    main()




