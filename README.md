# Bulk Pull Request Creator

A production-ready Python script that automates bulk Pull Request creation across multiple GitHub repositories by applying configurable file changes.

## Features

- ✅ Clone repositories using GitHub CLI (`gh`)
- ✅ Create branches and apply configurable file changes
- ✅ Support for YAML, JSON, ENV, Jenkinsfile, Helm values.yaml, GitHub Actions, and text files
- ✅ Flexible replacement rules (string replace, JSON key update, YAML key update)
- ✅ Automatic commit, push, and PR creation
- ✅ Skip repositories if target files don't exist
- ✅ Skip commits if no changes were made
- ✅ Continue processing on errors
- ✅ Dry-run mode for testing
- ✅ Comprehensive logging and summary reports
- ✅ Target specific base branches (e.g., qa2)
- ✅ All configuration in one place (`config.py`)

## Requirements

- Python 3.7+
- GitHub CLI (`gh`) installed and authenticated
- PyYAML library

## Quick Start

### 1. Install GitHub CLI

#### macOS
```bash
brew install gh
```

#### Linux (Ubuntu/Debian)
```bash
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
sudo chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
sudo apt update
sudo apt install gh
```

#### Linux (Fedora/RHEL)
```bash
sudo dnf install 'dnf-command(config-manager)'
sudo dnf config-manager --add-repo https://cli.github.com/packages/rpm/gh-cli.repo
sudo dnf install gh
```

#### Windows
Download and install from: https://cli.github.com/

### 2. Authenticate GitHub CLI

```bash
gh auth login
```

Follow the prompts to authenticate. You can choose:
- GitHub.com or GitHub Enterprise Server
- HTTPS or SSH protocol
- Browser(Recommended) or token authentication

Verify authentication:
```bash
gh auth status
```

### 3. Install Python Dependencies

Using a virtual environment (recommended):

```bash
python3 -m venv .venv
source .venv/bin/activate   # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Or with an existing venv:

```bash
pip install -r requirements.txt
```

### 4. Configure the Script

Edit `config.py` to customize:

**Repositories:**
```python
REPOS = [
    "owner1/repo1",
    "owner2/repo2",
]
```

**Change Rules:**
```python
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
]
```

**Base Branch (for PRs):**
```python
DEFAULT_BASE_BRANCH = "qa2"  # or None for default branch
```

### 5. Test with Dry Run

```bash
./bulk_repo_pr_creator.py --dry-run
```

This will show you what would happen without making any actual changes.

### 6. Run the Script

```bash
./bulk_repo_pr_creator.py
```

Or with verbose logging:
```bash
./bulk_repo_pr_creator.py --verbose
```

## Configuration Guide

All configuration is in `config.py`. Here's how to configure each section:

### Repository List

Add repositories to the `REPOS` list:

```python
REPOS = [
    "gdncomm/nonprod-deployment-gdn-tms-api",
    "gdncomm/nonprod-deployment-gdn-tms-authentication",
    # You can also use full URLs - they'll be normalized automatically
    # "https://github.com/owner/repo",
    # "git@github.com:owner/repo.git",
]
```

### Change Rules

Define what files to modify and how:

#### Text Replacement (Jenkinsfile, README, etc.)

```python
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
```

#### YAML Key Updates

```python
{
    "file": "deployment/qa2/values.yaml",
    "type": "yaml",
    "changes": [
        {
            "action": "update_key",
            "path": "image.tag",
            "value": "v1.2.3"
        },
        {
            "action": "update_key",
            "path": "replicaCount",
            "value": 3
        },
        {
            "action": "update_key",
            "path": "config.database.host",  # Nested keys
            "value": "new-db-host.example.com"
        },
        {
            "action": "update_key",
            "path": "jobs.build.steps[0].uses",  # Array access
            "value": "actions/checkout@v4"
        }
    ]
}
```

#### JSON Key Updates

```python
{
    "file": "package.json",
    "type": "json",
    "changes": [
        {
            "action": "update_key",
            "path": "dependencies.react",
            "value": "^18.0.0"
        }
    ]
}
```

#### Environment File Updates

```python
{
    "file": ".env.example",
    "type": "env",
    "changes": [
        {
            "action": "replace",
            "pattern": r"API_URL=https://api\.example\.com",
            "replacement": "API_URL=https://api.newdomain.com"
        },
        {
            "action": "update_key",
            "path": "API_VERSION",
            "value": "v2"
        }
    ]
}
```

### Git & PR Configuration

```python
# Commit message
DEFAULT_COMMIT_MESSAGE = "chore: update gcp-jenkins-library to 2.2.6"

