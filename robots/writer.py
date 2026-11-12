"""ReceptionistMatch writer robot (build plan s1/s3/s5). One post per run.

Picks the first queue item in state/rm_queue.json with status "ready" and gate "passed"
(the desk passes the topic gate by hand: Bing volume + top-10 owners logged, 0c.1), grounds
it in the vendor pricing-page snapshots, writes Markdown with Claude Opus 5.5 (effort medium),
then an editor pass (a second Opus 5.5 call: non-price claims vs the snapshots, math, logic,
voice; fails closed), then the deterministic honesty gate (robots/honesty.py): one revision pass on problems,
then strip-not-abort, then abort if anything is left. Inserts contextual links to the new page
into >= 3 existing guides (exact-match anchors only). The workflow builds, runs the CI gates,
commits, deploys and verifies the live URL.

Usage:
  python3 robots/writer.py              # write the next ready item
  python3 robots/writer.py --dry-run    # print the pick + prompt size, no API call, no writes
  python3 robots/writer.py --fixture f.json  # use a saved tool output instead of the API (tests; skips editor)
  python3 robots/writer.py --fixture f.json --edit-fixture e.json  # also test the editor merge offline
  python3 robots/writer.py --edit-only <slug> [--write]  # run the editor on a published post
Exit codes: 0 wrote a post (or nothing ready), 2 aborted by a gate.
"""
import datetime as dt
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import honesty  # noqa: E402

ROOT = honesty.ROOT
POSTS = os.path.join(ROOT, "src/content/posts")
QUEUE = os.path.join(ROOT, "state/rm_queue.json")
LOG = os.path.join(ROOT, "state/writer_log.jsonl")
MIN_LINKS = 3
SNAP_CHARS = 14000

BRAND = """BRAND: ReceptionistMatch, an independent buyer's guide to AI receptionists and live answering
services for small local businesses (HVAC, plumbing, dental, law, salons, home services).
Readers are busy owners on a phone between jobs, skeptical of software pitches.
TONE: plain, blunt, numbers first. A knowledgeable friend who read every pricing page. Calm. No hype.
RULES (hard):
- Answer first. Sentence one gives the answer with a real vendor name, a dollar price and a link to that
  vendor's own pricing page. The next line: "Prices come from each vendor's own pricing page, checked <date>."
- A Markdown lookup table within the first 400 words.
- Every dollar figure must come from the snapshots below, attributed to the vendor it belongs to. Computed
  numbers (totals, per-minute math) must be marked with "about" right before the number.
- External links ONLY to the vendor pricing URLs given below. Internal links as /slug/.
- Say "AI receptionist" (software) and "answering service" (live people) plainly; keep them distinct.
- Name who each option is for AND who it is NOT for ("**Not for you if** ...").
- Short sentences, second person. 600-1,100 words. H2 sections (##), no H1.
- NEVER: "we tested", "hands-on", "in our experience", invented customers/quotes/stats, exclamation points,
  em dashes, "game-changing", "revolutionary", "best-in-class", "seamless", "unlock", "supercharge",
  "never miss a call again". If a fact isn't in the snapshots, write "the pricing page doesn't say".
- Rank by fit, never by commission. Do not mention affiliate payouts."""

TOOL = {
    "name": "publish_post",
    "description": "Return the finished post and the internal-link insertions.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "<= 60 characters"},
            "description": {"type": "string", "description": "meta description, 80-160 characters"},
            "body_markdown": {"type": "string", "description": "post body in Markdown, no frontmatter, no H1"},
            "link_insertions": {
                "type": "array",
                "description": "3-4 sentences to add to EXISTING guides, each linking to the new post",
                "items": {"type": "object", "properties": {
                    "slug": {"type": "string", "description": "existing post slug"},
                    "after_text": {"type": "string", "description": "exact text (20-120 chars) copied from that post, ending a sentence; the new sentence goes right after it"},
                    "sentence": {"type": "string", "description": "one sentence, no dollar figures, containing a Markdown link to /<new-slug>/"}},
                    "required": ["slug", "after_text", "sentence"]}},
        },
        "required": ["title", "description", "body_markdown", "link_insertions"],
    },
}


def log(event):
    event["at"] = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"
    with open(LOG, "a") as fh:
        fh.write(json.dumps(event) + "\n")
    print(json.dumps(event))


