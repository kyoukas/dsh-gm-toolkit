# -*- coding: utf-8 -*-
"""P4 回归：从「读到」到「写前」之间，文件被别的东西改过（游戏自动存档），必须拒绝写入。

做法是注入：把 load_layers 包一层，解析完之后偷偷往文件末尾追加一个字节，
模拟「分析完、还没写」时游戏又存了一次档。这时：
  - 退出码必须是 5（不是 0，更不能是「已写回」）；
  - 文件里那条外来改动必须原样留着（不能被我们回滚成更早的快照）。
"""
import io
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'scripts'))
import gmtool  # noqa: E402

DOC = b'{\r\n\t"A" : 1\r\n}\r\n'
failures = 0


def check(name, ok, detail=''):
    global failures
    print(('  ok   ' if ok else '  FAIL ') + name + ('' if ok else ' :: ' + str(detail)[:300]))
    if not ok:
        failures += 1


def main():
    tmp = tempfile.mkdtemp(prefix='gm-race-')
    path = os.path.join(tmp, 'save.json')
    io.open(path, 'wb').write(DOC)

    real_load = gmtool.load_layers
    state = {'armed': True}

    def load_then_dirty(f, verbose=False):
        result = real_load(f, verbose=verbose)
        if state['armed']:
            state['armed'] = False
            with io.open(f, 'ab') as fh:      # 模拟：外部在我们分析完之后又写了一次
                fh.write(b' ')
        return result

    gmtool.load_layers = load_then_dirty
    args = type('A', (), {
        'file': path, 'cmd': 'set', 'spec': '.A=2', 'path': '.A',
        'out': None, 'backup': True, 'json': False,
    })()
    try:
        rc = gmtool.cmd_save(args)
    finally:
        gmtool.load_layers = real_load

    data = io.open(path, 'rb').read()
    check('拒绝写入 rc=5', rc == 5, rc)
    check('原文件没被我们改写', data == DOC + b' ', data)
    check('没有留下 .bak', not any('.bak' in n for n in os.listdir(tmp)), os.listdir(tmp))

    # 对照：没有外部改动时必须写成功
    path2 = os.path.join(tmp, 'clean.json')
    io.open(path2, 'wb').write(DOC)
    args2 = type('A', (), {
        'file': path2, 'cmd': 'set', 'spec': '.A=2', 'path': '.A',
        'out': None, 'backup': True, 'json': False,
    })()
    rc2 = gmtool.cmd_save(args2)
    check('无干扰时 rc=0', rc2 == 0, rc2)
    check('内容已改', b'"A" : 2' in io.open(path2, 'rb').read(), io.open(path2, 'rb').read()[:60])

    print('\nP4 回归：%s' % ('通过' if failures == 0 else '%d 项失败' % failures))
    return 0 if failures == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
