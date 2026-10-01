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
