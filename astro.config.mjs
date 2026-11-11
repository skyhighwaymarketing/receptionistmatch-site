import fs from 'node:fs';
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';
import rehypeAffiliate from './src/lib/rehype-affiliate.mjs';

// lastmod per URL (build plan 0c gate 4): posts use `updated` or `published` from front matter;
// hub pages (home, guides) use the newest post date; static pages carry no lastmod.
const POSTS = './src/content/posts';
const postDates = {};
for (const f of fs.existsSync(POSTS) ? fs.readdirSync(POSTS).filter((n) => n.endsWith('.md')) : []) {
  const fm = (fs.readFileSync(`${POSTS}/${f}`, 'utf8').match(/^---\n([\s\S]*?)\n---/) || [])[1] || '';
  if (/^draft:\s*true/m.test(fm)) continue;
  const d = (fm.match(/^updated:\s*(\S+)/m) || fm.match(/^published:\s*(\S+)/m) || [])[1];
  if (d) postDates[f.replace(/\.md$/, '')] = new Date(d).toISOString();
}
const newest = Object.values(postDates).sort().pop();

// Static site on GitHub Pages, apex host only (one self-canonical per page).
export default defineConfig({
  site: 'https://receptionistmatch.com',
  trailingSlash: 'always',
  build: { format: 'directory' },
  integrations: [sitemap({
    filter: (page) => !page.includes('/404'),
    serialize(item) {
      const slug = new URL(item.url).pathname.replace(/^\/|\/$/g, '');
      const lastmod = postDates[slug] ?? (['', 'guides'].includes(slug) ? newest : undefined);
      return lastmod ? { ...item, lastmod } : item;
    },
  })],
  markdown: { rehypePlugins: [rehypeAffiliate] },
});
