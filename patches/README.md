# 本地补丁（host 侧）

这里的东西**不属于插件本体**，改动的是 profile 里安装的第三方包。
升级那个包会把它冲掉，所以每次升级后要重跑一次。

## dsh-ops：让自定义 preset 也能拿到完整工具面

### 现象

「存档修改」模式的会话里只有 3 个 `ops_*` 工具（`ops_bash`、`ops_discover_tools`、`ops_read_files`），
而标准模式有 7 个：缺 `ops_glob`、`ops_grep`、`ops_inspect_local_file`、`ops_result`。
同时多出 4 个裸工具 `read` / `glob` / `grep` / `pwsh`，它们是标准模式里被 dsh-ops 替换掉的原始版本。

### 原因

`dsh-ops` 的工具面是按「模式」发布的，而模式由 preset id 反查：

```js
// node_modules/dsh-ops/lib/modes/detect.js
const modeByPreset = new Map(MODE_IDS.map(mode => [MODE_PRESET[mode], mode]))
```

`MODE_PRESET`（`lib/modes/types.js`）只有四个内置 id：`minimal` / `standard` / `ptc` / `cordis`。
我们自建的 `gm-toolkit` 不在表里 → `modeOf()` 返回 `undefined` → `matches()` 恒假 →
`dsh-ops/mode-standard` 那一行整块不发布（连 `mountWorkspacePreparation` 一起没有）。

这个 Map 是模块加载时建好的私有对象，`MODE_PRESET` 还被 `Object.freeze` 过，
运行期 monkey-patch 拿不到，只能改源码。

### 补法

```bash
node scripts/patch-dsh-ops.mjs          # 打补丁（幂等，已打过会提示）
node scripts/patch-dsh-ops.mjs --status # 看每个 profile 的状态
node scripts/patch-dsh-ops.mjs --revert # 撤销
```

补丁内容就一行，插在 Map 构造之后：

```js
modeByPreset.set('gm-toolkit', 'standard'); // dsh-gm-toolkit
```

即「`gm-toolkit` 这个 preset 按标准模式处理」。

### 打了补丁之后插件的行为

`src/preset.js` 会探测补丁状态：

- **已打**：preset 里**不再**自带 `dsh-ops/shell` 与 `dsh-ops/file` 组件行，
  交给 profile 上的 `dsh-ops/mode-standard` 统一发布（否则 `ops_bash` 会重复注册，宿主直接报冲突）。
- **没打 / 没装 dsh-ops**：退回两个组件行，工具面不完整但能用。

启动日志会告诉你当前是哪一种：

```
[gm-toolkit] dsh-ops 补丁已应用：预设会话的工具面与标准模式一致（…）
[gm-toolkit] dsh-ops 补丁未应用：预设会话缺 ops_glob / ops_grep / …；跑 node scripts/patch-dsh-ops.mjs 补上
```

### 什么时候要重跑

- 升级 / 重装 `dsh-ops` 之后
- 新建 profile 之后（脚本会扫 `~/.dsh/profiles/*/node_modules/`）
- 看到启动日志出现「补丁未应用」时

### 风险

改的是第三方包源码，只加一行、只影响模式判定。dsh-ops 若改了 `detect.js` 的写法，
脚本会报「找不到锚点」而不是乱改；补丁串是幂等的（`--status` 可查，`--revert` 可撤）。
