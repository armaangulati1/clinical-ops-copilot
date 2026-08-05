"""Before/after latency benchmark for the spoken-decision leg.

Measures the same sentence through both TTS backends and prints a markdown
table with the sample size, median, and full range. Also writes one audio
sample per backend so the two can be played back to back.

    uv run python scripts/tts_latency_bench.py --runs 7

Two metrics are reported, because one of them alone is misleading:

1. **Complete audio**: all of the audio in hand.
   * ``say``: local render of the sentence to an AIFF file (``say -o``). No
     network, no account, no cost.
   * ``elevenlabs``: the full HTTP round trip to
     ``POST /v1/text-to-speech/{voice_id}`` until the whole MP3 body is in
     memory. Includes TLS setup, queueing, synthesis, and transfer.
2. **Time to first audio**: when playback could actually begin. This is the
   number that matters on a phone call, and it is the fairer comparison, since
   a render-to-file tool is penalized by metric 1 for work a listener never
   waits on.
   * ``say``: polling the output file until it is non-empty.
   * ``elevenlabs``: first non-empty chunk from the ``/stream`` endpoint.

Caveats that must travel with the numbers:

* Both are **synthesis** latency, not playback and not end-to-end call latency.
  The agent's own decision takes far longer than either (measured at roughly
  14.9 s per decision on the telephony path), so the TTS leg is a small share of
  what a caller waits through. Changing it does not make the call feel fast.
* The ``say`` time-to-first-audio figure is a **proxy**: it is when bytes first
  appear in the output file, not when the speaker makes sound, and it carries up
  to one 2 ms poll interval of quantization error.
* Every run is included in the statistics, including the first (cold) one. The
  cold run is also reported on its own line so the TLS/process-spawn cost is
  visible rather than quietly dropped.
* One machine, one residential network, one free-tier account, one sentence,
  single-request (no concurrency). These are that configuration's numbers, not a
  vendor benchmark, and network latency is not separable from synthesis time.
* ``say`` renders to AIFF at the system default; ElevenLabs returns
  ``mp3_44100_128``. Different codecs and bitrates, so file sizes are not
  comparable and are reported only as evidence that audio actually arrived.
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # allow `python scripts/tts_latency_bench.py`
    sys.path.insert(0, str(REPO_ROOT))

from voice.tts import (  # noqa: E402
    API_KEY_ENV,
    ELEVENLABS_BACKEND,
    SAY_BACKEND,
    TTSBackend,
    TTSError,
    build_backend,
)

DEFAULT_RUNS = 7
DEFAULT_OUT_DIR = REPO_ROOT / "voice" / "samples"

# The real sentence the agent speaks, for a synthetic case. Benchmarking a
# sentence the system never says would measure the wrong thing.
DEFAULT_TEXT = (
    "For case-003, the agent's decision is request-more-info. "
    "Recommendation: request more information before submitting. "
    "Confidence 70 percent. Missing fields: das28 score."
)


@dataclass
class Samples:
    """One metric's measurements for one backend, or why there are none."""

    values: list[float]
    skipped_reason: str | None = None

    @property
    def n(self) -> int:
        return len(self.values)

    @property
    def median(self) -> float:
        return statistics.median(self.values)

    @property
    def cold(self) -> float:
        return self.values[0]

    def fmt_median(self) -> str:
        return f"{self.median * 1000:.0f} ms"

    def fmt_range(self) -> str:
        lo = min(self.values) * 1000
        hi = max(self.values) * 1000
        return f"{lo:.0f}-{hi:.0f} ms"


@dataclass
class BackendResult:
    """Both metrics for one backend, plus the bytes proving audio arrived."""

    name: str
    complete: Samples
    first_audio: Samples
    byte_counts: list[int]


