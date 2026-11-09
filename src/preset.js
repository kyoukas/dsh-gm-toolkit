/**
 * 「存档修改」preset 的组合声明。
 *
 * 为什么不用 YAML：宿主没有把它的 YAML 读取器暴露给插件，梁神模式为此自带了一个
 * 两百多行的手写解析器。我们干脆把宿主那份 standard.patch.yml 在开发期用 PyYAML
 * 转成 JSON（presets/gm-toolkit/plugins.standard.json，唯一来源，见 presets/README.md），
 * 运行期只做两件事：
 *   1. 把 !!js 表达式按白名单求值成真正的布尔值；
 *   2. 在最上面挂我们自己的工具行、并给 skill-filesystem 指定插件自带技能目录。
 *
 * 白名单是故意的：遇到没见过的 !!js 表达式直接抛错，而不是把一个插件猜坏。
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { dshOpsPatchState } from './dshops.js'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const PACKAGE_ROOT = path.dirname(HERE)
const STANDARD_ROWS = path.join(PACKAGE_ROOT, 'presets', 'gm-toolkit', 'plugins.standard.json')
const SKILLS_DIR = path.join(PACKAGE_ROOT, 'skills')
const TOOLS_ENTRY = path.join(PACKAGE_ROOT, 'tools.js')

export const PRESET_ID = 'gm-toolkit'

/** standard 预设里出现过的 !!js 表达式，仅此三条。 */
const JS_EXPRESSIONS = {
  "process.platform === 'win32'": () => process.platform === 'win32',
  "process.platform !== 'win32'": () => process.platform !== 'win32',
  "!ctx.get('profileContext')": (ctx) => {
    const profileContext = ctx && typeof ctx.get === 'function' ? ctx.get('profileContext') : undefined
    return !profileContext
  },
}

function isJsExpr(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value) &&
    Object.keys(value).length === 1 && typeof value.__jsExpr === 'string'
}

function evaluate(expression, ctx) {
  const resolve = JS_EXPRESSIONS[expression]
  if (resolve === undefined) {
    throw new Error(`未支持的 !!js 表达式: ${expression}（请把它加到 src/preset.js 的白名单里）`)
  }
  return resolve(ctx)
}

/** 深度遍历：把任何 {__jsExpr} 换成布尔值（group 行的 config 也是行数组）。 */
function resolveJsValues(value, ctx) {
  if (isJsExpr(value)) return evaluate(value.__jsExpr, ctx)
  if (Array.isArray(value)) return value.map((item) => resolveJsValues(item, ctx))
  if (value !== null && typeof value === 'object') {
    const out = {}
    for (const [key, item] of Object.entries(value)) out[key] = resolveJsValues(item, ctx)
    return out
  }
  return value
}

/**
 * 读宿主此刻真实注册的 standard 预设行（内部 definitions 表，读不到就返回 null 走快照）。
 * @returns {Array<object>|null}
 */
function liveStandardRows(ctx) {
  try {
    const service = ctx && typeof ctx.get === 'function' ? ctx.get('agentPresets') : undefined
    const record = service?.definitions?.get?.('standard')
    const plugins = record?.config?.plugins
    return Array.isArray(plugins) && plugins.length > 0 ? plugins : null
  } catch {
    return null
  }
}

/** mode 行靠 preset id 匹配，我们的 id 是 gm-toolkit，永远命中不了，不能进声明。 */
function isModeRow(row) {
  return Boolean(row && typeof row.id === 'string' && row.id.startsWith('dsh-ops-mode-'))
}

/** profile 级 dsh-ops 组件行（shell / file …），不含 mode 行。 */
function isOpsComponent(row) {
  return Boolean(row && typeof row.id === 'string' && row.id.startsWith('dsh-ops-') && !isModeRow(row))
}

/**
 * 兜底组件行：profile 根不继承到 preset 作用域，不显式带上就退回裸 pwsh。
 * isolate 是必须的，见 withOpsIsolation 的注释。
 */
const OPS_COMPONENT_FALLBACK = [
  { id: 'dsh-ops-shell', name: 'dsh-ops/shell', config: { promptPolicy: true }, isolate: { opsSettings: true } },
  { id: 'dsh-ops-file', name: 'dsh-ops/file', config: { promptPolicy: false } },
]

/**
 * dsh-ops/shell 内部会 ctx.provide('opsSettings')。preset 里发布的 service 必须落在 isolate realm，
 * 否则宿主会打 "Preset services require isolate realms: opsSettings" 并把 service 写进 root store ——
 * 预设卸载时按 realm 清理，可能连带删掉 root 的 slot，弄坏 profile 级设置页。
 *
 * live 行通常已经带 isolate，那就原样沿用，只补 opsSettings 这一项（幂等）。
 */
