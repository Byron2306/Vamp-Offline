#!/usr/bin/env python3
"""
Run Outlook evidence collection for Jan, Feb, March 2026 (staff 20172672).
Calls the running VAMP server API sequentially and shows results.
"""
import json
import sys
import os
import time

import requests

BASE_URL = "http://localhost:5050"
STAFF_ID = "20172672"
YEAR = 2026
MONTHS = ["2026-01", "2026-02", "2026-03"]
MAX_MESSAGES = 50


def collect_month(month_bucket: str) -> dict:
    payload = {
        "staff_id": STAFF_ID,
        "year": YEAR,
        "month": month_bucket,
        "mode": "month_all_tasks",
        "max_messages": MAX_MESSAGES,
        "include_body_only_candidates": True,
        "include_calendar_events": True,
        "headless": True,
    }
    print(f"\n{'='*60}")
    print(f"  Collecting: {month_bucket}  (max {MAX_MESSAGES} messages)")
    print(f"{'='*60}")
    t0 = time.time()
    try:
        resp = requests.post(
            f"{BASE_URL}/api/outlook/collect",
            json=payload,
            timeout=900,  # up to 15 min per month
        )
    except requests.exceptions.ConnectionError:
        print("ERROR: Could not connect to server at", BASE_URL)
        print("Make sure the VAMP server is running: python run_web.py")
        sys.exit(1)

    elapsed = time.time() - t0
    print(f"  Completed in {elapsed:.1f}s  |  HTTP {resp.status_code}")

    if not resp.ok:
        print(f"  ERROR: {resp.text[:300]}")
        return {"error": resp.text, "month": month_bucket}

    data = resp.json()

    # Show summary
    results = data.get("results", [])
    ingested = data.get("ingested", 0)
    candidates_total = data.get("candidates_total", len(results))
    print(f"  Candidates found : {candidates_total}")
    print(f"  Evidence ingested: {ingested}")

    if results:
        print(f"\n  Top evidence items:")
        for r in results[:10]:
            subj = r.get("subject") or r.get("title") or "(no subject)"
            src  = r.get("source", "")
            task = ", ".join(r.get("task_candidates") or [])[:40]
            print(f"    [{src[:15]:<15}] {subj[:55]:<55} → {task}")

    if data.get("search_diagnostics"):
        diag = data["search_diagnostics"]
        print(f"\n  Search diagnostics ({len(diag)} plans):")
        for d in diag[:6]:
            qs = d.get("queries") or []
            print(f"    [{d.get('kpa_code')}] {d.get('title','')[:55]}")
            for q in qs[:3]:
                print(f"           query: {q}")

    return data


def main():
    # Quick health check
    try:
        r = requests.get(f"{BASE_URL}/", timeout=5)
        if r.status_code not in (200, 404):
            print(f"Server health check failed: {r.status_code}")
            sys.exit(1)
        print(f"Server is up at {BASE_URL}")
    except Exception as e:
        print(f"Cannot reach server: {e}")
        print("Start with: python run_web.py")
        sys.exit(1)

    all_results = {}
    for month in MONTHS:
        result = collect_month(month)
        all_results[month] = result
        if "error" in result:
            print(f"\n  Skipping remaining months due to error in {month}")
            break

    # Final summary
    print(f"\n{'='*60}")
    print("  COLLECTION SUMMARY")
    print(f"{'='*60}")
    for month, data in all_results.items():
        if "error" in data:
            print(f"  {month}: ERROR - {str(data['error'])[:60]}")
        else:
            ingested = data.get("ingested", len(data.get("results", [])))
            candidates = data.get("candidates_total", len(data.get("results", [])))
            print(f"  {month}: {ingested} ingested / {candidates} candidates")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
