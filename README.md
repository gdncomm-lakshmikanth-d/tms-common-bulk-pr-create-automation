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

**Repository source (default: org + team):**
```python
GITHUB_ORG = "gdncomm"
GITHUB_TEAM = "TMS-DEPLOYMENT-NONPROD"
```
With these set, running `./bulk_repo_pr_creator.py` with no arguments lists repos for that team in that org, then prompts you to select. Alternatively use `--repos-file path/to/repos.txt` to supply a list (one `owner/repo` per line).

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

**Step-by-step progress:** For each repo the script prints:
1. **Clone** – cloning the repo  
2. **Branch** – creating/checking out the branch  
3. **Changes** – eligible or not; if eligible, applied files are listed  
4. **Push** – pushing the branch  
5. **PR** – creating or linking the pull request  

Each step shows `✓` (done), `⊘` (skipped), or `✗` (failed).

## Configuration Guide

All configuration is in `config.py`. Here's how to configure each section:

### Repository source (org + team)

Repos are listed from GitHub by org and optional team; no manual repo list in config.

Set in `config.py`:
```python
GITHUB_ORG = "gdncomm"
GITHUB_TEAM = "TMS-DEPLOYMENT-NONPROD"
```
Then run `./bulk_repo_pr_creator.py` with no arguments to list repos for that team in that org and select interactively.

To use a file instead: `./bulk_repo_pr_creator.py --repos-file path/to/repos.txt` (one `owner/repo` per line).

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
- `--repos-file`: Path to file with repo list (one owner/repo per line). Use instead of org/team.
- `--org ORG`: List all repos from GitHub org ORG and then select which to process (e.g., `--org gdncomm`)
- `--team TEAM`: Filter by GitHub team — list only repos for this team (e.g., `--team TMS-DEPLOYMENT-NONPROD`). Requires `--org`. Use `--team` alone to use `GITHUB_TEAM` from config.
- `--no-select`: Process all repos without selection prompt (for scripting)
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

### List and select repos (like Stash script)

**Default (no arguments):** If `GITHUB_ORG` and `GITHUB_TEAM` are set in `config.py`, running `./bulk_repo_pr_creator.py` with no arguments will list repos for that org and team, then prompt you to select. So you can run the script with no flags and get org + team behavior.

- **Default:** With `GITHUB_ORG` and `GITHUB_TEAM` in config, `./bulk_repo_pr_creator.py` lists repos for that team in that org, then you select.
- **From file:** Use `--repos-file path/to/repos.txt` (one owner/repo per line) to list from a file, then select.
- **Override org/team:** Run with `--org gdncomm` and/or `--team TMS-DEPLOYMENT-NONPROD` to override config. Use `--team` with no value to use `GITHUB_TEAM` from config.

**Selection format:**
- Numbers: `1,3,5` (repos 1, 3, 5)
- Ranges: `1-5,10-15`
- All: `all`
- Abort: `none` or Enter

Use **`--no-select`** to skip the prompt and process all repos (e.g., in CI).

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
- `GITHUB_ORG`: Default GitHub org to list repos from
- `GITHUB_TEAM`: Default team to filter repos (optional)
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