# PR title and body
DEFAULT_PR_TITLE = "Update gcp-jenkins-library to 2.2.6"
DEFAULT_PR_BODY = "Automated update of gcp-jenkins-library from version 2.2.5 to 2.2.6 in Jenkinsfile."

# Feature branch name
BRANCH_NAME = "update-jenkins-library-2.2.6"

# Base branch for PRs (the branch PRs will target)
DEFAULT_BASE_BRANCH = "qa2"  # Set to None to use default branch (main/master)
```

## Usage

### Basic Usage

```bash
./bulk_repo_pr_creator.py
```

Uses all settings from `config.py`.

### Command Line Options

Override any configuration via command-line arguments:

```bash
./bulk_repo_pr_creator.py \
    --commit-message "chore: update dependencies" \
    --pr-title "Update Dependencies" \
    --pr-body "Automated dependency update" \
    --branch "update-deps" \
    --base-branch "main" \
    --verbose
```

**Available Options:**
- `--repos-file`: Use a file instead of REPOS from config.py (optional)
- `--dry-run`: Perform a dry run without making actual changes
- `--commit-message`: Override commit message
- `--pr-title`: Override PR title
- `--pr-body`: Override PR body
- `--branch`: Override branch name
- `--base-branch`: Override base branch
- `--update-existing-pr`: If PR already exists, commit to the existing branch instead of skipping
- `--verbose`: Enable verbose logging
- `--clone-dir`: Directory to clone repositories (default: from config or `bulk_pr_clones`)
- `--debug`: Keep cloned repos after run (override config)
- `--no-debug`: Delete all cloned repos after run (override config)
- `--cleanup`: Force delete clone directory after run

### Debug option (config and CLI)

In `config.py`, set **`DEBUG = True`** to keep cloned repos in `CLONE_DIR` for inspection after each run. Set **`DEBUG = False`** to delete all cloned repos after the run.

- **DEBUG = True** (default): Clones are kept in `bulk_pr_clones/` for debugging.
- **DEBUG = False**: Clone directory is removed after the run.

Override from the command line: use **`--no-debug`** to delete clones after this run, or **`--debug`** to keep them.

### Examples

**Dry Run (Test Mode):**
```bash
./bulk_repo_pr_creator.py --dry-run
```

**Target Different Base Branch:**
```bash
./bulk_repo_pr_creator.py --base-branch main
```

**Custom Branch Name:**
```bash
./bulk_repo_pr_creator.py --branch my-custom-branch
```

**Verbose Logging:**
```bash
./bulk_repo_pr_creator.py --verbose
```

**Update Existing PR (commit to existing branch):**
If a PR already exists and you have new changes to push, you **must** use `--update-existing-pr`; otherwise the script skips and does not commit:
```bash
./bulk_repo_pr_creator.py --update-existing-pr
```
Without this flag, the script will apply changes locally but skip commit/push when it finds an existing PR.

**Note:** If multiple open PRs exist for the same branch (rare but possible), the script will:
- Use the most recent open PR
- Log a warning about multiple PRs found
- Commit to that branch (which will update all PRs using that branch)

## How It Works

For each repository, the script:

1. ✅ Clones the repository using `gh repo clone`
2. ✅ Fetches latest changes and checks out the default branch
3. ✅ Creates a new feature branch (or checks out existing)
4. ✅ Applies configured file changes
5. ✅ Commits changes (if any modifications were made)
6. ✅ Pushes branch to origin
7. ✅ Creates a Pull Request targeting the specified base branch
8. ✅ Continues to next repository (even if one fails)

## Output

The script provides:

1. **Real-time logging**: Progress for each repository
2. **Summary report**: Counts of successful, skipped, and failed repositories
3. **Detailed results**: Lists of modified files, PR URLs, and error messages

Example output:
```
================================================================
SUMMARY REPORT
================================================================
Total repositories: 2
Successful: 2
Skipped: 0
Failed: 0

