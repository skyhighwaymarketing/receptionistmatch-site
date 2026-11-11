import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

// One Markdown file per post, written by the publish robot (build plan section 3).
const posts = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/posts' }),
  schema: z.object({
    title: z.string().max(60),
    description: z.string().min(80).max(160),
    type: z.enum(['trade', 'vs', 'pricing', 'alternatives', 'pillar']),
    published: z.coerce.date(),
    updated: z.coerce.date().optional(),
    pricesChecked: z.coerce.date(),
    keyword: z.string().optional(),
    hasAffiliateLinks: z.boolean().default(false),
    draft: z.boolean().default(false),
  }),
});

export const collections = { posts };
