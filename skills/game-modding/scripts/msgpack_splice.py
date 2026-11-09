#!/usr/bin/env python3
"""带偏移的 MessagePack 编辑器：只做字节级 splice，绝不整体 re-serialize。

为什么：游戏存档往往对字段顺序/float 宽度敏感，整体重新 packb 会把
float32(0xca) 变成 float64(0xcb)、map 顺序也变，导致游戏读档失败。

用法:
  python msgpack_splice.py dump   <file.msgpack> [字段路径]     # 打印树/某个字段
  python msgpack_splice.py get    <file.msgpack> <路径>          # 如 394 或 1162.4.1
  python msgpack_splice.py set    <in> <路径>=<值> [-o out]      # 同宽度优先替换
  python msgpack_splice.py add    <in> <路径>=<int> [-o out]     # 数组插入（保持排序）
  python msgpack_splice.py remove <in> <路径>=<int> [-o out]     # 数组删除

路径用点号分隔；数组用下标。不带 -o 时原地覆盖。
"""
import struct
import sys


class Node:
    __slots__ = ('start', 'end', 'value', 'kind', 'children')

    def __init__(self, start, end, value, kind, children=None):
        self.start = start
        self.end = end
        self.value = value
        self.kind = kind
        self.children = children

    def __repr__(self):
        return f"<Node {self.kind} {self.start}:{self.end} {str(self.value)[:30]}>"


def _u(b, i, n, signed=False):
    return int.from_bytes(b[i:i + n], 'big', signed=signed)


def decode(b, i=0):
    s = i
    c = b[i]
    i += 1
    if c <= 0x7f:
        return Node(s, i, c, 'int')
    if 0x80 <= c <= 0x8f:
        return _map(b, s, i, c & 0x0f)
    if 0x90 <= c <= 0x9f:
        return _array(b, s, i, c & 0x0f)
    if 0xa0 <= c <= 0xbf:
        n = c & 0x1f
        return Node(s, i + n, bytes(b[i:i + n]).decode('utf-8', 'surrogatepass'), 'str')
    if c >= 0xe0:
        return Node(s, i, c - 0x100, 'int')
    if c == 0xc0:
        return Node(s, i, None, 'nil')
    if c == 0xc2:
        return Node(s, i, False, 'bool')
    if c == 0xc3:
        return Node(s, i, True, 'bool')
    if c == 0xc4:
        n = b[i]; i += 1
        return Node(s, i + n, bytes(b[i:i + n]), 'bin')
    if c == 0xc5:
        n = _u(b, i, 2); i += 2
        return Node(s, i + n, bytes(b[i:i + n]), 'bin')
    if c == 0xc6:
        n = _u(b, i, 4); i += 4
        return Node(s, i + n, bytes(b[i:i + n]), 'bin')
    if c in (0xc7, 0xc8, 0xc9):
        if c == 0xc7:
            n = b[i]; i += 1
        elif c == 0xc8:
            n = _u(b, i, 2); i += 2
        else:
            n = _u(b, i, 4); i += 4
        t = b[i]; i += 1
        return Node(s, i + n, (t, bytes(b[i:i + n])), 'ext')
    if c == 0xca:
        return Node(s, i + 4, struct.unpack('>f', b[i:i + 4])[0], 'float32')
    if c == 0xcb:
        return Node(s, i + 8, struct.unpack('>d', b[i:i + 8])[0], 'float64')
    if c == 0xcc:
        return Node(s, i + 1, _u(b, i, 1), 'int')
    if c == 0xcd:
        return Node(s, i + 2, _u(b, i, 2), 'int')
    if c == 0xce:
        return Node(s, i + 4, _u(b, i, 4), 'int')
    if c == 0xcf:
        return Node(s, i + 8, _u(b, i, 8), 'int')
    if c == 0xd0:
        return Node(s, i + 1, _u(b, i, 1, True), 'int')
    if c == 0xd1:
        return Node(s, i + 2, _u(b, i, 2, True), 'int')
    if c == 0xd2:
        return Node(s, i + 4, _u(b, i, 4, True), 'int')
    if c == 0xd3:
        return Node(s, i + 8, _u(b, i, 8, True), 'int')
    if c == 0xd4:
        t = b[i]; i += 1
        return Node(s, i + 1, (t, bytes(b[i:i + 1])), 'ext')
    if c == 0xd5:
        t = b[i]; i += 1
        return Node(s, i + 2, (t, bytes(b[i:i + 2])), 'ext')
    if c == 0xd6:
        t = b[i]; i += 1
        return Node(s, i + 4, (t, bytes(b[i:i + 4])), 'ext')
    if c == 0xd7:
        t = b[i]; i += 1
        return Node(s, i + 8, (t, bytes(b[i:i + 8])), 'ext')
    if c == 0xd8:
        t = b[i]; i += 1
        return Node(s, i + 16, (t, bytes(b[i:i + 16])), 'ext')
    if c in (0xd9, 0xda, 0xdb):
        if c == 0xd9:
            n = b[i]; i += 1
        elif c == 0xda:
            n = _u(b, i, 2); i += 2
        else:
            n = _u(b, i, 4); i += 4
        return Node(s, i + n, bytes(b[i:i + n]).decode('utf-8', 'surrogatepass'), 'str')
    if c == 0xdc:
        return _array(b, s, i + 2, _u(b, i, 2))
    if c == 0xdd:
        return _array(b, s, i + 4, _u(b, i, 4))
    if c == 0xde:
        return _map(b, s, i + 2, _u(b, i, 2))
    if c == 0xdf:
        return _map(b, s, i + 4, _u(b, i, 4))
    raise ValueError('unknown msgpack code 0x%02x at %d' % (c, s))


