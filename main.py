"""Find promo clips with deterministic timing and Gemini narrative ranking."""
import argparse
import math
import os
from pathlib import Path
import shlex
import sys
import time
from parser import parse_script, timecode
from engine import generate, score, shortlist, suppress
from semantic import GeminiEvaluator
from report import render_report

ROOT = Path(__file__).resolve().parent


def load_env(path=ROOT / '.env'):
    """Read Gemini variables without executing shell code or overriding exports."""
    if not path.exists():
        return
    for line_no, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:].lstrip()
        key, separator, raw = line.partition('=')
        key = key.strip()
        if key not in {'GEMINI_API_KEY', 'GEMINI_MODEL'}:
            continue
        if not separator:
            raise ValueError(f'.env line {line_no}: expected KEY=value')
        try:
            parts = shlex.split(raw, comments=True)
        except ValueError:
            raise ValueError(f'.env line {line_no}: invalid quoting') from None
        if len(parts) > 1:
            raise ValueError(f'.env line {line_no}: quote values containing spaces')
        os.environ.setdefault(key, parts[0] if parts else '')


def build_parser():
    parser = argparse.ArgumentParser(description='Rank 20–60 second screenplay promos using Gemini.')
    parser.add_argument('--input', type=Path, default=ROOT.parent / 'I Married a Broken Soldier. He was a Duke', help='TXT file or folder of episode TXT files')
    parser.add_argument('--output', type=Path, default=ROOT / 'report', help='Destination directory; writes only report.html')
    parser.add_argument('--model', default=os.environ.get('GEMINI_MODEL') or GeminiEvaluator.default_model, help='Gemini model ID; defaults to GEMINI_MODEL or gemini-3.5-flash-lite')
    parser.add_argument('--limit-episodes', type=int, help='Process only the first N files in filename order')
    parser.add_argument('--max-candidates', type=int, default=4, help='Maximum candidates sent to Gemini per episode (default: 4)')
    parser.add_argument('--shortlist-fraction', type=float, default=.15, help='Fraction of valid windows shortlisted before the cap (default: 0.15)')
    parser.add_argument('--promos-per-episode', type=int, default=3, help='Maximum selected promos per episode (default: 3)')
    parser.add_argument('--min-duration', type=float, default=20, help='Minimum clip seconds, at least 20 (default: 20)')
    parser.add_argument('--max-duration', type=float, default=60, help='Maximum clip seconds, at most 60 (default: 60)')
    parser.add_argument('--iou-threshold', type=float, default=.4, help='Suppress overlap above this IoU; 0 prohibits all overlap (default: 0.4)')
    parser.add_argument('--request-interval', type=float, default=6, help='Minimum seconds between API request starts, 0–60 (default: 6)')
    return parser


def serialize(candidate, source, rank):
    result = candidate.evaluation
    return {
        'rank': rank, 'candidate_id': candidate.candidate_id,
        'episode_id': candidate.episode_id, 'duration_sec': candidate.duration,
        'viral_score': result['viral_score'], 'heuristic_scores': candidate.scores,
        'segments': [{'episode_id': candidate.episode_id, 'source_file': source,
                      'start_timestamp': timecode(candidate.start_sec),
                      'end_timestamp': timecode(candidate.end_sec)}],
        'hook': {'quote': result['hook_quote']},
        'cliffhanger': {'quote': result['cliffhanger_quote']},
        'justification': result['justification'],
        'transcript': [dict(e.to_dict(), start_timestamp=timecode(e.start_sec),
                            end_timestamp=timecode(e.end_sec))
                       for e in candidate.entries if e.kind in ('dialogue', 'action')],
    }


def run(args):
    if not 20 <= args.min_duration <= args.max_duration <= 60:
        raise ValueError('Durations must satisfy 20 <= min <= max <= 60')
    if not 0 < args.shortlist_fraction <= 1 or not 0 <= args.iou_threshold <= 1:
        raise ValueError('Shortlist fraction must be in (0,1]; IoU must be in [0,1]')
    if min(args.max_candidates, args.promos_per_episode) < 1:
        raise ValueError('Candidate and promo limits must be positive')
    if args.limit_episodes is not None and args.limit_episodes < 1:
        raise ValueError('--limit-episodes must be positive')
    if not math.isfinite(args.request_interval) or not 0 <= args.request_interval <= 60:
        raise ValueError('--request-interval must be between 0 and 60')
    files = [args.input] if args.input.is_file() else sorted(args.input.glob('*.txt'))
    if not files:
        raise ValueError(f'No screenplay TXT files found: {args.input}')
    if args.limit_episodes:
        files = files[:args.limit_episodes]
    evaluator = GeminiEvaluator(args.model, request_interval=args.request_interval)
    selected, seen = [], set()
    start = time.perf_counter()
    for path in files:
        entries, warnings = parse_script(path)
        episode = entries[0].episode_id
        if episode in seen:
            raise ValueError(f'Duplicate episode ID: {episode}')
        seen.add(episode)
        for warning in warnings:
            print(f'{path.name}:{warning["line"]}: {warning["reason"]}', file=sys.stderr)
        candidates = [score(c) for c in generate(entries, args.min_duration, args.max_duration)]
        chosen = shortlist(candidates, args.shortlist_fraction, args.max_candidates)
        for index, candidate in enumerate(chosen, 1):
            print(f'{episode}: evaluating {index}/{len(chosen)} with {evaluator.model}...', flush=True)
            try:
                candidate.evaluation = evaluator.evaluate(candidate)
            except (ValueError, KeyError, TypeError) as exc:
                print(f'{episode}: skipped {candidate.candidate_id} after retries: {exc}', file=sys.stderr, flush=True)
            except RuntimeError as exc:
                raise RuntimeError(f'{candidate.candidate_id}: {exc}') from None
        chosen = [c for c in chosen if c.evaluation]
        picks = suppress(chosen, args.iou_threshold, args.promos_per_episode)
        selected.extend((c, path.name) for c in picks)
        print(f'{episode}: {len(candidates)} valid windows, {len(picks)} promos selected', flush=True)
    selected.sort(key=lambda item: (-item[0].evaluation['viral_score'], -item[0].scores['raw'], item[0].episode_id, item[0].start_sec))
    promos = [serialize(c, source, rank) for rank, (c, source) in enumerate(selected, 1)]
    args.output.mkdir(parents=True, exist_ok=True)
    render_report(args.output, promos)
    print(f'Saved {len(promos)} ranked promos: {(args.output / "report.html").resolve()}')
    print(f'{evaluator.calls} API attempts; {time.perf_counter()-start:.1f}s; token usage: {evaluator.usage}')
    return promos


def main(argv=None):
    try:
        load_env()
        args = build_parser().parse_args(argv)
        run(args)
    except (ValueError, RuntimeError, OSError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())