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
  const calls = path.join(root, "calls.jsonl");
  mkdirSync(path.join(plugin, "dist/src/auth"), { recursive: true });
  mkdirSync(path.join(plugin, "dist/src/messaging"), { recursive: true });
  writeFileSync(path.join(plugin, "package.json"), JSON.stringify({ type: "module", version: "2.4.6" }));
  writeFileSync(
    path.join(plugin, "dist/src/auth/accounts.js"),
    `export const DEFAULT_BASE_URL = "https://fixture.invalid";
export async function listIndexedWeixinAccountIds() {
  if (process.env.FAKE_SCENARIO === "zero_accounts") return [];
  if (process.env.FAKE_SCENARIO === "multiple_accounts") return ["fixture-account", "other-account"];
  return ["fixture-account"];
}
export async function loadWeixinAccount() {
  return {
    token: process.env.FAKE_SCENARIO === "missing_token" ? "" : "fixture-token",
    userId: process.env.FAKE_SCENARIO === "bad_user" ? "invalid" :
      process.env.FAKE_SCENARIO === "owner_mismatch" ? "other@im.wechat" : "fixture-owner@im.wechat",
    baseUrl: "",
  };
}
`,
  );
  writeFileSync(
    path.join(plugin, "dist/src/messaging/inbound.js"),
    `export async function restoreContextTokens() {}
export async function getContextToken() {
  return process.env.FAKE_SCENARIO === "missing_context" ? "" : "fixture-context";
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
  return { root, plugin, calls, manifest };
}


function invoke(fx, payload, scenario = "ready") {
  const result = spawnSync(process.execPath, [SEAM], {
    encoding: "utf8",
    env: {
      PATH: process.env.PATH,
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


for (const scenario of ["zero_accounts", "multiple_accounts", "missing_token", "bad_user", "missing_context"]) {
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


for (const scenario of ["owner_mismatch", "missing_context"]) {
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
