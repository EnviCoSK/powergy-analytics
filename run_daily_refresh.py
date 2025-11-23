#!/usr/bin/env python3
"""
Script na denné obnovenie dát cez API endpointy.
Nahrádza bash script v cron jobe "daily-refresh".
"""
import sys
import os
import time
import requests

# Pridáme /app do sys.path
sys.path.insert(0, '/app')

print("=" * 60, file=sys.stderr)
print(f"Starting run_daily_refresh.py at {__import__('datetime').datetime.now()}", file=sys.stderr)
print("=" * 60, file=sys.stderr)

# Získame base URL z environment variable alebo použijeme default
base_url = os.getenv('APP_BASE_URL', 'https://powergy-analytics.onrender.com')
print(f"Base URL: {base_url}", file=sys.stderr)

def hit(url, name, max_retries=3, retry_delay=10):
    """Volá API endpoint s retry logikou."""
    print(f"Calling {name} at {url}...", file=sys.stderr)
    for i in range(1, max_retries + 1):
        try:
            response = requests.get(url, timeout=60)
            if response.status_code == 200:
                print(f"{name} OK (HTTP {response.status_code})", file=sys.stderr)
                try:
                    result = response.json()
                    print(f"  Result: {result}", file=sys.stderr)
                except:
                    print(f"  Response: {response.text[:200]}", file=sys.stderr)
                return True
            else:
                print(f"{name} attempt {i} failed (HTTP {response.status_code})", file=sys.stderr)
                if i < max_retries:
                    print(f"  Retry in {retry_delay}s...", file=sys.stderr)
                    time.sleep(retry_delay)
        except Exception as e:
            print(f"{name} attempt {i} failed with exception: {e}", file=sys.stderr)
            if i < max_retries:
                print(f"  Retry in {retry_delay}s...", file=sys.stderr)
                time.sleep(retry_delay)
    
    print(f"{name} FAILED after {max_retries} attempts", file=sys.stderr)
    return False

try:
    # 1. Ingest AGSI data
    if not hit(f"{base_url}/api/ingest-agsi-today", "Ingest AGSI"):
        print("ERROR: Ingest AGSI failed", file=sys.stderr)
        sys.exit(1)
    
    # 2. Recompute deltas
    if not hit(f"{base_url}/api/recompute-deltas?days=7", "Recompute deltas"):
        print("ERROR: Recompute deltas failed", file=sys.stderr)
        sys.exit(1)
    
    # 3. Refresh comment
    if not hit(f"{base_url}/api/refresh-comment?force=true", "Refresh comment"):
        print("ERROR: Refresh comment failed", file=sys.stderr)
        sys.exit(1)
    
    print("=" * 60, file=sys.stderr)
    print("ALL OK", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    sys.exit(0)
    
except Exception as e:
    import traceback
    print(f"ERROR: {e}", file=sys.stderr)
    print(traceback.format_exc(), file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    sys.exit(1)

