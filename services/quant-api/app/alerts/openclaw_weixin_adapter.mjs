process.env.OPENCLAW_LOG_LEVEL = "FATAL";

import { createRequire } from "node:module";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";


const PLUGIN_NAME = "@tencent-weixin/openclaw-weixin";
const PLUGIN_VERSION = "2.4.6";
const MODULES = Object.freeze({
  accounts: "dist/src/auth/accounts.js",
  api: "dist/src/api/api.js",
  syncBuffer: "dist/src/storage/sync-buf.js",
  inbound: "dist/src/messaging/inbound.js",
  send: "dist/src/messaging/send.js",
});


class AdapterFailure extends Error {
  constructor(code) {
    super(code);
    this.code = code;
  }
}


function fail(code) {
  throw new AdapterFailure(code);
}


function requireObject(value) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    fail("WEIXIN_ADAPTER_INPUT_INVALID");
  }
  return value;
}


async function readInput() {
  let text = "";
  for await (const chunk of process.stdin) {
    text += chunk;
    if (text.length > 65_536) {
      fail("WEIXIN_ADAPTER_INPUT_INVALID");
    }
  }
  try {
    return requireObject(JSON.parse(text));
  } catch (error) {
    if (error instanceof AdapterFailure) throw error;
    fail("WEIXIN_ADAPTER_INPUT_INVALID");
  }
}


function requireFunction(module, name) {
  if (typeof module[name] !== "function") {
    fail("WEIXIN_ADAPTER_INCOMPATIBLE");
  }
  return module[name];
}


async function importExactModule(pluginRoot, relativePath) {
  const modulePath = path.resolve(pluginRoot, relativePath);
  if (path.relative(pluginRoot, modulePath).startsWith("..")) {
    fail("WEIXIN_ADAPTER_INCOMPATIBLE");
  }
  return import(pathToFileURL(modulePath).href);
}


async function loadPrivateSeam(pluginRoot) {
  if (typeof pluginRoot !== "string" || !path.isAbsolute(pluginRoot)) {
    fail("WEIXIN_ADAPTER_INPUT_INVALID");
  }
  const manifest = requireObject(JSON.parse(await readFile(path.join(pluginRoot, "package.json"), "utf8")));
  if (manifest.name !== PLUGIN_NAME || manifest.version !== PLUGIN_VERSION) {
    fail("WEIXIN_ADAPTER_INCOMPATIBLE");
  }
  const pluginRequire = createRequire(path.join(pluginRoot, "package.json"));
  const configRuntimePath = pluginRequire.resolve("openclaw/plugin-sdk/config-runtime");
  const [configRuntime, accounts, api, syncBuffer, inbound, send] = await Promise.all([
    import(pathToFileURL(configRuntimePath).href),
    importExactModule(pluginRoot, MODULES.accounts),
    importExactModule(pluginRoot, MODULES.api),
    importExactModule(pluginRoot, MODULES.syncBuffer),
    importExactModule(pluginRoot, MODULES.inbound),
    importExactModule(pluginRoot, MODULES.send),
  ]);
  return {
    loadConfig: requireFunction(configRuntime, "loadConfig"),
    listIndexedWeixinAccountIds: requireFunction(accounts, "listIndexedWeixinAccountIds"),
    resolveWeixinAccount: requireFunction(accounts, "resolveWeixinAccount"),
    getUpdates: requireFunction(api, "getUpdates"),
    notifyStart: requireFunction(api, "notifyStart"),
    notifyStop: requireFunction(api, "notifyStop"),
    getSyncBufFilePath: requireFunction(syncBuffer, "getSyncBufFilePath"),
    loadGetUpdatesBuf: requireFunction(syncBuffer, "loadGetUpdatesBuf"),
    saveGetUpdatesBuf: requireFunction(syncBuffer, "saveGetUpdatesBuf"),
    restoreContextTokens: requireFunction(inbound, "restoreContextTokens"),
    getContextToken: requireFunction(inbound, "getContextToken"),
    setContextToken: requireFunction(inbound, "setContextToken"),
    sendMessageWeixin: requireFunction(send, "sendMessageWeixin"),
  };
}


function validateProjection(input) {
  if (
    typeof input.account_id !== "string"
    || !Array.isArray(input.enabled_recipients)
    || input.enabled_recipients.length === 0
  ) {
    fail("WEIXIN_ADAPTER_INPUT_INVALID");
  }
  for (const recipient of input.enabled_recipients) {
    requireObject(recipient);
    if (
      Object.keys(recipient).sort().join(",") !== "alias,target"
      || typeof recipient.alias !== "string"
      || typeof recipient.target !== "string"
    ) {
      fail("WEIXIN_ADAPTER_INPUT_INVALID");
    }
  }
}


async function probe(input) {
  validateProjection(input);
  const seam = await loadPrivateSeam(input.plugin_root);
  const config = await seam.loadConfig();
  const accountIds = seam.listIndexedWeixinAccountIds();
  if (!Array.isArray(accountIds) || !accountIds.includes(input.account_id)) {
    fail("WEIXIN_ACCOUNT_UNAVAILABLE");
  }
  const account = seam.resolveWeixinAccount(config, input.account_id);
  if (
    account === null
    || typeof account !== "object"
    || account.accountId !== input.account_id
    || account.enabled !== true
    || account.configured !== true
    || typeof account.token !== "string"
    || account.token.length === 0
    || typeof account.baseUrl !== "string"
    || account.baseUrl.length === 0
  ) {
    fail("WEIXIN_ACCOUNT_UNAVAILABLE");
  }
  seam.restoreContextTokens(input.account_id);
  for (const recipient of input.enabled_recipients) {
    const contextToken = seam.getContextToken(input.account_id, recipient.target);
    if (typeof contextToken !== "string" || contextToken.length === 0) {
      fail("WEIXIN_CONTEXT_MISSING");
    }
  }
  return { status: "ready", recipient_count: input.enabled_recipients.length };
}


async function main() {
  const command = process.argv[2];
  const input = await readInput();
  if (command !== "probe" || Object.keys(input).sort().join(",") !== "account_id,enabled_recipients,plugin_root") {
    fail("WEIXIN_ADAPTER_INPUT_INVALID");
  }
  return probe(input);
}


try {
  const result = await main();
  process.stdout.write(`${JSON.stringify(result)}\n`);
} catch (error) {
  const code = error instanceof AdapterFailure ? error.code : "WEIXIN_ADAPTER_INCOMPATIBLE";
  process.stdout.write(`${JSON.stringify({ status: "failed", error_code: code })}\n`);
  process.exitCode = 1;
}
