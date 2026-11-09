# Changelog

## 0.5.4

`set` 到「和当前值一样」不再报自检失败：

- **现象**：`save set s.json .a=1`（`a` 本身就是 1）退出码 5，stderr 是
  `自检未通过: 原文件侧差异终点 23 超出目标区间终点 10` + `已中止：原文件一个字节都没改`。
  文件确实没动，但值根本没变，报「自检未通过」把用户往「工具有毛病」的方向引（UI 上就是点写入、
  某个字段没改，却弹「写入失败（写前自检未通过）」）。
- **成因**：`assert_edit` 用 `_diff_span(before, after)` 算差异区间；新旧字节完全相同时这个区间是退化的，
  后面「差异终点不得超出目标区间」两条检查必然误报。
- **修法**：写档流程里 `plain == plain0`（即内容一模一样）时提前 `return 0`，打印
  「值没有变化，没有写任何东西」——不备份、不落盘；`assert_edit` 开头也加了 `before == after → 无问题`
  的兜底，保护直接调用它的两处。
- 回归：`test/smoke.mjs` 新增 no-op 用例（必须说「值没有变化」、不许出现「自检未通过」、
  不许改文件、不许产生 `.bak-*`）。
- 技能侧两份 `gmtool.py` 同步（`skills/game-modding/SKILL.md` version 11 → 12）。

## 0.5.3

### 预设会话补齐工具箱（ops_* 工具面）

- `gm-toolkit` 现在按标准模式发布工具面：`ops_glob` / `ops_grep` / `ops_inspect_local_file` / `ops_result`
  不再缺席，裸 `read` / `glob` / `grep` / `pwsh` 也被正常替换。
- 新增 `scripts/patch-dsh-ops.mjs`（`--status` / `--revert`，幂等）：`dsh-ops` 只按内置 preset id 判定模式
  （`MODE_PRESET` 里只有 minimal/standard/ptc/cordis，且 Map 是模块加载时建好、`Object.freeze` 过的），
  自定义 preset 需要一行本地补丁 `modeByPreset.set('gm-toolkit', 'standard')` 把它映射到标准模式。
- 新增 `src/dshops.js`：探测补丁状态（`applied` / `missing` / `absent`）。
- `src/preset.js`：补丁生效时不再自带 `dsh-ops/shell` + `dsh-ops/file` 组件行（否则 `ops_bash` 重复注册），
  未生效才退回组件行；启动日志会写明当前处于哪种状态。
- 新增 `patches/README.md`：现象、根因、补法、重跑时机、风险。
- `test/smoke.mjs`：按补丁状态分别断言组件行的去留。

### 批量写入的备份判定

`gm_save_apply` 的备份判定改成「真的备份过没有」，不再看数组下标：

- **第一条被跳过时后面那条会零备份原地改原文件**：`changes` 里第 1 条解析不出来会被 `[跳过]`，
  但第 2 条的 `index` 仍是 1，于是按 `index > 0` 加了 `--no-backup` —— 而 `--no-backup` 是原地写、
  不产生任何 `.bak-*`。工具 description 承诺的「默认先自动备份再原子写」在这条路径上是假的。
- **同一场景给了 `out` 更糟**：`-o` 死盯 `index === 0`，第 1 条被跳过后 `-o` 永远不加、`input` 停在原文件，
  结果是「写原文件 + 不生成 out + 带 `--no-backup`」。
- 改法：用 `backedUp` 标志（每轮从输出里 `/原文件已备份 -> /` 探测）代替下标判断，只有备份过才加
  `--no-backup`；`-o` 改成「第一条真正执行的」带，`input` 也只在那条落地后才推进到 out。
- 回归：`test/smoke.mjs` 新增 1c 段，覆盖「首条跳过后仍备份」「首条跳过 + out 仍带 -o」
  「已备份过才省备份」三条。

## 0.5.2

审查后的一轮修复（两处「实际没生效」+ 五处边角）：

