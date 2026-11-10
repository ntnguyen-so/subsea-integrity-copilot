# Subsea Lens

**From pressure alerts to evidence-backed inspection decisions.**

[Run the demo](#run-the-demo) · [One-page brief](docs/ONE_PAGE_BRIEF.pdf) ·
[Dashboard (local)](http://127.0.0.1:8086/?tab=live) ·
[Evaluation (local)](http://127.0.0.1:8086/?tab=evaluation)

The figures below introduce the workflow. Follow **Run the demo** to explore it
yourself; the local links open the dashboard on your computer after setup.

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

The three questions become harder when many instruments raise alerts together.
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
and next checks into one report. An additional automated review checks the report
against its sources before the engineer receives it.

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

To evaluate this handoff, we measured report-preparation time and checked whether
the findings matched known simulated leaks and instrument problems.

Subsea Lens can generate reviewed reports in about **2.5-2.8 minutes**, as observed
in two controlled tests, helping engineers respond promptly to pipeline issues.

For the diagnostic checks, the known answers were hidden from the agents.
We then compared their findings with those answers. Across all evaluated
snapshots in the held-out synthetic detection test, leak detection achieved
**100% precision and recall, with no false leak alarms**. Identifying affected
instruments and classifying their problems also achieved **100% precision and recall**.

See the [evaluation results](docs/RESULTS.md) for the methods, measurements and
supporting evidence.

**Synthetic-data demonstration. Engineers review findings before acting.**

## Run the demo

The figures above show selected moments from a dashboard you can explore yourself.
Its **Live** workspace lets you run simulated monitoring scenarios, inspect sensor
readings and compare their histories. Its **Evaluation** workspace lets you
replay saved tests and compare agent findings with the known simulated outcomes.

After setup, start with **Evaluation → Detection**, which includes the saved
readings and reports behind the detection results above. Playback displays existing findings
instead of calling the agents again, so **no Copilot account is needed**.
You can also replay agent-assisted runs in Live without Copilot when their
recordings are available locally.

For a new simulated run, **Sensor alerts only** shows readings and alerts for
manual investigation, also without Copilot. Choose **Agent-assisted investigation**
when you want the agents to generate a new report. **Only new AI investigations
require a GitHub Copilot account**, with access to **`gpt-6.1-sol`** and Copilot CLI
sign-in.

Steps 1 and 2 below set up the dashboard for saved playback and sensor-only
monitoring. Step 3 adds the Copilot connection for new AI reports.

### 1. Install the Windows tools

The demo runs locally on Windows. Open **PowerShell as Administrator** and paste
this block. Approve the installation and local-script prompts. It installs WSL,
PowerShell 7, Git, uv, Node.js (including npm) and Docker Desktop.

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

With the tools installed, paste this block into the PowerShell 7 window opened
after the restart. Complete Docker Desktop's first-run prompts when it opens.
The commands download the project, install Python 3.11 and the project
dependencies, create local credentials, prepare the database and start the
dashboard.

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

When the server is ready, visit **http://127.0.0.1:8086** and sign in as
**`operator`**, using the password printed in the terminal. This is the dashboard's
local sign-in, separate from your GitHub account. Keep the terminal open while
using the dashboard.

Keep your credentials private. They are stored locally in
`%LOCALAPPDATA%\SubseaCopilot\secrets.json` and reused on subsequent starts.

The dashboard is now ready for the [walkthrough below](#explore-the-demo).
If you also want new AI reports, complete step 3 first.

### 3. Optional: install and enable AI report generation

After exploring saved reports or sensor-only monitoring, you can connect the
agents to investigate a new run. This requires a GitHub Copilot account with
access to **`gpt-6.1-sol`**. New investigations and the availability check below
use your Copilot allowance.

Press **Ctrl+C** in the server terminal from step 2; leave the database running.
In that same terminal, paste the following and complete the Copilot sign-in
prompts. The dashboard restarts after a successful model-access check:

```powershell
npm install --global @github/copilot
copilot login
uv run --no-sync subsea provider-check --mode live --model gpt-6.1-sol
uv run --no-sync subsea serve
```

## Explore the demo

Once signed in, use the three investigation questions introduced above to guide
your walkthrough. Begin with the included saved results, then explore the sensor
readings, and finally try a new agent-assisted investigation if you enabled
Copilot in step 3.

For the two **Live** walkthroughs, use **S7**, seed **2026**, to explore the
112-instrument network illustrated above. Compare the workflows using the
**same scenario, seed and measurement window**.

| Question | What to do and inspect |
|---|---|
| **Leak or faulty sensors?** | In **Evaluation → Detection**, select a case and play its saved timeline. Compare the known simulated outcome with the agent's findings on the two maps, then open the recorded report and supporting quotations. |
| **Which measurements support that conclusion?** | In **Live**, choose **S7** and **Sensor alerts only**, then **Start new run** and **Play**. After warm-up, choose **Inspect this sensor** or **Compare sensor histories** in the sensor-analysis panel to review readings and their measurement window. This path makes no model calls. |
| **Where should we inspect, and why?** | After enabling model access, choose **S7 → Agent-assisted investigation**, **Start new run** and **Play**. Open the investigation's findings and **Review evidence** to inspect the proposed area, competing explanations and supporting sources. |

To replay an S1-S7 agent-assisted run in **Live**, choose **Agent-assisted
investigation → Load recorded timeline**. This uses a locally prepared recording
library, separate from the Detection recordings included with the project.
The [recording guide](docs/DEMO_DETAILS.md#prepare-a-local-recording-library)
explains how to generate that library with Copilot; replaying it afterwards makes
no new model calls.

Replay controls offer **5x, 10x, 20x and 30x** to move through simulated time.
The simulated clock pauses while an agent investigation is being processed.

For a separate review of report quality, **Evaluation → Agent reliability**
provides additional checks. Their results are generated separately from the
included Detection evaluation; the
[evaluation guide](docs/DEMO_DETAILS.md#reproduce-evaluation) explains how to run
these new AI checks with Copilot.

For interviews and architecture discussions, the
[30-minute code walkthrough](docs/REPORT.md#30-minute-technical-code-route)
connects the screens above to their implementation and evaluation evidence.

## Stop and return later

When finished, press **Ctrl+C** in the server terminal. In that same terminal,
stop the database with:

```powershell
docker compose stop db
```

Your local credentials and database are retained. For a later session, open
PowerShell 7 and paste the following to return to the same installation:

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

[Setup questions](https://github.com/ntnguyen-so/subsea-integrity-copilot/issues)