def load_dotenv(path: Path) -> None:
    """Load ``.env`` into the process environment without echoing any value."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def _unavailable_reason(name: str) -> str:
    if name == ELEVENLABS_BACKEND:
        return f"{API_KEY_ENV} not set"
    return "macOS 'say' binary not on PATH"


def run_backend(
    name: str,
    text: str,
    runs: int,
    out_dir: Path,
    environ: Mapping[str, str],
) -> BackendResult:
    """Time ``runs`` calls of each metric, saving the first run's audio."""
    complete = Samples(values=[])
    first_audio = Samples(values=[])
    byte_counts: list[int] = []
    result = BackendResult(
        name=name,
        complete=complete,
        first_audio=first_audio,
        byte_counts=byte_counts,
    )

    backend: TTSBackend = build_backend(name, environ)
    if not backend.is_available():
        complete.skipped_reason = _unavailable_reason(name)
        first_audio.skipped_reason = _unavailable_reason(name)
        return result

    for index in range(runs):
        try:
            audio = backend.synthesize(text)
        except TTSError as exc:
            complete.skipped_reason = f"run {index + 1} failed: {exc}"
            break
        complete.values.append(audio.latency_seconds)
        byte_counts.append(len(audio.data))
        if index == 0:
            audio.write(out_dir / f"decision_{name}{audio.suffix}")
        print(
            f"  {name} complete-audio run {index + 1}/{runs}: "
            f"{audio.latency_seconds * 1000:.0f} ms"
        )

    for index in range(runs):
        try:
            elapsed = backend.time_to_first_audio(text)
        except TTSError as exc:
            first_audio.skipped_reason = f"run {index + 1} failed: {exc}"
            break
        first_audio.values.append(elapsed)
        print(f"  {name} first-audio run {index + 1}/{runs}: {elapsed * 1000:.0f} ms")

    return result


def _metric_rows(
    results: list[BackendResult],
    pick: str,
) -> list[str]:
    rows: list[str] = []
    for result in results:
        samples = result.complete if pick == "complete" else result.first_audio
        if samples.n == 0:
            reason = samples.skipped_reason or "no successful runs"
            rows.append(
                f"| `{result.name}` | 0 | not measured | not measured "
                f"| not measured | skipped: {reason} |"
            )
            continue
        first_bytes = f"{result.byte_counts[0]:,}" if result.byte_counts else "n/a"
        rows.append(
            f"| `{result.name}` | {samples.n} | {samples.fmt_median()} "
            f"| {samples.fmt_range()} | {samples.cold * 1000:.0f} ms "
            f"| {first_bytes} |"
        )
    return rows


def _delta_line(results: list[BackendResult], pick: str) -> list[str]:
    def samples_for(name: str) -> Samples | None:
        for result in results:
            if result.name != name:
                continue
            samples = result.complete if pick == "complete" else result.first_audio
            return samples if samples.n else None
        return None

    say_s = samples_for(SAY_BACKEND)
    eleven_s = samples_for(ELEVENLABS_BACKEND)
    if say_s is None or eleven_s is None or say_s.median <= 0:
        return []
    delta_ms = (eleven_s.median - say_s.median) * 1000
    ratio = eleven_s.median / say_s.median
    return [
        "",
        f"Delta on medians (say n = {say_s.n}, elevenlabs n = {eleven_s.n}): "
        f"ElevenLabs is {delta_ms:+.0f} ms ({ratio:.2f}x) versus `say`.",
    ]


_HEADER = (
    "| Backend | n | Median | Range (min-max) | Cold (1st) run | Audio bytes (1st) |"
)
_DIVIDER = "|---|---|---|---|---|---|"


def render_table(results: list[BackendResult], text: str, runs: int) -> str:
    """Markdown tables. Every number carries its sample size."""
    lines = [
        f"Sentence: {len(text)} characters, {len(text.split())} words.",
        f"Requested runs per backend per metric: n = {runs} "
        "(all runs included, cold run first).",
        "",
        "**Metric 1: complete audio in hand**",
        "",
        _HEADER,
        _DIVIDER,
    ]
    lines += _metric_rows(results, "complete")
    lines += _delta_line(results, "complete")
    lines += [
        "",
        "**Metric 2: time to first audio (when playback could begin)**",
        "",
        _HEADER,
        _DIVIDER,
    ]
    lines += _metric_rows(results, "first_audio")
    lines += _delta_line(results, "first_audio")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--backends",
        default=f"{SAY_BACKEND},{ELEVENLABS_BACKEND}",
        help="comma-separated backend names to benchmark",
    )
    args = parser.parse_args(argv)

    if args.runs < 1:
        print("--runs must be at least 1", file=sys.stderr)
        return 2

    load_dotenv(REPO_ROOT / ".env")
    args.out_dir.mkdir(parents=True, exist_ok=True)

    names = [n.strip() for n in args.backends.split(",") if n.strip()]
    results = [
        run_backend(name, args.text, args.runs, args.out_dir, os.environ)
        for name in names
    ]

    table = render_table(results, args.text, args.runs)
    print()
    print(table)
    print()
    print(f"Audio samples written to {args.out_dir} (gitignored; never committed).")
    for result in results:
        if result.byte_counts:
            print(f"  play: afplay {args.out_dir}/decision_{result.name}.*")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
