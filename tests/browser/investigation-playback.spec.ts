/**
 * Recorded/live timeline boundary: no future backfill, exact checkpoint evidence,
 * no inference on playback, pause-before-recording and separate fixed-time live work.
 * Delayed reads must hold each window without catching up/skipping after load.
 */
import { test, expect, type Page } from "@playwright/test";
import { availableRecording } from "../../web/ts/investigation_playback";
import type { SavedInvestigation } from "../../web/ts/investigation_playback";

async function selectCheckpoint(page: Page, seconds: number): Promise<void> {
  await page.getByRole("tab", { name: "Live", exact: true }).click();
  const slider = page.getByRole("slider", { name: "Selected source time" });
  await expect(slider).toBeEnabled();
  await slider.evaluate((element, value) => {
    const input = element as HTMLInputElement;
    input.value = String(value); input.dispatchEvent(new Event("input", { bubbles: true }));
  }, seconds);
  await expect(page.locator("#investigation-time-label")).toHaveText(`+${seconds}s`);
}

test("recording selection never backfills future findings and retains newest trial", () => {
  const row = (id: string, time: number, created: string, state = "SUCCEEDED"): SavedInvestigation => ({
    task_id: id, source_seconds: time, created_at: created, state,
    snapshot_id: id, input_hash: id, origin: "library",
  });
  const rows = [row("later", 120, "b"), row("first", 100, "a"), row("retry", 100, "b"),
    row("failed", 110, "c", "FAILED")];
  expect(availableRecording(rows, 95)).toBeUndefined();
  expect(availableRecording(rows, 100)?.task_id).toBe("retry");
  expect(availableRecording(rows, 115)?.task_id).toBe("failed");
  expect(availableRecording(rows, 120)?.task_id).toBe("later");
});

