/**
 * 探测 dsh-ops 那行本地补丁的状态。
 *
 * dsh-ops 的 mode 行只认内置 preset id，`attach` 用的 `modeByPreset` 是模块加载时
 * 建好的私有 Map。补丁就是往那个 Map 里塞一行 `gm-toolkit -> standard`
 * （见 scripts/patch-dsh-ops.mjs）。
 *
 * 三种状态：
 *   applied —— 补丁在。预设会话会走 standard 模式，拿到完整 ops_* 工具面，
 *              我们自己就不再挂 dsh-ops/shell、dsh-ops/file（否则 ops_bash 会重复注册）。
 *   missing —— dsh-ops 在、但没补丁（升级冲掉了）。退回组件行，缺 ops_glob/grep/…，
 *              日志里必须说清楚，别让人以为工具面跟标准一样。
 *   absent  —— 这台机器没装 dsh-ops。同样退回组件行。
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

export const DSH_OPS_MARKER = "modeByPreset.set('gm-toolkit', 'standard'); // dsh-gm-toolkit"

let override = null

/** 测试用：强制返回某个状态（传 null 恢复自动探测）。 */
export function __setOpsPatchState(value) {
  override = value
}

/** @returns {'applied'|'missing'|'absent'} */
export function dshOpsPatchState() {
  if (override !== null) return override
  const home = process.env.DSH_HOME || path.join(os.homedir(), '.dsh')
  const profiles = path.join(home, 'profiles')
  let names = []
  try {
    names = fs.readdirSync(profiles)
  } catch {
    return 'absent'
  }
  let found = false
  for (const name of names) {
    const file = path.join(profiles, name, 'node_modules', 'dsh-ops', 'lib', 'modes', 'detect.js')
    let text
    try {
      text = fs.readFileSync(file, 'utf8')
    } catch {
      continue
    }
    found = true
    if (text.includes(DSH_OPS_MARKER)) return 'applied'
  }
  return found ? 'missing' : 'absent'
}