def pick(queue):
    for item in queue["items"]:
        if item.get("status") == "ready" and item.get("gate") == "passed" \
                and not os.path.exists(os.path.join(POSTS, item["slug"] + ".md")):
            return item
    return None


def grounding(item):
    slugs = item.get("vendors") or [v["slug"] for v in honesty.VENDORS]
    parts, dates = [], []
    for s in slugs:
        v = honesty.G[s]["v"]
        date, text, data = honesty.latest_snapshot(s)
        if not date:
            continue
        dates.append(date)
        plans = json.dumps(data.get("plans", []), ensure_ascii=False)
        parts.append(f"### {v['name']} ({v['kind']}) pricing page {v['pricingUrl']} checked {date}\n"
                     f"Extracted plans: {plans}\nPage text:\n{text[:SNAP_CHARS]}")
    return "\n\n".join(parts), max(dates) if dates else dt.date.today().isoformat()


def existing_posts():
    out = []
    for f in sorted(glob.glob(os.path.join(POSTS, "*.md"))):
        slug = os.path.basename(f)[:-3]
        if slug == "sample-render-test":
            continue
        fm, body, _ = honesty.split_frontmatter(open(f).read())
        if fm.get("draft") == "true":
            continue
        out.append({"slug": slug, "title": fm.get("title", ""), "body": body})
    return out


def build_prompt(item, ground, checked, posts):
    nice = dt.date.fromisoformat(checked).strftime("%B %-d, %Y")
    others = "\n\n".join(f"=== /{p['slug']}/ : {p['title']}\n{p['body']}" for p in posts)
    return f"""{BRAND}

PAGE TO WRITE
- Target search: "{item['keyword']}"   page type: {item['type']}   URL: /{item['slug']}/
- Angle (why this page deserves to exist; one post per search, never repeat an existing page): {item['angle']}
- Prices checked: {nice}

EXISTING GUIDES (do not repeat their job; link to them where useful; link insertions go INTO these):
{others}

VENDOR SNAPSHOTS (the only allowed source of prices and features):
{ground}
"""


def call_model(prompt, fixture=None, revise=None):
    if fixture:
        return json.load(open(fixture))
    import anthropic
    from writer_model import writer_tool_call
    msgs = [{"role": "user", "content": prompt}]
    if revise:
        msgs += [{"role": "assistant", "content": "Draft:\n" + json.dumps(revise["draft"])[:60000]},
                 {"role": "user", "content": "The honesty gate flagged these problems. Fix every one (use the "
                  "snapshot numbers exactly, attribute each price to its own vendor, mark computed numbers with "
                  "'about', remove banned words) and return the full corrected post:\n"
                  + "\n".join(f"- line {p[0]} [{p[1]}] {p[2]}" for p in revise["problems"])}]
    resp = writer_tool_call(anthropic.Anthropic(), tools=[TOOL], messages=msgs, max_tokens=24000,
                            tool_choice={"type": "tool", "name": "publish_post"})
    for b in resp.content:
        if b.type == "tool_use" and b.name == "publish_post":
            return b.input
    raise SystemExit("writer returned no publish_post call")


EDIT_TOOL = {
    "name": "edit_post",
    "description": "Return the edited post and a list of every change you made.",
    "input_schema": {
        "type": "object",
        "properties": {
            "changes": {
                "type": "array",
                "description": "every change, in order; empty if the draft needed none",
                "items": {"type": "object", "properties": {
                    "kind": {"type": "string", "enum": ["unsupported_claim", "wrong_vendor", "math", "logic", "voice", "other"]},
                    "before": {"type": "string", "description": "the original text (short quote)"},
                    "after": {"type": "string", "description": "the replacement, or empty if cut"},
                    "why": {"type": "string", "description": "one line; for claims, what the snapshot says or that it is silent"}},
                    "required": ["kind", "before", "after", "why"]}},
            "title": {"type": "string", "description": "<= 60 characters"},
            "description": {"type": "string", "description": "meta description, 80-160 characters"},
            "body_markdown": {"type": "string", "description": "the FULL edited body in Markdown, no frontmatter, no H1"},
        },
        "required": ["changes", "title", "description", "body_markdown"],
    },
}