test("S7 walkthrough renders preserved outputs next to their exact map without inference", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Requires local owned demo.");
  const login = await page.request.post("/api/login", { data: {
    username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD,
  } });
  expect(login.status()).toBe(200);
  const { replays } = await (await page.request.get("/api/replays")).json();
  const replay = replays.find((row: { scenario: string; seed: number }) => row.scenario === "S7" && row.seed === 2026);
  expect(replay).toBeDefined();
  const manifest = await (await page.request.get(`/api/replays/${replay.id}/recordings`)).json();
  await page.route(`**/api/replays/${replay.id}/recordings`, route => route.fulfill({
    json: { ...manifest, recordings: manifest.recordings.filter(
      (row: SavedInvestigation) => row.origin === "library",
    ) },
  }));
  const requests: string[] = [];
  page.on("request", request => { if (request.method() === "POST") requests.push(request.url()); });
  await page.goto("/?replay=" + encodeURIComponent(replay.id));
  await expect(page.locator("#play")).toBeEnabled({ timeout: 30000 });
  await expect(page.locator("#source-clock")).toContainText("RECORDED PAUSED");
  await expect(page.locator("#replay-history, #recorded-investigation")).toHaveCount(0);
  await expect(page.locator("#speed")).toHaveValue("5");
  await selectCheckpoint(page, 0);
  await expect(page.locator(".live-grid")).toBeVisible();
  await expect(page.locator("#topology [data-sensor]")).toHaveCount(112);
  await expect(page.locator("#topology")).toHaveAttribute("data-source-seconds", "");
  await expect(page.locator("#agent-investigation-map")).toContainText("No earlier accepted evidence");
  await selectCheckpoint(page, 100);
  const map = page.getByRole("group", { name: "Dedicated agent investigation pipeline map" });
  await expect(map).toBeVisible();
  await expect(map).toHaveAttribute("data-source-seconds", "100");
  await expect(page.locator("#topology")).toHaveAttribute("data-source-seconds", "100");
  await expect(page.locator("#channel-charts svg")).toHaveCount(1);
  const snapshot = await page.locator("#topology").getAttribute("data-snapshot");
  await expect(page.locator("#channel-charts")).toHaveAttribute("data-snapshot", snapshot!);
  await page.locator('#topology [data-sensor="P2-ST2-A"]').click();
  await expect(page.locator("#sensor-title")).toContainText("P2-ST2-A");
  await expect(page.locator("#channel-charts")).toHaveAttribute("data-snapshot", snapshot!);
  await expect(page.locator("#automatic-progress")).toContainText("Why this location");
  await expect(page.locator("#automatic-state")).toContainText("RECORDED");
  await expect(page.locator('#topology [data-issue-kinds]:not([data-issue-kinds=""])').first())
    .toHaveAttribute("aria-label", /Agent instrument finding:/);
  await expect(page.locator("#simulation-policy")).toContainText("checkpoints");
  await expect(page.locator("#simulation-policy")).toContainText("preserved attempts");
  await page.getByRole("tab", { name: "Inspect", exact: true }).click();
  await expect(page.locator(".inspection-agent")).toHaveAttribute("data-status", "matched");
  await expect(page.locator(".inspection-agent")).toContainText("Compatible saved investigation");
  await expect(page.locator(".inspection-trends svg")).toHaveCount(2);
  await page.getByRole("button", { name: "Review this saved report and its quoted findings" }).click();
  await expect(page.locator("#tab-live")).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("#automatic-title")).toBeFocused();
  await page.getByRole("tab", { name: "Evaluation", exact: true }).click();
  await page.locator("#review-agent-findings").click();
  await expect(page.locator("#tab-live")).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("#automatic-title")).toBeFocused();
  await selectCheckpoint(page, 115);
  await page.getByRole("tab", { name: "Inspect", exact: true }).click();
  await expect(page.locator(".inspection-agent")).not.toHaveAttribute("data-status", "matched");
  await page.getByRole("tab", { name: "Live", exact: true }).click();
  await expect(page.locator("#topology")).toHaveAttribute("data-source-seconds", "115");
  await expect(page.locator("#topology .inspection-interval")).toHaveCount(0);
  await expect(map).toHaveAttribute("data-source-seconds", "110");
  const savedTask = await page.locator("#automatic-state").getAttribute("data-task");
  for (const speed of ["10", "20", "30"]) {
    await page.locator("#speed").selectOption(speed);
    await expect(page.locator("#automatic-state")).toHaveAttribute("data-task", savedTask!);
  }
  await selectCheckpoint(page, 0);
  await expect(map).toHaveCount(0);
  await expect(page.locator("#topology")).toHaveAttribute("data-source-seconds", "");
  await expect(page.locator("#channel-charts svg")).toHaveCount(0);
  await selectCheckpoint(page, 100);
  await expect(map).toHaveAttribute("data-source-seconds", "100");
  await expect(page.locator("#simulation-policy")).toContainText("Between checkpoints");
  await expect(page.locator(".live-grid")).toBeVisible();
  expect(requests).toEqual([]);
  const boxes = await Promise.all([
    page.locator("#agent-investigation-map").boundingBox(),
    page.locator("#automatic-progress").boundingBox(),
  ]);
  expect(boxes[0]!.x + boxes[0]!.width).toBeLessThanOrEqual(boxes[1]!.x + 1);
});

test("default S7 timeline selects genuinely accepted reports at every saved checkpoint", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Requires local owned demo.");
  await page.request.post("/api/login", { data: {
    username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD,
  } });
  const { replays } = await (await page.request.get("/api/replays")).json();
  const replay = replays.find((row: { scenario: string; seed: number; workflow: string }) =>
    row.scenario === "S7" && row.seed === 2026 && row.workflow === "agent_assisted");
  expect(replay).toBeDefined();
  const endpoint = `/api/replays/${replay.id}/recordings`;
  const { recordings }: { recordings: SavedInvestigation[] } =
    await (await page.request.get(endpoint)).json();
  const points = [...new Set(recordings.map(row => row.source_seconds))].sort((a, b) => a - b);
  expect(points.length).toBeGreaterThan(0);
  await page.goto("/?replay=" + encodeURIComponent(replay.id));
  for (const point of points) {
    const selected = availableRecording(recordings, point)!;
    expect(selected.state, `Latest attempt at +${point}s`).toBe("SUCCEEDED");
    const response = await page.request.get(`${endpoint}/${selected.task_id}`);
    expect(response.status()).toBe(200);
    const { snapshot, detail } = await response.json();
    expect(snapshot.input_hash).toBe(selected.input_hash);
    expect(detail.casefile.state).toBe("SUCCEEDED");
    expect(detail.casefile.input_hash).toBe(snapshot.input_hash);
    expect(detail.task.interpretation_review.rounds.at(-1).assessment.decision).toBe("accept");
    expect(detail.children.every((child: { state: string }) => child.state === "SUCCEEDED")).toBe(true);
    await selectCheckpoint(page, point);
    await expect(page.locator("#automatic-state")).toHaveAttribute("data-task", selected.task_id);
    await expect(page.locator("#automatic-state")).toContainText("SUCCEEDED");
    const traceResponse = await page.request.get(`${endpoint}/${selected.task_id}/trace`);
    expect(traceResponse.ok()).toBeTruthy();
    const trace = await traceResponse.json();
    expect(trace.task_id).toBe(selected.task_id);
    expect(trace.snapshot_id).toBe(snapshot.id);
    expect(trace.trace_id).toMatch(/^[a-f0-9]{32}$/);
    await expect(page.locator("#automatic-langfuse")).toBeVisible();
    await expect(page.locator("#automatic-langfuse")).toHaveAttribute("data-task", selected.task_id);
    await expect(page.locator("#automatic-langfuse")).toHaveAttribute("href",
      new RegExp(trace.trace_layout === "investigation-v1" ? trace.trace_id : trace.session_id));
    await expect(page.locator("#trace-view")).toHaveAttribute("data-task", selected.task_id);
  }
});

