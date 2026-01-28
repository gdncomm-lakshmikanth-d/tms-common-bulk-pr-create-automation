# Jenkins Library Update Configuration

## Configuration Summary

The script is now configured to update the Jenkins library version in the following repositories:

1. `gdncomm/nonprod-deployment-gdn-tms-api`
2. `gdncomm/nonprod-deployment-gdn-tms-authentication`

### What will be updated:

**File:** `Jenkinsfile`

**Change:**
- From: `@Library('gcp-jenkins-library@2.2.5')`
- To: `@Library('gcp-jenkins-library@2.2.6')`

**Branch:** `update-jenkins-library-2.2.6`

**Commit Message:** `chore: update gcp-jenkins-library to 2.2.6`

**PR Title:** `Update gcp-jenkins-library to 2.2.6`

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Verify GitHub CLI Authentication
```bash
gh auth status
```

If not authenticated:
```bash
gh auth login
```

### 3. Test with Dry Run (Recommended First Step)
```bash
./bulk_repo_pr_creator.py --dry-run
```

This will show you what would happen without making any actual changes.

### 4. Run the Update
```bash
./bulk_repo_pr_creator.py
```

Or with verbose logging:
```bash
./bulk_repo_pr_creator.py --verbose
```

## What the Script Will Do

For each repository:

1. ✅ Clone the repository using `gh repo clone`
2. ✅ Create branch `update-jenkins-library-2.2.6`
3. ✅ Update `Jenkinsfile` (replace library version)
4. ✅ Commit changes with message "chore: update gcp-jenkins-library to 2.2.6"
5. ✅ Push branch to origin
6. ✅ Create Pull Request with title "Update gcp-jenkins-library to 2.2.6"

## Expected Output

```
================================================================
Processing repository 1/2: gdncomm/nonprod-deployment-gdn-tms-api
================================================================
Cloning gdncomm/nonprod-deployment-gdn-tms-api...
Creating branch update-jenkins-library-2.2.6...
Applying changes to Jenkinsfile
Modified: Jenkinsfile
Staging changes...
Committing changes: chore: update gcp-jenkins-library to 2.2.6
Pushing branch update-jenkins-library-2.2.6 to origin...
Creating pull request for gdncomm/nonprod-deployment-gdn-tms-api...
Successfully created PR for gdncomm/nonprod-deployment-gdn-tms-api
✓ Successfully processed gdncomm/nonprod-deployment-gdn-tms-api

================================================================
Processing repository 2/2: gdncomm/nonprod-deployment-gdn-tms-authentication
================================================================
...

================================================================
SUMMARY REPORT
================================================================
Total repositories: 2
Successful: 2
Skipped: 0
Failed: 0
```

## Customization

If you need to modify the configuration, edit the `CHANGE_RULES` section in `bulk_repo_pr_creator.py`:

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

## Troubleshooting

### Repository Access Issues
Ensure you have access to both repositories:
```bash
gh repo view gdncomm/nonprod-deployment-gdn-tms-api
gh repo view gdncomm/nonprod-deployment-gdn-tms-authentication
```

### Jenkinsfile Not Found
If a repository doesn't have a Jenkinsfile, it will be skipped automatically.

### No Changes Detected
If the Jenkinsfile already has version 2.2.6, the commit will be skipped.

## Notes

- The script will skip repositories if the Jenkinsfile doesn't exist
- The script will skip commits if no changes are detected
- If one repository fails, processing continues with the next one
- All operations are logged for audit purposes
