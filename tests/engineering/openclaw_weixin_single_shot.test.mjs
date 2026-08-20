import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";


const PROJECT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SEAM = path.join(
  PROJECT_ROOT,
  "services/quant-api/app/alerts/openclaw_weixin_single_shot.mjs",
);


function fixture() {
  const root = mkdtempSync(path.join(os.tmpdir(), "guiyi-clawbot-plugin-"));
  const plugin = path.join(root, "plugin");
  const state = path.join(root, "state");
  const calls = path.join(root, "calls.jsonl");
  mkdirSync(path.join(plugin, "dist/src/auth"), { recursive: true });
  mkdirSync(path.join(plugin, "dist/src/messaging"), { recursive: true });
  mkdirSync(path.join(state, "openclaw-weixin/accounts"), { recursive: true });
  writeFileSync(path.join(plugin, "package.json"), JSON.stringify({ type: "module", version: "2.4.6" }));
  writeFileSync(
    path.join(plugin, "dist/src/auth/accounts.js"),
    `export const DEFAULT_BASE_URL = "https://fixture.invalid";
export async function listIndexedWeixinAccountIds() {
  if (process.env.FAKE_SCENARIO === "zero_accounts") return [];
  if (process.env.FAKE_SCENARIO === "multiple_accounts") return ["fixture-account", "other-account"];
  if (process.env.FAKE_SCENARIO === "bad_account") return [" fixture-account"];
  return ["fixture-account"];
}
export async function loadWeixinAccount() {
  if (process.env.FAKE_SCENARIO === "missing_account") return null;
  return {
    token: process.env.FAKE_SCENARIO === "missing_token" ? "" : "fixture-token",
    userId: process.env.FAKE_SCENARIO === "bad_user" ? "invalid" :
      process.env.FAKE_SCENARIO === "noncanonical_user" ? " fixture-owner@im.wechat" :
      process.env.FAKE_SCENARIO === "owner_mismatch" ? "other@im.wechat" : "fixture-owner@im.wechat",
    baseUrl: "",
  };
}
`,
  );
  writeFileSync(
    path.join(plugin, "dist/src/messaging/inbound.js"),
    `export async function restoreContextTokens() {}
export async function getContextToken(_accountId, targetUserId) {
  if (process.env.FAKE_SCENARIO === "missing_context") return "";
  if (process.env.FAKE_SCENARIO === "context_leading_space") return " fixture-context";
  if (process.env.FAKE_SCENARIO === "context_control") return "fixture\\ncontext";
  if (process.env.FAKE_SCENARIO === "context_c1") return "fixture\\u0085context";
  if (targetUserId === "fixture-friend@im.wechat") return "fixture-friend-context";
  return "fixture-context";
}
`,
  );
  writeFileSync(
    path.join(plugin, "dist/src/messaging/send.js"),
    `import { appendFileSync } from "node:fs";
export async function sendMessageWeixin(value) {
  appendFileSync(process.env.FAKE_CALLS_PATH, JSON.stringify(value) + "\\n");
  if (process.env.FAKE_SCENARIO === "send_throw") throw new Error("private vendor detail");
}
`,
  );
  const manifest = path.join(root, "versions.json");
  writeFileSync(
    manifest,
    JSON.stringify({
      schema_version: 1,
      openclaw_version: "OpenClaw fixture",
      openclaw_weixin_version: "2.4.6",
      node_version: process.version,
      plugin_modules: {
        accounts: "dist/src/auth/accounts.js",
        inbound: "dist/src/messaging/inbound.js",
        send: "dist/src/messaging/send.js",
      },
    }),
  );
  const contexts = path.join(
    state,
    "openclaw-weixin/accounts/fixture-account.context-tokens.json",
  );
  writeFileSync(
    contexts,
    JSON.stringify({
      "fixture-owner@im.wechat": "fixture-context",
      "fixture-friend@im.wechat": "fixture-friend-context",
    }),
  );
  return { root, plugin, state, calls, contexts, manifest };
}