for (const scenario of ["S1", "S2", "S3", "S4", "S5", "S6"]) {
  test(`${scenario} recorded timeline keeps reviewed results, maps and traces at all four speeds`, async ({ page }) => {
    test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Requires local owned recordings.");
    test.setTimeout(180000);
    const login = await page.request.post("/api/login", { data: {
      username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD,
    } });
    expect(login.ok()).toBeTruthy();
    const created = await page.request.post("/api/replays", {
      headers: { "X-CSRF-Token": (await login.json()).csrf_token },
      data: { scenario, seed: 2026, mode: "live", workflow: "agent_assisted",
        idempotency_key: `scenario-recordings-${scenario}-${Date.now()}` },
    });
    expect(created.ok()).toBeTruthy();
    const replay = await created.json();
    expect(replay.speed).toBe(5);
    await page.goto("/");
    await expect(page.locator("#load-recording")).toBeEnabled();
    await page.locator("#scenario").selectOption(scenario);
    await page.locator(".run-settings > summary").click();
    await page.locator("#seed").fill("2026");
    const loaded = page.waitForResponse(new RegExp(`/api/replays/${replay.id}/projection$`));
    await page.getByRole("button", { name: "Load recorded timeline", exact: true }).click();
    expect((await loaded).ok()).toBeTruthy();
    await expect(page.locator("#source-clock")).toContainText("RECORDED PAUSED");
    await expect(page.locator("#speed")).toHaveValue("5");
    expect(await page.locator("#speed option:not([disabled])").evaluateAll(options =>
      options.map(option => (option as HTMLOptionElement).value))).toEqual(["5", "10", "20", "30"]);
    const endpoint = `/api/replays/${replay.id}/recordings`;
    const { recordings }: { recordings: SavedInvestigation[] } =
      await (await page.request.get(endpoint)).json();
    const writes: string[] = [];
    page.on("request", request => {
      if (request.method() === "POST") writes.push(request.url());
    });
    const points = [95, 100, 105, 110, 120, 135, 150, 180, 360];
    if (scenario === "S1") points.push(115, 260);
    if (scenario === "S4") points.push(155);
    for (const point of points.sort((a, b) => a - b)) {
      const selected = availableRecording(recordings, point)!;
      expect(selected.source_seconds).toBe(point);
      expect(["SUCCEEDED", "ABSTAINED"]).toContain(selected.state);
      const response = await page.request.get(`${endpoint}/${selected.task_id}`);
      expect(response.ok()).toBeTruthy();
      const { snapshot, detail } = await response.json();
      expect(detail.casefile.input_hash).toBe(snapshot.input_hash);
      expect(detail.task.interpretation_review.rounds.at(-1).assessment.decision).toBe("accept");
      await selectCheckpoint(page, point);
      await expect(page.locator("#automatic-state")).toHaveAttribute("data-task", selected.task_id);
      const map = page.getByRole("group", { name: "Dedicated agent investigation pipeline map" });
      await expect(map).toHaveAttribute("data-source-seconds", String(point));
      await expect(page.locator("#topology [data-sensor]")).toHaveCount(24);
      await expect(page.locator("#automatic-langfuse")).toHaveAttribute("data-task", selected.task_id);
      const traceResponse = await page.request.get(`${endpoint}/${selected.task_id}/trace`);
      expect(traceResponse.ok()).toBeTruthy();
      const trace = await traceResponse.json();
      expect(trace.stored_trace_visible).toBe(true);
      expect(trace.snapshot_id).toBe(snapshot.id);
      if (selected.state === "ABSTAINED") {
        await expect(page.locator("#agent-investigation-map")).toContainText(
          "abstained report; cause and location not established");
        await expect(page.locator("#agent-investigation-map")).toContainText("No diagnosis overlay");
        await expect(map.locator(".eval-inspection")).toHaveCount(0);
      } else {
        expect(detail.output_mapping.status).toBe("completed");
      }
    }
    const selectedTask = await page.locator("#automatic-state").getAttribute("data-task");
    for (const speed of ["5", "10", "20", "30"]) {
      await page.locator("#speed").selectOption(speed);
      await expect(page.locator("#step")).toHaveText(`Forward ${speed}s`);
      await expect(page.locator("#automatic-state")).toHaveAttribute("data-task", selectedTask!);
    }
    expect(writes).toEqual([]);
  });
}

