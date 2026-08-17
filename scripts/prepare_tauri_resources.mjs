import { existsSync, readdirSync, rmSync } from 'node:fs'
import { resolve } from 'node:path'
import { spawnSync } from 'node:child_process'

const projectRoot = process.cwd()
const resourceSourceRoots = [
  resolve(projectRoot, 'combo'),
  resolve(projectRoot, 'web_frontend/backend'),
]

for (const root of resourceSourceRoots) {
  removePythonBytecode(root)
}

const bundledPython = process.platform === 'win32'
  ? resolve(projectRoot, 'src-tauri/resources/python/python.exe')
  : resolve(projectRoot, 'src-tauri/resources/python/bin/python3')
if (!existsSync(bundledPython)) {
  throw new Error(`Bundled Python executable is unavailable: ${bundledPython}`)
}
const precompile = spawnSync(
  bundledPython,
  [
    resolve(projectRoot, 'scripts/precompile_python_resources.py'),
    ...resourceSourceRoots.flatMap((root) => ['--source', root]),
  ],
  { stdio: 'inherit' },
)
if (precompile.error) {
  throw precompile.error
}
if (precompile.status !== 0) {
  throw new Error(`Python application resource precompilation failed with exit code ${precompile.status}`)
}

function removePythonBytecode(directory) {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = resolve(directory, entry.name)
    if (entry.isDirectory()) {
      if (entry.name === '__pycache__') {
        rmSync(path, { recursive: true })
      } else {
        removePythonBytecode(path)
      }
      continue
    }
    if (entry.isFile() && (entry.name.endsWith('.pyc') || entry.name.endsWith('.pyo'))) {
      rmSync(path)
      continue
    }
  }
}
