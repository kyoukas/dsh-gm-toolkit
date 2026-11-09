/**
 * dsh-gm-toolkit —— 单机游戏修改工具箱（宿主侧插件，常驻部分）
 *
 * 本文件只做三件不占模型上下文的事：
 *   1. 注册 HTTP 路由（/api/gm/*）—— 给「存档修改」面板用；
 *   2. 向 agent-preset 注册表登记一个 preset（id: gm-toolkit，显示名「存档修改」）；
 *   3. 自检信息（解释器 / 脚本 / Python 依赖）。
 *
 * 9 个 gm_* 工具**不在这里注册**，它们住在 tools.js，只由 preset 挂载：
 * 普通会话因此零 token 常驻，只有从「存档修改」入口（模式选择器或面板按钮）
 * 新建的会话才会看到这些工具与 game-modding 技能。
 *
 * 设计取舍：
 *   - 零 JS 依赖（只用 node: 内置模块），因为宿主 profile 里的 @deepseek-ai/* 软链
 *     可能不可解析，带 peerDependencies 的包在部分安装上根本加载不起来。
 *   - 真正的解析逻辑放在 Python 侧：二进制/加密/压缩这些活 Python 生态更全。
 *   - Python 解释器不写死，按 配置 → 环境变量 → PATH → 常见路径 探测。
 */
import { resolveScriptPath } from './src/runner.js'
import { makeRoutes } from './src/routes.js'
import { buildDeclaration, PRESET_ID } from './src/preset.js'
import { dshOpsPatchState } from './src/dshops.js'

export const name = 'dsh-gm-toolkit'

/**
 * 不声明静态 inject：路由等 webServer、preset 等 agentPresets，
 * 两者都可能缺席（例如纯 CLI 宿主），用 ctx.inject 各自等待即可。
 */
export async function apply(ctx, config) {
  const cfg = config && typeof config === 'object' ? config : {}
  // 常驻侧只要 scriptPath；Python 由路由/工具在真正调用时才探测（装上就能用，不必重启）。
  const scriptPath = resolveScriptPath(cfg)
  const log = (...args) => ctx.logger?.info?.('[gm-toolkit]', ...args)

  // ---- 图形面板走宿主 HTTP 路由：客户端只 fetch，不碰文件系统 ----------------
  if (typeof ctx.inject === 'function') {
    ctx.inject(['webServer'], (scoped) => {
      const routes = makeRoutes({ config: cfg, scriptPath, log })
      scoped.effect(() => {
        const registered = routes.map((route) => scoped.webServer.register(route))
        log(`注册 ${registered.length} 条 HTTP 路由（/api/gm/*）`)
        return () => {
          for (const dispose of registered) {
            try { dispose() } catch { /* 卸载时忽略 */ }
          }
        }
      }, 'dsh-gm-toolkit.routes')
    })

    // ---- preset：只有从该入口新建的会话才挂载 gm_* 工具与技能 ----------------
    ctx.inject(['agentPresets'], (scoped) => {
      scoped.effect(() => {
        let release
        let cancelled = false
        Promise.resolve(scoped.agentPresets.register(buildDeclaration(scoped, (src) => log(
          src === 'live' ? 'preset 行取自宿主 current standard（跟随 profile 升级）'
            : 'preset 行取自本地快照 presets/gm-toolkit/plugins.standard.json（宿主没暴露 standard 行）',
        )))).then((disposer) => {
          if (cancelled) {
            try { disposer() } catch { /* 已取消，忽略 */ }
            return
          }
          release = disposer
          log(`已注册 preset "${PRESET_ID}"（显示名：存档修改）`)
        }).catch((reason) => {
          ctx.logger?.warn?.(`[gm-toolkit] preset 注册失败: ${reason instanceof Error ? reason.message : String(reason)}`)
        })
        return () => {
          cancelled = true
          if (release !== undefined) {
            try { release() } catch { /* 卸载时忽略 */ }
          }
        }
      }, 'dsh-gm-toolkit.preset')
    })
  }

  log(`就绪；9 个 gm_* 工具只在「存档修改」模式挂载`)

  // dsh-ops 只认内置 preset id，我们这行本地补丁决定预设会话能不能拿到完整 ops_* 工具面。
  // 升级 dsh-ops 会把它冲掉，所以每次启动都报一下，别让工具面悄悄退化。
  const opsState = dshOpsPatchState()
  if (opsState === 'applied') {
    log('dsh-ops 补丁已应用：预设会话的工具面与标准模式一致（ops_glob / ops_grep / ops_inspect_local_file / ops_result 都在）')
  } else if (opsState === 'missing') {
    log('dsh-ops 补丁未应用：预设会话缺 ops_glob / ops_grep / ops_inspect_local_file / ops_result；'
      + '跑 node scripts/patch-dsh-ops.mjs 补上（dsh-ops 升级后要重跑）')
  } else {
    log('这台机器没装 dsh-ops：预设会话退回 dsh-ops/shell + dsh-ops/file 两个组件行')
  }
}
