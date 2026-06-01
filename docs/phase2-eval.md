# Phase 2 manual evaluation checklist (Tier C)

Run before tagging a Phase 2 release. Document results with date and reviewer initials.

## Chester corpus queries

| ID | Query | Pass? | Notes |
|----|-------|-------|-------|
| L-01 | `"liability"` returns duty-of-care passages | | |
| L-01 | `"negligence"` returns negligence standard text | | |
| L-01 | `"Hambrook v Stokes Brothers"` returns case discussion | | |
| **L-01** | **`plaintiff claimed damages in the sum of £1,000` → page 3 chunk** | | **Primary benchmark** |
| **L-01** | **`What damages sum did the plaintiff claim?` → same page 3 chunk** | | Complex NL |
| L-04 | No wrong-agreement boilerplate in top 10 for liability | | |

## CARP (page 3 co-occurrence)

| ID | Query | Pass? | Notes |
|----|-------|-------|-------|
| L-02 | `case context for supreme court and refused` → page 3 bundles | | |
| **L-02** | **`case context for supreme court with plaintiff damages of £1,000` → page 3** | | **Benchmark CARP** |
| L-03 | Refuse query (janet chester + agreement that) shows diagnostics | | |

## Visual (Phase 3 prep)

| ID | Check | Pass? |
|----|-------|-------|
| L-05 | 5 sampled hit bboxes align with PDF text | |

## Sign-off

- [ ] Tier A scorecard `tier_a_pass: true`
- [ ] Attorney / reviewer would rely on retrieval for client work (L-06)
