import { readFile, lstat, realpath } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";


const MODULE_PATHS = Object.freeze({
  accounts: "dist/src/auth/accounts.js",
  inbound: "dist/src/messaging/inbound.js",
  send: "dist/src/messaging/send.js",
});
const MANIFEST_KEYS = new Set([
  "schema_version",
  "openclaw_version",
  "openclaw_weixin_version",
  "node_version",
  "plugin_modules",
]);
const MAX_CONTEXT_CANDIDATES = 64;
const MAX_CONTEXT_SNAPSHOT_BYTES = 65536;
const ACTION_KEYS = Object.freeze({
  discover_owner: new Set(["action"]),
  snapshot_contexts: new Set(["action"]),
  probe: new Set(["action", "recipient_alias", "account_id", "target_user_id"]),
  send: new Set(["action", "recipient_alias", "account_id", "target_user_id", "text"]),
});


class PublicError extends Error {
  constructor(code) {
    super(code);
    this.code = code;
  }
}


function fail(code) {
  throw new PublicError(code);
}


async function readInput() {
  let raw = "";
  for await (const chunk of process.stdin) {
    raw += chunk;
    if (raw.length > 65536) fail("CLAWBOT_INPUT_INVALID");
  }
  let value;
  try {
    value = JSON.parse(raw);
  } catch {
    fail("CLAWBOT_INPUT_INVALID");
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) fail("CLAWBOT_INPUT_INVALID");
  const allowedKeys = Object.hasOwn(ACTION_KEYS, value.action) ? ACTION_KEYS[value.action] : null;
  if (
    !allowedKeys ||
    Object.keys(value).length !== allowedKeys.size ||
    Object.keys(value).some((key) => !allowedKeys.has(key))
  ) {
    fail("CLAWBOT_INPUT_INVALID");
  }
  return value;
}


function isPrivateText(value) {
  return typeof value === "string" && Boolean(value) && value.trim() === value && !/\p{C}/u.test(value);
}


function requirePrivateText(value) {
  if (!isPrivateText(value)) {
    fail("CLAWBOT_INPUT_INVALID");
  }
  return value;
}


function requireRecipientAlias(value) {
  if (typeof value !== "string" || !/^[a-z][a-z0-9_-]{0,31}$/u.test(value)) {
    fail("CLAWBOT_INPUT_INVALID");
  }
  return value;
}


function requireMessageText(value) {
  if (
    typeof value !== "string" ||
    !value ||
    value.trim() !== value ||
    /[\u0000-\u0009\u000b-\u001f\u007f-\u009f]/u.test(value)
  ) {
    fail("CLAWBOT_INPUT_INVALID");
  }
  return value;
}


async function requireRegularFile(file) {
  const metadata = await lstat(file);
  if (!metadata.isFile() || metadata.isSymbolicLink()) fail("CLAWBOT_DEPENDENCY_INVALID");
}


