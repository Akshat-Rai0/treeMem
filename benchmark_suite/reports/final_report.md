# TreeMem Comprehensive Benchmark Report

## Executive Summary
This report is generated only from measured benchmark outputs. Sections without completed experiments are marked **not run** rather than estimated.

## ablation
```json
{
  "arms": {
    "treemem_guided": {
      "by_category": {
        "ambiguous": {
          "context_tokens": 166.0,
          "count": 3,
          "f1@1": 1.0,
          "f1@10": 0.1818181818181818,
          "f1@3": 0.5,
          "f1@5": 0.3333333333333333,
          "full_support": 1.0,
          "latency_ms": 7.634791681387772,
          "map": 1.0,
          "mrr": 1.0,
          "ndcg@1": 1.0,
          "ndcg@10": 1.0,
          "ndcg@3": 1.0,
          "ndcg@5": 1.0,
          "precision@1": 1.0,
          "precision@10": 0.10000000000000002,
          "precision@3": 0.3333333333333333,
          "precision@5": 0.20000000000000004,
          "recall@1": 1.0,
          "recall@10": 1.0,
          "recall@3": 1.0,
          "recall@5": 1.0
        },
        "direct": {
          "context_tokens": 143.16666666666666,
          "count": 30,
          "f1@1": 0.6,
          "f1@10": 0.1090909090909091,
          "f1@3": 0.3,
          "f1@5": 0.20000000000000004,
          "full_support": 0.6,
          "latency_ms": 9.14067083116,
          "map": 0.6,
          "mrr": 0.6,
          "ndcg@1": 0.6,
          "ndcg@10": 0.6,
          "ndcg@3": 0.6,
          "ndcg@5": 0.6,
          "precision@1": 0.6,
          "precision@10": 0.060000000000000005,
          "precision@3": 0.2,
          "precision@5": 0.12000000000000001,
          "recall@1": 0.6,
          "recall@10": 0.6,
          "recall@3": 0.6,
          "recall@5": 0.6
        },
        "long_context": {
          "context_tokens": 174.66666666666666,
          "count": 27,
          "f1@1": 0.5555555555555556,
          "f1@10": 0.12121212121212122,
          "f1@3": 0.3333333333333333,
          "f1@5": 0.22222222222222227,
          "full_support": 0.6666666666666666,
          "latency_ms": 8.664378139656037,
          "map": 0.6111111111111112,
          "mrr": 0.6111111111111112,
          "ndcg@1": 0.5555555555555556,
          "ndcg@10": 0.6256588615079397,
          "ndcg@3": 0.6256588615079397,
          "ndcg@5": 0.6256588615079397,
          "precision@1": 0.5555555555555556,
          "precision@10": 0.06666666666666667,
          "precision@3": 0.2222222222222222,
          "precision@5": 0.13333333333333333,
          "recall@1": 0.5555555555555556,
          "recall@10": 0.6666666666666666,
          "recall@3": 0.6666666666666666,
          "recall@5": 0.6666666666666666
        },
        "semantic": {
          "context_tokens": 148.46666666666667,
          "count": 30,
          "f1@1": 0.6,
          "f1@10": 0.1090909090909091,
          "f1@3": 0.3,
          "f1@5": 0.20000000000000004,
          "full_support": 0.6,
          "latency_ms": 9.201676532393321,
          "map": 0.6,
          "mrr": 0.6,
          "ndcg@1": 0.6,
          "ndcg@10": 0.6,
          "ndcg@3": 0.6,
          "ndcg@5": 0.6,
          "precision@1": 0.6,
          "precision@10": 0.060000000000000005,
          "precision@3": 0.2,
          "precision@5": 0.12000000000000001,
          "recall@1": 0.6,
          "recall@10": 0.6,
          "recall@3": 0.6,
          "recall@5": 0.6
        }
      },
      "context_tokens": {
        "count": 90,
        "max": 183.0,
        "mean": 155.14444444444445,
        "median": 165.0,
        "min": 0.0,
        "p90": 176.20000000000002,
        "p95": 179.0,
        "p99": 183.0,
        "std": 38.128275836014616
      },
      "errors": 0,
      "latency_ms": {
        "count": 90,
        "max": 14.437542005907744,
        "mean": 8.967922285794177,
        "median": 7.894749956903979,
        "min": 6.981999962590635,
        "p90": 11.837866704445332,
        "p95": 13.490249981987288,
        "p99": 14.248305739602074,
        "std": 2.0450744535160488
      },
      "overall": {
        "context_tokens": 155.14444444444445,
        "count": 90,
        "f1@1": 0.6,
        "f1@10": 0.11515151515151514,
        "f1@3": 0.31666666666666665,
        "f1@5": 0.21111111111111114,
        "full_support": 0.6333333333333333,
        "latency_ms": 8.967922285794177,
        "map": 0.6166666666666667,
        "mrr": 0.6166666666666667,
        "ndcg@1": 0.6,
        "ndcg@10": 0.6210309917857153,
        "ndcg@3": 0.6210309917857153,
        "ndcg@5": 0.6210309917857153,
        "precision@1": 0.6,
        "precision@10": 0.06333333333333334,
        "precision@3": 0.2111111111111111,
        "precision@5": 0.12666666666666668,
        "recall@1": 0.6,
        "recall@10": 0.6333333333333333,
        "recall@3": 0.6333333333333333,
        "recall@5": 0.6333333333333333
      }
    },
    "treemem_manual": {
      "by_category": {
        "ambiguous": {
          "context_tokens": 0.0,
          "count": 2,
          "f1@1": 0.0,
          "f1@10": 0.0,
          "f1@3": 0.0,
          "f1@5": 0.0,
          "full_support": 0.0,
          "latency_ms": 4.847791540669277,
          "map": 0.0,
          "mrr": 0.0,
          "ndcg@1": 0.0,
          "ndcg@10": 0.0,
          "ndcg@3": 0.0,
          "ndcg@5": 0.0,
          "precision@1": 0.0,
          "precision@10": 0.0,
          "precision@3": 0.0,
          "precision@5": 0.0,
          "recall@1": 0.0,
          "recall@10": 0.0,
          "recall@3": 0.0,
          "recall@5": 0.0
        },
        "direct": {
          "context_tokens": 9.1,
          "count": 20,
          "f1@1": 0.0,
          "f1@10": 0.0,
          "f1@3": 0.0,
          "f1@5": 0.0,
          "full_support": 0.0,
          "latency_ms": 8.203879202483222,
          "map": 0.0,
          "mrr": 0.0,
          "ndcg@1": 0.0,
          "ndcg@10": 0.0,
          "ndcg@3": 0.0,
          "ndcg@5": 0.0,
          "precision@1": 0.0,
          "precision@10": 0.0,
          "precision@3": 0.0,
          "precision@5": 0.0,
          "recall@1": 0.0,
          "recall@10": 0.0,
          "recall@3": 0.0,
          "recall@5": 0.0
        },
        "long_context": {
          "context_tokens": 10.11111111111111,
          "count": 18,
          "f1@1": 0.0,
          "f1@10": 0.0,
          "f1@3": 0.0,
          "f1@5": 0.0,
          "full_support": 0.0,
          "latency_ms": 8.666634514358723,
          "map": 0.0,
          "mrr": 0.0,
          "ndcg@1": 0.0,
          "ndcg@10": 0.0,
          "ndcg@3": 0.0,
          "ndcg@5": 0.0,
          "precision@1": 0.0,
          "precision@10": 0.0,
          "precision@3": 0.0,
          "precision@5": 0.0,
          "recall@1": 0.0,
          "recall@10": 0.0,
          "recall@3": 0.0,
          "recall@5": 0.0
        },
        "semantic": {
          "context_tokens": 9.1,
          "count": 20,
          "f1@1": 0.0,
          "f1@10": 0.0,
          "f1@3": 0.0,
          "f1@5": 0.0,
          "full_support": 0.0,
          "latency_ms": 8.060310102882795,
          "map": 0.0,
          "mrr": 0.0,
          "ndcg@1": 0.0,
          "ndcg@10": 0.0,
          "ndcg@3": 0.0,
          "ndcg@5": 0.0,
          "precision@1": 0.0,
          "precision@10": 0.0,
          "precision@3": 0.0,
          "precision@5": 0.0,
          "recall@1": 0.0,
          "recall@10": 0.0,
          "recall@3": 0.0,
          "recall@5": 0.0
        }
      },
      "context_tokens": {
        "count": 60,
        "max": 38.0,
        "mean": 9.1,
        "median": 0.0,
        "min": 0.0,
        "p90": 28.100000000000016,
        "p95": 38.0,
        "p99": 38.0,
        "std": 14.335803229581805
      },
      "errors": 0,
      "latency_ms": {
        "count": 60,
        "max": 16.129417053889483,
        "mean": 8.182979840785265,
        "median": 6.8118755298200995,
        "min": 4.771750012878329,
        "p90": 13.358621526276693,
        "p95": 14.671854936750602,
        "p99": 15.955121003789825,
        "std": 3.5946754837759256
      },
      "overall": {
        "context_tokens": 9.1,
        "count": 60,
        "f1@1": 0.0,
        "f1@10": 0.0,
        "f1@3": 0.0,
        "f1@5": 0.0,
        "full_support": 0.0,
        "latency_ms": 8.1829798407852
```
# Benchmark Tables

