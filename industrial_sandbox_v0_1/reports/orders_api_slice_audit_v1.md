# Orders API Slice Audit v1

- source csv: `data/synthetic/telemetry_events_20260425T172122-0400.csv`
- decisions log: `reports/detector_decisions.jsonl`

## Summary
- payments-api|normal: count=895, candidate=4.02%, flag=0.56%, avg_score=0.589065, avg_margin=-0.112562
- orders-api|normal: count=956, candidate=7.11%, flag=1.67%, avg_score=0.568954, avg_margin=-0.102311
- checkout-api|normal: count=917, candidate=3.6%, flag=0.33%, avg_score=0.572464, avg_margin=-0.119369
- payments-api|anomalous: count=772, candidate=75.52%, flag=58.42%, avg_score=0.69636, avg_margin=-0.005267
- orders-api|anomalous: count=711, candidate=67.65%, flag=47.4%, avg_score=0.675111, avg_margin=0.003846
- checkout-api|anomalous: count=749, candidate=74.9%, flag=57.41%, avg_score=0.690517, avg_margin=-0.001316

## Orders Diagnostic Read
- orders anomalous false negatives: `374`
- orders normal false positives: `16`
- orders anomalous candidate misses: `230`
- orders anomalous top reasons: `[('service_threshold_breach', 481), ('persistent_window', 337), ('within_expected_range', 230), ('awaiting_window_confirmation', 144)]`
- orders normal top reasons: `[('within_expected_range', 886), ('service_threshold_breach', 68), ('awaiting_window_confirmation', 52), ('persistent_window', 16), ('stabilizing_window', 2)]`
