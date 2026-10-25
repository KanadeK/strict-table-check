# Security

Only the latest release is supported. Never attach production data, credentials,
or unredacted diagnostic output to a public issue. Report sensitive problems using
the repository's Security tab / private vulnerability reporting. If unavailable,
open a minimal public issue asking for a private contact without exploit details.

The tool operates locally and does not contact a network or load database
extensions. Input limits reduce accidental resource use, but are not an OS
sandbox. Use a patched Python/database runtime and OS process isolation for
hostile files. See README for diagnostic disclosure and unsupported cases.
