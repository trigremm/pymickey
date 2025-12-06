#!/usr/bin/env python
import sys
import re
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import httpx
import yaml


@dataclass
class StepResult:
    test_name: str
    step_name: str
    status: str  # "OK", "FAIL", "SKIP", "ERROR"
    message: str = ""


def load_suite(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


VAR_PATTERN = re.compile(r"{{\s*(\w+)\s*}}")


def render_value(value: Any, ctx: Dict[str, Any]) -> Any:
    """Рекурсивно подставляем {{var}} в строках."""
    if isinstance(value, str):
        def repl(match: re.Match) -> str:
            var = match.group(1)
            if var not in ctx:
                raise KeyError(f"Variable '{var}' is not defined in context")
            return str(ctx[var])

        return VAR_PATTERN.sub(repl, value)
    elif isinstance(value, dict):
        return {k: render_value(v, ctx) for k, v in value.items()}
    elif isinstance(value, list):
        return [render_value(v, ctx) for v in value]
    else:
        return value


def check_demand(demand: List[str], ctx: Dict[str, Any]) -> Optional[str]:
    missing = [name for name in demand if ctx.get(name) is None]
    if missing:
        return f"Demand not satisfied, missing variables: {', '.join(missing)}"
    return None


def assert_status(expected: Union[int, List[int]], actual: int) -> Optional[str]:
    if isinstance(expected, int):
        if actual != expected:
            return f"Expected status {expected}, got {actual}"
    else:
        if actual not in expected:
            return f"Expected status in {expected}, got {actual}"
    return None


def get_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"Response is not JSON: {e}")


def json_field_equals(body: Any, mapping: Dict[str, Any]) -> Optional[str]:
    if not isinstance(body, dict):
        return "Expected JSON object at root for 'field_equals'"
    for field, expected in mapping.items():
        if field not in body:
            return f"Expected field '{field}' in JSON"
        if body[field] != expected:
            return f"Field '{field}' mismatch: expected {expected!r}, got {body[field]!r}"
    return None


def json_has_keys(body: Any, keys: List[str]) -> Optional[str]:
    if not isinstance(body, dict):
        return "Expected JSON object at root for 'has_keys'"
    for k in keys:
        if k not in body:
            return f"Expected key '{k}' in JSON root"
    return None


def apply_expect(expect: Dict[str, Any], resp: httpx.Response) -> Optional[str]:
    # status
    if "status" in expect:
        msg = assert_status(expect["status"], resp.status_code)
        if msg:
            return msg

    if "json" in expect:
        body = get_json(resp)
        jexp = expect["json"]
        if "field_equals" in jexp:
            msg = json_field_equals(body, jexp["field_equals"])
            if msg:
                return msg
        if "has_keys" in jexp:
            msg = json_has_keys(body, jexp["has_keys"])
            if msg:
                return msg

    return None


def extract_vars(extract: Dict[str, str], resp: httpx.Response, ctx: Dict[str, Any]) -> None:
    body: Any = None
    for name, expr in extract.items():
        if expr == "status":
            ctx[name] = resp.status_code
            continue
        if expr.startswith("header."):
            header_name = expr.split(".", 1)[1]
            ctx[name] = resp.headers.get(header_name)
            continue
        if expr.startswith("json."):
            if body is None:
                body = get_json(resp)
            path = expr.split(".", 1)[1]
            # пока поддерживаем только один уровень: json.field
            if not isinstance(body, dict):
                raise ValueError("JSON root is not an object for json.* extraction")
            value = body.get(path)
            ctx[name] = value
            continue
        raise ValueError(f"Unsupported extract expression '{expr}' for variable '{name}'")


