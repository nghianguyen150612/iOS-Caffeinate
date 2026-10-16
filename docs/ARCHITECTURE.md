# Architecture — P002

Root CLI `ios-caffeinate` (or symlink `ic`) -> Unix stream socket -> foreground `ios-caffeinated` -> power backend.

## Protocol and access

- Default endpoint stays `/var/run/ioscaffeinated.sock`, owned by root with mode `0600`. Default daemon use requires effective UID 0. A custom absolute `--socket` supports unprivileged tests in a private directory owned by the invoking user.
- IPC: `PROBE\n`, `STATUS\n`, `START seconds\n`, `STOP\n`; one printable ASCII frame per connection, maximum 127 bytes including newline. NUL, CR, oversized/incomplete frames, extra queued commands and invalid durations are rejected. No pipelining; bytes sent after an accepted frame are not another request.
- Fragmented commands/replies are assembled to newline. A whole command read is limited to one second; expiry checks continue while waiting. Replies have a one-second send timeout; the CLI waits at most four seconds for a complete reply. System API calls themselves are synchronous and cannot be time-bounded by the IPC timer.
- CLI exit codes: 0 = complete OK reply/help; 1 = daemon, protocol, transport or power error; 2 = usage/duration/path error. A disconnected client does not cancel a successfully acquired hold; it remains bounded and can be stopped through another CLI.
- A stable `socket-path.lock` file (owner-only `0600`, regular, single link, no symlinks) is held with nonblocking `flock` across stale-socket detection, bind, listen and shutdown. Never unlink it during daemon operation or normal cleanup. It contains no PID or installation state.
- Existing live sockets are refused; only an owned socket that refuses a nonblocking connection may be replaced. Regular files/symlinks are preserved. Graceful cleanup removes only the socket inode created by that process. Custom socket directories must be private and trusted; same-UID/root processes are within the trust boundary.

## Assertion lifecycle

- One assertion at a time; durations 1..86400 seconds. Monotonic deadlines (`clock_gettime`, available on iOS 12) avoid wall-clock jumps. Suspension still delays userspace cleanup; this is not a kernel-enforced lease.
- PROBE performs one create/release pair and refuses to add another assertion during a hold. Failed probe release remains tracked with its ID.
- STOP and expiry clear state only after successful release. On failure, status retains `active=yes`, the ID, and `release_pending=yes`. Retries occur once per second, on STOP and at shutdown; errors never become a successful STOP response.
- SIGTERM/SIGINT request normal cleanup outside the signal handler. Failed final release produces nonzero daemon exit and an `UNRESOLVED` log. Process-exit cleanup by iOS is not claimed as measured. SIGKILL/crash cannot run cleanup; the next instance can replace the stale socket, but cannot verify an old process's assertion was removed.
- Startup/teardown errors remain failures. SIGPIPE is ignored by daemon and CLI to handle closed peers.

## Backends and diagnostics

Apple builds load `/System/Library/Frameworks/IOKit.framework/IOKit` at runtime and resolve `IOPMAssertionCreateWithName` and `IOPMAssertionRelease`. They request `PreventUserIdleSystemSleep`, level 255, name `ios-caffeinated timed keep-awake`. Only CoreFoundation and libSystem are linked. SDK success does not prove these APIs exist or work on iOS 12.

Probe/status report backend identity, assertion type, IOKit load result, each symbol result, latest create/release return code in hexadecimal, and `last_assertion_id` (the current tracked hold is `assertion_id`). Before the first acquisition attempt the backend diagnostics say `not_attempted`/`not_called`. Successful STOP and foreground logs include release results. `IOKit_RUNTIME_UNVERIFIED` deliberately makes no network-effect claim after an API success.

Linux requires explicit `IOSCAFFEINATE_TEST_MOCK`; ungated non-Apple compilation fails. `MOCK_NO_POWER_EFFECT` never inhibits sleep. Acquire/release fault injection environment variables exist only inside the compiled mock branch; Apple behavior cannot be replaced by a runtime environment switch.

An accepted assertion does not establish Wi-Fi/LAN/Tailscale behavior, continued daemon scheduling, battery/thermal safety, or a reliable wake timer. Each requires independent hardware evidence. No network-facing listener, shell execution, service installation, Apple daemon changes or persistent power settings are introduced.

Apple API references:
https://developer.apple.com/documentation/iokit/kiopmassertiontypepreventuseridlesystemsleep
https://developer.apple.com/documentation/iokit/1557134-iopmassertioncreatewithname
https://developer.apple.com/documentation/iokit/1557090-iopmassertionrelease
