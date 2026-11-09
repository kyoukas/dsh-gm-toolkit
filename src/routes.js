/**
 * Host 侧的 HTTP 路由：图形界面点一下就调一条，全部 POST + JSON body。
 *
 * 这些路由只做「转发 + 兜底」，真正的逻辑都在 gmtool.py 里；CLI 认什么参数，
 * 这里就传什么参数，避免两端各写一套规则。
 */
import { resolvePython, runGmtoolEx } from './python.js'

const API_PREFIX = '/api/gm'
const BODY_MAX = 64 * 1024

/** gmtool 的 save 子命令只认这三个动词。 */
const OPS = ['set', 'add', 'remove']

/** gmtool.py 用退出码区分失败阶段（见 scripts/gmtool.py 的写档流程）。 */
const EXIT_SELF_CHECK = 5   // 写前自检未通过，原文件未改动
const EXIT_ROLLED_BACK = 6  // 落盘后复核失败，已回滚原字节

const JSON_HEADERS = {
  'content-type': 'application/json; charset=utf-8',
  'cache-control': 'no-store',
  'referrer-policy': 'no-referrer',
}

function writeJson(res, status, body) {
  const payload = JSON.stringify(body)
  res.writeHead(status, { ...JSON_HEADERS, 'content-length': Buffer.byteLength(payload) })
  res.end(payload)
}

async function readJson(req, maxBytes = BODY_MAX) {
  const chunks = []
  let size = 0
  for await (const chunk of req) {
    size += chunk.length
    if (size > maxBytes) throw new Error('body too large')
    chunks.push(chunk)
  }
  const text = Buffer.concat(chunks).toString('utf8').trim()
  if (!text) return {}
  return JSON.parse(text)
}

function failureReason(text) {
  const raw = String(text || '')
  const at = raw.indexOf('[stderr]')
  const body = at >= 0 ? raw.slice(at + 8) : raw
  const lines = body.split(/\r?\n/).map((l) => l.trim()).filter(Boolean)
  const meaningful = lines.find((l) => !/^提示[:：]/.test(l))
  return meaningful || lines[0] || '执行失败'
}

function isLoopback(req) {
  const address = req.socket?.remoteAddress || ''
  return address === '127.0.0.1' || address === '::1' || address === '::ffff:127.0.0.1'
}

/**
 * 把 gmtool 的 --json 输出切出来：前面可能还有几行「穿透了几层」的说明。
 * 从每个 { 起试一遍，取第一个能解析成对象的 —— 说明文字里带 { 也不会切错。
 */
function pickJson(text) {
  const raw = String(text || '')
  for (let at = raw.indexOf('{'); at >= 0; at = raw.indexOf('{', at + 1)) {
    try {
      const value = JSON.parse(raw.slice(at))
      if (value !== null && typeof value === 'object') return value
    } catch {
      /* 这个位置不是 JSON 起点，继续往后找 */
    }
  }
  return null
}

/**
 * @param {{ config: Record<string, unknown>, scriptPath: string, log?: Function }} deps
 */