test("recorded trace selection rejects late and mismatched traces without withholding the report", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Requires local owned demo.");
  await page.request.post("/api/login", { data: {
    username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD,
  } });
  const { replays } = await (await page.request.get("/api/replays")).json();
  const replay = replays.find((row: { scenario: string; seed: number; state: string }) =>
    row.scenario === "S7" && row.seed === 2026 && row.state === "PAUSED");
  expect(replay).toBeDefined();
  const endpoint = `/api/replays/${replay.id}/recordings`;
  const { recordings }: { recordings: SavedInvestigation[] } =
    await (await page.request.get(endpoint)).json();
  const first = availableRecording(recordings, 100)!;
  const second = availableRecording(recordings, 105)!;
  expect(first.task_id).not.toBe(second.task_id);
  let release = (): void => {};
  const gate = new Promise<void>(resolve => { release = resolve; });
  let started = false, wrongScope = false;
  const trace = (row: SavedInvestigation, id: string) => ({
    task_id: row.task_id, snapshot_id: row.snapshot_id, trace_id: id,
    trace_layout: "investigation-v1", stored_trace_visible: true,
    langfuse_url: `http://localhost:3001/project/subsea-copilot/traces/${id}`,
  });
  await page.route(`**${endpoint}/${first.task_id}/trace`, async route => {
    started = true;
    await gate;
    await route.fulfill({ json: trace(first, "1".repeat(32)) });
  });
  await page.route(`**${endpoint}/${second.task_id}/trace`, route => route.fulfill({
    json: { ...trace(second, "2".repeat(32)), task_id: wrongScope ? "wrong-run" : second.task_id },
  }));
  const writes: string[] = [];
  page.on("request", request => { if (request.method() === "POST") writes.push(request.url()); });
  await page.goto("/?replay=" + encodeURIComponent(replay.id));
  try {
    await selectCheckpoint(page, 100);
    await expect.poll(() => started).toBe(true);
    await expect(page.locator("#automatic-langfuse")).toBeHidden();
    await selectCheckpoint(page, 105);
    await expect(page.locator("#automatic-langfuse")).toHaveAttribute("data-task", second.task_id);
  } finally {
    release();
  }
  await expect(page.locator("#automatic-langfuse")).toHaveAttribute("href", /2{32}$/);
  await page.locator("#investigation-technical > summary").click();
  await page.getByRole("button", { name: "View Langfuse run", exact: true }).click();
  await expect(page.locator("#trace-view")).toHaveAttribute("data-task", second.task_id);
  await page.getByRole("switch", { name: /Recorded results/ }).click();
  await expect(page.locator("#trace-view")).not.toHaveAttribute("data-task", second.task_id);
  await expect(page.locator("#trace-view")).not.toHaveAttribute("data-recorded");
  await page.getByRole("switch", { name: /Live investigation/ }).click();
  await expect(page.locator("#trace-view")).toHaveAttribute("data-task", second.task_id);
  await selectCheckpoint(page, 0);
  await expect(page.locator("#automatic-langfuse")).toBeHidden();
  await expect(page.locator("#trace-view")).not.toHaveAttribute("data-task");
  wrongScope = true;
  await selectCheckpoint(page, 105);
  await expect(page.locator("#automatic-trace-status")).toContainText("scope mismatch");
  await expect(page.locator("#automatic-langfuse")).toBeHidden();
  await expect(page.locator("#automatic-state")).toContainText("SUCCEEDED");
  expect(writes).toEqual([]);
});

