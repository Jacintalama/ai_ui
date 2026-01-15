"""
Database module for MCP Proxy tenant access lookups.

Uses PostgreSQL to store user-tenant access mappings.
This provides secure, database-backed access control instead of relying on
headers or token groups.
"""

import os
import asyncpg
from typing import Optional
from functools import lru_cache

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://openwebui:localdevpassword@postgresql:5432/openwebui")


def log(msg: str):
    """Debug logging."""
    print(f"[DB] {msg}")


_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    """Get or create database connection pool."""
    global _pool
    if _pool is None:
        log(f"Creating connection pool...")
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=1,
            max_size=10,
            command_timeout=30
        )
        log("Connection pool created")
    return _pool


async def get_user_tenants(email: str) -> list[str]:
    """
    Get list of tenant IDs the user has access to.

    Args:
        email: User's email address

    Returns:
        List of tenant IDs (e.g., ['Tenant-Google', 'github', 'filesystem'])
    """
    if not email:
        return []

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT tenant_id FROM user_tenant_access
                WHERE LOWER(user_email) = LOWER($1)
                """,
                email
            )
            tenants = [row['tenant_id'] for row in rows]
            log(f"User {email} has access to: {tenants}")
            return tenants
    except Exception as e:
        log(f"Error fetching tenants for {email}: {e}")
        return []


async def get_user_access_level(email: str, tenant_id: str) -> Optional[str]:
    """
    Get user's access level for a specific tenant.

    Args:
        email: User's email address
        tenant_id: Tenant ID to check

    Returns:
        Access level ('admin', 'read', etc.) or None if no access
    """
    if not email or not tenant_id:
        return None

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT access_level FROM user_tenant_access
                WHERE LOWER(user_email) = LOWER($1) AND tenant_id = $2
                """,
                email, tenant_id
            )
            return row['access_level'] if row else None
    except Exception as e:
        log(f"Error fetching access level: {e}")
        return None


async def user_has_tenant_access(email: str, tenant_id: str) -> bool:
    """
    Check if user has access to a specific tenant.

    Args:
        email: User's email address
        tenant_id: Tenant ID to check

    Returns:
        True if user has access, False otherwise
    """
    access_level = await get_user_access_level(email, tenant_id)
    return access_level is not None


async def add_user_tenant_access(email: str, tenant_id: str, access_level: str = 'read') -> bool:
    """
    Add tenant access for a user.

    Args:
        email: User's email address
        tenant_id: Tenant ID to grant access to
        access_level: Access level ('admin', 'read', etc.)

    Returns:
        True if added successfully, False otherwise
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO user_tenant_access (user_email, tenant_id, access_level)
                VALUES ($1, $2, $3)
                ON CONFLICT (user_email, tenant_id) DO UPDATE SET access_level = $3
                """,
                email, tenant_id, access_level
            )
            log(f"Added access: {email} -> {tenant_id} ({access_level})")
            return True
    except Exception as e:
        log(f"Error adding access: {e}")
        return False


async def close_pool():
    """Close the database connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        log("Connection pool closed")


# =============================================================================
# GROUP-TENANT MAPPING FUNCTIONS
# =============================================================================

async def get_tenants_from_groups(groups: list[str]) -> list[str]:
    """
    Get list of tenant IDs from group names.

    Args:
        groups: List of group names (e.g., ['Tenant-Google', 'MCP-GitHub'])

    Returns:
        List of unique tenant IDs the groups have access to
    """
    if not groups:
        return []

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            # Use ANY to match any of the provided groups
            rows = await conn.fetch(
                """
                SELECT DISTINCT tenant_id FROM group_tenant_mapping
                WHERE group_name = ANY($1)
                """,
                groups
            )
            tenants = [row['tenant_id'] for row in rows]
            log(f"Groups {groups} have access to: {tenants}")
            return tenants
    except Exception as e:
        log(f"Error fetching tenants from groups: {e}")
        return []


async def group_has_tenant_access(groups: list[str], tenant_id: str) -> bool:
    """
    Check if any of the groups has access to a specific tenant.

    Args:
        groups: List of group names
        tenant_id: Tenant ID to check

    Returns:
        True if any group has access, False otherwise
    """
    if not groups or not tenant_id:
        return False

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT 1 FROM group_tenant_mapping
                WHERE group_name = ANY($1) AND tenant_id = $2
                LIMIT 1
                """,
                groups, tenant_id
            )
            return row is not None
    except Exception as e:
        log(f"Error checking group tenant access: {e}")
        return False


async def add_group_tenant_mapping(group_name: str, tenant_id: str) -> bool:
    """
    Add a group-tenant mapping.

    Args:
        group_name: Group name (e.g., 'Tenant-Google')
        tenant_id: Tenant/server ID (e.g., 'github')

    Returns:
        True if added successfully, False otherwise
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO group_tenant_mapping (group_name, tenant_id)
                VALUES ($1, $2)
                ON CONFLICT (group_name, tenant_id) DO NOTHING
                """,
                group_name, tenant_id
            )
            log(f"Added group mapping: {group_name} -> {tenant_id}")
            return True
    except Exception as e:
        log(f"Error adding group mapping: {e}")
        return False


async def remove_group_tenant_mapping(group_name: str, tenant_id: str) -> bool:
    """
    Remove a group-tenant mapping.

    Args:
        group_name: Group name
        tenant_id: Tenant/server ID

    Returns:
        True if removed successfully, False otherwise
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                DELETE FROM group_tenant_mapping
                WHERE group_name = $1 AND tenant_id = $2
                """,
                group_name, tenant_id
            )
            log(f"Removed group mapping: {group_name} -> {tenant_id}")
            return True
    except Exception as e:
        log(f"Error removing group mapping: {e}")
        return False


async def get_all_group_mappings() -> dict[str, list[str]]:
    """
    Get all group-tenant mappings.

    Returns:
        Dictionary mapping group names to lists of tenant IDs
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT group_name, tenant_id FROM group_tenant_mapping
                ORDER BY group_name, tenant_id
                """
            )
            mappings = {}
            for row in rows:
                group = row['group_name']
                tenant = row['tenant_id']
                if group not in mappings:
                    mappings[group] = []
                mappings[group].append(tenant)
            return mappings
    except Exception as e:
        log(f"Error fetching all group mappings: {e}")
        return {}
