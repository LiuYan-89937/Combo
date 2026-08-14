/**
 * 将调色板和设计 Token 转换为 CSS 变量注入到 :root
 * 支持运行时切换主题
 */

import type { AppPalette } from './palette'
import { designTokens } from './tokens'

const CSS_VAR_STYLE_ID = 'app-palette-vars'
type AppColorScheme = 'light' | 'dark'

function toCssVariableName(key: string): string {
  return `--app-${key.replace(/([A-Z])/g, '-$1').toLowerCase()}`
}

/**
 * 将主题作为一组原子状态直接应用到根元素。
 *
 * 使用根元素内联变量而不是运行时重写整段 style 文本，避免复杂页面的
 * 合成层继续显示旧主题；data-theme、color-scheme 与设计变量同步更新。
 */
export function applyPaletteToRoot(palette: AppPalette, colorScheme: AppColorScheme): void {
  if (typeof document === 'undefined') return

  const root = document.documentElement
  const variables = {
    ...designTokens,
    ...palette,
  }

  for (const [key, value] of Object.entries(variables)) {
    root.style.setProperty(toCssVariableName(key), value)
  }

  root.dataset.theme = colorScheme
  root.style.colorScheme = colorScheme

  // 清理旧实现遗留的动态样式节点，避免同时存在两套主题来源。
  document.getElementById(CSS_VAR_STYLE_ID)?.remove()
}
