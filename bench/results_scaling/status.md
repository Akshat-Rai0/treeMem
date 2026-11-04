# Scaling Benchmark Status

Measured data from `progress.jsonl`. No extrapolation or estimation.

**Total episodes**: 305

**Note**: 20 private question episodes moved to `invalidated.jsonl` due to question format change.
These used the old question format (secret in question text) and must be rerun.

## Completion Matrix

Table shows completed episodes per size x arm x run (out of 50 per cell).

### Size 50

| Arm | Run 1 | Run 2 | Run 3 | Run 4 | Run 5 |
|-----|-------|-------|-------|-------|-------|
| flat | 46 | 46 | 38 | 0 | 0 |
| tree_follow | 3 | 0 | 0 | 0 | 0 |
| rag_bm25 | 3 | 0 | 0 | 0 | 0 |
| rag_bm25_k10 | 3 | 0 | 0 | 0 | 0 |

### Size 200

| Arm | Run 1 | Run 2 | Run 3 | Run 4 | Run 5 |
|-----|-------|-------|-------|-------|-------|
| flat | 46 | 0 | 0 | 0 | 0 |
| tree_follow | 46 | 0 | 0 | 0 | 0 |
| rag_bm25 | 46 | 0 | 0 | 0 | 0 |
| rag_bm25_k10 | 23 | 0 | 0 | 0 | 0 |

### Size 1000

| Arm | Run 1 | Run 2 | Run 3 | Run 4 | Run 5 |
|-----|-------|-------|-------|-------|-------|
| flat | 0 | 0 | 0 | 0 | 0 |
| tree_follow | 0 | 0 | 0 | 0 | 0 |
| rag_bm25 | 5 | 0 | 0 | 0 | 0 |
| rag_bm25_k10 | 0 | 0 | 0 | 0 | 0 |

### Size 5000

| Arm | Run 1 | Run 2 | Run 3 | Run 4 | Run 5 |
|-----|-------|-------|-------|-------|-------|
| flat | 0 | 0 | 0 | 0 | 0 |
| tree_follow | 0 | 0 | 0 | 0 | 0 |
| rag_bm25 | 0 | 0 | 0 | 0 | 0 |
| rag_bm25_k10 | 0 | 0 | 0 | 0 | 0 |

## Outcomes Breakdown

For each completed cell, count of each outcome type.

Note: 'request_exceeded_provider_token_limit' means the flat arm's prompt exceeded Groq's 7000 token per-request limit.

### Size 50

#### flat

| Run | ok | request_exceeded_provider_token_limit | api_error | rate_limited_giveup |
|-----|----|--------------------------------------|-----------|-------------------|
| 1 | 46 | 0 | 0 | 0 |
| 2 | 46 | 0 | 0 | 0 |
| 3 | 38 | 0 | 0 | 0 |
| 4 | - | - | - | - |
| 5 | - | - | - | - |

#### tree_follow

| Run | ok | request_exceeded_provider_token_limit | api_error | rate_limited_giveup |
|-----|----|--------------------------------------|-----------|-------------------|
| 1 | 3 | 0 | 0 | 0 |
| 2 | - | - | - | - |
| 3 | - | - | - | - |
| 4 | - | - | - | - |
| 5 | - | - | - | - |

#### rag_bm25

| Run | ok | request_exceeded_provider_token_limit | api_error | rate_limited_giveup |
|-----|----|--------------------------------------|-----------|-------------------|
| 1 | 3 | 0 | 0 | 0 |
| 2 | - | - | - | - |
| 3 | - | - | - | - |
| 4 | - | - | - | - |
| 5 | - | - | - | - |

#### rag_bm25_k10

| Run | ok | request_exceeded_provider_token_limit | api_error | rate_limited_giveup |
|-----|----|--------------------------------------|-----------|-------------------|
| 1 | 3 | 0 | 0 | 0 |
| 2 | - | - | - | - |
| 3 | - | - | - | - |
| 4 | - | - | - | - |
| 5 | - | - | - | - |

### Size 200

#### flat

| Run | ok | request_exceeded_provider_token_limit | api_error | rate_limited_giveup |
|-----|----|--------------------------------------|-----------|-------------------|
| 1 | 0 | 46 | 0 | 0 |
| 2 | - | - | - | - |
| 3 | - | - | - | - |
| 4 | - | - | - | - |
| 5 | - | - | - | - |

#### tree_follow

| Run | ok | request_exceeded_provider_token_limit | api_error | rate_limited_giveup |
|-----|----|--------------------------------------|-----------|-------------------|
| 1 | 46 | 0 | 0 | 0 |
| 2 | - | - | - | - |
| 3 | - | - | - | - |
| 4 | - | - | - | - |
| 5 | - | - | - | - |

