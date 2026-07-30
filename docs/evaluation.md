# Replay evaluation inputs

The public sample evaluation inputs are versioned under `evaluation/` and are
validated by `platform_agent_orchestrator.evaluation`. They are test fixtures,
not observed operational data or a claim about production performance.

The fixed `sock-shop-alerts` dataset contains the 24 scenarios approved in the
sample metric plan: 10 actionable cases, including four critical cases, and 14
non-actionable cases. It covers available, missing, stale, and mismatched
evidence plus instruction-like untrusted text. Its illustrative manual baseline
contains nine notifications and one actionable miss. Candidate results are not
included; D02 owns replay execution and report generation.

Every public dataset and rubric must:

- use the strict versioned contract and reject unknown fields;
- declare C0 synthetic provenance, ownership, source locator, review date, and
  that it contains no real data;
- remain below one MiB with unique JSON keys and bounded nesting;
- pass the credential-material scan before typed validation;
- contain no company alerts, private paths/endpoints, credentials, raw source
  corpora, model traffic, or protected tool output.

Protected datasets are never committed here. A separately approved system may
provide a metadata record using `ProtectedDatasetLocatorV1`. Its locator is an
opaque `protected://<owner>/<dataset>` handle plus a SHA-256 digest and approval
reference. Resolution, authorization, physical paths, endpoints, and
credentials remain outside Git and outside workflow state. The public sample
does not resolve this scheme.
