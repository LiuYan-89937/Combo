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
  // 基础背景
  surface: '#ffffff',
  surfaceElevated: '#ffffff',
  surfaceMuted: '#f5f5f5',
  surfacePressed: '#eeeeee',
  surfaceActiveHover: '#e8e8e8',
  surfaceHover: '#fafafa',

  // 边框和分隔
  border: '#d9d9d9',
  borderHover: '#8a8a8a',
  borderFocus: '#111111',
  divider: '#e5e5e5',

  // 文本
  text: '#111111',
  textStrong: '#000000',
  textSecondary: '#333333',
  textMuted: '#666666',
  textPlaceholder: '#757575',
  textDisabled: '#9a9a9a',
  textInverse: '#ffffff',

  // 主色（极简黑）
  primary: '#111111',
  primaryHover: '#2f2f2f',
  primaryPressed: '#000000',
  primarySuppl: '#4a4a4a',

  // 语义色
  success: '#18a058',
  successHover: '#36ad6a',
  successPressed: '#0c7a43',

  info: '#2080f0',
  infoHover: '#4098fc',
  infoPressed: '#1060c9',

  warning: '#f0a020',
  warningHover: '#fcb040',
  warningPressed: '#c97c10',

  error: '#d03050',
  errorHover: '#de576d',
  errorPressed: '#ab1f3f',

  // 特殊用途
  focusShadow: 'rgba(17, 17, 17, 0.12)',
  transparent: 'transparent',
  overlay: 'rgba(0, 0, 0, 0.45)',

  // 阴影
  shadowSm: '0 1px 3px rgba(0, 0, 0, 0.06), 0 1px 2px rgba(0, 0, 0, 0.04)',
  shadowMd: '0 2px 8px rgba(0, 0, 0, 0.08), 0 1px 3px rgba(0, 0, 0, 0.04)',
  shadowLg: '0 8px 24px rgba(0, 0, 0, 0.12), 0 2px 6px rgba(0, 0, 0, 0.06)',

  // 代码/终端
  codeBackground: '#f6f6f6',
  codeBorder: '#e5e5e5',
}

export const darkPalette: AppPalette = {
  // 基础背景
  surface: '#1a1a1a',
  surfaceElevated: '#222222',
  surfaceMuted: '#2a2a2a',
  surfacePressed: '#353535',
  surfaceActiveHover: '#3a3a3a',
  surfaceHover: '#252525',

  // 边框和分隔
  border: '#3a3a3a',
  borderHover: '#5a5a5a',
  borderFocus: '#dddddd',
  divider: '#2f2f2f',

  // 文本
  text: '#e5e5e5',
  textStrong: '#ffffff',
  textSecondary: '#c5c5c5',
  textMuted: '#999999',
  textPlaceholder: '#7a7a7a',
  textDisabled: '#5a5a5a',
  textInverse: '#111111',

  // 主色（暗色下的极简白）
  primary: '#e5e5e5',
  primaryHover: '#ffffff',
  primaryPressed: '#cccccc',
  primarySuppl: '#b5b5b5',

  // 语义色（暗色优化版本）
  success: '#4cc38a',
  successHover: '#5fd89f',
  successPressed: '#3ba871',

  info: '#4098fc',
  infoHover: '#5fabff',
  infoPressed: '#307cd8',

  warning: '#f2c97d',
  warningHover: '#f5d89a',
  warningPressed: '#d4a857',

  error: '#e88592',
  errorHover: '#f09ca8',
  errorPressed: '#c9697a',

  // 特殊用途
  focusShadow: 'rgba(229, 229, 229, 0.15)',
  transparent: 'transparent',
  overlay: 'rgba(0, 0, 0, 0.65)',

  // 阴影
  shadowSm: '0 1px 3px rgba(0, 0, 0, 0.4), 0 1px 2px rgba(0, 0, 0, 0.25)',
  shadowMd: '0 2px 8px rgba(0, 0, 0, 0.4), 0 1px 3px rgba(0, 0, 0, 0.25)',
  shadowLg: '0 8px 24px rgba(0, 0, 0, 0.5), 0 2px 6px rgba(0, 0, 0, 0.3)',

  // 代码/终端
  codeBackground: '#252525',
  codeBorder: '#3a3a3a',
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
