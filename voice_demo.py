"""Voice-interface prototype: speak a question, hear the agent's decision.

Pipeline (all glue; the agent itself is untouched):

    audio file  --Whisper-->  transcript  --route-->  case-0NN
                                                          |
                                                 EXISTING agent runs
                                             (StdioMcpHost + AnthropicPlanner
                                              + agent.runner.run_case)
                                                          |
                                   decision  --say-->  spoken reply

Run (file-in, the reliable path):

    OPENAI_API_KEY=... uv run python voice_demo.py \
        --audio voice/samples/prior_auth_question.wav

Offline / no-Whisper-key path (still exercises the real agent + spoken reply):

    uv run python voice_demo.py --text "What is the prior auth status for case one?"

This module imports the production agent; it never modifies it. It requires
ANTHROPIC_API_KEY (same as `python -m agent`) because the real planner runs.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import anyio

from agent.config import load_config
from agent.llm import AnthropicPlanner
from agent.mcp_host import StdioMcpHost
from agent.run_log import RunLogWriter
from agent.runner import run_case
from schemas.loader import load_case_file
from voice.route import DEFAULT_CASE_ID, case_id_from_transcript
from voice.speak import say_available, speak, spoken_answer
from voice.transcribe import TranscriptionUnavailable, transcribe_file


async def _run_agent_for_case(case_id: str, project_root: Path) -> tuple[str, str]:
    """Run the EXISTING agent on one case exactly as `python -m agent` does.

    Returns (spoken_text, printable_summary).
    """
    case_path = project_root / "data/cases" / f"{case_id}.json"
    case = load_case_file(case_path)  # validates the id exists

    config = load_config(project_root)
    writer = RunLogWriter(config.runs_dir)
    host = await StdioMcpHost.connect(config)
    planner = AnthropicPlanner(config.anthropic_model)
    try:
        result = await run_case(case, host, planner, config=config, writer=writer)
    finally:
        await host.close()

    decision = result.decision
    spoken = spoken_answer(case_id, decision)
    summary = (
        f"case: {case_id}\n"
        f"drug: {case.drug}\n"
        f"condition: {case.condition}\n"
        f"decision: {decision.action.value} "
        f"(confidence={decision.confidence:.2f})\n"
        f"rationale: {decision.rationale}"
    )
    if decision.missing_fields:
        summary += f"\nmissing_fields: {', '.join(decision.missing_fields)}"
    return spoken, summary


def _get_transcript(args: argparse.Namespace) -> str:
    if args.text:
        print(f"[voice] Using --text override (no transcription): {args.text!r}")
        return str(args.text)
    audio_path = Path(args.audio).expanduser().resolve()
    print(f"[voice] Transcribing {audio_path} via Whisper (whisper-1)...")
    return transcribe_file(audio_path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Voice prototype for the prior-auth agent (file-in / spoken-out)."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--audio",
        type=str,
        help="Path to an audio file (.wav/.m4a/...) to transcribe via Whisper.",
    )
    source.add_argument(
        "--text",
        type=str,
        help="Skip transcription; feed this text straight to routing + agent.",
    )
    parser.add_argument(
        "--case",
        type=str,
        default="",
        help="Force a specific case id (e.g. case-003), bypassing transcript routing.",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Repository root (default: this file's directory).",
    )
    parser.add_argument(
        "--voice",
        type=str,
        default=None,
        help="Optional macOS 'say' voice name (e.g. Samantha).",
    )
    parser.add_argument(
        "--no-speak",
        action="store_true",
        help="Print the answer but do not speak it aloud.",
    )
    args = parser.parse_args()

    # 1. Speech-to-text (or text override).
    try:
        transcript = _get_transcript(args)
    except TranscriptionUnavailable as exc:
        print(f"[voice] Transcription unavailable: {exc}")
        return 2
    print(f"[voice] Transcript: {transcript}")

    # 2. Route transcript -> case id (deterministic; the agent decides, not us).
    if args.case:
        case_id = args.case.strip()
        print(f"[voice] Case forced via --case: {case_id}")
    else:
        case_id = case_id_from_transcript(transcript, default_case_id=DEFAULT_CASE_ID)
        print(f"[voice] Routed to: {case_id}")

    # 3. Run the EXISTING agent on that case.
    print("[voice] Running the prior-auth agent (real planner + MCP tools)...")
    try:
        spoken, summary = anyio.run(_run_agent_for_case, case_id, args.project_root)
    except FileNotFoundError:
        print(f"[voice] No such case file for {case_id!r}. Try --case case-001.")
        return 2

    # 4. Print + speak the agent's answer.
    print("\n===== AGENT ANSWER =====")
    print(summary)
    print("========================\n")

    if args.no_speak:
        print("[voice] --no-speak set; not speaking.")
    elif not say_available():
        print("[voice] macOS 'say' unavailable; printed answer only.")
    else:
        print(f"[voice] Speaking: {spoken}")
        speak(spoken, voice=args.voice)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
