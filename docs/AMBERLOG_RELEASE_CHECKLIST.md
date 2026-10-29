# Amberlog release checklist

Current decision: **NO-GO for external publication**. Local migration evidence
does not satisfy independent review, real pilot or index/account readiness.

| Gate | Acceptance |
|---|---|
| Namespace | Current tracked text and file paths contain only the canonical branding |
| API/CLI | `import amberlog`, `from amberlog import Amberlog`, `amberlog --help` work |
| Stored data | Prior-store identity, exact event digest, decryption and chain pass |
| Governance | Full regression suite plus negative isolation/retraction/action/erasure checks pass |
| Evidence | Generated references and manifests match the current tree; original commits retained |
| Package contents | Wheel/sdist contain package assets and typing marker, no tests/data/secrets |
| Installation | Independent wheel and sdist installs outside checkout pass import, CLI and doctor |
| Supported Python | Exact-candidate CI on 3.11, 3.12 and 3.13 passes |
| Federation | New-to-new passes; mixed-version support is not claimed |
| Name/accounts | Owner resolves existing software usage and confirms both index projects/publishers |
| External qualification | Required independent review, real pilot and remaining release gates pass |
| Approval | Protected environment review plus exact approved SHA, manual dispatch only |

Validation commands:

```
python tools/check.py --full
python -m build
python -m twine check --strict dist/*
python tools/fresh_machine.py dist/amberlog-0.14.0-py3-none-any.whl
```

Run `doctor` with a real initialized database, not an unrelated empty path.
`amberlog init ./memory` prepares one; `amberlog --db ./memory/store.db --keys
./memory/keys doctor` checks it. Do not invent an unsupported `sandbox` command;
the current interactive introduction is `amberlog tour`.
