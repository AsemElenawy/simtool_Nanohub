# @package      hubzero-simtool
# @file         cache_config.py
# @copyright    Copyright (c) 2019-2021 The Regents of the University of California.
# @license      http://opensource.org/licenses/MIT MIT
# @trademark    HUBzero is a registered trademark of The Regents of the University of California.
#
"""Configuration module for cache web server client."""

import os
import sys


class CacheConfig:
    """Configuration for cache web server connection."""

    # Default cache server URL - can be overridden via environment variable
    DEFAULT_CACHE_SERVER_URL = "http://localhost:5000"
    CACHE_SERVER_URL_ENV_VAR = "SIM2L_CACHE_SERVER_URL"

    # Default authentication token - can be overridden via environment variable
    CACHE_AUTH_TOKEN_ENV_VAR = "SIM2L_CACHE_AUTH_TOKEN"

    # Request timeout in seconds
    REQUEST_TIMEOUT = 30

    # Retry configuration
    MAX_RETRIES = 3
    RETRY_DELAY = 1  # seconds

    @classmethod
    def get_cache_server_url(cls):
        """Get the cache server URL from environment or use default.

        Returns:
            str: The cache server URL
        """
        return os.environ.get(cls.CACHE_SERVER_URL_ENV_VAR, cls.DEFAULT_CACHE_SERVER_URL)

    @classmethod
    def get_auth_token(cls):
        """Get the authentication token from environment.

        Returns:
            str or None: The authentication token if set, None otherwise
        """
        return os.environ.get(cls.CACHE_AUTH_TOKEN_ENV_VAR)

    @classmethod
    def set_cache_server_url(cls, url):
        """Set the cache server URL.

        Args:
            url (str): The cache server URL
        """
        os.environ[cls.CACHE_SERVER_URL_ENV_VAR] = url

    @classmethod
    def set_auth_token(cls, token):
        """Set the authentication token.

        Args:
            token (str): The authentication token
        """
        os.environ[cls.CACHE_AUTH_TOKEN_ENV_VAR] = token
