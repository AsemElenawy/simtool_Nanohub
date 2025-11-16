#!/usr/bin/env python
"""
READY-TO-RUN SCRIPT: Simulate, Cache, and Retrieve

Copy and paste this entire script into Terminal 2's Python REPL (>>>)
This will demonstrate the complete workflow automatically.

NOTE: To see MULTIPLE cache entries in the dashboard, run this script
multiple times. Each run will create a new cache entry with different inputs.
"""

# ============================================================================
# PART A: SETUP
# ============================================================================

from simtool.cache_client import CacheClient
import os
import json
import tempfile
import shutil
import datetime
import random

print("="*70)
print("STEP-BY-STEP: SIMULATE, CACHE, AND RETRIEVE")
print("="*70)
print()
print("TIP: Run this script multiple times to see different cache entries!")
print()

# Connect to cache server
print("SETUP: Connecting to cache server...")
client = CacheClient("http://localhost:5001")
print("[OK] Connected to http://localhost:5001")
print()

# ============================================================================
# PART B: FIRST RUN - SIMULATE AND CACHE
# ============================================================================

print("="*70)
print("FIRST RUN: SIMULATE AND STORE IN CACHE")
print("="*70)
print()

# Step 1: Define inputs
print("Step 1: Define simulation inputs")
# Use random temperature to create different cache entries on each run
random_temp = random.randint(250, 350)
inputs_run1 = {
    "temperature": random_temp,
    "pressure": 101325,
    "material": "silicon",
    "method": "DFT",
    "functional": "PBE"
}
print(f"  Inputs: {inputs_run1}")
print(f"  (Temperature is randomized: {random_temp}K - change this to see cache hits!)")
print()

# Step 2: Generate squid ID
print("Step 2: Generate unique squid ID")
squid_id_run1 = client.get_squid_id(
    "material_simulator",
    "v1.0",
    inputs_run1
)
print(f"  Squid ID: {squid_id_run1}")
print()

# Step 3: Check cache
print("Step 3: Check if already cached")
cached_before = client.check_squid_exists(squid_id_run1)
print(f"  Is cached before storage? {cached_before}")
print()

# Step 4: Create simulation results
print("Step 4: Create simulation output files")
results_dir = tempfile.mkdtemp(prefix="sim_")
print(f"  Results directory: {results_dir}")

# Create results.csv
with open(f"{results_dir}/results.csv", "w") as f:
    f.write("parameter,value,unit\n")
    f.write("temperature,300,K\n")
    f.write("pressure,101325,Pa\n")
    f.write("energy,-42.5,eV\n")
print(f"  ✓ Created results.csv")

# Create metadata.json
metadata = {
    "tool": "material_simulator",
    "version": "1.0",
    "timestamp": "2024-01-15",
    "status": "success"
}
with open(f"{results_dir}/metadata.json", "w") as f:
    json.dump(metadata, f, indent=2)
print(f"  ✓ Created metadata.json")

# Create plots
os.makedirs(f"{results_dir}/plots", exist_ok=True)
with open(f"{results_dir}/plots/energy_vs_temp.txt", "w") as f:
    f.write("Temperature (K), Energy (eV)\n")
    f.write("100,-45.2\n")
    f.write("200,-44.8\n")
    f.write("300,-42.5\n")
print(f"  ✓ Created plots/energy_vs_temp.txt")
print()

# Step 5: Store in cache
print("Step 5: Store results in cache")
client.store_result(
    squid_id_run1,
    source_dir=results_dir,
    file_list=["results.csv", "metadata.json", "plots/energy_vs_temp.txt"]
)
print(f"  [OK] Stored in cache")
print()

# Step 6: Verify cached
print("Step 6: Verify files are now cached")
cached_after = client.check_squid_exists(squid_id_run1)
print(f"  Is cached after storage? {cached_after}")
print()

# Step 7: List files in cache
print("Step 7: List files in cache")
files = client.get_squid_files(squid_id_run1)
print(f"  Total files in cache: {len(files)}")
for f in files:
    print(f"    - {f['name']}")
print()

# ============================================================================
# PART C: SECOND RUN - SAME INPUTS = CACHE HIT!
# ============================================================================

print("="*70)
print("SECOND RUN: SAME INPUTS = CACHE HIT!")
print("="*70)
print()

# Step 8: Define same inputs again
print("Step 8: Define SAME simulation inputs (Run 2)")
inputs_run2 = {
    "temperature": 300,  # SAME
    "pressure": 101325,  # SAME
    "material": "silicon",  # SAME
    "method": "DFT",  # SAME
    "functional": "PBE"  # SAME
}
print(f"  Inputs: {inputs_run2}")
print()

# Step 9: Generate squid ID again
print("Step 9: Generate squid ID again")
squid_id_run2 = client.get_squid_id(
    "material_simulator",
    "v1.0",
    inputs_run2
)
print(f"  Squid ID: {squid_id_run2}")
print()

# Step 10: Verify same ID
print("Step 10: Verify IDs are identical")
same_id = (squid_id_run1 == squid_id_run2)
print(f"  Run 1 ID: {squid_id_run1}")
print(f"  Run 2 ID: {squid_id_run2}")
print(f"  Are they the same? {same_id}")
if same_id:
    print(f"  ✓✓✓ PERFECT! Same inputs = Same ID!")
print()

