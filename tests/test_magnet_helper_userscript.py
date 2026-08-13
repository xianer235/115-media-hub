import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
USERSCRIPT_PATH = ROOT / "115-magnet-helper-webhook.user.js"

DOM_SETUP = """
const registry = [];
const makeEl = (tag) => {
  const el = {
    tagName: (tag || 'div').toUpperCase(),
    style: {},
    dataset: {},
    children: [],
    textContent: '',
    id: '',
    type: '',
    title: '',
    className: '',
    innerHTML: '',
    _listeners: {},
    addEventListener(name, fn) { el._listeners[name] = fn; },
    appendChild(child) { el.children.push(child); registry.push(child); child.parentNode = el; return child; },
    removeChild(child) {
      const index = el.children.indexOf(child);
      if (index >= 0) el.children.splice(index, 1);
      const ridx = registry.indexOf(child);
      if (ridx >= 0) registry.splice(ridx, 1);
      return child;
    },
    remove() { if (el.parentNode) el.parentNode.removeChild(el); },
    setAttribute() {},
    querySelector() { return null; },
    querySelectorAll() { return []; },
    closest() { return null; },
    focus() {},
    insertAdjacentElement() {}
  };
  registry.push(el);
  return el;
};
const body = makeEl('body');
context.document = {
  body,
  readyState: 'complete',
  getElementById: (id) => registry.find((el) => el.id === id) || null,
  createElement: (tag) => makeEl(tag),
  createDocumentFragment: () => makeEl('fragment'),
  createTreeWalker: () => ({ nextNode: () => null }),
  addEventListener() {},
  removeEventListener() {},
  querySelectorAll: () => []
};
context.window = {
  setTimeout,
  clearTimeout,
  getComputedStyle: () => ({ display: 'block', visibility: 'visible' }),
  localStorage: { getItem: () => null, setItem() {} }
};
"""


def run_userscript(expression: str, setup: str = ""):
    if not USERSCRIPT_PATH.exists():
        raise AssertionError(f"油猴脚本文件不存在: {USERSCRIPT_PATH}")
    script = f"""
const fs = require('fs');
const vm = require('vm');
const context = {{
  module: {{ exports: {{}} }},
  console,
  setTimeout,
  clearTimeout,
  TextEncoder,
  URL,
  URLSearchParams,
  Symbol,
  Promise,
  JSON,
  Math,
  Date,
  String,
  Number,
  Set,
  Array,
  Object,
  RegExp,
  Error,
  Map,
  Uint8Array,
  ArrayBuffer,
  DataView,
  window: {{}}
}};
{setup}
vm.createContext(context);
vm.runInContext(fs.readFileSync({json.dumps(str(USERSCRIPT_PATH))}, 'utf8'), context);
const api = context.module.exports.__mhTest;
const window = context.window;
const document = context.document;
(async () => {{
  const result = await ({expression});
  process.stdout.write(JSON.stringify(result));
}})().catch((err) => {{
  console.error(err && err.stack ? err.stack : err);
  process.exit(1);
}});
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


class MagnetHelperUserscriptCompatibilityTest(unittest.TestCase):
    def test_userscript_syntax_valid(self):
        completed = subprocess.run(
            ["node", "--check", str(USERSCRIPT_PATH)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_async_gm_storage_round_trip(self):
        # Userscripts (iOS) 的 GM_getValue/GM_setValue 是异步 Promise，
        # 任务与密钥必须能正常加载、保存。
        setup = """
const store = {
  magnet_push_tasks_v2: [
    { id: 't1', name: '电影', webhookUrl: 'http://x/webhook/电影', savepath: '/自存' }
  ],
  magnet_push_secret_v2: 'abc'
};
const writes = [];
context.GM_getValue = async (key, fallback) => (key in store ? store[key] : fallback);
context.GM_setValue = async (key, value) => { store[key] = value; writes.push([key, value]); };
"""
        result = run_userscript(
            """