## Table A — Retrieval Quality
| System | P@5 | R@5 | F1@5 | MRR | MAP | NDCG@10 |
|---|---:|---:|---:|---:|---:|---:|
| treemem_guided | 0.127 | 0.633 | 0.211 | 0.617 | 0.617 | 0.621 |
| treemem_manual | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |

## Table B — Context Efficiency
| System | Mean Tokens | Median Tokens | P95 Tokens | Max Tokens |
|---|---:|---:|---:|---:|
| treemem_guided | 155.1 | 165.0 | 179.0 | 183.0 |
| treemem_manual | 9.1 | 0.0 | 38.0 | 38.0 |

## Table D — Latency
| System | Retrieval P50 | Retrieval P95 | Mean | P99 |
|---|---:|---:|---:|---:|
| treemem_guided | 7.89 | 13.49 | 8.97 | 14.25 |
| treemem_manual | 6.81 | 14.67 | 8.18 | 15.96 |

Manifest: `ablation/manifest.json`

## e2e
```json
{
  "arms": {
    "bm25": {
      "by_category": {
        "ambiguous": {
          "context_tokens": 147.4,
          "count": 10
        },
        "broad": {
          "context_tokens": 150.0,
          "count": 6
        },
        "direct": {
          "context_tokens": 164.2,
          "count": 10
        },
        "hierarchical": {
          "context_tokens": 159.83333333333334,
          "count": 6
        },
        "long_context": {
          "context_tokens": 174.77777777777777,
          "count": 9
        },
        "multi_entity": {
          "context_tokens": 156.33333333333334,
          "count": 3
        },
        "multi_hop": {
          "context_tokens": 164.33333333333334,
          "count": 3
        },
        "semantic": {
          "context_tokens": 159.6,
          "count": 10
        },
        "temporal": {
          "context_tokens": 153.5,
          "count": 2
        },
        "update": {
          "context_tokens": 130.0,
          "count": 1
        }
      },
      "context_tokens": {
        "count": 60,
        "max": 181.0,
        "mean": 159.05,
        "median": 161.0,
        "min": 121.0,
        "p90": 176.0,
        "p95": 178.0,
        "p99": 180.41,
        "std": 15.083299778343923
      },
      "errors": 0,
      "latency_ms": {
        "count": 0,
        "max": null,
        "mean": null,
        "median": null,
        "min": null,
        "p90": null,
        "p95": null,
        "p99": null,
        "std": null
      },
      "overall": {
        "context_tokens": 159.05,
        "count": 60
      }
    },
    "treemem_guided": {
      "by_category": {
        "ambiguous": {
          "context_tokens": 133.7,
          "count": 10
        },
        "broad": {
          "context_tokens": 75.83333333333333,
          "count": 6
        },
        "direct": {
          "context_tokens": 144.2,
          "count": 10
        },
        "hierarchical": {
          "context_tokens": 17.5,
          "count": 6
        },
        "long_context": {
          "context_tokens": 174.66666666666666,
          "count": 9
        },
        "multi_entity": {
          "context_tokens": 156.33333333333334,
          "count": 3
        },
        "multi_hop": {
          "context_tokens": 81.33333333333333,
          "count": 3
        },
        "semantic": {
          "context_tokens": 149.5,
          "count": 10
        },
        "temporal": {
          "context_tokens": 38.0,
          "count": 2
        },
        "update": {
          "context_tokens": 130.0,
          "count": 1
        }
      },
      "context_tokens": {
        "count": 60,
        "max": 183.0,
        "mean": 122.08333333333333,
        "median": 159.0,
        "min": 0.0,
        "p90": 174.1,
        "p95": 176.1,
        "p99": 180.64,
        "std": 64.39583407587547
      },
      "errors": 0,
      "latency_ms": {
        "count": 0,
        "max": null,
        "mean": null,
        "median": null,
        "min": null,
        "p90": null,
        "p95": null,
        "p99": null,
        "std": null
      },
      "overall": {
        "context_tokens": 122.08333333333333,
        "count": 60
      }
    },
    "treemem_search": {
      "by_category": {
        "ambiguous": {
          "context_tokens": 151.6,
          "count": 10
        },
        "broad": {
          "context_tokens": 75.83333333333333,
          "count": 6
        },
        "direct": {
          "context_tokens": 157.4,
          "count": 10
        },
        "hierarchical": {
          "context_tokens": 159.83333333333334,
          "count": 6
        },
        "long_context": {
          "context_tokens": 174.66666666666666,
          "count": 9
        },
        "multi_entity": {
          "context_tokens": 156.33333333333334,
          "count": 3
        },
        "multi_hop": {
          "context_tokens": 164.33333333333334,
          "count": 3
        },
        "semantic": {
          "context_tokens": 161.7,
          "count": 10
        },
        "temporal": {
          "context_tokens": 154.0,
          "count": 2
        },
        "update": {
          "context_tokens": 130.0,
          "count": 1
        }
      },
      "context_tokens": {
        "count": 60,
        "max": 183.0,
        "mean": 151.55,
        "median": 161.5,
        "min": 0.0,
        "p90": 176.0,
        "p95": 178.0,
        "p99": 180.64,
        "std": 36.354387980321285
      },
      "errors": 0,
      "latency_ms": {
        "count": 0,
        "max": null,
        "mean": null,
        "median": null,
        "min": null,
        "p90": null,
        "p95": null,
        "p99": null,
        "std": null
      },
      "overall": {
        "context_tokens": 151.55,
        "count": 60
      }
    }
  },
  "count": 180
}
```
# Benchmark Tables

