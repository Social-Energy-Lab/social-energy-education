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
    range pressing within 5 minutes of each other. Click to jump. This is everyone.</p>
    <p>Middle, when people are picked: one row per picked person across the academy, their
    presses as blue ticks and, in the team view, their EDA moments as yellow dots (the person
    view's working rule, exploratory). Click a mark to jump to it, a name to open the person.</p>
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
  if (document.getElementById("explain-sound")) set("explain-sound", `
    <p>Each hall's AudioMoth recorder across the whole camp (or the playhead's day, with "This
    day"), inside its recording slots; a gap is not recorded. The shaded band is the playhead's
    day. <b>Top line: loudness</b>, the Leq (average level) of each 5-minute bin, in dBFS: relative
    to that recorder's full scale, not calibrated decibels. "Louder than 70%" means louder than 70%
    of all 5-minute bins that hall was recorded over the study.</p>
    <p><b>Below: the frequency mix</b>, how the bin's sound power splits between low sound below
    300 Hz (rumble, footsteps, ventilation), the voice range 300–4000 Hz (speech, singing) and high
    sound above 4000 Hz (clatter, hiss). A taller voice band means more of what the recorder heard
    was in the range of voices; it is not a count of speakers.</p>
    <p>Days can be compared within one hall: it is the same recorder. The two halls are drawn on
    their own scales and compared only by their shape over time, never by level, since the
    recorders are not calibrated against each other. No people are in this: it is the room. A
    quiet stretch can be the hall not being used. Exploratory: the team's sound analysis
    (acoustics_over_time) has the figures by day and by programme kind.</p>`);
  set("explain-programme", `
    <p>The day's programme as the field log recorded it: dark items were for the whole camp,
    light ones ran in some rooms only (electives, rehearsals, sport). A dashed edge means the end
    was not recorded and is filled with the usual length of that kind of item. Overlapping items
    get their own rows.</p>
    <p><b>Click a room item to see only its people</b> (click it again, or "Show everyone", to
    go back). Someone counts as at the item when their room tag placed them in one of its rooms
    for more than half of the 5-minute bins they were placed in, from the item's start to the
    playhead. The network, the frame and the views below then show only them and the lines
    between them, counted from the item's start. People whose room tag was not heard cannot be
    placed and drop out. Whole-camp items and items with no room in the log only jump to their
    time. The filter ends when the playhead leaves the item.</p>`);
  set("explain-frame", `
    <p>Everyone whose tag was heard anywhere in the camp in the window before the playhead,
    whatever they were at; click a programme item (in the strip above or under "Programme now")
    to see only the people at it. <b>Close now</b> is the
    network's line: close range for at least the <b>together</b> minutes in the window, which
    is physical nearness, not proof of talking. Each tie is then sorted by how long the same two
    people had been at close range before the window, from the start of the study: <b>new</b>
    under 1 hour, <b>acquainted</b> 1 to 5 hours, <b>close</b> 5 hours or more. That is shared
    time, a proxy for knowing each other, not a measure of the relationship. Early in the
    academy most ties are new by construction; later, few are.</p>
    <p>Click people in the network or the table to pick them (click again to drop). Picked
    people are ringed and named in the network, and the table puts them side by side: minutes
    close now and close time before. Double-click a dot to open the person view.</p>
    <p>A self-report press shows what its presser wrote on their card when they gave a time
    within 45 minutes of it. Most cards give only a day or a programme item, so they are listed
    by day. ${n("descriptions")} written moments are in this bundle; cards without a study ID,
    by staff, or by participants without a dot are not. The frame is only computed while paused.</p>`);
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
    <p><b>Bars: this person only</b>, their presses and EDA moments per camp day and per phase of
    the day. <b>Black lines: the camp</b>, the mean per person, for comparison: over the
    participants with a self-report dot for presses and those with worn EDA for EDA moments. The
    bars follow the SCR rule chosen above. To see several people's presses and EDA moments side
    by side, pick them (or use "Pick … and their top 5" above) and open the camp's
    "Self-reports" view.</p>`);
  set("explain-ties", `
    <p>Everyone who was ever at close range of this person (the close-range setting of the camp
    view), most time together first. <b>Together</b>: the hours of 5-minute bins in which the two
    were at close range, over the whole academy; the small bars split it per camp day, so a tie
    that grew late or faded shows. <b>Shared items</b>: the room items of the programme
    (electives, rehearsals, sport…) both were placed at by their room tag, for most of the
    item; whole-camp items are left out, since everyone was at them. Close range is physical
    nearness, a proxy for shared time, not proof of talking or of a friendship.</p>
    <p>"open" goes to that person, with their membranes, and the breadcrumb at the top comes back.
    "Pick … in the camp" picks this person and their five closest, for the network, the frame and
    the Self-reports view.</p>`);
  void meta;
}
