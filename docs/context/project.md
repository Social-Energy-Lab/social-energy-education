# The research project

A summary in our own words of the PhD project this repo serves. Sources are the project proposal (Feb 2026), the approved FSU ethics application (Jul 2026) and team presentations. The full documents live in the private context library (see [AGENTS.md](../../AGENTS.md#private-context-library)). Theory background: [theory.md](theory.md).

## Frame

- **Title:** *The invisible dynamics of the social.* How social energy emerges, circulates and is blocked in educational settings, and how this affects talent development.
- **Who:** Mahdi Srour, PhD at FSU Jena (Institute of Sociology, Hartmut Rosa's group) and the Max Planck Institute of Geoanthropology (IMPRS "Modeling the Anthropocene"), supervised by Hartmut Rosa and two further supervisors. Collaborators: a physicist (beacon hardware and firmware, see [`instruments/beacons.md`](instruments/beacons.md)) and Álvaro Francisco Gil (computer science; this repo). Everyone else is named by role until they have said they are happy to be named here.
- **When:** Oct 2025 to Sep 2028. The ethics approval covers data collection until 2028-09-30, when the ID code list is deleted.
- **Funding:** university research; no external project grant.

## Problem

German schools face growing heterogeneity, scarce resources and falling well-being among pupils and teachers. Pupils from low-income families, with a migration background or with mental-health difficulties are affected most. The project's claim is that regular schools lack the conditions under which **social energy** can circulate. When it is blocked, the result is weaker motivation, stalled development, less self-efficacy, less belonging and more inequality. Extracurricular programmes run by foundations are studied as places where it *does* circulate, as models for compensatory structures in regular schooling.

## Hypotheses and research questions

- **H1:** Social energy is a central concept for understanding talent development in education.
- **H2:** Access to social energy strongly shapes educational success.
- **H3:** Institutional structures, pedagogical practices and interaction patterns make access to "participation in social energy" unequal.

Research questions:

1. How can social energy in education be grasped theoretically and empirically?
2. How does participation in (circulating) social energy affect young people's educational success?
3. How do structures, practices and interaction patterns shape the emergence, flow or blockage of social energy?
4. What particular barriers do young people with a migration background or from disadvantaged families face?
5. How can structures, practices and interaction patterns be adapted to support talent development for all?

## Settings (field phases)

| Setting | Population | Role in design | Status |
|---|---|---|---|
| Deutsche SchülerAkademie (Bildung & Begabung) | selected, highly motivated upper-secondary pupils; 16-day residential academy | first field phase: [`studies/dsa-2026`](../../studies/dsa-2026/) | collected Aug 2026 |
| SUPER YOU (Bildung & Begabung) | disadvantaged lower-secondary pupils | contrast setting (RQ4) | planned |
| START-Stiftung | young people with a migration background | contrast setting (RQ4) | planned |

Plan: two to three field phases of about 100 people each, about 250–300 people in total. Alumni can join qualitative pre/post rounds.

## Design

- **Best-account principle** (Rosa, after Taylor): combine every available source (measurements, interviews, theory, participants' self-interpretations) into the most coherent interpretation, open to correction.
- **Perspectival dualism:** the 1st-person perspective says *what* was experienced and *why*; the 3rd-person perspective says *when* and *how intensely*. Analyses look where the two agree and where they diverge.
- **Mixed design:** time is a within-subject factor (before t0 / during t1…tn / after tn+1); setting is a between-subject factor. Observational, non-interventional, no control group.
- **Six analytic dimensions:**

| Dimension | Focus | Example variables |
|---|---|---|
| I individual | subjective variables | SES, migration background, personality, motivation (needs, goals, fears), trust, belonging |
| II group | collective patterns | rhythmic entrainment, collective effervescence, synchronisation (turn-taking, speech rate) |
| III institution | structural settings | flat vs hierarchical, admission and participation rules, fixed vs open programme |
| IV individual ↔ group | group interaction | dimensions of engagement: experience, intentionality, embodiment, empathy, affective sharing, mutual commitment, participatory sense-making |
| V individual ↔ institution | fit / alignment | understanding and accepting the institution's logic; fit between personal goals and programme |
| VI group ↔ institution | spatial dynamics, collective appropriation | use of rooms and programme items; "do we understand the system, does it understand us?" |

- **Top-down and bottom-up variable selection:** theory proposes candidate variables per dimension (e.g. mutual focus of attention, shared mood, rhythmic entrainment). Interviews with alumni and participants before the academy surface what they themselves find relevant.
- **Thermodynamic framing** (heuristic): social energy as a state quantity built from process variables that act as gradients or potentials enabling movement. Open non-equilibrium systems and dissipative structures ("order through flow") and attractor landscapes with tipping points serve as metaphors. Energy *shapes* the landscape; it is neither the ball nor the valley. Blocked energy has been likened to entropy (flow that cannot be recovered, e.g. rigid institutional processes). These are not yet operational state variables. See [theory.md](theory.md#open-tensions).

## Data modules (as approved)

| Code (Aug 2026 forms) | Module | Notes |
|---|---|---|
| QL-1 | in-person phenomenological interviews | audio deleted after transcription |
| QL-2 | AI voice/chat interviews before and after | transcripts only, pseudonymised |
| QL-3 | structured questionnaire (SurveyJS) | before (and after) the academy |
| QA-1 | sociometric badges ("beacons") incl. self-report button; also room tags | worn as name tags |
| — | physiological: heart rate / PPG, EDA | named in the ethics application; module code on the final participant form not recorded here (see below) |
| — | ambient acoustics (AudioMoth) | frequency and level features only; WAVs deleted after extraction |
| — | course-leader observations | trust/lust-for-life impressions per consenting participant |

Consent is **modular**. Each person can accept or decline each module, and minors need guardians' consent too. The April 2026 drafts used a different scheme (QA-1 smart buttons, QA-2 physiology, QA-3 acoustics, QA-4 badges, QA-5 body cameras). Body cameras and smart buttons were dropped before the field phase.

The final participant form's module codes are not in the context library, and for analysis they are not needed: **wherever data exists with a study ID attached, consent for that module exists** (2026-09-20, Mahdi). No consent means no labelled data, and usually no data at all. Analyses still call `spine.consented(<module>)`, as a guard rather than as an expected filter.

## Ethics and publication constraints (binding for this repo)

- Pseudonymised under an abstract study ID. The code list is stored separately and encrypted, and deleted by **2028-09-30**. After that the data count as anonymous, and deletion requests are no longer possible.
- Publications contain **only aggregated or anonymised results**. Small groups are merged or not reported. Findings are interpreted in a non-stigmatising way.
- **Analysis code and data documentation may be published.** Fully anonymised data may be published. Detailed physiological and interaction data only through controlled access on request.
- No individual results go back to participants or to course/academy leaders. Participants may opt in to an aggregate summary (2027–2028).
- Pedagogy and participants' well-being always take priority over data collection.

## Paper framing

Do not claim to have "measured social energy". Describe **interactional, experiential and developmental signatures** of it. Treat belonging as a process unfolding in real time, not only an attitude reported afterwards. Put inequality at the centre: for whom, under which conditions, through which interaction patterns.
