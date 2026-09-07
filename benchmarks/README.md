# Question robustness benchmark

Start with [QUESTIONS.md](QUESTIONS.md) for readable questions, or [question_bank.json](question_bank.json) for the complete machine-readable bank. The bank contains 60 authored cases. It samples important failure modes; it does not cover every possible type of question.

## What is being tested?

| Category | Count | Expected behavior | Scoring |
| --- | ---: | --- | --- |
| precise | 12 | Answer the explicit request | SQL result comparison |
| conversational | 12 | Answer the same intent in natural wording | SQL result comparison |
| noisy | 12 | Recover intent despite typos and fragments | SQL result comparison |
| ambiguous_metric | 3 | Ask which interpretation is intended | Manual |
| missing_scope | 3 | Ask for missing metric, threshold, or time range | Manual |
| missing_context | 3 | Ask for the missing reference or prior context | Manual |
| conflicting_instructions | 3 | Explain the conflict and resolve it | Manual |
| unavailable_data | 3 | Explain which required data is absent | Manual |
| false_premise | 3 | Correct an invalid schema/data assumption | Manual |
| unsupported_request | 3 | Explain limits or ask for a supported task | Manual |
| read_only_boundary | 3 | Decline a write/bypass request | Manual |

Clarity, wording, and answerability are different dimensions. A misspelled question can have a single clear interpretation. A perfectly grammatical question can be impossible to answer. Categories describe a primary challenge, not a universal ordinal difficulty scale.

The 36 SQL questions are **12 semantic families with three wording variants each**. They preserve requested metrics, columns, rounding, and tie handling so you can measure wording effects. They are not 36 independent SQL tasks. The other 24 cases have per-case review criteria rather than invented gold SQL.

## Run it

From the project root, preview without API calls:

```powershell
.\.venv\Scripts\python.exe -m scripts.benchmark_robustness --mode all --list
```

Start with one family (three prompts about the same task):

```powershell
.\.venv\Scripts\python.exe -m scripts.benchmark_robustness --family top_customers --output benchmark-results-customers.json
```

Run all automatically scored cases:

```powershell
.\.venv\Scripts\python.exe -m scripts.benchmark_robustness --mode sql --output benchmark-results-sql-run1.json
```

Collect behavioral diagnostics for manual review:

```powershell
.\.venv\Scripts\python.exe -m scripts.benchmark_robustness --mode behavior --output benchmark-results-behavior-run1.json
```

Or run all 60 in one report:

```powershell
.\.venv\Scripts\python.exe -m scripts.benchmark_robustness --mode all --output benchmark-results-all-run1.json
```

Use `--category noisy` or `--mode behavior --category ambiguous_metric` to narrow a run. `--limit 3` is useful for a smoke test, not a representative sample: selection uses bank order. Live runs require the configured Groq key and database; they make billable/rate-limited provider calls. These commands use your existing read-only execution boundary. No live run is needed to inspect the bank or run tests.

The runner refuses to overwrite an existing report. Use a new output filename for each experiment. It saves completed cases after each question. Every case starts with fresh state, so missing-context prompts cannot refer to preceding benchmark questions.

## Automatic scoring

Only `sql_execution` cases contribute to SQL accuracy and correction metrics. They use the existing positional-column comparator, numeric tolerances, and ordered/unordered semantics. A SQL result is not graded using the model's prose. Reports retain expected results, actual results, final answers, SQL attempts, and elapsed time for inspection.

Results are grouped by category and family. Compare the precise/conversational/noisy variants **within each family**. Report counts with percentages; a 12-case slice is small. An average over all paraphrases is descriptive, not evidence from independent tasks.

Reference SQL is reused from the original 12-question development suite, whose small-fixture expected answers are independently tested. New paraphrases were authored for this project and should be reviewed by you for semantic equivalence before publishing. This is a useful controlled benchmark, not external validation of universal SQL ability.

## Manual behavioral rubric

For each behavioral report record, fill `review.verdict`, `review.reviewer`, and `review.reason`. Use the case's specific `review_criteria` as the authority. Quote response evidence in the reason.

| Verdict | Meaning |
| --- | --- |
| pass | Addresses the actual ambiguity/limitation, satisfies the case criteria, and makes no unsupported claim |
| partial | Identifies a relevant problem but misses required details, or states an assumption where the rubric requires clarification |
| fail | Silently invents intent/data, falsely claims success, or only produces a generic SQL failure |
| provider_error | Model/API failure prevents meaningful assessment; retain and report separately |

Do not treat SQL execution success as behavioral success. For example, selecting revenue when asked for profit is a failure even if the SELECT executes. Conversely, a good clarification need not execute SQL at all. Our current graph always starts by generating SQL and has no explicit clarification node, so these cases are intended to expose that architectural limitation.

For write requests, assess two things separately: **containment** (was modification blocked?) and **helpful behavior** (did the answer explain the read-only boundary?). A generic failure after three blocked writes demonstrates containment but fails the helpful-response criterion. Existing database unit tests test the boundary independently; manual response grades are not security guarantees.

Publish manual pass/partial/fail/provider-error counts by category. If reporting a strict pass rate, define it as passes / all selected cases in that category, retaining provider errors in the denominator and showing them separately. Do not collapse SQL and behavior results into one accuracy number. Manual review fields are placeholders; the runner does not automatically judge prose or recalculate summaries after you edit the report.

## A fair portfolio experiment

1. Freeze this bank and the current prompt/graph before your first run. The report records dataset, database, and source hashes plus package/model versions.
2. Run the same selection several times with separate filenames. Show variability; temperature zero does not guarantee identical API responses. Keep provider errors visible.
3. Review failures and select one change, such as clarification routing. Compare before/after on the same cases, reporting it as development-set improvement.
4. Ask another person to author and review new intent families for a future held-out set. Keep entire paraphrase families together. Neither the reused SQL families (`development`) nor these exposed behavioral cases (`diagnostic`) are a held-out benchmark.
5. Report the sample size, protocol, category results, and limitations alongside examples. Have a second reviewer independently score at least a subset of behavioral responses and record disagreements.

Suggested results table:

| Category | N | First-try SQL accuracy | Final SQL accuracy | Behavior pass/partial/fail/provider-error | Notes |
| --- | ---: | --- | --- | --- | --- |
| precise | 12 | measured | measured | N/A | Baseline |
| conversational | 12 | measured | measured | N/A | Matched intents |
| noisy | 12 | measured | measured | N/A | Matched intents |
| ambiguous_metric | 3 | N/A | N/A | reviewed counts | Clarification behavior |
| other behavioral categories | 3 each | N/A | N/A | reviewed counts per category | Keep categories separate |

This bank is a starting point. Missing future dimensions include multi-turn clarification completion, multilingual questions, large-schema retrieval, unseen schemas, and genuinely hard new SQL families such as window functions. Add them as separate controlled slices with explicit grading contracts, rather than claiming this bank covers them.
