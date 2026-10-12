# Team-only frontend deployment and CI/CD

Status: production implementation, native container deployment, Google sign-in, live brief and reload completed. Automatic/manual deployment proof is pending. Earlier backend revision `samurai-backend-00002-p4s` has separate accepted Agno Live evidence.

## Delivery sequence

1. Completed: PR #1 reviewed, two UI defects fixed, checks passed, merged as `6be6ec6e184ae96c46cf4fe6c4de6c9ff74b5331`.
2. Completed: integrate backend deployment, production frontend/IAP identity and per-user browser storage; build and deploy native containers; verify sign-in and the real application.
3. In progress: publish the main/manual deployment workflow, prove both triggers and update the final deployment record.

## Scope and decisions

- Preserve the React/Vite workspace and local authenticated AgentOS integration.
- Deploy a Node static server/BFF to `samurai-frontend`, `samurai-ai-company-2026`, `asia-south1`, protected by team-only Google IAP.
- Verify signed IAP identity and bridge `iap:<sub>` to short-lived RS256 AgentOS JWTs. Add a backend public verification key while retaining Agno Live's version 2 key. Store the frontend private signer in Secret Manager with frontend-only runtime access.
- Use main push and manual main GitHub Actions, same-commit checks, immutable images and restricted Google OIDC federation. Deploy backend then frontend with image-only updates.
- Preserve secrets, Cloud SQL, runtime accounts, IAP, owner isolation and Agno Live. No durable-job or atomic two-service rollout claim.

## Acceptance

- [ ] Production auth/proxy, additive backend trust, container and deployment-script checks pass.
- [ ] Independent review passes for the final commit.
- [ ] Team sign-in, unauthorized-account rejection, owner isolation, real call/reload and Agno Live regression accepted in Google Cloud.
- [ ] Main automatic and manual deployments prove same-commit checks and matching digests.
- [ ] Record revision/digest rollback targets and any remaining limitation.

The operational contract, access onboarding, exact configuration, rollback steps and live acceptance record are maintained in [the deployment guide](../../docs/gcp-deployment.md). New runtime evidence and secrets remain ignored; this is the portable plan summary.
