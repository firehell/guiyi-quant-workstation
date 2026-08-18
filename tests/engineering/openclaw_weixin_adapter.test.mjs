import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
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
export async function getUpdates() { throw new Error("probe called getUpdates"); }
export async function notifyStart() { throw new Error("probe called notifyStart"); }
export async function notifyStop() { throw new Error("probe called notifyStop"); }
`,
  );
  await writeModule(
    path.join(root, "dist/src/storage/sync-buf.js"),
    `
export function getSyncBufFilePath() { return "unused"; }
export function loadGetUpdatesBuf() { return ""; }
export function saveGetUpdatesBuf() { throw new Error("probe saved cursor"); }
`,
  );
  await writeModule(
    path.join(root, "dist/src/messaging/inbound.js"),
    `
export function restoreContextTokens() {}
export function getContextToken(_accountId, target) {
  return target === "u1@im.wechat" || target === "u2@im.wechat" ? "context-fixture" : undefined;
}
export function setContextToken() { throw new Error("probe set context"); }
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


function runAdapter(pluginRoot, input) {
  return spawnSync(process.execPath, [ADAPTER, "probe"], {
    input: JSON.stringify({ plugin_root: pluginRoot, ...input }),
    encoding: "utf8",
    env: { ...process.env, OPENCLAW_LOG_LEVEL: "FATAL" },
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
