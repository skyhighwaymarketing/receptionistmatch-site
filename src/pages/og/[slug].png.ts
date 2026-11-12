// Per-post share card (1200x630 PNG) at /og/<slug>.png, built with every deploy.
// Same look as public/og-default.png: ink navy, paper text, one coral accent (brand card).
// satori lays out the card with the real brand fonts (static TTFs in src/assets/fonts), sharp rasterizes it.
import type { APIRoute } from 'astro';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import satori from 'satori';
import sharp from 'sharp';
import { livePosts, KIND, fmt } from '../../lib/posts';

const FONTS = join(process.cwd(), 'src/assets/fonts');
const font = (f: string) => readFileSync(join(FONTS, f));
const fonts = [
  { name: 'Fraunces', data: font('Fraunces-SemiBold.ttf'), weight: 600 as const, style: 'normal' as const },
  { name: 'Inter', data: font('Inter-Medium.ttf'), weight: 500 as const, style: 'normal' as const },
  { name: 'Inter', data: font('Inter-SemiBold.ttf'), weight: 600 as const, style: 'normal' as const },
];

const MARK = 'data:image/svg+xml;base64,' + Buffer.from(
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="#F6F4EF"/>' +
  '<path d="M10.2 9.5c.9-.9 2.3-.9 3.1 0l1.6 1.7c.7.7.8 1.9.1 2.7l-.9 1c.9 1.8 2.3 3.2 4.1 4.1l1-.9c.8-.7 2-.6 2.7.1l1.7 1.6c.9.8.9 2.2 0 3.1l-.8.8c-1.2 1.2-3.1 1.5-4.6.7-3.6-1.9-6.5-4.8-8.4-8.4-.8-1.5-.5-3.4.7-4.6z" fill="#0E1726"/>' +
  '<circle cx="23" cy="9" r="3" fill="#E8613C"/></svg>').toString('base64');

type Node = { type: string; props: Record<string, unknown> };
const el = (type: string, style: Record<string, unknown>, children?: unknown, extra = {}): Node =>
  ({ type, props: { style, children, ...extra } });

export async function getStaticPaths() {
  const posts = await livePosts();
  return posts.map((post) => ({ params: { slug: post.id }, props: { post } }));
}

export const GET: APIRoute = async ({ props }) => {
  const d = (props as any).post.data;
  const size = d.title.length <= 36 ? 82 : d.title.length <= 50 ? 72 : 64;
  const card = el('div', {
    width: 1032, height: 486, display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
    padding: '72px 84px', background: '#0E1726',
    backgroundImage: 'radial-gradient(circle at 1080px 120px, rgba(246,244,239,0) 0, rgba(246,244,239,0) 180px, rgba(246,244,239,0.035) 181px, rgba(246,244,239,0.035) 250px, rgba(246,244,239,0) 251px, rgba(246,244,239,0) 320px, rgba(246,244,239,0.022) 321px, rgba(246,244,239,0.022) 390px, rgba(246,244,239,0) 391px)', color: '#F6F4EF', fontFamily: 'Inter',
  }, [
    el('div', { display: 'flex', alignItems: 'center', gap: 18, fontSize: 34, fontWeight: 600 }, [
      el('img', {}, undefined, { src: MARK, width: 60, height: 60 }),
      el('div', {}, 'ReceptionistMatch'),
    ]),
    el('div', { display: 'flex', flexDirection: 'column', gap: 22 }, [
      el('div', { fontSize: 24, fontWeight: 600, letterSpacing: 3, textTransform: 'uppercase', color: '#E8613C' },
        KIND[d.type] ?? 'Guide'),
      el('div', { fontFamily: 'Fraunces', fontSize: size, lineHeight: 1.08, letterSpacing: -0.5, maxWidth: 1030 }, d.title),
    ]),
    el('div', { display: 'flex', alignItems: 'center', gap: 22, fontSize: 27, fontWeight: 500, color: '#B9C0CC' }, [
      el('div', { width: 56, height: 4, background: '#E8613C', borderRadius: 2 }),
      el('div', {}, `Prices from each vendor's own page, checked ${fmt(d.pricesChecked)}`),
    ]),
  ]);
  const svg = await satori(card as any, { width: 1200, height: 630, fonts });
  const png = await sharp(Buffer.from(svg)).png({ compressionLevel: 9, palette: true, quality: 90 }).toBuffer();
  return new Response(png, { headers: { 'Content-Type': 'image/png' } });
};
