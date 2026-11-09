#!/usr/bin/env python3
"""dnfile + dncil 通用反汇编工具（无需 .NET SDK / dnSpy）。

用法:
  python dotnet_disasm.py <dll> types [正则]          列出类型
  python dotnet_disasm.py <dll> methods <类型名>      列出方法
  python dotnet_disasm.py <dll> fields <类型名>       列出字段
  python dotnet_disasm.py <dll> dis <类型名> [方法名]  反汇编（带 token 解析）
  python dotnet_disasm.py <dll> xref <名字>           全程序集交叉引用（字段或方法）
  python dotnet_disasm.py <dll> grep <正则>           反汇编里搜字符串常量
  python dotnet_disasm.py <dll> enum <枚举类型名>      导出枚举 名称->数值

依赖: pip install -i https://pypi.tuna.tsinghua.edu.cn/simple dnfile dncil
"""
import re
import sys

import dnfile
from dncil.cil.body import CilMethodBody
from dncil.cil.body.reader import CilMethodBodyReaderBase
from dncil.cil.error import MethodBodyFormatError


class _Reader(CilMethodBodyReaderBase):
    """把方法的 RVA 映射到文件偏移后按字节读（dncil 的 offset 是文件偏移）。"""

    def __init__(self, pe, row):
        self.pe = pe
        self.offset = pe.get_offset_from_rva(row.Rva)

    def read(self, n):
        data = self.pe.get_data(self.pe.get_rva_from_offset(self.offset), n)
        self.offset += n
        return data

    def tell(self):
        return self.offset

    def seek(self, offset):
        self.offset = offset


class Asm:
    def __init__(self, path):
        self.pe = dnfile.dnPE(path, fast_load=False)
        t = self.pe.net.mdtables
        self.types = list(t.TypeDef.rows)
        self.methods = list(t.MethodDef.rows)
        self.fields = list(t.Field.rows)
        self.mrefs = list(t.MemberRef.rows)
        self.mid = {id(r): i + 1 for i, r in enumerate(self.methods)}
        self.fid = {id(r): i + 1 for i, r in enumerate(self.fields)}
        self.owner_of_method, self.owner_of_field = {}, {}
        for ty in self.types:
            for m in ty.MethodList:
                self.owner_of_method[self.mid.get(id(m.row))] = self.tf(ty)
            for f in ty.FieldList:
                self.owner_of_field[self.fid.get(id(f.row))] = self.tf(ty)

    @staticmethod
    def tf(row):
        ns = str(getattr(row, 'TypeNamespace', '') or '')
        nm = str(getattr(row, 'TypeName', '') or '')
        return f"{ns}.{nm}" if ns else nm

    def body(self, mrow):
        try:
            return CilMethodBody(_Reader(self.pe, mrow))
        except MethodBodyFormatError:
            return None

    def resolve(self, operand):
        if operand is None or not hasattr(operand, 'table'):
            return ''
        tb, rid = operand.table, operand.rid
        try:
            if tb == 0x06:
                return f"{self.owner_of_method.get(rid, '?')}::{self.methods[rid - 1].Name}"
            if tb == 0x04:
                return f"{self.owner_of_field.get(rid, '?')}::{self.fields[rid - 1].Name}"
            if tb == 0x0A:
                mr = self.mrefs[rid - 1]
                cls = mr.Class.row if hasattr(mr.Class, 'row') else mr.Class
                owner = self.tf(cls) if hasattr(cls, 'TypeName') else 'Ext'
                return f"{owner}::{mr.Name}"
            if tb == 0x01:
                return f"<TypeRef {self.mrefs[rid - 1].Name}>"
            if tb == 0x02:
                return f"<TypeDef {self.tf(self.types[rid - 1])}>"
        except Exception:
            pass
        return f"<tok 0x{tb:02X}/{rid}>"

    def text_of(self, operand):
        if operand is not None and not hasattr(operand, 'table'):
            cls = type(operand).__name__
            if cls == 'UserString':
                try:
                    return repr(operand.value[:120])
                except Exception:
                    pass
            return str(operand)
        return self.resolve(operand)


