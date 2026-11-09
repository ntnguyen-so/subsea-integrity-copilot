# Subsea Integrity Copilot

**From pressure alerts to evidence-backed inspection decisions.**

Existing detectors flag unusual readings. This demo helps an integrity engineer
investigate whether they suggest a pipeline leak, faulty instruments or an
operating change, and understand where to inspect and why.
**Synthetic data only. Read-only decision support, not a safety system.**

[One-page customer brief](docs/ONE_PAGE_BRIEF.pdf) ·
[Brief source](docs/ONE_PAGE_BRIEF.md) ·
[Architecture and engineering report](docs/REPORT.md)

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

## Interview walkthrough

### 30-minute technical code route

The source comments follow the same boundaries as this whiteboard route.
Start with **measurements → immutable window → governed investigation → checked
handoff → browser**, and draw evaluation as a separate path with hidden labels.

| Time | Discussion and code to open |
|---|---|
| 0–5 min | **Architecture:** `api.py` wires the service; `monitoring.py` advances measurements independently of model calls; `runtime/workflow.py` coordinates durable specialist tasks. `store.py` and `migrations/` enforce scope, leases, budgets and immutable evidence. |
| 5–11 min | **Data:** `synthetic.py` declares seeded, illustrative pressure signals; `ingest.py` normalizes units/time while retaining raw records and quarantining identity conflicts. `contracts.py` defines the versioned window policy; `diagnostics.py` computes the evidence ledger. |
| 11–18 min | **Agent reasoning and answer checks:** `runtime/registry.py` defines role capabilities; `runtime/gateway.py` executes bounded reads; `history.py` retrieves incident-visible records and computes comparisons. `validation.py` checks structured claims and executed citations; `grounding.py` checks the review protocol, whose semantic verdict remains a model opinion. |
| 18–24 min | **Where numbers come from:** `anomaly.py` fits median/MAD; `profiles.py` computes measured deltas and paired-complete correlations; `localization.py` explains legacy station brackets. `evaluation_metrics.py` and the evaluation runners score hidden synthetic labels; `execution_usage.py` separates reported usage from estimated cost. |
| 24–30 min | **Evidence and limits:** `casefile.py` assembles an auditable handoff; `playback.py` binds saved reports to their input hashes; `web/ts/console.ts` and `evaluation.ts` present live/recorded evidence. Open the corresponding `tests/test_*.py` for failure cases, and discuss what remains unvalidated in the field. |

**Separate assumptions from results.** The default 1 Hz cadence, 60-second
window, 5-second hop/lateness allowance, five-scale alert threshold, 60% minimum
coverage and 15-second persistence are declared demo policy in `SitePack`, not
learned accuracy figures. The detector uses
`(pressure − baseline median) / max(1.4826 × MAD, minimum scale)`;
that score is **not a leak probability**. Coverage is distinct usable timestamps
divided by expected samples across instruments.

**Separate monitoring from diagnosis.** Agent-assisted windows use
`screening_only=True`: they contain measured alerts, not a preselected numerical
cause or inspection answer. The fuller deterministic diagnosis and bracket helpers
remain for legacy/evaluation paths. Correlation is not causal independence;
station/gateway metadata and operating records matter. An inspection interval is
not an exact hydraulic source coordinate or a confidence interval.

**Separate evidence from evaluation.** Raw fixtures, advisory knowledge and
operating records serve different roles; authored evaluation labels must stay
outside agent inputs. Report measured scores with their actual case denominators,
failures, split and saved artifacts, not just a headline percentage. Scripted
tests establish software invariants, not hosted reasoning quality; model reviews
and synthetic held-out results do not establish field reliability.

**Artifact boundaries:** `packs/` contains site configuration; `fixtures/` holds
raw synthetic arrivals, operational/advisory documents and evaluation references.
`src/subsea_copilot/prompts/` contains executable model instructions; its Python
loader documents prompt selection and hashing without changing those instructions.
`docs/evidence/` contains saved observations/results, while `runtime/` contains
locally generated artifacts. JSON, JSONL, lockfiles and saved evidence are left
unaltered: adding inline comments would invalidate their formats or provenance.
`scripts/` and `tools/` document preparation/export side effects at their entry
points; tests describe which software guarantees they establish.

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
Its eight authored factual-reference cases are in
[`fixtures/synthetic/agent-reliability-cases.json`](fixtures/synthetic/agent-reliability-cases.json).
A clean clone has no locally generated Agent reliability results. To run them:

```powershell
. .\tools\load-environment.ps1
$env:SUBSEA_TELEMETRY_ENABLED = '0'
$env:SUBSEA_TRACE_CONTENT = '1'
uv run subsea provider-check --mode live --model gpt-6.1-sol
uv run subsea agent-evaluation --split all --output runtime\interview-agent-eval
```

This makes real hosted calls; use a **new output directory** for each evaluation.
Detection uses independently declared synthetic labels. Answer-quality scores
are model opinions, not engineer-validated reliability or field-accuracy claims.
The bundled recording retains its actual failures and unmet targets.

## Troubleshooting and shutdown

| Symptom | Action |
|---|---|
| Bootstrap says credentials already exist | Skip bootstrap; dot-source `tools\load-environment.ps1` in each new terminal. |
| Database connection fails | Check Docker is running, then `docker compose ps` and `docker compose logs db` in the loaded terminal. Default database port: `15433`. |
| Authentication, quota or model error | Run the explicit provider check above. Sensor-only monitoring and bundled Detection playback do not require inference. |
| **Load recorded timeline** has no investigations | That library is generated locally. Use **Evaluation → Detection** for the bundled recording; see the detailed guide to create live recordings. |

Stop the server with **Ctrl+C**. Run `docker compose stop db` in a loaded terminal
to stop this demo's database; its volume preserves evidence.

[Detailed demo, recordings and evaluation commands](docs/DEMO_DETAILS.md) ·
[Evaluation evidence and limitations](docs/RESULTS.md) ·
[Setup questions](https://github.com/ntnguyen-so/subsea-integrity-copilot/issues)
