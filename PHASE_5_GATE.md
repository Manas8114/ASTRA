# PHASE 5 GATE — Root-Cause Ranking

**Date completed:** 2026-07-23  
**Status:** ✅ PASSED  

---

## 1. Ranking Logic and Rules

To prevent false positives, CR²E implements a robust ranking policy:
1. **Statistical Significance First:** All candidates where the 95% confidence interval does NOT contain zero are sorted first.
2. **ATE Magnitude Sorting:** Within significant candidates, sorting is by absolute Average Treatment Effect (`|ATE|`) descending.
3. **Failing Refutations Flagged:** Candidates with failing refutations are NOT discarded (which would violate anti-fabrication) but are flagged with a warning in the ranking report.
4. **Insufficient Data Excluded:** Candidates with insufficient rows (<200) are excluded from ranking to prevent noise propagation.

---

## 2. Verification Against Planted Cause
`cr2e/tests/test_ranker.py` verifies the ranking logic against synthetic scenarios:
- **Test cases:**
  - Planted significant cause (`slice_utilisation_pct` with ATE=0.8, CI=[0.6, 1.0]) correctly ranks #1.
  - Significant cause with smaller ATE ranks above non-significant cause with huge ATE (prioritizes certainty).
  - Top-K limiting successfully restricts list size.
  - Refutation failures are visible but carry warnings.

**Gate Decision:** PASSED. Root-cause ranking logic unit-tested and verified.
