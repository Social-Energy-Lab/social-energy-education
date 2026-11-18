# Explorer: the hosted team copy

**Priority:** high — the project lead's ask: the team explorer without a data root on every machine
**Gate:** none
**Next:** run the server setup once, deploy, add the first logins, and check it with the project lead

**Goal:** the research team opens the team explorer in a browser on the institute VPN, with its
own login, and sees the same data as `social-energy explore` shows locally
([decision](../../decisions/explorer-hosted.md)).

## Tasks

- [x] `social-energy deploy-explorer` and `explorer-user`, reading the target from `local.yaml`
      (`social_energy.explorer.deploy`) (2026-11-18).
- [x] One-time server setup script (`scripts/explorer-server-setup.sh`) (2026-11-18).
- [ ] Run the setup on the server (needs the deploying account's admin password).
- [ ] First deploy; first logins for the researchers the project lead names.
- [ ] Check with the project lead in the browser.
- [ ] Ask the institute for a proper certificate, so browsers stop warning.

## Later

- **Free text behind the login:** the self-report descriptions in a pop-up and the interview
  themes (the project lead's level 3). Needs a bundle field for text, and the writer's refusal of
  free text relaxed for team bundles only.
- **Names** only if the project lead confirms the ethics approval and consent allow them.
- The local additions for the presentation (programme names on the timeline, several people
  highlighted, who is in the paused frame) reach the hosted copy with the next deploy.
