import { visit } from 'unist-util-visit'

type ImageUrlResolver = (source: string) => string | null

export function rehypeImageSources() {
  return (tree: any, file: any) => {
    const resolver = file.data?.resolveImageUrl as ImageUrlResolver | undefined
    if (!resolver) return

    visit(tree, 'element', (node: any, index: number | undefined, parent: any) => {
      if (node.tagName !== 'img') return
      const source = typeof node.properties?.src === 'string' ? node.properties.src : ''
      const resolved = resolver(source)
      if (resolved) {
        node.properties = { ...node.properties, src: resolved }
        return
      }
      if (!parent || typeof index !== 'number') return
      parent.children[index] = {
        type: 'text',
        value: String(node.properties?.alt || source || ''),
      }
    })
  }
}
