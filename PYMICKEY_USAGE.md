# Pymickey Usage Guide

Declarative HTTP API testing framework using YAML scenarios.

## Running Tests

```bash
# With CLI-specified env file
pymickey test_suite.mickey.yaml --env env.mickey.yaml

# Or using config-defined env file
pymickey test_suite.mickey.yaml
```

## File Structure

```
project/
├── env.mickey.yaml              # Environment variables (credentials, URLs)
├── pymickey_tests/
│   └── endpoints/
│       └── feature/
│           └── test_feature.mickey.yaml
```

## Environment File

```yaml
# env.mickey.yaml
base_url: "https://api.example.com"
email: "test@example.com"
password: "secret123"
```

## Test Suite Structure

```yaml
config:
  env_file: "../../env.mickey.yaml"   # Relative path from test file
  # OR multiple files (merged in order):
  # env_files:
  #   - "base.mickey.yaml"
  #   - "local.mickey.yaml"

  timeout: 10.0                       # Request timeout in seconds (default: 10.0)

  default_headers:                    # Applied to all requests without explicit headers
    Content-Type: "application/json"
    Authorization: "Bearer {{ access_token }}"

  auth:                               # Optional: runs before all tests
    login:
      name: "Login"
      set:                            # Optional: define variables before login request
        login_timestamp: "{{ randint(1000, 9999) }}"
      request:
        method: POST
        url: "{{ base_url }}/api/auth/login/"
        headers: {}                   # Empty to skip default_headers (no token yet)
        json:
          email: "{{ email }}"
          password: "{{ password }}"
      expect:
        status: 200
      extract:
        access_token: "json.data.access"
      echo: false                     # Optional: print response for debugging

tests:
  - name: "Test Name"
    demand: ["access_token"]          # Skip test if variables missing
    skip: false                       # Or skip: "reason string"
    set:                              # Define variables before steps run
      test_var: "value"
    steps:
      - name: "Step 1"
        # ... step definition
```

## Step Definition

```yaml
steps:
  - name: "Create Resource"

    # Skip this step
    skip: false                       # Or: "Reason to skip"

    # Define variables before request
    set:
      random_id: "{{ randint(1000, 9999) }}"
      timestamp: "{{ randweekday }}"

    # Required variables (skip if missing)
    demand: ["access_token", "tenant_id"]

    # HTTP Request
    request:
      method: POST                    # GET, POST, PUT, PATCH, DELETE
      url: "{{ base_url }}/api/resources/"
      headers:                        # Optional: overrides default_headers
        Authorization: "Bearer {{ access_token }}"
      params:                         # Query parameters
        page: 1
        search: "test"
      json:                           # JSON body
        name: "Resource {{ random_id }}"
        type: "example"
      # OR form data:
      # data:
      #   field: "value"

    # Response validation
    expect:
      status: 200                     # Single status or list: [200, 201]
      json:
        has_keys: ["data", "message"]
        field_equals:
          message: "Success"
          data.status: "active"       # Nested paths supported
          data.items[0].id: 123       # Array indexing supported
        list_len_gte:
          items: 1                    # List at root level must have >= 1 elements

    # Extract values for subsequent steps
    extract:
      resource_id: "json.data.id"
      resource_uid: "json.data.items[0].uid"
      status_code: "status"
      auth_header: "header.Authorization"

    # Debug: print full request/response
    echo: true
    # Outputs: Request (method, URL), Status, Headers, Body (JSON formatted if applicable)
```

## Template Syntax

Variables use `{{ variable_name }}` syntax:

```yaml
url: "{{ base_url }}/api/users/{{ user_id }}/"
json:
  token: "{{ access_token }}"
```

### Built-in Functions

| Function | Usage | Result |
|----------|-------|--------|
| `randint(min, max)` | `{{ randint(100, 999) }}` | Random integer |
| `randweekday` | `{{ randweekday }}` | Current weekday ("Mon", "Tue", ...) |
| `randmonth` | `{{ randmonth }}` | Current month ("Jan", "Feb", ...) |

## Expect Validations

### Status Code

```yaml
expect:
  status: 200           # Exact match
  # OR
  status: [200, 201]    # Any of these
```

### JSON Assertions

```yaml
expect:
  json:
    # Check keys exist at root level
    has_keys: ["data", "message", "success"]

    # Check field values (supports nested paths)
    field_equals:
      success: true
      message: "Created"
      data.status: "active"
      data.user.role: "admin"
      data.items[0].type: "default"

    # Check list minimum length (root-level fields only)
    list_len_gte:
      data: 1                    # len(body["data"]) >= 1
      items: 5                   # len(body["items"]) >= 5
```

## Extract Patterns

