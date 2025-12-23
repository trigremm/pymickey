# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Pymickey is a minimal declarative HTTP API testing tool that uses YAML scenarios. It executes sequential HTTP requests with template variable substitution and validates responses.

## Commands

```bash
# Run a test suite
pymickey test_suite.mickey.yaml --env env.mickey.yaml

# Alternative runner (direct execution)
python runner.py test_suite.mickey.yaml --env env.mickey.yaml

# Format code
make format   # or: make f
```

## Architecture

### Core Module: `pymickey/runner.py`

This is the main orchestration module (~560 lines). Key functions:

- **`main()`** (line 509): Entry point - parses CLI args, loads YAML files, runs suite
- **`run_suite()`** (line 405): Executes all tests, manages httpx.Client and authentication
- **`run_step()`** (line 254): Executes a single step - request, expect, extract lifecycle
- **`render_value()`** (line 97): Recursively processes `{{ variable }}` templates in strings/dicts/lists
- **`extract_vars()`** (line 230): Extracts values from responses into context (`status`, `header.X-Token`, `json.path[0].field`)
- **`apply_expect()`** (line 204): Validates response against expectations

### Template System

- Pattern: `{{ variable }}` or `{{ function(args) }}`
- Built-in functions (lines 34-57): `randint(min, max)`, `randweekday()`, `randmonth()`
- JSON path navigation supports array indexing: `items[0].uid`

### Step Execution Order

1. Skip rule check (`skip:`)
2. Set variables (`set:`)
3. Demand validation (`demand:`)
4. Template render request
5. Execute HTTP request
6. Echo response if enabled (`echo: true`)
7. Validate expectations (`expect:`)
8. Extract variables (`extract:`)

### YAML Structure

```yaml
config:
  base_url: "{{ base_url }}"
  timeout: 10.0
  default_headers: {}
  env_file: "env.mickey.yaml"    # or env_files: []
  auth:
    login:
      request: {}
      extract: {}

tests:
  - name: "Test Name"
    demand: [required_var]       # skip test if var missing
    skip: false                  # or "reason string"
    steps:
      - name: "Step Name"
        set:
          var: "value"
        request:
          method: GET
          url: "/endpoint"
          json: {}
        expect:
          status: 200            # or [200, 201]
          json:
            field_equals: {}
            has_keys: []
            list_len_gte: {}
        extract:
          token: "json.data.token"
          code: "status"
```

### Result Statuses

- `OK` - Step passed
- `FAIL` - Assertion failure
- `SKIP` - Skipped (skip rule or unmet demand)
- `ERROR` - Exception during execution

Exit code is 1 if any FAIL or ERROR, otherwise 0.
