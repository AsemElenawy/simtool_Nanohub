# @package      hubzero-simtool
# @file         cache_web_server.py
# @copyright    Copyright (c) 2019-2021 The Regents of the University of California.
# @license      http://opensource.org/licenses/MIT MIT
# @trademark    HUBzero is a registered trademark of The Regents of the University of California.
#
"""Web server for cache management using FastAPI.

This module provides a REST API interface for the cache system, replacing
the ionhelper bash scripts. It implements endpoints for:
- Getting squid IDs based on inputs
- Retrieving cached files
- Storing cache entries
- Listing files in a cached entry

To run the server:
    python -m simtool.cache_web_server
    
Or with uvicorn directly:
    uvicorn simtool.cache_web_server:app --host 0.0.0.0 --port 5000
"""

import os
import sys
import json
import hashlib
import traceback
import base64
from typing import Dict, List, Optional
from pathlib import Path

try:
    from fastapi import FastAPI, HTTPException, File, UploadFile, Form, Query
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
    from pydantic import BaseModel
except ImportError:
    print(
        "FastAPI is required for the cache web server. Install with: pip install fastapi uvicorn",
        file=sys.stderr,
    )
    sys.exit(1)


# Pydantic models for request/response validation
class SquidRequest(BaseModel):
    """Request model for getting squid ID."""
    simtool_name: str
    simtool_revision: str
    inputs: Dict = {}


class SquidResponse(BaseModel):
    """Response model for squid ID."""
    id: str


class ExistsResponse(BaseModel):
    """Response model for exists check."""
    exists: bool


class FileInfo(BaseModel):
    """File information model."""
    id: str
    name: str


class FilesResponse(BaseModel):
    """Response model for file list."""
    files: List[FileInfo]


class RunRequest(BaseModel):
    """Request model for running simtool."""
    simtool_name: str
    simtool_revision: str
    inputs: str = ""


class RunResponse(BaseModel):
    """Response model for run request."""
    success: bool
    squid_id: str


class HealthResponse(BaseModel):
    """Response model for health check."""
    status: str


# Global cache root directory
CACHE_ROOT = os.path.expanduser("~/.cache/simtool_cache")

# Create FastAPI app
app = FastAPI(
    title="SimTool Cache API",
    description="HTTP-based cache system for SimTool results",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)


def set_cache_root(cache_root: str):
    """Set the cache root directory."""
    global CACHE_ROOT
    CACHE_ROOT = cache_root
    os.makedirs(CACHE_ROOT, exist_ok=True)


def generate_squid_id(simtool_name: str, simtool_revision: str, inputs: dict) -> str:
    """Generate a squid ID based on tool info and inputs.
    
    Args:
        simtool_name: Name of the simulation tool
        simtool_revision: Revision of the simulation tool
        inputs: Input parameters
        
    Returns:
        The generated squid ID in format: tool_name/revision/input_hash
    """
    inputs_str = json.dumps(inputs, sort_keys=True)
    inputs_hash = hashlib.md5(inputs_str.encode()).hexdigest()
    return f"{simtool_name}/{simtool_revision}/{inputs_hash}"


def get_file_id(squid_id: str, file_path: str) -> str:
    """Generate a file ID from squid_id and file_path.
    
    Args:
        squid_id: The squid ID
        file_path: The file path (relative to squid directory)
        
    Returns:
        A base64-encoded file ID
    """
    file_ref = f"{squid_id}:{file_path}"
    return base64.b64encode(file_ref.encode()).decode()


def decode_file_id(file_id: str) -> tuple:
    """Decode a file ID to get squid_id and file_path.
    
    Args:
        file_id: The file ID
        
    Returns:
        Tuple of (squid_id, file_path) or raises HTTPException if invalid
    """
    try:
        decoded = base64.b64decode(file_id.encode()).decode()
        parts = decoded.split(":", 1)
        if len(parts) == 2:
            return tuple(parts)
    except Exception:
        pass
    raise HTTPException(status_code=400, detail="Invalid file ID")


