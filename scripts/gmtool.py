#!/usr/bin/env python3
"""gmtool —— 单机游戏修改一体化工具（“能看能改”）。

三个子命令组：
  probe  存档/资源格式探测：自动识别 AES 头布局、gzip/zlib/lz4/zstd/zip、msgpack、LZ4BlockArray
  save   在已解密的 MessagePack 上读/改（同宽度字节级 splice，绝不整体重序列化）
  dll    .NET/Unity Mono 程序集：列类型/反汇编/交叉引用/枚举/等长 IL 打补丁

例子：
  python gmtool.py probe "C:\\...\\slot_0.mp"
  python gmtool.py save dump "C:\\...\\slot_0.mp" --path 394
  python gmtool.py save set  "C:\\...\\slot_0.mp" 635=True --out new.mp
  python gmtool.py save add  "C:\\...\\slot_0.mp" 394=411
  python gmtool.py dll types Game.dll demo
  python gmtool.py dll dis   Dll GameManager get_IsDemo
  python gmtool.py dll xref  Dll IsDemo
  python gmtool.py dll patch Dll GameManager get_IsDemo --ret-false -o out.dll
"""
import argparse
import json
import os
import struct
import sys

# ---------------------------------------------------------------- msgpack 层
class Node:
    __slots__ = ('start', 'end', 'value', 'kind', 'children')

    def __init__(self, start, end, value, kind, children=None):
        self.start, self.end, self.value, self.kind, self.children = start, end, value, kind, children

    def __repr__(self):
        return f"<Node {self.kind} {self.start}:{self.end} {str(self.value)[:30]}>"


def _u(b, i, n, signed=False):
    return int.from_bytes(b[i:i + n], 'big', signed=signed)


def mp_decode(b, i=0):
    s = i
    c = b[i]
    i += 1
    if c <= 0x7f:
        return Node(s, i, c, 'int')
    if 0x80 <= c <= 0x8f:
        return _mp_map(b, s, i, c & 0x0f)
    if 0x90 <= c <= 0x9f:
        return _mp_arr(b, s, i, c & 0x0f)
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
    if c in (0xc4, 0xc5, 0xc6):
        n = b[i] if c == 0xc4 else (_u(b, i, 2) if c == 0xc5 else None)
        if c == 0xc4:
            i += 1
        elif c == 0xc5:
            i += 2
        else:
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
    if c in (0xd4, 0xd5, 0xd6, 0xd7, 0xd8):
        n = {0xd4: 1, 0xd5: 2, 0xd6: 4, 0xd7: 8, 0xd8: 16}[c]
        t = b[i]; i += 1
        return Node(s, i + n, (t, bytes(b[i:i + n])), 'ext')
    if c in (0xd9, 0xda, 0xdb):
        if c == 0xd9:
            n = b[i]; i += 1
        elif c == 0xda:
            n = _u(b, i, 2); i += 2
        else:
            n = _u(b, i, 4); i += 4
        return Node(s, i + n, bytes(b[i:i + n]).decode('utf-8', 'surrogatepass'), 'str')
    if c == 0xdc:
        return _mp_arr(b, s, i + 2, _u(b, i, 2))
    if c == 0xdd:
        return _mp_arr(b, s, i + 4, _u(b, i, 4))
    if c == 0xde:
        return _mp_map(b, s, i + 2, _u(b, i, 2))
    if c == 0xdf:
        return _mp_map(b, s, i + 4, _u(b, i, 4))
    raise ValueError('unknown msgpack code 0x%02x at %d' % (c, s))


def _mp_arr(b, s, i, n):
    kids = []
    for _ in range(n):
        nd = mp_decode(b, i)
        kids.append(nd)
        i = nd.end
    return Node(s, i, [k.value for k in kids], 'array', kids)


def _mp_map(b, s, i, n):
    kids, value = [], {}
    for _ in range(n):
        k = mp_decode(b, i); i = k.end
        v = mp_decode(b, i); i = v.end
        kids.append((k, v))
        try:
            value[k.value] = v.value
        except TypeError:
            value[repr(k.value)] = v.value
    return Node(s, i, value, 'map', kids)


def mp_walk(node, path=()):
    yield path, node
    if node.kind == 'array':
        for i, k in enumerate(node.children):
            yield from mp_walk(k, path + (i,))
    elif node.kind == 'map':
        for k, v in node.children:
            yield from mp_walk(v, path + (k.value,))


def mp_get(node, path):
    cur = node
    for p in path:
        if cur.kind == 'array':
            if not isinstance(p, int):
                raise GmError(f'这一层是数组，下标要用整数（例如 1162.0），收到 {p!r}')
            if p < 0 or p >= len(cur.children):
                raise GmError(f'数组下标越界: {p}（共 {len(cur.children)} 项）')
            cur = cur.children[p]
        elif cur.kind == 'map':
            for k, v in cur.children:
                if k.value == p:
                    cur = v
                    break
            else:
                raise GmError(f"找不到键: {p!r}（先 dump 看看这一层有哪些字段）")
        else:
            raise TypeError('cannot index %s' % cur.kind)
    return cur


def mp_encode_int(v):
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


def mp_set(buf, node, value):
    if isinstance(value, bool):
        new = b'\xc3' if value else b'\xc2'
    elif isinstance(value, int):
        want = node.end - node.start
        new = mp_encode_int(value)
        if len(new) != want and node.kind == 'int':
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
                if len(f) == want:
                    new = f
                    break
    elif isinstance(value, float):
        new = (b'\xca' + struct.pack('>f', value)) if node.kind == 'float32' or (node.end - node.start) == 5 \
            else (b'\xcb' + struct.pack('>d', value))
    elif isinstance(value, str):
        raw = value.encode('utf-8')
        new = (bytes([0xa0 | len(raw)]) if len(raw) <= 31 else b'\xd9' + bytes([len(raw)])) + raw
    else:
        raise TypeError('unsupported value type')
    return buf[:node.start] + new + buf[node.end:]


def _arr_header(n):
    if n <= 15:
        return bytes([0x90 | n])
    if n <= 0xffff:
        return b'\xdc' + struct.pack('>H', n)
    return b'\xdd' + struct.pack('>I', n)


def mp_add_int(buf, arr, value):
    ids = [c.value for c in arr.children]
    if value in ids:
        return buf, False
    chunks = [buf[c.start:c.end] for c in arr.children]
    idx = len(ids)
    if ids == sorted(ids):
        lo, hi = 0, len(ids)
        while lo < hi:
            mid = (lo + hi) // 2
            if ids[mid] < value:
                lo = mid + 1
            else:
                hi = mid
        idx = lo
    chunks.insert(idx, mp_encode_int(value))
    return buf[:arr.start] + _arr_header(len(chunks)) + b''.join(chunks) + buf[arr.end:], True


def mp_remove_int(buf, arr, value):
    kept = [c for c in arr.children if c.value != value]
    if len(kept) == len(arr.children):
        return buf, False
    return buf[:arr.start] + _arr_header(len(kept)) + b''.join(buf[c.start:c.end] for c in kept) + buf[arr.end:], True


class GmError(Exception):
    """路径不对 / 越界 / 类型不符之类「用户输入问题」，只报一句话，不甩 Traceback。"""


def _preview(node):
    """给图形界面用的单值预览。"""
    if node.kind in ('array', 'map', 'object'):
        return '%s[%d]' % (node.kind, len(node.children))
    v = node.value
    if isinstance(v, bytes):
        return '<%d 字节>' % len(v)
    if isinstance(v, str) and len(v) > 200:
        return v[:200] + '…'
    if isinstance(v, (list, tuple)):
        return '<%s %d 项>' % (type(v).__name__, len(v))
    return v


def _parents(path):
    """面包屑：'1162.4' -> [['根', ''], ['1162', '1162'], ['4', '1162.4']]。"""
    out = [['根', '']]
    if not path:
        return out
    parts = str(path).split('.')
    for i in range(len(parts)):
        out.append([parts[i], '.'.join(parts[:i + 1])])
    return out


def _rows(node, base='', limit=200):
    """把容器的直接子项摊成表格行；容器行只给摘要，点进去再展开。"""
    rows = []
    if node.kind == 'array':
        for i, c in enumerate(node.children[:limit]):
            p = ('%s.%d' % (base, i)) if base else str(i)
            rows.append({'path': p, 'kind': c.kind, 'value': _preview(c),
                         'leaf': c.kind not in ('array', 'map')})
    elif node.kind == 'map':
        for k, v in node.children[:limit]:
            key = k.value
            p = ('%s.%s' % (base, key)) if base else str(key)
            rows.append({'path': p, 'kind': v.kind, 'value': _preview(v),
                         'leaf': v.kind not in ('array', 'map')})
    else:
        rows.append({'path': base or '?', 'kind': node.kind, 'value': _preview(node), 'leaf': True})
    return rows


def mp_dump(node, indent=0, limit=40):
    pad = '  ' * indent
    if node.kind == 'array':
        print(f"{pad}array[{len(node.children)}] @{node.start}")
        for i, c in enumerate(node.children[:limit]):
            if c.kind in ('array', 'map'):
                print(f"{pad}  [{i}]")
                mp_dump(c, indent + 2, limit)
            else:
                print(f"{pad}  [{i}] {c.kind} {c.value!r}")
        if len(node.children) > limit:
            print(f"{pad}  ... 共 {len(node.children)} 项")
    elif node.kind == 'map':
        print(f"{pad}map[{len(node.children)}] @{node.start}")
        for k, v in node.children[:limit]:
            print(f"{pad}  {k.value!r}: {v.value!r}")
    else:
        print(f"{pad}{node.kind} {node.value!r}")


# ---------------------------------------------------------------- JSON 层
# 纯文本 JSON（很多 Unity 游戏把存档存成 JSON，甚至带 __type 标记）也用「记跨度、
# 字节拼接」的方式改，绝不重新序列化整个文件——重排键序/缩进会让游戏读不动。
class JNode:
    __slots__ = ('kind', 'value', 'children', 'start', 'end',
                 'key', 'key_start', 'key_end', 'closed')

    def __init__(self, kind, start, end, value=None, children=None):
        self.kind = kind
        self.value = value
        self.children = children if children is not None else []
        self.start = start
        self.end = end
        self.key = None
        self.key_start = None
        self.key_end = None
        self.closed = False

    def __repr__(self):
        return '<JNode %s %r>' % (self.kind, self.value)


