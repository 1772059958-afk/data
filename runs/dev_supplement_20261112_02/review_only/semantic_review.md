# 正式100条提交的语义复核

覆盖20例、100条提交、49个实例内唯一补丁组（含空提交）。复核者为当前代码agent，不是外部真人签审。官方标签保持原样；静态合理性不替代独立测试。逐项理由、风险、原始提交哈希见 semantic_review.json 及 notes_batch1–4.json。参考答案在全部正式预测封存后才进入隔离复核目录，未用于生成。

| 实例 | 各组复核结论 |
| --- | --- |
| astropy__astropy-14995 | A/C/D/E: supports_requested_behavior; B: supports_requested_behavior_with_redundancy |
| django__django-11910 | A/D: no_submission; B/C/E: supports_requested_behavior |
| django__django-12708 | A/C/D/E: supports_requested_behavior; B: supports_requested_behavior_with_extra_change |
| django__django-13230 | A/C/D/E: supports_requested_behavior; B: supports_requested_behavior_with_extra_default |
| django__django-17087 | A/B/C/D/E: supports_requested_behavior |
| matplotlib__matplotlib-23987 | A/B: no_submission; C: partial_fix_with_boundary_regression; D: misdirected_fix; E: misdirected_fix |
| matplotlib__matplotlib-24970 | A/C/D/E: supports_requested_behavior; B: supports_requested_behavior_with_extra_copy |
| mwaskom__seaborn-2848 | A/D/E: no_submission; B: supports_requested_behavior; C: supports_requested_behavior_with_broader_null_handling |
| pallets__flask-4045 | A/B/C/D/E: partial_fix_confirmed_target_failure |
| psf__requests-1963 | A/C/D/E: plausibly_supports_requested_behavior_official_verdict_unknown; B: plausibly_supports_requested_behavior_official_verdict_unknown |
| pydata__xarray-3364 | A/E: no_submission; B: overbroad_fill_with_unverified_dtype_and_dimension_semantics; C: partial_fix_misses_merge_rejection; D: concrete_runtime_regression |
| pylint-dev__pylint-7114 | A/C/D/E: partial_workaround_with_broader_path_risk; B: no_submission |
| pytest-dev__pytest-6116 | A/C/D/E: supports_requested_behavior; B: concrete_option_destination_regression |
| pytest-dev__pytest-8906 | A/C/D/E: supports_requested_behavior; B: partial_fix_with_contradictory_guidance |
| scikit-learn__scikit-learn-11281 | A/C/D/E: plausible_wrapper_with_validation_gap; B: api_expansion_with_misplaced_label_state |
| scikit-learn__scikit-learn-13496 | A/C/D/E: supports_requested_behavior; B: no_submission |
| sphinx-doc__sphinx-8595 | A/B/C/D/E: supports_requested_behavior |
| sympy__sympy-13480 | A/C/D/E: supports_requested_behavior; B: no_submission |
| sympy__sympy-16503 | A: unjustified_global_baseline_shift; B: partial_offset_without_sign_geometry_fix; C/E: no_submission; D: replacement_baseline_loses_summand_geometry |
| sympy__sympy-23262 | A/C/D/E: wrong_layer_for_native_tuple_path; B: no_submission |
