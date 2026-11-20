"""Music structure analysis.

The pipeline is a classic, fully deterministic MIR chain (no neural network,
no network access, no model download):

1. beat tracking, then beat-synchronous timbre (MFCC) and harmony (chroma)
   features;
2. two self-similarity matrices, one per feature family;
3. a novelty curve obtained by sliding a Gaussian checkerboard kernel along
   the diagonal of both matrices (Foote, 2000); its peaks are the section
   boundaries;
4. sections are compared pairwise along the best diagonal of the similarity
   matrices and grouped by average-linkage clustering, so repeated sections
   share a group;
5. groups get functional names (Intro, Verse, Chorus, ...) from repetition,
   energy and position heuristics.

Step 5 is a heuristic: boundaries and repetition groups come from the audio,
the *names* are an educated guess that the user is expected to review.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np
import scipy.cluster.hierarchy
import scipy.ndimage
import scipy.signal
import scipy.spatial.distance

ANALYSIS_SR = 22050
HOP_LENGTH = 512

SILENCE_GROUP = -1

LABEL_SILENCE = "Silence"
LABEL_INTRO = "Intro"
LABEL_OUTRO = "Outro"
LABEL_VERSE = "Verse"
LABEL_PRE_CHORUS = "Pre-Chorus"
LABEL_CHORUS = "Chorus"
LABEL_BRIDGE = "Bridge"
LABEL_BREAK = "Break"
LABEL_INTERLUDE = "Interlude"

ProgressCallback = Callable[[float, str], None]


class AnalysisError(Exception):
    """Raised when the audio cannot be analysed at all."""


@dataclass(frozen=True)
class AnalysisConfig:
    """Tunable parameters of the structure analysis."""

    #: Half-width of the checkerboard kernel, in seconds of music.
    kernel_seconds: float = 13.0
    #: Two boundaries are never closer than this.
    min_segment_seconds: float = 4.0
    #: Minimum prominence of a novelty peak (novelty is scaled to 0..1).
    peak_prominence: float = 0.06
    #: Beats of context stacked around each beat before comparing (odd).
    embedding_beats: int = 3
    #: Weight of timbre against harmony in novelty and section similarity.
    timbre_weight: float = 0.5
    #: Sections closer than this (1 - similarity) end up in the same group.
    cluster_threshold: float = 0.38
    #: Level, relative to the loudest frame, under which audio is silence.
    silence_db: float = -50.0
    #: Leading / trailing silence shorter than this is not a section.
    min_silence_seconds: float = 1.0


@dataclass(frozen=True)
class Section:
    """One section of the song. ``group`` is shared by repeated sections."""

    start: float
    end: float
    label: str
    group: int

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(frozen=True)
class AnalysisResult:
    duration: float
    tempo: float
    key: str
    sections: list[Section]
    beat_times: list[float] = field(default_factory=list)
    #: Only the neural engine knows where the bars start.
    downbeat_times: list[float] = field(default_factory=list)
    engine: str = "classic"


def _noop_progress(_fraction: float, _message: str) -> None:
    return None


# --------------------------------------------------------------------------
# Building blocks (pure numpy, unit-tested without audio)
# --------------------------------------------------------------------------


def centered_stack(features: np.ndarray, n_steps: int) -> np.ndarray:
    """Stack ``n_steps`` neighbouring columns *centred* on each column.

    A causal delay embedding (``librosa.feature.stack_memory``) shifts every
    boundary late by about ``n_steps / 2`` beats; centring removes the bias.
    """
    if n_steps <= 1:
        return features
    half = n_steps // 2
    padded = np.pad(features, ((0, 0), (half, n_steps - 1 - half)), mode="edge")
    width = features.shape[1]
    return np.concatenate([padded[:, k : k + width] for k in range(n_steps)], axis=0)


def self_similarity(features: np.ndarray, n_steps: int = 1) -> np.ndarray:
    """Cosine self-similarity matrix of the columns of ``features``."""
    stacked = centered_stack(features, n_steps)
    norms = np.linalg.norm(stacked, axis=0, keepdims=True)
    unit = stacked / np.maximum(norms, 1e-9)
    return unit.T @ unit


def checkerboard_kernel(half_width: int) -> np.ndarray:
    """Gaussian-tapered checkerboard kernel of size ``2 * half_width``."""
    window = scipy.signal.windows.gaussian(2 * half_width, std=half_width / 2.0)
    kernel = np.outer(window, window)
    kernel[:half_width, half_width:] *= -1.0
    kernel[half_width:, :half_width] *= -1.0
    return kernel


def novelty_curve(ssm: np.ndarray, half_width: int) -> np.ndarray:
    """Foote novelty of a self-similarity matrix, scaled to 0..1."""
    n = ssm.shape[0]
    kernel = checkerboard_kernel(half_width)
    padded = np.pad(ssm, half_width, mode="reflect")
    size = 2 * half_width
    out = np.empty(n)
    for i in range(n):
        out[i] = np.sum(padded[i : i + size, i : i + size] * kernel)
    out -= out.min()
    peak = out.max()
    return out / peak if peak > 0 else out


def section_similarity(ssm: np.ndarray, starts: Sequence[int], n: int) -> np.ndarray:
    """Similarity between sections delimited by ``starts`` (beat indices).

    Two sections are compared along the best diagonal of their block of the
    self-similarity matrix, so a repetition is recognised even if one of the
    two occurrences starts a little earlier or is a little shorter. Sections
    of very different length are penalised.
    """
    ends = list(starts[1:]) + [n]
    count = len(starts)
    sim = np.zeros((count, count))
    for i in range(count):
        for j in range(i, count):
            block = ssm[starts[i] : ends[i], starts[j] : ends[j]]
            rows, cols = block.shape
            shortest = min(rows, cols)
            need = max(2, int(0.7 * shortest))
            best = -1.0
            for offset in range(-(rows - 1), cols):
                diagonal = np.diagonal(block, offset)
                if len(diagonal) >= need:
                    best = max(best, float(diagonal.mean()))
            if best > -1.0:
                ratio = shortest / max(rows, cols)
                sim[i, j] = sim[j, i] = best * (0.5 + 0.5 * ratio)
    return sim


def cluster_sections(similarity: np.ndarray, threshold: float) -> list[int]:
    """Group sections by average linkage; groups are numbered by appearance."""
    count = similarity.shape[0]
    if count == 0:
        return []
    if count == 1:
        return [0]
    distance = np.clip(1.0 - similarity, 0.0, None)
    np.fill_diagonal(distance, 0.0)
    condensed = scipy.spatial.distance.squareform(distance, checks=False)
    tree = scipy.cluster.hierarchy.linkage(condensed, method="average")
    raw = scipy.cluster.hierarchy.fcluster(tree, t=threshold, criterion="distance")
    return renumber_groups(raw)


def renumber_groups(groups: Sequence[int]) -> list[int]:
    """Renumber groups 0, 1, 2... in order of first appearance.

    Negative groups (silence) are left untouched.
    """
    mapping: dict[int, int] = {}
    out = []
    for group in groups:
        group = int(group)
        if group < 0:
            out.append(group)
            continue
        if group not in mapping:
            mapping[group] = len(mapping)
        out.append(mapping[group])
    return out


def section_letter(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA ..."""
    letters = ""
    index += 1
    while index > 0:
        index, rem = divmod(index - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def assign_labels(
    groups: Sequence[int],
    energies_db: Sequence[float],
    durations: Sequence[float],
) -> list[str]:
    """Give a functional name to every section.

    ``groups`` comes from :func:`cluster_sections` (``SILENCE_GROUP`` marks
    silence). The rules, in order:

    * the most "anthemic" repeated group (loud, repeated, not the opening
      one when there is an alternative) is the **Chorus**;
    * the repeated group that first appears before the first chorus is the
      **Verse**; a repeated group that is nearly always followed by the
      chorus is the **Pre-Chorus**;
    * other repeated groups are called ``Section A``, ``Section B``...
    * sections that never repeat are **Intro** (first), **Outro** (last),
      **Bridge** (between two choruses, late in the song), **Break** (much
      quieter than the rest) or **Interlude**.
    """
    count = len(groups)
    labels = [""] * count
    music = [i for i in range(count) if groups[i] != SILENCE_GROUP]
    for i in range(count):
        if groups[i] == SILENCE_GROUP:
            labels[i] = LABEL_SILENCE
    if not music:
        return labels

    members: dict[int, list[int]] = {}
    for i in music:
        members.setdefault(groups[i], []).append(i)
    repeated = [g for g, idx in members.items() if len(idx) >= 2]

    weights = np.array([durations[i] for i in music], dtype=float)
    levels = np.array([energies_db[i] for i in music], dtype=float)
    mean_level = float(np.average(levels, weights=np.maximum(weights, 1e-6)))

    def group_level(group: int) -> float:
        idx = members[group]
        w = np.maximum([durations[i] for i in idx], 1e-6)
        return float(np.average([energies_db[i] for i in idx], weights=w))

    first, last = music[0], music[-1]
    names: dict[int, str] = {}

    chorus = None
    if repeated:
        candidates = [g for g in repeated if members[g][0] != first] or repeated

        def chorus_score(group: int) -> float:
            return (group_level(group) - mean_level) / 3.0 + 0.5 * len(members[group])

        chorus = max(candidates, key=chorus_score)
        names[chorus] = LABEL_CHORUS

        first_chorus = members[chorus][0]
        others = [g for g in repeated if g != chorus]
        before = [g for g in others if members[g][0] < first_chorus]
        verse = None
        pre = None
        if before:
            # A group whose occurrences mostly lead straight into the chorus
            # is a pre-chorus, provided another group can be the verse.
            def leads_to_chorus(group: int) -> float:
                idx = members[group]
                hits = sum(1 for i in idx if i + 1 < count and groups[i + 1] == chorus)
                return hits / len(idx)

            ordered = sorted(before, key=lambda g: members[g][0])
            if len(ordered) >= 2:
                lead = max(ordered, key=leads_to_chorus)
                if leads_to_chorus(lead) >= 0.6 and lead != ordered[0]:
                    pre = lead
            verse = next(g for g in ordered if g != pre)
        elif others:
            verse = min(others, key=lambda g: members[g][0])
        if verse is not None:
            names[verse] = LABEL_VERSE
        if pre is not None:
            names[pre] = LABEL_PRE_CHORUS

    letter = 0
    for group in sorted(members, key=lambda g: members[g][0]):
        if group in names or len(members[group]) < 2:
            continue
        names[group] = f"Section {section_letter(letter)}"
        letter += 1

    chorus_positions = members[chorus] if chorus is not None else []
    for i in music:
        group = groups[i]
        if group in names:
            labels[i] = names[group]
            continue
        if i == first:
            labels[i] = LABEL_INTRO
        elif i == last:
            labels[i] = LABEL_OUTRO
        elif energies_db[i] < mean_level - 8.0:
            labels[i] = LABEL_BREAK
        elif (
            len(chorus_positions) >= 2
            and chorus_positions[0] < i < chorus_positions[-1]
            and i > count / 2
        ):
            labels[i] = LABEL_BRIDGE
        else:
            labels[i] = LABEL_INTERLUDE

    if not repeated:
        # Nothing repeats: letters carry more information than a row of
        # "Interlude".
        for i in music:
            if labels[i] == LABEL_INTERLUDE:
                labels[i] = f"Section {section_letter(letter)}"
                letter += 1
    return labels


_KS_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_KS_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
_PITCH_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]