export function makeRoutes({ config, scriptPath, log }) {
  const call = async (args, opts) => {
    const python = await resolvePython(config?.python)
    if (!python) return { ok: false, exitCode: null, error: 'no-python', text: '没找到可用的 Python 解释器。装一个 Python 3.9+，或在插件配置里填 python 路径。' }
    const { code, text } = await runGmtoolEx(python.executable, scriptPath, args, opts)
    // 保留数字退出码：调用方要靠它区分「自检拦截(5)」和「回滚(6)」，不能折叠成一个字符串。
    if (code !== 0) return { ok: false, exitCode: code, code: 'GMTOOL_FAILED', python: python.executable, text }
    return { ok: true, exitCode: 0, python: python.executable, text }
  }

  const post = (path, handler) => ({
    kind: 'exact',
    path: `${API_PREFIX}/${path}`,
    handler: async (req, res) => {
      if (req.method !== 'POST') return writeJson(res, 405, { ok: false, error: 'method-not-allowed' })
      if (!isLoopback(req)) return writeJson(res, 403, { ok: false, error: 'forbidden' })
      let body = {}
      try {
        body = await readJson(req)
      } catch (error) {
        return writeJson(res, 400, { ok: false, error: String(error?.message || error) })
      }
      try {
        const result = await handler(body)
        writeJson(res, 200, result)
      } catch (error) {
        log?.(`路由 ${path} 失败: ${error?.message || error}`)
        writeJson(res, 500, { ok: false, error: String(error?.message || error) })
      }
    },
  })

  return [
    // 环境体检：解释器在哪、依赖缺哪些
    post('doctor', async () => {
      const python = await resolvePython(config?.python)
      if (!python) return { ok: false, error: 'no-python', text: '没找到可用的 Python 解释器。' }
      const text = await runGmtoolEx(python.executable, scriptPath, ['__doctor__'], { timeoutMs: 30000 }).then((r) => r.text)
      const info = pickJson(text)
      return { ok: Boolean(info?.ok), python: python.executable, info, text }
    }),

    // 缺依赖时一键安装（默认走清华镜像，国内装得快）
    post('install', async (body) => {
      const python = await resolvePython(config?.python)
      if (!python) return { ok: false, error: 'no-python' }
      const modules = Array.isArray(body.modules) && body.modules.length > 0
        ? body.modules
        : ['dnfile', 'dncil', 'msgpack', 'lz4', 'pycryptodome']
      const mirror = String(body.mirror || 'https://pypi.tuna.tsinghua.edu.cn/simple')
      const result = await runGmtoolEx(python.executable, scriptPath, ['__pip__', mirror, ...modules], { timeoutMs: 600000, maxOutput: 8000 })
      if (result.code !== 0) {
        return { ok: false, python: python.executable, text: result.text, error: failureReason(result.text) }
      }
      return { ok: true, python: python.executable, text: result.text }
    }),

    // 不知道存档在哪：扫一遍常见位置
    post('scan', async (body) => {
      const args = ['scan', '--json', '--limit', String(body.limit || 80)]
      for (const root of Array.isArray(body.roots) ? body.roots : []) {
        if (root) args.push('--root', String(root))
      }
      const result = await call(args, { timeoutMs: 180000 })
      if (!result.ok) return result
      const data = pickJson(result.text)
      if (!data) return { ok: false, text: result.text, error: '扫描没有返回结果' }
      return { ok: true, data, text: result.text }
    }),

    // 这个文件是什么格式
    post('probe', async (body) => {
      if (!body.path) return { ok: false, error: '缺少 path' }
      const args = ['probe', String(body.path)]
      if (body.depth) args.push('--depth', String(body.depth))
      return await call(args, { timeoutMs: 120000 })
    }),

    // 列字段（可带 path 钻进去）
    post('list', async (body) => {
      if (!body.path) return { ok: false, error: '缺少 path' }
      const args = ['save', 'dump', String(body.path), String(body.target || ''), '--json', '--limit', String(body.limit || 200)]
      const result = await call(args, { timeoutMs: 300000 })
      if (!result.ok) return result
      const data = pickJson(result.text)
      if (!data) return { ok: false, text: result.text, error: '这台机器解不开这个存档（可能是自定义格式或加密），需要先在会话里分析。' }
      return { ok: true, data, text: result.text }
    }),

    // 读单个字段原值
    post('get', async (body) => {
      if (!body.path || body.target === undefined) return { ok: false, error: '缺少 path 或 target' }
      return await call(['save', 'get', String(body.path), String(body.target)], { timeoutMs: 300000 })
    }),

    // 改（set/add/remove），默认写回原文件并自动备份
    //
    // 批量语义：第一条写原始文件（自动备份），后续条在原文件上继续改并加 --no-backup，
    // 一次操作只留一份恢复点；中途失败就停在第 N 条，并回报已经成功了几条。
    post('apply', async (body) => {
      if (!body.path) return { ok: false, error: '缺少 path' }
      const changes = Array.isArray(body.changes) ? body.changes : []
      if (changes.length === 0) return { ok: false, error: '没有要执行的修改' }

      // 先整体校验，避免改到一半才发现参数不合法（那时前几条已经落盘了）
      const plan = []
      for (const [index, change] of changes.entries()) {
        if (!change || typeof change !== 'object') return { ok: false, error: `第 ${index + 1} 条修改格式不对` }
        const op = String(change.op || 'set')
        if (!OPS.includes(op)) return { ok: false, error: `不支持的 op: ${op}（只认 ${OPS.join(' / ')}）` }
        const target = String(change.target ?? '').trim()
        if (!target) return { ok: false, error: `第 ${index + 1} 条修改缺少 target（要改哪个字段）` }
        if (target.includes('=')) return { ok: false, error: `target 里不能有 = ：${target}` }
        plan.push({ op, target, value: String(change.value ?? '') })
      }

      const logs = []
      const backups = []
      // 指定 out 时：第一条从原文件读到 out（原文件不动），后续条必须读 out 继续改。
      // 否则每条都从原文件重新起算，写同一个 out，后一条会把前一条的改动覆盖掉。
      const outPath = body.out ? String(body.out) : null
      let input = String(body.path)
      for (const [index, item] of plan.entries()) {
        const args = ['save', item.op, input, `${item.target}=${item.value}`]
        if (outPath !== null && index === 0) args.push('-o', outPath)
        else if (index > 0) args.push('--no-backup')  // 第一条已经备份过原始文件

        const result = await call(args, { timeoutMs: 300000 })
        logs.push(`$ save ${item.op} ${item.target}=${item.value}\n${result.text}`)

        const backup = result.text.match(/原文件已备份 -> (.+)/)
        if (backup) backups.push(backup[1].trim())
        if (outPath !== null) input = outPath

        if (!result.ok) {
          const detail = result.code === 'GMTOOL_FAILED' ? failureReason(result.text) : ''
          const reason = result.exitCode === EXIT_SELF_CHECK ? `写前自检未通过（${detail}），原文件未改动`
            : result.exitCode === EXIT_ROLLED_BACK ? `落盘后复核失败，已自动回滚原字节（${detail}）`
            : result.code === 'GMTOOL_FAILED' ? failureReason(result.text)
            : (result.error || '执行失败')
          return {
            ok: false,
            applied: index,
            backups,
            backup: backups[0] || null,
            // 前几条是真的落盘了，必须说清楚，否则用户会以为整批没生效。
            error: `${plan.length > 1 ? `第 ${index + 1} 条失败：${reason}` : reason}`
              + (index > 0 ? `（前 ${index} 条已生效，回滚用 ${backups[0] || '无备份'}）` : ''),
            log: logs.join('\n\n'),
          }
        }
      }
      return { ok: true, applied: plan.length, backups, backup: backups[0] || null, log: logs.join('\n\n') }
    }),
  ]
}
