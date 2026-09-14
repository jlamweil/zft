# Security Policy

## Supported versions

The ZFT team applies security fixes to the current `0.x` line, which ships
as the `zft` package on PyPI (Python 3.12+).

| Version | Status | Notes |
| --- | --- | --- |
| 0.2.x (current)   | Fully supported | Active development; security patches and bug fixes. |
| 0.1.x             | EOL | No longer receiving updates. Please upgrade to 0.2.x. |
| < 0.1.0           | EOL | No longer receiving updates. Please upgrade to 0.2.x. |

## Reporting a vulnerability

Security issues must be reported **privately** and must never be discussed in
public issues, pull requests, or forums.

To report a vulnerability, use this repository's **Report a vulnerability**
form (Security tab → *Report a vulnerability*), GitHub's private disclosure
channel — it is the only accepted report path. Include:

- A description of the vulnerability and the potential impact.
- Steps to reproduce (ideally, a minimal proof of concept).
- Your name and affiliation (if any) and whether you are eligible for a
  coordinated disclosure credit.

### What to expect

1. **Acknowledgement** within 5 business days. We will confirm receipt and
   provide a tracking reference.
2. **Investigation** — we validate the report and assess impact. Complex
   issues may be escalated internally.
3. **Fix** — we develop a patch in a private branch.
4. **Disclosure** — once a fix is released, we will publish a security
   advisory (GHSA) and credit the reporter unless anonymity is requested.

We ask that you refrain from public disclosure for **90 days** following our
acknowledgement, to allow time for the fix and release to reach users. Please
coordinate with us before any public announcement or CVE reservation.

## Scope

In scope: vulnerabilities in the `zft` package, its bundled CLI, the L0-L3
gate engines, and generated verification artefacts.

Out of scope: vulnerabilities in third-party dependencies; issues in other
agent frameworks or orchestration layers that merely invoke ZFT; and any
finding discovered through automated scanning (e.g. dependency advisories)
that is already mitigated by the supported versions above.
