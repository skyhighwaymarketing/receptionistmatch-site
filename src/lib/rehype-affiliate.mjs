// Marks affiliate links rel="sponsored nofollow noopener" (FTC + Google guidance; WAG Hub 362 gotcha f).
// A link is affiliate when its URL carries a tracking param, or its host is in src/data/affiliates.json.
import fs from 'node:fs';

const PARAMS = ['fp_ref', 'ref', 'via', 'aff', 'affiliate', 'partner', 'irclickid', 'utm_source=receptionistmatch'];
const registry = JSON.parse(fs.readFileSync(new URL('../data/affiliates.json', import.meta.url), 'utf8'));
const HOSTS = new Set(registry.vendors.filter(v => v.status === 'approved').map(v => v.host));

export function isAffiliate(href) {
  let u;
  try { u = new URL(href); } catch { return false; }
  if (u.hostname.endsWith('receptionistmatch.com')) return false;
  if (HOSTS.has(u.hostname.replace(/^www\./, ''))) return true;
  const q = u.search.toLowerCase();
  return PARAMS.some(p => q.includes(p.includes('=') ? p : `${p}=`));
}

export default function rehypeAffiliate() {
  const walk = (node) => {
    if (node.type === 'element' && node.tagName === 'a' && typeof node.properties?.href === 'string') {
      const href = node.properties.href;
      if (isAffiliate(href)) {
        node.properties.rel = ['sponsored', 'nofollow', 'noopener'];
        node.properties.dataAffiliate = 'true';
      } else if (/^https?:/.test(href) && !href.includes('receptionistmatch.com')) {
        node.properties.rel = ['noopener'];
      }
    }
    (node.children || []).forEach(walk);
  };
  return (tree) => walk(tree);
}
