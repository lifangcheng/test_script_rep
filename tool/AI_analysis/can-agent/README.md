# CAN Agent CLI

## 新增特性（whitelist/skills/AI per-anomaly）
- 新增 CLI：`--skills-dir`（技能目录），`--slice-window-sec`，`--slice-format`。
- 配置 schema 扩展：`skills/whitelist/slice(min_points)/fallback/ai`。
- 新增节点 `load_skills`：递归加载 `rules.*` 与 `knowledge.*`，生成白名单，注入规则/知识。
- BLF/DBC 解码支持白名单过滤，降低大文件内存占用。
- `anomaly_detect` 输出带窗口切片（至少 5 点，不足则 2s 窗口），上下文写入 `anomalies` + `slices`。
- `ai_analyze` 逐异常调用，注入 knowledge + 切片上下文，产出 `ai_report.json`；`report.html/json` 合并 AI 分析区块。
- 兜底规则参数：`fallback.variance_z`、`timeout_multiplier`、`uds_service_ids`、`keyword_signals`。

## CLI 示例
```bash
python start_can_agent.py cli \
  --blf ".../Test_2026-02-26_19-35-24.blf" \
  --dbc ".../MS12&MS13_EDCU_PTCANFD_251301.dbc" \
  --out outputs \
  --skills-dir skills/powertrain \
  --slice-window-sec 2.0 \
  --slice-format csv \
  --ai
```

## 配置片段 (YAML)
```yaml
skills:
  dir: "skills"
  allow_missing: true
whitelist:
  can_ids: [0x123, 0x456]
  signals: [BattU, Speed]
  enforce: false
slice:
  window_sec: 2.0
  format: csv
  max_rows: 500
  min_points: 5
fallback:
  variance_z: 6.0
  timeout_multiplier: 3.0
  uds_service_ids: [0x19]
  keyword_signals: ["flt", "warn", "status"]
ai:
  enabled: false
  system_prompt: ""
  user_prompt: ""
```

## 输出
- `report.json` / `report.html`（含 AI 区块）、`ai_report.json`、`diagnosis.json`、`signals/`、`status.json`、`graph.html`。

## 技能目录
- 支持多层递归：`rules.yaml|yml|json` 或 `*.rules.*`；知识 `knowledge.txt|*.knowledge.txt|*.md`，按目录聚合。
