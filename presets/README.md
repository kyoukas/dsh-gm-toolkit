# presets/

「存档修改」模式（`gm-toolkit`）的插件行清单。

## 文件

| 文件 | 作用 |
| --- | --- |
| `gm-toolkit/plugins.standard.json` | **唯一来源**。标准模式的插件行快照（数组），运行期只读它 |

`gm-toolkit/standard.patch.yml` 已删除：两份并存一定会漂移，而运行期不可能去解析 YAML
（宿主没把读取器暴露给插件，梁神模式为此自带了两百多行手写解析器）。需要追溯原始内容时看下面。

## 原始出处

宿主安装包里的标准模式补丁：

```
<DSH 安装目录>/resources/app.asar → node_modules/@deepseek-ai/dsh-web-app/presets/standard.patch.yml
```

（`app.asar` 里 `unpacked: true` 的条目没有 `offset`/`size`，真实文件在同级
`app.asar.unpacked/` 下。）

## 怎么重新生成

宿主升级后如果标准模式加了新插件，重新生成一次快照：

```bash
# 1) 从 asar 取出 standard.patch.yml（任选一种 asar 工具；下面这条不需要装依赖）
#    npx @electron/asar extract-file app.asar node_modules/@deepseek-ai/dsh-web-app/presets/standard.patch.yml
# 2) 注意结构：真正的插件行在 config.plugins 里，顶层那一条只是 @deepseek-ai/dsh-agent-preset 声明
python - <<'PY'
import io, json, yaml

class L(yaml.SafeLoader):
    pass

L.add_constructor('tag:yaml.org,2002:js', lambda loader, node: {'__jsExpr': node.value})

doc = yaml.load(io.open('standard.patch.yml', encoding='utf-8'), Loader=L)
rows = doc['insert'][0]['config']['plugins']
io.open(r'presets\gm-toolkit\plugins.standard.json', 'w', encoding='utf-8', newline='\n').write(
    json.dumps(rows, ensure_ascii=False, indent=2) + '\n')
print(len(rows), 'rows')
PY
```

`!!js` 表达式以 `{"__jsExpr": "..."}` 形式保存，运行期由 `src/preset.js` 的
`JS_EXPRESSIONS` 白名单求值——遇到白名单外的表达式会直接抛错，而不是把 preset 猜坏。

## 生成之后

`node test/smoke.mjs` 会检查行数、`gm-tools` 是否在末尾、`skill-filesystem` 的
`bundledSkillDir` 是否指向包内技能。行数变化是正常的（宿主升级会加插件），
失败的应该是 `dsh-ops-shell` / `dsh-ops-file` 这类行不见了。
