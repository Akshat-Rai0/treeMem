# TreeMem Comprehensive Benchmark Report

## Executive Summary
This report is generated only from measured benchmark outputs. Sections without completed experiments are marked **not run** rather than estimated.

## scale_1000
```json
{
  "arms": {
    "bm25": {
      "count": 701,
      "errors": 0,
      "retrieval_recall": 0.8403946742748455
    },
    "dense": {
      "count": 701,
      "errors": 0,
      "retrieval_recall": 0.7599381835473134
    },
    "flat_all": {
      "count": 701,
      "errors": 0,
      "retrieval_recall": 0.9443651925820257
    },
    "hybrid": {
      "count": 701,
      "errors": 0,
      "retrieval_recall": 0.8377080361388493
    },
    "hybrid_rerank": {
      "count": 701,
      "errors": 0,
      "retrieval_recall": 0.7730147408464099
    },
    "treemem_guided": {
      "count": 701,
      "dist_guided_path_match": {
        "False": 688,
        "True": 1,
        "null": 12
      },
      "dist_guided_stopped_reason": {
        "leaf": 120,
        "search_fallback": 538,
        "stop": 43
      },
      "errors": 0,
      "guided_child_score": 0.17483309557774607,
      "guided_facts": 0.1840228245363766,
      "guided_parent_score": 0.012034236804564908,
      "guided_payload_tokens": 329.7960057061341,
      "guided_recall": 0.535282929148835,
      "guided_search_hits": 3.574893009985735,
      "guided_steps": 1.355206847360913,
      "retrieval_recall": 0.535282929148835,
      "teaser_coverage_root": 0.142325023209474
    },
    "treemem_guided_no_fallback": {
      "count": 701,
      "dist_guided_path_match": {
        "False": 688,
        "True": 1,
        "null": 12
      },
      "dist_guided_stopped_reason": {
        "leaf": 120,
        "search_fallback": 538,
        "stop": 43
      },
      "errors": 0,
      "guided_child_score": 0.17483309557774607,
      "guided_facts": 0.1840228245363766,
      "guided_parent_score": 0.012034236804564908,
      "guided_payload_tokens": 329.7960057061341,
      "guided_recall": 0.018901569186875893,
      "guided_search_hits": 0.0,
      "guided_steps": 1.355206847360913,
      "retrieval_recall": 0.018901569186875893,
      "teaser_coverage_root": 0.142325023209474
    },
    "treemem_manual": {
      "count": 701,
      "dist_manual_path_match": {
        "False": 685,
        "True": 4,
        "null": 12
      },
      "errors": 0,
      "manual_tool_calls": 2.8587731811697576,
      "retrieval_recall": 0.03649548264384213
    },
    "treemem_search": {
      "count": 701,
      "dist_search_arm_count": {
        "0": 6,
        "113": 5,
        "122": 5,
        "126": 1,
        "162": 1,
        "163": 10,
        "164": 1,
        "165": 2,
        "166": 4,
        "167": 28,
        "168": 87,
        "169": 1,
        "170": 1,
        "171": 3,
        "172": 1,
        "174": 2,
        "175": 3,
        "177": 1,
        "178": 1,
        "179": 3,
        "180": 2,
        "181": 7,
        "182": 2,
        "185": 3,
        "186": 23,
        "187": 81,
        "188": 8,
        "189": 8,
        "190": 11,
        "191": 13,
        "192": 38,
        "193": 36,
        "194": 35,
        "195": 32,
        "196": 29,
        "197": 22,
        "198": 16,
        "199": 39,
        "200": 86,
        "21": 3,
        "23": 5,
        "24": 5,
        "26": 3,
        "28": 8,
        "33": 6,
        "74": 4,
        "80": 7,
        "85": 3
      },
      "errors": 0,
      "retrieval_recall": 0.8242510699001426,
      "search_mapped_hits": 175.7803138373752,
      "search_raw_hits": 187.0756062767475,
      "search_recall": 0.8242510699001426,
      "search_visible_hits": 175.7803138373752
    }
  },
  "contamination": {
    "contaminated": false,
    "count_mismatches": 0,
    "fresh_counts": [
      10,
      9,
      10,
      10,
      10,
      10,
      10,
      10,
      10,
      9,
      10,
      10,
      9,
      10,
      10,
      10,
      10,
      10,
      10,
      10,
      10,
      9,
      10,
      10,
      10
    ],
    "fresh_zero_rate": 0.0,
    "sample_k": 25,
    "shared_counts": [
      10,
      9,
      10,
      10,
      10,
      10,
      10,
      10,
      10,
      9,
      10,
      10,
      9,
      10,
      10,
      10,
      10,
      10,
      10,
      10,
      10,
      9,
      10,
      10,
      10
    ],
    "shared_zero_rate": 0.0
  },
  "count": 6309,
  "experiment": "diagnose",
  "vault_audit": {
    "bm25_fitted": true,
    "entry_docs": 1040,
    "health_violations": 0,
    "leaf_nodes": 868,
    "node_count": 1272,
    "placement_coverage": 1.0,
    "placement_table_size": 1040,
    "private_nodes": 45,
    "total_leaf_facts": 1040
  }
}
```
# Benchmark Tables