_JWS = b' \t\r\n'


def _jws(b, i):
    n = len(b)
    while i < n and b[i] in _JWS:
        i += 1
    return i


def _jstr(b, i):
    """i 指向开引号，返回 (解码后的字符串, 结束位置)。"""
    n = len(b)
    j = i + 1
    out = bytearray()
    esc = {0x6e: b'\n', 0x74: b'\t', 0x72: b'\r', 0x62: b'\b', 0x66: b'\f',
           0x2f: b'/', 0x5c: b'\\', 0x22: b'\x22'}
    while j < n:
        c = b[j]
        if c == 0x5c:
            e = b[j + 1] if j + 1 < n else 0
            if e == 0x75 and j + 5 < n:
                try:
                    out += chr(int(b[j + 2:j + 6], 16)).encode('utf-8')
                except Exception:
                    out += b[j:j + 6]
                j += 6
                continue
            out += esc.get(e, bytes([e]) if e else b'')
            j += 2
            continue
        if c == 0x22:
            return out.decode('utf-8', 'replace'), j + 1
        out.append(c)
        j += 1
    raise ValueError('字符串没有闭合')


def _jvalue(b, i):
    i = _jws(b, i)
    n = len(b)
    if i >= n:
        raise ValueError('提前结束')
    c = b[i]
    if c == 0x7b:
        return _jobject(b, i)
    if c == 0x5b:
        return _jarray(b, i)
    if c == 0x22:
        v, j = _jstr(b, i)
        return JNode('str', i, j, v)
    j = i
    while j < n and b[j] not in b' \t\r\n,}]':
        j += 1
    if j == i:
        raise ValueError('空 token')
    tok = b[i:j]
    low = tok.lower()
    if low in (b'true', b'false'):
        return JNode('bool', i, j, low == b'true')
    if low == b'null':
        return JNode('null', i, j, None)
    try:
        if b'.' in tok or b'e' in low:
            return JNode('float', i, j, float(tok))
        return JNode('int', i, j, int(tok))
    except Exception:
        return JNode('raw', i, j, tok.decode('utf-8', 'replace'))


def _jobject(b, i):
    n = len(b)
    start = i
    i += 1
    kids = []
    got_close = False
    while True:
        i = _jws(b, i)
        if i >= n:
            break
        c = b[i]
        if c == 0x7d:
            i += 1
            got_close = True
            break
        if c == 0x2c:
            i += 1
            continue
        if c == 0x22:
            ks = i
            try:
                key, j = _jstr(b, i)
            except ValueError:
                i += 1
                continue
            k = _jws(b, j)
            if k < n and b[k] == 0x3a:
                try:
                    v = _jvalue(b, k + 1)
                except ValueError:
                    i = k + 1
                    continue
                v.key = key
                v.key_start = ks
                v.key_end = j
                kids.append(v)
                i = v.end
                continue
            # "key" 后面没有冒号：当成一个普通字符串成员留着
            nd = JNode('str', ks, j, key)
            kids.append(nd)
            i = j
            continue
        # 没有 key 的裸值（畸形存档里很常见，比如 {"__type" : "int"0}）
        try:
            v = _jvalue(b, i)
        except ValueError:
            i += 1
            continue
        kids.append(v)
        i = max(v.end, i + 1)
    node = JNode('object', start, i, None, kids)
    node.closed = got_close
    return node


def _jarray(b, i):
    n = len(b)
    start = i
    i += 1
    kids = []
    got_close = False
    while True:
        i = _jws(b, i)
        if i >= n:
            break
        c = b[i]
        if c == 0x5d:
            i += 1
            got_close = True
            break
        if c == 0x2c:
            i += 1
            continue
        try:
            v = _jvalue(b, i)
        except ValueError:
            i += 1
            continue
        kids.append(v)
        i = max(v.end, i + 1)
    node = JNode('array', start, i, None, kids)
    node.closed = got_close
    return node


def _try_json(data):
    """容忍式解析：返回 (root, 是否吃完整段) 或 (None, False)。"""
    if data.startswith(b'\xef\xbb\xbf'):
        data = data[3:]
    i = _jws(data, 0)
    if i >= len(data) or data[i] not in (0x7b, 0x5b):
        return None, False
    try:
        root = _jvalue(data, i)
    except Exception:
        return None, False
    tail = len(data)
    while tail > root.end and data[tail - 1] in _JWS:
        tail -= 1
    return root, bool(root.closed) and root.end == tail


def j_get(node, path):
    cur = node
    for seg in path:
        if cur.kind == 'array':
            try:
                idx = int(seg)
            except (TypeError, ValueError):
                raise GmError('这一层是数组，下标要用整数（例如 Arr.0），收到 %r' % (seg,))
            if idx < 0 or idx >= len(cur.children):
                raise GmError('数组下标越界: %s（共 %d 项）' % (idx, len(cur.children)))
            cur = cur.children[idx]
        elif cur.kind == 'object':
            hit = None
            for c in cur.children:
                if c.key == seg:
                    # 重复键：按「后出现的生效」语义（和 Unity/Most JSON 解析器一致）
                    hit = c
            if hit is None:
                raise GmError('找不到键: %r（用 dump 看看有哪些字段）' % (seg,))
            cur = hit
        else:
            raise GmError('路径 %r 走不到底：%s 不是容器' % (seg, cur.kind))
    return cur


def j_encode(value):
    if isinstance(value, bool):
        return b'true' if value else b'false'
    if value is None:
        return b'null'
    if isinstance(value, int):
        return str(value).encode()
    if isinstance(value, float):
        return repr(value).encode()
    return json.dumps(value, ensure_ascii=False).encode('utf-8')


def j_value_for(kind, text):
    t = text.strip()
    low = t.lower()
    if kind == 'bool':
        if low not in ('true', 'false', '1', '0', 'yes', 'no', 'on', 'off'):
            raise GmError('bool 字段只接受 true/false/1/0/yes/no/on/off，收到 %r' % text)
        return low in ('true', '1', 'yes', 'on')
    if kind == 'float':
        v = float(t)
        if v != v or v in (float('inf'), float('-inf')):
            raise GmError('浮点数不接受 inf/nan，收到 %r' % text)
        return v
    if kind == 'int':
        try:
            return int(t, 0)
        except ValueError:
            raise GmError('整数字段只接受整数，收到 %r' % text)
    if kind == 'null':
        if low in ('null', 'none'):
            return None
        # 允许把 null 改造成别的类型（否则 null 字段永远被写成字符串）
        return j_guess_value(text)
    if kind == 'object' or kind == 'array':
        return json.loads(t)
    if kind == 'str':
        return text
    return t


def j_guess_value(text):
    t = text.strip()
    low = t.lower()
    if low in ('true', 'false'):
        return low == 'true'
    if low in ('null', 'none'):
        return None
    try:
        return int(t, 0)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        return t


def j_set(buf, node, value):
    return buf[:node.start] + j_encode(value) + buf[node.end:]


def _child_indent(buf, node):
    """取该节点所在行的前导空白，用于新增元素时对齐缩进。"""
    pos = node.key_start if node.key_start is not None else node.start
    nl = buf.rfind(b'\n', 0, pos)
    if nl < 0:
        return b''
    seg = buf[nl + 1:pos]
    j = 0
    while j < len(seg) and seg[j] in (0x20, 0x09):
        j += 1
    return seg[:j]


def _nl_of(buf, near):
    return b'\r\n' if b'\r\n' in buf[max(0, near - 200):near + 200] else b'\n'


def j_add(buf, arr, value):
    """数组追加一个元素（沿用原文件的换行与缩进风格）。"""
    enc = j_encode(value)
    if arr.children:
        last = arr.children[-1]
        ind = _child_indent(buf, last)
        ins = b',' + _nl_of(buf, last.end) + ind + enc
        return buf[:last.end] + ins + buf[last.end:]
    gap = buf[arr.start + 1:arr.end - 1]
    return buf[:arr.start + 1] + gap + enc + buf[arr.end - 1:]


def j_add_member(buf, obj, key, value):
    kenc = json.dumps(key, ensure_ascii=False).encode('utf-8')
    body = kenc + b' : ' + j_encode(value)
    if obj.children:
        last = obj.children[-1]
        ind = _child_indent(buf, last)
        ins = b',' + _nl_of(buf, last.end) + ind + body
        return buf[:last.end] + ins + buf[last.end:]
    gap = buf[obj.start + 1:obj.end - 1]
    return buf[:obj.start + 1] + gap + body + buf[obj.end - 1:]


def j_remove(buf, parent, node):
    kids = parent.children
    idx = kids.index(node)
    if parent.kind == 'array':
        if len(kids) == 1:
            return buf[:node.start] + buf[node.end:]
        if idx + 1 < len(kids):
            return buf[:node.start] + buf[kids[idx + 1].start:]
        return buf[:kids[idx - 1].end] + buf[node.end:]
    ks = node.key_start if node.key_start is not None else node.start
    if len(kids) == 1:
        return buf[:ks] + buf[node.end:]
    if idx + 1 < len(kids):
        nxt = kids[idx + 1]
        ns = nxt.key_start if nxt.key_start is not None else nxt.start
        return buf[:ks] + buf[ns:]
    prev = kids[idx - 1]
    return buf[:prev.end] + buf[node.end:]


def j_dump(node, indent=0, limit=40):
    pad = '  ' * indent
    if node.kind in ('object', 'array'):
        print('%s%s[%d] @%d' % (pad, node.kind, len(node.children), node.start))
        for i, c in enumerate(node.children[:limit]):
            name = c.key if c.key is not None else '#%d' % i
            if c.kind in ('object', 'array'):
                print('%s  %s:' % (pad, name))
                j_dump(c, indent + 2, limit)
            else:
                print('%s  %s = %s %r' % (pad, name, c.kind, c.value))
        if len(node.children) > limit:
            print('%s  ... 共 %d 项' % (pad, len(node.children)))
    else:
        print('%s%s %r' % (pad, node.kind, node.value))


