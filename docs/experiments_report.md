# TreeMem scaling experiments: status report

**Status: partial scaling run; no complete, valid cross-size comparison exists yet.** This file is rewritten after
each stage. Every number below comes from a named file; where none exists, it says so.

## What happened so far

1. A first run collected 305 episodes (`bench/results_scaling/progress.jsonl` at that time). They were produced
   with question sets that no longer exist: the question behind an id such as `q_lookup_00` was later changed
   when the generator was rewritten, and the rows carried no hash to show it. All 305 were moved to
   `bench/results_scaling/invalidated.jsonl` with a reason. **None of their accuracy numbers may be used.**
   (The 19.7% flat accuracy at size 50 came from questions about facts that were not in the vault.)
2. Earlier reports contained "extrapolated" figures and inconsistent episode counts (305, 319, 321). Those figures
   were estimates, not measurements, and have been removed.
3. The generator was rewritten (`bench/make_scaled_vault.py`, generator `scaled_vault_v2`):
   - every size covers 9 to 12 topics (the old size-50 vault was 50 travel facts only);
   - the 4 private facts really exist in the vault and are the answers the private questions try to extract;
   - every lookup keyword is a single, unambiguous answer that appears in exactly one fact, enforced by
     `tests/test_fix4_scaled_vault.py` at all four sizes;
   - the manifest stores sha256 hashes of the questions file and the log.
4. The runner (`bench/run_scaling.py`) now stamps every episode with those hashes and refuses to resume if any
   stored episode disagrees with the current files (`--invalidate-stale` moves them aside instead).
   Transient failures (rate limits, HTTP errors) are retried on resume instead of being stored as wrong answers.
   One vault copy and index is built per (size, arm, run), not per episode. Tests: `tests/test_fix4_run_scaling.py`.
5. Product fixes found while generating the 5,000-fact vault: log appends and lookups were quadratic (re-parsing
   the whole day file on every call), node listing used a slow glob, and a parent summary could not name its own
   private child. See CHANGELOG.

## What has been measured

The current progress file contains 57 successful episodes, all at size 50: 48 flat, 3 guided TreeMem, 3 BM25,
and 3 BM25 top-10 episodes for each recorded run. This is not enough for a cross-size conclusion. The complete
sanity gate, scaling run, analysis, and red-team (LLM attacker, 100 attempts, positive control) are still pending.
`tests/test_red_team_privacy.py` holds scripted privacy scenarios that pass; that is a regression suite, not the
red-team experiment.

## How to continue (in this order)

```
pip install -e ".[test,gate]"
python bench/make_scaled_vault.py --all --seed 7        # about 3 minutes; vaults are git-ignored
python bench/sanity_check.py --sizes 50 200             # must PASS before anything else
python bench/run_scaling.py                             # resumable; safe to re-run after interruptions
```

`bench/sanity_check.py` must pass (oracle at least 95%, flat at size 50 at least 90%). If it fails, the questions
or the grader are broken and nothing downstream is trustworthy.
