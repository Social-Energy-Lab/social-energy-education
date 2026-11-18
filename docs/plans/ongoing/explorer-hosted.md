# Explorer: the hosted team copy

**Priority:** high — the project lead's ask: the team explorer without a data root on every machine
**Gate:** none
**Next:** the project lead signs in and invites the researchers he names

**Goal:** the research team opens the team explorer in a browser on the institute VPN, with its
own login, and sees the same data as `social-energy explore` shows locally
([decision](../../decisions/explorer-hosted.md)).

## Tasks

- [x] `social-energy deploy-explorer` and `explorer-user`, reading the target from `local.yaml`
      (`social_energy.explorer.deploy`) (2026-11-18).
- [x] One-time server setup script (`scripts/explorer-server-setup.sh`) (2026-11-18).
- [x] Run the setup on the server (2026-11-18).
- [x] First deploy and first login (2026-11-18).
- [x] Own sign-in service with invite links and an admin page (`auth_service.py`) (2026-11-18).
- [x] Run the updated setup on the server; admin invites for Álvaro and the project lead (2026-11-18).
- [ ] Invites for the researchers the project lead names (admins do it at `/auth/admin`).
- [ ] Check with the project lead in the browser.
- [ ] Ask the institute for a proper certificate, so browsers stop warning.

## Later

- **Interview themes behind the login** (the project lead's level 3). The self-report
  descriptions are in (2026-11-18): `moments.json`, team bundle only.
- **Names** only if the project lead confirms the ethics approval and consent allow them.
- Presentation additions (2026-11-18): the day's programme by name, several people picked and
  compared, who is together in the paused frame (close now, and how long before), and the
  written descriptions. Deployed with the bundle of the same day.
