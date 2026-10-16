# Architecture — P001

Root CLI -> Unix domain socket -> daemon -> power backend.

- CLI: ioscaffeinate
- Daemon: ioscaffeinated
- Default socket: /var/run/ioscaffeinated.sock, chmod 0600, root-only.
- IPC commands: PROBE, STATUS, START seconds, STOP, one request and reply per connection.
- One assertion held at a time, maximum 24 hours, with expiry.
- SIGTERM/SIGINT releases the assertion and cleans the socket during graceful exit.
- The iOS implementation dynamically loads IOKit and resolves IOPMAssertionCreateWithName / IOPMAssertionRelease.
- Requests assertion type PreventUserIdleSystemSleep, level 255.
- The Linux mock backend requires explicit IOSCAFFEINATE_TEST_MOCK.
- iOS 12 power assertion availability and efficacy are UNVERIFIED.

Important limitations: a successful API call does not establish whether the display can remain off while Wi-Fi and SSH stay reachable. A daemon may itself be suspended. A timed hold expires on next execution if suspended. The P001 deadline uses wall clock; monotonic clock and timezone testing are later enhancements.

Security: no network-facing port, no arbitrary command execution, no Apple system daemon modifications. The CLI socket must not be made world-writeable. Do not enable persistent launchd operation before device safety testing.

Apple API references:
https://developer.apple.com/documentation/iokit/kiopmassertiontypepreventuseridlesystemsleep
https://developer.apple.com/documentation/iokit/1557134-iopmassertioncreatewithname
https://developer.apple.com/documentation/iokit/1557090-iopmassertionrelease
