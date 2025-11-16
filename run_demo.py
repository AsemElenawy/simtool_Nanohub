#!/usr/bin/env python
"""Run the demo with an embedded cache server."""

import os
import sys
import time
import threading
import logging

# Suppress Flask logs
logging.getLogger('werkzeug').setLevel(logging.ERROR)

# Import the server and demo
from simtool.cache_web_server import CacheWebServer
from examples.demo_cache_write_read import example_workflow

def run_server(stop_event):
    """Run the cache server."""
    server = CacheWebServer(cache_root=None, host="127.0.0.1", port=5001, debug=False)
    try:
        server.app.run(host="127.0.0.1", port=5001, debug=False, use_reloader=False, 
                       threaded=True, use_evalex=False)
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    # Set environment variable
    os.environ["SIM2L_CACHE_SERVER_URL"] = "http://localhost:5001"
    
    # Start server in background thread
    stop_event = threading.Event()
    server_thread = threading.Thread(target=run_server, args=(stop_event,), daemon=True)
    server_thread.start()
    
    # Wait for server to start
    time.sleep(3)
    
    print("\n" + "="*70)
    print("Cache Server: READY")
    print("="*70 + "\n")
    
    try:
        # Run demo
        success = example_workflow()
        
        # Exit with proper code
        sys.exit(0 if success else 1)
    finally:
        stop_event.set()
        time.sleep(1)
