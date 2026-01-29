#!/usr/bin/env python3
"""
Script to apply changes from a sample PR across multiple repos and create PRs.
Handles: Jenkins library upgrade, node auto-selector, Datadog/Signoz migration.
"""

import requests
import json
import sys
import os
import re
import subprocess
import tempfile
import shutil
import urllib3
import yaml
from urllib.parse import urljoin
from requests.auth import HTTPBasicAuth

# Configuration
BASE_URL = "https://stash.gdn-app.com/"
SAMPLE_PR_PROJECT = "DA"
SAMPLE_PR_REPO = "devops-poc"
SAMPLE_PR_ID = 6

# TARGET_PROJECT can be overridden via environment variable
TARGET_PROJECT = os.environ.get("STASH_PROJECT", "PROD-FULLFILLMENT-TMS")

SOURCE_BRANCH = os.environ.get("STASH_SOURCE_BRANCH", "enableDatadog")
TARGET_BRANCH = os.environ.get("STASH_TARGET_BRANCH", "master")

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
VERIFY_SSL = False

# Git configuration
GIT_AUTHOR_NAME = "Lakshmikanth D"
GIT_AUTHOR_EMAIL = "lakshmikanth.d@gdn-app.com"


def get_auth():
    """Get authentication credentials from config file or environment."""
    username = None
    password = None
    
    # Try to load from config file first (if it exists)
    try:
        # Check if there's a stash_config.py file
        if os.path.exists("stash_config.py"):
            import stash_config
            username = getattr(stash_config, "STASH_USERNAME", None)
            password = getattr(stash_config, "STASH_PASSWORD", None)
            if username and password:
                print(f"Using credentials from stash_config.py (user: {username})")
                return HTTPBasicAuth(username, password), username, password
    except ImportError:
        pass
    
    # Fall back to environment variables
    username = os.environ.get("STASH_USERNAME")
    password = os.environ.get("STASH_PASSWORD")
    
    if username and password:
        print(f"Using credentials from environment variables (user: {username})")
        return HTTPBasicAuth(username, password), username, password
    
    print("ERROR: Stash credentials not found!")
    print("Set credentials using one of these methods:")
    print("  1. Create stash_config.py with STASH_USERNAME and STASH_PASSWORD")
    print("  2. Set STASH_USERNAME and STASH_PASSWORD environment variables")
    print("\nExample stash_config.py:")
    print("  STASH_USERNAME = 'your-username'")
    print("  STASH_PASSWORD = 'your-password'")
    sys.exit(1)


def api_get(auth, endpoint):
    """Make GET request to Bitbucket API."""
    url = urljoin(BASE_URL, endpoint)
    try:
        response = requests.get(url, auth=auth, verify=VERIFY_SSL, timeout=30)
        return response
    except Exception as e:
        print(f"API Error: {e}")
        return None


def api_post(auth, endpoint, data):
    """Make POST request to Bitbucket API."""
    url = urljoin(BASE_URL, endpoint)
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(url, auth=auth, headers=headers, json=data, verify=VERIFY_SSL, timeout=30)
        return response
    except Exception as e:
        print(f"API Error: {e}")
        return None


def get_sample_pr_info(auth):
    """Get sample PR title and description."""
    endpoint = f"rest/api/1.0/projects/{SAMPLE_PR_PROJECT}/repos/{SAMPLE_PR_REPO}/pull-requests/{SAMPLE_PR_ID}"
    response = api_get(auth, endpoint)
    if response and response.status_code == 200:
        data = response.json()
        return {
            "title": data.get("title", "Enable Datadog & Node Auto-Selector"),
            "description": data.get("description", "")
        }
    return {"title": "Enable Datadog & Node Auto-Selector", "description": ""}


def get_sample_pr_diff(auth):
    """Get the diff from sample PR."""
    endpoint = f"rest/api/1.0/projects/{SAMPLE_PR_PROJECT}/repos/{SAMPLE_PR_REPO}/pull-requests/{SAMPLE_PR_ID}/diff"
    response = api_get(auth, endpoint)
    if response and response.status_code == 200:
        return response.json()
    print(f"Failed to fetch sample PR diff: {response.status_code if response else 'No response'}")
    return None