- **P1 技能根本没加载**：`skills/game-modding/SKILL.md` 带 UTF-8 BOM，`---` 不在文件开头，
  宿主按 `missing YAML frontmatter` 静默丢弃整个技能（`desktop-next.log:259`）。
  去掉 BOM；`index.js`、`src/preset.js`、`src/routes.js` 的 BOM 一并清掉，统一成无 BOM。
- **P2 isolate 修复会被 live 分支绕过**：宿主暴露 standard 真实行时 `dsh-ops-shell` 已存在，
  按 id 去重会保留那份没 isolate 的、丢掉补过的。`buildRows` 里对 live 行同样 `.map(withOpsIsolation)`。
- **P3 批量 + out 丢改动**：每条都从 `body.path` 读、写同一个 out，后一条直接把前一条覆盖。
  改成链式：第一条 原文件 → out，后续条在 out 上继续改（`--no-backup`），原文件不动。
  `gm_save_apply` 工具侧同样处理。
- **P4 写前基线取晚了**：`st0` 原本在 `load_layers` 之后，读 → stat 之间游戏存一次档就比不出来。
  改成先 `stat` + 读原始字节，写前再读一次逐字节比对；备份/回滚也用最初那份字节。
- **P5 退出码 5 有两种含义但文案只认一种**：路由把 5/6 统一翻成固定文案，新加的
  「文件在读取之后被改动过」被吞掉。现在两条都拼上 `failureReason` 的具体原因。
- **P6 `presets/README.md` 引用不存在的 `_asar.py`**：换成 `npx @electron/asar extract-file`。
- **P7 小尾巴**：`install` 不再无条件 `ok: true`（`__pip__` 非 0 就 `ok:false` + 原因）；
  面板改用响应里的 `applied`/`backups`，批量中途失败会说「前 N 处已生效」并给出回滚备份。
- 新增回归用例：`out + 多条` 必须两条改动都在、且不碰原文件。
- 技能侧 `gmtool.py` 同步，`SKILL.md` version 10 → 11。

## 0.5.1

- `apply` 批量中途失败时，错误文案补上「前 N 条已生效 + 回滚用哪个备份」——此前只说「第 N 条失败」，
  容易让人以为整批没落盘。
- `add` 的落盘复核从「容器非空」升级为「容器恰好 +1 项，且新增的键/值确实在」。
- 写前再 `stat` 一次：从读到写之间文件被改动（游戏自动存档）就拒绝写入（退出码 5），
  避免回滚把更晚的存档覆盖成更早的快照。
- preset 注册时打印插件行来源（宿主 current standard / 本地快照），漂移时能查。
- 磁盘清理：`*.bak*` / `*.orig-*` 移入 `_attic/`；删除 `presets/gm-toolkit/standard.patch.yml`
  （与 `plugins.standard.json` 重复），新增 `presets/README.md` 记原始出处与重新生成步骤。
- 技能侧 `gmtool.py` 同步，`SKILL.md` version 9 → 10。

## 0.5.0

审查后的一轮修复（不动 gmtool.py 的写档逻辑，只修宿主侧、面板与打包）：

- **修运行期告警** `Preset services require isolate realms: opsSettings`：`dsh-ops/shell` 会
  `provide('opsSettings')`，preset 里发布的 service 不落 isolate realm 就会被宿主写进 root store，
  预设卸载时按 realm 清理，可能连带删掉 root 的 slot。现在 shell 行带 `isolate: { opsSettings: true }`，
  并且优先沿用宿主真实的 standard 行（自带 isolate），只补缺的那一项。
- **修浅色主题下不可读**：面板的 CSS 变量名 9 个错 8 个（`--dsw-alias-text-primary` 这类根本不存在），
  全部改成权威 token（`--dsw-alias-label-primary` / `-border-l1` / `-bg-layer-1|-bg-layer-2` /
  `-brand-primary` 等），硬编码颜色换成 `--dsw-alias-state-*`；同时去掉 `var(…, fallback)` 的兜底值 ——
  正是它把写错的变量名静默吞掉，才让这个问题一直没被发现。
