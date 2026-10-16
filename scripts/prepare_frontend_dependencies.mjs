import { createHash, randomUUID } from 'node:crypto'
import { spawn } from 'node:child_process'
import { existsSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendDirectory = resolve(dirname(fileURLToPath(import.meta.url)), '../web_frontend/frontend')
const modulesDirectory = join(frontendDirectory, 'node_modules')
const manifestPath = join(modulesDirectory, '.combo-dependencies.json')
const installedLockPath = join(modulesDirectory, '.package-lock.json')
const npmCli = process.env.npm_execpath
const installOptions = [
  '--include=dev', '--include=optional', '--include=peer',
  '--ignore-scripts=false', '--bin-links=true', '--no-audit', '--no-fund',
]

function npm(arguments_, capture = false) {
  return new Promise((resolveResult, reject) => {
    const child = spawn(process.execPath, [npmCli, '--prefix', frontendDirectory, ...arguments_], {
      cwd: frontendDirectory,
      stdio: capture ? ['ignore', 'pipe', 'pipe'] : 'inherit',
    })
    let stdout = ''
    let stderr = ''
    child.stdout?.setEncoding('utf8').on('data', (chunk) => { stdout += chunk })
    child.stderr?.setEncoding('utf8').on('data', (chunk) => { stderr += chunk })
    child.on('error', reject)
    child.on('close', (status, signal) => {
      if (signal) reject(new Error(`npm ${arguments_[0]} was interrupted by ${signal}`))
      else resolveResult({ status, stdout, stderr })
    })
  })
}

function digest(value) {
  return createHash('sha256').update(value).digest('hex')
}

function installationConfiguration(configuration) {
  const keys = [
    'bin-links', 'cpu', 'engine-strict', 'force', 'ignore-scripts', 'include',
    'install-links', 'install-strategy', 'legacy-peer-deps', 'libc',
    'node-options', 'omit', 'os', 'script-shell', 'strict-peer-deps',
  ]
  return Object.fromEntries(keys.sort().map((key) => {
    const value = configuration[key] ?? null
    return [key, Array.isArray(value) ? [...value].sort() : value]
  }))
}

function readOptionalJson(path) {
  try {
    return JSON.parse(readFileSync(path, 'utf8'))
  } catch (error) {
    if (error.code === 'ENOENT' || error instanceof SyntaxError) return null
    throw error
  }
}

function matchesPlatform(allowed, value) {
  return !allowed || (allowed.includes('any') || !allowed.some((item) => !item.startsWith('!'))
    || allowed.includes(value)) && !allowed.includes(`!${value}`)
}

function installedPackagesIssue(lock, packageJson) {
  const installed = readOptionalJson(installedLockPath)
  if (!installed?.packages) return 'node_modules/.package-lock.json is missing or invalid'
  if (!lock.packages?.['']) return 'package-lock.json has no root package metadata'
  for (const field of ['dependencies', 'devDependencies', 'optionalDependencies', 'peerDependencies']) {
    const declared = packageJson[field] ?? {}
    const locked = lock.packages[''][field] ?? {}
    if (Object.keys(declared).length !== Object.keys(locked).length
      || Object.entries(declared).some(([name, spec]) => locked[name] !== spec)) {
      return `package.json ${field} do not match package-lock.json`
    }
  }
  for (const [location, expected] of Object.entries(lock.packages)) {
    if (!location) continue
    const current = installed.packages[location]
    const compatible = matchesPlatform(expected.os, process.platform)
      && matchesPlatform(expected.cpu, process.arch)
    if (!current) {
      if (!expected.optional || (compatible && (expected.os || expected.cpu))) {
        return `locked dependency is missing: ${location}`
      }
      continue
    }
    if (!compatible) return `installed dependency does not support ${process.platform}/${process.arch}: ${location}`
    if (['version', 'resolved', 'integrity', 'link'].some((key) => current[key] !== expected[key])) {
      return `installed dependency metadata does not match package-lock.json: ${location}`
    }
    const directory = resolve(frontendDirectory, location)
    const metadata = readOptionalJson(join(directory, 'package.json'))
    const packageVersion = expected.link ? lock.packages[expected.resolved]?.version : expected.version
    if (!metadata || metadata.version !== packageVersion) {
      return `package.json is missing, invalid or has a different version: ${location}`
    }
    const binaries = typeof metadata.bin === 'string'
      ? { [metadata.name.split('/').at(-1)]: metadata.bin } : metadata.bin ?? {}
    const parentModules = location.slice(0, location.lastIndexOf('node_modules/') + 'node_modules'.length)
    for (const [name, binary] of Object.entries(binaries)) {
      const launcher = process.platform === 'win32' ? `${name}.cmd` : name
      if (!existsSync(resolve(directory, binary))) return `package executable is missing: ${location}/${binary}`
      if (location.includes('node_modules/')
        && !existsSync(resolve(frontendDirectory, parentModules, '.bin', launcher))) {
        return `package launcher is missing: ${parentModules}/.bin/${launcher}`
      }
    }
  }
  const extra = Object.keys(installed.packages).find((location) => !lock.packages[location])
  return extra ? `installed dependency is absent from package-lock.json: ${extra}` : null
}

async function dependencyTreeIssue(lock, packageJson) {
  const issue = installedPackagesIssue(lock, packageJson)
  if (issue) return issue
  const result = await npm(['ls', '--all', '--json', '--package-lock-only=false', ...installOptions], true)
  const tree = JSON.parse(result.stdout)
  if (tree.problems?.length) return `npm dependency validation failed: ${tree.problems.join('; ')}`
  if (result.status !== 0 || tree.error) {
    return `npm ls failed: ${tree.error?.summary || result.stderr.trim() || result.status}`
  }
  return null
}

async function requireNpmSuccess(arguments_) {
  const result = await npm(arguments_)
  if (result.status !== 0) throw new Error(`npm ${arguments_[0]} failed with exit code ${result.status}`)
}

async function main() {
  if (!npmCli) throw new Error('Run this script with npm run prepare-dependencies.')
  const arguments_ = process.argv.slice(2)
  if (arguments_.some((argument) => !['--force', '--check'].includes(argument))
    || arguments_.includes('--force') && arguments_.includes('--check')) {
    throw new Error('Use either --check (validation only) or --force (clean install).')
  }
  const lockBytes = readFileSync(join(frontendDirectory, 'package-lock.json'))
  const packageBytes = readFileSync(join(frontendDirectory, 'package.json'))
  const lock = JSON.parse(lockBytes)
  const packageJson = JSON.parse(packageBytes)
  const configuration = await npm(['config', 'list', '--json', ...installOptions], true)
  if (configuration.status !== 0) throw new Error(configuration.stderr.trim() || 'Cannot read npm configuration.')
  const expected = {
    schemaVersion: 2,
    lock: digest(lockBytes),
    package: digest(packageBytes),
    node: process.version,
    abi: process.versions.modules,
    platform: process.platform,
    arch: process.arch,
    npm: JSON.parse(readFileSync(resolve(dirname(npmCli), '../package.json'), 'utf8')).version,
    configuration: digest(JSON.stringify(installationConfiguration(JSON.parse(configuration.stdout)))),
    nodeEnv: process.env.NODE_ENV ?? '',
  }
  const recorded = readOptionalJson(manifestPath)
  const previous = recorded?.schemaVersion === expected.schemaVersion ? recorded : null
  const changedKeys = previous ? Object.keys(expected).filter((key) => previous[key] !== expected[key]) : []
  let issue = arguments_.includes('--force') ? 'clean installation was explicitly requested' : null
  if (!issue && changedKeys.length) issue = `dependency environment changed: ${changedKeys.join(', ')}`
  if (!issue && previous && existsSync(installedLockPath)
    && previous.installedLock !== digest(readFileSync(installedLockPath))) {
    issue = 'node_modules/.package-lock.json changed since the last successful preparation'
  }
  issue ??= await dependencyTreeIssue(lock, packageJson)
  const reusable = !issue
  if (arguments_.includes('--check')) {
    console.log(issue ? `Frontend dependencies cannot be reused: ${issue}` : 'Frontend dependencies can be reused.')
    process.exitCode = issue ? 3 : 0
    return
  }
  if (reusable && previous) {
    console.log('Frontend dependencies match the lockfile and environment; reusing node_modules.')
    return
  }
  rmSync(manifestPath, { force: true })
  if (reusable) {
    console.log('Existing dependencies match package-lock.json; completing installation scripts...')
    await requireNpmSuccess(['rebuild', ...installOptions])
  } else {
    console.log(`Frontend dependency installation required: ${issue}`)
    console.log('Frontend dependencies are missing or changed; installing from package-lock.json...')
    await requireNpmSuccess(['ci', ...installOptions])
  }
  const remainingIssue = await dependencyTreeIssue(lock, packageJson)
  if (remainingIssue) throw new Error(`Frontend dependency preparation failed: ${remainingIssue}`)
  const temporaryPath = `${manifestPath}.${randomUUID()}.tmp`
  try {
    writeFileSync(temporaryPath, JSON.stringify({
      ...expected, installedLock: digest(readFileSync(installedLockPath)),
    }, null, 2) + '\n', { flag: 'wx' })
    renameSync(temporaryPath, manifestPath)
  } finally {
    rmSync(temporaryPath, { force: true })
  }
}

main().catch((error) => {
  console.error(error.message)
  process.exitCode = 1
})
