"""The camp breathes: an animated co-presence network over DSA 2026, with self-report presses.

Research question: RQ3, embedded vs peripheral participation and formal vs informal settings, and
RQ1, what "moved" moments look like from the outside (`research/questions.md`). This is a picture
for looking at the data together, not an analysis that tests anything.

Unit: the participant. An edge joins two participants who were at close range
(``cp.CLOSE_RSSI``) in at least ``EDGE_MIN_BINS`` of the 5-minute bins in a sliding ``WINDOW``.
A node flashes when its wearer starts a self-report episode, and the flash fades over ``FLASH``.

Filters: nodes and edges inherit every filter of ``copresence_by_phase.py build`` (window, spine
resolution, exclusion windows, ``beacons`` consent), which must have run first; flashes inherit
``self_report_context.press_episodes`` (``self_report`` consent). Participants only. Presses by
participants without a node (no ``beacons`` consent) are not drawn and are counted in ``qa.json``.

Layout: each course has a home on a ring. Nodes are pulled weakly home and strongly along their
edges, so a node far from home is with people from other courses. Positions come from a small
force simulation stepped every frame, so they move continuously. The home ring is a design choice
that makes mixing readable, not a finding `[inferred]`.

The video shows individual, unlabelled participants. It is for internal meetings of the research
team only and is never published or committed.

    uv run --extra analysis python studies/dsa-2026/analyses/camp_breathes.py [--preview]
    uv run --extra analysis python studies/dsa-2026/analyses/camp_breathes.py --day 2026-08-20 \\
        --frames-per-step 8
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import copresence_by_phase as cp
import self_report_context as sr

from social_energy import paths
from social_energy.spine import Spine

SLUG = "camp-breathes"
BIN = timedelta(minutes=5)
#: Sliding window over which an edge is counted, and the step between keyframes.
WINDOW_BINS = 24  # 2 h
STEP_BINS = 6  # 30 min
#: An edge: close in at least this many bins of the window (15 min) `[inferred]`.
EDGE_MIN_BINS = 3
FRAMES_PER_STEP = 2
FPS = 30
FLASH = timedelta(minutes=40)
#: Dark-surface categorical slots 1-5 and 7 of the dataviz palette (green is too dark on this
#: surface); validated with the palette checker.
SURFACE = "#1a1a19"
INK, INK_2, INK_3 = "#ffffff", "#c3c2b7", "#8a8984"
COURSE_COLORS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#9085e9"]
FLASH_COLOR = "#fff3b0"
BATTERY_DAYS = ("2026-08-24", "2026-08-28")  # 24-27 Aug, see copresence_by_phase
NOTES = {
    "2026-08-13": "arrival day",
    "2026-08-18": "excursion day",
    "2026-08-22": "rotation day",
    "2026-08-24": "tag batteries failing: fewer scans, not fewer encounters",
    "2026-08-25": "tag batteries failing: fewer scans, not fewer encounters",
    "2026-08-26": "tag batteries failing: fewer scans, not fewer encounters",
    "2026-08-27": "tag batteries failing: fewer scans, not fewer encounters",
}


def local_dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=ZoneInfo(cp.TZ))


def build_arrays(participants: set[str], consented_sr: set[str], layout, spine):
    """Per-bin close-contact and seen arrays over the camp, indexed by node."""
    start = local_dt(f"{cp.FIRST_DAY} 07:30")
    end = local_dt(f"{cp.LAST_DAY} 07:30")
    n_bins = int((end - start) / BIN)
    t0 = pl.lit(start).dt.convert_time_zone("UTC")

    beacon_ok = {f"person:{p}" for p in spine.consented("beacons")}
    nodes = sorted(participants & beacon_ok)
    idx = {p: i for i, p in enumerate(nodes)}
    n = len(nodes)

    def bin_index(df: pl.DataFrame) -> pl.DataFrame:
        return df.with_columns(
            ((pl.col("bin") - t0).dt.total_seconds() // BIN.total_seconds())
            .cast(pl.Int64)
            .alias("k")
        ).filter((pl.col("k") >= 0) & (pl.col("k") < n_bins))

    pairs = (
        cp.load_all("pairs")
        .filter(
            pl.col("a").is_in(nodes)
            & pl.col("b").is_in(nodes)
            & (pl.col("max_rssi") >= cp.CLOSE_RSSI)
        )
        .pipe(bin_index)
    )
    close = np.zeros((n_bins, n, n), dtype=np.uint8)
    ka = pairs["k"].to_numpy()
    ia = np.array([idx[p] for p in pairs["a"]])
    ib = np.array([idx[p] for p in pairs["b"]])
    close[ka, ia, ib] = 1
    close[ka, ib, ia] = 1

    seen_df = cp.load_all("seen").filter(pl.col("entity").is_in(nodes)).pipe(bin_index)
    seen = np.zeros((n_bins, n), dtype=np.uint8)
    seen[seen_df["k"].to_numpy(), [idx[p] for p in seen_df["entity"]]] = 1

    presses, qa = sr.press_episodes(layout, spine, participants, consented_sr)
    qa["presses_without_node"] = presses.filter(~pl.col("entity").is_in(nodes)).height
    presses = presses.filter(pl.col("entity").is_in(nodes)).with_columns(
        ((pl.col("t") - t0).dt.total_seconds() / BIN.total_seconds()).alias("k")
    )
    press_k = presses["k"].to_numpy()
    press_i = np.array([idx[p] for p in presses["entity"]])
    qa["presses_drawn"] = len(press_k)
    return start, nodes, close, seen, press_k, press_i, qa


def keyframes(close: np.ndarray, seen: np.ndarray):
    """Edge weights and visibility per keyframe, from windows ending at each step."""
    cum = np.concatenate([np.zeros((1, *close.shape[1:]), np.int32), close.cumsum(0, np.int32)])
    cum_seen = np.concatenate([np.zeros((1, seen.shape[1]), np.int32), seen.cumsum(0, np.int32)])
    ends = np.arange(STEP_BINS, close.shape[0] + 1, STEP_BINS)
    lo = np.maximum(ends - WINDOW_BINS, 0)
    counts = cum[ends] - cum[lo]
    weight = np.where(counts >= EDGE_MIN_BINS, counts / WINDOW_BINS, 0.0).astype(np.float32)
    visible = (cum_seen[ends] - cum_seen[lo]) > 0
    return ends, weight, visible


class Simulation:
    """A small force layout that is stepped, not solved, so it moves continuously."""

    def __init__(self, home: np.ndarray, seed: int = 0):
        rng = np.random.default_rng(seed)
        self.home = home
        self.pos = home + rng.normal(0, 0.05, home.shape)
        self.vel = np.zeros_like(home)

    def step(self, w: np.ndarray, vis: np.ndarray, substeps: int = 4) -> None:
        for _ in range(substeps):
            d = self.pos[None, :, :] - self.pos[:, None, :]  # d[i, j] = pos j - pos i
            dist = np.linalg.norm(d, axis=2) + np.eye(len(d))
            unit = d / dist[..., None]
            spring = (w * 0.6 * (dist - 0.12))[..., None] * unit
            both = (vis[:, None] & vis[None, :]).astype(float) * 0.9 + 0.1
            push = -(both * 0.0012 / np.maximum(dist, 0.04) ** 2)[..., None] * unit
            np.einsum("ii->i", push[..., 0])[:] = 0
            np.einsum("ii->i", push[..., 1])[:] = 0
            gravity = np.where(vis, 0.03, 0.08)[:, None] * (self.home - self.pos)
            force = spring.sum(1) + push.sum(1) + gravity
            self.vel = (self.vel + 0.25 * force) * 0.7
            speed = np.linalg.norm(self.vel, axis=1, keepdims=True)
            self.vel *= np.minimum(1, 0.03 / np.maximum(speed, 1e-9))
            self.pos += self.vel


def homes(course_idx: np.ndarray, rng_seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(rng_seed)
    angle = course_idx / 6 * 2 * np.pi + np.pi / 2
    center = np.stack([np.cos(angle), np.sin(angle)], axis=1) * 0.85
    return center + rng.normal(0, 0.1, center.shape)


def phase_of(t: datetime) -> str:
    clock = t.time()
    for name, begin in sorted(cp.PHASES, key=lambda p: p[1], reverse=True):
        if clock >= begin and name != "night":
            return name
    return "late" if clock.hour < 2 else "night"


def render(preview: bool = False, day: str | None = None, per_step: int = FRAMES_PER_STEP) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.animation import FFMpegWriter
    from matplotlib.collections import LineCollection

    layout = paths.study(cp.STUDY)
    spine = Spine.load(layout.spine)
    out = layout.derived / "analyses" / SLUG
    out.mkdir(parents=True, exist_ok=True)
    participants = {p.ref for p in spine.people if p.role == "participant"}
    consented_sr = {f"person:{p}" for p in spine.consented("self_report")}
    roster = next((layout.root / "context" / "personal").glob("*StudyIDs*.md"))
    course = cp.course_of(roster)

    start, nodes, close, seen, press_k, press_i, qa = build_arrays(
        participants, consented_sr, layout, spine
    )
    ends, weight, visible = keyframes(close, seen)
    courses = sorted({course[p] for p in nodes if p in course})
    c_idx = np.array([courses.index(course[p]) if p in course else -1 for p in nodes])
    qa.update(nodes=len(nodes), no_course=int((c_idx < 0).sum()), keyframes=len(ends))
    color = np.array([COURSE_COLORS[c] if c >= 0 else INK_3 for c in c_idx])
    same_course = c_idx[:, None] == c_idx[None, :]

    # Summary strips: mean ties per visible participant, and presses per hour.
    ties = np.array([(w > 0).sum() / max(v.sum(), 1) for w, v in zip(weight, visible, strict=True)])
    hours = np.arange(0, close.shape[0] // 12)
    press_hour = np.bincount((press_k // 12).astype(int), minlength=len(hours))[: len(hours)]

    plt.rcParams.update({"font.family": "DejaVu Sans", "text.color": INK})
    fig = plt.figure(figsize=(16, 9), dpi=120, facecolor=SURFACE)
    ax = fig.add_axes((0.01, 0.22, 0.66, 0.76), facecolor=SURFACE)
    ax.set_xlim(-1.95, 1.95)
    ax.set_ylim(-1.5, 1.5)
    ax.set_aspect("equal")
    ax.axis("off")

    # Course legend on the home ring, so the label sits where the course lives.
    for c, name in enumerate(courses):
        a = c / 6 * 2 * np.pi + np.pi / 2
        ax.text(
            1.78 * np.cos(a), 1.4 * np.sin(a), f"course {name}", color=COURSE_COLORS[c],
            ha="center", va="center", fontsize=13, fontweight="bold",
        )  # fmt: skip

    edges_lc = LineCollection([], linewidths=1.2, zorder=1)
    ax.add_collection(edges_lc)
    halo = ax.scatter([], [], s=[], c=FLASH_COLOR, alpha=0.0, zorder=2, linewidths=0)
    dots = ax.scatter([], [], s=70, zorder=3, linewidths=1.5, edgecolors=SURFACE)

    # Right panel: when, and what was going on.
    fig.text(0.69, 0.90, "DSA 2026 · who is close to whom", color=INK_2, fontsize=15)
    t_day = fig.text(0.69, 0.80, "", color=INK, fontsize=34, fontweight="bold")
    t_clock = fig.text(0.69, 0.73, "", color=INK, fontsize=26)
    t_note = fig.text(0.69, 0.67, "", color=FLASH_COLOR, fontsize=14, wrap=True)
    key = (
        "Each dot is one participant (no IDs), coloured by course.\n"
        "A line: close range for ≥15 min in the last 2 hours.\n"
        "Coloured line: same course. White line: across courses.\n"
        "A glow: that participant pressed their button\n"
        '("I feel moved").\n\n'
        "Each course has a home; ties pull people away from it.\n"
        "Faded dot: tag not heard in the last 2 hours.\n"
        "Grey dot: course not known."
    )
    fig.text(0.69, 0.30, key, color=INK_2, fontsize=11.5, linespacing=1.6, va="bottom")

    # Bottom strips share the time axis (hours since start), one measure each.
    def strip(rect, title):
        s = fig.add_axes(rect, facecolor=SURFACE)
        s.set_xlim(0, len(hours))
        for side in ("top", "right", "left"):
            s.spines[side].set_visible(False)
        s.spines["bottom"].set_color(INK_3)
        s.tick_params(colors=INK_3, labelsize=9, length=0)
        s.set_yticks([])
        s.text(0, 1.02, title, transform=s.transAxes, color=INK_2, fontsize=10, va="bottom")
        for lo_s, hi_s in [BATTERY_DAYS]:
            lo_h = (local_dt(f"{lo_s} 07:30") - start) / timedelta(hours=1)
            hi_h = (local_dt(f"{hi_s} 07:30") - start) / timedelta(hours=1)
            s.axvspan(lo_h, hi_h, color="#2a2a28", zorder=0, lw=0)
            s.text(
                (lo_h + hi_h) / 2, 1.02, "tag batteries failing", transform=s.get_xaxis_transform(),
                color=INK_3, fontsize=9, ha="center", va="bottom",
            )  # fmt: skip
        return s

    days = [start + timedelta(days=d) for d in range(len(hours) // 24)]
    s1 = strip((0.05, 0.12, 0.90, 0.07), "close ties per participant")
    s1.plot(ends / 12, ties, color="#3987e5", lw=1.5)
    s1.set_xticks([])
    s2 = strip((0.05, 0.035, 0.90, 0.05), "button presses per hour")
    s2.bar(hours + 0.5, press_hour, width=1.0, color=FLASH_COLOR, lw=0)
    s2.set_xticks([d_i * 24 + 12 for d_i in range(len(days))])
    s2.set_xticklabels([d.strftime("%a %d") for d in days])
    cursors = [s.axvline(0, color=INK, lw=1.2) for s in (s1, s2)]

    sim = Simulation(homes(np.maximum(c_idx, 0)))
    # Settle the first layout before recording.
    for _ in range(40):
        sim.step(weight[0], visible[0])

    first = 0
    n_steps = len(ends) - 1
    if day:  # one camp day, 07:30 to 07:30
        first = int((local_dt(f"{day} 07:30") - start) / (BIN * STEP_BINS))
        n_steps = 24 * 60 // (5 * STEP_BINS)
    elif preview:
        n_steps = 96  # two days
    for _ in range(first * 2):  # let the layout catch up with the day it starts on
        sim.step(weight[first], visible[first])
    n_frames = n_steps * per_step
    writer = FFMpegWriter(
        fps=FPS, codec="libx264", extra_args=["-pix_fmt", "yuv420p", "-crf", "20"]
    )
    name = f"day_{day}" if day else "preview" if preview else "camp"
    video = out / f"camp_breathes_{name}.mp4"
    snapshots = {}
    with writer.saving(fig, str(video), dpi=120):
        for f in range(n_frames):
            k, frac = divmod(f, per_step)
            k += first
            frac /= per_step
            w = (1 - frac) * weight[k] + frac * weight[k + 1]
            vis = visible[k + 1] if frac >= 0.5 else visible[k]
            sim.step(w, vis)
            p = sim.pos

            ii, jj = np.nonzero(np.triu(w > 0))
            segs = np.stack([p[ii], p[jj]], axis=1)
            alpha = np.clip(w[ii, jj] * 2.2, 0.15, 0.85)
            rgba = np.array(
                [
                    matplotlib.colors.to_rgba(color[i] if same_course[i, j] else INK, a)
                    for i, j, a in zip(ii, jj, alpha, strict=True)
                ]
            ).reshape(-1, 4)
            edges_lc.set_segments(segs)
            edges_lc.set_color(rgba)

            now_bins = ends[k] + frac * STEP_BINS  # bins since start at the window's end
            age = (now_bins - press_k) * BIN.total_seconds() / FLASH.total_seconds()
            live = (age >= 0) & (age < 1)
            glow = np.zeros(len(nodes))
            np.maximum.at(glow, press_i[live], 1 - age[live])
            halo.set_offsets(p)
            halo.set_sizes(900 * glow)
            halo.set_alpha(0.55)

            face = np.array([matplotlib.colors.to_rgba(c) for c in color])
            face[~vis, 3] = 0.18
            dots.set_offsets(p)
            dots.set_facecolors(face)

            now = start + now_bins * BIN
            t_day.set_text(now.strftime("%a %d %b"))
            t_clock.set_text(f"{now:%H:%M}  ·  {phase_of(now)}")
            camp_day = (now - timedelta(hours=7, minutes=30)).date().isoformat()
            t_note.set_text(NOTES.get(camp_day, ""))
            for c_line in cursors:
                c_line.set_xdata([now_bins / 12, now_bins / 12])
            writer.grab_frame(facecolor=SURFACE)
            if not (preview or day) and now.strftime("%d %H:%M") in {
                "13 16:00",
                "20 21:00",
                "22 11:00",
            }:
                snapshots[now.strftime("%d_%H%M")] = True
                fig.savefig(out / f"still_{now:%d_%H%M}.png", facecolor=SURFACE)
    qa["frames"] = n_frames
    qa["stills"] = sorted(snapshots)
    (out / "qa.json").write_text(json.dumps(qa, indent=2, default=str), encoding="utf-8")
    print(json.dumps(qa, indent=2, default=str))
    print(video)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true", help="first two days only")
    ap.add_argument("--day", help="one camp day, slowly, e.g. 2026-08-20")
    ap.add_argument("--frames-per-step", type=int, default=FRAMES_PER_STEP)
    a = ap.parse_args()
    render(a.preview, a.day, a.frames_per_step)