## Table A — Retrieval Quality
| System | P@5 | R@5 | F1@5 | MRR | MAP | NDCG@10 |
|---|---:|---:|---:|---:|---:|---:|
| bm25 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| treemem_guided | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| treemem_search | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |

## Table B — Context Efficiency
| System | Mean Tokens | Median Tokens | P95 Tokens | Max Tokens |
|---|---:|---:|---:|---:|
| bm25 | 159.1 | 161.0 | 178.0 | 181.0 |
| treemem_guided | 122.1 | 159.0 | 176.1 | 183.0 |
| treemem_search | 151.6 | 161.5 | 178.0 | 183.0 |

## Table D — Latency
| System | Retrieval P50 | Retrieval P95 | Mean | P99 |
|---|---:|---:|---:|---:|
| bm25 | 0.00 | 0.00 | 0.00 | 0.00 |
| treemem_guided | 0.00 | 0.00 | 0.00 | 0.00 |
| treemem_search | 0.00 | 0.00 | 0.00 | 0.00 |

Manifest: `e2e/manifest.json`

## lifecycle
```json
{
  "count": 3,
  "rows": [
    {
      "detail": {
        "dirtied": [
          "personal/preferences/group_0/leaf_0/item_1",
          "",
          "personal",
          "personal/preferences",
          "personal/preferences/group_0",
          "personal/preferences/group_0/leaf_0"
        ],
        "entry_id": "2026-11-10#2",
        "path": "personal/preferences/group_0/leaf_0/item_1",
        "status": "placed",
        "tokens": 7
      },
      "recovered": true,
      "scenario": "duplicate_insert"
    },
    {
      "fact_count": 3,
      "recovered": true,
      "scenario": "rebuild_preserves_facts"
    },
    {
      "hits": [
        "Alice prefers tea for morning meetings.",
        "Alice prefers coffee for morning meetings."
      ],
      "recovered": true,
      "scenario": "update_retrieval",
      "stale_present": true
    }
  ]
}
```
# Benchmark Tables

Manifest: `lifecycle/manifest.json`

## privacy
```json
{
  "count": 7,
  "rows": [
    {
      "arm": "treemem_search",
      "authorized_success": false,
      "category": "private",
      "context_tokens": 232,
      "experiment": "privacy",
      "false_denial": false,
      "leak": false,
      "metadata": {
        "leaked_values": []
      },
      "passed": true,
      "query_id": "q_100_000171"
    },
    {
      "arm": "treemem_guided",
      "authorized_success": false,
      "category": "private",
      "context_tokens": 99,
      "experiment": "privacy",
      "false_denial": false,
      "leak": false,
      "metadata": {
        "leaked_values": []
      },
      "passed": true,
      "query_id": "q_100_000171"
    },
    {
      "arm": "treemem_search",
      "authorized_success": false,
      "category": "private",
      "context_tokens": 294,
      "experiment": "privacy",
      "false_denial": false,
      "leak": false,
      "metadata": {
        "leaked_values": []
      },
      "passed": true,
      "query_id": "q_100_000172"
    },
    {
      "arm": "treemem_guided",
      "authorized_success": false,
      "category": "private",
      "context_tokens": 137,
      "experiment": "privacy",
      "false_denial": false,
      "leak": false,
      "metadata": {
        "leaked_values": []
      },
      "passed": true,
      "query_id": "q_100_000172"
    },
    {
      "arm": "treemem_search",
      "authorized_success": false,
      "category": "private",
      "context_tokens": 304,
      "experiment": "privacy",
      "false_denial": false,
      "leak": false,
      "metadata": {
        "leaked_values": []
      },
      "passed": true,
      "query_id": "q_100_000173"
    },
    {
      "arm": "treemem_guided",
      "authorized_success": false,
      "category": "private",
      "context_tokens": 149,
      "experiment": "privacy",
      "false_denial": false,
      "leak": false,
      "metadata": {
        "leaked_values": []
      },
      "passed": true,
      "query_id": "q_100_000173"
    },
    {
      "arm": "treemem_search_reveal",
      "authorized_success": true,
      "category": "private",
      "context_tokens": 303,
      "experiment": "privacy",
      "false_denial": false,
      "leak": false,
      "passed": true,
      "query_id": "q_100_000171"
    }
  ]
}
```
# Benchmark Tables

Manifest: `privacy/manifest.json`

## reliability
```json
{
  "count": 3,
  "rows": [
    {
      "corruption": false,
      "data_loss": false,
      "duplicate_reconstruction": false,
      "recovered": true,
      "recovery_ms": 0.0,
      "scenario": "crash_recovery_0",
      "stray_tmp_detected": true
    },
    {
      "corruption": false,
      "data_loss": false,
      "duplicate_reconstruction": false,
      "recovered": true,
      "recovery_ms": 0.0,
      "scenario": "crash_recovery_1",
      "stray_tmp_detected": true
    },
    {
      "corruption": false,
      "data_loss": false,
      "duplicate_reconstruction": false,
      "recovered": true,
      "recovery_ms": 0.0,
      "scenario": "crash_recovery_2",
      "stray_tmp_detected": true
    }
  ]
}
```
# Benchmark Tables

