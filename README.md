# Subsea Lens

**From pressure alerts to evidence-backed inspection decisions.**

Existing detectors flag unusual readings. This demo helps an integrity engineer
investigate whether they suggest a pipeline leak, faulty instruments or an
operating change, and understand where to inspect and why.
**Synthetic data only. Read-only decision support, not a safety system.**

## Documentation

| Read | Purpose |
|---|---|
| [Customer brief](docs/ONE_PAGE_BRIEF.pdf) ([source](docs/ONE_PAGE_BRIEF.md)) | One-page problem, same-data comparison and proposed pilot. |
| [Engineering report](docs/REPORT.md) | Architecture, data, answer checks, numerical sources and [30-minute code route](docs/REPORT.md#30-minute-technical-code-route). |
| [Demo reference](docs/DEMO_DETAILS.md) | Recording, evaluation, development and document-export commands. |
| [Qualification results](docs/RESULTS.md) | Published measurements, limitations and retained historical failures. |
| [Historical agent/fixed benchmark](docs/AGENT_EVALUATION.md) | Matched comparison under its original protocol. |
| [Interview deck](docs/INTERVIEW_DECK.html) ([PDF](docs/INTERVIEW_DECK.pdf)) | Presentation and appendix for the full interview. |

## Run the demo

**Supported setup:** Windows, PowerShell 7, Git, Python 3.11, [uv](https://docs.astral.sh/uv/),
Node.js 22+ and Docker Desktop running **Linux containers**. Fresh AI investigations
also require an authenticated [GitHub Copilot CLI](https://github.com/github/copilot-cli)
with access to `gpt-6.1-sol`. **You can explore the bundled Detection recording
and run sensor-only monitoring without model access.**

In PowerShell, with Docker Desktop running:

```powershell
git clone https://github.com/ntnguyen-so/subsea-integrity-copilot.git
Set-Location subsea-integrity-copilot
uv sync --locked
npm ci
.\tools\bootstrap.ps1                    # Once per Windows account; skip if configured
. .\tools\load-environment.ps1
$env:SUBSEA_TELEMETRY_ENABLED = '0'      # Optional tracing services are not needed
docker compose up -d --wait db
uv run subsea migrate
uv run subsea serve
```

Keep that terminal open. Visit **http://127.0.0.1:8086** and sign in as
**`operator`**. Get your generated password locally in a second PowerShell terminal:

```powershell
Set-Location subsea-integrity-copilot    # Use your clone's actual location
. .\tools\load-environment.ps1
$env:SUBSEA_OPERATOR_PASSWORD
```

Credentials stay outside Git in `%LOCALAPPDATA%\SubseaCopilot\secrets.json`.
Do not share them. Bootstrap refuses to overwrite an existing setup.
Wait for the site and timeline to load before starting a run.
The server builds the frontend automatically. First-time dependency/image downloads
need internet; fresh inference uses your own Copilot entitlement and quota.

Fresh inference uses the installed authenticated CLI through a persistent SDK
runtime, with isolated sessions and no automatic transport fallback.
See the [runtime reference](docs/DEMO_DETAILS.md#live-runtime-and-observability)
for tracing and explicit transport troubleshooting.

The main timeline supports **5x, 10x, 20x and 30x**, with new live sources defaulting
to 5x. Select S1-S7 and **Load recorded timeline** to use a locally prepared library;
higher speeds reuse the same 5x-basis investigations without new inference.
Reviewed abstentions remain labelled as abstentions, not successful leak clearance.
See the [recording commands](docs/DEMO_DETAILS.md#dashboard-recorded-walkthrough)
to build all scenarios.

## Interview walkthrough

Use the [30-minute technical code route](docs/REPORT.md#30-minute-technical-code-route)
for the whiteboard discussion and source walkthrough. The report separates
measured evidence, declared assumptions, model opinions and evaluation truth.

**Lead with the same-data comparison:** use **S1**, seed **2026**, in both
monitoring modes and pin the **same measurement window**. Sensor alerts only
leaves the investigation to the engineer; agent assistance adds the cited
assessment, inspection priority and verification handoff. Compare these outputs,
not different detector inputs or replay speeds. This does not establish measured
labor savings or superiority over a strong fixed workflow.

| Question | What to do and inspect |
|---|---|
| **Leak or faulty sensors?** | In **Evaluation → Detection**, select a case and play its saved timeline. Compare the ground-truth and agent maps, then open the recorded report and supporting quotations. Playback makes no model calls. |
| **Which measurements support that conclusion?** | In **Live**, choose **S1** and **Sensor alerts only**, then **Start new run** and **Play**. After warm-up, open **Inspect** and select a measurement window to compare paired readings, anomalies, missing/invalid values and source times. This path makes no model calls. |
| **Where should we inspect, and why?** | With model access, choose **S1 → Agent-assisted investigation**, **Start new run** and **Play**. Open the investigation's findings and **Review evidence**. Inspect the proposed interval, competing explanations and limitations; an unsupported interval is withheld. |

Fresh investigations can take several minutes and have a 15-minute hard deadline.
Numerical warnings appear independently; simulated source time pauses for an
investigation. Replay speed does **not** make model inference faster.
These are investigation questions answered through the workflow, not a chat interface.

**Evaluation → Agent reliability** explains six advisory answer-quality targets.
A clean clone has no locally generated results for that view. See the
[evaluation commands](docs/DEMO_DETAILS.md#reproduce-evaluation) to run hosted
checks; these model opinions do not establish field reliability.
The bundled Detection recording retains its actual failures and unmet targets.

## Troubleshooting and shutdown

| Symptom | Action |
|---|---|
| Bootstrap says credentials already exist | Skip bootstrap; dot-source `tools\load-environment.ps1` in each new terminal. |
| Database connection fails | Check Docker is running, then `docker compose ps` and `docker compose logs db` in the loaded terminal. Default database port: `15433`. |
| Authentication, quota or model error | Run `uv run --no-sync subsea provider-check --mode live --model gpt-6.1-sol` in the loaded terminal. Sensor-only monitoring and bundled Detection playback do not require inference. |
| **Load recorded timeline** has no investigations | That library is generated locally. Use **Evaluation → Detection** for the bundled recording; see the detailed guide to create live recordings. |

Stop the server with **Ctrl+C**. Run `docker compose stop db` in a loaded terminal
to stop this demo's database; its volume preserves evidence.

[Setup questions](https://github.com/ntnguyen-so/subsea-integrity-copilot/issues)