async function loadDependency() {
  const rootInput = process.env.GUIYI_OPENCLAW_WEIXIN_PLUGIN_ROOT;
  const manifestInput = process.env.GUIYI_CLAWBOT_VERSIONS_PATH;
  if (!rootInput || !manifestInput || !path.isAbsolute(rootInput) || !path.isAbsolute(manifestInput)) {
    fail("CLAWBOT_DEPENDENCY_INVALID");
  }
  const rootMetadata = await lstat(rootInput);
  if (!rootMetadata.isDirectory() || rootMetadata.isSymbolicLink()) fail("CLAWBOT_DEPENDENCY_INVALID");
  await requireRegularFile(manifestInput);
  const root = await realpath(rootInput);
  const manifestPath = await realpath(manifestInput);
  let manifest;
  try {
    manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  } catch {
    fail("CLAWBOT_DEPENDENCY_INVALID");
  }
  if (
    !manifest ||
    typeof manifest !== "object" ||
    Array.isArray(manifest) ||
    Object.keys(manifest).length !== MANIFEST_KEYS.size ||
    Object.keys(manifest).some((key) => !MANIFEST_KEYS.has(key)) ||
    manifest.schema_version !== 1 ||
    typeof manifest.openclaw_version !== "string" ||
    !manifest.openclaw_version ||
    typeof manifest.openclaw_weixin_version !== "string" ||
    !manifest.openclaw_weixin_version ||
    manifest.node_version !== process.version ||
    !manifest.plugin_modules ||
    typeof manifest.plugin_modules !== "object" ||
    Array.isArray(manifest.plugin_modules) ||
    Object.keys(MODULE_PATHS).some((key) => manifest.plugin_modules[key] !== MODULE_PATHS[key]) ||
    Object.keys(manifest.plugin_modules).length !== Object.keys(MODULE_PATHS).length
  ) {
    fail("CLAWBOT_DEPENDENCY_INVALID");
  }
  await requireRegularFile(path.join(root, "package.json"));
  let packageJson;
  try {
    packageJson = JSON.parse(await readFile(path.join(root, "package.json"), "utf8"));
  } catch {
    fail("CLAWBOT_DEPENDENCY_INVALID");
  }
  if (packageJson.version !== manifest.openclaw_weixin_version) fail("CLAWBOT_DEPENDENCY_INVALID");

  const resolved = {};
  for (const [name, relative] of Object.entries(MODULE_PATHS)) {
    const candidate = path.join(root, relative);
    await requireRegularFile(candidate);
    const exact = await realpath(candidate);
    if (exact !== path.join(root, relative) || !exact.startsWith(`${root}${path.sep}`)) {
      fail("CLAWBOT_DEPENDENCY_INVALID");
    }
    resolved[name] = exact;
  }
  let accounts;
  let inbound;
  let send;
  try {
    accounts = await import(pathToFileURL(resolved.accounts).href);
    inbound = await import(pathToFileURL(resolved.inbound).href);
    send = await import(pathToFileURL(resolved.send).href);
  } catch {
    fail("CLAWBOT_DEPENDENCY_INVALID");
  }
  if (
    typeof accounts.listIndexedWeixinAccountIds !== "function" ||
    typeof accounts.loadWeixinAccount !== "function" ||
    typeof accounts.DEFAULT_BASE_URL !== "string" ||
    typeof inbound.restoreContextTokens !== "function" ||
    typeof inbound.getContextToken !== "function" ||
    typeof send.sendMessageWeixin !== "function"
  ) {
    fail("CLAWBOT_DEPENDENCY_INVALID");
  }
  return { accounts, inbound, send };
}


async function discoverOwner(dependency) {
  const ids = await dependency.accounts.listIndexedWeixinAccountIds();
  if (!Array.isArray(ids) || ids.length !== 1 || !isPrivateText(ids[0])) {
    fail("CLAWBOT_OWNER_UNAVAILABLE");
  }
  const account = await dependency.accounts.loadWeixinAccount(ids[0]);
  if (
    !account ||
    typeof account.token !== "string" ||
    !account.token.trim() ||
    !isPrivateText(account.userId) ||
    !account.userId.endsWith("@im.wechat")
  ) {
    fail("CLAWBOT_OWNER_UNAVAILABLE");
  }
  await dependency.inbound.restoreContextTokens(ids[0]);
  const contextToken = await dependency.inbound.getContextToken(ids[0], account.userId);
  if (typeof contextToken !== "string" || !contextToken.trim()) fail("CLAWBOT_CONTEXT_UNAVAILABLE");
  return {
    status: "ready",
    action: "discover_owner",
    account_count: 1,
    owner_candidate_count: 1,
    context_available: true,
    account_id: ids[0],
    target_user_id: account.userId,
  };
}