@app.get("/api/squid/id", response_model=SquidResponse, tags=["Squid"])
async def get_squid_id_endpoint(request: SquidRequest):
    """Get squid ID for a set of inputs.
    
    The squid ID is deterministic - same inputs always produce the same ID.
    Format: tool_name/revision/md5_hash_of_inputs
    """
    try:
        squid_id = generate_squid_id(
            request.simtool_name,
            request.simtool_revision,
            request.inputs
        )
        return SquidResponse(id=squid_id)
    except Exception as e:
        print(f"Error in get_squid_id: {e}", file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/squid/exists", response_model=ExistsResponse, tags=["Squid"])
async def check_squid_exists(squid_id: str = Query(..., description="Squid ID to check")):
    """Check if a squid ID exists in cache.
    
    Returns true if the squid directory exists in the cache.
    """
    try:
        squid_dir = os.path.join(CACHE_ROOT, squid_id)
        exists = os.path.isdir(squid_dir)
        return ExistsResponse(exists=exists)
    except Exception as e:
        print(f"Error in check_squid_exists: {e}", file=sys.stderr)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/squid/files", response_model=FilesResponse, tags=["Squid"])
async def get_squid_files(squid_id: str = Query(..., description="Squid ID to list files for")):
    """Get list of files for a squid ID.
    
    Returns all files stored in the cache for this squid ID.
    """
    try:
        squid_dir = os.path.join(CACHE_ROOT, squid_id)
        
        if not os.path.isdir(squid_dir):
            return FilesResponse(files=[])
        
        files = []
        for file_name in os.listdir(squid_dir):
            file_path = os.path.join(squid_dir, file_name)
            if os.path.isfile(file_path):
                file_id = get_file_id(squid_id, file_name)
                files.append(FileInfo(id=file_id, name=file_name))
        
        return FilesResponse(files=files)
    except Exception as e:
        print(f"Error in get_squid_files: {e}", file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/files/{file_id}", tags=["Files"])
async def download_file(file_id: str):
    """Download a file by its ID.
    
    The file ID is base64-encoded and contains the squid_id and file path.
    """
    try:
        squid_id, file_path = decode_file_id(file_id)
        full_path = os.path.join(CACHE_ROOT, squid_id, file_path)
        
        # Security check - ensure file is within cache_root
        real_path = os.path.realpath(full_path)
        cache_real_path = os.path.realpath(CACHE_ROOT)
        if not real_path.startswith(cache_real_path):
            raise HTTPException(status_code=403, detail="Access denied")
        
        if not os.path.isfile(full_path):
            raise HTTPException(status_code=404, detail="File not found")
        
        return FileResponse(
            full_path,
            filename=os.path.basename(full_path),
            media_type="application/octet-stream"
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in download_file: {e}", file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/squid/files", tags=["Squid"])
async def upload_files(
    squid_id: str = Form(...),
    files: List[UploadFile] = File(...)
):
    """Upload files for a squid ID.
    
    Stores one or more files in the cache for the given squid ID.
    """
    try:
        squid_dir = os.path.join(CACHE_ROOT, squid_id)
        os.makedirs(squid_dir, exist_ok=True)
        
        saved_files = []
        for file_obj in files:
            if file_obj.filename:
                # Sanitize filename
                filename = os.path.basename(file_obj.filename)
                file_path = os.path.join(squid_dir, filename)
                
                # Save file
                contents = await file_obj.read()
                with open(file_path, "wb") as f:
                    f.write(contents)
                saved_files.append(filename)
        
        return {"saved": saved_files, "count": len(saved_files)}
    except Exception as e:
        print(f"Error in upload_files: {e}", file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/run", response_model=RunResponse, tags=["Execution"])
async def run_simtool(request: RunRequest):
    """Execute a simtool and cache the results (for trusted users).
    
    This is a placeholder endpoint for future integration with actual
    simulation execution. Currently returns the squid ID that would be
    used for caching the results.
    """
    try:
        inputs_dict = json.loads(request.inputs) if request.inputs else {}
        squid_id = generate_squid_id(
            request.simtool_name,
            request.simtool_revision,
            inputs_dict
        )
        return RunResponse(success=True, squid_id=squid_id)
    except Exception as e:
        print(f"Error in run_simtool: {e}", file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health():
    """Health check endpoint.
    
    Returns the health status of the cache server.
    """
    return HealthResponse(status="healthy")


@app.get("/", response_class=HTMLResponse, tags=["Dashboard"])
@app.get("/dashboard", response_class=HTMLResponse, tags=["Dashboard"])
async def dashboard():
    """Web dashboard to browse cached data.
    
    Displays all cached entries with files and download buttons.
    """
    try:
        cached_entries = []
        
        if os.path.exists(CACHE_ROOT):
            def scan_for_squid_ids(base_path, prefix=""):
                """Recursively scan for squid_id directories."""
                entries = []
                try:
                    for item in os.listdir(base_path):
                        item_path = os.path.join(base_path, item)
                        if os.path.isdir(item_path):
                            current_prefix = f"{prefix}/{item}" if prefix else item
                            
                            has_files = False
                            files = []
                            total_size = 0
                            
                            for root, dirs, filenames in os.walk(item_path):
                                for fname in filenames:
                                    has_files = True
                                    fpath = os.path.join(root, fname)
                                    size = os.path.getsize(fpath)
                                    total_size += size
                                    rel_path = os.path.relpath(fpath, item_path)
                                    files.append({
                                        "name": fname,
                                        "path": rel_path,
                                        "size": size
                                    })
                            
                            if has_files:
                                entries.append({
                                    "squid_id": current_prefix,
                                    "files": files,
                                    "file_count": len(files),
                                    "total_size": total_size
                                })
                            else:
                                entries.extend(scan_for_squid_ids(item_path, current_prefix))
                except Exception as e:
                    print(f"Error scanning {base_path}: {e}", file=sys.stderr)
                
                return entries
            
            cached_entries = scan_for_squid_ids(CACHE_ROOT)
        
        def format_size(bytes_size):
            """Format bytes into human-readable size."""
            for unit in ['B', 'KB', 'MB', 'GB']:
                if bytes_size < 1024:
                    return f"{bytes_size:.1f} {unit}"
                bytes_size /= 1024
            return f"{bytes_size:.1f} TB"
        
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>SimTool Cache Dashboard</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    margin: 20px;
                    background-color: #f5f5f5;
                }
                h1 {
                    color: #333;
                    border-bottom: 2px solid #007bff;
                    padding-bottom: 10px;
                }
                .powered-by {
                    color: #666;
                    font-size: 14px;
                    margin-top: -10px;
                    margin-bottom: 20px;
                }
                .stats {
                    background: white;
                    padding: 15px;
                    border-radius: 5px;
                    margin-bottom: 20px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }
                .entry {
                    background: white;
                    padding: 15px;
                    margin-bottom: 15px;
                    border-left: 4px solid #007bff;
                    border-radius: 5px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }
                .entry-header {
                    font-weight: bold;
                    color: #007bff;
                    margin-bottom: 10px;
                    word-break: break-all;
                }
                .file-list {
                    margin-left: 20px;
                    font-size: 14px;
                }
                .file-item {
                    padding: 8px 0;
                    color: #555;
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                }
                .file-info {
                    flex: 1;
                }
                .file-size {
                    color: #999;
                    font-size: 12px;
                    margin-left: 10px;
                }
                .download-btn {
                    background-color: #28a745;
                    color: white;
                    border: none;
                    padding: 5px 12px;
                    border-radius: 3px;
                    cursor: pointer;
                    font-size: 12px;
                    margin-left: 10px;
                    text-decoration: none;
                    display: inline-block;
                }
                .download-btn:hover {
                    background-color: #218838;
                }
                .download-btn:active {
                    background-color: #1e7e34;
                }
                .stats-item {
                    display: inline-block;
                    margin-right: 30px;
                }
                .stats-label {
                    font-weight: bold;
                    color: #666;
                }
                .stats-value {
                    font-size: 20px;
                    color: #007bff;
                }
                .empty {
                    color: #999;
                    font-style: italic;
                }
            </style>
        </head>
        <body>
            <h1>SimTool Cache Dashboard</h1>
            <div class="powered-by">Powered by FastAPI</div>
            
            <div class="stats">
                <div class="stats-item">
                    <div class="stats-label">Cached Entries:</div>
                    <div class="stats-value">""" + str(len(cached_entries)) + """</div>
                </div>
                <div class="stats-item">
                    <div class="stats-label">Total Cache Size:</div>
                    <div class="stats-value">""" + format_size(sum(e["total_size"] for e in cached_entries)) + """</div>
                </div>
            </div>
        """
        
        if cached_entries:
            html += "<div>"
            for entry in sorted(cached_entries, key=lambda x: x["squid_id"]):
                html += f"""
            <div class="entry">
                <div class="entry-header">Squid ID: {entry["squid_id"]}</div>
                <div class="file-list">
                    <strong>{entry["file_count"]} files</strong> ({format_size(entry["total_size"])})
        """
                for file_info in sorted(entry["files"], key=lambda x: x["name"]):
                    file_id = get_file_id(entry['squid_id'], file_info['path'])
                    
                    html += f"""
                    <div class="file-item">
                        <div class="file-info">
                            ├─ {file_info["path"]}
                            <span class="file-size">({format_size(file_info["size"])})</span>
                        </div>
                        <a href="/api/files/{file_id}" class="download-btn" download>↓ Download</a>
                    </div>
        """
                html += """
                </div>
            </div>
        """
            html += "</div>"
        else:
            html += '<p class="empty">No cached entries yet.</p>'
        
        html += """
            <hr style="margin-top: 30px; border: none; border-top: 1px solid #ddd;">
            <p style="color: #999; font-size: 12px;">
                Cache root: """ + CACHE_ROOT + """<br>
                <a href="/health">/health</a> | 
                <a href="/docs">API Docs (Swagger)</a> | 
                <a href="/redoc">API Docs (ReDoc)</a>
            </p>
        </body>
        </html>
        """
        
        return HTMLResponse(content=html)
    except Exception as e:
        print(f"Error in dashboard: {e}", file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        raise HTTPException(status_code=500, detail=str(e))


def create_app(cache_root: str = None):
    """Factory function to create FastAPI app with custom cache root.
    
    Args:
        cache_root: Root directory for cache storage
        
    Returns:
        FastAPI app instance
    """
    if cache_root:
        set_cache_root(cache_root)
    return app


if __name__ == "__main__":
    import argparse
    import uvicorn
    
    parser = argparse.ArgumentParser(description="SimTool Cache Web Server (FastAPI)")
    parser.add_argument(
        "--cache-root",
        default=None,
        help="Root directory for cache storage (default: ~/.cache/simtool_cache)",
    )
    parser.add_argument(
        "--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", type=int, default=5000, help="Port to bind to (default: 5000)"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload (development mode)",
    )
    
    args = parser.parse_args()
    
    # Set cache root
    if args.cache_root:
        set_cache_root(args.cache_root)
    else:
        os.makedirs(CACHE_ROOT, exist_ok=True)
    
    print(f"Starting cache web server on {args.host}:{args.port}")
    print(f"Cache root: {CACHE_ROOT}")
    print(f"API Documentation: http://{args.host}:{args.port}/docs")
    
    # Run server with uvicorn
    uvicorn.run(
        "simtool.cache_web_server:app",
        host=args.host,
        port=args.port,
        reload=args.reload
    )