def run_step(
    client: httpx.Client,
    test_name: str,
    step_def: Dict[str, Any],
    ctx: Dict[str, Any],
) -> StepResult:
    step_name = step_def.get("name", "<unnamed step>")

    # demand
    demand = step_def.get("demand") or []
    if demand:
        msg = check_demand(demand, ctx)
        if msg:
            return StepResult(test_name, step_name, "SKIP", msg)

    # request
    req_def = step_def.get("request")
    if not req_def:
        return StepResult(test_name, step_name, "ERROR", "Step has no 'request' section")

    try:
        req_def_rendered = render_value(req_def, ctx)
    except KeyError as e:
        return StepResult(test_name, step_name, "ERROR", f"Template error: {e}")

    method = req_def_rendered.get("method", "GET").upper()
    url = req_def_rendered.get("url")
    if not url:
        return StepResult(test_name, step_name, "ERROR", "Request has no URL")

    headers = req_def_rendered.get("headers") or {}
    params = req_def_rendered.get("params") or None
    json_data = req_def_rendered.get("json", None)
    data = req_def_rendered.get("data", None)

    try:
        resp = client.request(method=method, url=url, headers=headers, params=params, json=json_data, data=data)
    except Exception as e:  # noqa: BLE001
        return StepResult(test_name, step_name, "ERROR", f"Request error: {e}")

    # expect
    expect = step_def.get("expect") or {}
    msg = apply_expect(expect, resp)
    if msg:
        # печатаем кусок ответа для дебага
        snippet = resp.text[:300]
        return StepResult(
            test_name,
            step_name,
            "FAIL",
            msg + f"\nResponse snippet:\n{snippet}",
        )

    # extract
    extract = step_def.get("extract") or {}
    if extract:
        try:
            extract_vars(extract, resp, ctx)
        except Exception as e:  # noqa: BLE001
            return StepResult(test_name, step_name, "ERROR", f"Extract error: {e}")

    return StepResult(test_name, step_name, "OK")


def run_suite(suite: Dict[str, Any]) -> List[StepResult]:
    config = suite.get("config") or {}
    tests = suite.get("tests") or []

    ctx: Dict[str, Any] = {}
    # прокидываем config сразу в контекст, чтобы можно было использовать {{base_url}}
    ctx.update(config)

    timeout = config.get("timeout", 10.0)
    base_headers = config.get("default_headers") or {}

    results: List[StepResult] = []

    with httpx.Client(timeout=timeout) as client:
        for test in tests:
            test_name = test.get("name", "<unnamed test>")
            steps = test.get("steps") or []
            print(f"\n=== TEST: {test_name} ===")

            for step_def in steps:
                # объединяем default_headers + headers из шага на этапе render_value
                # (мы можем просто добавить base_headers в ctx и использовать в YAML, если хотим)
                # или сделать примитив: если в request нет headers — подставляем default_headers
                if "request" in step_def and "headers" not in step_def["request"]:
                    step_def["request"]["headers"] = base_headers.copy()

                res = run_step(client, test_name, step_def, ctx)
                results.append(res)

                status_symbol = {
                    "OK": "✅",
                    "FAIL": "❌",
                    "SKIP": "⚪",
                    "ERROR": "💥",
                }.get(res.status, res.status)

                line = f"  {status_symbol} {res.step_name} [{res.status}]"
                print(line)
                if res.status in ("FAIL", "ERROR", "SKIP") and res.message:
                    print("     ", res.message.replace("\n", "\n      "))

    return results


def print_summary(results: List[StepResult]) -> int:
    total = len(results)
    ok = sum(1 for r in results if r.status == "OK")
    failed = sum(1 for r in results if r.status == "FAIL")
    skipped = sum(1 for r in results if r.status == "SKIP")
    errors = sum(1 for r in results if r.status == "ERROR")

    print("\n=== SUMMARY ===")
    print(f"Total steps:  {total}")
    print(f"OK:           {ok}")
    print(f"FAILED:       {failed}")
    print(f"SKIPPED:      {skipped}")
    print(f"ERRORS:       {errors}")

    # код выхода для CI:
    # если есть FAIL или ERROR → возвращаем 1
    if failed or errors:
        return 1
    return 0


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print(f"Usage: {argv[0]} path/to/tests.yaml")
        return 1

    path = Path(argv[1])
    if not path.exists():
        print(f"File not found: {path}")
        return 1

    suite = load_suite(path)
    results = run_suite(suite)
    return print_summary(results)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