Manifest: `reliability/manifest.json`

## retrieval
```json
{
  "arms": {
    "bm25": {
      "by_category": {
        "ambiguous": {
          "context_tokens": 336.42857142857144,
          "count": 7,
          "f1@1": 0.8571428571428571,
          "f1@10": 0.18181818181818182,
          "f1@3": 0.5,
          "f1@5": 0.33333333333333337,
          "full_support": 1.0,
          "latency_ms": 0.09397628517555338,
          "map": 0.9285714285714286,
          "mrr": 0.9285714285714286,
          "ndcg@1": 0.8571428571428571,
          "ndcg@10": 0.9472756790816368,
          "ndcg@3": 0.9472756790816368,
          "ndcg@5": 0.9472756790816368,
          "precision@1": 0.8571428571428571,
          "precision@10": 0.1,
          "precision@3": 0.3333333333333333,
          "precision@5": 0.2,
          "recall@1": 0.8571428571428571,
          "recall@10": 1.0,
          "recall@3": 1.0,
          "recall@5": 1.0
        },
        "direct": {
          "context_tokens": 356.0,
          "count": 11,
          "f1@1": 0.6363636363636364,
          "f1@10": 0.18181818181818182,
          "f1@3": 0.36363636363636365,
          "f1@5": 0.27272727272727276,
          "full_support": 1.0,
          "latency_ms": 0.1209620968438685,
          "map": 0.7303030303030303,
          "mrr": 0.7303030303030303,
          "ndcg@1": 0.6363636363636364,
          "ndcg@10": 0.7936542668201857,
          "ndcg@3": 0.6937208866883143,
          "ndcg@5": 0.7288893237096363,
          "precision@1": 0.6363636363636364,
          "precision@10": 0.1,
          "precision@3": 0.2424242424242424,
          "precision@5": 0.16363636363636364,
          "recall@1": 0.6363636363636364,
          "recall@10": 1.0,
          "recall@3": 0.7272727272727273,
          "recall@5": 0.8181818181818182
        },
        "long_context": {
          "context_tokens": 366.6363636363636,
          "count": 11,
          "f1@1": 0.7272727272727273,
          "f1@10": 0.18181818181818182,
          "f1@3": 0.36363636363636365,
          "f1@5": 0.24242424242424246,
          "full_support": 1.0,
          "latency_ms": 0.10635991665450009,
          "map": 0.7683982683982684,
          "mrr": 0.7683982683982684,
          "ndcg@1": 0.7272727272727273,
          "ndcg@10": 0.8202612594340626,
          "ndcg@3": 0.7272727272727273,
          "ndcg@5": 0.7272727272727273,
          "precision@1": 0.7272727272727273,
          "precision@10": 0.1,
          "precision@3": 0.2424242424242424,
          "precision@5": 0.14545454545454548,
          "recall@1": 0.7272727272727273,
          "recall@10": 1.0,
          "recall@3": 0.7272727272727273,
          "recall@5": 0.7272727272727273
        },
        "semantic": {
          "context_tokens": 337.27272727272725,
          "count": 11,
          "f1@1": 0.6363636363636364,
          "f1@10": 0.1487603305785124,
          "f1@3": 0.36363636363636365,
          "f1@5": 0.27272727272727276,
          "full_support": 0.8181818181818182,
          "latency_ms": 0.15242818467827005,
          "map": 0.7000000000000001,
          "mrr": 0.7000000000000001,
          "ndcg@1": 0.6363636363636364,
          "ndcg@10": 0.7288893237096363,
          "ndcg@3": 0.6937208866883143,
          "ndcg@5": 0.7288893237096363,
          "precision@1": 0.6363636363636364,
          "precision@10": 0.08181818181818182,
          "precision@3": 0.2424242424242424,
          "precision@5": 0.16363636363636364,
          "recall@1": 0.6363636363636364,
          "recall@10": 0.8181818181818182,
          "recall@3": 0.7272727272727273,
          "recall@5": 0.8181818181818182
        }
      },
      "context_tokens": {
        "count": 40,
        "max": 405.0,
        "mean": 350.35,
        "median": 351.0,
        "min": 305.0,
        "p90": 376.4,
        "p95": 389.25,
        "p99": 400.71000000000004,
        "std": 22.752345610271277
      },
      "errors": 0,
      "latency_ms": {
        "count": 40,
        "max": 0.33725000685080886,
        "mean": 0.12087715440429747,
        "median": 0.10350049706175923,
        "min": 0.07995800115168095,
        "p90": 0.14095421065576383,
        "p95": 0.259264645865187,
        "p99": 0.3106488758930936,
        "std": 0.05332796593143734
      },
      "overall": {
        "context_tokens": 350.35,
        "count": 40,
        "f1@1": 0.7,
        "f1@10": 0.17272727272727273,
        "f1@3": 0.3875,
        "f1@5": 0.275,
        "full_support": 0.95,
        "latency_ms": 0.12087715440429747,
        "map": 0.7671428571428571,
        "mrr": 0.7671428571428571,
        "ndcg@1": 0.7,
        "ndcg@10": 0.8100445775793548,
        "ndcg@3": 0.7473197315178594,
        "ndcg@5": 0.7666623718795864,
        "precision@1": 0.7,
        "precision@10": 0.095,
        "precision@3": 0.2583333333333333,
        "precision@5": 0.165,
        "recall@1": 0.7,
        "recall@10": 0.95,
        "recall@3": 0.775,
        "recall@5": 0.825
      }
    },
    "treemem_guided": {
      "by_category": {
        "ambiguous": {
          "context_tokens": 0.0,
          "count": 7,
          "f1@1": 0.0,
          "f1@10": 0.0,
          "f1@3": 0.0,
          "f1@5": 0.0,
          "full_support": 0.0,
          "latency_ms": 7.261732135832842,
          "map": 0.0,
          "mrr": 0.0,
          "ndcg@1": 0.0,
          "ndcg@10": 0.0,
          "ndcg@3": 0.0,
          "ndcg@5": 0.0,
          "precision@1": 0.0,
          "precision@10": 0.0,
          "precision@3": 0.0,
          "precision@5": 0.0,
          "recall@1": 0.0,
          "recall@10": 0.0,
          "recall@3": 0.0,
          "recall@5": 0.0
        },
        "direct": {
          "context_tokens": 0.0,
          "count": 11,
          "f1@1": 0.0,
          "f1@10": 0.0,
          "f1@3": 0.0,
          "f1@5": 0.0,
          "full_support": 0.0,
          "latency_ms": 7.741333371747962,
          "map": 0.0,
          "mrr": 0.0,
          "ndcg@1": 0.0,
          "ndcg@10": 0.0,
          "ndcg@3": 0.0,
          "ndcg@5": 0.0,
          "precision@1": 0.0,
          "precision@10": 0.0,
          "precision@3": 0.0,
          "precision@5": 0.0,
          "recall@1": 0.0,
          "recall@10": 0.0,
          "recall@3": 0.0,
          "recall@5": 0.0
        },
        "long_context": {
          "context_tokens": 0.0,
          "count": 11,
          "f1@1": 0.0,
          "f1@10": 0.0,
          "f1@3": 0.0,
          "f1@5": 0.0,
          "full_support": 0.0,
          "latency_ms": 8.042530278378928,
          "map": 0.0,
          "mrr": 0.0,
          "ndcg@1": 0.0,
          "ndcg@10": 0.0,
          "ndcg@3": 0.0,
          "ndcg@5": 0.0,
          "precision@1": 0.0,
          "precision@10": 0.0,
          "precision@3": 0.0,
          "precision@5": 0.0,
          "recall@1": 0.0,
          "recall@10": 0.0,
          "recall@3": 0.0,
          "recall@5": 0.0
        },
        "semantic": {
          "context_tokens": 0.0,
          "count": 11,
          "f1@1": 0.0,
          "f1@10": 0.0,
          "f1@3": 0.0,
          "f1@5": 0.0,
          "full_support": 0.0,
          "latency_ms": 7.767170286652717,
          "map": 0.0,
          "mrr": 0.0,
          "ndcg@1": 0.0,
          "ndcg@10": 0.0,
          "ndcg@3": 0.0,
          "ndcg@5": 0.0,
          "precision@1": 0.0,
          "precision@10": 0.0,
          "precision@3": 0.0,
          "precision@5": 0.0,
          "recall@1": 0.0,
          "recall@10": 0.0,
          "recall@3": 0.0,
          "recall@5": 0.0
        }
      },
      "context_tokens": {
        "count": 40,
        "max": 0.0,
        "mean": 0.0,
        "median": 0.0,
        "min": 0.0,
        "p90": 0.0,
        "p95": 0.0,
        "p99": 0.0,
        "std": 0.0
      },
      "errors": 0,
      "latency_ms": {
        "count": 40,
        "max": 11.217333027161658,
        "mean": 7.747337456385139,
        "median": 7.287937478395179,
        "min": 6.415374984499067,
        "p90": 10.299291601404548,
        "p95": 11.02590770169627,
    
```
# Benchmark Tables

