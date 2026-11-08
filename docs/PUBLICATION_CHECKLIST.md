# Public repository checklist

Use this checklist before changing the repository visibility to public.

## Required

- [ ] Confirm redistribution rights for Kalshi snapshots and CF Benchmarks BRTI-derived data.
- [ ] Remove tracked raw market snapshots and live-order exports from the public branch.
- [ ] Remove row-level generated files that can reconstruct private orders or licensed source data.
- [ ] Scan the full Git history for credentials, PEM blocks, account identifiers, email addresses, and absolute
      workstation paths.
- [ ] Decide whether historical notebooks add portfolio value; remove outputs and hidden metadata if they do not.
- [ ] Run every documented command from a clean environment with authorized local inputs.
- [ ] Verify that report numbers state their sample period and are not presented as current performance.
- [ ] Add a license only after choosing the rights granted for code, reports, and any included data.

## Files currently requiring an explicit publication decision

The following categories were tracked before public-release rules were added:

- `data/raw/*.csv`;
- `outputs/actual/*.csv` and `outputs/simulated/*.csv`;
- notebooks and notebook backups in the repository root and `archive/`.

Adding a path to `.gitignore` does not remove it from Git history. Preserve a private backup first, then remove it
from the public branch or rewrite history with an appropriate repository-history tool. History rewriting changes
commit identifiers and should be coordinated before pushing.

## Proposed history cleanup

Make a private mirror backup before running these commands. Install `git-filter-repo`, work from a fresh clone, and
remove private or redistributable-data paths from every commit:

```bash
git clone --mirror <private-repository-url> analysis-report-AI-clean.git
cd analysis-report-AI-clean.git
git filter-repo \
  --path data/raw \
  --path outputs/actual \
  --path outputs/simulated \
  --path archive \
  --path AIRelated.ipynb \
  --invert-paths
```

Inspect the rewritten mirror before replacing any remote history:

```bash
git log --all --stat
git rev-list --objects --all
git fsck --full
```

After review, push to a new empty public repository first. Replacing an existing shared remote requires a coordinated
force push of branches and tags. Every collaborator must then clone again because all rewritten commit IDs differ.

## Recommended public surface

```text
README.md
requirements.txt
reports/
src/
experiments/
scripts/
docs/
data/README.md
```

Compact aggregate outputs may be included when their provenance permits redistribution and they do not reveal
private execution records. Raw inputs should be supplied out of band.