test("empty recording timeline remains usable without substituting future results", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Requires local owned demo.");
  await page.request.post("/api/login", { data: {
    username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD,
  } });
  const { replays } = await (await page.request.get("/api/replays")).json();
  const replay = replays.find((row: { scenario: string }) => row.scenario === "S7");
  await page.route(`**/api/replays/${replay.id}/recordings`, route => route.fulfill({
    json: { base_playback_speed: 5, recordings: [] },
  }));
  await page.goto("/?replay=" + encodeURIComponent(replay.id));
  await expect(page.locator("#source-clock")).toContainText("RECORDED PAUSED");
  await selectCheckpoint(page, 120);
  await expect(page.locator("#topology")).toHaveAttribute("data-source-seconds", "120");
  await expect(page.locator("#channel-charts svg")).toHaveCount(1);
  await expect(page.locator("#automatic-state")).toContainText("awaiting first saved checkpoint");
  await expect(page.locator("#agent-investigation-map svg")).toHaveCount(0);
  await page.locator("#speed").selectOption("30");
  await page.getByRole("switch", { name: /Recorded results/ }).click();
  await expect(page.locator("#speed")).toHaveValue("30");
  await expect(page.locator("#speed")).toBeEnabled();
  await expect(page.locator("#step")).toHaveText("Forward 30s");
  await page.locator("#step").click();
  await expect(page.locator("#investigation-time-label")).toHaveText("+150s");
  await expect(page.locator("#topology")).toHaveAttribute("data-source-seconds", "150");
  await page.locator("#step-back").click();
  await expect(page.locator("#investigation-time-label")).toHaveText("+120s");
  await page.locator("#speed").selectOption("10");
  await expect(page.locator("#step")).toHaveText("Forward 10s");
  await page.locator("#step").click();
  await expect(page.locator("#investigation-time-label")).toHaveText("+130s");
  await page.locator("#step-back").click();
  await expect(page.getByRole("button", { name: "Run agents at +120s" })).toBeEnabled();
  await expect(page.locator("#automatic-state")).toContainText("no investigation at +120s");
  await page.getByRole("switch", { name: /Live investigation/ }).click();
  await expect(page.locator("#investigation-time-label")).toHaveText("+120s");
  await expect(page.locator("#agent-investigation-map svg")).toHaveCount(0);
});

