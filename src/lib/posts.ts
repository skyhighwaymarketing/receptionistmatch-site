import { getCollection } from 'astro:content';
export const KIND: Record<string, string> = { trade: 'By trade', vs: 'Comparison', pricing: 'Pricing', alternatives: 'Alternatives', pillar: 'Guide' };
const showDrafts = import.meta.env.SHOW_DRAFTS === '1';
export async function livePosts() {
  const all = await getCollection('posts', ({ data }) => showDrafts || !data.draft);
  return all.sort((a, b) => b.data.published.valueOf() - a.data.published.valueOf());
}
export const fmt = (d: Date) => d.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC' });
