# Licensing options (for the owner's decision)

The code is proprietary today ("All rights reserved"). That blocks outside
contributors and reviewers, and makes a pilot a legal question for most
companies. This page lays out the usual options; it decides nothing.

| option | what users may do | what it gives you | what it costs you |
|---|---|---|---|
| **Keep proprietary**, with a pilot agreement | run it under a signed evaluation licence | full control, every deal negotiated | slow adoption; no community; reviewers need an agreement too |
| **Source-available** (e.g. BSL 1.1 converting to Apache-2.0 after N years, or the Elastic License 2.0) | read, run and modify; not offer it as a competing hosted service | visible code for reviewers and pilots; hosting stays yours | not "open source"; some companies' policies refuse it |
| **Open core**: Apache-2.0 core, commercial extras | anything with the core; pay for extras (hosted control plane, SSO, support, regulated-mode features) | adoption and contributions on the core; revenue on extras | you must keep the line between core and extras clear and stable |
| **Fully open** (Apache-2.0 or MIT) | anything | fastest adoption; easiest independent review and academic use | revenue only from services, hosting or support |

Points specific to this project:

- **The independent security review and outside pilots are the two biggest
  gaps** (LIMITATIONS.md). Both are much easier with visible source.
- The research write-up (the exposure-probability log and decision
  dependence) is citable under any of these; a paper does not need the code
  to be open, but reproducibility does.
- Changing later is one-way in practice: code released under an open licence
  stays available under it.
- A licence change touches `LICENSE`, `pyproject.toml` (`license`), the README
  badge and the copyright lines, and should come with a CONTRIBUTING note on
  contributor terms (a DCO or a CLA).
