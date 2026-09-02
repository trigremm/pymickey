# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Pymickey is a minimal declarative HTTP API testing tool that uses YAML scenarios. It executes sequential HTTP requests with template variable substitution and validates responses.

## Commands

```bash
# Run a test suite
pymickey test_suite.mickey.yaml --env env.mickey.yaml

# Skip interactive prompts (for CI)
pymickey test_suite.mickey.yaml --no-interactive

# Alternative runner (direct execution)
python -m pymickey.runner test_suite.mickey.yaml --env env.mickey.yaml

# Format code
make format   # or: make f
```

## Architecture

### Core Module: `pymickey/runner.py`

This is the main orchestration module. Key functions:

- **`main()`**: Entry point - parses CLI args, loads YAML files, runs suite
- **`run_suite()`**: Executes all tests, manages httpx.Client and authentication
- **`run_step()`**: Executes a single step - request, expect, extract lifecycle
- **`render_value()`**: Recursively processes `{{ variable }}` templates in strings/dicts/lists
- **`extract_vars()`**: Extracts values from responses into context (`status`, `header.X-Token`, `json.path[0].field`)
- **`apply_expect()`**: Validates response against expectations

### Template System

- Pattern: `{{ variable }}` or `{{ function(args) }}`
- Built-in functions: `randint(min, max)`, `randweekday()`, `randmonth()`
- JSON path navigation supports array indexing: `items[0].uid`

### Step Execution Order

1. Skip rule check (`skip:`)
2. Set variables (`set:`)
3. Interactive prompt (`prompt:`) — asks user for input, skips in non-interactive mode
4. Demand validation (`demand:`)
5. Template render request
6. Execute HTTP request
7. Echo response if enabled (`echo: true`)
8. Validate expectations (`expect:`)
9. Extract variables (`extract:`)

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
        prompt:                      # interactive input (skipped in CI)
          code: "Enter verification code"
        request:
          method: GET
          url: "/endpoint"
          json: {}
          files: {}              # multipart upload, see PYMICKEY_USAGE.md
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
