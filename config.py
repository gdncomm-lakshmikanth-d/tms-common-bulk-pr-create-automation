#!/usr/bin/env python3
"""
Configuration file for Bulk Pull Request Creator

This file contains all configuration settings for the bulk PR creation script.
Modify the values below to customize the behavior of the script.
"""

# ============================================================================
# CHANGE RULES CONFIGURATION
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
    },
    {
        "file": "deployment/values.yaml",
        "type": "yaml",
        "changes": [
            # Remove tolerations only if it contains an item with key: role
            {
                "action": "delete_key",
                "path": "tolerations",
                "value": [{"key": "role"}]
            },
            # Remove affinity only if it has nodeAffinity
            {
                "action": "delete_key",
                "path": "affinity",
                "value": {"nodeAffinity": {}}
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
    #         },
    #         {
    #             "action": "update_key",
    #             "path": "config.database.host",  # Nested keys supported
    #             "value": "new-db-host.example.com"
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
    #         },
    #         {
    #             "action": "replace",
    #             "pattern": r"replicas:\s+\d+",
    #             "replacement": "replicas: 5"
    #         }
    #     ]
    # }
]

# ============================================================================
# REPOSITORY LIST
# ============================================================================

# List of repositories to process
# Format: owner/repo (e.g., "gdncomm/nonprod-deployment-gdn-tms-api")
# You can also use full GitHub URLs - they will be automatically normalized
REPOS = [
    "gdncomm/nonprod-deployment-gdn-osrm-backend"
]

# ============================================================================
# GIT & PR CONFIGURATION
# ============================================================================

# Default commit message
DEFAULT_COMMIT_MESSAGE = "chore: remove tolerations and affinity"

# PR title and body
DEFAULT_PR_TITLE = "Update gcp-jenkins-library to 2.2.6"
DEFAULT_PR_BODY = "Automated update of gcp-jenkins-library from version 2.2.5 to 2.2.6 in Jenkinsfile."

# Branch name for the feature branch
BRANCH_NAME = "update-jenkins-library-2.2.6"

# Base branch for PR (the branch the PR will be merged into)
# Set to None to use the repository's default branch (usually main or master)
# Set to a branch name (e.g., "qa2") to target a specific branch
DEFAULT_BASE_BRANCH = "qa2"  # Change to None to use default branch, or "qa2" to target qa2 branch

# Debug mode: if True, keep cloned repos in CLONE_DIR for inspection; if False, delete all clones after run.
DEBUG = False

# Clone directory: used when DEBUG is True or when --clone-dir is set. Set to None to use a temp dir when not debugging.
CLONE_DIR = "bulk_pr_clones"

# Whether to delete the clone directory after the run when using CLONE_DIR (overridden by DEBUG and --cleanup).
CLEANUP_CLONE_DIR = False

# ============================================================================
# CONFIGURATION NOTES
# ============================================================================
#
# Change Rule Types:
# - "text": Use for text files, Jenkinsfiles, or when you need regex pattern matching
# - "yaml" or "yml": Use for YAML files with structured updates
# - "json": Use for JSON files with structured updates
# - "env": Use for .env files
#
# Change Actions:
# - "replace": Use regex pattern matching to replace text (works with text, env types)
# - "update_key": Update a specific key in structured files (works with yaml, json types)
#
# Path Format for update_key:
# - Simple key: "image.tag"
# - Nested key: "config.database.host"
# - Array access: "jobs.build.steps[0].uses"
#
# Debug and clone directory:
# - DEBUG: True = keep clones in CLONE_DIR after run; False = delete all cloned repos after run.
# - CLONE_DIR: Path to store clones (e.g. "bulk_pr_clones"); set to None to use a temp dir when not debugging.
# - CLEANUP_CLONE_DIR: Legacy; cleanup is driven by DEBUG (and --cleanup / --no-debug).
#
# All values can be overridden via command-line arguments:
# - --repos-file: Use a file instead of REPOS from config.py (optional)
# - --clone-dir: Override clone directory
# - --debug / --no-debug: Override DEBUG (keep or delete clones after run)
# - --cleanup: Force delete clone directory after run
# - --commit-message: Override commit message
# - --pr-title: Override PR title
# - --pr-body: Override PR body
# - --branch: Override branch name
# - --base-branch: Override base branch
