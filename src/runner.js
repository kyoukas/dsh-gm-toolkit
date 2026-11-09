/**
 * 一次解释器探测 + 一个 run(argv) 执行器。
 *
 * 宿主侧有两处用到它：HTTP 路由（/api/gm/*）与工具插件（tools.js）。
 * 把它抽出来是为了让「插件常驻部分」（路由、面板）和「preset 里的工具部分」
 * 共用同一套 Python 探测与错误话术，而不是各写一份。
 */
import fs from 'node:fs'
import path from 'node:path'
import { execFile } from 'node:child_process'
import { fileURLToPath } from 'node:url'

import { resolvePython, runGmtool } from './python.js'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const PACKAGE_ROOT = path.dirname(HERE)
export const BUNDLED_GMTOOL = path.join(PACKAGE_ROOT, 'scripts', 'gmtool.py')

/** 插件配置里的 gmtool.py 路径，没配就用插件自带的那份。同步、不探测 Python。 */
export function resolveScriptPath(config) {
  const cfg = config && typeof config === 'object' ? config : {}
  return cfg.gmtool ? String(cfg.gmtool) : BUNDLED_GMTOOL
}

export const PY_MODULES = ['dnfile', 'dncil', 'msgpack', 'lz4', 'Crypto']

/** 自检：解释器、脚本、Python 依赖三件事一次说清。 */
export function doctor(python, scriptPath) {
  const lines = []
  lines.push(`插件目录: ${PACKAGE_ROOT}`)
  lines.push(`gmtool.py: ${scriptPath}${fs.existsSync(scriptPath) ? '' : '  ← 不存在！'}`)
  if (!python) {
    lines.push('Python: 未找到。装一个 Python 3 并把 python.exe 放进 PATH，或在插件配置里写 python: C:\\Python3xx\\python.exe')
    return lines.join('\n')
  }
  lines.push(`Python: ${python.executable}  (通过 ${python.command} 找到)`)
  return lines.join('\n')
}

export function checkModules(python) {
  if (!python) return Promise.resolve('')
  const code = 'import importlib.util as u,sys;print("python "+sys.version.split()[0]);' +
    `[print(m+": "+("ok" if u.find_spec(m) else "missing")) for m in ${JSON.stringify(PY_MODULES)}]`
  return new Promise((resolve) => {
    execFile(python.executable, ['-c', code], { timeout: 20000, windowsHide: true }, (error, stdout, stderr) => {
      const text = String(stdout || '').trim() || String(stderr || error || '').trim()
      resolve(text)
    })
  })
}

/** 未找到解释器时统一的话术。 */
export const NO_PYTHON_HINT = '未找到可用的 Python 解释器，所有 gmtool 子命令都无法执行。\n' +
  '请安装 Python 3（并 pip install dnfile dncil msgpack lz4 pycryptodome），' +
  '或在插件配置里指定 python 路径。'

/**
 * @param {object} config 插件配置（python / gmtool 两个可选字段）
 * @returns {Promise<{python: object|null, scriptPath: string, run: (argv: string[]) => Promise<string>}>}
 */
export async function createRunner(config) {
  const cfg = config && typeof config === 'object' ? config : {}
  const python = await resolvePython(cfg.python)
  const scriptPath = cfg.gmtool ? String(cfg.gmtool) : BUNDLED_GMTOOL

  const run = async (argv) => {
    if (argv[0] === '__doctor__') {
      const base = doctor(python, scriptPath)
      const mods = await checkModules(python)
      return mods ? `${base}\n\n${mods}` : base
    }
    if (!python) return NO_PYTHON_HINT
    return runGmtool(python.executable, scriptPath, argv)
  }

  return { python, scriptPath, run }
}
