---
name: game-modding
description: 单机游戏修改方法论与一体化工具 gmtool：引擎判定、Unity Mono 程序集反汇编/等长 IL 打补丁、存档格式自动探测（AES 头布局/压缩/MessagePack/LZ4BlockArray/明文 JSON）与字节级安全改写、输入注入工具。适用于“关掉试玩模式 / 解锁内容 / 改存档 / 做辅助工具”这类需求。
whenToUse: 用户要求修改某个单机游戏的试玩限制、解锁内容、存档数据、快捷键，或为游戏做外部辅助工具时使用；也适用于需要逆向 Unity/.NET 游戏二进制与存档的场合。
version: 12
---

# 游戏修改方法论 + gmtool

本技能随 `dsh-gm-toolkit` 插件发布，**只挂在「存档修改」模式的会话里**：普通会话
看不到它、也不挂 `gm_*` 工具，所以日常零开销。要用，先在「全局面板 → 存档修改」里
点「用「存档修改」模式新建会话」，或新建会话时在模式里选「存档修改」。

**能看到 `gm_*` 工具时**直接调 `gm_doctor` / `gm_probe` / `gm_save_list` /
`gm_save_get` / `gm_save_apply` / `gm_dll_types` / `gm_dll_dis` / `gm_dll_xref` /
`gm_dll_patch`（参数与下面的 CLI 一一对应，不必进 shell）。

**看不到工具但需要跑命令时**，用本技能目录里的同一份脚本：

```bash
export PYTHONIOENCODING=utf-8
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
G="$HERE/scripts/gmtool.py"          # 技能目录内；与插件根目录 scripts/gmtool.py 字节相同（test/smoke.mjs 会断言）
/c/Python312/python.exe "$G" probe "<存档或资源文件>"
/c/Python312/python.exe "$G" dll types "<Assembly-CSharp.dll>" demo
```

Windows 上路径带反斜杠时直接写绝对路径，例如
`C:\Python312\python.exe "D:\deepseek\dsh-gm-toolkit\scripts\gmtool.py" probe "…"`；
双击可用 `scripts/gmtool.bat`。

---

## 0. 开工三问（不问清楚必返工）

