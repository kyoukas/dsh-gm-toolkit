/**
 * 冒烟测试：不启动宿主，用假 ctx 验证三件事
 *   1. tools.js（preset 里挂的 9 个工具）能注册、能真跑；
 *   2. index.js（常驻部分）不注册任何工具 —— 这是「零 token 常驻」的回归判据；
 *   3. preset 声明能组装出来，行数与平台开关符合预期。
 * 运行：node test/smoke.mjs
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const root = path.join(HERE, '..')

// ---- 1. 工具部分 ------------------------------------------------------------
const toolsPlugin = await import(pathToFileURL(path.join(root, 'tools.js')).href)
assert.deepEqual(toolsPlugin.inject, ['tools'], 'tools.js 必须声明 inject: tools')

const registered = new Map()
const toolCtx = {
  tools: { register: (def) => { registered.set(def.name, def); return () => registered.delete(def.name) } },
  effect: () => {},
  logger: { info: () => {}, warn: () => {} },
}
await toolsPlugin.apply(toolCtx, {})

const expected = [
  'gm_doctor', 'gm_probe', 'gm_save_list', 'gm_save_get', 'gm_save_apply',
  'gm_dll_types', 'gm_dll_dis', 'gm_dll_xref', 'gm_dll_patch',
]
for (const toolName of expected) assert.ok(registered.has(toolName), `缺少工具 ${toolName}`)
assert.equal(registered.size, expected.length, '不应注册多余工具')

for (const [toolName, def] of registered) {
  assert.equal(typeof def.execute, 'function', `${toolName} 缺 execute`)
  assert.equal(def.parameters.type, 'object', `${toolName} 的 parameters 必须是 object`)
  assert.equal(typeof def.output.render, 'function', `${toolName} 缺 output.render`)
}

const doctor = await registered.get('gm_doctor').execute({})
assert.match(doctor.text, /gmtool\.py/, '自检必须报告 gmtool.py 路径')

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'gm-toolkit-'))
const sample = path.join(tmp, 'sample.bin')
fs.writeFileSync(sample, Buffer.from('dummy-save-bytes-for-probe'))
const probed = await registered.get('gm_probe').execute({ path: sample })
assert.match(probed.text, /文件:/, 'probe 必须回显文件信息')
assert.match(probed.text, /未识别|MessagePack|AES|gzip/, 'probe 必须给出一个判定')

// ---- 1b. 明文 JSON 存档（含畸形片段）-----------------------------------------
const jsonPath = path.join(tmp, 'json-sample.sav')
const jsonOriginal = Buffer.from(
  '{\r\n\t"A" : 1,\r\n\t"B" : {\r\n\t\t"__type" : "int"0,\r\n\t\t"C" : "hi"\r\n\t}\r\n}',
  'utf8',
)
fs.writeFileSync(jsonPath, jsonOriginal)

const probedJson = await registered.get('gm_probe').execute({ path: jsonPath })
assert.match(probedJson.text, /JSON 根/, 'probe 必须把明文 JSON 认出来')

const listed = await registered.get('gm_save_list').execute({ path: jsonPath, target: '.B' })
assert.match(listed.text, /__type/, 'JSON 的字段要能列出来')

const got = await registered.get('gm_save_get').execute({ path: jsonPath, target: '.A' })
assert.match(got.text, /int 1/, 'JSON 的字段要能读到')

const outPath = path.join(tmp, 'json-out.sav')
const applied = await registered.get('gm_save_apply').execute({
  path: jsonPath,
  changes: ['set .A=4242'],
  out: outPath,
})
assert.match(applied.text, /自检通过/, 'JSON 改动必须通过不变量自检')

const jsonAfter = fs.readFileSync(outPath)
assert.ok(
  jsonAfter.includes(Buffer.from('{\r\n\t"A" : 4242,')),
  '只应替换目标值，其余格式化原样保留',
)
assert.ok(jsonAfter.includes(Buffer.from('"__type" : "int"0')), '畸形片段必须原样保留')

// set 到「和当前值一样」：不该备份、不该落盘，更不该报「自检未通过」
const noopPath = path.join(tmp, 'noop.sav')
const noopBefore = Buffer.from('{\n  "A": 1\n}\n', 'utf8')
fs.writeFileSync(noopPath, noopBefore)
const noop = await registered.get('gm_save_apply').execute({ path: noopPath, changes: ['set .A=1'] })
assert.match(noop.text, /值没有变化/, 'no-op 必须明确说没改动')
assert.ok(!/自检未通过/.test(noop.text), `no-op 不该报自检未通过：${noop.text}`)
assert.ok(fs.readFileSync(noopPath).equals(noopBefore), 'no-op 不该改文件')
assert.ok(!fs.readdirSync(tmp).some((n) => n.startsWith('noop.sav.bak')), 'no-op 不该产生备份')

fs.rmSync(tmp, { recursive: true, force: true })

// ---- 1c. 批量 apply 的备份判定 ----------------------------------------------
// 判据必须是「真的备份过没有」，不能是数组下标：第 1 条解析失败被跳过时，
// 它既没备份也没写 out；后面那条若按下标省备份，就会原地改原文件且零备份。
const { buildTools } = await import(pathToFileURL(path.join(root, 'src', 'toolkit.js')).href)

const skippedCalls = []
const applySkip = buildTools(async (argv) => {
  skippedCalls.push(argv.join(' '))
  return 'ok'
}).find((d) => d.name === 'gm_save_apply')

// 第 1 条无法解析 → 被跳过；第 2 条是真正执行的第一条，必须走默认备份
await applySkip.execute({ path: 'S.json', changes: ['坏掉的一行', 'set .a=1'] })
assert.equal(skippedCalls.length, 1, `应只执行 1 条命令，实际 ${skippedCalls.length}`)
assert.ok(!/--no-backup/.test(skippedCalls[0]), `第一条被跳过时仍必须备份：${skippedCalls[0]}`)

// 同一场景 + out：-o 必须落在「第一条真正执行的」上，而不是死盯 index === 0
skippedCalls.length = 0
await applySkip.execute({ path: 'S.json', changes: ['坏掉的一行', 'set .a=1'], out: 'OUT.json' })
assert.equal(skippedCalls.length, 1, `应只执行 1 条命令，实际 ${skippedCalls.length}`)
assert.match(skippedCalls[0], /-o OUT\.json/, `out 必须带上，否则写的还是原文件：${skippedCalls[0]}`)
assert.ok(!/--no-backup/.test(skippedCalls[0]), 'mutation: out 模式不该省备份')

// 正常两条：第一条输出备份路径 → 第二条才允许 --no-backup（只留一份恢复点）
const chainedCalls = []
const applyChain = buildTools(async (argv) => {
  chainedCalls.push(argv.join(' '))
  return chainedCalls.length === 1 ? '原文件已备份 -> S.json.bak-1' : 'ok'
}).find((d) => d.name === 'gm_save_apply')
await applyChain.execute({ path: 'S.json', changes: ['set .a=1', 'set .b=2'] })
assert.equal(chainedCalls.length, 2)
assert.ok(!/--no-backup/.test(chainedCalls[0]), '第一条必须备份')
assert.ok(/--no-backup/.test(chainedCalls[1]), `已备份过时第二条应省备份：${chainedCalls[1]}`)

// ---- 2. 常驻部分不得注册工具 ------------------------------------------------
const mainPlugin = await import(pathToFileURL(path.join(root, 'index.js')).href)
assert.equal(mainPlugin.name, 'dsh-gm-toolkit')
assert.equal(mainPlugin.inject, undefined, 'index.js 不该声明 inject: tools（否则工具又常驻了）')

const leaked = []
const mainCtx = {
  tools: { register: (def) => { leaked.push(def.name); return () => {} } },
  effect: () => {},
  inject: () => {},
  get: () => undefined,
  logger: { info: () => {}, warn: () => {} },
}
await mainPlugin.apply(mainCtx, {})
assert.deepEqual(leaked, [], `常驻部分不得注册工具，却注册了 ${leaked.join(',')}`)

// ---- 3. preset 声明 ---------------------------------------------------------
const { buildDeclaration, PRESET_ID } = await import(pathToFileURL(path.join(root, 'src', 'preset.js')).href)
const { dshOpsPatchState, __setOpsPatchState } = await import(pathToFileURL(path.join(root, 'src', 'dshops.js')).href)
const patchState = dshOpsPatchState()
const declaration = buildDeclaration({ get: () => ({ id: 'profile' }) })
assert.equal(declaration.id, PRESET_ID)
assert.equal(declaration.name, '存档修改')
assert.ok(declaration.plugins.length >= 20, 'preset 必须带上标准模式的插件行')
assert.ok(declaration.plugins.some((row) => row.id === 'gm-tools'), 'preset 必须挂 gm 工具行')
assert.ok(!declaration.plugins.some((row) => row.disabled === true && row.id === 'tool-pwsh'), 'Windows 上 tool-pwsh 必须启用')
const skillRow = declaration.plugins.find((row) => row.id === 'skill-filesystem')
assert.ok(skillRow.config.bundledSkillDir.endsWith('skills'), 'skill-filesystem 必须指向插件自带技能目录')
assert.ok(fs.existsSync(path.join(root, 'skills', 'game-modding', 'SKILL.md')), '插件必须自带 game-modding 技能')

// 技能目录里的 gmtool.py 必须与插件根目录那份字节相同。
// 曾经漂移过（技能副本 34KB / 根目录 82KB），模型照 SKILL.md 跑技能副本时会用上旧逻辑。
assert.ok(
  fs.readFileSync(path.join(root, 'scripts', 'gmtool.py'))
    .equals(fs.readFileSync(path.join(root, 'skills', 'game-modding', 'scripts', 'gmtool.py'))),
  'skills/game-modding/scripts/gmtool.py 与 scripts/gmtool.py 不一致（技能侧会跑旧逻辑）',
)

// preset 行数不该写死：标准模式升级后行数会变，这里只保证「够多 + 结构对」
const rows = declaration.plugins
assert(rows.length >= 20, `preset 行数太少: ${rows.length}`)
assert(rows.some((r) => r.id === 'gm-tools'), 'preset 缺 gm-tools 行')

// dsh-ops 组件行的去留取决于那行本地补丁：打了补丁就让 profile 上的 mode 行代为发布，
// 没打才需要自带 shell/file（否则 ops_bash 会重复注册）。
const hasShell = rows.some((r) => r.id === 'dsh-ops-shell')
const hasFile = rows.some((r) => r.id === 'dsh-ops-file')
if (patchState === 'applied') {
  assert(!hasShell, '补丁生效时不该再挂 dsh-ops/shell（ops_bash 会重复注册）')
  assert(!hasFile, '补丁生效时不该再挂 dsh-ops/file')
} else {
  assert(hasShell, '未打补丁时必须自带 dsh-ops/shell 行（ops_bash 与沙箱准备）')
  assert(hasFile, '未打补丁时必须自带 dsh-ops/file 行（ops_read_files 等）')
  // dsh-ops/shell 会 provide('opsSettings')。preset 里发布的 service 必须落在 isolate realm，
  // 否则宿主会打 "Preset services require isolate realms: opsSettings" 并写进 root store。
  const shell = rows.find((r) => r.id === 'dsh-ops-shell')
  assert.equal(shell.isolate?.opsSettings, true, 'dsh-ops-shell 必须 isolate: { opsSettings: true }')
}
assert(!rows.some((r) => String(r.id ?? '').startsWith('dsh-ops-mode-')), 'preset 不应带 mode 行（对自定义 preset 永不命中）')
assert(rows.filter((r) => r.id === 'skill-filesystem').length === 1, 'skill-filesystem 行数异常')

// 宿主真实 standard 行优先（防漂移）：给一个带 definitions 的假服务
{
  const live = [{ id: 'persona', name: '@deepseek-ai/dsh-persona', config: { prefix: 'LIVE' } }]
  const fake = { get: (k) => (k === 'agentPresets' ? { definitions: new Map([['standard', { config: { plugins: live } }]]) } : { id: 'p' }) }
  const d = buildDeclaration(fake)
  assert(d.plugins.some((r) => r.id === 'persona' && r.config?.prefix === 'LIVE'), '没有优先采用宿主真实 standard 行')
  assert(d.plugins.some((r) => r.id === 'gm-tools'), '走真实行时仍要挂 gm-tools')
}

// live 分支的 isolate 回归（只有未打补丁时才会自带组件行）：
// 宿主真实行里已经有 dsh-ops-shell（没带 isolate）时，
// 按 id 去重会保留它、把补过 isolate 的丢掉 —— 必须在这里就把 live 行过一遍 withOpsIsolation
{
  __setOpsPatchState('missing')
  const live = [
    { id: 'persona', name: '@deepseek-ai/dsh-persona', config: { prefix: 'LIVE' } },
    { id: 'dsh-ops-shell', name: 'dsh-ops/shell', config: { promptPolicy: true } },
  ]
  const fake = { get: (k) => (k === 'agentPresets' ? { definitions: new Map([['standard', { config: { plugins: live } }]]) } : { id: 'p' }) }
  const d = buildDeclaration(fake)
  const shell = d.plugins.find((r) => r.id === 'dsh-ops-shell')
  assert.equal(shell?.isolate?.opsSettings, true, 'live 分支的 dsh-ops-shell 必须补上 isolate: { opsSettings: true }')
  __setOpsPatchState(null)
}

console.log(`smoke ok：tools.js 注册 9 个工具、index.js 零工具、preset 声明 ${rows.length} 行`)
console.log(doctor.text.split('\n').slice(0, 4).join('\n'))
