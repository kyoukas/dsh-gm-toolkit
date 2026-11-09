# dsh-gm-toolkit

给 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 用的**单机游戏修改工具箱**插件。

它把「看不懂的存档 / 打不开的开关」这类活拆成四步，并各给一个工具：探测格式 → 读写存档 → 反汇编定位 → 等长打补丁。模型可以直接调用，不需要你记命令行。

## 两种用法（默认零开销）

插件分「常驻部分」和「按需部分」，目的只有一个：**平时不占你的上下文**。

| | 常驻（每个会话都在） | 按需（只在「存档修改」模式的会话里） |
| --- | --- | --- |
| 内容 | 存档修改面板、`/api/gm/*` 路由、preset 声明 | 9 个 `gm_*` 工具（≈1.5K tokens）、`game-modding` 技能（≈110 tokens） |
| 怎么进来 | 自动（客户端 UI 不占模型上下文） | 新建会话时在模式里选「存档修改」，或点面板上的「用「存档修改」模式新建会话」 |

模式在会话创建时就定了，之后不能换 —— 所以想改存档，从入口进，别在普通会话里现装。

## 它能干什么

| 工具 | 用途 |
| --- | --- |
| `gm_doctor` | 自检：Python 解释器、`gmtool.py`、依赖库是否齐全 |
| `gm_probe` | 探测任意游戏文件：gzip/zlib/lz4/zstd、AES 头布局爆破、Unity `LZ4BlockArray`、最内层 MessagePack，或直接认出明文 JSON |
| `gm_save_list` | 列出存档全部字段（编号 / 名字 / 类型 / 当前值） |
| `gm_save_get` | 读单个字段，并告诉你它穿透了哪些封装层 |
| `gm_save_apply` | 改存档（`set` / `add` / `remove`），自动备份 + 写完回读校验 |
| `gm_dll_types` | 列出 .NET 程序集类型（正则过滤） |
| `gm_dll_dis` | 反汇编某类型 / 方法的 IL，token 自动解析成可读名 |
| `gm_dll_xref` | 找出所有读写某字段、调用某方法的位置 |
| `gm_dll_patch` | 等长 IL 打补丁，RVA→文件偏移自动换算，回读验证 |

## 图形面板：存档修改

装上插件后，左侧「全局面板」里会多一行 **存档修改**，点进去是一个可视化的存档编辑器，不依赖模型：

- **运行环境**：进页面自动体检（Python 解释器 + `dnfile`/`dncil`/`msgpack`/`lz4`/`pycryptodome`），缺什么就点「一键安装缺失」（走清华镜像）。
- **找存档**：点「扫描我的存档」，自动扫 `LocalLow` / `Local` / `Roaming` / `My Games` / `Saved Games` / Steam 云存档，按可信度排序，标出每个文件的格式（`AES-CBC` / `EasySave3` / `JSON` / `MessagePack` …），点一行就填进路径框；备份副本默认折叠。
- **存档文件**：粘贴完整路径（或从扫描结果里点一行）→ 「探测格式」，认不出来会明确告诉你需要先在会话里分析。
- **字段浏览**：面包屑 + 逐层下钻 + 本层搜索；叶子字段点「改」就地编辑，容器字段点「展开」。
- **待应用列表**：改动先攒着，点「应用到存档」才真正写盘；写前自动备份，页面显示备份路径。
- **引导**：面板顶部「怎么用」写明了完整流程和「先退游戏再写档」这条硬规矩。

面板和模型工具共用同一份 `gmtool.py`，所以格式支持完全一致；区别只是面板不会替你猜字段含义，也不支持未识别的自定义格式。

## 安装

```bash
# 1. 装本插件
dsh plugin --profile desktop add dsh-gm-toolkit
# 本地开发时用 link：
dsh plugin --profile desktop add "link:D:/path/to/dsh-gm-toolkit"

# 2. 准备 Python 侧依赖（只有存档/反汇编需要，缺哪个对应功能就不能用）
python -m pip install dnfile dncil msgpack lz4 pycryptodome
```