EDITOR_BRIEF = """You are the editor for ReceptionistMatch. A writer drafted the post below. Your job is to make it
true, correct and tight before it goes live. A code gate already checks every dollar figure against the
snapshots, so you focus on what code cannot check. Work through the draft line by line:

1. CLAIMS. Every statement about a vendor (features, plan limits, transfers, trials, contracts, cancellation,
   billing rules, who it is for) must be supported by THAT vendor's snapshot text below. If a claim is not
   supported, rewrite it to what the snapshot does say, or to "the pricing page doesn't say", or cut it.
   A claim credited to the wrong vendor is a "wrong_vendor" change. Do not add facts from memory.
2. MATH. Recompute every total, per-unit figure and worked example from the snapshot plans. Fix any that are
   wrong; computed numbers keep "about" right before them.
3. LOGIC. Recommendations, "Not for you if" lines and the How-to-pick steps must follow from the numbers and
   facts on the page. Remove advice that contradicts the tables.
4. VOICE. Apply the brand rules: plain, blunt, short sentences, second person, no hype, no banned words,
   no em dashes, no exclamation points. Tighten padding. Do not rewrite sentences that are already fine.

Keep: the structure (H2 sections, tables), the opening answer line with its vendor link and price, the
"Prices come from..." line, every link that is still accurate, and 600-1,100 words. Never add a new dollar
figure that is not in the snapshots. Never add links. Log every change you make in `changes`."""


def edit_post(prompt, draft, fixture=None):
    """Editor pass: a second Opus 5.5 call that fact-checks non-price claims, math, logic and voice."""
    if fixture:
        return json.load(open(fixture))
    import anthropic
    from writer_model import writer_tool_call
    msgs = [{"role": "user", "content": prompt + "\n\n" + EDITOR_BRIEF + "\n\nDRAFT TO EDIT:\n"
             + json.dumps({k: draft[k] for k in ("title", "description", "body_markdown")}, ensure_ascii=False)}]
    resp = writer_tool_call(anthropic.Anthropic(), tools=[EDIT_TOOL], messages=msgs, max_tokens=24000,
                            tool_choice={"type": "tool", "name": "edit_post"})
    for b in resp.content:
        if b.type == "tool_use" and b.name == "edit_post":
            return b.input
    raise SystemExit("editor returned no edit_post call")


def apply_edit(draft, edited):
    """Merge the editor's output into the draft. Returns (post, why_rejected or None)."""
    body = (edited.get("body_markdown") or "").strip()
    before, after = len(draft["body_markdown"].split()), len(body.split())
    if after < 0.6 * before or after < 450:
        return draft, f"edited body {after} words vs draft {before}; looks truncated"
    out = dict(draft)
    out.update(title=edited.get("title") or draft["title"],
               description=edited.get("description") or draft["description"], body_markdown=body)
    return out, None


def assemble(item, out, checked):
    fm = ["---", f'title: "{out["title"].strip()}"', f'description: "{out["description"].strip()}"',
          f"type: {item['type']}", f"published: {dt.date.today().isoformat()}", f"pricesChecked: {checked}",
          f"keyword: {item['keyword']}", "draft: false", "---"]
    body = re.sub(r"^#\s.*\n", "", out["body_markdown"].strip() + "\n")
    return "\n".join(fm) + "\n" + body


def apply_links(item, insertions):
    done, notes = {}, []
    for ins in insertions:
        slug, after, sent = ins["slug"], ins["after_text"], ins["sentence"].strip()
        f = os.path.join(POSTS, slug + ".md")
        if slug in done or slug == item["slug"] or not os.path.exists(f):
            notes.append(f"skip {slug}: missing or duplicate")
            continue
        if f"](/{item['slug']}/)" not in sent or "$" in sent or any(b in sent.lower() for b in honesty.BANNED):
            notes.append(f"skip {slug}: sentence must link /{item['slug']}/ with no $ and no banned words")
            continue
        text = open(f).read()
        if text.count(after) != 1:
            notes.append(f"skip {slug}: anchor found {text.count(after)} times")
            continue
        done[slug] = text.replace(after, after + " " + sent, 1)
    return done, notes