- **侧栏图标**改成矢量「存档文件 + 折角 + 字段行」，接 `ownerProps { size, active }`（跟随尺寸与激活态），
  不再用 `⚙` 字符。
- **「用「存档修改」模式新建会话」按钮不再卡在降级文案**：面板改用 `ctx.get('uiWorkspace')` 取服务，
  不再依赖非响应式的 `ref.current`（服务晚于首渲染到达时永远不会刷新）。
- **批量改档只留一份备份**：第一条写原始文件（自动备份），后续条目加 `--no-backup`；失败时回报
  `applied`（已成功几条）和 `backups[]`，前端能看到「前 N 条已经写进去了」。
- **`/api/gm/apply` 改用数字退出码**（5 = 写前自检拦截、6 = 落盘后已回滚）判定失败，删掉三条匹配输出文本的正则
  （它们原本是死代码：非零码在更早的分支就返回了）；写盘前先整体校验 `op` / `target`，`target` 里带 `=` 直接拒绝。
- `pickJson` 从每个 `{` 位置试解析，说明文字里带 `{` 也不会切错 JSON。
- **Python 探测不再永久缓存失败结果**：装好 Python 后最多 5 秒即可用，不必重启 DSH。
- 常驻侧不再在加载时探测 Python（原来 `createRunner()` 会跑一遍解释器探测，现在只取脚本路径）。
- **技能目录里的 `gmtool.py` 与 `scripts/gmtool.py` 重新同步**（技能侧原是 34KB 旧副本，根目录已是 82KB），
  `SKILL.md` 升到 v9；`test/smoke.mjs` 增加「两份必须字节相同」断言。
- 打包排除 `scripts/`、`src/` 下的 `*.bak*` / `*.orig-*` 与 `__pycache__`。
- 测试：`test/routes-smoke.mjs` 在没有那份 CotL 存档的机器上自动跳过存档用例，不再换机即挂；
  新增批量改档、空 `target`/非法 `op` 校验用例；`import.meta.dirname` 换成 `fileURLToPath`（Node 20.0 也能跑）。
- README 的安全边界改成如实描述：扫描按钮会遍历常用存档目录（只读不写）、一键安装会联网（不点不发生），
  本插件自身没有出网代码。

## 0.4.1

- 修「存档修改」会话里没有 `ops_*` 工具（`pwsh` 会撞工作区属主报错）：
  `dsh-ops/mode-standard` 行对自定义 preset 无效——dsh-ops 的 `modeOf()` 只认内置 preset id
  （`minimal`/`standard`/`ptc`/`cordis`），我们的 `gm-toolkit` 命中不了，整块不发布。
  改为挂不带 mode 门禁的组件行 `dsh-ops/shell` + `dsh-ops/file`，preset 声明变为 27 行。

## 0.4.0

从「例子对例子地修」改成「不变量 + 独立校验 + 自动回滚 + 模糊测试」：

- **L1 写前不变量**：差异字节区间必须落在目标节点 span 内；并用独立解析器（json.loads / 第三方 msgpack）
  解码前后两份文档逐路径比对，只允许目标路径不同。不满足则拒绝写入（退出码 5），原文件零改动。
- **L2 原子写 + 落盘后回滚**：临时文件 + `os.replace`；落盘后复核格式/明文字节/目标值，
  任一不一致就自动写回原字节（退出码 6）。最坏结果是「没改成」，不是「档毁了」。
- **L3 `gmtool fuzz`**：随机 JSON（BOM/CRLF/缩进/空容器/unicode/尾垃圾）+ 随机 set/add/remove，
  正向验证「只动目标字节」，反向验证「区间外改动必须被抓出」，失败样本落到 `test/corpus/`。
- 目标节点前后字节逐字节必须原样保留（能抓到「改到文件末尾垃圾区」这类情况）。
- 严格解析器读不了的原文件（带尾垃圾/畸形）退回本工具容忍解析做结构比对，不再跳过语义检查。
- 修模糊测试暴露的自身缺陷：期望值比对取错了文档（拿了 before）；`_deep_mask` 数组下标 int 与路径 str 对不上；
  `add`/`remove` 归一化用宽松相等（`False == 0.0`）会删错元素；反向测试把「新增值所占区间」误判为区间外；
  容器变化量为负时尾部对齐算错。
