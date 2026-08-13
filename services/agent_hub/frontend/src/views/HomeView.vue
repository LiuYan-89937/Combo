<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import BaseButton from '@/components/base/BaseButton.vue'
import ComboFrameAnimation from '@/components/brand/ComboFrameAnimation.vue'
import ProductShowcase from '@/components/home/ProductShowcase.vue'
import { useI18n } from '@/i18n'
import { useConfigStore } from '@/stores/config'
import { useSeo, ORIGIN } from '@/composables/useSeo'
import { formatCount } from '@/composables/useFormat'

const { t } = useI18n()
const { config } = storeToRefs(useConfigStore())

const preferredPlatform = computed<'macos' | 'windows'>(() => (
  typeof navigator !== 'undefined' && /windows/i.test(navigator.userAgent) ? 'windows' : 'macos'
))
const orderedDownloads = computed(() => [...config.value.downloads].sort((left, right) => (
  left.platform === preferredPlatform.value ? -1 : right.platform === preferredPlatform.value ? 1 : 0
)))
const primaryDownload = computed(() => orderedDownloads.value.find(item => item.url) || null)
const hasDownload = computed(() => config.value.downloads.some(item => item.url))

const capabilities = computed(() => [
  { key: 'skill', index: '01', icon: '/brand/combo/ui-icons/plan.png' },
  { key: 'tool', index: '02', icon: '/brand/combo/ui-icons/send.png' },
  { key: 'mcp', index: '03', icon: '/brand/combo/ui-icons/collaboration.png' },
  { key: 'knowledge', index: '04', icon: '/brand/combo/ui-icons/context.png' },
])

const controlPoints = computed(() => [
  { key: 'workspace', icon: '/brand/combo/ui-icons/empty-workspace.png' },
  { key: 'approval', icon: '/brand/combo/ui-icons/permission.png' },
  { key: 'recovery', icon: '/brand/combo/ui-icons/finish-flag.png' },
])

useSeo(() => ({
  title: t('home.title'),
  description: t('home.subtitle'),
  path: '/',
  jsonLd: {
    '@context': 'https://schema.org',
    '@type': 'SoftwareApplication',
    name: 'Combo',
    applicationCategory: 'DeveloperApplication',
    operatingSystem: 'macOS, Windows',
    url: ORIGIN,
    offers: { '@type': 'Offer', price: '0', priceCurrency: 'USD' },
    description: t('home.subtitle'),
  },
}))
</script>

