// Inbound-link gate (build plan 0c gate 5): every article needs links from >= MIN distinct other
// pages, counted inside <main> only (header nav and footer don't count). Exit 1 on a shortfall.
// Usage: node scripts/check_links.mjs [dist] [min]
import fs from 'node:fs';
import path from 'node:path';

const DIST = process.argv[2] || 'dist';
const MIN = Number(process.argv[3] || 5);
const pages = {};
const walk = (d) => fs.readdirSync(d, { withFileTypes: true }).forEach((e) => {
  const p = path.join(d, e.name);
  if (e.isDirectory()) return walk(p);
  if (!p.endsWith('index.html')) return;
  const url = '/' + path.relative(DIST, path.dirname(p)).split(path.sep).filter(Boolean).map((s) => s + '/').join('');
  pages[url] = fs.readFileSync(p, 'utf8');
});
walk(DIST);

const inbound = {};
for (const [src, html] of Object.entries(pages)) {
  const main = (html.match(/<main\b[\s\S]*?<\/main>/) || [''])[0];
  const targets = new Set([...main.matchAll(/<a\b[^>]*href="([^"#?]+)/g)]
    .map((m) => m[1].replace(/^https:\/\/receptionistmatch\.com/, ''))
    .filter((h) => h.startsWith('/') && h !== src));
  for (const t of targets) (inbound[t] ||= new Set()).add(src);
}
const articles = Object.entries(pages).filter(([, h]) => /<article class="article"/.test(h)).map(([u]) => u);
let bad = 0;
for (const u of articles.sort()) {
  const n = inbound[u]?.size || 0;
  console.log(`${n >= MIN ? 'ok  ' : 'FAIL'} ${n} inbound  ${u}${n < MIN ? `  (from: ${[...(inbound[u] || [])].join(', ') || 'none'})` : ''}`);
  if (n < MIN) bad++;
}
console.log(bad ? `${bad} of ${articles.length} articles under ${MIN} inbound links` : `OK: ${articles.length} articles have >= ${MIN} inbound links`);
process.exit(bad ? 1 : 0);
