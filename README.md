# Subsea Integrity Copilot

Read-only FDE demo for a fictional offshore oil-and-gas operator's gas pipelines: distinguish coherent
possible-leak evidence from sensor/telemetry faults, then identify a defensible
inspection section or withhold location. **Synthetic data only; not a safety system.**

Private repository: https://github.com/ntnguyen-so/subsea-integrity-copilot.
Reviewers need repository access before the interview.

## Run on Windows

Requires Python 3.11, `uv`, Node.js, Docker Desktop with Linux containers, and
PowerShell. Live mode additionally requires an authenticated GitHub Copilot CLI
with model access. Scripted mode works without inference but is visibly labeled;
it is not evidence of live-model performance.

```powershell
uv sync --locked
npm ci
npm run build
.\tools\bootstrap.ps1
. .\tools\load-environment.ps1
docker compose up -d --wait
docker compose -f docker-compose.langfuse.yml up -d --wait
uv run subsea migrate
uv run subsea serve
```

Bootstrap runs **once** and refuses overwriting credentials. It stores user-only
credentials outside the repository at `%LOCALAPPDATA%\SubseaCopilot\secrets.json`.
Dot-source the loader in every new terminal before running database commands.

Open http://127.0.0.1:8086; username `operator`, password from the locally loaded
`SUBSEA_OPERATOR_PASSWORD`. Never commit or share credential values. Langfuse is
http://127.0.0.1:3001 (`operator@subsea.local`, `LF_ADMIN_PASSWORD`); optional Jaeger
is http://127.0.0.1:16687. Services/volumes are project-owned and loopback-bound.
Stopping Compose without `-v` preserves evidence.

Create S1, select 10x speed, Play, then pause when a possible leak appears. Select
a sensor with mouse or keyboard; inspect all three channels and raw/canonical
records. Ask the three suggested questions and inspect the **pinned window,
specialist tasks, cited evidence and counters**. Compare S2's scattered faults and
S5's physical signal with too few observers. S3 demonstrates a shared-gateway/full-source
outage, S4 a broad environmental disturbance, and S6 verified-normal variability.
No actuator or shutdown endpoint exists.

For an explicit synthetic availability check or live qualification:

```powershell
uv run subsea provider-check --mode live --model gpt-6.1-sol
uv run subsea evaluate --suite agents --mode live
```

Live calls consume your Copilot allowance and may take minutes. Authentication or
quota failure blocks further live work; it does not stop numerical monitoring.
There is no automatic provider switch/retry. The CLI is local, **inference is hosted**.
The console and qualification pin `gpt-6.1-sol`; choose LIVE before creating a new
generation to demonstrate real inference. SCRIPTED remains an explicit offline mode.

## Architecture and verification

CustomerOps-inspired Python/FastAPI + PostgreSQL + original TypeScript/esbuild UI.
LangChain provides the model interface; LangGraph persists interrupt-driven role
workflows in PostgreSQL. Native OpenTelemetry exports bounded asynchronous spans
to self-hosted Langfuse/Jaeger; stored trace visibility is checked separately from
HTTP acceptance.

Numerical code owns unit/time normalization, conflict quarantine, median/MAD
anomalies, independent spatial corroboration and distance-decay fitting. Three
scoped quality/diagnosis/response agents use read-only tools, immutable evidence,
bounded calls and checked claim IDs. The model cannot fabricate accepted numbers.
Monitoring uses 60-second windows, 5-second hops and 5-second lateness, independently
of the inference worker; late evidence creates revisions rather than rewriting history.

```powershell
. .\tools\load-environment.ps1
uv run pytest -q
uv run ruff check .
uv run mypy src
npm run typecheck
npm run build
npx playwright test
uv run subsea evaluate --suite agents --mode scripted
```

Browser qualification requires the running server and installed Chrome. Numerical
held-out results are in `fixtures\synthetic\evaluation-results.json`; fresh cohort
receipts go to ignored `eval\results`. Never substitute scripted success for live
qualification or synthetic accuracy for field reliability.

Final live qualification accepted 27/27 answers across S1/S2/S5, including required
location abstentions, with actual `gpt-6.1-sol` receipts and a verified stored trace.
The same-evidence single-agent baseline also passed with fewer calls and lower latency
in this cohort; separate roles provide bounded authority and audit, not demonstrated accuracy
improvement. See `docs\RESULTS.md` and `docs\evidence\agents-live.json` for measurements,
retained failures and synthetic-only limitations.

See [the brief](https://github.com/ntnguyen-so/subsea-integrity-copilot/blob/main/docs/ONE_PAGE_BRIEF.md),
[engineering report](https://github.com/ntnguyen-so/subsea-integrity-copilot/blob/main/docs/REPORT.md)
and the retained milestone/design plans in `docs`. Localization is a compatible
range under an idealized model, not a calibrated confidence interval. Human
integrity engineers retain inspection and safety authority.

The verified one-page attachment is `docs\ONE_PAGE_BRIEF.pdf`; regenerate it with
`node scripts\render-brief.cjs` after editing the brief.

## Interview deck

Open `docs\INTERVIEW_DECK.html` directly in Chrome or Edge; no server is required
for the presentation. `docs\INTERVIEW_DECK.pdf` is the widescreen audience export.
Its evidence/code links point to GitHub rather than this computer's local paths;
reviewers need private repository access.
The 18-slide main story follows **5m problem / 10m live demo / 30m technical
whiteboard / 10m business / 5m out-of-role questions**. Four on-demand appendices
do not add scheduled time.

Use Left/Right or Page Up/Down to navigate, Home for the first slide, End for the
out-of-role questions, and **N** for presenter notes. Chapter buttons and the slide
selector jump directly. Start/pause/reset the elapsed interview clock explicitly;
navigation does not reset it. Notes include live-demo steps, whiteboard prompts,
timed handoffs and an honestly labeled recorded-evidence fallback.

The deck is original; CustomerOps informs its customer-first narrative, evidence
chain, scoped specialists, durable execution and explicit tradeoffs. Diagrams are
original SVGs, not copied reference/marketing assets. LIVE measurements and synthetic
limits link to retained receipts; the deck does not introduce new field claims.

```powershell
npm run deck:test
npm run deck:pdf
```