- 重复键、null 改类型、字符串空格、根节点保护等 0.3.3 的修复全部纳入不变量覆盖。

## 0.3.3

子代理 JSON 压测（32 个场景）后的第二批修复：

- 修 P0：BOM 文件所有写操作错位 3 字节。`load_layers` 入口统一剥 BOM，`rewrap` 负责补回；`set .a=42` 不再把 `{"a": 1}` 写成 `{"a42: 1}`。
- 修 P0：回读校验从「能解析就算过」改为「按期望值核对目标字段」。
- 未闭合 JSON 不再报「全消耗=True」：`JNode.closed` 标记括号是否真的闭合。
- 禁止直接改根节点（`set =5` 原先先写坏再崩）。
- `null` 字段可以改类型（原先一旦是 null 就永远被写成字符串）。
- 字符串值不再吞首尾空格。
- `j_get` 抛 `GmError` 而非 `SystemExit`（否则失败路径退出码与提示都错）。
- 重复键改为「后者生效」，与 Unity/Newtonsoft 一致。

## 0.3.2

- 修：`bool` 字段给非法字符串（如 `635=abc`）过去会被静默当成 `false` 写盘，现在直接报错、不写文件。
- 修：路径写错不再甩 Python Traceback —— 数组用字符串下标、下标越界、缺字段、文件不存在、没权限，都给一句中文提示 + 退出码。
- 修：同一秒内连续改档会覆盖备份，现在自动加 `-2`、`-3` 后缀。
- 修：明文（未压缩）MessagePack 存档被改写后会被擅自套上 `LZ4BlockArray`，现在原样写回。
- 修：HTTP 层把失败当成功返回（`ok:true`）；现在非零退出码一律 `ok:false`，并只回错误那一行，不再掺层信息。
- 新：`save get --json` 真正输出 JSON（给面板用）。
- 新：JSON 允许 UTF-8 BOM。
- 改：「存档修改」模式的组合优先取宿主当前真实注册的 standard 行（读不到才用快照），并把 `dsh-ops` 的 `mode-standard` / `discovery` / `panel` 行一并带上 —— 之前预设会话缺 `ops_*`，会退回裸 `pwsh` 撞上工作区属主那类沙箱报错。

## 0.3.1

支持明文 JSON 存档：`gm_probe` / `gm_save_list` / `gm_save_get` / `gm_save_apply` 现在也能读写
不经压缩、不经加密的 JSON 存档（Unity 常见的 `{"key" : {"__type": ..., "value": ...}}` 形状）。

- `gmtool.py` 新增 JSON 层：带字节跨度的容忍式解析器，遇到畸形片段（例如 `{"__type" : "int"0`
  少了逗号）不报错、当匿名成员收下，改动时只拼接目标区间
- **不整体重新序列化**：键序、缩进（`\r\n` + TAB）、空格风格、畸形片段全部原样保留，
  只替换目标值那几个字节；`add` / `remove` 沿用原换行与缩进风格，加完再删可字节级还原
- `load_layers()` 改为返回 `(明文, rewrap, kind)`，`kind` 为 `msgpack` 或 `json`；
  加密分支也接受「解出来是 JSON」的存档
- `gm_probe` 对开头 `{` / `[` 的文件直接报告 `JSON 根: object 子项=N (全消耗=True)`
- 新增回归测试：`test/smoke.mjs` 里用一段含畸形片段的 JSON 走完 probe → list → get → set，
  并断言「只替换目标值、畸形片段原样保留」

## 0.3.0

改成「按入口激活」：普通会话零常驻，工具与技能只在「存档修改」模式的会话里挂载。

- 新增 agent preset `gm-toolkit`（显示名「存档修改」，`order: 20`）：组合 = 标准模式的
  22 行插件 + 本插件自己的 `gm-tools` 行，由 `index.js` 在激活时通过
  `ctx.agentPresets.register()` 声明（不写任何 harness 配置文件）
