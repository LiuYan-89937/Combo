/*
 * Per-route document head management for a static SPA. Sets title, description,
 * canonical, Open Graph / Twitter tags and an optional JSON-LD block, then
 * restores nothing — each navigation calls this again with fresh values.
 *
 * Robots crawl the pre-rendered index.html for the base tags; this keeps the
 * head correct for social unfurls and in-app navigation.
 */
import { onBeforeUnmount, watchEffect } from 'vue'

const SITE_NAME = 'FastAgentFactory'
const ORIGIN = 'https://liuyanai.top'

export interface SeoInput {
  title: string
  description?: string
  path?: string
  image?: string
  type?: 'website' | 'article'
  jsonLd?: Record<string, unknown> | null
  noindex?: boolean
}

function upsertMeta(selector: string, attr: 'name' | 'property', key: string, content: string) {
  let el = document.head.querySelector<HTMLMetaElement>(selector)
  if (!el) {
    el = document.createElement('meta')
    el.setAttribute(attr, key)
    document.head.appendChild(el)
  }
  el.setAttribute('content', content)
}

function upsertLink(rel: string, href: string) {
  let el = document.head.querySelector<HTMLLinkElement>(`link[rel="${rel}"]`)
  if (!el) {
    el = document.createElement('link')
    el.setAttribute('rel', rel)
    document.head.appendChild(el)
  }
  el.setAttribute('href', href)
}

const JSONLD_ID = 'faf-route-jsonld'

export function useSeo(input: () => SeoInput) {
  watchEffect(() => {
    const seo = input()
    const fullTitle = seo.title.includes(SITE_NAME) ? seo.title : `${seo.title} — ${SITE_NAME}`
    document.title = fullTitle

    const url = `${ORIGIN}${seo.path ?? window.location.pathname}`
    const image = seo.image ?? `${ORIGIN}/og-cover.png`
    const desc = seo.description ?? ''

    if (desc) upsertMeta('meta[name="description"]', 'name', 'description', desc)
    upsertLink('canonical', url)
    upsertMeta('meta[name="robots"]', 'name', 'robots', seo.noindex ? 'noindex,follow' : 'index,follow')

    upsertMeta('meta[property="og:title"]', 'property', 'og:title', fullTitle)
    upsertMeta('meta[property="og:description"]', 'property', 'og:description', desc)
    upsertMeta('meta[property="og:type"]', 'property', 'og:type', seo.type ?? 'website')
    upsertMeta('meta[property="og:url"]', 'property', 'og:url', url)
    upsertMeta('meta[property="og:image"]', 'property', 'og:image', image)
    upsertMeta('meta[property="og:site_name"]', 'property', 'og:site_name', SITE_NAME)

    upsertMeta('meta[name="twitter:card"]', 'name', 'twitter:card', 'summary_large_image')
    upsertMeta('meta[name="twitter:title"]', 'name', 'twitter:title', fullTitle)
    upsertMeta('meta[name="twitter:description"]', 'name', 'twitter:description', desc)
    upsertMeta('meta[name="twitter:image"]', 'name', 'twitter:image', image)

    const existing = document.getElementById(JSONLD_ID)
    if (existing) existing.remove()
    if (seo.jsonLd) {
      const script = document.createElement('script')
      script.type = 'application/ld+json'
      script.id = JSONLD_ID
      script.textContent = JSON.stringify(seo.jsonLd)
      document.head.appendChild(script)
    }
  })

  onBeforeUnmount(() => {
    document.getElementById(JSONLD_ID)?.remove()
  })
}

export { ORIGIN, SITE_NAME }
