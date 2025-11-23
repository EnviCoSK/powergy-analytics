#!/usr/bin/env python3
"""
Script na spustenie denného načítania dát z AGSI.
Používa sa v cron jobe na Render.com.
"""
import sys
import os

# Pridáme /app do sys.path
sys.path.insert(0, '/app')

print("=" * 60, file=sys.stderr)
print(f"Starting run_daily.py at {__import__('datetime').datetime.now()}", file=sys.stderr)
print(f"Python version: {sys.version}", file=sys.stderr)
print(f"Working directory: {os.getcwd()}", file=sys.stderr)
print(f"PYTHONPATH: {os.environ.get('PYTHONPATH', 'not set')}", file=sys.stderr)
print("=" * 60, file=sys.stderr)

# Skontrolujeme environment variables
print("Environment variables:", file=sys.stderr)
print(f"  DATABASE_URL: {'set' if os.getenv('DATABASE_URL') else 'MISSING'}", file=sys.stderr)
print(f"  AGSI_API_KEY: {'set' if os.getenv('AGSI_API_KEY') else 'MISSING'}", file=sys.stderr)
print(f"  OPENAI_API_KEY: {'set' if os.getenv('OPENAI_API_KEY') else 'MISSING'}", file=sys.stderr)
print(f"  KYOS_URL: {os.getenv('KYOS_URL', 'not set')}", file=sys.stderr)
print("=" * 60, file=sys.stderr)

try:
    print("Importing app.scraper...", file=sys.stderr)
    from app.scraper import run_daily_agsi
    print("Import successful", file=sys.stderr)
    
    print("Calling run_daily_agsi()...", file=sys.stderr)
    result = run_daily_agsi()
    print(f"run_daily_agsi() completed: {result}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    sys.exit(0)
except Exception as e:
    import traceback
    print(f"ERROR: {e}", file=sys.stderr)
    print(traceback.format_exc(), file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    sys.exit(1)

