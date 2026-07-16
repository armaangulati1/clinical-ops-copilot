# RUNBOOK: live phone-call test of the prior-auth voice agent

Goal: call a real phone number, say a case number, and hear the agent's decision
read back. This captures the evidence needed to demonstrate the live phone-call
demo end to end.

Two ways to expose the webhook to Twilio:

- **Option A (recommended for the trial): local `uvicorn` + a tunnel.** Fastest,
  nothing to deploy, and you see the agent logs live in your terminal.
- **Option B: deploy to Fly.io.** Use this if you want an always-on URL.

Do the prerequisites once, then pick Option A or B, then do the Twilio console
steps, then make the call.

Formatting note: each step says WHICH app to use. Run one command per code block.
The expected output is stated after each command so you know it worked.

---

## Prerequisites (do these once)

### 1. In the Terminal app, go to the repo

```bash
cd /Users/agulati/Documents/clinical-ops-copilot
```

Expected: the prompt now shows you are in `clinical-ops-copilot`.

### 2. In the Terminal app, switch to the branch

```bash
git checkout twilio-voice
```

Expected output: `Switched to branch 'twilio-voice'`.

### 3. In the Terminal app, install the telephony extra

```bash
uv sync --extra telephony
```

Expected: it finishes with a line listing installed packages including `twilio`.
No error.

### 4. In the Terminal app, confirm your Twilio secrets are in `.env`

```bash
grep -c TWILIO_AUTH_TOKEN .env
```

Expected output: `1`. If it prints `0`, open `.env` and add these three lines
(values from your Twilio Console), then re-run:

```
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_twilio_auth_token
VOICE_PUBLIC_BASE_URL=set_this_in_the_option_below
```

`.env` is gitignored, so these never get committed.

### 5. In the Terminal app, confirm the Anthropic key is in `.env`

```bash
grep -c ANTHROPIC_API_KEY .env
```

Expected output: `1`. The webhook runs the real agent (the same planner used by
`python -m agent`), so it needs this key. If it prints `0`, add the line
`ANTHROPIC_API_KEY=your_anthropic_key` to `.env` and re-run this step until it
prints `1`.

---

## Option A: local uvicorn + a tunnel (recommended)

You will run the webhook on your Mac and expose it with a tunnel. Use two
Terminal windows.

### A1. In Terminal window 1, install a tunnel tool (once)

```bash
brew install cloudflared
```

Expected: Homebrew finishes with `cloudflared` installed (or "already installed").

### A2. In Terminal window 1, start the tunnel

```bash
cloudflared tunnel --url http://localhost:8080
```

Expected: after a few seconds it prints a line like
`https://random-words-1234.trycloudflare.com`. Copy that https URL. Leave this
window running.

### A3. In Terminal window 2, go to the repo and set the public URL

```bash
cd /Users/agulati/Documents/clinical-ops-copilot
```

Expected: prompt shows `clinical-ops-copilot`.

### A4. In Terminal window 2, put the tunnel URL into `.env`

Open `.env` and set this line to the URL from step A2 (no trailing slash):

```
VOICE_PUBLIC_BASE_URL=https://random-words-1234.trycloudflare.com
```

Expected: saved. This must match exactly what Twilio will call, or signature
validation will reject the request.

### A5. In Terminal window 2, load the environment

```bash
set -a && source .env && set +a
```

Expected: no output, prompt returns. The variables are now loaded.

### A6. In Terminal window 2, start the webhook

```bash
uv run uvicorn voice_telephony.asgi:app --host 0.0.0.0 --port 8080
```

Expected: `Uvicorn running on http://0.0.0.0:8080`. If it instead prints
`Missing required telephony environment variable(s): ...`, go back to step A4/A5.
Leave this window running.

Now skip to "Twilio console: point the number at your webhook". Your webhook URL
is `VOICE_PUBLIC_BASE_URL` + `/voice/incoming`.

---

## Option B: deploy to Fly.io (always-on URL)

This runs the webhook as its own small Fly app in the same repo image.

### B1. In the Terminal app, launch a new Fly app (once)

```bash
fly launch --no-deploy --name copilot-voice --copy-config --dockerfile Dockerfile
```

Expected: it creates the app `copilot-voice` and writes a fly config. Answer "no"
to a database.

### B2. In the Terminal app, set the run command to the webhook

Edit the generated `fly.<name>.toml` so the process runs the webhook:

```
[processes]
  app = "uvicorn voice_telephony.asgi:app --host 0.0.0.0 --port 8000"
```

Expected: saved. (Keep `internal_port = 8000`.)

### B3. In the Terminal app, set the secrets

```bash
fly secrets set --app copilot-voice TWILIO_ACCOUNT_SID=ACxxxx TWILIO_AUTH_TOKEN=your_token ANTHROPIC_API_KEY=your_anthropic_key VOICE_PUBLIC_BASE_URL=https://copilot-voice.fly.dev
```

Expected: `Secrets are staged for the first deployment`.

### B4. In the Terminal app, deploy

```bash
fly deploy --app copilot-voice --ha=false
```

Expected: ends with `1 desired, 1 placed, 1 healthy`. Your webhook URL is
`https://copilot-voice.fly.dev/voice/incoming`.

---

## Twilio console: point the number at your webhook

Do this in the Chrome browser at https://console.twilio.com.

### T1. Open your trial number

Go to Phone Numbers -> Manage -> Active numbers, and click your trial number.

### T2. Set the voice webhook

In the "Voice Configuration" section, under "A call comes in", choose **Webhook**,
paste your incoming URL, and set the method to **HTTP POST**:

- Option A: `https://random-words-1234.trycloudflare.com/voice/incoming`
- Option B: `https://copilot-voice.fly.dev/voice/incoming`

### T3. Save

Click **Save configuration** at the bottom. Expected: a green "saved" confirmation.

---

## Make the call

### C1. On your phone, call the Twilio number

Dial your trial number. Expected: you hear the trial preamble ("You have a trial
account..."), then the prompt: "say the case number and your question."

### C2. Say a case number

Say clearly: "case three, what is the prior authorization status".

Expected: you first hear a short hold message ("Looking up case three now. One
moment."), possibly followed by one "Still working, one moment." while the agent
runs, and then something like "For case-003, the agent's decision is submit.
Recommendation: submit the prior authorization. Confidence 95 percent." (The exact
decision/number comes from the agent, not a script.)

The hold messages exist because Twilio's webhook times out at 15 seconds and a
full agent decision takes roughly that long, so the webhook holds the call and
polls until the agent finishes instead of answering the first request
synchronously.

If you used Option A, Terminal window 2 shows the agent running: MCP
`CallToolRequest` log lines and the decision, proving the real agent ran.

---

## Evidence to capture

1. **Twilio call log.** In the Console: Monitor -> Logs -> Calls, open the call
   you just made. Screenshot the call detail (status "completed", your number,
   timestamp). Twilio also shows the request/response to `/voice/incoming` and
   `/voice/decision` there.

2. **Short screen recording.** Record ~30 seconds: your phone on speaker placed
   by the screen, Terminal window 2 (Option A) showing the agent's MCP log lines
   and the decision scrolling, and the audible spoken reply. Narrate: "I call a
   real number, say a case, and the unchanged agent decides and reads it back."

3. **Optional: one signed request in the logs.** In the Twilio call log, expand
   the `/voice/decision` request and confirm the `X-Twilio-Signature` header is
   present. Our webhook validated it before running the agent.

Once you have heard a live decision and captured the call log, the live
phone-call demo is complete and its evidence is on record.
