"use strict";

/**
 * Pick the newest non-expired state artifact from the service's workflows.
 *
 * The GitHub runs API is intentionally limited to one page per workflow: a
 * state artifact older than the newest hundred completed runs is not a useful
 * recovery source. The caller writes the two outputs to the workflow.
 */
async function selectLatestArtifact({
  github,
  context,
  workflowIds,
  artifactName,
}) {
  if (!github || !context || !Array.isArray(workflowIds) || !artifactName) {
    throw new Error("github, context, workflowIds and artifactName are required");
  }
  const { owner, repo } = context.repo;
  const runs = [];
  for (const workflowId of workflowIds) {
    const { data: runPage } = await github.rest.actions.listWorkflowRuns({
      owner,
      repo,
      workflow_id: workflowId,
      status: "completed",
      per_page: 100,
    });
    runs.push(...(runPage.workflow_runs || []));
  }
  runs.sort(
    (left, right) => new Date(right.created_at) - new Date(left.created_at),
  );

  for (const run of runs) {
    if (run.id === context.runId) {
      continue;
    }
    const { data: artifactPage } =
      await github.rest.actions.listWorkflowRunArtifacts({
        owner,
        repo,
        run_id: run.id,
        per_page: 100,
      });
    const artifact = (artifactPage.artifacts || []).find(
      (item) => item.name === artifactName && !item.expired,
    );
    if (artifact) {
      return {
        artifactId: String(artifact.id),
        sourceRunId: String(run.id),
      };
    }
  }
  return { artifactId: "", sourceRunId: "" };
}

module.exports = { selectLatestArtifact };
