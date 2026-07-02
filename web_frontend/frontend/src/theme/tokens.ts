/**
 * 设计 Token
 * 与调色板独立，主题切换不影响间距/圆角/字号
 */

export interface DesignTokens {
  // 间距（8px 基础网格）
  spaceXxs: string
  spaceXs: string
  spaceSm: string
  spaceMd: string
  spaceLg: string
  spaceXl: string
  spaceXxl: string

  // 圆角
  radiusSm: string
  radiusMd: string
  radiusLg: string
  radiusXl: string
  radiusPill: string

  // 字号
  fontXs: string
  fontSm: string
  fontMd: string
  fontLg: string
  fontXl: string
  fontXxl: string

  // 行高
  leadingTight: string
  leadingNormal: string
  leadingRelaxed: string

  // 过渡
  transitionFast: string
  transitionBase: string
  transitionSlow: string

  // 层级
  zBase: string
  zSticky: string
  zDropdown: string
  zDrawer: string
  zModal: string
  zNotification: string

  // 布局
  headerHeight: string
  toolbarHeight: string
  contentMaxWidth: string
  chatMaxWidth: string
}

export const designTokens: DesignTokens = {
  // 间距（8px 基础网格）
  spaceXxs: '2px',
  spaceXs: '4px',
  spaceSm: '8px',
  spaceMd: '12px',
  spaceLg: '16px',
  spaceXl: '24px',
  spaceXxl: '32px',

  // 圆角
  radiusSm: '4px',
  radiusMd: '6px',
  radiusLg: '8px',
  radiusXl: '12px',
  radiusPill: '999px',

  // 字号
  fontXs: '11px',
  fontSm: '12px',
  fontMd: '13px',
  fontLg: '14px',
  fontXl: '16px',
  fontXxl: '20px',

  // 行高
  leadingTight: '1.25',
  leadingNormal: '1.5',
  leadingRelaxed: '1.65',

  // 过渡
  transitionFast: '0.12s ease',
  transitionBase: '0.2s ease',
  transitionSlow: '0.3s ease',

  // 层级
  zBase: '1',
  zSticky: '10',
  zDropdown: '100',
  zDrawer: '1000',
  zModal: '2000',
  zNotification: '3000',

  // 布局
  headerHeight: '56px',
  toolbarHeight: '40px',
  contentMaxWidth: '1440px',
  chatMaxWidth: '960px',
}

/**
 * 将 tokens 转为 CSS 变量文本片段
 */
export function tokensToCssVars(tokens: DesignTokens): string {
  const vars: string[] = []
  for (const [key, value] of Object.entries(tokens)) {
    const varName = key.replace(/([A-Z])/g, '-$1').toLowerCase()
    vars.push(`  --app-${varName}: ${value};`)
  }
  return vars.join('\n')
}
