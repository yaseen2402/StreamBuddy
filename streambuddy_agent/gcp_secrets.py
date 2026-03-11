"""
Google Cloud Secret Manager Integration for StreamBuddy

This module provides functions to retrieve credentials from Google Cloud Secret Manager
for production deployments, with fallback to local .env file for development.

Requirements: 13.1, 13.2 (Security and Privacy)
"""

import os
import logging
import time
from typing import Optional, Dict, Tuple
from functools import lru_cache

# Try to import Google Cloud Secret Manager
try:
    from google.cloud import secretmanager
    SECRETMANAGER_AVAILABLE = True
except ImportError:
    SECRETMANAGER_AVAILABLE = False
    logging.warning("google-cloud-secret-manager not installed. Using .env file only.")

# Configure logging
logger = logging.getLogger(__name__)

# Cache configuration
DEFAULT_CACHE_TTL = 300  # 5 minutes in seconds
_cache: Dict[str, Tuple[str, float]] = {}  # {secret_name: (value, expiry_time)}


class SecretManagerClient:
    """Client for retrieving secrets from Google Cloud Secret Manager with caching"""
    
    def __init__(self, project_id: Optional[str] = None, cache_ttl: int = DEFAULT_CACHE_TTL):
        """
        Initialize Secret Manager client.
        
        Args:
            project_id: GCP project ID. If None, will try to get from environment.
            cache_ttl: Time-to-live for cached secrets in seconds (default: 300)
        """
        self.project_id = project_id or os.getenv('GCP_PROJECT_ID')
        self.client = None
        self.cache_ttl = cache_ttl
        
        if SECRETMANAGER_AVAILABLE and self.project_id:
            try:
                self.client = secretmanager.SecretManagerServiceClient()
                logger.info(f"Secret Manager client initialized for project: {self.project_id}")
            except Exception as e:
                logger.warning(f"Failed to initialize Secret Manager client: {e}")
                self.client = None
        else:
            if not SECRETMANAGER_AVAILABLE:
                logger.info("Secret Manager not available. Using environment variables only.")
            elif not self.project_id:
                logger.info("GCP_PROJECT_ID not set. Using environment variables only.")
    
    def _is_cache_valid(self, secret_name: str) -> bool:
        """
        Check if cached secret is still valid.
        
        Args:
            secret_name: Name of the secret
            
        Returns:
            True if cache entry exists and hasn't expired
        """
        if secret_name not in _cache:
            return False
        
        _, expiry_time = _cache[secret_name]
        return time.time() < expiry_time
    
    def _get_from_cache(self, secret_name: str) -> Optional[str]:
        """
        Get secret from cache if valid.
        
        Args:
            secret_name: Name of the secret
            
        Returns:
            Cached secret value or None if not in cache or expired
        """
        if self._is_cache_valid(secret_name):
            value, _ = _cache[secret_name]
            logger.debug(f"Retrieved {secret_name} from cache")
            return value
        return None
    
    def _store_in_cache(self, secret_name: str, value: str) -> None:
        """
        Store secret in cache with TTL.
        
        Args:
            secret_name: Name of the secret
            value: Secret value to cache
        """
        expiry_time = time.time() + self.cache_ttl
        _cache[secret_name] = (value, expiry_time)
        logger.debug(f"Cached {secret_name} with TTL {self.cache_ttl}s")
    
    @lru_cache(maxsize=10)
    def get_secret(self, secret_name: str, version: str = "latest", use_cache: bool = True) -> Optional[str]:
        """
        Retrieve a secret from Google Cloud Secret Manager with caching.
        
        Args:
            secret_name: Name of the secret to retrieve
            version: Version of the secret (default: "latest")
            use_cache: Whether to use cache (default: True)
        
        Returns:
            Secret value as string, or None if not found
        """
        # Check cache first if enabled
        if use_cache:
            cached_value = self._get_from_cache(secret_name)
            if cached_value is not None:
                return cached_value
        
        if not self.client or not self.project_id:
            logger.debug(f"Secret Manager not available. Cannot retrieve secret: {secret_name}")
            return None
        
        try:
            # Build the secret version name
            name = f"projects/{self.project_id}/secrets/{secret_name}/versions/{version}"
            
            # Access the secret version
            response = self.client.access_secret_version(request={"name": name})
            
            # Decode the secret payload
            secret_value = response.payload.data.decode('UTF-8')
            
            logger.info(f"Successfully retrieved secret: {secret_name}")
            
            # Store in cache if enabled
            if use_cache:
                self._store_in_cache(secret_name, secret_value)
            
            return secret_value
            
        except Exception as e:
            logger.error(f"Failed to retrieve secret '{secret_name}': {e}")
            return None
    
    def refresh_secret(self, secret_name: str, version: str = "latest") -> Optional[str]:
        """
        Force refresh a secret from Secret Manager, bypassing cache.
        
        Args:
            secret_name: Name of the secret to refresh
            version: Version of the secret (default: "latest")
            
        Returns:
            Refreshed secret value or None if not found
        """
        logger.info(f"Force refreshing secret: {secret_name}")
        
        # Remove from cache
        if secret_name in _cache:
            del _cache[secret_name]
        
        # Clear LRU cache for this method
        self.get_secret.cache_clear()
        
        # Fetch fresh value
        return self.get_secret(secret_name, version, use_cache=True)
    
    def clear_cache(self):
        """Clear the secret cache. Useful for testing or forcing refresh."""
        global _cache
        _cache.clear()
        self.get_secret.cache_clear()
        logger.info("Secret cache cleared")


# Global client instance
_secret_client: Optional[SecretManagerClient] = None


