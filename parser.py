"""Parse concurrent screenplay tracks without adding their durations together."""
from dataclasses import dataclass, asdict
from pathlib import Path
import math
import re

STAMP = r"\d{1,3}:\d{2}(?::\d{2})?(?:\.\d+)?"
HEADER = re.compile(r"^\*\*(.+?):?\*\*:?\s*$")
TIMING = re.compile(rf"Start:\s*\(?({STAMP})\)?(?:\s*\|?\s*End:\s*\(?({STAMP})\)?)?", re.I)
VISUAL = {"CAMERA", "ACTION", "SOUND FX", "SFX", "MUSIC", "SCENE", "NARRATOR"}


def seconds(value: str) -> float:
    parts = value.strip().strip("()").split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"Invalid timestamp: {value}")
    numbers = [float(x) for x in parts]
    if any(not math.isfinite(x) or x < 0 for x in numbers):
        raise ValueError(f"Invalid timestamp: {value}")
    if numbers[-1] >= 60 or (len(parts) == 3 and numbers[-2] >= 60):
        raise ValueError(f"Invalid timestamp: {value}")
    return round(sum(x * 60 ** i for i, x in enumerate(reversed(numbers))), 6)


def timecode(value: float) -> str:
    ms = round(value * 1000)
    mins, ms = divmod(ms, 60000)
    secs, ms = divmod(ms, 1000)
    return f"{mins:02d}:{secs:02d}.{ms:03d}"


@dataclass
class Entry:
    entry_id: int
    episode_id: str
    scene_id: str
    speaker: str
    kind: str
    start_sec: float
    end_sec: float
    content: str
    source_line: int
    timing_inferred: bool = False

    @property
    def duration(self):
        return round(self.end_sec - self.start_sec, 6)

    def to_dict(self):
        return dict(asdict(self), duration=self.duration)


def parse_script(path: Path) -> tuple[list[Entry], list[dict]]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    episode = re.search(r"EPISODE NUMBER:\s*(.+)", "\n".join(lines))
    episode_id = episode.group(1).strip() if episode else path.stem
    if len(re.findall(r"^EPISODE NUMBER:", "\n".join(lines), re.M)) > 1:
        raise ValueError(f"{path.name}: use one episode per TXT file (multiple episode markers found)")
    warnings, records = [], []
    scene, tag, start, end, body, source = "1", None, None, None, [], 0

    def flush():
        nonlocal tag, start, end, body
        if tag:
            content = " ".join(s.strip() for s in body if s.strip())
            if start is None or not content:
                warnings.append({"line": source, "reason": "missing_start_or_payload", "tag": tag})
            else:
                speaker = re.sub(r"\s*\(.*", "", tag).strip().upper()
                kind = speaker.lower() if speaker in VISUAL else "dialogue"
                records.append([scene, speaker, kind, start, end, content, source])
        tag, start, end, body = None, None, None, []

    for line_no, line in enumerate(lines, 1):
        stripped = line.strip()
        head = HEADER.match(stripped)
        boundary = re.match(r"^(?:SCENE\s+(\d+)|(?:INT\.|EXT\.).*|--- SCRIPT END ---)", stripped)
        if head:
            flush()
            tag, source = head.group(1).rstrip(":"), line_no
        elif boundary:
            flush()
            if boundary.group(1):
                scene = boundary.group(1)
            elif stripped.startswith(("INT.", "EXT.")):
                scene = f"line-{line_no}"
        elif tag:
            timing = TIMING.fullmatch(stripped)
            if timing:
                start = seconds(timing.group(1))
                end = seconds(timing.group(2)) if timing.group(2) else None
            elif stripped.startswith(("Start:", "End:")):
                raise ValueError(f"{path.name}:{line_no}: malformed timing: {stripped}")
            else:
                body.append(stripped)
    flush()
    records.sort(key=lambda r: (r[3], r[6]))
    entries = []
    for i, (sc, speaker, kind, st, en, content, line_no) in enumerate(records):
        inferred = en is None
        if inferred:
            # Next start of the same track, never the concurrent camera track.
            next_start = next((r[3] for r in records[i+1:] if r[0] == sc and r[3] > st
                               and (r[2] == kind if kind != "dialogue" else r[2] == "dialogue")), None)
            estimate = st + max(0.5, len(content.split()) / 2.5)
            en = min(estimate, next_start) if next_start is not None else estimate
            warnings.append({"line": line_no, "reason": "inferred_end", "end_sec": en})
        if en <= st:
            raise ValueError(f"{path.name}:{line_no}: end must be after start")
        entries.append(Entry(i, episode_id, sc, speaker, kind, st, en, content, line_no, inferred))
    if not entries:
        raise ValueError(f"No timestamped entries in {path}")
    return entries, warnings
