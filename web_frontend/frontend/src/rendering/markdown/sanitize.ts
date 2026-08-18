import { defaultSchema } from 'rehype-sanitize'

export function markdownSanitizeSchema() {
  const schema: any = structuredClone(defaultSchema)
  schema.attributes = {
    ...schema.attributes,
    '*': [
      ...(schema.attributes?.['*'] || []),
      'className',
      'dataLanguage',
      'ariaHidden',
      'ariaLabel',
      'role',
      'title',
    ],
    a: [
      ...(schema.attributes?.a || []),
      'href',
      'title',
      'target',
      'rel',
    ],
    code: [
      ...(schema.attributes?.code || []),
      'className',
    ],
    div: [
      ...(schema.attributes?.div || []),
      'className',
    ],
    span: [
      ...(schema.attributes?.span || []),
      'className',
      'style',
    ],
    button: [
      ...(schema.attributes?.button || []),
      'type',
      'title',
      'ariaLabel',
      'dataMarkdownCopy',
    ],
  }
  schema.tagNames = Array.from(new Set([
    ...(schema.tagNames || []),
    'div',
    'span',
    'button',
    'math',
    'semantics',
    'mrow',
    'mi',
    'mn',
    'mo',
    'msup',
    'msub',
    'msubsup',
    'mfrac',
    'msqrt',
    'mroot',
    'mtable',
    'mtr',
    'mtd',
    'annotation',
  ]))
  schema.protocols = {
    ...(schema.protocols || {}),
    href: Array.from(new Set([...(schema.protocols?.href || []), 'blob'])),
    src: Array.from(new Set([...(schema.protocols?.src || []), 'blob'])),
  }
  return schema
}