async function snapshotContexts(dependency) {
  const ids = await dependency.accounts.listIndexedWeixinAccountIds();
  if (!Array.isArray(ids) || ids.length !== 1 || !isPrivateText(ids[0])) {
    fail("CLAWBOT_CONTEXT_UNAVAILABLE");
  }
  const account = await dependency.accounts.loadWeixinAccount(ids[0]);
  if (
    !account ||
    typeof account.token !== "string" ||
    !account.token.trim() ||
    !isPrivateText(account.userId) ||
    !account.userId.endsWith("@im.wechat")
  ) {
    fail("CLAWBOT_CONTEXT_UNAVAILABLE");
  }
  const stateInput = process.env.OPENCLAW_STATE_DIR;
  if (!stateInput || !path.isAbsolute(stateInput)) fail("CLAWBOT_CONTEXT_UNAVAILABLE");
  try {
    const stateMetadata = await lstat(stateInput);
    if (!stateMetadata.isDirectory() || stateMetadata.isSymbolicLink()) {
      fail("CLAWBOT_CONTEXT_UNAVAILABLE");
    }
    const state = await realpath(stateInput);
    const accountsRoot = path.join(state, "openclaw-weixin", "accounts");
    const contextPath = path.join(accountsRoot, `${ids[0]}.context-tokens.json`);
    await requireRegularFile(contextPath);
    const exact = await realpath(contextPath);
    if (exact !== contextPath || !exact.startsWith(`${accountsRoot}${path.sep}`)) {
      fail("CLAWBOT_CONTEXT_UNAVAILABLE");
    }
    const metadata = await lstat(exact);
    if (metadata.size > MAX_CONTEXT_SNAPSHOT_BYTES) fail("CLAWBOT_CONTEXT_UNAVAILABLE");
    const stored = JSON.parse(await readFile(exact, "utf8"));
    if (!stored || typeof stored !== "object" || Array.isArray(stored)) {
      fail("CLAWBOT_CONTEXT_UNAVAILABLE");
    }
    const entries = Object.entries(stored);
    if (entries.length > MAX_CONTEXT_CANDIDATES) fail("CLAWBOT_CONTEXT_UNAVAILABLE");
    const contexts = entries.map(([userId, contextToken]) => {
      if (
        !isPrivateText(userId) ||
        !userId.endsWith("@im.wechat") ||
        userId === "@im.wechat" ||
        !isPrivateText(contextToken)
      ) {
        fail("CLAWBOT_CONTEXT_UNAVAILABLE");
      }
      return { user_id: userId, context_token: contextToken };
    });
    contexts.sort((left, right) => {
      if (left.user_id < right.user_id) return -1;
      if (left.user_id > right.user_id) return 1;
      return 0;
    });
    return {
      status: "ready",
      action: "snapshot_contexts",
      account_id: ids[0],
      contexts,
    };
  } catch (error) {
    if (error instanceof PublicError) throw error;
    fail("CLAWBOT_CONTEXT_UNAVAILABLE");
  }
}


async function loadFrozenRecipient(dependency, input) {
  const recipientAlias = requireRecipientAlias(input.recipient_alias);
  const accountId = requirePrivateText(input.account_id);
  const targetUserId = requirePrivateText(input.target_user_id);
  if (!targetUserId.endsWith("@im.wechat") || targetUserId === "@im.wechat") {
    fail("CLAWBOT_OWNER_INVALID");
  }
  const account = await dependency.accounts.loadWeixinAccount(accountId);
  if (
    !account ||
    typeof account.token !== "string" ||
    !account.token.trim() ||
    !isPrivateText(account.userId) ||
    !account.userId.endsWith("@im.wechat")
  ) {
    fail("CLAWBOT_OWNER_INVALID");
  }
  if (recipientAlias === "owner" && account.userId !== targetUserId) {
    fail("CLAWBOT_OWNER_INVALID");
  }
  await dependency.inbound.restoreContextTokens(accountId);
  const contextToken = await dependency.inbound.getContextToken(accountId, targetUserId);
  if (!isPrivateText(contextToken)) fail("CLAWBOT_CONTEXT_UNAVAILABLE");
  return { account, accountId, targetUserId, contextToken };
}


async function execute() {
  const input = await readInput();
  const dependency = await loadDependency();
  if (input.action === "discover_owner") return discoverOwner(dependency);
  if (input.action === "snapshot_contexts") return snapshotContexts(dependency);
  const recipient = await loadFrozenRecipient(dependency, input);
  if (input.action === "probe") {
    return { status: "ready", action: "probe", account_configured: true, context_available: true };
  }
  const text = requireMessageText(input.text);
  try {
    await dependency.send.sendMessageWeixin({
      to: recipient.targetUserId,
      text,
      opts: {
        baseUrl: recipient.account.baseUrl?.trim() || dependency.accounts.DEFAULT_BASE_URL,
        token: recipient.account.token,
        contextToken: recipient.contextToken,
      },
    });
  } catch {
    fail("CLAWBOT_SEND_FAILED");
  }
  return { status: "accepted", action: "send" };
}


try {
  const result = await execute();
  process.stdout.write(JSON.stringify(result));
} catch (error) {
  const code = error instanceof PublicError ? error.code : "CLAWBOT_DEPENDENCY_INVALID";
  process.stdout.write(JSON.stringify({ status: "error", error: code }));
  process.exitCode = 1;
}