def get_sample_pr_changes(auth):
    """Get list of changed files from sample PR."""
    endpoint = f"rest/api/1.0/projects/{SAMPLE_PR_PROJECT}/repos/{SAMPLE_PR_REPO}/pull-requests/{SAMPLE_PR_ID}/changes"
    response = api_get(auth, endpoint)
    if response and response.status_code == 200:
        return response.json()
    return None


def get_file_content_from_pr(auth, file_path):
    """Get the new content of a file from the sample PR's source branch."""
    endpoint = f"rest/api/1.0/projects/{SAMPLE_PR_PROJECT}/repos/{SAMPLE_PR_REPO}/raw/{file_path}?at=refs/heads/{SOURCE_BRANCH}"
    response = api_get(auth, endpoint)
    if response and response.status_code == 200:
        return response.text
    return None


def get_repos_in_project(auth, project_key):
    """Get all repositories in a project."""
    repos = []
    start = 0
    limit = 100
    
    while True:
        endpoint = f"rest/api/1.0/projects/{project_key}/repos?start={start}&limit={limit}"
        response = api_get(auth, endpoint)
        
        if response and response.status_code == 200:
            data = response.json()
            repos.extend(data.get("values", []))
            if data.get("isLastPage", True):
                break
            start = data.get("nextPageStart", start + limit)
        else:
            break
    
    return repos


def clone_repo(username, password, project_key, repo_slug, target_dir, branch=None):
    """Clone a repository. If branch is specified, clone that branch."""
    # URL encode password for git URL
    encoded_password = requests.utils.quote(password, safe='')
    clone_url = f"https://{username}:{encoded_password}@stash.gdn-app.com/scm/{project_key}/{repo_slug}.git"
    
    try:
        # Clone without depth limit to allow branch operations
        clone_branch = branch if branch else TARGET_BRANCH
        result = subprocess.run(
            ["git", "clone", "-b", clone_branch, clone_url, target_dir],
            capture_output=True, text=True, timeout=180,
            env={**os.environ, "GIT_SSL_NO_VERIFY": "true"}
        )
        if result.returncode != 0:
            print(f"    Clone error: {result.stderr}")
            return False
        return True
    except Exception as e:
        print(f"    Clone exception: {e}")
        return False


def find_files(repo_dir, filename):
    """Find files matching a name in the repo."""
    matches = []
    for root, dirs, files in os.walk(repo_dir):
        # Skip hidden directories and common non-code directories
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['node_modules', 'vendor', 'target', 'build']]
        for file in files:
            if file == filename:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, repo_dir)
                matches.append(rel_path)
    return matches


def apply_jenkinsfile_changes(repo_dir, jenkinsfile_path):
    """Apply changes to Jenkinsfile - upgrade gcp-jenkins-library to 2.2.6."""
    full_path = os.path.join(repo_dir, jenkinsfile_path)
    
    try:
        with open(full_path, 'r') as f:
            content = f.read()
        
        original_content = content
        
        # Update gcp-jenkins-library to version 2.2.6
        # Pattern: @Library('gcp-jenkins-library@X.X.X') -> @Library('gcp-jenkins-library@2.2.6')
        pattern = r"@Library\(['\"]gcp-jenkins-library@[\d.]+['\"]\)"
        replacement = "@Library('gcp-jenkins-library@2.2.6')"
        
        if re.search(pattern, content):
            content = re.sub(pattern, replacement, content)
            print(f"      - Updated gcp-jenkins-library to 2.2.6")
        
        if content != original_content:
            with open(full_path, 'w') as f:
                f.write(content)
            return True
        return False
    except Exception as e:
        print(f"    Error modifying Jenkinsfile: {e}")
        return False


def get_indentation(line):
    """Get the indentation level of a line (number of leading spaces)."""
    return len(line) - len(line.lstrip())