#### rag_bm25

| Run | ok | request_exceeded_provider_token_limit | api_error | rate_limited_giveup |
|-----|----|--------------------------------------|-----------|-------------------|
| 1 | 46 | 0 | 0 | 0 |
| 2 | - | - | - | - |
| 3 | - | - | - | - |
| 4 | - | - | - | - |
| 5 | - | - | - | - |

#### rag_bm25_k10

| Run | ok | request_exceeded_provider_token_limit | api_error | rate_limited_giveup |
|-----|----|--------------------------------------|-----------|-------------------|
| 1 | 23 | 0 | 0 | 0 |
| 2 | - | - | - | - |
| 3 | - | - | - | - |
| 4 | - | - | - | - |
| 5 | - | - | - | - |

### Size 1000

#### flat

| Run | ok | request_exceeded_provider_token_limit | api_error | rate_limited_giveup |
|-----|----|--------------------------------------|-----------|-------------------|
| 1 | - | - | - | - |
| 2 | - | - | - | - |
| 3 | - | - | - | - |
| 4 | - | - | - | - |
| 5 | - | - | - | - |

#### tree_follow

| Run | ok | request_exceeded_provider_token_limit | api_error | rate_limited_giveup |
|-----|----|--------------------------------------|-----------|-------------------|
| 1 | - | - | - | - |
| 2 | - | - | - | - |
| 3 | - | - | - | - |
| 4 | - | - | - | - |
| 5 | - | - | - | - |

#### rag_bm25

| Run | ok | request_exceeded_provider_token_limit | api_error | rate_limited_giveup |
|-----|----|--------------------------------------|-----------|-------------------|
| 1 | 5 | 0 | 0 | 0 |
| 2 | - | - | - | - |
| 3 | - | - | - | - |
| 4 | - | - | - | - |
| 5 | - | - | - | - |

#### rag_bm25_k10

| Run | ok | request_exceeded_provider_token_limit | api_error | rate_limited_giveup |
|-----|----|--------------------------------------|-----------|-------------------|
| 1 | - | - | - | - |
| 2 | - | - | - | - |
| 3 | - | - | - | - |
| 4 | - | - | - | - |
| 5 | - | - | - | - |

### Size 5000

#### flat

| Run | ok | request_exceeded_provider_token_limit | api_error | rate_limited_giveup |
|-----|----|--------------------------------------|-----------|-------------------|
| 1 | - | - | - | - |
| 2 | - | - | - | - |
| 3 | - | - | - | - |
| 4 | - | - | - | - |
| 5 | - | - | - | - |

#### tree_follow

| Run | ok | request_exceeded_provider_token_limit | api_error | rate_limited_giveup |
|-----|----|--------------------------------------|-----------|-------------------|
| 1 | - | - | - | - |
| 2 | - | - | - | - |
| 3 | - | - | - | - |
| 4 | - | - | - | - |
| 5 | - | - | - | - |

#### rag_bm25

| Run | ok | request_exceeded_provider_token_limit | api_error | rate_limited_giveup |
|-----|----|--------------------------------------|-----------|-------------------|
| 1 | - | - | - | - |
| 2 | - | - | - | - |
| 3 | - | - | - | - |
| 4 | - | - | - | - |
| 5 | - | - | - | - |

#### rag_bm25_k10

| Run | ok | request_exceeded_provider_token_limit | api_error | rate_limited_giveup |
|-----|----|--------------------------------------|-----------|-------------------|
| 1 | - | - | - | - |
| 2 | - | - | - | - |
| 3 | - | - | - | - |
| 4 | - | - | - | - |
| 5 | - | - | - | - |

## Accuracy

Accuracy is reported only for cells with at least 50 completed episodes in at least 3 runs.
Cells with insufficient data show 'insufficient data'.

### Size 50

| Arm | Accuracy |
|-----|----------|
| flat | insufficient data |
| tree_follow | insufficient data |
| rag_bm25 | insufficient data |
| rag_bm25_k10 | insufficient data |

### Size 200

| Arm | Accuracy |
|-----|----------|
| flat | insufficient data |
| tree_follow | insufficient data |
| rag_bm25 | insufficient data |
| rag_bm25_k10 | insufficient data |

### Size 1000

| Arm | Accuracy |
|-----|----------|
| flat | insufficient data |
| tree_follow | insufficient data |
| rag_bm25 | insufficient data |
| rag_bm25_k10 | insufficient data |

### Size 5000

| Arm | Accuracy |
|-----|----------|
| flat | insufficient data |
| tree_follow | insufficient data |
| rag_bm25 | insufficient data |
| rag_bm25_k10 | insufficient data |

