# Implementation and evaluation notes

## Execution boundary

The model proposes SQL, SQLite evaluates it, and deterministic Python routing selects the next node. A model implementing `invoke(messages)` can replace Groq without changing graph construction. Tests use that interface to isolate application behavior from provider variation.

`Database` resolves the database path and verifies its existence before connecting, preventing accidental creation of an empty SQLite database. A URI with `mode=ro` opens read-only access. Connections are explicitly closed: SQLite's connection context manager alone manages transactions, not connection lifetime.

The schema inspector reads table DDL, including foreign keys. Generated queries pass through a SQLite authorizer that permits read operations. Single-statement execution, a cooperative progress deadline, a SQL-length limit, and bounded result fetching constrain execution. An overflow produces an error rather than a silently truncated reference comparison.

Results retain column names and positional rows. This supports joins with duplicate column names without overwriting values in a dictionary.

## State contract

`AgentState` defines the question, schema, current SQL, execution result, error, failure count, and final answer. Additional fields record attempts, correction duration, and provider errors. `TypedDict` supplies static typing, not runtime validation; `initial_state()` initializes fields and rejects empty questions.

Nodes return partial state updates. Each supplied key replaces its previous value. Attempt history is replaced with a new list, so no append reducer is needed. A missing result means no successful execution; an empty row list can be a successful query.

## Bounded correction

For a generated query referring to a nonexistent column, the sequence is:

| Step | State change |
| --- | --- |
| generate_sql | Stores proposed SQL |
| execute_sql | Stores SQLite traceback and increments failure count |
| self_correct | Supplies question, schema, failed SQL, and traceback to the model |
| execute_sql | Stores corrected result and clears error on success |
| format_response | Generates an explanation grounded in the result preview |

Routing uses only state, without mutation or model calls. Three failed executions terminate the run: one initial execution and at most two corrections. The graph recursion limit is a separate backstop.

The original question remains in correction prompts to preserve intent. SQLite feedback identifies execution problems, but provides no signal when executable SQL answers the wrong question. There is no semantic-verification or clarification stage in this version.

LangGraph can stream a `None` update for a node that writes no state. The CLI skips that update and continues consuming events, allowing the terminal failure node to run.

## Provider failures

Provider exceptions are handled separately from SQL errors and recorded by exception type. Generation and correction failures terminate gracefully. Formatting failure preserves the successful SQL result and returns a result preview. Transport retries within a model call are distinct from SQL correction attempts.

Generation and repair prompts receive schema and question data, never reference SQL or benchmark labels. Response formatting receives a bounded result preview. Formatting quality is not inferred from execution accuracy.

## Result comparison

Execution scoring compares reference and generated result values, not SQL strings. Equivalent queries may differ syntactically. Column aliases are ignored, while positional values and column counts must match.

Ordered tasks retain row order. Unordered tasks preserve duplicate multiplicities using iterative matching, including reassignment when numeric tolerance permits several candidate pairs. Numeric tolerances accommodate small floating-point differences; NULL, text, and zero remain distinct.

Reference SQL is itself fallible. The small relational fixture has independently calculated expected answers; real Chinook integration checks verify that the queries execute on the released schema. These checks do not prove equivalence over every possible database instance.

## Metric interpretation

First-try and final accuracy use all SQL questions as their denominator. Correction success uses initially SQL-failing questions only. Execution recovery is weaker than correctness: a revised query may execute while returning the wrong answer.

For illustration only, suppose 12 questions produce seven correct first answers, three SQL failures, and two executable but incorrect answers. If two of the three SQL failures become correct, first-try accuracy is 7/12, correction success is 2/3, and final accuracy is 9/12. These hypothetical values are not experimental results.

Behavioral cases require separate manual judgments. Clarification, missing-data explanations, and helpful refusal cannot be established by SQL execution success. Reports retain review evidence and keep those denominators separate.

## Reproducibility and limits

The robustness runner records model/package versions, dataset/database hashes, source hashes, and selected case IDs. Each question starts with fresh state. Saved reports permit analysis without additional model calls.

Temperature zero does not guarantee reproducible provider responses. Report repeated runs and family-level comparisons; matched paraphrases are correlated. Keep development changes separate from future held-out intent families.

The container constrains resources and filesystem access, but the application is a local experimental CLI without per-user data authorization, durable conversation state, or a public service interface. Remaining research dimensions include semantic error detection, clarification completion, unseen schemas, and natural-language faithfulness.