def is_yaml_key(line):
    """Check if a line is a YAML key (word followed by colon)."""
    stripped = line.strip()
    # A YAML key starts with a word character and contains a colon
    # But not a list item (starts with -)
    if stripped.startswith("-"):
        return False
    return bool(re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*:', stripped))


def remove_yaml_block(lines, block_name):
    """Remove a YAML block and all its nested content, including list items."""
    result = []
    i = 0
    removed = False
    
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        
        # Check if this line starts the block we want to remove
        if stripped.startswith(f"{block_name}:"):
            block_indent = get_indentation(line)
            removed = True
            i += 1
            
            # Skip all lines that are part of this block
            while i < len(lines):
                next_line = lines[i]
                next_stripped = next_line.strip()
                
                # Empty lines - skip them (they're part of the block)
                if not next_stripped:
                    i += 1
                    continue
                
                next_indent = get_indentation(next_line)
                
                # If next line has greater indentation, it's nested - remove it
                if next_indent > block_indent:
                    i += 1
                    continue
                
                # If at same indentation level:
                if next_indent == block_indent:
                    # If it's a list item (starts with -), it's part of this block
                    if next_stripped.startswith("-"):
                        i += 1
                        continue
                    # If it's a new YAML key, the block is done
                    if is_yaml_key(next_line):
                        break
                    # Otherwise continue (could be continuation)
                    i += 1
                    continue
                
                # Lower indentation means block is definitely done
                break
        else:
            result.append(line)
            i += 1
    
    return result, removed


def remove_yaml_block_v2(content, block_name):
    """Remove a YAML block using line-by-line processing."""
    lines = content.split('\n')
    result = []
    i = 0
    removed = False
    
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        
        # Check if this line is the block we want to remove
        if stripped == f"{block_name}:" or stripped.startswith(f"{block_name}: "):
            block_indent = len(line) - len(line.lstrip())
            removed = True
            i += 1
            
            # Now skip all lines belonging to this block
            while i < len(lines):
                next_line = lines[i]
                
                # Empty line - could be part of block or separator, peek ahead
                if not next_line.strip():
                    # Look ahead to see if there's more block content
                    peek = i + 1
                    while peek < len(lines) and not lines[peek].strip():
                        peek += 1
                    if peek < len(lines):
                        peek_line = lines[peek]
                        peek_indent = len(peek_line) - len(peek_line.lstrip())
                        peek_stripped = peek_line.strip()
                        # If peek line is still part of block, skip empty line
                        if peek_indent > block_indent or (peek_indent == block_indent and peek_stripped.startswith('-')):
                            i += 1
                            continue
                    # Otherwise, empty line marks end of block
                    break
                
                next_indent = len(next_line) - len(next_line.lstrip())
                next_stripped = next_line.strip()
                
                # Lines with greater indentation are definitely part of the block
                if next_indent > block_indent:
                    i += 1
                    continue
                
                # Lines at same indentation that start with - are list items (part of block)
                if next_indent == block_indent and next_stripped.startswith('-'):
                    i += 1
                    continue
                
                # Lines at same indentation that don't start with - are new keys
                if next_indent <= block_indent and not next_stripped.startswith('-'):
                    break
                
                i += 1
            continue
        
        result.append(line)
        i += 1
    
    return '\n'.join(result), removed


def apply_values_yaml_changes(repo_dir, values_path):
    """Apply changes to values.yaml - remove tolerations/affinity, replace otel with datadog."""
    full_path = os.path.join(repo_dir, values_path)
    
    try:
        with open(full_path, 'r') as f:
            content = f.read()
        
        original_content = content
        changes_made = False
        
        # 1. Remove entire tolerations block (may need multiple passes for nested blocks)
        while True:
            content, removed = remove_yaml_block_v2(content, "tolerations")
            if removed:
                print(f"      - Removed tolerations block")
                changes_made = True
            else:
                break
        
        # 2. Remove entire affinity block
        while True:
            content, removed = remove_yaml_block_v2(content, "affinity")
            if removed:
                print(f"      - Removed affinity block")
                changes_made = True
            else:
                break
        
        # 3. Replace otel: with datadog: (keep the nested content like enabled: true)
        if re.search(r'^(\s*)otel:\s*$', content, re.MULTILINE):
            content = re.sub(r'^(\s*)otel:', r'\1datadog:', content, flags=re.MULTILINE)
            print(f"      - Replaced otel: with datadog:")
            changes_made = True
        
        # 4. Enable nodeAutoSelector if it exists and is false
        if re.search(r'nodeAutoSelector:\s*false', content):
            content = re.sub(r'nodeAutoSelector:\s*false', 'nodeAutoSelector: true', content)
            print(f"      - Set nodeAutoSelector: true")
            changes_made = True
        
        # Clean up excessive blank lines
        content = re.sub(r'\n{3,}', '\n\n', content)
        
        if changes_made:
            with open(full_path, 'w') as f:
                f.write(content)
            return True
        return False
    except Exception as e:
        print(f"    Error modifying values.yaml: {e}")
        import traceback
        traceback.print_exc()
        return False


def git_create_branch_and_commit(repo_dir, branch_name, commit_message, branch_exists=False):
    """Create branch (if needed), add changes, and commit."""
    env = {
        **os.environ,
        "GIT_SSL_NO_VERIFY": "true",
        "GIT_AUTHOR_NAME": GIT_AUTHOR_NAME,
        "GIT_AUTHOR_EMAIL": GIT_AUTHOR_EMAIL,
        "GIT_COMMITTER_NAME": GIT_AUTHOR_NAME,
        "GIT_COMMITTER_EMAIL": GIT_AUTHOR_EMAIL,
    }
    
    try:
        # Create and checkout new branch only if it doesn't exist
        if not branch_exists:
            result = subprocess.run(
                ["git", "checkout", "-b", branch_name],
                cwd=repo_dir, capture_output=True, text=True, env=env
            )
            if result.returncode != 0:
                print(f"    Branch creation error: {result.stderr}")
                return False
        
        # Add all changes
        result = subprocess.run(
            ["git", "add", "-A"],
            cwd=repo_dir, capture_output=True, text=True, env=env
        )
        
        # Check if there are changes to commit
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_dir, capture_output=True, text=True, env=env
        )
        if not result.stdout.strip():
            print(f"    No changes to commit")
            return False
        
        # Commit
        result = subprocess.run(
            ["git", "commit", "-m", commit_message],
            cwd=repo_dir, capture_output=True, text=True, env=env
        )
        if result.returncode != 0:
            print(f"    Commit error: {result.stderr}")
            return False
        
        return True
    except Exception as e:
        print(f"    Git error: {e}")
        return False


