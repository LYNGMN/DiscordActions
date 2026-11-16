const WORKFLOWS = [
  "googlenews-to-discord.yml",
  "youtube_to_discord.yml",
];

const API_VERSION = "2022-11-28";
const MAX_ATTEMPTS = 3;

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function requireSetting(value, name) {
  const text = String(value || "").trim();
  if (!text) {
    throw new Error(`${name} is not configured`);
  }
  return text;
}

export async function dispatchWorkflow(
  env,
  workflow,
  fetchImpl = fetch,
  sleepImpl = sleep,
) {
  const repo = requireSetting(env.REPO, "REPO");
  const token = requireSetting(env.GITHUB_TOKEN, "GITHUB_TOKEN");
  const ref = String(env.REF || "main").trim() || "main";
  const url = `https://api.github.com/repos/${repo}/actions/workflows/${workflow}/dispatches`;

  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
    const response = await fetchImpl(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": "discordactions-scheduler",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref }),
    });

    if (response.status === 204) {
      return { workflow, status: 204, attempts: attempt };
    }

    // A bad token, a missing repository or a disabled workflow will not heal
    // by retrying. Leave the detail out of the message so logs never contain
    // credentials or GitHub response bodies.
    if ([401, 403, 404].includes(response.status)) {
      throw new Error(`dispatch ${workflow} rejected with HTTP ${response.status}`);
    }

    if (attempt < MAX_ATTEMPTS) {
      await sleepImpl(attempt * 1000);
      continue;
    }

    throw new Error(`dispatch ${workflow} failed with HTTP ${response.status}`);
  }

  throw new Error(`dispatch ${workflow} exhausted retries`);
}

export async function dispatchAll(env, fetchImpl = fetch, sleepImpl = sleep) {
  const results = [];
  for (const workflow of WORKFLOWS) {
    results.push(await dispatchWorkflow(env, workflow, fetchImpl, sleepImpl));
  }
  return results;
}

export default {
  async scheduled(controller, env, ctx) {
    ctx.waitUntil(
      dispatchAll(env).catch((error) => {
        console.error("scheduled dispatch failed:", error.message);
        throw error;
      }),
    );
  },
};
