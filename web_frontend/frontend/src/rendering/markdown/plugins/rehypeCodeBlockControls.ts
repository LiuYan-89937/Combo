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

export function rehypeCodeBlockControls() {
  return (tree: any) => {
    visit(tree, 'element', (node: ElementNode, index: number | undefined, parent: ElementNode | undefined) => {
      if (!parent?.children || typeof index !== 'number' || node.tagName !== 'pre') return
      if (elementClasses(parent).includes('markdown-code-block')) return
      const code = node.children?.find((child): child is ElementNode => (
        child.type === 'element' && child.tagName === 'code'
      ))
      if (!code) return
      parent.children[index] = codeBlock(node, codeLanguage(code))
    })
  }
}

function elementClasses(node: ElementNode): string[] {
  return Array.isArray(node.properties?.className)
    ? node.properties.className.map(value => String(value))
    : []
}

function codeBlock(pre: ElementNode, language: string): ElementNode {
  return {
    type: 'element',
    tagName: 'div',
    properties: { className: ['markdown-code-block'] },
    children: [
      {
        type: 'element',
        tagName: 'div',
        properties: { className: ['markdown-code-toolbar'] },
        children: [
          {
            type: 'element',
            tagName: 'span',
            properties: { className: ['markdown-code-language'] },
            children: language ? [{ type: 'text', value: language }] : [],
          },
          {
            type: 'element',
            tagName: 'button',
            properties: {
              className: ['markdown-code-copy'],
              type: 'button',
              dataMarkdownCopy: 'true',
            },
            children: [
              {
                type: 'element',
                tagName: 'span',
                properties: { ariaHidden: 'true' },
                children: [{ type: 'text', value: '⧉' }],
              },
            ],
          },
        ],
      },
      pre,
    ],
  }
}

function codeLanguage(code: ElementNode): string {
  const classes = elementClasses(code)
  const languageClass = classes.find(value => value.startsWith('language-'))
  return languageClass ? languageClass.slice('language-'.length) : ''
}
