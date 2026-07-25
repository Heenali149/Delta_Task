# Cost & latency budget -- pair_001 QA set

Model: `llama-3.3-70b-versatile` &middot; 6 questions, one live LLM call each (no caching).

| Question | retrieval (ms) | LLM call (ms) | total (ms) | in tok | out tok | cost (USD) |
|---|---|---|---|---|---|---|
| QA01 | 3.1 | 2202.4 | 2205.6 | 670 | 33 | 0.000421 |
| QA02 | 2.2 | 372.4 | 374.6 | 660 | 33 | 0.000415 |
| QA03 | 1.6 | 325.5 | 327.2 | 615 | 32 | 0.000388 |
| QA04 | 2.6 | 226.1 | 228.8 | 717 | 26 | 0.000444 |
| QA05 | 2.6 | 204.2 | 206.8 | 616 | 18 | 0.000378 |
| QA06 | 1.6 | 260.6 | 262.3 | 565 | 44 | 0.000368 |

## Summary

- Avg retrieval latency: **2.3 ms** (TF-IDF over ~1,500 chunks -- not the bottleneck)
- Avg LLM call latency: **598.5 ms** (100% of total request time)
- Avg total latency per question: **600.9 ms**
- Avg cost per question: **$0.000402**
- This run's total cost (6 questions): **$0.002414**
- Projected cost at 10,000 questions/month: **$4.02/month**

Retrieval is effectively free and fast; nearly all latency and 100% of marginal cost is the LLM call, which is exactly why the LLM boundary in this system is drawn where it is (see README "Design decisions") -- everything upstream (ingest, align, delta, retrieval) is deterministic and free to re-run. A cache on repeated/near-duplicate questions would cut the monthly figure in direct proportion to the repeat rate.
