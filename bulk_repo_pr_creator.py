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


# ============================================================================
# CONFIGURATION SECTION
# ============================================================================

# Define your change rules here
# Each rule specifies what file to modify and how to modify it
CHANGE_RULES = [
    {
        "file": "Jenkinsfile",
        "type": "text",
        "changes": [
            {
                "action": "replace",
                "pattern": r"@Library\('gcp-jenkins-library@2\.2\.5'\)",
                "replacement": "@Library('gcp-jenkins-library@2.2.6')"
            }
        ]
    }
    # Example: To modify deployment/qa2/values.yaml, add a rule like this:
    # {
    #     "file": "deployment/qa2/values.yaml",
    #     "type": "yaml",
    #     "changes": [
    #         {
    #             "action": "update_key",
    #             "path": "image.tag",  # Example: update image tag
    #             "value": "v1.2.3"
    #         },
    #         {
    #             "action": "update_key",
    #             "path": "replicaCount",  # Example: update replica count
    #             "value": 3
    #         }
    #     ]
    # },
    # Or for text replacement in YAML:
    # {
    #     "file": "deployment/qa2/values.yaml",
    #     "type": "text",
    #     "changes": [
    #         {
    #             "action": "replace",
    #             "pattern": r"image:\s+myapp:v1\.0\.0",
    #             "replacement": "image: myapp:v1.0.1"
    #         }
    #     ]
    # }
]

# Default commit message
DEFAULT_COMMIT_MESSAGE = "chore: update gcp-jenkins-library to 2.2.6"

# PR title and body
DEFAULT_PR_TITLE = "Update gcp-jenkins-library to 2.2.6"
DEFAULT_PR_BODY = "Automated update of gcp-jenkins-library from version 2.2.5 to 2.2.6 in Jenkinsfile."

# Branch name
BRANCH_NAME = "update-jenkins-library-2.2.6"

# Base branch for PR (the branch the PR will be merged into)
DEFAULT_BASE_BRANCH = None  # None means use default branch (main/master)
# To target qa2 branch, set: DEFAULT_BASE_BRANCH = "qa2"


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
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
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
    
    new_data = yaml.dump(data, sort_keys=True)
    if new_data != original_data:
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                yaml.dump(data, f, default_flow_style=False, sort_keys=False)
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


