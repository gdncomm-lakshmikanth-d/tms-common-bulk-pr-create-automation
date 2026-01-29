#!/usr/bin/env python3
"""
Bulk Pull Request Creator for GitHub Repositories

This script automates the creation of pull requests across multiple GitHub repositories
by applying configurable file changes and creating PRs via GitHub CLI.

Requirements:
- GitHub CLI (gh) installed and authenticated
- Python 3.7+
- Access to all repositories listed in repos.txt
"""

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import yaml

# Import configuration from config.py
try:
    from config import (
        CHANGE_RULES,
        DEFAULT_COMMIT_MESSAGE,
        DEFAULT_PR_TITLE,
        DEFAULT_PR_BODY,
        BRANCH_NAME,
        DEFAULT_BASE_BRANCH,
    )
    CLONE_DIR = getattr(__import__("config"), "CLONE_DIR", None)
    CLEANUP_CLONE_DIR = getattr(__import__("config"), "CLEANUP_CLONE_DIR", False)
    DEBUG = getattr(__import__("config"), "DEBUG", True)
    GITHUB_ORG = getattr(__import__("config"), "GITHUB_ORG", None)
    GITHUB_TEAM = getattr(__import__("config"), "GITHUB_TEAM", None)
except ImportError:
    # Setup basic logging for error message
    logging.basicConfig(
        level=logging.ERROR,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    logger = logging.getLogger(__name__)
    logger.error("Configuration file 'config.py' not found. Please create it based on config.py.example")
    sys.exit(1)


# ============================================================================
# LOGGING SETUP
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def run_command(
    cmd: List[str],
    cwd: Optional[str] = None,
    check: bool = True,
    capture_output: bool = False,
    dry_run: bool = False
) -> Tuple[int, str, str]:
    """
    Execute a shell command and return the result.
    
    Args:
        cmd: Command to run as a list of strings
        cwd: Working directory for the command
        check: If True, raise exception on non-zero exit code
        capture_output: If True, capture stdout and stderr
        dry_run: If True, only log the command without executing
    
    Returns:
        Tuple of (exit_code, stdout, stderr)
    """
    if dry_run:
        logger.info(f"[DRY RUN] Would execute: {' '.join(cmd)}")
        return 0, "", ""
    
    logger.debug(f"Executing: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            check=False,
            capture_output=capture_output,
            text=True,
            timeout=300  # 5 minute timeout
        )
        stdout = result.stdout if capture_output else ""
        stderr = result.stderr if capture_output else ""
        
        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, cmd, stdout, stderr)
        
        return result.returncode, stdout, stderr
    except subprocess.TimeoutExpired:
        logger.error(f"Command timed out: {' '.join(cmd)}")
        raise
    except Exception as e:
        logger.error(f"Error executing command: {e}")
        raise


