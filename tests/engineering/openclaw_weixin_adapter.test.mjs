import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";


const REPO_ROOT = path.resolve(import.meta.dirname, "../..");
const ADAPTER = path.join(
  REPO_ROOT,
  "services/quant-api/app/alerts/openclaw_weixin_adapter.mjs",
);


async function writeModule(filePath, source) {
  await mkdir(path.dirname(filePath), { recursive: true });
  await writeFile(filePath, source, "utf8");
}


async function fakePluginTree({ missingSend = false } = {}) {
  const root = await mkdtemp(path.join(os.tmpdir(), "guiyi-weixin-plugin-"));
  await writeFile(
    path.join(root, "package.json"),
    JSON.stringify({ name: "@tencent-weixin/openclaw-weixin", version: "2.4.6", type: "module" }),
  );
  await writeModule(
    path.join(root, "node_modules/openclaw/package.json"),
    JSON.stringify({
      name: "openclaw",
      version: "2026.8.1",
      type: "module",
      exports: { "./plugin-sdk/config-runtime": "./config-runtime.js" },
    }),
  );
  await writeModule(
    path.join(root, "node_modules/openclaw/config-runtime.js"),
    "export async function loadConfig() { return { channels: { 'openclaw-weixin': {} } }; }\n",
  );
  await writeModule(
    path.join(root, "dist/src/auth/accounts.js"),
    `
export function listIndexedWeixinAccountIds() { return ["account-fixture"]; }
export function resolveWeixinAccount(_cfg, accountId) {
  return { accountId, enabled: true, configured: true, token: "token-fixture", baseUrl: "https://fixture.invalid" };
}
`,
  );
  await writeModule(
    path.join(root, "dist/src/api/api.js"),
    `
import { appendFileSync } from "node:fs";
const updates = JSON.parse(process.env.FAKE_UPDATES || "[]");
export async function getUpdates() {
  appendFileSync(process.env.FAKE_LOG, "getUpdates\\n");
  const next = updates.shift();
  if (next) return next;
  await new Promise((resolve) => setTimeout(resolve, 20));
  return { ret: 0, msgs: [], get_updates_buf: "idle" };
}
export async function notifyStart() { throw new Error("probe called notifyStart"); }
export async function notifyStop() { throw new Error("probe called notifyStop"); }
`,
  );
  await writeModule(
    path.join(root, "dist/src/storage/sync-buf.js"),
    `
import { appendFileSync } from "node:fs";
export function getSyncBufFilePath() { return "cursor-fixture"; }
export function loadGetUpdatesBuf() { return "cursor-start"; }
export function saveGetUpdatesBuf(_path, value) { appendFileSync(process.env.FAKE_LOG, "save:" + value + "\\n"); }
`,
  );
  await writeModule(
    path.join(root, "dist/src/messaging/inbound.js"),
    `
import { appendFileSync } from "node:fs";
export function restoreContextTokens() {}
export function getContextToken(_accountId, target) {
  return target === "u1@im.wechat" || target === "u2@im.wechat" ? "context-fixture" : undefined;
}
export function setContextToken(_account, target, _token) { appendFileSync(process.env.FAKE_LOG, "context:" + target + "\\n"); }
`,
  );
  await writeModule(
    path.join(root, "dist/src/messaging/send.js"),
    missingSend
      ? "export const wrongExport = true;\n"
      : "export async function sendMessageWeixin() { throw new Error('probe sent'); }\n",
  );
  return root;
}


function runAdapter(pluginRoot, input, { command = "probe", env = {} } = {}) {
  return spawnSync(process.execPath, [ADAPTER, command], {
    input: JSON.stringify({ plugin_root: pluginRoot, ...input }),
    encoding: "utf8",
    env: { ...process.env, OPENCLAW_LOG_LEVEL: "FATAL", ...env },
  });
}


test("probe requires exact account readiness and all enabled contexts without I/O", async () => {
  const pluginRoot = await fakePluginTree();
  const result = runAdapter(pluginRoot, {
    account_id: "account-fixture",
    enabled_recipients: [
      { alias: "owner", target: "u1@im.wechat" },
      { alias: "member_2", target: "u2@im.wechat" },
    ],
  });

  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(result.stdout), { status: "ready", recipient_count: 2 });
  assert.equal(result.stderr, "");
});


