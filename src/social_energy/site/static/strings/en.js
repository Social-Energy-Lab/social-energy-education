// English copy. Every number is a {placeholder} filled from the data at runtime; method
// settings are written out as words. Keys must match strings/de.js.
export default {
  page_title: "Signatures of social energy · DSA 2026",
  page_description:
    "Who was with whom, and when did a moment move someone? The German Pupils' Academy 2026 as a living network.",
  site_kicker: "Deutsche SchülerAkademie 2026 · a research project",
  lang_switch: "Deutsch",
  lang_switch_label: "Auf Deutsch lesen",
  skip_to_story: "Skip to the story",

  banner_synthetic: "Demo with synthetic data",
  banner_synthetic_sub:
    "Everything on this page is simulated. The real results will appear here once they are cleared for release.",

  hero_title: "The camp breathes",
  hero_lede:
    "Each dot is one person, with no name. People who spent a while close together are joined by a line. And when a dot lights up, someone has pressed the button on their wristband: this moment moved me.",
  legend_dot: "A dot: one person. The colour stands for their course; which course, we don't say.",
  legend_line:
    "A line: close together in at least three five-minute slots of the last two hours.",
  legend_cross: "White line: across courses.",
  legend_glow: "A glow: someone just pressed.",
  legend_faded: "Faded: the wristband wasn't heard for two hours.",
  legend_ring:
    "Each course has its place on the ring. Someone far from it is usually with people from other courses.",

  player_label: "Animated network of the academy: who was with whom, and when",
  player_play: "Play",
  player_pause: "Pause",
  player_speed: "Speed",
  player_speed_value: "{h} h/s",
  player_speed_hint: "hours of academy per second",
  player_day: "Day",
  player_time: "Time",
  player_fullscreen: "Full screen",
  player_exit_fullscreen: "Exit full screen",
  player_night: "Night",
  player_night_sub: "Between midnight and six in the morning we show nothing.",
  player_loading: "Loading the network …",
  player_error: "The data could not be loaded. Reload the page to try again.",
  player_keys: "Space: play or pause · arrow keys: step back and forth",
  player_summary: "{n_participants} participants, day by day, from six in the morning to midnight.",

  phase_morning: "Morning",
  phase_midday: "Midday",
  phase_afternoon: "Afternoon",
  phase_dinner: "Dinner",
  phase_evening: "Evening",
  phase_late: "Late evening",
  phase_night: "Night",
  phase_all: "",

  label_excursion: "Excursion day",
  label_rotation: "Rotation day",
  label_arrival: "Arrival day",
  label_records_missing: "Records missing here, not encounters: the wristband batteries were running low.",

  intro_title: "Signatures of social energy",
  intro_body:
    "Some moments carry a group: an evening when nobody wants to leave, a conversation that won't end. We call this social energy. It can't be measured directly. But it leaves traces: who is together, for how long, and when someone feels moved. We call these traces signatures, and we recorded them during the academy.",
  intro_body2:
    "{n_participants} participants wore wristbands and pressed {n_presses} times in all. What follows are the traces we are following up, and one test we fixed in advance.",
  tier_confirmatory: "Fixed in advance",
  tier_exploratory: "A lead, not proof",
  chart_pending: "The chart for this chapter is coming soon.",

  ch_day_title: "A day at the academy",
  ch_day_body:
    "Course in the morning, lunch, course in the afternoon, then the evening with music, sport and long conversations. The map shows, for every day and time of day, how many others someone had close by on average, and how many people were with no one at all.",
  ch_day_show_others: "Others close by",
  ch_day_show_alone: "With no one",
  ch_day_axis_day: "Day",
  ch_day_axis_phase: "Time of day",

  ch_circles_title:
    "Do courses keep to themselves?",
  ch_circles_body:
    "On ordinary days, {mixing_ordinary_lo} to {mixing_ordinary_hi} % of ties crossed a course boundary. If everyone mixed at random, it would be about {mixing_random} %.",
  ch_circles_body2:
    "On the excursion day the share was {mixing_excursion} %, on the rotation day {mixing_rotation} %. “Show me on the network” moves the network above to the excursion day, where you can compare the ring with an ordinary day.",
  ch_circles_body3:
    "Do the new acquaintances last? Of the ties that formed on an ordinary day, {persistence_ordinary} % came back within the next three days; of those from the excursion day, {persistence_excursion} %.",
  ch_circles_show: "Show me on the network",
  ch_circles_observed: "Across courses",
  ch_circles_expected: "If mixing were random",
  ch_circles_persistence: "Together again within the next three days",
  origin_ordinary: "Ordinary day",
  origin_excursion: "Excursion day",
  origin_rotation: "Rotation day",

  ch_moments_title:
    "Do people press together?",
  ch_moments_body:
    "When two people are close together and both press within a few seconds, it may have been the same moment. We counted how often that happened and compared it with chance: {cascade_excess} times as often as expected (range {cascade_excess_lo} to {cascade_excess_hi}). A value of one would mean as often as by chance.",
  ch_moments_body2:
    "When at most ten seconds lay between the two presses, the ratio was {latency_0_10_ratio}. Here is how to read the curve below: a peak right at the start would suggest two people reacting to the same thing; a later peak would suggest one person setting off the other.",
  ch_moments_body3_pos:
    "Someone who pressed had, on average, {company_gain} more people close by at that moment than usual.",
  ch_moments_body3_neg:
    "Someone who pressed had, on average, {company_gain_abs} fewer people close by at that moment than usual.",
  ch_moments_latency: "Time between two presses",
  ch_moments_size: "Size of the group pressing together",
  ch_moments_ratio: "How often compared with chance",
  ch_moments_reference: "As often as by chance",
  ch_moments_seconds: "seconds",
  ch_moments_people: "people",

  ch_places_title:
    "Where do people press?",
  ch_places_body:
    "We sorted the presses by situation: course, plenary, meals, evening programme and more. The grouping is ours, made from the programme and the rooms. An hour in the plenary brought {plenum_vs_course} times as many presses as an hour in a course.",
  ch_places_rate: "Presses per ten hours",
  setting_plenum: "Plenary",
  setting_course_block: "Course",
  setting_meal_time: "Meals",
  setting_kua_evening: "Evening programme",
  setting_late_evening: "Late evening",
  setting_other_daytime: "Other daytime",
  setting_night: "Night",

  ch_null_title: "What we did not find",
  ch_null_body:
    "Before looking at the data, we wrote down what we would test and how. The idea: people who report more trust in life and more lust for life in the questionnaire are more embedded, mix more across courses and press more often. With {n_confirmatory} participants, this test found no support.",
  ch_null_body2:
    "That doesn't mean the link isn't there. With so few people a small effect can easily stay invisible; the intervals in the chart below show how uncertain the estimates are. It means this academy gives no evidence for it. Everything else on this page is exploratory: leads for the next camps, not tested results.",
  ch_null_axis_sd: "Effect in standard deviations",
  ch_null_axis_rr: "Ratio of press rates",
  ch_null_no_effect: "No effect",
  test_c1: "Trust in life → strength of ties",
  test_c2: "Lust for life → share across courses",
  test_c4_trust: "Trust in life → how often pressed",
  test_c4_lust: "Lust for life → how often pressed",

  ch_how_title: "How this works",
  ch_how_beacons:
    "Every participant who agreed wore a small radio wristband. The wristbands hear each other: for every five-minute slot we know who was close to whom. Fixed transmitters in the rooms also tell which room someone was in; this page does not show that.",
  ch_how_button:
    "The wristband has a button. We asked people to press it whenever a moment moved them, not necessarily in a good way. What made the moment, we don't know.",
  ch_how_not_recorded:
    "Not on this page: where anyone was, questionnaires, interviews and observations. They are part of the study but do not appear here.",
  ch_how_privacy_title: "What we do to protect everyone",
  privacy_names: "No names and no IDs. Nobody can be clicked on or searched for here.",
  privacy_courses: "Courses are not labelled; colours and places on the ring are shuffled.",
  privacy_night: "The nights, between midnight and six in the morning, are not shown.",
  privacy_staff: "Course leaders and staff are not shown, only participants.",
  privacy_presses: "Presses are shown to the nearest five minutes, not to the second.",
  privacy_groups: "Every number rests on at least five people. No result is about a single course.",
  ch_how_tiers:
    "Two kinds of result: the test in “What we did not find” was fixed in advance and is the only one that could confirm or refute anything. Everything else is exploratory: patterns for the next camps to follow up.",
  ch_how_repo:
    "The methods, the code and the analysis plan are open. The data is not: it describes minors and stays with the researchers.",
  ch_how_repo_link: "See the code on GitHub",
  ch_how_cite:
    "Cite as: Social Energy Lab, Signatures of social energy, Deutsche SchülerAkademie 2026, https://github.com/Social-Energy-Lab/social-energy-education",

  footer_project:
    "A research project of Friedrich Schiller University Jena and the Max Planck Institute of Geoanthropology.",
  footer_thanks: "Thank you to everyone who took part.",
  footer_privacy: "This page sets no cookies, counts no visits and loads nothing from other servers.",
};
