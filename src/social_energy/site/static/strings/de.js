// German copy (the default). Every number is a {placeholder} filled from the data at runtime;
// method settings are written out as words. Keys must match strings/en.js.
export default {
  page_title: "Signaturen sozialer Energie · DSA 2026",
  page_description:
    "Wer war wann mit wem zusammen, und wann hat ein Moment bewegt? Die Deutsche SchülerAkademie 2026 als lebendiges Netz.",
  site_kicker: "Deutsche SchülerAkademie 2026 · ein Forschungsprojekt",
  lang_switch: "English",
  lang_switch_label: "Switch to English",
  skip_to_story: "Zur Geschichte springen",

  banner_synthetic: "Demo mit erfundenen Daten",
  banner_synthetic_sub:
    "Alles auf dieser Seite ist simuliert. Die echten Ergebnisse erscheinen hier, sobald sie freigegeben sind.",

  hero_title: "Das Camp atmet",
  hero_lede:
    "Jeder Punkt ist eine Person, ohne Namen. Wer länger nah beieinander war, ist durch eine Linie verbunden. Und wenn ein Punkt aufleuchtet, hat jemand auf den Knopf am Armband gedrückt: Dieser Moment hat mich bewegt.",
  legend_dot: "Ein Punkt: eine Person. Die Farbe steht für ihren Kurs, welcher es ist, verraten wir nicht.",
  legend_line:
    "Eine Linie: in mindestens drei Fünf-Minuten-Abschnitten der letzten zwei Stunden nah beieinander.",
  legend_cross: "Weiße Linie: über Kursgrenzen hinweg.",
  legend_glow: "Leuchten: Jemand hat gerade gedrückt.",
  legend_faded: "Blass: Das Armband war zwei Stunden lang nicht zu hören.",
  legend_ring:
    "Jeder Kurs hat seinen Platz auf dem Ring. Wer weit weg davon ist, ist meist mit Leuten aus anderen Kursen zusammen.",

  player_label: "Animiertes Netz der Akademie: wer wann mit wem zusammen war",
  player_play: "Abspielen",
  player_pause: "Anhalten",
  player_speed: "Tempo",
  player_speed_value: "{h} h/s",
  player_speed_hint: "Stunden Akademie pro Sekunde",
  player_day: "Tag",
  player_time: "Zeitpunkt",
  player_fullscreen: "Vollbild",
  player_exit_fullscreen: "Vollbild beenden",
  player_night: "Nacht",
  player_night_sub: "Zwischen Mitternacht und sechs Uhr zeigen wir nichts.",
  player_loading: "Das Netz wird geladen …",
  player_error: "Die Daten ließen sich nicht laden. Lade die Seite neu, um es noch einmal zu versuchen.",
  player_keys: "Leertaste: abspielen oder anhalten · Pfeiltasten: vor und zurück",
  player_summary:
    "{n_participants} Teilnehmende, Tag für Tag, von sechs Uhr morgens bis Mitternacht.",

  phase_morning: "Vormittag",
  phase_midday: "Mittag",
  phase_afternoon: "Nachmittag",
  phase_dinner: "Abendessen",
  phase_evening: "Abend",
  phase_late: "Spätabend",
  phase_night: "Nacht",
  phase_all: "",

  label_excursion: "Exkursionstag",
  label_rotation: "Rotationstag",
  label_arrival: "Anreisetag",
  label_records_missing: "Hier fehlen Aufzeichnungen, nicht Begegnungen: Die Akkus der Armbänder wurden schwach.",

  intro_title: "Signaturen sozialer Energie",
  intro_body:
    "Manche Momente tragen eine Gruppe: ein Abend, an dem alle bleiben, ein Gespräch, das nicht aufhören will. Wir nennen das soziale Energie. Messen lässt sie sich nicht direkt. Aber sie hinterlässt Spuren: wer zusammen ist, wie lange, und wann sich jemand bewegt fühlt. Diese Spuren, wir nennen sie Signaturen, haben wir während der Akademie aufgezeichnet.",
  intro_body2:
    "{n_participants} Teilnehmende haben Armbänder getragen und insgesamt {n_presses}-mal gedrückt. Was folgt, sind die Spuren, denen wir nachgehen, und eine Prüfung, die wir vorab festgelegt haben.",
  tier_confirmatory: "Vorab festgelegt",
  tier_exploratory: "Eine Spur, kein Beweis",
  chart_pending: "Die Grafik zu diesem Kapitel folgt bald.",
  chart_empty:
    "Für diese Grafik gibt es nicht genug Daten: Jede Zahl muss auf mindestens fünf Personen beruhen.",
  chart_interval_note:
    "Die dünne Linie an jedem Balken zeigt die Spanne der Unsicherheit.",

  ch_day_title: "Ein Tag an der Akademie",
  ch_day_body:
    "Kurs am Vormittag, Essen, Kurs am Nachmittag, dann der Abend mit Musik, Sport und langen Gesprächen. Die Karte zeigt für jeden Tag und jede Tageszeit, wie viele andere jemand im Schnitt in der Nähe hatte und wie viele gerade mit niemandem zusammen waren.",
  ch_day_show_others: "Andere in der Nähe",
  ch_day_show_alone: "Mit niemandem",
  ch_day_axis_day: "Tag",
  ch_day_axis_phase: "Tageszeit",
  ch_day_toggle:
    "Was die Farbe zeigt",
  ch_day_aria:
    "Eine Zeile je Tag, eine Spalte je Tageszeit; je kräftiger die Farbe, desto höher der Wert. Jedes Feld nennt seinen Wert.",
  ch_day_legend:
    "Je kräftiger ein Feld, desto höher der Wert. „Andere in der Nähe“ ist ein Durchschnitt pro Person, „Mit niemandem“ ein Anteil in Prozent. Ein leeres Feld: zu wenige Personen für eine Zahl.",

  ch_circles_title:
    "Bleiben die Kurse unter sich?",
  ch_circles_body:
    "An gewöhnlichen Tagen gingen {mixing_ordinary_lo} bis {mixing_ordinary_hi} % der Verbindungen über Kursgrenzen. Würden sich alle zufällig mischen, wären es etwa {mixing_random} %.",
  ch_circles_body2:
    "Am Exkursionstag lag der Anteil bei {mixing_excursion} %, am Rotationstag bei {mixing_rotation} %. Mit „Im Netz zeigen“ springt das Netz oben zum Exkursionstag, dort lässt sich der Ring mit einem gewöhnlichen Tag vergleichen.",
  ch_circles_body3:
    "Halten die neuen Bekanntschaften? Von den Verbindungen, die an einem gewöhnlichen Tag entstanden, kamen {persistence_ordinary} % in den drei Tagen danach wieder vor; bei denen vom Exkursionstag {persistence_excursion} %.",
  ch_circles_show: "Im Netz zeigen",
  ch_circles_observed: "Über Kursgrenzen",
  ch_circles_expected: "Bei zufälliger Mischung",
  ch_circles_persistence: "Wieder zusammen in den drei Tagen danach",
  ch_circles_aria:
    "Eine Linie zeigt je Tag den Anteil der Verbindungen über Kursgrenzen, eine gestrichelte Linie den Anteil bei zufälliger Mischung; besondere Tage sind hinterlegt.",
  ch_circles_aria_persistence:
    "Ein Balken je Art des Tages, an dem die Verbindung entstand; seine Länge zeigt den Anteil, der in den drei Tagen danach wieder vorkam.",
  ch_circles_share_axis:
    "Anteil in Prozent",
  origin_ordinary: "Gewöhnlicher Tag",
  origin_excursion: "Exkursionstag",
  origin_rotation: "Rotationstag",

  ch_moments_title:
    "Drücken Menschen gemeinsam?",
  ch_moments_body:
    "Wenn zwei Menschen nah beieinander sind und beide innerhalb weniger Sekunden drücken, war das vielleicht derselbe Moment. Wir haben gezählt, wie oft das vorkam, und mit dem Zufall verglichen: {cascade_excess}-mal so oft wie erwartet (Spanne {cascade_excess_lo} bis {cascade_excess_hi}). Ein Wert von eins hieße: so oft wie durch Zufall.",
  ch_moments_body2:
    "Lagen höchstens zehn Sekunden zwischen den beiden Drücken, war das Verhältnis {latency_0_10_ratio}. So lässt sich die Balken unten lesen: Eine Spitze ganz am Anfang spräche dafür, dass zwei auf dasselbe reagiert haben; eine Spitze später eher dafür, dass einer den anderen angesteckt hat.",
  ch_moments_body3_pos:
    "Wer drückte, hatte in diesem Moment im Schnitt {company_gain} Menschen mehr in der Nähe als sonst.",
  ch_moments_body3_neg:
    "Wer drückte, hatte in diesem Moment im Schnitt {company_gain_abs} Menschen weniger in der Nähe als sonst.",
  ch_moments_latency: "Abstand zwischen zwei Drücken",
  ch_moments_size: "Größe der Gruppe, die gemeinsam drückt",
  ch_moments_ratio: "Wie oft im Vergleich zum Zufall",
  ch_moments_reference: "So oft wie durch Zufall",
  ch_moments_seconds: "Sekunden",
  ch_moments_people: "Personen",
  ch_moments_headline:
    "Gemeinsame Drücke im Vergleich zum Zufall: das {cascade_excess}-Fache, Spanne {cascade_excess_lo} bis {cascade_excess_hi}.",
  ch_moments_aria_latency:
    "Ein Balken je Abstand zwischen zwei Drücken; seine Länge zeigt, wie oft solche Paare im Vergleich zum Zufall vorkamen. Die senkrechte Linie markiert: so oft wie durch Zufall.",
  ch_moments_aria_size:
    "Ein Balken je Gruppengröße; seine Länge zeigt, wie oft solche Gruppen gemeinsam drückten, im Vergleich zum Zufall. Die senkrechte Linie markiert: so oft wie durch Zufall.",

  ch_places_title:
    "Wo wird gedrückt?",
  ch_places_body:
    "Wir haben die Drücke nach Situationen sortiert: Kurs, Plenum, Essen, Abendprogramm und mehr. Die Einteilung stammt von uns, aus dem Programm und den Räumen. Auf eine Stunde im Plenum kamen {plenum_vs_course}-mal so viele Drücke wie auf eine Stunde im Kurs.",
  ch_places_rate: "Drücke pro zehn Stunden",
  ch_places_aria:
    "Ein Balken je Situation, sortiert nach der Zahl der Drücke pro zehn Stunden; die dünne Linie zeigt die Spanne der Unsicherheit.",
  setting_plenum: "Plenum",
  setting_course_block: "Kurs",
  setting_meal_time: "Essen",
  setting_kua_evening: "Abendprogramm",
  setting_late_evening: "Später Abend",
  setting_other_daytime: "Sonst tagsüber",
  setting_night: "Nacht",

  ch_null_title: "Was wir nicht gefunden haben",
  ch_null_body:
    "Bevor wir die Daten angesehen haben, haben wir aufgeschrieben, was wir prüfen wollen und wie. Die Vermutung: Wer im Fragebogen mehr Vertrauen ins Leben und mehr Lust aufs Leben angibt, ist stärker eingebunden, mischt sich mehr über Kursgrenzen und drückt öfter. Mit {n_confirmatory} Teilnehmenden fand diese Prüfung keine Bestätigung.",
  ch_null_body2:
    "Das heißt nicht, dass es den Zusammenhang nicht gibt. Bei so wenigen Menschen kann ein kleiner Effekt leicht unsichtbar bleiben; wie groß die Unsicherheit ist, zeigen die Intervalle in der Grafik unten. Es heißt: Diese Akademie liefert keinen Beleg dafür. Alles andere auf dieser Seite ist erkundend, Spuren für die nächsten Camps, keine geprüften Ergebnisse.",
  ch_null_axis_sd: "Effekt in Standardabweichungen",
  ch_null_axis_rr: "Verhältnis der Drückrate",
  ch_null_no_effect: "Kein Effekt",
  ch_null_aria:
    "Ein Punkt je vorab festgelegter Prüfung, die waagrechte Linie zeigt die Spanne der Unsicherheit, die senkrechte Linie markiert: kein Effekt.",
  ch_null_note:
    "So liest man die Grafik: Jeder Punkt ist eine Schätzung, die Linie durch ihn ihre Spanne. Berührt oder kreuzt die Linie die Markierung „Kein Effekt“, sind die Daten auch damit vereinbar, dass es keinen Effekt gibt. Je länger die Linie, desto unsicherer die Schätzung.",
  test_c1: "Vertrauen ins Leben → Stärke der Verbindungen",
  test_c2: "Lust aufs Leben → Anteil über Kursgrenzen",
  test_c4_trust: "Vertrauen ins Leben → wie oft gedrückt",
  test_c4_lust: "Lust aufs Leben → wie oft gedrückt",

  ch_how_title: "Wie das funktioniert",
  ch_how_beacons:
    "Alle Teilnehmenden, die zugestimmt haben, trugen ein kleines Funk-Armband. Die Armbänder hören einander: Für jeden Fünf-Minuten-Abschnitt wissen wir, wer nah beieinander war. Feste Sender in den Räumen verraten auch, in welchem Raum jemand war; das zeigt diese Seite nicht.",
  ch_how_button:
    "Am Armband ist ein Knopf. Wir haben gebeten, ihn zu drücken, wenn ein Moment einen bewegt, nicht unbedingt im guten Sinn. Was den Moment ausgemacht hat, wissen wir nicht.",
  ch_how_not_recorded:
    "Nicht auf dieser Seite: wo jemand war, Fragebögen, Interviews und Beobachtungen. Sie gehören zur Studie, erscheinen hier aber nicht.",
  ch_how_privacy_title: "Was wir zum Schutz aller tun",
  privacy_names: "Keine Namen und keine Kennungen. Niemand lässt sich hier anklicken oder suchen.",
  privacy_courses: "Die Kurse sind nicht beschriftet, Farben und Plätze auf dem Ring sind gemischt.",
  privacy_night: "Die Nächte, zwischen Mitternacht und sechs Uhr, zeigen wir nicht.",
  privacy_staff: "Kursleitungen und Team sind nicht zu sehen, nur Teilnehmende.",
  privacy_presses: "Drücke zeigen wir nur auf fünf Minuten genau, nicht auf die Sekunde.",
  privacy_groups: "Jede Zahl beruht auf mindestens fünf Personen. Kein Ergebnis gilt für einen einzelnen Kurs.",
  ch_how_tiers:
    "Zwei Arten von Ergebnissen: Die Prüfung in „Was wir nicht gefunden haben“ war vorab festgelegt und ist die einzige, die etwas bestätigen oder widerlegen konnte. Alles andere ist erkundend: Muster, denen die nächsten Camps nachgehen.",
  ch_how_repo:
    "Methoden, Code und Analyseplan liegen offen. Die Daten nicht: Sie beschreiben Minderjährige und bleiben bei den Forschenden.",
  ch_how_repo_link: "Zum Code auf GitHub",
  ch_how_cite:
    "Zitieren: Social Energy Lab, Signaturen sozialer Energie, Deutsche SchülerAkademie 2026, https://github.com/Social-Energy-Lab/social-energy-education",

  footer_project:
    "Ein Forschungsprojekt der Friedrich-Schiller-Universität Jena und des Max-Planck-Instituts für Geoanthropologie.",
  footer_thanks: "Danke an alle, die mitgemacht haben.",
  footer_privacy: "Diese Seite setzt keine Cookies, zählt keine Besuche und lädt nichts von anderen Servern.",
};