def find_type(asm, name):
    for ty in asm.types:
        full = asm.tf(ty)
        if full == name or str(ty.TypeName) == name or full.endswith('.' + name):
            return ty
    return None


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 1
    path, cmd = argv[1], argv[2]
    rest = argv[3:]
    asm = Asm(path)

    if cmd == 'types':
        pat = rest[0] if rest else ''
        rx = re.compile(pat, re.I) if pat else None
        seen = set()
        for ty in asm.types:
            full = asm.tf(ty)
            if rx and not rx.search(full):
                continue
            if full in seen:
                continue
            seen.add(full)
            n = len(list(ty.MethodList))
            print(f"{full}    ({n} methods)")
        return 0

    if cmd in ('methods', 'fields'):
        ty = find_type(asm, rest[0])
        if ty is None:
            print('找不到类型:', rest[0])
            return 2
        if cmd == 'methods':
            for m in ty.MethodList:
                print(f"  rid={asm.mid.get(id(m.row))}  {m.row.Name}")
        else:
            for f in ty.FieldList:
                print(f"  rid={asm.fid.get(id(f.row))}  {f.row.Name}")
        return 0

    if cmd == 'dis':
        ty = find_type(asm, rest[0])
        if ty is None:
            print('找不到类型:', rest[0])
            return 2
        want = rest[1] if len(rest) > 1 else None
        for m in ty.MethodList:
            if want and str(m.row.Name) != want:
                continue
            b = asm.body(m.row)
            if b is None:
                continue
            print(f"--- {asm.tf(ty)}::{m.row.Name} ({len(b.instructions)} insn) ---")
            for ins in b.instructions:
                print(f"  {ins.offset:06X}: {str(ins.opcode):<14}{asm.text_of(ins.operand)}")
        return 0

    if cmd == 'xref':
        target = rest[0]
        for ty in asm.types:
            for m in ty.MethodList:
                b = asm.body(m.row)
                if b is None:
                    continue
                hits = []
                for ins in b.instructions:
                    op = ins.operand
                    if op is None or not hasattr(op, 'table'):
                        continue
                    if op.table == 0x04:
                        nm = str(asm.fields[op.rid - 1].Name)
                    elif op.table == 0x06:
                        nm = str(asm.methods[op.rid - 1].Name)
                    else:
                        continue
                    if nm == target:
                        hits.append((ins.offset, str(ins.opcode)))
                if hits:
                    print(f"{asm.tf(ty)}::{m.row.Name}")
                    for off, op in hits:
                        print(f"    {off:06X} {op}")
        return 0

    if cmd == 'grep':
        rx = re.compile(rest[0], re.I)
        for ty in asm.types:
            for m in ty.MethodList:
                b = asm.body(m.row)
                if b is None:
                    continue
                for ins in b.instructions:
                    txt = asm.text_of(ins.operand)
                    if txt and rx.search(txt):
                        print(f"{asm.tf(ty)}::{m.row.Name} @{ins.offset:06X} {txt[:160]}")
                        break
        return 0

    if cmd == 'enum':
        t = asm.pe.net.mdtables
        consts = list(t.Constant.rows)
        byparent = {}
        for c in consts:
            p = c.Parent
            if type(p.table).__name__ == 'Field':
                byparent[p.row_index] = c
        ty = find_type(asm, rest[0])
        if ty is None:
            print('找不到枚举:', rest[0])
            return 2
        rows = []
        for f in ty.FieldList:
            c = byparent.get(asm.fid.get(id(f.row)))
            if c is None:
                continue
            raw = c.Value.raw_data
            blob = raw[1:] if raw and raw[0] == len(raw) - 1 else raw
            if not blob or len(blob) > 8:
                continue
            val = int.from_bytes(blob, 'little', signed=(blob[-1] & 0x80) != 0)
            if str(f.row.Name) == 'value__':
                continue
            rows.append((val, str(f.row.Name)))
        for v, n in sorted(rows):
            print(f"   {v}\t{n}")
        return 0

    print(__doc__)
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