1. **游戏在跑吗？** 存档会被内存覆盖，`Assembly-CSharp.dll`/exe 会被占用（写入失败或改完被覆盖）。
2. **分清楚两个目录**：安装目录 ≠ 存档目录。Windows Unity 存档常见于
   `C:\Users\<用户>\AppData\LocalLow\<厂商>\<游戏>\saves\`。
   （本项目里用户为此纠正过一次：“别搞错了，你看看上下文”。）
3. **可逆性**：动手前复制整个存档目录到 `D:\...\<游戏>_backup_<时间戳>\`，记录大小 + md5 + 还原命令，写进交付。

---

## 1. gmtool 三个子命令

### probe —— 存档/资源格式探测（先跑这个，别靠猜）

自动尝试：gzip / zlib / lz4 frame / zstd / zip / MessagePack / 明文 JSON / **AES 头布局爆破**
（枚举 `头长度 0..32` × `key 16/32` × `iv 16/0`，满足 `(size-hdr-key-iv)%16==0` 且解出合法 PKCS7 就命中），
然后递归穿透 `LZ4BlockArray`（Cysharp）直到最内层 MessagePack。开头是 `{` / `[` 的文件直接认成 JSON。

实测输出（咩咩启示录 `slot_0.mp`）：

```
[0] AES-128-CBC: 头=1 字节 45 | salt 16 | iv 16 | 密文 42448 = 2653*16
        解开 -> 42442 字节
[1] MessagePack LZ4BlockArray: 5 块 [4092, 32764, 32765, 32766, 16421]
[2] MessagePack 根: array 长度=1396  (118808 字节, 全消耗=True)
        -> 这就是最终数据，可用 save 子命令读写
```

### save —— 读/改存档（MessagePack 自动穿透 AES + LZ4 并重新加密；明文 JSON 直接原地改）

```bash
$G save dump "<slot>"            # 整棵树
$G save dump "<slot>" 394        # 只看某个字段（点号路径可下钻 1162.4.1）
$G save get  "<slot>" 635
$G save set  "<slot>" 635=True          # 原地写（自动 .bak 备份）
$G save set  "<slot>" 422=99 -o new.mp  # 写副本
$G save add  "<slot>" 394=411           # 数组插入（有序列表保持有序）
$G save remove "<slot>" 405=54
```

铁律（已在真实存档上验证）：
- **字节级 splice，绝不整体 re-serialize**：容器只记元素个数不记总长，替换同类值安全；整体 packb 会把 float32(0xca) 变 float64(0xcb)、改变字段顺序，游戏可能直接拒读。
- **同宽度优先**：换 int 时优先选与原编码等长的形式，周围偏移一个字节都不动。
- 数组增删会重写数组头（≤15 用 `0x90|n`，≤0xffff 用 `0xdc`+u16）。
- 写回时**重新生成随机 salt/IV**，保留原头字节；压缩块数可以变（单块也行，实测游戏能读）。

明文 JSON 存档（Unity 常见的 `{"Key" : {"__type": "…", "value": …}}`）：

```bash
$G probe     "<save>"                    # 报 JSON 根: object 子项=N
$G save dump "<save>" --limit 20          # 缩进树形
$G save get  "<save>" ".Item/MainCharacterItemData.value.entries.0.instanceID"
$G save set  "<save>" ".GameRulesManager_RuleIndex.value=77"
$G save add  "<save>" ".Item/…​.entries=123"        # 数组追加
$G save add  "<save>" "<对象路径>=新键=123"          # 对象加字段
$G save remove "<save>" ".Item/…​.entries.28"
```

JSON 存档的铁律同上，另加两条：
- **容忍畸形**：真实存档里会有 `{"__type" : "int"0`（少逗号）这种碎片，解析器不报错，
  当匿名成员收下；改动只拼接目标区间，碎片原样留着。
- **保留原排版**：`add` / `remove` 沿用原文件的 `\r\n` 与 TAB 缩进，加完再删可用字节级比对还原。

### dll —— 反汇编 + 等长 IL 打补丁

```bash
$G dll types  "<dll>" demo          # 找可疑类型（正则）
$G dll methods "<dll>" GameManager
$G dll fields  "<dll>" GameManager
$G dll dis    "<dll>" GameManager get_IsDemo
$G dll xref   "<dll>" IsDemo        # 全程序集交叉引用（字段/方法都行）
$G dll enum   "<dll>" UpgradeSystem.Type
$G dll patch  "<dll>" GameManager get_IsDemo --ret-false -o out.dll
$G dll patch  "<dll>" A B --bytes 16,2A     # 手写 IL 字节
$G dll patch  "<dll>" A B --nop             # 整个方法体变 nop
```

`patch` 会自动做：RVA→文件偏移、算 IL 起止（`insn.offset` 是**文件偏移**不是 RVA）、
校验等长（放不下就拒绝）、`0x00` 补 nop、写副本、**回读反汇编打印结果**。

实测：

```
补丁 Interaction_BaseTeleporter::GetLabel
  IL 文件偏移 0x159200..0x15924C  容量 76 字节
  新版: 16 2a 00 00 ...（填充 0x00 = nop）
回读: 159200:ldc.i4.0 | 159201:ret | 159202:nop | ...
```
差异校验：64 字节变化，**全部落在 0x159201..0x15924B**，文件长度不变。

---

## 2. 引擎判定（决定路线，先看再干）

| 证据 | 引擎 | 路线 |
| --- | --- | --- |
| `<游戏>_Data\Managed\Assembly-CSharp.dll` + `MonoBleedingEdge\` | Unity **Mono** | 直接改 DLL 里的 IL（最容易） |
| `GameAssembly.dll` + `il2cpp_data\Metadata\global-metadata.dat` | Unity **IL2CPP** | 无托管元数据，改内存/改 metadata，成本高 |
| exe 带 CLR 头（`BSJB` 元数据签名） | .NET 程序 | 直接反编译 |
| 纯原生 exe（无托管痕迹） | C++ 等 | 训练器 / 内存修改 / 外部转接 |

判断：目录里有没有 `Managed\`；`grep -c BSJB <file>`。

---

## 3. 定位“开关”的套路

1. **先找总开关**：`get_IsDemo` / `get_IsTrial` / `IsLockedForXxx` / `CanUse` / `IsUnlocked`。
   典型形态 `bool get_IsDemo() => this.isDemo;` → 补成 `ldc.i4.0; ret`（2 字节 + nop 填满）。
2. **改 getter 优先于改字段**：一处覆盖全部调用方，且不依赖存档/场景里的序列化值。
3. **但要看调用方完整性**：`$G dll xref IsDemo` 把所有引用列出来，逐个判断
   （例：Guns 'n Goblins 有 13 个 `IsLockedForDemo`、`DemoLevelCap.Update` 的封顶警告、`UIManager.OpenMenu(6)` 的无条件弹窗）。
4. **UI 写死的提示要单独处理**：只改逻辑不改 UI，会出现“能用了但仍然提示锁定”。
5. **硬编码清单很常见**：例如建造菜单 `MajorDLCCategory.GetStructuresForCategory(i)` 直接
   `ldc.i4` 一串 id，再用 `StructuresData.GetUnlocked(type)` 过滤 → 清单在代码里，很好 dump。

### 最坑的一类：标志不同步（只读代码看不出来）

本项目实证：`405 UnlockedUpgrades` 里有 `311 Building_Furnace`（升级已解锁），
但 `394 UnlockedStructures` 里没有 `411 FURNACE_1`（建筑结构未解锁）→
**任务让你造熔炉，建造菜单里一个可建造项都没有**。
这类问题只能拿存档逐字段比对 + 看游戏日志（`Player.log` 里直接有 `Unlock Building_Furnace!`）才能发现。
→ 修法：`$G save add "<slot>" 394=411`。

---

## 4. 存档格式破解（代码驱动，别靠猜）

1. **从写入代码切入**：搜 `Serialize` / `Save` / `CryptoStream` / `Aes` / `WriteByte`。
   例：`MMJsonDataReadWriter\`1::SerializeResult` →
   `WriteByte(69)` → 16 字节随机 salt → 16 字节 IV → `CryptoStream(aes.CreateEncryptor(salt, iv))`。
   于是布局 = `0x45 | salt(16) | iv(16) | AES-128-CBC/PKCS7(正文)`，校验：`size - 33` 是 16 的倍数。
2. **用 `gmtool probe` 验证**（它会把这种布局直接爆破出来，不用手算）。
3. **字段名映射**：读 `CustomAttribute` 表找 `MessagePack.KeyAttribute`，blob 形态
   `01 00 08 <int32> 00 00`（7 字节）或 `01 00 <int32> 00 00`（6 字节，CLI 固定参数不带类型字节），
   **首字节是 blob 长度前缀要去掉**。本项目由此建出 1392 条“索引→字段名”。

---

## 5. 写档协议（不变量优先，别靠举例）

gmtool 的每次写操作现在自带三道闸，**改档时的正确姿势是相信闸门、不要去查回读文本**：

1. **L1 不变量**：写之前先算，
   差异字节区间必须落在目标节点 span 内，且**用另一套独立解析器**（JSON 用 `json.loads`、msgpack 用第三方 `msgpack`）
   解码前后两份文档、逐路径比对，只允许目标路径不同。任一不满足 → **一个字节都不写**，退出码 5。
2. **L2 原子写 + 回滚**：先写临时文件、`os.replace` 原子替换；落盘后立刻回读复核
   （格式、明文字节、目标值三样都对得上才算过）。对不上 → 自动把原字节写回去，退出码 6。
   **最坏结果是“没改成”，不会是“档毁了”。**
3. **L3 模糊测试**：`gmtool fuzz --n 400 --seed 1` 随机生成 400 份风格各异的 JSON
   （BOM/CRLF/无缩进/空容器/unicode/尾垃圾），随机做 set/add/remove，
   既验证“合法改动只动目标字节”，也**反向**验证“改动落在区间外必须被抓出来”。
   失败样本自动落到 `test/corpus/`。怀疑工具本身有问题时先跑它，别拿真存档试。

给 agent 的硬规则：

- 见到退出码 **5** = 判据不通过（工具拒绝写），**不要**绕过、不要手改字节，先 `save dump` 看结构再改。
- 见到退出码 **6** = 落盘后复核失败并已回滚，**原文件完好**；把 `[stderr]` 那行原样报给用户。
- 不要用 `--out` 覆盖原文件来自测；用副本。
- 新增格式（protobuf、ES3、自定义二进制）时，**先给它加一条同样的不变量**（差异区间 + 独立解析器比对），
  再谈功能。这是本工具唯一一条不能省的成本。

## 6. 验证纪律（交付可信度的全部来源）

- 改完**逐字段比对**新旧存档，输出“差异字段列表”，必须等于预期（通常是 1 个）。
- DLL 补丁**逐字节比对**，输出差异字节数与范围，必须落在目标 IL 区间内、总长度不变。
- 写回前 `tasklist` 检查游戏是否在跑。
- 交付时给：备份路径 + 文件大小 + md5/sha256 + 还原命令。

---

## 6. 输入注入 / 热键工具

- 训练器热键常**硬编码且不可配置**（无 config、无键位表、API 名哈希解析）→ 只能外部转接：监听 A 键，合成 B 组合键。
- 合成按键必须带**扫描码**：`keybd_event(vk, MapVirtualKey(vk, 0), ...)`；只给 vk 多数程序收不到。
- 组合键时序：修饰键按下 → 30ms → 目标键按下 → 70ms → 抬起 → 30ms → 修饰键抬起。
- **本机重大坑**：`csc.exe` 编译的 .NET 进程里 `GetAsyncKeyState` 恒 0、`WH_KEYBOARD_LL` 收不到事件、
  `RegisterHotKey` 不触发、自己 `keybd_event` 也没人看得见；而 `powershell.exe`（含 exe 派生的）完全正常。
  → 架构：**exe 只当界面/配置器，键盘读写交给它点开的 PowerShell 引擎**。
  引擎 DLL 用 `[Reflection.Assembly]::Load([IO.File]::ReadAllBytes($dll))` 加载（`LoadFrom` 会报 `0x80131515`）；
  不要用 `Add-Type -TypeDefinition`（现场调 csc 报“客户端没有所需的特权”）。
- 工具“窗口在前台好用、切到游戏失效”时：先加**常开日志**（前台窗口标题 + 是否检测到键 + 是否 fire），
  用日志区分“读不到键”和“注入了但游戏没收”，别猜。

---

## 7. 本机环境与踩坑清单

- **没有 .NET SDK**，只有 C# 5 编译器 `C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe`
  （不能用 `$"..."`、`?.`、表达式体、`nameof`）。
- 没有 ilspycmd / dnSpy / Mono.Cecil → 用 Python：
  `C:\Python312\python.exe -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple dnfile dncil msgpack lz4 pycryptodome`
  （官方 pypi 被拒，nuget CDN 会卡死；清华/阿里镜像可用）
- **MSYS2 精简版没有 `strings` / `iconv` / `md5sum` / `od` / `cygpath`**：用 Python 代替。
- shell 只有 `win_bash`（MSYS2 bash）；Windows PowerShell 5.1 路径
  `/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -ExecutionPolicy Bypass -File x.ps1`
- **带中文的 `.ps1` 必须 UTF-8 with BOM**，否则 PS 5.1 按 GBK 读，报 `表达式或语句中包含意外的标记`。
- 中文输出先 `export PYTHONIOENCODING=utf-8`。
- `tasklist` 输出是 GBK，MSYS2 里乱码：用 `//FI "IMAGENAME eq X.exe"` 看“没有运行的任务”关键字，或 Python `subprocess(errors='ignore')`。
- 传参给 Windows exe 时 `/nologo` 会被当路径 → 用 `-nologo`，或 `export MSYS2_ARG_CONV_EXCL='*'`。
- 编译报“未能写入输出文件” = 目标 exe 正在运行，先 `Stop-Process`。
- `dnfile` 坑：`pe.net.mdtables`（大写 M）、`ClrFieldAttr` 是属性式标志（`flags.fdStatic`）、
  `CustomAttribute` 的 `Parent.table` 是表对象用 `.row_index`、`Value.raw_data` 首字节是长度前缀。
- `dncil` 的 `instruction.offset` 是**文件偏移**；`ins.size` 有；`CilMethodBody` 用 `.max_stack`。
- 别用 `timeout` 命令（被 Windows 的 `timeout.exe` 抢走）；后台任务用 `&` + `sleep` + `kill`。
- 大 DLL 加载慢是正常的（12 MB 程序集 `dnPE(fast_load=False)` 约 60–70 秒），一个命令一次加载，别串太多。

## 8. 同目录附带脚本（gmtool 的前身，独立可用）

- `scripts/dotnet_disasm.py` —— 只做反汇编（types/methods/fields/dis/xref/grep/enum）
- `scripts/msgpack_splice.py` —— 只做 msgpack 字节级编辑（dump/get/set/add/remove）

## 不知道存档在哪时

先跑 `gmtool.py scan`（面板里是「扫描我的存档」）：它扫 LocalLow / Local / Roaming /
Documents\My Games / Saved Games / Steam userdata，按「目录像不像存档目录 + 扩展名 +
文件头格式 + 大小」打分，并自动把备份副本排到后面。输出带格式判定
（AES-CBC / EasySave3 / gzip / zlib / lz4 / zstd / JSON / MessagePack），
`未识别` 的才需要按下面「破解未知存档格式」的流程继续挖。