- 9 个 `gm_*` 工具从 `index.js` 拆到根目录 `tools.js`，**不再全局注册**：
  常量上下文从 ≈1507 tokens/轮 降到 0；只有 preset 会话才挂载
- `game-modding` 技能随包发布（`skills/game-modding/`），通过 preset 里
  `skill-filesystem` 行的 `bundledSkillDir` 提供：普通会话的技能目录里不再出现它
  （省 ≈110 tokens），也不再需要手工装到 `~/.dsh/skills`
- `presets/gm-toolkit/plugins.standard.json`：把宿主自带的 `standard.patch.yml`
  在开发期转成 JSON（宿主没暴露 YAML 读取器，梁神模式为此自带解析器，这里不重复造）
- `src/preset.js`：把 `!!js` 表达式按白名单求值成真布尔值（只认 standard 里那三条），
  未知表达式直接抛错而不是猜；并给 `skill-filesystem` 注入 `bundledSkillDir`
- 面板顶部新增「存档修改模式」卡片：一键 `uiWorkspace.startSession(undefined, {agentPreset})`
  开一个带工具的会话；拿不到该服务时降级成文字提示（新建会话时选模式）
- `src/runner.js`：把 Python 探测与 `run(argv)` 抽出来，常驻侧（路由）与工具侧共用
- `test/smoke.mjs` 增加两条回归判据：`index.js` 不得注册任何工具、preset 声明必须带
  `gm-tools` 行与 `bundledSkillDir`

## 0.2.1

面板加「扫描存档」：不用知道存档在哪。

- `gmtool.py` 新增 `scan` 子命令：扫 `LocalLow` / `Local`(浅) / `Roaming`(浅) /
  `Documents\My Games` / `Documents\Saved Games` / Steam `userdata`，
  按「所在目录像不像存档目录 + 扩展名 + 文件头格式 + 大小」打分排序
- 只读文件头判格式：`AES-CBC` / `EasySave3` / `gzip` / `zlib` / `lz4` / `zstd` / `JSON` / `MessagePack`
- 自动区分「当前存档」与「备份副本」（目录名含 backup/bak/old/副本、文件名带 .bac/.bak、同目录更旧的文件）
- 宿主路由 `POST /api/gm/scan`；面板里点「扫描我的存档」，列表点一行直接填入路径并探测

## 0.2.0

新增图形面板，并把 `gmtool.py` 的能力暴露给界面。

- 客户端面板「存档修改」：全局面板入口 + 独立页面（`client.js`，零构建，手写 module-loader 格式）
- 宿主 HTTP 路由 `/api/gm/{doctor,install,probe,list,get,apply}`：全部 POST + JSON body，
  只接受环回地址，body 上限 64 KB
- `gmtool.py` 新增 `__doctor__`（输出 JSON 体检结果）与 `__pip__`（按镜像安装缺失依赖）
- `save dump|get` 新增 `--json`（给界面用的行式输出：`path` / `kind` / `value` / `leaf` / `parents`），
  并让 `--json` 时不再打印「穿透层」说明，避免污染 stdout
- 新增 `test/routes-smoke.mjs`：起最小 http 服务把 6 条路由全打一遍（含 apply 到副本 + 回读校验）
- `package.json`：`exports["./client"]`、`dsh.client`（`platform: web`），version 0.2.0

## 0.1.0

首个版本。

- 9 个工具：`gm_doctor` / `gm_probe` / `gm_save_list` / `gm_save_get` / `gm_save_apply` /
  `gm_dll_types` / `gm_dll_dis` / `gm_dll_xref` / `gm_dll_patch`
- 内置 `gmtool.py`（961 行）：格式探测、MessagePack 存档字节级改写、
  .NET 反汇编与等长 IL 打补丁、无 schema protobuf 浏览
- Python 解释器自动探测（配置 / 环境变量 / PATH / 常见安装路径）
- 零 JS 依赖，纯 `node:` 内置模块
