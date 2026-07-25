import { readdirSync, rmSync } from 'node:fs'
import { resolve } from 'node:path'

const projectRoot = process.cwd()
const resourceSourceRoots = [
  resolve(projectRoot, 'agent_factory'),
  resolve(projectRoot, 'web_frontend/backend'),
]

for (const root of resourceSourceRoots) {
  removePythonBytecode(root)
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
