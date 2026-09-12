import { visit } from 'unist-util-visit'

interface ElementNode {
  type: 'element'
  tagName: string
  properties?: Record<string, unknown>
  children?: Array<ElementNode | TextNode>
}

interface TextNode {
  type: 'text'
  value: string
}

/**
 * Wraps every table in a scroll container.
 *
 * A table cannot scroll on its own without giving up `display: table`, and that
 * is exactly what made tables shrink to their content width instead of filling
 * the message and lining up with the text around them. The wrapper scrolls; the
 * table keeps its real layout.
 */
export function rehypeTableScroll() {
  return (tree: any) => {
    visit(tree, 'element', (node: ElementNode, index: number | undefined, parent: ElementNode | undefined) => {
      if (!parent?.children || typeof index !== 'number' || node.tagName !== 'table') return
      if (elementClasses(parent).includes('markdown-table-scroll')) return
      parent.children[index] = {
        type: 'element',
        tagName: 'div',
        properties: { className: ['markdown-table-scroll'] },
        children: [node],
      }
    })
  }
}

function elementClasses(node: ElementNode): string[] {
  return Array.isArray(node.properties?.className)
    ? node.properties.className.map(value => String(value))
    : []
}
