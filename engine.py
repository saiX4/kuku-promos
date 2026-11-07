"""Entry-boundary windows, transparent heuristics and temporal suppression."""
from dataclasses import dataclass, field
import math
import re
from parser import Entry

CONFLICT = re.compile(r"\b(?:betray\w*|lie|liar|marry|married|stop|touch|money|bastard|poison\w*|kill\w*|dead|die|dying|blood\w*|slap\w*|strike|struck|threat\w*|secret|husband|wife|ruin\w*|arrest\w*|murder\w*|pregnan\w*|duke)\b", re.I)
SUSPENSE = re.compile(r"\b(?:truth|secret|poison\w*|kill\w*|danger\w*|revenge|pay|regret|destroy\w*|reveal\w*|discover\w*|recogniz\w*|never|unless|or else|this time|who|why|what|how|will|shall)\b", re.I)
ACTION_INTENSE = re.compile(r"\b(?:slap\w*|struck|blood\w*|scream\w*|gasp\w*|blade|knife|gun|collaps\w*|poison\w*|chok\w*|grab\w*|wound\w*|kill\w*|dead|dying)\b", re.I)


def clean(text):
    return text.strip().strip('"\u201c\u201d').strip()


def starts_clean(entry):
    return not re.match(r"^(?:\.{2,}|\u2026|--|\u2014)", clean(entry.content))


def ends_clean(entry, following):
    text = clean(entry.content)
    # A suspended thought is allowed only if it is not the first half of a split line.
    interrupted = bool(re.search(r"(?:\.{2,}|\u2026|--|\u2014)$", text))
    if interrupted and following and following.speaker == entry.speaker and not starts_clean(following):
        return False
    return bool(re.search(r"[.!?\u2026\u2014]$|--$", text))


@dataclass
class Candidate:
    candidate_id: str
    episode_id: str
    start_sec: float
    end_sec: float
    entries: list[Entry]
    scores: dict = field(default_factory=dict)
    evaluation: dict = field(default_factory=dict)

    @property
    def duration(self):
        return round(self.end_sec - self.start_sec, 6)

    @property
    def speakers(self):
        return sorted({e.speaker for e in self.entries if e.kind == "dialogue"})

    def edge(self, hook=True):
        a, b = (self.start_sec, self.start_sec + 3) if hook else (self.end_sec - 3, self.end_sec)
        return [e for e in self.entries if e.kind in ("dialogue", "action") and e.start_sec < b and e.end_sec > a]


def generate(entries, min_duration=20.0, max_duration=60.0):
    # Camera and SFX metadata cannot create false hooks or speaker diversity.
    anchors = [e for e in entries if e.kind in ("dialogue", "action")]
    dialogue = [e for e in entries if e.kind == "dialogue"]
    result = []
    for i, first in enumerate(anchors):
        if not starts_clean(first):
            continue
        for last in anchors[i:]:
            span = round(last.end_sec - first.start_sec, 6)
            # End times of overlapping tracks are not monotonic: do not early-break on end.
            if last.start_sec - first.start_sec > max_duration:
                break
            if not min_duration <= span <= max_duration or first.scene_id != last.scene_id:
                continue
            following = next((e for e in dialogue if e.start_sec >= last.end_sec), None)
            if not ends_clean(last, following):
                continue
            if any((e.start_sec < first.start_sec < e.end_sec - 1e-6) or
                   (e.start_sec + 1e-6 < last.end_sec < e.end_sec - 1e-6) for e in dialogue):
                continue
            included = [e for e in entries if e.start_sec < last.end_sec and e.end_sec > first.start_sec]
            if any(e.scene_id != first.scene_id for e in included):
                continue
            spoken = [e for e in included if e.kind == "dialogue"]
            if spoken:
                next_spoken = next((e for e in dialogue if e.start_sec >= spoken[-1].end_sec), None)
                if not starts_clean(spoken[0]) or not ends_clean(spoken[-1], next_spoken):
                    continue
            speakers = {e.speaker for e in included if e.kind == "dialogue"}
            if len(speakers) < 2 and not ACTION_INTENSE.search(" ".join(e.content for e in included if e.kind != "camera")):
                continue
            result.append(Candidate(f"{first.episode_id.replace(' ', '-')}-{first.entry_id}-{last.entry_id}",
                                    first.episode_id, first.start_sec, last.end_sec, included))
    # Multiple concurrent anchors can describe the same time interval.
    return list({(c.start_sec, c.end_sec): c for c in result}.values())


