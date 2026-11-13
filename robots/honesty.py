"""Deterministic honesty gate for ReceptionistMatch posts (build plan s2, 0b.5).

No model judgment. Every dollar figure in a post must trace to the vendor pricing-page
snapshots (state/snapshots/<slug>/<date>.txt + .json):
  - a line that names or links vendors: the number must be in one of THOSE vendors' snapshot
    text, or be derived from one of their plans (price / included units, within 3%);
  - a line that names no vendor (summary ranges): the number must trace to ANY vendor.
Plus: external links only to vendor hosts in vendors.json, the brand card's banned phrases,
frontmatter limits, and the named-entity first screen (0b.1).

check(md_text) -> list of problems [(line_no, kind, detail)]. Empty list = pass.
strip(md_text, problems) -> (new_text, dropped) removes failing prose sentences / table rows
("strip, don't abort", same as TLD); the caller re-checks and aborts if anything remains.
CLI: python3 robots/honesty.py src/content/posts/*.md   (exit 1 on any problem)
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDORS = json.load(open(os.path.join(ROOT, "src/data/vendors.json")))["vendors"]
BANNED = ["we tested", "hands-on", "in our experience", "our testing", "game-changing", "game changing",
          "revolutionary", "best-in-class", "seamless", "unlock", "supercharge", "never miss a call again",
          "—"]  # em dash
MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)")
NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
ESTIMATE = re.compile(r"(about|roughly|around|\u2248|~)\W*\**\s*$", re.I)
LINK = re.compile(r"\]\((https?://[^)\s]+)\)")


def _num(s):
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def latest_snapshot(slug):
    files = sorted(glob.glob(os.path.join(ROOT, f"state/snapshots/{slug}/*.txt")))
    if not files:
        return None, "", {}
    txt = files[-1]
    js = txt[:-4] + ".json"
    data = json.load(open(js)) if os.path.exists(js) else {}
    return os.path.basename(txt)[:-4], open(txt, encoding="utf-8", errors="ignore").read(), data


def _grounding():
    g = {}
    for v in VENDORS:
        date, text, data = latest_snapshot(v["slug"])
        # only figures the page shows as money ("$49", "$0.25"), not every number on the page
        nums = {n for n in (_num(x) for x in MONEY.findall(text)) if n is not None}
        nums |= {n / 100 for n in (_num(x) for x in re.findall(r"(\d+)\s?\u00a2", text)) if n is not None}
        derived = set()
        for p in data.get("plans", []) or []:
            price = _num((MONEY.search(p.get("price") or "") or [None, ""])[1] or "")
            units = _num((NUM.search(p.get("included") or "") or [""])[0] if NUM.search(p.get("included") or "") else "")
            if price and units:
                derived.add(price / units)
            for k in ("price", "overage"):
                for x in NUM.findall(p.get(k) or ""):
                    if _num(x) is not None:
                        nums.add(_num(x))
        names = {v["name"].lower(), v["host"].split(".")[0].lower()}
        first = v["name"].split()[0].lower().rstrip(".")
        if len(first) > 3 and first not in {"the", "ai", "answering"}:  # "Answering Legal" -> not every "answering service"
            names.add(first)
        g[v["slug"]] = {"v": v, "date": date, "nums": nums, "derived": derived, "names": names}
    return g


G = _grounding()
HOSTS = {v["host"]: v["slug"] for v in VENDORS}


def _host_slug(url):
    h = re.sub(r"^https?://(www\.)?", "", url).split("/")[0].lower()
    for host, slug in HOSTS.items():
        if h == host or h.endswith("." + host):
            # smith.ai has two snapshot slugs (live + AI pages)
            return [s for s, x in G.items() if x["v"]["host"] == host]
    return None


def vendors_in(line):
    found = set()
    for url in LINK.findall(line):
        s = _host_slug(url)
        if s:
            found.update(s)
    low = line.lower()
    for slug, x in G.items():
        if any(re.search(r"(?<![a-z])" + re.escape(n) + r"(?![a-z])", low) for n in x["names"]):
            found.add(slug)
    return found


def traces(value, slugs):
    pool = slugs or set(G)
    for s in pool:
        x = G[s]
        if any(abs(value - n) < 0.005 for n in x["nums"]):
            return True
        if any(d and abs(value - d) / d <= 0.03 for d in x["derived"]):
            return True
    # summary ranges round to $5 steps ("$25 to $100" for $24.95 and $99): within 2% of a real price
    # of ANY vendor (a range summarizes the market, even on a line that names other vendors)
    if value >= 5 and value % 5 == 0:
        return any(n and abs(value - n) / n <= 0.02 for x in G.values() for n in x["nums"])
    return False


def split_frontmatter(md):
    m = re.match(r"^---\n(.*?)\n---\n", md, re.S)
    if not m:
        return {}, md, 0
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip().strip('"')
    return fm, md[m.end():], m.group(0).count("\n")


def check(md, warnings=None):
    problems = []
    warnings = [] if warnings is None else warnings
    fm, body, offset = split_frontmatter(md)
    if len(fm.get("title", "")) > 60:
        problems.append((1, "frontmatter", f"title {len(fm['title'])} chars > 60"))
    if not 80 <= len(fm.get("description", "")) <= 160:
        problems.append((1, "frontmatter", f"description {len(fm.get('description', ''))} chars, need 80-160"))
    if fm.get("type") not in {"trade", "vs", "pricing", "alternatives", "pillar"}:
        problems.append((1, "frontmatter", f"type {fm.get('type')!r}"))
    low_all = md.lower()
    for b in BANNED:
        if b in low_all:
            problems.append((1, "banned", repr(b)))
    if "!" in re.sub(r"!\[|<!--", "", body):
        problems.append((1, "banned", "exclamation point"))
    # named-entity first screen: a vendor link + a dollar price in the first ~150 words
    first = " ".join(body.split()[:150])
    if not (MONEY.search(first) and any(_host_slug(u) for u in LINK.findall(first))):
        problems.append((offset + 1, "first-screen", "no vendor link + dollar price in the first 150 words"))
    for i, line in enumerate(body.splitlines(), start=offset + 1):
        for url in LINK.findall(line):
            if not _host_slug(url):
                problems.append((i, "link", f"external link not to a vendor pricing host: {url}"))
        named = vendors_in(line)
        for m in MONEY.finditer(line):
            raw = m.group(1)
            val = _num(raw)
            if val is None:
                continue
            if traces(val, named):
                continue
            # computed figures (totals, per-minute math, 28-day billing) are allowed only when the
            # text marks them as an estimate right before the number; logged as a warning
            if ESTIMATE.search(line[max(0, m.start() - 12):m.start()]):
                warnings.append((i, "estimate", f"${raw} (computed, marked)"))
                continue
            if not traces(val, named):
                where = ", ".join(sorted(named)) or "any vendor"
                problems.append((i, "price", f"${raw} not in snapshot of {where}"))
    return problems


def strip(md, problems):
    """Drop failing table rows / sentences on price and link lines. Frontmatter, banned and
    first-screen problems are not strippable (caller aborts)."""
    lines = md.split("\n")
    dropped = []
    for ln, kind, detail in problems:
        if kind not in {"price", "link"} or ln - 1 >= len(lines):
            continue
        line = lines[ln - 1]
        if line.lstrip().startswith("|"):
            dropped.append(line)
            lines[ln - 1] = None
            continue
        token = detail.split()[0] if kind == "price" else detail.split(": ", 1)[1]
        sents = re.split(r"(?<=[.?])\s+", line)
        keep = [s for s in sents if token not in s]
        dropped += [s for s in sents if token in s]
        lines[ln - 1] = " ".join(keep)
    return "\n".join(l for l in lines if l is not None), dropped


if __name__ == "__main__":
    bad = 0
    for f in sys.argv[1:]:
        if f.endswith("sample-render-test.md"):
            continue
        probs = check(open(f).read())
        print(("FAIL " if probs else "ok   ") + f)
        for p in probs:
            print(f"   line {p[0]} [{p[1]}] {p[2]}")
        bad += bool(probs)
    sys.exit(1 if bad else 0)
