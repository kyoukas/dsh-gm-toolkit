/**
 * 给 dsh-ops 打一行本地补丁：让它认得我们自建的 preset id。
 *
 * 为什么需要：dsh-ops 的 mode 行（mode-standard）决定「这个会话要不要发 ops_* 工具、
 * 要不要把官方 read/glob/grep 换成 ops_ 版本」，判定用的是 preset id 白名单
 * （`MODE_PRESET` 只有 minimal/standard/ptc/cordis）。我们自建的 `gm-toolkit`
 * 不在白名单里 → mode 行对我们整个不发布，会话里就缺 ops_glob / ops_grep /
 * ops_inspect_local_file / ops_result。
 *
 * 这一行把 `gm-toolkit` 映射成 standard 模式，于是预设会话拿到的工具面与标准模式一致。
 * 代价：dsh-ops 升级会被覆盖，所以做成可重放的脚本（升级后再跑一次即可），
 * 插件启动时也会自检并在日志里说明当前状态。
 *
 * 用法：
 *   node scripts/patch-dsh-ops.mjs           # 应用（幂等）
 *   node scripts/patch-dsh-ops.mjs --revert  # 撤销
 *   node scripts/patch-dsh-ops.mjs --status  # 只看状态
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

export const MARKER = "modeByPreset.set('gm-toolkit', 'standard'); // dsh-gm-toolkit"
const ANCHOR = "const modeByPreset = new Map(MODE_IDS.map(mode => [MODE_PRESET[mode], mode]));"

/** 找到所有 dsh-ops 的 modes/detect.js（可能有多套 profile）。 */
export function findTargets() {
  const home = process.env.DSH_HOME || path.join(os.homedir(), '.dsh')
  const out = []
  const profiles = path.join(home, 'profiles')
  let names = []
  try {
    names = fs.readdirSync(profiles)
  } catch {
    return out
  }
  for (const name of names) {
    const file = path.join(profiles, name, 'node_modules', 'dsh-ops', 'lib', 'modes', 'detect.js')
    if (fs.existsSync(file)) out.push(file)
  }
  return out
}

export function statusOf(file) {
  const text = fs.readFileSync(file, 'utf8')
  if (text.includes(MARKER)) return 'applied'
  if (text.includes(ANCHOR)) return 'patchable'
  return 'unknown'
}

export function apply(file) {
  const text = fs.readFileSync(file, 'utf8')
  if (text.includes(MARKER)) return 'already'
  if (!text.includes(ANCHOR)) return 'anchor-missing'
  const next = text.replace(ANCHOR, `${ANCHOR}\n${MARKER}`)
  fs.writeFileSync(file, next)
  return 'applied'
}

export function revert(file) {
  const text = fs.readFileSync(file, 'utf8')
  if (!text.includes(MARKER)) return 'nothing'
  const next = text.split(`\n${MARKER}`).join('')
  fs.writeFileSync(file, next)
  return 'reverted'
}

function main(argv) {
  const mode = argv.includes('--revert') ? 'revert' : argv.includes('--status') ? 'status' : 'apply'
  const targets = findTargets()
  if (targets.length === 0) {
    console.log('没找到 dsh-ops（找的是 <DSH_HOME>/profiles/*/node_modules/dsh-ops/lib/modes/detect.js）')
    return 1
  }
  let bad = 0
  for (const file of targets) {
    const at = statusOf(file)
    if (mode === 'status') {
      console.log(`${at}\t${file}`)
      continue
    }
    if (mode === 'revert') {
      const r = revert(file)
      console.log(`${r}\t${file}`)
      if (r === 'nothing') continue
      continue
    }
    const r = apply(file)
    console.log(`${r}\t${file}`)
    if (r === 'anchor-missing') bad += 1
  }
  if (mode === 'apply' && bad > 0) {
    console.log('\n锚点没匹配上：dsh-ops 可能换了写法，请手动在 modeByPreset 定义之后加一行：')
    console.log(`  ${MARKER}`)
    return 2
  }
  return 0
}

if (process.argv[1] && process.argv[1].endsWith('patch-dsh-ops.mjs')) process.exit(main(process.argv.slice(2)))