def score(candidate):
    first, last = candidate.edge(), candidate.edge(False)
    opening = " ".join(e.content for e in first)
    # Score the final completed beat; a preceding question may already have an answer.
    completed = [e for e in last if e.end_sec <= candidate.end_sec + 1e-6]
    final_beat = max(completed or last, key=lambda e: (e.end_sec, e.kind == "dialogue"))
    ending = final_beat.content
    words = 0.0
    for e in first:
        if e.kind == "dialogue":
            overlap = max(0, min(e.end_sec, candidate.start_sec + 3) - max(e.start_sec, candidate.start_sec))
            words += len(e.content.split()) * overlap / e.duration
    hook = min(10, 1 + min(4, len(CONFLICT.findall(opening)) * 1.5) +
               (2 if re.search(r"[!?]", opening) else 0) + min(1.5, words / 6) +
               (2 if ACTION_INTENSE.search(opening) else 0))
    cliff = min(10, 1 + (3 if "?" in ending else 0) +
                (2 if re.search(r"\.\.\.|\u2026|--", ending) else 0) +
                min(4, len(SUSPENSE.findall(ending)) * 1.5) +
                (2 if ACTION_INTENSE.search(ending) else 0) + (0.5 if "!" in ending else 0))
    start_text = clean(first[0].content) if first else ""
    ambiguous = bool(re.match(r"^(?:and\b|but\b|so\b|he\b|she\b|they\b|it\b|that\b|this\b)", start_text, re.I))
    coherence = 7 - (3 if ambiguous else 0) + (1 if any(e.kind == "action" for e in first) else 0)
    coherence += 1 if len(candidate.speakers) >= 2 else 0
    candidate.scores = {"hook": round(hook, 3), "cliffhanger": round(cliff, 3),
                        "coherence": coherence, "raw": round(.4*hook+.4*cliff+.2*coherence, 3)}
    return candidate


def shortlist(candidates, fraction=.15, cap=12, max_overlap=.4):
    """Top-scoring windows, skipping near-duplicates so Gemini sees different moments."""
    count = min(cap, max(1, math.ceil(len(candidates) * fraction)))
    ranked = sorted(candidates, key=lambda c: (-c.scores["raw"], c.start_sec, c.end_sec))
    chosen = []
    for c in ranked:
        if all(temporal_iou(c, o) <= max_overlap for o in chosen):
            chosen.append(c)
            if len(chosen) == count:
                break
    return chosen


def temporal_iou(a, b):
    if a.episode_id != b.episode_id:
        return 0.0
    overlap = max(0.0, min(a.end_sec, b.end_sec) - max(a.start_sec, b.start_sec))
    return overlap / (a.duration + b.duration - overlap)


def suppress(candidates, threshold=.4, limit=3):
    selected = []
    for candidate in sorted(candidates, key=lambda c: (-c.evaluation["viral_score"], -c.scores["raw"], c.start_sec, c.end_sec)):
        if candidate.evaluation.get("standalone", True) and all(temporal_iou(candidate, other) <= threshold for other in selected):
            selected.append(candidate)
            if len(selected) >= limit:
                break
    return selected


def fallback(candidates):
    """If every clip was rejected, keep the best one, clearly labelled for editor review."""
    if not candidates:
        return []
    best = max(candidates, key=lambda c: (c.evaluation["viral_score"], c.scores["raw"]))
    note = "[Review needed: Gemini judged this clip not standalone] "
    best.evaluation = dict(best.evaluation, justification=note + best.evaluation["justification"])
    return [best]