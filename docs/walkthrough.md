# Build your understanding from the execution boundary upward

The project separates three kinds of decisions: the model proposes SQL, SQLite decides whether it can execute, and ordinary Python decides what node runs next. You should be able to replace Groq with a scripted responder without changing the graph. The tests demonstrate that separation.

## 1. Reproduce the database layer

Read `src/database.py`. `Path.resolve()` gives an absolute location; checking `is_file()` prevents SQLite from silently creating an empty database on a typo. `as_uri()` safely encodes spaces and other special path characters. `mode=ro` makes the database read-only. `closing()` matters: SQLite's connection context manager manages transactions but does not close the connection for you.

`schema()` reads DDL from `sqlite_master`; foreign-key declarations help the model choose joins. It does not scan the database's rows. `execute()` installs an authorizer after connection setup, permitting only operations needed for reading. This is why a valid SELECT CTE works while a CTE preceding DELETE fails. SQL fences are a presentation concern, not a security boundary.

`perf_counter()` is a monotonic clock suitable for elapsed durations. The progress callback returns nonzero after the deadline, which interrupts SQLite work. `fetchmany(max_rows + 1)` detects overflow rather than mistaking a truncated result for the complete answer. A list of columns and positional rows preserves duplicate column names in joins; converting rows directly into dictionaries could overwrite those names.

Exercise: write a SELECT and a DELETE against the test fixture. Predict which authorizer operations each requires. Explain why denying only strings beginning with DELETE would be insufficient.

## 2. Understand the state contract

Read `src/agent/state.py`. `TypedDict` describes dictionary keys to type checkers; it does not validate arbitrary runtime input. `initial_state()` creates every required field and rejects empty questions. `None` for the result means no successful execution; an empty `rows` list is a valid successful query.

The seven requested fields contain the functional workflow. `attempts`, `correction_seconds`, and `llm_error` provide evidence for evaluation and distinguish provider outages from SQL errors. Attempt history is not a transcript and is not automatically sent to the model.

Nodes return partial dictionaries because LangGraph merges node updates into the current state. Without an explicit reducer, a returned key replaces its old value. `[*state['attempts'], attempt]` creates a new history list; appending directly would mutate the input snapshot and make reasoning harder. Adding an append reducer as well would double-count history.

Exercise: explain why the schema need not be returned by every node and why `retry_count` must not increment during successful execution.

## 3. Trace one complete repair

Suppose generation returns `SELECT FullName FROM Customer`. Chinook has `FirstName` and `LastName`, so execution fails.

| Step | Key state changes | Next node |
| --- | --- | --- |
| generate_sql | generated_sql contains the invalid SELECT | execute_sql |
| execute_sql | error_message contains a traceback; retry_count becomes 1; attempts has one entry | self_correct |
| self_correct | generated_sql becomes a corrected SELECT; correction duration is recorded | execute_sql |
| execute_sql | result contains rows; error_message becomes None; retry_count remains 1 | format_response |
| format_response | final_answer is populated | END |

`traceback.format_exc()` is called inside `except sqlite3.Error`, where the active traceback exists. The repair prompt contains the original question, schema, failed SQL, and raw error. Without the original question, a repair could satisfy SQLite while abandoning the task. Without schema, the model might guess another nonexistent column.

The router is pure: it reads state and returns a node name. A conditional edge maps that name to a destination. The fixed edge from self_correct to execute_sql creates the cycle. Compilation checks the graph structure and produces a runnable object; it does not precompute model outputs or make them deterministic.

Exercise: trace three consecutive errors. There are three executions and two correction calls. Explain why a fourth execution is unreachable with the current router. Then run `test_streamed_cycle_clears_error` and compare the actual node order with your prediction.

## 4. Separate provider failure from SQL failure

The model dependency follows a small Protocol with `invoke(messages)`. Groq and the scripted test model both meet that interface. `create_llm()` is called only by live entry points, so tests need no API key. Model exceptions are caught at that boundary and represented by their type, avoiding propagation of provider error text into user output. Programming mistakes outside model calls still surface normally.

Initial-generation and repair provider failures terminate gracefully. A formatting outage preserves the successful SQL result and gives a factual result preview. Groq's SDK can retry transport requests, but those retries are separate from the graph's SQL corrections. This distinction affects latency and API usage.

Exercise: inject `RuntimeError` on the second model call. Predict whether that call was repair or formatting from the first SQL result, and explain why the two terminal behaviors differ.

## 5. Measure correctness independently

Read `src/evaluation.py` after the routing tests. SQL-string equality is too strict: aliases and equivalent join structures can differ while producing the same result. Execution success is too weak: `SELECT 42` executes perfectly but answers almost none of the dataset questions.

The comparator checks column count and positional values. Ordered tasks retain rank order. Unordered tasks use matching over rows so duplicates are preserved. Numeric tolerances absorb small floating-point differences; NULL, zero, and text remain distinct. For unordered rows, the matching algorithm can reassign an earlier pairing when several numeric values fall inside tolerance. This avoids a greedy false negative, at the cost of more work than hashing exact rows.

Reference SQL is also code and can contain mistakes. The tiny fixture has independently calculated expected answers to anchor the 12 golden queries. The real Chinook integration test checks that each runs on the actual schema. This still does not prove equivalence on every possible database: add adversarial fixtures with ties, duplicate names, missing children, and NULLs as the suite grows.

Example: among 12 questions, 7 are correct immediately, 3 initially fail SQL, 2 of those become correct, and 2 execute incorrectly on the first try. First-try accuracy is 7/12, correction success is 2/3, and final accuracy is 9/12. If the remaining initially failing query becomes executable but wrong, execution recovery is 3/3 while correction success stays 2/3.

Exercise: add a query that executes but double-counts invoice totals after a join. Verify the evaluator fails it and explain why the runtime agent cannot repair it using SQLite errors alone.

## 6. Rebuild and defend the design

Reimplement the modules in this order without copying: database, state, router, nodes, graph, evaluation, CLI. Keep each existing test as a behavioral specification. Before reading a failed assertion, predict whether the defect concerns state, routing, SQL semantics, or result comparison.

Be ready to explain these tradeoffs in your own words:

- Why use a graph when a while loop could implement the same behavior? The graph exposes transitions, streaming, and future extension points, at the cost of a dependency and state contract.
- What makes the workflow agentic? A model proposes an action, receives execution feedback, and revises it within a bounded control loop; Python owns the routing.
- Why stop after two corrections? It bounds model cost and repeated failures; the threshold should ultimately be informed by measured recovery and latency.
- What remains unmeasured? Natural-language faithfulness, generalization outside 12 questions, authorization, and robustness under concurrent production load.
- How would semantic correction work? Add an independently evaluated validation signal, such as invariant checks or a separate verifier, and measure false approvals and added latency before expanding the cycle. Never use test-set gold SQL as a runtime hint.
- Why is temperature zero insufficient for reproducibility? Provider execution and serving behavior can vary; record versions and run repeated live benchmarks. Scripted offline tests isolate deterministic application behavior.

The next useful milestone is to run the live benchmark, inspect every incorrect result, and classify each failure as schema selection, join logic, aggregation, ordering, or provider failure. Use a separate development set for prompt changes and preserve a held-out set for honest reporting.