<template>
  <div class="home">
    <section class="hero">
      <div class="hero__atmosphere" aria-hidden="true"><i /><i /><i /><i /><i /></div>
      <div class="container hero__layout">
        <div class="hero__copy">
          <span class="hero__badge"><i />{{ t('home.badge') }}</span>
          <h1>{{ t('home.title') }}</h1>
          <p>{{ t('home.subtitle') }}</p>
          <div class="hero__actions">
            <BaseButton
              v-if="primaryDownload"
              :href="primaryDownload.url"
              size="lg"
              icon="download"
            >
              {{ t('home.ctaPlatformDownload', { platform: primaryDownload.label }) }}
            </BaseButton>
            <BaseButton v-else to="/#download" size="lg" icon="download">
              {{ t('home.ctaDownload') }}
            </BaseButton>
            <BaseButton to="/#how-it-works" size="lg" variant="ghost" icon-end="chevron-down">
              {{ t('home.ctaWatch') }}
            </BaseButton>
          </div>
          <p class="hero__note">{{ t('home.heroNote') }}</p>
        </div>

        <div class="hero-scene" aria-hidden="true">
          <div class="hero-scene__rhythm rhythm--one" /><div class="hero-scene__rhythm rhythm--two" /><div class="hero-scene__rhythm rhythm--three" />
          <div class="hero-scene__bubble">
            <span>{{ t('home.heroPrompt') }}</span>
            <i />
          </div>
          <div class="hero-scene__mascot">
            <span class="mascot-halo" />
            <ComboFrameAnimation character="paired" action="thinking" :size="276" />
          </div>
          <span class="capability-pill pill--skill"><i />Skill</span>
          <span class="capability-pill pill--tool"><i />Tool</span>
          <span class="capability-pill pill--mcp"><i />MCP</span>
          <span class="capability-pill pill--knowledge"><i />Knowledge</span>
          <div class="hero-scene__task">
            <ComboFrameAnimation character="companion" action="running" :size="44" />
            <span><strong>{{ t('home.heroTaskTitle') }}</strong><small>{{ t('home.heroTaskBody') }}</small></span>
            <i />
          </div>
          <div class="hero-scene__status"><i />{{ t('home.heroStatus') }}</div>
        </div>
      </div>
    </section>

    <ProductShowcase />

    <section id="capabilities" class="capability-section section">
      <div class="container">
        <header class="section-head section-head--split">
          <div><span class="eyebrow">{{ t('home.capabilityEyebrow') }}</span><h2>{{ t('home.capabilityTitle') }}</h2></div>
          <p>{{ t('home.capabilitySubtitle') }}</p>
        </header>
        <div class="capability-composer">
          <article v-for="capability in capabilities" :key="capability.key" class="capability-card">
            <header><span>{{ capability.index }}</span><img :src="capability.icon" alt="" /></header>
            <h3>{{ t(`home.capabilities.${capability.key}.title`) }}</h3>
            <p>{{ t(`home.capabilities.${capability.key}.description`) }}</p>
          </article>
          <div class="composer-center" aria-hidden="true">
            <span class="composer-ring composer-ring--outer" />
            <span class="composer-ring composer-ring--inner" />
            <ComboFrameAnimation character="paired" action="idle" :size="152" />
            <strong>COMBO</strong>
          </div>
        </div>
      </div>
    </section>

    <section class="control-section section">
      <div class="container control-section__layout">
        <div class="control-copy">
          <span class="eyebrow">{{ t('home.controlEyebrow') }}</span>
          <h2>{{ t('home.controlTitle') }}</h2>
          <p>{{ t('home.controlSubtitle') }}</p>
        </div>
        <div class="control-points">
          <article v-for="point in controlPoints" :key="point.key">
            <img :src="point.icon" alt="" />
            <div><strong>{{ t(`home.controlPoints.${point.key}.title`) }}</strong><span>{{ t(`home.controlPoints.${point.key}.description`) }}</span></div>
          </article>
        </div>
      </div>
    </section>

    <section id="download" class="download-section section">
      <div class="container download-shell">
        <div class="download-mascot" aria-hidden="true">
          <span class="download-mascot__halo" />
          <ComboFrameAnimation character="paired" action="idle" :size="220" />
        </div>
        <header class="download-copy">
          <span class="eyebrow">{{ t('nav.download') }}</span>
          <h2>{{ t('home.downloadTitle') }}</h2>
          <p>{{ t('home.downloadSubtitle') }}</p>
          <span class="download-count">{{ t('home.totalDownloads', { count: formatCount(config.totalDownloadCount) }) }}</span>
        </header>
        <div class="download-grid">
          <article v-for="(download, index) in orderedDownloads" :key="`${download.platform}-${download.arch}`" :class="{ preferred: index === 0 }">
            <span v-if="index === 0" class="recommended">{{ t('home.recommended') }}</span>
            <div class="download-platform"><strong>{{ download.label }}</strong><span>{{ download.arch }}</span></div>
            <div class="download-meta"><span>v{{ download.version || '—' }}</span><span>{{ download.sizeLabel || '—' }}</span></div>
            <BaseButton v-if="download.url" :href="download.url" block icon="download">{{ t('home.downloadFor', { platform: download.label }) }}</BaseButton>
            <BaseButton v-else block disabled variant="secondary">{{ t('home.downloadUnavailable') }}</BaseButton>
          </article>
        </div>
        <p v-if="!hasDownload" class="download-soon">{{ t('home.downloadComingSoon') }}</p>
        <div class="download-steps">
          <span><i>1</i>{{ t('home.downloadSteps.install') }}</span>
          <span><i>2</i>{{ t('home.downloadSteps.model') }}</span>
          <span><i>3</i>{{ t('home.downloadSteps.start') }}</span>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.home { overflow: clip; color: var(--text); background: var(--surface); }
