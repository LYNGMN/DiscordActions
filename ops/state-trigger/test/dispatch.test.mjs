import assert from "node:assert/strict";
import test from "node:test";

import { dispatchAll, dispatchWorkflow } from "../src/index.js";

const ENV = {
  REPO: "owner/repo",
  GITHUB_TOKEN: "super-secret-token",
};

function response(status) {
  return { status };
}

function recorder(...statuses) {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url, init });
    const status = statuses.length > 1 ? statuses.shift() : statuses[0];
    return response(status);
  };
  return { calls, fetchImpl };
}

test("dispatches every workflow with the least-privilege API request", async () => {
  const { calls, fetchImpl } = recorder(204);

  const results = await dispatchAll(ENV, fetchImpl, async () => {});

  assert.equal(results.length, 2);
  assert.equal(calls.length, 2);
  assert.equal(
    calls[0].url,
    "https://api.github.com/repos/owner/repo/actions/workflows/googlenews-to-discord.yml/dispatches",
  );
  assert.equal(
    calls[1].url,
    "https://api.github.com/repos/owner/repo/actions/workflows/youtube_to_discord.yml/dispatches",
  );
  for (const call of calls) {
    assert.equal(call.init.method, "POST");
    assert.equal(call.init.headers.Authorization, "Bearer super-secret-token");
    assert.equal(call.init.headers.Accept, "application/vnd.github+json");
    assert.equal(call.init.headers["X-GitHub-Api-Version"], "2022-11-28");
    assert.deepEqual(JSON.parse(call.init.body), { ref: "main" });
  }
});

test("retries a transient GitHub failure before giving up", async () => {
  const { calls, fetchImpl } = recorder(502, 204);
  const sleeps = [];

  const result = await dispatchWorkflow(
    ENV,
    "googlenews-to-discord.yml",
    fetchImpl,
    async (milliseconds) => sleeps.push(milliseconds),
  );

  assert.equal(result.attempts, 2);
  assert.equal(calls.length, 2);
  assert.deepEqual(sleeps, [1000]);
});

test("does not retry authorization or missing-repository failures", async () => {
  for (const status of [401, 403, 404]) {
    const { calls, fetchImpl } = recorder(status);
    await assert.rejects(
      dispatchWorkflow(ENV, "googlenews-to-discord.yml", fetchImpl, async () => {}),
      new RegExp(`HTTP ${status}`),
    );
    assert.equal(calls.length, 1);
  }
});

test("fails closed when a setting is missing", async () => {
  await assert.rejects(
    dispatchAll({ REPO: "owner/repo" }, async () => response(204), async () => {}),
    /GITHUB_TOKEN is not configured/,
  );
  await assert.rejects(
    dispatchAll({ GITHUB_TOKEN: "token" }, async () => response(204), async () => {}),
    /REPO is not configured/,
  );
});

test("never puts the token in an error message", async () => {
  const { fetchImpl } = recorder(500);

  await assert.rejects(
    dispatchWorkflow(ENV, "googlenews-to-discord.yml", fetchImpl, async () => {}),
    (error) => {
      assert.equal(error.message.includes("super-secret-token"), false);
      assert.match(error.message, /HTTP 500/);
      return true;
    },
  );
});

test("accepts a custom ref for a branch deploy", async () => {
  const { calls, fetchImpl } = recorder(204);

  const result = await dispatchWorkflow(
    { ...ENV, REF: "release" },
    "youtube_to_discord.yml",
    fetchImpl,
    async () => {},
  );

  assert.equal(result.status, 204);
  assert.deepEqual(JSON.parse(calls[0].init.body), { ref: "release" });
});
