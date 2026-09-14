#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""产业朝闻交付前自检（preflight）。

把历史上反复被用户退回的问题（来源标签、标题改写、链接404、栏目边界、宏观不合格、
重复选题、来源集中、字节不一致）固化成机器检查，交付前必跑，全绿才交付。

用法：
    python preflight_check.py --selected selected.json --pool pool/完整新闻池.json \
        --out-dir output --stamp 2026-09-14 [--skip-links] [--strict]

退出码：0 全部通过（允许提示）；1 存在错误项。
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

try:
    import urllib.request

    def _fetch_status(url: str, timeout: int = 15) -> int | str:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status
        except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
            return exc.code
        except Exception as exc:  # noqa: BLE001
            return f"ERR:{type(exc).__name__}"

except Exception:  # pragma: no cover
    def _fetch_status(url: str, timeout: int = 15):  # type: ignore
        return "ERR:no-urllib"


FORBIDDEN = ["http://", "auth_key", "bexp.135editor.com", "file:"]

# 承载平台（不计入"独立来源多样性"，且合计占比须 <50%）
CARRIER_PLATFORMS = ("财联社", "科创板日报")

# 栏目最低条数
MIN_COUNT = {"热点资讯": 3, "国际资讯": 3, "国内资讯": 5, "企业动态": 6, "宏观政策": 3}

# 宏观政策栏必须是可执行的制度文件；出现下列字样直接判错
MACRO_FORBIDDEN_HINT = [
    "倡议", "宣言", "座谈会", "讲话", "致辞", "会见", "论坛上表示",
    "领导人会晤", "答记者问", "吹风会", "研讨会",
]

# 标题合法性：相对时间词可去掉，但不得自拟改写（除用户指定）
TITLE_REWRITE_OK_MARK = ("用户指定", "用户修订", "标题改回源标题", "源标题", "去时间词")

# 选题价值红线（命中即提示人工复核）
VALUE_RED_FLAGS = [
    "正式开启全国交付", "首批车主", "预售即售罄", "举办活动", "预告将于",
    "庆祝", "周年", "发布会现场", "签约仪式", "揭牌仪式",
]
# 非产业冲突类红线（不应进国际/国内资讯）
CONFLICT_RED_FLAGS = ["遭袭", "袭击", "商船改变航向", "击落", "交火", "军事行动", "空袭"]

SRC_TAIL_RE = re.compile(r"[（(]([^（）()]{2,14})[）)]\s*$")
SRC_SAY_RE = re.compile(r"据([\u4e00-\u9fa5A-Za-z]{2,12})(?:报道|消息|称|表示|发布|电|讯)")
SENT_SPLIT_RE = re.compile(r"[。；\n]")

