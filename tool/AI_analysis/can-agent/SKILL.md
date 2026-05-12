---
name: can-agent
description: |
  Analyze automotive CAN BLF logs with a DBC using the can-agent pipeline, generate report.html/report.json, and optionally batch-run a folder of BLFs. Use this whenever the user asks to decode BLF/CAN logs, detect anomalies (rule_trigger/period_deviation/missing/spike/freeze), update rules.yaml, or summarize CAN analysis outputs.
---

Run the can-agent pipeline in this repo to decode BLF with a DBC, detect anomalies (including skills/default/rules.yaml conditions), and generate reports.

## Preferred workflows

### 1) Single BLF analysis
- Use `py -3.13`.
- Run:
  - `py -3.13 cli.py --blf "<blf>" --dbc "<dbc>" --out "<out_dir>" --skills-dir "skills"`
- Then open:
  - `<out_dir>/report.html`
  - `<out_dir>/report.json`

### 2) Batch analyze a folder of BLFs
- For a folder containing many `*.blf`, **do not use app/main or any LangGraph server**. Just loop the CLI.
- Example:
  - `for f in "/c/Users/lifangcheng/Downloads/log/log"/*.blf; do py -3.13 cli.py --blf "$f" --dbc "MS12&MS13_EDCU_PTCANFD_251301.dbc" --out "outputs/batch" --skills-dir "skills"; done`
- Each run will write to:
  - `outputs/batch/<blf_basename>/` and also `outputs/batch/<blf_basename>/artifacts/`
- Produce a short summary:
  - how many succeeded
  - how many failed (and why, from `artifacts/status.json`)
  - top anomaly kinds/signals observed

### 3) Rules-driven analysis
- Rules live in `skills/**/rules.yaml`.
- If rules are invalid, the pipeline should fail in `load_skills` with `skills_invalid`.
- For “communication quality” rules (scheme A): do not create new `rule_trigger`; only attach rule metadata to period_deviation/missing/spike anomalies.

## Output expectations
- Reports must use UTC (`start_iso`/`end_iso` with trailing `Z`).
- CAN ID should be shown as hex only (`can_id_hex`), not decimal.
- Each anomaly row should include rule linkage when available (`rule_id`, `rule_name`, `rule_condition`, `rule_source`).

## When unsure
- Prefer running the smallest repro (one BLF) before batch runs.
- If tests are relevant, run:
  - `py -3.13 -m pytest -q tests/test_anomaly.py tests/test_anomaly_rules.py`