def _array(b, s, i, n):
    kids = []
    for _ in range(n):
        node = decode(b, i)
        kids.append(node)
        i = node.end
    return Node(s, i, [k.value for k in kids], 'array', kids)


def _map(b, s, i, n):
    kids = []
    value = {}
    for _ in range(n):
        k = decode(b, i); i = k.end
        v = decode(b, i); i = v.end
        kids.append((k, v))
        try:
            value[k.value] = v.value
        except TypeError:
            value[repr(k.value)] = v.value
    return Node(s, i, value, 'map', kids)


def walk(node, path=()):
    yield path, node
    if node.kind == 'array':
        for idx, k in enumerate(node.children):
            yield from walk(k, path + (idx,))
    elif node.kind == 'map':
        for k, v in node.children:
            yield from walk(v, path + (k.value,))


def get(node, path):
    cur = node
    for p in path:
        if cur.kind == 'array':
            cur = cur.children[p]
        elif cur.kind == 'map':
            for k, v in cur.children:
                if k.value == p:
                    cur = v
                    break
            else:
                raise KeyError(p)
        else:
            raise TypeError('cannot index %s' % cur.kind)
    return cur


def encode_int(v):
    if 0 <= v <= 0x7f:
        return bytes([v])
    if -32 <= v < 0:
        return bytes([v & 0xff])
    if 0 <= v <= 0xff:
        return b'\xcc' + bytes([v])
    if 0 <= v <= 0xffff:
        return b'\xcd' + struct.pack('>H', v)
    if 0 <= v <= 0xffffffff:
        return b'\xce' + struct.pack('>I', v)
    if 0 <= v:
        return b'\xcf' + struct.pack('>Q', v)
    if -0x80 <= v:
        return b'\xd0' + struct.pack('>b', v)
    if -0x8000 <= v:
        return b'\xd1' + struct.pack('>h', v)
    if -0x80000000 <= v:
        return b'\xd2' + struct.pack('>i', v)
    return b'\xd3' + struct.pack('>q', v)


def splice(buf, node, newbytes):
    return buf[:node.start] + newbytes + buf[node.end:]


def set_scalar(buf, node, value):
    """同宽度优先：尽量用和原编码等长的形式，避免周围偏移移动。"""
    if isinstance(value, bool):
        new = b'\xc3' if value else b'\xc2'
    elif isinstance(value, int):
        orig_len = node.end - node.start
        new = encode_int(value)
        if len(new) != orig_len and node.kind == 'int':
            forms = []
            if 0 <= value < 0x80:
                forms.append(bytes([value]))
            if 0 <= value <= 0xff:
                forms.append(b'\xcc' + bytes([value]))
            if 0 <= value <= 0xffff:
                forms.append(b'\xcd' + struct.pack('>H', value))
            if 0 <= value <= 0xffffffff:
                forms.append(b'\xce' + struct.pack('>I', value))
            if -0x80 <= value < 0:
                forms.append(b'\xd0' + struct.pack('>b', value))
            if -0x8000 <= value < 0:
                forms.append(b'\xd1' + struct.pack('>h', value))
            for f in forms:
                if len(f) == orig_len:
                    new = f
                    break
    elif isinstance(value, float):
        if node.kind == 'float32' or (node.end - node.start) == 5:
            new = b'\xca' + struct.pack('>f', value)
        else:
            new = b'\xcb' + struct.pack('>d', value)
    else:
        raise TypeError('只支持 int/bool/float')
    return splice(buf, node, new)


