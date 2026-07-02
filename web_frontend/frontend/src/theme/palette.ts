/**
 * 应用调色板
 * 支持亮色和暗色两套主题
 */

export interface AppPalette {
  // 基础背景
  surface: string
  surfaceElevated: string
  surfaceMuted: string
  surfacePressed: string
  surfaceActiveHover: string
  surfaceHover: string

  // 玻璃效果（液态玻璃感）
  glassBackground: string
  glassBackgroundLight: string
  glassBorder: string
  glassBorderLight: string

  // 边框和分隔
  border: string
  borderHover: string
  borderFocus: string
  divider: string

  // 文本
  text: string
  textStrong: string
  textSecondary: string
  textMuted: string
  textPlaceholder: string
  textDisabled: string
  textInverse: string

  // 主色
  primary: string
  primaryHover: string
  primaryPressed: string
  primarySuppl: string

  // 语义色
  success: string
  successHover: string
  successPressed: string

  info: string
  infoHover: string
  infoPressed: string

  warning: string
  warningHover: string
  warningPressed: string

  error: string
  errorHover: string
  errorPressed: string

  // 特殊用途
  focusShadow: string
  transparent: string
  overlay: string

  // 阴影
  shadowSm: string
  shadowMd: string
  shadowLg: string

  // 代码/终端
  codeBackground: string
  codeBorder: string
}

export const lightPalette: AppPalette = {
  // 基础背景（苹果官网的纯净白）
  surface: '#ffffff',
  surfaceElevated: '#ffffff',
  surfaceMuted: '#f5f5f7',
  surfacePressed: '#e8e8ed',
  surfaceActiveHover: '#d2d2d7',
  surfaceHover: '#fbfbfd',

  // 玻璃效果（液态玻璃感）
  glassBackground: 'rgba(255, 255, 255, 0.72)',
  glassBackgroundLight: 'rgba(255, 255, 255, 0.88)',
  glassBorder: 'rgba(0, 0, 0, 0.04)',
  glassBorderLight: 'rgba(0, 0, 0, 0.06)',

  // 边框和分隔（极淡，几乎透明）
  border: 'rgba(0, 0, 0, 0.06)',
  borderHover: 'rgba(0, 0, 0, 0.12)',
  borderFocus: '#0071e3',
  divider: 'rgba(0, 0, 0, 0.04)',

  // 文本（苹果的深灰，不是纯黑）
  text: '#1d1d1f',
  textStrong: '#000000',
  textSecondary: '#6e6e73',
  textMuted: '#86868b',
  textPlaceholder: '#c7c7cc',
  textDisabled: '#d2d2d7',
  textInverse: '#ffffff',

  // 主色（苹果蓝）
  primary: '#0071e3',
  primaryHover: '#0077ed',
  primaryPressed: '#006edb',
  primarySuppl: '#147ce5',

  // 语义色（清爽克制）
  success: '#30d158',
  successHover: '#32d65a',
  successPressed: '#2dca53',

  info: '#0071e3',
  infoHover: '#0077ed',
  infoPressed: '#006edb',

  warning: '#ff9f0a',
  warningHover: '#ffa61a',
  warningPressed: '#ff9500',

  error: '#ff3b30',
  errorHover: '#ff4d42',
  errorPressed: '#ff2d20',

  // 特殊用途
  focusShadow: 'rgba(0, 113, 227, 0.25)',
  transparent: 'transparent',
  overlay: 'rgba(0, 0, 0, 0.3)',

  // 阴影（苹果风格 - 极柔和多层）
  shadowSm: '0 2px 8px rgba(0, 0, 0, 0.04)',
  shadowMd: '0 4px 16px rgba(0, 0, 0, 0.08), 0 2px 4px rgba(0, 0, 0, 0.04)',
  shadowLg: '0 8px 24px rgba(0, 0, 0, 0.12), 0 4px 8px rgba(0, 0, 0, 0.06)',

  // 代码/终端
  codeBackground: '#f5f5f7',
  codeBorder: '#d2d2d7',
}

export const darkPalette: AppPalette = {
  // 基础背景（苹果暗色的深蓝黑）
  surface: '#000000',
  surfaceElevated: '#1c1c1e',
  surfaceMuted: '#2c2c2e',
  surfacePressed: '#3a3a3c',
  surfaceActiveHover: '#48484a',
  surfaceHover: '#1c1c1e',

  // 玻璃效果（暗色下更透明，对比更强）
  glassBackground: 'rgba(28, 28, 30, 0.78)',
  glassBackgroundLight: 'rgba(44, 44, 46, 0.88)',
  glassBorder: 'rgba(255, 255, 255, 0.1)',
  glassBorderLight: 'rgba(255, 255, 255, 0.15)',

  // 边框和分隔
  border: '#38383a',
  borderHover: '#6e6e73',
  borderFocus: '#0a84ff',
  divider: '#38383a',

  // 文本
  text: '#f5f5f7',
  textStrong: '#ffffff',
  textSecondary: '#98989d',
  textMuted: '#6e6e73',
  textPlaceholder: '#48484a',
  textDisabled: '#3a3a3c',
  textInverse: '#000000',

  // 主色（苹果暗色蓝）
  primary: '#0a84ff',
  primaryHover: '#409cff',
  primaryPressed: '#0077ed',
  primarySuppl: '#409cff',

  // 语义色（暗色优化）
  success: '#30d158',
  successHover: '#32d65a',
  successPressed: '#2dca53',

  info: '#0a84ff',
  infoHover: '#409cff',
  infoPressed: '#0077ed',

  warning: '#ff9f0a',
  warningHover: '#ffa61a',
  warningPressed: '#ff9500',

  error: '#ff453a',
  errorHover: '#ff6961',
  errorPressed: '#ff3b30',

  // 特殊用途
  focusShadow: 'rgba(10, 132, 255, 0.3)',
  transparent: 'transparent',
  overlay: 'rgba(0, 0, 0, 0.6)',

  // 阴影（暗色下更深）
  shadowSm: '0 1px 3px rgba(0, 0, 0, 0.6), 0 1px 2px rgba(0, 0, 0, 0.4)',
  shadowMd: '0 4px 12px rgba(0, 0, 0, 0.7), 0 2px 4px rgba(0, 0, 0, 0.5)',
  shadowLg: '0 12px 32px rgba(0, 0, 0, 0.8), 0 4px 8px rgba(0, 0, 0, 0.6)',

  // 代码/终端
  codeBackground: '#1c1c1e',
  codeBorder: '#38383a',
}

/**
 * 根据主题模式获取调色板
 */
export function getPalette(isDark: boolean): AppPalette {
  return isDark ? darkPalette : lightPalette
}

/**
 * 向后兼容的默认导出
 */
export const appPalette = lightPalette
