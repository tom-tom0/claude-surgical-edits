# Edit-pattern validation study

48 scenarios simulating real edits a coding assistant makes, authored by six
independent Claude Opus 5 agents (one per category: refactor, config, docs,
format, webstack, adversarial), each labeling the outcome a USER would want
('deny' = wasteful retype worth blocking, 'allow' = blocking would be
harassment, 'either' = borderline). Run offline against the hook exactly as
Claude Code invokes it. Study date: 2026-09-02.

```
category     scenario                         size  want    got    time  verdict         
refactor     rename_constant_full_retype      78L   deny    deny   32ms  ok              
refactor     add_method_to_class              103L  deny    deny   31ms  ok              
refactor     small_file_signature_change      17L   allow   allow  33ms  ok              
refactor     class_to_functions_rewrite       58L   allow   allow  30ms  ok              
refactor     callbacks_to_async_await         79L   allow   allow  31ms  ok              
refactor     typed_dataclass_reformat         50L   allow   allow  38ms  ok              
refactor     extract_validation_helper        48L   either  deny   32ms  ok(borderline)  
refactor     delete_dead_function             141L  deny    deny   37ms  ok              
webstack     html_utm_attribute_tweak         190L  deny    deny   36ms  ok              
webstack     css_scattered_brand_colors       190L  deny    deny   35ms  ok              
webstack     jsx_small_avatar_prop            15L   allow   allow  31ms  ok              
webstack     sql_append_invoices_table        16L   allow   allow  29ms  ok              
webstack     express_patch_route_field        142L  deny    deny   34ms  ok              
webstack     css_token_system_rewrite         130L  allow   allow  32ms  ok              
webstack     jsx_class_to_hooks_rewrite       128L  allow   allow  29ms  ok              
webstack     express_partial_async_migration  92L   either  deny   28ms  ok(borderline)  
config       package_json_version_bump        81L   deny    deny   32ms  ok              
config       lockfile_single_dep_bump         363L  deny    deny   31ms  ok              
config       env_append_two_vars              55L   deny    deny   30ms  ok              
config       tiny_toml_target_version         15L   allow   allow  34ms  ok              
config       ci_yaml_matrix_rewrite           78L   allow   allow  35ms  ok              
config       k8s_yaml_logging_section         91L   deny    deny   32ms  ok              
config       eslintrc_strict_migration        75L   allow   allow  37ms  ok              
config       nested_json_add_key              28L   either  deny   38ms  ok(borderline)  
docs         readme_three_typos               130L  deny    deny   37ms  ok              
docs         changelog_prepend_entry          112L  deny    deny   39ms  ok              
docs         toc_regeneration_body_identical  130L  deny    deny   30ms  ok              
docs         short_contributing_reword        17L   allow   allow  31ms  ok              
docs         quickstart_v3_rewrite            60L   allow   allow  34ms  ok              
docs         faq_rewrap_and_regroup           41L   allow   allow  33ms  ok              
docs         docs_index_domain_migration      67L   either  deny   33ms  ok(borderline)  
docs         auth_add_device_flow_section     48L   either  deny   30ms  ok(borderline)  
format       tabs_to_spaces_reindent          119L  allow   allow  34ms  ok              
format       sort_dedupe_imports_only         115L  deny    deny   33ms  ok              
format       strip_trailing_whitespace        92L   deny    deny   31ms  ok              
format       insert_license_header            80L   deny    deny   30ms  ok              
format       prettier_partial_reformat        104L  either  deny   33ms  ok(borderline)  
format       black_full_reformat              59L   allow   allow  35ms  ok              
format       rewrap_comments_tiny_file        10L   allow   allow  30ms  ok              
format       css_expand_single_line_rules     54L   allow   allow  38ms  ok              
adversarial  duplicate_blocks_one_delay       119L  deny    deny   36ms  ok              
adversarial  emoji_table_one_row              49L   deny    deny   31ms  ok              
adversarial  minified_bundle_config_swap      7L    allow   allow  35ms  ok              
adversarial  crlf_mixed_normalized_retype     51L   deny    allow  32ms  MISMATCH(missed)
adversarial  codegen_schema_v2_regen          88L   allow   allow  30ms  ok              
adversarial  deploy_log_append_retype         61L   deny    deny   33ms  ok              
adversarial  runbook_table_emoji_reflow       25L   allow   allow  32ms  ok              
adversarial  generated_routes_tenant_scoping  101L  either  deny   31ms  ok(borderline)  

48 scenarios | agree: 40 | borderline-ok: 7 | MISMATCH: 1 | errors: 0
hook latency: median 32ms, p95 38ms, max 39ms
```

The single remaining mismatch is intended behavior: normalizing mixed
CRLF/LF endings while changing one value is allowed by design, because an
Edit cannot practically convert line endings (covered by an explicit test).

This study drove the substantive-line weighting rule: two false blocks
(a CSS token-system rewrite and an FAQ reflow, where the only surviving
lines were braces and blank separators) were fixed by excluding trivial
lines (<=3 chars stripped) from the retype count, and all 24 deny verdicts
were preserved. Regression tests: Group 9 of the test suite.