def create_branch(repo_path: Path, branch_name: str, dry_run: bool = False) -> bool:
    """
    Create and checkout a new branch.
    
    Args:
        repo_path: Path to the repository
        branch_name: Name of the branch to create
        dry_run: If True, skip actual branch creation
    
    Returns:
        True if successful
    """
    if dry_run:
        logger.info(f"[DRY RUN] Would create branch {branch_name}")
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
        
        # Checkout default branch first
        logger.debug(f"Checking out default branch: {default_branch}")
        run_command(
            ["git", "checkout", default_branch],
            cwd=str(repo_path),
            check=False,
            capture_output=True
        )
        
        # Pull latest changes
        run_command(
            ["git", "pull", "origin", default_branch],
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
            logger.info(f"Branch {branch_name} already exists locally, checking out...")
            run_command(["git", "checkout", branch_name], cwd=str(repo_path), check=True)
        else:
            # Check if branch exists remotely
            exit_code_remote, _, _ = run_command(
                ["git", "ls-remote", "--heads", "origin", branch_name],
                cwd=str(repo_path),
                check=False,
                capture_output=True
            )
            
            if exit_code_remote == 0:
                logger.info(f"Branch {branch_name} exists remotely, checking out and tracking...")
                run_command(
                    ["git", "checkout", "-b", branch_name, f"origin/{branch_name}"],
                    cwd=str(repo_path),
                    check=True
                )
            else:
                logger.info(f"Creating new branch {branch_name}...")
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


def create_pull_request(repo: str, branch_name: str, title: str, body: str, base_branch: Optional[str] = None, dry_run: bool = False) -> Optional[str]:
    """
    Create a pull request using GitHub CLI.
    
    Args:
        repo: Repository identifier (owner/repo)
        branch_name: Branch name for the PR
        title: PR title
        body: PR body
        base_branch: Base branch for the PR (None means use default branch)
        dry_run: If True, skip actual PR creation
    
    Returns:
        PR URL if successful, None otherwise
    """
    if dry_run:
        logger.info(f"[DRY RUN] Would create PR for {repo}")
        return None
    
    try:
        # Check if PR already exists for this branch
        cmd_check = [
            "gh", "pr", "list",
            "--repo", repo,
            "--head", branch_name,
            "--json", "url",
            "--limit", "1"
        ]
        exit_code, stdout, _ = run_command(cmd_check, check=False, capture_output=True)
        
        if exit_code == 0 and stdout.strip():
            try:
                pr_list = json.loads(stdout)
                if pr_list and len(pr_list) > 0:
                    pr_url = pr_list[0].get("url", "")
                    logger.info(f"PR already exists for {repo} branch {branch_name}: {pr_url}")
                    return pr_url
            except json.JSONDecodeError:
                pass  # Continue to create new PR
        
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
        return pr_url
    except Exception as e:
        logger.error(f"Failed to create PR for {repo}: {e}")
        return None


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
    
    try:
        # Clone repository
        repo_path = clone_repository(repo, clone_dir, dry_run)
        if not repo_path:
            result["status"] = "failed"
            result["error"] = "Failed to clone repository"
            return result
        
        # Create branch
        if not create_branch(repo_path, branch_name, dry_run):
            result["status"] = "failed"
            result["error"] = "Failed to create branch"
            return result
        
        # Apply file changes
        changes_made, modified_files = apply_file_changes(repo_path, rules)
        result["modified_files"] = modified_files
        
        if not changes_made:
            result["status"] = "skipped"
            result["skipped"] = True
            result["skipped_reason"] = "No changes were made"
            logger.info(f"Skipping {repo}: no changes made")
            return result
        
        # Commit changes
        if not commit_changes(repo_path, commit_message, dry_run):
            result["status"] = "skipped"
            result["skipped"] = True
            result["skipped_reason"] = "No changes to commit"
            return result
        
        # Push branch
        if not push_branch(repo_path, branch_name, dry_run):
            result["status"] = "failed"
            result["error"] = "Failed to push branch"
            return result
        
        # Create PR
        pr_url = create_pull_request(repo, branch_name, pr_title, pr_body, base_branch, dry_run)
        if not pr_url:
            result["status"] = "failed"
            result["error"] = "Failed to create pull request"
            return result
        
        result["pr_url"] = pr_url
        result["status"] = "success"
        return result
        
    except Exception as e:
        logger.error(f"Error processing {repo}: {e}")
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
        default="repos.txt",
        help="Path to file containing repository list (default: repos.txt)"
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
        help="Directory to clone repositories (default: temporary directory)"
    )
    parser.add_argument(
        "--base-branch",
        default=DEFAULT_BASE_BRANCH,
        help=f"Base branch for PRs (default: {DEFAULT_BASE_BRANCH or 'default branch'})"
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    if args.dry_run:
        logger.info("=" * 60)
        logger.info("DRY RUN MODE - No changes will be made")
        logger.info("=" * 60)
    
    # Read repositories
    repos = read_repos_file(args.repos_file)
    if not repos:
        logger.error(f"No repositories found in {args.repos_file}")
        sys.exit(1)
    
    logger.info(f"Found {len(repos)} repositories to process")
    
    # Setup clone directory
    if args.clone_dir:
        clone_dir = Path(args.clone_dir)
        clone_dir.mkdir(parents=True, exist_ok=True)
        cleanup_clone_dir = False
    else:
        clone_dir = Path(tempfile.mkdtemp(prefix="bulk_pr_creator_"))
        cleanup_clone_dir = True
        logger.info(f"Using temporary clone directory: {clone_dir}")
    
    # Process repositories
    results = []
    summary = defaultdict(int)
    
    for i, repo in enumerate(repos, 1):
        repo = normalize_repo_name(repo)
        logger.info("=" * 60)
        logger.info(f"Processing repository {i}/{len(repos)}: {repo}")
        logger.info("=" * 60)
        
        result = process_repository(
            repo=repo,
            rules=CHANGE_RULES,
            commit_message=args.commit_message,
            pr_title=args.pr_title,
            pr_body=args.pr_body,
            branch_name=args.branch,
            clone_dir=clone_dir,
            base_branch=args.base_branch,
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
        logger.info("Skipped repositories:")
        for result in results:
            if result["status"] == "skipped":
                logger.info(f"  - {result['repo']}: {result.get('skipped_reason', 'Unknown')}")
    
    if summary['failed'] > 0:
        logger.info("Failed repositories:")
        for result in results:
            if result["status"] == "failed":
                logger.error(f"  - {result['repo']}: {result.get('error', 'Unknown error')}")
    
    # Cleanup
    if cleanup_clone_dir and not args.dry_run:
        logger.info(f"Cleaning up temporary directory: {clone_dir}")
        shutil.rmtree(clone_dir, ignore_errors=True)
    
    # Exit with error code if any failures
    if summary['failed'] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
