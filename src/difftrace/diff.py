from __future__ import annotations

import subprocess
from pathlib import Path

from difftrace.graph import WorkspacePackage

# Default files/dirs at the workspace root that trigger testing all packages.
DEFAULT_ROOT_TRIGGERS = {"pyproject.toml", "uv.lock"}
DEFAULT_DIR_TRIGGERS = {".github/"}


def get_git_root(cwd: Path | None = None) -> Path:
    """Get the git repository root directory."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if result.returncode != 0:
        raise ValueError("Not a git repository. Run difftrace from within a git repo.")
    return Path(result.stdout.strip())


def get_changed_files(base_ref: str, repo_root: Path | None = None) -> list[str]:
    """Get list of files changed between base_ref and HEAD.

    Returns paths relative to the git root.
    """
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "unknown revision" in stderr or "not a git repository" in stderr:
            raise ValueError(
                f"Could not resolve ref '{base_ref}'. "
                "Does the branch/ref exist? "
                "Try 'git fetch' or use --base with a valid ref."
            )
        raise RuntimeError(f"git diff failed: {stderr}")
    return [f for f in result.stdout.strip().splitlines() if f]


def relativize_to_workspace(
    changed_files: list[str],
    git_root: Path,
    workspace_root: Path,
) -> list[str]:
    """Convert git-root-relative paths to workspace-root-relative paths.

    Files outside the workspace are dropped.
    """
    workspace_root = workspace_root.resolve()
    git_root = git_root.resolve()

    if workspace_root == git_root:
        return changed_files

    try:
        prefix = str(workspace_root.relative_to(git_root))
    except ValueError:
        return []

    prefix_with_slash = prefix + "/"
    result = []
    for f in changed_files:
        if f.startswith(prefix_with_slash):
            result.append(f[len(prefix_with_slash) :])
        elif f == prefix:
            result.append(".")
    return result


def map_files_to_packages(
    changed_files: list[str],
    packages: dict[str, WorkspacePackage],
    *,
    root_triggers: set[str] | None = None,
    dir_triggers: set[str] | None = None,
) -> tuple[set[str], bool]:
    """Map workspace-relative changed files to affected packages.

    Args:
        changed_files: File paths relative to the workspace root.
        packages: Workspace packages from the dependency graph.
        root_triggers: File names that trigger test_all. None uses defaults.
        dir_triggers: Directory prefixes that trigger test_all. None uses defaults.

    Returns:
        Tuple of (directly changed package names, test_all flag).
    """
    if root_triggers is None:
        root_triggers = DEFAULT_ROOT_TRIGGERS
    if dir_triggers is None:
        dir_triggers = DEFAULT_DIR_TRIGGERS

    test_all = False
    directly_changed: set[str] = set()

    # Sort packages by source_path length descending for longest-prefix match
    sorted_packages = sorted(
        packages.values(),
        key=lambda p: len(p.source_path),
        reverse=True,
    )

    for filepath in changed_files:
        # Check root triggers
        if filepath in root_triggers:
            test_all = True
            continue

        if any(filepath.startswith(trigger) for trigger in dir_triggers):
            test_all = True
            continue

        # Try to match to a package
        for pkg in sorted_packages:
            # Skip virtual root packages to avoid matching everything
            if pkg.source_path == ".":
                continue
            if filepath.startswith(pkg.source_path + "/"):
                directly_changed.add(pkg.name)
                break

    return directly_changed, test_all