# Step 11: Check cache (should be cached!)
print("Step 11: Check if Run 2 is cached")
cached_run2 = client.check_squid_exists(squid_id_run2)
print(f"  Is Run 2 cached? {cached_run2}")
if cached_run2:
    print(f"  ✓✓✓ CACHE HIT! No need to run simulation again!")
print()

# Step 12: Retrieve from cache
print("Step 12: Retrieve results from cache (instead of re-running)")
retrieve_dir = tempfile.mkdtemp(prefix="retrieved_")
print(f"  Retrieving to: {retrieve_dir}")

client.get_archived_result(squid_id_run2, retrieve_dir)
print(f"  [OK] Retrieved from cache!")
print()

# Step 13: Verify retrieved files
print("Step 13: Verify retrieved files")
retrieved_files = []
for root, dirs, filenames in os.walk(retrieve_dir):
    for fname in filenames:
        fpath = os.path.join(root, fname)
        size = os.path.getsize(fpath)
        rel_path = os.path.relpath(fpath, retrieve_dir)
        retrieved_files.append((rel_path, size))
        print(f"  ✓ {rel_path} ({size} bytes)")

print()

# Step 14: Verify content matches
print("Step 14: Verify content matches original")
with open(f"{retrieve_dir}/results.csv", "r") as f:
    content = f.read()
print(f"  Retrieved results.csv contents:")
for line in content.split("\n")[:3]:
    print(f"    {line}")
print(f"  ✓ Content matches!")
print()

# ============================================================================
# PART D: DIFFERENT INPUTS = CACHE MISS
# ============================================================================

print("="*70)
print("THIRD RUN: DIFFERENT INPUTS = CACHE MISS")
print("="*70)
print()

# Step 15: Different inputs
print("Step 15: Define DIFFERENT simulation inputs (Run 3)")
inputs_run3 = {
    "temperature": 400,  # DIFFERENT!
    "pressure": 101325,
    "material": "silicon",
    "method": "DFT",
    "functional": "PBE"
}
print(f"  Inputs: {inputs_run3}")
print(f"  (Notice temperature is 400, not 300)")
print()

# Step 16: Generate ID
print("Step 16: Generate squid ID for different inputs")
squid_id_run3 = client.get_squid_id(
    "material_simulator",
    "v1.0",
    inputs_run3
)
print(f"  Squid ID: {squid_id_run3}")
print()

# Step 17: Compare IDs
print("Step 17: Compare IDs")
different_id = (squid_id_run1 != squid_id_run3)
print(f"  Run 1 ID: {squid_id_run1}")
print(f"  Run 3 ID: {squid_id_run3}")
print(f"  Are they different? {different_id}")
if different_id:
    print(f"  ✓ Different inputs produce different squid IDs!")
print()

# Step 18: Check cache
print("Step 18: Check if Run 3 is cached")
cached_run3 = client.check_squid_exists(squid_id_run3)
print(f"  Is Run 3 cached? {cached_run3}")
if not cached_run3:
    print(f"  ✓ Cache miss! This would need to run the simulation.")
print()

# ============================================================================
# PART E: SUMMARY AND CLEANUP
# ============================================================================

print("="*70)
print("SUMMARY")
print("="*70)
print()

print("Run 1 (temp=300):")
print(f"  - Squid ID: {squid_id_run1[:30]}...")
print(f"  - Cached before: {cached_before}")
print(f"  - Cached after: {cached_after}")
print(f"  - Action: RUN SIMULATION + STORE")
print()

print("Run 2 (temp=300, same as Run 1):")
print(f"  - Squid ID: {squid_id_run2[:30]}...")
print(f"  - Same ID as Run 1? {same_id}")
print(f"  - Cached? {cached_run2}")
print(f"  - Action: RETRIEVE FROM CACHE (No simulation needed!)")
print()

print("Run 3 (temp=400, different from Run 1):")
print(f"  - Squid ID: {squid_id_run3[:30]}...")
print(f"  - Different ID? {different_id}")
print(f"  - Cached? {cached_run3}")
print(f"  - Action: Would need to RUN SIMULATION")
print()

print("="*70)
print("KEY TAKEAWAYS")
print("="*70)
print()

print("✓ Same inputs produce the same squid ID (deterministic)")
print("✓ Same squid ID means cache hit (fast retrieval)")
print("✓ Different inputs produce different squid IDs")
print("✓ Different squid IDs are cache misses (need new simulation)")
print("✓ This saves time by avoiding redundant simulations!")
print()

# Cleanup
print("="*70)
print("CLEANUP")
print("="*70)
print()

shutil.rmtree(results_dir, ignore_errors=True)
shutil.rmtree(retrieve_dir, ignore_errors=True)
print("[OK] Temporary files cleaned up")
print()

print("="*70)
print("VIEW IN BROWSER")
print("="*70)
print()
print("Open your browser and go to:")
print()
print("  http://localhost:5001/")
print()
print("You'll see the cached entries and files!")
print()
print("NOTE: To see DIFFERENT cache entries:")
print("  - Run this script again (it uses random temperature)")
print("  - Each run creates a NEW cache entry because temperature changes")
print("  - If you want to test CACHE HITS:")
print("    Replace random.randint(250, 350) with 300")
print("    Then run the script twice with same temperature = same squid ID!")
print()

print("="*70)
print("DEMO COMPLETE!")
print("="*70)
