# Atlas OS v3 — Project Status

Atlas OS v3 is the final planned release of this project. No additional
feature-development roadmap is active.

## Final release scope

- A host-run Python CLI subsystem for Windows, macOS, and Linux conventions.
- A user-level installer that creates an isolated Python environment and
  persistent, directory-backed virtual storage.
- Host-backed hardware discovery where the host exposes supported telemetry.
- Optional native demonstrations and integrations that remain platform- and
  toolchain-dependent.

## Known limitations

- Atlas OS is not a bootable image, virtual machine, hypervisor, or replacement
  for the host operating system.
- The sparse 2 GB storage image is a logical simulation. It is not mounted as a
  filesystem and does not enforce a hard capacity limit.
- Windows is the only host on which the complete installer flow has been
  exercised end-to-end. macOS and Linux support is unverified.
- Native compiler outputs and third-party game/runtime binaries are not
  cross-platform and are not included by the portable installer.
- Some subsystems depend on external programs, network access, host APIs, or
  optional development toolchains.

The roadmap entries formerly listed here were ideas, not implemented
capabilities or promises. This document records the final project's scope and
known limits rather than proposing additional v3 work.
