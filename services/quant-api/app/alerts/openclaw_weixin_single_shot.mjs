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
  if (!new Set(["discover_owner", "probe", "send"]).has(value.action)) fail("CLAWBOT_INPUT_INVALID");
  return value;
}


function requirePrivateText(value) {
  if (typeof value !== "string" || !value || value.trim() !== value || /[\u0000-\u001f\u007f]/u.test(value)) {
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
  if (!Array.isArray(ids) || ids.length !== 1 || typeof ids[0] !== "string" || !ids[0]) {
    fail("CLAWBOT_OWNER_UNAVAILABLE");
  }
  const account = await dependency.accounts.loadWeixinAccount(ids[0]);
  if (
    !account ||
    typeof account.token !== "string" ||
    !account.token.trim() ||
    typeof account.userId !== "string" ||
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


async function loadFrozenOwner(dependency, input) {
  const accountId = requirePrivateText(input.account_id);
  const targetUserId = requirePrivateText(input.target_user_id);
  if (!targetUserId.endsWith("@im.wechat")) fail("CLAWBOT_OWNER_INVALID");
  const account = await dependency.accounts.loadWeixinAccount(accountId);
  if (
    !account ||
    typeof account.token !== "string" ||
    !account.token.trim() ||
    account.userId !== targetUserId
  ) {
    fail("CLAWBOT_OWNER_INVALID");
  }
  await dependency.inbound.restoreContextTokens(accountId);
  const contextToken = await dependency.inbound.getContextToken(accountId, targetUserId);
  if (typeof contextToken !== "string" || !contextToken.trim()) fail("CLAWBOT_CONTEXT_UNAVAILABLE");
  return { account, accountId, targetUserId, contextToken };
}


async function execute() {
  const input = await readInput();
  const dependency = await loadDependency();
  if (input.action === "discover_owner") return discoverOwner(dependency);
  const owner = await loadFrozenOwner(dependency, input);
  if (input.action === "probe") {
    return { status: "ready", action: "probe", account_configured: true, context_available: true };
  }
  const text = requirePrivateText(input.text);
  try {
    await dependency.send.sendMessageWeixin({
      to: owner.targetUserId,
      text,
      opts: {
        baseUrl: owner.account.baseUrl?.trim() || dependency.accounts.DEFAULT_BASE_URL,
        token: owner.account.token,
        contextToken: owner.contextToken,
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