def read_repos_file(repos_file: str) -> List[str]:
    """
    Read repository URLs/names from a text file.
    
    Args:
        repos_file: Path to the repos.txt file
    
    Returns:
        List of repository identifiers (owner/repo format or full URLs)
    """
    repos = []
    if not os.path.exists(repos_file):
        logger.error(f"Repos file not found: {repos_file}")
        return repos
    
    try:
        with open(repos_file, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if line and not line.startswith('#'):
                    # Normalize repo format to owner/repo
                    if 'github.com' in line:
                        # Extract owner/repo from URL (handle .git suffix)
                        # Pattern: github.com[:/]owner/repo[.git][/...]
                        match = re.search(r'github\.com[:/]([\w\-\.]+)/([\w\-\.]+?)(?:\.git)?(?:/|$)', line)
                        if match:
                            repos.append(f"{match.group(1)}/{match.group(2)}")
                        else:
                            logger.warning(f"Could not parse GitHub URL on line {line_num}: {line}")
                    else:
                        # Validate owner/repo format
                        if '/' in line and len(line.split('/')) == 2:
                            repos.append(line)
                        else:
                            logger.warning(f"Invalid repository format on line {line_num}: {line} (expected owner/repo)")
    except Exception as e:
        logger.error(f"Error reading repos file {repos_file}: {e}")
    
    return repos


def _team_name_to_slug(team: str) -> str:
    """Convert team name to GitHub API team slug (lowercase, spaces to hyphens)."""
    slug = team.strip().lower().replace(" ", "-")
    # Keep only alphanumeric and hyphens (GitHub slugs are typically like 'tms-deployment-nonprod')
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    return slug or team.strip().lower().replace(" ", "-")


def list_repos_from_github_team(org: str, team: str) -> List[str]:
    """
    List repositories for a GitHub organization team using GitHub API.
    Uses: GET /orgs/{org}/teams/{team_slug}/repos
    
    Args:
        org: GitHub organization name (e.g., "gdncomm")
        team: Team name or slug (e.g., "TMS-DEPLOYMENT-NONPROD" or "tms-deployment-nonprod")
    
    Returns:
        List of repository identifiers in owner/repo format
    """
    slug = _team_name_to_slug(team)
    try:
        # gh api orgs/ORG/teams/SLUG/repos --paginate
        # With pagination we get multiple JSON arrays; -q '.[].full_name' gives one name per line per page
        exit_code, stdout, stderr = run_command(
            ["gh", "api", f"orgs/{org}/teams/{slug}/repos", "--paginate", "-q", ".[].full_name"],
            check=False,
            capture_output=True,
            dry_run=False
        )
        if exit_code != 0:
            logger.warning(f"Failed to list repos for team {team} (slug: {slug}): {stderr or stdout}")
            return []
        repos = [line.strip() for line in stdout.strip().split("\n") if line.strip()]
        return repos
    except Exception as e:
        logger.warning(f"Error listing repos for team {team}: {e}")
        return []


def list_repos_from_github_org(org: str) -> List[str]:
    """
    List repositories in a GitHub organization using gh CLI.
    
    Args:
        org: GitHub organization name (e.g., "gdncomm")
    
    Returns:
        List of repository identifiers in owner/repo format
    """
    try:
        # gh repo list ORG --limit 1000 --json nameWithOwner -q '.[].nameWithOwner'
        exit_code, stdout, stderr = run_command(
            ["gh", "repo", "list", org, "--limit", "1000", "--json", "nameWithOwner", "-q", ".[].nameWithOwner"],
            check=False,
            capture_output=True,
            dry_run=False
        )
        if exit_code != 0:
            logger.warning(f"Failed to list repos from org {org}: {stderr or stdout}")
            return []
        repos = [line.strip() for line in stdout.strip().split("\n") if line.strip()]
        return repos
    except Exception as e:
        logger.warning(f"Error listing repos from org {org}: {e}")
        return []


def select_repos_interactive(repos: List[str]) -> List[str]:
    """
    Display repositories with numbers and let user select which to process.
    
    Args:
        repos: Full list of repository identifiers (owner/repo)
    
    Returns:
        List of selected repository identifiers
    """
    if not repos:
        return []
    
    logger.info("")
    logger.info("Repositories:")
    for i, repo in enumerate(repos, 1):
        logger.info(f"  {i:3d}. {repo}")
    
    print("")
    print("Select repositories to process:")
    print("  - Enter numbers separated by commas (e.g., 1,3,5)")
    print("  - Enter ranges (e.g., 1-5,10-15)")
    print("  - Enter 'all' to process all repositories")
    print("  - Enter 'none' or press Enter to abort")
    print("")
    
    try:
        selection = input("Your selection: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("")
        return []
    
    if not selection or selection.lower() in ["none", "n", ""]:
        logger.info("Aborted.")
        return []
    
    if selection.lower() == "all":
        return repos
    
    # Parse selection (e.g., "1,3,5-10,15")
    selected_indices = set()
    for part in selection.split(","):
        part = part.strip()
        if "-" in part:
            try:
                start, end = map(int, part.split("-", 1))
                selected_indices.update(range(start, end + 1))
            except ValueError:
                logger.warning(f"Invalid range: {part}")
        else:
            try:
                selected_indices.add(int(part))
            except ValueError:
                logger.warning(f"Invalid number: {part}")
    
    selected = [repos[i - 1] for i in selected_indices if 1 <= i <= len(repos)]
    if not selected:
        logger.error("No valid repositories selected. Aborting.")
        return []
    
    logger.info(f"Selected {len(selected)} repository/repositories:")
    for repo in selected:
        logger.info(f"  - {repo}")
    return selected


def normalize_repo_name(repo: str) -> str:
    """
    Normalize repository identifier to owner/repo format.
    
    Args:
        repo: Repository identifier (URL or owner/repo)
    
    Returns:
        Normalized owner/repo string
    """
    if 'github.com' in repo:
        match = re.search(r'github\.com[:/]([\w\-\.]+)/([\w\-\.]+)', repo)
        if match:
            return f"{match.group(1)}/{match.group(2)}"
    return repo


# ============================================================================
# FILE MODIFICATION FUNCTIONS
# ============================================================================

def apply_text_replacements(file_path: Path, changes: List[Dict]) -> bool:
    """
    Apply text replacements to a file.
    
    Args:
        file_path: Path to the file
        changes: List of replacement rules
    
    Returns:
        True if any changes were made
    """
    if not file_path.exists():
        return False
    
    try:
        content = file_path.read_text(encoding='utf-8')
    except Exception as e:
        logger.warning(f"Failed to read {file_path}: {e}")
        return False
    
    original_content = content
    
    for change in changes:
        if change.get("action") == "replace":
            pattern = change.get("pattern", "")
            replacement = change.get("replacement", "")
            if pattern:
                content = re.sub(pattern, replacement, content)
    
    if content != original_content:
        try:
            file_path.write_text(content, encoding='utf-8')
            return True
        except Exception as e:
            logger.warning(f"Failed to write {file_path}: {e}")
            return False
    return False


def apply_json_changes(file_path: Path, changes: List[Dict]) -> bool:
    """
    Apply JSON modifications to a file.
    
    Args:
        file_path: Path to the JSON file
        changes: List of change rules
    
    Returns:
        True if any changes were made
    """
    if not file_path.exists():
        return False
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError, OSError) as e:
        logger.warning(f"Failed to read or parse JSON in {file_path}: {e}")
        return False
    
    original_data = json.dumps(data, sort_keys=True)
    
    for change in changes:
        if change.get("action") == "update_key":
            path = change.get("path", "")
            value = change.get("value")
            
            if path:
                keys = path.split('.')
                current = data
                
                # Navigate to the parent of the target key
                for key in keys[:-1]:
                    if isinstance(current, dict):
                        if key not in current:
                            current[key] = {}
                        current = current[key]
                    elif isinstance(current, list):
                        idx = int(key)
                        if idx >= len(current):
                            current.append({})
                        current = current[idx]
                    else:
                        logger.warning(f"Cannot navigate to {path} in JSON")
                        break
                else:
                    # Set the final key
                    final_key = keys[-1]
                    if isinstance(current, dict):
                        current[final_key] = value
    
    new_data = json.dumps(data, sort_keys=True)
    if new_data != original_data:
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write('\n')
            return True
        except (IOError, OSError) as e:
            logger.warning(f"Failed to write JSON to {file_path}: {e}")
            return False
    return False


def _yaml_values_equal(a: Any, b: Any) -> bool:
    """Compare two YAML-loaded values for equality (dict key order independent)."""
    try:
        # Round-trip through YAML to normalize (handles key order, type coercion)
        a_str = yaml.dump(a, sort_keys=True, default_flow_style=False)
        b_str = yaml.dump(b, sort_keys=True, default_flow_style=False)
        # Also try loading back in case of type differences (e.g. str vs int)
        try:
            a_norm = yaml.safe_load(a_str)
            b_norm = yaml.safe_load(b_str)
            return yaml.dump(a_norm, sort_keys=True) == yaml.dump(b_norm, sort_keys=True)
        except Exception:
            pass
        return a_str.strip() == b_str.strip()
    except Exception:
        return a == b


def _yaml_value_contains(current_val: Any, expected_pattern: Any) -> bool:
    """
    Check if current YAML value contains the expected pattern (partial matching).
    
    Supports:
    - For tolerations: Check if list contains an item with specific key (e.g., {"key": "role"})
    - For affinity: Check if dict contains a specific key (e.g., {"nodeAffinity": ...})
    
    Args:
        current_val: The current value from YAML
        expected_pattern: The pattern to match against
    
    Returns:
        True if pattern is found, False otherwise
    """
    try:
        # Case 1: Check if tolerations list contains an item with key "role"
        # Pattern: [{"key": "role"}] or [{"key": "role", ...}]
        if isinstance(expected_pattern, list) and len(expected_pattern) == 1:
            pattern_item = expected_pattern[0]
            if isinstance(pattern_item, dict) and "key" in pattern_item:
                # Check if current_val is a list and contains an item with matching key
                if isinstance(current_val, list):
                    for item in current_val:
                        if isinstance(item, dict) and item.get("key") == pattern_item.get("key"):
                            return True
                    return False
        
        # Case 2: Check if affinity dict contains nodeAffinity key
        # Pattern: {"nodeAffinity": ...}
        if isinstance(expected_pattern, dict) and "nodeAffinity" in expected_pattern:
            if isinstance(current_val, dict):
                return "nodeAffinity" in current_val
        
        # Default: fall back to exact match
        return _yaml_values_equal(current_val, expected_pattern)
    except Exception:
        return False


def delete_yaml_key_preserve_formatting(file_path: Path, key_name: str, expected_value: Optional[Any] = None) -> bool:
    """
    Delete a top-level YAML key using text-based approach to preserve file formatting.
    
    Args:
        file_path: Path to the YAML file
        key_name: Name of the top-level key to delete
        expected_value: If set, only delete if value matches exactly
    
    Returns:
        True if key was deleted, False otherwise
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except (IOError, OSError) as e:
        logger.warning(f"Failed to read {file_path}: {e}")
        return False
    
    # Check if key exists (allow leading whitespace so we match nested keys like "  tolerations:")
    key_pattern = rf'^\s*{re.escape(key_name)}\s*:'
    if not re.search(key_pattern, content, re.MULTILINE):
        return False  # Key doesn't exist
    
    # If expected_value is provided, verify structure matches (only when key is top-level)
    if expected_value is not None:
        try:
            data = yaml.safe_load(content) or {}
            if key_name in data:
                current_val = data[key_name]
                if not _yaml_value_contains(current_val, expected_value):
                    logger.info(
                        f"Key '{key_name}' in {file_path.name}: value does not contain expected pattern, skipping delete"
                    )
                    return False
            # If key not in data (e.g. nested), still proceed with text-based delete
        except Exception as e:
            logger.debug(f"Value check for '{key_name}' failed: {e}, attempting text delete")
    
    # Find the key and its value block using text-based approach
    lines = content.split('\n')
    result_lines = []
    i = 0
    deleted = False
    
    while i < len(lines):
        line = lines[i]
        
        # Check if this line starts the key we want to delete (at start of line or with leading whitespace)
        # Match: optional whitespace, key name, colon, optional whitespace, optional value
        key_match = re.match(rf'^(\s*){re.escape(key_name)}\s*:(.*)$', line)
        if key_match:
            indent = len(key_match.group(1))
            rest_of_line = key_match.group(2).strip()
            
            # This is the key to delete - skip it and its value
            deleted = True
            
            # Check if it's an inline value (has content after colon on same line)
            if rest_of_line and not rest_of_line.startswith('#'):
                # Inline value: key: value (skip just this line)
                i += 1
                continue
            
            # Block value: key: followed by indented content on next lines
            i += 1
            
            # Skip all lines that are more indented than the key, or list items at the same level
            # This handles nested structures like arrays and objects
            # Note: In YAML, list items at the same indentation as the key are part of the value
            while i < len(lines):
                next_line = lines[i]
                
                # Empty lines - include them in the block to delete
                if not next_line.strip():
                    i += 1
                    continue
                
                # Calculate indentation of next line
                next_indent = len(next_line) - len(next_line.lstrip())
                next_stripped = next_line.lstrip()
                
                # If next line is at same indentation and starts with '-' (list item), it's part of the value
                # Example: "tolerations:\n- key: role" - the list item is part of tolerations
                # SAFEGUARD: Only delete lines starting with '-' - other keys at same level are preserved
                if next_indent == indent and next_stripped.startswith('-'):
                    # This is a list item at the same level - delete it and its nested content
                    i += 1
                    # Continue to delete nested content of this list item
                    while i < len(lines):
                        nested_line = lines[i]
                        if not nested_line.strip():
                            i += 1
                            continue
                        nested_indent = len(nested_line) - len(nested_line.lstrip())
                        # Stop when we hit a line at same or less indentation as the list item
                        if nested_indent <= next_indent:
                            break
                        i += 1
                    # Continue to check if there are more list items at the same level
                    continue
                
                # If next line is at same or less indentation (and NOT a list item), we've reached the end
                # This could be another key (e.g., "affinity:") or end of file - stop deleting
                # SAFEGUARD: This ensures we never delete other keys at the same level
                if next_indent <= indent:
                    break
                
                i += 1
            continue
        
        result_lines.append(line)
        i += 1
    
    if deleted:
        # Write back with preserved formatting
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(result_lines))
                # Preserve trailing newline if original had it
                if content.endswith('\n'):
                    f.write('\n')
            return True
        except (IOError, OSError) as e:
            logger.warning(f"Failed to write {file_path}: {e}")
            return False
    
    return False


def apply_yaml_changes(file_path: Path, changes: List[Dict]) -> bool:
    """
    Apply YAML modifications to a file.
    
    Args:
        file_path: Path to the YAML file
        changes: List of change rules
    
    Returns:
        True if any changes were made
    """
    if not file_path.exists():
        return False
    
    # Check if we only have delete_key actions for top-level keys
    # If so, use text-based deletion to preserve formatting
    only_top_level_deletes = True
    has_updates = False
    
    for change in changes:
        if change.get("action") == "delete_key":
            path = change.get("path", "")
            # Check if it's a top-level key (no dots, no array notation)
            if '.' in path or '[' in path:
                only_top_level_deletes = False
                break
        elif change.get("action") == "update_key":
            has_updates = True
            only_top_level_deletes = False
            break
    
    # If only top-level deletes, use text-based approach to preserve formatting
    if only_top_level_deletes and not has_updates:
        any_deleted = False
        for change in changes:
            if change.get("action") == "delete_key":
                key_name = change.get("path", "")
                expected_value = change.get("value")
                if delete_yaml_key_preserve_formatting(file_path, key_name, expected_value):
                    any_deleted = True
        return any_deleted
    
    # Otherwise, use structured approach (for updates or nested deletes)
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            original_content = f.read()
            f.seek(0)
            data = yaml.safe_load(f) or {}
    except (yaml.YAMLError, IOError, OSError) as e:
        logger.warning(f"Failed to read or parse YAML in {file_path}: {e}")
        return False
    
    original_data = yaml.dump(data, sort_keys=True)
    
    for change in changes:
        if change.get("action") == "update_key":
            path = change.get("path", "")
            value = change.get("value")
            
            if path:
                # Handle array notation like "jobs.build.steps[0].uses"
                parts = re.split(r'\[(\d+)\]', path)
                keys = []
                for i, part in enumerate(parts):
                    if i % 2 == 0:
                        keys.extend(part.split('.'))
                    else:
                        keys.append(int(part))
                
                keys = [k for k in keys if k]  # Remove empty strings
                
                current = data
                # Navigate to the parent
                for key in keys[:-1]:
                    if isinstance(current, dict):
                        if key not in current:
                            current[key] = {}
                        current = current[key]
                    elif isinstance(current, list) and isinstance(key, int):
                        if key >= len(current):
                            current.append({})
                        current = current[key]
                    else:
                        logger.warning(f"Cannot navigate to {path} in YAML")
                        break
                else:
                    # Set the final key
                    final_key = keys[-1]
                    if isinstance(current, dict):
                        current[final_key] = value
                    elif isinstance(current, list) and isinstance(final_key, int):
                        if final_key < len(current):
                            current[final_key] = value
                        else:
                            current.append(value)
        elif change.get("action") == "delete_key":
            path = change.get("path", "")
            expected_value = change.get("value")  # If set, only delete when value matches exactly
            
            if path:
                # Handle array notation
                parts = re.split(r'\[(\d+)\]', path)
                keys = []
                for i, part in enumerate(parts):
                    if i % 2 == 0:
                        keys.extend(part.split('.'))
                    else:
                        keys.append(int(part))
                
                keys = [k for k in keys if k]  # Remove empty strings
                
                current = data
                # Navigate to the parent
                for key in keys[:-1]:
                    if isinstance(current, dict):
                        if key not in current:
                            # Key path doesn't exist, nothing to delete
                            break
                        current = current[key]
                    elif isinstance(current, list) and isinstance(key, int):
                        if key >= len(current):
                            # Index doesn't exist, nothing to delete
                            break
                        current = current[key]
                    else:
                        break
                else:
                    # Delete the final key (optionally only if value matches or contains pattern)
                    final_key = keys[-1]
                    if isinstance(current, dict) and final_key in current:
                        if expected_value is not None:
                            # Only delete if current value contains expected pattern (partial matching)
                            current_val = current[final_key]
                            if _yaml_value_contains(current_val, expected_value):
                                del current[final_key]
                        else:
                            del current[final_key]
                    elif isinstance(current, list) and isinstance(final_key, int) and final_key < len(current):
                        if expected_value is not None:
                            current_val = current[final_key]
                            if _yaml_value_contains(current_val, expected_value):
                                del current[final_key]
                        else:
                            del current[final_key]
    
    new_data = yaml.dump(data, sort_keys=True)
    if new_data != original_data:
        try:
            # Try to preserve original formatting by using ruamel.yaml if available
            # Otherwise fall back to PyYAML but try to match original indentation
            try:
                from ruamel.yaml import YAML as ruamel_yaml
                y = ruamel_yaml()
                y.preserve_quotes = True
                y.width = 4096  # Prevent line wrapping
                with open(file_path, 'r', encoding='utf-8') as f:
                    yaml_data = y.load(f)
                # Apply changes to ruamel data structure
                # (This is a simplified version - full implementation would need to replicate the logic)
                with open(file_path, 'w', encoding='utf-8') as f:
                    y.dump(data, f)
                return True
            except ImportError:
                # Fall back to PyYAML with best-effort formatting
                with open(file_path, 'w', encoding='utf-8') as f:
                    yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True, width=4096)
                return True
        except (IOError, OSError) as e:
            logger.warning(f"Failed to write YAML to {file_path}: {e}")
            return False
    return False


def apply_env_changes(file_path: Path, changes: List[Dict]) -> bool:
    """
    Apply changes to .env files.
    
    Args:
        file_path: Path to the .env file
        changes: List of change rules
    
    Returns:
        True if any changes were made
    """
    if not file_path.exists():
        return False
    
    try:
        content = file_path.read_text(encoding='utf-8')
    except Exception as e:
        logger.warning(f"Failed to read {file_path}: {e}")
        return False
    
    original_content = content
    
    for change in changes:
        if change.get("action") == "replace":
            pattern = change.get("pattern", "")
            replacement = change.get("replacement", "")
            if pattern:
                content = re.sub(pattern, replacement, content)
        elif change.get("action") == "update_key":
            key = change.get("path", "")
            value = change.get("value", "")
            if key:
                # Update or add key=value pair
                # Use word boundary to avoid partial matches (e.g., API_KEY matching API_KEY_VERSION)
                # Match key at start of line, followed by =, with optional whitespace
                pattern = rf'^{re.escape(key)}\s*=\s*.*$'
                replacement = f"{key}={value}"
                if re.search(pattern, content, re.MULTILINE):
                    content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
                else:
                    # Add new key if it doesn't exist
                    # Ensure content ends with newline before adding
                    if content and not content.endswith('\n'):
                        content += '\n'
                    content += f"{key}={value}\n"
    
    if content != original_content:
        try:
            file_path.write_text(content, encoding='utf-8')
            return True
        except Exception as e:
            logger.warning(f"Failed to write {file_path}: {e}")
            return False
    return False


def apply_file_changes(repo_path: Path, rules: List[Dict]) -> Tuple[bool, List[str]]:
    """
    Apply all configured changes to a repository.
    
    Args:
        repo_path: Path to the cloned repository
        rules: List of change rules
    
    Returns:
        Tuple of (changes_made, list_of_modified_files)
    """
    changes_made = False
    modified_files = []
    
    for rule in rules:
        file_path = repo_path / rule["file"]
        file_type = rule.get("type", "text")
        changes = rule.get("changes", [])
        
        if not file_path.exists():
            logger.debug(f"File not found: {file_path}, skipping")
            continue
        
        logger.info(f"Applying changes to {file_path}")
        
        try:
            modified = False
            if file_type == "json":
                modified = apply_json_changes(file_path, changes)
            elif file_type == "yaml" or file_type == "yml":
                modified = apply_yaml_changes(file_path, changes)
            elif file_type == "env":
                modified = apply_env_changes(file_path, changes)
            else:  # text, Jenkinsfile, etc.
                modified = apply_text_replacements(file_path, changes)
            
            if modified:
                changes_made = True
                modified_files.append(str(file_path.relative_to(repo_path)))
                logger.info(f"Modified: {file_path.name}")
        except Exception as e:
            logger.error(f"Error applying changes to {file_path}: {e}")
            continue
    
    return changes_made, modified_files


# ============================================================================
# GITHUB OPERATIONS
# ============================================================================

def clone_repository(repo: str, clone_dir: Path, dry_run: bool = False) -> Optional[Path]:
    """
    Clone a repository using GitHub CLI.
    
    Args:
        repo: Repository identifier (owner/repo)
        clone_dir: Directory to clone into
        dry_run: If True, skip actual cloning
    
    Returns:
        Path to cloned repository or None if failed
    """
    repo_name = repo.split('/')[-1]
    repo_path = clone_dir / repo_name
    
    if dry_run:
        logger.info(f"[DRY RUN] Would clone {repo} to {repo_path}")
        return repo_path
    
    # Check if already cloned and is a valid git repo
    if repo_path.exists():
        git_dir = repo_path / ".git"
        if git_dir.exists():
            logger.info(f"Repository already exists at {repo_path}, skipping clone")
            return repo_path
        else:
            logger.warning(f"Directory {repo_path} exists but is not a git repository, removing...")
            shutil.rmtree(repo_path, ignore_errors=True)
    
    try:
        logger.info(f"Cloning {repo}...")
        cmd = ["gh", "repo", "clone", repo, str(repo_path)]
        run_command(cmd, check=True, dry_run=False)
        return repo_path
    except Exception as e:
        logger.error(f"Failed to clone {repo}: {e}")
        return None


def create_branch(repo_path: Path, branch_name: str, base_branch: Optional[str] = None, dry_run: bool = False) -> bool:
    """
    Create and checkout a new branch.
    
    Args:
        repo_path: Path to the repository
        branch_name: Name of the branch to create
        base_branch: Branch to checkout and create from (e.g., "qa2", "preprod"). If None, uses default branch.
        dry_run: If True, check but don't actually create/checkout
    
    Returns:
        True if successful
    """
    if dry_run:
        # In dry-run, check if branch exists to give accurate message
        # But only if repo directory exists (might not be cloned in dry-run)
        if repo_path.exists() and (repo_path / ".git").exists():
            try:
                # Check if branch exists locally (read-only check)
                exit_code, _, _ = run_command(
                    ["git", "rev-parse", "--verify", branch_name],
                    cwd=str(repo_path),
                    check=False,
                    capture_output=True,
                    dry_run=False  # Execute this check even in dry-run
                )
                if exit_code == 0:
                    logger.info(f"[DRY RUN] Branch {branch_name} already exists locally, would checkout")
                    return True
                
                # Check if branch exists remotely (read-only check; ls-remote returns 0 with empty output when ref missing)
                _, stdout_remote, _ = run_command(
                    ["git", "ls-remote", "--heads", "origin", f"refs/heads/{branch_name}"],
                    cwd=str(repo_path),
                    check=False,
                    capture_output=True,
                    dry_run=False  # Execute this check even in dry-run
                )
                if stdout_remote.strip():
                    logger.info(f"[DRY RUN] Branch {branch_name} exists remotely, would checkout and track")
                    return True
                
                logger.info(f"[DRY RUN] Would create new branch {branch_name}")
            except Exception:
                # If we can't check, just show generic message
                logger.info(f"[DRY RUN] Would check/create branch {branch_name}")
        else:
            # Repo not cloned yet in dry-run, show generic message
            logger.info(f"[DRY RUN] Would check/create branch {branch_name}")
        return True
    
    try:
        # First, ensure we're on the default branch (usually main or master)
        # Fetch latest changes
        run_command(["git", "fetch", "origin"], cwd=str(repo_path), check=False, capture_output=True)
        
        # Get default branch name
        _, stdout, _ = run_command(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
            cwd=str(repo_path),
            check=False,
            capture_output=True
        )
        
        # Determine which branch to checkout (base_branch if provided, otherwise default branch)
        checkout_branch = base_branch
        if not checkout_branch:
            # Get default branch name
            default_branch = "main"
            if stdout.strip():
                default_branch = stdout.strip().split("/")[-1]
            else:
                # Fallback: try to determine default branch
                _, stdout, _ = run_command(
                    ["git", "branch", "-r", "--format", "%(refname:short)"],
                    cwd=str(repo_path),
                    check=False,
                    capture_output=True
                )
                branches = [b.strip() for b in stdout.strip().split("\n") if b.strip()]
                if "origin/main" in branches:
                    default_branch = "main"
                elif "origin/master" in branches:
                    default_branch = "master"
            checkout_branch = default_branch
        
        # Checkout the branch we'll create from (base_branch or default branch)
        logger.info(f"Checking out branch: {checkout_branch}")
        run_command(
            ["git", "checkout", checkout_branch],
            cwd=str(repo_path),
            check=False,
            capture_output=True
        )
        
        # Pull latest changes
        run_command(
            ["git", "pull", "origin", checkout_branch],
            cwd=str(repo_path),
            check=False,
            capture_output=True
        )
        
        # Check if branch already exists locally
        exit_code, _, _ = run_command(
            ["git", "rev-parse", "--verify", branch_name],
            cwd=str(repo_path),
            check=False,
            capture_output=True
        )
        
        if exit_code == 0:
            # Branch exists locally - delete it and recreate from current base branch
            # This ensures the branch is always based on the correct base branch
            # First, make sure we're not on the branch we want to delete
            _, current_branch, _ = run_command(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(repo_path),
                check=False,
                capture_output=True
            )
            if current_branch.strip() == branch_name:
                # We're on the branch we want to delete - switch to base branch first
                logger.info(f"Currently on {branch_name}, switching to {checkout_branch} before deletion...")
                run_command(["git", "checkout", checkout_branch], cwd=str(repo_path), check=False, capture_output=True)
            logger.info(f"Branch {branch_name} already exists locally, deleting and recreating from {checkout_branch}...")
            run_command(["git", "branch", "-D", branch_name], cwd=str(repo_path), check=False, capture_output=True)
        
        # Check if branch exists remotely (ls-remote returns 0 with empty output when ref missing)
        _, stdout_remote, _ = run_command(
            ["git", "ls-remote", "--heads", "origin", f"refs/heads/{branch_name}"],
            cwd=str(repo_path),
            check=False,
            capture_output=True
        )
        remote_branch_exists = bool(stdout_remote.strip())

        if remote_branch_exists:
            # Branch exists remotely - create local branch tracking remote
            logger.info(f"Branch {branch_name} exists remotely, creating local branch tracking remote...")
            run_command(
                ["git", "checkout", "-b", branch_name, f"origin/{branch_name}"],
                cwd=str(repo_path),
                check=True
            )
            # Reset to base branch to ensure we're working from the correct base
            # This ensures changes are applied relative to the current base branch, not the old one
            logger.info(f"Resetting branch {branch_name} to {checkout_branch} to ensure correct base...")
            run_command(
                ["git", "reset", "--hard", checkout_branch],
                cwd=str(repo_path),
                check=True
            )
            # Set upstream again after reset (reset might have removed tracking)
            run_command(
                ["git", "branch", "--set-upstream-to", f"origin/{branch_name}", branch_name],
                cwd=str(repo_path),
                check=False,
                capture_output=True
            )
        else:
            # Branch doesn't exist - create new branch from current base branch
            logger.info(f"Branch {branch_name} does not exist remotely, creating from {checkout_branch}...")
            run_command(["git", "checkout", "-b", branch_name], cwd=str(repo_path), check=True)
        
        return True
    except Exception as e:
        logger.error(f"Failed to create branch: {e}")
        return False


def commit_changes(repo_path: Path, commit_message: str, dry_run: bool = False) -> bool:
    """
    Commit changes to the repository.
    
    Args:
        repo_path: Path to the repository
        commit_message: Commit message
        dry_run: If True, skip actual commit
    
    Returns:
        True if successful
    """
    if dry_run:
        logger.info(f"[DRY RUN] Would commit changes with message: {commit_message}")
        return True
    
    try:
        # Check if there are any changes
        _, stdout, _ = run_command(
            ["git", "status", "--porcelain"],
            cwd=str(repo_path),
            check=False,
            capture_output=True
        )
        
        if not stdout.strip():
            logger.info("No changes to commit")
            return False
        
        logger.info("Staging changes...")
        run_command(["git", "add", "-A"], cwd=str(repo_path), check=True)
        
        logger.info(f"Committing changes: {commit_message}")
        run_command(
            ["git", "commit", "-m", commit_message],
            cwd=str(repo_path),
            check=True
        )
        
        return True
    except Exception as e:
        logger.error(f"Failed to commit changes: {e}")
        return False


def push_branch(repo_path: Path, branch_name: str, dry_run: bool = False) -> bool:
    """
    Push branch to remote.
    
    Args:
        repo_path: Path to the repository
        branch_name: Name of the branch to push
        dry_run: If True, skip actual push
    
    Returns:
        True if successful
    """
    if dry_run:
        logger.info(f"[DRY RUN] Would push branch {branch_name} to origin")
        return True
    
    try:
        logger.info(f"Pushing branch {branch_name} to origin...")
        run_command(
            ["git", "push", "-u", "origin", branch_name],
            cwd=str(repo_path),
            check=True
        )
        return True
    except Exception as e:
        logger.error(f"Failed to push branch: {e}")
        return False


def check_existing_pr(repo: str, branch_name: str, base_branch: Optional[str] = None, dry_run: bool = False) -> Optional[str]:
    """
    Check if an open PR exists for the given branch (head) and base branch.
    
    Args:
        repo: Repository identifier (owner/repo)
        branch_name: Head branch name (BRANCH_NAME)
        base_branch: Base branch to match (DEFAULT_BASE_BRANCH)
        dry_run: If True, still check but log as [DRY RUN]
    
    Returns:
        PR URL if exists with matching head and base branch, None otherwise
    """
    # Note: We still check in dry-run mode to show existing PRs in summary
    # PR checking is read-only, so we execute it even in dry-run mode
    
    try:
        # Check for open PRs with this branch as head
        cmd_check = [
            "gh", "pr", "list",
            "--repo", repo,
            "--head", branch_name,
            "--state", "open",
            "--json", "url,baseRefName"
        ]
        if dry_run:
            logger.debug(f"[DRY RUN] Checking for existing PR (read-only check): {' '.join(cmd_check)}")
        # Execute even in dry-run mode since it's a read-only operation
        exit_code, stdout, _ = run_command(cmd_check, check=False, capture_output=True, dry_run=False)
        
        if exit_code == 0 and stdout.strip():
            try:
                pr_list = json.loads(stdout)
                if pr_list and len(pr_list) > 0:
                    # Filter by base branch if specified
                    if base_branch:
                        for pr in pr_list:
                            if pr.get("baseRefName") == base_branch:
                                return pr.get("url", "")
                        # No PR found with matching base branch
                        return None
                    else:
                        # No base branch specified, return first open PR
                        return pr_list[0].get("url", "")
            except json.JSONDecodeError:
                pass
    except Exception as e:
        logger.debug(f"Error checking for existing PR: {e}")
    
    return None


def create_pull_request(repo: str, branch_name: str, title: str, body: str, base_branch: Optional[str] = None, dry_run: bool = False, update_existing: bool = False) -> Tuple[Optional[str], bool]:
    """
    Create a pull request using GitHub CLI.
    
    Args:
        repo: Repository identifier (owner/repo)
        branch_name: Branch name for the PR
        title: PR title
        body: PR body
        base_branch: Base branch for the PR (None means use default branch)
        dry_run: If True, skip actual PR creation
        update_existing: If True, allow updating existing PR branch
    
    Returns:
        Tuple of (PR URL if successful/existing, is_existing_pr)
    """
    if dry_run:
        logger.info(f"[DRY RUN] Would create PR for {repo}")
        return None
    
    try:
        # Check if PR already exists for this branch and base branch
        existing_pr_url = check_existing_pr(repo, branch_name, base_branch, dry_run)
        
        if existing_pr_url:
            if update_existing:
                logger.info(f"PR already exists for {repo} branch {branch_name}: {existing_pr_url}")
                logger.info("Returning existing PR URL (new commits will be added to this branch)")
                return existing_pr_url, True
            else:
                # This shouldn't happen if called correctly, but handle it
                return existing_pr_url, True
        
        logger.info(f"Creating pull request for {repo}...")
        cmd = [
            "gh", "pr", "create",
            "--repo", repo,
            "--head", branch_name,
            "--title", title,
            "--body", body
        ]
        if base_branch:
            cmd.extend(["--base", base_branch])
        _, stdout, _ = run_command(cmd, check=True, capture_output=True)
        pr_url = stdout.strip()
        logger.info(f"Successfully created PR for {repo}: {pr_url}")
        return pr_url, False
    except Exception as e:
        logger.error(f"Failed to create PR for {repo}: {e}")
        return None, False


# ============================================================================
# STEP PROGRESS DISPLAY
# ============================================================================

def step_progress(step_num: int, total: int, label: str, status: str = "...") -> None:
    """Print a single step progress line (e.g. '  [1/5] Clone ✓')."""
    logger.info(f"  [{step_num}/{total}] {label} {status}")


# ============================================================================
# MAIN PROCESSING FUNCTION
# ============================================================================

def process_repository(
    repo: str,
    rules: List[Dict],
    commit_message: str,
    pr_title: str,
    pr_body: str,
    branch_name: str,
    clone_dir: Path,
    base_branch: Optional[str] = None,
    update_existing_pr: bool = False,
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Process a single repository: clone, modify, commit, push, and create PR.
    
    Returns:
        Dictionary with processing results
    """
    result = {
        "repo": repo,
        "status": "unknown",
        "error": None,
        "modified_files": [],
        "skipped": False,
        "skipped_reason": None,
        "pr_url": None
    }
    
    TOTAL_STEPS = 5
    repo_short = repo.split("/")[-1] if "/" in repo else repo
    
    try:
        logger.info("")
        logger.info(f"  ┌─ {repo_short}")
        
        # Step 1: Clone
        step_progress(1, TOTAL_STEPS, "Clone", "...")
        repo_path = clone_repository(repo, clone_dir, dry_run)
        if not repo_path:
            step_progress(1, TOTAL_STEPS, "Clone", "✗ failed")
            result["status"] = "failed"
            result["error"] = "Failed to clone repository"
            return result
        step_progress(1, TOTAL_STEPS, "Clone", "✓")
        
        # Step 2: Branch
        step_progress(2, TOTAL_STEPS, "Branch", "...")
        if not create_branch(repo_path, branch_name, base_branch, dry_run):
            step_progress(2, TOTAL_STEPS, "Branch", "✗ failed")
            result["status"] = "failed"
            result["error"] = "Failed to create branch"
            return result
        step_progress(2, TOTAL_STEPS, "Branch", "✓")
        
        # Check if PR already exists (check before applying changes so we can show it even if no changes)
        existing_pr_url = check_existing_pr(repo, branch_name, base_branch, dry_run)
        if existing_pr_url:
            result["pr_url"] = existing_pr_url
        
        # Step 3: Changes (eligible or not, then apply if eligible)
        step_progress(3, TOTAL_STEPS, "Changes", "...")
        changes_made, modified_files = apply_file_changes(repo_path, rules)
        result["modified_files"] = modified_files
        
        if not changes_made:
            step_progress(3, TOTAL_STEPS, "Changes", "⊘ not eligible (no changes)")
            result["status"] = "skipped"
            result["skipped"] = True
            if existing_pr_url:
                result["skipped_reason"] = "No changes were made (PR already exists)"
            else:
                result["skipped_reason"] = "No changes were made"
            logger.info(f"  └─ Skipped")
            return result
        
        step_progress(3, TOTAL_STEPS, "Changes", f"✓ applied ({', '.join(modified_files) if modified_files else 'done'})")
        
        # Re-check PR in case it was created between initial check and now
        if not existing_pr_url:
            existing_pr_url = check_existing_pr(repo, branch_name, base_branch, dry_run)
            if existing_pr_url:
                result["pr_url"] = existing_pr_url
        
        # If PR exists and we're not updating, skip (don't commit)
        if existing_pr_url and not update_existing_pr:
            step_progress(4, TOTAL_STEPS, "Push", "⊘ skipped")
            step_progress(5, TOTAL_STEPS, "PR", "⊘ already exists")
            result["status"] = "skipped"
            result["skipped"] = True
            result["skipped_reason"] = "PR already exists (use --update-existing-pr to commit to existing branch)"
            result["pr_url"] = existing_pr_url
            logger.info(f"  └─ PR already exists")
            return result
        
        # Commit changes (to new branch or existing PR branch)
        if existing_pr_url and update_existing_pr:
            logger.info(f"  → Committing to existing PR")
        if not commit_changes(repo_path, commit_message, dry_run):
            result["status"] = "skipped"
            result["skipped"] = True
            result["skipped_reason"] = "No changes to commit"
            logger.info(f"  └─ No changes to commit")
            return result
        
        # Step 4: Push
        step_progress(4, TOTAL_STEPS, "Push", "...")
        if not push_branch(repo_path, branch_name, dry_run):
            step_progress(4, TOTAL_STEPS, "Push", "✗ failed")
            result["status"] = "failed"
            result["error"] = "Failed to push branch"
            return result
        step_progress(4, TOTAL_STEPS, "Push", "✓")
        
        # Step 5: PR
        step_progress(5, TOTAL_STEPS, "PR", "...")
        pr_url, is_existing = create_pull_request(
            repo, branch_name, pr_title, pr_body, base_branch, dry_run, update_existing_pr
        )
        
        if not pr_url:
            step_progress(5, TOTAL_STEPS, "PR", "✗ failed")
            result["status"] = "failed"
            result["error"] = "Failed to create pull request"
            return result
        
        result["pr_url"] = pr_url
        step_progress(5, TOTAL_STEPS, "PR", "✓")
        logger.info(f"      {pr_url}")
        result["status"] = "success"
        logger.info(f"  └─ Done")
        return result
        
    except Exception as e:
        logger.error(f"  └─ Error: {e}")
        result["status"] = "failed"
        result["error"] = str(e)
        return result


# ============================================================================
# MAIN FUNCTION
# ============================================================================

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Bulk Pull Request Creator for GitHub Repositories",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--repos-file",
        default=None,
        help="Path to file containing repository list (one owner/repo per line)"
    )
    parser.add_argument(
        "--org",
        nargs="?",
        default=None,
        const=GITHUB_ORG,
        metavar="ORG",
        help="List repos from GitHub org and then select. Use --org ORG (e.g., gdncomm) or --org to use GITHUB_ORG from config."
    )
    parser.add_argument(
        "--team",
        nargs="?",
        default=None,
        const=GITHUB_TEAM,
        metavar="TEAM",
        help="Filter by GitHub team: list only repos for this team (e.g., TMS-DEPLOYMENT-NONPROD). Requires --org. Use --team alone to use GITHUB_TEAM from config."
    )
    parser.add_argument(
        "--no-select",
        action="store_true",
        help="Process all repos without selection prompt (default: prompt to select when interactive)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform a dry run without making actual changes"
    )
    parser.add_argument(
        "--commit-message",
        default=DEFAULT_COMMIT_MESSAGE,
        help=f"Commit message (default: {DEFAULT_COMMIT_MESSAGE})"
    )
    parser.add_argument(
        "--pr-title",
        default=DEFAULT_PR_TITLE,
        help=f"PR title (default: {DEFAULT_PR_TITLE})"
    )
    parser.add_argument(
        "--pr-body",
        default=DEFAULT_PR_BODY,
        help=f"PR body (default: {DEFAULT_PR_BODY})"
    )
    parser.add_argument(
        "--branch",
        default=BRANCH_NAME,
        help=f"Branch name (default: {BRANCH_NAME})"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    parser.add_argument(
        "--clone-dir",
        help="Directory to clone repositories (default: CLONE_DIR from config or temporary directory)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        dest="debug",
        default=DEBUG,
        help="Keep cloned repos after run (override config DEBUG)"
    )
    parser.add_argument(
        "--no-debug",
        action="store_false",
        dest="debug",
        help="Delete all cloned repos after run (override config DEBUG)"
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Force delete clone directory after run"
    )
    parser.add_argument(
        "--base-branch",
        default=DEFAULT_BASE_BRANCH,
        help=f"Base branch for PRs (default: {DEFAULT_BASE_BRANCH or 'default branch'})"
    )
    parser.add_argument(
        "--update-existing-pr",
        action="store_true",
        help="If PR already exists, commit to the existing branch instead of skipping"
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    if args.dry_run:
        logger.info("=" * 60)
        logger.info("DRY RUN MODE - No changes will be made")
        logger.info("=" * 60)
    
    # Read repositories: default to org + team from config when no args
    use_org_mode = (args.org is not None or GITHUB_ORG) and not args.repos_file
    if use_org_mode:
        # List repos from GitHub org (--org or GITHUB_ORG from config), optionally filtered by team
        org = args.org if args.org is not None else GITHUB_ORG
        team = args.team if args.team is not None else GITHUB_TEAM
        if not org:
            logger.error("--org requires an org name (e.g., --org gdncomm) or set GITHUB_ORG in config.py")
            sys.exit(1)
        if team:
            logger.info(f"Listing repositories for team '{team}' in org: {org}")
            repos = list_repos_from_github_team(org, team)
            if not repos:
                logger.error(f"No repositories found for team {team} in org {org} (check team name/slug and 'gh auth status')")
                sys.exit(1)
            logger.info(f"Found {len(repos)} repositories for team {team}")
        else:
            logger.info(f"Listing repositories from GitHub org: {org}")
            repos = list_repos_from_github_org(org)
            if not repos:
                logger.error(f"No repositories found in org {org} (check 'gh auth status' and org name)")
                sys.exit(1)
            logger.info(f"Found {len(repos)} repositories in org {org}")
    elif args.repos_file:
        # Use file if specified
        repos = read_repos_file(args.repos_file)
        if not repos:
            logger.error(f"No repositories found in {args.repos_file}")
            sys.exit(1)
        logger.info(f"Using {len(repos)} repositories from {args.repos_file}")
    else:
        # No org and no repos file: need GITHUB_ORG in config or --org / --repos-file
        logger.error(
            "No repository source. Set GITHUB_ORG (and optionally GITHUB_TEAM) in config.py, "
            "or use --org ORG [--team TEAM], or --repos-file PATH."
        )
        sys.exit(1)
    
    # Interactive selection (unless --no-select or dry-run with no TTY)
    if not args.no_select and repos:
        selected = select_repos_interactive(repos)
        if not selected:
            sys.exit(0)
        repos = selected
        logger.info(f"Processing {len(repos)} selected repositories")
    else:
        logger.info(f"Found {len(repos)} repositories to process")
    
    # Debug: if True keep clones, if False delete after run (--debug / --no-debug override config)
    debug = args.debug
    if debug:
        logger.info("Debug mode: clones will be kept after run")
    else:
        logger.info("Debug off: clone directory will be deleted after run")

    # Setup clone directory; when debug is False, delete all clones after run
    if args.clone_dir:
        clone_dir = Path(args.clone_dir)
        clone_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Using clone directory: {clone_dir}")
    elif CLONE_DIR or debug:
        clone_dir = Path(CLONE_DIR if CLONE_DIR else "bulk_pr_clones")
        clone_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Using clone directory from config: {clone_dir}")
    else:
        clone_dir = Path(tempfile.mkdtemp(prefix="bulk_pr_creator_"))
        logger.info(f"Using temporary clone directory: {clone_dir}")
    cleanup_clone_dir = args.cleanup or (not debug)
    
    # Process repositories
    results = []
    summary = defaultdict(int)
    
    for i, repo in enumerate(repos, 1):
        repo = normalize_repo_name(repo)
        logger.info("=" * 60)
        logger.info(f"  [{i}/{len(repos)}] {repo}")
        
        result = process_repository(
            repo=repo,
            rules=CHANGE_RULES,
            commit_message=args.commit_message,
            pr_title=args.pr_title,
            pr_body=args.pr_body,
            branch_name=args.branch,
            clone_dir=clone_dir,
            base_branch=args.base_branch,
            update_existing_pr=args.update_existing_pr,
            dry_run=args.dry_run
        )
        
        results.append(result)
        summary[result["status"]] += 1
        
        if result["status"] == "success":
            logger.info(f"✓ Successfully processed {repo}")
        elif result["status"] == "skipped":
            logger.info(f"⊘ Skipped {repo}: {result.get('skipped_reason', 'Unknown reason')}")
        else:
            logger.error(f"✗ Failed to process {repo}: {result.get('error', 'Unknown error')}")
    
    # Print summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("SUMMARY REPORT")
    logger.info("=" * 60)
    logger.info(f"Total repositories: {len(repos)}")
    logger.info(f"Successful: {summary['success']}")
    logger.info(f"Skipped: {summary['skipped']}")
    logger.info(f"Failed: {summary['failed']}")
    logger.info("")
    
    # Detailed results
    if summary['success'] > 0:
        logger.info("Successful repositories:")
        pr_count = 0
        for result in results:
            if result["status"] == "success":
                pr_count += 1
                repo_name = result['repo']
                pr_url = result.get("pr_url")
                
                if pr_url:
                    logger.info(f"@PR {pr_count}: {repo_name}")
                    logger.info(f"    {pr_url}")
                else:
                    logger.info(f"  - {repo_name}")
                
                if result.get("modified_files"):
                    logger.info(f"    Modified files: {', '.join(result['modified_files'])}")
    
    if summary['skipped'] > 0:
        # Separate skipped repos with existing PRs from others
        skipped_with_prs = [r for r in results if r["status"] == "skipped" and r.get("pr_url")]
        skipped_others = [r for r in results if r["status"] == "skipped" and not r.get("pr_url")]
        
        if skipped_with_prs:
            logger.info("Skipped repositories (PR already exists):")
            for result in skipped_with_prs:
                repo_name = result['repo']
                pr_url = result.get("pr_url")
                logger.info(f"  - {repo_name}")
                logger.info(f"    Existing PR: {pr_url}")
        
        if skipped_others:
            logger.info("Skipped repositories:")
            for result in skipped_others:
                repo_name = result['repo']
                skipped_reason = result.get('skipped_reason', 'Unknown')
                logger.info(f"  - {repo_name}: {skipped_reason}")
    
    if summary['failed'] > 0:
        logger.info("Failed repositories:")
        for result in results:
            if result["status"] == "failed":
                logger.error(f"  - {result['repo']}: {result.get('error', 'Unknown error')}")
    
    # Cleanup: delete clone directory when debug is False or --cleanup
    if cleanup_clone_dir and not args.dry_run:
        logger.info(f"Cleaning up clone directory: {clone_dir}")
        shutil.rmtree(clone_dir, ignore_errors=True)
    
    # Exit with error code if any failures
    if summary['failed'] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
