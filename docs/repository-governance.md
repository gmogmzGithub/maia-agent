# Repository Governance

Maia is public, so repository hygiene is part of the product.

## Branches

Use three branch categories:

| Branch | Visibility | Purpose |
| --- | --- | --- |
| `main` | Public | Recruiter-visible product code, public docs, tests, and reproducible setup |
| `feature/<topic>` or `codex/<topic>` | Public by default | Normal implementation work before review |
| `private/<topic>` | Private/local only | Raw planning, sensitive notes, experiments, or memory curation that must not reach `main` |

Important: branch names do not create privacy. In a public GitHub repository,
any pushed branch is public. `private/*` means **local-only** unless it has been
reviewed as public-safe. Do not push those branches to `origin`.

For private material that still needs version control, use one of these instead:

- a local-only branch that is never pushed;
- an ignored `private-notes/` folder for working notes that do not need remote
  backup;
- a separate private repository if the notes need cloud backup or multi-machine
  access.

## Protecting `main`

Recommended GitHub settings for `main`:

1. Go to **Settings -> Branches -> Add branch ruleset**.
2. Target branch: `main`.
3. Enable **Require a pull request before merging**.
4. Enable **Require approvals**.
5. Enable **Dismiss stale pull request approvals when new commits are pushed**.
6. Enable **Require status checks to pass**.
7. Add the `tests` workflow once GitHub Actions has run at least once.
8. Enable **Require conversation resolution before merging**.
9. Enable **Block force pushes**.
10. Enable **Restrict deletions**.

For solo development, one approval can be relaxed later, but status checks and
force-push protection should stay on.

After authenticating the GitHub CLI, the repository owner can apply the
description and branch protection with:

```bash
gh auth login
scripts/configure-github-repo.sh
```

This script does not make private notes private. It protects `main` from
accidental direct pushes, force pushes, and unreviewed merges.

## Public-Safety Checklist

Before opening or merging a PR:

- `git status --short` shows only intended files.
- `git diff --stat` matches the stated scope.
- No `.env`, provider key, token, raw lead, transcript, database, or local
  Hermes runtime file is included.
- Docs do not claim production readiness unless current evidence proves it.
- README changes remain recruiter-readable and do not expose private working
  notes.
- `git branch --list 'private/*'` branches are not pushed to `origin`.
- Tests run locally or the skipped checks are named explicitly in the PR.

## What Belongs on `main`

- Source code.
- Tests.
- Public architecture and operation docs.
- Synthetic examples.
- Public-safe role prompts.
- Curated project decisions in `PROJECT_MEMORY.md`.

## What Does Not Belong on `main`

- Raw Codex memory.
- Personal notes from unrelated projects.
- Private GitHub strategy notes beyond this public governance file.
- Real customer or lead data.
- Real property documents unless intentionally synthetic and clearly labeled.
- Local `hermes-home` state.
- Generated DB files, coverage files, caches, and virtual environments.
