# Discord Actions state trigger

GitHub's `schedule` event is best effort. On this repository it fired only
about five times a day instead of every fifteen minutes, so news arrived hours
late and some articles disappeared from the RSS feed before delivery. This
Worker calls the GitHub `workflow_dispatch` API on a fifteen-minute cron. The
repository's `schedule` entries stay in place as a fallback.

## What it dispatches

| Workflow | Purpose |
| --- | --- |
| `googlenews-to-discord.yml` | Google News delivery |
| `youtube_to_discord.yml` | YouTube delivery |

Both run in their own concurrency group, so a slow Google News run does not
block YouTube. GitHub keeps at most one pending run per group; overlapping
ticks are coalesced instead of piling up.

## Setup

1. Create a **fine-grained personal access token**:
   - GitHub → Settings → Developer settings → Personal access tokens →
     Fine-grained tokens → Generate new token.
   - Repository access: **Only select repositories** → this repository.
   - Repository permissions: **Actions: Read and write**. Nothing else.
   - Expiration: 90 days.
   - Copy the token once. Do not paste it into an issue, a commit, or a chat.
2. Store it as a Worker secret and deploy:

   ```sh
   cd ops/state-trigger
   npx wrangler secret put GITHUB_TOKEN
   npx wrangler deploy
   ```

3. Watch the first ticks:

   ```sh
   npx wrangler tail
   ```

   A successful dispatch logs a 204 from GitHub. In the repository's Actions
   tab the production workflows should now appear with the
   `workflow_dispatch` event every fifteen minutes.

4. After a day of successful runs, set the repository variable
   `GOOGLE_NEWS_HEALTH_MAX_AGE_HOURS` to `3`. Leave it at `6` during rollout to
   avoid false alarms while the Worker is being verified.

## Testing

```sh
cd ops/state-trigger
npm test
```

The tests mock GitHub and verify the request shape, retry behavior, and that
the token never appears in an error message.

## Rotation and rollback

- Rotate: create a new token, run `npx wrangler secret put GITHUB_TOKEN`, then
  revoke the old token on GitHub.
- Roll back: `npx wrangler delete` (or remove the cron trigger). The GitHub
  `schedule` entries continue to run a few times a day, and the health workflow
  alerts when delivery stops.

## Security notes

- The token lives only in the Worker secret. It is never written to this
  repository or printed by the Worker.
- The token needs `Actions: Read and write` on one repository. It cannot read
  code, change files, or access other repositories.
- The Worker only sends the fixed `ref` and workflow names; it does not accept
  user input.
