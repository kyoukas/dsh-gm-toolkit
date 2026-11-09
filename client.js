// dsh-gm-toolkit 客户端面板：存档修改
// 手写 Client module-loader 格式，不依赖 Harness 客户端包；只调用宿主侧的 /api/gm/*。
window.__ModuleLoader__.load({
  id: 'dsh-gm-toolkit',
  factory(require) {
    var React = require('react');
    var h = React.createElement;
    var useState = React.useState;
    var useEffect = React.useEffect;
    var useCallback = React.useCallback;

    var PANEL_ID = 'gm-save-editor';
    var PRESET_ID = 'gm-toolkit';
    // uiWorkspace 是客户端的工作区/导航控制器；拿不到时按钮降级成文字提示。
    // 存普通变量而不是 ref 的 .current：EntryCard 读的是渲染期值，apply 一定早于首渲染，
    // 直接读 ctx 就没有「服务晚到、但不触发重渲染」的死角。
    var hostCtx = null;
    var STORE_KEY = 'dsh-gm-toolkit:lastPath';

    var CSS = {
      page: {
        height: '100%',
        overflow: 'auto',
        padding: '20px 24px 40px',
        fontFamily: 'inherit',
        fontSize: 13,
        color: 'var(--dsw-alias-label-primary)',
        background: 'var(--dsw-alias-bg-base)',
      },
      card: {
        border: '1px solid var(--dsw-alias-border-l1)',
        borderRadius: 10,
        padding: '14px 16px',
        marginBottom: 14,
        background: 'var(--dsw-alias-bg-layer-1))',
      },
      h1: { fontSize: 17, fontWeight: 600, margin: '0 0 6px' },
      h2: { fontSize: 13, fontWeight: 600, margin: '0 0 10px' },
      muted: { color: 'var(--dsw-alias-label-secondary)', fontSize: 12, lineHeight: 1.7 },
      row: { display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' },
      input: {
        flex: '1 1 320px',
        minWidth: 220,
        padding: '7px 10px',
        borderRadius: 8,
        border: '1px solid var(--dsw-alias-border-l1)',
        background: 'var(--dsw-alias-bg-layer-2)',
        color: 'inherit',
        fontFamily: 'inherit',
        fontSize: 12.5,
      },
      btn: {
        padding: '7px 13px',
        borderRadius: 8,
        border: '1px solid var(--dsw-alias-border-l1)',
        background: 'var(--dsw-alias-bg-layer-2)',
        color: 'inherit',
        cursor: 'pointer',
        fontFamily: 'inherit',
        fontSize: 12.5,
      },
      btnPrimary: { background: 'var(--dsw-alias-brand-primary)', borderColor: 'transparent', color: '#fff' },
      pre: {
        margin: '10px 0 0',
        padding: '10px 12px',
        borderRadius: 8,
        background: 'var(--dsw-alias-bg-layer-2)',
        border: '1px solid var(--dsw-alias-border-l1)',
        fontSize: 11.5,
        lineHeight: 1.6,
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-all',
        maxHeight: 260,
        overflow: 'auto',
        color: 'var(--dsw-alias-label-secondary)',
      },
      table: { width: '100%', borderCollapse: 'collapse', marginTop: 10, fontSize: 12.5 },
      th: {
        textAlign: 'left',
        padding: '7px 8px',
        borderBottom: '1px solid var(--dsw-alias-border-l1)',
        color: 'var(--dsw-alias-label-secondary)',
        fontWeight: 500,
        whiteSpace: 'nowrap',
      },
      td: {
        padding: '6px 8px',
        borderBottom: '1px solid var(--dsw-alias-border-l1)',
        verticalAlign: 'top',
      },
      mono: { fontFamily: 'ui-monospace, Consolas, monospace', fontSize: 11.5 },
      crumb: { cursor: 'pointer', textDecoration: 'underline dotted', marginRight: 6 },
      ok: { color: 'var(--dsw-alias-state-success-primary)' },
      bad: { color: 'var(--dsw-alias-state-error-primary)' },
      warn: { color: 'var(--dsw-alias-state-warn-primary)' },
    };

    function api(path, body) {
      return fetch('/api/gm/' + path, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body || {}),
      })
        .then(function (res) {
          return res.json().catch(function () {
            return { ok: false, error: 'HTTP ' + res.status };
          });
        })
        .catch(function (error) {
          return { ok: false, error: String((error && error.message) || error) };
        });
    }

    function short(value, max) {
      var text = value === null || value === undefined ? '' : String(value);
      if (text.length > max) return text.slice(0, max) + '…';
      return text;
    }

    function fmtSize(bytes) {
      if (!bytes && bytes !== 0) return '';
      if (bytes >= 1048576) return (bytes / 1048576).toFixed(1) + ' MB';
      if (bytes >= 1024) return (bytes / 1024).toFixed(1) + ' KB';
      return bytes + ' B';
    }

    function fmtTime(seconds) {
      if (!seconds) return '';
      var d = new Date(seconds * 1000);
      var pad = function (n) { return (n < 10 ? '0' : '') + n; };
      return (d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
    }

    function Badge(props) {
      var style = props.tone === 'ok' ? CSS.ok : props.tone === 'bad' ? CSS.bad : CSS.warn;
      return h('span', { style: style }, props.text);
    }

    function EntryCard() {
      var workspace = hostCtx && typeof hostCtx.get === 'function' ? hostCtx.get('uiWorkspace') : null;
      var available = !!(workspace && typeof workspace.startSession === 'function');
      return h('div', { style: Object.assign({}, CSS.card, { borderLeft: '3px solid var(--dsw-alias-brand-primary)' }) },
        h('div', { style: CSS.h2 }, '「存档修改」模式'),
        h('div', { style: { fontSize: 12, opacity: 0.75, lineHeight: 1.7, marginBottom: 8 } },
          '本面板不挂任何工具，普通会话因此零开销。模型手里那 9 个 gm_* 工具只在「存档修改」模式的会话里挂载 —— 点了下面的按钮，或者新建会话时在模式里选「存档修改」。'
        ),
        h('button', {
          style: available ? Object.assign({}, CSS.btn, CSS.btnPrimary) : Object.assign({}, CSS.btn, { opacity: 0.55 }),
          onClick: function () {
            if (!available) return;
            try {
              workspace.startSession(undefined, { agentPreset: PRESET_ID });
            } catch (error) {
              console.warn('[gm-toolkit] startSession failed', error);
            }
          },
        }, available ? '用「存档修改」模式新建会话' : '新建会话请在左上角选择「存档修改」模式'),
        h('div', { style: { fontSize: 11, opacity: 0.55, marginTop: 6 } },
          '提示：模式在会话创建时就定了，之后不能换成另一种模式。'
        )
      );
    }

    function Guide() {
      var open = useState(false);
      return h(
        'div',
        { style: CSS.card },
        h('div', { style: CSS.row, justifyContent: 'space-between' },
          h('div', null,
            h('div', { style: CSS.h1 }, '存档修改'),
            h('div', { style: CSS.muted }, '先探测格式，再改字段；每次写入都会自动备份原文件。')
          ),
          h('button', { style: CSS.btn, onClick: function () { open[1](!open[0]); } },
            open[0] ? '收起说明' : '怎么用'
          )
        ),
        open[0]
          ? h('div', { style: Object.assign({}, CSS.muted, { marginTop: 12 }) },
              h('div', null, '1. 填存档文件的完整路径（Windows 路径，例如 C:\\Users\\你\\AppData\\LocalLow\\游戏\\saves\\slot_0.mp）。'),
              h('div', null, '2. 点「探测格式」：能认出来才继续；认不出说明这个游戏用了自定义格式，需要我在会话里先分析。'),
              h('div', null, '3. 字段表里点带 [n] 的行往下钻，找到目标字段后点「改」，输入新值。'),
              h('div', null, '4. 改完点「应用修改」写回。原文件会先备份，页面会显示备份路径。'),
              h('div', null, '5. 写档前请退出游戏，否则游戏退出时会用内存里的旧数据覆盖你的修改。'),
              h('div', { style: { marginTop: 8 } }, '这个面板只做「已知格式的直接读写」，不支持未识别的格式，也不会替你猜字段含义。')
            )
          : null
      );
    }

    function EnvCard(props) {
      var env = props.env;
      var busy = props.busy;
      var tone = 'warn';
      var text = '还没体检';
      if (env) {
        if (env.ok) { tone = 'ok'; text = '环境就绪'; }
        else if (env.error === 'no-python') { tone = 'bad'; text = '没找到 Python'; }
        else { tone = 'bad'; text = '缺少 Python 依赖'; }
      }
      var missing = env && env.info && env.info.missing ? env.info.missing : [];
      return h(
        'div',
        { style: CSS.card },
        h('div', { style: CSS.row, justifyContent: 'space-between' },
          h('div', null,
            h('div', { style: CSS.h2 }, '运行环境'),
            h('div', { style: CSS.muted },
              h(Badge, { tone: tone, text: text }),
              env && env.python ? h('span', null, '  ·  ' + env.python) : null,
              env && env.info && env.info.version ? h('span', null, '  ·  Python ' + env.info.version) : null,
              missing.length ? h('span', null, '  ·  缺: ' + missing.join(', ')) : null
            )
          ),
          h('div', { style: CSS.row },
            h('button', { style: CSS.btn, disabled: busy, onClick: props.onCheck }, busy ? '检测中…' : '重新检测'),
            missing.length
              ? h('button', { style: Object.assign({}, CSS.btn, CSS.btnPrimary), disabled: busy, onClick: props.onInstall },
                  busy ? '安装中…' : '一键安装缺失')
              : null
          )
        ),
        env && env.text ? h('pre', { style: CSS.pre }, short(env.text, 1600)) : null
      );
    }

    function ScanList(props) {
      var scan = props.scan;
      if (!scan) return null;
      var items = scan.items || [];
      var shown = props.showBackup ? items : items.filter(function (item) { return !item.backup; });
      var hidden = items.length - shown.length;
      return h('div', { style: { marginTop: 12 } },
        h('div', { style: CSS.row, justifyContent: 'space-between' },
          h('span', { style: CSS.muted },
            '扫到 ' + items.length + ' 个候选' + (scan.truncated ? '（文件太多，已截断）' : '') + '，按可信度排序'),
          hidden > 0
            ? h('button', { style: CSS.btn, onClick: props.onToggleBackup },
                props.showBackup ? '隐藏备份' : '显示备份（' + hidden + '）')
            : null
        ),
        shown.length === 0
          ? h('div', { style: Object.assign({}, CSS.muted, { marginTop: 8 }) }, '没有找到可用候选。可以在会话里告诉我要扫的目录。')
          : h('div', { style: { marginTop: 8, maxHeight: 340, overflow: 'auto', border: '1px solid var(--dsw-alias-border-l1)', borderRadius: 8 } },
              shown.map(function (item, index) {
                return h('div', {
                  key: index,
                  style: { display: 'flex', gap: 10, alignItems: 'center', padding: '8px 10px', cursor: 'pointer', borderBottom: '1px solid var(--dsw-alias-border-l1)' },
                  onClick: function () { props.onPick(item.path); },
                  onMouseEnter: function (event) { event.currentTarget.style.background = 'var(--dsw-alias-bg-layer-2))'; },
                  onMouseLeave: function (event) { event.currentTarget.style.background = 'transparent'; },
                },
                  h('span', { style: Object.assign({}, CSS.mono, { flex: '0 0 92px', color: item.fmt === '未识别' ? 'var(--dsw-alias-state-warn-primary)' : 'var(--dsw-alias-state-success-primary)' }) }, item.fmt),
                  h('span', { style: { flex: '1 1 auto', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, item.game || ''),
                  h('span', { style: Object.assign({}, CSS.mono, { flex: '0 0 auto', color: 'var(--dsw-alias-label-secondary)' }) },
                    fmtSize(item.size) + ' · ' + fmtTime(item.mtime)),
                  item.backup ? h('span', { style: Object.assign({}, CSS.mono, { flex: '0 0 auto' }, CSS.warn) }, '备份') : null
                );
              })
            ),
        h('div', { style: Object.assign({}, CSS.muted, { marginTop: 6 }) }, '点任意一行就把路径填进上面的输入框。')
      );
    }

    function BrowserCard(props) {
      var state = props.state;
      var setPath = props.setPath;
      return h(
        'div',
        { style: CSS.card },
        h('div', { style: CSS.row, justifyContent: 'space-between' },
          h('div', { style: CSS.h2 }, '存档文件'),
          h('button', {
            style: CSS.btn,
            disabled: state.scanBusy,
            onClick: props.onScan,
            title: '扫描 LocalLow / Local / Roaming / Documents / Steam 云存档里的存档文件',
          }, state.scanBusy ? '扫描中…' : '扫描我的存档')
        ),
        h('div', { style: CSS.row },
          h('input', {
            style: CSS.input,
            placeholder: 'C:\\...\\saves\\slot_0.mp',
            value: state.path,
            onChange: function (event) { setPath(event.target.value); },
            onKeyDown: function (event) { if (event.key === 'Enter') props.onProbe(); },
          }),
          h('button', { style: CSS.btn, disabled: state.busy, onClick: props.onProbe }, state.busy ? '探测中…' : '探测格式'),
          h('button', { style: CSS.btn, disabled: state.busy || !state.path, onClick: props.onList }, '打开字段')
        ),
        h(ScanList, {
          scan: state.scan,
          showBackup: state.showBackup,
          onPick: function (path) { setPath(path); props.onProbe(path); },
          onToggleBackup: function () { props.onToggleBackup(); },
        }),
        state.probeText ? h('pre', { style: CSS.pre }, state.probeText) : null,
        state.listError ? h('div', { style: Object.assign({}, CSS.muted, { marginTop: 10 }) }, h(Badge, { tone: 'bad', text: state.listError })) : null
      );
    }

    var TABLE_STEP = 300;

    function FieldsCard(props) {
      var state = props.state;
      // hooks 必须在提前 return 之前调用
      var moreBox = useState(TABLE_STEP);
      useEffect(function () { moreBox[1](TABLE_STEP); }, [state.data]);
      if (!state.data) return null;
      var rows = state.data.rows || [];
      var filter = state.filter.toLowerCase();
      var shown = filter
        ? rows.filter(function (row) {
            return String(row.path).toLowerCase().indexOf(filter) >= 0 ||
              String(row.value).toLowerCase().indexOf(filter) >= 0;
          })
        : rows;
      var parents = state.data.parents || [['根', '']];
      return h(
        'div',
        { style: CSS.card },
        h('div', { style: CSS.row, justifyContent: 'space-between' },
          h('div', { style: CSS.row },
            h('span', { style: CSS.muted }, '位置：'),
            parents.map(function (pair, index) {
              return h('span', {
                key: index,
                style: Object.assign({}, CSS.crumb, CSS.mono),
                onClick: function () { props.onJump(pair[1]); },
              }, pair[0]);
            })
          ),
          h('div', { style: CSS.row },
            h('span', { style: CSS.muted }, (state.data.kind || '') + ' · ' + rows.length + ' 行'),
            state.data.path ? h('button', { style: CSS.btn, onClick: function () { props.onJump(state.data.parents[state.data.parents.length - 2] ? state.data.parents[state.data.parents.length - 2][1] : ''); } }, '上一级') : null
          )
        ),
        h('div', { style: Object.assign({}, CSS.row, { marginTop: 10 }) },
          h('input', {
            style: Object.assign({}, CSS.input, { flex: '1 1 200px' }),
            placeholder: '在本层里搜字段名 / 值',
            value: state.filter,
            onChange: function (event) { props.setFilter(event.target.value); },
          }),
          h('button', { style: CSS.btn, disabled: !state.path, onClick: props.onSavePath }, '记住这个路径')
        ),
        h('table', { style: CSS.table },
          h('thead', null,
            h('tr', null,
              h('th', { style: CSS.th }, '字段'),
              h('th', { style: CSS.th }, '类型'),
              h('th', { style: CSS.th }, '当前值'),
              h('th', { style: CSS.th }, '操作')
            )
          ),
          h('tbody', null,
            shown.slice(0, moreBox[0]).map(function (row) {
              var editing = state.editing && state.editing.path === row.path;
              return h('tr', { key: row.path },
                h('td', { style: Object.assign({}, CSS.td, CSS.mono) }, row.path),
                h('td', { style: Object.assign({}, CSS.td, CSS.mono) }, row.kind),
                h('td', { style: Object.assign({}, CSS.td, CSS.mono) },
                  editing
                    ? h('input', {
                        style: Object.assign({}, CSS.input, { padding: '4px 8px', fontSize: 12 }),
                        autoFocus: true,
                        value: state.editing.value,
                        onChange: function (event) { props.setEditing({ path: row.path, value: event.target.value }); },
                        onKeyDown: function (event) { if (event.key === 'Enter') props.onStage(row); },
                      })
                    : short(row.value, 160)
                ),
                h('td', { style: CSS.td },
                  row.leaf === false
                    ? h('button', { style: CSS.btn, onClick: function () { props.onJump(row.path); } }, '展开')
                    : editing
                      ? h('button', { style: Object.assign({}, CSS.btn, CSS.btnPrimary), onClick: function () { props.onStage(row); } }, '加入')
                      : h('button', { style: CSS.btn, onClick: function () { props.setEditing({ path: row.path, value: String(row.value) }); } }, '改')
                )
              );
            })
          )
        ),
        shown.length > moreBox[0]
          ? h('div', { style: Object.assign({}, CSS.row, { marginTop: 8 }) },
              h('button', { style: CSS.btn, onClick: function () { moreBox[1](moreBox[0] + TABLE_STEP); } },
                '加载更多（还有 ' + (shown.length - moreBox[0]) + ' 行）'),
              h('span', { style: CSS.muted }, '或在上面的搜索框里缩小范围')
            )
          : null
      );
    }

    function PendingCard(props) {
      var pending = props.pending;
      if (pending.length === 0) return null;
      return h(
        'div',
        { style: CSS.card },
        h('div', { style: CSS.row, justifyContent: 'space-between' },
          h('div', { style: CSS.h2 }, '待应用的修改（' + pending.length + '）'),
          h('div', { style: CSS.row },
            h('button', { style: CSS.btn, onClick: props.onClear }, '清空'),
            h('button', { style: Object.assign({}, CSS.btn, CSS.btnPrimary), disabled: props.busy, onClick: props.onApply }, props.busy ? '写入中…' : '应用到存档')
          )
        ),
        pending.map(function (item, index) {
          return h('div', { key: index, style: Object.assign({}, CSS.mono, { padding: '3px 0' }) },
            (item.op || 'set') + ' ' + item.target + ' = ' + item.value
          );
        })
      );
    }

    function PanelPage() {
      var envState = useState(null);
      var busyState = useState(false);
      var stateBox = useState({
        path: '',
        probeText: '',
        data: null,
        listError: '',
        filter: '',
        editing: null,
        busy: false,
        scan: null,
        scanBusy: false,
        showBackup: false,
      });
      var pendingBox = useState([]);
      var logBox = useState([]);

      var pending = pendingBox[0];
      var state = stateBox[0];
      var log = logBox[0];

      useEffect(function () {
        try {
          var saved = window.localStorage.getItem(STORE_KEY);
          if (saved) setStateField({ path: saved });
        } catch (error) { /* localStorage 被禁用时忽略 */ }
        checkEnv();
      }, []);

      function pushLog(text) {
        logBox[1](function (list) {
          var next = list.concat([new Date().toLocaleTimeString() + '  ' + text]);
          return next.slice(-80);
        });
      }

      function setStateField(patch) {
        stateBox[1](function (previous) { return Object.assign({}, previous, patch); });
      }

      function setBusy(value) {
        busyState[1](value);
        setStateField({ busy: value });
      }

      function checkEnv() {
        setBusy(true);
        api('doctor', {}).then(function (result) {
          envState[1](result);
          setBusy(false);
          pushLog(result.ok ? '环境体检通过' : '环境体检未通过');
        });
      }

      function installDeps() {
        setBusy(true);
        pushLog('开始安装缺失依赖（清华镜像）…');
        api('install', {}).then(function (result) {
          pushLog(result.ok ? '安装命令已执行' : '安装失败: ' + (result.error || ''));
          if (result.text) pushLog(short(result.text, 400));
          setBusy(false);
          checkEnv();
        });
      }

      function scanSaves() {
        setStateField({ scanBusy: true });
        pushLog('开始扫描存档目录…');
        api('scan', { limit: 120 }).then(function (result) {
          setStateField({ scanBusy: false });
          if (!result.ok || !result.data) {
            pushLog('扫描失败: ' + (result.error || '未知错误'));
            return;
          }
          var items = result.data.items || [];
          setStateField({ scan: result.data, showBackup: false });
          pushLog('扫描完成：' + items.length + ' 个候选');
        });
      }

      function probe(path) {
        var target = typeof path === 'string' && path ? path : state.path;
        if (!target) return;
        if (target !== state.path) setStateField({ path: target, data: null });
        setBusy(true);
        setStateField({ probeText: '', listError: '' });
        api('probe', { path: target }).then(function (result) {
          setBusy(false);
          if (!result.ok) {
            setStateField({ probeText: result.text || result.error || '探测失败', listError: result.error || '' });
            return;
          }
          setStateField({ probeText: result.text });
          pushLog('探测完成');
        });
      }

      function openList(target) {
        if (!state.path) return;
        setBusy(true);
        api('list', { path: state.path, target: target === undefined ? '' : target }).then(function (result) {
          setBusy(false);
          if (!result.ok || !result.data) {
            setStateField({ listError: result.error || '读不出来', data: null });
            pushLog('打开字段失败: ' + (result.error || ''));
            return;
          }
          setStateField({ data: result.data, listError: '', editing: null });
          pushLog('打开 ' + (result.data.path || '根') + '（' + (result.data.rows || []).length + ' 行）');
        });
      }

      function stage() {
        var editing = state.editing;
        if (!editing) return;
        var value = String(editing.value);
        pendingBox[1](function (list) {
          var next = list.filter(function (item) { return item.target !== editing.path; });
          next.push({ op: 'set', target: editing.path, value: value });
          return next;
        });
        setStateField({ editing: null });
        pushLog('加入待应用: ' + editing.path + ' = ' + value);
      }

      function applyChanges() {
        if (pending.length === 0) return;
        setBusy(true);
        pushLog('写入 ' + pending.length + ' 处修改…');
        api('apply', { path: state.path, changes: pending }).then(function (result) {
          setBusy(false);
          if (result.log) pushLog(short(result.log, 1200));
          if (result.ok) {
            pushLog('写入成功 ' + (result.applied || 0) + ' 处'
              + (result.backup ? '，备份在 ' + result.backup : '，未产生备份'));
            pendingBox[1]([]);
            if (state.data) openList(state.data.path || '');
          } else {
            var done = result.applied || 0;
            pushLog('写入失败' + (done > 0 ? '（前 ' + done + ' 处已生效）' : '')
              + ': ' + (result.error || '未知错误'));
            if (result.backup) pushLog('回滚用备份: ' + result.backup);
          }
        });
      }

      return h(
        'div',
        { style: CSS.page },
        h(EntryCard, null),
        h(Guide, null),
        h(EnvCard, { env: envState[0], busy: busyState[0], onCheck: checkEnv, onInstall: installDeps }),
        h(BrowserCard, {
          state: state,
          setPath: function (value) { setStateField({ path: value }); },
          onProbe: probe,
          onList: function () { openList(''); },
          onScan: scanSaves,
          onToggleBackup: function () { setStateField({ showBackup: !state.showBackup }); },
        }),
        h(FieldsCard, {
          state: state,
          setFilter: function (value) { setStateField({ filter: value }); },
          setEditing: function (value) { setStateField({ editing: value }); },
          onJump: function (target) { openList(target); },
          onStage: stage,
          onSavePath: function () {
            try {
              window.localStorage.setItem(STORE_KEY, state.path);
              pushLog('已记住路径');
            } catch (error) {
              pushLog('记不住路径（localStorage 不可用）');
            }
          },
        }),
        h(PendingCard, {
          pending: pending,
          busy: busyState[0],
          onApply: applyChanges,
          onClear: function () { pendingBox[1]([]); pushLog('已清空待应用'); },
        }),
        log.length
          ? h('div', { style: CSS.card },
              h('div', { style: CSS.h2 }, '日志'),
              h('pre', { style: CSS.pre }, log.join('\n'))
            )
          : null
      );
    }

    // 侧栏图标：必须接 ownerProps { size, active }（跟随尺寸与激活态），
    // 用矢量线条画「存档文件 + 折角 + 字段行」，不用字符图标。
    function PanelIcon(props) {
      var size = props && typeof props.size === 'number' ? props.size : 16;
      var active = Boolean(props && props.active);
      return h('svg', {
        width: size,
        height: size,
        viewBox: '0 0 24 24',
        fill: 'none',
        stroke: active ? 'var(--dsw-alias-brand-primary)' : 'currentColor',
        strokeWidth: 1.7,
        strokeLinecap: 'round',
        strokeLinejoin: 'round',
        'aria-hidden': 'true',
        focusable: 'false',
        style: { display: 'block', opacity: active ? 1 : 0.72 },
      },
        h('path', { d: 'M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z' }),
        h('path', { d: 'M14 3v5h5' }),
        h('path', { d: 'M8 13h8' }),
        h('path', { d: 'M8 17h5' })
      );
    }

    return {
      inject: ['slots'],
      apply: function (ctx) {
        var slots = ctx.slots;
        hostCtx = ctx;
        var disposers = [];
        disposers.push(slots.inject('sidebar.panellist', function () {
          return slots.register({
            name: 'sidebar.panellist',
            id: PANEL_ID,
            order: 64,
            label: function () { return '存档修改'; },
          }, PanelIcon);
        }));
        disposers.push(slots.inject('main', function () {
          return slots.register({
            name: 'main',
            key: PANEL_ID,
            inject: function () { return {}; },
          }, PanelPage);
        }));
        ctx.effect(function () {
          return function () {
            for (var i = 0; i < disposers.length; i++) {
              try { disposers[i](); } catch (error) { /* 卸载时忽略 */ }
            }
          };
        }, 'dsh-gm-toolkit.panel');
      },
    };
  },
});
