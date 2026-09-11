/**
 * Joins a native absolute directory with a repository-relative path.
 *
 * Git reports repository-relative paths with forward slashes while the root is a
 * native path, so on Windows the two have to be combined with a backslash for the
 * system shell to resolve the result.
 */
export function joinNativePath(root: string, relative: string): string {
  const base = String(root || '').trim().replace(/[\\/]+$/, '')
  const tail = String(relative || '').trim().replace(/^[\\/]+/, '')
  if (!base) return tail
  if (!tail) return base
  const separator = base.includes('\\') ? '\\' : '/'
  return `${base}${separator}${tail.split('/').join(separator)}`
}