def _array_header(n):
    if n <= 15:
        return bytes([0x90 | n])
    if n <= 0xffff:
        return b'\xdc' + struct.pack('>H', n)
    return b'\xdd' + struct.pack('>I', n)


def add_int(buf, arrnode, value):
    ids = [c.value for c in arrnode.children]
    if value in ids:
        return buf, False
    chunks = [buf[c.start:c.end] for c in arrnode.children]
    chunks.insert(len(ids) if ids != sorted(ids) else _bisect(ids, value), encode_int(value))
    return buf[:arrnode.start] + _array_header(len(chunks)) + b''.join(chunks) + buf[arrnode.end:], True


def _bisect(ids, value):
    lo, hi = 0, len(ids)
    while lo < hi:
        mid = (lo + hi) // 2
        if ids[mid] < value:
            lo = mid + 1
        else:
            hi = mid
    return lo


def remove_ints(buf, arrnode, values):
    kept = [c for c in arrnode.children if c.value not in values]
    payload = b''.join(buf[c.start:c.end] for c in kept)
    return buf[:arrnode.start] + _array_header(len(kept)) + payload + buf[arrnode.end:], len(kept)


def dump(node, indent=0, limit=60):
    pad = '  ' * indent
    if node.kind == 'array':
        print(f"{pad}array[{len(node.children)}] @{node.start}")
        for i, c in enumerate(node.children[:limit]):
            print(f"{pad}  [{i}]", end=' ')
            if c.kind in ('array', 'map'):
                print()
                dump(c, indent + 2)
            else:
                print(f"{c.kind} {c.value!r}")
        if len(node.children) > limit:
            print(f"{pad}  ... 共 {len(node.children)} 项")
    elif node.kind == 'map':
        print(f"{pad}map[{len(node.children)}] @{node.start}")
        for k, v in node.children[:limit]:
            print(f"{pad}  {k.value!r}: {v.value!r}")
    else:
        print(f"{pad}{node.kind} {node.value!r}")


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 1
    cmd = argv[1]
    path = argv[2]
    out = None
    if '-o' in argv:
        i = argv.index('-o')
        out = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]

    if cmd == 'dump':
        buf = open(path, 'rb').read()
        root = decode(buf)
        if len(argv) > 3:
            node = get(root, tuple(int(x) if x.lstrip('-').isdigit() else x for x in argv[3].split('.')))
            dump(node)
        else:
            dump(root)
        return 0

    if cmd == 'get':
        buf = open(path, 'rb').read()
        node = get(decode(buf), tuple(int(x) if x.lstrip('-').isdigit() else x for x in argv[3].split('.')))
        print(node.kind, repr(node.value), f"bytes {node.start}:{node.end}")
        return 0

    spec = argv[3]
    pstr, _, vstr = spec.partition('=')
    p = tuple(int(x) if x.lstrip('-').isdigit() else x for x in pstr.split('.'))
    buf = open(path, 'rb').read()
    root = decode(buf)
    node = get(root, p)

    if cmd == 'set':
        v = vstr.strip()
        if node.kind == 'bool':
            v2 = v.lower() in ('true', '1', 'yes', 'on')
        elif node.kind in ('float32', 'float64'):
            v2 = float(v)
        elif node.kind == 'str':
            v2 = v
        else:
            v2 = int(v, 0)
        new = set_scalar(buf, node, v2)
        print(f"set {pstr}: {node.value!r} -> {v2!r}  ({len(buf)} -> {len(new)} bytes)")
        buf = new
    elif cmd == 'add':
        buf, ok = add_int(buf, node, int(vstr, 0))
        print(('add' if ok else 'exists') + f" {pstr} += {vstr}  ({len(node.children)} -> {len(get(decode(buf), p).children)})")
    elif cmd == 'remove':
        buf, n = remove_ints(buf, node, {int(vstr, 0)})
        print(f"remove {pstr} -= {vstr}  ({len(node.children)} -> {n})")
    else:
        print(__doc__)
        return 1

    if out:
        open(out, 'wb').write(buf)
        print('written', out)
    else:
        open(path, 'wb').write(buf)
        print('written in place', path)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
