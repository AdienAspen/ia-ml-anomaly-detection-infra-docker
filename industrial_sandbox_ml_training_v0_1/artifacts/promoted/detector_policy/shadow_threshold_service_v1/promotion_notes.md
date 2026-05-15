# Detector Policy Promotion Notes

- 1B discovers and validates; 1A executes the validated detector policy.
- promoted runtime mode: `shadow`
- scoring policy: `score_samples`
- threshold mode: `service_specific`
- 1A must load this policy at startup and keep it cached in memory during inference.
- checkout-api threshold: `0.691832591180323`
- orders-api threshold: `0.6712653569641552`
- payments-api threshold: `0.7016270755997039`
- TPR anomalous: `0.719821`
- FPR normal: `0.048732`
- service span: `0.055333`
