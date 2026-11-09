/**
 * Python 运行时定位与调用。
 *
 * gmtool.py 需要第三方库（dnfile/dncil 做反汇编、msgpack+lz4+pycryptodome 做存档），
 * 因此插件不绑定解释器路径：按「配置 → 环境变量 → PATH → 常见安装位置」依次探测，
 * 探测结果缓存，避免每次工具调用都去试一遍。
 */
import { execFile } from 'node:child_process'

const PROBE_TIMEOUT_MS = 8000

/** 探测失败后的负缓存时长：太短会让每次工具调用都重试一圈 PATH，太长又失去「装上就能用」。 */
const NEGATIVE_TTL_MS = 5000

/** Windows / POSIX 上常见的解释器名与安装路径，按优先级排列。 */
const CANDIDATES = [
  'python.exe',
  'python3',
  'python',
  'C:\\Python313\\python.exe',
  'C:\\Python312\\python.exe',
  'C:\\Python311\\python.exe',
  'C:\\Python310\\python.exe',
  '/usr/bin/python3',
  '/usr/local/bin/python3',
]

let cached = null
let inflight = null
let missAt = 0

function probe(command) {
  return new Promise((resolve) => {
    execFile(command, ['-c', 'import sys; print(sys.executable)'], {
      timeout: PROBE_TIMEOUT_MS,
      windowsHide: true,
    }, (error, stdout) => {
      if (error) return resolve(null)
      const text = String(stdout || '').trim().split(/\r?\n/).pop() || ''
      resolve(text ? { command, executable: text } : null)
    })
  })
}

/**
 * 选出可用的 Python。
 *
 * 只缓存成功结果：旧版把 null 也永久缓存，用户装好 Python 后必须重启 DSH 才能用。
 * 失败结果走 5 秒负缓存，既避免每次工具调用都重跑一圈 PATH，又能「装上就能用」。
 *
 * @param {string} [configured] 插件配置里的 python 路径，优先级最高。
 * @returns {Promise<{command: string, executable: string}|null>}
 */
export function resolvePython(configured) {
  if (cached) return Promise.resolve(cached)
  if (inflight) return inflight
  if (Date.now() - missAt < NEGATIVE_TTL_MS) return Promise.resolve(null)
  inflight = (async () => {
    const ordered = []
    if (configured && String(configured).trim()) ordered.push(String(configured).trim())
    const fromEnv = process.env.DSH_GM_PYTHON
    if (fromEnv && fromEnv.trim()) ordered.push(fromEnv.trim())
    ordered.push(...CANDIDATES)
    for (const command of ordered) {
      const hit = await probe(command)
      if (hit) {
        cached = hit
        return hit
      }
    }
    missAt = Date.now()
    return null
  })().finally(() => {
    inflight = null
  })
  return inflight
}

/** 清掉探测缓存（配置改动、或测试用）。 */
export function resetPythonCache() {
  cached = null
  inflight = null
  missAt = 0
}

/**
 * 跑一条 gmtool 子命令，返回 stdout+stderr 合并文本。
 * 不抛异常：非零退出码也把输出交给模型看，让模型自己判断。
 */
export function runGmtoolEx(python, scriptPath, args, { timeoutMs = 900000, maxOutput = 20000 } = {}) {
  return new Promise((resolve) => {
    execFile(python, [scriptPath, ...args], {
      env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
      timeout: timeoutMs,
      maxBuffer: 64 * 1024 * 1024,
      windowsHide: true,
      encoding: 'utf8',
    }, (error, stdout, stderr) => {
      let text = String(stdout || '')
      if (stderr) text += (text ? '\n' : '') + '[stderr]\n' + String(stderr)
      if (!text.trim() && error) text = String(error)
      if (text.length > maxOutput) text = `${text.slice(0, maxOutput)}\n…（已截断，完整输出 ${text.length} 字符）`
      const code = error && typeof error.code === 'number' ? error.code : (error ? 1 : 0)
      resolve({ code, text: text.trim() || '(无输出)' })
    })
  })
}

/**
 * 跑一条 gmtool 子命令，返回 stdout+stderr 合并文本。
 * 不抛异常：非零退出码也把输出交给模型看，让模型自己判断。
 */
export function runGmtool(python, scriptPath, args, options = {}) {
  return runGmtoolEx(python, scriptPath, args, options).then((r) => r.text)
}
