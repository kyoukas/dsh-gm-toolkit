/**
 * dsh-gm-toolkit 的「工具」部分 —— 只在 agent preset 里挂载。
 *
 * 这个文件由主插件包根目录的 index.js 拆出来，目的很单纯：
 *   - index.js 常驻（HTTP 路由 + 面板 + preset 注册），必须零 token；
 *   - 这里的 9 个 gm_* 工具约 1.5K tokens/轮，只在「存档修改」模式的会话里挂载。
 *
 * preset 用绝对 file URL 引用它（见 src/preset.js），所以这里不做任何相对解析。
 */
import { createRunner } from './src/runner.js'
import { buildTools } from './src/toolkit.js'

export const name = 'dsh-gm-toolkit/tools'
export const inject = ['tools']

export async function apply(ctx, config) {
  const { python, run } = await createRunner(config)

  const disposers = []
  for (const definition of buildTools(run)) {
    disposers.push(ctx.tools.register(definition))
  }
  if (typeof ctx.effect === 'function') {
    ctx.effect(() => () => {
      for (const dispose of disposers) {
        try { dispose() } catch { /* 卸载时忽略单个工具的失败 */ }
      }
    }, 'dsh-gm-toolkit.tools')
  }
  ctx.logger?.info?.(`dsh-gm-toolkit/tools: 注册 ${disposers.length} 个工具` +
    (python ? `，Python = ${python.executable}` : '，但未找到 Python'))
}
