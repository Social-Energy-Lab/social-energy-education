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
- Workspace layout (2026-11-18): the network and the paused frame side by side under a sticky
  time bar that carries the day's programme; the other views as "More views" tabs; the three
  sliders behind "Advanced", with a plain sentence in front ("Lines join two people who were
  close for at least 15 min in the last 2 h"); the person view as a drawer over the camp; the
  address keeps the view (time, picked people, person, changed settings) so a link reopens it.
  The network stops moving when paused, so dots can be clicked.
- The halls' sound (2026-11-18): a "How the halls sounded" tab and a "Sound now" line in the
  frame, each hall against its own recorded time.
- The project lead's first questions (2026-11-19): click a room item of the programme to see
  only the people at it (placed in its rooms by their room tag for most of the item); "Their
  people across the academy" in the person view (everyone close to the person, hours per day,
  room items shared, open to dive in); the picked people one row each in Self-reports (presses
  and EDA moments); the sound over the whole camp with the frequency mix (below 300 Hz, voice
  range, above 4000 Hz) under the loudness.
- **Remove the classic view** (`classic.html`, `classic.js`, `classic.css`) after the next field
  phase, once nobody asks for it.
- Not yet: ready-made starting points (a question that sets day, time and view), presentation
  mode (full screen, bigger text, arrow keys through bookmarked moments), a key under every
  view.
