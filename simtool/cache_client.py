# @package      hubzero-simtool
# @file         cache_client.py
# @copyright    Copyright (c) 2019-2021 The Regents of the University of California.
# @license      http://opensource.org/licenses/MIT MIT
# @trademark    HUBzero is a registered trademark of The Regents of the University of California.
#
"""HTTP cache client for communicating with the cache web server."""

import os
import sys
import json
import time
import requests
import traceback
from .cache_config import CacheConfig


class CacheClientException(Exception):
    """Exception raised by cache client operations."""
    pass


class CacheClient:
    """Client for interacting with the cache web server via HTTP.

    This class replaces the ionhelper shell scripts with HTTP-based communication
    to a web server cache system. It handles all cache operations including
    retrieving cached results, storing cache entries, and managing squid IDs.
    """

    def __init__(self, cache_server_url=None, auth_token=None, timeout=None):
        """Initialize the cache client.

        Args:
            cache_server_url (str, optional): The cache server URL. Uses environment
                variable or default if not provided.
            auth_token (str, optional): Authentication token for the cache server.
                Uses environment variable if not provided.
            timeout (int, optional): Request timeout in seconds. Uses default if not provided.
        """
        self.cache_server_url = (
            cache_server_url or CacheConfig.get_cache_server_url()
        ).rstrip("/")
        self.auth_token = auth_token or CacheConfig.get_auth_token()
        self.timeout = timeout or CacheConfig.REQUEST_TIMEOUT
        self.max_retries = CacheConfig.MAX_RETRIES
        self.retry_delay = CacheConfig.RETRY_DELAY

    def _get_headers(self):
        """Get request headers with authentication if available.

        Returns:
            dict: Request headers
        """
        headers = {"Content-Type": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers

    def _make_request(
        self, method, endpoint, data=None, files=None, params=None, retry=True
    ):
        """Make an HTTP request to the cache server.

        Args:
            method (str): HTTP method (GET, POST, PUT, DELETE)
            endpoint (str): API endpoint path (without base URL)
            data (dict, optional): JSON data to send
            files (dict, optional): Files to upload
            params (dict, optional): Query parameters
            retry (bool, optional): Whether to retry on failure

        Returns:
            requests.Response: The response object

        Raises:
            CacheClientException: If the request fails after retries
        """
        url = f"{self.cache_server_url}/{endpoint.lstrip('/')}"
        headers = self._get_headers()

        for attempt in range(self.max_retries):
            try:
                if method.upper() == "GET":
                    response = requests.get(
                        url,
                        headers=headers,
                        json=data,
                        params=params,
                        timeout=self.timeout,
                    )
                elif method.upper() == "POST":
                    response = requests.post(
                        url,
                        headers=headers,
                        json=data,
                        timeout=self.timeout,
                    )
                elif method.upper() == "PUT":
                    if files:
                        # Don't set Content-Type for multipart uploads
                        headers_copy = headers.copy()
                        del headers_copy["Content-Type"]
                        response = requests.put(
                            url,
                            headers=headers_copy,
                            data=data,
                            files=files,
                            timeout=self.timeout,
                        )
                    else:
                        response = requests.put(
                            url,
                            headers=headers,
                            json=data,
                            timeout=self.timeout,
                        )
                elif method.upper() == "DELETE":
                    response = requests.delete(
                        url, headers=headers, json=data, timeout=self.timeout
                    )
                else:
                    raise CacheClientException(f"Unsupported HTTP method: {method}")

                # If successful, return response
                if response.status_code < 400:
                    return response

                # If client error (4xx), don't retry
                if response.status_code < 500:
                    raise CacheClientException(
                        f"HTTP {response.status_code}: {response.text}"
                    )

                # If server error (5xx), retry
                if attempt < self.max_retries - 1 and retry:
                    print(
                        f"Server error (attempt {attempt + 1}/{self.max_retries}): "
                        f"HTTP {response.status_code}. Retrying in {self.retry_delay}s...",
                        file=sys.stderr,
                    )
                    time.sleep(self.retry_delay)
                else:
                    raise CacheClientException(
                        f"HTTP {response.status_code}: {response.text}"
                    )

            except requests.exceptions.Timeout:
                if attempt < self.max_retries - 1 and retry:
                    print(
                        f"Request timeout (attempt {attempt + 1}/{self.max_retries}). "
                        f"Retrying in {self.retry_delay}s...",
                        file=sys.stderr,
                    )
                    time.sleep(self.retry_delay)
                else:
                    raise CacheClientException(f"Request timeout: {url}")

            except requests.exceptions.ConnectionError as e:
                if attempt < self.max_retries - 1 and retry:
                    print(
                        f"Connection error (attempt {attempt + 1}/{self.max_retries}): {e}. "
                        f"Retrying in {self.retry_delay}s...",
                        file=sys.stderr,
                    )
                    time.sleep(self.retry_delay)
                else:
                    raise CacheClientException(f"Cannot connect to cache server: {url}")

            except requests.exceptions.RequestException as e:
                raise CacheClientException(f"Request failed: {e}")

        raise CacheClientException(f"Request failed after {self.max_retries} retries: {url}")

    def get_squid_id(self, simtool_name, simtool_revision, inputs):
        """Get the squid ID for a set of inputs.

        This replaces the squid ID lookup that was previously done via
        the ionhelper scripts.

        Args:
            simtool_name (str): Name of the simulation tool
            simtool_revision (str): Revision of the simulation tool
            inputs (dict): Input parameters for the simulation

        Returns:
            str: The squid ID for the given inputs

        Raises:
            CacheClientException: If the request fails
        """
        try:
            response = self._make_request(
                "GET",
                "api/squid/id",
                data={
                    "simtool_name": simtool_name,
                    "simtool_revision": simtool_revision,
                    "inputs": inputs,
                },
            )
            result = response.json()
            return result.get("id")
        except Exception as e:
            print(f"Error getting squid ID: {e}", file=sys.stderr)
            print(traceback.format_exc(), file=sys.stderr)
            raise

    def check_squid_exists(self, squid_id):
        """Check if a squid ID exists in the cache.

        Args:
            squid_id (str): The squid ID to check

        Returns:
            bool: True if the squid exists, False otherwise
        """
        try:
            response = self._make_request(
                "GET", "api/squid/exists", params={"squid_id": squid_id}
            )
            result = response.json()
            return result.get("exists", False)
        except Exception as e:
            print(f"Error checking squid existence: {e}", file=sys.stderr)
            return False

    def get_squid_files(self, squid_id):
        """Get the list of files for a squid ID.

        Args:
            squid_id (str): The squid ID

        Returns:
            list: List of file metadata dictionaries containing 'id' and 'name'

        Raises:
            CacheClientException: If the request fails
        """
        try:
            response = self._make_request(
                "GET", "api/squid/files", params={"squid_id": squid_id}
            )
            result = response.json()
            return result.get("files", [])
        except Exception as e:
            print(f"Error getting squid files: {e}", file=sys.stderr)
            print(traceback.format_exc(), file=sys.stderr)
            raise

    def download_file(self, file_id, output_path):
        """Download a cached file from the server.

        Args:
            file_id (str): The file ID
            output_path (str): Path where to save the file

        Raises:
            CacheClientException: If the download fails
        """
        try:
            url = f"{self.cache_server_url}/api/files/{file_id}"
            headers = self._get_headers()

            response = requests.get(
                url,
                headers=headers,
                params={"download": "true"},
                timeout=self.timeout,
                stream=True,
            )

            if response.status_code >= 400:
                raise CacheClientException(
                    f"HTTP {response.status_code}: Failed to download file {file_id}"
                )

            # Ensure output directory exists
            output_dir = os.path.dirname(output_path)
            if output_dir and not os.path.isdir(output_dir):
                os.makedirs(output_dir)

            # Write file
            with open(output_path, "wb") as fp:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        fp.write(chunk)

        except Exception as e:
            print(f"Error downloading file {file_id}: {e}", file=sys.stderr)
            print(traceback.format_exc(), file=sys.stderr)
            raise

    def upload_files(self, squid_id, file_dict):
        """Upload files to the cache server.

        Args:
            squid_id (str): The squid ID to associate with these files
            file_dict (dict): Dictionary mapping file names to file-like objects

        Raises:
            CacheClientException: If the upload fails
        """
        try:
            files = []
            for file_name, file_obj in file_dict.items():
                files.append(("files", (file_name, file_obj)))

            response = self._make_request(
                "PUT",
                "api/squid/files",
                data={"squid_id": squid_id},
                files=files,
            )

            if response.status_code >= 400:
                raise CacheClientException(
                    f"HTTP {response.status_code}: Failed to upload files"
                )

        except Exception as e:
            print(f"Error uploading files: {e}", file=sys.stderr)
            print(traceback.format_exc(), file=sys.stderr)
            raise

    def get_archived_result(self, squid_id, output_dir):
        """Retrieve archived results from cache for a given squid ID.

        This replaces the ionhelperGetArchivedSimToolResult.sh functionality.

        Args:
            squid_id (str): The squid ID
            output_dir (str): Directory where to extract the results

        Returns:
            bool: True if successful, False otherwise

        Raises:
            CacheClientException: If the request fails
        """
        try:
            print(f"Fetching cached result for squid ID: {squid_id}")

            # Get list of files for this squid ID
            files = self.get_squid_files(squid_id)

            if not files:
                print(f"No cached files found for squid ID: {squid_id}")
                return False

            # Create output directory if it doesn't exist
            if not os.path.isdir(output_dir):
                os.makedirs(output_dir)

            # Download each file
            for file_info in files:
                file_id = file_info.get("id")
                file_name = file_info.get("name")

                if not file_id or not file_name:
                    print(f"Invalid file info: {file_info}", file=sys.stderr)
                    continue

                # Handle nested paths (files stored with "_._" separator)
                if "_._" in file_name:
                    parts = file_name.split("_._")
                    file_path = os.path.join(output_dir, *parts)
                else:
                    file_path = os.path.join(output_dir, file_name)

                print(f"Downloading: {file_name}")
                self.download_file(file_id, file_path)

            return True

        except Exception as e:
            print(f"Error retrieving archived result: {e}", file=sys.stderr)
            print(traceback.format_exc(), file=sys.stderr)
            return False

    def store_result(self, squid_id, source_dir, file_list):
        """Store result files in the cache.

        This replaces the ionhelper caching functionality.

        Args:
            squid_id (str): The squid ID for this result
            source_dir (str): Source directory containing files to cache
            file_list (list): List of file paths to cache (relative to source_dir)

        Returns:
            bool: True if successful, False otherwise

        Raises:
            CacheClientException: If the upload fails
        """
        try:
            print(f"Storing result in cache for squid ID: {squid_id}")

            files_to_upload = {}

            for file_path in file_list:
                full_path = os.path.join(source_dir, file_path)

                if os.path.isdir(full_path):
                    # Handle directories by walking through them
                    for root, dirs, file_names in os.walk(full_path):
                        for file_name in file_names:
                            full_file_path = os.path.join(root, file_name)
                            rel_path = os.path.relpath(full_file_path, source_dir)
                            # Replace path separators with _._
                            cache_key = rel_path.replace(os.sep, "_._")
                            with open(full_file_path, "rb") as fp:
                                files_to_upload[cache_key] = fp.read()
                else:
                    if os.path.exists(full_path):
                        rel_path = os.path.relpath(full_path, source_dir)
                        cache_key = rel_path.replace(os.sep, "_._")
                        with open(full_path, "rb") as fp:
                            files_to_upload[cache_key] = fp.read()

            if not files_to_upload:
                print("No files to upload", file=sys.stderr)
                return False

            # Upload the files
            self.upload_files(squid_id, files_to_upload)
            print(f"Successfully stored {len(files_to_upload)} files in cache")
            return True

        except Exception as e:
            print(f"Error storing result: {e}", file=sys.stderr)
            print(traceback.format_exc(), file=sys.stderr)
            return False

    def run_simtool(self, simtool_name, simtool_revision, inputs_path):
        """Execute a simtool and retrieve results (trusted user mode).

        This replaces the ionhelperRunSimTool.sh functionality.

        Args:
            simtool_name (str): Name of the simulation tool
            simtool_revision (str): Revision of the simulation tool
            inputs_path (str): Path to the inputs YAML file

        Returns:
            dict: Result containing 'success' and 'squid_id' keys

        Raises:
            CacheClientException: If the request fails
        """
        try:
            with open(inputs_path, "r") as fp:
                inputs = fp.read()

            response = self._make_request(
                "POST",
                "api/run",
                data={
                    "simtool_name": simtool_name,
                    "simtool_revision": simtool_revision,
                    "inputs": inputs,
                },
            )

            result = response.json()
            return result

        except Exception as e:
            print(f"Error running simtool: {e}", file=sys.stderr)
            print(traceback.format_exc(), file=sys.stderr)
            raise
