# Installer platform support

This document defines current support status for `./install.sh`.

## Support states

- **Stable**: full tested path in CI and expected to work end-to-end.
- **Scaffolded**: distro is detected and actionable install guidance is provided, but full automatic package installation is not implemented yet.
- **Unsupported**: distro/package manager is not detected by installer.

## Current matrix

| Distro family | Package manager | State | Notes |
|---|---|---|---|
| Debian / Ubuntu | `apt` | **Stable** | Full automatic dependency install path. |
| Fedora / RHEL / CentOS | `dnf` / `yum` | **Scaffolded** | Detection + actionable commands present; auto-install path is TODO. |
| openSUSE | `zypper` | **Scaffolded** | Detection + actionable commands present; auto-install path is TODO. |
| Arch Linux | `pacman` | **Scaffolded** | Detection + actionable commands present; auto-install path is TODO. |
| Other Linux distros | unknown | **Unsupported** | Installer exits with package-manager guidance requirement. |

## Guard rails

- Debian/Ubuntu behavior must remain stable for every portability PR.
- New distro support should be added behind explicit package-manager adapters and tests.
- If a distro is scaffolded but not fully automated, installer should fail fast with actionable manual commands (not generic errors).
