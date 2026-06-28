# Su Bing Strategy Source Map

This reference maps the Su Bing strategy documents that Codex may read when using the `su-bing-strategy` skill.

Private source files may exist locally or in the private repository. Do not copy private Notion exports, course text, long passages, screenshots, or image-only case content into Skill-facing documents.

## Public Documents

- `docs/strategy_knowledge/su_bing/SOURCE_INDEX.md`: source classification, extraction status, target documents, and quantization flags.
- `docs/strategy_knowledge/su_bing/NOTION_EXTRACTION_SUMMARY.md`: short paraphrased summaries and classification decisions.
- `docs/strategy_knowledge/su_bing/SU_BING_SKILL.md`: source-material boundary and allowed/disallowed work.
- `docs/strategy_knowledge/su_bing/SU_BING_RULEBOOK.md`: rulebook section structure for trend, EMA21, MACD, entry, and exit.
- `docs/strategy_knowledge/su_bing/SU_BING_REVIEW_TAGS.md`: placeholder structure for future review tags.
- `docs/strategy_knowledge/su_bing/SU_BING_QUANT_SPEC_V0_1.md`: history draft, legacy reference, and engineering reference only; not a default Strategy Spec.

## Loading Guidance

- Read `SOURCE_INDEX.md` first when deciding whether material is quantizable or needs manual review.
- Read `NOTION_EXTRACTION_SUMMARY.md` when summarizing source coverage or deciding which topics belong in Skill, Rulebook, or review tags.
- Read `SU_BING_RULEBOOK.md` when producing rule specifications.
- Read `SU_BING_REVIEW_TAGS.md` when producing review-note or trade-review labels.
- Read `SU_BING_SKILL.md` when checking source-use boundaries.
- Read old Quant Spec material only when a task explicitly needs historical or engineering context, and label it as `history_draft`, `legacy_reference`, or `engineering_reference`.
