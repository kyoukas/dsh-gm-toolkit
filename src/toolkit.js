/**
 * 工具定义。
 *
 * 契约（与官方 defineTool 运行时等价）：{ name, description, parameters, output: { schema, render }, execute }。
 * 每个工具都是 gmtool.py 子命令的薄包装，输出一段文本，指针型 schema 由 render 直接拼。
 */
import { runGmtool } from './python.js'

const PATH_DESC = 'Windows 绝对路径，例如 D:\\game\\save.dat 或 D:\\game\\Managed\\Assembly-CSharp.dll'

const OUTPUT_SCHEMA = {
  type: 'object',
  properties: {
    text: { type: 'string', description: '命令的原始输出（可能已截断）。' },
  },
  required: ['text'],
  additionalProperties: false,
}

const PATH_PROP = { type: 'string', description: PATH_DESC }

/** 把 "set 635=True" 这类人类可读操作解析成 gmtool 的 argv。 */
const CHANGE_PATTERN = /^\s*(set|add|remove)\s+(\S+?)\s*=\s*(.+?)\s*$/i

/**
 * 构建全部工具定义。
 * @param {(args: string[]) => Promise<string>} run 已绑定解释器与脚本路径的执行器
 */
export function buildTools(run) {
  return [
    {
      name: 'gm_doctor',
      description: '自检：报告 Python 解释器、gmtool.py 路径，以及 dnfile/dncil/msgpack/lz4/pycryptodome 是否可用。工具报错或换机器时先跑它。',
      parameters: { type: 'object', properties: {}, required: [], additionalProperties: false },
      output: { schema: OUTPUT_SCHEMA, render: (_a, v) => [{ type: 'text', text: v.text }] },
      async execute() {
        return { text: await run(['__doctor__']) }
      },
    },

    {
      name: 'gm_probe',
      description: '探测游戏文件格式：自动识别 gzip/zlib/lz4 frame/zstd，暴力枚举 AES 头布局（头长 / key 长度 / IV 长度，用 PKCS7 合法性验证），再穿透 Unity Cysharp LZ4BlockArray 直到最内层 MessagePack，或识别出明文 JSON。看不懂一个存档时第一步就跑它。',
      parameters: {
        type: 'object',
        properties: {
          path: PATH_PROP,
          depth: { type: 'integer', description: '最多穿透层数，默认 6。' },
          hexlen: { type: 'integer', description: '打印开头多少字节的十六进制，默认 32。' },
        },
        required: ['path'],
        additionalProperties: false,
      },
      output: { schema: OUTPUT_SCHEMA, render: (_a, v) => [{ type: 'text', text: v.text }] },
      async execute(args) {
        const a = args || {}
        return { text: await run(['probe', String(a.path), '--depth', String(a.depth ?? 6), '--hexlen', String(a.hexlen ?? 32)]) }
      },
    },

    {
      name: 'gm_save_list',
      description: '列出存档的全部字段（编号或键名 / 类型 / 当前值）。支持 MessagePack 与明文 JSON。target 可传字段名或编号关键字做过滤。',
      parameters: {
        type: 'object',
        properties: {
          path: PATH_PROP,
          target: { type: 'string', description: '过滤关键字，可空。' },
          limit: { type: 'integer', description: '最多显示多少条，默认 200。' },
        },
        required: ['path'],
        additionalProperties: false,
      },
      output: { schema: OUTPUT_SCHEMA, render: (_a, v) => [{ type: 'text', text: v.text }] },
      async execute(args) {
        const a = args || {}
        const argv = ['save', 'dump', String(a.path)]
        if (a.target) argv.push(String(a.target))
        argv.push('--limit', String(a.limit ?? 200))
        return { text: await run(argv) }
      },
    },

    {
      name: 'gm_save_get',
      description: '读取存档里的单个字段，target 为点分路径（如 635、1162.4.1 或 .B.C）。输出会说明它穿透了哪些封装层，以及该值在字节流里的位置。',
      parameters: {
        type: 'object',
        properties: { path: PATH_PROP, target: { type: 'string', description: '字段路径。' } },
        required: ['path', 'target'],
        additionalProperties: false,
      },
      output: { schema: OUTPUT_SCHEMA, render: (_a, v) => [{ type: 'text', text: v.text }] },
      async execute(args) {
        const a = args || {}
        return { text: await run(['save', 'get', String(a.path), String(a.target)]) }
      },
    },

    {
      name: 'gm_save_apply',
      description: '改写存档，按顺序逐条执行 changes。每条形如 "set 635=True" / "add 394=411" / "remove 405=54"。默认先自动备份再原子写。写前有不变量校验：差异必须落在目标字节区间内，且用独立解析器比对目标之外语义不变——判据不过就一个字节都不写（退出码 5）；落盘后复核失败会自动回滚原字节（退出码 6）。只替换目标字节，其余（含 JSON 的缩进与畸形片段、MessagePack 的同宽度整数编码）原样保留。',
      parameters: {
        type: 'object',
        properties: {
          path: PATH_PROP,
          changes: { type: 'array', items: { type: 'string' }, description: '操作列表，按顺序执行。' },
          out: { type: 'string', description: '输出到另一个文件（留空则原地改）。' },
        },
        required: ['path', 'changes'],
        additionalProperties: false,
      },
      output: { schema: OUTPUT_SCHEMA, render: (_a, v) => [{ type: 'text', text: v.text }] },
      async execute(args) {
        const a = args || {}
        const list = Array.isArray(a.changes) ? a.changes : []
        if (list.length === 0) return { text: 'changes 为空，什么都没做。' }
        const lines = []
        // 给了 out 时：第一条从原文件读到 out，后续条在 out 上继续改（原文件不动）。
        // 否则每条都从原文件起算，后一条会覆盖前一条的改动。
        const outPath = a.out ? String(a.out) : null
        let input = String(a.path)
        // 备份判定必须看「真的备份过没有」，不能看数组下标：
        // 第 1 条解析失败或被跳过时，它没备份也没写 out，后面那条若按下标省备份，
        // 就会直接原地改原文件且零备份（--no-backup 不产生任何 .bak-*）。
        let backedUp = false
        let outWritten = false
        for (const change of list) {
          const matched = CHANGE_PATTERN.exec(String(change))
          if (!matched) {
            lines.push(`[跳过] 无法解析：${change}`)
            continue
          }
          const argv = ['save', matched[1].toLowerCase(), input, `${matched[2]}=${matched[3]}`]
          if (outPath !== null && !outWritten) argv.push('-o', outPath)
          else if (backedUp) argv.push('--no-backup')
          lines.push(`$ gmtool ${argv.join(' ')}`)
          const text = await run(argv)
          lines.push(text)
          if (/原文件已备份 -> /.test(text)) backedUp = true
          if (outPath !== null && !outWritten) {
            input = outPath
            outWritten = true
          }
        }
        return { text: lines.join('\n') }
      },
    },

    {
      name: 'gm_dll_types',
      description: '列出 .NET 程序集里的类型，pattern 是匹配 TypeNamespace.TypeName 的正则。找「试玩 / 解锁 / 开关」这类入口的第一步。',
      parameters: {
        type: 'object',
        properties: { dll: PATH_PROP, pattern: { type: 'string', description: '正则，可空则列出全部。' } },
        required: ['dll'],
        additionalProperties: false,
      },
      output: { schema: OUTPUT_SCHEMA, render: (_a, v) => [{ type: 'text', text: v.text }] },
      async execute(args) {
        const a = args || {}
        const argv = ['dll', 'types', String(a.dll)]
        if (a.pattern) argv.push(String(a.pattern))
        return { text: await run(argv) }
      },
    },

    {
      name: 'gm_dll_dis',
      description: '反汇编某个类型的 IL（member / 类型 token 自动解析成可读名字）。method 留空则整个类型；程序集较大时先列方法再挑一个。',
      parameters: {
        type: 'object',
        properties: {
          dll: PATH_PROP,
          type: { type: 'string', description: '类型全名，如 GunsNGoblins.GameManager。' },
          method: { type: 'string', description: '方法名，可空。' },
        },
        required: ['dll', 'type'],
        additionalProperties: false,
      },
      output: { schema: OUTPUT_SCHEMA, render: (_a, v) => [{ type: 'text', text: v.text }] },
      async execute(args) {
        const a = args || {}
        const argv = ['dll', 'dis', String(a.dll), String(a.type)]
        if (a.method) argv.push(String(a.method))
        return { text: await run(argv) }
      },
    },

    {
      name: 'gm_dll_xref',
      description: '找出所有读写指定字段或调用指定方法的位置，返回 类型.方法 + IL 文件偏移。定位「谁把这个开关打开了」用它。',
      parameters: {
        type: 'object',
        properties: { dll: PATH_PROP, target: { type: 'string', description: '字段名或方法名。' } },
        required: ['dll', 'target'],
        additionalProperties: false,
      },
      output: { schema: OUTPUT_SCHEMA, render: (_a, v) => [{ type: 'text', text: v.text }] },
      async execute(args) {
        const a = args || {}
        return { text: await run(['dll', 'xref', String(a.dll), String(a.target)]) }
      },
    },

    {
      name: 'gm_dll_patch',
      description: '等长 IL 打补丁并写副本到 out：自动算 RVA→文件偏移与 IL 起止、长度不够直接拒绝、用 0x00 补 nop，写完回读反汇编打印新指令。mode 取 ret-false / ret-true / nop / 十六进制字节串（如 "16,2A"）。不改原文件。',
      parameters: {
        type: 'object',
        properties: {
          dll: PATH_PROP,
          type: { type: 'string', description: '类型全名。' },
          method: { type: 'string', description: '方法名。' },
          mode: { type: 'string', description: 'ret-false | ret-true | nop | 十六进制字节串。' },
          out: { type: 'string', description: '输出文件路径（必填，避免误改原文件）。' },
        },
        required: ['dll', 'type', 'method', 'mode', 'out'],
        additionalProperties: false,
      },
      output: { schema: OUTPUT_SCHEMA, render: (_a, v) => [{ type: 'text', text: v.text }] },
      async execute(args) {
        const a = args || {}
        const mode = String(a.mode || '').trim()
        const flag = mode === 'ret-false' || mode === 'ret-true' || mode === 'nop' ? `--${mode}` : '--bytes'
        const argv = ['dll', 'patch', String(a.dll), String(a.type), String(a.method), flag]
        if (flag === '--bytes') argv.push(mode)
        argv.push('-o', String(a.out))
        return { text: await run(argv) }
      },
    },
  ]
}