def estimate_key(chroma_mean: np.ndarray) -> str:
    """Krumhansl-Schmuckler key estimate, e.g. ``"Em"`` or ``"G"``."""
    if chroma_mean.shape != (12,) or not np.any(chroma_mean > 0):
        return ""
    best_score = -np.inf
    best = ""
    for tonic in range(12):
        rotated = np.roll(chroma_mean, -tonic)
        for profile, suffix in ((_KS_MAJOR, ""), (_KS_MINOR, "m")):
            score = float(np.corrcoef(rotated, profile)[0, 1])
            if score > best_score:
                best_score = score
                best = _PITCH_NAMES[tonic] + suffix
    return best


def pick_boundaries(novelty: np.ndarray, min_distance: int, prominence: float) -> np.ndarray:
    """Beat indices of the novelty peaks."""
    smooth = scipy.ndimage.gaussian_filter1d(novelty, 1.0)
    peaks, _ = scipy.signal.find_peaks(smooth, distance=max(1, min_distance), prominence=prominence)
    return peaks


# --------------------------------------------------------------------------
# Audio front end
# --------------------------------------------------------------------------


def _beat_grid(onset_env: np.ndarray, sr: int, n_frames: int) -> tuple[float, np.ndarray]:
    import librosa

    tempo, beats = librosa.beat.beat_track(
        onset_envelope=onset_env, sr=sr, hop_length=HOP_LENGTH, trim=False
    )
    tempo = float(np.atleast_1d(tempo)[0])
    if len(beats) < 8 or tempo <= 0:
        # No usable pulse (ambient, rubato, speech): fall back to a 0.5 s grid.
        step = max(1, int(round(0.5 * sr / HOP_LENGTH)))
        beats = np.arange(0, n_frames, step)
        tempo = 0.0
    beats = librosa.util.fix_frames(beats, x_min=0, x_max=None)
    beats = beats[beats < n_frames]
    return tempo, beats