# 泛称不算来源（"据媒体报道"这类不能当标签）
GENERIC_SOURCE = {
    "媒体", "外媒", "报道", "消息", "记者", "人士", "业内人士", "知情人士", "有关部门",
    "相关人士", "当地媒体", "国内媒体", "多家媒体", "官方", "网络", "新华", "央视",
}
# 来源标签与池判定不同时，属于同集团/同源的可豁免
SAME_GROUP = [
    {"财联社", "科创板日报"},
    {"华尔街见闻", "华尔街见闻网"},
]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="产业朝闻交付前自检")
    ap.add_argument("--selected", required=True, help="selected.json 路径")
    ap.add_argument("--pool", default="", help="完整新闻池.json 路径（用于标题/来源比对）")
    ap.add_argument("--out-dir", default="", help="渲染输出目录（含 html / txt / 核查表）")
    ap.add_argument("--stamp", default="", help="日期戳，如 2026-09-14；留空则自动探测")
    ap.add_argument("--skip-links", action="store_true", help="跳过链接可达性检查（离线时使用）")
    ap.add_argument("--strict", action="store_true", help="把提示项也视为错误")
    return ap.parse_args()


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warns: list[str] = []
        self.infos: list[str] = []

    def err(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warns.append(msg)

    def info(self, msg: str) -> None:
        self.infos.append(msg)

    def dump(self, strict: bool) -> int:
        print("=" * 72)
        print("产业朝闻交付前自检报告")
        print("=" * 72)
        for tag, rows in (("错误", self.errors), ("警告", self.warns), ("提示", self.infos)):
            icon = {"错误": "✗", "警告": "!", "提示": "-"}[tag]
            for m in rows:
                print(f"[{icon} {tag}] {m}")
        print("-" * 72)
        print(f"错误 {len(self.errors)} / 警告 {len(self.warns)} / 提示 {len(self.infos)}")
        if self.errors:
            print("结论：不可交付，请先修正错误项。")
            return 1
        if strict and self.warns:
            print("结论：strict 模式下警告视为错误，不可交付。")
            return 1
        print("结论：通过（警告项请人工确认后交付）。")
        return 0


def load_pool(path: str) -> dict[str, dict]:
    if not path or not Path(path).exists():
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data if isinstance(data, list) else data.get("items", [])
    if isinstance(items, dict):
        flat: list[dict] = []
        for v in items.values():
            if isinstance(v, list):
                flat += v
        items = flat or [items]
    by_url: dict[str, dict] = {}
    for it in items:
        for key in ("link", "url"):
            u = it.get(key)
            if u:
                by_url[u.strip()] = it
    return by_url


def extract_sources(text: str) -> set[str]:
    """从原文里抽取"括号标注来源"和"据XX"的来源候选。"""
    found: set[str] = set()
    for m in SRC_TAIL_RE.finditer(text or ""):
        found.add(m.group(1).strip())
    for m in SRC_SAY_RE.finditer(text or ""):
        found.add(m.group(1).strip())
    return found


def normalize(s: str) -> str:
    return re.sub(r"[\s，,。．.·、：:；;“”\"'（）()《》\-—!！?？]", "", s or "")


def title_similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def check_render(out_dir: str, stamp: str, rep: Report) -> None:
    if not out_dir:
        rep.info("未提供 --out-dir，跳过渲染文件检查")
        return
    d = Path(out_dir)
    if not d.exists():
        rep.err(f"输出目录不存在：{d}")
        return
    htmls = sorted(d.glob(f"*{stamp}*公众号排版.html")) or sorted(d.glob("*公众号排版.html"))
    txts = sorted(d.glob(f"*{stamp}*HTML代码.txt")) or sorted(d.glob("*HTML代码.txt"))
    links = sorted(d.glob(f"*{stamp}*原链接核查表.md")) or sorted(d.glob("*原链接核查表.md"))
    if not htmls:
        rep.err("缺少公众号排版 HTML")
    if not txts:
        rep.err("缺少 HTML 源码 TXT")
    if not links:
        rep.err("缺少原链接核查表 MD")
    if not (htmls and txts):
        return
    hb = htmls[0].read_bytes()
    tb = txts[0].read_bytes()
    hs = hb.decode("utf-8", "ignore")
    for bad in FORBIDDEN:
        if bad in hs:
            rep.err(f"HTML 含禁用串 {bad!r}")
    if hb == tb:
        rep.info("HTML 与源码 TXT 字节一致")
    else:
        # 预览面板会往 HTML 注入 data-page-node-id，并把 <strong > 这类空属性写法规范化
        def _normalize(s: str) -> str:
            s = re.sub(r'\s*data-page-node-id="[^"]*"', "", s)
            s = re.sub(r"<(\w+)\s+>", r"<\1>", s)
            return s

        hs_n = _normalize(hs)
        tb_n = _normalize(tb.decode("utf-8", "ignore"))
        if hs_n == tb_n:
            rep.info("HTML/TXT 差异仅来自预览面板注入属性与标签规范化（平台行为），以源码 TXT 为准")
        else:
            diff = [
                x
                for x in difflib.unified_diff(hs_n.splitlines(), tb_n.splitlines(), lineterm="", n=0)
                if x.startswith(("+", "-")) and not x.startswith(("+++", "---"))
            ][:6]
            rep.err("HTML 与源码 TXT 内容不一致（非平台注入差异）：" + " | ".join(diff))


def check_items(items: dict[str, list[dict]], pool: dict[str, dict], rep: Report) -> None:
    labels: list[str] = []
    domains: set[str] = set()
    carrier = 0
    total = 0
    for cat, lst in items.items():
        if not lst:
            rep.err(f"栏目《{cat}》为空")
            continue
        low = MIN_COUNT.get(cat, 0)
        if len(lst) < low:
            rep.warn(f"栏目《{cat}》仅 {len(lst)} 条，低于建议下限 {low} 条")
    for cat, lst in items.items():
        for it in lst:
            total += 1
            title = it.get("title", "").strip()
            src = (it.get("source") or "").strip()
            url = (it.get("url") or "").strip()
            note = it.get("note", "") or ""
            summary = it.get("summary", "") or ""
            tag = f"[{cat}]《{title[:24]}》"
            if not title:
                rep.err(f"[{cat}] 存在空标题")
            if not src:
                rep.err(f"{tag} 缺少来源标签")
            if len(summary) < 40:
                rep.warn(f"{tag} 正文过短（{len(summary)} 字），疑似一句话快讯")
            if url:
                dom = urlparse(url).netloc
                if dom:
                    domains.add(dom)
            else:
                rep.err(f"{tag} 缺少原链接")
            if src:
                labels.append(src)
                if any(p in src for p in CARRIER_PLATFORMS):
                    carrier += 1
            # 选题价值红线
            for flag in VALUE_RED_FLAGS:
                if flag in title or flag in summary[:60]:
                    rep.warn(f"{tag} 命中价值红线“{flag}”，请确认是否有真实产业信息增量")
                    break
            # 冲突类不应进国际/国内资讯
            if cat in ("国际资讯", "国内资讯"):
                for flag in CONFLICT_RED_FLAGS:
                    if flag in title:
                        rep.err(f"{tag} 命中冲突类红线“{flag}”，战争冲突本身不属产业选题")
                        break
            # 池内比对：标题与来源
            if pool and url in pool:
                poolit = pool[url]
                ptitle = (poolit.get("title") or "").strip()
                if ptitle and title and normalize(title) != normalize(ptitle):
                    sim = title_similar(title, ptitle)
                    msg = f"{tag} 标题与源标题不一致（相似度 {sim:.2f}）→ 源标题：{ptitle[:40]}"
                    if any(m in note for m in TITLE_REWRITE_OK_MARK):
                        rep.info(msg + "（已备注理由，合规）")
                    else:
                        rep.err(msg + "；如确为改写，请在 note 写明理由")
                plabel = (poolit.get("source_label") or "").strip()
                text = (poolit.get("content") or "") + (poolit.get("title") or "")
                if plabel and src and plabel not in src and src not in plabel:
                    if src in text:
                        rep.info(f"{tag} 来源标签【{src}】取自原文提及的原始媒体，合规")
                    elif any({plabel, src} <= g for g in SAME_GROUP):
                        rep.info(f"{tag} 来源标签【{src}】与池判定【{plabel}】属同一媒体集团，视为合规")
                    else:
                        rep.warn(f"{tag} 来源标签【{src}】与抓取池判定【{plabel}】不同，请确认未把承载平台当来源")
                # 原文标注来源硬校验
                evid = extract_sources(text)
                strong = {e for e in evid if len(e) >= 2 and e not in GENERIC_SOURCE}
                if strong and src and not any(e in src or src in e for e in strong):
                    # 池判定与之冲突时以原文标注为准
                    rep.err(
                        f"{tag} 来源标签【{src}】与原文标注来源 {sorted(strong)} 不一致（来源标签硬规则）"
                    )
            # 宏观政策专项
            if cat == "宏观政策":
                if not it.get("official_source"):
                    rep.err(f"{tag} 宏观政策未标 official_source=true（必须官网核验）")
                for hint in MACRO_FORBIDDEN_HINT:
                    if hint in title:
                        rep.err(f"{tag} 宏观政策含“{hint}”，不符合“国家发布的可执行条例”标准")
                        break
                pub = str(it.get("published_at", ""))
                disclosed = any(k in note for k in ("补位", "披露", "目标新闻日", "目标日")) or (
                    bool(stamp) and stamp[:10] in note
                )
                if not disclosed:
                    rep.warn(f"{tag} 未在 note 披露发布日期与目标新闻日的关系")
                if pub[:10] and re.match(r"\d{4}-\d{2}-\d{2}", pub):
                    rep.info(f"{tag} 标注发布日期 {pub[:10]}")
    # 来源分布
    if total:
        ratio = carrier / total
        if ratio >= 0.5:
            rep.err(f"财联社/科创板日报承载占比 {ratio:.0%}（{carrier}/{total}），须 <50%")
        else:
            rep.info(f"财联社/科创板日报承载占比 {ratio:.0%}（{carrier}/{total}），合规")
        if len(domains) < 3:
            rep.err(f"独立承载域名仅 {len(domains)} 个（{sorted(domains)}），至少需 3 个")
        else:
            rep.info(f"独立承载域名 {len(domains)} 个")
        dup = [f"{k}×{v}" for k, v in Counter(labels).items() if v > 1]
        if dup:
            rep.info("来源标签出现多次（正常，仅提示）：" + "、".join(dup))
    # 跨栏重复主题
    allitems = [(c, it) for c, lst in items.items() for it in lst]
    for i in range(len(allitems)):
        for j in range(i + 1, len(allitems)):
            c1, a = allitems[i]
            c2, b = allitems[j]
            sim = title_similar(a.get("title", ""), b.get("title", ""))
            if sim >= 0.55:
                rep.warn(
                    f"疑似重复选题（相似度 {sim:.2f}）：[{c1}]《{a.get('title','')[:22]}》 × [{c2}]《{b.get('title','')[:22]}》"
                )


def check_links(items: dict[str, list[dict]], rep: Report) -> None:
    pairs = [(c, it) for c, lst in items.items() for it in lst if (it.get("url") or "").strip()]
    if not pairs:
        return

    def probe(pair):
        cat, it = pair
        url = it["url"].strip()
        return cat, it, url, _fetch_status(url)

    with ThreadPoolExecutor(max_workers=8) as ex:
        for cat, it, url, status in ex.map(probe, pairs):
            ok = status == 200 or (isinstance(status, int) and 200 <= status < 400)
            title = (it.get("title") or "")[:22]
            if isinstance(status, int) and status in (403, 401, 429):
                rep.warn(f"[{cat}]《{title}》链接返回 {status}（反爬拦截，需人工点开确认）：{url}")
            elif not ok:
                rep.err(f"[{cat}]《{title}》链接不可用（{status}）→ 必须更换：{url}")


def main() -> int:
    args = parse_args()
    rep = Report()
    raw = json.loads(Path(args.selected).read_text(encoding="utf-8"))
    items = raw.get("items", raw)
    if not isinstance(items, dict):
        print("selected.json 结构异常：缺少 items 字典")
        return 1
    stamp = args.stamp or ""
    if not stamp:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", str(raw.get("publish_date") or raw.get("date") or ""))
        if m:
            stamp = m.group(1)
    pool = load_pool(args.pool) if args.pool else {}
    if args.pool and not pool:
        rep.warn(f"未能读取新闻池（{args.pool}），跳过标题/来源比对")
    check_render(args.out_dir, stamp, rep)
    check_items(items, pool, rep)
    if args.skip_links:
        rep.info("已跳过链接可达性检查（--skip-links）")
    else:
        check_links(items, rep)
    return rep.dump(args.strict)


if __name__ == "__main__":
    sys.exit(main())
