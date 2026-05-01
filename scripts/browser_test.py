#!/usr/bin/env python3
"""
Liberty-Emporium Browser Test Suite
=====================================
Tests any app using a real Playwright Chromium browser.
Captures HTTP errors, JS exceptions, console errors, missing content.

Usage:
  python3 browser_test.py --app gymforge
  python3 browser_test.py --app gymforge --roles owner member
  python3 browser_test.py --app all
  python3 browser_test.py --url https://myapp.up.railway.app --email admin@x.com --password s3cr3t --pages "/" "/dashboard/"
  python3 browser_test.py --app floodclaim --headed
  python3 browser_test.py --app gymforge --timeout 30
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

# ── ANSI colors ───────────────────────────────────────────────────────────────
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

def ok(msg):    print(f"  {GREEN}✅ {msg}{RESET}")
def warn(msg):  print(f"  {YELLOW}⚠️  {msg}{RESET}")
def err(msg):   print(f"  {RED}❌ {msg}{RESET}")
def info(msg):  print(f"  {BLUE}ℹ️  {msg}{RESET}")
def dim(msg):   print(f"  {DIM}{msg}{RESET}")

# Noise to suppress from console output
CONSOLE_SUPPRESS = [
    "cdn.tailwindcss.com should not be used in production",
    "favicon.ico",
    "404 (Not Found)",
]


def is_noise(msg: str) -> bool:
    return any(s.lower() in msg.lower() for s in CONSOLE_SUPPRESS)


# ── Core page tester ──────────────────────────────────────────────────────────
def test_page(page, base_url: str, path: str, label: str,
              keywords: list[str], timeout_ms: int) -> dict:
    result = {
        "path": path, "label": label,
        "status": None, "http_errors": [], "console_errors": [],
        "js_exceptions": [], "missing_keywords": [],
    }

    page_http    = []
    page_console = []
    page_js      = []

    def on_response(r):
        if r.status >= 400:
            page_http.append(f"HTTP {r.status} → {r.url.replace(base_url, '')}")

    def on_console(m):
        if m.type in ("error", "warning") and not is_noise(m.text):
            page_console.append(f"[{m.type.upper()}] {m.text[:200]}")

    def on_pageerror(e):
        page_js.append(f"[JS] {str(e)[:200]}")

    page.on("response",  on_response)
    page.on("console",   on_console)
    page.on("pageerror", on_pageerror)

    try:
        resp = page.goto(f"{base_url}{path}", timeout=timeout_ms)
        page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)

        status = resp.status if resp else "?"
        final_url = page.url
        title = page.title()
        body = page.inner_text("body") if page.query_selector("body") else ""

        # Check for server errors
        if status >= 500 or "Server Error" in title or "500" in title:
            result["status"] = f"HTTP {status} — Server Error"
            result["http_errors"].append(f"Server error {status} on {path}")
            err(f"{label} ({path}) → SERVER ERROR {status}")

        elif status == 404 or "Page not found" in title or "404" in title:
            result["status"] = f"HTTP 404 — Not Found"
            result["http_errors"].append(f"404 on {path}")
            warn(f"{label} ({path}) → 404 Not Found")

        elif "/auth/login" in final_url or "/login" in final_url:
            result["status"] = "REDIRECT → login (access denied)"
            warn(f"{label} ({path}) → redirected to login")

        else:
            result["status"] = f"HTTP {status} OK"

            # Keyword smoke test
            missing = [kw for kw in keywords
                       if kw.lower() not in body.lower() and kw.lower() not in title.lower()]
            if missing:
                result["missing_keywords"] = missing
                warn(f"{label} ({path}) → loaded but missing: {missing}")
            else:
                ok(f"{label} ({path}) → {status} ✓")

    except Exception as e:
        result["status"] = f"EXCEPTION: {str(e)[:120]}"
        err(f"{label} ({path}) → {str(e)[:80]}")

    finally:
        page.remove_listener("response",  on_response)
        page.remove_listener("console",   on_console)
        page.remove_listener("pageerror", on_pageerror)

    result["http_errors"]    += page_http
    result["console_errors"]  = page_console
    result["js_exceptions"]   = page_js

    for e in page_http:    warn(f"  → Network: {e}")
    for e in page_js:      err(f"  → JS Exception: {e}")
    for c in page_console[:3]: dim(f"  → Console: {c}")

    return result


# ── Login helper ──────────────────────────────────────────────────────────────
def do_login(page, base_url: str, login_path: str,
             email: str, password: str, timeout_ms: int) -> bool:
    try:
        page.goto(f"{base_url}{login_path}", timeout=timeout_ms)
        page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)

        # Fill email/username
        for sel in ["input[name='username']", "input[name='email']", "input[type='email']"]:
            if page.query_selector(sel):
                page.fill(sel, email)
                break

        # Fill password
        page.fill("input[type='password']", password)

        # Submit
        page.click("button[type='submit'], input[type='submit']")
        page.wait_for_load_state("networkidle", timeout=timeout_ms)

        current = page.url
        if login_path.rstrip("/") in current.replace(base_url, "").rstrip("/"):
            return False  # Still on login page
        return True

    except Exception as e:
        return False


# ── Run one role ──────────────────────────────────────────────────────────────
def test_role(browser, base_url: str, role_config: dict,
              login_path: str, timeout_ms: int) -> dict:
    from playwright.sync_api import BrowserContext

    role    = role_config.get("role", "user")
    email   = role_config.get("email", "")
    password = role_config.get("password", "")
    pages   = role_config.get("pages", [])

    result = {"role": role, "login": None, "pages": [], "total_errors": 0}

    context: BrowserContext = browser.new_context(
        viewport={"width": 1280, "height": 900},
        ignore_https_errors=True,
    )
    page = context.new_page()

    try:
        print(f"\n{BOLD}{BLUE}── {role.upper()} ({email}) ──{RESET}")

        if email:
            logged_in = do_login(page, base_url, login_path, email, password, timeout_ms)
            result["login"] = "OK" if logged_in else "FAILED"
            if logged_in:
                ok(f"Login OK → {page.url.replace(base_url,'')}")
            else:
                err(f"Login FAILED for {email}")
                return result

        for page_def in pages:
            path, label = page_def[0], page_def[1]
            keywords = page_def[2] if len(page_def) > 2 else []
            pr = test_page(page, base_url, path, label, keywords, timeout_ms)
            result["pages"].append(pr)

    finally:
        context.close()

    return result


# ── Count hard errors ─────────────────────────────────────────────────────────
def count_errors(result: dict) -> int:
    n = 0
    if result.get("login") == "FAILED":
        n += 1
    for pr in result.get("pages", []):
        if pr.get("http_errors"):  n += len(pr["http_errors"])
        if pr.get("js_exceptions"): n += len(pr["js_exceptions"])
        if pr.get("status") and ("500" in str(pr["status"]) or "EXCEPTION" in str(pr["status"])):
            n += 1
    return n


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Liberty-Emporium Browser Test Suite")
    parser.add_argument("--app",      help="App name from app_configs.py, or 'all'")
    parser.add_argument("--roles",    nargs="*", help="Roles to test (default: all roles for app)")
    parser.add_argument("--url",      help="Override/specify base URL directly")
    parser.add_argument("--email",    help="Login email (with --url)")
    parser.add_argument("--password", help="Login password (with --url)")
    parser.add_argument("--pages",    nargs="*", help="Page paths to test (with --url)")
    parser.add_argument("--headed",   action="store_true", help="Show browser window")
    parser.add_argument("--slow",     type=int, default=0, help="Slow-mo ms")
    parser.add_argument("--timeout",  type=int, default=20, help="Page timeout in seconds")
    parser.add_argument("--out",      default="/tmp/browser_test_results.json", help="JSON output path")
    args = parser.parse_args()

    timeout_ms = args.timeout * 1000

    # Load app configs
    configs_path = Path(__file__).parent / "app_configs.py"
    app_configs = {}
    if configs_path.exists():
        import importlib.util
        spec = importlib.util.spec_from_file_location("app_configs", configs_path)
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        app_configs = mod.APPS

    # Build list of app configs to test
    test_queue = []

    if args.url:
        # Ad-hoc URL mode
        pages = [(p, p, []) for p in (args.pages or ["/"])]
        cfg = {
            "name": args.url,
            "url":  args.url.rstrip("/"),
            "login_path": "/auth/login/",
            "public_pages": pages,
            "roles": [],
        }
        if args.email:
            cfg["roles"] = [{
                "role": "user",
                "email": args.email,
                "password": args.password or "",
                "pages": pages,
            }]
        test_queue.append(cfg)

    elif args.app == "all":
        test_queue = list(app_configs.values())

    elif args.app:
        if args.app not in app_configs:
            print(f"Unknown app '{args.app}'. Available: {list(app_configs.keys())}")
            sys.exit(1)
        test_queue = [app_configs[args.app]]

    else:
        parser.print_help()
        sys.exit(0)

    # Print header
    app_names = [c.get("name", c.get("url", "?")) for c in test_queue]
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  Liberty-Emporium Browser Test Suite{RESET}")
    print(f"  Apps:    {', '.join(app_names)}")
    print(f"  Time:    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Timeout: {args.timeout}s per page")
    print(f"{BOLD}{'='*60}{RESET}")

    all_results = []
    grand_total_errors = 0

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=not args.headed,
            slow_mo=args.slow,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

        for cfg in test_queue:
            app_name   = cfg.get("name", cfg.get("url", "?"))
            base_url   = cfg.get("url", "").rstrip("/")
            login_path = cfg.get("login_path", "/auth/login/")

            print(f"\n{BOLD}{'─'*60}{RESET}")
            print(f"{BOLD}  {app_name}  ({base_url}){RESET}")
            print(f"{BOLD}{'─'*60}{RESET}")

            app_result = {"app": app_name, "url": base_url, "roles": [], "public": [], "errors": 0}

            # Public pages (no login)
            pub_pages = cfg.get("public_pages", [])
            if pub_pages:
                print(f"\n{BOLD}{BLUE}── PUBLIC PAGES ──{RESET}")
                ctx = browser.new_context(viewport={"width": 1280, "height": 900}, ignore_https_errors=True)
                pg  = ctx.new_page()
                try:
                    for page_def in pub_pages:
                        path, label = page_def[0], page_def[1]
                        keywords = page_def[2] if len(page_def) > 2 else []
                        pr = test_page(pg, base_url, path, label, keywords, timeout_ms)
                        app_result["public"].append(pr)
                finally:
                    ctx.close()

            # Authenticated roles
            roles = cfg.get("roles", [])
            if args.roles:
                roles = [r for r in roles if r.get("role") in args.roles]

            for role_cfg in roles:
                r = test_role(browser, base_url, role_cfg, login_path, timeout_ms)
                app_result["roles"].append(r)

            # Count errors for this app
            for pr in app_result["public"]:
                if pr.get("http_errors"):  app_result["errors"] += len(pr["http_errors"])
                if pr.get("js_exceptions"): app_result["errors"] += len(pr["js_exceptions"])
            for role_r in app_result["roles"]:
                app_result["errors"] += count_errors(role_r)

            grand_total_errors += app_result["errors"]
            all_results.append(app_result)

        browser.close()

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  SUMMARY{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")

    for app_r in all_results:
        app_errors = app_r["errors"]
        status_icon = f"{GREEN}✅{RESET}" if app_errors == 0 else f"{RED}❌{RESET}"
        print(f"\n  {status_icon} {BOLD}{app_r['app']}{RESET}")

        # Public pages summary
        for pr in app_r["public"]:
            e = len(pr.get("http_errors", [])) + len(pr.get("js_exceptions", []))
            if e == 0 and "500" not in str(pr.get("status", "")):
                print(f"    {GREEN}✅{RESET} {pr['label']} ({pr['path']})")
            else:
                print(f"    {RED}❌{RESET} {pr['label']} ({pr['path']}) → {pr['status']}")

        # Role summaries
        for role_r in app_r["roles"]:
            role_errors = count_errors(role_r)
            login_ok = role_r.get("login") == "OK"
            pages_ok = len([p for p in role_r.get("pages", []) if not p.get("http_errors") and "500" not in str(p.get("status",""))])
            pages_total = len(role_r.get("pages", []))

            if role_errors == 0 and login_ok:
                print(f"    {GREEN}✅{RESET} {role_r['role'].upper():<15} — {pages_ok}/{pages_total} pages OK")
            else:
                print(f"    {RED}❌{RESET} {role_r['role'].upper():<15} — login={'OK' if login_ok else 'FAILED'}, {role_errors} error(s)")
                for pr in role_r.get("pages", []):
                    for e in pr.get("http_errors", [])[:2]:
                        print(f"        {RED}→ {e}{RESET}")
                    for e in pr.get("js_exceptions", [])[:1]:
                        print(f"        {RED}→ {e}{RESET}")

    print(f"\n  Total hard errors: {BOLD}{RED if grand_total_errors else GREEN}{grand_total_errors}{RESET}")
    print(f"  Finished at:       {datetime.now().strftime('%H:%M:%S')}\n")

    # Save JSON
    with open(args.out, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "results": all_results,
            "total_errors": grand_total_errors,
        }, f, indent=2)
    info(f"Results → {args.out}")

    sys.exit(1 if grand_total_errors > 0 else 0)


if __name__ == "__main__":
    main()
