# The team explorer is also hosted, behind the institute VPN and a login

**Date:** 2026-11-18 · **Status:** adopted · amends [explorer-local-only.md](explorer-local-only.md)

## Context

The team explorer ran only on the researcher's own machine
([explorer-local-only.md](explorer-local-only.md)), so every collaborator needed the data root.
The project lead asked for a version the research team can open without that, and the Max
Planck Institute of Geoanthropology gave the project a server for it. The server is reachable
only on the institute's VPN, which needs an institute account and a second factor.

The VPN alone is not enough. It admits everyone at the institute, while the ethics approval
allows the pseudonymised data only to authorised research staff on access-restricted systems.

## Decision

- **The same app and the same team bundle, hosted.** `social-energy deploy-explorer` sends the
  app and the bundle to the server named in the study's private `local.yaml` over SSH and swaps
  them in whole. There is no upload page and nothing on the server writes data; the bundle is
  built locally exactly as for `explore`.
- **Two locks.** The institute VPN (account plus second factor) to reach the server, then the
  explorer's own sign-in: one account per researcher, checked on every request
  (`social_energy/explorer/auth_service.py`, standard library only, behind nginx
  `auth_request`). Only researchers the project lead names get one.
  - **Invites, not handed-out passwords.** An admin makes a one-time link (valid 7 days) in the
    browser at `/auth/admin`; on it the researcher chooses their own password (12 characters or
    more). A forgotten password is a new link. No admin ever knows anyone's password.
  - **Admins** (the project lead and the deploying researcher) invite, reset and remove;
    researchers only view. Removing someone signs them out at once.
  - Passwords are kept only as scrypt hashes, session and invite tokens only as SHA-256 hashes.
    Sessions last 12 hours (HttpOnly, Secure, SameSite=Strict cookie; forms carry a per-session
    token). Five failures for one name or one address block it for 15 minutes.
  - No second factor at sign-in: the VPN already asks for one.
  - The first version (2026-11-18, the same day) used the web server's basic auth with
    hand-made passwords; the service replaced it.
- **Study IDs stay on screen.** The hosted copy is the team mode, not a public view: behind both
  locks it is the same access-restricted, pseudonymised data as on a researcher's machine.
- **The server and its folder are private identifiers**, kept in `local.yaml`
  (`explorer.deploy`), never in this repo. A one-time setup (`scripts/explorer-server-setup.sh`,
  run as root) gives the deploying account its folder and the web server its site, so later
  deploys need no admin rights.
- **Self-report descriptions behind the login (added 2026-11-18).** What participants wrote on
  paper about a moment they marked is shown in the team bundle only, for `self_report` consent
  only, in its own file (`moments.json`) so the rest of the bundle stays codes-only. The public
  site's checks refuse it. It is free text by minors and may name other people, which makes it
  the most identifying thing in the bundle: it is shown in full to logged-in researchers and
  goes nowhere else.
- **The halls' sound (added 2026-11-18).** Each AudioMoth recorder's level per 5-minute bin
  (`sound.json`, from `acoustics_over_time.py`), shown against the day and in the paused frame
  as "louder than N% of that hall's recorded time". It describes rooms, not people, and carries
  no audio.
- **Not yet decided:** interview passages and real names. Interview text needs a decision on
  which passages and under what consent; names wait for the project lead to confirm what the
  ethics approval and the consent allow.

## Consequences

- The local `explore` stays as it was and remains the way to work offline or with a bundle not
  yet deployed. The public site is unchanged ([public-site.md](public-site.md)).
- The server and its backups now hold the team bundle. Removing a person's data means a new
  bundle and a deploy, and asking the institute about the backups.
- The certificate is the server's own until the institute issues one, so browsers warn once.
- Screens and screenshots of the hosted copy are pseudonymised data, as before.
- Researchers without an institute account cannot reach it. Opening it to them would need a
  different route and a new decision.
