#!/usr/bin/env python
import datetime
import json
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Union

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


# {{ ... }} шаблоны: поддерживаем и переменные, и вызовы функций
VAR_PATTERN = re.compile(r"{{\s*([^}]+?)\s*}}")
# JSON path: items[0].uid
JSON_PATH_PART = re.compile(r"^([a-zA-Z0-9_]+)(\[(\d+)\])?$")


# ===== Builtins для шаблонов =====


def builtin_randint(args: List[str]) -> str:
    if len(args) != 2:
        raise ValueError("randint requires 2 arguments")
    return str(random.randint(int(args[0]), int(args[1])))


def builtin_randweekday(args: List[str]) -> str:
    # например "Sat"
    return datetime.date.today().strftime("%a")


def builtin_randmonth(args: List[str]) -> str:
    # например "Dec"
    return datetime.date.today().strftime("%b")


BUILTINS = {
    "randint": builtin_randint,
    "randweekday": builtin_randweekday,
    "randmonth": builtin_randmonth,
}


def get_json_path_value(body: Any, path: str) -> Any:
    """
    Очень простой JSON-path:
    - 'items' → body['items']
    - 'items[0]' → body['items'][0]
    - 'items[0].uid' → body['items'][0]['uid']
    """
    current = body
    for part in path.split("."):
        # Handle direct array access at start: "[0]"
        if part.startswith("[") and part.endswith("]"):
            idx = int(part[1:-1])
            if not isinstance(current, list):
                raise ValueError(f"Value is not a list for json path '{path}'")
            if idx < 0 or idx >= len(current):
                raise ValueError(f"Index {idx} out of range in json path '{path}'")
            current = current[idx]
            continue

        m = JSON_PATH_PART.match(part)
        if not m:
            raise ValueError(f"Invalid json path part: {part!r} in {path!r}")

        key = m.group(1)
        idx_str = m.group(3)

        if not isinstance(current, dict) or key not in current:
            raise ValueError(f"Key '{key}' not found while resolving json path '{path}'")
        current = current[key]

        if idx_str is not None:
            idx = int(idx_str)
            if not isinstance(current, list):
                raise ValueError(f"Value at '{key}' is not a list for json path '{path}'")
            if idx < 0 or idx >= len(current):
                raise ValueError(f"Index {idx} out of range for '{key}' in json path '{path}'")
            current = current[idx]

    return current


def render_value(value: Any, ctx: Dict[str, Any]) -> Any:
    """Рекурсивно подставляем {{ ... }} в строках, dict и list."""
    if isinstance(value, str):

        def repl(match: re.Match) -> str:
            expr = match.group(1).strip()

            # вызов функции с аргументами: randint(100, 999)
            if "(" in expr and expr.endswith(")"):
                fname, argstr = expr.split("(", 1)
                fname = fname.strip()
                argstr = argstr[:-1]  # remove ")"
                args = [a.strip() for a in argstr.split(",")] if argstr else []

                if fname not in BUILTINS:
                    raise KeyError(f"Unknown function '{fname}' in template")

                return str(BUILTINS[fname](args))

            # вызов функции без аргументов: randmonth
            if expr in BUILTINS:
                return str(BUILTINS[expr]([]))

            # обычная переменная
            if expr not in ctx:
                raise KeyError(f"Variable '{expr}' is not defined in context")
            return str(ctx[expr])

        return VAR_PATTERN.sub(repl, value)

    elif isinstance(value, dict):
        return {k: render_value(v, ctx) for k, v in value.items()}

    elif isinstance(value, list):
        return [render_value(v, ctx) for v in value]

    else:
        return value


