export type MarkdownRenderSurface = 'chat_message' | 'reasoning' | 'workspace_preview'

export interface MarkdownRenderOptions {
  streaming?: boolean
  surface?: MarkdownRenderSurface
}

export interface MarkdownRenderResult {
  html: string
  source: string
}