def edit_only(slug, write=False):
    """Run the editor on an existing post (review tool). Prints the change list; --write saves it
    only if the honesty gate still passes."""
    f = os.path.join(POSTS, slug + ".md")
    fm, body, _ = honesty.split_frontmatter(open(f).read())
    queue = json.load(open(QUEUE))
    item = next(i for i in queue["items"] if i["slug"] == slug)
    ground, checked = grounding(item)
    posts = [p for p in existing_posts() if p["slug"] != slug]
    draft = {"title": fm.get("title", ""), "description": fm.get("description", ""), "body_markdown": body}
    edited = edit_post(build_prompt(item, ground, checked, posts), draft)
    out, rejected = apply_edit(draft, edited)
    for c in edited.get("changes", []):
        print(f"[{c['kind']}] {c['before']!r}\n   -> {c['after']!r}\n   why: {c['why']}")
    if rejected:
        print("REJECTED:", rejected)
        return 2
    text = open(f).read()
    head = text[:text.index("\n---", 3) + 4]
    head = re.sub(r'^title: ".*"$', f'title: "{out["title"].strip()}"', head, flags=re.M)
    head = re.sub(r'^description: ".*"$', f'description: "{out["description"].strip()}"', head, flags=re.M)
    md = head + "\n" + out["body_markdown"].strip() + "\n"
    problems = honesty.check(md)
    print(f"{len(edited.get('changes', []))} changes; honesty gate: {problems or 'pass'}")
    if write and not problems:
        open(f, "w").write(md)
        print("written", f)
    return 2 if problems else 0


def main():
    dry = "--dry-run" in sys.argv
    fixture = sys.argv[sys.argv.index("--fixture") + 1] if "--fixture" in sys.argv else None
    edit_fixture = sys.argv[sys.argv.index("--edit-fixture") + 1] if "--edit-fixture" in sys.argv else None
    if "--edit-only" in sys.argv:
        return edit_only(sys.argv[sys.argv.index("--edit-only") + 1], "--write" in sys.argv)
    queue = json.load(open(QUEUE))
    item = pick(queue)
    if not item:
        print("nothing ready in the queue (status ready + gate passed); no post today")
        return 0
    ground, checked = grounding(item)
    prompt = build_prompt(item, ground, checked, existing_posts())
    print(f"pick: {item['slug']} ({item['type']}) | prompt ~{len(prompt) // 4:,} tokens | checked {checked}")
    if dry:
        return 0

    out = call_model(prompt, fixture)
    edits = []
    if not fixture or edit_fixture:
        edited = edit_post(prompt, out, edit_fixture)
        out, rejected = apply_edit(out, edited)
        if rejected:
            log({"slug": item["slug"], "result": "ABORT", "why": "editor: " + rejected})
            return 2
        edits = edited.get("changes", [])
        print(f"editor: {len(edits)} changes " + json.dumps(
            {k: sum(e.get("kind") == k for e in edits) for k in {e.get("kind") for e in edits}}))
    md = assemble(item, out, checked)
    problems = honesty.check(md)
    if problems and not fixture:
        print(f"revision pass for {len(problems)} problems")
        out = call_model(prompt, revise={"draft": out, "problems": problems})
        md = assemble(item, out, checked)
        problems = honesty.check(md)
    dropped = []
    if problems:
        md, dropped = honesty.strip(md, problems)
        problems = honesty.check(md)
    if problems:
        log({"slug": item["slug"], "result": "ABORT", "problems": problems, "stripped": dropped})
        return 2

    links, notes = apply_links(item, out.get("link_insertions", []))
    if len(links) < MIN_LINKS:
        log({"slug": item["slug"], "result": "ABORT", "why": f"only {len(links)} link insertions applied",
             "notes": notes})
        return 2
    for slug, text in links.items():
        if honesty.check(text):
            log({"slug": item["slug"], "result": "ABORT", "why": f"link insertion broke {slug}"})
            return 2

    warnings = []
    honesty.check(md, warnings)
    with open(os.path.join(POSTS, item["slug"] + ".md"), "w") as fh:
        fh.write(md)
    for slug, text in links.items():
        with open(os.path.join(POSTS, slug + ".md"), "w") as fh:
            fh.write(text)
    item.update(status="published", published=dt.date.today().isoformat())
    with open(QUEUE, "w") as fh:
        json.dump(queue, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    log({"slug": item["slug"], "result": "WROTE", "title": out["title"], "words": len(md.split()),
         "stripped": dropped, "estimates": warnings, "editor_changes": edits, "linked_from": sorted(links), "link_notes": notes})
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as fh:
        fh.write(f"slug={item['slug']}\ntitle={out['title']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
