"""Present so that pytest prepends the repository root to ``sys.path``.

The package is not installed — there is nothing to install, since it has no
runtime dependencies and no build step — so ``import ledger`` has to resolve
from the repository root.
"""
