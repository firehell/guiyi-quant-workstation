process.env.OPENCLAW_LOG_LEVEL = "FATAL";

import { createRequire } from "node:module";
import {
  closeSync,
  fsyncSync,
  openSync,
  renameSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
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


function validateRecipientList(recipients, fieldName) {
  if (!Array.isArray(recipients)) {
    fail("WEIXIN_ADAPTER_INPUT_INVALID");
  }
  for (const recipient of recipients) {
    requireObject(recipient);
    if (
      Object.keys(recipient).sort().join(",") !== "alias,target"
      || typeof recipient.alias !== "string"
      || typeof recipient.target !== "string"
      || !recipient.target.endsWith("@im.wechat")
    ) {
      fail("WEIXIN_ADAPTER_INPUT_INVALID");
    }
  }
  if (fieldName === "enabled_recipients" && recipients.length === 0) {
    fail("WEIXIN_ADAPTER_INPUT_INVALID");
  }
}


function resolveExactAccount(seam, config, requestedAccountId) {
  const accountIds = seam.listIndexedWeixinAccountIds();
  if (!Array.isArray(accountIds)) fail("WEIXIN_ACCOUNT_UNAVAILABLE");
  const selectedIds = requestedAccountId === null
    ? accountIds
    : accountIds.filter((value) => value === requestedAccountId);
  const ready = selectedIds
    .map((accountId) => seam.resolveWeixinAccount(config, accountId))
    .filter((account) => (
      account !== null
      && typeof account === "object"
      && typeof account.accountId === "string"
      && account.enabled === true
      && account.configured === true
      && typeof account.token === "string"
      && account.token.length > 0
      && typeof account.baseUrl === "string"
      && account.baseUrl.length > 0
    ));
  if (ready.length !== 1 || (requestedAccountId !== null && ready[0].accountId !== requestedAccountId)) {
    fail("WEIXIN_ACCOUNT_UNAVAILABLE");
  }
  return ready[0];
}


async function probe(input) {
  validateProjection(input);
  const seam = await loadPrivateSeam(input.plugin_root);
  const config = await seam.loadConfig();
  const account = resolveExactAccount(seam, config, input.account_id);
  seam.restoreContextTokens(input.account_id);
  for (const recipient of input.enabled_recipients) {
    const contextToken = seam.getContextToken(input.account_id, recipient.target);
    if (typeof contextToken !== "string" || contextToken.length === 0) {
      fail("WEIXIN_CONTEXT_MISSING");
    }
  }
  return { status: "ready", recipient_count: input.enabled_recipients.length };
}


function registrationText(message) {
  return message.item_list?.find((item) => item?.type === 1)?.text_item?.text;
}


async function register(input) {
  if (
    (input.account_id !== null && typeof input.account_id !== "string")
    || typeof input.challenge !== "string"
    || input.challenge.length < 20
    || typeof input.timeout_seconds !== "number"
    || !Number.isFinite(input.timeout_seconds)
    || input.timeout_seconds <= 0
  ) {
    fail("WEIXIN_ADAPTER_INPUT_INVALID");
  }
  validateRecipientList(input.approved_recipients, "approved_recipients");
  const seam = await loadPrivateSeam(input.plugin_root);
  const config = await seam.loadConfig();
  const account = resolveExactAccount(seam, config, input.account_id);
  seam.restoreContextTokens(account.accountId);
  const approvedTargets = new Set(input.approved_recipients.map((item) => item.target));
  const syncPath = seam.getSyncBufFilePath(account.accountId);
  let cursor = seam.loadGetUpdatesBuf(syncPath) ?? "";
  const deadline = Date.now() + input.timeout_seconds * 1000;
  while (Date.now() < deadline) {
    const response = requireObject(await seam.getUpdates({
      baseUrl: account.baseUrl,
      token: account.token,
      timeoutMs: 35_000,
      get_updates_buf: cursor,
    }));
    if (response.ret !== 0 || !Array.isArray(response.msgs)) {
      fail("WEIXIN_ADAPTER_UNAVAILABLE");
    }
    if (typeof response.get_updates_buf === "string") {
      seam.saveGetUpdatesBuf(syncPath, response.get_updates_buf);
      cursor = response.get_updates_buf;
    }
    const candidates = [];
    for (const message of response.msgs) {
      if (message === null || typeof message !== "object") continue;
      const sender = message.from_user_id;
      const contextToken = message.context_token;
      if (
        approvedTargets.has(sender)
        && typeof contextToken === "string"
        && contextToken.length > 0
      ) {
        seam.setContextToken(account.accountId, sender, contextToken);
      }
      const isCandidate = (
        registrationText(message) === input.challenge
        && typeof sender === "string"
        && sender.endsWith("@im.wechat")
        && typeof contextToken === "string"
        && contextToken.length > 0
      );
      if (isCandidate) candidates.push({ target: sender, contextToken });
    }
    if (candidates.length > 1) fail("WEIXIN_REGISTRATION_AMBIGUOUS");
    if (candidates.length === 1) {
      const candidate = candidates[0];
      seam.setContextToken(account.accountId, candidate.target, candidate.contextToken);
      return {
        status: "registered",
        account_id: account.accountId,
        target: candidate.target,
      };
    }
  }
  fail("WEIXIN_REGISTRATION_TIMEOUT");
}


function writeMonitorStatus(statusPath, status) {
  const parent = path.dirname(statusPath);
  const temporary = path.join(parent, `.${path.basename(statusPath)}.${process.pid}.${Date.now()}.tmp`);
  let fileDescriptor;
  try {
    fileDescriptor = openSync(temporary, "wx", 0o600);
    writeFileSync(fileDescriptor, `${JSON.stringify(status)}\n`, "utf8");
    fsyncSync(fileDescriptor);
    closeSync(fileDescriptor);
    fileDescriptor = undefined;
    renameSync(temporary, statusPath);
    const directoryDescriptor = openSync(parent, "r");
    try {
      fsyncSync(directoryDescriptor);
    } finally {
      closeSync(directoryDescriptor);
    }
  } catch (error) {
    if (fileDescriptor !== undefined) closeSync(fileDescriptor);
    try { unlinkSync(temporary); } catch {}
    throw error;
  }
}


function monitorStatus(recipientCount, state, lastPollAt, lastRefreshAt, errorCode) {
  return {
    schema_version: 1,
    status: state,
    recipient_count: recipientCount,
    last_poll_at: lastPollAt,
    last_context_refresh_at: lastRefreshAt,
    last_error_code: errorCode,
  };
}


function interruptibleDelay(milliseconds, state) {
  if (state.stopping) return Promise.resolve();
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, milliseconds);
    state.wakeDelay = () => {
      clearTimeout(timer);
      resolve();
    };
  }).finally(() => { state.wakeDelay = undefined; });
}


