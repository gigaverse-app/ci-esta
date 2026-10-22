"""Compatibility entry point for the Octokit contract recorder."""
import sys

from ci_esta import github_script_surface as _implementation
from ci_esta.github_script_surface import main as main
from ci_esta.github_script_surface import rest_surface as rest_surface

if __name__ == "__main__":
    main()
sys.modules[__name__] = _implementation