def git_push(repo_dir, username, password, project_key, repo_slug, branch_name, force=False):
    """Push branch to remote."""
    encoded_password = requests.utils.quote(password, safe='')
    push_url = f"https://{username}:{encoded_password}@stash.gdn-app.com/scm/{project_key}/{repo_slug}.git"
    
    env = {**os.environ, "GIT_SSL_NO_VERIFY": "true"}
    
    try:
        cmd = ["git", "push", push_url, branch_name]
        if force:
            cmd.insert(2, "--force")
        
        result = subprocess.run(
            cmd,
            cwd=repo_dir, capture_output=True, text=True, timeout=120, env=env
        )
        if result.returncode != 0:
            print(f"    Push error: {result.stderr}")
            return False
        return True
    except Exception as e:
        print(f"    Push exception: {e}")
        return False


def create_pr(auth, project_key, repo_slug, title, description, source_branch, target_branch):
    """Create a pull request."""
    endpoint = f"rest/api/1.0/projects/{project_key}/repos/{repo_slug}/pull-requests"
    
    pr_data = {
        "title": title,
        "description": description,
        "state": "OPEN",
        "open": True,
        "closed": False,
        "fromRef": {
            "id": f"refs/heads/{source_branch}",
            "repository": {
                "slug": repo_slug,
                "project": {"key": project_key}
            }
        },
        "toRef": {
            "id": f"refs/heads/{target_branch}",
            "repository": {
                "slug": repo_slug,
                "project": {"key": project_key}
            }
        }
    }
    
    response = api_post(auth, endpoint, pr_data)
    return response


def check_branch_exists(auth, project_key, repo_slug, branch_name):
    """Check if a branch already exists."""
    endpoint = f"rest/api/1.0/projects/{project_key}/repos/{repo_slug}/branches?filterText={branch_name}"
    response = api_get(auth, endpoint)
    if response and response.status_code == 200:
        branches = response.json().get("values", [])
        for branch in branches:
            if branch.get("displayId") == branch_name:
                return True
    return False