(async () => {
  await api.loadPersistedState();
  const loaded = { tasks: api.getTasks(), secret: api.getSecret() };
  api.saveTasks([
    { id: 't2', name: '剧集', webhookUrl: 'http://x/webhook/剧集', savepath: '/剧集' }
  ]);
  await new Promise((resolve) => setTimeout(resolve, 0));
  return { loaded, writes };
})()
""",
            setup,
        )
        self.assertEqual(result["loaded"]["secret"], "abc")
        self.assertEqual(
            result["loaded"]["tasks"],
            [
                {
                    "id": "t1",
                    "name": "电影",
                    "webhookUrl": "http://x/webhook/电影",
                    "savepath": "自存",
                    "delaySeconds": 0,
                    "enabled": True,
                }
            ],
        )
        self.assertEqual(result["writes"][0][0], "magnet_push_tasks_v2")
        self.assertEqual(result["writes"][0][1][0]["name"], "剧集")

    def test_local_storage_fallback_without_gm_api(self):
        # 某些内置脚本运行器完全没有 GM API 时，回退到页面 localStorage。
        setup = """
const ls = {};
context.window = {
  localStorage: {
    getItem: (key) => (key in ls ? ls[key] : null),
    setItem: (key, value) => { ls[key] = value; }
  }
};
context.window.localStorage.setItem('magnet_push_secret_v2', JSON.stringify('xyz'));
context.window.localStorage.setItem(
  'magnet_push_tasks_v2',
  JSON.stringify([{ id: 't3', name: '散片', webhookUrl: 'http://x/webhook/散片', savepath: '电影' }])
);
"""
        result = run_userscript(
            """
(async () => {
  await api.loadPersistedState();
  const loaded = { tasks: api.getTasks(), secret: api.getSecret() };
  api.setSecret('xyz2');
  await new Promise((resolve) => setTimeout(resolve, 0));
  return { loaded, saved: window.localStorage.getItem('magnet_push_secret_v2') };
})()
""",
            setup,
        )
        self.assertEqual(result["loaded"]["secret"], "xyz")
        self.assertEqual(result["loaded"]["tasks"][0]["name"], "散片")
        self.assertEqual(json.loads(result["saved"]), "xyz2")

    def test_hmac_sha256_fallback_without_webcrypto(self):
        # http 页面没有 crypto.subtle 时，纯 JS 实现必须与 RFC 4231 已知向量一致。
        setup = "context.window = {};"
        result = run_userscript(
            """
(async () => {
  const key20 = new Uint8Array(20).fill(0x0b);
  const hiThere = new Uint8Array([0x48,0x69,0x20,0x54,0x68,0x65,0x72,0x65]);
  const fox = new Uint8Array([
    0x54,0x68,0x65,0x20,0x71,0x75,0x69,0x63,0x6b,0x20,0x62,0x72,0x6f,0x77,0x6e,0x20,
    0x66,0x6f,0x78,0x20,0x6a,0x75,0x6d,0x70,0x73,0x20,0x6f,0x76,0x65,0x72,0x20,0x74,
    0x68,0x65,0x20,0x6c,0x61,0x7a,0x79,0x20,0x64,0x6f,0x67
  ]);
  const key = new Uint8Array([0x6b,0x65,0x79]);
  return {
    rfc4231_1: api.jsHmacSha256Hex(key20, hiThere),
    fox: api.jsHmacSha256Hex(key, fox),
    sha256_empty: api.jsSha256Hex(new Uint8Array(0)),
    string_path: await api.hmacSha256Hex('key', 'The quick brown fox jumps over the lazy dog')
  };
})()
""",
            setup,
        )
        self.assertEqual(
            result["rfc4231_1"],
            "b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7",
        )
        self.assertEqual(
            result["fox"],
            "f7bc83f430538424b13298e6aa6fb143ef4d59a14946175997479dbc2d1a3cd8",
        )
        self.assertEqual(
            result["sha256_empty"],
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        )
        self.assertEqual(
            result["string_path"],
            "f7bc83f430538424b13298e6aa6fb143ef4d59a14946175997479dbc2d1a3cd8",
        )

    def test_post_json_falls_back_to_fetch_without_gm_request(self):
        # 没有 GM_xmlhttpRequest 时不再抛错，直接走 fetch（后端 CORS 默认 *）。
        setup = """
context.fetch = async () => ({ ok: true, status: 200, text: async () => 'ok' });
"""
        result = run_userscript(
            "api.postJson('https://hub.example/webhook/t', {'X-Webhook-Token': 's'}, '{}')",
            setup,
        )
        self.assertEqual(result, {"ok": True, "status": 200, "body": "ok"})

    def test_post_json_falls_back_to_fetch_when_gm_throws(self):
        # GM_xmlhttpRequest 存在但同步抛错（如某些 iOS 运行器）时也走 fetch 兜底。
        setup = """