def render_env(env: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    rendered: Dict[str, Any] = {}
    for key, value in env.items():
        combined = {**ctx, **rendered}
        rendered[key] = render_value(value, combined)
    return rendered


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
        try:
            actual = get_json_path_value(body, field)
        except ValueError as e:
            return f"Field path '{field}' error: {e}"
        if actual != expected:
            return f"Field '{field}' mismatch: expected {expected!r}, got {actual!r}"
    return None


def json_has_keys(body: Any, keys: List[str]) -> Optional[str]:
    if not isinstance(body, dict):
        return "Expected JSON object at root for 'has_keys'"
    for k in keys:
        if k not in body:
            return f"Expected key '{k}' in JSON root"
    return None


def json_list_len_gte(body: Any, mapping: Dict[str, int]) -> Optional[str]:
    """
    Проверяет, что указанные поля в JSON — списки с длиной >= заданной.
    Пример: {"items": 1} → len(body["items"]) >= 1
    """
    if not isinstance(body, dict):
        return "Expected JSON object at root for 'list_len_gte'"
    for field, min_len in mapping.items():
        if field not in body:
            return f"Expected field '{field}' in JSON for 'list_len_gte'"
        value = body[field]
        if not isinstance(value, list):
            return f"Field '{field}' is not a list for 'list_len_gte'"
        if len(value) < min_len:
            return f"List '{field}' length too short: " f"expected >= {min_len}, got {len(value)}"
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
        if "list_len_gte" in jexp:
            msg = json_list_len_gte(body, jexp["list_len_gte"])
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
        if expr.startswith("json.") or expr.startswith("json["):
            if body is None:
                body = get_json(resp)

            # Handle both "json.items[0].uid" and "json[0].name"
            if expr.startswith("json["):
                path = expr[4:]  # Remove "json" prefix, keep "[0].name"
            else:
                path = expr.split(".", 1)[1]  # "items[0].uid"

            value = get_json_path_value(body, path)
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

    # --- SKIP rule for step ---
    if "skip" in step_def and step_def["skip"]:
        reason = step_def["skip"] if isinstance(step_def["skip"], str) else "Step skipped by configuration"
        return StepResult(test_name, step_name, "SKIP", reason)

    # --- SET rule: calculate and store variables in ctx ---
    if "set" in step_def:
        assigns = step_def["set"]
        if not isinstance(assigns, dict):
            return StepResult(test_name, step_name, "ERROR", "'set' must be a mapping")
        try:
            for var, template in assigns.items():
                ctx[var] = render_value(template, ctx)
        except Exception as e:  # noqa: BLE001
            return StepResult(test_name, step_name, "ERROR", f"Set error: {e}")

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
        resp = client.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json=json_data,
            data=data,
        )
    except Exception as e:  # noqa: BLE001
        return StepResult(test_name, step_name, "ERROR", f"Request error: {e}")

    # echo response if requested
    if step_def.get("echo"):
        print(f"\n=== RESPONSE: {test_name} :: {step_name} ===")
        print(f"Request: {method} {url}")
        print(f"Status: {resp.status_code}")
        print("Headers:")
        for k, v in resp.headers.items():
            print(f"  {k}: {v}")
        print("Body:")
        try:
            parsed = resp.json()
            print(json.dumps(parsed, indent=2, ensure_ascii=False))
        except Exception:
            # не JSON – печатаем как есть
            print(resp.text)
        print("=== END RESPONSE ===\n")

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


def run_login_if_configured(
    config: Dict[str, Any],
    ctx: Dict[str, Any],
    client: httpx.Client,
) -> List[StepResult]:
    results: List[StepResult] = []

    auth_conf = config.get("auth") or {}
    login_def = auth_conf.get("login")
    if not login_def:
        return results  # логина не настроено — ничего не делаем

    test_name = "__auth__"
    step_name = login_def.get("name", "login")

    print("\n=== AUTH: login ===")

    # делаем вид, что это обычный шаг
    fake_step = {
        "name": step_name,
        "set": login_def.get("set", {}),
        "request": login_def.get("request"),
        "expect": login_def.get("expect", {}),
        "extract": login_def.get("extract", {}),
        "echo": login_def.get("echo", False),
    }

    res = run_step(client, test_name, fake_step, ctx)
    results.append(res)

    status_symbol = {
        "OK": "✅",
        "FAIL": "❌",
        "SKIP": "⚪",
        "ERROR": "💥",
    }.get(res.status, res.status)

    print(f"  {status_symbol} {res.step_name} [{res.status}]")
    if res.status in ("FAIL", "ERROR") and res.message:
        print("     ", res.message.replace("\n", "\n      "))

    return results