function invoke(fx, payload, scenario = "ready") {
  const result = spawnSync(process.execPath, [SEAM], {
    encoding: "utf8",
    env: {
      PATH: process.env.PATH,
      OPENCLAW_STATE_DIR: fx.state,
      GUIYI_OPENCLAW_WEIXIN_PLUGIN_ROOT: fx.plugin,
      GUIYI_CLAWBOT_VERSIONS_PATH: fx.manifest,
      FAKE_CALLS_PATH: fx.calls,
      FAKE_SCENARIO: scenario,
      OPENCLAW_LOG_LEVEL: "FATAL",
    },
    input: JSON.stringify(payload),
    timeout: 5000,
  });
  let output;
  try {
    output = JSON.parse(result.stdout);
  } catch {
    output = null;
  }
  const calls = (() => {
    try {
      return readFileSync(fx.calls, "utf8").trim().split("\n").filter(Boolean).map(JSON.parse);
    } catch {
      return [];
    }
  })();
  return { ...result, output, calls };
}


test("snapshot_contexts returns only sorted validated direct identifiers and tokens", () => {
  const fx = fixture();
  const result = invoke(fx, { action: "snapshot_contexts" });

  assert.equal(result.status, 0);
  assert.deepEqual(result.output, {
    status: "ready",
    action: "snapshot_contexts",
    account_id: "fixture-account",
    contexts: [
      { user_id: "fixture-friend@im.wechat", context_token: "fixture-friend-context" },
      { user_id: "fixture-owner@im.wechat", context_token: "fixture-context" },
    ],
  });
  assert.deepEqual(result.calls, []);
  assert.equal(result.stderr, "");
});


test("snapshot_contexts uses deterministic code-unit order for mixed-case direct ids", () => {
  const fx = fixture();
  writeFileSync(
    fx.contexts,
    JSON.stringify({
      "a@im.wechat": "lower-context",
      "Z@im.wechat": "upper-context",
    }),
  );

  const result = invoke(fx, { action: "snapshot_contexts" });

  assert.equal(result.status, 0);
  assert.deepEqual(
    result.output.contexts.map((item) => item.user_id),
    ["Z@im.wechat", "a@im.wechat"],
  );
});


test("snapshot_contexts rejects a message body field without reading contexts", () => {
  const fx = fixture();

  const result = invoke(fx, {
    action: "snapshot_contexts",
    text: "must never enter the snapshot action",
  });

  assert.notEqual(result.status, 0);
  assert.equal(result.output.error, "CLAWBOT_INPUT_INVALID");
  assert.deepEqual(result.calls, []);
});


for (const [name, payload] of [
  ["non-object state", []],
  ["non-direct user", { "fixture-group@chatroom": "fixture-context" }],
  ["empty token", { "fixture-owner@im.wechat": "" }],
  [
    "too many candidates",
    Object.fromEntries(
      Array.from({ length: 65 }, (_, index) => [
        `fixture-${index}@im.wechat`,
        `fixture-context-${index}`,
      ]),
    ),
  ],
]) {
  test(`snapshot_contexts fails closed for ${name} without sending`, () => {
    const fx = fixture();
    writeFileSync(fx.contexts, JSON.stringify(payload));

    const result = invoke(fx, { action: "snapshot_contexts" });

    assert.notEqual(result.status, 0);
    assert.deepEqual(result.calls, []);
    assert.equal(result.output.error, "CLAWBOT_CONTEXT_UNAVAILABLE");
    assert.equal(result.stderr, "");
  });
}


test("discover_owner returns one private candidate to the captured parent and never sends", () => {
  const fx = fixture();
  const result = invoke(fx, { action: "discover_owner" });

  assert.equal(result.status, 0);
  assert.deepEqual(result.output, {
    status: "ready",
    action: "discover_owner",
    account_count: 1,
    owner_candidate_count: 1,
    context_available: true,
    account_id: "fixture-account",
    target_user_id: "fixture-owner@im.wechat",
  });
  assert.deepEqual(result.calls, []);
  assert.equal(result.stderr, "");
});