## Table A — Retrieval Quality
| System | P@5 | R@5 | F1@5 | MRR | MAP | NDCG@10 |
|---|---:|---:|---:|---:|---:|---:|
| bm25 | 0.165 | 0.825 | 0.275 | 0.767 | 0.767 | 0.810 |
| treemem_guided | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| treemem_manual | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| treemem_search | 0.150 | 0.750 | 0.250 | 0.706 | 0.706 | 0.739 |

## Table B — Context Efficiency
| System | Mean Tokens | Median Tokens | P95 Tokens | Max Tokens |
|---|---:|---:|---:|---:|
| bm25 | 350.4 | 351.0 | 389.2 | 405.0 |
| treemem_guided | 0.0 | 0.0 | 0.0 | 0.0 |
| treemem_manual | 0.0 | 0.0 | 0.0 | 0.0 |
| treemem_search | 338.1 | 339.5 | 381.1 | 405.0 |

## Table D — Latency
| System | Retrieval P50 | Retrieval P95 | Mean | P99 |
|---|---:|---:|---:|---:|
| bm25 | 0.10 | 0.26 | 0.12 | 0.31 |
| treemem_guided | 7.29 | 11.03 | 7.75 | 11.17 |
| treemem_manual | 5.71 | 9.66 | 6.40 | 10.09 |
| treemem_search | 7.27 | 8.20 | 7.30 | 8.56 |

Manifest: `retrieval/manifest.json`

## retrieval_manual_v3
```json
{
  "arms": {
    "treemem_manual": {
      "by_category": {
        "ambiguous": {
          "context_tokens": 7.6,
          "count": 10,
          "f1@1": 0.0,
          "f1@10": 0.0,
          "f1@3": 0.0,
          "f1@5": 0.0,
          "full_support": 0.0,
          "latency_ms": 9.823521197540686,
          "map": 0.0,
          "mrr": 0.0,
          "ndcg@1": 0.0,
          "ndcg@10": 0.0,
          "ndcg@3": 0.0,
          "ndcg@5": 0.0,
          "precision@1": 0.0,
          "precision@10": 0.0,
          "precision@3": 0.0,
          "precision@5": 0.0,
          "recall@1": 0.0,
          "recall@10": 0.0,
          "recall@3": 0.0,
          "recall@5": 0.0
        },
        "direct": {
          "context_tokens": 3.1,
          "count": 10,
          "f1@1": 0.0,
          "f1@10": 0.0,
          "f1@3": 0.0,
          "f1@5": 0.0,
          "full_support": 0.0,
          "latency_ms": 10.631058301078156,
          "map": 0.0,
          "mrr": 0.0,
          "ndcg@1": 0.0,
          "ndcg@10": 0.0,
          "ndcg@3": 0.0,
          "ndcg@5": 0.0,
          "precision@1": 0.0,
          "precision@10": 0.0,
          "precision@3": 0.0,
          "precision@5": 0.0,
          "recall@1": 0.0,
          "recall@10": 0.0,
          "recall@3": 0.0,
          "recall@5": 0.0
        },
        "long_context": {
          "context_tokens": 0.0,
          "count": 9,
          "f1@1": 0.0,
          "f1@10": 0.0,
          "f1@3": 0.0,
          "f1@5": 0.0,
          "full_support": 0.0,
          "latency_ms": 9.636374791928878,
          "map": 0.0,
          "mrr": 0.0,
          "ndcg@1": 0.0,
          "ndcg@10": 0.0,
          "ndcg@3": 0.0,
          "ndcg@5": 0.0,
          "precision@1": 0.0,
          "precision@10": 0.0,
          "precision@3": 0.0,
          "precision@5": 0.0,
          "recall@1": 0.0,
          "recall@10": 0.0,
          "recall@3": 0.0,
          "recall@5": 0.0
        },
        "multi_hop": {
          "context_tokens": 38.0,
          "count": 1,
          "f1@1": 0.0,
          "f1@10": 0.0,
          "f1@3": 0.0,
          "f1@5": 0.0,
          "full_support": 0.0,
          "latency_ms": 13.071000052150339,
          "map": 0.0,
          "mrr": 0.0,
          "ndcg@1": 0.0,
          "ndcg@10": 0.0,
          "ndcg@3": 0.0,
          "ndcg@5": 0.0,
          "precision@1": 0.0,
          "precision@10": 0.0,
          "precision@3": 0.0,
          "precision@5": 0.0,
          "recall@1": 0.0,
          "recall@10": 0.0,
          "recall@3": 0.0,
          "recall@5": 0.0
        },
        "semantic": {
          "context_tokens": 3.1,
          "count": 10,
          "f1@1": 0.0,
          "f1@10": 0.0,
          "f1@3": 0.0,
          "f1@5": 0.0,
          "full_support": 0.0,
          "latency_ms": 10.189441812690347,
          "map": 0.0,
          "mrr": 0.0,
          "ndcg@1": 0.0,
          "ndcg@10": 0.0,
          "ndcg@3": 0.0,
          "ndcg@5": 0.0,
          "precision@1": 0.0,
          "precision@10": 0.0,
          "precision@3": 0.0,
          "precision@5": 0.0,
          "recall@1": 0.0,
          "recall@10": 0.0,
          "recall@3": 0.0,
          "recall@5": 0.0
        }
      },
      "context_tokens": {
        "count": 40,
        "max": 38.0,
        "mean": 4.4,
        "median": 0.0,
        "min": 0.0,
        "p90": 31.0,
        "p95": 38.0,
        "p99": 38.0,
        "std": 11.853377750774845
      },
      "errors": 0,
      "latency_ms": {
        "count": 40,
        "max": 17.35974900657311,
        "mean": 10.155964657315053,
        "median": 9.37324998085387,
        "min": 7.644418044947088,
        "p90": 13.018161949003115,
        "p95": 13.582229131134227,
        "p99": 15.916928412043486,
        "std": 2.032739545030896
      },
      "overall": {
        "context_tokens": 4.4,
        "count": 40,
        "f1@1": 0.0,
        "f1@10": 0.0,
        "f1@3": 0.0,
        "f1@5": 0.0,
        "full_support": 0.0,
        "latency_ms": 10.155964657315053,
        "map": 0.0,
        "mrr": 0.0,
        "ndcg@1": 0.0,
        "ndcg@10": 0.0,
        "ndcg@3": 0.0,
        "ndcg@5": 0.0,
        "precision@1": 0.0,
        "precision@10": 0.0,
        "precision@3": 0.0,
        "precision@5": 0.0,
        "recall@1": 0.0,
        "recall@10": 0.0,
        "recall@3": 0.0,
        "recall@5": 0.0
      }
    }
  },
  "count": 40
}
```
# Benchmark Tables