Successful repositories:
@PR 1: gdncomm/nonprod-deployment-gdn-tms-api
    https://github.com/gdncomm/nonprod-deployment-gdn-tms-api/pull/123
    Modified files: Jenkinsfile
@PR 2: gdncomm/nonprod-deployment-gdn-tms-authentication
    https://github.com/gdncomm/nonprod-deployment-gdn-tms-authentication/pull/456
    Modified files: Jenkinsfile
```

## Error Handling

The script is designed to be resilient:

- **Missing files**: If a target file doesn't exist, the rule is skipped for that repository
- **No changes**: If no changes are made, the commit and PR creation are skipped (no unnecessary commits)
- **Individual failures**: If one repository fails, processing continues with others
- **Comprehensive logging**: All operations are logged with clear error messages
- **Existing PRs**: 
  - By default: If PR already exists (checks for open PRs only), the repository is skipped
  - With `--update-existing-pr`: If PR exists, new commits are added to the existing branch
  - **Multiple PRs**: If multiple open PRs exist for the same branch, uses the most recent one and logs a warning

## Troubleshooting

### GitHub CLI Not Authenticated

```bash
gh auth login
gh auth status
```

### GitHub CLI Not Installed

See [Quick Start](#1-install-github-cli) section above for installation instructions.

### PyYAML Not Installed

```bash
pip install PyYAML
# or
pip install -r requirements.txt
```

### Permission Denied

Make the script executable:
```bash
chmod +x bulk_repo_pr_creator.py
```

### Repository Access Issues

Ensure you have access to all repositories listed in `config.py`. Private repositories require appropriate permissions.

Check access:
```bash
gh repo view owner/repo
```

### No Changes Detected

If the target file already has the expected values, the script will skip the commit. This is expected behavior.

### Using --update-existing-pr but Still No Commit

If one repo has changes to apply but the script skips without committing:

1. **Value match for delete_key**: When deleting YAML keys with an expected `value`, the current file value must match. If you see "value does not match expected config, skipping delete", the file content differs (e.g. extra keys, different formatting). Either align the file with the expected config, or remove the `"value"` from that rule in `config.py` to delete the key whenever it exists (no value check).
2. **Run with --verbose**: Use `./bulk_repo_pr_creator.py --update-existing-pr --verbose` to see why a key was or wasn’t deleted.

### Branch Already Exists

The script handles existing branches gracefully:
- If branch exists locally, it checks it out
- If branch exists remotely, it tracks and checks it out
- If branch has commits, new changes are added on top

## Best Practices

1. **Always test with `--dry-run` first** to verify your configuration
2. **Start with a small subset** of repositories to test
3. **Review the CHANGE_RULES** carefully before running
4. **Use descriptive commit messages** and PR titles
5. **Monitor the summary report** for any failures
6. **Keep config.py in version control** for tracking changes

## File Structure

```
tms-common-bulk-pr-create-automation/
├── bulk_repo_pr_creator.py  # Main script (logic)
├── config.py                # Configuration file
├── requirements.txt         # Python dependencies
├── README.md                # This file
└── .gitignore               # Git ignore rules
```

## Configuration File Reference

All configuration is in `config.py`:

- `CHANGE_RULES`: List of file modification rules
- `REPOS`: List of repositories to process
- `DEFAULT_COMMIT_MESSAGE`: Default commit message
- `DEFAULT_PR_TITLE`: Default PR title
- `DEFAULT_PR_BODY`: Default PR body
- `BRANCH_NAME`: Feature branch name
- `DEFAULT_BASE_BRANCH`: Base branch for PRs (None = default branch)

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review the configuration in `config.py`
3. Run with `--verbose` flag for detailed logging
4. Test with `--dry-run` to see what would happen

## License

This script is provided as-is for automation purposes.
