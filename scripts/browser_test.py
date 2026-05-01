#!/usr/bin/env python3
"""
GymForge Browser Test Suite
============================
Logs in as every role, visits their key pages, and captures ALL errors:
  - HTTP 4xx/5xx responses
  - JavaScript console errors & exceptions
  - Page crashes / timeouts
  - Missing expected elements (smoke-tests)

Usage:
    python3 scripts/browser_test.py                      # test all roles
    python3 scripts/browser_test.py --role owner         # one role
    python3 scripts/browser_test.py --role member trainer
    python3 scripts/browser_test.py --headed             # see the browser
    python3 scripts/browser_test.py --url https://your-railway-url.up.railway.app

Output: color-coded terminal report + scripts/test_results.json
"""

import argparse, json, sys, time
from datetime import datetime
from playwright.sync_api import sync_playwright, Page, BrowserContext

# ── Config ────────────────────────────────────────────────────────────────────
BASE_URL = "https://web-production-1c23.up.railway.app"

ROLES = {
    "owner": {
        "email": "jay@gymforge.com",
        "password": "GymForge2026!",
        "pages": [
            ("/owner/",              "dashboard",        ["Dashboard", "Gym"]),
            ("/owner/tiers/",        "membership tiers", ["Tier", "Plan", "Member"]),
            ("/owner/staff/",        "staff list",       ["Staff"]),
            ("/owner/leads/",        "leads",            ["Lead"]),
            ("/owner/branding/",     "branding preview", ["Brand", "Gym"]),
        ],
    },
    "manager": {
        "email": "manager@demo.gymforge.com",
        "password": "Demo2026!",
        "pages": [
            ("/manager/",          "dashboard",  ["Dashboard", "Manager"]),
            ("/manager/schedule/", "schedule",   ["Schedule", "Class"]),
            ("/manager/shifts/",   "shifts",     ["Shift", "Staff"]),
            ("/manager/checkins/", "check-ins",  ["Check"]),
        ],
    },
    "trainer": {
        "email": "trainer@demo.gymforge.com",
        "password": "Demo2026!",
        "pages": [
            ("/trainer/",              "client list",   ["Client", "Member"]),
            ("/trainer/appointments/", "appointments",  ["Appointment", "Schedule"]),
            ("/trainer/workout-plans/", "workout plans", ["Plan", "Workout"]),
        ],
    },
    "front_desk": {
        "email": "front_desk@demo.gymforge.com",
        "password": "Demo2026!",
        "pages": [
            ("/desk/",               "dashboard",     ["Dashboard", "Check"]),
            ("/desk/checkin/manual/","manual check-in",["Check", "Member"]),
            ("/desk/members/",       "member lookup", ["Member"]),
        ],
    },
    "cleaner": {
        "email": "cleaner@demo.gymforge.com",
        "password": "Demo2026!",
        "pages": [
            ("/cleaner/",          "dashboard",  ["Dashboard", "Task", "Cleaner"]),
            ("/cleaner/tasks/",    "task list",  ["Task"]),
            ("/cleaner/summary/",  "shift summary", ["Shift", "Summary"]),
        ],
    },
    "nutritionist": {
        "email": "nutritionist@demo.gymforge.com",
        "password": "Demo2026!",
        "pages": [
            ("/nutritionist/",              "client list",  ["Client", "Member"]),
            ("/nutritionist/appointments/", "appointments", ["Appointment"]),
            ("/nutritionist/plans/",        "nutrition plans", ["Plan", "Nutrition"]),
        ],
    },
    "member": {
        "email": "member@demo.gymforge.com",
        "password": "Demo2026!",
        "pages": [
            ("/app/",              "member home",     ["Welcome", "Dashboard", "Gym"]),
            ("/app/classes/",      "class schedule",  ["Class", "Schedule", "Book"]),
            ("/app/workouts/",     "workout history", ["Workout"]),
            ("/app/my-bookings/",  "my bookings",     ["Booking", "Class"]),
        ],
    },
}

# ── ANSI colors ───────────────────────────────────────────────────────────────
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):    print(f"  {GREEN}✅ {msg}{RESET}")
def warn(msg):  print(f"  {YELLOW}⚠️  {msg}{RESET}")
def err(msg):   print(f"  {RED}❌ {msg}{RESET}")
def info(msg):  print(f"  {BLUE}ℹ️  {msg}{RESET}")