def delete_branch(auth, project_key, repo_slug, branch_name):
    """Delete a branch via Bitbucket API."""
    # First get the branch details to get the commit ID
    endpoint = f"rest/api/1.0/projects/{project_key}/repos/{repo_slug}/branches?filterText={branch_name}"
    response = api_get(auth, endpoint)
    
    if not response or response.status_code != 200:
        return False
    
    branches = response.json().get("values", [])
    branch_id = None
    for branch in branches:
        if branch.get("displayId") == branch_name:
            branch_id = branch.get("latestCommit")
            break
    
    if not branch_id:
        return False
    
    # Delete the branch
    delete_endpoint = f"rest/branch-utils/1.0/projects/{project_key}/repos/{repo_slug}/branches"
    delete_data = {
        "name": f"refs/heads/{branch_name}",
        "dryRun": False
    }
    
    url = urljoin(BASE_URL, delete_endpoint)
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.delete(url, auth=auth, headers=headers, json=delete_data, verify=VERIFY_SSL, timeout=30)
        return response.status_code in [200, 204]
    except Exception as e:
        print(f"    Error deleting branch: {e}")
        return False


def delete_branch_git(username, password, project_key, repo_slug, branch_name):
    """Delete a remote branch using git push."""
    encoded_password = requests.utils.quote(password, safe='')
    remote_url = f"https://{username}:{encoded_password}@stash.gdn-app.com/scm/{project_key}/{repo_slug}.git"
    
    try:
        # Delete remote branch by pushing empty ref
        result = subprocess.run(
            ["git", "push", remote_url, "--delete", branch_name],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "GIT_SSL_NO_VERIFY": "true"}
        )
        return result.returncode == 0
    except Exception as e:
        print(f"    Error deleting branch via git: {e}")
        return False


def check_existing_pr(auth, project_key, repo_slug, source_branch, target_branch):
    """Check if a PR already exists for the given branches."""
    endpoint = f"rest/api/1.0/projects/{project_key}/repos/{repo_slug}/pull-requests?state=OPEN"
    response = api_get(auth, endpoint)
    
    if response and response.status_code == 200:
        prs = response.json().get("values", [])
        for pr in prs:
            from_ref = pr.get("fromRef", {}).get("displayId", "")
            to_ref = pr.get("toRef", {}).get("displayId", "")
            if from_ref == source_branch and to_ref == target_branch:
                return pr.get("id")
    return None


def git_reset_to_master(repo_dir, username, password, project_key, repo_slug):
    """Reset current branch to master's content."""
    encoded_password = requests.utils.quote(password, safe='')
    remote_url = f"https://{username}:{encoded_password}@stash.gdn-app.com/scm/{project_key}/{repo_slug}.git"
    
    env = {**os.environ, "GIT_SSL_NO_VERIFY": "true"}
    
    try:
        # Fetch master
        result = subprocess.run(
            ["git", "fetch", remote_url, TARGET_BRANCH],
            cwd=repo_dir, capture_output=True, text=True, timeout=120, env=env
        )
        if result.returncode != 0:
            print(f"    Fetch error: {result.stderr}")
            return False
        
        # Reset to master
        result = subprocess.run(
            ["git", "reset", "--hard", "FETCH_HEAD"],
            cwd=repo_dir, capture_output=True, text=True, env=env
        )
        if result.returncode != 0:
            print(f"    Reset error: {result.stderr}")
            return False
        
        return True
    except Exception as e:
        print(f"    Git reset error: {e}")
        return False