test("recorded and fixed-time live views share sensor warnings without leaking stale assessments", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Requires local owned demo.");
  await page.request.post("/api/login", { data: {
    username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD,
  } });
  const { replays } = await (await page.request.get("/api/replays")).json();
  const replay = replays.find((row: { scenario: string; workflow: string }) =>
    row.scenario === "S7" && row.workflow === "agent_assisted");
  expect(replay).toBeDefined();
  const endpoint = `/api/replays/${replay.id}/timeline-window`;
  const hundred = await (await page.request.get(`${endpoint}?source_seconds=100`)).json();
  const sixty = await (await page.request.get(`${endpoint}?source_seconds=60`)).json();
  await page.goto("/?replay=" + encodeURIComponent(replay.id));
  await expect(page.locator("#step")).toBeEnabled();
  const banner = page.locator("#monitoring-warning");
  await expect(banner).toHaveAttribute("data-kind", "waiting");
  await expect(banner).toContainText("WARM-UP");
  await selectCheckpoint(page, 100);
  await expect(banner).toHaveAttribute("data-snapshot", hundred.snapshot.id);
  await expect(banner).toHaveAttribute("data-kind", hundred.warning.kind);
  await expect(banner).toHaveClass(`monitoring-warning ${hundred.warning.severity}`);
  await expect(banner).toContainText(`${hundred.warning.title}. ${hundred.warning.message}`);
  await expect(banner).toContainText("Recorded measurements · +100s");
  await page.getByRole("switch", { name: /Recorded results/ }).click();
  await expect(banner).toContainText(`${hundred.warning.title}. ${hundred.warning.message}`);
  await expect(banner).toHaveAttribute("data-snapshot", hundred.snapshot.id);
  await page.getByRole("switch", { name: /Live investigation/ }).click();
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/timeline-window?source_seconds=120", async route => {
    await gate; await route.continue();
  });
  await selectCheckpoint(page, 120);
  try {
    await expect(banner).toContainText("Loading sensor assessment");
    await expect(banner).toHaveAttribute("data-snapshot", "");
    await expect(banner).not.toContainText(hundred.warning.title);
    await selectCheckpoint(page, 60);
    await expect(banner).toHaveAttribute("data-snapshot", sixty.snapshot.id);
  } finally { release(); }
  await expect(banner).toHaveAttribute("data-kind", sixty.warning.kind);
  await expect(banner).toContainText(`${sixty.warning.title}. ${sixty.warning.message}`);
  await page.route("**/timeline-window?source_seconds=180", route => route.fulfill({
    status: 503, json: { detail: "Test-only measurements unavailable" },
  }));
  await selectCheckpoint(page, 180);
  await expect(banner).toHaveAttribute("data-kind", "unavailable");
  await expect(banner).toHaveAttribute("data-snapshot", "");
  await expect(banner).toContainText("Sensor assessment unavailable");
});

test("live override stops playback and requests a separate investigation at the selected point", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Requires local owned demo.");
  await page.request.post("/api/login", { data: {
    username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD,
  } });
  const { replays } = await (await page.request.get("/api/replays")).json();
  const replay = replays.find((row: { scenario: string; seed: number }) => row.scenario === "S7" && row.seed === 2026);
  await page.goto("/?replay=" + encodeURIComponent(replay.id));
  await expect(page.locator("#source-clock")).toContainText("RECORDED PAUSED", { timeout: 30000 });
  await selectCheckpoint(page, 120);
  await expect(page.locator("#automatic-state")).toHaveText(
    /RECORDED · (SUCCEEDED|ABSTAINED|FAILED) · evidence \+120s/,
  );
  const recordedTask = await page.locator("#automatic-state").getAttribute("data-task");
  const { recordings } = await (await page.request.get(`/api/replays/${replay.id}/recordings`)).json();
  const earlier = availableRecording(recordings, 100)!;
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route(`**/recordings/${earlier.task_id}`, async route => {
    await gate; await route.continue();
  });
  await selectCheckpoint(page, 100);
  try {
    await expect(page.locator("#agent-investigation-map")).toContainText("Previous findings withheld");
    await expect(page.locator("#agent-investigation-map svg")).toHaveCount(0);
    await expect(page.locator("#automatic-state")).not.toHaveAttribute("data-task");
  } finally { release(); }
  await expect(page.locator("#automatic-state")).toHaveAttribute("data-task", earlier.task_id);
  await selectCheckpoint(page, 120);
  await expect(page.locator("#automatic-state")).toHaveAttribute("data-task", recordedTask!);
  await page.getByRole("switch", { name: /Recorded results/ }).click();
  await expect(page.locator("#automatic-state")).toContainText("LIVE");
  const attempts: { source_seconds: number; idempotency_key: string }[] = [];
  await page.route("**/investigate-here", async route => {
    attempts.push(route.request().postDataJSON());
    await route.fulfill({ status: 503, contentType: "application/json",
      body: JSON.stringify({ detail: "Test-only provider unavailable" }) });
  });
  await page.getByRole("button", { name: "Run agents at +120s", exact: true }).click();
  await expect(page.locator("#notice")).toContainText("saved runs remain preserved");
  expect(attempts[0].source_seconds).toBe(120);
  expect(attempts[0].idempotency_key).toBeTruthy();
  await page.getByRole("button", { name: "Run agents at +120s", exact: true }).click();
  await expect.poll(() => attempts.length).toBe(2);
  expect(attempts[1]).toEqual(attempts[0]);
  await expect(page.locator("#source-clock")).not.toContainText("RECORDED PLAYING");
  await page.getByRole("switch", { name: /Live investigation/ }).click();
  await expect(page.locator("#source-clock")).toContainText("RECORDED PAUSED");
  await expect(page.locator("#investigation-time-label")).toHaveText("+120s");
  await expect(page.locator("#automatic-state")).toHaveAttribute("data-task", recordedTask!);
});