装完**重启 DSH**（配置文件的热重载在部分安装上会失败，重启最稳），然后在插件列表里应能看到 `dsh-gm-toolkit`。

## 配置

```yaml
- insert:
    - id: dsh-gm-toolkit
      name: dsh-gm-toolkit
      config:
        python: 'C:\Python312\python.exe'   # 可选，留空则自动探测
        gmtool: ''                          # 可选，换成你自己的脚本
```

解释器探测顺序：`config.python` → 环境变量 `DSH_GM_PYTHON` → `PATH` 上的 `python3`/`python` → 常见安装路径。

## 典型工作流

```
# 1. 这个文件是什么？
gm_probe  path=D:\game\save.dat

# 2. 里面有什么字段？
gm_save_list  path=D:\game\save.dat  target=Unlock

# 3. 改它
gm_save_apply  path=D:\game\save.dat  changes=["add 394=411", "set 635=True"]

# 4. 改不动？去代码里找开关
gm_dll_types  dll=D:\game\Managed\Assembly-CSharp.dll  pattern=demo|trial
gm_dll_xref   dll=...\Assembly-CSharp.dll  target=IsDemo
gm_dll_patch  dll=...  type=GameManager  method=get_IsDemo  mode=ret-false  out=patched.dll
```

## 环境依赖：dsh-ops 模式补丁

`dsh-ops` 的工具面按 preset id 查表发布，表里只有四个内置 id。自定义的 `gm-toolkit`
不在表里，于是「存档修改」模式一开始只有 3 个 `ops_*`（`ops_bash` / `ops_discover_tools` / `ops_read_files`），
缺 `ops_glob` / `ops_grep` / `ops_inspect_local_file` / `ops_result`。

补一行让它按标准模式处理：

```bash
node scripts/patch-dsh-ops.mjs --status   # 看状态
node scripts/patch-dsh-ops.mjs            # 打补丁（幂等）
node scripts/patch-dsh-ops.mjs --revert   # 撤销
```

升级 `dsh-ops` 后要重跑。细节见 [patches/README.md](patches/README.md)。

## 设计取舍

- **零 JS 依赖**：只用 `node:` 内置模块。有些 DSH 安装里 `@deepseek-ai/*` 的软链是坏的，带 `peerDependencies` 的插件会加载失败 —— 本插件不受影响。
- **逻辑放 Python**：AES / LZ4 / MessagePack / .NET 元数据这些活，Python 生态比 JS 全得多（`pycryptodome`、`python-lz4`、`msgpack`、`dnfile`+`dncil`）。
- **默认不破坏文件**：`gm_save_apply` 先备份再写，写完回读校验；`gm_dll_patch` 必须给 `out`，只写副本。
- **同宽度优先**：改整数时优先用和原值一样宽的 MessagePack 编码，字节数不变，避免整段偏移移动；JSON 存档则只替换目标值那一段字节，缩进、键序、甚至残缺片段都原样留着。

## 安全边界

- **读写只发生在你显式给出的路径上**：`gm_probe` / `gm_save_get` / `gm_save_apply` / `gm_dll_*` 都只碰你传进来的那个文件。
- **「扫描我的存档」会扫盘**：`/api/gm/scan`（面板上的「扫描我的存档」按钮）会遍历
  `%USERPROFILE%\AppData\LocalLow`、`AppData\Local`、`AppData\Roaming`、`Documents` 和 Steam 云存档目录，
  只读取文件名/大小/前若干字节做格式判定，**不写**这些目录。不想被扫就不要点它，直接在输入框里填路径。
- **「一键安装缺失」会联网**：`/api/gm/install` 会调 `pip install -i <镜像>` 装
  `dnfile` / `dncil` / `msgpack` / `lz4` / `pycryptodome`。不点就不会联网，本插件自身没有任何出网代码。
- **HTTP 路由只对本机回环地址开放**（`127.0.0.1` / `::1`），且只接受 POST + JSON body。
- 打补丁一律写副本，不原地改程序集（原文件留给你自己核对）。
- 改存档前请先退出游戏，否则游戏退出时会用内存里的旧数据覆盖你的改动。

## License

MIT
