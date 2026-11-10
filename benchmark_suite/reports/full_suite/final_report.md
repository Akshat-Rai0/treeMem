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
          "context_tokens": 126.15384615384616,
          "count": 39,
          "f1@1": 0.7692307692307693,
          "f1@10": 0.13986013986013987,
          "f1@3": 0.38461538461538464,
          "f1@5": 0.25641025641025644,
          "full_support": 0.7692307692307693,
          "latency_ms": 16.33242519948488,
          "map": 0.7692307692307693,
          "mrr": 0.7692307692307693,
          "ndcg@1": 0.7692307692307693,
          "ndcg@10": 0.7692307692307693,
          "ndcg@3": 0.7692307692307693,
          "ndcg@5": 0.7692307692307693,
          "precision@1": 0.7692307692307693,
          "precision@10": 0.07692307692307693,
          "precision@3": 0.2564102564102564,
          "precision@5": 0.15384615384615385,
          "recall@1": 0.7692307692307693,
          "recall@10": 0.7692307692307693,
          "recall@3": 0.7692307692307693,
          "recall@5": 0.7692307692307693
        },
        "direct": {
          "context_tokens": 125.24867724867725,
          "count": 189,
          "f1@1": 0.708994708994709,
          "f1@10": 0.1317941317941318,
          "f1@3": 0.36243386243386244,
          "f1@5": 0.2416225749559083,
          "full_support": 0.7248677248677249,
          "latency_ms": 14.883777563073352,
          "map": 0.716931216931217,
          "mrr": 0.716931216931217,
          "ndcg@1": 0.708994708994709,
          "ndcg@10": 0.7190094669879068,
          "ndcg@3": 0.7190094669879068,
          "ndcg@5": 0.7190094669879068,
          "precision@1": 0.708994708994709,
          "precision@10": 0.07248677248677249,
          "precision@3": 0.24162257495590828,
          "precision@5": 0.14497354497354498,
          "recall@1": 0.708994708994709,
          "recall@10": 0.7248677248677249,
          "recall@3": 0.7248677248677249,
          "recall@5": 0.7248677248677249
        },
        "long_context": {
          "context_tokens": 142.96236559139786,
          "count": 186,
          "f1@1": 0.7365591397849462,
          "f1@10": 0.13391984359726294,
          "f1@3": 0.3682795698924731,
          "f1@5": 0.24551971326164876,
          "full_support": 0.7365591397849462,
          "latency_ms": 15.193148752704504,
          "map": 0.7365591397849462,
          "mrr": 0.7365591397849462,
          "ndcg@1": 0.7365591397849462,
          "ndcg@10": 0.7365591397849462,
          "ndcg@3": 0.7365591397849462,
          "ndcg@5": 0.7365591397849462,
          "precision@1": 0.7365591397849462,
          "precision@10": 0.07365591397849464,
          "precision@3": 0.24551971326164873,
          "precision@5": 0.14731182795698927,
          "recall@1": 0.7365591397849462,
          "recall@10": 0.7365591397849462,
          "recall@3": 0.7365591397849462,
          "recall@5": 0.7365591397849462
        },
        "semantic": {
          "context_tokens": 129.91397849462365,
          "count": 186,
          "f1@1": 0.6881720430107527,
          "f1@10": 0.13391984359726294,
          "f1@3": 0.3682795698924731,
          "f1@5": 0.24551971326164876,
          "full_support": 0.7365591397849462,
          "latency_ms": 15.229251139023672,
          "map": 0.7123655913978495,
          "mrr": 0.7123655913978495,
          "ndcg@1": 0.6881720430107527,
          "ndcg@10": 0.7187009020545329,
          "ndcg@3": 0.7187009020545329,
          "ndcg@5": 0.7187009020545329,
          "precision@1": 0.6881720430107527,
          "precision@10": 0.07365591397849464,
          "precision@3": 0.24551971326164873,
          "precision@5": 0.14731182795698927,
          "recall@1": 0.6881720430107527,
          "recall@10": 0.7365591397849462,
          "recall@3": 0.7365591397849462,
          "recall@5": 0.7365591397849462
        }
      },
      "context_tokens": {
        "count": 600,
        "max": 189.0,
        "mean": 132.245,
        "median": 153.0,
        "min": 0.0,
        "p90": 171.0,
        "p95": 175.04999999999995,
        "p99": 186.0,
        "std": 51.973233527835255
      },
      "errors": 0,
      "latency_ms": {
        "count": 600,
        "max": 62.91933299507946,
        "mean": 15.180941536770357,
        "median": 13.620187499327585,
        "min": 8.907917013857514,
        "p90": 21.336932998383418,
        "p95": 23.503029151470393,
        "p99": 32.29251036420463,
        "std": 5.103707285840383
      },
      "overall": {
        "context_tokens": 132.245,
        "count": 600,
        "f1@1": 0.715,
        "f1@10": 0.13363636363636364,
        "f1@3": 0.3675,
        "f1@5": 0.24500000000000005,
        "full_support": 0.735,
        "latency_ms": 15.180941536770357,
        "map": 0.725,
        "mrr": 0.725,
        "ndcg@1": 0.715,
        "ndcg@10": 0.7276185950714291,
        "ndcg@3": 0.7276185950714291,
        "ndcg@5": 0.7276185950714291,
        "precision@1": 0.715,
        "precision@10": 0.0735,
        "precision@3": 0.245,
        "precision@5": 0.147,
        "recall@1": 0.715,
        "recall@10": 0.735,
        "recall@3": 0.735,
        "recall@5": 0.735
      }
    },
    "treemem_manual": {
      "by_category": {
        "ambiguous": {
          "context_tokens": 21.384615384615383,
          "count": 26,
          "f1@1": 0.07692307692307693,
          "f1@10": 0.013986013986013986,
          "f1@3": 0.038461538461538464,
          "f1@5": 0.025641025641025644,
          "full_support": 0.07692307692307693,
          "latency_ms": 15.425267692010562,
          "map": 0.07692307692307693,
          "mrr": 0.07692307692307693,
          "ndcg@1": 0.07692307692307693,
          "ndcg@10": 0.07692307692307693,
          "ndcg@3": 0.07692307692307693,
          "ndcg@5": 0.07692307692307693,
          "precision@1": 0.07692307692307693,
          "precision@10": 0.007692307692307693,
          "precision@3": 0.02564102564102564,
          "precision@5": 0.015384615384615385,
          "recall@1": 0.07692307692307693,
          "recall@10": 0.07692307692307693,
          "recall@3": 0.07692307692307693,
          "recall@5": 0.07692307692307693
        },
        "direct": {
          "context_tokens": 13.761904761904763,
          "count": 126,
          "f1@1": 0.015873015873015872,
          "f1@10": 0.002886002886002886,
          "f1@3": 0.007936507936507936,
          "f1@5": 0.005291005291005292,
          "full_support": 0.015873015873015872,
          "latency_ms": 14.0908479700715,
          "map": 0.015873015873015872,
          "mrr": 0.015873015873015872,
          "ndcg@1": 0.015873015873015872,
          "ndcg@10": 0.015873015873015872,
          "ndcg@3": 0.015873015873015872,
          "ndcg@5": 0.015873015873015872,
          "precision@1": 0.015873015873015872,
          "precision@10": 0.0015873015873015873,
          "precision@3": 0.005291005291005291,
          "precision@5": 0.0031746031746031746,
          "recall@1": 0.015873015873015872,
          "recall@10": 0.015873015873015872,
          "recall@3": 0.015873015873015872,
          "recall@5": 0.015873015873015872
        },
        "long_context": {
          "context_tokens": 13.983870967741936,
          "count": 124,
          "f1@1": 0.016129032258064516,
          "f1@10": 0.002932551319648094,
          "f1@3": 0.008064516129032258,
          "f1@5": 0.005376344086021506,
          "full_support": 0.016129032258064516,
          "latency_ms": 13.917716064644347,
          "map": 0.016129032258064516,
          "mrr": 0.016129032258064516,
          "ndcg@1": 0.016129032258064516,
          "ndcg@10": 0.016129032258064516,
          "ndcg@3": 0.016129032258064516,
          "ndcg@5": 0.016129032258064516,
          "precision@1": 0.016129032258064516,
          "precision@10": 0.0016129032258064516,
          "precision@3": 0.005376344086021505,
          "precision@5": 0.0032258064516129032,
          "recall@1": 0.016129032258064516,
          "recall@10": 0.016129032258064516,
          "recall@3": 0.016
```
# Benchmark Tables

## Table A — Retrieval Quality
| System | P@5 | R@5 | F1@5 | MRR | MAP | NDCG@10 |
|---|---:|---:|---:|---:|---:|---:|
| treemem_guided | 0.147 | 0.735 | 0.245 | 0.725 | 0.725 | 0.728 |
| treemem_manual | 0.004 | 0.020 | 0.007 | 0.020 | 0.020 | 0.020 |

## Table B — Context Efficiency
| System | Mean Tokens | Median Tokens | P95 Tokens | Max Tokens |
|---|---:|---:|---:|---:|
| treemem_guided | 132.2 | 153.0 | 175.0 | 189.0 |
| treemem_manual | 14.4 | 0.0 | 38.0 | 84.0 |

## Table D — Latency
| System | Retrieval P50 | Retrieval P95 | Mean | P99 |
|---|---:|---:|---:|---:|
| treemem_guided | 13.62 | 23.50 | 15.18 | 32.29 |
| treemem_manual | 12.75 | 25.20 | 14.08 | 28.41 |

Manifest: `ablation/manifest.json`

## e2e
```json
{
  "arms": {
    "bm25": {
      "by_category": {
        "ambiguous": {
          "context_tokens": 147.0,
          "count": 14
        },
        "broad": {
          "context_tokens": 150.0,
          "count": 6
        },
        "direct": {
          "context_tokens": 156.578125,
          "count": 64
        },
        "hierarchical": {
          "context_tokens": 159.83333333333334,
          "count": 6
        },
        "long_context": {
          "context_tokens": 163.15625,
          "count": 64
        },
        "multi_entity": {
          "context_tokens": 156.33333333333334,
          "count": 3
        },
        "multi_hop": {
          "context_tokens": 164.33333333333334,
          "count": 3
        },
        "negative": {
          "context_tokens": 152.58333333333334,
          "count": 12
        },
        "private": {
          "context_tokens": 171.66666666666666,
          "count": 3
        },
        "semantic": {
          "context_tokens": 152.234375,
          "count": 64
        },
        "temporal": {
          "context_tokens": 158.33333333333334,
          "count": 3
        },
        "update": {
          "context_tokens": 160.66666666666666,
          "count": 3
        }
      },
      "context_tokens": {
        "count": 245,
        "max": 189.0,
        "mean": 156.68571428571428,
        "median": 158.0,
        "min": 121.0,
        "p90": 172.6,
        "p95": 177.0,
        "p99": 184.56,
        "std": 13.306722077920483
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
        "context_tokens": 156.68571428571428,
        "count": 245
      }
    },
    "treemem_guided": {
      "by_category": {
        "ambiguous": {
          "context_tokens": 131.57142857142858,
          "count": 14
        },
        "broad": {
          "context_tokens": 75.83333333333333,
          "count": 6
        },
        "direct": {
          "context_tokens": 128.078125,
          "count": 64
        },
        "hierarchical": {
          "context_tokens": 17.5,
          "count": 6
        },
        "long_context": {
          "context_tokens": 145.6875,
          "count": 64
        },
        "multi_entity": {
          "context_tokens": 156.33333333333334,
          "count": 3
        },
        "multi_hop": {
          "context_tokens": 81.33333333333333,
          "count": 3
        },
        "negative": {
          "context_tokens": 131.75,
          "count": 12
        },
        "private": {
          "context_tokens": 128.33333333333334,
          "count": 3
        },
        "semantic": {
          "context_tokens": 132.171875,
          "count": 64
        },
        "temporal": {
          "context_tokens": 81.33333333333333,
          "count": 3
        },
        "update": {
          "context_tokens": 158.66666666666666,
          "count": 3
        }
      },
      "context_tokens": {
        "count": 245,
        "max": 189.0,
        "mean": 129.71836734693878,
        "median": 151.0,
        "min": 0.0,
        "p90": 170.6,
        "p95": 175.0,
        "p99": 184.68,
        "std": 51.467782670921665
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
        "context_tokens": 129.71836734693878,
        "count": 245
      }
    },
    "treemem_search": {
      "by_category": {
        "ambiguous": {
          "context_tokens": 150.57142857142858,
          "count": 14
        },
        "broad": {
          "context_tokens": 75.83333333333333,
          "count": 6
        },
        "direct": {
          "context_tokens": 145.28125,
          "count": 64
        },
        "hierarchical": {
          "context_tokens": 159.83333333333334,
          "count": 6
        },
        "long_context": {
          "context_tokens": 165.09375,
          "count": 64
        },
        "multi_entity": {
          "context_tokens": 156.33333333333334,
          "count": 3
        },
        "multi_hop": {
          "context_tokens": 164.33333333333334,
          "count": 3
        },
        "negative": {
          "context_tokens": 140.25,
          "count": 12
        },
        "private": {
          "context_tokens": 128.33333333333334,
          "count": 3
        },
        "semantic": {
          "context_tokens": 149.875,
          "count": 64
        },
        "temporal": {
          "context_tokens": 158.66666666666666,
          "count": 3
        },
        "update": {
          "context_tokens": 158.66666666666666,
          "count": 3
        }
      },
      "context_tokens": {
        "count": 245,
        "max": 189.0,
        "mean": 150.85714285714286,
        "median": 155.0,
        "min": 0.0,
        "p90": 172.6,
        "p95": 177.59999999999997,
        "p99": 184.68,
        "std": 23.782656582021293
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
        "context_tokens": 150.85714285714286,
        "count": 245
      }
    }
  },
  "count": 735
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
| bm25 | 156.7 | 158.0 | 177.0 | 189.0 |
| treemem_guided | 129.7 | 151.0 | 175.0 | 189.0 |
| treemem_search | 150.9 | 155.0 | 177.6 | 189.0 |

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

## logs
**not run / no summary**

## reliability
```json
{
  "count": 5,
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
    },
    {
      "corruption": false,
      "data_loss": false,
      "duplicate_reconstruction": false,
      "recovered": true,
      "recovery_ms": 0.0,
      "scenario": "crash_recovery_3",
      "stray_tmp_detected": true
    },
    {
      "corruption": false,
      "data_loss": false,
      "duplicate_reconstruction": false,
      "recovered": true,
      "recovery_ms": 0.0,
      "scenario": "crash_recovery_4",
      "stray_tmp_detected": true
    }
  ]
}
```
# Benchmark Tables

Manifest: `reliability/manifest.json`

## scale_100
**not run / no summary**

## scale_1000
**not run / no summary**

## scale_10000
**not run / no summary**

## scale_50000
**not run / no summary**

## Reproduction
See `benchmark_suite/README.md` for exact commands. Raw episodes are under `benchmark_suite/results/`.