.hero { position: relative; display: flex; min-height: calc(100vh - var(--header-height)); align-items: center; overflow: hidden; padding: clamp(72px, 9vw, 122px) 0; }
.hero::before { position: absolute; inset: 0; background-image: radial-gradient(circle at 1px 1px, var(--border) .8px, transparent 0); background-size: 38px 38px; mask-image: linear-gradient(to bottom, black 5%, transparent 92%); content: ''; opacity: .55; pointer-events: none; }
.hero__atmosphere { position: absolute; inset: 0; pointer-events: none; }
.hero__atmosphere i { position: absolute; width: 5px; height: 5px; border-radius: 50%; background: var(--text-strong); opacity: .18; animation: ambient-note 8s ease-in-out infinite; }
.hero__atmosphere i:nth-child(1) { top: 18%; left: 8%; }.hero__atmosphere i:nth-child(2) { top: 72%; left: 17%; animation-delay: -2s; }.hero__atmosphere i:nth-child(3) { top: 22%; right: 14%; animation-delay: -4s; }.hero__atmosphere i:nth-child(4) { right: 5%; bottom: 18%; animation-delay: -6s; }.hero__atmosphere i:nth-child(5) { top: 10%; left: 52%; animation-delay: -3s; }
.hero__layout { position: relative; display: grid; grid-template-columns: minmax(0, .94fr) minmax(480px, 1.06fr); align-items: center; gap: clamp(48px, 7vw, 110px); }
.hero__copy { max-width: 690px; }
.hero__badge { display: inline-flex; align-items: center; gap: 9px; padding: 6px 12px; border: 1px solid var(--border-strong); border-radius: 999px; color: var(--text-secondary); background: color-mix(in srgb, var(--surface) 84%, transparent); font: 10px/1.2 var(--font-mono); letter-spacing: .12em; text-transform: uppercase; }
.hero__badge i, .hero-scene__status i { width: 6px; height: 6px; border-radius: 50%; background: var(--text-strong); animation: status-breathe 1.8s ease-in-out infinite; }
.hero h1 { max-width: 740px; margin: 24px 0 24px; color: var(--text-strong); font-size: clamp(58px, 6.3vw, 94px); font-weight: 780; line-height: .96; letter-spacing: -.075em; text-wrap: balance; }
.hero__copy > p:not(.hero__note) { max-width: 640px; margin: 0; color: var(--text-secondary); font-size: clamp(17px, 1.5vw, 21px); line-height: 1.72; }
.hero__actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 34px; }
.hero__note { margin: 15px 0 0; color: var(--text-muted); font-size: 11px; }
.hero-scene { position: relative; min-height: 590px; }
.hero-scene::before { position: absolute; inset: 7% 3% 5%; border: 1px solid var(--border-strong); border-radius: 44% 56% 48% 52% / 50% 42% 58% 50%; background: color-mix(in srgb, var(--surface-subtle) 70%, transparent); content: ''; animation: scene-shape 13s ease-in-out infinite alternate; }
.hero-scene__rhythm { position: absolute; left: 5%; width: 88%; height: 1px; background: linear-gradient(90deg, transparent, var(--border-strong) 18%, var(--border-strong) 82%, transparent); transform-origin: center; }
.rhythm--one { top: 33%; transform: rotate(-5deg); }.rhythm--two { top: 50%; transform: rotate(3deg); }.rhythm--three { top: 66%; transform: rotate(-2deg); }
.hero-scene__mascot { position: absolute; top: 48%; left: 50%; display: grid; place-items: center; transform: translate(-50%, -50%); }
.mascot-halo { position: absolute; width: 270px; height: 270px; border: 1px solid var(--border-strong); border-radius: 50%; box-shadow: 0 0 0 38px color-mix(in srgb, var(--text-strong) 2%, transparent), 0 0 0 76px color-mix(in srgb, var(--text-strong) 1.2%, transparent); animation: halo-pulse 4s ease-in-out infinite; }
.hero-scene__bubble { position: absolute; top: 6%; left: 2%; z-index: 2; display: flex; max-width: 330px; align-items: center; gap: 12px; padding: 14px 16px; border: 1px solid var(--border-strong); border-radius: 18px 18px 18px 4px; color: var(--text); background: color-mix(in srgb, var(--surface) 92%, transparent); box-shadow: var(--shadow-soft); font-size: 11px; line-height: 1.5; animation: float-soft 5.5s ease-in-out infinite; }
.hero-scene__bubble i { width: 8px; height: 8px; flex: none; border-radius: 50%; background: var(--text-strong); }
.capability-pill { position: absolute; z-index: 2; display: flex; align-items: center; gap: 7px; padding: 8px 11px; border: 1px solid var(--border-strong); border-radius: 999px; color: var(--text-secondary); background: color-mix(in srgb, var(--surface) 92%, transparent); box-shadow: var(--shadow-soft); font: 9px/1 var(--font-mono); letter-spacing: .08em; text-transform: uppercase; animation: float-soft 6s ease-in-out infinite; }
.capability-pill i { width: 5px; height: 5px; border-radius: 50%; background: var(--text-strong); }.pill--skill { top: 24%; left: 0; animation-delay: -1s; }.pill--tool { top: 20%; right: 1%; animation-delay: -3s; }.pill--mcp { bottom: 21%; left: 3%; animation-delay: -4s; }.pill--knowledge { right: 0; bottom: 29%; animation-delay: -2s; }
.hero-scene__task { position: absolute; right: 4%; bottom: 5%; z-index: 3; display: grid; width: 230px; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 8px; padding: 8px 10px 8px 6px; border: 1px solid var(--border-strong); border-radius: 18px; background: color-mix(in srgb, var(--surface) 94%, transparent); box-shadow: 0 18px 50px color-mix(in srgb, var(--text-strong) 12%, transparent); animation: float-soft 4.8s ease-in-out infinite -2s; }
.hero-scene__task > span { display: grid; min-width: 0; gap: 2px; }.hero-scene__task strong { overflow: hidden; color: var(--text-strong); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }.hero-scene__task small { color: var(--text-muted); font-size: 8px; }.hero-scene__task > i { width: 6px; height: 6px; border-radius: 50%; background: var(--text-strong); animation: status-breathe 1.5s ease-in-out infinite; }
.hero-scene__status { position: absolute; bottom: 8%; left: 8%; display: flex; align-items: center; gap: 8px; color: var(--text-muted); font: 8px/1 var(--font-mono); letter-spacing: .13em; text-transform: uppercase; }
.section-head--split { display: grid; grid-template-columns: minmax(0, 1fr) minmax(300px, .65fr); align-items: end; gap: 50px; }
.section-head h2 { max-width: 780px; margin: 12px 0 0; color: var(--text-strong); font-size: clamp(42px, 5.5vw, 74px); font-weight: 760; line-height: 1; letter-spacing: -.06em; }
.section-head > p { margin: 0; color: var(--text-secondary); font-size: 16px; line-height: 1.75; }
.capability-section { position: relative; background: var(--surface-subtle); }
.capability-composer { position: relative; display: grid; min-height: 680px; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; margin-top: 64px; }
.capability-card { position: relative; display: flex; min-height: 260px; flex-direction: column; padding: 25px; overflow: hidden; border: 1px solid var(--border-strong); border-radius: 24px; background: var(--surface); transition: transform 320ms var(--ease-out), box-shadow 320ms var(--ease-out); }
.capability-card:hover { transform: translateY(-5px); box-shadow: 0 22px 60px color-mix(in srgb, var(--text-strong) 8%, transparent); }
.capability-card header { display: flex; align-items: center; justify-content: space-between; color: var(--text-muted); font: 10px/1 var(--font-mono); }
.capability-card img { width: 36px; height: 36px; object-fit: contain; filter: var(--brand-mark-filter); opacity: .8; }
.capability-card h3 { margin: auto 0 10px; color: var(--text-strong); font-size: 25px; letter-spacing: -.04em; }
.capability-card p { max-width: 390px; margin: 0; color: var(--text-secondary); font-size: 13px; line-height: 1.7; }
.capability-card:nth-child(1), .capability-card:nth-child(3) { padding-right: 150px; }.capability-card:nth-child(2), .capability-card:nth-child(4) { padding-left: 150px; }
.composer-center { position: absolute; top: 50%; left: 50%; z-index: 2; display: grid; width: 250px; height: 250px; place-items: center; border: 1px solid var(--border-strong); border-radius: 50%; background: color-mix(in srgb, var(--surface) 94%, transparent); box-shadow: 0 25px 70px color-mix(in srgb, var(--text-strong) 12%, transparent); transform: translate(-50%, -50%); }
.composer-center > * { grid-area: 1 / 1; }.composer-center strong { align-self: end; margin-bottom: 31px; color: var(--text-muted); font: 8px/1 var(--font-mono); letter-spacing: .2em; }
.composer-ring { width: 196px; height: 196px; border: 1px dashed var(--border-strong); border-radius: 50%; animation: spin-slow 22s linear infinite; }.composer-ring--inner { width: 145px; height: 145px; animation-direction: reverse; animation-duration: 16s; }

