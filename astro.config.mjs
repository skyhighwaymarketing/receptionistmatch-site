import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';
import rehypeAffiliate from './src/lib/rehype-affiliate.mjs';

// Static site on GitHub Pages, apex host only (one self-canonical per page).
export default defineConfig({
  site: 'https://receptionistmatch.com',
  trailingSlash: 'always',
  build: { format: 'directory' },
  integrations: [sitemap({ filter: (page) => !page.includes('/404') })],
  markdown: { rehypePlugins: [rehypeAffiliate] },
});