async function monitor(input) {
  if (
    typeof input.account_id !== "string"
    || typeof input.status_path !== "string"
    || !path.isAbsolute(input.status_path)
  ) {
    fail("WEIXIN_ADAPTER_INPUT_INVALID");
  }
  validateRecipientList(input.approved_recipients, "enabled_recipients");
  const seam = await loadPrivateSeam(input.plugin_root);
  let config = await seam.loadConfig();
  let account = resolveExactAccount(seam, config, input.account_id);
  seam.restoreContextTokens(account.accountId);
  const approvedTargets = new Set(input.approved_recipients.map((item) => item.target));
  const syncPath = seam.getSyncBufFilePath(account.accountId);
  let cursor = seam.loadGetUpdatesBuf(syncPath) ?? "";
  let lastPollAt = null;
  let lastRefreshAt = null;
  let backoffIndex = 0;
  const transportBackoffs = [2_000, 5_000, 15_000, 30_000];
  const state = { stopping: false, wakeDelay: undefined, controller: undefined };
  const requestStop = () => {
    state.stopping = true;
    state.controller?.abort();
    state.wakeDelay?.();
  };
  process.once("SIGTERM", requestStop);
  process.once("SIGINT", requestStop);
  try {
    try {
      await seam.notifyStart({ baseUrl: account.baseUrl, token: account.token });
    } catch {
      // Provider lifecycle notification is best-effort and never user-visible.
    }
    while (!state.stopping) {
      state.controller = new AbortController();
      let response;
      try {
        response = requireObject(await seam.getUpdates({
          baseUrl: account.baseUrl,
          token: account.token,
          timeoutMs: 35_000,
          get_updates_buf: cursor,
          abortSignal: state.controller.signal,
        }));
      } catch {
        if (state.stopping) break;
        writeMonitorStatus(input.status_path, monitorStatus(
          input.approved_recipients.length,
          "degraded",
          lastPollAt,
          lastRefreshAt,
          "WEIXIN_CONTEXT_TRANSPORT_ERROR",
        ));
        const delay = transportBackoffs[Math.min(backoffIndex, transportBackoffs.length - 1)];
        backoffIndex += 1;
        await interruptibleDelay(delay, state);
        continue;
      } finally {
        state.controller = undefined;
      }
      if (state.stopping) break;
      if (response.ret === -14 || response.errcode === -14) {
        writeMonitorStatus(input.status_path, monitorStatus(
          input.approved_recipients.length,
          "degraded",
          lastPollAt,
          lastRefreshAt,
          "WEIXIN_CONTEXT_TOKEN_STALE",
        ));
        const staleToken = account.token;
        await interruptibleDelay(60_000, state);
        if (state.stopping) break;
        try {
          config = await seam.loadConfig();
          const candidate = resolveExactAccount(seam, config, input.account_id);
          if (candidate.token !== staleToken) account = candidate;
        } catch {
          // Stay degraded and reread the same account after the next fixed interval.
        }
        continue;
      }
      if (response.ret !== 0 || !Array.isArray(response.msgs)) {
        writeMonitorStatus(input.status_path, monitorStatus(
          input.approved_recipients.length,
          "degraded",
          lastPollAt,
          lastRefreshAt,
          "WEIXIN_CONTEXT_API_ERROR",
        ));
        await interruptibleDelay(30_000, state);
        continue;
      }
      if (typeof response.get_updates_buf === "string") {
        seam.saveGetUpdatesBuf(syncPath, response.get_updates_buf);
        cursor = response.get_updates_buf;
      }
      let refreshed = false;
      for (const message of response.msgs) {
        if (message === null || typeof message !== "object") continue;
        const sender = message.from_user_id;
        const contextToken = message.context_token;
        if (
          approvedTargets.has(sender)
          && typeof contextToken === "string"
          && contextToken.length > 0
        ) {
          seam.setContextToken(account.accountId, sender, contextToken);
          refreshed = true;
        }
      }
      lastPollAt = new Date().toISOString();
      if (refreshed) lastRefreshAt = lastPollAt;
      backoffIndex = 0;
      writeMonitorStatus(input.status_path, monitorStatus(
        input.approved_recipients.length,
        "ok",
        lastPollAt,
        lastRefreshAt,
        null,
      ));
    }
  } finally {
    try {
      await seam.notifyStop({ baseUrl: account.baseUrl, token: account.token });
    } catch {
      // Best-effort lifecycle stop only.
    }
  }
}


async function main() {
  const command = process.argv[2];
  const input = await readInput();
  if (command === "probe" && Object.keys(input).sort().join(",") === "account_id,enabled_recipients,plugin_root") {
    return probe(input);
  }
  if (
    command === "register"
    && Object.keys(input).sort().join(",") === "account_id,approved_recipients,challenge,plugin_root,timeout_seconds"
  ) {
    return register(input);
  }
  if (
    command === "monitor"
    && Object.keys(input).sort().join(",") === "account_id,approved_recipients,plugin_root,status_path"
  ) {
    await monitor(input);
    return undefined;
  }
  {
    fail("WEIXIN_ADAPTER_INPUT_INVALID");
  }
}


try {
  const result = await main();
  if (result !== undefined) process.stdout.write(`${JSON.stringify(result)}\n`);
} catch (error) {
  const code = error instanceof AdapterFailure ? error.code : "WEIXIN_ADAPTER_INCOMPATIBLE";
  process.stdout.write(`${JSON.stringify({ status: "failed", error_code: code })}\n`);
  process.exitCode = 1;
}
