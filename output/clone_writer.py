"""
Writes a full clone of the target repository with refactored file contents substituted in.

Structure:
  Input repo:  /path/to/myrepo/
  Clone output: /path/to/myrepo_refactored/

Every file in the original repo is mirrored. Files that Arkhe successfully
refactored get the improved version; all other files are copied byte-for-byte.
The .git directory is always excluded from the clone.
"""
import os
import shutil
import logging

logger = logging.getLogger("arkhe.clone")

# Directories that are never cloned (build artifacts, environments, VCS internals)
_SKIP_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules",
    ".next", "dist", "build", "coverage", ".pytest_cache",
}


def write_clone(repo_path: str, refactored: dict[str, str]) -> str:
    """
    Mirror the repository to a sibling directory, substituting refactored files.

    Args:
        repo_path:  Path to the original repository (absolute or relative).
        refactored: Mapping of relative file path → improved file content.

    Returns:
        Absolute path to the clone directory.
    """
    abs_repo  = os.path.abspath(repo_path)
    parent    = os.path.dirname(abs_repo)
    name      = os.path.basename(abs_repo)
    clone_dir = os.path.join(parent, name + "_refactored")

    copied    = 0
    improved  = 0
    failed    = 0

    for root, dirs, files in os.walk(abs_repo):
        # Prune skipped directories in-place so os.walk doesn't descend into them
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]

        for fname in files:
            src_abs  = os.path.join(root, fname)
            rel_path = os.path.relpath(src_abs, abs_repo).replace("\\", "/")
            dst_abs  = os.path.join(clone_dir, rel_path)

            os.makedirs(os.path.dirname(dst_abs), exist_ok=True)

            if rel_path in refactored:
                try:
                    with open(dst_abs, "w", encoding="utf-8") as f:
                        f.write(refactored[rel_path])
                    improved += 1
                except Exception as e:
                    logger.warning(f"Failed to write refactored {rel_path}: {e} — copying original")
                    shutil.copy2(src_abs, dst_abs)
                    failed += 1
            else:
                try:
                    shutil.copy2(src_abs, dst_abs)
                    copied += 1
                except Exception as e:
                    logger.warning(f"Failed to copy {rel_path}: {e}")
                    failed += 1

    logger.info(
        f"Clone complete: {improved} improved, {copied} copied as-is, {failed} failed — {clone_dir}"
    )
    return clone_dir
