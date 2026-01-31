#!/usr/bin/env python3
"""Verification script to check if the archiver is properly set up."""

import sys
from pathlib import Path


def check_item(description: str, condition: bool, fix_hint: str = "") -> bool:
    """Check an item and print result."""
    if condition:
        print(f"✓ {description}")
        return True
    else:
        print(f"✗ {description}")
        if fix_hint:
            print(f"  Fix: {fix_hint}")
        return False


def main():
    """Run verification checks."""
    print("Granola Archiver Setup Verification")
    print("=" * 50)
    print()

    checks_passed = 0
    total_checks = 0

    # Check Python version
    total_checks += 1
    python_version = sys.version_info
    if check_item(
        f"Python version ({python_version.major}.{python_version.minor})",
        python_version >= (3, 13),
        "Install Python 3.13 or higher"
    ):
        checks_passed += 1

    print()

    # Check uv installation
    total_checks += 1
    import shutil
    uv_path = shutil.which("uv")
    if check_item(
        "uv installed",
        uv_path is not None,
        "curl -LsSf https://astral.sh/uv/install.sh | sh"
    ):
        checks_passed += 1

    print()

    # Check granola-client
    total_checks += 1
    try:
        import granola_client
        check_item("granola-client installed", True)
        checks_passed += 1
    except ImportError:
        check_item(
            "granola-client installed",
            False,
            "uv sync"
        )

    # Check dependencies
    deps_to_check = [
        ("httpx", "uv add httpx"),
        ("pydantic", "uv add pydantic"),
        ("yaml", "uv add pyyaml"),
        ("git", "uv add gitpython"),
        ("dotenv", "uv add python-dotenv"),
        ("rich", "uv add rich"),
    ]

    for module_name, install_cmd in deps_to_check:
        total_checks += 1
        try:
            __import__(module_name)
            check_item(f"{module_name} installed", True)
            checks_passed += 1
        except ImportError:
            check_item(f"{module_name} installed", False, install_cmd)

    print()

    # Check config file
    total_checks += 1
    config_file = Path("config.yaml")
    if check_item(
        "config.yaml exists",
        config_file.exists(),
        "Copy config.yaml.example to config.yaml"
    ):
        checks_passed += 1

        # Check if repo_path is configured
        if config_file.exists():
            total_checks += 1
            with open(config_file, 'r') as f:
                content = f.read()
                if check_item(
                    "Archive repo path configured",
                    "/path/to/" not in content,
                    "Edit config.yaml and set archive.repo_path"
                ):
                    checks_passed += 1

    print()

    # Check Granola credentials
    total_checks += 1
    credentials_path = Path.home() / ".granola" / "credentials.json"
    if check_item(
        "Granola credentials exist",
        credentials_path.exists(),
        "Run the Granola client first to authenticate"
    ):
        checks_passed += 1

    print()

    # Check state directory
    total_checks += 1
    state_dir = Path("state")
    if check_item(
        "State directory exists",
        state_dir.exists(),
        "mkdir state"
    ):
        checks_passed += 1

    print()
    print("=" * 50)
    print(f"Checks passed: {checks_passed}/{total_checks}")
    print()

    if checks_passed == total_checks:
        print("✓ All checks passed! You're ready to run:")
        print("  uv run archiver --dry-run")
        return 0
    else:
        print("✗ Some checks failed. Please fix the issues above.")
        print("\nQuick fix: Run 'uv sync' to install all dependencies")
        return 1


if __name__ == "__main__":
    sys.exit(main())