def process_repo(auth, username, password, repo, pr_info, force_reset=False):
    """Process a single repository."""
    repo_slug = repo["slug"]
    repo_name = repo.get("name", repo_slug)
    
    print(f"\n  Processing: {repo_name}")
    
    # Check if branch already exists
    branch_exists = check_branch_exists(auth, TARGET_PROJECT, repo_slug, SOURCE_BRANCH)
    
    if branch_exists:
        print(f"    ℹ️  Branch '{SOURCE_BRANCH}' exists")
    
    # Create temp directory
    temp_dir = tempfile.mkdtemp(prefix=f"stash_{repo_slug}_")
    
    try:
        # Clone repo
        print(f"    Cloning repository...")
        if branch_exists:
            # Clone the existing branch
            if not clone_repo(username, password, TARGET_PROJECT, repo_slug, temp_dir, branch=SOURCE_BRANCH):
                return "failed", "Clone failed"
            
            # If force_reset, reset branch content to master
            if force_reset:
                print(f"    🔄 Resetting branch to master's content...")
                if not git_reset_to_master(temp_dir, username, password, TARGET_PROJECT, repo_slug):
                    return "failed", "Reset to master failed"
                print(f"    ✓ Branch reset to master")
        else:
            # Clone master
            if not clone_repo(username, password, TARGET_PROJECT, repo_slug, temp_dir, branch=TARGET_BRANCH):
                return "failed", "Clone failed"
        
        # Find and modify files
        changes_made = False
        
        # Find Jenkinsfile
        jenkinsfiles = find_files(temp_dir, "Jenkinsfile")
        for jf in jenkinsfiles:
            print(f"    Found Jenkinsfile: {jf}")
            if apply_jenkinsfile_changes(temp_dir, jf):
                print(f"    ✓ Updated {jf}")
                changes_made = True
        
        # Find values.yaml files
        values_files = find_files(temp_dir, "values.yaml")
        for vf in values_files:
            print(f"    Found values.yaml: {vf}")
            if apply_values_yaml_changes(temp_dir, vf):
                print(f"    ✓ Updated {vf}")
                changes_made = True
        
        if not changes_made:
            print(f"    ⚠️  No changes needed or no matching files found")
            return "skipped", "No changes needed"
        
        # Create branch (if needed) and commit
        print(f"    Committing changes...")
        commit_msg = "Enable nodeAutoSelector & switch to Datadog monitoring\n\n- Upgrade gcp-jenkins-library to 2.2.6\n- Enable nodeAutoSelector\n- Remove tolerations and affinity blocks\n- Replace otel with datadog"
        # Need new branch only if branch doesn't exist yet
        # If branch exists (even if we reset it), we're already on that branch
        need_new_branch = not branch_exists
        if not git_create_branch_and_commit(temp_dir, SOURCE_BRANCH, commit_msg, branch_exists=not need_new_branch):
            return "failed", "Commit failed"
        
        # Push (force push if we reset the branch)
        need_force_push = branch_exists and force_reset
        print(f"    Pushing branch{'(force)' if need_force_push else ''}...")
        if not git_push(temp_dir, username, password, TARGET_PROJECT, repo_slug, SOURCE_BRANCH, force=need_force_push):
            return "failed", "Push failed"
        
        # Check if PR already exists
        existing_pr_id = check_existing_pr(auth, TARGET_PROJECT, repo_slug, SOURCE_BRANCH, TARGET_BRANCH)
        if existing_pr_id:
            pr_url = f"{BASE_URL}projects/{TARGET_PROJECT}/repos/{repo_slug}/pull-requests/{existing_pr_id}"
            print(f"    ✅ PR already exists, updated branch: {pr_url}")
            return "success", f"{pr_url} (updated)"
        
        # Create PR
        print(f"    Creating PR...")
        response = create_pr(auth, TARGET_PROJECT, repo_slug, pr_info["title"], pr_info["description"], SOURCE_BRANCH, TARGET_BRANCH)
        
        if response and response.status_code == 201:
            pr_data = response.json()
            pr_id = pr_data.get("id")
            pr_url = f"{BASE_URL}projects/{TARGET_PROJECT}/repos/{repo_slug}/pull-requests/{pr_id}"
            print(f"    ✅ PR created: {pr_url}")
            return "success", pr_url
        elif response and response.status_code == 409:
            # PR might already exist or branches are up to date
            error_data = response.json() if response.text else {}
            error_msg = error_data.get("errors", [{}])[0].get("message", response.text[:200])
            print(f"    ⚠️  {error_msg}")
            return "skipped", error_msg
        else:
            error = response.text if response else "No response"
            print(f"    ❌ PR creation failed: {error[:200]}")
            return "failed", f"PR creation failed: {error[:200]}"
    
    finally:
        # Cleanup temp directory
        shutil.rmtree(temp_dir, ignore_errors=True)


