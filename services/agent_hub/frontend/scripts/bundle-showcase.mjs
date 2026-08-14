import { cp, mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url))
const siteDirectory = path.resolve(scriptDirectory, '..')
const repositoryDirectory = path.resolve(siteDirectory, '../../..')
const applicationDirectory = path.join(repositoryDirectory, 'web_frontend/frontend')
const applicationDist = path.join(applicationDirectory, 'dist')
const siteDist = path.join(siteDirectory, 'dist')
const showcaseDirectory = path.join(siteDist, 'app-showcase')

const build = spawnSync('npm', ['run', 'build'], {
  cwd: applicationDirectory,
  stdio: 'inherit',
})

if (build.status !== 0) {
  throw new Error('Unable to build the current Combo application showcase.')
}

await rm(showcaseDirectory, { recursive: true, force: true })
await mkdir(showcaseDirectory, { recursive: true })
await cp(path.join(applicationDist, 'assets'), path.join(siteDist, 'assets'), {
  recursive: true,
  force: true,
})
await cp(
  path.join(applicationDirectory, 'public/brand/combo'),
  path.join(siteDist, 'brand/combo'),
  { recursive: true, force: true },
)

const showcaseHtml = await readFile(path.join(applicationDist, 'showcase.html'), 'utf8')
await writeFile(
  path.join(showcaseDirectory, 'showcase.html'),
  showcaseHtml.replace('<title>Combo Showcase</title>', '<title>Combo 产品演示</title>'),
)

console.log('Bundled the current Combo application into the public-site build.')