## Table A — Retrieval Quality
| System | P@5 | R@5 | F1@5 | MRR | MAP | NDCG@10 |
|---|---:|---:|---:|---:|---:|---:|
| treemem_manual | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |

## Table B — Context Efficiency
| System | Mean Tokens | Median Tokens | P95 Tokens | Max Tokens |
|---|---:|---:|---:|---:|
| treemem_manual | 4.4 | 0.0 | 38.0 | 38.0 |

## Table D — Latency
| System | Retrieval P50 | Retrieval P95 | Mean | P99 |
|---|---:|---:|---:|---:|
| treemem_manual | 9.37 | 13.58 | 10.16 | 15.92 |

Manifest: `retrieval_manual_v3/manifest.json`

## retrieval_manual_v4
```json
{
  "arms": {
    "treemem_manual": {
      "by_category": {
        "ambiguous": {
          "context_tokens": 18.7,
          "count": 10,
          "f1@1": 0.0,
          "f1@10": 0.0,
          "f1@3": 0.0,
          "f1@5": 0.0,
          "full_support": 0.0,
          "latency_ms": 9.187404392287135,
          "map": 0.0,
          "mrr": 0.0,
          "ndcg@1": 0.0,
          "ndcg@10": 0.0,
          "ndcg@3": 0.0,
          "ndcg@5": 0.0,
          "precision@1": 0.0,
          "precision@10": 0.0,
          "precision@3": 0.0,
          "precision@5": 0.0,
          "recall@1": 0.0,
          "recall@10": 0.0,
          "recall@3": 0.0,
          "recall@5": 0.0
        },
        "direct": {
          "context_tokens": 9.1,
          "count": 10,
          "f1@1": 0.0,
          "f1@10": 0.0,
          "f1@3": 0.0,
          "f1@5": 0.0,
          "full_support": 0.0,
          "latency_ms": 8.86207478470169,
          "map": 0.0,
          "mrr": 0.0,
          "ndcg@1": 0.0,
          "ndcg@10": 0.0,
          "ndcg@3": 0.0,
          "ndcg@5": 0.0,
          "precision@1": 0.0,
          "precision@10": 0.0,
          "precision@3": 0.0,
          "precision@5": 0.0,
          "recall@1": 0.0,
          "recall@10": 0.0,
          "recall@3": 0.0,
          "recall@5": 0.0
        },
        "long_context": {
          "context_tokens": 10.11111111111111,
          "count": 9,
          "f1@1": 0.0,
          "f1@10": 0.0,
          "f1@3": 0.0,
          "f1@5": 0.0,
          "full_support": 0.0,
          "latency_ms": 9.49242152273655,
          "map": 0.0,
          "mrr": 0.0,
          "ndcg@1": 0.0,
          "ndcg@10": 0.0,
          "ndcg@3": 0.0,
          "ndcg@5": 0.0,
          "precision@1": 0.0,
          "precision@10": 0.0,
          "precision@3": 0.0,
          "precision@5": 0.0,
          "recall@1": 0.0,
          "recall@10": 0.0,
          "recall@3": 0.0,
          "recall@5": 0.0
        },
        "multi_hop": {
          "context_tokens": 38.0,
          "count": 1,
          "f1@1": 0.0,
          "f1@10": 0.0,
          "f1@3": 0.0,
          "f1@5": 0.0,
          "full_support": 0.0,
          "latency_ms": 12.966458045411855,
          "map": 0.0,
          "mrr": 0.0,
          "ndcg@1": 0.0,
          "ndcg@10": 0.0,
          "ndcg@3": 0.0,
          "ndcg@5": 0.0,
          "precision@1": 0.0,
          "precision@10": 0.0,
          "precision@3": 0.0,
          "precision@5": 0.0,
          "recall@1": 0.0,
          "recall@10": 0.0,
          "recall@3": 0.0,
          "recall@5": 0.0
        },
        "semantic": {
          "context_tokens": 9.1,
          "count": 10,
          "f1@1": 0.0,
          "f1@10": 0.0,
          "f1@3": 0.0,
          "f1@5": 0.0,
          "full_support": 0.0,
          "latency_ms": 8.719904377358034,
          "map": 0.0,
          "mrr": 0.0,
          "ndcg@1": 0.0,
          "ndcg@10": 0.0,
          "ndcg@3": 0.0,
          "ndcg@5": 0.0,
          "precision@1": 0.0,
          "precision@10": 0.0,
          "precision@3": 0.0,
          "precision@5": 0.0,
          "recall@1": 0.0,
          "recall@10": 0.0,
          "recall@3": 0.0,
          "recall@5": 0.0
        }
      },
      "context_tokens": {
        "count": 40,
        "max": 84.0,
        "mean": 12.45,
        "median": 0.0,
        "min": 0.0,
        "p90": 38.0,
        "p95": 38.0,
        "p99": 66.05999999999997,
        "std": 19.25796538498371
      },
      "errors": 0,
      "latency_ms": {
        "count": 40,
        "max": 16.77049999125302,
        "mean": 9.152302182337735,
        "median": 7.977458502864465,
        "min": 4.88291698275134,
        "p90": 15.534532809397207,
        "p95": 16.28186072630342,
        "p99": 16.623047609464265,
        "std": 4.296968538935856
      },
      "overall": {
        "context_tokens": 12.45,
        "count": 40,
        "f1@1": 0.0,
        "f1@10": 0.0,
        "f1@3": 0.0,
        "f1@5": 0.0,
        "full_support": 0.0,
        "latency_ms": 9.152302182337735,
        "map": 0.0,
        "mrr": 0.0,
        "ndcg@1": 0.0,
        "ndcg@10": 0.0,
        "ndcg@3": 0.0,
        "ndcg@5": 0.0,
        "precision@1": 0.0,
        "precision@10": 0.0,
        "precision@3": 0.0,
        "precision@5": 0.0,
        "recall@1": 0.0,
        "recall@10": 0.0,
        "recall@3": 0.0,
        "recall@5": 0.0
      }
    }
  },
  "count": 40
}
```
# Benchmark Tables

