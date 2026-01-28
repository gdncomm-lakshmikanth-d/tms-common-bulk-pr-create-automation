# Bulk Pull Request Creator

A production-ready Python script that automates bulk Pull Request creation across multiple GitHub repositories.

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
- ✅ Works on Mac and Linux

## Requirements

- Python 3.7+
- GitHub CLI (`gh`) installed and authenticated
- PyYAML library (`pip install PyYAML`)

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Ensure GitHub CLI is installed and authenticated:
```bash
gh auth login
```

3. Create your `repos.txt` file with repository list (see `repos.txt.example`)

## Configuration

Edit the `CHANGE_RULES` section in `bulk_repo_pr_creator.py` to define what changes to apply:

```python
CHANGE_RULES = [
    {
        "file": ".github/workflows/ci.yml",
        "type": "yaml",
        "changes": [
            {
                "action": "update_key",
                "path": "jobs.build.steps[0].uses",
                "value": "actions/checkout@v4"
            }
        ]
    },
    {
        "file": "config.json",
        "type": "json",
        "changes": [
            {
                "action": "update_key",
                "path": "version",
                "value": "2.0.0"
            }
        ]
    },
    {
        "file": ".env.example",
        "type": "env",
        "changes": [
            {
                "action": "replace",
                "pattern": r"API_URL=https://api\.example\.com",
                "replacement": "API_URL=https://api.newdomain.com"
            }
        ]
    }
]
```

### Change Rule Types

#### YAML Files
```python
{
    "file": "values.yaml",
    "type": "yaml",
    "changes": [
        {
            "action": "update_key",
            "path": "image.tag",  # Supports nested keys
            "value": "v1.2.3"
        },
        {
            "action": "update_key",
            "path": "jobs.build.steps[0].uses",  # Supports array notation
            "value": "actions/checkout@v4"
        }
    ]
}
```

#### JSON Files
```python
{
    "file": "package.json",
    "type": "json",
    "changes": [
        {
            "action": "update_key",
            "path": "dependencies.react",  # Supports nested keys
            "value": "^18.0.0"
        }
    ]
}
```

#### ENV Files
```python
{
    "file": ".env",
    "type": "env",
    "changes": [
        {
            "action": "replace",
            "pattern": r"DEBUG=false",
            "replacement": "DEBUG=true"
        },
        {
            "action": "update_key",
            "path": "API_VERSION",
            "value": "v2"
        }
    ]
}
```

#### Text Files
```python
{
    "file": "README.md",
    "type": "text",
    "changes": [
        {
            "action": "replace",
            "pattern": r"old text",
            "replacement": "new text"
        }
    ]
}
```

## Usage

### Basic Usage

```bash
./bulk_repo_pr_creator.py
```

### Dry Run (Test Mode)

Test your configuration without making actual changes:

```bash
./bulk_repo_pr_creator.py --dry-run
```

### Custom Options

```bash
./bulk_repo_pr_creator.py \
    --repos-file repos.txt \
    --commit-message "chore: update dependencies" \
    --pr-title "Update Dependencies" \
    --pr-body "Automated dependency update" \
    --branch "update-deps" \
    --verbose
```

### Command Line Options

- `--repos-file`: Path to file containing repository list (default: `repos.txt`)
- `--dry-run`: Perform a dry run without making actual changes
- `--commit-message`: Custom commit message
- `--pr-title`: Custom PR title
- `--pr-body`: Custom PR body
- `--branch`: Branch name (default: `bulk-config-update`)
- `--verbose`: Enable verbose logging
- `--clone-dir`: Directory to clone repositories (default: temporary directory)

## Repository File Format

Create a `repos.txt` file with one repository per line:

```
owner1/repo1
owner2/repo2
https://github.com/owner3/repo3
git@github.com:owner4/repo4.git
```

- Supports `owner/repo` format
- Supports full GitHub URLs
- Lines starting with `#` are ignored
- Empty lines are ignored

## Error Handling

The script is designed to be resilient:

- **Missing files**: If a target file doesn't exist, the rule is skipped for that repository
- **No changes**: If no changes are made, the commit and PR creation are skipped
- **Individual failures**: If one repository fails, processing continues with others
- **Comprehensive logging**: All operations are logged with clear error messages

## Output

The script provides:

1. **Real-time logging**: Progress for each repository
2. **Summary report**: Counts of successful, skipped, and failed repositories
3. **Detailed results**: Lists of modified files and error messages

Example output:
```
================================================================
SUMMARY REPORT
================================================================
Total repositories: 10
Successful: 8
Skipped: 1
Failed: 1

Successful repositories:
  - owner1/repo1
    Modified files: .github/workflows/ci.yml, config.json
  - owner2/repo2
    Modified files: .env.example
...
```

## Best Practices

1. **Always test with `--dry-run` first** to verify your configuration
2. **Start with a small subset** of repositories to test
3. **Review the CHANGE_RULES** carefully before running
4. **Use descriptive commit messages** and PR titles
5. **Monitor the summary report** for any failures

## Troubleshooting

### GitHub CLI Not Authenticated
```bash
gh auth login
```

### PyYAML Not Installed
```bash
pip install PyYAML
```

### Permission Denied
```bash
chmod +x bulk_repo_pr_creator.py
```

### Repository Access Issues
Ensure you have access to all repositories listed in `repos.txt`. Private repositories require appropriate permissions.

## License

This script is provided as-is for automation purposes.
