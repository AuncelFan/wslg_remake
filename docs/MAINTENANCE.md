# Maintenance after WSL updates

The accepted baseline targets WSL 3.0.5.0 / WSLg 1.0.79, Weston 9.0.0 commit `a7e35fdab455dce5774b43b8aff682f748307e31`, and FreeRDP commit `c4030980b29322a9cb2190711a5fadeeeb8b6a33`. It modifies four source files (+83 / −3 lines, including comments).

## Keep a private local baseline

Record the following locally before deployment and after a successful upgrade:

- `wsl.exe --version`, the distribution release and kernel version.
- The WSLg `/mnt/wslg/versions.txt` and system-distro release/glibc versions.
- SHA256 of installed Weston, its core library, RDP backend, desktop library, shell, FreeRDP/WinPR and loaded dependencies.
- SHA256 of candidate binaries, patches, source and SDK inputs; full build commands.
- Active configuration and actual Weston process mappings.
- The original application's package identity and integrity fingerprints.

Run system-distro inspection explicitly in the WSLg system distro, for example `wsl.exe --system -d Ubuntu -u root --exec ...`. Its `/usr/lib` is distinct from Ubuntu's `/usr/lib`.

Keep raw environment snapshots, logs and desktop evidence private. Do not commit user profiles, local filesystem paths, machine names, process environments, account data or screenshots to the public repository.

## Evaluate changes

1. Confirm the updated WSLg is actually running. A new WSL package version can coexist temporarily with an older running compositor session.
2. Verify that the expected candidates still exist and are actually mapped by Weston. Do not rely solely on `.wslgconfig` or `weston --version`.
3. If Weston or dependency fingerprints changed, review ABI and source changes even if the version string stayed the same.
4. Obtain the new matching source and SDK. Check whether upstream already fixed either issue before applying patches again.
5. Review the xdg-shell comparison, last-ACK state semantics, bufferless commit behavior, queue handling and geometry logic.
6. Review RAIL ACK callbacks, task threading, destruction/wait behavior, backpressure conditions and output lifetime.
7. Build into new directories; make the shell copy from the **new** stock shell. Check exported symbols, required symbols, SONAME/dependencies, GLIBC limits and actual process maps.
8. Repeat the same physical minimize/restore sequence and preserve a new private baseline. Do not overwrite the previous accepted baseline.

Successful `git apply --check` only establishes textual applicability. Matching fingerprints only establish absence of measured drift. Neither proves behavior or complete ABI compatibility.

## Preserve test behavior

Use the original application without injection or keepalive changes. Move the pointer onto the application's own minimize button, hover about 800 ms, click, then restore by physically clicking the taskbar. Verify content scrolling/input without dragging, resizing or maximizing as a recovery aid.

Test normal and maximized windows, longer hover, and short/long hidden intervals. Test other reachable application minimize entry points separately. Windows minimize shortcuts exercise a distinct path and are not a replacement for application-button tests.

## Binary distribution note

The original tested artifacts were approximately 0.86 MiB (backend), 0.35 MiB (desktop library), and 0.15 MiB (shell copy), or 1.36 MiB combined. Size is not the reason this draft excludes them.

The compiled artifacts retain local build paths; the shell copy also has a machine-specific absolute dependency. A reusable binary release would require reproducible path sanitization, a relocatable deployment design, and fresh validation. The current public draft contains source only.
