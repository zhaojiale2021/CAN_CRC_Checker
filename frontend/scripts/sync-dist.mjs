// Mirror frontend/dist into webapp/static/dist — the copy bundled into the
// Python wheel. Keeping both committed lets deploy machines run without Node;
// this script removes the manual "copy the build output" step.
import { cpSync, existsSync, rmSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const source = resolve(here, '..', 'dist')
const target = resolve(here, '..', '..', 'webapp', 'static', 'dist')

if (!existsSync(source)) {
  console.error(`[sync-dist] missing build output: ${source}`)
  process.exit(1)
}

rmSync(target, { recursive: true, force: true })
cpSync(source, target, { recursive: true })
console.log(`[sync-dist] ${source} -> ${target}`)