def get_secret_client() -> SecretManagerClient:
    """
    Get or create the global Secret Manager client instance.
    
    Returns:
        SecretManagerClient instance
    """
    global _secret_client
    if _secret_client is None:
        _secret_client = SecretManagerClient()
    return _secret_client


def get_credential(credential_name: str, env_var_name: Optional[str] = None) -> Optional[str]:
    """
    Retrieve a credential from Secret Manager or environment variable.
    
    This function implements a fallback strategy:
    1. Try to get from Secret Manager (production)
    2. Fall back to environment variable (development)
    
    Args:
        credential_name: Name of the secret in Secret Manager
        env_var_name: Name of the environment variable (defaults to credential_name.upper())
    
    Returns:
        Credential value as string, or None if not found
    """
    if env_var_name is None:
        env_var_name = credential_name.upper().replace('-', '_')
    
    # Try Secret Manager first (production)
    client = get_secret_client()
    secret_value = client.get_secret(credential_name)
    
    if secret_value:
        logger.debug(f"Retrieved {credential_name} from Secret Manager")
        return secret_value
    
    # Fall back to environment variable (development)
    env_value = os.getenv(env_var_name)
    
    if env_value:
        logger.debug(f"Retrieved {credential_name} from environment variable: {env_var_name}")
        return env_value
    
    logger.warning(f"Credential not found: {credential_name} (tried Secret Manager and {env_var_name})")
    return None


def get_gemini_api_key() -> Optional[str]:
    """
    Retrieve the Gemini API key.
    
    Returns:
        Gemini API key, or None if not found
    """
    return get_credential('gemini-api-key', 'GOOGLE_API_KEY')


def get_youtube_oauth_token() -> Optional[str]:
    """
    Retrieve the YouTube OAuth token.
    
    Returns:
        YouTube OAuth token, or None if not found
    """
    return get_credential('youtube-oauth-token', 'YOUTUBE_OAUTH_TOKEN')


def get_stream_mixer_config() -> Optional[str]:
    """
    Retrieve the stream mixer configuration.
    
    Returns:
        Stream mixer config (JSON string), or None if not found
    """
    return get_credential('stream-mixer-config', 'STREAM_MIXER_CONFIG')


def get_all_credentials() -> Dict[str, Optional[str]]:
    """
    Retrieve all required credentials for StreamBuddy.
    
    Returns:
        Dictionary mapping credential names to values
    """
    return {
        'gemini_api_key': get_gemini_api_key(),
        'youtube_oauth_token': get_youtube_oauth_token(),
        'stream_mixer_config': get_stream_mixer_config(),
    }


def validate_credentials() -> bool:
    """
    Validate that all required credentials are available.
    
    Returns:
        True if all credentials are available, False otherwise
    """
    credentials = get_all_credentials()
    
    missing = [name for name, value in credentials.items() if value is None]
    
    if missing:
        logger.error(f"Missing required credentials: {', '.join(missing)}")
        return False
    
    logger.info("All required credentials are available")
    return True


def refresh_credentials() -> Dict[str, Optional[str]]:
    """
    Force refresh all credentials from Secret Manager, bypassing cache.
    
    Returns:
        Dictionary mapping credential names to refreshed values
    """
    logger.info("Refreshing all credentials")
    
    client = get_secret_client()
    
    # Clear cache
    client.clear_cache()
    
    # Fetch fresh credentials
    return get_all_credentials()


def store_secret(secret_name: str, secret_value: str, project_id: Optional[str] = None) -> bool:
    """
    Store a secret in Google Cloud Secret Manager.
    
    This is a helper function for initial setup or credential rotation.
    
    Args:
        secret_name: Name of the secret to create/update
        secret_value: Value of the secret
        project_id: GCP project ID (optional, uses environment if not provided)
    
    Returns:
        True if successful, False otherwise
    """
    if not SECRETMANAGER_AVAILABLE:
        logger.error("Secret Manager library not available")
        return False
    
    project_id = project_id or os.getenv('GCP_PROJECT_ID')
    if not project_id:
        logger.error("GCP_PROJECT_ID not set")
        return False
    
    try:
        client = secretmanager.SecretManagerServiceClient()
        parent = f"projects/{project_id}"
        
        # Try to create the secret first
        try:
            secret = client.create_secret(
                request={
                    "parent": parent,
                    "secret_id": secret_name,
                    "secret": {
                        "replication": {"automatic": {}},
                    },
                }
            )
            logger.info(f"Created secret: {secret_name}")
        except Exception as e:
            # Secret might already exist, that's okay
            logger.debug(f"Secret might already exist: {e}")
        
        # Add a new version with the secret value
        secret_path = f"{parent}/secrets/{secret_name}"
        version = client.add_secret_version(
            request={
                "parent": secret_path,
                "payload": {"data": secret_value.encode('UTF-8')},
            }
        )
        
        logger.info(f"Added new version to secret: {secret_name}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to store secret '{secret_name}': {e}")
        return False


# Example usage
if __name__ == "__main__":
    # Configure logging for testing
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("StreamBuddy Secret Manager Integration Test")
    print("=" * 50)
    print()
    
    # Test credential retrieval
    print("Testing credential retrieval...")
    credentials = get_all_credentials()
    
    for name, value in credentials.items():
        if value:
            # Mask the value for security
            masked = value[:4] + "..." + value[-4:] if len(value) > 8 else "***"
            print(f"✓ {name}: {masked}")
        else:
            print(f"✗ {name}: NOT FOUND")
    
    print()
    
    # Validate all credentials
    print("Validating credentials...")
    if validate_credentials():
        print("✓ All credentials are available")
    else:
        print("✗ Some credentials are missing")
    
    print()
    print("Test complete")
