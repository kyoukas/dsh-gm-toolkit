// 路由冒烟测试：起一个只挂了 /api/gm/* 的最小 http 服务，逐个打一遍。
// 只验证「宿主路由 → gmtool.py → 返回 JSON」这条链路，不依赖 DSH 进程。
//
// 存档相关的用例需要本机真有那份 CotL 存档；没有就自动跳过，换机器不会一片红。
import http from 'node:http'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { makeRoutes } from '../src/routes.js'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.dirname(HERE)

const SOUND_SAVE = path.join(
  os.homedir(),
  'AppData', 'LocalLow', 'Massive Monster', 'Cult Of The Lamb', 'saves', 'slot_0.mp',
)
const hasSave = fs.existsSync(SOUND_SAVE)

const routes = makeRoutes({ config: {}, scriptPath: path.join(ROOT, 'scripts', 'gmtool.py'), log: () => {} })

const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1')
  const route = routes.find((item) => item.kind === 'exact' && item.path === url.pathname)
  if (!route) {
    res.writeHead(404, { 'content-type': 'application/json' })
    res.end('{"ok":false,"error":"no-route"}')
    return
  }
  route.handler(req, res)
})

await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
const base = `http://127.0.0.1:${server.address().port}`

async function post(name, body) {
  const res = await fetch(`${base}/api/gm/${name}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body || {}),
  })
  return { status: res.status, body: await res.json() }
}

let failures = 0
function check(label, condition, detail) {
  if (condition) {
    console.log(`  ok   ${label}`)
  } else {
    failures += 1
    console.log(`  FAIL ${label}${detail ? ' :: ' + detail : ''}`)
  }
}

function skip(label) {
  console.log(`  skip ${label}`)
}

// 1. 非 POST 必须 405
{
  const res = await fetch(`${base}/api/gm/doctor`, { method: 'GET' })
  check('GET 回 405', res.status === 405, String(res.status))
}

// 2. doctor
{
  const { status, body } = await post('doctor')
  check('doctor 200', status === 200, String(status))
  check('doctor ok=true', body.ok === true, JSON.stringify(body.info || body.text))
  check('doctor 带模块表', Boolean(body.info && body.info.modules), JSON.stringify(body.info || null))
  console.log('    python =', body.python)
  console.log('    modules =', body.info ? JSON.stringify(body.info.modules) : '(无)')
}

// 2.5 scan（扫盘不依赖具体存档，但「认得 CotL」这条依赖本机有没有那份存档）
{
  const started = Date.now()
  const { body } = await post('scan', { limit: 40 })
  const cost = Date.now() - started
  check('scan ok', body.ok === true, body.error || body.text)
  const items = (body.data && body.data.items) || []
  check('scan 有候选', items.length > 0, 'items=' + items.length)
  if (hasSave) {
    check('scan 排在第一的是当前存档', items.length > 0 && items[0].backup === false, JSON.stringify(items[0] && items[0].path))
    check('scan 认得 CotL 存档', items.some((it) => /Cult Of The Lamb/.test(it.path) && it.fmt === 'AES-CBC'), '')
  } else {
    skip('scan 认得 CotL 存档（本机没有那份存档）')
  }
  check('scan 耗时可接受(<30s)', cost < 30000, cost + 'ms')
  console.log('    耗时 =', cost + 'ms', '· 候选 =', items.length, '· 首个 =', items[0] && items[0].game)
}

if (!hasSave) {
  skip('probe / list / get / apply（缺 ' + SOUND_SAVE + '）')
} else {
  // 3. probe
  {
    const { body } = await post('probe', { path: SOUND_SAVE })
    check('probe ok', body.ok === true, body.text)
    check('probe 认得出 AES', /AES-128-CBC/.test(body.text || ''), String(body.text).slice(0, 120))
  }

  // 4. list（根）
  {
    const { body } = await post('list', { path: SOUND_SAVE, target: '', limit: 4 })
    check('list ok', body.ok === true, body.error || body.text)
    check('list 根是 1396 字段', body.data && body.data.value === 'array[1396]', body.data && body.data.value)
    check('list 有行', Boolean(body.data && body.data.rows && body.data.rows.length === 4), 'rows=' + (body.data?.rows?.length))
    console.log('    前几行 =', JSON.stringify(body.data?.rows?.slice(0, 3)))
  }

  // 5. list（钻进去）
  {
    const { body } = await post('list', { path: SOUND_SAVE, target: '1162', limit: 3 })
    check('list 子层 ok', body.ok === true, body.error || body.text)
    check('list 面包屑', Boolean(body.data && body.data.parents && body.data.parents.length === 2), JSON.stringify(body.data?.parents))
    console.log('    1162 前几行 =', JSON.stringify(body.data?.rows))
  }

  // 6. get
  {
    const { body } = await post('get', { path: SOUND_SAVE, target: '635' })
    check('get ok', body.ok === true, body.text)
    check('get 读到布尔值', /bool/.test(body.text || ''), String(body.text).slice(0, 120))
  }

  // 7. apply 到副本（不碰真存档）
  {
    const copy = path.join(os.tmpdir(), `gm-route-smoke-${Date.now()}.mp`)
    fs.copyFileSync(SOUND_SAVE, copy)
    const { body } = await post('apply', { path: copy, changes: [{ op: 'set', target: '422', value: '7' }] })
    check('apply ok', body.ok === true, body.error || body.log)
    check('apply 有备份路径', Boolean(body.backup), JSON.stringify(body.backup))
    check('apply 回报 applied=1', body.applied === 1, JSON.stringify(body.applied))
    check('apply 只留 1 份备份', Array.isArray(body.backups) && body.backups.length === 1, JSON.stringify(body.backups))
    const back = await post('get', { path: copy, target: '422' })
    check('apply 回读为新值', /7\b/.test(back.body.text || ''), String(back.body.text).slice(-160))
    console.log('    backup =', body.backup)
    fs.rmSync(copy, { force: true })
  }

  // 7b. 批量 apply：两条修改只应留一份备份（后续条走 --no-backup）
  {
    const copy = path.join(os.tmpdir(), `gm-route-batch-${Date.now()}.mp`)
    fs.copyFileSync(SOUND_SAVE, copy)
    const { body } = await post('apply', {
      path: copy,
      changes: [
        { op: 'set', target: '422', value: '3' },
        { op: 'set', target: '422', value: '9' },
      ],
    })
    check('批量 apply ok', body.ok === true, body.error || body.log)
    check('批量 applied=2', body.applied === 2, JSON.stringify(body.applied))
    check('批量只留 1 份备份', Array.isArray(body.backups) && body.backups.length === 1, JSON.stringify(body.backups))
    fs.rmSync(copy, { force: true })
  }

  // 7c. out + 多条：必须串起来改同一个输出，后一条不能把前一条覆盖掉，原文件不能被碰
  {
    const copy = path.join(os.tmpdir(), `gm-route-out-${Date.now()}.mp`)
    const out = path.join(os.tmpdir(), `gm-route-out-${Date.now()}-o.mp`)
    fs.copyFileSync(SOUND_SAVE, copy)
    const before = fs.readFileSync(copy)
    const { body } = await post('apply', {
      path: copy,
      out,
      changes: [
        { op: 'set', target: '422', value: '11' },
        { op: 'set', target: '283', value: '5' },
      ],
    })
    check('out 批量 ok', body.ok === true, body.error || body.log)
    check('out 批量 applied=2', body.applied === 2, JSON.stringify(body.applied))
    // 两条都要在：这条用例就是抓「后一条从原文件重新起算、把前一条覆盖掉」的老 bug
    const g1 = (await post('get', { path: out, target: '422' })).body.text
    const g2 = (await post('get', { path: out, target: '283' })).body.text
    check('out 里第 1 条改动还在', /\bint 11\b/.test(String(g1)), String(g1).slice(-120))
    check('out 里第 2 条改动也在', /float32 5(\.0+)?\b|\bint 5\b/.test(String(g2)), String(g2).slice(-120))
    check('out 模式不动原文件', Buffer.compare(before, fs.readFileSync(copy)) === 0)
    fs.rmSync(copy, { force: true })
    fs.rmSync(out, { force: true })
  }

  // 8. 失败路径：改一个不存在的字段必须报 ok:false（不能假装成功）
  {
    const copy = path.join(os.tmpdir(), `gm-route-fail-${Date.now()}.mp`)
    fs.copyFileSync(SOUND_SAVE, copy)
    const before = fs.readFileSync(copy)
    const { body } = await post('apply', { path: copy, changes: [{ op: 'set', target: 'NopeDeep.deep', value: '1' }] })
    check('坏路径 ok=false', body.ok === false, JSON.stringify(body).slice(0, 200))
    check('坏路径给了原因', /找不到|无效|失败|错误/.test(String(body.error || '')), String(body.error).slice(0, 160))
    check('原因里不含层信息', !/AES-128-CBC|LZ4BlockArray/.test(String(body.error || '')), String(body.error).slice(0, 160))
    check('坏路径没动文件', Buffer.compare(before, fs.readFileSync(copy)) === 0)
    fs.rmSync(copy, { force: true })
  }
}

// 9. 参数校验：空 target 必须在落盘前就被拦住
{
  const { body } = await post('apply', { path: 'x', changes: [{ op: 'set', target: '  ', value: '1' }] })
  check('空 target 被拦', body.ok === false && /target/.test(String(body.error || '')), JSON.stringify(body))
  const bad = await post('apply', { path: 'x', changes: [{ op: 'delete', target: 'a', value: '1' }] })
  check('非法 op 被拦', bad.body.ok === false && /op/.test(String(bad.body.error || '')), JSON.stringify(bad.body))
}

// 10. 失败路径：文件不存在应友好报错，而不是 Traceback
{
  const { body } = await post('list', { path: 'D:/definitely/not/here.sav' })
  check('缺文件 ok=false', body.ok === false, JSON.stringify(body).slice(0, 160))
  check('缺文件无 Traceback', !/Traceback/.test(String(body.text || '') + String(body.error || '')), String(body.text).slice(-160))
}

server.close()
console.log(failures === 0 ? '\n路由冒烟：全部通过' : `\n路由冒烟：${failures} 项失败`)
process.exit(failures === 0 ? 0 : 1)
