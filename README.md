# Subsea Lens

**From pressure alerts to evidence-backed inspection decisions.**

[Run the demo](#run-the-demo) · [One-page brief](docs/ONE_PAGE_BRIEF.pdf) ·
[Dashboard (local)](http://127.0.0.1:8086/?tab=live) ·
[Evaluation (local)](http://127.0.0.1:8086/?tab=evaluation)

The local links open your own running demo after setup.

## The problem

Subsea pipelines carry oil and gas from offshore fields. Operators monitor pressure
along these pipelines to spot possible problems and decide when to intervene. A
missed leak can harm the marine environment, stop production and put operating
permissions at risk. But sending a vessel or underwater inspection team to
investigate faulty measurements can also be costly. The integrity engineer must
therefore distinguish a real pipeline problem from a measurement problem before
directing a response.

Making that distinction is difficult because different causes can produce similar
alerts. A pressure drop may indicate a leak, an operating change or a faulty
sensor; missing readings can obscure the picture. A leak and sensor faults may
also occur together. Before directing a response, the engineer must establish
what is happening, where attention is needed and whether the evidence is reliable
enough to act on. This turns each investigation into three practical questions:

1. Is this a leak, a change in operating or measurement conditions, or an instrument problem?
2. If a leak is suspected, which branch and section should be inspected?
3. What evidence supports that conclusion, and what still needs checking before a team is sent?

## From alerts to an investigation

The illustration below shows this challenge on a simulated 11.2 km network with
seven connected sections (P1-P7) and 112 pressure instruments. A leak on P5 occurs
alongside sensor faults, missing data and a shared data-connection problem on P7.
Both maps summarize the same 60-second slice of simulated readings of scenario S7
(see the Live tab of the dashboard), from 50 to 110 seconds into the replay, with
69 instruments flagged.

![Dashboard crop: individual pressure alerts and missing readings across seven pipeline segments](docs/assets/brief-sensor-alerts.png)

**Figure 1. Sensor alerts only.** Orange dots show unusual pressure; dashed dots
show missing or invalid readings. Question 1 requires comparing histories and
records to separate the P5 leak from P7's connection problem and sensor faults.
Question 2 requires tracing related pressure changes across branches to narrow
the inspection area. Question 3 requires checking sensor reliability and
documenting the supporting evidence. The map alone answers none of these:
repeated cross-checks take time and require knowledge of pipeline behavior.

Subsea Lens organizes these cross-checks with **three AI agents working in
sequence**. Sensor Quality checks reading reliability. Event Diagnosis uses that
assessment, pressure patterns and records to assess causes and inspection
priorities. Operator Response assembles the findings, evidence, uncertainties
and next checks into one report. A separate review checks the report against its
sources.

![Figure 2: suspected P5 leak and separate sensor or data concerns](docs/assets/brief-agent-assisted.png)

**Figure 2. The agents add an explanation to the alerts in Figure 1.** Red
highlights P5 because the report finds evidence of a possible leak there. Green
narrows the inspection priority to 700-900 m from P5's start. Purple rings identify
separate sensor or data concerns. These markings summarize the report.

The report explains which readings and records support each finding, considers
other possible causes and lists the next checks. The engineer can follow those
references, challenge the reasoning and decide what to inspect, instead of
assembling the investigation from individual alerts.

## Evaluation

Subsea Lens can generate reviewed reports in about **2.5-2.8 minutes**, as observed
in two controlled tests, helping engineers respond promptly to pipeline issues.

To test the system's answers, we compared its findings with known leaks and
instrument problems that were hidden from the agents. Across all evaluated
snapshots in the held-out synthetic detection test, leak detection achieved
**100% precision and recall, with no false leak alarms**. Identifying affected
instruments and classifying their problems also achieved **100% precision and recall**.

See the [evaluation results](docs/RESULTS.md) for the methods, measurements and
supporting evidence.

**Synthetic-data demonstration. Engineers review findings before acting.**

## Documentation

| Read | Purpose |
|---|---|
| [Customer brief](docs/ONE_PAGE_BRIEF.pdf) ([source](docs/ONE_PAGE_BRIEF.md)) | One-page problem, illustrated investigation and evaluation results. |
| [Engineering report](docs/REPORT.md) | Architecture, implementation and [30-minute code walkthrough](docs/REPORT.md#30-minute-technical-code-route). |
| [Demo reference](docs/DEMO_DETAILS.md) | Recording, evaluation, development and document-export commands. |
| [Evaluation results](docs/RESULTS.md) | Test methods, measurements and supporting evidence. |
| [Interview deck](docs/INTERVIEW_DECK.html) ([PDF](docs/INTERVIEW_DECK.pdf)) | Presentation and appendix for the full interview. |

## Run the demo

**Prerequisite for agent-assisted mode:** A GitHub Copilot account with access to
**`gpt-6.1-sol`**. Sign in through the Copilot CLI in step 3 before running new
AI investigations.

You can explore the included Detection evaluation and run sensor-only monitoring
**without a Copilot account**.

### 1. Install the Windows tools

Open **PowerShell as Administrator** and paste this block. Approve the
installation and local-script prompts. It installs WSL, PowerShell 7, Git, uv,
Node.js (including npm) and Docker Desktop.

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Install-PackageProvider -Name NuGet -Force | Out-Null
    Install-Module -Name Microsoft.WinGet.Client -Force -Repository PSGallery
    Repair-WinGetPackageManager -AllUsers
}

wsl --install --no-distribution
winget install --id Microsoft.PowerShell --exact --source winget --accept-package-agreements --accept-source-agreements
winget install --id Git.Git --exact --source winget --accept-package-agreements --accept-source-agreements
winget install --id astral-sh.uv --exact --source winget --accept-package-agreements --accept-source-agreements
winget install --id OpenJS.NodeJS.LTS --exact --source winget --accept-package-agreements --accept-source-agreements
winget install --id Docker.DockerDesktop --exact --source winget --accept-package-agreements --accept-source-agreements
```

Restart Windows after installation. Then open **PowerShell 7** from the Start
menu under your usual Windows account.

### 2. Install and start Subsea Lens

Paste this block into PowerShell 7. Complete Docker Desktop's first-run prompts
when it opens. The commands download the project, install Python 3.11 and the
project dependencies, create local credentials, prepare the database and start
the dashboard.

```powershell
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true

wsl --update
docker desktop start --timeout 180
docker desktop engine use linux

Set-Location $HOME
git clone https://github.com/ntnguyen-so/subsea-integrity-copilot.git
Set-Location subsea-integrity-copilot
uv sync --locked --python 3.11
npm ci

$secretFile = Join-Path $env:LOCALAPPDATA 'SubseaCopilot\secrets.json'
if (-not (Test-Path -LiteralPath $secretFile)) {
    .\tools\bootstrap.ps1
}
. .\tools\load-environment.ps1
$env:SUBSEA_TELEMETRY_ENABLED = '0'
docker compose up -d --wait db
uv run --no-sync subsea migrate

Write-Host "Dashboard: http://127.0.0.1:8086"
Write-Host "Username: operator"
Write-Host "Password: $env:SUBSEA_OPERATOR_PASSWORD"
uv run --no-sync subsea serve
```

Keep the terminal open. Visit **http://127.0.0.1:8086** and sign in as
**`operator`**, using the password printed in the terminal.

Keep your credentials private. They are stored locally in
`%LOCALAPPDATA%\SubseaCopilot\secrets.json` and reused on subsequent starts.
The frontend builds automatically when the server starts.

### 3. Optional: install and enable AI report generation

For new agent-assisted reports, use a Copilot account with access to
**`gpt-6.1-sol`**. Investigations and the availability check below use your
Copilot allowance.

Stop the server with **Ctrl+C** first; leave the database running. In the loaded
repository terminal, paste the following and complete the sign-in prompts.
The dashboard restarts after a successful model-access check:

```powershell
npm install --global @github/copilot
copilot login
uv run --no-sync subsea provider-check --mode live --model gpt-6.1-sol
uv run --no-sync subsea serve
```

### Start the demo again

For later sessions, open PowerShell 7 and paste:

```powershell
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
Set-Location (Join-Path $HOME 'subsea-integrity-copilot')
. .\tools\load-environment.ps1
$env:SUBSEA_TELEMETRY_ENABLED = '0'
docker desktop start --timeout 180
docker compose up -d --wait db
uv run --no-sync subsea serve
```

## Explore the demo

For technical interviews, the
[30-minute code walkthrough](docs/REPORT.md#30-minute-technical-code-route)
connects the architecture, implementation and evaluation evidence.

Use **S7**, seed **2026**, for the 112-instrument network illustrated above.
Compare monitoring modes using the **same scenario, seed and measurement window**.

| Question | What to do and inspect |
|---|---|
| **Leak or faulty sensors?** | In **Evaluation → Detection**, select a case and play its saved timeline. Compare the ground-truth and agent maps, then open the recorded report and supporting quotations. Playback makes no model calls. |
| **Which measurements support that conclusion?** | In **Live**, choose **S7** and **Sensor alerts only**, then **Start new run** and **Play**. After warm-up, open **Inspect** and select a measurement window to compare paired readings, anomalies, missing/invalid values and source times. This path makes no model calls. |
| **Where should we inspect, and why?** | After enabling model access, choose **S7 → Agent-assisted investigation**, **Start new run** and **Play**. Open the investigation's findings and **Review evidence** to inspect the proposed area, competing explanations and supporting sources. |

The included recording is available under **Evaluation → Detection**.
**Load recorded timeline** uses an optional, locally generated library; the
[recording guide](docs/DEMO_DETAILS.md#prepare-a-local-recording-library)
explains how to create it. Replay supports **5x, 10x, 20x and 30x**; simulated time
pauses while agents investigate.

Additional results for **Evaluation → Agent reliability** can be generated using
the [evaluation guide](docs/DEMO_DETAILS.md#reproduce-evaluation).

## Shutdown and support

Stop the server with **Ctrl+C**. Run `docker compose stop db` in a loaded terminal
to stop this demo's database; its volume preserves evidence.

[Setup questions](https://github.com/ntnguyen-so/subsea-integrity-copilot/issues)