test("entering recorded walkthrough pauses live ingestion before local playback", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Requires local owned demo.");
  const login = await page.request.post("/api/login", { data: {
    username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD,
  } });
  const headers = { "X-CSRF-Token": (await login.json()).csrf_token };
  const created = await page.request.post("/api/replays", { headers, data: {
    scenario: "S7", seed: 2026, mode: "scripted", workflow: "sensor_alerts",
    idempotency_key: `playback-pause-test-${Date.now()}`,
  } });
  expect(created.status()).toBe(200);
  const replay = await created.json();
  const url = `/api/replays/${replay.id}`;
  expect((await page.request.post(`${url}/control`, { headers, data: {
    action: "play", idempotency_key: "play-once",
  } })).status()).toBe(200);
  await page.goto("/?replay=" + encodeURIComponent(replay.id));
  await expect(page.locator("#source-clock")).toContainText("RECORDED PAUSED", { timeout: 30000 });
  await expect.poll(async () => {
    const projection = await (await page.request.get(`${url}/projection`)).json();
    expect(projection.tasks).toEqual([]);
    return projection.replay.state;
  }).toBe("PAUSED");
  for (const speed of ["20", "30"]) {
    await page.locator("#speed").selectOption(speed);
    await expect(page.locator("#speed")).toHaveValue(speed);
    await page.getByRole("button", { name: "Play", exact: true }).click();
    await expect(page.locator("#source-clock")).toContainText("RECORDED PLAYING");
    await expect(page.locator("#source-clock")).toContainText(`${speed}×`);
    await page.getByRole("button", { name: "Pause", exact: true }).click();
    await expect(page.locator("#source-clock")).toContainText("RECORDED PAUSED");
  }
  expect((await (await page.request.get(`${url}/projection`)).json()).replay.state).toBe("PAUSED");
});

for (const delayed of ["measurements", "sensor", "investigation"] as const) {
test(`recorded playback waits for ${delayed} without skipping windows or catching up`, async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Requires local owned demo.");
  await page.request.post("/api/login", { data: {
    username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD,
  } });
  const { replays } = await (await page.request.get("/api/replays")).json();
  const replay = replays.find((row: { scenario: string; seed: number }) =>
    row.scenario === "S7" && row.seed === 2026);
  expect(replay).toBeDefined();
  await page.goto("/?replay=" + encodeURIComponent(replay.id));
  await expect(page.locator("#source-clock")).toContainText("RECORDED PAUSED", { timeout: 30000 });
  await selectCheckpoint(page, 105);
  await expect(page.locator("#step")).toBeEnabled();
  const { recordings } = await (await page.request.get(`/api/replays/${replay.id}/recordings`)).json();
  const next = availableRecording(recordings, 110)!;
  expect(next.source_seconds).toBe(110);
  let release!: () => void;
  let requested = false;
  const gate = new Promise<void>(resolve => { release = resolve; });
  const pattern = delayed === "measurements" ? "**/timeline-window?source_seconds=110"
    : delayed === "sensor" ? "**/api/windows/*/sensors/*" : `**/recordings/${next.task_id}`;
  await page.route(pattern, async route => {
    requested = true;
    await gate;
    await route.continue();
  });
  await page.clock.install();
  await page.clock.pauseAt(new Date(Date.now() + 1000));
  await page.locator("#speed").selectOption("30");
  await page.getByRole("button", { name: "Play", exact: true }).click();
  try {
    await page.clock.fastForward(2000);
    await expect.poll(() => requested).toBe(true);
    await expect(page.locator("#source-clock")).toHaveAttribute("data-seconds", "110");
    await expect(page.locator("#clock-basis")).toContainText("Waiting for");
    await expect(page.locator("#step")).toBeDisabled();
    await page.clock.fastForward(10000);
    await expect(page.locator("#source-clock")).toHaveAttribute("data-seconds", "110");
  } finally {
    release();
  }
  await expect(page.locator("#clock-basis")).toContainText("Load-aware");
  await expect(page.locator("#topology")).toHaveAttribute("data-source-seconds", "110");
  const snapshot = await page.locator("#topology").getAttribute("data-snapshot");
  await expect(page.locator("#channel-charts")).toHaveAttribute("data-snapshot", snapshot!);
  await expect(page.locator("#automatic-state")).toHaveAttribute("data-task", next.task_id);
  await page.clock.fastForward(250);
  await expect(page.locator("#source-clock")).toHaveAttribute("data-seconds", "115");
  await page.getByRole("button", { name: "Pause", exact: true }).click();
  const paused = await page.locator("#source-clock").getAttribute("data-seconds");
  await page.clock.fastForward(5000);
  await expect(page.locator("#source-clock")).toHaveAttribute("data-seconds", paused!);
});
}

