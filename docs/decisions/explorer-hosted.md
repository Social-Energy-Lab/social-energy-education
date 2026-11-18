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
- **Two locks.** The institute VPN (account plus second factor) to reach the server, then one
  login per researcher, checked by the web server (basic auth over HTTPS).
  `social-energy explorer-user --add NAME` asks for the password on the deploying machine and
  sends only a SHA-512 crypt hash; `--remove NAME` withdraws access. Only researchers the project
  lead names get a login.
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