for (const scenario of [
  "zero_accounts",
  "multiple_accounts",
  "missing_token",
  "bad_user",
  "bad_account",
  "noncanonical_user",
  "missing_context",
]) {
  test(`discover_owner fails closed for ${scenario} with zero send`, () => {
    const result = invoke(fixture(), { action: "discover_owner" }, scenario);
    assert.notEqual(result.status, 0);
    assert.equal(result.output.status, "error");
    assert.deepEqual(result.calls, []);
    assert.equal(result.stderr, "");
  });
}


test("probe validates the frozen owner and context without sending", () => {
  const result = invoke(fixture(), {
    action: "probe",
    account_id: "fixture-account",
    target_user_id: "fixture-owner@im.wechat",
  });
  assert.equal(result.status, 0);
  assert.deepEqual(result.output, {
    status: "ready",
    action: "probe",
    account_configured: true,
    context_available: true,
  });
  assert.deepEqual(result.calls, []);
});


for (const scenario of ["missing_account", "missing_context"]) {
  test(`probe fails closed for ${scenario} with zero send`, () => {
    const result = invoke(
      fixture(),
      { action: "probe", account_id: "fixture-account", target_user_id: "fixture-owner@im.wechat" },
      scenario,
    );
    assert.notEqual(result.status, 0);
    assert.deepEqual(result.calls, []);
    assert.equal(result.output.error, scenario === "missing_context" ? "CLAWBOT_CONTEXT_UNAVAILABLE" : "CLAWBOT_OWNER_INVALID");
  });
}


test("probe accepts a direct recipient that differs from the account owner", () => {
  const result = invoke(fixture(), {
    action: "probe",
    account_id: "fixture-account",
    target_user_id: "fixture-friend@im.wechat",
  });

  assert.equal(result.status, 0);
  assert.deepEqual(result.output, {
    status: "ready",
    action: "probe",
    account_configured: true,
    context_available: true,
  });
  assert.deepEqual(result.calls, []);
});


test("send accepts one direct friend and invokes Tencent exactly once", () => {
  const result = invoke(fixture(), {
    action: "send",
    account_id: "fixture-account",
    target_user_id: "fixture-friend@im.wechat",
    text: "fixture alert",
  });

  assert.equal(result.status, 0);
  assert.equal(result.calls.length, 1);
  assert.equal(result.calls[0].to, "fixture-friend@im.wechat");
  assert.equal(result.calls[0].opts.contextToken, "fixture-friend-context");
});


for (const [name, targetUserId, scenario, error] of [
  ["suffix-only target", "@im.wechat", "ready", "CLAWBOT_OWNER_INVALID"],
  ["leading-space target", " fixture-friend@im.wechat", "ready", "CLAWBOT_INPUT_INVALID"],
  ["control target", "fixture\nfriend@im.wechat", "ready", "CLAWBOT_INPUT_INVALID"],
  ["C1 target", "fixture\u0085friend@im.wechat", "ready", "CLAWBOT_INPUT_INVALID"],
  ["leading-space context", "fixture-owner@im.wechat", "context_leading_space", "CLAWBOT_CONTEXT_UNAVAILABLE"],
  ["control context", "fixture-owner@im.wechat", "context_control", "CLAWBOT_CONTEXT_UNAVAILABLE"],
  ["C1 context", "fixture-owner@im.wechat", "context_c1", "CLAWBOT_CONTEXT_UNAVAILABLE"],
]) {
  test(`direct send rejects ${name} before physical send`, () => {
    const result = invoke(
      fixture(),
      {
        action: "send",
        account_id: "fixture-account",
        target_user_id: targetUserId,
        text: "fixture alert",
      },
      scenario,
    );

    assert.notEqual(result.status, 0);
    assert.equal(result.output.error, error);
    assert.deepEqual(result.calls, []);
  });
}


