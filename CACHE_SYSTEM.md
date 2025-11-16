# SimTool HTTP Cache System - Complete Documentation

## 📖 TABLE OF CONTENTS
1. [What is the Cache System?](#what-is-the-cache-system)
2. [Quick Start (3 Steps)](#quick-start-3-steps)
3. [How to Use](#how-to-use)
4. [API Reference](#api-reference)
5. [Advanced Topics](#advanced-topics)
6. [Troubleshooting](#troubleshooting)

---

## What is the Cache System?

The **HTTP Cache System** replaces the old ionhelper shell scripts with a modern, reliable cache infrastructure:

- ✅ **REST API** - HTTP-based cache operations
- ✅ **Python Client** - Easy-to-use library (`CacheClient`)
- ✅ **Web Dashboard** - Visual browser interface at `http://localhost:5001/`
- ✅ **File Storage** - Filesystem-based cache at `~/.cache/simtool_cache/`
- ✅ **Error Handling** - Automatic retries and error recovery
- ✅ **Docker Support** - Ready for containerized deployment

### Key Concept: Squid ID

A **Squid ID** is a deterministic unique identifier for your simulation:
```
Format: tool_name/revision/input_hash
Example: material_simulator/v1.0/b3ef85c078f6a3b7697e672905d3d1c1
```

**Important:** Same inputs always produce the same Squid ID. This enables cache hits!

---

## Quick Start (3 Steps)

### Step 1: Start the Cache Server

**Terminal 1:**
```bash
cd d:\nanohub_sim2ls_repo\simtool_Nanohub
python -m simtool.cache_web_server --port 5001
```

Expected output:
```
Starting cache web server on 0.0.0.0:5001
Cache root: C:\Users\<user>\.cache\simtool_cache
Running on http://127.0.0.1:5001
```

### Step 2: Open the Web Dashboard

Open your browser:
```
http://localhost:5001/
```

You'll see:
- Cached entries with their Squid IDs
- Files in each entry with sizes
- Total cache usage

### Step 3: Run the Complete Demo

**Terminal 2:**
```bash
python demo_copypaste.py
```

This demonstrates:
1. Creating simulation results
2. Storing them in cache
3. Running same simulation again
4. Retrieving from cache (faster!)
5. Demonstrating cache hits/misses

---

## How to Use

### Method 1: Python CacheClient (Recommended)

**Most common usage in your code:**

```python
from simtool.cache_client import CacheClient
import os
import tempfile

# 1. Connect to cache server
client = CacheClient("http://localhost:5001")

# 2. Define your simulation inputs
inputs = {
    "temperature": 300,
    "pressure": 101325,
    "material": "silicon",
    "method": "DFT"
}

# 3. Generate unique ID from inputs
squid_id = client.get_squid_id(
    simtool_name="material_simulator",
    simtool_revision="v1.0",
    inputs=inputs
)
print(f"Squid ID: {squid_id}")

# 4. Check if already cached
if client.check_squid_exists(squid_id):
    print("✓ Results found in cache!")
    
    # Retrieve results from cache (fast!)
    output_dir = tempfile.mkdtemp()
    client.get_archived_result(squid_id, output_dir)
    print(f"Retrieved from cache to: {output_dir}")
    
else:
    print("Results not cached, running simulation...")
    
    # Create/run your simulation here
    # ... save results to temp directory ...
    
    results_dir = tempfile.mkdtemp()
    # Write your result files here
    
    # Store results in cache
    client.store_result(
        squid_id,
        source_dir=results_dir,
        file_list=["output.csv", "metadata.json"]
    )
    print(f"Stored in cache: {squid_id}")

# 5. List files in cache
files = client.get_squid_files(squid_id)
print(f"\nCached files ({len(files)}):")
for f in files:
    print(f"  - {f['name']}")
```

**Key Methods:**
- `get_squid_id(name, revision, inputs)` - Generate cache key
- `check_squid_exists(squid_id)` - Check if cached (boolean)
- `store_result(squid_id, source_dir, file_list)` - Save to cache
- `get_archived_result(squid_id, output_dir)` - Retrieve from cache
- `get_squid_files(squid_id)` - List files in cache
- `download_file(file_id, output_path)` - Download specific file

---

### Method 2: REST API with PowerShell

Use HTTP calls directly. Useful for testing or non-Python environments.

**Health Check:**
```powershell
Invoke-WebRequest http://localhost:5001/health
```
Response: `{"status": "healthy"}`

**Generate Squid ID:**
```powershell
$body = @{
    simtool_name = "material_simulator"
    simtool_revision = "v1.0"
    inputs = @{
        temperature = 300
        pressure = 101325
        material = "silicon"
    }
} | ConvertTo-Json

$response = Invoke-WebRequest -Uri "http://localhost:5001/api/squid/id" `
    -Method POST -Body $body -ContentType "application/json"
    
$response.Content | ConvertFrom-Json
```

**Check if Cached:**
```powershell
$squid_id = "material_simulator/v1.0/abc123..."
$response = Invoke-WebRequest "http://localhost:5001/api/squid/exists?squid_id=$squid_id"
$response.Content | ConvertFrom-Json  # {"exists": true/false}
```

**List Files:**
```powershell
$squid_id = "material_simulator/v1.0/abc123..."
$response = Invoke-WebRequest "http://localhost:5001/api/squid/files?squid_id=$squid_id"
($response.Content | ConvertFrom-Json).files
```

**Download File:**
```powershell
$file_id = "bWF0ZXJpYWxfc2ltdWxhdG9yL3YxLjAvYWJjMTIz..."
Invoke-WebRequest "http://localhost:5001/api/files/$file_id" `
    -OutFile "C:\Users\YourUsername\Downloads\results.csv"
```

---

### Method 3: Web Dashboard (Visual)

**Open:** `http://localhost:5001/`

**Features:**
- Browse all cached entries
- View Squid ID for each entry
- See files in each entry with sizes
- **Download button** next to each file (green button)
- View total cache usage

**To download files:**
1. Find your cache entry (search by Squid ID)
2. Click the green **↓ Download** button next to the file
3. File downloads to your browser's Downloads folder

---

## API Reference

### Endpoints

| Endpoint | Method | Parameters | Purpose |
|----------|--------|-----------|---------|
| `/` | GET | none | Web dashboard |
| `/health` | GET | none | Health check |
| `/api/squid/id` | POST | `{simtool_name, simtool_revision, inputs}` | Generate/get squid ID |
| `/api/squid/exists` | GET | `squid_id` (query) | Check if cached |
| `/api/squid/files` | GET | `squid_id` (query) | List files in cache |
| `/api/files/<file_id>` | GET | none | Download file |
| `/api/squid/files` | PUT | `squid_id`, `files` (form) | Upload/store files |

### Response Formats

**Squid ID Response:**
```json
{
    "squid_id": "material_simulator/v1.0/b3ef85c078f6a3b7697e672905d3d1c1"
}
```

**Exists Response:**
```json
{
    "exists": true
}
```

**Files Response:**
```json
{
    "files": [
        {"id": "...", "name": "results.csv"},
        {"id": "...", "name": "metadata.json"}
    ]
}
```

---

## Environment Variables

Configure the cache client with environment variables:

**Windows PowerShell:**
```powershell
$env:SIM2L_CACHE_SERVER_URL = "http://localhost:5001"
$env:SIM2L_CACHE_AUTH_TOKEN = "your-token"  # Optional
```

**Windows CMD:**
```cmd
set SIM2L_CACHE_SERVER_URL=http://localhost:5001
set SIM2L_CACHE_AUTH_TOKEN=your-token
```

**Linux/Mac:**
```bash
export SIM2L_CACHE_SERVER_URL="http://localhost:5001"
export SIM2L_CACHE_AUTH_TOKEN="your-token"
```

### Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `SIM2L_CACHE_SERVER_URL` | Cache server address | `http://localhost:5000` |
| `SIM2L_CACHE_AUTH_TOKEN` | Authentication token | (none) |

---

## Cache Directory Structure

Files are stored at: **`~/.cache/simtool_cache/`**

### Layout

```
~/.cache/simtool_cache/
├── material_simulator/v1.0/b3ef85c078f6a3b7697e672905d3d1c1/
│   ├── results.csv
│   ├── metadata.json
│   └── plots_._energy_vs_temp.txt
└── other_tool/v2/abc123def456.../
    └── output.json
```

### Notes
- Each Squid ID gets its own directory
- Path separators `/` in filenames are replaced with `_._` for storage
- Use custom cache root: `--cache-root "C:\my\cache"`

---

## Server Configuration

### Starting the Server

**Development Mode (with auto-reload):**
```bash
python -m simtool.cache_web_server --port 5001 --debug
```

**Production Mode (faster):**
```bash
python -m simtool.cache_web_server --port 5001
```

**Custom Options:**
```bash
python -m simtool.cache_web_server \
    --port 5001 \
    --host 0.0.0.0 \
    --cache-root "C:\my\cache" \
    --debug
```

### Command Options

```
--port PORT           Server port (default: 5000)
--host HOST          Bind address (default: 0.0.0.0)
--cache-root PATH    Cache directory (default: ~/.cache/simtool_cache/)
--debug              Enable debug mode with auto-reload
```

---

## Advanced Topics

### Docker Deployment

**Run in Docker:**
```bash
docker-compose -f docker-compose.cache.yml up -d
```

**Or manually:**
```bash
docker build -f Dockerfile.cache -t simtool-cache .
docker run -d -p 5001:5000 \
    -v cache-storage:/root/.cache/simtool_cache \
    simtool-cache
```

### Production with Gunicorn

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5001 'simtool.cache_web_server:create_app()'
```

### HTTPS/TLS

```bash
gunicorn -w 4 -b 0.0.0.0:5001 \
    --certfile=/path/to/cert.pem \
    --keyfile=/path/to/key.pem \
    'simtool.cache_web_server:create_app()'
```

### Load Balancing

Use Nginx as reverse proxy (see `nginx.conf` for configuration):
```bash
docker-compose -f docker-compose.cache.yml up -d --scale cache-server=3
```

---

## Complete Workflow Example

**File: `demo_copypaste.py`**

See the complete working example that demonstrates:
1. Creating simulation results
2. Generating Squid ID
3. Checking cache
4. Storing results
5. Verifying cache hit
6. Retrieving cached results
7. Demonstrating cache misses with different inputs

Run it with:
```bash
python demo_copypaste.py
```

---

## Troubleshooting

### Server won't start

**Error:** `Address already in use`

**Solution:** Port 5001 is taken
```bash
python -m simtool.cache_web_server --port 5002
```

### Connection refused

**Error:** `No connection could be made because the target machine actively refused it`

**Solution:** Server isn't running
```bash
# Terminal 1: Start server
python -m simtool.cache_web_server --port 5001

# Terminal 2: Run your code
python your_script.py
```

### "Not cached" when it should be

**Issue:** Same inputs give different Squid IDs

**Solution:** Verify inputs are identical
```python
squid_id1 = client.get_squid_id("tool", "v1", {"a": 1})
squid_id2 = client.get_squid_id("tool", "v1", {"a": 1})
print(squid_id1 == squid_id2)  # Should be True
```

### Dashboard shows no entries

- Refresh browser page
- Store some results first: `client.store_result(...)`
- Check cache directory exists: `~/.cache/simtool_cache/`

### Permission denied errors

**Solution:** Specify writable cache directory
```bash
python -m simtool.cache_web_server --cache-root "C:\Users\YourUser\cache"
```

### Files can't be downloaded from dashboard

- Ensure server is running and healthy: `http://localhost:5001/health`
- Refresh browser page
- Check browser console for errors (F12)
- Try downloading via Python: `client.download_file(file_id, path)`

---

## Quick Reference

### Start Everything
```bash
# Terminal 1: Start server
python -m simtool.cache_web_server --port 5001

# Terminal 2: Open dashboard
# Open browser to: http://localhost:5001/

# Terminal 3: Run code
python demo_copypaste.py
```

### Common Python Patterns

```python
# Pattern 1: Simple check & retrieve
if client.check_squid_exists(squid_id):
    client.get_archived_result(squid_id, output_dir)

# Pattern 2: Check & store
if not client.check_squid_exists(squid_id):
    client.store_result(squid_id, results_dir, files)

# Pattern 3: List and download
files = client.get_squid_files(squid_id)
for f in files:
    client.download_file(f['id'], f"output/{f['name']}")

# Pattern 4: Complete workflow
squid_id = client.get_squid_id(name, version, inputs)
if client.check_squid_exists(squid_id):
    client.get_archived_result(squid_id, output_dir)
else:
    # Run simulation
    client.store_result(squid_id, results_dir, files)
```

### Common PowerShell Patterns

```powershell
# Check server health
Invoke-WebRequest http://localhost:5001/health

# Get Squid ID
$body = @{simtool_name="tool"; simtool_revision="v1"; inputs=@{}} | ConvertTo-Json
Invoke-WebRequest -Uri http://localhost:5001/api/squid/id -Method POST -Body $body -ContentType application/json

# List files
$squid = "tool/v1/hash..."
Invoke-WebRequest "http://localhost:5001/api/squid/files?squid_id=$squid"

# Download file
Invoke-WebRequest "http://localhost:5001/api/files/$file_id" -OutFile "file.csv"
```

---

## Key Points to Remember

✅ **Same inputs = Same Squid ID** (deterministic hashing)
✅ **Same Squid ID = Cache hit** (fast retrieval)
✅ **Different inputs = Different Squid ID** (cache miss)
✅ **Squid ID format:** `tool_name/revision/input_hash`
✅ **Cache location:** `~/.cache/simtool_cache/`
✅ **Three ways to interact:** Python, REST API, Web Dashboard
✅ **Server blocks terminal** - use separate terminals for concurrent tasks
✅ **Files in cache stay until manually deleted**

---

## File Components

### Core Python Library
- `simtool/cache_client.py` - HTTP client (460+ lines)
- `simtool/cache_config.py` - Configuration management
- `simtool/cache_web_server.py` - Flask REST API server (560+ lines)

### Demo & Examples
- `demo_copypaste.py` - Complete working demo (copy-paste friendly)

### Documentation
- `CACHE_SYSTEM.md` - This file (comprehensive guide)
- `CHEAT_SHEET.md` - One-page quick reference
- `HTTP_CACHE_README.md` - Architecture overview

### Deployment
- `Dockerfile.cache` - Docker image
- `docker-compose.cache.yml` - Docker Compose setup
- `nginx.conf` - Reverse proxy configuration

---

## Next Steps

1. **Start the server:**
   ```bash
   python -m simtool.cache_web_server --port 5001
   ```

2. **Open the dashboard:**
   ```
   http://localhost:5001/
   ```

3. **Run the demo:**
   ```bash
   python demo_copypaste.py
   ```

4. **Use in your code:**
   ```python
   from simtool.cache_client import CacheClient
   client = CacheClient("http://localhost:5001")
   ```

5. **Check the cheat sheet:**
   - See `CHEAT_SHEET.md` for quick commands

---

## Support

For issues:
1. Check server is running: `http://localhost:5001/health`
2. Review environment variables: `echo $SIM2L_CACHE_SERVER_URL`
3. Check cache directory: `~/.cache/simtool_cache/`
4. See troubleshooting section above
5. Review demo: `demo_copypaste.py`

---

**Version:** 2.0 (HTTP-based, replaces ionhelper scripts)
**Last Updated:** November 2025
**License:** MIT (same as parent project)
