# @package      hubzero-simtool
# @file         cache_web_server.py
# @copyright    Copyright (c) 2019-2021 The Regents of the University of California.
# @license      http://opensource.org/licenses/MIT MIT
# @trademark    HUBzero is a registered trademark of The Regents of the University of California.
#
"""Web server for cache management using Flask.

This module provides a REST API interface for the cache system, replacing
the ionhelper bash scripts. It implements endpoints for:
- Getting squid IDs based on inputs
- Retrieving cached files
- Storing cache entries
- Listing files in a cached entry

To run the server:
    python -m simtool.cache_web_server
"""

import os
import sys
import json
import uuid
import hashlib
import traceback
from pathlib import Path

try:
    from flask import Flask, request, jsonify, send_file
    from werkzeug.utils import secure_filename
except ImportError:
    print(
        "Flask is required for the cache web server. Install with: pip install flask",
        file=sys.stderr,
    )
    sys.exit(1)


class CacheWebServer:
    """Flask-based cache web server."""

    def __init__(self, cache_root=None, host="0.0.0.0", port=5000, debug=False):
        """Initialize the cache web server.

        Args:
            cache_root (str, optional): Root directory for cache storage.
                Defaults to ~/.cache/simtool_cache
            host (str): Host to bind to. Defaults to 0.0.0.0
            port (int): Port to bind to. Defaults to 5000
            debug (bool): Enable Flask debug mode. Defaults to False
        """
        if cache_root is None:
            cache_root = os.path.expanduser("~/.cache/simtool_cache")

        self.cache_root = cache_root
        self.host = host
        self.port = port
        self.debug = debug

        # Ensure cache root exists
        os.makedirs(self.cache_root, exist_ok=True)

        # Initialize Flask app
        self.app = Flask(__name__)
        self.app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024  # 1GB max upload

        # Register routes
        self._register_routes()

    def _register_routes(self):
        """Register all API routes."""

        @self.app.route("/api/squid/id", methods=["GET"])
        def get_squid_id():
            """Get squid ID for a set of inputs."""
            try:
                data = request.get_json()

                simtool_name = data.get("simtool_name")
                simtool_revision = data.get("simtool_revision")
                inputs = data.get("inputs", {})

                if not simtool_name or not simtool_revision:
                    return (
                        jsonify({"error": "simtool_name and simtool_revision required"}),
                        400,
                    )

                # Generate squid ID based on inputs hash
                squid_id = self._generate_squid_id(
                    simtool_name, simtool_revision, inputs
                )

                return jsonify({"id": squid_id}), 200

            except Exception as e:
                print(f"Error in get_squid_id: {e}", file=sys.stderr)
                print(traceback.format_exc(), file=sys.stderr)
                return jsonify({"error": str(e)}), 500

        @self.app.route("/api/squid/exists", methods=["GET"])
        def check_squid_exists():
            """Check if a squid ID exists in cache."""
            try:
                squid_id = request.args.get("squid_id")

                if not squid_id:
                    return jsonify({"error": "squid_id parameter required"}), 400

                squid_dir = os.path.join(self.cache_root, squid_id)
                exists = os.path.isdir(squid_dir)

                return jsonify({"exists": exists}), 200

            except Exception as e:
                print(f"Error in check_squid_exists: {e}", file=sys.stderr)
                return jsonify({"error": str(e)}), 500

        @self.app.route("/api/squid/files", methods=["GET"])
        def get_squid_files():
            """Get list of files for a squid ID."""
            try:
                squid_id = request.args.get("squid_id")

                if not squid_id:
                    return jsonify({"error": "squid_id parameter required"}), 400

                squid_dir = os.path.join(self.cache_root, squid_id)

                if not os.path.isdir(squid_dir):
                    return jsonify({"files": []}), 200

                files = []
                for file_name in os.listdir(squid_dir):
                    file_path = os.path.join(squid_dir, file_name)
                    if os.path.isfile(file_path):
                        file_id = self._get_file_id(squid_id, file_name)
                        files.append({"id": file_id, "name": file_name})

                return jsonify({"files": files}), 200

            except Exception as e:
                print(f"Error in get_squid_files: {e}", file=sys.stderr)
                print(traceback.format_exc(), file=sys.stderr)
                return jsonify({"error": str(e)}), 500

        @self.app.route("/api/files/<file_id>", methods=["GET"])
        def download_file(file_id):
            """Download a file by its ID."""
            try:
                download = request.args.get("download", "false").lower() == "true"

                # Decode file_id to get squid_id and file_name
                decoded = self._decode_file_id(file_id)
                if not decoded:
                    return jsonify({"error": "Invalid file ID"}), 400

                squid_id, file_name = decoded
                file_path = os.path.join(self.cache_root, squid_id, file_name)

                # Security check - ensure file is within cache_root
                real_path = os.path.realpath(file_path)
                cache_real_path = os.path.realpath(self.cache_root)
                if not real_path.startswith(cache_real_path):
                    return jsonify({"error": "Access denied"}), 403

                if not os.path.isfile(file_path):
                    return jsonify({"error": "File not found"}), 404

                return send_file(
                    file_path,
                    as_attachment=download,
                    download_name=os.path.basename(file_path),
                )

            except Exception as e:
                print(f"Error in download_file: {e}", file=sys.stderr)
                print(traceback.format_exc(), file=sys.stderr)
                return jsonify({"error": str(e)}), 500

        @self.app.route("/api/squid/files", methods=["PUT"])
        def upload_files():
            """Upload files for a squid ID."""
            try:
                squid_id = request.form.get("squid_id")

                if not squid_id:
                    return jsonify({"error": "squid_id parameter required"}), 400

                if "files" not in request.files:
                    return jsonify({"error": "No files provided"}), 400

                squid_dir = os.path.join(self.cache_root, squid_id)
                os.makedirs(squid_dir, exist_ok=True)

                files = request.files.getlist("files")
                saved_files = []

                for file_obj in files:
                    if file_obj.filename:
                        filename = secure_filename(file_obj.filename)
                        file_path = os.path.join(squid_dir, filename)

                        # Ensure parent directories exist
                        os.makedirs(os.path.dirname(file_path), exist_ok=True)

                        file_obj.save(file_path)
                        saved_files.append(filename)

                return (
                    jsonify({"saved": saved_files, "count": len(saved_files)}),
                    200,
                )

            except Exception as e:
                print(f"Error in upload_files: {e}", file=sys.stderr)
                print(traceback.format_exc(), file=sys.stderr)
                return jsonify({"error": str(e)}), 500

        @self.app.route("/api/run", methods=["POST"])
        def run_simtool():
            """Execute a simtool and cache the results (for trusted users).

            This endpoint would typically be called by a trusted user process
            that can actually execute the simulation tool.
            """
            try:
                data = request.get_json()

                simtool_name = data.get("simtool_name")
                simtool_revision = data.get("simtool_revision")
                inputs = data.get("inputs", "")

                if not simtool_name or not simtool_revision:
                    return (
                        jsonify(
                            {
                                "error": "simtool_name and simtool_revision required"
                            }
                        ),
                        400,
                    )

                # This endpoint is a placeholder for future integration with
                # actual simulation execution. In a production system, this would:
                # 1. Queue the job for execution
                # 2. Execute the simulation
                # 3. Cache the results
                # 4. Return the squid_id

                squid_id = self._generate_squid_id(
                    simtool_name, simtool_revision, json.loads(inputs)
                )

                return jsonify({"success": True, "squid_id": squid_id}), 200

            except Exception as e:
                print(f"Error in run_simtool: {e}", file=sys.stderr)
                print(traceback.format_exc(), file=sys.stderr)
                return jsonify({"error": str(e)}), 500

        @self.app.route("/health", methods=["GET"])
        def health():
            """Health check endpoint."""
            return jsonify({"status": "healthy"}), 200

        @self.app.route("/", methods=["GET"])
        @self.app.route("/dashboard", methods=["GET"])
        def dashboard():
            """Web dashboard to browse cached data."""
            try:
                # Scan cache directory for squid IDs
                cached_entries = []
                
                if os.path.exists(self.cache_root):
                    # Scan for squid_id entries: tool_name/revision/input_hash
                    def scan_for_squid_ids(base_path, prefix=""):
                        entries = []
                        try:
                            for item in os.listdir(base_path):
                                item_path = os.path.join(base_path, item)
                                if os.path.isdir(item_path):
                                    current_prefix = f"{prefix}/{item}" if prefix else item
                                    
                                    # Check if this looks like a squid_id (has files in it)
                                    has_files = False
                                    files = []
                                    total_size = 0
                                    
                                    for root, dirs, filenames in os.walk(item_path):
                                        for fname in filenames:
                                            has_files = True
                                            fpath = os.path.join(root, fname)
                                            size = os.path.getsize(fpath)
                                            total_size += size
                                            files.append({
                                                "name": fname,
                                                "path": os.path.relpath(fpath, item_path),
                                                "size": size
                                            })
                                    
                                    if has_files:
                                        # This is a squid_id directory (has files)
                                        entries.append({
                                            "squid_id": current_prefix,
                                            "files": files,
                                            "file_count": len(files),
                                            "total_size": total_size
                                        })
                                    else:
                                        # Recursively scan subdirectories
                                        entries.extend(scan_for_squid_ids(item_path, current_prefix))
                        except Exception as e:
                            print(f"Error scanning {base_path}: {e}", file=sys.stderr)
                        
                        return entries
                    
                    cached_entries = scan_for_squid_ids(self.cache_root)
                
                # Format total size nicely
                def format_size(bytes_size):
                    for unit in ['B', 'KB', 'MB', 'GB']:
                        if bytes_size < 1024:
                            return f"{bytes_size:.1f} {unit}"
                        bytes_size /= 1024
                    return f"{bytes_size:.1f} TB"
                
                # Generate HTML
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
                            # Create a safe file ID for download
                            import base64
                            file_ref = f"{entry['squid_id']}:{file_info['path']}"
                            file_id = base64.b64encode(file_ref.encode()).decode()
                            
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
                        Cache root: """ + self.cache_root + """<br>
                        <a href="/health">/health</a> | 
                        <a href="https://localhost:5001/api/squid/id">API Docs</a>
                    </p>
                </body>
                </html>
                """
                
                return html, 200, {'Content-Type': 'text/html'}
            except Exception as e:
                print(f"Error in dashboard: {e}", file=sys.stderr)
                print(traceback.format_exc(), file=sys.stderr)
                return jsonify({"error": str(e)}), 500

    def _generate_squid_id(self, simtool_name, simtool_revision, inputs):
        """Generate a squid ID based on tool info and inputs.

        Args:
            simtool_name (str): Name of the simulation tool
            simtool_revision (str): Revision of the simulation tool
            inputs (dict): Input parameters

        Returns:
            str: The generated squid ID
        """
        # Create a hash of the inputs
        inputs_str = json.dumps(inputs, sort_keys=True)
        inputs_hash = hashlib.md5(inputs_str.encode()).hexdigest()

        # Format: simtool_name/simtool_revision/input_hash
        squid_id = f"{simtool_name}/{simtool_revision}/{inputs_hash}"
        return squid_id

    def _get_file_id(self, squid_id, file_name):
        """Generate a file ID from squid_id and file_name.

        Args:
            squid_id (str): The squid ID
            file_name (str): The file name

        Returns:
            str: A base64-encoded file ID
        """
        import base64

        file_ref = f"{squid_id}:{file_name}"
        return base64.b64encode(file_ref.encode()).decode()

    def _decode_file_id(self, file_id):
        """Decode a file ID to get squid_id and file_name.

        Args:
            file_id (str): The file ID

        Returns:
            tuple or None: (squid_id, file_name) or None if invalid
        """
        try:
            import base64

            decoded = base64.b64decode(file_id.encode()).decode()
            parts = decoded.split(":", 1)
            if len(parts) == 2:
                return tuple(parts)
        except Exception:
            pass
        return None

    def run(self):
        """Start the Flask development server."""
        print(f"Starting cache web server on {self.host}:{self.port}")
        print(f"Cache root: {self.cache_root}")
        self.app.run(host=self.host, port=self.port, debug=self.debug)


def create_app(cache_root=None):
    """Factory function to create a Flask app for the cache server.

    This is useful for production deployments with Gunicorn or similar.

    Args:
        cache_root (str, optional): Root directory for cache storage

    Returns:
        Flask: The Flask app
    """
    server = CacheWebServer(cache_root=cache_root)
    return server.app


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SimTool Cache Web Server")
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
        "--debug",
        action="store_true",
        help="Enable Flask debug mode",
    )

    args = parser.parse_args()

    server = CacheWebServer(
        cache_root=args.cache_root, host=args.host, port=args.port, debug=args.debug
    )
    server.run()
