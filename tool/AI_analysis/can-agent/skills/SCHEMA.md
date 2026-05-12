# can-agent skills schema

This folder configures *domain rules* and *domain knowledge* that can-agent uses to guide anomaly detection and AI explanation.

## Directory layout

- `skills/**/rules.yaml|rules.yml|rules.json`
- `skills/**/knowledge.txt` (optional)
- `skills/**/*.knowledge.txt` (optional)
- `skills/**/*.md` (optional; treated as knowledge text)

## Rules format

A rules file contains either:
- a list of rule objects (recommended), or
- a single rule object

### Normalized schema (preferred)

```yaml
- id: ccu_temp_warning
  name: "CCU温度预警"
  target:
    signal: CCUTCooltInlet
    # can_id: 123          # optional
  trigger:
    condition: "> 60 or <= -40"
    min_points: 2          # optional; consecutive points required
  severity: high           # optional; default high
  context_signals:         # optional; for AI context
    - OBCModSts
    - OBCFltFlg
```

### Backward-compatible fields

These are accepted and will be normalized:

- `skill_name` -> `name`
- `signal_name` -> `target.signal`
- top-level `signal` -> `target.signal`
- top-level `can_id` -> `target.can_id`

### trigger.condition expression

`condition` is evaluated against a single variable: `value`.

Supported operators:
- comparisons: `> >= < <= == !=`
- boolean ops: `and or not` and parentheses
- membership: `in` / `not in` with list/tuple literals

Examples:
- `"> 60 or <= -40"`
- `"value in [0, 1, 2]"`
- `"not (value >= 0 and value <= 4)"`

Notes:
- Shorthand comparisons like `"> 60"` are supported and treated as `"value > 60"`.
- Expressions are parsed with a restricted AST whitelist (no function calls).
