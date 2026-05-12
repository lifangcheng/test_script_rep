# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

can-agent is a CAN (Controller Area Network) log analysis and diagnosis tool for automotive applications. It reads BLF (Vector Binary Log Format) files, decodes CAN signals using DBC (CAN database) files, detects anomalies, and optionally provides AI-based analysis and diagnosis.

## Core Commands

### Main Entry Points

1. **Start can-agent (with virtual environment management)**:
   ```bash
   python start_can_agent.py cli --blf "path/to/file.blf" --dbc "path/to/file.dbc" --out outputs
   ```

2. **Enable AI analysis (requires AI service)**:
   ```bash
   python start_can_agent.py cli --blf "file.blf" --dbc "file.dbc" --out outputs --ai
   ```

3. **Quick test (no BLF file)**:
   ```bash
   python start_can_agent.py quick-test
   ```

4. **Start FastAPI service**:
   ```bash
   python start_can_agent.py api --port 8000
   ```

5. **Direct CLI (without virtual environment management)**:
   ```bash
   python cli.py --blf "file.blf" --dbc "file.dbc" --out outputs --ai=false
   ```

### Testing and Verification

1. **Quick validation**:
   ```bash
   python quick_test.py
   ```

2. **Debug testing**:
   ```bash
   python debug_test.py "file.blf" "file.dbc"
   ```

3. **Test run with sample data**:
   ```bash
   python test_run.py
   ```

4. **Run all pytest tests**:
   ```bash
   python -m pytest tests/
   ```

5. **Run specific test**:
   ```bash
   python -m pytest tests/test_diagnosis.py -v
   ```

## Architecture and Data Flow

The project uses LangGraph to build a state machine pipeline with these nodes (see `graph/builder.py`):

1. **validate_input** - Validate input files
2. **load_skills** - Load skills (rules and knowledge)
3. **parse_blf** - Parse BLF file (`core/blf_reader.py`)
4. **decode_dbc** - Decode signals using DBC file (`core/dbc_decoder.py`)
5. **build_dataframe** - Build Pandas DataFrame
6. **anomaly_detect** - Detect anomalies
7. **summarize** - Generate data summary
8. **report_generate** - Generate reports
9. **signal_index** - Create signal index
10. **ai_analyze** - AI analysis (optional, requires AI service)

The state is managed by `CANState` class in `graph/state.py`.

## Directory Structure

- `start_can_agent.py` - Main entry point with virtual environment management
- `cli.py` - CLI tool for BLF analysis
- `app/main.py` - FastAPI service entry
- `app/task_store.py` - Task storage for the API
- `core/` - Core modules:
  - `ai_client.py` - AI service client for chat completions
  - `ai_analyzer.py` - AI analysis orchestration
  - `blf_reader.py` - BLF file reader
  - `dbc_decoder.py` - DBC file decoder
  - `dataframe.py` - DataFrame utilities
  - `diagnosis.py` - Diagnosis report builder
  - `pipeline.py` - Core processing pipeline
  - `signals.py` - Signal processing utilities
  - `types.py` - Type definitions
- `graph/` - LangGraph nodes:
  - `builder.py` - Build the processing graph
  - `state.py` - CAN state management
  - `nodes/` - Individual graph nodes (e.g., `parse_blf.py`, `decode_dbc.py`)
- `config/` - Configuration:
  - `loader.py` - YAML configuration loader
  - `schema.py` - Pydantic schema definitions
  - `ai_strict.yaml` - AI configuration example
- `utils/` - Utilities:
  - `io.py` - I/O utilities
  - `logging.py` - Logging setup
- `tests/` - Test files
- `skills/` - Skills directory for rules and knowledge
- `frontend/` - Frontend interface (served by FastAPI)
- `outputs/` - Default output directory (ignored by git)

## Configuration

### Default Configuration
Defaults are defined in `config/schema.py` and `config/loader.py`.

### Custom Configuration
Provide a YAML configuration file:
```bash
python start_can_agent.py cli --blf file.blf --dbc file.dbc --config config/ai_strict.yaml
```

### AI Configuration Example (`config/ai_strict.yaml`):
```yaml
ai:
  base_url: "http://model.mify.ai.srv"
  model: "deepseek-v3.1"
  api_key: "sk-HXFiS9bEeg95uypM96B6kJfKaxe3ze52FUeQEriGGaGIIefS"
  timeout_s: 90
  system_prompt: |
    You are an expert automotive CAN log analyst.
    Respond with one valid JSON object only.
    Do not include markdown, code fences, or any extra text.
```

## Skills System

The skills system provides domain-specific rules and knowledge for anomaly detection:

1. **Rules** - Defined in YAML files (e.g., `skills/default/rules.yaml`):
   ```yaml
   - id: ccu_temp_warning
     skill_name: "CCU温度预警"
     signal: "CCUTCooltInlet"
     trigger:
       signal: "CCUTCooltInlet"
       condition: "> 60 or <= -40"
   ```

2. **Knowledge** - Provided in text files (`*.knowledge.txt` or `*.md`)

3. **Usage**:
   ```bash
   python start_can_agent.py cli --blf file.blf --dbc file.dbc --skills-dir skills/default
   ```

## Output Files

Analysis generates these files in the specified output directory:

1. `status.json` - Processing status and error logs
2. `decoded.parquet` - Decoded signal data (Pandas DataFrame format)
3. `anomalies.json` - Detected anomalies with details
4. `ai_report.md` - AI analysis report (if AI enabled)
5. `report.json` / `report.html` - Comprehensive reports
6. `diagnosis.json` - Diagnosis summary
7. `signals/` - Directory with signal-specific data

## Key Files and Paths

- Main entry: `start_can_agent.py` (manages virtual environment and execution modes)
- CLI entry: `cli.py` (direct command-line interface)
- API entry: `app/main.py` (FastAPI service)
- Graph builder: `graph/builder.py` (builds processing pipeline)
- State management: `graph/state.py` (CANState class)
- Core modules: All in `core/` directory
- Configuration: `config/loader.py` and `config/schema.py`

## Notes for Development

- The project uses virtual environment management automatically via `start_can_agent.py`
- AI analysis requires a running AI service (default: `http://model.mify.ai.srv`)
- BLF parsing requires `python-can` library
- DBC decoding requires `cantools` library
- Output directory (`outputs/`) is ignored by git
- See `USAGE_GUIDE.md` for troubleshooting and detailed usage