## Table A — Retrieval Quality
| System | P@5 | R@5 | F1@5 | MRR | MAP | NDCG@10 |
|---|---:|---:|---:|---:|---:|---:|
| treemem_manual | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |

## Table B — Context Efficiency
| System | Mean Tokens | Median Tokens | P95 Tokens | Max Tokens |
|---|---:|---:|---:|---:|
| treemem_manual | 12.4 | 0.0 | 38.0 | 84.0 |

## Table D — Latency
| System | Retrieval P50 | Retrieval P95 | Mean | P99 |
|---|---:|---:|---:|---:|
| treemem_manual | 7.98 | 16.28 | 9.15 | 16.62 |

Manifest: `retrieval_manual_v4/manifest.json`

## retrieval_v2
```json
{
  "arms": {
    "bm25": {
      "by_category": {
        "ambiguous": {
          "context_tokens": 306.9,
          "count": 10,
          "f1@1": 0.8,
          "f1@10": 0.18181818181818182,
          "f1@3": 0.5,
          "f1@5": 0.33333333333333337,
          "full_support": 1.0,
          "latency_ms": 0.0929499976336956,
          "map": 0.8833333333333334,
          "mrr": 0.8833333333333334,
          "ndcg@1": 0.8,
          "ndcg@10": 0.9130929753571457,
          "ndcg@3": 0.9130929753571457,
          "ndcg@5": 0.9130929753571457,
          "precision@1": 0.8,
          "precision@10": 0.1,
          "precision@3": 0.3333333333333333,
          "precision@5": 0.2,
          "recall@1": 0.8,
          "recall@10": 1.0,
          "recall@3": 1.0,
          "recall@5": 1.0
        },
        "direct": {
          "context_tokens": 332.5,
          "count": 10,
          "f1@1": 0.6,
          "f1@10": 0.16363636363636364,
          "f1@3": 0.35,
          "f1@5": 0.2666666666666667,
          "full_support": 0.9,
          "latency_ms": 0.10458760079927742,
          "map": 0.6866666666666666,
          "mrr": 0.6866666666666666,
          "ndcg@1": 0.6,
          "ndcg@10": 0.7373989747914022,
          "ndcg@3": 0.6630929753571457,
          "ndcg@5": 0.7017782560806,
          "precision@1": 0.6,
          "precision@10": 0.09,
          "precision@3": 0.2333333333333333,
          "precision@5": 0.16,
          "recall@1": 0.6,
          "recall@10": 0.9,
          "recall@3": 0.7,
          "recall@5": 0.8
        },
        "long_context": {
          "context_tokens": 342.1111111111111,
          "count": 9,
          "f1@1": 0.6666666666666666,
          "f1@10": 0.16161616161616163,
          "f1@3": 0.3333333333333333,
          "f1@5": 0.2222222222222222,
          "full_support": 0.8888888888888888,
          "latency_ms": 0.10751400582699312,
          "map": 0.701058201058201,
          "mrr": 0.701058201058201,
          "ndcg@1": 0.6666666666666666,
          "ndcg@10": 0.7432822800490395,
          "ndcg@3": 0.6666666666666666,
          "ndcg@5": 0.6666666666666666,
          "precision@1": 0.6666666666666666,
          "precision@10": 0.08888888888888889,
          "precision@3": 0.2222222222222222,
          "precision@5": 0.13333333333333336,
          "recall@1": 0.6666666666666666,
          "recall@10": 0.8888888888888888,
          "recall@3": 0.6666666666666666,
          "recall@5": 0.6666666666666666
        },
        "multi_hop": {
          "context_tokens": 293.0,
          "count": 1,
          "f1@1": 0.6666666666666666,
          "f1@10": 0.3050847457627119,
          "f1@3": 0.7499999999999999,
          "f1@5": 0.5294117647058824,
          "full_support": 1.0,
          "latency_ms": 0.14141702558845282,
          "map": 1.0,
          "mrr": 1.0,
          "ndcg@1": 1.0,
          "ndcg@10": 1.0,
          "ndcg@3": 1.0,
          "ndcg@5": 1.0,
          "precision@1": 1.0,
          "precision@10": 0.18,
          "precision@3": 0.6,
          "precision@5": 0.36,
          "recall@1": 0.5,
          "recall@10": 1.0,
          "recall@3": 1.0,
          "recall@5": 1.0
        },
        "semantic": {
          "context_tokens": 315.6,
          "count": 10,
          "f1@1": 0.6,
          "f1@10": 0.12727272727272726,
          "f1@3": 0.35,
          "f1@5": 0.23333333333333334,
          "full_support": 0.7,
          "latency_ms": 0.14414169709198177,
          "map": 0.65,
          "mrr": 0.65,
          "ndcg@1": 0.6,
          "ndcg@10": 0.6630929753571457,
          "ndcg@3": 0.6630929753571457,
          "ndcg@5": 0.6630929753571457,
          "precision@1": 0.6,
          "precision@10": 0.07,
          "precision@3": 0.2333333333333333,
          "precision@5": 0.14,
          "recall@1": 0.6,
          "recall@10": 0.7,
          "recall@3": 0.7,
          "recall@5": 0.7
        }
      },
      "context_tokens": {
        "count": 40,
        "max": 364.0,
        "mean": 323.05,
        "median": 324.5,
        "min": 278.0,
        "p90": 344.0,
        "p95": 351.5,
        "p99": 362.83,
        "std": 19.983262226943058
      },
      "errors": 0,
      "latency_ms": {
        "count": 40,
        "max": 0.23674999829381704,
        "mean": 0.11314590083202347,
        "median": 0.10133348405361176,
        "min": 0.08187501225620508,
        "p90": 0.13729229103773832,
        "p95": 0.16331662482116355,
        "p99": 0.22620361880399287,
        "std": 0.03182520122777599
      },
      "overall": {
        "context_tokens": 323.05,
        "count": 40,
        "f1@1": 0.6666666666666667,
        "f1@10": 0.16217257318952233,
        "f1@3": 0.39375,
        "f1@5": 0.2715686274509804,
        "full_support": 0.875,
        "latency_ms": 0.11314590083202347,
        "map": 0.7377380952380952,
        "mrr": 0.7377380952380952,
        "ndcg@1": 0.675,
        "ndcg@10": 0.7706347443874573,
        "ndcg@3": 0.7348197315178593,
        "ndcg@5": 0.7444910516987229,
        "precision@1": 0.675,
        "precision@10": 0.0895,
        "precision@3": 0.265,
        "precision@5": 0.164,
        "recall@1": 0.6625,
        "recall@10": 0.875,
        "recall@3": 0.775,
        "recall@5": 0.8
      }
    },
    "treemem_guided": {
      "by_category": {
        "ambiguous": {
          "context_tokens": 133.7,
          "count": 10,
          "f1@1": 0.8,
          "f1@10": 0.14545454545454545,
          "f1@3": 0.4,
          "f1@5": 0.2666666666666667,
          "full_support": 0.8,
          "latency_ms": 9.959012392209843,
          "map": 0.8,
          "mrr": 0.8,
          "ndcg@1": 0.8,
          "ndcg@10": 0.8,
          "ndcg@3": 0.8,
          "ndcg@5": 0.8,
          "precision@1": 0.8,
          "precision@10": 0.08,
          "precision@3": 0.26666666666666666,
          "precision@5": 0.16,
          "recall@1": 0.8,
          "recall@10": 0.8,
          "recall@3": 0.8,
          "recall@5": 0.8
        },
        "direct": {
          "context_tokens": 144.2,
          "count": 10,
          "f1@1": 0.6,
          "f1@10": 0.10909090909090909,
          "f1@3": 0.3,
          "f1@5": 0.2,
          "full_support": 0.6,
          "latency_ms": 9.79617081466131,
          "map": 0.6,
          "mrr": 0.6,
          "ndcg@1": 0.6,
          "ndcg@10": 0.6,
          "ndcg@3": 0.6,
          "ndcg@5": 0.6,
          "precision@1": 0.6,
          "precision@10": 0.06000000000000001,
          "precision@3": 0.2,
          "precision@5": 0.12000000000000002,
          "recall@1": 0.6,
          "recall@10": 0.6,
          "recall@3": 0.6,
          "recall@5": 0.6
        },
        "long_context": {
          "context_tokens": 174.66666666666666,
          "count": 9,
          "f1@1": 0.5555555555555556,
          "f1@10": 0.1212121212121212,
          "f1@3": 0.3333333333333333,
          "f1@5": 0.2222222222222222,
          "full_support": 0.6666666666666666,
          "latency_ms": 8.730199116851306,
          "map": 0.6111111111111112,
          "mrr": 0.6111111111111112,
          "ndcg@1": 0.5555555555555556,
          "ndcg@10": 0.6256588615079397,
          "ndcg@3": 0.6256588615079397,
          "ndcg@5": 0.6256588615079397,
          "precision@1": 0.5555555555555556,
          "precision@10": 0.06666666666666668,
          "precision@3": 0.2222222222222222,
          "precision@5": 0.13333333333333336,
          "recall@1": 0.5555555555555556,
          "recall@10": 0.6666666666666666,
          "recall@3": 0.6666666666666666,
          "recall@5": 0.6666666666666666
        },
        "multi_hop": {
          "context_tokens": 38.0,
          "count": 1,
          "f1@1": 0.0,
          "f1@10": 0.0,
          "f1@3": 0.0,
          "f1@5": 0.0,
          "full_support": 0.0,
          "latency_ms": 13.838957995176315,
          "map": 0.0,
          "mrr": 0.0,
          "ndcg@1": 0.0,
          "ndcg@10": 0.0,
          "ndcg@3": 0.0,
          "nd
```
# Benchmark Tables

