import subprocess
from datetime import datetime
from pathlib import Path


class GitSyncError(Exception):
    pass


def push_state(repo_root: Path, state_dir: Path, new_count: int) -> None:
    """
    Commit and push the .state/ directory to the GitHub remote.

    repo_root: the root of the pies-alac-rip-tool git repo
    state_dir: path to <repo_root>/.state/ — MUST be inside repo_root
    new_count: number of new tracks downloaded (used in commit message)
    """
    if not state_dir.exists():
        return

    # Verify state_dir is inside repo_root to ensure git add works
    try:
        state_dir.relative_to(repo_root)
    except ValueError:
        raise GitSyncError(
            f"state_dir {state_dir} is not inside repo_root {repo_root}. "
            "Check your config.yaml — state_dir must be set to <repo>/.state by install.sh."
        )

    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    message = f"sync: {date_str} — {new_count} new track(s)"

    def run(cmd: list[str]) -> None:
        result = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True)
        if result.returncode != 0:
            raise GitSyncError(
                f"Git command failed: {' '.join(cmd)}\n{result.stderr}"
            )

    # Use repo-relative path so git add always works
    relative = state_dir.relative_to(repo_root)
    run(["git", "add", str(relative)])
    run(["git", "commit", "-m", message])
    run(["git", "push"])