def analyze(
    samples: np.ndarray,
    sr: int,
    config: AnalysisConfig | None = None,
    progress: ProgressCallback | None = None,
) -> AnalysisResult:
    """Analyse a mono or multi-channel signal and return its structure.

    ``samples`` is ``(n,)`` or ``(n, channels)`` float audio at rate ``sr``.
    """
    import librosa

    cfg = config or AnalysisConfig()
    report = progress or _noop_progress

    y = np.asarray(samples, dtype=np.float32)
    if y.ndim == 2:
        y = y.mean(axis=1)
    if y.ndim != 1 or y.size == 0:
        raise AnalysisError("Il file non contiene audio.")
    if not np.all(np.isfinite(y)):
        y = np.nan_to_num(y, nan=0.0, posinf=0.0, neginf=0.0)
    duration = len(y) / float(sr)

    report(0.05, "Ricampionamento")
    if sr != ANALYSIS_SR:
        y = librosa.resample(y, orig_sr=sr, target_sr=ANALYSIS_SR)
    sr = ANALYSIS_SR

    rms = librosa.feature.rms(y=y, hop_length=HOP_LENGTH)[0]
    n_frames = len(rms)
    peak = float(rms.max()) if n_frames else 0.0
    if peak <= 1e-6 or duration < 2 * cfg.min_segment_seconds:
        label = LABEL_SILENCE if peak <= 1e-6 else f"Section {section_letter(0)}"
        group = SILENCE_GROUP if peak <= 1e-6 else 0
        return AnalysisResult(duration, 0.0, "", [Section(0.0, duration, label, group)])
    rms_db = 20.0 * np.log10(np.maximum(rms, 1e-10) / peak)

    report(0.15, "Rilevamento del tempo")
    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP_LENGTH)
    tempo, beats = _beat_grid(onset_env, sr, n_frames)

    report(0.35, "Analisi armonica")
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=HOP_LENGTH, bins_per_octave=36)
    report(0.6, "Analisi timbrica")
    mel = librosa.feature.melspectrogram(y=y, sr=sr, hop_length=HOP_LENGTH)
    mfcc = librosa.feature.mfcc(S=librosa.power_to_db(mel), n_mfcc=14)[1:]

    width = min(n_frames, chroma.shape[1], mfcc.shape[1])
    chroma, mfcc, rms_db = chroma[:, :width], mfcc[:, :width], rms_db[:width]
    beats = beats[beats < width]

    timbre = librosa.util.sync(mfcc, beats, aggregate=np.mean)
    timbre = (timbre - timbre.mean(axis=1, keepdims=True)) / np.maximum(
        timbre.std(axis=1, keepdims=True), 1e-9
    )
    harmony = librosa.util.sync(chroma, beats, aggregate=np.median)
    level = librosa.util.sync(rms_db[np.newaxis, :], beats, aggregate=np.median)[0]
    n_beats = timbre.shape[1]
    edges = np.concatenate([beats, [width]])[: n_beats + 1]
    edge_times = librosa.frames_to_time(edges, sr=sr, hop_length=HOP_LENGTH)
    edge_times[0] = 0.0
    edge_times[-1] = duration
    beat_period = float(np.median(np.diff(edge_times))) if n_beats > 1 else 0.5

    active = rms_db > cfg.silence_db
    key = estimate_key(chroma[:, active].mean(axis=1)) if np.any(active) else ""

    report(0.75, "Ricerca dei confini")
    half_width = int(round(cfg.kernel_seconds / max(beat_period, 1e-3)))
    half_width = max(2, min(half_width, 64, n_beats // 4))
    starts = [0]
    if n_beats >= 8:
        ssm_timbre = self_similarity(timbre, cfg.embedding_beats)
        ssm_harmony = self_similarity(harmony, cfg.embedding_beats)
        w = cfg.timbre_weight
        novelty = w * novelty_curve(ssm_timbre, half_width) + (1 - w) * novelty_curve(
            ssm_harmony, half_width
        )
        min_distance = int(round(cfg.min_segment_seconds / max(beat_period, 1e-3)))
        peaks = pick_boundaries(novelty, min_distance, cfg.peak_prominence)
        starts += [int(p) for p in peaks if 0 < p < n_beats]
    else:
        ssm_timbre = ssm_harmony = np.ones((n_beats, n_beats))

    # Leading / trailing silence become their own sections.
    silent_beat = level <= cfg.silence_db
    lead = int(np.argmax(~silent_beat)) if np.any(~silent_beat) else 0
    trail = n_beats - int(np.argmax(~silent_beat[::-1])) if np.any(~silent_beat) else n_beats
    min_beats = max(1, int(round(cfg.min_segment_seconds / max(beat_period, 1e-3))))
    has_lead = edge_times[lead] >= cfg.min_silence_seconds
    has_trail = duration - edge_times[trail] >= cfg.min_silence_seconds
    lo = lead + min_beats // 2 if has_lead else 0
    hi = trail - min_beats // 2 if has_trail else n_beats
    starts = [0] + [s for s in starts[1:] if lo < s < hi]
    if has_lead and 0 < lead < n_beats:
        starts.append(lead)
    if has_trail and 0 < trail < n_beats:
        starts.append(trail)
    starts = sorted(set(starts))

    ends = starts[1:] + [n_beats]
    energies = [float(np.median(level[s:e])) for s, e in zip(starts, ends)]
    durations = [float(edge_times[e] - edge_times[s]) for s, e in zip(starts, ends)]
    silent = [(has_lead and e <= lead) or (has_trail and s >= trail) for s, e in zip(starts, ends)]

    report(0.85, "Confronto delle sezioni")
    music = [i for i, is_silent in enumerate(silent) if not is_silent]
    groups = [SILENCE_GROUP] * len(starts)
    if music:
        music_starts = [starts[i] for i in music]
        stop = ends[music[-1]]
        w = cfg.timbre_weight
        similarity = w * section_similarity(ssm_timbre, music_starts, stop) + (
            1 - w
        ) * section_similarity(ssm_harmony, music_starts, stop)
        for i, group in zip(music, cluster_sections(similarity, cfg.cluster_threshold)):
            groups[i] = group

    labels = assign_labels(groups, energies, durations)
    sections = [
        Section(float(edge_times[s]), float(edge_times[e]), label, group)
        for s, e, label, group in zip(starts, ends, labels, groups)
    ]
    report(1.0, "Analisi completata")
    return AnalysisResult(
        duration=duration,
        tempo=round(tempo, 1),
        key=key,
        sections=sections,
        beat_times=[float(t) for t in edge_times[:-1]],
    )