def main():
    print("=" * 70)
    print("Bitbucket Server - Apply Changes & Create PRs")
    print("=" * 70)
    print(f"\nTarget Project: {TARGET_PROJECT}")
    print(f"Source Branch: {SOURCE_BRANCH}")
    print(f"Target Branch: {TARGET_BRANCH}")
    print(f"Sample PR: {SAMPLE_PR_PROJECT}/{SAMPLE_PR_REPO}/pull-requests/{SAMPLE_PR_ID}")
    print("=" * 70)
    
    # Get authentication
    auth, username, password = get_auth()
    
    # Test connection
    print("\n[1/4] Testing connection...")
    response = api_get(auth, "rest/api/1.0/projects")
    if not response or response.status_code != 200:
        print(f"  ❌ Connection failed: {response.status_code if response else 'No response'}")
        sys.exit(1)
    print("  ✅ Connection successful")
    
    # Get sample PR info
    print("\n[2/4] Fetching sample PR info...")
    pr_info = get_sample_pr_info(auth)
    print(f"  Title: {pr_info['title']}")
    
    # Get repos
    print(f"\n[3/4] Fetching repos in project '{TARGET_PROJECT}'...")
    repos = get_repos_in_project(auth, TARGET_PROJECT)
    print(f"  Found {len(repos)} repositories")
    
    if not repos:
        print("No repositories found. Exiting.")
        sys.exit(1)
    
    # List repos with numbers
    print("\n  Repositories:")
    for i, repo in enumerate(repos, 1):
        print(f"    {i:2d}. {repo['slug']}")
    
    # Select repositories
    auto_confirm = os.environ.get("STASH_AUTO_CONFIRM", "").lower() in ["yes", "y", "true", "1"]
    selected_repos = repos
    
    if not auto_confirm:
        print(f"\nSelect repositories to process:")
        print("  - Enter numbers separated by commas (e.g., 1,3,5)")
        print("  - Enter ranges (e.g., 1-5,10-15)")
        print("  - Enter 'all' to process all repositories")
        print("  - Enter 'none' or press Enter to abort")
        
        selection = input("\nYour selection: ").strip()
        
        if not selection or selection.lower() in ["none", "n", ""]:
            print("Aborted.")
            sys.exit(0)
        
        if selection.lower() == "all":
            selected_repos = repos
            print(f"\n✓ Selected all {len(repos)} repositories")
        else:
            # Parse selection (e.g., "1,3,5-10,15")
            selected_indices = set()
            parts = selection.split(',')
            
            for part in parts:
                part = part.strip()
                if '-' in part:
                    # Range (e.g., "5-10")
                    try:
                        start, end = map(int, part.split('-'))
                        selected_indices.update(range(start, end + 1))
                    except ValueError:
                        print(f"  ⚠️  Invalid range: {part}")
                else:
                    # Single number
                    try:
                        selected_indices.add(int(part))
                    except ValueError:
                        print(f"  ⚠️  Invalid number: {part}")
            
            # Filter repos (indices are 1-based in display, 0-based in list)
            selected_repos = [repos[i - 1] for i in selected_indices if 1 <= i <= len(repos)]
            
            if not selected_repos:
                print("  ❌ No valid repositories selected. Aborting.")
                sys.exit(0)
            
            print(f"\n✓ Selected {len(selected_repos)} repository/repositories:")
            for repo in selected_repos:
                print(f"    - {repo['slug']}")
    else:
        print("\n  Auto-confirming - processing all repositories...")
    
    # Check if force reset is enabled
    force_reset = os.environ.get("STASH_FORCE_RESET", "").lower() in ["yes", "y", "true", "1"]
    if force_reset:
        print("\n  ⚠️  FORCE RESET enabled - will delete and recreate branches from master")
    
    # Process repos
    print(f"\n[4/4] Processing {len(selected_repos)} repository/repositories...")
    results = {"success": [], "failed": [], "skipped": []}
    
    for repo in selected_repos:
        status, detail = process_repo(auth, username, password, repo, pr_info, force_reset=force_reset)
        results[status].append({"repo": repo["slug"], "detail": detail})
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total repositories processed: {len(selected_repos)}")
    print(f"✅ Success: {len(results['success'])}")
    print(f"❌ Failed: {len(results['failed'])}")
    print(f"⏭️  Skipped: {len(results['skipped'])}")
    
    if results['success']:
        print("\n✅ Created PRs:")
        for r in results['success']:
            print(f"  - {r['repo']}: {r['detail']}")
    
    if results['failed']:
        print("\n❌ Failed:")
        for r in results['failed']:
            print(f"  - {r['repo']}: {r['detail']}")
    
    if results['skipped']:
        print("\n⏭️  Skipped:")
        for r in results['skipped']:
            print(f"  - {r['repo']}: {r['detail']}")


if __name__ == "__main__":
    main()