def _rows_json(node, base='', limit=200):
    rows = []
    if node.kind in ('object', 'array'):
        for i, c in enumerate(node.children[:limit]):
            if node.kind == 'array':
                seg = str(i)
            else:
                seg = c.key if c.key is not None else '#%d' % i
            p = ('%s.%s' % (base, seg)) if base else seg
            rows.append({'path': p, 'kind': c.kind, 'value': _preview(c),
                         'leaf': c.kind not in ('object', 'array')})
    else:
        rows.append({'path': base or '?', 'kind': node.kind,
                     'value': _preview(node), 'leaf': True})
    return rows


def _parse_json_path(s):
    return tuple(x for x in str(s).split('.') if x != '')


# ---------------------------------------------------------------- 格式探测层
def _try_msgpack(data):
    try:
        root = mp_decode(data)
    except Exception:
        return None
    if root.end != len(data):
        return None
    return root


def _lz4_block_array(root, data):
    """Cysharp Lz4BlockArray: array[1+N]，[0] 是 ext(98)，payload 是块长度列表。"""
    try:
        if root.kind != 'array' or not root.children:
            return None, None
        first = root.children[0]
        if first.kind != 'ext' or first.value[0] != 98:
            return None, None
        import lz4.block
        sizes, i = [], 0
        payload = first.value[1]
        while i < len(payload):
            nd = mp_decode(payload, i)
            sizes.append(nd.value)
            i = nd.end
        out = b''
        idx = 1
        for n in sizes:
            block = root.children[idx].value
            idx += 1
            out += lz4.block.decompress(block, uncompressed_size=n)
        return out, sizes
    except Exception:
        return None, None


def _aes_candidates(data):
    """找 (header, keylen, ivlen)：满足 (size-header-key-iv) % 16 == 0 且首字节小。"""
    cands = []
    for hdr in range(0, 33):
        for keylen, ivlen in ((16, 16), (32, 16), (16, 0), (32, 0)):
            body = len(data) - hdr - keylen - ivlen
            if body <= 0 or body % 16:
                continue
            cands.append((hdr, keylen, ivlen))
    return cands


def _try_aes(data, hdr, keylen, ivlen):
    try:
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import unpad
    except Exception:
        return None
    key = data[hdr:hdr + keylen]
    iv = data[hdr + keylen:hdr + keylen + ivlen] if ivlen else b'\x00' * 16
    ct = data[hdr + keylen + ivlen:]
    try:
        pt = AES.new(key, AES.MODE_CBC, iv).decrypt(ct)
        return unpad(pt, 16)
    except Exception:
        return None


def _pack_blocks(data, block=1 << 20):
    import lz4.block
    blocks, sizes = [], []
    for i in range(0, len(data), block):
        chunk = data[i:i + block]
        comp = lz4.block.compress(chunk, store_size=False)
        blocks.append(comp)
        sizes.append(len(chunk))
    ext = b''.join(mp_encode_int(n) for n in sizes)
    out = bytearray()
    out.append(0x90 | min(len(blocks) + 1, 15))
    if len(blocks) + 1 > 15:
        out = bytearray(b'\xdc' + struct.pack('>H', len(blocks) + 1))
    out += b'\xc7' + bytes([len(ext)]) + b'\x62' + ext
    for comp in blocks:
        if len(comp) <= 0xff:
            out += b'\xc4' + bytes([len(comp)]) + comp
        elif len(comp) <= 0xffff:
            out += b'\xc5' + struct.pack('>H', len(comp)) + comp
        else:
            out += b'\xc6' + struct.pack('>I', len(comp)) + comp
    return bytes(out)


def load_layers(path, verbose=False):
    """返回 (msgpack 字节, rewrap(bytes)->文件字节, 说明列表)。自动穿透 AES 与 LZ4BlockArray。"""
    data = open(path, 'rb').read()
    notes = []
    cipher = None
    bom = b''
    if data.startswith(b'\xef\xbb\xbf'):
        # BOM 必须先剥掉再解析，否则所有节点的 start/end 都会偏 3 字节；
        # 写回时由 rewrap 负责补回去。
        bom = data[:3]
        data = data[3:]

    root = _try_msgpack(data)
    if root is not None:
        notes.append('明文 MessagePack')
        plain = data
    else:
        jroot, jfull = _try_json(data)
        if jroot is not None:
            notes.append('明文 JSON' + ('' if jfull else '（含畸形片段，已容忍解析）'))
            if verbose:
                print('  ' + '\n  '.join(notes))
            return data, (lambda b: bom + b), 'json'
        plain = None
        for hdr, keylen, ivlen in _aes_candidates(data):
            pt = _try_aes(data, hdr, keylen, ivlen)
            if pt is None:
                continue
            if _try_msgpack(pt) is not None or _try_json(pt)[0] is not None \
                    or _lz4_block_array(_try_msgpack(pt) or mp_decode(b'\x90'), pt)[0]:
                plain = pt
                cipher = (hdr, keylen, ivlen)
                notes.append(f'AES-{keylen * 8}-CBC  头={hdr}字节({data[:hdr].hex()}) salt={keylen} iv={ivlen}')
                break
        if plain is None:
            head = data[:8]
            hint = ''
            if head[:1] in (0x7b, 0x5b):
                hint = '（开头像 JSON，但解析失败；用 probe --hexlen 64 看一段原文）'
            raise SystemExit('无法识别：明文 MessagePack / 明文 JSON / AES 布局 都不匹配' + hint)
    if cipher is None and _try_msgpack(plain) is None and _try_json(plain)[0] is None:
        raise SystemExit('解密后仍不是 MessagePack 也不是 JSON')

    wrapped_lz4 = False
    root = _try_msgpack(plain)
    if root is not None and root.kind == 'array' and root.children and root.children[0].kind == 'ext' \
            and root.children[0].value[0] == 98:
        inner, sizes = _lz4_block_array(root, plain)
        wrapped_lz4 = inner is not None
        if inner is not None:
            notes.append(f'LZ4BlockArray  {len(sizes)} 块 / 共 {sum(sizes)} 字节')
            plain = inner

    if _try_msgpack(plain) is None:
        jroot, jfull = _try_json(plain)
        if jroot is not None:
            notes.append('明文 JSON' + ('' if jfull else '（含畸形片段，已容忍解析）'))
            if verbose:
                print('  ' + '\n  '.join(notes))
            return plain, (lambda b: bom + b), 'json'

    def rewrap(mp_bytes):
        # 原始就是「未压缩的明文 MessagePack」时原样写回，别擅自套一层 LZ4BlockArray
        if not wrapped_lz4:
            return mp_bytes
        body = _pack_blocks(mp_bytes)
        if cipher is None:
            return body
        hdr, keylen, ivlen = cipher
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import pad
        key = os.urandom(keylen)
        iv = os.urandom(ivlen) if ivlen else b''
        ct = AES.new(key, AES.MODE_CBC, iv or b'\x00' * 16).encrypt(pad(body, 16))
        return bom + data[:hdr] + key + iv + ct

    if verbose:
        print('  ' + '\n  '.join(notes))
    return plain, rewrap, 'msgpack'


def cmd_probe(args):
    data = open(args.file, 'rb').read()
    print(f"文件: {args.file}")
    print(f"大小: {len(data)} 字节")
    print(f"开头: {data[:args.hexlen].hex(' ')}")
    cur = data
    tag = '原始'
    for level in range(args.depth):
        if cur[:2] == b'\x1f\x8b':
            import gzip
            cur = gzip.decompress(cur); tag = 'gzip'; print(f"[{level}] gzip 解压 -> {len(cur)}")
            continue
        if cur[:2] in (b'\x78\x9c', b'\x78\xda', b'\x78\x01'):
            import zlib
            cur = zlib.decompress(cur); tag = 'zlib'; print(f"[{level}] zlib 解压 -> {len(cur)}")
            continue
        if cur[:4] == b'\x04\x22\x4d\x18':
            import lz4.frame
            cur = lz4.frame.decompress(cur); print(f"[{level}] lz4 frame 解压 -> {len(cur)}")
            continue
        if cur[:4] == b'\x28\xb5\x2f\xfd':
            import zstandard
            cur = zstandard.ZstdDecompressor().decompress(cur); print(f"[{level}] zstd 解压 -> {len(cur)}")
            continue
        root = _try_msgpack(cur)
        if root is not None:
            if root.kind == 'array' and root.children and root.children[0].kind == 'ext' and root.children[0].value[0] == 98:
                inner, sizes = _lz4_block_array(root, cur)
                print(f"[{level}] MessagePack LZ4BlockArray: {len(sizes)} 块 {sizes} (每块压缩后 {[c.end - c.start for c in root.children[1:]]})")
                if inner is None:
                    print("        (解压失败，可能缺少 lz4 库)")
                    return 0
                cur = inner
                continue
            print(f"[{level}] MessagePack 根: {root.kind} 长度={len(root.children) if root.children is not None else '?'}  ({len(cur)} 字节, 全消耗={root.end == len(cur)})")
            print("        -> 这就是最终数据，可用 save 子命令读写")
            return 0
        hit = None
        for hdr, keylen, ivlen in _aes_candidates(cur):
            pt = _try_aes(cur, hdr, keylen, ivlen)
            if pt is None:
                continue
            if _try_msgpack(pt) is not None or _try_json(pt)[0] is not None \
                    or _lz4_block_array(_try_msgpack(pt) or mp_decode(b'\x90'), pt)[0]:
                hit = (hdr, keylen, ivlen, pt)
                break
        if hit:
            hdr, keylen, ivlen, pt = hit
            print(f"[{level}] AES-{keylen * 8}-CBC: 头={hdr} 字节 {cur[:hdr].hex(' ')} | salt {keylen} | iv {ivlen} | 密文 {(len(cur) - hdr - keylen - ivlen)} = {(len(cur) - hdr - keylen - ivlen) // 16}*16")
            print(f"        解开 -> {len(pt)} 字节")
            cur = pt
            continue
        jroot, jfull = _try_json(cur)
        if jroot is not None:
            print(f"[{level}] JSON 根: {jroot.kind} 子项={len(jroot.children) if jroot.children is not None else '?'}  ({len(cur)} 字节, 全消耗={jfull})")
            if not jfull:
                print("        注意：含畸形片段（如缺逗号），按容忍模式解析；改动只替换目标字节，其余原样保留")
            print("        -> 这就是最终数据，可直接用 save 子命令读写（无需解密）")
            return 0
        print(f"[{level}] 未识别的层，开头 {cur[:16].hex(' ')}")
        break
    return 0