.control-section { border-block: 1px solid var(--border); background: var(--surface-subtle); }
.control-section__layout { display: grid; grid-template-columns: minmax(360px, .9fr) minmax(520px, 1.1fr); align-items: start; gap: clamp(52px, 8vw, 120px); }
.control-copy h2 { margin: 13px 0 20px; color: var(--text-strong); font-size: clamp(44px, 5.4vw, 72px); line-height: 1; letter-spacing: -.06em; }.control-copy > p { margin: 0; color: var(--text-secondary); font-size: 16px; line-height: 1.75; }
.control-points { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); border: 1px solid var(--border-strong); border-radius: 24px; background: var(--surface); }
.control-points article { display: grid; align-content: start; gap: 18px; min-height: 250px; padding: 26px 22px; }.control-points article + article { border-left: 1px solid var(--border); }.control-points img { width: 42px; height: 42px; object-fit: contain; filter: var(--brand-mark-filter); }.control-points article > div { display: grid; gap: 7px; margin-top: auto; }.control-points strong { color: var(--text-strong); font-size: 14px; }.control-points span { color: var(--text-secondary); font-size: 11px; line-height: 1.65; }

.download-section { padding-bottom: clamp(90px, 10vw, 150px); }.download-shell { position: relative; display: grid; grid-template-columns: 220px minmax(280px, .75fr) minmax(420px, 1fr); align-items: center; gap: clamp(26px, 5vw, 70px); padding-block: clamp(52px, 6vw, 82px); border-block: 1px solid var(--border-strong); }.download-mascot { position: relative; display: grid; place-items: center; }.download-mascot > * { grid-area: 1 / 1; }.download-mascot__halo { width: 180px; height: 180px; border: 1px solid var(--border); border-radius: 50%; box-shadow: 0 0 0 28px color-mix(in srgb, var(--text-strong) 2%, transparent); }.download-copy h2 { margin: 10px 0 15px; color: var(--text-strong); font-size: clamp(38px, 4.5vw, 62px); line-height: 1; letter-spacing: -.06em; }.download-copy p { margin: 0; color: var(--text-secondary); font-size: 13px; line-height: 1.7; }.download-count { display: block; margin-top: 16px; color: var(--text-muted); font: 9px/1 var(--font-mono); }.download-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }.download-grid article { position: relative; display: grid; gap: 18px; padding: 22px; border: 1px solid var(--border); border-radius: 20px; background: var(--surface); }.download-grid article.preferred { border-color: var(--text-strong); }.recommended { position: absolute; top: -10px; right: 15px; padding: 5px 8px; border-radius: 999px; color: var(--on-primary); background: var(--primary); font-size: 8px; }.download-platform { display: grid; gap: 2px; }.download-platform strong { color: var(--text-strong); font-size: 19px; }.download-platform span, .download-meta { color: var(--text-secondary); font-size: 10px; }.download-meta { display: flex; gap: 10px; font-family: var(--font-mono); }.download-steps { display: flex; grid-column: 2 / -1; justify-content: space-between; gap: 12px; color: var(--text-secondary); font-size: 9px; }.download-steps span { display: flex; align-items: center; gap: 7px; }.download-steps i { display: grid; width: 19px; height: 19px; place-items: center; border: 1px solid var(--border-strong); border-radius: 50%; color: var(--text-strong); font-style: normal; font-size: 8px; }.download-soon { grid-column: 3; margin: 0; color: var(--text-muted); font-size: 10px; }

