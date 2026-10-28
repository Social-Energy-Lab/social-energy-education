// "What am I looking at?": definitions, filters and caveats per view, with the bundle's QA counts.
export function explanations(ctx) {
  const { meta } = ctx;
  const qa = meta.qa || {};
  const n = (k) => (qa[k] ?? 0).toLocaleString("en-GB");
  const set = (id, html) => { document.getElementById(id).innerHTML = html; };
  const filters =
    "Only participants who consented to the beacon module are shown, outside exclusion windows. " +
    "Nobody is labelled: dots are shuffled and carry no study ID.";
  set("explain-network", `
    <p>Each dot is one participant, coloured by course. A line joins two people whose strongest
    signal reached the <b>close range</b> threshold in at least the <b>together</b> minutes of the
    <b>window</b> before the playhead. Thicker lines: more time together.</p>
    <p>Each course has a home on the ring and ties pull people away from it, so a dot in the
    middle is spending time with other courses. The home ring is a drawing choice, not a finding.
    A faded dot's tag was not heard in the window: it may be out of range, off, or failing, which
    is not the same as being alone. A glow marks a self-report press in the last 40 minutes.</p>
    <p>${filters} Signal strength is uncalibrated: the close-range default is a working choice.</p>`);
  set("explain-matrix", `
    <p>The grid splits the window's lines by the courses at each end: the diagonal is ties inside
    a course, the rest are ties between courses (% of all ties). Grey cells have fewer than
    ${meta.min_group} people heard on one side. Click a cell to show only those lines.</p>
    <p>The line below is today's share of ties that cross courses, every 30 minutes, against the
    share expected if the people heard at that moment mixed at random.</p>`);
  set("explain-zones", `
    <p>Participants per zone across the current camp day. A person is placed in the room whose
    tag they heard most in a 5-minute bin; <i>not placed</i> means their tag was heard but no room
    tag often enough. Rooms without a tag never appear. Click a zone to show only the people in it
    at the playhead.</p>`);
  set("explain-presses", `
    <p>Top: self-report presses per hour (holding the button repeats the report, so presses
    seconds apart count once). A dot marks hours with a <b>shared moment</b>: two people at close
    range pressing within 5 minutes of each other. Click to jump.</p>
    <p>Bottom: how many people were at close range at a press, against the same participants'
    ordinary 5-minute bins, per phase of the day. It follows the close-range slider.
    Phases with fewer than ${meta.min_group} presses are not shown.</p>
    <p>${n("presses_without_node")} presses belong to participants who did not consent to the
    beacon module and have no dot, so they are not drawn.</p>`);
  set("explain-strips", `
    <p>Close ties per participant heard (lines in the network, averaged over the people whose tags
    were heard) every 30 minutes, and the number of tags heard per 5 minutes. Shaded spans mark
    known coverage problems; a drop there means fewer scans, not fewer encounters. Yellow dots
    are day notes. Click anywhere to jump.</p>
    <p>Bundle: ${meta.nodes.length} participants, ${meta.files.pairs.count.toLocaleString("en-GB")}
    pair readings at or above ${meta.rssi_floor} dBm; dropped at export: ${n("pairs_no_node")} pair
    readings without a participant at one end, ${n("rooms_dropped")} room readings.</p>`);
}

// The person view's definitions and caveats.
export function personExplanations(ctx) {
  const { meta, person: P } = ctx;
  const set = (id, html) => { document.getElementById(id).innerHTML = html; };
  const r = P.moment_rule;
  set("explain-picker", `
    <p>Every participant with a beacon dot, by the same shuffled number as in the camp view. The
    number carries no study ID and changes with every export. Filter by course and by
    <b>membrane type</b>: high or low trust in life and lust for life, split at the camp's median
    composite (at the median counts as high). People without a survey have no type.</p>
    <p>Each part of a person's view shows only data they consented to: survey, interview, EDA
    and self-report separately, outside exclusion windows. Staff are not in the bundle.</p>`);
  set("explain-profile", `
    <p>The square places everyone with both composites; the large dot is this person, the lines
    are the camp medians. Composites are the confirmatory ones (mean of the core scales'
    z-scores); z here is against the people in this bundle with a survey.</p>
    <p>Below, every trust-in-life (block B) and lust-for-life (block C) scale and gradient: the dot
    is the person's z against the camp, the number the scale mean and its z. ● marks the scales in
    the composite. Click a scale for its items: recoded answers (reverse-keyed items turned) and
    the camp's mean per item. Item codes only, no wording.</p>`);
  set("explain-membrane", `
    <p>The membrane block of the in-person interview, coded with the draft membrane codebook:
    the state in everyday life, on arrival and at the interview (1 closed – 5 open, within the
    person's own range, so not comparable across people), the change over the academy
    (<b>D_academy_lenient</b> is the primary measure; strict and signed-amount variants beside it),
    the person's own account, openers, closers and episodes placed on a day. Codes only: the
    bundle holds no transcript text, evidence or notes.</p>`);
  set("explain-timeline", `
    <p>One row per source, across the academy or one day. <b>Programme</b>: the spine's programme
    items that apply to this person, all-camp items or items in the room they were placed in
    (a dashed outline: the end was not logged and is filled with the kind's median length).
    <b>Place</b>: the zone of the room tag heard most in each 5 minutes (grey: heard but not
    placed; blank: tag not heard). <b>Close others</b>: participants at or above the close-range
    slider in each 5 minutes. <b>Moments</b>: blue ticks are presses (first-person special
    moments), yellow dots EDA moments (third-person, exploratory), the diamond the interview.
    <b>SCR</b> rate and <b>heart rate</b>: per minute in a day view, the mean per 5 minutes over
    the academy. Pale: EDA not worn; yellow tint: the device clock is uncertain, so times there
    may be off by minutes.</p>
    <p><b>EDA moment</b> (exploratory): a usable minute whose SCR rate is at least ${r.z} SD
    above the person-day's mean, in days with at least ${r.min_usable_minutes} usable minutes;
    minutes up to ${r.merge_minutes} min apart join one moment. Not adjusted for movement, and
    not validated: the camp-wide analysis found no arousal peak at presses.</p>
    <p>Click a tick, a dot or any time to look at that moment below.</p>`);
  set("explain-dist", `
    <p>The person's presses and EDA moments per camp day and per phase of the day (bars), against
    the camp's mean per person (lines): participants with a self-report dot for presses,
    participants with worn EDA for EDA moments. The bars follow the SCR rule chosen above.</p>`);
  void meta;
}
