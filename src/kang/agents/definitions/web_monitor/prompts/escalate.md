<!--
web_monitor's escalation prompt (classification task_class) — FIRST
DRAFT, not tuned (ADR-040 D4). No executor exists yet.
-->

Classify whether this fetched item belongs in Kang's digest for this
monitor's own configured purpose (news, GitHub trending, scholarships —
whichever this monitor instance is). Answer only: include or skip, plus
one line of reasoning. A stale or off-topic item skipped costs
nothing; one wrongly included clutters a digest Kang reads daily —
prefer skip when genuinely unsure.