## Table A — Retrieval Quality
| System | P@5 | R@5 | F1@5 | MRR | MAP | NDCG@10 |
|---|---:|---:|---:|---:|---:|---:|
| bm25 | 0.164 | 0.800 | 0.272 | 0.738 | 0.738 | 0.771 |
| treemem_guided | 0.130 | 0.650 | 0.217 | 0.637 | 0.637 | 0.641 |
| treemem_manual | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| treemem_search | 0.154 | 0.750 | 0.255 | 0.702 | 0.702 | 0.725 |

## Table B — Context Efficiency
| System | Mean Tokens | Median Tokens | P95 Tokens | Max Tokens |
|---|---:|---:|---:|---:|
| bm25 | 323.1 | 324.5 | 351.5 | 364.0 |
| treemem_guided | 147.1 | 162.5 | 178.1 | 183.0 |
| treemem_manual | 2.9 | 0.0 | 38.0 | 38.0 |
| treemem_search | 314.8 | 315.5 | 355.3 | 364.0 |

## Table D — Latency
| System | Retrieval P50 | Retrieval P95 | Mean | P99 |
|---|---:|---:|---:|---:|
| bm25 | 0.10 | 0.16 | 0.11 | 0.23 |
| treemem_guided | 8.57 | 14.50 | 9.59 | 15.19 |
| treemem_manual | 8.46 | 10.66 | 8.39 | 11.52 |
| treemem_search | 6.27 | 7.19 | 6.38 | 7.80 |

Manifest: `retrieval_v2/manifest.json`

## Reproduction
See `benchmark_suite/README.md` for exact commands. Raw episodes are under `benchmark_suite/results/`.