context.GM_xmlhttpRequest = () => { throw new Error('boom'); };
context.fetch = async () => ({ ok: true, status: 200, text: async () => 'ok2' });
"""
        result = run_userscript(
            "api.postJson('https://hub.example/webhook/t', {}, '{}')",
            setup,
        )
        self.assertEqual(result, {"ok": True, "status": 200, "body": "ok2"})

    def test_no_tasks_click_opens_manager_instead_of_alert(self):
        # 未配置任务时点击“115”按钮直接打开任务管理器，不再只弹“没有可用任务”，
        # 且任何路径都不会创建全局悬浮窗。
        result = run_userscript(
            """
(async () => {
  const btn = api.createPushButton('magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef');
  btn._listeners.click({ preventDefault() {}, stopPropagation() {} });
  await new Promise((resolve) => setTimeout(resolve, 0));
  return {
    managerOpened: registry.some((el) => el.id === 'mh-manager-overlay'),
    alertShown: registry.some((el) => el.id === 'mh-core-dialog-overlay'),
    fabShown: registry.some((el) => el.id === 'mh-manager-fab')
  };
})()
""",
            DOM_SETUP,
        )
        self.assertTrue(result["managerOpened"])
        self.assertFalse(result["alertShown"])
        self.assertFalse(result["fabShown"])

    def test_task_picker_has_manage_button_and_opens_manager(self):
        # 任务选择器底部有“任务管理”按钮，点击后进入任务管理器。
        result = run_userscript(
            """
(async () => {
  const candidates = [
    { id: 't1', name: '电影', webhookUrl: 'http://x/webhook/电影', savepath: '自存' },
    { id: 't2', name: '剧集', webhookUrl: 'http://x/webhook/剧集', savepath: '剧集' }
  ];
  const pickPromise = api.chooseTask(
    candidates,
    'magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef'
  );
  await new Promise((resolve) => setTimeout(resolve, 0));
  const picker = registry.find((el) => el.id === 'mh-task-picker-overlay');
  const hasManageButton = !!picker
    && picker.innerHTML.includes('任务管理')
    && picker.innerHTML.includes('data-mh-picker-action="manage"');
  const fakeBtn = makeEl('button');
  fakeBtn.dataset.mhPickerAction = 'manage';
  fakeBtn.closest = () => fakeBtn;
  picker._listeners.click({ target: fakeBtn, preventDefault() {} });
  await pickPromise;
  await new Promise((resolve) => setTimeout(resolve, 0));
  return {
    hasManageButton,
    managerOpened: registry.some((el) => el.id === 'mh-manager-overlay')
  };
})()
""",
            DOM_SETUP,
        )
        self.assertTrue(result["hasManageButton"])
        self.assertTrue(result["managerOpened"])

    def test_task_picker_shows_even_with_single_task(self):
        # 即使只有一个任务也必须弹出选择器，否则 iOS 用户无法进入任务管理器。
        result = run_userscript(
            """
(async () => {
  const candidates = [
    { id: 't1', name: '电影', webhookUrl: 'http://x/webhook/电影', savepath: '自存' }
  ];
  const pickPromise = api.chooseTask(
    candidates,
    'magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef'
  );
  await new Promise((resolve) => setTimeout(resolve, 0));
  const picker = registry.find((el) => el.id === 'mh-task-picker-overlay');
  const hasPicker = !!picker;
  const hasManage = !!picker && picker.innerHTML.includes('任务管理');
  const fakeBtn = makeEl('button');
  fakeBtn.dataset.mhPickerAction = 'pick';
  fakeBtn.dataset.taskId = 't1';
  fakeBtn.closest = () => fakeBtn;
  picker._listeners.click({ target: fakeBtn, preventDefault() {} });
  const picked = await pickPromise;
  return {
    hasPicker,
    hasManage,
    pickedId: picked && picked.id
  };
})()
""",
            DOM_SETUP,
        )
        self.assertTrue(result["hasPicker"])
        self.assertTrue(result["hasManage"])
        self.assertEqual(result["pickedId"], "t1")