def run_suite(suite: Dict[str, Any], ctx: Dict[str, Any]) -> List[StepResult]:
    """
    ctx сюда уже приходит из main, где мы подмешали env.
    Здесь НЕ затираем ctx config'ом.
    """
    config = suite.get("config") or {}
    tests = suite.get("tests") or []

    timeout = config.get("timeout", 10.0)
    base_headers = config.get("default_headers") or {}

    results: List[StepResult] = []

    with httpx.Client(timeout=timeout) as client:
        # сначала пробуем логин
        login_results = run_login_if_configured(config, ctx, client)
        results.extend(login_results)

        for test in tests:
            test_name = test.get("name", "<unnamed test>")
            test_demand = test.get("demand") or []

            # --- SKIP rule for whole test ---
            if "skip" in test and test["skip"]:
                reason = test["skip"] if isinstance(test["skip"], str) else "Test skipped by configuration"
                print(f"\n=== TEST: {test_name} ===")
                res = StepResult(
                    test_name=test_name,
                    step_name="__test_skip__",
                    status="SKIP",
                    message=reason,
                )
                results.append(res)
                print(f"  ⚪ [SKIP] {reason}")
                continue

            # Если у теста есть demand и он не выполнен — скипаем ВСЕ шаги
            demand_msg = None
            if test_demand:
                demand_msg = check_demand(test_demand, ctx)

            print(f"\n=== TEST: {test_name} ===")

            if demand_msg:
                # весь тест SKIP
                res = StepResult(
                    test_name=test_name,
                    step_name="__test_setup__",
                    status="SKIP",
                    message=demand_msg,
                )
                results.append(res)
                print(f"  ⚪ [SKIP] {res.message}")
                continue

            # Apply test-level set: before running steps
            test_set = test.get("set") or {}
            for k, v in test_set.items():
                ctx[k] = render_value(v, ctx)

            steps = test.get("steps") or []

            for step_def in steps:
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
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("suite", help="Path to test YAML file")
    parser.add_argument("--env", help="Path to env YAML file", required=False)
    args = parser.parse_args()

    suite_path = Path(args.suite)
    if not suite_path.exists():
        print(f"File not found: {suite_path}")
        return 1

    suite = load_suite(suite_path)
    config = suite.get("config") or {}

    ctx: Dict[str, Any] = {}

    # 1) ENV из CLI имеет приоритет
    if args.env:
        env_path = Path(args.env)
        if not env_path.exists():
            print(f"Env file not found: {env_path}")
            return 1
        print(f"Using env from CLI: {env_path}")
        env_data = load_suite(env_path) or {}
        try:
            ctx.update(render_env(env_data, ctx))
        except Exception as e:  # noqa: BLE001
            print(f"Env template error in {env_path}: {e}")
            return 1

    # 2) Если --env не указан, смотрим config.env_file / config.env_files
    else:
        # поддержим сразу и одиночный файл, и список
        env_files: List[str] = []

        if "env_file" in config and config["env_file"]:
            env_files.append(config["env_file"])
        if "env_files" in config and config["env_files"]:
            # ожидаем список строк
            env_files.extend(config["env_files"])

        for name in env_files:
            env_path = suite_path.parent / name
            if env_path.exists():
                print(f"Using env_file from config: {env_path}")
                env_data = load_suite(env_path) or {}
                try:
                    ctx.update(render_env(env_data, ctx))
                except Exception as e:  # noqa: BLE001
                    print(f"Env template error in {env_path}: {e}")
                    return 1
            else:
                print(f"WARNING: env_file declared but not found: {env_path}")

    results = run_suite(suite, ctx)
    return print_summary(results)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
