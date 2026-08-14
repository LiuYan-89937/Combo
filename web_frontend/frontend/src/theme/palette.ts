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

  // 操作控件
  controlSurface: string
  controlSurfaceHover: string
  controlSurfacePressed: string
  controlDisabledSurface: string
  controlDisabledBorder: string
  controlDisabledText: string

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
  // 基础背景（纯净白）
  surface: '#ffffff',
  surfaceElevated: '#ffffff',
  surfaceMuted: '#ffffff',
  surfacePressed: '#ffffff',
  surfaceActiveHover: '#ffffff',
  surfaceHover: '#ffffff',

  // 操作控件（保持白底和轻边框，避免禁用态形成灰色块）
  controlSurface: '#ffffff',
  controlSurfaceHover: '#ffffff',
  controlSurfacePressed: '#ffffff',
  controlDisabledSurface: '#ffffff',
  controlDisabledBorder: 'rgba(0, 0, 0, 0.08)',
  controlDisabledText: '#000000',

  // 玻璃效果
  glassBackground: 'rgba(255, 255, 255, 0.72)',
  glassBackgroundLight: 'rgba(255, 255, 255, 0.88)',
  glassBorder: 'rgba(0, 0, 0, 0.06)',
  glassBorderLight: 'rgba(0, 0, 0, 0.1)',

  // 边框和分隔（极淡）
  border: 'rgba(0, 0, 0, 0.08)',
  borderHover: 'rgba(0, 0, 0, 0.18)',
  borderFocus: '#000000',
  divider: 'rgba(0, 0, 0, 0.06)',

  // 文本（黑白灰）
  text: '#000000',
  textStrong: '#000000',
  textSecondary: '#000000',
  textMuted: '#000000',
  textPlaceholder: '#000000',
  textDisabled: '#000000',
  textInverse: '#ffffff',

  // 主色（纯黑）
  primary: '#000000',
  primaryHover: '#000000',
  primaryPressed: '#000000',
  primarySuppl: '#000000',

  success: '#000000',
  successHover: '#000000',
  successPressed: '#000000',
  info: '#000000',
  infoHover: '#000000',
  infoPressed: '#000000',
  warning: '#000000',
  warningHover: '#000000',
  warningPressed: '#000000',
  error: '#000000',
  errorHover: '#000000',
  errorPressed: '#000000',

  // 特殊用途
  focusShadow: 'rgba(0, 0, 0, 0.1)',
  transparent: 'transparent',
  overlay: 'rgba(0, 0, 0, 0.3)',

  // 阴影（柔和）
  shadowSm: '0 2px 8px rgba(0, 0, 0, 0.04)',
  shadowMd: '0 4px 16px rgba(0, 0, 0, 0.08), 0 2px 4px rgba(0, 0, 0, 0.04)',
  shadowLg: '0 8px 24px rgba(0, 0, 0, 0.12), 0 4px 8px rgba(0, 0, 0, 0.06)',

  // 代码/终端
  codeBackground: '#ffffff',
  codeBorder: 'rgba(0, 0, 0, 0.08)',
}

export const darkPalette: AppPalette = {
  // 基础背景（纯黑）
  surface: '#000000',
  surfaceElevated: '#000000',
  surfaceMuted: '#000000',
  surfacePressed: '#000000',
  surfaceActiveHover: '#000000',
  surfaceHover: '#000000',

  // 操作控件（暗色主题使用干净的分层底色，不用大块中灰）
  controlSurface: '#000000',
  controlSurfaceHover: '#000000',
  controlSurfacePressed: '#000000',
  controlDisabledSurface: '#000000',
  controlDisabledBorder: 'rgba(255, 255, 255, 0.12)',
  controlDisabledText: '#ffffff',

  // 玻璃效果
  glassBackground: 'rgba(0, 0, 0, 0.78)',
  glassBackgroundLight: 'rgba(0, 0, 0, 0.88)',
  glassBorder: 'rgba(255, 255, 255, 0.1)',
  glassBorderLight: 'rgba(255, 255, 255, 0.16)',

  // 边框和分隔
  border: 'rgba(255, 255, 255, 0.12)',
  borderHover: 'rgba(255, 255, 255, 0.24)',
  borderFocus: '#ffffff',
  divider: 'rgba(255, 255, 255, 0.1)',

  // 文本（黑白灰）
  text: '#ffffff',
  textStrong: '#ffffff',
  textSecondary: '#ffffff',
  textMuted: '#ffffff',
  textPlaceholder: '#ffffff',
  textDisabled: '#ffffff',
  textInverse: '#000000',

  // 主色（纯白）
  primary: '#ffffff',
  primaryHover: '#ffffff',
  primaryPressed: '#ffffff',
  primarySuppl: '#ffffff',

  success: '#ffffff',
  successHover: '#ffffff',
  successPressed: '#ffffff',
  info: '#ffffff',
  infoHover: '#ffffff',
  infoPressed: '#ffffff',
  warning: '#ffffff',
  warningHover: '#ffffff',
  warningPressed: '#ffffff',
  error: '#ffffff',
  errorHover: '#ffffff',
  errorPressed: '#ffffff',

  // 特殊用途
  focusShadow: 'rgba(255, 255, 255, 0.2)',
  transparent: 'transparent',
  overlay: 'rgba(0, 0, 0, 0.6)',

  // 阴影（暗色下更深）
  shadowSm: '0 2px 8px rgba(0, 0, 0, 0.6)',
  shadowMd: '0 4px 16px rgba(0, 0, 0, 0.7), 0 2px 4px rgba(0, 0, 0, 0.5)',
  shadowLg: '0 8px 24px rgba(0, 0, 0, 0.8), 0 4px 8px rgba(0, 0, 0, 0.6)',

  // 代码/终端
  codeBackground: '#000000',
  codeBorder: 'rgba(255, 255, 255, 0.12)',
}

/**
 * 根据主题模式获取调色板
 */
export function getPalette(isDark: boolean): AppPalette {
  return isDark ? darkPalette : lightPalette
}
