declare module 'diff' {
  export interface Change {
    value: string
    added?: boolean
    removed?: boolean
    count?: number
  }

  export function diffLines(oldText: string, newText: string): Change[]
}