```yaml
extract:
  # From JSON body (prefix: json.)
  user_id: "json.data.id"
  first_item: "json.items[0]"
  nested_value: "json.data.nested.field"

  # Direct array access (when response is an array)
  first_element: "json[0]"
  first_name: "json[0].name"

  # From HTTP status
  status_code: "status"

  # From response headers (prefix: header.)
  token: "header.X-Auth-Token"
  content_type: "header.Content-Type"
```

## Control Flow

### Test-level Set

Define variables before any steps run:

```yaml
tests:
  - name: "Test with variables"
    set:
      base_id: "{{ randint(1000, 9999) }}"
      test_name: "Test-{{ randint(1, 100) }}"
    steps:
      - name: "Use test variables"
        request:
          url: "{{ base_url }}/api/items/{{ base_id }}/"
```

### Skip Rules

```yaml
# Skip entire test
tests:
  - name: "Disabled Test"
    skip: true
    # OR with reason:
    skip: "API not ready yet"

# Skip single step
steps:
  - name: "Optional Step"
    skip: "{{ some_condition }}"
```

### Demand (Conditional Execution)

```yaml
# Test-level: skip all steps if variables missing
tests:
  - name: "Authenticated Test"
    demand: ["access_token"]
    steps: [...]

# Step-level: skip this step if variables missing
steps:
  - name: "Use Tenant"
    demand: ["tenant_id", "plan_id"]
    request: ...
```

## Execution Order

### Test Execution Order
1. Check `skip:` rule (skip entire test if true)
2. Check `demand:` (skip entire test if variables missing)
3. Apply `set:` variables to context
4. Run steps sequentially

### Step Execution Order
1. Check `skip:` rule
2. Apply `set:` variables to context
3. Check `demand:` (skip step if variables missing)
4. Render request template with variable substitution
5. Execute HTTP request
6. Print response if `echo: true`
7. Validate `expect:` assertions
8. Extract variables with `extract:`

## Complete Example

```yaml
config:
  env_file: "../../env.mickey.yaml"

  default_headers:
    Content-Type: "application/json"
    Authorization: "Bearer {{ access_token }}"

  auth:
    login:
      name: "Authenticate"
      request:
        method: POST
        url: "{{ base_url }}/api/auth/login/"
        headers: {}
        json:
          email: "{{ email }}"
          password: "{{ password }}"
      expect:
        status: 200
        json:
          has_keys: ["data"]
      extract:
        access_token: "json.data.access"

tests:
  - name: "CRUD Operations"
    demand: ["access_token"]
    set:
      test_suffix: "{{ randint(1000, 9999) }}"

    steps:
      - name: "Create item"
        set:
          item_name: "Test Item {{ test_suffix }}"
        request:
          method: POST
          url: "{{ base_url }}/api/items/"
          json:
            name: "{{ item_name }}"
        expect:
          status: 201
          json:
            has_keys: ["data"]
            field_equals:
              data.name: "{{ item_name }}"
        extract:
          item_id: "json.data.id"

      - name: "Read item"
        demand: ["item_id"]
        request:
          method: GET
          url: "{{ base_url }}/api/items/{{ item_id }}/"
        expect:
          status: 200
          json:
            field_equals:
              data.id: "{{ item_id }}"

      - name: "Update item"
        demand: ["item_id"]
        request:
          method: PATCH
          url: "{{ base_url }}/api/items/{{ item_id }}/"
          json:
            name: "Updated Name"
        expect:
          status: 200

      - name: "Delete item"
        demand: ["item_id"]
        request:
          method: DELETE
          url: "{{ base_url }}/api/items/{{ item_id }}/"
        expect:
          status: [200, 204]
```

## Result Statuses

| Status | Meaning |
|--------|---------|
| OK | Step passed all validations |
| FAIL | Assertion failed (status, json validation) |
| SKIP | Skipped due to `skip: true` or unmet `demand` |
| ERROR | Exception (network error, invalid template, etc.) |

Exit code is `1` if any FAIL or ERROR, otherwise `0`.

## Tips

1. **Empty headers to skip defaults**: Use `headers: {}` in auth login to avoid sending Authorization header before you have a token

2. **Relative env paths**: `env_file` paths are relative to the test file location

3. **Debug with echo**: Add `echo: true` to any step to see full request/response details

4. **Chain extractions**: Extract values in one step, use them in subsequent steps via `{{ variable }}`

5. **Nested field_equals**: Use dot notation for nested objects: `data.user.email: "test@example.com"`

6. **Array access**: Use bracket notation: `data.items[0].id` or `json[0].name` for direct array access

7. **Test-level set**: Use `set:` at test level to define variables shared across all steps in that test

8. **list_len_gte limitation**: Only works with root-level fields, not nested paths