# ---------------------------------------------------------------- 自检 / 模糊测试
def _fuzz_value(rng, depth=0):
    kinds = ['int', 'float', 'str', 'bool', 'null'] + (['dict', 'list'] if depth < 3 else [])
    k = rng.choice(kinds)
    if k == 'int':
        return rng.choice([0, 1, -1, 42, 999999, -7777, 2 ** 31 - 1])
    if k == 'float':
        return rng.choice([0.5, -1.25, 3.14159, 1e9, -0.0])
    if k == 'str':
        return rng.choice(['', 'x', '中文', 'a b ', 'quote\"in', 'tab\tx', '😀', 'line\nbreak'])
    if k == 'bool':
        return rng.choice([True, False])
    if k == 'null':
        return None
    if k == 'list':
        return [_fuzz_value(rng, depth + 1) for _ in range(rng.randint(0, 4))]
    return {rng.choice(['a', 'b', 'k1', 'k2', '中文键']): _fuzz_value(rng, depth + 1)
            for _ in range(rng.randint(0, 4))}


def _fuzz_doc(rng):
    """随机生成风格各异的 JSON 文本（含 BOM / CRLF / 无缩进 / 尾垃圾），返回 bytes。"""
    doc = _fuzz_value(rng)
    if not isinstance(doc, (dict, list)):
        doc = {'root': doc}
    indent = rng.choice([None, '', '\t', '  ', '    '])
    seps = rng.choice([(',', ':'), (', ', ': '), (',', ': ')])
    text = json.dumps(doc, ensure_ascii=rng.choice([True, False]), indent=indent, separators=seps)
    nl = rng.choice(['\n', '\r\n'])
    text = text.replace('\n', nl)
    if rng.random() < 0.3:
        text = text.rstrip() + rng.choice(['', nl])
    if rng.random() < 0.2:
        text = text.rstrip() + rng.choice(['xyz', '  ', nl + ' '])
    data = text.encode('utf-8')
    if rng.random() < 0.25:
        data = b'\xef\xbb\xbf' + data
    return data


def _collect_paths(node, base, out):
    if node.kind in ('object', 'array') and node.children:
        out.append((base, node))
        for c, ch in enumerate(node.children):
            if node.kind == 'array':
                _collect_paths(ch, base + (str(c),), out)
            elif ch.key is not None:
                _collect_paths(ch, base + (ch.key,), out)
    else:
        out.append((base, node))


def cmd_fuzz(args):
    import random
    rng = random.Random(args.seed)
    ok_n = caught_n = skipped = 0
    fails = []
    corpus = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir,
                          'test', 'corpus')
    os.makedirs(corpus, exist_ok=True)
    for i in range(args.n):
        data = _fuzz_doc(rng)
        if data.startswith(b'\xef\xbb\xbf'):
            data = data[3:]          # 和 load_layers 一致：BOM 由外层负责，解析只看正文
        root, full = _try_json(data)
        if root is None:
            skipped += 1
            continue
        paths = []
        _collect_paths(root, (), paths)
        if not paths:
            skipped += 1
            continue
        path, node = rng.choice(paths)
        if not path:
            skipped += 1
            continue
        try:
            if node.kind == 'array':
                new = j_add(data, node, _fuzz_value(rng, 3))
                op = 'add'
            elif node.kind == 'object':
                new = j_add_member(data, node, 'zz', _fuzz_value(rng, 3))
                op = 'add'
            else:
                if node.kind == 'bool':
                    val = rng.choice([True, False])
                elif node.kind == 'int':
                    val = rng.randint(-1000, 1000)
                elif node.kind == 'float':
                    val = rng.choice([1.5, -2.25])
                elif node.kind == 'null':
                    val = None
                else:
                    val = 'v' + str(rng.randint(0, 99))
                new = j_set(data, node, val)
                op = 'set'
        except Exception as exc:
            fails.append((i, '改写出错: %s' % exc, data))
            continue
        if new == data:
            skipped += 1
            continue
        problems = assert_edit('json', data, new, (node.start, node.end), op, path, None)
        if problems:
            fails.append((i, '; '.join(problems), data))
            continue
        ok_n += 1
        # 反向测试：把目标区间之外的一个字节改掉，检查器必须报警
        grown = node.end + max(0, len(new) - len(data))
        outside = [p for p in range(len(new)) if not (node.start <= p < grown)]
        if len(new) > 2 and outside:
            pos = rng.choice(outside)
            mutated = bytes(new[:pos]) + bytes([(new[pos] ^ 0xFF)]) + bytes(new[pos + 1:])
            if not assert_edit('json', data, mutated, (node.start, node.end), op, path, None):
                fails.append((i, '检查器漏报：改动落在目标区间外却没被抓住', data))
                continue
            caught_n += 1
        else:
            skipped += 1
    for idx, why, data in fails[:5]:
        fn = os.path.join(corpus, 'fuzz-%s-%d.json' % (args.seed, idx))
        with open(fn, 'wb') as f:
            f.write(data)
        print('失败 #%d: %s\n  复现用例 -> %s' % (idx, why, fn))
    print('模糊测试: %d 轮, 通过 %d, 反向抓漏 %d, 跳过 %d, 失败 %d'
          % (args.n, ok_n, caught_n, skipped, len(fails)))
    return 0 if not fails else 7


# ---------------------------------------------------------------- 存档读写
def _parse_path(s):
    return tuple(int(x) if x.lstrip('-').isdigit() else x for x in s.split('.'))


# ------------------------------------------------------- 写操作不变量（L1）
def _diff_span(a, b):
    """返回 (公共前缀长度, a 侧结束, b 侧结束)。"""
    n = min(len(a), len(b))
    lo = 0
    while lo < n and a[lo] == b[lo]:
        lo += 1
    i, j = len(a), len(b)
    while i > lo and j > lo and a[i - 1] == b[j - 1]:
        i -= 1
        j -= 1
    return lo, i, j


def _deep_mask(x, y, target, cur, out):
    """逐路径比较 x/y；target 路径下的差异被允许。"""
    if len(cur) == len(target) and all(str(a) == str(b) for a, b in zip(cur, target)):
        return
    if type(x) is not type(y):
        out.append(('%s' % '.'.join(map(str, cur)), '类型 %s -> %s' % (type(x).__name__, type(y).__name__)))
        return
    if isinstance(x, dict):
        for k in sorted(set(x) - set(y)):
            out.append(('%s.%s' % ('.'.join(map(str, cur)), k), '字段丢失'))
        for k in sorted(set(y) - set(x)):
            out.append(('%s.%s' % ('.'.join(map(str, cur)), k), '多出字段'))
        for k in set(x) & set(y):
            _deep_mask(x[k], y[k], target, cur + (k,), out)
    elif isinstance(x, list):
        if len(x) != len(y):
            out.append(('.'.join(map(str, cur)), '长度 %d -> %d' % (len(x), len(y))))
            return
        for i in range(len(x)):
            _deep_mask(x[i], y[i], target, cur + (str(i),), out)
    elif x != y:
        out.append(('.'.join(map(str, cur)), '%r -> %r' % (x, y)))


def _ref_decode(kind, data):
    """用与 gmtool 无关的第三方解析器解码，拿不到时返回 (None, 原因)。"""
    if kind == 'json':
        try:
            return json.loads(data.decode('utf-8')), None
        except Exception as exc:
            return None, '参考解析失败：%s' % exc
    try:
        import msgpack as _mp
    except Exception:
        return None, '缺少 msgpack 参考解码器'
    try:
        return _mp.unpackb(data, strict_map_key=False), None
    except Exception as exc:
        return None, '参考解析失败：%s' % exc


_NO_MASK = ('\x00__never__',)


def _dig(doc, path):
    cur = doc
    for seg in path:
        if isinstance(cur, list):
            cur = cur[int(seg)]
        else:
            cur = cur[seg]
    return cur


def _canon(x):
    """把值折成可严格比较的规范形（类型敏感：bool≠int、-0.0≠0.0）。"""
    if isinstance(x, bool):
        return ('b', x)
    if isinstance(x, float):
        return ('f', repr(x))
    if isinstance(x, int):
        return ('i', str(x))
    if isinstance(x, str):
        return ('s', x)
    if x is None:
        return ('z',)
    if isinstance(x, list):
        return ('l', tuple(_canon(i) for i in x))
    if isinstance(x, dict):
        return ('d', tuple(sorted((str(k), _canon(v)) for k, v in x.items())))
    return ('o', repr(x))


def _eq(x, y):
    if isinstance(x, bool) or isinstance(y, bool):
        return x is y
    if isinstance(x, (int, float)) and isinstance(y, (int, float)):
        return float(x) == float(y)
    return x == y


def _norm_pair(a, b, path, op):
    """把 add/remove 造成的长度差异抹平，使两份文档可以直接整体比对。"""
    if not path:
        raise ValueError('不能改根节点')
    # add 的 path 指向容器本身；remove 的 path 指向被删元素
    cup = list(path) if op == 'add' else list(path[:-1])
    pa = _dig(a, cup)
    pb = _dig(b, cup)
    if op == 'add':
        if isinstance(pb, list) and isinstance(pa, list) and len(pb) == len(pa) + 1:
            for i in range(len(pb)):
                if _canon(pb[:i] + pb[i + 1:]) == _canon(pa):
                    del pb[i]
                    return a, b
            raise ValueError('新增项的插入位置改变了其余元素顺序')
        if isinstance(pb, dict) and isinstance(pa, dict) and len(pb) == len(pa) + 1:
            extra = [k for k in pb if k not in pa]
            if len(extra) != 1:
                raise ValueError('新增了不止一个字段：%r' % extra)
            del pb[extra[0]]
            return a, b
        raise ValueError('add 之后容器形状不符（%s -> %s）' % (type(pa).__name__, type(pb).__name__))
    if isinstance(pa, list) and isinstance(pb, list) and len(pa) == len(pb) + 1:
        for i in range(len(pa)):
            if _canon(pa[:i] + pa[i + 1:]) == _canon(pb):
                del pa[i]
                return a, b
        raise ValueError('删除项改变了其余元素顺序')
    if isinstance(pa, dict) and isinstance(pb, dict) and len(pa) == len(pb) + 1:
        gone = [k for k in pa if k not in pb]
        if len(gone) != 1:
            raise ValueError('删掉了不止一个字段：%r' % gone)
        del pa[gone[0]]
        return a, b
    raise ValueError('remove 之后容器形状不符（%s -> %s）' % (type(pa).__name__, type(pb).__name__))


