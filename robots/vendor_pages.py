"""Vendor-page snapshot (build plan section 2): the grounding every RM price claim traces to.

  python3 robots/vendor_pages.py snapshot [slug ...]   fetch pricing pages -> state/snapshots/<slug>/<date>.txt
  python3 robots/vendor_pages.py extract  [slug ...]   today's .txt -> <date>.json (plans, prices, trial...) via Claude

Extraction rule: every value carries the snapshot line number it came from, and the script drops any
value whose number/text is not literally on that line (trace check, no model judgment). A page that
blocks bots or ships no prices in raw HTML is recorded as "not published", never guessed.
"""
import datetime, html, json, os, re, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDORS = json.loads((ROOT / "src/data/vendors.json").read_text())["vendors"]
SNAP = ROOT / "state/snapshots"
TODAY = datetime.date.today().isoformat()
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
MODEL = "claude-opus-5-5"  # Michael's default (CLAUDE.md 2026-10-07): adaptive thinking, effort medium


def page_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|svg|head)\b.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr|td|th|section|span|a|button)>", "\n", raw)
    txt = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    lines = [re.sub(r"\s+", " ", l).strip() for l in txt.splitlines()]
    out, prev = [], None
    for l in lines:
        if l and l != prev:
            out.append(l)
        prev = l
    return "\n".join(out)


def snapshot(v) -> dict:
    d = SNAP / v["slug"]; d.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(v["pricingUrl"], headers={"User-Agent": UA, "Accept-Language": "en-US"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            status, raw = r.status, r.read().decode("utf-8", "replace")
    except Exception as e:  # 403s land here
        status, raw = getattr(e, "code", 0), ""
    text = page_text(raw) if raw else ""
    prices = len(re.findall(r"\$\s?\d", text))
    head = f"# {v['name']} | {v['pricingUrl']} | fetched {TODAY} | HTTP {status} | {prices} price mentions\n"
    (d / f"{TODAY}.txt").write_text(head + text)
    return {"slug": v["slug"], "status": status, "lines": text.count("\n") + 1 if text else 0, "prices": prices}


TOOL = {"name": "record_pricing", "description": "Record the vendor's published plans exactly as the snapshot states them.",
        "input_schema": {"type": "object", "properties": {
            "plans": {"type": "array", "items": {"type": "object", "properties": {
                "name": {"type": "string"}, "price": {"type": "string", "description": "verbatim, e.g. '$99/mo' or '$0.07/min'"},
                "billing": {"type": "string", "description": "monthly | annual | per-minute | usage | unknown"},
                "included": {"type": "string", "description": "minutes/calls included, verbatim or ''"},
                "overage": {"type": "string"}, "line": {"type": "integer", "description": "snapshot line the price is on"}},
                "required": ["name", "price", "billing", "included", "overage", "line"]}},
            "setup_fee": {"type": "object", "properties": {"text": {"type": "string"}, "line": {"type": "integer"}}, "required": ["text", "line"]},
            "free_trial": {"type": "object", "properties": {"text": {"type": "string"}, "line": {"type": "integer"}}, "required": ["text", "line"]},
            "notes": {"type": "string"}},
            "required": ["plans", "setup_fee", "free_trial", "notes"]}}


def traced(val: str, line_no: int, lines: list) -> bool:
    if not val or not (1 <= line_no <= len(lines)):
        return False
    window = " ".join(lines[max(0, line_no - 2): line_no + 1]).lower()  # line +/-1 (prices often split from units)
    nums = re.findall(r"\d[\d,.]*", val)
    return all(n.rstrip(".,") in window for n in nums) if nums else val.lower()[:20] in window


def extract(v) -> dict:
    import anthropic
    p = SNAP / v["slug"] / f"{TODAY}.txt"
    if not p.exists():
        return {"slug": v["slug"], "error": "no snapshot today"}
    head, _, body = p.read_text().partition("\n")
    lines = body.splitlines()
    out = {"vendor": v["name"], "url": v["pricingUrl"], "checked": TODAY, "source": str(p.relative_to(ROOT))}
    if len(re.findall(r"\$\s?\d", body)) == 0:
        out.update(published=False, plans=[], note="price on request / not published in the page's raw HTML")
    else:
        numbered = "\n".join(f"{i}: {l}" for i, l in enumerate(lines, 1))[:180000]
        r = anthropic.Anthropic().messages.create(
            model=MODEL, max_tokens=16000, thinking={"type": "adaptive"}, output_config={"effort": "medium"},
            tools=[TOOL], tool_choice={"type": "auto"},
            messages=[{"role": "user", "content": f"Pricing page snapshot for {v['name']} (line-numbered):\n\n{numbered}\n\n"
                       "Record only what the page states. Copy prices verbatim and give the line number each is on. "
                       "Use '' and line 0 for a setup fee or trial the page does not mention. Answer only by calling record_pricing, exactly once."}])
        call = next((b.input for b in r.content if b.type == "tool_use"), None)
        if not call:
            return {"slug": v["slug"], "error": f"no tool call ({r.stop_reason})"}
        kept, dropped = [], []
        for pl in call["plans"]:
            (kept if traced(pl["price"], pl["line"], lines) else dropped).append(pl)
        out.update(published=bool(kept), plans=kept, dropped_untraced=dropped, notes=call.get("notes", ""))
        for k in ("setup_fee", "free_trial"):
            f = call.get(k) or {}
            out[k] = f if f.get("text") and traced(f["text"], f.get("line", 0), lines) else None
    (SNAP / v["slug"] / f"{TODAY}.json").write_text(json.dumps(out, indent=1))
    return {"slug": v["slug"], "plans": len(out["plans"]), "dropped": len(out.get("dropped_untraced", [])), "published": out["published"]}


if __name__ == "__main__":
    cmd, picks = sys.argv[1], set(sys.argv[2:])
    todo = [v for v in VENDORS if not picks or v["slug"] in picks]
    for v in todo:
        print(json.dumps((snapshot if cmd == "snapshot" else extract)(v)))
