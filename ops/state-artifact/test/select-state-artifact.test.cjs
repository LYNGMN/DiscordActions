"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const { selectLatestArtifact } = require("../select-state-artifact.cjs");

const CONTEXT = {
  repo: { owner: "owner", repo: "repo" },
  runId: 99,
};

function fakeGithub({ runsByWorkflow, artifactsByRun }) {
  const calls = [];
  return {
    calls,
    rest: {
      actions: {
        async listWorkflowRuns(query) {
          calls.push(["runs", query.workflow_id]);
          return { data: { workflow_runs: runsByWorkflow[query.workflow_id] || [] } };
        },
        async listWorkflowRunArtifacts(query) {
          calls.push(["artifacts", query.run_id]);
          return { data: { artifacts: artifactsByRun[query.run_id] || [] } };
        },
      },
    },
  };
}

test("picks the newest run with a non-expired artifact", async () => {
  const github = fakeGithub({
    runsByWorkflow: {
      "google-news.yml": [
        { id: 2, created_at: "2026-11-16T10:00:00Z" },
        { id: 1, created_at: "2026-11-16T09:00:00Z" },
      ],
      "google-news-manual.yml": [
        { id: 3, created_at: "2026-11-16T10:30:00Z" },
      ],
    },
    artifactsByRun: {
      3: [{ id: 30, name: "google-news-state", expired: false }],
      2: [{ id: 20, name: "google-news-state", expired: false }],
    },
  });

  const result = await selectLatestArtifact({
    github,
    context: CONTEXT,
    workflowIds: ["google-news.yml", "google-news-manual.yml"],
    artifactName: "google-news-state",
  });

  assert.deepEqual(result, { artifactId: "30", sourceRunId: "3" });
  assert.deepEqual(github.calls, [
    ["runs", "google-news.yml"],
    ["runs", "google-news-manual.yml"],
    ["artifacts", 3],
  ]);
});

test("skips the current run and expired artifacts", async () => {
  const github = fakeGithub({
    runsByWorkflow: {
      "workflow.yml": [
        { id: 99, created_at: "2026-11-16T11:00:00Z" },
        { id: 5, created_at: "2026-11-16T10:00:00Z" },
        { id: 4, created_at: "2026-11-16T09:00:00Z" },
      ],
    },
    artifactsByRun: {
      5: [{ id: 50, name: "state", expired: true }],
      4: [{ id: 40, name: "state", expired: false }],
    },
  });

  const result = await selectLatestArtifact({
    github,
    context: CONTEXT,
    workflowIds: ["workflow.yml"],
    artifactName: "state",
  });

  assert.deepEqual(result, { artifactId: "40", sourceRunId: "4" });
});

test("returns empty outputs when no artifact exists", async () => {
  const github = fakeGithub({
    runsByWorkflow: { "workflow.yml": [] },
    artifactsByRun: {},
  });

  const result = await selectLatestArtifact({
    github,
    context: CONTEXT,
    workflowIds: ["workflow.yml"],
    artifactName: "state",
  });

  assert.deepEqual(result, { artifactId: "", sourceRunId: "" });
});

test("ignores an artifact with another name", async () => {
  const github = fakeGithub({
    runsByWorkflow: {
      "workflow.yml": [{ id: 1, created_at: "2026-11-16T09:00:00Z" }],
    },
    artifactsByRun: {
      1: [{ id: 11, name: "other", expired: false }],
    },
  });

  const result = await selectLatestArtifact({
    github,
    context: CONTEXT,
    workflowIds: ["workflow.yml"],
    artifactName: "state",
  });

  assert.deepEqual(result, { artifactId: "", sourceRunId: "" });
});

test("requires the caller to pass a workflow list", async () => {
  await assert.rejects(
    selectLatestArtifact({
      github: {},
      context: CONTEXT,
      artifactName: "state",
    }),
    /required/,
  );
});
