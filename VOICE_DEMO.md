# Voice Prototype — Demo & Handoff

STATUS (honest): The end-to-end pipeline RUNS and is verified for the
`--text` path (transcript in -> real agent -> spoken reply out). The **Whisper
speech-to-text leg is UNVERIFIED**: there was no `OPENAI_API_KEY` in this
environment, so live audio transcription could not be exercised. When no key is
present the tool degrades cleanly with a clear message and exits — it does not
crash. See "Two ways to run" below and pick the one that matches your keys.

This is an isolated prototype. It adds a `voice/` package + `voice_demo.py` and
one test file. It does NOT modify the agent, MCP wiring, or any existing code
(verified: `git diff main -- agent/ .github/ servers/ ui/ evals/ schemas/` is
empty). Existing tests: 137 before, 137 still passing after (+11 new voice
tests = 148 total, `pytest -m "not network"`).

Scope: file-in / spoken-out. No telephony, no Twilio, no streaming.

---

## (a) The single run command

Guaranteed-to-work path (uses only `ANTHROPIC_API_KEY`, which the repo already
has in `.env`; skips Whisper, exercises the REAL agent + spoken reply):

```bash
cd /Users/agulati/Documents/clinical-ops-copilot
set -a && source .env && set +a
uv run python voice_demo.py --text "What is the prior authorization status for case one?"
```

Full voice-in path (adds live Whisper STT; needs `OPENAI_API_KEY` — UNVERIFIED
here because no such key was available):

```bash
cd /Users/agulati/Documents/clinical-ops-copilot
set -a && source .env && set +a
export OPENAI_API_KEY="sk-..."          # your OpenAI key; Whisper whisper-1
uv run python voice_demo.py --audio voice/samples/prior_auth_question.wav
```

Both speak the agent's decision aloud via the macOS `say` command. Add
`--no-speak` to print only.

---

## (b) What Armaan should see / hear, step by step

Running the command above prints, in order:

1. `[voice] Using --text override ...` (or `Transcribing ... via Whisper`).
2. `[voice] Transcript: What is the prior authorization status for case one?`
   — the words the agent will act on.
3. `[voice] Routed to: case-001` — the voice layer mapped the spoken question
   to an existing case ID. (Routing is deterministic; the AGENT makes the
   decision, not the router.)
4. `[voice] Running the prior-auth agent (real planner + MCP tools)...` —
   followed by MCP `CallToolRequest` log lines: this is the actual, unchanged
   agent reading the chart and payer policy through the MCP tools.
5. An `===== AGENT ANSWER =====` block: case, drug, condition, the decision
   (`submit` / `request-more-info` / `deny-risk`), confidence, and the agent's
   full rationale.
6. `[voice] Speaking: For case-001, the agent's decision is submit ...` — and
   you HEAR that sentence spoken aloud through your speakers.

Verified example output (case-001): decision `submit`, confidence `0.98`, with
a five-point rationale confirming diagnosis, disease duration, failed DMARDs,
DAS28, and methotrexate trial all meet payer criteria.

To route to a different case, just say/type its number:
`--text "check prior auth for case three"` -> routes to `case-003`. Or force
one with `--case case-039`.

---

## (c) 3-step verify checklist

1. **Tests green.** From the repo root on the `voice-prototype` branch:
   `uv run pytest -m "not network" -q` -> `148 passed, 15 deselected`.
   (137 pre-existing + 11 new voice tests; nothing existing changed.)
2. **Agent actually ran.** In the run output, confirm you see MCP
   `CallToolRequest` lines AND an `AGENT ANSWER` block with a non-empty
   rationale. That proves the real planner + MCP tools ran, not a canned reply.
3. **You heard it.** Confirm the final `[voice] Speaking:` line played through
   your speakers. If silent, re-run with your volume up, or `--no-speak` to
   confirm the text is at least printed. (macOS `say` only — silent no-op on
   non-macOS.)

---

## (d) 30-second Loom segment script

Goal: show voice-in -> agent reasoning -> spoken reply in ~30s.

On screen: split view — terminal on the left, this heading visible.

| Time | You SAY (voice-over) | What's ON SCREEN |
|------|----------------------|------------------|
| 0-5s | "This agent already triages prior-auth cases. I added a voice front-end that routes a spoken question into the *unchanged* agent." | Terminal at the repo root, `voice-prototype` branch shown (`git branch --show-current`). |
| 5-12s | "I ask it a question out loud." | Run the command. Highlight the printed `Transcript:` line — the spoken question in text. |
| 12-20s | "The voice layer just routes to a case. The real agent does the reasoning — reading the chart and payer policy through MCP tools." | Point at `Routed to: case-001`, then the `CallToolRequest` MCP log lines scrolling. |
| 20-27s | "It reads back the decision, with its confidence and why." | The `AGENT ANSWER` block fills in: `submit`, `confidence 0.98`, rationale. |
| 27-30s | (stop talking; let the spoken reply play) | Audio: "For case-001, the agent's decision is submit. Confidence 98 percent." |

Tip: if demoing the Whisper leg live, pre-record the question with the exact
`say -o` command in section (f) so it plays even if your mic misbehaves.

---

## (e) Files added (isolated; nothing existing edited)

- `voice_demo.py` — entry script: transcribe -> route -> run existing agent -> speak.
- `voice/__init__.py`, `voice/transcribe.py` (Whisper `whisper-1`),
  `voice/route.py` (transcript -> case id), `voice/speak.py` (macOS `say`).
- `voice/samples/prior_auth_question.wav` — pre-recorded question (see (f)).
- `tests/test_voice_prototype.py` — 11 unit tests for routing + phrasing.

## (f) Regenerate the sample audio (so the demo works even if the mic fails)

The committed `voice/samples/prior_auth_question.wav` was produced with:

```bash
say -o voice/samples/prior_auth_question.wav --data-format=LEI16@22050 \
  "What is the prior authorization status for case one?"
```

Re-run that any time to regenerate it, or point `--audio` at your own recording.

## (g) Honesty caveats (for the fact-lock)

- **Verified:** transcript -> existing agent -> spoken decision, end to end,
  on real cases (case-001 `submit` 0.98; case-003 `submit` 0.95). Existing 137
  tests unchanged and green; 11 new voice tests pass. Lint + `mypy --strict`
  clean on the new module. No edits to agent/CI/servers/ui/evals/schemas.
- **NOT verified:** the live Whisper (`whisper-1`) transcription leg — no
  `OPENAI_API_KEY` was available. The code path exists and degrades cleanly,
  but it has not been run against real audio. Do not claim "voice-in works"
  externally until you run the `--audio` path once with a real OpenAI key.
- **Prototype boundaries:** file-in only (no live mic — `portaudio`/mic access
  was intentionally not added per the dependency rule); macOS `say` for TTS;
  the voice layer routes by case number, it does not free-form question-answer.
  The agent's decision is 100% the existing agent's, not the voice layer's.
