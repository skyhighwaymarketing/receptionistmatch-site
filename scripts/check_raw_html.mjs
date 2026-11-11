// Raw-HTML gate for every built page (WAG Hub 362 gotchas + brand card). No JS runs: this is what
// GPTBot and Bingbot see. Exit 1 on any failure so CI and the publish robot stop.
import fs from 'node:fs';
import path from 'node:path';

const DIST = process.argv[2] || 'dist';
const BANNED = [/we tested/i, /hands-on/i, /in our experience/i, /never miss a call again/i, /game-changing/i,
  /revolutionary/i, /best-in-class/i, /\bseamless/i, /\bunlock/i, /supercharge/i, /—/];
const files = [];
const walk = (d) => fs.readdirSync(d, { withFileTypes: true }).forEach((e) => {
  const p = path.join(d, e.name);
  e.isDirectory() ? walk(p) : p.endsWith('.html') && files.push(p);
});
walk(DIST);

let bad = 0;
const fail = (f, msg) => { bad++; console.log(`FAIL ${path.relative(DIST, f)}: ${msg}`); };
for (const f of files) {
  const html = fs.readFileSync(f, 'utf8');
  const is404 = f.endsWith('404.html');
  const canon = [...html.matchAll(/<link rel="canonical" href="([^"]+)"/g)].map((m) => m[1]);
  if (!is404) {
    if (canon.length !== 1) fail(f, `${canon.length} canonical tags (need exactly 1)`);
    else {
      const want = 'https://receptionistmatch.com/' + path.relative(DIST, path.dirname(f)).split(path.sep).filter(Boolean).map((s) => s + '/').join('');
      if (canon[0] !== want) fail(f, `canonical ${canon[0]} != ${want}`);
    }
  }
  if (!/<h1[\s>]/.test(html)) fail(f, 'no <h1> in raw HTML');
  const body = html.slice(html.indexOf('<body'));
  const text = body.replace(/<script[\s\S]*?<\/script>/g, '').replace(/<style[\s\S]*?<\/style>/g, '').replace(/<[^>]+>/g, ' ');
  for (const re of BANNED) if (re.test(text)) fail(f, `banned phrase ${re}`);
  const links = [...body.matchAll(/<a\b[^>]*>/g)].map((m) => ({ tag: m[0], at: m.index }));
  const aff = links.filter((l) => /data-affiliate/.test(l.tag));
  for (const l of aff) if (!/rel="sponsored nofollow noopener"/.test(l.tag)) fail(f, `affiliate link missing rel=sponsored: ${l.tag}`);
  if (aff.length) {
    const disc = body.indexOf('class="disclosure"');
    if (disc < 0 || disc > aff[0].at) fail(f, 'affiliate link appears before the disclosure');
  }
  // Named-entity first screen (WAG Hub 364 audit, 2026-11-11): generic posts don't get indexed.
  // Every article names a dollar price and links a vendor's own page within its first ~150 words.
  const pi = body.indexOf('class="prose"');
  if (pi >= 0) {
    const proseHtml = body.slice(pi);
    let words = 0, cut = proseHtml.length;
    for (const m of proseHtml.matchAll(/>([^<]+)</g)) {
      words += m[1].trim().split(/\s+/).filter(Boolean).length;
      if (words >= 150) { cut = m.index; break; }
    }
    const first = proseHtml.slice(0, cut);
    if (!/\$\s?\d/.test(first.replace(/<[^>]+>/g, ' '))) fail(f, 'no dollar price in the first ~150 words');
    if (!/<a\b[^>]*href="https?:\/\/(?!receptionistmatch\.com)[^"]+"/.test(first)) fail(f, 'no vendor link in the first ~150 words');
    if (!/Prices checked /.test(body)) fail(f, 'no prices-checked stamp');
  }
  for (const img of body.matchAll(/<img\b[^>]*>/g)) {
    if (!/\balt="[^"]+"/.test(img[0])) fail(f, `img without alt: ${img[0].slice(0, 80)}`);
    if (!/\bwidth=/.test(img[0]) || !/\bheight=/.test(img[0])) fail(f, `img without width/height: ${img[0].slice(0, 80)}`);
  }
}
const keyFiles = fs.readdirSync(DIST).filter((n) => /^[0-9a-f]{32}\.txt$/.test(n));
if (keyFiles.length !== 1) { bad++; console.log(`FAIL IndexNow key file at root: found ${keyFiles.length}`); }
for (const need of ['sitemap-index.xml', 'robots.txt', 'CNAME', '404.html']) if (!fs.existsSync(path.join(DIST, need))) { bad++; console.log(`FAIL missing ${need}`); }
console.log(bad ? `${bad} problem(s) in ${files.length} pages` : `OK: ${files.length} pages pass the raw-HTML gate`);
process.exit(bad ? 1 : 0);