function withOpsIsolation(row) {
  if (!row || row.id !== 'dsh-ops-shell') return row
  const isolate = row.isolate && typeof row.isolate === 'object' && !Array.isArray(row.isolate) ? row.isolate : {}
  if (isolate.opsSettings === true) return row
  return { ...row, isolate: { ...isolate, opsSettings: true } }
}

/** 组装 dsh-ops 组件行：优先用宿主真实行（自带 isolate），缺的补兜底行。 */
function opsComponentRows(raw, live, ctx) {
  const source = (Array.isArray(live) ? live : raw).filter(isOpsComponent)
  const rows = resolveJsValues(source, ctx).map(withOpsIsolation)
  for (const fallback of OPS_COMPONENT_FALLBACK) {
    if (!rows.some((row) => row && row.id === fallback.id)) rows.push(withOpsIsolation({ ...fallback }))
  }
  return rows
}

/**
 * 组装 preset 的 plugins 行。
 * @param {object} ctx 注册时的 Context（用于求值 !!js 与取 profileContext）
 * @returns {Array<object>} 行数组：标准模式那批行 + dsh-ops 组件行 + 我们的工具行
 */
export function buildRows(ctx, note) {
  const raw = JSON.parse(fs.readFileSync(STANDARD_ROWS, 'utf8'))
  if (!Array.isArray(raw)) throw new Error('plugins.standard.json 必须是一个插件行数组')

  // 快照只用来「兜底」。优先拿宿主当前真实注册的 standard 行，避免 preset 与 profile 漂移
  // （例如用户后来升级标准模式、改了某行 config，这边就自动跟上）。
  const live = liveStandardRows(ctx)
  // 读的是宿主当前注册的 standard 行，还是本地快照？必须留痕，
  // 否则日后 preset 与 profile 漂移时没人知道该看哪边。
  if (typeof note === 'function') note(live ? 'live' : 'snapshot')
  // live 分支同样要过 withOpsIsolation：宿主真实行里若已有 dsh-ops-shell，
  // 下面的按 id 去重会保留它、把补过 isolate 的丢掉了，isolate 修复就白做了。
  const rows = resolveJsValues((live ?? raw).filter((row) => !isModeRow(row)), ctx).map(withOpsIsolation)

  // 技能：插件自带 game-modding，普通会话看不到这一条。
  const skillRow = rows.find((row) => row && row.id === 'skill-filesystem')
  if (skillRow !== undefined) {
    skillRow.config = { ...(skillRow.config ?? {}), bundledSkillDir: SKILLS_DIR }
  } else {
    rows.push({ id: 'skill-filesystem', name: '@deepseek-ai/dsh-skill-filesystem', config: { bundledSkillDir: SKILLS_DIR } })
  }

  // profile 级插件（dsh-ops 提供 ops_* 与沙箱准备）：preset 作用域不继承 profile 根。
  //
  // 但只有在 dsh-ops 没打补丁时才需要我们自己挂组件行——补丁生效后，profile 上的
  // dsh-ops-mode-standard 行会认得 gm-toolkit 这个 preset id，直接把完整工具面
  // （ops_bash / ops_glob / ops_grep / ops_inspect_local_file / ops_result 与官方工具的
  // 替换）发布给我们；这时再挂组件行会让 ops_bash 重复注册。
  const opsState = dshOpsPatchState()
  if (typeof note === 'function') note(`ops-patch:${opsState}`)
  if (opsState !== 'applied') {
    for (const row of opsComponentRows(raw, live, ctx)) {
      if (!rows.some((item) => item && item.id === row.id)) rows.push(row)
    }
  }

  // 工具：绝对 file URL，避免 preset 目录成为解析基准。
  rows.push({ id: 'gm-tools', name: pathToFileURL(TOOLS_ENTRY).href })

  return rows
}

/**
 * 提交给 ctx.agentPresets.register 的声明。
 * @returns {{id: string, name: string, description: string, order: number, plugins: Array<object>}}
 */
export function buildDeclaration(ctx, note) {
  return {
    id: PRESET_ID,
    name: '存档修改',
    description: '游戏存档侦探与编辑器：扫描存档、识别格式、读写字段、反汇编与 IL 打补丁。仅此模式的会话挂载 gm_* 工具。',
    order: 20,
    plugins: buildRows(ctx, note),
  }
}