def _json_value(node):
    """把容忍解析出来的 JNode 转成 Python 值（重复键按“后者生效”）。"""
    if node.kind == 'object':
        out = {}
        for c in node.children:
            if c.key is not None:
                out[c.key] = _json_value(c)
        return out
    if node.kind == 'array':
        return [_json_value(c) for c in node.children]
    return node.value


def _ref_check(kind, before, after, op, path, expect_value):
    """独立语义比对：除目标结点外整篇文档必须一致。返回 (True/False/None, 说明)。"""
    a, msg_a = _ref_decode(kind, before)
    strict = a is not None
    if not strict:
        # 严格解析器读不了（原文件本身带畸形/尾垃圾）→ 退回本工具的容忍解析做结构比对
        ra, _ = _try_json(before)
        if ra is None:
            return None, msg_a
        a = _json_value(ra)
        b = None
    else:
        b, msg_b = _ref_decode(kind, after)
    if b is None:
        rb, _ = _try_json(after)
        if rb is None:
            return False, '写后的文件无法被解析'
        b = _json_value(rb)
    elif not strict:
        pass
    if op in ('add', 'remove'):
        try:
            a, b = _norm_pair(a, b, list(path), op)
        except ValueError as exc:
            return False, str(exc)
        diffs = []
        _deep_mask(a, b, _NO_MASK, (), diffs)
    else:
        diffs = []
        _deep_mask(a, b, tuple(path), (), diffs)  # 路径元素可能是 int（msgpack）或 str（JSON）
        if expect_value is not None:
            try:
                got = _dig(b, list(path))
            except Exception:
                return False, '目标路径在写后文档里取不到'
            if not _eq(got, expect_value) and repr(got) != repr(expect_value):
                return False, '目标值写成了 %r，期望 %r' % (got, expect_value)
    if diffs:
        head = '；'.join('%s: %s' % (q or '<根>', m) for q, m in diffs[:4])
        return False, '目标之外的字段也变了 -> ' + head
    return True, ''


def _same_val(a, b):
    """落盘复核用的值比较：类型敏感（bool 不等于 1），int/float 互等。"""
    try:
        return _canon(a) == _canon(b)
    except Exception:
        return a == b


def assert_edit(kind, before, after, allowed, op, path, expect_value):
    """写操作必须满足：差异落在目标区间内 + 目标之外语义不变。返回问题列表（空=通过）。"""
    # 新旧字节完全一样时没有「差异区间」可校验，_diff_span 会给出退化区间，
    # 后面几条检查必然误报（原文件侧/新文件侧差异终点超出目标区间）。
    # 这种情况本来就是空操作，直接放行；真正要告诉用户「没改动」由调用方负责。
    if before == after:
        return []
    problems = []
    lo, hi_a, hi_b = _diff_span(before, after)
    a0, a1 = allowed
    delta = len(after) - len(before)      # 可为负（删减）
    grew = max(0, delta)
    if lo < a0:
        problems.append('差异起点 %d 早于目标区间起点 %d' % (lo, a0))
    if hi_a > a1:
        problems.append('原文件侧差异终点 %d 超出目标区间终点 %d' % (hi_a, a1))
    if hi_b > max(a1, a1 + delta):
        problems.append('新文件侧差异终点 %d 超出目标区间终点 %d' % (hi_b, max(a1, a1 + delta)))
    # 目标节点之前 / 之后的字节必须原样保留（这一条能抓到“改到文件末尾垃圾区”这类情况）
    if before[:a0] != after[:a0]:
        problems.append('目标节点之前的字节被改动')
    if before[a1:] != after[a1 + delta:]:
        problems.append('目标节点之后的字节被改动')
    try:
        ok, msg = _ref_check(kind, before, after, op, path, expect_value)
    except Exception as exc:
        problems.append('语义比对时出错（%s: %s），为安全起见拒绝写入' % (type(exc).__name__, exc))
    else:
        if ok is False:
            problems.append(msg)
    return problems


