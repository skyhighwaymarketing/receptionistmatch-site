# receptionistmatch.com

Static Astro site on GitHub Pages. Independent buyer's guides to AI receptionists and answering services.
Owner: the Blog Fleet desk (~/blog-analytics). Build plan: ~/blog-analytics/RECEPTIONISTMATCH_BUILD_PLAN.md.

- Posts: one Markdown file per post in `src/content/posts/` (schema in `src/content.config.ts`). `draft: true` stays out of production.
- `npm run build` then `node scripts/check_raw_html.mjs`: the raw-HTML gate (one canonical, sponsored affiliate links, disclosure before the first affiliate link, banned phrases, img alt/size, IndexNow key, sitemap).
- Affiliate registry for the site: `src/data/affiliates.json` (mirror of RECEPTIONISTMATCH_AFFILIATES.md). Rankings never read payout.
- Deploy: `.github/workflows/deploy.yml` on push to main. Pages source must be "GitHub Actions".
- Local preview with drafts: `SHOW_DRAFTS=1 npx astro dev`.