# ── Core test runner ──────────────────────────────────────────────────────────
def test_role(page: Page, role: str, config: dict, base_url: str) -> dict:
    results = {"role": role, "login": None, "pages": [], "errors": []}
    email    = config["email"]
    password = config["password"]

    # ── Login ──────────────────────────────────────────────────────────────
    http_errors = []
    console_errors = []

    page.on("response", lambda r: http_errors.append(
        f"HTTP {r.status} {r.url.replace(base_url, '')}"
    ) if r.status >= 400 else None)

    page.on("console", lambda m: console_errors.append(
        f"[{m.type.upper()}] {m.text}"
    ) if m.type in ("error", "warning") else None)

    page.on("pageerror", lambda e: console_errors.append(f"[JS EXCEPTION] {e}"))

    try:
        page.goto(f"{base_url}/auth/login/", timeout=15000)
        page.fill("input[name='username'], input[name='email'], input[type='email']", email)
        page.fill("input[name='password'], input[type='password']", password)
        page.click("button[type='submit'], input[type='submit']")
        page.wait_for_load_state("networkidle", timeout=15000)

        current = page.url
        if "/auth/login/" in current:
            results["login"] = "FAILED — still on login page"
            results["errors"].append(f"Login failed for {email}")
            err(f"Login FAILED for {role} ({email})")
            return results

        results["login"] = "OK"
        ok(f"Login OK  ({email}  →  {current.replace(base_url,'')})")

    except Exception as e:
        results["login"] = f"ERROR: {e}"
        results["errors"].append(str(e))
        err(f"Login exception for {role}: {e}")
        return results

    # ── Page tests ─────────────────────────────────────────────────────────
    for path, label, expected_keywords in config["pages"]:
        page_errors   = []
        page_console  = []
        page_http     = []

        # Per-page listeners
        def on_response(r, _ph=page_http):
            if r.status >= 400:
                _ph.append(f"HTTP {r.status} → {r.url.replace(base_url,'')}")

        def on_console(m, _pc=page_console):
            if m.type in ("error", "warning"):
                _pc.append(f"[{m.type.upper()}] {m.text}")

        def on_pageerror(e, _pe=page_errors):
            _pe.append(f"[JS EXCEPTION] {e}")

        page.on("response",  on_response)
        page.on("console",   on_console)
        page.on("pageerror", on_pageerror)

        page_result = {
            "path": path, "label": label,
            "status": None, "http_errors": [], "console_errors": [],
            "js_exceptions": [], "missing_elements": [],
        }

        try:
            resp = page.goto(f"{base_url}{path}", timeout=15000)
            page.wait_for_load_state("domcontentloaded", timeout=10000)
            status_code = resp.status if resp else "?"

            # Check for server errors in page title / body
            title = page.title()
            body_text = page.inner_text("body") if page.query_selector("body") else ""

            if status_code >= 500 or "Server Error" in title or "500" in title:
                page_result["status"] = f"HTTP {status_code} — Server Error"
                page_result["http_errors"].append(f"{status_code} on {path}")
                err(f"{label} ({path}) → {RED}SERVER ERROR {status_code}{RESET}")

            elif status_code == 404 or "Page not found" in title:
                page_result["status"] = f"HTTP 404 — Not Found"
                page_result["http_errors"].append(f"404 on {path}")
                warn(f"{label} ({path}) → 404 Not Found")

            elif "/auth/login/" in page.url:
                page_result["status"] = "REDIRECT → login (permission denied)"
                warn(f"{label} ({path}) → redirected to login")

            else:
                page_result["status"] = f"HTTP {status_code} OK"

                # Smoke test — check expected keywords appear somewhere on page
                missing = []
                for kw in expected_keywords:
                    if kw.lower() not in body_text.lower() and kw.lower() not in title.lower():
                        missing.append(kw)
                if missing:
                    page_result["missing_elements"] = missing
                    warn(f"{label} ({path}) → loaded but missing: {missing}")
                else:
                    ok(f"{label} ({path}) → {status_code} ✓ content looks good")

        except Exception as e:
            page_result["status"] = f"EXCEPTION: {e}"
            err(f"{label} ({path}) → Exception: {e}")

        finally:
            page.remove_listener("response",  on_response)
            page.remove_listener("console",   on_console)
            page.remove_listener("pageerror", on_pageerror)

        page_result["http_errors"]    += page_http
        page_result["console_errors"] += page_console
        page_result["js_exceptions"]  += page_errors

        if page_http:
            for e in page_http:
                warn(f"  → Network: {e}")
        if page_errors:
            for e in page_errors:
                err(f"  → JS: {e}")
        if page_console:
            filtered = [c for c in page_console if "favicon" not in c.lower()]
            for c in filtered[:3]:
                warn(f"  → Console: {c}")

        results["pages"].append(page_result)

    return results


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="GymForge Browser Test Suite")
    parser.add_argument("--role",   nargs="*", help="Roles to test (default: all)")
    parser.add_argument("--headed", action="store_true", help="Show browser window")
    parser.add_argument("--url",    default=BASE_URL, help="Override base URL")
    parser.add_argument("--slow",   type=int, default=0, help="Slow-mo ms (use with --headed)")
    args = parser.parse_args()

    base_url  = args.url.rstrip("/")
    roles_to_test = args.role or list(ROLES.keys())
    invalid = [r for r in roles_to_test if r not in ROLES]
    if invalid:
        print(f"Unknown roles: {invalid}. Available: {list(ROLES.keys())}")
        sys.exit(1)

    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  GymForge Browser Test Suite{RESET}")
    print(f"  URL:   {base_url}")
    print(f"  Roles: {', '.join(roles_to_test)}")
    print(f"  Time:  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{BOLD}{'='*60}{RESET}\n")

    all_results = []
    total_errors = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=not args.headed,
            slow_mo=args.slow,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

        for role in roles_to_test:
            config = ROLES[role]
            print(f"\n{BOLD}{BLUE}── {role.upper()} ──{RESET}")

            context: BrowserContext = browser.new_context(
                viewport={"width": 1280, "height": 900},
                ignore_https_errors=True,
            )
            page = context.new_page()

            try:
                result = test_role(page, role, config, base_url)
                all_results.append(result)

                # Count errors for this role
                role_errors = len(result["errors"])
                for pr in result["pages"]:
                    role_errors += len(pr["http_errors"])
                    role_errors += len(pr["js_exceptions"])
                    if pr["status"] and ("500" in str(pr["status"]) or "Error" in str(pr["status"])):
                        role_errors += 1
                total_errors += role_errors

            finally:
                context.close()

        browser.close()

    # ── Summary ───────────────────────────────────────────────────────────
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  SUMMARY{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")

    for r in all_results:
        role_errs = []
        for pr in r["pages"]:
            if pr["http_errors"]:    role_errs += pr["http_errors"]
            if pr["js_exceptions"]:  role_errs += pr["js_exceptions"]
            if pr["status"] and ("500" in str(pr["status"]) or "Exception" in str(pr["status"])):
                role_errs.append(pr["status"])

        login_ok = r["login"] == "OK"
        if not role_errs and login_ok:
            print(f"  {GREEN}✅ {r['role'].upper():15}{RESET} — {len(r['pages'])} pages, no errors")
        else:
            print(f"  {RED}❌ {r['role'].upper():15}{RESET} — login={'OK' if login_ok else 'FAILED'}, {len(role_errs)} error(s)")
            for e in role_errs[:5]:
                print(f"      {RED}→ {e}{RESET}")

    print(f"\n  Total hard errors: {BOLD}{RED if total_errors else GREEN}{total_errors}{RESET}")
    print(f"  Tested roles:      {', '.join(roles_to_test)}")
    print(f"  Finished at:       {datetime.now().strftime('%H:%M:%S')}\n")

    # ── Save JSON results ──────────────────────────────────────────────────
    out_path = "/root/.openclaw/workspace/GymForge/scripts/test_results.json"
    with open(out_path, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "base_url": base_url,
            "results": all_results,
            "total_errors": total_errors,
        }, f, indent=2)
    info(f"Full results saved → {out_path}")

    sys.exit(1 if total_errors > 0 else 0)


if __name__ == "__main__":
    main()