test("starting a new run stays live despite compatible saved checkpoints", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Requires local owned demo.");
  await page.request.post("/api/login", { data: {
    username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD,
  } });
  await page.goto("/");
  await page.locator("#scenario").selectOption("S7");
  await page.locator("#workflow").selectOption("sensor_alerts");
  await page.locator("#create-replay").click();
  await expect(page.locator("#notice")).toContainText("New generation created", { timeout: 30000 });
  await expect(page.locator("#source-clock")).not.toContainText("RECORDED");
  await expect(page.locator("#investigate-live-here")).toBeDisabled();
  await expect(page.locator(".live-grid")).toBeVisible();
  await expect(page.locator("#play")).toBeEnabled({ timeout: 30000 });
  await expect(page.locator("#source-clock")).not.toContainText("RECORDED");
});

test("paused recordings step backward and forward without changing the saved source", async ({ page }) => {
  test.skip(!process.env.SUBSEA_OPERATOR_PASSWORD, "Requires local owned demo.");
  const login = await page.request.post("/api/login", { data: {
    username: "operator", password: process.env.SUBSEA_OPERATOR_PASSWORD,
  } });
  const headers = { "X-CSRF-Token": (await login.json()).csrf_token };
  const replay = await (await page.request.post("/api/replays", { headers, data: {
    scenario: "S7", seed: 2026, mode: "scripted", workflow: "sensor_alerts",
    idempotency_key: `paused-navigation-${Date.now()}`,
  } })).json();
  const writes: string[] = [];
  page.on("request", request => { if (request.method() === "POST") writes.push(request.url()); });
  await page.goto("/?replay=" + encodeURIComponent(replay.id));
  const back = page.locator("#step-back");
  const forward = page.locator("#step");
  await expect(forward).toBeEnabled();
  await expect(back).toBeDisabled();
  await forward.click();
  await expect(page.locator("#source-clock")).toHaveAttribute("data-seconds", "5");
  await expect(page.locator("#topology")).toHaveAttribute("data-source-seconds", "5");
  await back.click();
  await expect(page.locator("#source-clock")).toHaveAttribute("data-seconds", "0");
  await expect(back).toBeDisabled();
  for (const speed of [5, 10, 20, 30]) {
    await page.locator("#speed").selectOption(String(speed));
    await expect(back).toHaveText(`Back ${speed}s`);
    await expect(forward).toHaveText(`Forward ${speed}s`);
    await selectCheckpoint(page, 100);
    await forward.click();
    await expect(page.locator("#source-clock")).toHaveAttribute("data-seconds", String(100 + speed));
    await back.click();
    await expect(page.locator("#source-clock")).toHaveAttribute("data-seconds", "100");
  }
  await selectCheckpoint(page, 360);
  await expect(forward).toBeDisabled();
  await back.click();
  await expect(page.locator("#source-clock")).toHaveAttribute("data-seconds", "330");
  await selectCheckpoint(page, 100);
  await page.getByRole("button", { name: "Play", exact: true }).click();
  await expect(back).toBeDisabled();
  await expect(forward).toBeDisabled();
  await page.getByRole("button", { name: "Pause", exact: true }).click();
  await expect(back).toBeEnabled();
  await expect(forward).toBeEnabled();
  const projection = await (await page.request.get(`/api/replays/${replay.id}/projection`)).json();
  expect(projection.replay.clock_seconds).toBe(0);
  expect(projection.tasks).toEqual([]);
  expect(writes).toEqual([]);
});