## Table — Diagnose Stage Metrics
| Arm | n | errors | retrieval_recall | search_recall | guided_recall | search_raw_hits | search_visible_hits | search_mapped_hits | guided_steps | guided_parent_score | guided_child_score | guided_facts | guided_search_hits | guided_payload_tokens | manual_tool_calls | teaser_coverage_root |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| bm25 | 701 | 0 | 0.840 | - | - | - | - | - | - | - | - | - | - | - | - | - |
| dense | 701 | 0 | 0.760 | - | - | - | - | - | - | - | - | - | - | - | - | - |
| flat_all | 701 | 0 | 0.944 | - | - | - | - | - | - | - | - | - | - | - | - | - |
| hybrid | 701 | 0 | 0.838 | - | - | - | - | - | - | - | - | - | - | - | - | - |
| hybrid_rerank | 701 | 0 | 0.773 | - | - | - | - | - | - | - | - | - | - | - | - | - |
| treemem_guided | 701 | 0 | 0.535 | - | 0.535 | - | - | - | 1.355 | 0.012 | 0.175 | 0.184 | 3.575 | 329.796 | - | 0.142 |
| treemem_guided_no_fallback | 701 | 0 | 0.019 | - | 0.019 | - | - | - | 1.355 | 0.012 | 0.175 | 0.184 | 0.000 | 329.796 | - | 0.142 |
| treemem_manual | 701 | 0 | 0.036 | - | - | - | - | - | - | - | - | - | - | - | 2.859 | - |
| treemem_search | 701 | 0 | 0.824 | 0.824 | - | 187.076 | 175.780 | 175.780 | - | - | - | - | - | - | - | - |

## Table — guided_stopped_reason
| Arm | leaf | search_fallback | stop |
|---|---:|---:|---:|
| bm25 |  |
| dense |  |
| flat_all |  |
| hybrid |  |
| hybrid_rerank |  |
| treemem_guided | 120 | 538 | 43 |
| treemem_guided_no_fallback | 120 | 538 | 43 |
| treemem_manual |  |
| treemem_search |  |

## Table — guided_path_match
| Arm | False | True | null |
|---|---:|---:|---:|
| bm25 |  |
| dense |  |
| flat_all |  |
| hybrid |  |
| hybrid_rerank |  |
| treemem_guided | 688 | 1 | 12 |
| treemem_guided_no_fallback | 688 | 1 | 12 |
| treemem_manual |  |
| treemem_search |  |

## Table — manual_path_match
| Arm | False | True | null |
|---|---:|---:|---:|
| bm25 |  |
| dense |  |
| flat_all |  |
| hybrid |  |
| hybrid_rerank |  |
| treemem_guided |  |
| treemem_guided_no_fallback |  |
| treemem_manual | 685 | 4 | 12 |
| treemem_search |  |

## Table — Vault Audit
| Metric | Value |
|---|---:|
| bm25_fitted | True |
| entry_docs | 1040 |
| health_violations | 0 |
| leaf_nodes | 868 |
| node_count | 1272 |
| placement_coverage | 1.0 |
| placement_table_size | 1040 |
| private_nodes | 45 |
| total_leaf_facts | 1040 |

## Table — Arm Contamination Check
- sample_k: 25, count_mismatches: 0, contaminated: False
- shared_zero_rate: 0.0, fresh_zero_rate: 0.0

Manifest: `scale_1000/manifest.json`

## Reproduction
See `benchmark_suite/README.md` for exact commands. Raw episodes are under `benchmark_suite/results/`.