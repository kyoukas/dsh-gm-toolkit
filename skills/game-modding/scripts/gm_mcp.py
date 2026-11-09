#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gm-mcp —— 把 game-modding 技能里的 gmtool.py 暴露成 MCP 工具。

DSH 通过 @deepseek-ai/dsh-mcp-client 连接本服务（stdio），
工具会以 mcp__gm__<name> 的形式出现在模型工具列表里。

所有工具都是对同级目录 gmtool.py 的薄封装：解析、探测、反汇编、打补丁。
写操作一律先自动备份，并由调用方显式指定。
"""
from __future__ import annotations

import os
import subprocess
import sys

from mcp.server.mcpserver import MCPServer

HERE = os.path.dirname(os.path.abspath(__file__))
GMTOOL = os.path.join(HERE, "gmtool.py")
PYTHON = sys.executable
MAX_OUT = 20000

srv = MCPServer(
    name="gm",
    instructions=(
        "单机游戏修改工具集（存档探测/改写、.NET 程序集反汇编与等长打补丁）。"
        "先 gm_probe 看格式，再 gm_save_dump 看字段，最后 gm_save_apply 改；"
        "改 DLL 用 gm_dll_types → gm_dll_dis → gm_dll_patch。"
        "写档前确认游戏已退出，写档后比对差异字段。"
    ),
)


def _run(args: list[str]) -> str:
    """调用 gmtool.py，返回合并后的文本输出。"""
    if not os.path.exists(GMTOOL):
        return f"错误：找不到 gmtool.py（应在 {GMTOOL}）"
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        cp = subprocess.run(
            [PYTHON, GMTOOL] + args,
            capture_output=True,
            timeout=900,
            env=env,
            cwd=HERE,
        )
    except subprocess.TimeoutExpired:
        return "错误：gmtool 超时（900 秒）。大程序集首次加载较慢，可重试一次。"
    out = (cp.stdout or b"").decode("utf-8", "replace")
    err = (cp.stderr or b"").decode("utf-8", "replace").strip()
    txt = out
    if err:
        txt = (txt + "\n[stderr]\n" + err).strip()
    if not txt:
        txt = f"（无输出，退出码 {cp.returncode}）"
    if cp.returncode not in (0, None):
        txt = f"[退出码 {cp.returncode}]\n" + txt
    if len(txt) > MAX_OUT:
        txt = txt[:MAX_OUT] + f"\n…（截断，完整 {len(txt)} 字符；用更窄的条件再查）"
    return txt


@srv.tool(
    name="gm_probe",
    description=(
        "探测任意游戏文件的格式层级，是改档/改资源的第一步。"
        "自动识别 gzip/zlib/lz4/zstd/MessagePack，并暴力枚举 AES 头布局"
        "（头长度 0..32 × 密钥 16/32 字节 × IV 16/0），成功则打印解密后的下一层；"
        "遇到 Unity/Cysharp 的 LZ4BlockArray 会继续穿透到最内层 MessagePack。"
    ),
)
def gm_probe(path: str, depth: int = 6) -> str:
    """path: 存档或资源文件路径；depth: 最多向下穿透几层（默认 6）。"""
    return _run(["probe", path, "--depth", str(depth)])


@srv.tool(
    name="gm_save_dump",
    description=(
        "读取存档（自动穿透 AES + LZ4）并按字段打印内容。"
        "target 为空时打印整棵树（可能很长，用 limit 控制）；"
        "target 可以是顶层字段索引（如 394）或点号路径（如 1162.4）。"
    ),
)
def gm_save_dump(path: str, target: str = "", limit: int = 200) -> str:
    args = ["save", "dump", path]
    if target:
        args.append(target)
    args += ["--limit", str(limit)]
    return _run(args)


@srv.tool(
    name="gm_save_get",
    description="读取存档里单个字段的值（点号路径，如 635 或 1162.4.1）。",
)
def gm_save_get(path: str, target: str) -> str:
    return _run(["save", "get", path, target])


@srv.tool(
    name="gm_save_apply",
    description=(
        "批量修改存档。changes 是字符串列表，每条一个操作，格式：\n"
        "'set 635=True'      改值（按原编码宽度优先，不移动后续字节）\n"
        "'add 394=411'       往数组里插入（保持有序）\n"
        "'remove 405=54'     从数组里删除\n"
        "out 为空则原地写（先自动备份 <文件>.bak-<时间戳>）；给 out 则写副本。"
        "函数会输出每条操作的增减与字节宽度变化。"
    ),
)
def gm_save_apply(path: str, changes: list[str], out: str = "") -> str:
    """changes: 形如 ["set 635=True", "add 394=411"]；out: 输出路径，留空=原地写。"""
    if not changes:
        return "错误：changes 为空，没有要执行的操作。"
    lines: list[str] = []
    for raw in changes:
        raw = (raw or "").strip()
        if not raw:
            continue
        parts = raw.split(None, 1)
        op = parts[0].lower()
        if op not in ("set", "add", "remove") or len(parts) < 2:
            return f"错误：无法解析操作 {raw!r}，应为 'set 路径=值' / 'add 路径=值' / 'remove 路径=值'。"
        spec = parts[1].strip()
        args = ["save", op, path, spec]
        if out:
            args += ["-o", out]
        lines.append(f"### {op} {spec}")
        lines.append(_run(args))
    return "\n".join(lines)


@srv.tool(
    name="gm_dll_types",
    description=(
        "在 .NET / Unity Mono 程序集里按名称正则查找类型，显示类型名与类型命名空间。"
        "做游戏逻辑 patch 的第一站：先找 IsDemo / IsLocked / CanUse / Unlock 之类。"
        "12MB 的程序集首次加载约需 60 秒。"
    ),
)
def gm_dll_types(dll: str, pattern: str = "") -> str:
    args = ["dll", "types", dll]
    if pattern:
        args.append(pattern)
    return _run(args)


@srv.tool(
    name="gm_dll_dis",
    description=(
        "反汇编指定类型的某个方法（或整个类型），标注 RVA/文件偏移、token 解析后的引用。"
        "method 留空则输出该类型全部方法。"
    ),
)
def gm_dll_dis(dll: str, type_name: str, method: str = "") -> str:
    args = ["dll", "dis", dll, type_name]
    if method:
        args.append(method)
    return _run(args)


@srv.tool(
    name="gm_dll_xref",
    description=(
        "全程序集交叉引用：谁读/写了某个字段、谁调用了某个方法。"
        "改开关前必查——用它可以确认「一处改掉是否全覆盖」以及有没有其它硬编码入口。"
    ),
)
def gm_dll_xref(dll: str, name: str) -> str:
    return _run(["dll", "xref", dll, name])


@srv.tool(
    name="gm_dll_patch",
    description=(
        "对 IL 做等长补丁，自动算 RVA→文件偏移、校验长度、0x00 补 nop、写副本并回读反汇编。"
        "mode 取值：ret-false（改成 return false）、ret-true（return true）、"
        "nop（整个方法体变 nop）、或直接给 IL 十六进制字节串如 '16,2A'。\n"
        "补完请用逐字节比对确认差异只落在目标 IL 区间内。"
    ),
)
def gm_dll_patch(dll: str, type_name: str, method: str, mode: str, out: str = "") -> str:
    """mode: ret-false / ret-true / nop / 十六进制字节串（如 16,2A）。"""
    args = ["dll", "patch", dll, type_name, method]
    m = (mode or "").strip()
    low = m.lower()
    if low in ("ret-false", "ret_false", "false"):
        args.append("--ret-false")
    elif low in ("ret-true", "ret_true", "true"):
        args.append("--ret-true")
    elif low == "nop":
        args.append("--nop")
    else:
        args += ["--bytes", m]
    if out:
        args += ["-o", out]
    return _run(args)


def main() -> None:
    srv.run("stdio")


if __name__ == "__main__":
    main()