@keyframes float-soft { 50% { transform: translateY(-7px); } }
@keyframes ambient-note { 50% { opacity: .45; transform: translateY(-18px) scale(1.5); } }
@keyframes status-breathe { 50% { opacity: .3; transform: scale(.72); } }
@keyframes scene-shape { to { border-radius: 54% 46% 57% 43% / 43% 56% 44% 57%; transform: rotate(2deg) scale(1.02); } }
@keyframes halo-pulse { 50% { transform: scale(1.04); opacity: .72; } }
@keyframes spin-slow { to { transform: rotate(360deg); } }

@media (max-width: 1040px) {
  .hero__layout { grid-template-columns: 1fr; }.hero__copy { max-width: 820px; }.hero-scene { width: min(720px, 100%); min-height: 580px; margin: 0 auto; }
  .control-section__layout { grid-template-columns: 1fr; }.control-copy { max-width: 720px; }
  .download-shell { grid-template-columns: 160px 1fr; }.download-grid { grid-column: 1 / -1; }.download-steps { grid-column: 1 / -1; }.download-soon { grid-column: 1 / -1; }
}

@media (max-width: 720px) {
  .hero { min-height: auto; padding: 70px 0 48px; }.hero__layout { gap: 28px; }.hero h1 { margin-top: 20px; font-size: clamp(54px, 16vw, 72px); }.hero__copy > p:not(.hero__note) { font-size: 16px; }.hero__actions { align-items: stretch; flex-direction: column; }.hero__actions :deep(.btn) { width: 100%; }.hero-scene { min-height: 480px; transform: scale(.94); }.hero-scene__mascot :deep(.combo-frame-animation) { width: 220px !important; }.mascot-halo { width: 220px; height: 220px; }.hero-scene__bubble { top: 3%; left: 0; max-width: 245px; }.pill--skill { top: 25%; }.pill--tool { top: 20%; }.pill--mcp { bottom: 24%; }.pill--knowledge { right: -3%; bottom: 29%; }.hero-scene__task { right: 0; bottom: 2%; }.hero-scene__status { bottom: 8%; left: 0; }
  .section-head--split { grid-template-columns: 1fr; gap: 20px; }.section-head h2 { font-size: 46px; }
  .capability-composer { min-height: auto; grid-template-columns: 1fr; margin-top: 38px; padding-top: 160px; }.capability-card, .capability-card:nth-child(n) { min-height: 210px; padding: 22px; }.composer-center { top: 0; width: 150px; height: 150px; transform: translate(-50%, 0); }.composer-center :deep(.combo-frame-animation) { width: 104px !important; }.composer-ring--outer { width: 128px; height: 128px; }.composer-ring--inner { width: 96px; height: 96px; }.composer-center strong { margin-bottom: 16px; }
  .control-points { grid-template-columns: 1fr; }.control-points article { min-height: 180px; }.control-points article + article { border-top: 1px solid var(--border); border-left: 0; }.control-copy h2 { font-size: 47px; }
  .download-shell { grid-template-columns: 1fr; text-align: center; }.download-mascot { display: none; }.download-grid { grid-template-columns: 1fr; text-align: left; }.download-steps { align-items: flex-start; flex-direction: column; width: fit-content; margin: 0 auto; text-align: left; }
}

@media (prefers-reduced-motion: reduce) {
  .hero__atmosphere i, .hero__badge i, .hero-scene__bubble, .capability-pill, .hero-scene__task, .hero-scene__task > i, .mascot-halo, .composer-ring { animation: none; }
  .capability-card { transition: none; }
}
</style>