def _atomic_write(path, data):
    """先写临时文件再原子替换：任何时刻磁盘上都是一份完整文件。"""
    import tempfile
    d = os.path.dirname(os.path.abspath(path)) or '.'
    fd, tmp = tempfile.mkstemp(dir=d, prefix='.gmtool-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def cmd_save(args):
    # 先记下「读到的那一刻」的文件状态与字节，再解析。顺序反过来的话，读→stat 之间
    # 游戏又存了一次档，基线记的就是新状态，后面复检什么都比不出来，回滚会把新档盖成旧内容。
    st0 = os.stat(args.file)
    raw0 = open(args.file, 'rb').read()
    plain, rewrap, kind = load_layers(args.file, verbose=not getattr(args, 'json', False))
    if kind == 'json':
        root = _try_json(plain)[0]
        parse_path, getter, rows, dumper = _parse_json_path, j_get, _rows_json, j_dump
    else:
        root = mp_decode(plain)
        parse_path, getter, rows, dumper = _parse_path, mp_get, _rows, mp_dump
    changed = False
    plain0 = bytes(plain)
    allowed = (0, 0)
    expect = None
    p = ()

    if args.cmd == 'dump':
        node = root if not args.path else getter(root, parse_path(args.path))
        if getattr(args, 'json', False):
            base = args.path or ''
            print(json.dumps({
                'path': base,
                'kind': node.kind,
                'value': _preview(node),
                'rows': rows(node, base, args.limit),
                'parents': _parents(base),
            }, ensure_ascii=False))
            return 0
        dumper(node, limit=args.limit)
        return 0
    if args.cmd == 'get':
        try:
            node = getter(root, parse_path(args.path))
        except (KeyError, IndexError, GmError) as exc:
            print(f'路径无效: {args.path}（{exc}）', file=sys.stderr)
            print('提示: 先用 save dump 看看这一层有哪些字段名。', file=sys.stderr)
            return 1
        if getattr(args, 'json', False):
            print(json.dumps({
                'path': args.path,
                'kind': node.kind,
                'value': _preview(node),
                'raw': node.value if node.kind in ('bool', 'int', 'float', 'str') else None,
                'bytes': [node.start, node.end],
            }, ensure_ascii=False))
            return 0
        print(f"{node.kind} {node.value!r}  bytes {node.start}:{node.end}")
        return 0

    expect = None
    if args.cmd in ('set', 'add', 'remove'):
        pstr, _, vstr = args.spec.partition('=')
        p = parse_path(pstr)
        if not p:
            raise GmError('不能直接改根节点（路径为空）：请给到具体字段，例如 set 405=54 或 .Root.a=1')
        node = getter(root, p)
        if args.cmd == 'set':
            if kind == 'json':
                v = j_value_for(node.kind, vstr)
                plain2 = j_set(plain, node, v)
            else:
                if node.kind == 'bool':
                    low = vstr.strip().lower()
                    if low not in ('true', 'false', '1', '0', 'yes', 'no', 'on', 'off'):
                        raise GmError('bool 字段只接受 true/false/1/0/yes/no/on/off，收到 %r' % vstr)
                    v = low in ('true', '1', 'yes', 'on')
                elif node.kind.startswith('float'):
                    v = float(vstr)
                elif node.kind == 'str':
                    v = vstr
                else:
                    v = int(vstr, 0)
                plain2 = mp_set(plain, node, v)
            print(f"set {pstr}: {node.value!r} -> {v!r}  ({len(plain)} -> {len(plain2)} 字节)")
            plain = plain2
            changed = True
            allowed = (node.start, node.end)
            expect = ('set', p, v)
        elif kind == 'json' and args.cmd == 'add':
            n_before = len(node.children)
            if node.kind == 'array':
                added = j_guess_value(vstr)
                plain2 = j_add(plain, node, added)
                print(f"add {pstr} += {vstr}  ({len(plain)} -> {len(plain2)} 字节)")
            elif node.kind == 'object':
                k, sep, rest = vstr.partition('=')
                if not sep:
                    raise SystemExit('给对象加字段要写成 add <路径>=键=值，例如 add .Root=NewKey=123')
                added = j_guess_value(rest)
                added_key = k.strip()
                plain2 = j_add_member(plain, node, added_key, added)
                print(f"add {pstr} += {k.strip()}  ({len(plain)} -> {len(plain2)} 字节)")
            else:
                raise SystemExit('add 只能用在数组或对象上，当前是 %s' % node.kind)
            plain = plain2
            changed = True
            allowed = (node.start, node.end)
            expect = ('add', p, added, (added_key if node.kind == 'object' else None), n_before)
        elif kind == 'json' and args.cmd == 'remove':
            parent = getter(root, p[:-1]) if p else root
            plain2 = j_remove(plain, parent, node)
            what = '成员' if (parent.kind == 'object') else '元素'
            print(f"remove {pstr}: 删掉 1 个{what}  ({len(plain)} -> {len(plain2)} 字节)")
            plain = plain2
            changed = True
            allowed = (parent.start, parent.end)
            expect = ('remove', p)
        elif args.cmd == 'add':
            plain2, ok = mp_add_int(plain, node, int(vstr, 0))
            n_before = len(node.children)
            plain = plain2
            changed = ok
            if ok:
                allowed = (node.start, node.end)
                expect = ('add', p, int(vstr, 0), None, n_before)
            print(f"{'add' if ok else '已存在'} {pstr} += {vstr}  ({n_before} -> {len(mp_get(mp_decode(plain), p).children)})")
        else:
            plain2, ok = mp_remove_int(plain, node, int(vstr, 0))
            n_before = len(node.children)
            plain = plain2
            changed = ok
            if ok:
                allowed = (node.start, node.end)
                expect = ('remove', p)
            print(f"{'remove' if ok else '未找到'} {pstr} -= {vstr}  ({n_before} -> {len(mp_get(mp_decode(plain), p).children)})")

    if not changed:
        print('没有变化')
        return 0

    # set 到「和当前值一样」时 j_set/mp_set 会照常返回新字节，但内容一模一样。
    # 这时候不该备份、不该落盘，更不该报「自检未通过」——直接说清楚没改动。
    if plain == plain0:
        print('值没有变化，没有写任何东西')
        return 0

    out = args.out or args.file
    if args.out and os.path.abspath(out) == os.path.abspath(args.file):
        raise GmError('--out 不能和输入相同')

    # ---- L1：差异必须落在目标字节区间内，且目标之外语义不变
    want = expect[2] if (expect and expect[0] == 'set') else None
    problems = assert_edit(kind, plain0, plain, allowed, args.cmd, p, want)
    if problems:
        for msg in problems:
            print('自检未通过:', msg, file=sys.stderr)
        print('已中止：原文件一个字节都没改', file=sys.stderr)
        return 5

    # 从读到写这段时间里，文件可能又被别人动过（游戏自动存档就是最常见的一种）。
    # 这时候回滚会把更晚的内容覆盖成更早的快照，所以宁可拒绝。
    st1 = os.stat(args.file)
    now = open(args.file, 'rb').read()
    if (st1.st_size, st1.st_mtime_ns) != (st0.st_size, st0.st_mtime_ns) or now != raw0:
        print('已中止：文件在读取之后被改动过（可能游戏又存了一次档），请重新执行', file=sys.stderr)
        print('原文件一个字节都没改', file=sys.stderr)
        return 5

    blob = rewrap(plain)
    # 备份与回滚都用「最初读到的那份字节」，不再重读，免得备份的不是被分析的内容。
    orig = raw0
    if not args.out and args.backup:
        import time
        bak = args.file + '.bak-%s' % time.strftime('%Y%m%d-%H%M%S')
        if os.path.exists(bak):
            i = 2
            while os.path.exists(f'{bak}-{i}'):
                i += 1
            bak = f'{bak}-{i}'
        _atomic_write(bak, orig)
        print('原文件已备份 ->', bak)

    _atomic_write(out, blob)
    print(f"已写出 {out}  ({len(blob)} 字节)")

    # ---- L2：落盘后复核，不一致就原子回滚
    ok, reason = True, ''
    try:
        back, _, kind2 = load_layers(out)
        if kind2 != kind:
            ok, reason = False, '回读的格式与写入前不同（%s -> %s）' % (kind, kind2)
        elif back != plain:
            ok, reason = False, '回读的明文字节与内存不一致'
        elif expect is not None:
            op_, path_, want_ = (list(expect) + [None])[0:3]
            root2 = _try_json(back)[0] if kind2 == 'json' else mp_decode(back)
            getter2 = j_get if kind2 == 'json' else mp_get
            if op_ == 'set':
                got = getter2(root2, path_)
                if got.value != want_:
                    ok, reason = False, '目标字段回读为 %r，期望 %r' % (got.value, want_)
            elif op_ == 'remove':
                try:
                    getter2(root2, path_)
                    ok, reason = False, '要删的项删除后仍然存在'
                except Exception:
                    ok = True
            elif op_ == 'add':
                got = getter2(root2, path_)
                kids = got.children or []
                added_key_ = expect[3] if len(expect) > 3 else None
                n_before_ = expect[4] if len(expect) > 4 else None
                if n_before_ is not None and len(kids) != n_before_ + 1:
                    ok, reason = False, '新增后容器 %d 项，期望 %d 项' % (len(kids), n_before_ + 1)
                elif added_key_ is not None:
                    hit = [c for c in kids if getattr(c, 'key', None) == added_key_]
                    if not hit:
                        ok, reason = False, '新增的键 %r 不在容器里' % (added_key_,)
                    elif not _same_val(hit[-1].value, want_):
                        ok, reason = False, '新增的键 %r 回读为 %r，期望 %r' % (added_key_, hit[-1].value, want_)
                elif not any(_same_val(getattr(c, 'value', None), want_) for c in kids):
                    ok, reason = False, '新增的值 %r 不在容器里' % (want_,)
    except Exception as exc:
        ok, reason = False, '回读异常: %s' % exc

    if not ok:
        _atomic_write(out, orig)
        print('回滚:', reason, '（已恢复原字节）', file=sys.stderr)
        return 6
    print('自检通过：差异仅在目标区间内，目标之外语义一致')
    return 0


# ---------------------------------------------------------------- .NET 层
class Asm:
    def __init__(self, path):
        import dnfile
        self.dnfile = dnfile
        self.path = path
        self.pe = dnfile.dnPE(path, fast_load=False)
        t = self.pe.net.mdtables
        self.types = list(t.TypeDef.rows)
        self.methods = list(t.MethodDef.rows)
        self.fields = list(t.Field.rows)
        self.mrefs = list(t.MemberRef.rows)
        self.mid = {id(r): i + 1 for i, r in enumerate(self.methods)}
        self.fid = {id(r): i + 1 for i, r in enumerate(self.fields)}
        self.owner_m, self.owner_f = {}, {}
        for ty in self.types:
            for m in ty.MethodList:
                self.owner_m[self.mid.get(id(m.row))] = self.tf(ty)
            for f in ty.FieldList:
                self.owner_f[self.fid.get(id(f.row))] = self.tf(ty)

    @staticmethod
    def tf(row):
        ns = str(getattr(row, 'TypeNamespace', '') or '')
        nm = str(getattr(row, 'TypeName', '') or '')
        return f"{ns}.{nm}" if ns else nm

    def body(self, mrow):
        from dncil.cil.body import CilMethodBody
        from dncil.cil.body.reader import CilMethodBodyReaderBase
        from dncil.cil.error import MethodBodyFormatError
        pe = self.pe

        class R(CilMethodBodyReaderBase):
            def __init__(self):
                self.offset = pe.get_offset_from_rva(mrow.Rva)

            def read(self, n):
                d = pe.get_data(pe.get_rva_from_offset(self.offset), n)
                self.offset += n
                return d

            def tell(self):
                return self.offset

            def seek(self, off):
                self.offset = off

        try:
            return CilMethodBody(R())
        except MethodBodyFormatError:
            return None

    def text_of(self, op):
        if op is None:
            return ''
        if not hasattr(op, 'table'):
            if type(op).__name__ == 'UserString':
                try:
                    return repr(op.value[:120])
                except Exception:
                    return 'str'
            return str(op)
        tb, rid = op.table, op.rid
        try:
            if tb == 0x06:
                return f"{self.owner_m.get(rid, '?')}::{self.methods[rid - 1].Name}"
            if tb == 0x04:
                return f"{self.owner_f.get(rid, '?')}::{self.fields[rid - 1].Name}"
            if tb == 0x0A:
                mr = self.mrefs[rid - 1]
                cls = mr.Class.row if hasattr(mr.Class, 'row') else mr.Class
                return f"{(self.tf(cls) if hasattr(cls, 'TypeName') else 'Ext')}::{mr.Name}"
            if tb == 0x01:
                return f"<TypeRef {self.mrefs[rid - 1].Name}>"
            if tb == 0x02:
                return f"<TypeDef {self.tf(self.types[rid - 1])}>"
        except Exception:
            pass
        return f"<tok 0x{tb:02X}/{rid}>"

    def find_type(self, name):
        for ty in self.types:
            full = self.tf(ty)
            if full == name or str(ty.TypeName) == name or full.endswith('.' + name):
                return ty
        return None


def cmd_dll(args):
    asm = Asm(args.dll)
    if args.cmd == 'types':
        import re
        rx = re.compile(args.pattern, re.I) if args.pattern else None
        seen = set()
        for ty in asm.types:
            full = asm.tf(ty)
            if full in seen or (rx and not rx.search(full)):
                continue
            seen.add(full)
            print(f"{full}    ({len(list(ty.MethodList))} methods)")
        return 0

    ty = asm.find_type(args.type) if getattr(args, 'type', None) else None
    if getattr(args, 'type', None) and ty is None:
        print('找不到类型:', args.type)
        return 2

    if args.cmd == 'methods':
        for m in ty.MethodList:
            print(f"  rid={asm.mid.get(id(m.row))}  {m.row.Name}")
        return 0
    if args.cmd == 'fields':
        for f in ty.FieldList:
            print(f"  rid={asm.fid.get(id(f.row))}  {f.row.Name}")
        return 0
    if args.cmd == 'dis':
        for m in ty.MethodList:
            if args.method and str(m.row.Name) != args.method:
                continue
            b = asm.body(m.row)
            if b is None:
                continue
            print(f"--- {asm.tf(ty)}::{m.row.Name} ({len(b.instructions)} insn, IL @0x{b.instructions[0].offset:X}) ---")
            for ins in b.instructions:
                print(f"  {ins.offset:06X}: {str(ins.opcode):<14}{asm.text_of(ins.operand)}")
        return 0
    if args.cmd == 'xref':
        target = args.name
        for t in asm.types:
            for m in t.MethodList:
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
                    print(f"{asm.tf(t)}::{m.row.Name}")
                    for off, op in hits:
                        print(f"    {off:06X} {op}")
        return 0
    if args.cmd == 'enum':
        cmap = {}
        for c in asm.pe.net.mdtables.Constant.rows:
            p = c.Parent
            if type(p.table).__name__ == 'Field':
                cmap[p.row_index] = c
        rows = []
        for f in ty.FieldList:
            c = cmap.get(asm.fid.get(id(f.row)))
            if c is None or str(f.row.Name) == 'value__':
                continue
            raw = c.Value.raw_data
            blob = raw[1:] if raw and raw[0] == len(raw) - 1 else raw
            if not blob or len(blob) > 8:
                continue
            rows.append((int.from_bytes(blob, 'little', signed=(blob[-1] & 0x80) != 0), str(f.row.Name)))
        for v, n in sorted(rows):
            print(f"   {v}\t{n}")
        return 0
    if args.cmd == 'patch':
        return _patch(asm, args)
    return 1


def _patch(asm, args):
    ty = asm.find_type(args.type)
    if ty is None:
        print('找不到类型:', args.type)
        return 2
    mrow = None
    for m in ty.MethodList:
        if str(m.row.Name) == args.method:
            mrow = m.row
            break
    if mrow is None:
        print('找不到方法:', args.method)
        return 2
    b = asm.body(mrow)
    if b is None:
        print('方法没有 IL 体')
        return 2
    il_start = b.instructions[0].offset
    il_end = b.instructions[-1].offset + b.instructions[-1].size
    cap = il_end - il_start
    if args.ret_false:
        new = b'\x16\x2a'
    elif args.ret_true:
        new = b'\x17\x2a'
    elif args.nop:
        new = b''
    elif args.bytes:
        new = bytes(int(x, 16) for x in args.bytes.replace(' ', '').split(','))
    else:
        print('需要 --bytes / --ret-false / --ret-true / --nop')
        return 2
    if len(new) > cap:
        print(f'新 IL {len(new)} 字节 > 原容量 {cap} 字节，等长补丁放不下')
        return 3
    payload = new + b'\x00' * (cap - len(new))
    data = bytearray(open(asm.path, 'rb').read())
    print(f"补丁 {asm.tf(ty)}::{args.method}")
    print(f"  IL 文件偏移 0x{il_start:X}..0x{il_end:X}  容量 {cap} 字节")
    print(f"  原始: {data[il_start:il_end].hex(' ')}")
    print(f"  新版: {payload.hex(' ')}   (填充 0x00 = nop)")
    data[il_start:il_end] = payload
    out = args.out or (os.path.splitext(asm.path)[0] + '.patched.dll')
    open(out, 'wb').write(data)
    print('已写出', out)
    # 回读校验
    chk = Asm(out)
    t2 = chk.find_type(args.type)
    m2 = None
    for m in t2.MethodList:
        if str(m.row.Name) == args.method:
            m2 = m.row
            break
    b2 = chk.body(m2)
    print('回读:', ' | '.join(f"{i.offset:X}:{str(i.opcode)} {chk.text_of(i.operand)}".strip() for i in b2.instructions))
    return 0



# ---------------------------------------------------------------- protobuf 层
def _pb_varint(b, i):
    """读 varint，返回 (值, 新下标)。"""
    shift = 0
    val = 0
    while True:
        if i >= len(b):
            raise ValueError('varint 截断')
        c = b[i]
        i += 1
        val |= (c & 0x7F) << shift
        shift += 7
        if not (c & 0x80):
            return val, i
        if shift > 63:
            raise ValueError('varint 过长')


def _pb_str(payload):
    """若 payload 是干净的可打印 UTF-8，返回字符串，否则 None。"""
    try:
        t = payload.decode('utf-8')
    except UnicodeDecodeError:
        return None
    if not t or any(ord(ch) < 0x20 and ch not in '\r\n\t' for ch in t):
        return None
    return t


def pb_walk(b, depth=0, path='', out=None, maxfields=64, maxdepth=6):
    """把字节流当作 protobuf 消息遍历，返回 (是否整段被完整解析, 语句列表)。

    没有 .proto schema 时也能看出结构：字段号 / 线类型 / 数值 / 内嵌字符串 /
    可继续下钻的子消息。用于 UE、gRPC、Protobuf-CSharp 之类没有元数据的存档。
    """
    out = out if out is not None else []
    i = 0
    n = 0
    while i < len(b) and n < maxfields:
        start = i
        try:
            tag, i = _pb_varint(b, i)
        except ValueError:
            return False, out
        field, wt = tag >> 3, tag & 7
        if field == 0:
            return False, out
        name = f'{path}.{field}' if path else str(field)
        if wt == 0:
            try:
                v, i = _pb_varint(b, i)
            except ValueError:
                return False, out
            out.append(f"{'  ' * depth}{name}  varint  {v}")
        elif wt == 1:
            if i + 8 > len(b):
                return False, out
            out.append(f"{'  ' * depth}{name}  fixed64  {b[i:i+8].hex()}")
            i += 8
        elif wt == 5:
            if i + 4 > len(b):
                return False, out
            out.append(f"{'  ' * depth}{name}  fixed32  {b[i:i+4].hex()}")
            i += 4
        elif wt == 2:
            try:
                ln, i = _pb_varint(b, i)
            except ValueError:
                return False, out
            if i + ln > len(b):
                return False, out
            payload = b[i:i + ln]
            i += ln
            text = _pb_str(payload)
            if text is not None and len(text) >= 1:
                shown = text if len(text) <= 60 else text[:57] + '...'
                out.append(f"{'  ' * depth}{name}  str({ln})  {shown!r}")
            else:
                sub_ok, sub_out = (False, [])
                if depth < maxdepth and ln > 1:
                    sub_ok, sub_out = pb_walk(payload, depth + 1, name, None, maxfields, maxdepth)
                if sub_ok and sub_out:
                    out.append(f"{'  ' * depth}{name}  msg({ln})")
                    out.extend(sub_out)
                else:
                    out.append(f"{'  ' * depth}{name}  bytes({ln})  {payload[:16].hex()}")
        else:
            return False, out
        n += 1
        if i == start:
            return False, out
    return (i == len(b)), out


def cmd_proto(args):
    data = open(args.file, 'rb').read()
    print(f"文件: {args.file}")
    print(f"大小: {len(data)} 字节")
    ok, lines = pb_walk(data, 0, '', None, args.max, args.depth)
    print(f"protobuf 解析: {'整段完整' if ok else '部分（可能有其它封装）'}")
    for ln in lines[:args.max]:
        print(ln)
    return 0


# ---------------------------------------------------------------- CLI
# --------------------------------------------------------------------------
# 存档扫描：用户不知道存档在哪时，先扫一遍常见位置再决定读哪个
# --------------------------------------------------------------------------
_SKIP_DIRS = {
    'node_modules', '.git', '__pycache__', 'temp', 'tmp', 'cache', 'logs',
    'crashes', 'gpucache', 'shadercache', 'code cache', 'service worker',
    'webviewdata', 'dumps', 'crashpad', 'crashreportclient', 'packages',
    'microsoft', 'google', 'mozilla', 'adobe', 'npm-cache', 'pnpm-store',
    'windows', 'programs', 'connecteddevicesplatform', 'comms',
}
_HINT_DIRS = {
    'saves', 'save', 'savegames', 'savegame', 'saved', 'slots', 'slot',
    'profiles', 'profile', 'userdata', 'remote',
}
_BACKUP_MARKERS = ('backup', 'bak', 'old', 'archive', 'copy', '副本')
_STRONG_EXT = {'.sav', '.save', '.savf', '.mp', '.es3', '.nson', '.slot', '.sl2', '.srm'}
_WEAK_EXT = {'.json', '.dat', '.bin', '.bkp', '.bak', '.profile', '.gd', '.rsv'}
_SKIP_EXT = {'.log', '.txt', '.dll', '.exe', '.pdb', '.xml', '.png', '.jpg', '.asset',
             '.assets', '.cfg', '.ini', '.zip', '.ttf', '.otf', '.wav', '.mp3', '.dmp',
             '.pak', '.vdf', '.manifest', '.acf', '.db', '.sqlite', '.lnk', '.ico'}


def _scan_roots(extra=None):
    """列出值得扫的根目录（存在才加）：(路径, 最大深度)。"""
    roots = []
    home = os.environ.get('USERPROFILE') or os.path.expanduser('~')
    for rel, depth in (('AppData\\LocalLow', 8), ('AppData\\Local', 4), ('AppData\\Roaming', 5)):
        p = os.path.join(home, *rel.split('\\'))
        if os.path.isdir(p):
            roots.append((p, depth))
    docs = os.path.join(home, 'Documents')
    for sub in ('My Games', 'Saved Games'):
        p = os.path.join(docs, sub)
        if os.path.isdir(p):
            roots.append((p, 8))
    for lib in ('D:\\Steam', 'C:\\Program Files (x86)\\Steam', 'C:\\Program Files\\Steam'):
        ud = os.path.join(lib, 'userdata')
        if os.path.isdir(ud):
            roots.append((ud, 7))
    for item in (extra or []):
        if os.path.isdir(item):
            roots.append((item, 8))
    return roots


def _sniff_format(path, size):
    """只看文件头就把常见存档格式认出来，认不出返回 None。"""
    try:
        with open(path, 'rb') as handle:
            head = handle.read(256)
    except OSError:
        return None
    if not head:
        return None
    if head[:2] == b'\x1f\x8b':
        return 'gzip'
    if head[:4] == b'\x04\x22\x4d\x18':
        return 'lz4'
    if head[:4] == b'\x28\xb5\x2f\xfd':
        return 'zstd'
    if head[:4] == b'\xaa\x2d\x3a\x73':
        return 'EasySave3'
    if head[:1] == b'\x45' and size > 33 and (size - 33) % 16 == 0:
        return 'AES-CBC'
    if head[:2] in (b'\x78\x9c', b'\x78\x01', b'\x78\xda', b'\x78\x5e'):
        return 'zlib'
    stripped = head.lstrip(b'\xef\xbb\xbf \t\r\n')
    if stripped[:1] in (b'{', b'['):
        text = stripped[:200].decode('utf-8', 'ignore').strip()
        if text[:1] in ('{', '['):
            return 'JSON'
    first = head[0]
    if 0x80 <= first <= 0x9f or first in (0xdc, 0xdd, 0xde, 0xdf):
        return 'MessagePack'
    return None


def _scan_score(path, size, fmt):
    score = 0
    parent = os.path.basename(os.path.dirname(path)).lower()
    grand = os.path.basename(os.path.dirname(os.path.dirname(path))).lower()
    ext = os.path.splitext(path)[1].lower()
    if parent in _HINT_DIRS or grand in _HINT_DIRS:
        score += 50
    if ext in _STRONG_EXT:
        score += 40
    elif ext in _WEAK_EXT:
        score += 5
    if fmt in ('AES-CBC', 'EasySave3', 'gzip', 'zlib', 'lz4', 'zstd'):
        score += 25
    elif fmt in ('JSON', 'MessagePack'):
        score += 12
    if size >= 1024:
        score += 10
    if size > 64 * 1024 * 1024:
        score -= 200
    if ext in _SKIP_EXT:
        score -= 120
    return score


def _is_backup(path, mtime, newest_by_dir):
    """是不是「备份副本」：目录名带 backup/bak/old/副本，或同目录里已有更新的同名文件。"""
    lower = path.lower()
    segments = lower.replace('/', '\\').split('\\')
    for segment in segments[:-1]:
        if any(marker in segment for marker in _BACKUP_MARKERS):
            return True
        if '.bak-' in segment or segment.startswith('backup'):
            return True
    base = os.path.basename(lower)
    if any(marker in base for marker in ('.bac', '.bak', '.old', '.orig', '.copy', 'backup')):
        return True
    newest = newest_by_dir.get(os.path.dirname(lower))
    if newest is not None and mtime < newest - 60:
        return True
    return False


def _scan_label(path):
    """把路径变成人能读的「游戏名」。"""
    parts = [p for p in path.replace('/', '\\').split('\\') if p]
    lower = [p.lower() for p in parts]
    if 'locallow' in lower:
        index = lower.index('locallow')
        if len(parts) > index + 2:
            return '%s · %s' % (parts[index + 2], parts[index + 1])
    if 'userdata' in lower:
        index = lower.index('userdata')
        if len(parts) > index + 2:
            return 'Steam 云存档 · AppID %s' % parts[index + 2]
    if 'my games' in lower:
        index = lower.index('my games')
        if len(parts) > index + 1:
            return '%s · My Games' % parts[index + 1]
    if len(parts) >= 3:
        return '%s · %s' % (parts[-2], parts[-3])
    return path


def scan_saves(extra_roots=None, limit=60, max_files=30000):
    """扫常见存档位置，返回候选清单（按可信度排序，备份副本排后面）。"""
    roots = _scan_roots(extra_roots)
    found = []
    seen = set()
    visited = 0
    truncated = False
    for root, max_depth in roots:
        base_depth = root.rstrip('\\/').count(os.sep)
        for dirpath, dirnames, filenames in os.walk(root, topdown=True):
            depth = dirpath.count(os.sep) - base_depth
            if depth >= max_depth:
                dirnames[:] = []
            dirnames[:] = [d for d in dirnames
                           if d.lower() not in _SKIP_DIRS and not d.startswith('.')]
            for name in filenames:
                visited += 1
                if visited > max_files:
                    truncated = True
                    break
                path = os.path.join(dirpath, name)
                key = os.path.normcase(path)
                if key in seen:
                    continue
                ext = os.path.splitext(name)[1].lower()
                parent = os.path.basename(dirpath).lower()
                if ext in _SKIP_EXT:
                    continue
                if ext not in _STRONG_EXT and ext not in _WEAK_EXT and parent not in _HINT_DIRS:
                    continue
                try:
                    stat = os.stat(path)
                except OSError:
                    continue
                size = stat.st_size
                if size < 32 or size > 64 * 1024 * 1024:
                    continue
                fmt = _sniff_format(path, size)
                score = _scan_score(path, size, fmt)
                if score <= 0:
                    continue
                seen.add(key)
                found.append({
                    'path': path,
                    'game': _scan_label(path),
                    'dir': dirpath,
                    'size': size,
                    'mtime': int(stat.st_mtime),
                    'fmt': fmt or '未识别',
                    'score': score,
                })
            if truncated:
                break
        if truncated:
            break

    # 同一目录里最新的那个才算「当前存档」，其余标成备份
    newest_by_dir = {}
    for item in found:
        key = os.path.dirname(item['path'].lower())
        if item['mtime'] > newest_by_dir.get(key, 0):
            newest_by_dir[key] = item['mtime']
    for item in found:
        item['backup'] = _is_backup(item['path'], item['mtime'], newest_by_dir)
        if item['backup']:
            item['score'] -= 45
    found.sort(key=lambda it: (it['backup'], -it['score'], -it['mtime']))
    return {'roots': [r for r, _ in roots], 'scanned': visited,
            'truncated': truncated, 'items': found[:limit]}


def cmd_scan(args):
    result = scan_saves(extra_roots=args.root, limit=args.limit)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
        return 0
    print('扫描根目录:')
    for root in result['roots']:
        print('  ' + root)
    print('检查文件数: %d%s' % (result['scanned'], '（已截断）' if result.get('truncated') else ''))
    print('')
    if not result['items']:
        print('没找到像存档的文件。可以加 --root 指定目录再看看。')
        return 0
    import datetime
    for item in result['items']:
        when = datetime.datetime.fromtimestamp(item['mtime']).strftime('%Y-%m-%d %H:%M')
        tag = '备份' if item['backup'] else '当前'
        print('[%s] %-11s %10d B  %s  %s' % (tag, item['fmt'], item['size'], when, item['path']))
    return 0


def main(argv=None):
    argv = argv or sys.argv[1:]
    if argv and argv[0] == '__doctor__':
        import platform
        mods = {}
        for m in ('dnfile', 'dncil', 'msgpack', 'lz4', 'Crypto'):
            try:
                __import__(m)
                mods[m] = True
            except Exception:
                mods[m] = False
        print(json.dumps({
            'ok': all(mods.values()),
            'python': sys.executable,
            'version': platform.python_version(),
            'script': os.path.abspath(__file__),
            'modules': mods,
            'missing': [k for k, v in mods.items() if not v],
        }, ensure_ascii=False))
        return 0
    if argv and argv[0] == '__pip__':
        import subprocess
        mirror = argv[1] if len(argv) > 1 else 'https://pypi.tuna.tsinghua.edu.cn/simple'
        mods = argv[2:]
        if not mods:
            print('没有要安装的模块')
            return 2
        cmd = [sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '-i', mirror] + mods
        print('$ ' + ' '.join(cmd), flush=True)
        rc = subprocess.call(cmd)
        print('pip 退出码: %d' % rc, flush=True)
        return 0 if rc == 0 else 1
    ap = argparse.ArgumentParser(prog='gmtool', description='单机游戏修改工具（探测/存档/反汇编/打补丁）')
    sub = ap.add_subparsers(dest='group')

    p = sub.add_parser('probe', help='探测文件格式（AES 头布局 / 压缩 / MessagePack）')
    p.add_argument('file')
    p.add_argument('--depth', type=int, default=6)
    p.add_argument('--hexlen', type=int, default=32)

    s = sub.add_parser('save', help='读写 MessagePack 存档（自动穿透 AES/LZ4）')
    ss = s.add_subparsers(dest='cmd')
    for name in ('dump', 'get'):
        q = ss.add_parser(name)
        q.add_argument('file')
        q.add_argument('path', nargs='?')
        q.add_argument('--limit', type=int, default=40)
        q.add_argument('--json', action='store_true', help='输出 JSON 行（供图形界面用）')
    for name in ('set', 'add', 'remove'):
        q = ss.add_parser(name)
        q.add_argument('file')
        q.add_argument('spec', help='如 1162.4.1=1234 或 394=411')
        q.add_argument('-o', '--out')
        q.add_argument('--no-backup', dest='backup', action='store_false', default=True)

    q = sub.add_parser('proto', help='无 schema 的 protobuf 结构浏览')
    q.add_argument('file')
    q.add_argument('--max', type=int, default=80)
    q.add_argument('--depth', type=int, default=4)

    q = sub.add_parser('fuzz', help='模糊测试写操作不变量（随机 JSON + 反向抓漏）')
    q.add_argument('--n', type=int, default=200)
    q.add_argument('--seed', type=int, default=0)
    sc = sub.add_parser('scan', help='扫描常见存档位置（不知道存档在哪时先用它）')
    sc.add_argument('--root', action='append', default=[], help='额外扫描的目录，可重复')
    sc.add_argument('--limit', type=int, default=60)
    sc.add_argument('--json', action='store_true')

    d = sub.add_parser('dll', help='.NET/Unity Mono 程序集操作')
    ds = d.add_subparsers(dest='cmd')
    q = ds.add_parser('types'); q.add_argument('dll'); q.add_argument('pattern', nargs='?')
    for name in ('methods', 'fields', 'dis'):
        q = ds.add_parser(name); q.add_argument('dll'); q.add_argument('type')
        if name == 'dis':
            q.add_argument('method', nargs='?')
    q = ds.add_parser('xref'); q.add_argument('dll'); q.add_argument('name')
    q = ds.add_parser('enum'); q.add_argument('dll'); q.add_argument('type')
    q = ds.add_parser('patch')
    q.add_argument('dll'); q.add_argument('type'); q.add_argument('method')
    q.add_argument('--bytes')
    q.add_argument('--ret-false', action='store_true')
    q.add_argument('--ret-true', action='store_true')
    q.add_argument('--nop', action='store_true')
    q.add_argument('-o', '--out')

    args = ap.parse_args(argv)
    if args.group is None:
        ap.print_help()
        return 0
    if args.group == 'fuzz':
        return cmd_fuzz(args)
    if args.group == 'scan':
        return cmd_scan(args)
    if args.group == 'probe':
        return cmd_probe(args)
    if args.group == 'save':
        if not getattr(args, 'cmd', None):
            s.print_help()
            return 1
        return cmd_save(args)
    if args.group == 'proto':
        return cmd_proto(args)
    if args.group == 'dll':
        if not getattr(args, 'cmd', None):
            d.print_help()
            return 1
        return cmd_dll(args)
    return 1


def run_cli():
    """友好地兜住「文件不存在 / 没权限」这类常见错误，不甩 Traceback 给用户看。"""
    try:
        return main()
    except FileNotFoundError as exc:
        missing = getattr(exc, 'filename', None) or str(exc)
        print(f'文件不存在: {missing}', file=sys.stderr)
        print('提示: 用 scan 子命令找你机器上的存档，或检查路径里的分隔符。', file=sys.stderr)
        return 2
    except IsADirectoryError as exc:
        print(f'这是一个目录，不是文件: {getattr(exc, "filename", None) or exc}', file=sys.stderr)
        return 2
    except PermissionError as exc:
        print(f'没有权限访问: {getattr(exc, "filename", None) or exc}', file=sys.stderr)
        print('提示: 以管理员身份运行，或先把文件复制到可写目录再改。', file=sys.stderr)
        return 3
    except (GmError, KeyError, IndexError, TypeError, ValueError) as exc:
        print(f'参数或路径无效: {exc}', file=sys.stderr)
        print('提示: 先用 save dump 看结构；数组下标用整数，字符串值不要加引号。', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('已中断', file=sys.stderr)
        return 130


if __name__ == '__main__':
    sys.exit(run_cli())