test("send invokes Tencent primitive exactly once with the required shape", () => {
  const result = invoke(fixture(), {
    action: "send",
    account_id: "fixture-account",
    target_user_id: "fixture-owner@im.wechat",
    text: "fixture alert",
  });
  assert.equal(result.status, 0);
  assert.deepEqual(result.output, { status: "accepted", action: "send" });
  assert.equal(result.calls.length, 1);
  assert.deepEqual(result.calls[0], {
    to: "fixture-owner@im.wechat",
    text: "fixture alert",
    opts: {
      baseUrl: "https://fixture.invalid",
      token: "fixture-token",
      contextToken: "fixture-context",
    },
  });
});


test("send preserves the fixed multiline Alert canary and invokes Tencent exactly once", () => {
  const text = "【归一量化】微信通知测试\n\nAlert 通知通道正常";
  const result = invoke(fixture(), {
    action: "send",
    account_id: "fixture-account",
    target_user_id: "fixture-owner@im.wechat",
    text,
  });
  assert.equal(result.status, 0);
  assert.deepEqual(result.output, { status: "accepted", action: "send" });
  assert.equal(result.calls.length, 1);
  assert.equal(result.calls[0].text, text);
});


for (const [name, text] of [
  ["NUL", "fixture\u0000alert"],
  ["CR", "fixture\ralert"],
  ["TAB", "fixture\talert"],
  ["DEL", "fixture\u007falert"],
  ["C1 control", "fixture\u0085alert"],
]) {
  test(`send rejects ${name} in message text before physical send`, () => {
    const result = invoke(fixture(), {
      action: "send",
      account_id: "fixture-account",
      target_user_id: "fixture-owner@im.wechat",
      text,
    });
    assert.notEqual(result.status, 0);
    assert.equal(result.output.error, "CLAWBOT_INPUT_INVALID");
    assert.deepEqual(result.calls, []);
  });
}


test("send throw records one physical attempt and never retries", () => {
  const result = invoke(
    fixture(),
    { action: "send", account_id: "fixture-account", target_user_id: "fixture-owner@im.wechat", text: "fixture alert" },
    "send_throw",
  );
  assert.notEqual(result.status, 0);
  assert.equal(result.output.error, "CLAWBOT_SEND_FAILED");
  assert.equal(result.calls.length, 1);
  assert.equal(result.stderr, "");
  assert.equal(result.stdout.includes("private vendor detail"), false);
});


test("missing context prevents physical send", () => {
  const result = invoke(
    fixture(),
    { action: "send", account_id: "fixture-account", target_user_id: "fixture-owner@im.wechat", text: "fixture alert" },
    "missing_context",
  );
  assert.notEqual(result.status, 0);
  assert.equal(result.output.error, "CLAWBOT_CONTEXT_UNAVAILABLE");
  assert.deepEqual(result.calls, []);
});


test("manifest version mismatch fails before any send", () => {
  const fx = fixture();
  const manifest = JSON.parse(readFileSync(fx.manifest, "utf8"));
  manifest.openclaw_weixin_version = "9.9.9";
  writeFileSync(fx.manifest, JSON.stringify(manifest));
  const result = invoke(fx, {
    action: "send",
    account_id: "fixture-account",
    target_user_id: "fixture-owner@im.wechat",
    text: "fixture alert",
  });
  assert.notEqual(result.status, 0);
  assert.equal(result.output.error, "CLAWBOT_DEPENDENCY_INVALID");
  assert.deepEqual(result.calls, []);
});


test("module path escaping the plugin root is rejected before import", () => {
  const fx = fixture();
  const manifest = JSON.parse(readFileSync(fx.manifest, "utf8"));
  manifest.plugin_modules.send = "../outside.js";
  writeFileSync(fx.manifest, JSON.stringify(manifest));
  const result = invoke(fx, { action: "discover_owner" });
  assert.notEqual(result.status, 0);
  assert.equal(result.output.error, "CLAWBOT_DEPENDENCY_INVALID");
  assert.deepEqual(result.calls, []);
});
