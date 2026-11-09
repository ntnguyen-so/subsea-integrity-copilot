"""Generate the brief's geometry and example evidence from the running domain code."""

# Offline source-of-truth exporter: seed 2026 S1/S2, a 140s endpoint with 145s receive
# cutoff, and the current generated pack. Overwrites packs/northsea.json and the brief
# fixture consumed by render-topology.cjs; no database/inference. Reproducible for the
# same domain code, so rerun after numerical changes rather than edit figure numbers.
import json
from datetime import timedelta
from pathlib import Path

from subsea_copilot.diagnostics import analyze_window
from subsea_copilot.ingest import normalize_records
from subsea_copilot.synthetic import SOURCE_VERSION, generate_pack, generate_scenario


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    pack = generate_pack()
    (root / "packs" / "northsea.json").write_text(
        pack.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    examples = {}
    for scenario in ("S1", "S2"):
        source = generate_scenario(scenario, 2026, 180)
        rows = normalize_records(source.records, source.pack)
        snapshot = analyze_window(
            source.pack,
            normalize_records(source.baseline, source.pack),
            rows,
            f"brief-{scenario}",
            140,
            145,
            source.epoch,
        )
        selected = (
            snapshot.event.supporting_sensor_ids[:3]
            if scenario == "S1"
            else ["P2-ST2-A", "P3-ST3-A", "P1-ST2-A"]
        )
        examples[scenario] = {
            "snapshot": snapshot.model_dump(mode="json"),
            "window_start_seconds": (snapshot.window_start - source.epoch).total_seconds(),
            "window_end_seconds": (snapshot.window_end - source.epoch).total_seconds(),
            # The plot uses the snapshot's half-open observed-time bounds and receive
            # cutoff. Unusable records become null gaps, never interpolated pressure.
            "traces": {
                sensor: [
                    {
                        "seconds": (row.observed_at - source.epoch).total_seconds(),
                        "value": row.value if row.validity == "usable" else None,
                    }
                    for row in sorted(rows, key=lambda row: row.observed_at)
                    if row.sensor_id == sensor
                    and snapshot.window_start <= row.observed_at < snapshot.window_end
                    and row.received_at <= source.epoch + timedelta(seconds=145)
                ]
                for sensor in selected
            },
        }
    destination = root / "fixtures" / "synthetic" / "brief-evidence.json"
    destination.write_text(
        json.dumps(
            {
                "source_version": SOURCE_VERSION,
                "pack_version": pack.version,
                "seed": 2026,
                "examples": examples,
            },
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print("Exported brief geometry and two scoped pressure examples.")


if __name__ == "__main__":
    main()
