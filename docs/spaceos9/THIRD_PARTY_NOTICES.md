# SpaceOS 9 third-party notices

Release: SpaceOS 9 / SpaceKernel 3.0 #13 (2026-10-25)
Image: `SpaceOS-9-x86_64.iso`
SHA-256: `2e6164b0ee92a1e4852f108b2b247e82005013fc10072d9f4a0be3f1eb9ccdb1`

The image contains the following third-party components. SpaceOS-9's own
kernel and userland are Copyright (C) 2026 ViudiraTech, all rights reserved;
their source is published at <https://github.com/ViudiraTech/SpaceOS-9>.

## BusyBox 1.36.1 — GPL-2.0-only

- Upstream source: <https://busybox.net/downloads/busybox-1.36.1.tar.bz2>
- Source SHA-256: `b8cc24c9574d809e7279c3be349795c5d5ceb6fdf19ca709f80cde50e47de314`
- Build configuration and build script:
  <https://github.com/ViudiraTech/SpaceOS-9/blob/master/tools/build_busybox.sh>
- License: <https://busybox.net/license.html>

The BusyBox binary in this image is an unmodified upstream release compiled
with the configuration produced by the linked script. The complete
corresponding source is the upstream tarball above; the exact configuration
and build steps are in the SpaceOS-9 repository.

## musl 1.2.5 — MIT

- Upstream source: <https://musl.libc.org/releases/musl-1.2.5.tar.gz>
- Source SHA-256: `a9a118bbe84d8764da0ea0d28b3ab3fae8477fc7e4085d90102b8596fc7c75e4`
- License: <https://git.musl-libc.org/cgit/musl/tree/COPYRIGHT>

## Limine v12.9.1 — BSD-2-Clause

- Upstream source: <https://github.com/limine-bootloader/limine>
- License: <https://github.com/limine-bootloader/limine/blob/trunk/COPYING>

## Rust core / compiler-builtins

The kernel links Rust `core` and compiler support code, distributed under the
MIT OR Apache-2.0 license. Upstream: <https://github.com/rust-lang/rust>.

## Linux UAPI headers

The BusyBox build uses Linux UAPI headers from the host toolchain. Those
headers are GPL-2.0 WITH Linux-syscall-note; they are not part of SpaceOS-9's
proprietary kernel source.

## Written offer

For a physical copy of the complete corresponding source for BusyBox and musl,
contact the project maintainers through
<https://github.com/ViudiraTech/SpaceOS-9/issues> or `goutoustdio@outlook.com`.
This offer is valid for three years from the release date above.