test("probe fails closed when exact private module shape changes", async () => {
  const pluginRoot = await fakePluginTree({ missingSend: true });
  const result = runAdapter(pluginRoot, {
    account_id: "account-fixture",
    enabled_recipients: [{ alias: "owner", target: "u1@im.wechat" }],
  });

  assert.equal(result.status, 1);
  assert.deepEqual(JSON.parse(result.stdout), {
    status: "failed",
    error_code: "WEIXIN_ADAPTER_INCOMPATIBLE",
  });
  assert.equal(result.stderr, "");
});


function message(from, text, context = "context-new") {
  return {
    from_user_id: from,
    context_token: context,
    item_list: [{ type: 1, text_item: { text } }],
  };
}

const EXACT_CHALLENGE = "exact-challenge-value-123";


test("register saves cursor first, refreshes approved context, and matches exact challenge", async () => {
  const pluginRoot = await fakePluginTree();
  const logPath = path.join(pluginRoot, "events.log");
  await writeFile(logPath, "");
  const updates = [{
    ret: 0,
    get_updates_buf: "cursor-next",
    msgs: [
      message("unknown@im.wechat", "wrong"),
      message("u1@im.wechat", "ordinary approved message", "approved-context"),
      message("candidate@im.wechat", EXACT_CHALLENGE, "candidate-context"),
    ],
  }];
  const result = runAdapter(pluginRoot, {
    account_id: "account-fixture",
    approved_recipients: [{ alias: "owner", target: "u1@im.wechat" }],
    challenge: EXACT_CHALLENGE,
    timeout_seconds: 1,
  }, {
    command: "register",
    env: { FAKE_LOG: logPath, FAKE_UPDATES: JSON.stringify(updates) },
  });

  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(result.stdout), {
    status: "registered",
    account_id: "account-fixture",
    target: "candidate@im.wechat",
  });
  assert.deepEqual((await readFile(logPath, "utf8")).trim().split("\n"), [
    "getUpdates",
    "save:cursor-next",
    "context:u1@im.wechat",
    "context:candidate@im.wechat",
  ]);
});


test("register fails ambiguous without persisting either matching context", async () => {
  const pluginRoot = await fakePluginTree();
  const logPath = path.join(pluginRoot, "events.log");
  await writeFile(logPath, "");
  const result = runAdapter(pluginRoot, {
    account_id: "account-fixture",
    approved_recipients: [],
    challenge: EXACT_CHALLENGE,
    timeout_seconds: 1,
  }, {
    command: "register",
    env: {
      FAKE_LOG: logPath,
      FAKE_UPDATES: JSON.stringify([{
        ret: 0,
        get_updates_buf: "cursor-next",
        msgs: [
          message("first@im.wechat", EXACT_CHALLENGE),
          message("second@im.wechat", EXACT_CHALLENGE),
        ],
      }]),
    },
  });

  assert.equal(result.status, 1);
  assert.deepEqual(JSON.parse(result.stdout), {
    status: "failed",
    error_code: "WEIXIN_REGISTRATION_AMBIGUOUS",
  });
  assert.equal((await readFile(logPath, "utf8")).includes("context:"), false);
});


test("register ignores missing-context and invalid sender then times out", async () => {
  const pluginRoot = await fakePluginTree();
  const logPath = path.join(pluginRoot, "events.log");
  await writeFile(logPath, "");
  const result = runAdapter(pluginRoot, {
    account_id: "account-fixture",
    approved_recipients: [],
    challenge: EXACT_CHALLENGE,
    timeout_seconds: 0.04,
  }, {
    command: "register",
    env: {
      FAKE_LOG: logPath,
      FAKE_UPDATES: JSON.stringify([{
        ret: 0,
        get_updates_buf: "cursor-next",
        msgs: [
          message("invalid-group-id", EXACT_CHALLENGE),
          message("missing@im.wechat", EXACT_CHALLENGE, ""),
        ],
      }]),
    },
  });

  assert.equal(result.status, 1);
  assert.deepEqual(JSON.parse(result.stdout), {
    status: "failed",
    error_code: "WEIXIN_REGISTRATION_TIMEOUT",
  });
  assert.equal((await readFile(logPath, "utf8")).includes("context:"), false);
});
